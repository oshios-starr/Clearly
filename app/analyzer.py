# app/analyzer.py
#
# WHY THIS FILE EXISTS:
# /explain looks at ONE line and fixes ONE line, so a script with 8 bugs needs
# 8 runs. /analyze reads the WHOLE file, finds every problem the program would
# hit (in the order it would hit them), explains each one, and returns exact
# edits. The CLI shows them all, asks once, applies them, and re-runs.
#
# This file reuses the AI clients, the "credit ran out" flag and the email
# alert from llm_client.py, so /explain and /analyze always behave the same.

import json
import logging
import os
import re
import time

from google.genai import types
from openai import APIStatusError

from app import llm_client as base
from app.config import GEMINI_MODEL, LLM_MODEL
from app.models import AnalyzeRequest, AnalyzeResponse, Problem

# Fail loudly at startup (with a clear message) if llm_client.py doesn't have
# the names this file borrows from it, instead of failing on the first request.
for _name in ("openrouter_client", "gemini_client", "_primary_exhausted",
              "_alert_sent", "_send_fallback_alert", "MAX_RETRIES"):
    if not hasattr(base, _name):
        raise ImportError(f"app/llm_client.py has no '{_name}', which app/analyzer.py needs")

log = logging.getLogger("clearly.analyzer")

# How much of the file the model gets to see. Whole file when it fits; otherwise
# a window around the crash. These caps also protect your credit from someone
# sending a 5 MB file.
MAX_LINES = int(os.getenv("ANALYZE_MAX_LINES", "500"))
MAX_CHARS = int(os.getenv("ANALYZE_MAX_CHARS", "40000"))
LINE_CAP = 400            # one absurdly long line (minified code) is cut here
MAX_PROBLEMS = 12
MAX_OUTPUT_TOKENS = 4000  # a list of 8-12 problems needs far more than the old 800

OPS = ("replace", "insert_before", "delete", "none")

ANALYZE_SYSTEM_PROMPT = """You are Clearly, a debugging assistant for developers.

A program just crashed. You get the error, the stack trace and the source file with line numbers. Your job: find EVERY problem in this file that would stop the program from running, not only the one that crashed first, so the developer can fix them all in one go. Submit them with the submit_analysis tool.

HOW TO WORK
1. The reported crash is ground truth. problems[0] must be that crash.
2. Then read the rest of the file the way the interpreter would, top to bottom, assuming every earlier problem is already fixed. Each further statement that would raise an error is another problem. Trace real values using the data the file itself defines: an empty list, a missing dictionary key, a list that is too short, a string that is not a number, a name that is never defined or imported, a method the type does not have, a call with wrong arguments or types, division by zero.
3. List crashes in the order they would happen when the program runs.
4. Report only what you can justify from the code you can see. If something depends on code or data you cannot see, leave it out, or include it with confidence "low".
5. Never change behaviour that may be intentional: thresholds, formulas, business rules, wording of output. If something looks wrong but would not raise an error, you may add at most 2 problems with kind "logic" and op "none" (one-sentence explanation, no code change).
6. If the file has no other problems, return only the reported crash.
7. At most 12 problems.
8. Typical culprits. Python: NameError (typos, missing imports), TypeError (mixing types), AttributeError (a method the type does not have), KeyError, IndexError, ValueError (bad conversion), ZeroDivisionError, IndentationError. JavaScript: reading a property of undefined or null, calling something that is not a function, a missing await, reassigning a const, a wrong require/import path, an undefined variable.

EACH PROBLEM
- title: at most 8 words, plain English.
- explanation: 1 to 3 short sentences, plain English: what went wrong and why, using the real names from the code.
- line / end_line: 1-based line numbers from the listing. end_line = line unless the fix replaces or deletes several lines in a row.
- op: how to fix it.
    replace        lines line..end_line are replaced by `new` (which may be several lines)
    insert_before  `new` is inserted above `line`
    delete         lines line..end_line are removed
    none           no code change makes sense (a package must be installed, a file is missing, ...). Say what to do in the explanation.
- old: the exact current text of lines line..end_line, copied character for character. For insert_before it is the text of the line you are inserting above. Do NOT include the "N |" line-number prefix or the arrow marker. null when op is none.
- new: the replacement or inserted code with correct indentation, several lines separated by newlines. null for delete and none.
- confidence: "high" only when you are sure the fix is right.
- needs_decision: true when several reasonable fixes exist and you had to pick one (for example what an empty list should average to, or what to do when a key is missing). Pick the safest, most conservative default and say in decision_note, in one sentence, what you chose and what the alternative is. Otherwise false, and decision_note is null.

RULES FOR EDITS
- Make the smallest change that really fixes the problem and match the file's style.
- Two problems must never edit the same line.
- Do not hide an error (no bare "except: pass", no deleting code just to silence it) unless that is clearly the right fix.
- Do not rewrite or reformat code that is not broken.

EXAMPLE of insert_before: a guard against an empty list. The listing shows line 15 as "    return sum(scores) / len(scores)". The problem has line 15, end_line 15, op insert_before, old "    return sum(scores) / len(scores)" and new = the two lines "    if not scores:" and "        return 0.0"."""

