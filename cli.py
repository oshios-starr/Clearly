#!/usr/bin/env python3
import sys
import os
import re
import shutil
import subprocess
import requests

BACKEND_URL = "http://localhost:8000/explain"


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
    result = subprocess.run(
        runner_command,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


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
    frame_pattern = re.compile(r'^\s*at\s+(?:.*\()?(.+):(\d+):(\d+)\)?\s*$')
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


def get_explanation(error_message, stack_trace, file_content, error_line, language):
    payload = {
        "error_message": error_message,
        "stack_trace": stack_trace,
        "file_content": file_content,
        "error_line": error_line,
        "language": language,
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
        print("Usage: clearly <script_to_run.py|.js>")
        sys.exit(1)

    script_path = sys.argv[1]
    language, runner_command = get_language_and_runner(script_path)

    if language is None:
        print(f"Clearly doesn't support this file type yet: {script_path}")
        print("Currently supported: .py (Python), .js (Node.js)")
        sys.exit(1)

    print(f"Running {script_path} ...\n")
    returncode, stdout, stderr = run_target_script(runner_command)

    if stdout:
        print("--- Program output ---")
        print(stdout, end="" if stdout.endswith(chr(10)) else chr(10))
        print("-----------------------")

    if returncode == 0:
        print("Ran successfully, no errors.")
        return

    print(stderr)
    print("Analyzing the error with Clearly...\n")

    if language == "python":
        file_path, error_line, error_message = parse_python_traceback(stderr)
    else:  # javascript
        file_path, error_line, error_message = parse_node_traceback(stderr)

    if file_path is None:
        print("Couldn't parse a stack trace from this error — nothing to analyze.")
        sys.exit(1)

    try:
        with open(file_path, "r") as f:
            file_content = f.read()
    except (FileNotFoundError, OSError):
        print(f"Couldn't read {file_path} to gather code context.")
        sys.exit(1)

    try:
        result = get_explanation(error_message, stderr, file_content, error_line, language)
        print_result(result)
    except requests.exceptions.ConnectionError:
        print("Couldn't reach the Clearly backend. Is it running?")
        print("Start it with: uvicorn app.main:app --reload --port 8000")
        return
    except Exception as e:
        print(f"Clearly hit an error explaining this: {e}")
        return

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

    returncode, stdout, stderr = run_target_script(runner_command)
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