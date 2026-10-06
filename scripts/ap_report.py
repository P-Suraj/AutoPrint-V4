"""Founder report, through the deployed API (the database port is not reachable from the founder PC).

  PY scripts/ap_report.py ABC123                 one shop, last 24 hours
  PY scripts/ap_report.py ABC123 --days 7        one shop, last 7 days (up to 90)
  PY scripts/ap_report.py ABC123 --hours 6       one shop, last 6 hours
  PY scripts/ap_report.py --all                  every shop, one line each

Reads AUTOPRINT_V4_MAINTENANCE_TOKEN from .env and never prints it. Shows no document names and no customer data.
Read-only: running it changes nothing."""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://autoprint-v4.vercel.app"
HTTP = httpx                        # tests swap this for a test client


def token() -> str:
    env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if l and not l.startswith("#") and "=" in l)
    return env["AUTOPRINT_V4_MAINTENANCE_TOKEN"]


def fetch(path: str, params: dict) -> dict:
    r = HTTP.get(BASE + path, params=params, headers={"X-Maintenance-Token": token()}, timeout=60)
    if r.status_code != 200:
        raise SystemExit(f"could not get the report ({r.status_code}): {r.text[:200]}")
    return r.json()


# ------------------------------------------------------------------ small formatters
def when(iso):
    return datetime.fromisoformat(iso) if iso else None


def local(iso) -> str:
    """A server time shown in this computer's own time zone."""
    d = when(iso)
    return d.astimezone().strftime("%d %b %H:%M") if d else "never"


def span(seconds) -> str:
    if seconds is None:
        return "-"
    s = int(round(float(seconds)))
    if s < 90:
        return f"{s} s"
    if s < 5400:
        return f"{s // 60} min {s % 60:02d} s" if s < 600 else f"{s // 60} min"
    if s < 172800:
        return f"{s // 3600} h {s % 3600 // 60:02d} min"
    return f"{s // 86400} days {s % 86400 // 3600} h"


def ago(iso, now) -> str:
    d = when(iso)
    return "never" if d is None else span((now - d).total_seconds()) + " ago"


def pct(rate, part, whole) -> str:
    return "no jobs yet" if rate is None else f"{rate * 100:.0f}%  ({part} of {whole})"


