# app/config.py
#
# WHY THIS FILE EXISTS:
# Your Anthropic API key is a secret. If you hardcode it into main.py and
# later push that file to GitHub, the key leaks and someone else can spend
# your money. This file's only job is to pull the key out of a separate
# .env file (which you'll add to .gitignore) so the secret never touches
# your actual source code.

import os
from dotenv import load_dotenv

# load_dotenv() reads the ".env" file in your project root and copies
# its contents into the environment variables this Python process can see.
# It does nothing if .env doesn't exist yet, so this line is safe to run
# even before you've created that file.
load_dotenv()

# os.getenv(key, default) looks up an environment variable by name.
# If ANTHROPIC_API_KEY isn't set anywhere, this returns None instead of
# crashing — we check for that explicitly below so you get a clear error
# message instead of a confusing failure three files later.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

if not ANTHROPIC_API_KEY:
    # Fail loudly and immediately at startup, not silently later when
    # the first real request comes in and the LLM call mysteriously fails.
    raise RuntimeError(
        "ANTHROPIC_API_KEY is not set. Create a .env file in the project "
        "root with the line: ANTHROPIC_API_KEY=your-key-here"
    )

# The model you call is a config value, not a hardcoded string in your
# LLM-calling code — this means you can A/B test Sonnet vs Haiku for
# speed/cost/quality tradeoffs later by changing one environment variable,
# not editing code. Defaults to Sonnet 5 (good quality/speed balance for
# an MVP); switch to a faster/cheaper model later once latency matters.
MODEL_NAME = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

# How many lines of code to grab above and below the error line.
# This is also pulled into config (not hardcoded in context_extractor.py)
# because you'll want to tune this number based on real eval results —
# too small and the model lacks context, too large and you waste tokens
# and money on every single request.
CONTEXT_WINDOW_LINES = int(os.getenv("CONTEXT_WINDOW_LINES", "10"))