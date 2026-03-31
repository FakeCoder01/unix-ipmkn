import json
import os
import uuid
from collections import Counter
from datetime import datetime

import psycopg2
import redis as redis_lib
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from kafka import KafkaProducer
from pydantic import BaseModel

app = FastAPI(title="Text Analysis Pipeline", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

redis_client = redis_lib.from_url(os.environ["REDIS_URL"], decode_responses=True)


def make_producer() -> KafkaProducer:
    kwargs: dict = dict(
        bootstrap_servers=os.environ["KAFKA_BOOTSTRAP_SERVERS"],
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
        acks="all",
        retries=3,
    )
    if os.environ.get("KAFKA_USE_SSL", "true").lower() == "true":
        kwargs.update(
            security_protocol="SSL",
            ssl_cafile="/app/certs/ca.pem",
            ssl_certfile="/app/certs/service.cert",
            ssl_keyfile="/app/certs/service.key",
        )
    return KafkaProducer(**kwargs)


producer: KafkaProducer | None = None

TOPIC = os.environ.get("KAFKA_TOPIC", "text-analysis")


def get_conn():
    return psycopg2.connect(os.environ["POSTGRES_URL"])


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id          UUID PRIMARY KEY,
            status      VARCHAR(20)  NOT NULL DEFAULT 'pending',
            input_text  TEXT         NOT NULL,
            result      JSONB,
            worker_id   VARCHAR(64),
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status);
        """
    )
    conn.commit()
    cur.close()
    conn.close()


@app.on_event("startup")
def startup():
    global producer
    init_db()
    producer = make_producer()
    print("API ready ✓")


@app.on_event("shutdown")
def shutdown():
    if producer:
        producer.close()


## models


class JobRequest(BaseModel):
    text: str


class JobResponse(BaseModel):
    job_id: str
    status: str


## routes


@app.get("/health")
def health():
    return {"status": "ok", "instance": os.environ.get("HOSTNAME", "unknown")}


@app.post("/jobs", response_model=JobResponse, status_code=202)
def create_job(req: JobRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")

    job_id = str(uuid.uuid4())
    now = datetime.utcnow()

    # persist in db
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO jobs (id, status, input_text, created_at, updated_at) VALUES (%s, %s, %s, %s, %s)",
        (job_id, "pending", req.text, now, now),
    )
    conn.commit()
    cur.close()
    conn.close()

    # cache initial status
    redis_client.setex(f"job:{job_id}", 3600, json.dumps({"status": "pending"}))

    # publish to Kafka (key = job_id ensures ordering per job)
    producer.send(TOPIC, key=job_id, value={"job_id": job_id, "text": req.text})
    producer.flush()

    return {"job_id": job_id, "status": "pending"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    # fast path: redis cache
    cached = redis_client.get(f"job:{job_id}")
    if cached:
        data = json.loads(cached)
        data["job_id"] = job_id
        data["source"] = "cache"
        return data

    # slow path: db
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT status, result, worker_id, created_at, updated_at FROM jobs WHERE id = %s",
        (job_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        "status": row[0],
        "result": row[1],
        "worker_id": row[2],
        "created_at": row[3].isoformat() if row[3] else None,
        "updated_at": row[4].isoformat() if row[4] else None,
        "source": "db",
    }


@app.get("/jobs")
def list_jobs(limit: int = 20, status: str | None = None):
    conn = get_conn()
    cur = conn.cursor()
    if status:
        cur.execute(
            "SELECT id, status, worker_id, created_at, updated_at FROM jobs WHERE status=%s ORDER BY created_at DESC LIMIT %s",
            (status, limit),
        )
    else:
        cur.execute(
            "SELECT id, status, worker_id, created_at, updated_at FROM jobs ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {
            "job_id": r[0],
            "status": r[1],
            "worker_id": r[2],
            "created_at": r[3].isoformat() if r[3] else None,
            "updated_at": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]


@app.get("/stats")
def stats():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {r[0]: r[1] for r in rows}
