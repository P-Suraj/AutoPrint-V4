"""Load test of the backend on THIS PC only: many customers and several shop computers, real HTTP routes, nothing else.

Starts a local API (uvicorn) with a scratch database and local file storage, exactly like run_local_chain.py, then:
  * creates shops with prices and pairs one computer per shop (pair/start, shop-login, pair/approve, pair/poll)
  * runs every shop's poll loop at the desktop app's real interval (10 s, woken at once after an approve or a print),
    approving (a few rejected, some previewed) and playing the print: claim, download, sent, outcome
  * runs customers through the whole flow: shop + rates, new order, upload intent, PUT, finalize, quote, submit,
    then the status page poll (4 s, like the web page) until every job is final
  * a separate run hits the per-address and per-shop rate limits on purpose and checks they answer 429 cleanly,
    do not touch other callers, and recover at the next 10-minute window

Rate limits are NOT what the pilot and stress runs measure: every simulated customer and shop computer sends its
own X-Forwarded-For address (the API reads the first value of that header), so no per-address limit is reached, and
the shops are sized so the per-shop cap (300 new orders per 10 minutes) is not reached either.

Latency is measured twice: at the client (what a caller waits) and from the API's own request log (time inside the
app, written by its middleware; switched on with uvicorn --log-config, no API change). The gap between the two is
time spent queued in front of the app.

Usage:  apps/api/.venv/Scripts/python.exe e2e/load_test.py [all|pilot|stress|limits] [options]   (see --help)
Local only. It never calls the live site and needs no secret (the maintenance token is random per run).
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import random
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "supabase" / "tests"))
from dbtools import build_database, drop_database  # noqa: E402

RULES = {"bw": {"simplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 200}],
                "duplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 120}]},
         "color": {"simplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 1000}],
                   "duplex": [{"from_sides": 1, "to_sides": None, "paise_per_side": 800}]}}
MAX_UPLOAD = 26_214_400                      # the API's limit (25 MiB)
SHOP_POLL_SECONDS = 10.0                     # AgentService._pollEvery
CUSTOMER_POLL_SECONDS, CUSTOMER_POLL_SLOW, CUSTOMER_SLOW_AFTER = 4.0, 8.0, 120.0     # OrderPage.tsx
OPEN = {"awaiting_approval", "approved", "printing"}
CONTRACT = {"X-AutoPrint-Contract-Version": "1"}
OK = (200, 201, 204)


# ---------------------------------------------------------------- PDFs
def build_pdf(pages: int, target_bytes: int | None = None, seed: int = 1) -> bytes:
    """A valid PDF with one content stream per page. With target_bytes the result is exactly that long (random,
    incompressible streams, like scanned pages)."""
    rng = random.Random(seed)

    def make(lengths: list[int]) -> bytes:
        objs = [b"<</Type/Catalog/Pages 2 0 R>>",
                ("<</Type/Pages/Kids[" + " ".join(f"{3 + 2 * i} 0 R" for i in range(pages)) + f"]/Count {pages}>>").encode()]
        for i, n in enumerate(lengths):
            objs.append(f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents {4 + 2 * i} 0 R>>".encode())
            body = random.Random(seed * 1000 + i).randbytes(n) if target_bytes else b"0 0 m 100 100 l S".ljust(n)
            objs.append(b"<</Length %d>>\nstream\n" % n + body + b"\nendstream")
        buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(objs, start=1):
            offsets.append(len(buf))
            buf += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref_at = len(buf)
        buf += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
        for off in offsets:
            buf += f"{off:010d} 00000 n \n".encode()
        buf += f"trailer\n<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref_at}\n%%EOF\n".encode()
        return bytes(buf)

    if target_bytes is None:
        return make([40 + rng.randrange(20)] * pages)
    lengths = [max(1, (target_bytes - 400 * pages - 400) // pages)] * pages
    for _ in range(8):
        data = make(lengths)
        if len(data) == target_bytes:
            return data
        lengths[-1] += target_bytes - len(data)
    raise RuntimeError("could not size the PDF")


def file_pool(max_mb: float) -> list[dict]:
    """The mix of documents customers send: mostly small, some large, a few exactly at the size limit."""
    cap = int(min(max_mb * 1024 * 1024, MAX_UPLOAD))
    spec = [("1 page, tiny", 1, None, 28), ("12 pages, tiny", 12, None, 22), ("150 pages, tiny", 150, None, 6),
            ("4 pages, 300 KB", 4, 300_000, 14), ("10 pages, 1 MB", 10, 1_000_000, 12), ("30 pages, 5 MB", 30, 5_000_000, 9),
            ("80 pages, 12 MB", 80, 12_000_000, 5), ("120 pages, 25 MiB (the limit)", 120, MAX_UPLOAD, 4)]
    pool = []
    for i, (label, pages, size, weight) in enumerate(spec):
        if size and size > cap:
            size = cap
        data = build_pdf(pages, size, seed=i + 1)
        n = len(data)
        pool.append({"label": label, "pages": pages, "data": data, "weight": weight, "sha": hashlib.sha256(data).hexdigest(),
                     "cls": "<=1 MB" if n <= 1_048_576 else ("1-12 MB" if n <= 12_000_000 else "25 MiB")})
    return pool


# ---------------------------------------------------------------- measurements
def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    v = sorted(values)
    return v[min(len(v) - 1, max(0, int(round(p / 100 * (len(v) - 1)))))]


class Stats:
    def __init__(self) -> None:
        self.ms: dict[str, list[float]] = defaultdict(list)
        self.outcomes: dict[str, Counter] = defaultdict(Counter)
        self.detail: dict[str, list[float]] = defaultdict(list)       # e.g. finalize by file size

    def add(self, route: str, ms: float, outcome: str, detail: str | None = None) -> None:
        self.ms[route].append(ms)
        self.outcomes[route][outcome] += 1
        if detail:
            self.detail[f"{route}  [{detail}]"].append(ms)


class Ctx:
    def __init__(self, base: str, token: str, http: httpx.AsyncClient, sync: httpx.Client, args) -> None:
        self.base, self.token, self.http, self.sync, self.args = base, token, http, sync, args
        self.stats = Stats()
        self.submitted: dict[str, float] = {}     # job id -> when the customer got the submit answer
        self.seen: dict[str, float] = {}          # job id -> when a shop poll first returned it
        self.flow_failures: Counter = Counter()
        self.finals: Counter = Counter()
        self.to_printing: list[float] = []
        self.to_final: list[float] = []
        self.new_to_submitted: list[float] = []
        self.stuck: list[str] = []
        self.loop_lag: list[float] = []
        self.probe: dict[str, list[float]] = {}
        self.server_cpu: float | None = None


class FlowFailed(Exception):
    pass


def outcome_of(r: httpx.Response) -> str:
    try:
        code = r.json()["error"]["code"]
    except Exception:
        code = "?"
    return f"{r.status_code} {code}"


async def req(ctx: Ctx, route: str, method: str, path: str, *, retries: int = 3, detail: str | None = None, **kw) -> httpx.Response:
    """One measured request. 503 and transport failures are counted, then retried after 2 s as the web page and the
    shop app do; any other refusal is counted and raised as a failed flow."""
    last = "?"
    for attempt in range(retries + 1):
        t = time.perf_counter()
        try:
            r = await ctx.http.request(method, ctx.base + path, **kw)
        except httpx.HTTPError as e:
            last = f"ERR {type(e).__name__}"
            ctx.stats.add(route, (time.perf_counter() - t) * 1000, last, detail)
        else:
            ms = (time.perf_counter() - t) * 1000
            if r.status_code in OK:
                ctx.stats.add(route, ms, "ok", detail)
                return r
            last = outcome_of(r)
            ctx.stats.add(route, ms, last, detail)
            if r.status_code != 503:
                break
        if attempt < retries:
            await asyncio.sleep(2)
    raise FlowFailed(f"{route}: {last}")


def blocking(ctx: Ctx, method: str, url: str, **kw) -> tuple[float, str, bytes]:
    """Large bodies go through a plain thread so they do not hold up the load generator's own event loop."""
    t = time.perf_counter()
    try:
        r = ctx.sync.request(method, url, **kw)
        return (time.perf_counter() - t) * 1000, ("ok" if r.status_code in OK else outcome_of(r)), r.content
    except httpx.HTTPError as e:
        return (time.perf_counter() - t) * 1000, f"ERR {type(e).__name__}", b""


