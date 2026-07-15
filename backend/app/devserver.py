"""Windows host-dev runner: async psycopg needs a selector event loop, and
the policy must be set BEFORE uvicorn creates the loop (the uvicorn CLI
creates it before importing the app). Linux containers use the CLI directly.

    python -m app.devserver
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

from .config import settings

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.api_port,
                loop="asyncio", log_level=settings.log_level)
