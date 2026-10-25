#!/usr/bin/env python3
# cli.py
#
# Clearly: runs your script. If it crashes, Clearly reads the WHOLE file, explains
# EVERY problem it finds, and, after one OK from you, fixes them all in one run.
#
#   clearly yourfile.py
#
# Safety rules (the AI never has the last word):
#   - nothing changes until you say yes (all at once, or one by one)
#   - every edit is checked against the real file first; mismatches are dropped
#   - the original is saved as yourfile.py.bak before the first change
#   - the edited file must still parse; edits that would break it are dropped
#   - the script is re-run so you see the real result, not a guess

import codecs
import locale
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import textwrap
import threading
from urllib.parse import unquote, urlparse

import requests

BASE_URL = os.environ.get("CLEARLY_BACKEND_URL", "https://clearly-2176.onrender.com").rstrip("/")
ANALYZE_URL = BASE_URL + "/analyze"
HEALTH_URL = BASE_URL + "/health"

MAX_ROUNDS = 3  # "fix, re-run, hit a new error" is allowed this many times in one run
EDIT_OPS = ("replace", "insert_before", "delete")


# ----------------------------------------------------------------------------
# Output helpers
# ----------------------------------------------------------------------------

USE_COLOR = False


def _enable_color():
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if os.name == "nt":  # Windows consoles need ANSI colours switched on
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
        except Exception:
            return False
    return True


def _paint(code, text):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def bold(t): return _paint("1", t)
def dim(t): return _paint("2", t)
def red(t): return _paint("31", t)
def green(t): return _paint("32", t)
def yellow(t): return _paint("33", t)


def say(text=""):
    print(text, flush=True)


def wrap(text, indent):
    width = max(60, min(shutil.get_terminal_size((100, 24)).columns - 2, 100))
    pad = " " * indent
    return textwrap.fill(text, width=width, initial_indent=pad, subsequent_indent=pad)


def show_path(path):
    try:
        return os.path.relpath(path)
    except ValueError:  # different drive on Windows
        return path


# ----------------------------------------------------------------------------
# Running your script
# ----------------------------------------------------------------------------

