# app/llm_client.py
#
# WHY THIS FILE EXISTS:
# Isolates all direct contact with the Anthropic API into one place. If you
# ever swap providers, change models, or add retry logic, you change it
# here once — nothing else in the codebase needs to know or care that
# you're specifically calling Claude versus any other model.

import json
from anthropic import Anthropic
from app.config import ANTHROPIC_API_KEY, MODEL_NAME
from app.prompt_builder import SYSTEM_PROMPT, build_prompt
from app.models import ExplainRequest, ExplainResponse

# Create ONE client instance when this module is first imported, not a
# new one on every request. Creating a new client per-request wastes
# a small amount of setup time on every single API call for no benefit —
# the client object is safe to reuse across requests.
client = Anthropic(api_key=ANTHROPIC_API_KEY)


def get_explanation(request: ExplainRequest, code_context: str) -> ExplainResponse:
    """
    Sends the built prompt to Claude and parses the JSON response back
    into our ExplainResponse model. This is the function main.py actually
    calls — everything above it (prompt building, context extraction) was
    preparation for this one API call.
    """

    user_message = build_prompt(request, code_context)

    # messages.create() is the actual network call to Anthropic's API.
    # max_tokens caps the response length — 500 is generous for a short
    # explanation + fix but stops a runaway response from costing more
    # than it should.
    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    # response.content is a LIST of content blocks (the API supports
    # multiple blocks per response, e.g. for tool use). For a plain text
    # answer like ours, we want the text out of the first block.
    raw_text = response.content[0].text

    # We told the model to return ONLY JSON, but models occasionally wrap
    # output in markdown code fences (```json ... ```) even when told not
    # to. Stripping those defensively here means one weird response
    # doesn't crash your endpoint — better to handle this quirk than
    # assume the model will always follow the format instruction perfectly.
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        # Remove the opening fence (```json or ```) and closing fence,
        # then strip again to clean up any leftover whitespace/newlines.
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
        cleaned = cleaned.strip()

    try:
        # json.loads() turns the JSON string into a Python dictionary.
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # If the model still didn't give us valid JSON, we fail with a
        # clear, specific error rather than letting a confusing
        # KeyError or crash happen two lines later. Seeing the raw
        # text in the error is essential for debugging prompt issues.
        raise ValueError(
            f"Model did not return valid JSON. Raw response: {raw_text}"
        ) from e

    # **parsed unpacks the dictionary's keys as arguments — this only
    # works cleanly because we control the prompt and told the model
    # exactly which keys to use (explanation, fix_suggestion, confidence),
    # matching the ExplainResponse field names exactly.
    return ExplainResponse(**parsed)