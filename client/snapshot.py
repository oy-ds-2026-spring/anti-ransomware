import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import pika

from logger import Logger

BROKER_HOST = os.getenv("BROKER_HOST", "rabbitmq")
MONITOR_DIR = os.getenv("MONITOR_DIR", "/data")
CLIENT_ID = os.getenv("CLIENT_ID", "Client-Node")
RESTIC_REPOSITORY = os.getenv("RESTIC_REPOSITORY", "rest:http://finance:12345678@rest-server:8000/finance1/finance1")
RESTIC_PASSWORD_FILE = os.getenv("RESTIC_PASSWORD_FILE", "/run/secrets/restic_repo_pass")

def start_snapshot():
    try:
        snap_id = take_snapshot(
            source_path=MONITOR_DIR,
            repo_path=RESTIC_REPOSITORY,
            hostname=CLIENT_ID,
            password_file=RESTIC_PASSWORD_FILE,
        )

        return snap_id
    except Exception as e:
        print("ERROR:", e)
        return None

def start_restore(snapshot_id: str):

    return restore_snapshot(
        snapshot_id=snapshot_id,
        target_dir=MONITOR_DIR,
        repo_path=RESTIC_REPOSITORY,
        password_file=RESTIC_PASSWORD_FILE,
    )


def take_snapshot(
    source_path: str,
    repo_path: str,
    hostname: str,
    password_file: Optional[str] = None,
    password: Optional[str] = None,
    tag: str = "regular",
) -> str:
    """
    Take a local restic snapshot of `source_path` into local repo `repo_path`.
    Returns the restic command stdout (includes snapshot id lines).
    """
    if hostname is None:
        hostname = os.uname().nodename

    env = os.environ.copy()
    env["RESTIC_REPOSITORY"] = repo_path
    if password is not None:
        env["RESTIC_PASSWORD"] = password
    elif password_file is not None:
        env["RESTIC_PASSWORD_FILE"] = password_file
    else:
        raise ValueError("ERROR: Failed to take snapshot due to RESTIC_PASSWORD missing.")

    ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    cmd = [
        "restic", "backup", source_path,
        "--host", hostname,
        "--tag", tag,
        "--json",
        # "--time", ts_utc,
    ]

    p = subprocess.run(cmd, env=env, capture_output=True, text=True)
    out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")

    if p.returncode != 0:
        raise RuntimeError(out.strip() or f"restic exit {p.returncode}")

    snapshot_id = None
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if isinstance(obj, dict) and obj.get("message_type") == "summary":
            snapshot_id = obj.get("snapshot_id") or snapshot_id

    if not snapshot_id:
        raise RuntimeError(f"restic output did not contain snapshot_id. Output:\n{p.stdout}")

    return snapshot_id


def restore_snapshot(
        snapshot_id: str,
        target_dir: str,
        repo_path: str,
        password_file: Optional[str] = None,
        password: Optional[str] = None,
):


    env = os.environ.copy()
    env["RESTIC_REPOSITORY"] = repo_path
    if password is not None:
        env["RESTIC_PASSWORD"] = password
    elif password_file is not None:
        env["RESTIC_PASSWORD_FILE"] = password_file
    else:
        raise ValueError("ERROR: Failed to restore snapshot due to RESTIC_PASSWORD missing.")

    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    cmd = ["restic", "restore", snapshot_id, "--target", str(target)]

    try:
        r = subprocess.run(
            cmd,
            check=True,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
        )

    except subprocess.CalledProcessError as e:
        Logger.error(f"RESTORE FAILED:{e.returncode}")
        Logger.error(e.stderr or e.stdout)
        return False, {"error": str(e)}

    has_anything = any(target.rglob("*"))
    if not has_anything:
        Logger.warning("RESTORE FINISHED BUT TARGET IS EMPTY")
        Logger.warning(r.stdout)
        return False, {"error": str(r.stdout)}

    Logger.info("RESTORE OK")
    return True, {"error": None}