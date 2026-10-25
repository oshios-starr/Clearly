# app/models.py
#
# WHY THIS FILE EXISTS:
# FastAPI uses Pydantic models to (1) validate incoming requests automatically
# — if the VS Code extension sends malformed data, FastAPI rejects it with a
# clear error before your code ever runs — and (2) auto-generate API docs at
# /docs, which is genuinely useful when you're testing this alone before the
# extension exists yet.

from pydantic import BaseModel, Field
from typing import Optional


class ExplainRequest(BaseModel):
    """
    This is exactly what the VS Code extension / CLI will send you.
    Nothing more, nothing less — keeping this minimal for the MVP means
    less that can go wrong while you validate the core idea.
    """

    # The raw error message, e.g. "TypeError: 'NoneType' object is not subscriptable"
    error_message: str

    # The full stack trace if available. Optional because a CLI wrapper
    # might only capture stderr text, not a structured trace, in v1.
    stack_trace: Optional[str] = None

    # The full source code of the file where the error happened.
    # The client reads this off the user's disk — your backend never does.
    file_content: str

    # 1-indexed line number where the error occurred (matches how editors
    # and stack traces normally report line numbers, so no off-by-one
    # translation is needed on either side of the API call).
    error_line: int = Field(gt=0, description="Must be a positive line number")

    # Which language this is, so the prompt can be tuned per-language later.
    # Defaulting to python since that's your first supported language.
    language: str = "python"


class ExplainResponse(BaseModel):
    """
    What you send back. Keeping this structured (not just one long string
    of prose) matters a lot: the VS Code extension needs to put the
    explanation in one UI element and the fix in a separate "Apply Fix"
    button — it can't do that if the model just returns a paragraph.
    """

    # Plain-English explanation of *why* the error happened.
    explanation: str

    # A concrete suggested fix, described in words.
    fix_suggestion: str

    # Optional confidence signal. Not every explanation will be equally
    # certain — surfacing that honestly is better than a wrong answer
    # presented with false confidence.
    confidence: Optional[str] = None

    # The exact corrected replacement for the single line at error_line —
    # only set when the fix genuinely fits on that one line. Left as None
    # when the real fix needs more than one line changed (e.g. adding a
    # new function, restructuring logic) — auto-applying a fix that
    # doesn't fit on one line is how you corrupt someone's file, so we
    # deliberately don't attempt it.
    fixed_line: Optional[str] = None
    # ---------------------------------------------------------------------------
# /analyze: find and fix EVERY problem in the file in one run
# (paste this at the bottom of app/models.py; the imports at the top of the
#  file already cover BaseModel, Field and Optional)
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    """Same inputs as /explain. The CLI now sends the whole file."""

    error_message: str
    stack_trace: Optional[str] = None
    file_content: str
    error_line: int = Field(gt=0, description="Must be a positive line number")
    language: str = "python"


class Problem(BaseModel):
    """One thing wrong in the file, with the exact edit that fixes it."""

    # 1-based lines this problem's edit touches (0 = not tied to a line).
    line: int = 0
    end_line: int = 0

    # "crash" = the program would stop here. "logic" = looks wrong but wouldn't crash.
    kind: str = "crash"

    title: str
    explanation: str  # plain English: what went wrong and why

    # replace | insert_before | delete | none
    # If op is "none" and `new` is set, `new` is only a suggestion, not an edit.
    op: str = "none"
    old: Optional[str] = None  # exact current text of lines line..end_line
    new: Optional[str] = None  # replacement text, or the text to insert

    confidence: str = "medium"  # high | medium | low

    # True when there were several reasonable fixes and one was picked for you.
    needs_decision: bool = False
    decision_note: Optional[str] = None


class AnalyzeResponse(BaseModel):
    summary: str
    problems: list[Problem]