"""Web research: the assistant may search the web and read pages.

The case file is the assistant's only source until an admin turns this on
(Admin → Model → Web research) AND the person asking ticks "May use the
web" on that question. Then it gets two more lookups — web_search and
read_page — and one more draft, save_web_page (a page kept as a document).

THE CONCERN IS WHAT LEAVES THE BOX, so:

- Every search is shown to the person before it is sent, by default
  (require_approval): the assistant's searches are queued, its answer says
  what it would look up, and nothing goes out until the person approves the
  queries — which they can edit or strike out. Approved, the searches run,
  and the assistant continues from the results; reading the pages those
  searches found is part of the approval. A new search is queued again.
- Every search and page read is in the audit log, with who asked and the
  exact query or address (web.search, web.read).
- An optional proxy carries all of it: a VPN's, or Tor (socks5h://…:9050),
  in which case names are resolved by the proxy, not this network's DNS.
- Page reads go out with an ordinary browser's User-Agent, not one naming
  this platform.
- What comes back is marked open-source and unverified, and never goes into
  a record by itself: a page becomes a document only when the person applies
  the draft, and links go through Review.

Search backends (one, chosen by the admin):

    searxng     a SearXNG instance (self-hosted; docker compose --profile
                websearch starts one) — no key, no account
    brave       Brave's Search API — needs a key
    duckduckgo  DuckDuckGo's plain-HTML page — nothing to install or sign up
                for, for light use; it may refuse automated queries
"""
import html as htmllib
import logging
import os
import re
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import audit
import auth
import reader
from db import db_cursor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/web-research", tags=["web research"])

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
BRAVE_URL = os.environ.get("WEB_BRAVE_URL", "https://api.search.brave.com/res/v1/web/search")
DDG_URL = os.environ.get("WEB_DDG_URL", "https://html.duckduckgo.com/html/")
MAX_RESULTS = 8
TIMEOUT = 25
COLS = ("enabled", "provider", "searxng_url", "brave_key", "proxy_url", "require_approval",
        "max_searches", "max_pages", "allowed", "updated_at")


class WebError(Exception):
    """A search that could not be made, in words for the person and the model."""


def settings() -> dict:
    with db_cursor() as cur:
        try:
            cur.execute(f"SELECT {', '.join(COLS)} FROM web_research_settings WHERE id = 1")
            r = cur.fetchone()
        except Exception:  # noqa: BLE001 - before the v1.19 migration
            cur.connection.rollback()
            r = None
    if not r:
        return {"enabled": False, "provider": "searxng", "searxng_url": None, "brave_key": None, "proxy_url": None,
                "require_approval": True, "max_searches": 4, "max_pages": 4, "allowed": "analysts",
                "updated_at": None}
    return dict(zip(COLS, r))


def allowed_for(user: dict, s: dict | None = None) -> bool:
    s = s or settings()
    if not s["enabled"]:
        return False
    role = user.get("role")
    return role == "admin" or (s["allowed"] == "analysts" and role == "analyst")


def _session(s: dict) -> requests.Session:
    sess = requests.Session()
    sess.trust_env = False                 # only the proxy set here, never one from the environment
    if s.get("proxy_url"):
        sess.proxies = {"http": s["proxy_url"], "https": s["proxy_url"]}
    return sess


def _strip(text: str) -> str:
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())


def _searxng(sess, s, query):
    base = (s.get("searxng_url") or "").rstrip("/")
    if not base:
        raise WebError("No SearXNG address is set (Admin → Model → Web research).")
    r = sess.get(f"{base}/search", params={"q": query, "format": "json", "safesearch": 0}, timeout=TIMEOUT,
                 headers={"User-Agent": BROWSER_UA, "Accept": "application/json"})
    if r.status_code == 403:
        raise WebError("SearXNG refused a JSON answer: turn on the json format under search.formats in its settings.yml.")
    r.raise_for_status()
    return [{"title": _strip(x.get("title")), "url": x.get("url"), "snippet": _strip(x.get("content"))}
            for x in (r.json().get("results") or [])]


def _brave(sess, s, query):
    if not s.get("brave_key"):
        raise WebError("No Brave Search API key is set (Admin → Model → Web research).")
    r = sess.get(BRAVE_URL, params={"q": query, "count": MAX_RESULTS}, timeout=TIMEOUT,
                 headers={"X-Subscription-Token": s["brave_key"], "Accept": "application/json"})
    if r.status_code in (401, 403):
        raise WebError("Brave refused the API key.")
    if r.status_code == 429:
        raise WebError("Brave's limit for this key was reached.")
    r.raise_for_status()
    return [{"title": _strip(x.get("title")), "url": x.get("url"), "snippet": _strip(x.get("description"))}
            for x in ((r.json().get("web") or {}).get("results") or [])]


