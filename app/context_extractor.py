# app/context_extractor.py
#
# WHY THIS FILE EXISTS — AND WHY IT'S THE MOST IMPORTANT FILE IN THE PROJECT:
# The entire pitch of "Clearly" versus pasting an error into ChatGPT is that
# Clearly automatically gathers the *relevant local code context* instead of
# making the developer manually copy-paste it. This file is where that
# actually happens. Right now it's a simple line-window approach (v1) —
# the note at the bottom explains the upgrade path to real AST-based
# parsing (tree-sitter) once you validate the simple version works.

from app.config import CONTEXT_WINDOW_LINES


def get_code_context(file_content: str, error_line: int, window: int = CONTEXT_WINDOW_LINES) -> str:
    """
    Given the full text of a file and the line number where an error
    occurred, return a chunk of that file centered on the error, with
    line numbers attached so the model can refer to specific lines
    when it explains the problem.

    Args:
        file_content: the entire source file as one string
        error_line: 1-indexed line number where the error happened
        window: how many lines to include above AND below the error line

    Returns:
        A string like:
            12: def process_order(order):
            13:     total = 0
        →   14:     for item in order.items:
            15:         total += item.price
            16:     return total
        (the → marks the actual error line so the model can't miss it)
    """

    # .splitlines() breaks the file into a list of individual lines,
    # e.g. "a\nb\nc" becomes ["a", "b", "c"]. We need this as a list
    # so we can slice out just the window we want, not the whole file —
    # sending the whole file on every request would waste tokens (money)
    # and slow down every single API call.
    lines = file_content.splitlines()

    # Convert the 1-indexed error_line (how humans and stack traces count)
    # into a 0-indexed position (how Python lists count). Line 14 to a
    # human is index 13 in the list. Getting this wrong is an easy,
    # silent bug — the model would explain the wrong line entirely.
    error_index = error_line - 1

    # Clamp the start of our window so it never goes below 0 (the start
    # of the file). Without max(), an error on line 3 with a window of 10
    # would try to start at index -7, which in Python silently wraps
    # around to the END of the list — a genuinely nasty bug to debug later.
    start = max(0, error_index - window)

    # Clamp the end of our window so it never goes past the last line
    # of the file. min() here prevents an IndexError-adjacent situation
    # when the error is near the end of a short file.
    end = min(len(lines), error_index + window + 1)

    # Build the output line by line, so we can prefix each with its real
    # line number (start=start means our loop's line numbers match the
    # file's actual numbering, not restart from 0).
    context_lines = []
    for i, line in enumerate(lines[start:end], start=start):
        # Convert back to 1-indexed for display, since that's what the
        # error_line the user gave us was in, and what a human expects.
        line_number = i + 1

        # Mark the exact error line with an arrow so the model's
        # attention is drawn to precisely the right spot, not just
        # "somewhere in this block of code."
        marker = "→" if line_number == error_line else " "

        context_lines.append(f"{marker} {line_number}: {line}")

    # Join everything back into one string with real newlines — this is
    # what gets embedded into the prompt in prompt_builder.py.
    return "\n".join(context_lines)


# UPGRADE PATH (don't build this yet — note it for Phase 2):
# This line-window approach works fine for simple errors but has an
# obvious limitation: it might cut a function off mid-way, or miss a
# variable definition that's outside the window but still relevant.
# The real fix is parsing the file into an Abstract Syntax Tree (AST)
# with a library like `tree-sitter`, so you can extract the FULL
# enclosing function (not just N lines) plus relevant imports —
# structurally correct context instead of a guessed window. Build
# this once you have real eval data showing the line-window approach
# is actually limiting explanation quality — don't build it speculatively.