# ---------------------------------------------------------------- the shop computer
class ShopSim:
    def __init__(self, ctx: Ctx, index: int, code: str, rng: random.Random) -> None:
        # its own connection, like a real shop PC (and one shared client pool for hundreds of callers is slow in httpx
        # itself, which would be measured as server latency)
        self.ctx, self.code, self.rng = copy.copy(ctx), code, rng
        self.ctx.http = httpx.AsyncClient(timeout=60, verify=False)
        self.addr = {"X-Forwarded-For": f"172.16.{index // 250}.{index % 250 + 1}"}
        self.headers: dict[str, str] = {}
        self.wake, self.stop = asyncio.Event(), asyncio.Event()
        self.todo: asyncio.Queue = asyncio.Queue()
        self.decided: set[str] = set()
        self.printing: asyncio.Task | None = None
        self.last_jobs: list[dict] = []
        self.pages: dict[str, int] = {}

    async def setup(self) -> None:
        ctx, admin = self.ctx, {"X-Maintenance-Token": self.ctx.token}
        await req(ctx, "POST /v1/internal/shop", "POST", "/v1/internal/shop", headers=admin,
                  json={"code": self.code, "name": f"Load Shop {self.code}", "rules": RULES})
        poll_token, secret = secrets.token_hex(32), secrets.token_hex(32)
        start = await req(ctx, "POST /v1/agent/pair/start", "POST", "/v1/agent/pair/start", headers=self.addr,
                          json={"display_name": f"PC-{self.code}", "poll_token": poll_token, "device_secret": secret})
        login = await req(ctx, "POST /v1/internal/shop-login", "POST", "/v1/internal/shop-login", headers=admin,
                          json={"shop_code": self.code, "label": "load"})
        key = {"X-Shop-Key": login.json()["key"]}
        await req(ctx, "POST /v1/shop/pair/approve", "POST", "/v1/shop/pair/approve", headers=key, json={"pair_code": start.json()["pair_code"]})
        polled = (await req(ctx, "POST /v1/agent/pair/poll", "POST", "/v1/agent/pair/poll", json={"poll_token": poll_token})).json()
        assert polled["status"] == "approved", polled
        self.headers = {"X-Device-Id": polled["device_id"], "X-Device-Secret": secret, "X-Agent-Version": "load-test", **CONTRACT, **self.addr}

    async def poll(self) -> None:
        try:
            r = await req(self.ctx, "GET /v1/agent/jobs", "GET", "/v1/agent/jobs", headers=self.headers, retries=0)
        except FlowFailed:
            return
        now = time.perf_counter()
        self.last_jobs = r.json()["jobs"]
        for j in self.last_jobs:
            self.ctx.seen.setdefault(j["job_id"], now)
            self.pages[j["job_id"]] = j["page_count"]
            if j["status"] == "awaiting_approval" and j["job_id"] not in self.decided:
                self.decided.add(j["job_id"])
                self.todo.put_nowait(j["job_id"])
        if any(j["status"] == "approved" for j in self.last_jobs) and (self.printing is None or self.printing.done()):
            self.printing = asyncio.create_task(self.print_approved())

    async def run(self) -> None:
        """AgentService.RunAsync: poll, then wait 10 s or until woken."""
        await asyncio.sleep(self.rng.random() * SHOP_POLL_SECONDS)       # shops do not all start on the same second
        while not self.stop.is_set():
            await self.poll()
            try:
                await asyncio.wait_for(self.wake.wait(), SHOP_POLL_SECONDS)
            except asyncio.TimeoutError:
                pass
            self.wake.clear()

    async def shopkeeper(self) -> None:
        """The person at the counter: looks at a card, sometimes opens the preview, approves (rarely rejects)."""
        ctx = self.ctx
        while True:
            job = await self.todo.get()
            await asyncio.sleep(ctx.args.approve_seconds)
            try:
                if self.rng.random() < 0.25:
                    doc = (await req(ctx, "GET /v1/agent/jobs/{job_id}/document", "GET", f"/v1/agent/jobs/{job}/document", headers=self.headers)).json()
                    await self.download(doc["download_url"], doc["sha256"], doc["byte_size"])
                if self.rng.random() < 0.05:
                    await req(ctx, "POST /v1/agent/jobs/{job_id}/reject", "POST", f"/v1/agent/jobs/{job}/reject", headers=self.headers, json={"reason": "load test"})
                else:
                    await req(ctx, "POST /v1/agent/jobs/{job_id}/approve", "POST", f"/v1/agent/jobs/{job}/approve", headers=self.headers)
            except FlowFailed as e:
                ctx.flow_failures[f"shop: {e}"] += 1
            self.wake.set()                                              # the app polls at once after a decision

    async def download(self, url: str, sha: str, size: int) -> bool:
        cls = "<=1 MB" if size <= 1_048_576 else ("1-12 MB" if size <= 12_000_000 else "25 MiB")
        ms, outcome, body = await asyncio.to_thread(blocking, self.ctx, "GET", url)
        good = outcome == "ok" and await asyncio.to_thread(lambda: hashlib.sha256(body).hexdigest() == sha)
        self.ctx.stats.add("GET /v1/dev-storage/{key:path}", ms, outcome if outcome != "ok" or good else "wrong bytes", cls)
        return bool(good)

    async def print_approved(self) -> None:
        """AgentService.PrintApprovedAsync + PrintOrchestrator.RunOnceAsync, with the printer replaced by a sleep."""
        ctx = self.ctx
        try:
            while True:
                r = await req(ctx, "POST /v1/agent/claim", "POST", "/v1/agent/claim", headers=self.headers)
                c = r.json()
                if c["status"] != "claimed":
                    break
                auth = {"attempt_token": c["attempt_token"]}
                got = await self.download(c["document"]["download_url"], c["document"]["sha256"], c["document"]["byte_size"])
                pages = c["document"]["page_count"] or 1
                if not got:
                    await req(ctx, "POST /v1/agent/attempts/{attempt_id}/outcome", "POST", f"/v1/agent/attempts/{c['attempt_id']}/outcome",
                              headers=self.headers, json={**auth, "outcome": "failed", "evidence": {"reason": "download_failed", "printed": False}})
                    continue
                await req(ctx, "POST /v1/agent/attempts/{attempt_id}/sent", "POST", f"/v1/agent/attempts/{c['attempt_id']}/sent", headers=self.headers, json=auth)
                await asyncio.sleep(ctx.args.print_seconds)
                evidence = {"rule_version": 2, "spooler_job_seen": True, "printing_seen": True, "left_queue": True,
                            "flags_seen": ["SPOOLING", "PRINTING"], "max_pages_printed": pages, "expected_pages": pages}
                await req(ctx, "POST /v1/agent/attempts/{attempt_id}/outcome", "POST", f"/v1/agent/attempts/{c['attempt_id']}/outcome",
                          headers=self.headers, json={**auth, "outcome": "completed", "evidence": evidence})
                self.wake.set()
        except FlowFailed as e:
            ctx.flow_failures[f"shop: {e}"] += 1
        finally:
            self.wake.set()


