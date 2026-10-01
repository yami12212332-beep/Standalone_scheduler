import asyncio, sys, shlex, time
from pathlib import Path
import psutil
from sqlmodel import Session
from .db import engine
from .models import Task, Run, utcnow

SCRIPTS_DIR = Path("scripts").resolve()
LOGS_DIR = Path("logs").resolve()
LOGS_DIR.mkdir(exist_ok=True)
MAX_CHARS = 20000            # tail kept in the DB for the UI; full logs stay in files

def log_path(run_id: int, stream: str) -> Path:
    return LOGS_DIR / f"run_{run_id}.{stream}"       # stream: "out" or "err"

def tail(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - MAX_CHARS * 4))
            return f.read().decode(errors="replace")[-MAX_CHARS:]
    except OSError:
        return ""

def resolve_script(name: str) -> Path:
    p = (SCRIPTS_DIR / name).resolve()
    if SCRIPTS_DIR not in p.parents or not p.is_file():
        raise ValueError("Script not found in scripts/ folder")
    return p

def snapshot_tree(pid: int) -> str:
    lines = []
    def walk(p, depth):
        try:
            mem = p.memory_info().rss // 1048576
            lines.append(f"{'   ' * depth}{'└─ ' if depth else ''}{p.pid} {p.name()} [{p.status()}] {mem}MB")
            for c in p.children():
                walk(c, depth + 1)
        except psutil.Error:
            pass
    try:
        walk(psutil.Process(pid), 0)
    except psutil.Error:
        pass
    return "\n".join(lines)

def kill_tree(pid: int):
    try:
        root = psutil.Process(pid)
        procs = root.children(recursive=True) + [root]
    except psutil.Error:
        return
    for p in procs:
        try:
            p.kill()
        except psutil.Error:
            pass

def save(run_id: int, **fields):
    """Write run fields; retry so a brief DB hiccup doesn't lose the result."""
    for attempt in range(3):
        try:
            with Session(engine) as s:
                r = s.get(Run, run_id)
                for k, v in fields.items():
                    setattr(r, k, v)
                s.add(r); s.commit()
            return
        except Exception as e:
            print(f"DB save failed (attempt {attempt + 1}): {e}", file=sys.stderr)
            time.sleep(0.5)

async def run_task(task_id: int):
    with Session(engine) as s:
        task = s.get(Task, task_id)
        if not task:
            return
        run = Run(task_id=task_id)
        s.add(run); s.commit(); s.refresh(run)
        run_id, script, args, timeout = run.id, task.script, task.args, task.timeout_sec

    out_p, err_p = log_path(run_id, "out"), log_path(run_id, "err")
    tree, notes = {"last": ""}, []
    status, code = "failed", None

    async def monitor(pid):                  # live tail + process tree into the DB every 2s
        while True:
            tree["last"] = snapshot_tree(pid) or tree["last"]
            save(run_id, output=tail(out_p), error_log=tail(err_p), process_tree=tree["last"])
            await asyncio.sleep(2)

    try:
        with open(out_p, "wb") as fo, open(err_p, "wb") as fe:   # files, not pipes: no deadlock
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-u", str(resolve_script(script)), *shlex.split(args),
                stdout=fo, stderr=fe,
            )
            mon = asyncio.create_task(monitor(proc.pid))
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
                code = proc.returncode
                status = "success" if code == 0 else "failed"
            except asyncio.TimeoutError:
                tree["last"] = snapshot_tree(proc.pid) or tree["last"]
                kill_tree(proc.pid)          # script and any children it spawned
                await proc.wait()
                code, status = proc.returncode, "timeout"
                notes.append(f"Timed out after {timeout}s; process tree killed\n")
            finally:
                mon.cancel()
        if status == "failed" and not tail(err_p).strip():
            notes.append(f"Script exited with code {code}\n")
    except Exception as e:
        notes.append(f"Runner error: {type(e).__name__}: {e}\n")

    if notes:
        with open(err_p, "ab") as f:
            f.write("".join(notes).encode())

    save(run_id, status=status, exit_code=code, output=tail(out_p), error_log=tail(err_p),
         process_tree=tree["last"] if status != "success" else "", finished_at=utcnow())
