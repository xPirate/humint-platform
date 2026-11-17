"""Reader mode: a news page reduced to its headline and paragraphs.

Used for outside events (api/outside_events.py, worker/outside_events.py):
an article is fetched once, by the server, and kept, so the console shows
it in a side panel instead of a new browser tab, a field server can show it
offline later, and duplicates can be spotted by headline.

The same file is in api/ and worker/ (the two share no code);
tests/test_outside_reader.py checks they are identical.

Extraction, without a library: the page is walked with Python's own HTML
parser. Scripts, styles, navigation, headers, footers, asides and forms are
skipped. The paragraph-like blocks left (p, headings, list items, quotes)
are grouped by the container they sit in — <article>, <main>, or an element
marked as the article body — and the container holding the most text wins.
That is what reader views do, roughly; on a page with no such structure it
falls back to every substantial paragraph on the page.

Fetching: only public addresses, checked again at every redirect (these
links come from outside data, so a link — or a redirect — to 127.0.0.1 or a
cloud metadata address must not be followed), a size cap, text pages only.
"""
import html as htmllib
import ipaddress
import os
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

MAX_BYTES = 3 * 1024 * 1024
TIMEOUT = int(os.environ.get("READER_TIMEOUT_SECONDS", "20"))
USER_AGENT = os.environ.get(
    "READER_USER_AGENT",
    "Mozilla/5.0 (compatible; humint-platform reader; +https://github.com/xPirate/humint-platform)")
ALLOW_PRIVATE = os.environ.get("FEED_FETCH_ALLOW_PRIVATE", "false").lower() == "true"
MAX_REDIRECTS = 5

SKIP = {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form",
        "button", "select", "template", "iframe", "figure", "figcaption", "dialog", "menu"}
