from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select
from .db import init_db, engine
from .models import Run
from .scheduler import scheduler, load_all
from .routes import router

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with Session(engine) as s:   # runs interrupted by a restart
        for r in s.exec(select(Run).where(Run.status == "running")).all():
            r.status, r.error_log, r.finished_at = "failed", "Server restarted during run", datetime.now(timezone.utc)
            s.add(r)
        s.commit()
    scheduler.start()
    load_all()
    yield
    scheduler.shutdown(wait=False)

app = FastAPI(title="Scheduler", lifespan=lifespan)
app.include_router(router, prefix="/api")
app.mount("/", StaticFiles(directory="static", html=True), name="ui")   # keep last
