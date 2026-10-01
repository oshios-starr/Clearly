import os
from dotenv import load_dotenv
load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise RuntimeError(
        "ANTHROPIC_API_KEY is not set. Create a .env file in the project "
        "root with the line: ANTHROPIC_API_KEY=your-key-here"
    )
MODEL_NAME = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
CONTEXT_WINDOW_LINES = int(os.getenv("CONTEXT_WINDOW_LINES", "10"))