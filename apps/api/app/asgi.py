"""Process entry point: `uvicorn app.asgi:app`. Reads configuration from AUTOPRINT_V4_* variables."""
from app.main import create_app

app = create_app()
