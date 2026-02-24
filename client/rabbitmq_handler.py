import pika
import time
import json
import uuid
import os
import threading

from client import config
from client import utils
from logger import Logger

# offline outbox
OFFLINE_QUEUE_FILE = os.path.join(config.MONITOR_DIR, f"offline_{config.CLIENT_ID}.json")
OFFLINE_LOCK = threading.Lock()  # thread lock

# save file operation when offline
def save_to_offline_queue(payload):
    with OFFLINE_LOCK:
        queue = []
        if os.path.exists(OFFLINE_QUEUE_FILE):
            try:
                with open(OFFLINE_QUEUE_FILE, "r") as f:
                    queue = json.load(f)
            except:  # noqa: E722
                pass
        queue.append(payload)
        with open(OFFLINE_QUEUE_FILE, "w") as f:
            json.dump(queue, f)
        Logger.warning(f"[PARTITION] Network down: Operation saved locally. Total pending: {len(queue)}")
    

# clear offline operation queue when reconnects
def flush_offline_queue(channel):
    with OFFLINE_LOCK:
        if not os.path.exists(OFFLINE_QUEUE_FILE):
            return
        try:
            with open(OFFLINE_QUEUE_FILE, "r") as f:
                queue = json.load(f)
            if not queue:
                return

            Logger.info(f"Network Restored: Flushing {len(queue)} offline operations")
            for payload in queue:
                corr_id = str(uuid.uuid4())
                channel.basic_publish(
                    exchange="finance_sync",
                    routing_key="",
                    properties=pika.BasicProperties(correlation_id=corr_id),
                    body=json.dumps(payload),
                )
            os.remove(OFFLINE_QUEUE_FILE)
            Logger.done("Offline queue flushed successfully!")
        except Exception as e:
            Logger.warning(f"Failed to flush offline queue: {e}")


def _on_sync_message(ch, method, properties, body):
    msg = json.loads(body)
    filename = msg.get("filename")
    incoming_clock = msg.get("v_clock", {})

    # not listen to self
    if msg.get("sender") == config.CLIENT_ID:
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    # wait for snapshot if needed
    config.WRITE_PERMISSION.wait()

    # get and merge the clock
    incoming_clock = msg.get("v_clock", {})
    # local_clock = utils.get_clock()

    op, filename, content = (
        msg.get("operation"),
        msg.get("filename"),
        msg.get("content", ""),
    )
    
    local_file_clock = utils.get_clock(filename)
    is_conflict = utils.detect_conflict(local_file_clock, incoming_clock)
    # is_conflict = utils.detect_conflict(local_clock, incoming_clock)
    if is_conflict and op in ["WRITE", "CREATE"]:
        Logger.error(f" CONFLICT DETECTED on {filename}!")
        Logger.error(f"   -> Local: {local_file_clock} | Incoming: {incoming_clock}")
        # if conflict: combine both data and add mark to indicate conflict
        content = f"\n\n[=== CONFLICT DETECTED FROM {msg.get('sender')} ===]\n" + content

    utils.merge_clock(filename, incoming_clock)

    try:
        if op == "CREATE":
            utils.local_create(filename, content)
        elif op == "WRITE":
            utils.local_write(filename, content)
        elif op == "DELETE":
            utils.local_delete(filename)
            
        ch.basic_ack(delivery_tag=method.delivery_tag)

        # after operation reply SYNC_ACK, `finance_sync_ack`
        if msg.get("sender"):
            try:
                ch.basic_publish(
                    exchange="finance_sync_ack",
                    routing_key=msg.get("sender"),
                    properties=pika.BasicProperties(
                        correlation_id=properties.correlation_id
                    ),
                    body=json.dumps({"status": "ACK", "sender": config.CLIENT_ID}),
                )
                Logger.done(f"ACK sent for {op}, {filename}")
            except Exception:
                pass # if receiver offline, ignore
            
    except Exception as e:
        Logger.warning(f"Sync processing failed: {e}")


# mq connection
def _get_channel():
    credentials = pika.PlainCredentials("guest", "guest")
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=config.BROKER_HOST, credentials=credentials)
    )
    return connection, connection.channel()


