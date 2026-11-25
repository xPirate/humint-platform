"""The assistant's web lookups (v1.19): web_search, read_page, save_web_page.

Offered only for a question the person has allowed the web on, when an admin
has turned web research on (web_research.py has the why and the controls).
The tool context carries the question's web state:

    ctx["web"] = {
        "settings":  web_research.settings(),
        "live":      True when searches may go out now (no approval needed,
                     or this is the run after the person approved them),
        "queued":    [{"kind": "search"|"page", "text"}] — waiting for approval,
        "allowed":   addresses the approved searches found (readable now),
        "searches", "pages": counts against the admin's limits,
        "read":      addresses read this question (save_web_page needs one),
    }

When approval is required, a search is QUEUED, not sent: the tool tells the
model so, the answer goes back with the queue, and the panel shows it for
the person to approve, change or skip (assistant.py continues the question
with what they approved).
"""
import assistant_drafts
import web_research
from db import db_cursor

NOT_ALLOWED = ("The web is not allowed for this question: only the case file. If something could only be "
               "answered from the web, say so — the analyst can ask again with the web allowed.")


def _ref(url, title):
    return {"kind": "web", "id": url, "label": f"Web: {title[:60] or url}"}


def web_search(ctx, query: str = "") -> tuple[str, list]:
    w = ctx.get("web")
    if not w:
        return NOT_ALLOWED, []
    q = " ".join((query or "").split())[:300]
    if not q:
        return "web_search needs a query.", []
    s = w["settings"]
    if w["searches"] + sum(1 for x in w["queued"] if x["kind"] == "search") >= s["max_searches"]:
        return (f"No more web searches for this question (the limit is {s['max_searches']}). "
                "Answer from what you have."), []
    if not w["live"]:
        if not any(x["kind"] == "search" and x["text"].lower() == q.lower() for x in w["queued"]):
            w["queued"].append({"kind": "search", "text": q})
        return (f"Queued for the analyst's approval: search \"{q}\". Web searches leave this machine, so "
                "the analyst approves each one first. Do not wait for it: answer from the case file now, "
                "and say plainly which web searches you would like to run and why."), []
    try:
        results = web_research.search(q, ctx["user"], s)
    except web_research.WebError as exc:
        w["searches"] += 1
        return f"The web search failed: {exc}", []
    w["searches"] += 1
    if not results:
        return f"The web search \"{q}\" found nothing.", []
    for r in results:
        w["allowed"].add(r["url"])
    lines = [f"Web search \"{q}\" — open-source, unverified; read a page with read_page:"]
    for r in results:
        lines.append(f"- {r['title']} — {r['url']}")
        if r["snippet"]:
            lines.append(f"  {r['snippet']}")
    return "\n".join(lines), [_ref(r["url"], r["title"]) for r in results]


def read_page(ctx, url: str = "") -> tuple[str, list]:
    w = ctx.get("web")
    if not w:
        return NOT_ALLOWED, []
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return "read_page needs a web address (http:// or https://), e.g. from web_search.", []
    s = w["settings"]
    if w["pages"] + sum(1 for x in w["queued"] if x["kind"] == "page") >= s["max_pages"]:
        return f"No more page reads for this question (the limit is {s['max_pages']}).", []
    if not w["live"] and url not in w["allowed"]:
        if not any(x["kind"] == "page" and x["text"] == url for x in w["queued"]):
            w["queued"].append({"kind": "page", "text": url})
        return (f"Queued for the analyst's approval: read {url}. Answer from the case file now and say "
                "why you would read it."), []
    art, err = web_research.read(url, ctx["user"], s)
    w["pages"] += 1
    if not art:
        return f"The page could not be read: {err}", []
    w["read"].add(url)
    w["read"].add(art["url"])
    body = art["text"][:ctx.get("body_chars", 2500)]
    head = f"Web page (open-source, unverified): {art['title'] or url}" + (f" — {art['site']}" if art.get("site") else "")
    meta = [f"Address: {art['url']}"]
    if art.get("published"):
        meta.append(f"Published: {art['published']}")
    return "\n".join([head, *meta, "", body + (" … [more]" if art["chars"] > len(body) else "")]), \
        [_ref(art["url"], art["title"] or url)]


def save_web_page(ctx, url: str = "", title: str = "", note: str = "") -> tuple[str, list]:
    w = ctx.get("web")
    if not w:
        return NOT_ALLOWED, []
    url = (url or "").strip()
    if url not in w["read"]:
        return "save_web_page takes a page you have read with read_page in this question.", []
    title = " ".join((title or "").split())[:300] or url
    did = assistant_drafts._add(ctx, "web_to_document", {"url": url, "title": title,
                                                          "note": (note or "").strip()[:500] or None},
                                f"Web page to Documents: {title}")
    if did is None:
        return assistant_drafts._full(ctx), []
    return (f"Prepared keeping '{title}' as a document (draft #{did}); the analyst decides."), [_ref(url, title)]


