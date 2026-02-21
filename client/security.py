import os
import stat
from client import config
from logger import Logger

# lockdown action
def execute_lockdown(trigger_source="Unknown", reason=""):
    if getattr(config, 'IS_LOCKED_DOWN', False):
        return True, "System is already locked."

    Logger.warning(f"!!!EMERGENCY LOCKDOWN TRIGGERED BY: [{trigger_source}]")
    Logger.warning(f"   -> Reason: {reason}")
    # Owner: S_IREAD (Read) + S_IXUSR (Execute to enter dir)
    # Group: S_IRGRP (Read only)
    # Others: S_IROTH (Read only)
    LOCK_PERMS = stat.S_IREAD | stat.S_IXUSR | stat.S_IRGRP | stat.S_IROTH
    try:
        os.chmod(config.MONITOR_DIR, LOCK_PERMS)
        config.IS_LOCKED_DOWN = True
        return True, f"Directory locked successfully."
    except Exception as e:
        Logger.error(f"Lockdown failed: {e}")
        return False, str(e)