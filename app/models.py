from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import DateTime
from sqlmodel import SQLModel, Field

def utcnow():
    return datetime.now(timezone.utc)

class TaskIn(SQLModel):
    name: str
    script: str                 # filename inside scripts/
    args: str = ""
    cron: str                   # "*/5 * * * *"
    enabled: bool = True
    timeout_sec: int = Field(default=300, ge=1, le=86400)   # mandatory, 1s to 24h

class Task(TaskIn, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(index=True)
    status: str = "running"     # running | success | failed | timeout
    started_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
    finished_at: Optional[datetime] = Field(default=None, sa_type=DateTime(timezone=True))
    exit_code: Optional[int] = None
    output: str = ""            # stdout + stderr in order (terminal view)
    error_log: str = ""         # stderr and runner errors only
    process_tree: str = ""      # last process tree seen (kept on failure/timeout)