def send_msg(file_path, entropy, event_type):
    try:
        # init short connection for every sending
        connection, channel = _get_channel()
        channel.queue_declare(queue="file_events")

        payload = {
            "client_id": config.CLIENT_ID,
            "file_path": file_path,
            "entropy": entropy,
            "event_type": event_type,
            "timestamp": time.time(),
            "v_clock": utils.get_clock(os.path.basename(file_path)),
        }

        channel.basic_publish(
            exchange="", routing_key="file_events", body=json.dumps(payload)
        )
        Logger.sent(f"{file_path} | Entropy: {entropy:.2f} | Event: {event_type}")
        connection.close()
    except Exception as e:  # noqa: F841
        # intentionally discard Watchdog entropy alerts
        
        # trade-off:
        # 1. entropy alerts are point-in-time metrics
        #    sending delayed/historical alerts after network recovery provides no real security value
        # 2. disconnected node is inherently isolated
        #    malware cannot spread across the network during a partition
        # 3. when the network restores, the malicious file 
        #    will be synced to other nodes via the durable "broadcast_sync" 
        #    local watchdogs will instantly intercept it 
        #    calculate the high entropy, and trigger the global lock down
        pass


def _on_lock_down(ch, method, properties, body):
    config.IS_LOCKED_DOWN = True
    Logger.lock_down(f"Command received! Isolating {config.CLIENT_ID}...")
    # report ok
    send_msg("SYSTEM_ISOLATED", 0, "LOCK_DOWN")


# listen to RabbitMQ
def lock_down_listener():
    while True:
        try:
            _, channel = _get_channel()
            channel.queue_declare(queue="commands")
            channel.basic_consume(
                queue="commands", on_message_callback=_on_lock_down, auto_ack=True
            )
            channel.start_consuming()
        except Exception:
            time.sleep(5)


# rabbitMQ sync, `finance_sync`, all nodes manage files only by this thread.
def sync_listener():
    while True:
        try:
            # connect
            _, channel = _get_channel()
            channel.exchange_declare(exchange="finance_sync", exchange_type="fanout")
            channel.exchange_declare(exchange="finance_sync_ack", exchange_type="direct")
            
            # use durable queue instead of temp queue
            queue_name = f"sync_queue_{config.CLIENT_ID}"
            channel.queue_declare(queue=queue_name, durable=True)
            channel.queue_bind(exchange="finance_sync", queue=queue_name)
            
            # when reconnects MQ, send all stored messages (during the offline) out
            flush_offline_queue(channel)

            channel.basic_consume(
                queue=queue_name, on_message_callback=_on_sync_message, auto_ack=False
            )
            Logger.sync("Listener started / Reconnected")
            channel.start_consuming()
        except Exception as e:
            Logger.warning(f"Sync listener connection lost. Error: {e}")
            time.sleep(5)


def broadcast_sync(operation, filename, content="", v_clock=None):
    payload = {
        "sender": config.CLIENT_ID,
        "operation": operation,
        "filename": filename,
        "content": content,
        "v_clock": v_clock or utils.get_clock(filename),
    }
    
    try:
        # connect
        connection, channel = _get_channel()
        channel.exchange_declare(exchange="finance_sync", exchange_type="fanout")
        channel.exchange_declare(exchange="finance_sync_ack", exchange_type="direct")
        callback_queue = channel.queue_declare(queue="", exclusive=True).method.queue
        channel.queue_bind(
            exchange="finance_sync_ack", queue=callback_queue, routing_key=config.CLIENT_ID
        )
        
        # publish command
        corr_id = str(uuid.uuid4())

        channel.basic_publish(
            exchange="finance_sync",
            routing_key="",
            properties=pika.BasicProperties(reply_to=callback_queue, correlation_id=corr_id),
            body=json.dumps(payload),
        )
        Logger.sync(f"request for {operation}, {filename}, {content}")

        # starts to count ACK number, `finance_sync_ack`
        ack_count = 0

        def on_ack(ch, method, props, body):
            nonlocal ack_count
            if props.correlation_id == corr_id:
                ack_count += 1

        # starts listening ack
        channel.basic_consume(
            queue=callback_queue, on_message_callback=on_ack, auto_ack=True
        )

        start_time = time.time()
        # wait for 3 ACKs (assuming 4 nodes total, 1 sender, 3 receivers)
        while ack_count < 3 and (time.time() - start_time) <= 10:
            connection.process_data_events(time_limit=1)
        if ack_count < 3:
            Logger.warning(f"Sync timeout. Received {ack_count}/3 ACKs.")
        else:
            Logger.done(f"SYNC_OK Received {ack_count} ACKs")
        connection.close()
    except Exception as e:
        Logger.error(f"Cannot reach RabbitMQ: {e}")
        # save to local offline queue, wait until reconnects
        save_to_offline_queue(payload)
