"""Writes supabase/_combined.sql (git-ignored): every migration, in order, as one script to paste into the
Supabase SQL Editor when the database port is not reachable from your network.

Run once on an EMPTY database. The migrations are not re-runnable; the schema_migrations table below
records what was applied so a second paste fails loudly instead of half-applying.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
files = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
parts = [
    "-- AutoPrint V4: all migrations in order. Paste into Supabase > SQL Editor and press Run, ONCE.\n",
    "BEGIN;\n",
    "CREATE SCHEMA IF NOT EXISTS ap;\n",
    "CREATE TABLE ap.schema_migrations (id text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());\n",
]
for f in files:
    body = f.read_text(encoding="utf-8")
    # each migration file carries its own plain statements; strip nothing, just fence them
    parts.append(f"\n-- ===== {f.name} =====\n{body}\n")
    parts.append(f"INSERT INTO ap.schema_migrations (id) VALUES ('{f.stem}');\n")
parts.append("\nCOMMIT;\n")
out = ROOT / "supabase" / "_combined.sql"
out.write_text("".join(parts), encoding="utf-8", newline="\n")
print(f"wrote {out} ({len(files)} migrations, {out.stat().st_size} bytes)")