# What the model must send back, for the OpenRouter (tool call) path...
ANALYZE_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_analysis",
        "description": "Submit every problem found in the file, in the order the program would hit them.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "One sentence overview."},
                "problems": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "line": {"type": "integer"},
                            "end_line": {"type": "integer"},
                            "kind": {"type": "string", "enum": ["crash", "logic"]},
                            "title": {"type": "string"},
                            "explanation": {"type": "string"},
                            "op": {"type": "string", "enum": list(OPS)},
                            "old": {"type": ["string", "null"]},
                            "new": {"type": ["string", "null"]},
                            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                            "needs_decision": {"type": "boolean"},
                            "decision_note": {"type": ["string", "null"]},
                        },
                        "required": ["line", "end_line", "kind", "title", "explanation",
                                     "op", "confidence", "needs_decision"],
                    },
                },
            },
            "required": ["summary", "problems"],
        },
    },
}


def _gemini_dialect(schema):
    """The same schema in Gemini's dialect: UPPERCASE types and a `nullable` flag."""
    if not isinstance(schema, dict):
        return schema
    out = {}
    for key, value in schema.items():
        if key == "description":
            continue
        if key == "type" and isinstance(value, list):  # ["string", "null"]
            out["type"] = next(t for t in value if t != "null").upper()
            out["nullable"] = True
        elif key == "type":
            out["type"] = value.upper()
        elif key == "properties":
            out[key] = {name: _gemini_dialect(sub) for name, sub in value.items()}
        elif key == "items":
            out[key] = _gemini_dialect(value)
        else:  # enum, required
            out[key] = value
    return out


# ...and for the Gemini fallback (schema-enforced JSON): derived, so the two never drift apart.
GEMINI_SCHEMA = _gemini_dialect(ANALYZE_TOOL["function"]["parameters"])


# ----------------------------------------------------------------------------
# Step 1: show the model the file, with line numbers
# ----------------------------------------------------------------------------

# Same line-splitting rule Python itself uses (\n, \r\n or lone \r), so our line
# numbers always match the numbers in the traceback. The CLI uses the same rule.
_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+")


def split_lines(text):
    return _LINE_RE.findall(text)


def _cost(line):
    return min(len(line), LINE_CAP) + 10


def _select_window(lines_text, center):
    """Whole file if it fits the budget, otherwise a window around the crash."""
    total = len(lines_text)
    if total == 0:
        return 0, 0
    if total <= MAX_LINES and sum(_cost(s) for s in lines_text) <= MAX_CHARS:
        return 0, total
    lo = hi = max(0, min(center, total - 1))
    used = _cost(lines_text[lo])
    while hi - lo + 1 < MAX_LINES:
        grew = False
        if lo > 0 and used + _cost(lines_text[lo - 1]) <= MAX_CHARS:
            lo -= 1
            used += _cost(lines_text[lo])
            grew = True
        if hi < total - 1 and hi - lo + 1 < MAX_LINES and used + _cost(lines_text[hi + 1]) <= MAX_CHARS:
            hi += 1
            used += _cost(lines_text[hi])
            grew = True
        if not grew:
            break
    return lo, hi + 1


