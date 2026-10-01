# app/prompt_builder.py
#
# WHY THIS FILE EXISTS:
# A raw "explain this error" prompt gives you inconsistent, prose-y answers
# that are hard to parse back into your structured ExplainResponse model.
# This file's job is to build a prompt that (1) gives the model everything
# it needs and nothing it doesn't, and (2) forces a predictable, parseable
# output format every time.

from app.models import ExplainRequest


# This is the SYSTEM prompt — it sets the model's role and output format
# once, separately from the actual error data. Keeping instructions and
# data separate (rather than jamming everything into one message) is a
# core prompting best practice: it makes the model far less likely to
# get confused about what's an instruction versus what's the user's code.
SYSTEM_PROMPT = """You are Clearly, an expert debugging assistant embedded \
directly in a developer's editor. A developer just hit an error. You will \
be given the error message, optionally a stack trace, and the actual code \
surrounding the line where it happened, with the exact error line marked.

Your job: explain in plain English WHY this specific error happened in \
THIS specific code (not a generic explanation of what this error class \
usually means), then suggest a concrete fix.

Respond with ONLY a JSON object in exactly this shape, and nothing else \
— no markdown code fences, no preamble, no closing remarks:

{
  "explanation": "why this happened, referencing the actual variable names and code shown",
  "fix_suggestion": "a specific, actionable fix for this exact code, in words",
  "confidence": "high" | "medium" | "low",
  "fixed_line": "the exact corrected replacement for the single error line, with correct indentation — OR null if the real fix needs more than one line changed"
}

IMPORTANT rules for fixed_line specifically:
- Only provide fixed_line if the ENTIRE fix fits by replacing that one \
line, with no other lines needing to change.
- Match the original line's indentation exactly.
- If the real fix requires adding a new line, changing a different line, \
or restructuring logic, set fixed_line to null — do NOT force a one-line \
fix onto a problem that needs more than that. An honest null is far \
better than a fix that looks plausible but breaks something else.

Set confidence to "low" if the code context given isn't enough to be sure \
of the root cause — an honest low-confidence answer is more useful to a \
developer than a confident-sounding guess."""


def build_prompt(request: ExplainRequest, code_context: str) -> str:
    """
    Combines the error details and extracted code context into the
    single user-turn message sent to the model. The SYSTEM_PROMPT above
    stays constant across every request; this function only builds the
    part that changes per-request.
    """

    # We build this as a list of lines then join them, rather than one
    # giant f-string, purely for readability — it's much easier to see
    # the structure of what's being sent to the model this way, which
    # matters a lot when you're debugging prompt quality later.
    parts = [
        f"Language: {request.language}",
        f"Error message: {request.error_message}",
    ]

    # stack_trace is optional (Optional[str] in the model), so we only
    # include this section if it was actually provided — an empty
    # "Stack trace: None" line in the prompt wastes tokens and can
    # confuse the model into thinking something is missing.
    if request.stack_trace:
        parts.append(f"Stack trace:\n{request.stack_trace}")

    # This is the payoff of context_extractor.py — the actual local code,
    # with the error line marked, gets dropped directly into the prompt.
    parts.append(f"Code context (→ marks the error line):\n{code_context}")

    # Join every section with a blank line between them for readability
    # in the final prompt — this doesn't affect the model's understanding
    # much, but makes the prompt much easier for YOU to read when
    # debugging, which you will do a lot in the first few weeks.
    return "\n\n".join(parts)