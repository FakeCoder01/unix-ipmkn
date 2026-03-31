FROM debian:stable-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends util-linux coreutils && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# define mount point for the shared volume
VOLUME ["/shared"]

ENTRYPOINT ["/app/entrypoint.sh"]
