import time
from enum import Enum


class LogType(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    SENT = "SENT"
    RECEIVED = "RECEIVED"
    LOCK_DOWN = "LOCK_DOWN"
    UNLOCK = "UNLOCK"
    SYNC = "SYNC"
    SNAPSHOT = "SNAPSHOT"
    DONE = "DONE"
    RANSOMWARE = "RANSOMWARE"
    ENCRYPTED = "ENCRYPTED"
    ANALYZE = "ANALYZE"


class Logger:
    EMOJIS = {
        LogType.INFO: "⚪️",
        LogType.WARNING: "🟡",
        LogType.ERROR: "🔴",
        LogType.SENT: "✉️",
        LogType.RECEIVED: "✉️",
        LogType.LOCK_DOWN: "🔒",
        LogType.UNLOCK: "🔓",
        LogType.SYNC: "🔁",
        LogType.SNAPSHOT: "📸",
        LogType.DONE: "🍺",
        LogType.RANSOMWARE: "🆘",
        LogType.ENCRYPTED: "㊙️",
        LogType.ANALYZE: "🤓",
    }

    @staticmethod
    def log(category, message):
        if isinstance(category, str):
            category = getattr(LogType, category.upper(), category)

        emoji = Logger.EMOJIS.get(category, "🔹")
        cat_str = category.value if isinstance(category, LogType) else str(category)
        print(f"[{emoji} {cat_str}] {message}")

    @staticmethod
    def info(msg):
        Logger.log(LogType.INFO, msg)

    @staticmethod
    def warning(msg):
        Logger.log(LogType.WARNING, msg)

    @staticmethod
    def error(msg):
        Logger.log(LogType.ERROR, msg)

    @staticmethod
    def sent(msg):
        Logger.log(LogType.SENT, msg)

    @staticmethod
    def received(msg):
        Logger.log(LogType.RECEIVED, msg)

    @staticmethod
    def lock_down(msg):
        Logger.log(LogType.LOCK_DOWN, msg)

    @staticmethod
    def unlock(msg):
        Logger.log(LogType.UNLOCK, msg)

    @staticmethod
    def sync(msg):
        Logger.log(LogType.SYNC, msg)

    @staticmethod
    def snapshot(msg):
        Logger.log(LogType.SNAPSHOT, msg)

    @staticmethod
    def done(msg):
        Logger.log(LogType.DONE, msg)

    @staticmethod
    def ransomware(msg):
        Logger.log(LogType.RANSOMWARE, msg)

    @staticmethod
    def encrypted(msg):
        Logger.log(LogType.ENCRYPTED, msg)

    @staticmethod
    def analyze(msg):
        Logger.log(LogType.ANALYZE, msg)