def _same_folder(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _python_works(python):
    try:
        return subprocess.run([python, "-c", "pass"], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False  # e.g. the Windows Store "python" shortcut when Python isn't installed from the Store


def find_python():
    """The Python that should run YOUR script.

    Normally that is the Python Clearly itself runs on. But when Clearly was installed with pipx
    (or uv tool) it lives in a private environment that has none of your packages, so a script
    that imports flask, numpy, requests... would fail there although it runs fine for you.
    In that case use the `python` your terminal would run. Activating a virtual environment puts
    its python first on PATH, so your project's environment wins."""
    in_venv = sys.prefix != sys.base_prefix
    active = os.environ.get("VIRTUAL_ENV")
    if in_venv and not (active and _same_folder(active, sys.prefix)):
        for name in ("python", "python3"):
            found = shutil.which(name)
            if found and _python_works(found):
                return found
    return sys.executable


# The Python that runs your script and where ITS standard library lives. The second part is
# only looked up (once, after a crash) when that Python is not the one Clearly runs on.
_target = {"python": None, "stdlib": None}


def _probe_stdlib(python):
    """Ask that Python where its standard library is, so its frames aren't mistaken for your code."""
    code = "import sysconfig; p = sysconfig.get_paths(); print(p.get('stdlib')); print(p.get('platstdlib'))"
    try:
        r = subprocess.run([python, "-c", code], capture_output=True, timeout=15,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    return [l.strip() for l in r.stdout.decode("utf-8", "replace").splitlines() if l.strip() not in ("", "None")]


def _stdlib_roots():
    roots = [sysconfig.get_paths().get(key) for key in ("stdlib", "platstdlib")]
    python = _target["python"]
    if python and python != sys.executable:
        if _target["stdlib"] is None:
            _target["stdlib"] = _probe_stdlib(python)
        roots += _target["stdlib"]
    return roots


def get_language_and_runner(script_path):
    ext = os.path.splitext(script_path)[1].lower()
    if ext == ".py":
        python = find_python()
        _target["python"], _target["stdlib"] = python, None
        return "python", [python, script_path]
    elif ext == ".js":
        return "javascript", ["node", script_path]
    return None, None


def run_target_script(runner_command):
    """stdout/stdin are inherited (so prompts and prints show live); only stderr is
    piped, echoed live, and captured so Clearly can read the error."""
    sys.stdout.flush()
    proc = subprocess.Popen(runner_command, stderr=subprocess.PIPE)
    chunks = []

    def pump():
        decoder = codecs.getincrementaldecoder(locale.getpreferredencoding(False) or "utf-8")(errors="replace")
        while True:
            data = proc.stderr.read1(4096)
            if not data:
                break
            text = decoder.decode(data)
            chunks.append(text)
            sys.stderr.write(text)
            sys.stderr.flush()
        tail = decoder.decode(b"", final=True)
        if tail:
            chunks.append(tail)
            sys.stderr.write(tail)
            sys.stderr.flush()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        returncode = proc.wait()
    except KeyboardInterrupt:
        try:
            returncode = proc.wait(timeout=5)
        except Exception:
            proc.kill()
            returncode = 130
    reader.join(timeout=5)
    return returncode, "".join(chunks)


# ----------------------------------------------------------------------------
# Reading the error
# ----------------------------------------------------------------------------

def _is_user_file(path):
    """True for your own code; False for libraries, the standard library and <frozen> stubs."""
    low = path.replace("\\", "/").lower()
    if low.startswith("<") or "site-packages" in low or "dist-packages" in low:
        return False
    for root in _stdlib_roots():
        root = (root or "").replace("\\", "/").lower().rstrip("/")
        if root and low.startswith(root + "/"):
            return False
    return os.path.isfile(path)


def parse_python_traceback(stderr_text):
    frames = re.findall(r'File "(.+?)", line (\d+)', stderr_text)
    if not frames:
        return None, None, None
    # The deepest frame is often inside a library; the bug is in the deepest frame of YOUR code.
    chosen = next(((p, int(n)) for p, n in reversed(frames) if _is_user_file(p)),
                  (frames[-1][0], int(frames[-1][1])))
    lines = [l for l in stderr_text.strip().splitlines() if l.strip()]
    return chosen[0], chosen[1], (lines[-1].strip() if lines else "Unknown error")


def _file_url_to_path(path):
    if path.startswith("file://"):
        path = unquote(urlparse(path).path)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
    return path


def parse_node_traceback(stderr_text):
    error_message = None
    for line in stderr_text.splitlines():
        m = re.match(r"^(\w+Error):\s*(.+)$", line.strip())
        if m:
            error_message = f"{m.group(1)}: {m.group(2)}"
            break
    frame_re = re.compile(r"^\s*at\s+(?:.*\()?(.+):(\d+):(\d+)\)?\s*$")
    for line in stderr_text.splitlines():
        m = frame_re.match(line)
        if not m:
            continue
        path = _file_url_to_path(m.group(1))
        if path.startswith("node:") or "node_modules" in path.replace("\\", "/"):
            continue
        if os.path.isfile(path):
            return path, int(m.group(2)), error_message or "Unknown error"
    # Syntax errors have no "at" frames; Node prints "/path/file.js:12" on top instead.
    for line in stderr_text.splitlines():
        m = re.match(r"^(.+):(\d+)$", line.strip())
        if m and os.path.isfile(_file_url_to_path(m.group(1))):
            return _file_url_to_path(m.group(1)), int(m.group(2)), error_message or "SyntaxError"
    return None, None, None


def parse_traceback(language, stderr_text):
    if language == "python":
        return parse_python_traceback(stderr_text)
    return parse_node_traceback(stderr_text)


# ----------------------------------------------------------------------------
# The file on disk, split the way Python counts lines
# ----------------------------------------------------------------------------

_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+")  # same rule as the server


class SourceFile:
    """Each line keeps its own line ending, so a rewrite touches only edited lines."""

    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            raw = f.read()
        self.bom = raw.startswith(b"\xef\xbb\xbf")
        self.lines = _LINE_RE.findall((raw[3:] if self.bom else raw).decode("utf-8"))

    @property
    def text(self):
        return "".join(self.lines)

    @property
    def plain(self):
        return [l.rstrip("\r\n") for l in self.lines]

    @property
    def newline(self):
        for l in self.lines:
            for ending in ("\r\n", "\n", "\r"):
                if l.endswith(ending):
                    return ending
        return "\n"


def _ending(line):
    return line[len(line.rstrip("\r\n")):]


# ----------------------------------------------------------------------------
# Checking the AI's edits against the real file, then applying them
# ----------------------------------------------------------------------------

def _same(a, b):
    return " ".join(a.split()) == " ".join(b.split())


def verify_edit(p, plain):
    """None if this edit is safe for the file as it is right now; otherwise the reason it isn't."""
    op = p.get("op")
    line = p.get("line") or 0
    end = line if op == "insert_before" else (p.get("end_line") or 0)
    old = p.get("old")
    if old is None:
        return "Clearly didn't quote the original text"
    old_lines = old.split("\n")
    n = len(old_lines)
    if not (1 <= line <= end) or line - 1 + n > len(plain):
        return "the line number is outside the file"
    if op != "insert_before" and n != end - line + 1:
        return "the line range doesn't match the quoted text"
    if not _same("\n".join(plain[line - 1:line - 1 + n]), old):
        return "the file changed since Clearly read it"
    if op in ("replace", "insert_before") and not (p.get("new") or "").strip():
        return "no new code was given"
    return None


def _span(p):
    line = p["line"]
    return (line, line, True) if p["op"] == "insert_before" else (line, p["end_line"], False)


def _conflict(a, b):
    (s1, e1, ins1), (s2, e2, ins2) = a, b
    if ins1 and ins2:
        return False
    if ins1:
        return s2 < s1 <= e2  # inserting above the first line of a replaced block is fine
    if ins2:
        return s1 < s2 <= e1
    return s1 <= e2 and s2 <= e1


def pick_applicable(chosen, plain):
    """Keep the verified, non-overlapping edits (earlier problems win). Returns (edits, skipped)."""
    edits, skipped = [], []
    for p in chosen:
        reason = verify_edit(p, plain)
        if reason is None:
            clash = next((q for q in edits if _conflict(_span(p), _span(q))), None)
            if clash:
                reason = f"it overlaps with '{clash['title']}'"
        if reason:
            skipped.append((p, reason))
        else:
            edits.append(p)
    return edits, skipped


def apply_edits(lines, edits, newline):
    """Build the new list of lines in one forward pass (so line numbers never drift)."""
    inserts, ranges = {}, {}
    for p in edits:
        if p["op"] == "insert_before":
            inserts.setdefault(p["line"], []).append(p)
        else:
            ranges[p["line"]] = p
    out = []
    i = 1
    while i <= len(lines):
        for p in inserts.get(i, []):
            out.extend(t + newline for t in p["new"].split("\n"))
        p = ranges.get(i)
        if p:
            if p["op"] == "replace":
                new_lines = p["new"].split("\n")
                last_ending = _ending(lines[p["end_line"] - 1])  # "" if the file had no final newline
                for k, t in enumerate(new_lines):
                    out.append(t + (newline if k < len(new_lines) - 1 else last_ending))
            i = p["end_line"] + 1
            continue
        out.append(lines[i - 1])
        i += 1
    return out


def _python_syntax_error(text, path):
    try:
        compile(text, path, "exec", dont_inherit=True)
    except SyntaxError as e:
        return f"{e.msg} (line {e.lineno})"
    except Exception as e:
        return str(e) or type(e).__name__
    return None


def _node_syntax_error(text, path):
    node = shutil.which("node")
    if not node:
        return None
    tmp = None
    try:
        # Same folder + same extension, so Node treats it exactly like your file.
        fd, tmp = tempfile.mkstemp(prefix=".clearly-check-", suffix=os.path.splitext(path)[1] or ".js",
                                   dir=os.path.dirname(os.path.abspath(path)))
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
        r = subprocess.run([node, "--check", tmp], capture_output=True, timeout=20)
        if r.returncode == 0:
            return None
        msgs = r.stderr.decode("utf-8", "replace").strip().splitlines()
        return next((m.strip() for m in reversed(msgs) if "Error" in m), "syntax error")
    except Exception:
        return None  # can't check (read-only folder, node missing...): don't block the fix
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def syntax_error(text, path, language):
    if language == "python":
        return _python_syntax_error(text, path)
    if language == "javascript":
        return _node_syntax_error(text, path)
    return None


def make_backup(path, state):
    """One backup per file per run, and never over an older backup."""
    key = os.path.abspath(path)
    if key in state["backups"]:
        return state["backups"][key]
    backup, k = path + ".bak", 2
    while os.path.exists(backup):
        backup = f"{path}.{k}.bak"
        k += 1
    shutil.copy2(path, backup)
    state["backups"][key] = backup
    return backup


def safe_subset(edits, src, language):
    """The edits that keep a file that parses today parseable. Returns (kept, dropped)."""
    if not edits or syntax_error(src.text, src.path, language) is not None:
        # Nothing to protect: if the file ALREADY had a syntax error, the re-run
        # shows what's left and Clearly goes round again.
        return edits, []
    if syntax_error("".join(apply_edits(src.lines, edits, src.newline)), src.path, language) is None:
        return edits, []
    kept, dropped = [], []
    for p in edits:  # something in the set breaks the file: find which edits are to blame
        trial = "".join(apply_edits(src.lines, kept + [p], src.newline))
        (kept if syntax_error(trial, src.path, language) is None else dropped).append(p)
    return kept, dropped


def plan_edits(candidates, src, language):
    """Which of these fixes can really be applied to the file as it is right now?
    Returns (edits, blocked) where blocked is a list of (problem, reason)."""
    edits, blocked = pick_applicable(candidates, src.plain)
    kept, dropped = safe_subset(edits, src, language)
    return kept, blocked + [(p, "it would have broken the file's syntax") for p in dropped]


def apply_to_file(src, chosen, language, state):
    """Re-check everything, back up, write. Returns the edits that were really applied."""
    try:
        if SourceFile(src.path).lines != src.lines:
            say(red(f"{show_path(src.path)} changed while Clearly was working, so nothing was applied. "
                    "Save your file and run Clearly again."))
            return []
    except (OSError, UnicodeDecodeError):
        say(red(f"Clearly couldn't re-read {show_path(src.path)}, so nothing was applied."))
        return []
    edits, blocked = plan_edits(chosen, src, language)
    for p, reason in blocked:
        say(yellow(f"  Skipped '{p['title']}': {reason}."))
    if not edits:
        return []
    new_text = "".join(apply_edits(src.lines, edits, src.newline))
    try:
        make_backup(src.path, state)  # first, so a failed write can never cost you the original
        with open(src.path, "wb") as f:
            f.write((b"\xef\xbb\xbf" if src.bom else b"") + new_text.encode("utf-8"))
    except OSError as e:
        say(red(f"Clearly couldn't save the changes to {show_path(src.path)} ({e.strerror or e})."))
        return []
    return edits


# ----------------------------------------------------------------------------
# Talking to the server
# ----------------------------------------------------------------------------

def wake_server():
    """Render's free tier sleeps after 15 idle minutes; the first request wakes it."""
    try:
        if requests.get(HEALTH_URL, timeout=5).ok:
            return
    except requests.RequestException:
        pass
    say(dim("Waking up Clearly's server (the first request after a quiet spell takes up to a minute)..."))
    try:
        requests.get(HEALTH_URL, timeout=90)
    except requests.RequestException:
        pass


def request_analysis(error_message, stack_trace, file_content, error_line, language, label):
    payload = {
        "error_message": error_message,
        "stack_trace": stack_trace,
        "file_content": file_content,
        "error_line": error_line,
        "language": language,
    }
    say(dim(f"Sending {label} to Clearly's AI to look for every problem (can take up to 30 seconds)..."))
    try:
        r = requests.post(ANALYZE_URL, json=payload, timeout=(10, 150))
    except requests.exceptions.Timeout:
        say(red("Clearly's server took too long to answer. Please try again in a minute."))
        return None
    except requests.exceptions.RequestException:
        say(red("Couldn't reach Clearly's server. Check your internet connection and try again."))
        return None
    if r.status_code == 404:
        say(red("Clearly's server doesn't know this feature yet (it's being updated). Try again in a few minutes."))
        return None
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = None
        say(red(f"Clearly's server returned an error ({r.status_code}). {detail if isinstance(detail, str) else ''}".strip()))
        return None
    try:
        return r.json()
    except ValueError:
        say(red("Clearly's server sent back something unreadable. Please try again."))
        return None


# ----------------------------------------------------------------------------
# Showing the result and asking
# ----------------------------------------------------------------------------

def diff_lines(p):
    op, out = p.get("op"), []
    if op == "insert_before":
        out.append(dim(f"(added above line {p['line']})"))
    if op in ("replace", "delete"):
        out += [red("- " + l) for l in (p.get("old") or "").split("\n")]
    if op in ("replace", "insert_before"):
        out += [green("+ " + l) for l in (p.get("new") or "").split("\n")]
    if op not in EDIT_OPS and p.get("new"):
        out.append(dim("suggested change (not applied automatically):"))
        out += ["  " + l for l in p["new"].split("\n")]
    return out


def show_problem(i, p, label, blocked_reason=None):
    where = dim(f"line {p['line']}") if p.get("line") else ""
    meta = "   ".join(x for x in (where, label) if x)
    say(f" {i}. {bold(p.get('title') or 'Problem')}" + (f"   {meta}" if meta else ""))
    say(wrap(p.get("explanation") or "", 5))
    if p.get("needs_decision") and (p.get("decision_note") or p.get("op") in EDIT_OPS):
        note = p.get("decision_note") or "Clearly picked a default; check it matches what you want."
        say(wrap("⚠ your call: " + note, 5).replace("⚠ your call:", yellow("⚠ your call:"), 1))
    if blocked_reason:
        say(yellow(wrap(f"Not applied automatically: {blocked_reason}. Suggested change:", 5)))
    for l in diff_lines(p):
        say("     " + l)
    if p.get("op") not in EDIT_OPS:
        say(dim("     (no automatic fix for this one)"))
    say()


def ask(prompt):
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return "n"


def review_one_by_one(fixable):
    chosen = []
    for k, p in enumerate(fixable):
        show_problem(p["_n"], p, dim(f"(fix {k + 1} of {len(fixable)})"))
        answer = ask("Apply this fix? [y]es / [n]o / [a]ll the rest / [q]uit: ")
        say()
        if answer in ("a", "all"):
            chosen.extend(fixable[k:])
            break
        if answer in ("q", "quit"):
            break
        if answer in ("y", "yes"):
            chosen.append(p)
    return chosen


def review_and_apply(result, src, language, error_line, state):
    """Show every problem, ask once, apply. Returns how many fixes were applied."""
    problems = result.get("problems") or []
    name = show_path(src.path)
    if not problems:
        say(wrap(result.get("summary") or "Clearly couldn't work out what is wrong here.", 0))
        return 0

    # Check every proposed edit BEFORE asking, so what you approve is exactly what gets applied.
    fixable, blocked = plan_edits([p for p in problems if p.get("op") in EDIT_OPS], src, language)
    why_blocked = {id(p): reason for p, reason in blocked}

    n = len(problems)
    say()
    say(bold(f"Clearly found {n} problem{'s' if n != 1 else ''} in {name}"))
    say()
    reported = next((k for k, p in enumerate(problems) if p.get("line") == error_line and p.get("kind") != "logic"),
                    0 if problems[0].get("kind") != "logic" else None)
    for k, p in enumerate(problems):
        p["_n"] = k + 1  # the number shown in the list, reused when reviewing one by one
        if p.get("kind") == "logic":
            label = dim("heads-up: wouldn't crash")
        elif k == reported:
            label = red("this crashed your script")
        else:
            label = yellow("would crash next")
        show_problem(k + 1, p, label, why_blocked.get(id(p)))

    if not fixable:
        say("Clearly has no safe automatic fix for these, so it changed nothing.")
        return 0
    count = len(fixable)
    judgment = sum(1 for p in fixable if p.get("needs_decision"))
    if count == 1:
        note = " (marked ⚠, please glance at it)" if judgment else ""
    else:
        note = f" ({judgment} marked ⚠, please glance at those)" if judgment else ""
    say(f"{count} fix{'es' if count != 1 else ''} ready{note}.")
    if count == 1:
        answer = ask("Apply this fix? [y]es / [n]o: ")
    else:
        answer = ask(f"Apply all {count}? [y]es / [n]o / [r]eview one by one: ")
    say()
    if answer in ("y", "yes"):
        chosen = fixable
    elif answer in ("r", "review") and count > 1:
        chosen = review_one_by_one(fixable)
    else:
        chosen = []
    if not chosen:
        say("No changes made.")
        return 0

    applied = apply_to_file(src, chosen, language, state)
    if not applied:
        say(red("Clearly couldn't apply any of the fixes safely, so your file is unchanged."))
        return 0
    for p in applied:
        state["fixed"].append({"file": name, "title": p["title"], "judgment": bool(p.get("needs_decision"))})
    backup = state["backups"][os.path.abspath(src.path)]
    say(green(f"✔ Applied {len(applied)} fix{'es' if len(applied) != 1 else ''} to {name}") +
        dim(f"  (original saved as {show_path(backup)})"))
    return len(applied)


def print_recap(state):
    if not state["fixed"]:
        return
    say()
    say(bold("What Clearly changed"))
    for item in state["fixed"]:
        flag = yellow("  ⚠") if item["judgment"] else ""
        say(f"  {item['file']}: {item['title']}{flag}")
    if any(item["judgment"] for item in state["fixed"]):
        say(dim("  ⚠ = a judgment call. Check it does what you want."))
    for backup in state["backups"].values():
        say(dim(f"  Original saved as {show_path(backup)}"))


# ----------------------------------------------------------------------------
# The whole run
# ----------------------------------------------------------------------------

def run(script_path, language, runner):
    state = {"backups": {}, "fixed": []}
    seen = set()
    woke = False

    returncode, stderr_text = run_target_script(runner)
    if returncode == 0:
        say(green("✔ Ran successfully, no errors."))
        return 0

    for round_no in range(1, MAX_ROUNDS + 1):
        file_path, error_line, error_message = parse_traceback(language, stderr_text)
        if not file_path:
            say(red("Clearly couldn't find a file and line number in that error, so it can't help with this one."))
            break
        if error_message.startswith("KeyboardInterrupt"):
            say("Stopped by you (Ctrl+C).")
            return 130
        key = (os.path.abspath(file_path), error_line, error_message)
        if key in seen:
            say(yellow("The same error is still happening after the fixes, so Clearly is stopping here."))
            break
        seen.add(key)
        try:
            src = SourceFile(file_path)
        except (OSError, UnicodeDecodeError):
            say(red(f"Clearly couldn't read {show_path(file_path)} as a UTF-8 text file."))
            break

        if not woke:
            wake_server()
            woke = True
        result = request_analysis(error_message, stderr_text, src.text, error_line, language, show_path(src.path))
        if result is None:
            break
        if not review_and_apply(result, src, language, error_line, state):
            break

        say()
        say(bold(f"Re-running {os.path.basename(script_path)} ..."))
        say()
        returncode, stderr_text = run_target_script(runner)
        if returncode == 0:
            total = len(state["fixed"])
            rounds = f" in {round_no} rounds" if round_no > 1 else ""
            say()
            say(green(f"✔ {os.path.basename(script_path)} runs now. Clearly fixed {total} "
                      f"problem{'s' if total != 1 else ''}{rounds}."))
            print_recap(state)
            return 0
        if round_no < MAX_ROUNDS:
            say()
            say(yellow(f"Still failing, with a different error. Looking at it (round {round_no + 1} of {MAX_ROUNDS})..."))
        else:
            say()
            say(yellow(f"Clearly stopped after {MAX_ROUNDS} rounds. The script still fails (see the error above)."))

    print_recap(state)
    return returncode or 1


def main():
    global USE_COLOR
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # never crash on a character the terminal can't show
        except Exception:
            pass
    USE_COLOR = _enable_color()

    args = sys.argv[1:]
    if len(args) != 1 or args[0] in ("-h", "--help"):
        say("Usage: clearly <your_script.py or your_script.js>")
        say("Runs your script. If it crashes, Clearly explains every problem in the file and fixes them in one go.")
        return 0 if args and args[0] in ("-h", "--help") else 1
    script_path = args[0]
    if not os.path.isfile(script_path):
        say(red(f"Can't find '{script_path}'."))
        return 1
    language, runner = get_language_and_runner(script_path)
    if not language:
        say(red("Clearly supports .py and .js files for now."))
        return 1
    try:
        return run(script_path, language, runner)
    except KeyboardInterrupt:
        say("\nCancelled.")
        return 130


if __name__ == "__main__":
    sys.exit(main())