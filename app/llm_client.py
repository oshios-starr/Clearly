# app/llm_client.py
import json
import time
from google import genai
from google.genai import types
from app.config import GOOGLE_API_KEY, GEMINI_MODEL
from app.prompt_builder import SYSTEM_PROMPT, build_prompt
from app.models import ExplainRequest, ExplainResponse

client = genai.Client(api_key=GOOGLE_API_KEY)

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "explanation": {"type": "STRING"},
        "fix_suggestion": {"type": "STRING"},
        "confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
        # nullable: true is what allows the model to explicitly return
        # JSON null here instead of being forced to invent some string —
        # this is what makes the "only auto-fix when it's actually safe"
        # rule from the system prompt enforceable at the schema level,
        # not just something we're hoping the model respects.
        "fixed_line": {"type": "STRING", "nullable": True},
    },
    # fixed_line is deliberately NOT in this list — that's what makes it
    # optional/nullable rather than a value the model is forced to fill.
    "required": ["explanation", "fix_suggestion", "confidence"],
}

MAX_RETRIES = 3


def get_explanation(request: ExplainRequest, code_context: str) -> ExplainResponse:
    user_message = build_prompt(request, code_context)

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=user_message,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    max_output_tokens=800,
                    response_mime_type="application/json",
                    response_schema=RESPONSE_SCHEMA,
                ),
            )

            raw_text = response.text
            if not raw_text:
                raise ValueError("Model returned an empty response.")

            parsed = json.loads(raw_text)
            return ExplainResponse(**parsed)

        except Exception as e:
            last_error = e
            print(f"Attempt {attempt} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(attempt)

    raise ValueError(
        f"Failed after {MAX_RETRIES} attempts. Last error: {last_error}"
    )