def apply_web_to_document(d: dict, user: dict) -> dict:
    """Read the page again (so the document is what is there now) and keep it."""
    import documents  # noqa: PLC0415
    from fastapi import HTTPException  # noqa: PLC0415
    from datetime import date  # noqa: PLC0415
    p = d["payload"] or {}
    art, err = web_research.read(p["url"], user, why="saved to Documents")
    if not art:
        raise HTTPException(status_code=502, detail=f"The page could not be read: {err}")
    note = f"Web page (open source, unverified), read {date.today().isoformat()}: {art['url']}"
    if p.get("note"):
        note += f" — {p['note']}"
    text = f"{art['title'] or p['title']}\n\n{art['text']}\n\nSource: {art['url']}"
    created = documents.paste_document(documents.PasteRequest(
        text=text[:documents.MAX_PASTE_CHARS], title=(p.get("title") or art["title"] or art["url"])[:300],
        source_note=note[:1000]), user)
    return {"document_id": created["id"], "title": created.get("title")}


def _fn(name, description, properties, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": list(required)}}}


TOOLS = [
    _fn("web_search",
        "Search the public web (allowed for this question). The query leaves this machine: use only what "
        "the question needs. Results are open-source and unverified.",
        {"query": {"type": "string"}}, ["query"]),
    _fn("read_page",
        "Read a web page found by web_search: its headline and text.",
        {"url": {"type": "string"}}, ["url"]),
    _fn("save_web_page",
        "Prepare keeping a page you read as a document in the case file, for the analyst to approve — when "
        "it adds something the file should keep.",
        {"url": {"type": "string"}, "title": {"type": "string"},
         "note": {"type": "string", "description": "Why it matters, in a line"}},
        ["url"]),
]
TOOL_FUNCS = {"web_search": web_search, "read_page": read_page, "save_web_page": save_web_page}

PROMPT = """
THE WEB IS ALLOWED for this question: web_search and read_page look on the public web,
save_web_page keeps a page as a document (a draft the analyst approves). Look in the case
file first; use the web for what the file does not have. Searches leave this machine, so
keep queries to what the question needs. Everything from the web is open-source and
unverified: say where each web fact came from (the site), and never present it as what the
case file shows."""
QUEUE_PROMPT = """
Web searches here are approved by the analyst first: a search you make is queued, not sent.
Make the searches you need, then answer from the case file and say what you would look up and why."""


def describe(name: str, args: dict) -> str:
    a = args or {}
    if name == "web_search":
        return f"Searched the web for “{a.get('query', '')}”"
    if name == "read_page":
        return f"Read {a.get('url', '')}"
    return f"Prepared keeping {a.get('url', '')} as a document"


def context(user: dict, live: bool, allowed=()) -> dict | None:
    s = web_research.settings()
    if not web_research.allowed_for(user, s):
        return None
    return {"settings": s, "live": live or not s["require_approval"], "queued": [], "allowed": set(allowed),
            "searches": 0, "pages": 0, "read": set()}


def run_approved(user: dict, items: list, s: dict, body_chars: int):
    """The searches and pages a person approved, as (step, tool message) pairs
    for the continuing question — yielding progress events as they run."""
    w = {"settings": s, "live": True, "queued": [], "allowed": set(), "searches": 0, "pages": 0, "read": set()}
    ctx = {"user": user, "web": w, "body_chars": body_chars, "drafts": []}
    out = []
    for it in items:
        name = "web_search" if it["kind"] == "search" else "read_page"
        args = {"query": it["text"]} if name == "web_search" else {"url": it["text"]}
        label = describe(name, args)
        yield {"type": "step", "label": label, "running": True}
        result, refs = TOOL_FUNCS[name](ctx, **args)
        n = sum(1 for line in result.splitlines() if line.startswith("- "))
        step = {"tool": name, "label": label,
                "summary": (f"{n} results" if name == "web_search" and n else result.splitlines()[0][:160])}
        yield {"type": "step", **step}
        out.append({"name": name, "args": args, "result": result, "refs": refs, "step": step})
    yield {"type": "_approved", "items": out, "allowed": w["allowed"], "read": w["read"],
           "searches": w["searches"], "pages": w["pages"]}


def mark(message_id: int, user_id: int, status: str, approved: list | None = None) -> None:
    """Record on the answer what became of its queued web lookups."""
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT steps FROM assistant_messages WHERE id = %s AND user_id = %s", (message_id, user_id))
        r = cur.fetchone()
        if not r or not r[0]:
            return
        trail = r[0]
        web = trail.get("web") or {}
        web["status"] = status
        if approved is not None:
            web["approved"] = approved
        trail["web"] = web
        import json  # noqa: PLC0415
        cur.execute("UPDATE assistant_messages SET steps = %s WHERE id = %s", (json.dumps(trail), message_id))