_DDG_LINK = re.compile(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_DDG_SNIP = re.compile(r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.S)


def _ddg(sess, s, query):
    r = sess.post(DDG_URL, data={"q": query}, timeout=TIMEOUT,
                  headers={"User-Agent": BROWSER_UA, "Accept": "text/html"})
    if r.status_code in (202, 403, 429):
        raise WebError("DuckDuckGo is refusing automated searches from this address for now. "
                       "Try again later, or use SearXNG or Brave.")
    r.raise_for_status()
    page = r.text
    links, snips = _DDG_LINK.findall(page), _DDG_SNIP.findall(page)
    out = []
    for i, (href, title) in enumerate(links):
        href = htmllib.unescape(href)
        if "duckduckgo.com/l/" in href:                  # its redirect: the real address is in uddg
            href = unquote((parse_qs(urlparse(href).query).get("uddg") or [""])[0])
        if href.startswith("//"):
            href = "https:" + href
        if "duckduckgo.com/y.js" in href:               # an advert
            continue
        out.append({"title": _strip(title), "url": href, "snippet": _strip(snips[i]) if i < len(snips) else ""})
    return out


PROVIDERS = {"searxng": _searxng, "brave": _brave, "duckduckgo": _ddg}


def search(query: str, user: dict, s: dict | None = None, why: str = "assistant") -> list:
    """The results ([{title, url, snippet}]), audited. Raises WebError."""
    s = s or settings()
    query = " ".join((query or "").split())[:300]
    if not query:
        raise WebError("An empty search.")
    if not s["enabled"]:
        raise WebError("Web research is turned off.")
    try:
        results = PROVIDERS[s["provider"]](_session(s), s, query)
    except WebError as exc:
        error = str(exc)
        results = None
    except requests.RequestException as exc:
        error = (f"The search could not be made ({type(exc).__name__})"
                 + (" — check the proxy" if s.get("proxy_url") else " — is this machine online?"))
        results = None
    except (ValueError, KeyError) as exc:
        error = f"The search answer could not be read ({type(exc).__name__})."
        results = None
    clean = []
    for x in results or []:
        u = x.get("url") or ""
        if u.startswith(("http://", "https://")) and u not in [c["url"] for c in clean]:
            clean.append({"title": x["title"][:200] or u, "url": u[:1000], "snippet": (x["snippet"] or "")[:400]})
        if len(clean) >= MAX_RESULTS:
            break
    audit.record("web.search", user=user, object_type="web", object_label=query[:200],
                 detail={"query": query, "provider": s["provider"], "via_proxy": bool(s.get("proxy_url")),
                         "results": len(clean), "error": None if results is not None else error, "for": why})
    if results is None:
        raise WebError(error)
    return clean


def read(url: str, user: dict, s: dict | None = None, why: str = "assistant") -> tuple:
    """(article, None) or (None, why), audited."""
    s = s or settings()
    if not s["enabled"]:
        return None, "Web research is turned off."
    art, err = reader.fetch(url, session=_session(s), user_agent=BROWSER_UA, resolve=not s.get("proxy_url"))
    audit.record("web.read", user=user, object_type="web", object_label=url[:200],
                 detail={"url": url, "via_proxy": bool(s.get("proxy_url")), "chars": art["chars"] if art else 0,
                         "error": err, "for": why})
    return art, err


# ---- admin ---------------------------------------------------------------------------------

def _public_settings(s: dict) -> dict:
    out = {k: v for k, v in s.items() if k != "brave_key"}
    out["has_brave_key"] = bool(s.get("brave_key"))
    out["updated_at"] = s["updated_at"].isoformat() if s.get("updated_at") else None
    return out


@router.get("")
def get_settings(user: dict = Depends(auth.require_admin)):
    return _public_settings(settings())


class WebSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    provider: Optional[str] = None
    searxng_url: Optional[str] = Field(default=None, max_length=500)
    brave_key: Optional[str] = Field(default=None, max_length=200)   # "" clears it
    proxy_url: Optional[str] = Field(default=None, max_length=500)   # "" clears it
    require_approval: Optional[bool] = None
    max_searches: Optional[int] = Field(default=None, ge=1, le=20)
    max_pages: Optional[int] = Field(default=None, ge=0, le=20)
    allowed: Optional[str] = None


@router.put("")
def update_settings(payload: WebSettingsUpdate, user: dict = Depends(auth.require_admin)):
    fields = payload.model_dump(exclude_unset=True)
    if "provider" in fields and fields["provider"] not in PROVIDERS:
        raise HTTPException(status_code=400, detail="Unknown search backend.")
    if "allowed" in fields and fields["allowed"] not in ("admins", "analysts"):
        raise HTTPException(status_code=400, detail="Unknown setting for who may use it.")
    for k in ("searxng_url", "proxy_url", "brave_key"):
        if k in fields:
            fields[k] = (fields[k] or "").strip() or None
    if fields.get("searxng_url") and not re.match(r"^https?://[^\s/]+", fields["searxng_url"]):
        raise HTTPException(status_code=400, detail="The SearXNG address is a web address (http:// or https://).")
    if fields.get("proxy_url") and not re.match(r"^(https?|socks5h?)://[^\s/]+", fields["proxy_url"]):
        raise HTTPException(status_code=400, detail="The proxy is http://, https://, socks5:// or socks5h:// "
                                                    "followed by host:port.")
    if fields:
        sets = ", ".join(f"{k} = %s" for k in fields)
        with db_cursor(commit=True) as cur:
            cur.execute(f"UPDATE web_research_settings SET {sets}, updated_at = now(), updated_by = %s WHERE id = 1",
                        [*fields.values(), user["id"]])
        shown = {k: ("(set)" if k == "brave_key" and v else v) for k, v in fields.items()}
        audit.record("web.settings", user=user, object_type="settings", object_label="Web research", detail=shown)
    return _public_settings(settings())


class TestRequest(BaseModel):
    query: str = Field(default="OpenStreetMap", min_length=1, max_length=200)


@router.post("/test")
def test_search(payload: TestRequest, user: dict = Depends(auth.require_admin)):
    """One search with the settings as saved — something harmless by default."""
    s = settings()
    if not s["enabled"]:
        raise HTTPException(status_code=409, detail="Turn web research on first.")
    try:
        results = search(payload.query, user, s, why="admin test")
    except WebError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"results": results[:5], "provider": s["provider"]}