BLOCKS = {"p", "h1", "h2", "h3", "h4", "li", "blockquote", "pre"}
# Elements whose boundaries end a run of loose text (text sitting directly
# in a <div>, as many sites write paragraphs).
BREAKS = {"div", "section", "article", "main", "table", "tr", "td", "ul", "ol", "dl", "center", "body"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
BODY_HINT = re.compile(r"article[-_]?(body|content|text)|story[-_]?(body|content)|entry[-_]content|"
                       r"post[-_](body|content)|articlebody|main[-_]content|content[-_]body", re.I)
BOILERPLATE = re.compile(r"^(advertisement|sponsored|subscribe|sign up|newsletter|share (this|on)|follow us|"
                         r"read more|related|cookie|all rights reserved|copyright|©|click here|"
                         r"we use cookies|this site uses)", re.I)


class _Walk(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.title = ""
        self._in_title = False
        self.skip = 0                 # depth inside skipped elements
        self.stack = []               # open tags: (tag, container id or None)
        self.containers = {}          # id -> kind
        self._next_c = 1
        self.blocks = []              # (container, tag, text)
        self._buf = None              # (tag, container, [parts])
        self._loose = None            # (container, [parts]): text straight inside a div
        self._brs = 0

    def _container(self):
        """Every container the text sits in, outermost first."""
        return tuple(c for _, c in self.stack if c is not None)

    def _flush_loose(self):
        if self._loose:
            c, parts = self._loose
            text = re.sub(r"\s+", " ", "".join(parts)).strip()
            if text:
                self.blocks.append((c, "p", text))
        self._loose = None

    def _flush(self):
        self._flush_loose()
        if self._buf:
            tag, c, parts = self._buf
            text = re.sub(r"\s+", " ", "".join(parts)).strip()
            if text:
                self.blocks.append((c, tag, text))
        self._buf = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"].strip())
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in VOID:
            if tag == "br":
                if self._buf:
                    self._buf[2].append(" ")
                elif self._loose:
                    # Two <br>s in a row: a paragraph break in loose text.
                    self._brs += 1
                    if self._brs >= 2:
                        self._flush_loose()
                    else:
                        self._loose[1].append(" ")
            return
        self._brs = 0
        if self.skip or tag in SKIP:
            self._flush() if tag in SKIP else None
            self.stack.append((tag, None))
            self._reskip()
            return
        cid = None
        hint = " ".join(filter(None, (a.get("class"), a.get("id"), a.get("itemprop"))))
        if tag not in BLOCKS and (tag in ("article", "main") or (hint and BODY_HINT.search(hint))):
            cid = self._next_c
            self._next_c += 1
            self.containers[cid] = tag
        if tag in BREAKS:
            self._flush_loose()
        self.stack.append((tag, cid))
        if tag in BLOCKS:
            self._flush()
            self._buf = (tag, self._container(), [])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            return
        if tag in VOID:
            return
        # Close up to the matching tag (HTML in the wild is not always tidy).
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        else:
            return
        self._reskip()
        if tag in BLOCKS:
            self._flush()
        elif tag in BREAKS:
            self._flush_loose()

    def _reskip(self):
        """Inside a skipped element: from the first one still open."""
        for k, (t, _) in enumerate(self.stack):
            if t in SKIP:
                self.skip = len(self.stack) - k
                return
        self.skip = 0

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self.skip:
            return
        if self._buf is not None:
            self._buf[2].append(data)
        elif data.strip() or self._loose:
            self._brs = 0 if data.strip() else self._brs
            if self._loose is None:
                self._loose = (self._container(), [])
            self._loose[1].append(data)

    def close(self):
        super().close()
        self._flush()


def _clean_title(title: str, site: str) -> str:
    title = re.sub(r"\s+", " ", htmllib.unescape(title or "")).strip()
    # "Headline | Site", "Headline - Site": drop a trailing site name.
    for sep in (" | ", " - ", " — ", " – ", " :: "):
        if sep in title:
            head, _, tail = title.rpartition(sep)
            if head and (len(tail) <= 40 or (site and site.lower() in tail.lower())):
                title = head.strip()
                break
    return title


def extract(html: str, url: str = "") -> dict:
    """{title, site, published, paragraphs: [...], text, chars}."""
    w = _Walk()
    try:
        w.feed(html)
        w.close()
    except Exception:        # the parser is forgiving; anything it still chokes on, take what it got
        pass
    host = urlparse(url).hostname or ""
    site = w.meta.get("og:site_name") or re.sub(r"^www\.", "", host)
    raw_title = (w.meta.get("og:title") or w.meta.get("twitter:title") or w.title
                 or next((t for _, tag, t in w.blocks if tag == "h1"), ""))
    title = _clean_title(raw_title, site)
    published = (w.meta.get("article:published_time") or w.meta.get("og:article:published_time")
                 or w.meta.get("pubdate") or w.meta.get("date") or None)

    def keep(tag, text):
        if tag in ("h2", "h3", "h4"):
            return 3 <= len(text) <= 200 and not BOILERPLATE.search(text)
        if tag == "h1":
            return False                  # the headline is shown on its own
        if BOILERPLATE.search(text) and len(text) < 160:
            return False
        return len(text) >= (25 if tag in ("li", "blockquote") else 40)

    # Each container's text, counting everything inside it; then the one with
    # the most, narrowed to a child while that child holds nearly all of it.
    total, parent = {}, {}
    for chain, tag, text in w.blocks:
        for i, c in enumerate(chain):
            parent.setdefault(c, chain[i - 1] if i else None)
            if tag == "p":
                total[c] = total.get(c, 0) + len(text)
    best = max(total, key=total.get) if total else None
    while best is not None:
        kids = [k for k, p_ in parent.items() if p_ == best and total.get(k, 0) >= 0.8 * total[best]]
        if not kids:
            break
        best = max(kids, key=lambda k: total.get(k, 0))
    if best is not None and total.get(best, 0) >= 300:
        chosen = [(tag, t) for chain, tag, t in w.blocks if best in chain]
    else:
        chosen = [(tag, t) for chain, tag, t in w.blocks if tag != "li"]
    paras, seen = [], set()
    for tag, text in chosen:
        text = htmllib.unescape(text)
        if keep(tag, text) and text not in seen:
            seen.add(text)
            paras.append(("## " + text) if tag in ("h2", "h3", "h4") else text)
    body = "\n\n".join(paras)
    return {"title": title or None, "site": site or None, "published": published,
            "paragraphs": paras, "text": body, "chars": len(body)}


def _public(host: str) -> bool:
    if ALLOW_PRIVATE:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def fetch(url: str, session=None) -> tuple:
    """(article dict, None) or (None, why). Never raises."""
    s = session or requests
    for _ in range(MAX_REDIRECTS + 1):
        try:
            p = urlparse(url)
        except ValueError:
            return None, "That link could not be read."
        if p.scheme not in ("http", "https") or not p.hostname:
            return None, "Only web links (http, https) can be read."
        if not _public(p.hostname):
            return None, "That link points at a private or unreachable address, so it was not opened."
        try:
            r = s.get(url, timeout=TIMEOUT, stream=True, allow_redirects=False,
                      headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
        except requests.RequestException as exc:
            return None, f"The page could not be fetched ({type(exc).__name__})."
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            url = urljoin(url, r.headers["Location"])
            r.close()
            continue
        break
    else:
        return None, "The page redirected too many times."
    with r:
        if r.status_code >= 400:
            return None, f"The publisher answered {r.status_code}" + (
                " (it may block automated readers, or need a subscription)." if r.status_code in (401, 403, 451)
                else ".")
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype and not (ctype.startswith("text/html") or ctype == "application/xhtml+xml"):
            return None, f"That link is {ctype}, not a web page."
        chunks, total = [], 0
        try:
            for chunk in r.iter_content(64 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    return None, "That page is larger than the reader's limit."
                chunks.append(chunk)
        except requests.RequestException as exc:
            return None, f"The page could not be fetched ({type(exc).__name__})."
        enc = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else None
    raw = b"".join(chunks)
    if not enc:
        m = re.search(rb'<meta[^>]+charset=["\']?([A-Za-z0-9_-]+)', raw[:4096], re.I)
        enc = m.group(1).decode() if m else "utf-8"
    try:
        page = raw.decode(enc, errors="replace")
    except LookupError:
        page = raw.decode("utf-8", errors="replace")
    art = extract(page, url)
    art["url"] = url
    if art["chars"] < 120:
        return None, ("The page held almost no readable text — it is probably built by scripts, "
                      "or behind a paywall. Open the original.")
    return art, None
