#!/usr/bin/env python3
"""
cli.py — Clearly's command-line wrapper.

WHY THIS FILE EXISTS:
This is the CLI delivery surface from the roadmap: it runs a Python
script exactly like `python your_script.py` would, but if it crashes,
Clearly automatically captures the error, sends it to your already-
running backend, and prints a plain-English explanation and fix —
instead of you staring at a raw traceback.

USAGE:
    python cli.py your_script.py
"""

import sys
import re
import subprocess
import requests

BACKEND_URL = "http://localhost:8000/explain"


def run_target_script(script_path):
    """
    Runs the given Python script as a separate process (exactly like
    typing `python script.py` yourself) and captures whatever it prints
    to stderr — which is where Python writes tracebacks when a script
    crashes. Using subprocess (rather than importing and running the
    script in-process) means a crash in the target script can never
    crash Clearly itself — the two are fully isolated.
    """
    result = subprocess.run(
        [sys.executable, script_path],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def parse_traceback(stderr_text):
    """
    Pulls the (file, line number) of the DEEPEST frame in the traceback
    — the frame closest to where the error actually happened — plus the
    final line, which is the actual error message (e.g. "ZeroDivisionError:
    division by zero"). Python traceback lines look like:
        File "script.py", line 5, in <module>
    so this regex grabs every (file, line) pair in order; the LAST match
    is the deepest frame, which is what we want to show code context for.
    """
    matches = re.findall(r'File "(.+?)", line (\d+)', stderr_text)
    if not matches:
        return None, None, None

    file_path, line_number = matches[-1]

    # The error message is the last non-empty line of the traceback —
    # everything after the last "File" block is the exception's own
    # message (e.g. "ZeroDivisionError: division by zero").
    lines = [l for l in stderr_text.strip().splitlines() if l.strip()]
    error_message = lines[-1] if lines else "Unknown error"

    return file_path, int(line_number), error_message


def get_explanation(error_message, stack_trace, file_content, error_line):
    """
    Sends the captured error to your already-running backend (the same
    /explain endpoint test_request.py has been testing) and returns the
    parsed JSON response.
    """
    payload = {
        "error_message": error_message,
        "stack_trace": stack_trace,
        "file_content": file_content,
        "error_line": error_line,
        "language": "python",
    }
    response = requests.post(BACKEND_URL, json=payload)
    response.raise_for_status()  # raises an error if the backend itself failed
    return response.json()


def print_result(result):
    """
    Formats the explanation nicely in the terminal instead of just
    dumping raw JSON — this is literally the product experience: an
    error happens, and instead of a scary traceback, the developer sees
    a clear explanation and fix.
    """
    print("\n" + "=" * 60)
    print("Clearly found the problem:")
    print("=" * 60)
    print(f"\nWHY THIS HAPPENED:\n{result['explanation']}")
    print(f"\nSUGGESTED FIX:\n{result['fix_suggestion']}")
    print(f"\nConfidence: {result['confidence']}")
    print("=" * 60 + "\n")


def main():
    if len(sys.argv) != 2:
        print("Usage: python cli.py <script_to_run.py>")
        sys.exit(1)

    script_path = sys.argv[1]

    print(f"Running {script_path} ...\n")
    returncode, stdout, stderr = run_target_script(script_path)

    # Show the script's normal output exactly as it would have printed
    # if you'd run it yourself — Clearly should never hide real output.
    if stdout:
        print(stdout)

    if returncode == 0:
        # The script ran successfully — nothing to explain, so Clearly
        # stays out of the way entirely.
        print("Ran successfully, no errors.")
        return

    # The script crashed — this is the moment Clearly exists for.
    print(stderr)  # still show the real traceback, don't hide it
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
    except Exception as e:
        print(f"Clearly hit an error explaining this: {e}")


if __name__ == "__main__":
    main()