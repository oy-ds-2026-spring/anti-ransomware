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
    # LOCK_PERMS = stat.S_IREAD | stat.S_IXUSR | stat.S_IRGRP | stat.S_IROTH
    try:
        # only owner can read and execute (enter) the directory, no permissions for anyone
        os.chmod(config.MONITOR_DIR, 0o500)
        
        config.IS_LOCKED_DOWN = True
        return True, "Directory physically locked via OS."
    except Exception as e:
        return False, str(e)
    

# unlock action
def execute_unlock(trigger_source="Unknown", reason=""):
    if not getattr(config, 'IS_LOCKED_DOWN', False):
        return True, "System is already unlocked."

    Logger.unlock(f"SYSTEM UNLOCKED BY: [{trigger_source}]")
    Logger.unlock(f"   -> Reason: {reason}")
    
    try:
        # restore permissions to allow full access again,owner: read/write/execute, group: read/write, others: read/write
        os.chmod(config.MONITOR_DIR, 0o755)
        
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
    