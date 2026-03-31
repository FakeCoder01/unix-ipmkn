#!/bin/sh

SHARED_DIR="/shared"
LOCKFILE="$SHARED_DIR/.lockfile"
mkdir -p "$SHARED_DIR"

# gen unique ID for this container instance
CONTAINER_ID=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 8 | head -n 1)
FILE_COUNTER=0

echo "Container $CONTAINER_ID started."

# open a file descriptor for the lock file
exec 9>>"$LOCKFILE"

while true; do
    # <atomic op>
    # obtain exclusive lock on the file descriptor
    flock -x 9

    i=1
    while true; do
        FILE_NAME=$(printf "%03d" $i)
        FILE_PATH="$SHARED_DIR/$FILE_NAME"

        if [ ! -f "$FILE_PATH" ]; then
            # create the file immediately while holding the lock
            touch "$FILE_PATH"
            break
        fi
        i=$((i + 1))
    done

    # release the lock
    flock -u 9
    # </atomic op>

    FILE_COUNTER=$((FILE_COUNTER + 1))
    echo "ID: $CONTAINER_ID | Seq: $FILE_COUNTER" > "$FILE_PATH"

    sleep 1

    rm -f "$FILE_PATH"

    sleep 1
done
