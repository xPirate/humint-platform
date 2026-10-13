"""The assistant's working loop: look things up, read them, decide, answer.

Until v1.11 the assistant made ONE search for records that shared words with
the question, pasted the top few into the prompt, and asked the model once.
It could never follow a link, check a date or count anything, so the best it
could do was read back the records an analyst would have clicked on anyway.

Now the model is given the lookups in assistant_tools.py and works in a loop:

    question → model decides what to look up → lookup runs → model reads the
    result → looks up something else, or answers

up to a budget of lookups an admin sets. Each lookup is shown in the panel as
it happens, and kept with the answer, so the reasoning can be checked rather
than taken on trust.

Three things an analyst's hardware decides, all on Admin → Ollama Settings:

- Thinking. A model that can reason (Qwen3, gpt-oss, DeepSeek-R1) works the
  question through before each step. Noticeably better at multi-step
  questions, and several times slower. A model that cannot think ignores it.
- Context window. Sent with every call. Ollama's default is small, and a
  longer prompt loses its BEGINNING — the instructions — silently.
- Lookups per question. 0 is the old single search, for a team whose model
  cannot call tools at all or whose machine cannot afford several calls.

Models that cannot call tools are detected on the first call (Ollama says so)
and answered the old way, with a note, rather than failing.

Read-only throughout: see assistant_tools.py.
"""

import json
import re
import time
from datetime import date

import assistant_tools
from ollama_client import OllamaUnsupported

SYSTEM_PROMPT = """You are the research assistant inside a HUMINT case-management console. \
You help an analyst answer questions about THEIR case file. Today is {today}.

You cannot see the case file directly. Use the lookups:
- search_case: find records and reports by name, alias, plate, number or words. Start here \
when you do not have an id.
- open_record: read one record or report in full.
- network: what a record is linked to (steps=2 for two steps out).
- connection: how two records are connected.
- list_reports / field_reports: what came in, when, and about whom.
- case_overview: the big picture. priorities: what the team needs answered.
Every record is shown with its id in [square brackets]; pass that id to the next lookup.

Work like an analyst: look things up before you answer, follow the links that matter, and \
stop when you have enough. Several lookups are normal for a question about connections, \
timelines or patterns.

Rules:
- Use only what the lookups returned. Never invent a person, link, date or fact. If the file \
does not show something, say so and say what you checked.
- Links and reports are graded 1 (confirmed) to 6 (cannot be judged). When a conclusion rests \
on a weak grade, say so. Keep what the file shows apart from your own inference.
- Answer first, in a sentence or two, then the supporting points. Short paragraphs or a short \
list; no headings. Write names as they appear; do not print ids."""

SINGLE_SEARCH_PROMPT = """You are the research assistant inside a HUMINT case-management console, \
helping an analyst with THEIR case file. Today is {today}. You have no knowledge of the case \
beyond the "Relevant case data" below, found by one search for this question.

Answer only from that data plus ordinary reasoning over it. If it does not contain the answer, \
say so plainly; never invent a name, date, link or fact. Answer first, then the supporting \
points; short paragraphs or a short list, no headings."""

NO_MORE_LOOKUPS = ("(No more lookups are available for this question. Answer it now from what "
                   "the lookups above showed, and say plainly if something could not be checked.)")

# Characters per token, roughly, for English with ids in it. Used only to
# keep the prompt inside the window; erring short just trims a little early.
CHARS_PER_TOKEN = 3.3


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "… [trimmed to fit]"