def _number_lines(lines_text, lo, hi, crash_line):
    width = len(str(max(hi, 1)))
    out = []
    for i in range(lo, hi):
        text = lines_text[i]
        if len(text) > LINE_CAP:
            text = text[:LINE_CAP] + " ...[line cut]"
        marker = "→" if i + 1 == crash_line else " "
        out.append(f"{marker} {i + 1:>{width}} | {text}")
    return "\n".join(out)


def build_prompt(request, lines_text):
    crash_line = min(request.error_line, max(len(lines_text), 1))
    lo, hi = _select_window(lines_text, crash_line - 1)
    scope = "the whole file" if (lo == 0 and hi == len(lines_text)) else f"lines {lo + 1}-{hi} of {len(lines_text)} only"
    parts = [f"Language: {request.language}", f"Reported error: {request.error_message}"]
    if request.stack_trace:
        parts.append("Stack trace:\n" + request.stack_trace[-4000:])
    parts.append(f"The reported crash is at line {crash_line} (marked with an arrow).")
    parts.append(
        f"Source file ({scope}). The 'N |' prefix is a line number for reference; it is not part of the code:\n"
        + _number_lines(lines_text, lo, hi, crash_line)
    )
    return "\n\n".join(parts)


# ----------------------------------------------------------------------------
# Step 2: call the model (OpenRouter first, Gemini as the safety net)
# ----------------------------------------------------------------------------

def _call_primary(user_message):
    response = base.openrouter_client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        timeout=90,  # seconds for this one attempt; a long list takes longer than a one-line fix
        messages=[
            {"role": "system", "content": ANALYZE_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        tools=[ANALYZE_TOOL],
        tool_choice={"type": "function", "function": {"name": "submit_analysis"}},
    )
    choice = response.choices[0]
    if choice.finish_reason == "length":
        raise ValueError("The AI ran out of room before finishing its answer.")
    calls = choice.message.tool_calls
    if not calls:
        raise ValueError("The AI did not return a structured answer.")
    return json.loads(calls[0].function.arguments)


def _call_gemini(user_message):
    response = base.gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=ANALYZE_SYSTEM_PROMPT,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
            response_schema=GEMINI_SCHEMA,
        ),
    )
    try:
        return json.loads(response.text)
    except (TypeError, ValueError):
        raise ValueError("The AI returned something that was not valid JSON.")


def _ask_model(user_message):
    """Same fallback rules as get_explanation() in llm_client.py."""
    if not base._primary_exhausted:
        for attempt in range(1, base.MAX_RETRIES + 1):
            try:
                return _call_primary(user_message)
            except APIStatusError as e:
                if e.status_code == 402:  # credit is gone: stop trying, tell the owner once
                    base._primary_exhausted = True
                    if not base._alert_sent:
                        base._send_fallback_alert("OpenRouter credit exhausted (HTTP 402)")
                        base._alert_sent = True
                    break
                log.warning("primary attempt %s failed: HTTP %s", attempt, e.status_code)
            except Exception as e:  # network blip, bad JSON, truncated answer...
                log.warning("primary attempt %s failed: %s", attempt, e)
            if attempt < base.MAX_RETRIES:
                time.sleep(attempt)  # back off 1s, 2s between attempts
    return _call_gemini(user_message)


# ----------------------------------------------------------------------------
# Step 3: don't trust the model's line numbers or quoting; check them against
# the real file and repair what can be repaired
# ----------------------------------------------------------------------------

_PREFIX_RE = re.compile(r"^[ →]*\d+ \| ?")


def _ws(s):
    return " ".join(s.split())


def _text(value, limit):
    if not isinstance(value, str):
        return ""
    return value.replace('\\"', '"').strip()[:limit]


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _bool(value):
    if isinstance(value, str):  # some models send "true" / "false" as text
        return value.strip().lower() in ("true", "yes", "1")
    return bool(value)


def _code(value):
    """Normalise a code snippet from the model: \\n newlines, no trailing newline."""
    if not isinstance(value, str):
        return None
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if value.endswith("\n"):
        value = value[:-1]
    return value


def _variants(old):
    """The ways the model may have mangled `old`: as-is, with the 'N |' prefix, with \\" escapes."""
    lines = old.split("\n")
    out = [(lines, False)]
    if all(_PREFIX_RE.match(l) for l in lines):
        out.append(([_PREFIX_RE.sub("", l, count=1) for l in lines], False))
    for ls, _ in list(out):
        if any('\\"' in l for l in ls):
            out.append(([l.replace('\\"', '"') for l in ls], True))
    return out


