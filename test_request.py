# test_request.py
#
# WHY THIS FILE EXISTS:
# A quick, manual way to hit your own /explain endpoint with a REAL
# example error, so you can eyeball the response quality before building
# the extension. Run this with the server already running in another
# terminal (`uvicorn app.main:app --reload --port 8000`).
#
# Run it with: python test_request.py

import requests
import json

# A deliberately realistic example: a classic Python bug where you loop
# over a list while also removing items from it, which silently skips
# elements. This is a good first test case because the fix isn't obvious
# from the error message alone (a plain traceback here often shows no
# error at all, just wrong output) — a good stretch test for whether your
# context extraction is actually giving the model something useful. If
# yours is a case that DOES raise an error, swap this for one that does;
# the important thing is testing with real code, not a toy example.
sample_file_content = """def remove_duplicates(items):
    seen = []
    for i, item in enumerate(items):
        if item in seen:
            items.pop(i)
        else:
            seen.append(item)
    return items

result = remove_duplicates([1, 2, 2, 3, 3, 3])
print(result)
"""

payload = {
    "error_message": "Output is [1, 2, 3, 3] instead of the expected [1, 2, 3] — a duplicate slipped through",
    "stack_trace": None,
    "file_content": sample_file_content,
    "error_line": 5,  # the items.pop(i) line
    "language": "python",
}

# requests.post sends an HTTP POST request — this is the exact same kind
# of call your VS Code extension will make later, just from a plain
# Python script instead of TypeScript, so you can test the backend in
# total isolation.
response = requests.post("http://localhost:8000/explain", json=payload)

print(f"Status code: {response.status_code}\n")

# json.dumps with indent=2 just pretty-prints the response so it's
# readable in your terminal instead of one unbroken line.
print(json.dumps(response.json(), indent=2))