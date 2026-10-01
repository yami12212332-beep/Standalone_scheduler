from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select
from apscheduler.triggers.cron import CronTrigger
from .db import get_session
from .models import Task, TaskIn, Run
from .runner import resolve_script, run_task, log_path, SCRIPTS_DIR
from .scheduler import scheduler, sync_job, remove_job, next_run

router = APIRouter()

def validate(t: TaskIn):
    try:
        resolve_script(t.script)
        CronTrigger.from_crontab(t.cron)
    except Exception as e:
        raise HTTPException(422, str(e))

def get_or_404(s: Session, task_id: int) -> Task:
    t = s.get(Task, task_id)
    if not t:
        raise HTTPException(404, "Task not found")
    return t

def view(t: Task):
    return {**t.model_dump(), "next_run": next_run(t.id)}

@router.get("/scripts")
def scripts():
    return sorted(p.name for p in SCRIPTS_DIR.glob("*.py"))

@router.get("/tasks")
def list_tasks(s: Session = Depends(get_session)):
    return [view(t) for t in s.exec(select(Task).order_by(Task.id)).all()]

@router.post("/tasks", status_code=201)
def create_task(data: TaskIn, s: Session = Depends(get_session)):
    validate(data)
    t = Task.model_validate(data)
    s.add(t); s.commit(); s.refresh(t)
    sync_job(t)
    return view(t)

@router.put("/tasks/{task_id}")
def update_task(task_id: int, data: TaskIn, s: Session = Depends(get_session)):
    t = get_or_404(s, task_id)
    validate(data)
    for k, v in data.model_dump().items():
        setattr(t, k, v)
    s.add(t); s.commit(); s.refresh(t)
    sync_job(t)
    return view(t)

@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, s: Session = Depends(get_session)):
    t = get_or_404(s, task_id)
    remove_job(task_id)
    s.delete(t); s.commit()

@router.post("/tasks/{task_id}/trigger", status_code=202)
def trigger(task_id: int, s: Session = Depends(get_session)):
    get_or_404(s, task_id)
    scheduler.add_job(run_task, args=[task_id])   # no trigger = run now
    return {"message": "triggered"}

@router.post("/tasks/{task_id}/toggle")
def toggle(task_id: int, s: Session = Depends(get_session)):
    t = get_or_404(s, task_id)
    t.enabled = not t.enabled
    s.add(t); s.commit(); s.refresh(t)
    sync_job(t)
    return view(t)

@router.get("/tasks/{task_id}/runs")
def runs(task_id: int, limit: int = 20, s: Session = Depends(get_session)):
    q = select(Run).where(Run.task_id == task_id).order_by(Run.id.desc()).limit(limit)
    return s.exec(q).all()

@router.get("/runs/{run_id}/logs")
def run_logs(run_id: int, stream: Literal["out", "err"] = "out"):
    p = log_path(run_id, stream)
    if not p.is_file():
        raise HTTPException(404, "Log file not found")
    return FileResponse(p, media_type="text/plain; charset=utf-8", filename=p.name)
