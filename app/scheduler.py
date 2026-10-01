from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select
from .db import engine
from .models import Task
from .runner import run_task

TZ = "Asia/Kolkata"

scheduler = AsyncIOScheduler(
    timezone=TZ,
    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60},
)

def sync_job(task: Task):
    jid = f"task-{task.id}"
    if scheduler.get_job(jid):
        scheduler.remove_job(jid)
    if task.enabled:
        scheduler.add_job(run_task, CronTrigger.from_crontab(task.cron, timezone=TZ),
                          args=[task.id], id=jid, name=task.name)

def remove_job(task_id: int):
    if scheduler.get_job(f"task-{task_id}"):
        scheduler.remove_job(f"task-{task_id}")

def load_all():
    with Session(engine) as s:
        for t in s.exec(select(Task)).all():
            sync_job(t)

def next_run(task_id: int):
    job = scheduler.get_job(f"task-{task_id}")
    return job.next_run_time if job else None
