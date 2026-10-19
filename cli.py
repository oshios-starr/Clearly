#!/usr/bin/env python3
import sys
import os
import re
import shutil
import subprocess
import threading
import codecs
import locale
import requests

# Live backend. Override for local development with:
#   $env:CLEARLY_BACKEND_URL="http://localhost:8000"   (PowerShell)
BASE_URL = os.environ.get(
    "CLEARLY_BACKEND_URL", "https://clearly-2176.onrender.com"
).rstrip("/")
EXPLAIN_URL = BASE_URL + "/explain"
HEALTH_URL = BASE_URL + "/health"


def get_language_and_runner(script_path):
    """Figure out which language this file is, and how to run it."""
    ext = os.path.splitext(script_path)[1].lower()
    if ext == ".py":
        return "python", [sys.executable, script_path]
    elif ext == ".js":
        return "javascript", ["node", script_path]
    else:
        return None, None


def run_target_script(runner_command):
    """
    Run the user's script so it behaves like it would in a normal terminal:
    its output and its input() / readline prompts appear live, and the user's
    keyboard works. Only stderr is copied (and echoed live) so Clearly can read
    the error afterwards. Returns (returncode, stderr_text).
    """
    proc = subprocess.Popen(runner_command, stderr=subprocess.PIPE)
    chunks = []

    def pump():
        decoder = codecs.getincrementaldecoder(
            locale.getpreferredencoding(False) or "utf-8"
        )(errors="replace")
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
        # Ctrl+C also reaches the script itself; give it a moment to exit.
        try:
            returncode = proc.wait(timeout=5)
        except Exception:
            proc.kill()
            returncode = 130
    reader.join(timeout=5)
    return returncode, "".join(chunks)


def parse_python_traceback(stderr_text):
    matches = re.findall(r'File "(.+?)", line (\d+)', stderr_text)
    if not matches:
        return None, None, None
    file_path, line_number = matches[-1]
    lines = [l for l in stderr_text.strip().splitlines() if l.strip()]
    error_message = lines[-1] if lines else "Unknown error"
    return file_path, int(line_number), error_message


def parse_node_traceback(stderr_text):
    """
    Node stack traces list frames DEEPEST-FIRST (the opposite of Python,
    which lists them deepest-last). So instead of taking the last frame
    like parse_python_traceback does, we take the FIRST frame that isn't
    inside Node's own internals (those start with "node:").
    """
    lines = stderr_text.strip().splitlines()

    error_message = None
    for line in lines:
        m = re.match(r'^(\w+Error):\s*(.+)$', line.strip())
        if m:
            error_message = line.strip()
            break

    file_path = None
    line_number = None
    frame_pattern = re.compile(r"^\s*at\s+(?:.*\()?(.+):(\d+):(\d+)\)?\s*$")
    for line in lines:
        m = frame_pattern.match(line)
        if not m:
            continue
        candidate_path = m.group(1)
        if candidate_path.startswith("node:"):
            continue
        file_path = candidate_path
        line_number = int(m.group(2))
        break

    if error_message is None:
        clean_lines = [l for l in lines if l.strip()]
        error_message = clean_lines[-1] if clean_lines else "Unknown error"

    return file_path, line_number, error_message


def wake_server():
    """
    The free hosting tier puts the server to sleep when idle. Check if it's
    awake; if not, tell the user and wait for it (up to ~90 seconds).
    """
    try:
        r = requests.get(HEALTH_URL, timeout=5)
        if r.ok:
            return
    except requests.exceptions.RequestException:
        pass

    print("Waking up the Clearly server - this can take up to a minute "
          "the first time...\n")
    try:
        requests.get(HEALTH_URL, timeout=90)
    except requests.exceptions.RequestException:
        pass  # the real request below will report any problem


