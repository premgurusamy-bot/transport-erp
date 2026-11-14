"""Background worker: scheduled jobs (compliance alerts, notification delivery retries, AI recommendations,
GPS staleness, retention, collections reminders). Run with:  python -m app.worker  (loops every 5 minutes)."""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, utcnow
from app.core.notify import deliver
from app.core.services import get_config, raise_exception_task
from app.modules.platform.models import Notification

log = logging.getLogger("grl.worker")


def job_notifications(db: Session) -> int:
    n = 0
    for x in db.execute(select(Notification).where(Notification.status.in_(("queued", "failed"))).limit(200)).scalars():
        deliver(db, x)
        n += 1
    return n


def job_gps_staleness(db: Session) -> int:
    from app.modules.operations.models import Trip
    stale = int(get_config(db, "gps.stale_minutes"))
    n = 0
    for t in db.execute(select(Trip).where(Trip.status.in_(("dispatched", "in_transit")))).scalars():
        if t.last_ping_at is None or utcnow() - t.last_ping_at > timedelta(minutes=stale * 3):
            raise_exception_task(db, kind="alert", severity="high", title=f"Tracking lost on {t.code}", entity="trip", entity_id=t.id,
                                 source="gps_monitor", owner_role="dispatcher",
                                 detail=f"Last known position at {t.last_ping_at} ({t.last_ping_source}); phone and tracker both stale")
            n += 1
    return n


def job_retention(db: Session) -> int:
    from app.modules.operations.models import GpsPing
    days = int(get_config(db, "retention.days")["gps_pings"])
    r = db.execute(delete(GpsPing).where(GpsPing.received_at < utcnow() - timedelta(days=days)))
    return r.rowcount or 0


def job_escalations(db: Session) -> int:
    from app.modules.platform.models import Task
    n = 0
    for t in db.execute(select(Task).where(Task.status != "closed", Task.due_at.isnot(None), Task.due_at < utcnow(), Task.escalated.is_(False))).scalars():
        t.escalated = True
        n += 1
    return n


def run_all(db: Session) -> dict:
    from app.modules.fleet.router import compliance_alerts
    from app.modules.intelligence.ai import generate_recommendations
    out = {}
    for name, fn in (("compliance_alerts", compliance_alerts), ("notifications", job_notifications), ("gps_staleness", job_gps_staleness),
                     ("escalations", job_escalations), ("ai_recommendations", generate_recommendations), ("retention", job_retention)):
        sp = db.begin_nested()
        try:
            out[name] = fn(db)
            sp.commit()
        except Exception as e:  # one failing job never stops the others
            sp.rollback()
            log.exception("job %s failed", name)
            out[name] = f"error: {e}"
    return out


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        db = SessionLocal()
        try:
            log.info("jobs: %s", run_all(db))
            db.commit()
        except Exception:
            db.rollback()
            log.exception("worker cycle failed")
        finally:
            db.close()
        time.sleep(300)


if __name__ == "__main__":
    main()
