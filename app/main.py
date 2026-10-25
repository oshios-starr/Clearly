# app/main.py
#
# WHY THIS FILE EXISTS:
# This is the actual server (`uvicorn app.main:app`). It receives a request,
# calls the other files in order, and returns the result.
#
#   /health   -> "is the server alive?"
#   /explain  -> explains ONE error and fixes ONE line (older CLIs still use this)
#   /analyze  -> reads the whole file, explains EVERY problem, returns every fix

import logging

from fastapi import FastAPI, HTTPException

from app.analyzer import analyze
from app.context_extractor import get_code_context
from app.llm_client import get_explanation
from app.models import AnalyzeRequest, AnalyzeResponse, ExplainRequest, ExplainResponse

app = FastAPI(title="Clearly Backend", version="0.2.0")


@app.get("/health")
def health_check():
    """Confirms the server is up. Also what UptimeRobot pings every 5 minutes."""
    return {"status": "ok"}


@app.post("/explain", response_model=ExplainResponse)
def explain_error(request: ExplainRequest) -> ExplainResponse:
    """The original endpoint: one error in, one explanation (and one-line fix) out."""
    try:
        code_context = get_code_context(
            file_content=request.file_content,
            error_line=request.error_line,
        )
        return get_explanation(request, code_context)
    except ValueError as e:
        # The model returned malformed JSON. 502 = "the service behind us gave a bad answer".
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze_file(request: AnalyzeRequest) -> AnalyzeResponse:
    """The new endpoint: the whole file in, every problem and every fix out."""
    if len(request.file_content) > 1_000_000:  # protects your credit and your server's memory
        raise HTTPException(status_code=413, detail="That file is bigger than 1 MB, which is more than Clearly can read.")
    try:
        return analyze(request)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception:
        # Both AI providers failed. Log the real reason for you; tell the CLI something calm.
        logging.exception("analyze failed")
        raise HTTPException(
            status_code=502,
            detail="Clearly's AI is unavailable right now. Please try again in a minute.",
        )