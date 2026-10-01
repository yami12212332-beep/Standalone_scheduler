# Scheduler Server

A small job scheduler. Register Python scripts with a cron schedule, and the server runs them on time, captures their output, and lets you track, edit, pause and trigger them from a web UI or REST API.

- **Backend:** FastAPI + APScheduler 3.x (in-process, asyncio)
- **Storage:** PostgreSQL (SQLModel)
- **Execution:** each script runs in its own subprocess; stdout/stderr go to log files
- **UI:** single static page served by the same server (no build step)

## Architecture

```
Browser UI --HTTP--> FastAPI routes --> PostgreSQL (tasks, runs)
                          |
                          +--> APScheduler (same event loop) --> run_task
                                                                    |
                                          subprocess: python scripts/<name>.py
                                                  |-> logs/run_<id>.out / .err
                                                  |-> (script's own work, e.g. weather DB)
```

- The `tasks` table is the source of truth; enabled tasks are loaded into APScheduler on startup and re-synced on every create/update/toggle/delete.
- The scheduler lives inside the uvicorn process, so **run exactly one worker**.

## Project structure

```
scheduler-server/
  app/
    main.py        app setup, lifespan (init DB, start scheduler), serves UI
    db.py          PostgreSQL engine and session
    models.py      Task and Run tables
    scheduler.py   APScheduler config, job sync, timezone
    runner.py      run_task: subprocess, timeout, log files, process tree
    routes.py      REST API under /api
  scripts/         the scripts that may be scheduled (only these can run)
    hello.py
    weather_to_postgres.py
  static/index.html   the UI
  logs/            created at runtime, one .out and .err per run
  requirements.txt  .env.example  .gitignore
```

## Prerequisites

- Python 3.10+
- PostgreSQL 13+ reachable from the server

## Quick start

1. **Create the databases** (once):
   ```sql
   CREATE DATABASE scheduler;   -- the app's own data
   CREATE DATABASE weather;     -- only if you use the weather script
   ```
   Tables are created automatically on first start.

2. **Install dependencies**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure**: copy `.env.example` to `.env` and set your passwords.

4. **Run** (single worker only):
   ```bash
   uvicorn app.main:app --port 8000 --env-file .env
   ```
   Or without a `.env` file, set variables in the shell first
   (PowerShell: `$env:SCHEDULER_DB_URL = "..."`; bash: `export SCHEDULER_DB_URL=...`).

5. **Open** `http://localhost:8000` (UI) or `http://localhost:8000/docs` (interactive API docs).

6. **Create a task**: New task -> script `hello.py` -> cron `*/1 * * * *` -> Save, then "Run now" and open History.

## Configuration

| Setting | Where | Default | Notes |
|---|---|---|---|
| `SCHEDULER_DB_URL` | env var | `postgresql+psycopg2://postgres:postgres@localhost:5432/scheduler` | App's own database |
| `DATABASE_URL` | env var | `postgresql://postgres:postgres@localhost:5432/weather` | Read by the weather script only. Scripts inherit the server's environment. |
| `TZ` | `app/scheduler.py` | `Asia/Kolkata` | Timezone cron expressions are evaluated in |
| `misfire_grace_time` | `app/scheduler.py` | 60 s | Late-start window after downtime or delay; beyond it the run is skipped |
| `max_instances` | `app/scheduler.py` | 1 | One scheduled run per task at a time; overlapping triggers are skipped, not queued |
| `coalesce` | `app/scheduler.py` | true | Several missed runs collapse into one |
| `MAX_CHARS` | `app/runner.py` | 20000 | Log tail kept in the DB for the UI (full logs stay in files) |
| `timeout_sec` | per task | 300 | Required, 1 to 86400. The process tree is killed when exceeded |

### Time zones
Cron schedules run in `TZ` (IST). Timestamps are stored in the database as UTC (`TIMESTAMPTZ`) and the UI converts them to IST for display.

## Adding your own script

1. Put `my_script.py` in `scripts/`. Only files in this folder can be run.
2. Make it exit with code `0` on success and non-zero on failure; print to stdout, errors to stderr.
3. It appears in the UI's script dropdown. Set arguments (shell-style, e.g. `--city Pune --lat 18.52`) and a cron.

Scripts run with the server's Python (`sys.executable`), so install their dependencies in the same virtual environment.

