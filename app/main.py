# app/main.py
#
# WHY THIS FILE EXISTS:
# This is the actual server — the thing you run with `uvicorn app.main:app`.
# It defines the HTTP endpoints the VS Code extension and CLI will call.
# Notice how short this file is: that's deliberate. All the real logic
# lives in the other files (context_extractor, prompt_builder, llm_client);
# main.py's only job is to receive a request, call those pieces in order,
# and return the result.

from fastapi import FastAPI, HTTPException
from app.models import ExplainRequest, ExplainResponse
from app.context_extractor import get_code_context
from app.llm_client import get_explanation

# This creates the actual FastAPI application object. Everything else
# (routes, middleware) attaches to this `app` instance — it's also what
# the `uvicorn app.main:app` command in your terminal is pointing at
# ("app.main" = this file's path, ":app" = this specific variable).
app = FastAPI(title="Clearly Backend", version="0.1.0")


@app.get("/health")
def health_check():
    """
    A trivial endpoint that just confirms the server is up and reachable.
    Not glamorous, but genuinely useful: this is what you'll curl first
    every time something seems broken, to rule out "is the server even
    running" before debugging anything more complex.
    """
    return {"status": "ok"}


@app.post("/explain", response_model=ExplainResponse)
def explain_error(request: ExplainRequest) -> ExplainResponse:
    """
    The core endpoint. FastAPI automatically:
    - parses the incoming JSON body into an ExplainRequest object
    - validates it against the model (rejects the request with a clear
      422 error if, say, error_line is missing or negative)
    - and, because we typed the return as ExplainResponse, validates
      and documents the shape of what we send back too.

    This is the entire "product" from the backend's point of view: one
    function that takes an error and returns an explanation.
    """

    try:
        # Step 1: extract just the relevant window of code around the
        # error, instead of using the whole file content.
        code_context = get_code_context(
            file_content=request.file_content,
            error_line=request.error_line,
        )

        # Step 2: build the prompt and call the LLM, returning an
        # already-validated ExplainResponse object.
        result = get_explanation(request, code_context)

        return result

    except ValueError as e:
        # This catches the case from llm_client.py where the model
        # returned malformed JSON. We convert it into a proper HTTP
        # error (502 = "the upstream service gave us a bad response")
        # instead of letting a raw Python exception leak out as a
        # generic 500 error with no useful message for the client.
        raise HTTPException(status_code=502, detail=str(e))