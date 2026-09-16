"""
Slack alerts — the platform tells us when something is wrong.

Runs from beat every 15 minutes, evaluates app.core.health.compute_health and
posts to SLACK_ALERT_WEBHOOK. Quiet by design:

  * a problem set is announced once, then re-announced only every RE_ALERT_HOURS
    while it persists (so a parked case does not shout every 15 minutes),
  * a changed problem set posts immediately (something new happened),
  * clearing posts a single "recovered" message.

State lives in Redis so it survives worker restarts and is shared by whichever
instance runs the task.

Blind spot worth knowing: this runs ON the worker, so it cannot alert about the
worker itself being dead. Render's own service notifications cover that.
"""
import json
import logging
import time

import httpx

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.health import compute_health

log = logging.getLogger("alerting")

STATE_KEY = "systemize:alerts:state"
RE_ALERT_HOURS = 4


def _redis():
    import redis
    return redis.Redis.from_url(settings.REDIS_URL, socket_timeout=5)


def _post(text: str) -> bool:
    with httpx.Client(timeout=10) as client:
        r = client.post(settings.SLACK_ALERT_WEBHOOK, json={"text": text})
    r.raise_for_status()
    return True


def _format(health: dict) -> str:
    j, o, i = health["jobs"], health["outcomes"], health["intake"]
    lines = ["*Systemize: something needs a look*"]
    lines += [f"• {p}" for p in health["problems"]]
    lines.append(
        f"_jobs_: {j['in_flight']} in flight, {j['failed']} failed, {j['stalled']} stalled  |  "
        f"_outcomes_: {o['pending']} pending, {o['parked']} parked  |  "
        f"_last case in_: {i['last_case_at'] or 'never'}  |  _last outcome out_: {o['last_sent_at'] or 'never'}"
    )
    lines.append("Dashboard: https://admin.systemizesolutions.co.uk/cases")
    return "\n".join(lines)


@celery_app.task(name="app.workers.alerting.check_and_alert")
def check_and_alert():
    if not settings.SLACK_ALERT_WEBHOOK:
        return {"skipped": "SLACK_ALERT_WEBHOOK not configured"}

    db = SessionLocal()
    try:
        health = compute_health(db)
    finally:
        db.close()

    signature = " | ".join(health["problems"])
    now_ts = time.time()

    try:
        r = _redis()
        raw = r.get(STATE_KEY)
        prev = json.loads(raw) if raw else {}
    except Exception:
        log.exception("Alerting: Redis unavailable — alerting on this tick without de-dupe")
        prev, r = {}, None

    prev_sig = prev.get("signature", "")
    prev_at = float(prev.get("at") or 0)

    # Recovered: we had something, now we don't.
    if not signature:
        if prev_sig:
            try:
                _post("*Systemize: recovered* — no outstanding problems.")
            except Exception:
                log.exception("Alerting: recovery post failed")
            if r:
                r.delete(STATE_KEY)
        return {"healthy": True}

    stale = (now_ts - prev_at) > RE_ALERT_HOURS * 3600
    if signature == prev_sig and not stale:
        return {"suppressed": signature}

    try:
        _post(_format(health))
    except Exception:
        log.exception("Alerting: Slack post failed (problems: %s)", signature)
        return {"post_failed": signature}

    if r:
        r.set(STATE_KEY, json.dumps({"signature": signature, "at": now_ts}))
    return {"alerted": health["problems"]}