### Weather example
`scripts/weather_to_postgres.py` fetches current weather from Open-Meteo (free, no key) and stores it in the `weather_readings` table.

| Field | Value |
|---|---|
| Script | `weather_to_postgres.py` |
| Arguments | `--city Pune --lat 18.5204 --lon 73.8567` |
| Cron | `*/30 * * * *` |

Chennai: `--city Chennai --lat 13.0827 --lon 80.2707`.

## Cron cheat sheet (min hour day month weekday)

| Expression | Meaning |
|---|---|
| `*/30 * * * *` | every 30 minutes |
| `0 9 * * *` | daily at 09:00 |
| `0 9 * * 1-5` | weekdays at 09:00 |
| `0 */6 * * *` | every 6 hours |
| `0 0 1 * *` | first day of each month |

## API reference

Base path `/api`. Interactive docs at `/docs`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/scripts` | List runnable scripts in `scripts/` |
| GET | `/api/tasks` | List tasks, each with `next_run` |
| POST | `/api/tasks` | Create a task (201) |
| PUT | `/api/tasks/{id}` | Update a task and re-sync its schedule |
| DELETE | `/api/tasks/{id}` | Delete a task and remove its job (204) |
| POST | `/api/tasks/{id}/trigger` | Run now (202); runs even if a scheduled run is active |
| POST | `/api/tasks/{id}/toggle` | Pause or resume (flips `enabled`) |
| GET | `/api/tasks/{id}/runs?limit=20` | Run history, newest first |
| GET | `/api/runs/{run_id}/logs?stream=out\|err` | Download the full log file (text) |

### Task body (POST and PUT)
```json
{
  "name": "Pune weather",
  "script": "weather_to_postgres.py",
  "args": "--city Pune --lat 18.5204 --lon 73.8567",
  "cron": "*/30 * * * *",
  "enabled": true,
  "timeout_sec": 300
}
```
Validation errors return `422` with a message (unknown script, invalid cron, `timeout_sec` outside 1-86400). Unknown IDs return `404`.

### Run object
```json
{
  "id": 12, "task_id": 1, "status": "failed",
  "started_at": "2026-09-29T07:42:12+00:00", "finished_at": "2026-09-29T07:42:14+00:00",
  "exit_code": 1,
  "output": "stdout tail", "error_log": "stderr tail",
  "process_tree": "last process tree seen (failed/timeout runs only)"
}
```
`status` is one of `running`, `success`, `failed`, `timeout`.

### Examples
```bash
curl -X POST localhost:8000/api/tasks -H "Content-Type: application/json" \
  -d '{"name":"hello","script":"hello.py","cron":"*/5 * * * *"}'
curl -X POST localhost:8000/api/tasks/1/trigger
curl localhost:8000/api/tasks/1/runs
curl -O -J "localhost:8000/api/runs/12/logs?stream=err"
```

## How runs behave

- **Overlap:** the same task will not start again while its scheduled run is still going (skipped, not queued). Different tasks run in parallel. "Run now" bypasses the per-task limit.
- **Timeout:** the script and every child process it spawned are killed (force kill, no grace period).
- **Failure capture:** `error_log` holds stderr plus runner messages (exit code, timeout); `process_tree` keeps the last process tree sampled (every 2 s) for failed and timed-out runs.
- **Restart:** runs left `running` by a restart are marked `failed` on startup.
- **Logs:** full logs are files in `logs/`; they are not cleaned up automatically.

## Production notes

- **One worker only.** `--workers N` would start N schedulers and fire every job N times.
- **Add authentication** (API key or JWT) before exposing beyond localhost: these endpoints decide which script runs and with what arguments.
- Run it as a service (systemd, NSSM or Docker) so the scheduler survives reboots; jobs only fire while the process is up.
- Rotate or delete old files in `logs/`.
- Embedding in an existing FastAPI app: merge the lifespan, mount the router under a prefix, skip the `StaticFiles` mount, and run a single instance.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Datetime values must have timezone information` | Use timezone-aware UTC datetimes (already done in this code) and a fresh database |
| `ModuleNotFoundError: psycopg2` in a script | Install it in the same venv the server uses |
| Task fails instantly with "Script not found" | The file must be directly in `scripts/` |
| Jobs fire several times | More than one uvicorn worker or process is running |
| Nothing runs after closing the terminal | The server stopped; run it as a service |
| UI shows 422 on save | Check cron has 5 fields and `timeout_sec` is 1-86400 |
