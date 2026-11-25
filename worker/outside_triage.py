"""Outside events: the model reads each incident and triages it.

GDELT's events are coded by a machine from the first sentences of an article,
so "the actor who played a soldier fighting the Germans" arrives as Fight, a
history feature as an attack, and a story filed in Baltimore about somewhere
else as a Baltimore event. Nothing in GDELT's own fields can tell these apart.
Reading the article can, and since v1.16 the server keeps the article.

For each incident (only the lead report of a group of duplicates, so one call
per incident, not per row) the model answers, in a fixed JSON shape:

    is_event   a real thing that happened, or a specific credible threat —
               not a film, a book, history, opinion, sport, an obituary
    in_area    it happened in, or directly affects, the marked area
    category   the team's own categories (CATEGORIES), not CAMEO's
    severity   1–5 (SEVERITY)
    summary    one plain sentence
    reason     why

Nothing is deleted: the console shows filtered events in a view of their own,
with the reason. A person's correction is final (triage_by = 'analyst', which
this never overwrites) and is kept as an example the model is shown next
time, so it learns the team's judgement without any retraining.

When unsure, the model is told to keep an event: a person looking at one
event too many costs less than one never seen.

api/outside_events.py has the same CATEGORIES; tests/test_outside_triage.py
checks they match.
"""
import json

from db import db_cursor

