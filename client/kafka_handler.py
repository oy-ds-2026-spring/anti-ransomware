import json
import time
import os
from kafka import KafkaProducer, KafkaConsumer
from client import config
from logger import Logger

# Kafka configuration
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
TOPIC_FILE_EVENTS = "file_events"
TOPIC_COMMANDS = "commands"

def get_producer():
    try:
        return KafkaProducer(
            bootstrap_servers=[KAFKA_BROKER],
            value_serializer=lambda x: json.dumps(x).encode('utf-8')
        )
    except Exception as e:
        Logger.warning(f"Kafka Producer Error: {e}")
        return None

def send_msg(file_path, entropy, event_type):
    """
    Sends a file event message to the Kafka 'file_events' topic.
    """
    producer = get_producer()
    if not producer:
        return

    try:
        payload = {
            "client_id": config.CLIENT_ID,
            "file_path": file_path,
            "entropy": entropy,
            "event_type": event_type,
            "timestamp": time.time(),
        }
        producer.send(TOPIC_FILE_EVENTS, value=payload)
        producer.flush()
        Logger.sent(f"[Kafka] {file_path} | Entropy: {entropy:.2f} | Event: {event_type}")
        producer.close()
    except Exception as e:
        Logger.warning(f"Kafka Send Error: {e}")

def lock_down_listener():
    """
    Listens for lockdown commands on the Kafka 'commands' topic.
    """
    while True:
        try:
            consumer = KafkaConsumer(
                TOPIC_COMMANDS,
                bootstrap_servers=[KAFKA_BROKER],
                auto_offset_reset='latest',
                enable_auto_commit=True,
                group_id=f'group_{config.CLIENT_ID}',
                value_deserializer=lambda x: json.loads(x.decode('utf-8'))
            )
            Logger.info("Kafka Lockdown Listener started")

            for message in consumer:
                # Trigger lockdown
                config.IS_LOCKED_DOWN = True
                Logger.lock_down(f"[Kafka] Command received! Isolating {config.CLIENT_ID}...")
                
                # Report status back via Kafka
                send_msg("SYSTEM_ISOLATED", 0, "LOCK_DOWN")
        except Exception as e:
            Logger.warning(f"Kafka Listener Error: {e}")
            time.sleep(5)