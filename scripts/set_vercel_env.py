"""Push the V4 production settings to the V4 Vercel project, reading secrets from the git-ignored .env.

Prints variable NAMES only. Refuses to run unless .vercel/project.json is the V4 project, so it can never
write to V3. Usage: python scripts/set_vercel_env.py [--database-url URL]
"""
import argparse
import json
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V4_PROJECT_ID = "prj_XTCCEAjd8cPiwuLoeRqSOqAJc2jh"
SITE = "https://autoprint-v4.vercel.app"


def dotenv() -> dict:
    out = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def vercel(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    exe = shutil.which("vercel.cmd") or shutil.which("vercel")
    return subprocess.run([exe, *args], cwd=ROOT, input=stdin, capture_output=True, text=True, timeout=120)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", help="override the database URL (for example a pooler address)")
    ap.add_argument("--keep-maintenance-token", action="store_true")
    args = ap.parse_args()

    link = json.loads((ROOT / ".vercel" / "project.json").read_text())
    if link.get("projectId") != V4_PROJECT_ID:
        raise SystemExit("this folder is not linked to the V4 Vercel project; refusing to write environment variables")

    env = dotenv()
    values = {
        "AUTOPRINT_V4_DATABASE_URL": args.database_url or env["AUTOPRINT_V4_DATABASE_URL"],
        "AUTOPRINT_V4_SUPABASE_URL": env["AUTOPRINT_V4_SUPABASE_URL"],
        "AUTOPRINT_V4_SUPABASE_SECRET_KEY": env["AUTOPRINT_V4_SUPABASE_SECRET_KEY"],
        "AUTOPRINT_V4_STORAGE_BACKEND": "supabase",
        "AUTOPRINT_V4_STORAGE_BUCKET": "print-documents",
        "AUTOPRINT_V4_ENVIRONMENT": "production",
        "AUTOPRINT_V4_ALLOWED_ORIGINS": SITE,
        "AUTOPRINT_V4_BACKGROUND_MAINTENANCE": "false",
    }
    # The maintenance token must also exist locally (git-ignored .env) so scripts can call the protected
    # endpoints. Generate it once, save it, and reuse it unless a new one is requested.
    token = env.get("AUTOPRINT_V4_MAINTENANCE_TOKEN")
    if not token:
        token = secrets.token_hex(24)
        with (ROOT / ".env").open("a", encoding="utf-8", newline="\n") as f:
            f.write(f"AUTOPRINT_V4_MAINTENANCE_TOKEN={token}\n")
    values["AUTOPRINT_V4_MAINTENANCE_TOKEN"] = token
    sensitive = {"AUTOPRINT_V4_DATABASE_URL", "AUTOPRINT_V4_SUPABASE_SECRET_KEY", "AUTOPRINT_V4_MAINTENANCE_TOKEN"}

    for name, value in values.items():
        flags = ["--force", "--yes"] + (["--sensitive"] if name in sensitive else [])
        r = vercel(["env", "add", name, "production", *flags], stdin=value)
        print(f"{'ok  ' if r.returncode == 0 else 'FAIL'} {name}" + ("" if r.returncode == 0 else f"  ({(r.stderr or r.stdout).strip()[:120]})"))
        if r.returncode != 0:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
