# Scheduler server

1. Create the scheduler database once:  CREATE DATABASE scheduler;
2. pip install -r requirements.txt
3. Set the connection string, then start (single worker only):

       # PowerShell
       $env:SCHEDULER_DB_URL = "postgresql+psycopg2://postgres:PASSWORD@localhost:5432/scheduler"
       uvicorn app.main:app --port 8000

Open http://localhost:8000. Scripts go in `scripts/`. Cron times use Asia/Kolkata; the UI shows IST; the DB stores UTC.

Logs: every run writes full logs to `logs/run_<id>.out` (stdout) and `.err` (stderr).
The UI shows the last 20,000 characters; "Download full log" serves the whole file
(GET /api/runs/{id}/logs?stream=out|err). Delete old files in `logs/` periodically.
