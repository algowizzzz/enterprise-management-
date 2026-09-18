#!/usr/bin/env python3
"""Load rehearsal: the portal pages and list calls at rising concurrency.

    cd <bench>/sites
    FRAPPE_BENCH_ROOT=<bench> <bench>/env/bin/python <repo>/scripts/load_test.py \\
        --site consilium.local --url http://127.0.0.1:8000 \\
        --levels 1,5,10,25,50 --duration 30 --json load.json

What it does, in two steps:

1. **Signs in without passwords.** Demonstration personas have no password (see
   ``deploy/demo_data.py``), and a load test should not need one. So sessions
   are created on the server side, exactly as a sign-in would create them — a
   row in the session table and the cached session — for up to ``--users``
   enabled users whose email matches ``--users-like``. This step imports the
   framework, so it runs under the installation's own interpreter from the
   ``sites`` directory. It also picks one real record for each record page, so
   the populated page is measured rather than the empty one.

   ``--mint-only FILE`` writes those sessions to a file and stops;
   ``--sessions FILE`` reads them back and skips the step, so the load itself
   can be driven from another machine with nothing but Python.

2. **Drives load** with threads and ``urllib`` only — no third-party package,
   so it runs anywhere the product runs. Each thread is one signed-in user
   working through a fixed mix of portal pages and API list calls, back to
   back with no think time, for ``--duration`` seconds at each concurrency
   level. That is a far heavier load per thread than a person generates:
   read "25 threads" as "25 requests in flight at once", not "25 users".

Reported per level: requests, throughput, p50/p95/p99/max latency, and errors.
An error is any HTTP status of 400 or above other than 403, any exception, or
a portal page that ends on the sign-in page (a session that did not take would
otherwise look like a very fast success). A 403 is the permission layer
refusing a persona a page its role may not see: correct behaviour, so it is
reported separately, per request, rather than counted as a failure.

The numbers depend on the machine far more than on the code. The report
states the hardware it ran on; do not compare numbers across machines.

Sessions created here expire like any other. ``--logout`` ends them at the
end of the run.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

# Portal pages, by route. Record pages take a record from the site (step 1).
PAGES = ["/", "/forums", "/policies", "/escalations", "/tasks", "/reports",
         "/formation-requests", "/attestation-campaigns"]
RECORD_PAGES = {
    "/forum": ("Governance Forum", "name"),
    "/policy": ("Governing Document", "name"),
    "/escalation": ("Escalation Matter", "name"),
}
# The list calls the portal and the desk make most. The fields are the ones a
# list view asks for, not "*", so the query is realistic.
LISTS = {
    "Governance Forum": ["name", "modified"],
    "Governing Document": ["name", "modified"],
    "Escalation Matter": ["name", "modified"],
    "ToDo": ["name", "description", "status"],
}


# ------------------------------------------------------------------ step 1
def mint_sessions(site: str, sites_path: str, users_like: str, max_users: int) -> dict:
    """Create server-side sessions; return them with sample record names."""
    import frappe
    from frappe.sessions import Session
    from werkzeug.test import EnvironBuilder
    from werkzeug.wrappers import Request

    frappe.init(site=site, sites_path=str(Path(sites_path).resolve()))
    frappe.connect()
    try:
        users = frappe.get_all(
            "User",
            filters={"enabled": 1, "user_type": "System User", "name": ["like", users_like]},
            fields=["name", "full_name", "user_type"],
            order_by="name asc",
            limit_page_length=max_users,
        )
        if not users:
            raise SystemExit(f"no enabled system users match {users_like!r} on {site}")

        sessions = []
        for user in users:
            # Session reads the sid cookie from the current request, so give it
            # one: an empty request from the loopback address.
            frappe.local.request = Request(EnvironBuilder(path="/", base_url=f"http://{site}").get_environ())
            frappe.local.request_ip = "127.0.0.1"
            frappe.set_user(user.name)
            session = Session(user.name, resume=False, full_name=user.full_name, user_type=user.user_type)
            sessions.append({"user": user.name, "sid": session.sid})
        frappe.db.commit()

        frappe.set_user("Administrator")
        records = {}
        for route, (doctype, param) in RECORD_PAGES.items():
            name = frappe.db.get_value(doctype, {}, "name", order_by="modified desc")
            if name:
                records[route] = {param: name}
        return {"site": site, "sessions": sessions, "records": records}
    finally:
        frappe.destroy()


def logout_sessions(site: str, sites_path: str, sessions: list[dict]) -> None:
    import frappe
    from frappe.sessions import delete_session

    frappe.init(site=site, sites_path=str(Path(sites_path).resolve()))
    frappe.connect()
    try:
        for s in sessions:
            delete_session(s["sid"], s["user"], reason="Load test finished")
        frappe.db.commit()
    finally:
        frappe.destroy()


# ------------------------------------------------------------------ step 2
def build_mix(records: dict) -> list[tuple[str, str]]:
    """(label, path) pairs one thread walks through, in order, repeatedly."""
    mix = [(f"page {p}", p) for p in PAGES]
    for route, query in records.items():
        mix.append((f"page {route}", f"{route}?{urllib.parse.urlencode(query)}"))
    for doctype, fields in LISTS.items():
        q = urllib.parse.urlencode({"fields": json.dumps(fields), "limit_page_length": 20,
                                    "order_by": "modified desc"})
        mix.append((f"api list {doctype}", f"/api/resource/{urllib.parse.quote(doctype)}?{q}"))
    mix.append(("api get_logged_user", "/api/method/frappe.auth.get_logged_user"))
    return mix


# No proxy, ever: a corporate HTTP(S)_PROXY in the environment would otherwise
# carry loopback traffic off the machine, or fail it.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def one_request(base: str, host: str | None, path: str, sid: str, timeout: float) -> tuple[float, str | None]:
    """Return (seconds, error or None)."""
    request = urllib.request.Request(base + path)
    request.add_header("Cookie", f"sid={sid}")
    request.add_header("Accept", "text/html,application/json")
    if host:
        request.add_header("Host", host)
    started = time.perf_counter()
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            body = response.read()
            final = response.geturl()
        elapsed = time.perf_counter() - started
        if "/login" in urllib.parse.urlsplit(final).path:
            return elapsed, "ended on the sign-in page"
        if path.startswith("/api/method/frappe.auth.get_logged_user") and b"Guest" in body:
            return elapsed, "session not recognised"
        return elapsed, None
    except urllib.error.HTTPError as e:
        return time.perf_counter() - started, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001 -- every failure is a data point
        return time.perf_counter() - started, type(e).__name__


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return float("nan")
    k = (len(sorted_values) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def run_level(base: str, host: str | None, sessions: list[dict], mix: list[tuple[str, str]],
              threads: int, duration: float, timeout: float) -> dict:
    samples: list[tuple[str, float, str | None]] = []
    lock = threading.Lock()
    stop_at = time.perf_counter() + duration

    def worker(index: int) -> None:
        sid = sessions[index % len(sessions)]["sid"]
        position = index  # stagger, so threads do not all hit the same page at once
        local = []
        while time.perf_counter() < stop_at:
            label, path = mix[position % len(mix)]
            position += 1
            elapsed, error = one_request(base, host, path, sid, timeout)
            local.append((label, elapsed, error))
        with lock:
            samples.extend(local)

    started = time.perf_counter()
    pool = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(threads)]
    for t in pool:
        t.start()
    for t in pool:
        t.join()
    wall = time.perf_counter() - started

    latencies = sorted(s[1] for s in samples)
    # A 403 is the permission layer refusing a persona a page its role may not
    # see — correct behaviour, counted apart from failures, per request.
    errors = Counter(s[2] for s in samples if s[2] and s[2] != "HTTP 403")
    denied = Counter(s[0] for s in samples if s[2] == "HTTP 403")
    by_label: dict[str, list[float]] = defaultdict(list)
    for label, elapsed, _ in samples:
        by_label[label].append(elapsed)
    return {
        "threads": threads,
        "requests": len(samples),
        "wall_seconds": round(wall, 2),
        "throughput_rps": round(len(samples) / wall, 2) if wall else 0,
        "p50_ms": round(percentile(latencies, 50) * 1000, 1),
        "p95_ms": round(percentile(latencies, 95) * 1000, 1),
        "p99_ms": round(percentile(latencies, 99) * 1000, 1),
        "max_ms": round(latencies[-1] * 1000, 1) if latencies else None,
        "mean_ms": round(statistics.fmean(latencies) * 1000, 1) if latencies else None,
        "errors": sum(errors.values()),
        "error_kinds": dict(errors.most_common(5)),
        "denied_by_permission": sum(denied.values()),
        "denied_requests": dict(denied.most_common()),
        "per_request": {
            label: {"n": len(v), "p50_ms": round(percentile(sorted(v), 50) * 1000, 1),
                    "p95_ms": round(percentile(sorted(v), 95) * 1000, 1)}
            for label, v in sorted(by_label.items())
        },
    }


def describe_hardware() -> dict:
    info = {
        "system": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
    }
    try:
        if sys.platform == "darwin":
            info["cpu"] = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                         capture_output=True, text=True).stdout.strip()
            mem = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout)
            info["memory_gb"] = round(mem / 2**30, 1)
        elif sys.platform.startswith("linux"):
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal"):
                    info["memory_gb"] = round(int(line.split()[1]) / 2**20, 1)
                    break
        elif os.name == "nt":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            info["cpu"] = platform.processor()
            info["memory_gb"] = round(status.ullTotalPhys / 2**30, 1)
    except Exception:  # noqa: BLE001 -- hardware detail is best effort
        pass
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", required=True, help="site name; also sent as the Host header")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="base URL of the running server")
    parser.add_argument("--sites-path", default=".")
    parser.add_argument("--users-like", default="%@demo.example",
                        help="which users to sign in as (SQL LIKE on the user id)")
    parser.add_argument("--users", type=int, default=20, help="at most this many distinct users")
    parser.add_argument("--levels", default="1,5,10,25", help="comma-separated thread counts")
    parser.add_argument("--duration", type=float, default=30, help="seconds per level")
    parser.add_argument("--warmup", type=float, default=5, help="seconds of single-thread warm-up, not reported")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--sessions", help="read sessions from this file instead of creating them")
    parser.add_argument("--mint-only", metavar="FILE", help="create sessions, write them here, and stop")
    parser.add_argument("--logout", action="store_true", help="end the sessions afterwards")
    parser.add_argument("--note", default="", help="free text recorded with the result (server settings, ...)")
    parser.add_argument("--json", help="also write the full result here")
    args = parser.parse_args()

    if args.sessions:
        minted = json.loads(Path(args.sessions).read_text())
    else:
        minted = mint_sessions(args.site, args.sites_path, args.users_like, args.users)
        if args.mint_only:
            Path(args.mint_only).write_text(json.dumps(minted, indent=1))
            print(f"{len(minted['sessions'])} sessions written to {args.mint_only}")
            return 0

    sessions = minted["sessions"]
    base = args.url.rstrip("/")
    host = args.site if urllib.parse.urlsplit(base).hostname in ("127.0.0.1", "localhost") else None
    mix = build_mix(minted.get("records", {}))
    hardware = describe_hardware()

    print(f"Load rehearsal against {args.site} at {base}")
    print(f"  client and hardware: {hardware}")
    print(f"  {len(sessions)} signed-in users; {len(mix)} requests in the mix; "
          f"{args.duration:.0f}s per level; no think time")
    if args.note:
        print(f"  note: {args.note}")

    # Sanity: every session must be recognised, or the numbers measure the
    # sign-in page.
    for s in sessions[:3]:
        _, error = one_request(base, host, "/api/method/frappe.auth.get_logged_user", s["sid"], args.timeout)
        if error:
            raise SystemExit(f"session for {s['user']} is not accepted by the server: {error}")

    if args.warmup:
        run_level(base, host, sessions, mix, 1, args.warmup, args.timeout)

    results = []
    print(f"\n  {'threads':>7} {'requests':>8} {'req/s':>7} {'p50 ms':>8} {'p95 ms':>8} "
          f"{'p99 ms':>8} {'max ms':>8} {'errors':>6} {'denied':>6}")
    for level in [int(x) for x in args.levels.split(",") if x.strip()]:
        r = run_level(base, host, sessions, mix, level, args.duration, args.timeout)
        results.append(r)
        print(f"  {r['threads']:>7} {r['requests']:>8} {r['throughput_rps']:>7} {r['p50_ms']:>8} "
              f"{r['p95_ms']:>8} {r['p99_ms']:>8} {r['max_ms']:>8} {r['errors']:>6} {r['denied_by_permission']:>6}"
              + (f"  {r['error_kinds']}" if r["errors"] else ""))
    denied_where = Counter()
    for r in results:
        denied_where.update(r["denied_requests"])
    if denied_where:
        print(f"\n  Refused by the permission layer (HTTP 403; the persona's role may not see it): "
              + ", ".join(f"{k} x{v}" for k, v in denied_where.most_common()))

    top = results[-1]
    print(f"\n  Per request at {top['threads']} threads (p50 / p95 ms):")
    for label, v in top["per_request"].items():
        print(f"    {label:<40} {v['p50_ms']:>8} / {v['p95_ms']:<8} n={v['n']}")

    if args.logout and not args.sessions:
        logout_sessions(args.site, args.sites_path, sessions)

    if args.json:
        Path(args.json).write_text(json.dumps({
            "site": args.site, "url": base, "hardware": hardware, "note": args.note,
            "users": len(sessions), "duration_per_level": args.duration,
            "mix": [label for label, _ in mix], "levels": results,
        }, indent=1))
        print(f"\n  full result written to {args.json}")
    return 1 if any(r["errors"] for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
