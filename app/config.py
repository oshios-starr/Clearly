# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    raise RuntimeError(
        "GOOGLE_API_KEY is not set. Add it to your .env file: "
        "GOOGLE_API_KEY=your-key-here"
    )

MODEL_NAME = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

CONTEXT_WINDOW_LINES = int(os.getenv("CONTEXT_WINDOW_LINES", "10"))