# ---------------------------------------------------------------- the customer
async def customer(ctx: Ctx, n: int, shop: str, start_at: float, pool: list[dict], rng: random.Random, scen: int) -> None:
    await asyncio.sleep(max(0.0, start_at - time.perf_counter()))
    ctx = copy.copy(ctx)                                                 # same counters, but this phone's own connection
    async with httpx.AsyncClient(timeout=60, verify=False) as ctx.http:
        await customer_flow(ctx, n, shop, pool, rng, scen)


async def customer_flow(ctx: Ctx, n: int, shop: str, pool: list[dict], rng: random.Random, scen: int) -> None:
    addr = {"X-Forwarded-For": f"10.{scen}.{n // 250}.{n % 250 + 1}"}
    think = lambda: asyncio.sleep(rng.uniform(*ctx.args.think))          # noqa: E731
    try:
        info, _ = await asyncio.gather(                                  # the page loads both at once
            req(ctx, "GET /v1/shops/{shop_code}", "GET", f"/v1/shops/{shop}", headers=addr),
            req(ctx, "GET /v1/shops/{shop_code}/rates", "GET", f"/v1/shops/{shop}/rates", headers=addr))
        if not info.json()["accepting_orders"]:
            raise FlowFailed("shop not accepting")
        await think()
        t_new = time.perf_counter()
        o = (await req(ctx, "POST /v1/shops/{shop_code}/orders", "POST", f"/v1/shops/{shop}/orders", headers=addr)).json()
        h = {"X-Order-Secret": o["order_secret"], **addr}
        oid = o["order_id"]
        items = []
        # customer 3 of every run sends the largest allowed file, so the limit is always exercised
        files = [pool[-1]] if n == 3 else rng.choices(pool, weights=[f["weight"] for f in pool], k=1 if rng.random() < 0.8 else 2)
        for f in files:
            reg = (await req(ctx, "POST /v1/orders/{order_id}/documents", "POST", f"/v1/orders/{oid}/documents", headers=h,
                             json={"file_name": f"load_{n}.pdf", "byte_size": len(f["data"]), "content_type": "application/pdf"})).json()
            ms, outcome, _ = await asyncio.to_thread(blocking, ctx, "PUT", reg["upload_url"], content=f["data"], headers=reg["upload_headers"])
            ctx.stats.add("PUT /v1/dev-storage/{key:path}", ms, outcome, f["cls"])
            if outcome != "ok":
                raise FlowFailed(f"PUT upload: {outcome}")
            fin = (await req(ctx, "POST /v1/orders/{order_id}/documents/{document_id}/finalize", "POST",
                             f"/v1/orders/{oid}/documents/{reg['document_id']}/finalize", headers=h, detail=f["cls"])).json()
            if fin["page_count"] != f["pages"] or fin["sha256"] != f["sha"]:
                raise FlowFailed("finalize: wrong page count or hash")
            items.append({"document_id": reg["document_id"], "options": {"copies": rng.choice([1, 1, 1, 2]), "duplex": rng.random() < 0.3}})
        await think()
        q = (await req(ctx, "POST /v1/orders/{order_id}/quote", "POST", f"/v1/orders/{oid}/quote", headers=h, json={"items": items})).json()
        await think()
        sub = (await req(ctx, "POST /v1/orders/{order_id}/submit", "POST", f"/v1/orders/{oid}/submit", headers=h, json={"quote_id": q["quote_id"]})).json()
        t_sub = time.perf_counter()
        ctx.new_to_submitted.append(t_sub - t_new)
        for j in sub["job_ids"]:
            ctx.submitted[j] = t_sub
    except FlowFailed as e:
        ctx.flow_failures[f"customer: {e}"] += 1
        return

    saw_printing = False
    while True:
        waited = time.perf_counter() - t_sub
        if waited > ctx.args.final_timeout:
            ctx.stuck.append(f"order {o['short_code']} at {shop}: not final after {waited:.0f}s")
            return
        try:
            v = (await req(ctx, "GET /v1/orders/{order_id}", "GET", f"/v1/orders/{oid}", headers=h, retries=0)).json()
            states = [j["status"] for j in v["jobs"]]
            if not saw_printing and any(s not in ("awaiting_approval", "approved") for s in states):
                saw_printing = True
                ctx.to_printing.append(time.perf_counter() - t_sub)
            if states and not any(s in OPEN for s in states):
                ctx.to_final.append(time.perf_counter() - t_sub)
                for s in states:
                    ctx.finals[s] += 1
                return
        except FlowFailed:
            pass                                                         # the page keeps polling after a failed poll
        await asyncio.sleep(CUSTOMER_POLL_SLOW if waited > CUSTOMER_SLOW_AFTER else CUSTOMER_POLL_SECONDS)


