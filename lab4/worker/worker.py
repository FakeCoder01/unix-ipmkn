import json
import os
import re
import socket
import time
from collections import Counter
from datetime import datetime

import boto3
import psycopg2
import redis as redis_lib
from botocore.config import Config
from kafka import KafkaConsumer


WORKER_ID = socket.gethostname()  # identity

redis_client = redis_lib.from_url(os.environ["REDIS_URL"], decode_responses=True)


def get_conn():
    return psycopg2.connect(os.environ["POSTGRES_URL"])


s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT_URL"],
    aws_access_key_id=os.environ["S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    region_name=os.environ.get("S3_REGION", "auto"),
    config=Config(signature_version="s3v4"),
)
BUCKET = os.environ["S3_BUCKET"]

TOPIC = os.environ.get("KAFKA_TOPIC", "text-analysis")
GROUP_ID = os.environ.get("KAFKA_GROUP_ID", "text-analysis-workers")


_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "is",
    "are",
    "was",
    "were",
    "it",
    "this",
    "that",
    "i",
    "you",
    "he",
    "she",
    "we",
    "they",
    "be",
    "have",
    "do",
    "not",
    "as",
    "by",
    "from",
    "so",
    "if",
    "about",
    "up",
    "out",
}


def analyze(text: str) -> dict:
    words_raw = re.findall(r"[a-zA-Z']+", text.lower())
    words = [w for w in words_raw if len(w) > 1]
    filtered = [w for w in words if w not in _STOPWORDS]

    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    top_words = Counter(filtered).most_common(10)
    avg_word_len = round(sum(len(w) for w in words) / max(len(words), 1), 2)
    avg_sentence_len = round(len(words) / max(len(sentences), 1), 2)

    # flesch reading ease (approx)
    syllable_count = sum(_count_syllables(w) for w in words)
    if len(sentences) > 0 and len(words) > 0:
        flesch = round(
            206.835
            - 1.015 * (len(words) / len(sentences))
            - 84.6 * (syllable_count / max(len(words), 1)),
            1,
        )
    else:
        flesch = 0

    return {
        "word_count": len(words),
        "char_count": len(text),
        "char_count_no_spaces": len(text.replace(" ", "")),
        "sentence_count": len(sentences),
        "paragraph_count": len(paragraphs),
        "unique_words": len(set(words)),
        "unique_words_ratio": round(len(set(words)) / max(len(words), 1), 4),
        "avg_word_length": avg_word_len,
        "avg_sentence_length_words": avg_sentence_len,
        "syllable_count": syllable_count,
        "flesch_reading_ease": flesch,
        "top_keywords": [{"word": w, "count": c} for w, c in top_words],
        "most_common_word": top_words[0][0] if top_words else None,
    }


def _count_syllables(word: str) -> int:
    """rough syllable count via vowel groups."""
    word = word.lower()
    vowels = "aeiouy"
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if word.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)


### core job handler
def handle_job(job_id: str, text: str):
    print(f"[{WORKER_ID}] Processing job {job_id} ({len(text)} chars)")

    result = analyze(text)

    # upload result JSON to S3
    s3_key = f"results/{job_id}.json"
    payload = json.dumps(
        {
            "job_id": job_id,
            "worker_id": WORKER_ID,
            "result": result,
            "processed_at": datetime.utcnow().isoformat(),
        },
        indent=2,
    )
    s3.put_object(
        Bucket=BUCKET,
        Key=s3_key,
        Body=payload.encode("utf-8"),
        ContentType="application/json",
    )

    # update Postgres
    now = datetime.utcnow()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """UPDATE jobs
              SET status='completed', result=%s, worker_id=%s, updated_at=%s
            WHERE id=%s""",
        (json.dumps(result), WORKER_ID, now, job_id),
    )
    conn.commit()
    cur.close()
    conn.close()

    # refresh redis cache (TTL 1 h)
    redis_client.setex(
        f"job:{job_id}",
        3600,
        json.dumps(
            {
                "status": "completed",
                "result": result,
                "worker_id": WORKER_ID,
                "s3_key": s3_key,
            }
        ),
    )

    print(f"[{WORKER_ID}] Job {job_id} done — words={result['word_count']}")


def fail_job(job_id: str, error: str):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE jobs SET status='failed', worker_id=%s, updated_at=%s WHERE id=%s",
            (WORKER_ID, datetime.utcnow(), job_id),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass
    redis_client.setex(
        f"job:{job_id}",
        3600,
        json.dumps({"status": "failed", "error": error, "worker_id": WORKER_ID}),
    )


## kafka
def make_consumer() -> KafkaConsumer:
    kwargs: dict = dict(
        bootstrap_servers=os.environ["KAFKA_BOOTSTRAP_SERVERS"],
        group_id=GROUP_ID,  # shared group → Kafka load-balances partitions
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=False,  # manual commit after success
        max_poll_interval_ms=300_000,
        session_timeout_ms=30_000,
        heartbeat_interval_ms=10_000,
    )
    if os.environ.get("KAFKA_USE_SSL", "true").lower() == "true":
        kwargs.update(
            security_protocol="SSL",
            ssl_cafile="/app/certs/ca.pem",
            ssl_certfile="/app/certs/service.cert",
            ssl_keyfile="/app/certs/service.key",
        )
    return KafkaConsumer(TOPIC, **kwargs)


def main():
    print(f"[{WORKER_ID}] Starting — group={GROUP_ID} topic={TOPIC}")

    # retry kafka connection on startup
    for attempt in range(10):
        try:
            consumer = make_consumer()
            break
        except Exception as exc:
            print(f"[{WORKER_ID}] Kafka not ready ({exc}), retry {attempt + 1}/10 …")
            time.sleep(5)
    else:
        raise RuntimeError("Could not connect to Kafka after 10 attempts")

    print(f"[{WORKER_ID}] Connected to Kafka, consuming …")

    for message in consumer:
        data = message.value
        job_id = data.get("job_id", "unknown")
        text = data.get("text", "")
        try:
            handle_job(job_id, text)
            consumer.commit()
        except Exception as exc:
            print(f"[{WORKER_ID}] ERROR on job {job_id}: {exc}")
            fail_job(job_id, str(exc))
            consumer.commit()


if __name__ == "__main__":
    main()