def _inline_tool_calls(content: str) -> list[dict]:
    """Some model templates leave a tool call in the text instead of in
    tool_calls — <tool_call>{...}</tool_call>, or the bare JSON. Picked up
    here so those models still work, rather than the call being shown to the
    analyst as the "answer"."""
    found = []
    blocks = re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content or "", re.S)
    if not blocks and (content or "").strip().startswith("{"):
        blocks = [content.strip()]
    for block in blocks:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        name = data.get("name")
        args = data.get("arguments", data.get("parameters", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if name in assistant_tools.TOOL_FUNCS and isinstance(args, dict):
            found.append({"name": name, "arguments": args})
    return found


def _estimate_tokens(messages: list[dict], extra_chars: int = 0) -> int:
    chars = extra_chars + sum(len(m.get("content") or "") + 20 for m in messages)
    for m in messages:
        if m.get("tool_calls"):
            chars += len(json.dumps(m["tool_calls"]))
    return int(chars / CHARS_PER_TOKEN)


def _fit(messages: list[dict], budget_tokens: int, tools_chars: int) -> list[dict]:
    """Shrink the conversation until it fits the window, oldest first.

    Order of sacrifice: old conversation turns, then the results of earlier
    lookups (the latest two stay whole — they are what the model is reasoning
    about right now), then the old turns entirely. The system prompt and the
    question are never touched."""
    msgs = [dict(m) for m in messages]
    if _estimate_tokens(msgs, tools_chars) <= budget_tokens:
        return msgs
    question_at = max(i for i, m in enumerate(msgs) if m["role"] == "user" and not m.get("_nudge"))
    for i in range(1, question_at):                       # earlier turns, to a line each
        msgs[i]["content"] = _clip(msgs[i]["content"] or "", 300)
    tool_idx = [i for i, m in enumerate(msgs) if m["role"] == "tool"]
    for i in tool_idx[:-2]:
        if _estimate_tokens(msgs, tools_chars) <= budget_tokens:
            break
        msgs[i]["content"] = _clip(msgs[i]["content"] or "", 500)
    if _estimate_tokens(msgs, tools_chars) > budget_tokens:
        msgs = [msgs[0]] + msgs[question_at:]             # drop the earlier turns
    for i in tool_idx[-2:]:
        if _estimate_tokens(msgs, tools_chars) <= budget_tokens:
            break
        for m in msgs:
            if m["role"] == "tool":
                m["content"] = _clip(m["content"] or "", 1200)
    return msgs


def _citations(answer: str, pool: dict, opened: list) -> list[dict]:
    """The records an answer actually rests on, for the chips under it.

    Everything the lookups returned is in `pool` — often dozens of records,
    most of them search results the model glanced past. Chips are only for
    the ones the answer names (by name or id), up to eight; if it names none,
    the records the model opened in full."""
    text = (answer or "").lower()
    chosen = []
    for ref in pool.values():
        name = ref["label"].split(": ", 1)[-1].lower()
        if len(name) >= 3 and (name in text or ref["id"].lower() in text):
            chosen.append(ref)
        if len(chosen) >= 8:
            break
    if not chosen:
        chosen = [pool[i] for i in opened if i in pool][:5]
    return chosen


def run(ollama, question: str, history: list[dict], settings: dict, user: dict,
        semantic=None, single_search=None):
    """Answer `question`, yielding progress events as it goes.

    Events: {"type": "status", "text"}, {"type": "step", "label", "summary"?,
    "running"?}, {"type": "thinking", "text"}, {"type": "note", "text"}, and
    finally {"type": "done", ...} or {"type": "error", "detail"}.

    `single_search(question)` -> (context_text, citations) is the pre-v1.11
    retrieval, used when lookups are set to 0 or the model cannot call tools.
    """
    started = time.monotonic()
    num_ctx = int(settings.get("context_tokens") or 8192)
    max_lookups = int(settings.get("max_lookups") if settings.get("max_lookups") is not None else 6)
    think = bool(settings.get("thinking"))
    think_flag: bool | None = think        # None once the model has said it cannot think
    today = date.today().strftime("%A %d %B %Y")

    # What fits. Room is kept for the reply (more when the model thinks,
    # since its reasoning comes out of the same window), and the tool
    # catalogue itself costs about a thousand tokens on every call.
    tools_chars = len(json.dumps(assistant_tools.TOOLS))
    reserve = 2000 if think else 900
    budget = max(1024, num_ctx - reserve)
    per_result = int(max(1200, min(8000, (budget - tools_chars / CHARS_PER_TOKEN - 600)
                                   * CHARS_PER_TOKEN / max(2, min(max_lookups, 4)))))
    turns = 2 if num_ctx <= 4096 else 4 if num_ctx <= 8192 else 6
    past = [{"role": m["role"], "content": _clip(m["content"] or "", 1500)}
            for m in (history or [])[-turns * 2:]]

    tool_ctx = {"user": user, "body_chars": int(per_result * 0.6), "semantic": semantic}
    steps, thinking, pool, opened, seen, notes = [], [], {}, [], {}, []
    lookups = 0

    def think_events(resp):
        if resp.get("thinking"):
            thinking.append(resp["thinking"])
            yield {"type": "thinking", "text": resp["thinking"][-4000:]}

    def note(text):
        notes.append(text)
        return {"type": "note", "text": text}

    def converse(msgs, tools):
        nonlocal think_flag
        while True:
            fitted = [{k: v for k, v in m.items() if not k.startswith("_")}
                      for m in _fit(msgs, budget, tools_chars if tools else 0)]
            try:
                return ollama.converse(fitted, tools=tools, think=think_flag, num_ctx=num_ctx)
            except OllamaUnsupported as exc:
                if exc.feature == "thinking" and think_flag is not None:
                    think_flag = None
                    notes.append("This model can't think before answering, so it answered "
                                 "straight away. Thinking needs a model such as Qwen3 or gpt-oss.")
                    continue
                raise

    def finish(answer, citations, mode):
        return {"type": "done", "answer": answer, "citations": citations,
                "steps": steps, "thinking": "\n\n".join(thinking)[-12000:],
                "seconds": round(time.monotonic() - started, 1), "lookups": lookups,
                "mode": mode, "thought": bool(thinking), "notes": notes,
                # Every record any lookup returned — what the model read on
                # the analyst's behalf, which is what the audit entry lists.
                "seen": list(pool) or [c["id"] for c in citations]}

    # ---------------------------------------------------------- single search
    def single():
        yield {"type": "status", "text": "Searching the case file…"}
        context, citations = single_search(question) if single_search else ("", [])
        steps.append({"tool": "single_search", "label": "Searched the case file once",
                      "summary": f"{len(citations)} record(s) found"})
        prompt = SINGLE_SEARCH_PROMPT.format(today=today) + (
            f"\n\nRelevant case data:\n\n{_clip(context, int(budget * CHARS_PER_TOKEN * 0.6))}" if context else
            "\n\nRelevant case data: none found for this question. Say plainly that nothing "
            "matching it was found, rather than guessing.")
        yield {"type": "status", "text": "Thinking…" if think_flag else "Writing the answer…"}
        resp = converse([{"role": "system", "content": prompt}, *past,
                         {"role": "user", "content": question}], None)
        if resp is None:
            yield {"type": "error", "detail": "unreachable"}
            return
        yield from think_events(resp)
        yield finish(resp["content"], citations, "single")

    if max_lookups <= 0:
        yield from single()
        return

    # ------------------------------------------------------------ lookup loop
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(today=today)}, *past,
                {"role": "user", "content": question}]
    nudged = empty_retries = 0
    while True:
        offer = lookups < max_lookups
        if not offer and not nudged:
            messages.append({"role": "user", "content": NO_MORE_LOOKUPS, "_nudge": True})
            nudged = 1
        yield {"type": "status",
               "text": ("Thinking…" if think_flag else "Deciding what to look up…") if not steps
               else ("Thinking about what it found…" if think_flag else "Reading what it found…")}
        try:
            resp = converse(messages, assistant_tools.TOOLS if offer else None)
        except OllamaUnsupported as exc:
            if exc.feature == "tools" and not steps:
                yield note("This model can't look things up, so it answered from one search "
                           "instead. A model that can call tools (Qwen3, Llama 3.1, gpt-oss) "
                           "does better.")
                yield from single()
                return
            yield {"type": "error", "detail": str(exc)}
            return
        if resp is None:
            yield {"type": "error", "detail": "unreachable"}
            return
        yield from think_events(resp)

        calls = resp["tool_calls"] or (_inline_tool_calls(resp["content"]) if offer else [])
        if calls and offer:
            echo = resp["message"].get("tool_calls") or [
                {"function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls]
            messages.append({"role": "assistant", "content": resp["content"] if resp["tool_calls"] else "",
                             "tool_calls": echo})
            for call in calls:
                name, args = call["name"], dict(call["arguments"] or {})
                key = name + json.dumps(args, sort_keys=True, default=str)
                if lookups >= max_lookups:
                    result = "Not run: no lookups left for this question."
                elif key in seen:
                    result = "You already ran this exact lookup; its result is above."
                else:
                    label = assistant_tools.describe(name, args)
                    yield {"type": "step", "label": label, "running": True}
                    result, refs = assistant_tools.run_tool(tool_ctx, name, args)
                    lookups += 1
                    seen[key] = True
                    for ref in refs:
                        pool.setdefault(ref["id"], ref)
                    if name == "open_record" and refs:
                        opened.append(refs[0]["id"])
                        label = assistant_tools.describe(name, {"_label": refs[0]["label"].split(": ", 1)[-1]})
                    elif name == "network" and refs:
                        label = assistant_tools.describe(name, {**args, "_label": refs[0]["label"].split(": ", 1)[-1]})
                    step = {"tool": name, "label": label,
                            "summary": _clip(assistant_tools.summarize(name, result, refs), 160)}
                    steps.append(step)
                    yield {"type": "step", **step}
                messages.append({"role": "tool", "tool_name": name, "content": _clip(result, per_result)})
            continue

        answer = (resp["content"] or "").strip()
        if not answer and empty_retries < 1:
            # Thought, then said nothing: ask once more for the answer itself.
            empty_retries += 1
            messages.append({"role": "user", "content": "Please give your answer now.", "_nudge": True})
            continue
        if not answer:
            answer = "I couldn't put an answer together from what I found. Try asking more narrowly."
        yield finish(answer, _citations(answer, pool, opened), "lookups")
        return
