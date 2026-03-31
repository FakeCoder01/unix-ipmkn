1. create local volume (w/ `shared_data`):

```bash
docker volume create shared_data
```

2. build the image:

```bash
docker build -t concurrent-task .
```

3. run:

- single instance

```bash
docker run -d --name worker1 --mount src=shared_data,target=/shared concurrent-task
```

- n instances (`n = 50`)

```bash
for i in $(seq 1 50); do
    docker run -d --name "worker_$i" --mount src=shared_data,target=/shared concurrent-task
done
```
