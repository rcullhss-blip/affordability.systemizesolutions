"""
Self-scaling for the Celery worker service on Render.

Runs from Celery Beat every couple of minutes (and is kicked directly after a
large upload). Reads the broker queue depth and sets the worker's instance
count through the Render API:

  * queued work  -> desired = ceil(queued / WORKER_AUTOSCALE_PER_INSTANCE),
                    capped at WORKER_AUTOSCALE_MAX. Scaling UP happens
                    immediately (a 32k upload goes to the cap on the next tick).
  * no queued work for WORKER_AUTOSCALE_IDLE_TICKS consecutive ticks
                 -> scale DOWN to 1.

We never scale down while work is queued: Render stops the newest instances on
a scale-down and any task they were running only comes back after the broker's
visibility timeout — so downscaling mid-run is exactly the thing to avoid. Up
fast, down only when idle.

Enabled only when WORKER_AUTOSCALE=1 and RENDER_API_KEY is set on the worker.
The target service defaults to Render's own RENDER_SERVICE_ID env var (set on
every Render instance), so no service id needs configuring.

State (idle-tick counter) lives in Redis so it survives worker restarts and is
shared by whichever instance runs the beat task.
"""

from __future__ import annotations

import json
import logging
import math
import os
import urllib.request

from app.core.celery_app import celery_app
from app.core.config import settings

log = logging.getLogger("autoscale")

RENDER_API = "https://api.render.com/v1"
PIPELINE_QUEUES = ("fetch", "extract", "parse", "analyse", "document", "deliver")
IDLE_KEY = "systemize:autoscale:idle_ticks"


def _redis():
    import redis
    return redis.Redis.from_url(settings.REDIS_URL, socket_timeout=5)


def queue_backlog(r=None) -> dict:
    r = r or _redis()
    return {q: int(r.llen(q)) for q in PIPELINE_QUEUES}


def _render(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        RENDER_API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {settings.RENDER_API_KEY}",
            "Accept": "application/json", "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def _service_id() -> str:
    return settings.RENDER_WORKER_SERVICE_ID or os.environ.get("RENDER_SERVICE_ID", "")


def current_instances(service_id: str) -> int:
    svc = _render("GET", f"/services/{service_id}")
    return int(svc.get("serviceDetails", {}).get("numInstances") or 1)


def desired_instances(queued: int) -> int:
    if queued <= 0:
        return 1
    return max(1, min(settings.WORKER_AUTOSCALE_MAX,
                      math.ceil(queued / settings.WORKER_AUTOSCALE_PER_INSTANCE)))


@celery_app.task(name="app.workers.autoscale.autoscale_workers")
def autoscale_workers():
    if not settings.WORKER_AUTOSCALE or not settings.RENDER_API_KEY:
        return {"skipped": "autoscale disabled"}
    service_id = _service_id()
    if not service_id:
        log.warning("Autoscale: no RENDER_SERVICE_ID / RENDER_WORKER_SERVICE_ID — skipping")
        return {"skipped": "no service id"}

    try:
        r = _redis()
        backlog = queue_backlog(r)
        queued = sum(backlog.values())

        if queued > 0:
            r.set(IDLE_KEY, 0)
            idle_ticks = 0
        else:
            idle_ticks = int(r.incr(IDLE_KEY))

        current = current_instances(service_id)
        want = desired_instances(queued)

        if want > current:
            _render("POST", f"/services/{service_id}/scale", {"numInstances": want})
            log.warning("Autoscale: %d queued (%s) -> scaling %d -> %d", queued, backlog, current, want)
            return {"queued": queued, "from": current, "to": want}

        if queued == 0 and current > 1 and idle_ticks >= settings.WORKER_AUTOSCALE_IDLE_TICKS:
            _render("POST", f"/services/{service_id}/scale", {"numInstances": 1})
            log.warning("Autoscale: idle for %d ticks -> scaling %d -> 1", idle_ticks, current)
            return {"queued": 0, "from": current, "to": 1}

        log.info("Autoscale: %d queued, %d instance(s), idle_ticks=%d — no change", queued, current, idle_ticks)
        return {"queued": queued, "instances": current, "idle_ticks": idle_ticks}
    except Exception:
        log.exception("Autoscale: tick failed (leaving instance count unchanged)")
        return {"error": "tick failed"}
