import pika
import config
import time
import json
import uuid

import utils
from logger import Logger


def _on_sync_message(ch, method, properties, body):
    msg = json.loads(body)

    # not listen to self
    if msg.get("sender") == config.CLIENT_ID:
        return

    # wait for snapshot if needed
    config.WRITE_PERMISSION.wait()

    op, filename, content = msg.get("operation"), msg.get("filename"), msg.get("content", "")

    try:
        if op == "CREATE":
            utils.local_create(filename, content)
        elif op == "WRITE":
            utils.local_write(filename, content)
        elif op == "DELETE":
            utils.local_delete(filename)

        # after operation reply SYNC_ACK
        if properties.reply_to:
            ch.basic_publish(
                exchange="",
                routing_key=properties.reply_to,
                properties=pika.BasicProperties(correlation_id=properties.correlation_id),
                body=json.dumps({"status": "ACK", "sender": config.CLIENT_ID}),
            )
            Logger.done(f"ACK sent for {op}, {filename}")

    except Exception as e:
        Logger.warning(f"Sync processing failed: {e}")


# mq connectionection
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
        }

        channel.basic_publish(exchange="", routing_key="file_events", body=json.dumps(payload))
        Logger.sent(f"{file_path} | Entropy: {entropy:.2f} | Event: {event_type}")
        connection.close()
    except Exception as e:
        Logger.warning(f"RabbitMQ Error: {e}")


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
        except Exception as e:
            time.sleep(5)


# rabbitMQ sync, `finance_sync`, all nodes manage files only by this thread.
def sync_listener():
    while True:
        try:
            # connect
            _, channel = _get_channel()
            channel.exchange_declare(exchange="finance_sync", exchange_type="fanout")
            queue_name = channel.queue_declare(queue="", exclusive=True).method.queue
            channel.queue_bind(exchange="finance_sync", queue=queue_name)

            channel.basic_consume(
                queue=queue_name, on_message_callback=_on_sync_message, auto_ack=True
            )
            Logger.sync("Listener started")
            channel.start_consuming()
        except Exception as e:
            Logger.warning(f"Sync listener connection lost: {e}")
            time.sleep(5)


def broadcast_sync(operation, filename, content=""):
    # connect
    connection, channel = _get_channel()
    channel.exchange_declare(exchange="finance_sync", exchange_type="fanout")
    callback_queue = channel.queue_declare(queue="", exclusive=True).method.queue

    # publish command
    corr_id = str(uuid.uuid4())
    payload = {
        "sender": config.CLIENT_ID,
        "operation": operation,
        "filename": filename,
        "content": content,
    }

    channel.basic_publish(
        exchange="finance_sync",
        routing_key="",
        properties=pika.BasicProperties(reply_to=callback_queue, correlation_id=corr_id),
        body=json.dumps(payload),
    )
    Logger.sync(f"request for {operation}, {filename}, {content}")

    # starts to count ACK number
    ack_count = 0

    def on_ack(ch, method, props, body):
        nonlocal ack_count
        if props.correlation_id == corr_id:
            ack_count += 1

    # starts listening ack
    channel.basic_consume(queue=callback_queue, on_message_callback=on_ack, auto_ack=True)

    start_time = time.time()
    # wait for 3 ACKs (assuming 4 nodes total, 1 sender, 3 receivers)
    while ack_count < 3 and (time.time() - start_time) <= 10:
        connection.process_data_events(time_limit=1)
    if ack_count < 3:
        Logger.warning(f"Sync timeout. Received {ack_count}/3 ACKs.")
    else:
        Logger.done(f"SYNC_OK Received {ack_count} ACKs")
    connection.close()
