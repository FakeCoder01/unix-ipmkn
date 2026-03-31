#### Практическая работа «Горизонтально масштабируемый сервис»

В рамках работы необходимо разработать сервис по микросервисной архитектуре, отвечающий следующим требованиям:

1. Сервис должен содержать контейнеры не менее двух различных типов и один брокер. В общем случае допускается реализация одного управляющего контейнера, одного брокера и множество тиражируемых контейнеров-работников, запускаемых из общего образа.
2. Сервис должен быть горизонтально масштабируемым. Другими словами, как минимум контейнер одного типа должен быть реплицируемым с балансировки нагрузки на все запущенные реплики.
3. Функциональность сервиса любая по интерес авторов.

---

# Text Analysis Pipeline - Horizontally Scalable Service

A microservice pipeline that accepts text jobs via an HTTP API, processes them
asynchronously through Kafka, and stores results in PostgreSQL, Redis, and S3.

---

## Details

### Container types

| Container | Role                                            | Scalable                   |
| --------- | ----------------------------------------------- | -------------------------- |
| `nginx`   | Reverse proxy / load balancer                   | - (stateless, 1 is enough) |
| `api`     | FastAPI REST service - submits/queries jobs     | `--scale api=N`            |
| `worker`  | Kafka consumer - processes text, writes results | `--scale worker=M`         |

### Managed services (no Docker)

| Service    | Provider    | Purpose                                     |
| ---------- | ----------- | ------------------------------------------- |
| Kafka      | Aiven Cloud | Message broker — decouples API from workers |
| PostgreSQL | Aiven Cloud | Persistent job storage                      |
| Redis      | Redis Cloud | Fast job status cache                       |
| S3         | Sufy        | Stores full result JSON files               |

---

## One-time Setup

### 1. Clone & configure

```bash
cp .env.example .env
# edit env with keys
```

### 2. Aiven — Kafka

1. Copy **Bootstrap URI** → `KAFKA_BOOTSTRAP_SERVERS` in `.env`
2. Download SSL certificates: Place `ca.pem`, `service.cert`, `service.key` in `./certs/`
3. Create the topic (run once):

```bash
pip install kafka-python
KAFKA_BOOTSTRAP_SERVERS=xxx python scripts/create_topic.py
```

### 3. Aiven — PostgreSQL

- Copy `POSTGRES_URL` in `.env`

### 4. Redis Cloud

- Paste into `REDIS_URL` in `.env`

### 5. Sufy — S3-compatible storage

1. put bucket name in `S3_BUCKET`
2. put Access Keys in `S3_ACCESS_KEY` / `S3_SECRET_KEY`
3. Set `S3_ENDPOINT_URL` eg. `https://s3.sufy.io`
4. Create the bucket (run once):

```bash
pip install boto3
python scripts/create_bucket.py
```

---

## Run

### Start (default 2 API + 3 workers)

```bash
docker compose up -d --build
```

### Scale workers dynamically

```bash
# scale to 5 workers and 3 API replicas while running
docker compose up -d --scale worker=5 --scale api=3
```

Kafka automatically rebalances partitions among the active workers - no
restart required. Each worker in the same consumer group (`KAFKA_GROUP_ID`)
receives a disjoint subset of Kafka partitions, guaranteeing each message
is processed **exactly once**.

### scale back down

```bash
docker compose up -d --scale worker=1
```

---

## API Reference

Base URL: `http://localhost` (goes through Nginx)

### submit a job

```bash
curl -X POST http://localhost/jobs \
  -H "Content-Type: application/json" \
  -d '{"text": "The quick brown fox jumps over the lazy dog."}'
```

resp:

```json
{
  "job_id": "3f8a...",
  "status": "pending"
}
```

### poll job status

```bash
curl http://localhost/jobs/3f8a...
```

resp (pending):

```json
{
  "job_id": "3f8a...",
  "status": "pending",
  "source": "cache"
}
```

Response (completed):

```json
{
  "job_id": "3f8a...",
  "status": "completed",
  "source": "cache",
  "worker_id": "worker-abc123",
  "result": {
    "word_count": 9,
    "char_count": 45,
    "sentence_count": 1,
    "unique_words": 9,
    "unique_words_ratio": 1.0,
    "avg_word_length": 3.89,
    "avg_sentence_length_words": 9.0,
    "flesch_reading_ease": 97.2,
    "top_keywords": [{"word": "quick", "count": 1}, ...],
    "most_common_word": "quick"
  }
}
```

### other endpoints

```
GET  /jobs           # list recent jobs (?status=pending|completed|failed)
GET  /stats          # job counts by status
GET  /health         # which API replica answered
```
