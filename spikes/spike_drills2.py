"""Phase 1 spike, second set of drills. Throwaway."""
import json
import subprocess
import time

import win32print

import spike_print as sp


def queue_snapshot():
    h = sp.open_printer()
    try:
        return [(j["JobId"], j["pDocument"], sp.flag_names(j["Status"]), j["PagesPrinted"], j["TotalPages"])
                for j in win32print.EnumJobs(h, 0, 999, 1)]
    finally:
        win32print.ClosePrinter(h)


def purge_queue():
    h = sp.open_printer(admin=True)
    try:
        win32print.SetPrinter(h, 0, None, win32print.PRINTER_CONTROL_PURGE)
        win32print.SetPrinter(h, 0, None, win32print.PRINTER_CONTROL_RESUME)
    finally:
        win32print.ClosePrinter(h)


def main():
    out = {}
    print("queue before:", queue_snapshot())

    print("D5 Sumatra killed mid-spool (3s into a 50-page job)")
    r = sp.run_print("t03_50pages.pdf", kill_after_s=3.0, timeout_s=60)
    out["killed_midspool_3s"] = r
    print(sp.brief(r))
    time.sleep(3)
    snap = queue_snapshot()
    out["killed_midspool_queue_after_3s"] = snap
    print("queue 3s after kill:", snap)
    time.sleep(20)
    snap2 = queue_snapshot()
    out["killed_midspool_queue_after_23s"] = snap2
    print("queue 23s after kill:", snap2)
    purge_queue()
    time.sleep(1)

    print("D4 nonexistent printer")
    t = time.perf_counter()
    p = subprocess.run([str(sp.SUMATRA), "-print-to", "NoSuchPrinter-XYZ", "-print-settings", "1x,monochrome,simplex",
                        str(sp.PDFS / "t01_1page.pdf")], capture_output=True, timeout=60)
    out["nonexistent_printer"] = {"exit_code": p.returncode, "seconds": round(time.perf_counter() - t, 1),
                                  "stderr": p.stderr.decode("utf-8", "ignore")[:200]}
    print(out["nonexistent_printer"])

    print("D1b paused queue then resume: does the job complete?")
    h = sp.open_printer(admin=True)
    win32print.SetPrinter(h, 0, None, win32print.PRINTER_CONTROL_PAUSE)
    name_run = sp.run_print("t01_1page.pdf", pause_before=False, timeout_s=8)
    snap_p = queue_snapshot()
    out["paused_queue_state"] = snap_p
    print("while paused:", snap_p)
    win32print.SetPrinter(h, 0, None, win32print.PRINTER_CONTROL_RESUME)
    win32print.ClosePrinter(h)
    t = time.perf_counter()
    while time.perf_counter() - t < 30 and queue_snapshot():
        time.sleep(0.5)
    out["paused_then_resumed_seconds_to_empty"] = round(time.perf_counter() - t, 1)
    print("seconds to empty after resume:", out["paused_then_resumed_seconds_to_empty"], "queue:", queue_snapshot())

    purge_queue()
    out["queue_after_cleanup"] = queue_snapshot()
    sp.save("drills2", out)
    print("queue after cleanup:", out["queue_after_cleanup"])


if __name__ == "__main__":
    main()
