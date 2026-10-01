#!/usr/bin/env python3
"""
cli.py — Clearly's command-line wrapper.

WHY THIS FILE EXISTS:
Runs a Python script like `python your_script.py` would, but if it
crashes, sends the error to your running backend and prints a plain-
English explanation and fix. If the backend can confidently express the
fix as a single corrected line, this also offers to apply it directly —
with your explicit yes/no confirmation and a backup file, never silently.

USAGE:
    clearly your_script.py
"""

import sys
import re
import shutil
import subprocess
import requests

BACKEND_URL = "http://localhost:8000/explain"


def run_target_script(script_path):
    result = subprocess.run(
        [sys.executable, script_path],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def parse_traceback(stderr_text):
    matches = re.findall(r'File "(.+?)", line (\d+)', stderr_text)
    if not matches:
        return None, None, None

    file_path, line_number = matches[-1]
    lines = [l for l in stderr_text.strip().splitlines() if l.strip()]
    error_message = lines[-1] if lines else "Unknown error"

    return file_path, int(line_number), error_message


def get_explanation(error_message, stack_trace, file_content, error_line):
    payload = {
        "error_message": error_message,
        "stack_trace": stack_trace,
        "file_content": file_content,
        "error_line": error_line,
        "language": "python",
    }
    response = requests.post(BACKEND_URL, json=payload)
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
    """
    Replaces exactly one line in the file with the model's corrected
    version. A .bak backup is written FIRST, unconditionally, before any
    edit — so even if something goes wrong, the original is never lost.

    Preserves whatever line-ending style the original file already used
    (\\n vs \\r\\n) so this doesn't introduce unrelated diff noise if the
    project is under version control.
    """
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


def main():
    if len(sys.argv) != 2:
        print("Usage: clearly <script_to_run.py>")
        sys.exit(1)

    script_path = sys.argv[1]

    print(f"Running {script_path} ...\n")
    returncode, stdout, stderr = run_target_script(script_path)

    if stdout:
        print("--- Program output ---")
        print(stdout, end="" if stdout.endswith(chr(10)) else chr(10))
        print("-----------------------")

    if returncode == 0:
        print("Ran successfully, no errors.")
        return

    print(stderr)
    print("Analyzing the error with Clearly...\n")

    file_path, error_line, error_message = parse_traceback(stderr)

    if file_path is None:
        print("Couldn't parse a traceback from this error — nothing to analyze.")
        sys.exit(1)

    try:
        with open(file_path, "r") as f:
            file_content = f.read()
    except (FileNotFoundError, OSError):
        print(f"Couldn't read {file_path} to gather code context.")
        sys.exit(1)

    try:
        result = get_explanation(error_message, stderr, file_content, error_line)
        print_result(result)
    except requests.exceptions.ConnectionError:
        print("Couldn't reach the Clearly backend. Is it running?")
        print("Start it with: uvicorn app.main:app --reload --port 8000")
        return
    except Exception as e:
        print(f"Clearly hit an error explaining this: {e}")
        return

    # Only offer the auto-fix if the model was confident enough to
    # provide one — a missing/null fixed_line means the real fix needs
    # more than one line, and we don't attempt anything in that case.
    fixed_line = result.get("fixed_line")
    if not fixed_line:
        return

    print(f"Clearly can apply this one-line fix automatically:\n")
    print(f"  {fixed_line.strip()}\n")
    choice = input("Apply this fix? [y/N]: ").strip().lower()

    if choice != "y":
        print("Skipped — no changes made.")
        return

    backup_path = apply_fixed_line(file_path, error_line, fixed_line)
    print(f"Applied. Original saved to {backup_path}")

    print(f"\nRe-running {script_path} to confirm the fix...\n")
    returncode, stdout, stderr = run_target_script(script_path)
    if stdout:
        print("--- Program output ---")
        print(stdout, end="" if stdout.endswith(chr(10)) else chr(10))
        print("-----------------------")
    if returncode == 0:
        print("Success — the script now runs without error.")
    else:
        print("Still failing after the fix — here's the new error:")
        print(stderr)


if __name__ == "__main__":
    main()