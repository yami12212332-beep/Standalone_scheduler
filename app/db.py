import os
from sqlmodel import SQLModel, Session, create_engine
from dotenv import load_dotenv
load_dotenv(dotenv_path=r"C:\Users\Yeshwanth\Downloads\scheduler-server (1)\scheduler-server\.env")

# Scheduler's own database (separate from the weather DB used by the script)
DB_URL = os.getenv("SCHEDULER_DB")

engine = create_engine(DB_URL, pool_pre_ping=True, pool_size=5, max_overflow=5)

def init_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as s:
        yield s