def _find(old_lines, hint, lines_text):
    """0-based index where old_lines occur (ignoring whitespace differences), or None."""
    target = [_ws(l) for l in old_lines]
    if not any(target):
        return None
    n = len(target)
    norm = [_ws(l) for l in lines_text]
    if 0 <= hint <= len(norm) - n and norm[hint:hint + n] == target:
        return hint
    hits = [i for i in range(len(norm) - n + 1) if norm[i:i + n] == target]
    if not hits:
        return None
    hits.sort(key=lambda i: abs(i - hint))
    if len(hits) == 1 or abs(hits[0] - hint) < abs(hits[1] - hint):
        return hits[0]
    return None  # several equally good places: refuse to guess


def _locate_edit(problem, old_raw, new_raw, lines_text):
    """Return the verified edit fields, or None if it can't be placed safely."""
    op = problem["op"]
    old, new = _code(old_raw), _code(new_raw)
    if old is None or not old.strip():
        return None
    if op in ("replace", "insert_before") and (new is None or not new.strip()):
        return None
    hint = max(problem["line"] - 1, 0)
    for old_lines, unescaped in _variants(old):
        idx = _find(old_lines, hint, lines_text)
        if idx is None:
            continue
        n = len(old_lines)
        if op == "insert_before":
            n = 1  # the anchor is just the line we insert above
        actual = "\n".join(lines_text[idx:idx + n])
        if new is not None and unescaped:
            new = new.replace('\\"', '"')
        if op == "replace" and [l.rstrip() for l in new.split("\n")] == [l.rstrip() for l in actual.split("\n")]:
            return None  # "fix" that changes nothing
        return {"line": idx + 1, "end_line": idx + n, "old": actual,
                "new": None if op == "delete" else new}
    return None


def _clean_problem(raw, lines_text):
    if not isinstance(raw, dict):
        return None
    p = {
        "kind": "logic" if str(raw.get("kind", "")).lower() == "logic" else "crash",
        "title": _text(raw.get("title"), 80) or "Problem",
        "explanation": _text(raw.get("explanation"), 700),
        "op": str(raw.get("op", "none")).strip().lower(),
        "confidence": str(raw.get("confidence", "medium")).strip().lower(),
        "needs_decision": _bool(raw.get("needs_decision")),
        "decision_note": _text(raw.get("decision_note"), 300) or None,
        "line": _int(raw.get("line")),
        "end_line": _int(raw.get("end_line")),
        "old": None,
        "new": None,
    }
    if not p["explanation"]:
        return None  # nothing useful to tell the developer
    if not 1 <= p["line"] <= len(lines_text):
        p["line"] = p["end_line"] = 0  # not tied to a real line
    if p["op"] not in OPS:
        p["op"] = "none"
    if p["confidence"] not in ("high", "medium", "low"):
        p["confidence"] = "medium"

    if p["op"] != "none":
        located = _locate_edit(p, raw.get("old"), raw.get("new"), lines_text)
        if located:
            p.update(located)
        else:
            # Couldn't place it safely. Keep the explanation (the developer still
            # learns the cause) and keep the suggested code as text only.
            p["op"] = "none"
            p["new"] = _code(raw.get("new"))
    if p["kind"] == "logic" or p["confidence"] == "low":
        p["needs_decision"] = True
    return p


def sanitize(raw, lines_text):
    problems = []
    for item in (raw.get("problems") or [])[:MAX_PROBLEMS]:
        cleaned = _clean_problem(item, lines_text)
        if cleaned:
            problems.append(Problem(**cleaned))
    summary = _text(raw.get("summary"), 300)
    if not summary:
        summary = f"Found {len(problems)} problem{'s' if len(problems) != 1 else ''}."
    return AnalyzeResponse(summary=summary, problems=problems)


# ----------------------------------------------------------------------------
# The one function main.py calls
# ----------------------------------------------------------------------------

def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    lines_text = [l.rstrip("\r\n") for l in split_lines(request.file_content)]
    raw = _ask_model(build_prompt(request, lines_text))
    return sanitize(raw, lines_text)