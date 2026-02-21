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
    

# unlock action
def execute_unlock(trigger_source="Unknown", reason=""):
    if not getattr(config, 'IS_LOCKED_DOWN', False):
        return True, "System is already unlocked."

    Logger.unlock(f"SYSTEM UNLOCKED BY: [{trigger_source}]")
    Logger.unlock(f"   -> Reason: {reason}")
    
    try:
        # restore to full permissions for everyone (777)
        os.chmod(config.MONITOR_DIR, 0o777)
        
        for root, dirs, files in os.walk(config.MONITOR_DIR):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o777)
            for f in files:
                os.chmod(os.path.join(root, f), 0o666)
        
        # reset the lockdown state
        config.IS_LOCKED_DOWN = False
        return True, f"Directory permissions fully restored."
    except Exception as e:
        Logger.error(f"Failed to unlock directory: {e}")
        return False, str(e)
    