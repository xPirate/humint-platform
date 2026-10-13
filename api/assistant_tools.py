"""The assistant's lookups: read-only views of the case file a model can ask for.

Each tool is a plain function over the same queries the console's own pages
run, returning compact TEXT rather than JSON. Text because the reader is a
small local model with a limited window: a line like

    Person · Daniel Kowal [person-daniel-kowal-1a2b3c] — Senior design engineer

costs a fraction of the tokens of the equivalent JSON object and is easier
for an 8B model to quote back correctly. Every record is printed with its id
in square brackets so the model can pass it straight to the next lookup.

Rules every tool here follows:

- READ-ONLY. Nothing in this module writes to the case file. The assistant is
  a research aid; proposing changes is what the Review queue is for.
- Never raises to the caller. A lookup that fails returns a sentence saying
  so, which the model can read and work around (try another name, give up
  and say so) instead of the whole answer failing.
- Accepts a name where it asks for an id. Small models often pass "Daniel
  Kowal" instead of the id they were shown; resolving that here costs one
  query and saves a wasted step.
- Returns (text, refs). `refs` is every record the text mentions, as
  {"kind", "id", "label"} — the pool the answer's source chips are chosen
  from (see assistant_agent.py).
"""

import json
import re
from collections import deque
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException

import boards as boards_module
import entities as entities_module
import graph as graph_module
import insights as insights_module
import reports as reports_module
from db import db_cursor

TYPE_LABELS = {
    "person": "Person", "organization": "Organization", "location": "Location",
    "event": "Event", "source": "Source", "communication": "Communication",
    "vehicle": "Vehicle", "record": "Record", "zone": "Zone", "route": "Route",
}
ENTITY_TYPES = tuple(TYPE_LABELS)
CREDIBILITY = entities_module.CONFIDENCE_LABELS   # 1-6, same scale for reports and links

# Detail columns worth searching and showing. Geometry, bounding boxes and the
# geocoder's bookkeeping are left out of both: a route's coordinates matching
# "41" is noise, and nobody asks the assistant about geocode_status.
_SKIP_DETAIL = {"geometry", "min_lat", "min_lon", "max_lat", "max_lon", "geocode_status",
                "geocode_error", "geocoded_at", "source_attachment_id", "id", "event_id"}

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for", "is", "are", "was",
    "were", "be", "been", "do", "does", "did", "what", "who", "where", "when", "why", "how",
    "which", "this", "that", "with", "about", "any", "all", "there", "have", "has", "had",
    "we", "our", "you", "me", "my", "it", "its", "from", "by", "as", "into", "than", "then",
}


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------

