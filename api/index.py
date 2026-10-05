"""Vercel serverless entry point. The application lives in apps/api; this file only exposes it.

Configuration comes from AUTOPRINT_V4_* environment variables set in the Vercel project.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from app.asgi import app  # noqa: E402,F401  (Vercel serves the ASGI object named `app`)
