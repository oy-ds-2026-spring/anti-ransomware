from logger import Logger
from recovery.backup_server import RECOVERY_QUEUE, BROKER_HOST
from recovery.database import SnapshotDB
from recovery.message_bus.rabbitmq_handler import publish_request
from recovery.message_bus.rabbitmq_handler import start_connection


def start_recovery(command_id: str):
    """
    Start the recovery server

    :param command_id: a unique command id representing this operation, can be generated via "command_id = str(uuid.uuid4())"
    """
    db = SnapshotDB("snapshots.db")
    connection = start_connection("guest", "guest", host=BROKER_HOST)
    _, client_id, restic_snapshot_id, created_ts = db.get_latest_success_snapshot(require_snapshot_id=True)

    Logger.info(f"[BACKUP] The latest clean snapshot is: {restic_snapshot_id}")

    publish_request(connection, RECOVERY_QUEUE, command_id, restic_snapshot_id, type="recover")
