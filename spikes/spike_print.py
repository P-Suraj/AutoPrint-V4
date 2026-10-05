"""Phase 1 spike: print PDFs through SumatraPDF and observe the Windows spooler.

Throwaway measurement code. Writes raw observations to spikes/_out/results.json.
Run: .venv\\Scripts\\python.exe spike_print.py <experiment>
Experiments: normal | settings | drills
"""
import json
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import win32print
from pypdf import PdfReader

HERE = Path(__file__).parent
OUT = HERE / "_out"
PDFS = OUT / "pdfs"
SUMATRA = OUT / "sumatra_portable" / "SumatraPDF-3.6.1-64.exe"
PRINTER = "AutoPrint-Spike-PDF"
PORT_FILE = OUT / "spike_out.pdf"
RESULTS = OUT / "results.json"

FLAGS = {
    0x0001: "PAUSED", 0x0002: "ERROR", 0x0004: "DELETING", 0x0008: "SPOOLING",
    0x0010: "PRINTING", 0x0020: "OFFLINE", 0x0040: "PAPEROUT", 0x0080: "PRINTED",
    0x0100: "DELETED", 0x0200: "BLOCKED_DEVQ", 0x0400: "USER_INTERVENTION",
    0x0800: "RESTART", 0x1000: "COMPLETE", 0x2000: "RETAINED",
}


def flag_names(status: int) -> str:
    return "|".join(n for b, n in FLAGS.items() if status & b) or "0"


def open_printer(admin: bool = False):
    if admin:
        return win32print.OpenPrinter(PRINTER, {"DesiredAccess": win32print.PRINTER_ALL_ACCESS})
    return win32print.OpenPrinter(PRINTER)


class SpoolerMonitor(threading.Thread):
    """Samples EnumJobs every 25 ms and records every distinct (job, status, pages) change."""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_flag = threading.Event()
        self.samples = []   # (t_rel_ms, job_id, document, status_names, total_pages, pages_printed)
        self.t0 = time.perf_counter()
        self._last = {}

    def run(self):
        h = open_printer()
        try:
            while not self.stop_flag.is_set():
                try:
                    jobs = win32print.EnumJobs(h, 0, 999, 1)
                except Exception as exc:  # record, do not hide
                    self.samples.append((self._t(), None, f"ENUM_ERROR {exc}", "", 0, 0))
                    time.sleep(0.1)
                    continue
                seen = set()
                for j in jobs:
                    jid = j["JobId"]
                    seen.add(jid)
                    key = (j["Status"], j["TotalPages"], j["PagesPrinted"])
                    if self._last.get(jid) != key:
                        self._last[jid] = key
                        self.samples.append((self._t(), jid, j["pDocument"], flag_names(j["Status"]),
                                             j["TotalPages"], j["PagesPrinted"]))
                for jid in list(self._last):
                    if jid not in seen:
                        self.samples.append((self._t(), jid, None, "GONE", 0, 0))
                        del self._last[jid]
                time.sleep(0.025)
        finally:
            win32print.ClosePrinter(h)

    def _t(self):
        return round((time.perf_counter() - self.t0) * 1000)

    def stop(self):
        self.stop_flag.set()
        self.join(timeout=2)


def settings_string(copies=1, color=False, duplex=False, page_range=None):
    parts = [f"{copies}x", "color" if color else "monochrome",
             "duplexlong" if duplex else "simplex", "fit", "paper=a4"]
    if page_range:
        parts.append(page_range)
    return ",".join(parts)


