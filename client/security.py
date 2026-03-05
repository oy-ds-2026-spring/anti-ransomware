import os
import json
from client import config
from logger import Logger

# State persistence file
STATE_FILE = "/logs/client_state.json"


def save_state():
    """Persist client state to file"""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        state = {
            "IS_LOCKED_DOWN": config.IS_LOCKED_DOWN,
            "IS_RECOVERING": config.IS_RECOVERING,
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        Logger.warning(f"Failed to save state: {e}")


def load_state():
    """Load client state from file

    Only the lockdown flag is persistent.  Recovery is an ephemeral
    process that should not survive a restart, so we deliberately avoid
    restoring ``IS_RECOVERING``.  Loading the previous recovery state
    caused the monitor to ignore all file events indefinitely.
    """
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
                config.IS_LOCKED_DOWN = state.get("IS_LOCKED_DOWN", False)
                # reset recovering unconditionally
                config.IS_RECOVERING = False
                Logger.info(f"Loaded state: IS_LOCKED_DOWN={config.IS_LOCKED_DOWN}, IS_RECOVERING={config.IS_RECOVERING}")
                return True
    except Exception as e:
        Logger.warning(f"Failed to load state: {e}")
    return False


# write protection action
def write_protection(trigger_source="Unknown", reason=""):
    try:
        # remove write permissions for all users (owner, group, others)
        os.chmod(config.MONITOR_DIR, 0o555)
        Logger.info(f"Write protection enabled by [{trigger_source}]. Reason: {reason}")
    except Exception as e:
        Logger.error(f"Failed to set write protection: {e}")


# lockdown action
def execute_lockdown(trigger_source="Unknown", reason=""):
    if getattr(config, "IS_LOCKED_DOWN", False):
        return True, "System is already locked."

    Logger.warning(f"!!!EMERGENCY LOCKDOWN TRIGGERED BY: [{trigger_source}]")
    Logger.warning(f"   -> Reason: {reason}")
    # we want to prevent any further write operations both locally and via sync
    config.WRITE_PERMISSION.clear()

    # Owner: S_IREAD (Read) + S_IXUSR (Execute to enter dir)
    # Group: S_IRGRP (Read only)
    # Others: S_IROTH (Read only)
    # LOCK_PERMS = stat.S_IREAD | stat.S_IXUSR | stat.S_IRGRP | stat.S_IROTH
    try:
        # directory itself should be rx only for everyone
        os.chmod(config.MONITOR_DIR, 0o500)

        # recursively make existing directories rx and files read-only
        for root, dirs, files in os.walk(config.MONITOR_DIR):
            for d in dirs:
                dir_path = os.path.join(root, d)
                try:
                    os.chmod(dir_path, 0o555)
                except Exception as e:
                    Logger.warning(f"Failed to lock dir {dir_path}: {e}")
            for f in files:
                file_path = os.path.join(root, f)
                try:
                    os.chmod(file_path, 0o444)
                except Exception as e:
                    Logger.warning(f"Failed to lock file {file_path}: {e}")

        config.IS_LOCKED_DOWN = True
        save_state()  # Persist locked state
        return True, "Directory physically locked via OS."
    except Exception as e:
        return False, str(e)


# unlock action
def execute_unlock(trigger_source="Unknown", reason=""):
    if not getattr(config, "IS_LOCKED_DOWN", False):
        return True, "System is already unlocked."

    Logger.unlock(f"SYSTEM UNLOCKED BY: [{trigger_source}]")
    Logger.unlock(f"   -> Reason: {reason}")

    try:
        # restore permissions to allow full access again, owner: read/write/execute, group: read/write, others: read/write
        os.chmod(config.MONITOR_DIR, 0o755)

        # use a multi-pass approach to ensure all dirs become writable
        # some dirs might be created during attack and were not walked
        for root, dirs, files in os.walk(config.MONITOR_DIR):
            for d in dirs:
                dir_path = os.path.join(root, d)
                try:
                    os.chmod(dir_path, 0o777)
                except Exception as e:
                    Logger.warning(f"Failed to chmod dir {dir_path}: {e}")
            for f in files:
                file_path = os.path.join(root, f)
                try:
                    os.chmod(file_path, 0o666)
                except Exception as e:
                    Logger.warning(f"Failed to chmod file {file_path}: {e}")

        # make one more pass to catch any missed directories (especially those that become writable after first pass)
        for root, dirs, files in os.walk(config.MONITOR_DIR):
            for d in dirs:
                dir_path = os.path.join(root, d)
                try:
                    # ensure all directories are fully writable for the restore process
                    os.chmod(dir_path, 0o777)
                except Exception as e:
                    Logger.warning(f"Second pass failed to chmod dir {dir_path}: {e}")

        # reset the lockdown state and resume writes
        config.IS_LOCKED_DOWN = False
        config.WRITE_PERMISSION.set()
        save_state()  # Persist unlocked state
        return True, f"Directory permissions fully restored."
    except Exception as e:
        Logger.error(f"Failed to unlock directory: {e}")
        return False, str(e)