# key: (label, what belongs in it — shown to the model)
CATEGORIES = {
    "protest": ("Protest or demonstration", "a rally, march, strike, picket or sit-in"),
    "unrest": ("Civil unrest or riot", "rioting, looting, clashes between crowds or with police"),
    "violent_crime": ("Violent crime", "a shooting, stabbing, robbery, assault, homicide, carjacking"),
    "police": ("Arrest or police action", "arrests, raids, warrants, police operations, charges filed"),
    "attack": ("Attack or armed violence", "a bombing, armed attack, arson attack, mass-casualty event"),
    "threat": ("Threat or extremism", "a specific threat, plot, extremist or gang activity, intimidation"),
    "disaster": ("Disaster or emergency", "a fire, explosion, flood, storm, hazmat, serious accident"),
    "infrastructure": ("Infrastructure or outage", "power, water, transit, roads, ports, communications"),
    "government": ("Government or political", "official decisions, emergency orders, elections, policy"),
    "other": ("Other", "a real event that fits none of the above"),
}
SEVERITY = {
    1: "routine — background, no effect on anyone's safety or operations",
    2: "minor — a local incident worth knowing about",
    3: "notable — worth a closer look",
    4: "significant — affects safety, movement or operations in the area",
    5: "critical — an immediate threat to life or a major disruption",
}
SCHEMA = {
    "type": "object",
    "properties": {
        "is_event": {"type": "boolean"},
        "in_area": {"type": "boolean"},
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "severity": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "summary": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["is_event", "in_area", "category", "severity", "summary", "reason"],
}
ARTICLE_CHARS = 2500
MAX_ATTEMPTS = 3

SYSTEM = """You triage open-source event reports for a team that watches specific areas.

The reports come from GDELT, which codes news articles into events automatically and often \
gets it wrong: it files a review of a war film as fighting, a history piece as an attack, a \
celebrity interview as a threat, and a story about somewhere else as local because the \
publisher is local. Read the article and decide for yourself. GDELT's coding is only a hint.

Answer with JSON:
- is_event: true only if the article reports something real that happened or is happening \
(recently), or a specific credible threat. false for: films, TV, books, games, actors and \
roles; history, anniversaries and memorials; opinion, editorials and commentary; sport; \
obituaries; general explainers and statistics; advertising; and articles that mention \
violence or conflict only in passing.
- in_area: true if it took place in, or directly affects, the area below. false if it \
happened elsewhere and only the publisher, a quote or a person's hometown is local.
- category: one of
{categories}
- severity, 1 to 5:
{severity}
- summary: one plain sentence (at most 25 words): what happened, where, when. No speculation.
- reason: one short sentence on why you judged it so.

When you cannot tell, keep it: is_event true, in_area true. A person will look at it."""


def _categories_text() -> str:
    return "\n".join(f"  {k}: {label} ({hint})" for k, (label, hint) in CATEGORIES.items())


def _severity_text() -> str:
    return "\n".join(f"  {n}: {text}" for n, text in SEVERITY.items())


def system_prompt(examples: list) -> str:
    text = SYSTEM.format(categories=_categories_text(), severity=_severity_text())
    if examples:
        lines = ["", "The team corrected these earlier. Follow their judgement on similar reports:"]
        for ex in examples:
            v = ex["verdict"]
            what = []
            if v.get("is_event") is False:
                what.append("not an event")
            elif v.get("in_area") is False:
                what.append("not in the area")
            else:
                what.append(f"category {v.get('category')}, severity {v.get('severity')}")
            lines.append(f"- \"{ex['text'][:240]}\" → {'; '.join(what)}")
        text += "\n".join(lines)
    return text


def user_prompt(ev: dict, zones: list) -> str:
    areas = []
    for z in zones:
        line = f"- {z['name']}"
        if z.get("focus"):
            line += f". The team's focus here: {z['focus']}"
        areas.append(line)
    parts = ["The area:" if len(areas) == 1 else "The areas:", *areas, "",
             f"GDELT coded it as: {ev['category'] or 'unknown'} — {ev['title']}",
             f"Placed at: {ev['place'] or 'unknown'}" + (f", {ev['occurred_on']}" if ev.get("occurred_on") else "")]
    if ev.get("headline"):
        parts.append(f"Headline: {ev['headline']}")
    if ev.get("body"):
        parts += ["", "The article (opening):", ev["body"][:ARTICLE_CHARS]]
    elif ev.get("notes"):
        parts += ["", "Notes:", ev["notes"][:ARTICLE_CHARS]]
    else:
        parts += ["", "No article text could be read. Judge from the headline and the coding; "
                      "when you cannot tell, keep it."]
    return "\n".join(parts)


def clean(data: dict) -> dict:
    """The model's answer, made safe to store whatever it actually said."""
    def boolish(v, default=True):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() not in ("false", "no", "0")
        return default
    cat = str(data.get("category") or "").strip().lower().replace(" ", "_")
    try:
        sev = int(data.get("severity"))
    except (TypeError, ValueError):
        sev = 2
    return {"is_event": boolish(data.get("is_event")), "in_area": boolish(data.get("in_area")),
            "category": cat if cat in CATEGORIES else "other", "severity": min(5, max(1, sev)),
            "summary": " ".join(str(data.get("summary") or "").split())[:300] or None,
            "reason": " ".join(str(data.get("reason") or "").split())[:300] or None}


def excerpt(ev: dict) -> str:
    """What a correction keeps as its example: the headline and opening."""
    head = ev.get("headline") or ev.get("title") or ""
    body = (ev.get("body") or ev.get("notes") or "")[:200]
    return (head + (" — " + body if body else "")).strip()


def load_examples(cur, limit: int) -> list:
    if limit <= 0:
        return []
    cur.execute("SELECT text, verdict FROM outside_triage_corrections ORDER BY created_at DESC LIMIT %s", (limit,))
    return [{"text": t, "verdict": v if isinstance(v, dict) else json.loads(v)} for t, v in cur.fetchall()]


def due(cur, settings: dict, limit: int) -> list:
    """Incidents not yet triaged, newest first, once their article has been
    read (or could not be, or it is not coming)."""
    cur.execute(
        "SELECT e.id, e.source, e.title, e.category, e.place, e.occurred_on, e.zone_ids, e.notes, "
        "       a.title, a.body "
        "FROM outside_events e LEFT JOIN outside_articles a ON a.url = e.url "
        "WHERE e.triaged_at IS NULL AND e.dup_of IS NULL AND e.triage_attempts < %s "
        "  AND e.status IN ('new', 'read') AND (e.source = 'gdelt' OR %s) "
        "  AND (a.body IS NOT NULL OR a.error IS NOT NULL OR e.url IS NULL OR NOT %s "
        "       OR e.created_at < now() - interval '30 minutes') "
        "ORDER BY e.created_at DESC, e.id DESC LIMIT %s",
        (MAX_ATTEMPTS, bool(settings.get("triage_acled")), bool(settings.get("prefetch_articles", True)), limit))
    cols = ("id", "source", "title", "category", "place", "occurred_on", "zone_ids", "notes", "headline", "body")
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def zones_of(cur, ids: list) -> list:
    if not ids:
        return []
    cur.execute("SELECT id, name, outside_focus FROM map_zones WHERE id = ANY(%s) ORDER BY id", (list(ids),))
    return [{"id": i, "name": n, "focus": (f or "").strip()} for i, n, f in cur.fetchall()]


def triage(settings: dict, client) -> dict:
    """One pass. {checked, filtered, failed, error}."""
    out = {"checked": 0, "filtered": 0, "failed": 0, "error": None}
    if not (client and client.enabled):
        out["error"] = "the model is turned off (Admin → Model)"
        return out
    model = (settings.get("triage_model") or "").strip() or client.model
    min_sev = int(settings.get("triage_min_severity") or 1)
    with db_cursor() as cur:
        todo = due(cur, settings, int(settings.get("triage_per_pass") or 20))
        examples = load_examples(cur, int(settings.get("triage_examples") or 0))
    if not todo:
        return out
    system = system_prompt(examples)
    for ev in todo:
        with db_cursor() as cur:
            zones = zones_of(cur, ev["zone_ids"])
        data = client.structured(system, user_prompt(ev, zones), SCHEMA, model=model)
        with db_cursor(commit=True) as cur:
            if data is None:
                out["failed"] += 1
                out["error"] = getattr(client, "last_error", None) or "the model did not answer"
                cur.execute("UPDATE outside_events SET triage_attempts = triage_attempts + 1, triage_error = %s "
                            "WHERE id = %s", (out["error"][:500], ev["id"]))
                if out["failed"] >= 3 and out["checked"] == 0:
                    break                      # the model is down or too slow: try again next pass
                continue
            v = clean(data)
            cur.execute(
                "UPDATE outside_events SET triage_is_event = %s, triage_in_area = %s, triage_category = %s, "
                "triage_severity = %s, triage_summary = %s, triage_reason = %s, triage_by = 'model', "
                "triage_model = %s, triaged_at = now(), triage_error = NULL "
                "WHERE id = %s AND triage_by IS DISTINCT FROM 'analyst'",
                (v["is_event"], v["in_area"], v["category"], v["severity"], v["summary"], v["reason"],
                 model, ev["id"]))
            out["checked"] += 1
            if not v["is_event"] or not v["in_area"] or v["severity"] < min_sev:
                out["filtered"] += 1
    return out