def run_print(src: str, *, copies=1, color=False, duplex=False, page_range=None,
              timeout_s=90, kill_after_s=None, pause_before=False, cancel_after_s=None):
    """Print one PDF under a unique file name and record everything observable."""
    job_name = f"apjob_{uuid.uuid4().hex[:8]}.pdf"
    tmp = OUT / "tmp"
    tmp.mkdir(exist_ok=True)
    pdf_path = tmp / job_name
    shutil.copyfile(PDFS / src, pdf_path)
    if PORT_FILE.exists():
        PORT_FILE.unlink()

    admin_h = None
    if pause_before:
        admin_h = open_printer(admin=True)
        win32print.SetPrinter(admin_h, 0, None, win32print.PRINTER_CONTROL_PAUSE)

    mon = SpoolerMonitor()
    mon.start()
    time.sleep(0.15)
    cmd = [str(SUMATRA), "-print-to", PRINTER, "-print-settings",
           settings_string(copies, color, duplex, page_range), str(pdf_path)]
    t_launch = time.perf_counter()
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    proc = subprocess.Popen(cmd, startupinfo=si, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    killed = False
    cancelled = False
    exit_code = None
    t_exit = None
    t_gone = None
    deadline = t_launch + timeout_s
    mon_job_id = None
    while time.perf_counter() < deadline:
        if exit_code is None and proc.poll() is not None:
            exit_code = proc.returncode
            t_exit = time.perf_counter()
        if kill_after_s is not None and not killed and time.perf_counter() - t_launch >= kill_after_s and exit_code is None:
            proc.kill()
            killed = True
        # find our job by document name
        ours = [s for s in mon.samples if s[2] and job_name in str(s[2])]
        if ours:
            mon_job_id = ours[0][1]
        if mon_job_id is not None:
            if cancel_after_s is not None and not cancelled and time.perf_counter() - t_launch >= cancel_after_s:
                h = open_printer(admin=True)
                try:
                    win32print.SetJob(h, mon_job_id, 0, None, win32print.JOB_CONTROL_DELETE)
                    cancelled = True
                finally:
                    win32print.ClosePrinter(h)
            gone = [s for s in mon.samples if s[1] == mon_job_id and s[3] == "GONE"]
            if gone and exit_code is not None:
                t_gone = t_launch + gone[0][0] / 1000.0 - (mon.t0 - t_launch) * 0  # placeholder replaced below
                break
        if pause_before and time.perf_counter() - t_launch > 6:
            break
        if exit_code is not None and mon_job_id is None and time.perf_counter() - t_exit > 2.5:
            break  # Sumatra finished but no spooler job ever appeared
        time.sleep(0.02)
    time.sleep(0.3)
    if exit_code is None and proc.poll() is not None:
        exit_code = proc.returncode
    mon.stop()
    stderr = ""
    try:
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode("utf-8", "ignore").strip()[:200]
    except Exception:
        pass

    if admin_h is not None:
        win32print.SetPrinter(admin_h, 0, None, win32print.PRINTER_CONTROL_RESUME)
        win32print.ClosePrinter(admin_h)

    mine = [s for s in mon.samples if mon_job_id is not None and s[1] == mon_job_id]
    first_seen = mine[0][0] if mine else None
    gone_ms = next((s[0] for s in mine if s[3] == "GONE"), None)
    launch_offset_ms = round((t_launch - mon.t0) * 1000)
    out_pages = None
    out_bytes = None
    if PORT_FILE.exists():
        try:
            out_bytes = PORT_FILE.stat().st_size
            out_pages = len(PdfReader(str(PORT_FILE)).pages)
        except Exception as exc:
            out_pages = f"unreadable: {exc}"
    return {
        "src": src, "job_name": job_name, "copies": copies, "color": color, "duplex": duplex,
        "page_range": page_range,
        "spooler_title_matches_filename": bool(mine),
        "titles_seen": sorted({str(s[2]) for s in mon.samples if s[2]})[:3],
        "sumatra_exit_code": exit_code, "sumatra_stderr": stderr, "killed": killed, "cancelled": cancelled,
        "sumatra_exit_ms_after_launch": round((t_exit - t_launch) * 1000) if t_exit else None,
        "job_first_seen_ms_after_launch": (first_seen - launch_offset_ms) if first_seen is not None else None,
        "job_gone_ms_after_launch": (gone_ms - launch_offset_ms) if gone_ms is not None else None,
        "status_sequence": [f"{s[3]}@{s[0]-launch_offset_ms}ms p{s[5]}/{s[4]}" for s in mine],
        "output_file_bytes": out_bytes, "output_pages": out_pages,
    }


def save(name, data):
    existing = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    existing[name] = data
    RESULTS.write_text(json.dumps(existing, indent=1), encoding="utf-8")


def brief(r):
    return (f"{r['src']:34s} exit={r['sumatra_exit_code']} match={r['spooler_title_matches_filename']} "
            f"seen={r['job_first_seen_ms_after_launch']}ms gone={r['job_gone_ms_after_launch']}ms "
            f"out_pages={r['output_pages']} seq={r['status_sequence'][:4]}")


def exp_normal(n=30):
    files = ["t01_1page.pdf", "t02_10pages.pdf", "t03_50pages.pdf",
             "t04_mixed_orientation_6pages.pdf", "t05_scan_like_3pages.pdf", "t06_large.pdf"]
    rows = []
    for i in range(n):
        r = run_print(files[i % len(files)])
        rows.append(r)
        print(i + 1, brief(r), flush=True)
    save("normal", rows)


def exp_settings():
    cases = [
        dict(src="t02_10pages.pdf"),
        dict(src="t02_10pages.pdf", copies=3),
        dict(src="t02_10pages.pdf", page_range="2-4"),
        dict(src="t02_10pages.pdf", page_range="1,3,5-6"),
        dict(src="t02_10pages.pdf", duplex=True),
        dict(src="t02_10pages.pdf", color=True),
        dict(src="t02_10pages.pdf", copies=2, page_range="1-2", duplex=True, color=True),
    ]
    rows = []
    for c in cases:
        r = run_print(**c)
        rows.append(r)
        print(brief(r), c, flush=True)
    save("settings", rows)


def exp_drills():
    rows = {}
    print("D1 paused queue (job must stay queued, then resume)")
    rows["paused_queue"] = run_print("t01_1page.pdf", pause_before=True)
    print(brief(rows["paused_queue"]))
    time.sleep(1)
    print("D2 Sumatra killed mid-process")
    rows["sumatra_killed_at_0.3s"] = run_print("t06_large.pdf", kill_after_s=0.3)
    print(brief(rows["sumatra_killed_at_0.3s"]))
    print("D3 job cancelled in spooler after it appears")
    rows["cancelled_in_spooler"] = run_print("t03_50pages.pdf", cancel_after_s=0.0)
    print(brief(rows["cancelled_in_spooler"]))
    print("D4 nonexistent printer")
    rows["bad_printer"] = "see run_bad_printer()"
    save("drills", rows)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "normal"
    {"normal": exp_normal, "settings": exp_settings, "drills": exp_drills}[which]()
