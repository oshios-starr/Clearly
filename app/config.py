import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    raise RuntimeError(
        "GOOGLE_API_KEY is not set. Add it to your .env file: "
        "GOOGLE_API_KEY=your-key-here"
    )

# Primary model, served through OpenRouter.
LLM_MODEL = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-5")
# Fallback model, used when the OpenRouter credit runs out.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

CONTEXT_WINDOW_LINES = int(os.getenv("CONTEXT_WINDOW_LINES", "10"))

# Alert email, sent once when Clearly falls back from OpenRouter to Gemini.
# Sent over HTTPS through Resend (Render blocks normal email ports).
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "onboarding@resend.dev")