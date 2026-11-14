"""Simple load test against a running API (development/staging only - never production data).

    python scripts/load_test.py --base http://localhost:8000 --users 20 --requests 1000

Signs in once, then fires a realistic mix of reads and enquiry writes from N concurrent workers and
reports latency percentiles and error rate per endpoint. Results depend on the machine; record them with
the hardware description in TEST_PLAN.md - they are not production capacity claims.
"""
from __future__ import annotations

import argparse
import random
import statistics
import threading
import time
from collections import defaultdict

import httpx

MIX = [
    ("GET", "/api/v1/control-tower", 3), ("GET", "/api/v1/bookings", 4), ("GET", "/api/v1/trips", 3),
    ("GET", "/api/v1/finance/reports/trial-balance", 1), ("GET", "/api/v1/approvals", 2), ("GET", "/api/v1/masters/lookup", 2),
    ("POST", "/api/v1/enquiries", 2),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--user", default="owner@groadlines.local")
    ap.add_argument("--password", default="Owner@12345")
    ap.add_argument("--users", type=int, default=20)
    ap.add_argument("--requests", type=int, default=1000)
    a = ap.parse_args()
    tok = httpx.post(f"{a.base}/api/v1/auth/login", json={"identifier": a.user, "password": a.password}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    weighted = [m for m in MIX for _ in range(m[2])]
    lat, errs, lock = defaultdict(list), defaultdict(int), threading.Lock()
    remaining = [a.requests]

    def worker():
        with httpx.Client(base_url=a.base, headers=h, timeout=30) as c:
            while True:
                with lock:
                    if remaining[0] <= 0:
                        return
                    remaining[0] -= 1
                method, path, _ = random.choice(weighted)
                t0 = time.perf_counter()
                body = {"source": "phone", "service_type": "PTL", "prospect_name": "LOADTEST synthetic", "goods_description": "cartons",
                        "contact_phone": "9000099999"} if method == "POST" else None
                r = c.request(method, path, json=body)
                ms = (time.perf_counter() - t0) * 1000
                with lock:
                    lat[path].append(ms)
                    if r.status_code >= 400:
                        errs[path] += 1

    t0 = time.perf_counter()
    ts = [threading.Thread(target=worker) for _ in range(a.users)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    wall = time.perf_counter() - t0
    allv = [x for v in lat.values() for x in v]
    print(f"{len(allv)} requests, {a.users} concurrent users, {wall:.1f}s, {len(allv) / wall:.1f} req/s, errors {sum(errs.values())}")
    print(f"{'endpoint':45} {'n':>5} {'p50 ms':>8} {'p95 ms':>8} {'max ms':>8} {'err':>4}")
    for path, v in sorted(lat.items()):
        v.sort()
        print(f"{path:45} {len(v):5d} {statistics.median(v):8.0f} {v[int(len(v) * .95) - 1]:8.0f} {v[-1]:8.0f} {errs[path]:4d}")


if __name__ == "__main__":
    main()
