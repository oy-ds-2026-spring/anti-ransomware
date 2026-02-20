import pika
import config
import time
import json
import uuid
import utils


# send msg to RabbitMQ
def send_msg(file_path, entropy, event_type):
    try:
        # init short connection for every sending
        credentials = pika.PlainCredentials("guest", "guest")
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=config.BROKER_HOST, credentials=credentials)
        )
        channel = connection.channel()

        channel.queue_declare(queue="file_events")

        payload = {
            "client_id": config.CLIENT_ID,
            "file_path": file_path,
            "entropy": entropy,
            "event_type": event_type,
            "timestamp": time.time(),
        }

        channel.basic_publish(exchange="", routing_key="file_events", body=json.dumps(payload))
        print(
            f"[SENT] {file_path} | Entropy: {entropy:.2f} | Event: {event_type}"
        )  # Add event type to output
        connection.close()
    except Exception as e:
        print(f"[ERROR] RabbitMQ Error: {e}")


# listen to RabbitMQ
def lock_down_listener():
    while True:
        try:
            credentials = pika.PlainCredentials("guest", "guest")
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=config.BROKER_HOST, credentials=credentials)
            )
            channel = connection.channel()
            channel.queue_declare(queue="commands")

            def callback(ch, method, properties, body):
                msg = json.loads(body)

                config.IS_LOCKED_DOWN = True
                print(f"[LOCK_DOWN] Command received! Isolating {config.CLIENT_ID}...")
                # report ok
                send_msg("SYSTEM_ISOLATED", 0, "LOCK_DOWN")

            channel.basic_consume(queue="commands", on_message_callback=callback, auto_ack=True)
            channel.start_consuming()
        except Exception as e:
            time.sleep(5)


# rabbitMQ sync, `finance_sync`, all nodes manage files only by this thread.
def sync_listener():
    while True:
        try:
            # connect
            credentials = pika.PlainCredentials("guest", "guest")
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=config.BROKER_HOST, credentials=credentials)
            )
            channel = connection.channel()
            channel.exchange_declare(exchange="finance_sync", exchange_type="fanout")

            result = channel.queue_declare(queue="", exclusive=True)
            queue_name = result.method.queue
            channel.queue_bind(exchange="finance_sync", queue=queue_name)

            def callback(ch, method, properties, body):
                msg = json.loads(body)
                sender = msg.get("sender")
                if sender == config.CLIENT_ID:
                    return

                # wait for permission (Snapshot consistency)
                config.WRITE_PERMISSION.wait()

                op = msg.get("operation")
                filename = msg.get("filename")
                content = msg.get("content", "")

                try:
                    if op == "CREATE":
                        utils.local_create(filename, content)
                    elif op == "WRITE":
                        utils.local_write(filename, content)
                    elif op == "DELETE":
                        utils.local_delete(filename)

                    # send ACK
                    if properties.reply_to:
                        reply_props = pika.BasicProperties(correlation_id=properties.correlation_id)
                        ch.basic_publish(
                            exchange="",
                            routing_key=properties.reply_to,
                            properties=reply_props,
                            body=json.dumps({"status": "ACK", "sender": config.CLIENT_ID}),
                        )
                        print(f"[SYNC_ACK] Sent ACK for {op}, {filename}")
                except Exception as e:
                    print(f"[ERROR] Sync processing failed: {e}")

            # starts listening
            channel.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=True)
            print("[SYNC] Listener started")
            channel.start_consuming()
        except Exception as e:
            print(f"[ERROR] Sync listener connection lost: {e}")
            time.sleep(5)


# primary client write node send function
def broadcast_sync(operation, filename, content=""):
    # connect
    credentials = pika.PlainCredentials("guest", "guest")
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=config.BROKER_HOST, credentials=credentials)
    )
    channel = connection.channel()

    channel.exchange_declare(exchange="finance_sync", exchange_type="fanout")
    result = channel.queue_declare(queue="", exclusive=True)
    callback_queue = result.method.queue

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
        properties=pika.BasicProperties(
            reply_to=callback_queue,
            correlation_id=corr_id,
        ),
        body=json.dumps(payload),
    )
    print(f"[SYNC] request for {operation}, {filename}, {content}")

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
    while ack_count < 3:
        connection.process_data_events(time_limit=1)
        if time.time() - start_time > 10:
            print(f"[WARNING] Sync timeout. Received {ack_count}/3 ACKs.")
            break

    print(f"[🍺 SYNC_OK] Received {ack_count} ACKs")
    connection.close()
