"""Write contracts/openapi.json from the API's declared routes.

Run:  apps/api/.venv/Scripts/python.exe scripts/export_openapi.py
tests/test_contract.py fails if the committed file is out of date.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.main import app  # noqa: E402


def render() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    out = ROOT / "contracts" / "openapi.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {out} ({len(app.openapi()['paths'])} paths)")
