#!/usr/bin/env python3
"""
Ops helper: scale the Render Celery worker (systemize-worker) up for a big batch
and automatically back down when the batch finishes.

Reads RENDER_API_KEY from backend/.env (or the environment).

Usage:
  python scale_worker.py status                 # current plan / instance count + queue snapshot
  python scale_worker.py scale 6                # set worker to 6 instances
  python scale_worker.py watch 7 [--down-to 1]  # poll batch 7 every 60s, print ETA,
                                                # scale worker to 1 when it completes
  python scale_worker.py watch 7,8,9            # watch several batches; scale down when ALL done

Cost note: Render prorates instances by the second, so 5 extra Standard
instances for 3 hours is well under $1. Leaving them on by accident is what
costs money — always run `watch` (or `scale 1`) after a bump.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

WORKER_SERVICE_ID = "srv-d9soe4710e5c73a9kue0"       # systemize-worker (Render)
API = "https://api.render.com/v1"
BACKEND = "https://systemize-backend.onrender.com/api/v1"
POLL_SECONDS = 60


def _api_key() -> str:
    key = os.getenv("RENDER_API_KEY")
    if not key:
        env = Path(__file__).with_name(".env")
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("RENDER_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit("RENDER_API_KEY not set (env or backend/.env)")
    return key


def _render(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def _backend(path: str):
    with urllib.request.urlopen(BACKEND + path, timeout=120) as r:
        return json.load(r)


def worker_status() -> tuple[str, int]:
    s = _render("GET", f"/services/{WORKER_SERVICE_ID}")
    d = s.get("serviceDetails", {})
    return d.get("plan"), int(d.get("numInstances") or 0)


def scale(n: int) -> None:
    if n < 1:
        sys.exit("refusing to scale below 1 instance (that would stop all processing)")
    _render("POST", f"/services/{WORKER_SERVICE_ID}/scale", {"numInstances": n})
    plan, cur = worker_status()
    print(f"systemize-worker -> {cur} x {plan}")


def progress(batch_id: int) -> dict:
    return _backend(f"/batches/{batch_id}/progress")


def cmd_status() -> None:
    plan, n = worker_status()
    print(f"systemize-worker: {n} instance(s) on plan={plan}")
    try:
        batches = _backend("/batches/?limit=5")
        for b in batches:
            p = progress(b["id"])
            print(f"  batch {b['id']:>4} {b.get('name','')[:40]:<40} "
                  f"{p['complete']}+{p['failed']}f / {p['total']}  ({p['percent_done']}%)")
    except Exception as exc:  # backend may be asleep/slow; status still useful
        print(f"  (batch snapshot unavailable: {exc})")


def cmd_watch(batch_ids: list[int], down_to: int) -> None:
    plan, n = worker_status()
    print(f"watching batch(es) {batch_ids}; worker currently {n} x {plan}; "
          f"will scale to {down_to} when all complete")
    last = None
    last_t = None
    while True:
        done = total = 0
        for bid in batch_ids:
            p = progress(bid)
            done += p["complete"] + p["failed"]
            total += p["total"]
        now = time.time()
        rate = ""
        if last is not None and now > last_t:
            per_h = (done - last) / (now - last_t) * 3600
            if per_h > 0:
                eta_h = (total - done) / per_h
                rate = f"  {per_h:,.0f}/h  ETA {eta_h:.1f}h"
        print(time.strftime("%H:%M:%S"), f"{done}/{total} ({done/max(total,1)*100:.1f}%){rate}", flush=True)
        last, last_t = done, now
        if total and done >= total:
            print("batch complete — scaling worker down")
            scale(down_to)
            return
        time.sleep(POLL_SECONDS)


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    cmd = argv[0]
    if cmd == "status":
        cmd_status()
    elif cmd == "scale":
        scale(int(argv[1]))
    elif cmd == "watch":
        ids = [int(x) for x in argv[1].split(",")]
        down_to = 1
        if "--down-to" in argv:
            down_to = int(argv[argv.index("--down-to") + 1])
        cmd_watch(ids, down_to)
    else:
        sys.exit(f"unknown command {cmd!r}; see --help")


if __name__ == "__main__":
    main(sys.argv[1:])