def get_explanation(error_message, stack_trace, file_content, error_line, language):
    payload = {
        "error_message": error_message,
        "stack_trace": stack_trace,
        "file_content": file_content,
        "error_line": error_line,
        "language": language,
    }
    response = requests.post(EXPLAIN_URL, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def print_result(result):
    print("\n" + "=" * 60)
    print("Clearly found the problem:")
    print("=" * 60)
    print(f"\nWHY THIS HAPPENED:\n{result['explanation']}")
    print(f"\nSUGGESTED FIX:\n{result['fix_suggestion']}")
    print(f"\nConfidence: {result['confidence']}")
    print("=" * 60 + "\n")


def apply_fixed_line(file_path, error_line, fixed_line):
    backup_path = file_path + ".bak"
    shutil.copyfile(file_path, backup_path)
    with open(file_path, "r") as f:
        lines = f.readlines()
    idx = error_line - 1
    original_line = lines[idx]
    if original_line.endswith("\r\n"):
        ending = "\r\n"
    elif original_line.endswith("\n"):
        ending = "\n"
    else:
        ending = ""
    lines[idx] = fixed_line.rstrip("\r\n") + ending
    with open(file_path, "w") as f:
        f.writelines(lines)
    return backup_path


def offer_fix(result, script_path, runner_command, file_path, error_line):
    """
    Offer the one-line fix. Returns what happened: "no_fix_offered",
    "declined", "applied_worked" or "applied_still_failing".
    """
    fixed_line = result.get("fixed_line")
    if not fixed_line:
        return "no_fix_offered"

    print(f"Clearly can apply this one-line fix automatically:\n")
    print(f"  {fixed_line.strip()}\n")
    try:
        choice = input("Apply this fix? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        choice = ""
    if choice != "y":
        print("Skipped - no changes made.")
        return "declined"

    backup_path = apply_fixed_line(file_path, error_line, fixed_line)
    print(f"Applied. Original saved to {backup_path}")
    print(f"\nRe-running {script_path} to confirm the fix...\n")

    returncode, stderr = run_target_script(runner_command)

    if returncode == 0:
        print("\nSuccess - the script now runs without error.")
        return "applied_worked"
    print("\nStill failing after the fix - see the new error above.")
    return "applied_still_failing"


def main():
    if len(sys.argv) != 2:
        print("Usage: clearly <script_to_run.py|.js>")
        sys.exit(1)

    script_path = sys.argv[1]
    language, runner_command = get_language_and_runner(script_path)

    if language is None:
        print(f"Clearly doesn't support this file type yet: {script_path}")
        print("Currently supported: .py (Python), .js (Node.js)")
        sys.exit(1)

    print(f"Running {script_path} ...\n")
    returncode, stderr = run_target_script(runner_command)

    if returncode == 0:
        print("\nRan successfully, no errors.")
        return

    if language == "python":
        file_path, error_line, error_message = parse_python_traceback(stderr)
    else:  # javascript
        file_path, error_line, error_message = parse_node_traceback(stderr)

    if error_message and error_message.strip().startswith("KeyboardInterrupt"):
        print("\nStopped by you (Ctrl+C) - nothing to analyze.")
        return

    print("\nAnalyzing the error with Clearly...\n")

    if file_path is None:
        print("Couldn't parse a stack trace from this error - nothing to analyze.")
        sys.exit(1)

    try:
        with open(file_path, "r") as f:
            file_content = f.read()
    except (FileNotFoundError, OSError):
        print(f"Couldn't read {file_path} to gather code context.")
        sys.exit(1)

    wake_server()

    try:
        result = get_explanation(error_message, stderr, file_content, error_line, language)
        print_result(result)
    except requests.exceptions.Timeout:
        print("The Clearly server took too long to respond. Please try again in a moment.")
        return
    except requests.exceptions.ConnectionError:
        print("Couldn't reach the Clearly server. Check your internet connection and try again.")
        return
    except Exception as e:
        print(f"Clearly hit an error explaining this: {e}")
        return

    offer_fix(result, script_path, runner_command, file_path, error_line)


if __name__ == "__main__":
    main()