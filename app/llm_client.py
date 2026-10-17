import json
import time

import resend
from openai import OpenAI, APIStatusError
from google import genai
from google.genai import types

from app.config import (
    OPENROUTER_API_KEY,
    LLM_MODEL,
    GOOGLE_API_KEY,
    GEMINI_MODEL,
    RESEND_API_KEY,
    ALERT_EMAIL_TO,
    ALERT_EMAIL_FROM,
)
from app.prompt_builder import SYSTEM_PROMPT, build_prompt
from app.models import ExplainRequest, ExplainResponse

# OpenRouter speaks the OpenAI API, so we use the OpenAI SDK pointed at it.
openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)
gemini_client = genai.Client(api_key=GOOGLE_API_KEY)

# Once OpenRouter says the credit is gone (HTTP 402), stop trying it for the
# rest of this process's life. Note: on Render's free tier the process
# restarts after sleeping, which resets these flags.
_primary_exhausted = False
_alert_sent = False

MAX_RETRIES = 3

GEMINI_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "explanation": {"type": "STRING"},
        "fix_suggestion": {"type": "STRING"},
        "confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
        "fixed_line": {"type": "STRING", "nullable": True},
    },
    "required": ["explanation", "fix_suggestion", "confidence"],
}

EXPLAIN_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_explanation",
        "description": "Submit the structured explanation of the code error.",
        "parameters": {
            "type": "object",
            "properties": {
                "explanation": {"type": "string"},
                "fix_suggestion": {"type": "string"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "fixed_line": {"type": ["string", "null"]},
            },
            "required": ["explanation", "fix_suggestion", "confidence"],
        },
    },
}


def _clean_response(result, request):
    """
    Some models double-escape quotes inside tool-call arguments, so text comes
    back as  order.get(\\"amount\\", 0)  instead of  order.get("amount", 0).
    Writing that into a file would break it, so undo it.

    - Prose fields: a backslash-quote is never intended, always unescape.
    - fixed_line: only unescape if the ORIGINAL line has no backslash-quote,
      so code that legitimately contains one is left alone.
    """
    def unescape(text):
        return text.replace('\\"', '"')

    result.explanation = unescape(result.explanation)
    result.fix_suggestion = unescape(result.fix_suggestion)

    if result.fixed_line and '\\"' in result.fixed_line:
        lines = request.file_content.splitlines()
        idx = request.error_line - 1
        original = lines[idx] if 0 <= idx < len(lines) else ""
        if '\\"' not in original:
            result.fixed_line = unescape(result.fixed_line)
    return result


def _send_fallback_alert(reason):
    """Best-effort email to the developer. Never allowed to break a request."""
    if not (RESEND_API_KEY and ALERT_EMAIL_TO):
        print("Alert email not configured (RESEND_API_KEY / ALERT_EMAIL_TO) -- skipping.")
        return
    try:
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": ALERT_EMAIL_FROM,
            "to": [ALERT_EMAIL_TO],
            "subject": "Clearly: switched from Claude to Gemini",
            "text": (
                "Clearly's backend just switched from the primary model to Gemini "
                f"because:\n\n{reason}\n\n"
                "The primary model won't be tried again until the process restarts "
                "or you top up your OpenRouter credits."
            ),
        })
        print("Sent fallback alert email.")
    except Exception as e:
        print(f"Could not send fallback alert email: {e}")


def _get_explanation_primary(user_message, request):
    response = openrouter_client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=800,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        tools=[EXPLAIN_TOOL],
        tool_choice={"type": "function", "function": {"name": "submit_explanation"}},
    )
    tool_calls = response.choices[0].message.tool_calls
    if not tool_calls:
        raise ValueError("Model did not return a structured tool call.")
    result = ExplainResponse(**json.loads(tool_calls[0].function.arguments))
    return _clean_response(result, request)


def _get_explanation_gemini(user_message, request):
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=800,
            response_mime_type="application/json",
            response_schema=GEMINI_RESPONSE_SCHEMA,
        ),
    )
    raw_text = response.text
    if not raw_text:
        raise ValueError("Gemini returned an empty response.")
    result = ExplainResponse(**json.loads(raw_text))
    return _clean_response(result, request)


def get_explanation(request: ExplainRequest, code_context: str) -> ExplainResponse:
    global _primary_exhausted, _alert_sent

    user_message = build_prompt(request, code_context)

    if not _primary_exhausted:
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return _get_explanation_primary(user_message, request)
            except APIStatusError as e:
                if e.status_code == 402:
                    # Out of credit: not transient. Switch for good, alert once.
                    _primary_exhausted = True
                    if not _alert_sent:
                        _alert_sent = True
                        _send_fallback_alert(f"OpenRouter billing error (HTTP 402): {e.message}")
                    break
                last_error = e
                print(f"Primary attempt {attempt} failed ({e.status_code}): {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(attempt)
            except Exception as e:
                last_error = e
                print(f"Primary attempt {attempt} failed: {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(attempt)
        else:
            # Transient failure: Gemini covers this one request only.
            print(f"Primary failed {MAX_RETRIES} times, using Gemini for this request: {last_error}")

    return _get_explanation_gemini(user_message, request)