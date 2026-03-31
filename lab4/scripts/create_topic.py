#!/usr/bin/env python3
"""
creates the Kafka topic on Aiven with enough partitions for horizontal scaling.

Usage:
    pip install kafka-python
    python scripts/create_topic.py
"""

import os
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError

BOOTSTRAP = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
TOPIC = os.environ.get("KAFKA_TOPIC", "text-analysis")
PARTITIONS = int(os.environ.get("KAFKA_PARTITIONS", "6"))  # supports up to 6 workers
REPLICAS = int(os.environ.get("KAFKA_REPLICAS", "2"))  # Aiven default replication

admin = KafkaAdminClient(
    bootstrap_servers=BOOTSTRAP,
    security_protocol="SSL",
    ssl_cafile="certs/ca.pem",
    ssl_certfile="certs/service.cert",
    ssl_keyfile="certs/service.key",
)

try:
    admin.create_topics(
        [NewTopic(name=TOPIC, num_partitions=PARTITIONS, replication_factor=REPLICAS)]
    )
    print(f"✓ Topic '{TOPIC}' created with {PARTITIONS} partitions.")
except TopicAlreadyExistsError:
    print(f"Topic '{TOPIC}' already exists — nothing to do.")
finally:
    admin.close()