# ---------------------------------------------------------------- the local API
class Server:
    def __init__(self, port: int) -> None:
        self.port, self.base = port, f"http://127.0.0.1:{port}"
        self.token = secrets.token_hex(24)                               # throwaway: lives only for this run
        self.name = "v4_load_" + uuid.uuid4().hex[:8]
        self.tmp: Path | None = None
        self.proc: subprocess.Popen | None = None
        self.db_built = False

    def start(self) -> "Server":
        s = socket.socket()
        busy = s.connect_ex(("127.0.0.1", self.port)) == 0
        s.close()
        if busy:
            raise SystemExit(f"port {self.port} is already in use; pass --port")
        url = build_database(self.name)
        self.db_built = True
        self.url = url
        self.tmp = Path(tempfile.mkdtemp(prefix="ap_load_"))
        # the API already logs "METHOD route status ms" at INFO; this only gives that logger somewhere to write
        cfg = {"version": 1, "disable_existing_loggers": False,
               "formatters": {"m": {"format": "%(message)s"}, "d": {"format": "%(levelname)s %(name)s %(message)s"}},
               "handlers": {"req": {"class": "logging.FileHandler", "filename": str(self.tmp / "requests.log"), "formatter": "m", "encoding": "utf-8"},
                            "err": {"class": "logging.FileHandler", "filename": str(self.tmp / "server.log"), "formatter": "d", "encoding": "utf-8"}},
               "loggers": {"autoprint.api": {"level": "INFO", "handlers": ["req"], "propagate": False}},
               "root": {"level": "WARNING", "handlers": ["err"]}}
        (self.tmp / "log.json").write_text(json.dumps(cfg))
        env = dict(os.environ, AUTOPRINT_V4_DATABASE_URL=url, AUTOPRINT_V4_STORAGE_BACKEND="local",
                   AUTOPRINT_V4_LOCAL_STORAGE_DIR=str(self.tmp / "files"), AUTOPRINT_V4_SIGNING_KEY="e" * 40,
                   AUTOPRINT_V4_PUBLIC_BASE_URL=self.base, AUTOPRINT_V4_MAINTENANCE_TOKEN=self.token,
                   AUTOPRINT_V4_ENVIRONMENT="development", AUTOPRINT_V4_ALLOWED_ORIGINS="")
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.asgi:app", "--port", str(self.port),
                                      "--log-config", str(self.tmp / "log.json")], cwd=ROOT / "apps" / "api", env=env)
        end = time.time() + 60
        while True:
            try:
                if httpx.get(self.base + "/health/ready", timeout=2).status_code == 200:
                    return self
            except httpx.HTTPError:
                pass
            if time.time() > end or self.proc.poll() is not None:
                self.stop()
                raise SystemExit("the local API did not start")
            time.sleep(0.3)

    def stop(self) -> tuple[dict[str, list[float]], Counter]:
        """Stops the API, returns (server-side ms per route, counts of error lines it logged), removes everything."""
        server_ms: dict[str, list[float]] = defaultdict(list)
        errors: Counter = Counter()
        if self.proc is not None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True)
            else:
                self.proc.terminate()
            self.proc = None
            time.sleep(1)
        if self.tmp is not None:
            line = re.compile(r"^(GET|POST|PUT|DELETE) (\S+) (\d{3}) (\d+)ms$")
            for name in ("requests.log", "server.log"):
                p = self.tmp / name
                for text in (p.read_text(encoding="utf-8", errors="replace").splitlines() if p.exists() else []):
                    m = line.match(text)
                    if m:
                        server_ms[f"{m[1]} {m[2]}"].append(float(m[4]))
                    elif re.match(r"^(ERROR|WARNING|CRITICAL) |^(dependency failure|unhandled|rate limiter|cleanup|maintenance|could not|download link)", text):
                        errors[text[:110]] += 1
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None
        if self.db_built:
            drop_database(self.name)
            self.db_built = False
        return server_ms, errors