def _d(value) -> str:
    """A date as YYYY-MM-DD, whatever shape it arrived in."""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _clip(text: str | None, n: int) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _plain(markdown: str | None) -> str:
    """Report markdown as plain text: mentions become 'Name [id]', the rest of
    the markup is dropped. The ids stay because they are what the model needs
    to open the person a report names."""
    text = markdown or ""
    text = re.sub(r"\[([^\]]+)\]\(#/entities/([A-Za-z0-9_-]+)\)", r"\1 [\2]", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`#>]+", "", text)
    return text


def _ent(entity_id: str, entity_type: str, name: str) -> str:
    return f"{TYPE_LABELS.get(entity_type, entity_type.title())} · {name} [{entity_id}]"


def _ref(kind: str, rid: str, label: str) -> dict:
    return {"kind": kind, "id": rid, "label": label}


def _ent_ref(entity_id: str, entity_type: str, name: str) -> dict:
    return _ref("entity", entity_id, f"{TYPE_LABELS.get(entity_type, entity_type)}: {name}")


def _terms(query: str) -> list[str]:
    words = re.findall(r"[\w][\w'\-./@+]*", (query or "").lower())
    out = []
    for w in words:
        w = w.strip("'.-")
        if len(w) < 2 or w in STOPWORDS or w in out:
            continue
        out.append(w)
    return out[:8]


def _hit(term: str, text: str) -> bool:
    """Does `term` appear in `text` as a word? Short terms must be whole words
    (otherwise "van" finds Vance and Vane); longer ones may start a word, so
    "kowal" still finds "Kowal's"."""
    pattern = rf"(?<![\w]){re.escape(term)}" + (r"(?![\w])" if len(term) <= 3 else "")
    return re.search(pattern, text) is not None


def _author_names(cur, user_ids) -> dict:
    ids = [u for u in set(user_ids) if u]
    if not ids:
        return {}
    cur.execute("SELECT u.id, COALESCE(NULLIF(p.display_name, ''), u.username) "
                "  FROM users u LEFT JOIN user_profiles p ON p.user_id = u.id "
                " WHERE u.id = ANY(%s)", (ids,))
    return dict(cur.fetchall())


def _days(value, default=None, cap=3650):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(cap, n))


def resolve_entity(cur, ref: str) -> tuple[str | None, list]:
    """An id, or a name the model passed instead of one.

    Returns (id, []) when it is unambiguous, (None, candidates) when several
    records fit, (None, []) when nothing does."""
    ref = (ref or "").strip().strip("[]").strip()
    if not ref:
        return None, []
    cur.execute("SELECT id, merged_into FROM entities WHERE id = %s", (ref,))
    row = cur.fetchone()
    if row:
        return (row[1] or row[0]), []
    cur.execute(
        "SELECT e.id, e.entity_type, e.name FROM entities e "
        "  LEFT JOIN person_details pd ON pd.entity_id = e.id "
        " WHERE e.is_active AND e.merged_into IS NULL "
        "   AND (lower(e.name) = lower(%s) OR lower(%s) = ANY(SELECT lower(a) FROM unnest(pd.aliases) a)) "
        " LIMIT 6", (ref, ref))
    exact = cur.fetchall()
    if len(exact) == 1:
        return exact[0][0], []
    if exact:
        return None, exact
    cur.execute("SELECT id, entity_type, name FROM entities "
                " WHERE is_active AND merged_into IS NULL AND name ILIKE %s "
                " ORDER BY length(name) LIMIT 6", (f"%{ref}%",))
    loose = cur.fetchall()
    if len(loose) == 1:
        return loose[0][0], []
    return None, loose


def _not_found(ref: str, candidates: list) -> tuple[str, list]:
    if candidates:
        lines = [f"More than one record could be '{ref}'. Pick one by id:"]
        lines += [f"- {_ent(i, t, n)}" for i, t, n in candidates]
        return "\n".join(lines), [_ent_ref(i, t, n) for i, t, n in candidates]
    return (f"No record matches '{ref}'. Try search_case with other words, a surname, "
            f"or part of the name."), []


# ---------------------------------------------------------------------------
# search_case
# ---------------------------------------------------------------------------

def _detail_search_sql() -> str:
    """One UNION over every detail table's searchable text columns, so a
    plate, a phone number, an alias or an address finds its record the same
    way a name does."""
    parts = []
    for entity_type, (table, cols) in entities_module.DETAIL_TABLES.items():
        searchable = [c for c in cols if c not in _SKIP_DETAIL and c not in ("lat", "lng")]
        if not searchable:
            continue
        concat = ", ".join(f"COALESCE({c}::text, '')" for c in searchable)
        parts.append(f"SELECT entity_id, concat_ws(' ', {concat}) AS t FROM {table}")
    parts.append("SELECT entity_id, string_agg(concat_ws(' ', kind, label, value, notes), ' ') "
                 "FROM contact_points GROUP BY entity_id")
    return " UNION ALL ".join(parts)


def search_case(ctx, query: str = "", record_type: str | None = None) -> tuple[str, list]:
    terms = _terms(query)
    if not terms:
        return "Give search_case one or more words to look for.", []
    rtype = (record_type or "").strip().lower() or None
    if rtype and rtype.endswith("s") and rtype[:-1] in ENTITY_TYPES:
        rtype = rtype[:-1]
    if rtype in ("report", "reports"):
        rtype = "report"
    elif rtype and rtype not in ENTITY_TYPES:
        rtype = None

    patterns = [f"%{t}%" for t in terms]
    phrase = " ".join(terms)
    refs, lines = [], []
    with db_cursor() as cur:
        entity_rows = []
        if rtype != "report":
            cur.execute(
                f"""
                WITH extra AS ({_detail_search_sql()})
                SELECT e.id, e.entity_type, e.name, e.description,
                       lower(e.name) AS n, lower(COALESCE(e.description, '')) AS d,
                       lower(COALESCE(string_agg(x.t, ' '), '')) AS x,
                       (SELECT count(*) FROM relationships r
                         WHERE r.from_entity_id = e.id OR r.to_entity_id = e.id) AS degree
                  FROM entities e LEFT JOIN extra x ON x.entity_id = e.id
                 WHERE e.is_active AND e.merged_into IS NULL
                   {"AND e.entity_type = %s" if rtype else ""}
                 GROUP BY e.id
                HAVING lower(e.name) ILIKE ANY(%s) OR lower(COALESCE(e.description,'')) ILIKE ANY(%s)
                    OR lower(COALESCE(string_agg(x.t, ' '), '')) ILIKE ANY(%s)
                """,
                ([rtype] if rtype else []) + [patterns, patterns, patterns])
            scored = []
            for eid, etype, name, desc, n, d, x, degree in cur.fetchall():
                score, matched = 0, 0
                for t in terms:
                    if _hit(t, n):
                        score, matched = score + 4, matched + 1
                    elif _hit(t, x):
                        score, matched = score + 2, matched + 1
                    elif _hit(t, d):
                        score, matched = score + 1, matched + 1
                if not matched:
                    continue          # only a fragment inside some other word
                if phrase in n:
                    score += 6
                if matched == len(terms):
                    score += 5
                scored.append((score, eid, etype, name, desc, degree, matched))
            # Records that match every word, when there are any; otherwise the
            # best partial matches.
            if any(s_[6] == len(terms) for s_ in scored):
                scored = [s_ for s_ in scored if s_[6] == len(terms)]
            # Equal matches: the better-connected record first. In a case file
            # the hub is usually the one being asked about — "Kowal" means the
            # man, not his work email.
            scored.sort(key=lambda s: (-s[0], -s[5], s[3]))
            scored = [s[:5] for s in scored]
            entity_rows = scored[:10]

        report_rows = []
        if rtype in (None, "report"):
            cur.execute(
                "SELECT id, title, status, created_at, lower(title), lower(body_markdown) "
                "  FROM reports WHERE title ILIKE ANY(%s) OR body_markdown ILIKE ANY(%s)",
                (patterns, patterns))
            scored = []
            for rid, title, status, created, t, b in cur.fetchall():
                hits = [x for x in terms if _hit(x, t) or _hit(x, b)]
                if not hits:
                    continue
                score = sum(4 for x in terms if _hit(x, t)) + len(hits) \
                    + (5 if len(hits) == len(terms) else 0)
                scored.append((score, rid, title, status, created, len(hits)))
            if any(r_[5] == len(terms) for r_ in scored):
                scored = [r_ for r_ in scored if r_[5] == len(terms)]
            scored = [r_[:5] for r_ in scored]
            scored.sort(key=lambda s: (-s[0], -(s[4].timestamp() if s[4] else 0)))
            report_rows = scored[:6]

        # Field reports are not case records until someone accepts them, but
        # they are often the only place a plate or a place has been written
        # down yet — leaving them out made "KX7" find nothing.
        field_rows = []
        if rtype in (None, "report"):
            try:
                cur.execute(
                    "SELECT id, title, COALESCE(observed_at, received_at), status, "
                    "       lower(title || ' ' || COALESCE(body,'') || ' ' || fields::text || ' ' "
                    "             || COALESCE(location_note,'') || ' ' || COALESCE(relay_note,'')) "
                    "  FROM field_submissions "
                    " WHERE (title || ' ' || COALESCE(body,'') || ' ' || fields::text || ' ' "
                    "        || COALESCE(location_note,'') || ' ' || COALESCE(relay_note,'')) ILIKE ANY(%s) "
                    " ORDER BY 3 DESC LIMIT 40", (patterns,))
                scored = []
                for sid, title, when, status, text in cur.fetchall():
                    hits = sum(1 for t in terms if _hit(t, text))
                    if hits:
                        scored.append((hits + (5 if hits == len(terms) else 0), sid, title, when, status))
                scored.sort(key=lambda s: -s[0])
                field_rows = scored[:4]
            except Exception:  # noqa: BLE001 - a console without the field queue
                field_rows = []

    if entity_rows:
        lines.append(f"Records ({len(entity_rows)}):")
        for _, eid, etype, name, desc in entity_rows:
            tail = f" — {_clip(desc, 110)}" if desc else ""
            lines.append(f"- {_ent(eid, etype, name)}{tail}")
            refs.append(_ent_ref(eid, etype, name))
    if report_rows:
        lines.append(f"Reports ({len(report_rows)}):")
        for _, rid, title, status, created in report_rows:
            lines.append(f"- {_d(created)} · {title} [{rid}] ({status})")
            refs.append(_ref("report", rid, f"Report: {title}"))

    if field_rows:
        lines.append(f"Field reports ({len(field_rows)}) — use field_reports with text to read them:")
        for _, sid, title, when, status in field_rows:
            lines.append(f"- {_d(when)} · {title} (field report #{sid}, "
                         f"{'waiting for review' if status == 'new' else status})")

    # Nothing by wording: try meaning, when an embedding model is set up.
    if not entity_rows and not report_rows and not field_rows and ctx.get("semantic"):
        hits = ctx["semantic"](query)
        if hits:
            lines.append("Nothing matched those words. Closest by meaning:")
            for kind, rid, label in hits:
                lines.append(f"- {label} [{rid}]")
                refs.append(_ref(kind, rid, label))
    if not lines:
        return (f"Nothing in the case file matches '{query}'. Try fewer or different words, "
                f"a surname, or part of a plate or number."), []
    return "\n".join(lines), refs


# ---------------------------------------------------------------------------
# open_record
# ---------------------------------------------------------------------------

def _open_report(cur, report_id: str, body_chars: int) -> tuple[str, list]:
    try:
        rep = reports_module._report_dict(cur, report_id)
    except HTTPException:
        return f"No report with id {report_id}.", []
    authors = _author_names(cur, [rep["author_id"]])
    cred = rep.get("credibility_rating")
    lines = [
        f"Report: {rep['title']} [{rep['id']}]",
        f"Written {_d(rep['created_at'])} by {authors.get(rep['author_id'], 'unknown')} · "
        f"status {rep['status']} · credibility "
        f"{(cred + ' (' + CREDIBILITY.get(cred, '') + ')') if cred else 'not rated'}"
        f"{' · precedence ' + rep['criticality'] if rep.get('criticality') else ''}",
    ]
    refs = [_ref("report", rep["id"], f"Report: {rep['title']}")]
    body = _plain(rep.get("body_markdown")).strip()
    if body:
        lines.append("Text:")
        lines.append(body if len(body) <= body_chars else body[:body_chars].rstrip() + " … [cut]")
    if rep.get("entities"):
        lines.append("Records linked to this report:")
        for e in rep["entities"][:25]:
            lines.append(f"- {_ent(e['id'], e['entity_type'], e['name'])}")
            refs.append(_ent_ref(e["id"], e["entity_type"], e["name"]))
    if rep.get("attachments"):
        lines.append("Attachments: " + ", ".join(a["filename"] for a in rep["attachments"][:8]))
    return "\n".join(lines), refs


def _open_entity(ctx, cur, entity_id: str) -> tuple[str, list]:
    try:
        ent = entities_module.get_entity(entity_id, user=ctx["user"])
    except HTTPException:
        return f"No record with id {entity_id}.", []
    refs = [_ent_ref(ent["id"], ent["entity_type"], ent["name"])]
    lines = [_ent(ent["id"], ent["entity_type"], ent["name"])]
    if not ent.get("is_active"):
        lines.append("(archived)")
    if ent.get("description"):
        lines.append(f"Description: {_clip(ent['description'], 700)}")
    for key, value in (ent.get("details") or {}).items():
        if key in _SKIP_DETAIL or value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        elif isinstance(value, (datetime, date)):
            value = _d(value)
        lines.append(f"{key.replace('_', ' ').capitalize()}: {_clip(str(value), 300)}")
    if ent.get("is_expired"):
        lines.append("Note: this event is past its relevant-until date.")
    for c in (ent.get("contacts") or [])[:10]:
        label = f" ({c['label']})" if c.get("label") else ""
        lines.append(f"Contact: {c['kind']}{label} {c['value']}"
                     f"{' — preferred' if c.get('is_preferred') else ''}")

    rels = ent.get("relationships") or []
    live = [r for r in rels if not r.get("expired")]
    expired = [r for r in rels if r.get("expired")]
    if live:
        lines.append(f"Links ({len(live)}):")
        for r in live[:40]:
            grade = f"{r['confidence']} {CREDIBILITY.get(r['confidence'], '')}".strip()
            seen = f", learned {_d(r['discovery_date'])}" if r.get("discovery_date") else ""
            note = f" — {_clip(r['notes'], 120)}" if r.get("notes") else ""
            lines.append(f"- {r['reads_as'].replace('_', ' ')} → "
                         f"{_ent(r['other_entity_id'], r['other_entity_type'], r['other_entity_name'])}"
                         f" (graded {grade}{seen}){note}")
            refs.append(_ent_ref(r["other_entity_id"], r["other_entity_type"], r["other_entity_name"]))
        if len(live) > 40:
            lines.append(f"  …and {len(live) - 40} more; use network to see them by type.")
    if expired:
        lines.append(f"Expired links (history, no longer current): {len(expired)} — "
                     + "; ".join(f"{r['reads_as'].replace('_', ' ')} {r['other_entity_name']} "
                                 f"until {_d(r['expires_on'])}" for r in expired[:8]))
    reps = ent.get("reports") or []
    if reps:
        lines.append(f"Reports that mention it ({len(reps)}, newest first):")
        for r in reps[:15]:
            lines.append(f"- {_d(r['created_at'])} · {r['title']} [{r['id']}] ({r['status']})")
            refs.append(_ref("report", r["id"], f"Report: {r['title']}"))
    if ent.get("attachments"):
        lines.append("Attachments: " + ", ".join(a["filename"] for a in ent["attachments"][:8]))

    try:
        on = boards_module.entity_boards(ent["id"], user=ctx["user"])
        for e in on.get("entries") or []:
            label = on["labels"].get(e["board"], e["board"])
            bits = [b for b in (e.get("urgency"), e.get("reason")) if b]
            lines.append(f"On the {label} board: {' — '.join(bits) or 'yes'}"
                         f"{', until ' + e['expires_at'][:10] if e.get('expires_at') else ''}")
        for p in on.get("priorities") or []:
            lines.append(f"Named in open priority P{p['priority']}: {p['title']}")
    except Exception:  # noqa: BLE001 - boards are optional; the dossier stands without them
        pass
    return "\n".join(lines), refs


def open_record(ctx, id: str = "") -> tuple[str, list]:  # noqa: A002 - the name the model sees
    ref = (id or "").strip().strip("[]").strip()
    if not ref:
        return "open_record needs the id of a record or report.", []
    with db_cursor() as cur:
        if ref.startswith("report-"):
            return _open_report(cur, ref, ctx.get("body_chars", 2500))
        entity_id, candidates = resolve_entity(cur, ref)
        if entity_id is None:
            cur.execute("SELECT id FROM reports WHERE lower(title) = lower(%s) LIMIT 1", (ref,))
            row = cur.fetchone()
            if row:
                return _open_report(cur, row[0], ctx.get("body_chars", 2500))
            return _not_found(ref, candidates)
        return _open_entity(ctx, cur, entity_id)


# ---------------------------------------------------------------------------
# network
# ---------------------------------------------------------------------------

def network(ctx, id: str = "", steps: int = 1, record_type: str | None = None) -> tuple[str, list]:  # noqa: A002
    with db_cursor() as cur:
        entity_id, candidates = resolve_entity(cur, id)
    if entity_id is None:
        return _not_found(id, candidates)
    depth = 2 if str(steps).strip() in ("2", "two") else 1
    rtype = (record_type or "").strip().lower().rstrip("s") or None
    if rtype not in ENTITY_TYPES:
        rtype = None
    try:
        g = graph_module._focus_graph(entity_id, depth, True, False, 160)
    except HTTPException:
        return f"No record with id {entity_id}.", []
    focus = g["focus"]
    by_id = {n["id"]: n for n in g["nodes"]}
    # How each record connects: to the focus directly, or via which neighbour.
    links: dict = {}
    for e in g["edges"]:
        for a, b, reads in ((e["from"], e["to"], e["relationship_type"]),
                            (e["to"], e["from"], entities_module.inverse_relationship_type(e["relationship_type"]))):
            if a == focus["id"]:
                links.setdefault(b, []).append((reads, None, e["confidence"]))
    via: dict = {}
    for e in g["edges"]:
        for a, b in ((e["from"], e["to"]), (e["to"], e["from"])):
            if by_id.get(a, {}).get("steps") == 1 and by_id.get(b, {}).get("steps") == 2:
                via.setdefault(b, []).append((e["relationship_type"], a))

    refs = [_ent_ref(focus["id"], focus["entity_type"], focus["name"])]
    lines = [f"Network around {_ent(focus['id'], focus['entity_type'], focus['name'])}"
             f" (live links only{', ' + TYPE_LABELS[rtype] + ' only' if rtype else ''}):"]
    for step in (1, 2) if depth == 2 else (1,):
        ring = [n for n in g["nodes"] if n["steps"] == step and (not rtype or n["entity_type"] == rtype)]
        if not ring:
            if step == 1:
                lines.append("No direct links" + (f" to any {TYPE_LABELS[rtype].lower()}" if rtype else "") + ".")
            continue
        lines.append("Direct links:" if step == 1 else "Two steps out:")
        for n in ring[:45]:
            if step == 1:
                how = "; ".join(f"{t.replace('_', ' ')} (graded {c})" for t, _, c in links.get(n["id"], [])[:3])
            else:
                hops = via.get(n["id"], [])[:2]
                how = "; ".join(f"via {by_id[m]['name']} ({t.replace('_', ' ')})" for t, m in hops if m in by_id)
            hostile = " — assessed Hostile" if n.get("alignment") == "Hostile" else ""
            lines.append(f"- {_ent(n['id'], n['entity_type'], n['name'])}"
                         f"{' — ' + how if how else ''}{hostile}")
            refs.append(_ent_ref(n["id"], n["entity_type"], n["name"]))
        if len(ring) > 45:
            lines.append(f"  …and {len(ring) - 45} more.")
    if g.get("truncated"):
        lines.append("(The network is larger than this; nearest records shown first.)")
    return "\n".join(lines), refs


# ---------------------------------------------------------------------------
# connection
# ---------------------------------------------------------------------------

def connection(ctx, from_id: str = "", to_id: str = "", max_steps: int = 4) -> tuple[str, list]:
    with db_cursor() as cur:
        a, ca = resolve_entity(cur, from_id)
        if a is None:
            return _not_found(from_id, ca)
        b, cb = resolve_entity(cur, to_id)
        if b is None:
            return _not_found(to_id, cb)
        if a == b:
            return "Those are the same record.", []
        limit = max(1, min(6, _days(max_steps, 4, 6)))
        cur.execute(
            """
            SELECT r.from_entity_id, r.to_entity_id, r.relationship_type, r.confidence
              FROM relationships r
              JOIN entities f ON f.id = r.from_entity_id AND f.is_active AND f.merged_into IS NULL
              JOIN entities t ON t.id = r.to_entity_id AND t.is_active AND t.merged_into IS NULL
             WHERE r.expires_on IS NULL OR r.expires_on >= CURRENT_DATE
            """)
        adj: dict = {}
        for f, t, rt, conf in cur.fetchall():
            adj.setdefault(f, []).append((t, rt, conf))
            adj.setdefault(t, []).append((f, entities_module.inverse_relationship_type(rt), conf))

        # Breadth-first, keeping every parent at the shortest distance, so we
        # can report more than one route when there are equally short ones —
        # two independent chains are a stronger finding than one.
        dist = {a: 0}
        parents: dict = {a: []}
        q = deque([a])
        while q:
            node = q.popleft()
            if dist[node] >= limit or (b in dist and dist[node] >= dist[b]):
                continue
            for nxt, rt, conf in adj.get(node, []):
                if nxt not in dist:
                    dist[nxt] = dist[node] + 1
                    parents[nxt] = [(node, rt, conf)]
                    q.append(nxt)
                elif dist[nxt] == dist[node] + 1:
                    parents[nxt].append((node, rt, conf))
        if b not in dist:
            cur.execute("SELECT id, entity_type, name FROM entities WHERE id = ANY(%s)", ([a, b],))
            names = {r[0]: r for r in cur.fetchall()}
            return (f"No chain of live links within {limit} steps connects "
                    f"{names[a][2]} and {names[b][2]}. They may be connected only through "
                    f"expired links, reports, or not at all."), \
                [_ent_ref(*names[a]), _ent_ref(*names[b])]

        paths = []

        def walk(node, tail):
            if len(paths) >= 3:
                return
            if node == a:
                paths.append(list(reversed(tail)))
                return
            for prev, rt, conf in parents[node]:
                walk(prev, tail + [(prev, rt, conf, node)])
        walk(b, [])

        ids = {a, b} | {x for p in paths for hop in p for x in (hop[0], hop[3])}
        cur.execute("SELECT id, entity_type, name FROM entities WHERE id = ANY(%s)", (list(ids),))
        names = {r[0]: r for r in cur.fetchall()}

    lines = [f"Shortest chain{'s' if len(paths) > 1 else ''} of live links "
             f"({dist[b]} step{'s' if dist[b] > 1 else ''}):"]
    for i, p in enumerate(paths, 1):
        chain = names[p[0][0]][2]
        for frm, rt, conf, to in p:
            chain += f" —{rt.replace('_', ' ')} (graded {conf})→ {names[to][2]}"
        lines.append(f"{i}. {chain}")
    lines.append("Ids: " + ", ".join(f"{names[i][2]} [{i}]" for i in ids))
    return "\n".join(lines), [_ent_ref(*names[i]) for i in ids]


# ---------------------------------------------------------------------------
# list_reports / field_reports
# ---------------------------------------------------------------------------

def list_reports(ctx, days: int | None = None, about: str | None = None, text: str | None = None,
                 status: str | None = None, precedence: str | None = None,
                 limit: int = 15) -> tuple[str, list]:
    where, params, joins = [], [], ""
    described = []
    with db_cursor() as cur:
        if about:
            entity_id, candidates = resolve_entity(cur, about)
            if entity_id is None:
                return _not_found(about, candidates)
            joins = "JOIN report_entities re ON re.report_id = r.id"
            where.append("re.entity_id = %s")
            params.append(entity_id)
            cur.execute("SELECT name FROM entities WHERE id = %s", (entity_id,))
            described.append(f"about {cur.fetchone()[0]}")
        n = _days(days)
        if n:
            where.append("r.created_at >= now() - %s * interval '1 day'")
            params.append(n)
            described.append(f"last {n} days")
        for t in _terms(text or ""):
            where.append("(r.title ILIKE %s OR r.body_markdown ILIKE %s)")
            params += [f"%{t}%", f"%{t}%"]
        if text:
            described.append(f"mentioning '{text}'")
        if status in ("draft", "confirmed"):
            where.append("r.status = %s")
            params.append(status)
            described.append(status)
        if precedence:
            where.append("lower(r.criticality) = lower(%s)")
            params.append(precedence)
            described.append(f"precedence {precedence}")
        cap = max(1, min(30, _days(limit, 15, 30)))
        sql_where = ("WHERE " + " AND ".join(where)) if where else ""
        cur.execute(f"SELECT COUNT(DISTINCT r.id) FROM reports r {joins} {sql_where}", params)
        total = cur.fetchone()[0]
        cur.execute(
            f"SELECT DISTINCT r.id, r.title, r.status, r.credibility_rating, r.criticality, "
            f"       r.created_at, r.author_id, r.body_markdown "
            f"  FROM reports r {joins} {sql_where} ORDER BY r.created_at DESC LIMIT %s",
            params + [cap])
        rows = cur.fetchall()
        authors = _author_names(cur, [r[6] for r in rows])

    what = ", ".join(described) or "all"
    if not rows:
        return f"No reports ({what}).", []
    lines = [f"Reports ({what}): {total} found" + (f", newest {len(rows)} shown" if total > len(rows) else "")]
    refs = []
    for rid, title, status, cred, crit, created, author, body in rows:
        meta = [status, f"credibility {cred}" if cred else "unrated"]
        if crit:
            meta.append(crit.upper())
        lines.append(f"- {_d(created)} · {title} [{rid}] ({', '.join(meta)}; "
                     f"by {authors.get(author, 'unknown')}) — {_clip(_plain(body), 150)}")
        refs.append(_ref("report", rid, f"Report: {title}"))
    return "\n".join(lines), refs


def field_reports(ctx, days: int | None = None, text: str | None = None,
                  status: str | None = None, limit: int = 15) -> tuple[str, list]:
    where, params, described = [], [], []
    n = _days(days)
    if n:
        where.append("s.received_at >= now() - %s * interval '1 day'")
        params.append(n)
        described.append(f"last {n} days")
    for t in _terms(text or ""):
        where.append("(s.title ILIKE %s OR COALESCE(s.body,'') ILIKE %s OR s.fields::text ILIKE %s "
                     " OR COALESCE(s.location_note,'') ILIKE %s OR COALESCE(s.relay_note,'') ILIKE %s)")
        params += [f"%{t}%"] * 5
    if text:
        described.append(f"mentioning '{text}'")
    if status in ("new", "accepted", "rejected"):
        where.append("s.status = %s")
        params.append(status)
        described.append({"new": "waiting for review", "accepted": "accepted",
                          "rejected": "set aside"}[status])
    cap = max(1, min(30, _days(limit, 15, 30)))
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    with db_cursor() as cur:
        try:
            cur.execute(
                f"""SELECT s.id, s.title, s.body, s.template, s.fields, s.criticality, s.observed_at,
                           s.received_at, s.lat, s.lng, s.location_note, s.status, s.report_id,
                           s.device_label, s.user_id, s.relay_label, s.relay_priorities, s.relay_note
                      FROM field_submissions s {sql_where}
                     ORDER BY COALESCE(s.observed_at, s.received_at) DESC LIMIT %s""",
                params + [cap])
        except Exception:  # noqa: BLE001 - an older console without the field queue
            return "This console has no field reports.", []
        rows = cur.fetchall()
        authors = _author_names(cur, [r[14] for r in rows])
    what = ", ".join(described) or "all"
    if not rows:
        return f"No field reports ({what}).", []
    lines = [f"Field reports ({what}), newest first:"]
    refs = []
    for (sid, title, body, template, fields, crit, observed, received, lat, lng, note, status,
         report_id, device, uid, relay, relay_pris, relay_note) in rows:
        when = _d(observed or received)
        bits = [f"{when} · {title} (field report #{sid}, {template or 'free text'}"
                f"{', ' + crit.upper() if crit else ''}; {status}"
                f"{' → report ' + report_id if report_id else ''})"]
        who = authors.get(uid)
        src = device or "a phone"
        if relay and relay not in src:
            src += f" via {relay}"
        bits.append(f"from {who} on {src}" if who else f"from {src}")
        if lat is not None and lng is not None:
            bits.append(f"at {lat:.5f}, {lng:.5f}{' (' + note + ')' if note else ''}")
        elif note:
            bits.append(f"at {note}")
        lines.append("- " + "; ".join(bits))
        flds = fields if isinstance(fields, dict) else (json.loads(fields) if fields else {})
        shown = [f"{k.replace('_', ' ')}: {_clip(str(v), 80)}" for k, v in flds.items()
                 if v not in (None, "", [], {})][:8]
        if shown:
            lines.append("  " + "; ".join(shown))
        if body:
            lines.append("  " + _clip(body, 220))
        if relay_pris:
            pris = relay_pris if isinstance(relay_pris, list) else []
            lines.append("  Team lead tagged: " + (", ".join(f"P{p}" for p in pris) or "background")
                         + (f" — note: {_clip(relay_note, 120)}" if relay_note else ""))
        if report_id:
            refs.append(_ref("report", report_id, f"Report from field #{sid}"))
    return "\n".join(lines), refs


# ---------------------------------------------------------------------------
# case_overview / priorities
# ---------------------------------------------------------------------------

def case_overview(ctx, days: int = 14) -> tuple[str, list]:
    n = _days(days, 14, 365)
    window = min(insights_module.WINDOW_CHOICES, key=lambda c: abs(c - n))
    refs, lines = [], []
    with db_cursor() as cur:
        cur.execute("SELECT entity_type, count(*) FROM entities WHERE is_active AND merged_into IS NULL "
                    "GROUP BY entity_type ORDER BY 2 DESC")
        counts = cur.fetchall()
        cur.execute("SELECT count(*), count(*) FILTER (WHERE created_at >= now() - %s * interval '1 day') "
                    "  FROM reports", (window,))
        total_reports, recent_reports = cur.fetchone()
        attention = insights_module._needs_attention(cur)
        hotspots = insights_module._hotspots(cur, window)
        rising = insights_module._rising(cur, window)
        tempo = insights_module._tempo(cur)
    lines.append("Records: " + ", ".join(f"{c} {TYPE_LABELS.get(t, t).lower()}" for t, c in counts))
    lines.append(f"Reports: {total_reports} in total, {recent_reports} in the last {window} days")
    weeks = tempo.get("weeks") or []
    if weeks:
        lines.append("Reports per week, oldest to newest: "
                     + ", ".join(str(w["reports"]) for w in weeks))
    urgent = attention.get("urgent_reports") or []
    if urgent:
        lines.append("Urgent reports (Flash/Immediate):")
        for r in urgent[:6]:
            lines.append(f"- {_d(r['created_at'])} · {r['title']} [{r['id']}] ({r['status']}, {r['criticality']})")
            refs.append(_ref("report", r["id"], f"Report: {r['title']}"))
    stale = attention.get("stale_drafts") or []
    if stale:
        lines.append(f"Drafts untouched for {attention.get('stale_draft_days')}+ days: "
                     + "; ".join(f"{r['title']} [{r['id']}]" for r in stale[:6]))
    for e in (attention.get("expiring_events") or [])[:5]:
        lines.append(f"Event lapsing soon: {e.get('name')} [{e.get('id')}] on {_d(e.get('expires_at'))}")
    for p in (attention.get("people_of_concern") or [])[:6]:
        lines.append(f"Person of concern: {p.get('name')} [{p.get('id')}] — "
                     f"{p.get('life_status') or ''} {p.get('disposition') or ''}".strip())
    if hotspots:
        lines.append(f"Hotspots (locations several records point at, last {window} days):")
        for h in hotspots[:5]:
            lines.append(f"- {h['name']} [{h['id']}]: {h['total']} records "
                         f"({h.get('report_count', 0)} reports, {h.get('event_count', 0)} events), "
                         f"last {_d(h.get('last_seen'))}")
            refs.append(_ref("entity", h["id"], f"Location: {h['name']}"))
    if rising:
        lines.append(f"Names rising (more reports this {window} days than the {window} before):")
        for r in rising[:6]:
            lines.append(f"- {r.get('name')} [{r.get('id')}]: {r.get('current')} vs {r.get('previous')}")
    return "\n".join(lines), refs


def priorities(ctx, include_closed: bool = False) -> tuple[str, list]:
    with db_cursor() as cur:
        try:
            boards = boards_module._load_boards(cur)
        except Exception:  # noqa: BLE001
            boards = {}
        if not (boards.get("priorities") or {}).get("enabled"):
            return "The Priorities board is switched off on this console, so there are no recorded priorities.", []
        items = boards_module._priority_rows(cur, None if include_closed else "open")
        label = boards["priorities"].get("label") or "Priorities"
    if not items:
        return f"No {'' if include_closed else 'open '}priorities on the {label} board.", []
    lines, refs = [f"{label} ({len(items)}), most wanted first:"], []
    for p in items:
        due = f", due {p['due_date'][:10]}" if p.get("due_date") else ""
        lines.append(f"- P{p['priority']} · {p['title']} (id {p['id']}, {p['status']}{due})")
        if p.get("question"):
            lines.append(f"  Question: {_clip(p['question'], 300)}")
        if p.get("indicators"):
            lines.append("  Would be answered by: " + "; ".join(_clip(i, 80) for i in p["indicators"][:8]))
        for e in (p.get("entities") or [])[:8]:
            refs.append(_ent_ref(e["id"], e["entity_type"], e["name"]))
        if p.get("entities"):
            lines.append("  Records: " + ", ".join(f"{e['name']} [{e['id']}]" for e in p["entities"][:8]))
        if p.get("answered_note"):
            lines.append(f"  Answer so far: {_clip(p['answered_note'], 240)}")
    return "\n".join(lines), refs


# ---------------------------------------------------------------------------
# The catalogue the model sees
# ---------------------------------------------------------------------------

def _fn(name, description, properties, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": list(required)}}}


TOOLS = [
    _fn("search_case",
        "Find records (people, organizations, locations, vehicles, events, sources, "
        "communications, documents) and reports by name, alias, plate, phone number, address "
        "or words in their text. Start here when you do not have an id yet.",
        {"query": {"type": "string", "description": "Words to look for, e.g. 'Kowal' or 'blue van'"},
         "record_type": {"type": "string", "description": "Optional: only this kind, e.g. person, "
                         "vehicle, location, report"}},
        ["query"]),
    _fn("open_record",
        "Read one record or report in full: its details, every live link with its grading, "
        "the reports that mention it, and any board it is on. For a report: its full text and "
        "the records linked to it.",
        {"id": {"type": "string", "description": "The id in square brackets, e.g. person-daniel-kowal-1a2b3c, "
                "or report-…"}},
        ["id"]),
    _fn("network",
        "List what a record is linked to, grouped as direct links and (with steps=2) the "
        "records two steps out, optionally only one kind (e.g. only vehicles).",
        {"id": {"type": "string"},
         "steps": {"type": "integer", "description": "1 (default) or 2"},
         "record_type": {"type": "string", "description": "Optional: only this kind"}},
        ["id"]),
    _fn("connection",
        "Find the shortest chains of links between two records — how A is connected to B.",
        {"from_id": {"type": "string"}, "to_id": {"type": "string"},
         "max_steps": {"type": "integer", "description": "Longest chain to consider, default 4"}},
        ["from_id", "to_id"]),
    _fn("list_reports",
        "List written reports, newest first, filtered by how recent, what they are about, "
        "words in them, status or precedence. Use for 'what came in this week' or 'every report "
        "about X'.",
        {"days": {"type": "integer", "description": "Only the last N days"},
         "about": {"type": "string", "description": "A record id: only reports linked to it"},
         "text": {"type": "string", "description": "Words that must appear in the report"},
         "status": {"type": "string", "description": "draft or confirmed"},
         "precedence": {"type": "string", "description": "Flash, Immediate, Priority or Routine"},
         "limit": {"type": "integer"}}),
    _fn("field_reports",
        "List reports sent in from field phones (and team relays): what was seen, where, by "
        "whom, and whether it has been reviewed.",
        {"days": {"type": "integer", "description": "Only the last N days"},
         "text": {"type": "string", "description": "Words that must appear, e.g. a plate or place"},
         "status": {"type": "string", "description": "new (waiting for review), accepted or rejected"},
         "limit": {"type": "integer"}}),
    _fn("case_overview",
        "A summary of the whole case file: how many records of each kind, reporting tempo, "
        "urgent and forgotten reports, hotspot locations and names that are suddenly appearing "
        "more often.",
        {"days": {"type": "integer", "description": "Window to look at, default 14"}}),
    _fn("priorities",
        "The team's intelligence priorities: each question the team needs answered, what "
        "would answer it, the records linked to it and any answer so far.",
        {"include_closed": {"type": "boolean"}}),
]

TOOL_FUNCS = {
    "search_case": search_case, "open_record": open_record, "network": network,
    "connection": connection, "list_reports": list_reports, "field_reports": field_reports,
    "case_overview": case_overview, "priorities": priorities,
}

# What the panel shows while a lookup runs, and in the trail under an answer.
def describe(name: str, args: dict) -> str:
    a = args or {}
    if name == "search_case":
        kind = f" ({a['record_type']})" if a.get("record_type") else ""
        return f"Searched for “{a.get('query', '')}”{kind}"
    if name == "open_record":
        return f"Opened {a.get('_label') or a.get('id', '')}"
    if name == "network":
        two = " two steps out" if str(a.get("steps")) == "2" else ""
        kind = f", {a['record_type']} only" if a.get("record_type") else ""
        return f"Looked at what is linked to {a.get('_label') or a.get('id', '')}{two}{kind}"
    if name == "connection":
        return f"Traced links from {a.get('from_id', '')} to {a.get('to_id', '')}"
    if name == "list_reports":
        bits = [f"last {a['days']} days" if a.get("days") else "",
                f"about {a['about']}" if a.get("about") else "",
                f"“{a['text']}”" if a.get("text") else "",
                a.get("status") or "", a.get("precedence") or ""]
        return "Listed reports" + (f" ({', '.join(b for b in bits if b)})" if any(bits) else "")
    if name == "field_reports":
        bits = [f"last {a['days']} days" if a.get("days") else "",
                f"“{a['text']}”" if a.get("text") else "", a.get("status") or ""]
        return "Listed field reports" + (f" ({', '.join(b for b in bits if b)})" if any(bits) else "")
    if name == "case_overview":
        return f"Checked the case overview (last {a.get('days') or 14} days)"
    if name == "priorities":
        return "Read the team's priorities"
    return name


def summarize(name: str, text: str, refs: list) -> str:
    """One line for the trail under an answer: what the lookup found."""
    lines = [l for l in (text or "").splitlines() if l.strip()]
    first = lines[0] if lines else "nothing"

    def names(limit=3):
        picked = [r["label"].split(": ", 1)[-1] for r in refs[:limit]]
        more = len(refs) - len(picked)
        return ", ".join(picked) + (f" and {more} more" if more > 0 else "")

    if name == "search_case":
        if not refs:
            fields = sum(1 for l in lines if "field report #" in l)
            return f"{fields} field report(s)" if fields else "Nothing matched"
        return "Found " + names()
    if name == "open_record" and refs:
        links = re.search(r"^Links \((\d+)\)", text, re.M)
        reps = re.search(r"^Reports that mention it \((\d+)", text, re.M)
        bits = [f"{links.group(1)} links" if links else "", f"{reps.group(1)} reports" if reps else ""]
        bits = [b for b in bits if b]
        return refs[0]["label"] + (f" — {', '.join(bits)}" if bits else "")
    if name == "network":
        return f"{len(refs) - 1} linked records" if len(refs) > 1 else first
    if name == "connection":
        chain = next((l for l in lines if l[:2] == "1."), first)
        return chain[3:] if chain.startswith("1. ") else chain
    if name in ("list_reports", "field_reports"):
        n = sum(1 for l in lines if l.startswith("- "))
        return first.rstrip(":") if "found" in first else f"{n} found"
    return first.rstrip(":")


def run_tool(ctx: dict, name: str, args: dict) -> tuple[str, list]:
    """Run one lookup. Unknown tools, bad arguments and database errors all
    come back as text the model can read — never as an exception."""
    func = TOOL_FUNCS.get(name)
    if func is None:
        return (f"There is no lookup called '{name}'. Available: {', '.join(TOOL_FUNCS)}."), []
    clean = {k: v for k, v in (args or {}).items()
             if k in TOOL_SCHEMA_KEYS[name] and v not in (None, "")}
    try:
        return func(ctx, **clean)
    except TypeError as exc:
        return f"That lookup was called with the wrong arguments ({exc}).", []
    except Exception as exc:  # noqa: BLE001 - reported to the model, logged by the caller
        return f"That lookup failed: {exc}", []


TOOL_SCHEMA_KEYS = {t["function"]["name"]: set(t["function"]["parameters"]["properties"]) for t in TOOLS}