def plural(n, one, many=None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


# ------------------------------------------------------------------ one shop
def render_shop(d: dict) -> str:
    out = []
    add = out.append
    now = when(d["generated_at"]) or datetime.now(timezone.utc)
    shop, o, dup, human = d["shop"], d["outcomes"], d["duplicates"], d["human_actions"]
    hours = d["window_hours"]
    window = f"last {hours} hours" if hours < 48 else f"last {hours // 24} days"
    add(f"{shop['name']} ({shop['code']}) - {'taking orders' if shop['is_active'] else 'SWITCHED OFF (not taking orders)'}")
    add(f"{window.capitalize()}, since {local(d['window_start'])} (your computer's time). Hours of the day are in {d['timezone']} time.")
    if d.get("first_job_at") is None:
        add("This shop has never received a job.")
    add("")

    look = []
    if o["needs_attention_now"]:
        look.append(plural(o["needs_attention_now"], "job needs", "jobs need") + " the shopkeeper to say what happened")
    if o["failed_now"]:
        look.append(plural(o["failed_now"], "job") + " failed")
    add("NEEDS A LOOK NOW: " + ("; ".join(look) + ". Phone the shop." if look else "nothing."))
    add("")

    add(f"JOBS SENT TO THE SHOP: {o['jobs_sent_to_shop']}")
    for label, n in [("sent to printer", o["sent_to_printer"]), ("rejected by the shop", o["rejected"]),
                     ("cancelled by the customer", o["cancelled"]), ("expired (not approved within 1 hour)", o["expired"]),
                     ("failed", o["failed_now"]), ("needs attention", o["needs_attention_now"]),
                     ("still open (waiting, approved or printing)", o["still_open"])]:
        add(f"  {label:<44}{n:>5}")
    orders = d["orders"]
    add(f"ORDERS STARTED BY CUSTOMERS: {orders['started']}, of which {orders['never_sent']} were never sent to the shop "
        "(the customer left before pressing send).")
    add("")

    reached = o["jobs_that_reached_the_printer_step"]
    add(f"RATES, out of the {plural(reached, 'job')} the shop computer picked up to print")
    add(f"  {'success rate (ended as sent to printer)':<44}{pct(o['success_rate'], o['sent_to_printer'], reached)}")
    add(f"  {'first try, nobody had to step in':<44}{pct(o['first_try_no_help_rate'], o['sent_to_printer_first_try_no_help'], reached)}")
    add(f"  {'needs-attention rate':<44}{pct(o['needs_attention_rate'], o['went_to_needs_attention'], reached)}")
    add("")

    add(f"SHOPKEEPER HAD TO STEP IN ON: {plural(human['jobs_resolved_by_hand'], 'job')}"
        f"  (chose \"It printed\" {human['said_it_printed']}, \"It did not print\" {human['said_it_did_not_print']},"
        f" \"Print again\" {human['print_again']})")
    add("")

    add("DUPLICATE CHECK")
    add(f"  {'jobs printed again by the shopkeeper':<52}{dup['jobs_with_more_than_one_attempt']:>4}")
    add(f"  {'jobs handed to Windows printing more than once':<52}{dup['jobs_handed_to_windows_printing_more_than_once']:>4}"
        "   (paper may have come out twice: ask the shop)")
    add(f"  {'jobs where two attempts both ended as printed':<52}{dup['jobs_where_two_attempts_ended_as_printed']:>4}"
        "   (a likely duplicate print)")
    add(f"  {'second attempts that nobody asked for':<52}{dup['attempts_without_a_human_print_again']:>4}"
        "   (must always be 0)")
    add(f"  {'late reports that disagreed with the record':<52}{dup['late_conflicting_reports']:>4}")
    add("")

    add("HOW LONG THINGS TOOK   (typical = half were faster; slow = 9 in 10 were faster)")
    if d["timings"]:
        add(f"  {'step':<54}{'count':>6}  {'typical':>12}  {'slow':>12}  {'longest':>12}")
        for t in d["timings"]:
            add(f"  {t['label']:<54}{t['jobs']:>6}  {span(t['median_seconds']):>12}  {span(t['p90_seconds']):>12}  {span(t['longest_seconds']):>12}")
    else:
        add("  nothing to measure in this period.")
    add("")

    if d["busiest_hours"]:
        add("BUSIEST HOURS: " + ", ".join(f"{h['hour']:02d}:00 ({plural(h['jobs'], 'job')})" for h in d["busiest_hours"][:6]))
    if len(d["days"]) > 1:
        add("BY DAY")
        for day in d["days"]:
            add(f"  {day['date']}   jobs {day['jobs']:>4}   sent to printer {day['sent_to_printer']:>4}   "
                f"failed or needs attention {day['failed_or_needs_attention']:>3}")
    add("")

    add("SHOP COMPUTERS")
    if not d["devices"]:
        add("  none connected yet.")
    for c in d["devices"]:
        if c["status"] != "active":
            state = "disconnected"
        elif c["online"]:
            state = "ONLINE"
        else:
            state = f"NOT ONLINE, last seen {ago(c['last_seen_at'], now)}"
        add(f"  {c['name']:<24}{state}   app version {c['agent_version'] or '?'}")
        off = c.get("offline")
        if c["status"] != "active":
            continue
        if off is None:
            add("      time away in this period: not recorded (only the last check-in time is kept)")
        else:
            line = (f"      time away since {local(off['recorded_from'])}: {plural(off['gaps_ended'], 'time')}, "
                    f"{span(off['seconds_in_ended_gaps'])} in total, longest {span(off['longest_ended_gap_seconds'])}")
            if off["away_now_seconds"]:
                line += f"; away right now for {span(off['away_now_seconds'])}"
            add(line)
    add("  " + d["offline_tracking"]["note"])
    add("  Time away includes nights and closed days: the report cannot tell a closed shop from a broken connection.")
    add("")

    if d["jobs"]:
        add("MOST RECENT JOBS (order code the customer sees, state, print attempts, when sent)")
        for j in d["jobs"][:15]:
            add(f"  {j['order']}  {j['status']:<18} attempts {j['attempts']}  {local(j['created_at'])}")
        add("")
    add("WHAT THIS REPORT CANNOT SHOW")
    for line in d["cannot_show"]:
        add("  - " + line)
    return "\n".join(out)


# ------------------------------------------------------------------ every shop, one line each
def render_all(d: dict) -> str:
    shops = d["shops"]
    if not shops:
        return "No shops yet."
    now = datetime.now(timezone.utc)
    out = [f"{'CODE':<8}{'NAME':<30}{'ORDERS':<8}{'COMPUTER':<26}{'JOBS TODAY':>10}  NEEDS A LOOK"]
    for s in shops:
        if s["computers"] == 0:
            computer = "none connected"
        elif s["online"]:
            computer = "online"
        else:
            computer = "last seen " + ago(s["last_seen_at"], now)
        look = []
        if s["needs_attention"]:
            look.append(f"{s['needs_attention']} need attention")
        if s["failed_last_24h"]:
            look.append(f"{s['failed_last_24h']} failed")
        if s["waiting_for_approval"]:
            look.append(f"{s['waiting_for_approval']} waiting for approval")
        if s["rate_card_version"] is None:
            look.append("NO PRICES SET")
        out.append(f"{s['code']:<8}{s['name'][:28]:<30}{'on' if s['is_active'] else 'OFF':<8}{computer:<26}{s['jobs_today']:>10}  "
                   + (", ".join(look) or "-"))
    return "\n".join(out)


def main(argv=None) -> int:
    global BASE
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("shop", nargs="?", help="shop code, for example ABC123")
    p.add_argument("--all", action="store_true", help="every shop, one line each")
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--days", type=int, help="use days instead of hours (up to 90)")
    p.add_argument("--tz", default="Asia/Kolkata", help="time zone for hours of the day (default Asia/Kolkata)")
    p.add_argument("--base", default=BASE)
    a = p.parse_args(argv)
    BASE = a.base
    if a.all:
        print(render_all(fetch("/v1/internal/shops", {"tz": a.tz})))
        return 0
    if not a.shop:
        p.error("give a shop code, or --all")
    params = {"tz": a.tz, "hours": a.hours}
    if a.days:
        params["days"] = a.days
    print(render_shop(fetch(f"/v1/internal/report/{a.shop.strip().upper()}", params)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