def clients() -> tuple[httpx.AsyncClient, httpx.Client]:
    lim = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    return httpx.AsyncClient(timeout=60, limits=lim, verify=False), httpx.Client(timeout=120, limits=lim, verify=False)


async def lag_monitor(ctx: Ctx) -> None:
    """How late this script's own event loop runs: an upper bound on the error in the client-side numbers."""
    while True:
        t = time.perf_counter()
        await asyncio.sleep(0.05)
        ctx.loop_lag.append((time.perf_counter() - t - 0.05) * 1000)


def shop_code(i: int) -> str:
    return f"L{chr(65 + i // 26)}{chr(65 + i % 26)}{100 + i}"



# ---------------------------------------------------------------- independent checks on the measurement
def probe_main(base: str, shop: str) -> int:
    """Runs as a separate process (its own interpreter, so the load generator cannot slow it down): every 0.25 s one
    GET /health (no database) and one GET /v1/shops/CODE (one database round trip). Prints its timings when stdin closes."""
    import threading
    stop = threading.Event()
    threading.Thread(target=lambda: (sys.stdin.read(), stop.set()), daemon=True).start()
    out: dict[str, list[float]] = {"health": [], "shop": []}
    with httpx.Client(timeout=60) as c:
        while not stop.is_set():
            for name, path in (("health", "/health"), ("shop", f"/v1/shops/{shop}")):
                t = time.perf_counter()
                try:
                    c.get(base + path, headers={"X-Forwarded-For": "192.0.2.1"})
                    out[name].append((time.perf_counter() - t) * 1000)
                except httpx.HTTPError:
                    out[name].append(60000.0)
            stop.wait(0.25)
    print(json.dumps(out))
    return 0


def process_tree_cpu_seconds(pid: int) -> float | None:
    """CPU time used so far by the API process and its children (the venv's python.exe starts the real interpreter
    as a child). Windows only; returns None when it cannot be read."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        found = subprocess.run(["powershell", "-NoProfile", "-Command",
                                f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={pid}').ProcessId"],
                               capture_output=True, text=True, timeout=30).stdout.split()
        total = 0.0
        k = ctypes.windll.kernel32
        k.OpenProcess.restype = wintypes.HANDLE
        for p in [pid] + [int(x) for x in found if x.isdigit()]:
            h = k.OpenProcess(0x1000, False, p)                           # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                continue
            times = [wintypes.FILETIME() for _ in range(4)]
            if k.GetProcessTimes(wintypes.HANDLE(h), *[ctypes.byref(t) for t in times]):
                total += sum(((t.dwHighDateTime << 32) + t.dwLowDateTime) / 1e7 for t in times[2:])
            k.CloseHandle(wintypes.HANDLE(h))
        return total
    except Exception:
        return None


# ---------------------------------------------------------------- scenarios
async def run_load(server: Server, args, label: str, n_shops: int, n_customers: int, ramp: float, pool: list[dict], scen: int) -> Ctx:
    http, sync = clients()
    ctx = Ctx(server.base, server.token, http, sync, args)
    rng = random.Random(args.seed + scen)
    tasks: list[asyncio.Task] = []
    shops: list[ShopSim] = []
    try:
        shops = [ShopSim(ctx, i, shop_code(i), random.Random(args.seed * 100 + i)) for i in range(n_shops)]
        await asyncio.gather(*(s.setup() for s in shops))
        tasks = [asyncio.create_task(c) for s in shops for c in (s.run(), s.shopkeeper())] + [asyncio.create_task(lag_monitor(ctx))]
        await asyncio.sleep(1)
        print(f"[{label}] {n_shops} shops paired; {n_customers} customers arriving over {ramp:.0f}s ...", flush=True)
        probe = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--probe", server.base, shops[0].code],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        cpu0 = await asyncio.to_thread(process_tree_cpu_seconds, server.proc.pid)
        t0 = time.perf_counter()
        ctx.started = t0
        await asyncio.gather(*(customer(ctx, n, rng.choice(shops).code, t0 + rng.random() * ramp, pool, random.Random(args.seed * 7919 + n), scen)
                               for n in range(n_customers)))
        ctx.wall = time.perf_counter() - t0
        cpu1 = await asyncio.to_thread(process_tree_cpu_seconds, server.proc.pid)
        ctx.server_cpu = None if cpu0 is None or cpu1 is None else (cpu1 - cpu0) / ctx.wall
        try:
            ctx.probe = json.loads((await asyncio.to_thread(probe.communicate, "stop", 30))[0].strip().splitlines()[-1])
        except Exception:
            probe.kill()
            ctx.probe = {}
        for s in shops:
            s.stop.set()
            s.wake.set()
        await asyncio.sleep(0.5)
        ctx.left_open = Counter()
        for s in shops:                                                  # what the shops' queues look like at the end
            await s.poll()
            for j in s.last_jobs:
                if j["status"] in OPEN or j["status"] == "needs_attention":
                    ctx.left_open[j["status"]] += 1
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for s in shops:
            await s.ctx.http.aclose()
        await http.aclose()
        sync.close()
    return ctx


async def limits_hit(server: Server, args) -> dict:
    """Reach three limits on purpose: new orders per address (60 / 10 min), pairing codes per address (12 / 10 min),
    new orders per shop (300 / 10 min). Returns what is needed to check recovery later."""
    left = 600 - time.time() % 600
    if left < 40:                                                        # do not let the window roll over mid-flood
        print(f"[limits] waiting {left + 1:.0f}s for a fresh 10-minute window ...", flush=True)
        await asyncio.sleep(left + 1)
    http, sync = clients()
    ctx = Ctx(server.base, server.token, http, sync, args)
    checks: list[tuple[str, bool, str]] = []
    admin = {"X-Maintenance-Token": server.token}
    for code in ("LMA001", "LMB002", "LMC003"):
        await req(ctx, "setup", "POST", "/v1/internal/shop", headers=admin, json={"code": code, "name": "Limit Shop", "rules": RULES})
    gate = asyncio.Semaphore(8)

    async def hit(route: str, method: str, path: str, **kw) -> tuple[int, str, dict]:
        async with gate:
            t = time.perf_counter()
            r = await http.request(method, server.base + path, **kw)
            ms = (time.perf_counter() - t) * 1000
            code = "ok" if r.status_code in OK else outcome_of(r)
            ctx.stats.add(f"{route}  -> {r.status_code}", ms, "ok" if r.status_code in OK + (429,) else code)
            return r.status_code, code, dict(r.headers)

    one = {"X-Forwarded-For": "198.51.100.7"}
    res = await asyncio.gather(*(hit("POST new order, one address", "POST", "/v1/shops/LMA001/orders", headers=one) for _ in range(75)))
    n201, n429 = sum(r[0] == 201 for r in res), sum(r[1] == "429 rate_limited" for r in res)
    checks.append(("one address, 75 new orders: 60 accepted, 15 refused with 429 rate_limited", (n201, n429) == (60, 15), f"{n201} x 201, {n429} x 429"))
    refused = [r for r in res if r[0] == 429]
    checks.append(("the refusals carry Cache-Control: no-store and the contract header",
                   bool(refused) and all(r[2].get("cache-control") == "no-store" and "x-autoprint-contract-version" in r[2] for r in refused), ""))
    other = await hit("POST new order, another address meanwhile", "POST", "/v1/shops/LMA001/orders", headers={"X-Forwarded-For": "198.51.100.8"})
    checks.append(("a different address is not affected", other[0] == 201, str(other[0])))
    reads = await asyncio.gather(hit("GET shop, limited address", "GET", "/v1/shops/LMA001", headers=one),
                                 hit("GET rates, limited address", "GET", "/v1/shops/LMA001/rates", headers=one))
    checks.append(("the limited address can still read the shop and its prices", all(r[0] == 200 for r in reads), ""))

    pair = lambda: {"display_name": "PC", "poll_token": secrets.token_hex(32), "device_secret": secrets.token_hex(32)}  # noqa: E731
    res = await asyncio.gather(*(hit("POST pair/start, one address", "POST", "/v1/agent/pair/start", headers=one, json=pair()) for _ in range(16)))
    n201, n429 = sum(r[0] == 201 for r in res), sum(r[1] == "429 rate_limited" for r in res)
    checks.append(("one address, 16 pairing codes: 12 issued, 4 refused", (n201, n429) == (12, 4), f"{n201} x 201, {n429} x 429"))

    res = await asyncio.gather(*(hit("POST new order, one shop, many addresses", "POST", "/v1/shops/LMB002/orders",
                                     headers={"X-Forwarded-For": f"203.0.{i // 250}.{i % 250 + 1}"}) for i in range(315)))
    n201, n429 = sum(r[0] == 201 for r in res), sum(r[1] == "429 rate_limited" for r in res)
    checks.append(("one shop, 315 new orders from 315 addresses: 300 accepted, 15 refused", (n201, n429) == (300, 15), f"{n201} x 201, {n429} x 429"))
    other = await hit("POST new order, another shop meanwhile", "POST", "/v1/shops/LMC003/orders", headers={"X-Forwarded-For": "203.0.9.9"})
    checks.append(("another shop is not affected", other[0] == 201, str(other[0])))
    return {"ctx": ctx, "http": http, "sync": sync, "checks": checks, "hit": hit, "one": one, "pair": pair, "window_ends": time.time() + 600 - time.time() % 600}


async def limits_recover(state: dict, args) -> None:
    checks, hit, one = state["checks"], state["hit"], state["one"]
    try:
        if args.no_recovery_wait:
            checks.append(("recovery at the next 10-minute window", True, "NOT CHECKED (--no-recovery-wait)"))
            return
        wait = state["window_ends"] - time.time() + 2
        if wait > 0:
            print(f"[limits] waiting {wait:.0f}s for the next 10-minute window to check recovery ...", flush=True)
            await asyncio.sleep(wait)
        a = await hit("POST new order, one address, next window", "POST", "/v1/shops/LMA001/orders", headers=one)
        b = await hit("POST pair/start, one address, next window", "POST", "/v1/agent/pair/start", headers=one, json=state["pair"]())
        c = await hit("POST new order, capped shop, next window", "POST", "/v1/shops/LMB002/orders", headers={"X-Forwarded-For": "203.0.9.10"})
        checks.append(("after the window: the limited address, pairing and the capped shop all work again",
                       (a[0], b[0], c[0]) == (201, 201, 201), f"{a[0]}, {b[0]}, {c[0]}"))
    finally:
        await state["http"].aclose()
        state["sync"].close()


# ---------------------------------------------------------------- report
def table(title: str, stats: Stats, server_ms: dict[str, list[float]]) -> None:
    print(f"\n{title}")
    head = f"  {'route':<58} {'n':>5} {'fail':>4} {'p50':>7} {'p90':>7} {'p99':>7} {'max':>7} | {'app p50':>7} {'app p90':>7} {'app max':>7}"
    print(head)
    print("  " + "-" * (len(head) - 2))
    for route in sorted(stats.ms, key=lambda r: (-pct(stats.ms[r], 90))):
        v, fails = stats.ms[route], sum(n for k, n in stats.outcomes[route].items() if k != "ok")
        sv = server_ms.get(route, [])
        app = f"{pct(sv, 50):>7.0f} {pct(sv, 90):>7.0f} {max(sv):>7.0f}" if sv else f"{'-':>7} {'-':>7} {'-':>7}"
        print(f"  {route:<58} {len(v):>5} {fails:>4} {pct(v, 50):>7.0f} {pct(v, 90):>7.0f} {pct(v, 99):>7.0f} {max(v):>7.0f} | {app}")
    if stats.detail:
        print("  by file size (client side):")
        for route in sorted(stats.detail):
            v = stats.detail[route]
            print(f"  {route:<58} {len(v):>5} {'':>4} {pct(v, 50):>7.0f} {pct(v, 90):>7.0f} {pct(v, 99):>7.0f} {max(v):>7.0f} |")


def report_load(label: str, ctx: Ctx, server_ms: dict[str, list[float]], server_errors: Counter, n_customers: int) -> bool:
    table(f"=== {label}: latency in milliseconds (client side | inside the app, from the API's own log) ===", ctx.stats, server_ms)
    lags = [ctx.seen[j] - t for j, t in ctx.submitted.items() if j in ctx.seen]
    never = [j for j in ctx.submitted if j not in ctx.seen]
    line = lambda name, v, unit="s": print(f"  {name:<52} n={len(v):<4} p50={pct(v, 50):6.2f}{unit} p90={pct(v, 90):6.2f}{unit} max={max(v) if v else float('nan'):6.2f}{unit}")  # noqa: E731
    print("\n  what people wait for:")
    line("customer: new order -> submitted (with think time)", ctx.new_to_submitted)
    line("submit answered -> job in a shop poll answer", [max(0.0, x) for x in lags])
    line("submit answered -> customer page shows printing", ctx.to_printing)
    line("submit answered -> customer page shows the end", ctx.to_final)
    line("load generator event-loop lag (measurement error)", [x / 1000 for x in ctx.loop_lag])
    for name, what in (("health", "GET /health (no database)"), ("shop", "GET /v1/shops/CODE (one database round trip)")):
        v = ctx.probe.get(name, [])
        if v:
            print(f"  separate probe process, {what:<44} n={len(v):<4} p50={pct(v, 50):6.0f}ms p90={pct(v, 90):6.0f}ms p99={pct(v, 99):6.0f}ms max={max(v):6.0f}ms")
    if ctx.server_cpu is not None:
        print(f"  API process CPU during the run: {ctx.server_cpu * 100:.0f}% of one core on average (it is one Python process: 100% means it is the limit)")
    bad: Counter = Counter()
    limited = 0
    for route, outs in ctx.stats.outcomes.items():
        for k, n in outs.items():
            if k.startswith("429"):
                limited += n
            elif k != "ok":
                bad[f"{route}: {k}"] += n
    total = sum(len(v) for v in ctx.stats.ms.values())
    print(f"\n  requests: {total} in {ctx.wall:.0f}s; rate-limited (429): {limited}; failed for any other reason: {sum(bad.values())}")
    for k, n in bad.most_common():
        print(f"    {n:>4} x {k}")
    print(f"  customers: {n_customers}; jobs submitted: {len(ctx.submitted)}; final job states seen by customers: {dict(ctx.finals)}")
    print(f"  flows that broke: {sum(ctx.flow_failures.values())}" + "".join(f"\n    {n:>4} x {k}" for k, n in ctx.flow_failures.most_common()))
    print(f"  orders not final within {ctx.args.final_timeout:.0f}s: {len(ctx.stuck)}" + "".join(f"\n    {s}" for s in ctx.stuck[:10]))
    print(f"  jobs never seen by their shop: {len(never)}; jobs left open in shop queues at the end: {dict(ctx.left_open) or 0}")
    print(f"  error lines in the API log: {sum(server_errors.values())}" + "".join(f"\n    {n:>4} x {k}" for k, n in server_errors.most_common(8)))
    ok = not bad and not ctx.flow_failures and not ctx.stuck and not never and not ctx.left_open and not limited
    print(f"  verdict: {'CLEAN (every flow finished, no failed request, no rate limit touched)' if ok else 'PROBLEMS, see above'}")
    return ok


def report_limits(state: dict, server_ms: dict[str, list[float]], server_errors: Counter) -> bool:
    table("=== limits: latency in milliseconds (client side) ===", state["ctx"].stats, {})
    sv = server_ms.get("POST /v1/shops/{shop_code}/orders", [])
    if sv:
        print(f"  inside the app, POST new order (accepted and refused together): p50={pct(sv, 50):.0f} p90={pct(sv, 90):.0f} max={max(sv):.0f}")
    print()
    for name, ok, note in state["checks"]:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{note}]" if note else ""))
    print(f"  error lines in the API log: {sum(server_errors.values())}" + "".join(f"\n    {n:>4} x {k}" for k, n in server_errors.most_common(8)))
    return all(ok for _, ok, _ in state["checks"])


async def amain(args) -> int:
    pool = file_pool(args.max_mb)
    print("documents in the mix: " + "; ".join(f"{f['label']} ({len(f['data']) / 1e6:.2f} MB, weight {f['weight']})" for f in pool), flush=True)
    plan = {"pilot": [("pilot", args.pilot_shops, args.pilot_customers)], "stress": [("stress", args.stress_shops, args.stress_customers)],
            "limits": [], "all": [("pilot", args.pilot_shops, args.pilot_customers), ("stress", args.stress_shops, args.stress_customers)]}[args.scenario]
    if args.shops and args.customers and plan:
        plan = [(plan[0][0] + " (custom size)", args.shops, args.customers)]
    results: list[bool] = []
    limit_server = limit_state = None
    try:
        if args.scenario in ("limits", "all"):
            limit_server = Server(args.port + 1).start()                 # stays idle while the load runs, so its window can pass
            limit_state = await limits_hit(limit_server, args)
        for scen, (label, n_shops, n_customers) in enumerate(plan, start=1):
            if n_customers / n_shops > 280:
                raise SystemExit("more than 280 customers per shop would reach the per-shop cap; add shops")
            server = Server(args.port).start()
            ctx = None
            try:
                ctx = await run_load(server, args, label, n_shops, n_customers, args.ramp, pool, scen)
                if args.explain:
                    explain(server.url)
            finally:
                server_ms, server_errors = server.stop()
            results.append(report_load(f"{label}: {n_shops} shops, {n_customers} customers over {args.ramp:.0f}s", ctx, server_ms, server_errors, n_customers))
        if limit_state is not None:
            await limits_recover(limit_state, args)
    finally:
        if limit_server is not None:
            server_ms, server_errors = limit_server.stop()
            if limit_state is not None:
                results.append(report_limits(limit_state, server_ms, server_errors))
    print(f"\noverall: {'PASS' if results and all(results) else 'FAIL'}")
    return 0 if results and all(results) else 1


def explain(url: str) -> None:
    """Optional: table sizes and the slowest statements' plans on the scratch database, after a run (read-only)."""
    import psycopg2
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT relname, n_live_tup, seq_scan, idx_scan FROM pg_stat_user_tables WHERE schemaname = 'ap' ORDER BY n_live_tup DESC")
    print("\n  scratch database after the run (table, rows, sequential scans, index scans):")
    for row in cur.fetchall():
        print(f"    {row[0]:<22} {row[1]:>7} {row[2]:>8} {row[3] or 0:>9}")
    conn.close()


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--probe":
        return probe_main(sys.argv[2], sys.argv[3])
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("scenario", nargs="?", default="all", choices=["all", "pilot", "stress", "limits"])
    p.add_argument("--port", type=int, default=8031, help="local API port (the limits run uses port+1)")
    p.add_argument("--pilot-shops", type=int, default=5)
    p.add_argument("--pilot-customers", type=int, default=50)
    p.add_argument("--stress-shops", type=int, default=10)
    p.add_argument("--stress-customers", type=int, default=300)
    p.add_argument("--shops", type=int, help="custom size for a single pilot or stress run")
    p.add_argument("--customers", type=int)
    p.add_argument("--ramp", type=float, default=60.0, help="seconds over which the customers arrive")
    p.add_argument("--max-mb", type=float, default=25.0, help="cap the largest document (25 = the API limit)")
    p.add_argument("--print-seconds", type=float, default=1.0, help="how long the pretend printer takes per job")
    p.add_argument("--approve-seconds", type=float, default=0.5, help="how long the shopkeeper takes per card")
    p.add_argument("--think", type=float, nargs=2, default=(0.3, 1.5), help="customer pause between steps, min max")
    p.add_argument("--final-timeout", type=float, default=240.0, help="an order not final this long after submit is reported stuck")
    p.add_argument("--no-recovery-wait", action="store_true", help="limits: do not wait (up to 10 min) for the next window")
    p.add_argument("--explain", action="store_true", help="print table and scan counts from the scratch database after each run")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()
    return asyncio.run(amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
