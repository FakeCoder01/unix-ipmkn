#!/bin/bash -e

E_USAGE=1
E_NOTFOUND=2
E_NOTARGET=3
E_BUILDFAIL=4

cleanup() {
    local rc=$?
    trap - EXIT
    [ -n "$TEMP_DIR" ] && rm -rf "$TEMP_DIR"
    exit $rc
}

# traps for signals and exit
trap cleanup EXIT HUP INT QUIT TERM

# valdiate args
if [ -z "$1" ] || [ ! -f "$1" ]; then
    echo "Usage: $0 <source_file>" >&2
    exit $E_USAGE
fi

SOURCE_FILE="$1"
# just the filename
FILENAME="${SOURCE_FILE##*/}"
# get the directory where the source file lives
SOURCE_DIR=$(cd "$(dirname "$SOURCE_FILE")" && pwd)

#  for parse 'Output:' comment
TARGET_NAME=$(grep "Output:" "$SOURCE_FILE" | head -n 1 | sed 's/.*Output:[[:space:]]*//;s/[[:space:]]*$//')

if [ -z "$TARGET_NAME" ]; then
    echo "Error: 'Output:' directive not found in $SOURCE_FILE" >&2
    exit $E_NOTARGET
fi

# setup tmp dir
TEMP_DIR=$(mktemp -d)
cp "$SOURCE_FILE" "$TEMP_DIR/"
cd "$TEMP_DIR"

# build lagic (based on ext)
EXT="${FILENAME##*.}"

case "$EXT" in
    c)
        cc -o "$TARGET_NAME" "$FILENAME" || exit $E_BUILDFAIL
        ;;
    cpp|cc|cxx)
        g++ -o "$TARGET_NAME" "$FILENAME" || exit $E_BUILDFAIL
        ;;
    tex)
        # for TeX = use pdflatex
        # then rename the output if necessary
        pdflatex -interaction=nonstopmode "$FILENAME" > /dev/null || exit $E_BUILDFAIL
        # rename <filename>.pdf to match the 'Output:'
        CURRENT_OUT="${FILENAME%.tex}.pdf"
        if [ "$CURRENT_OUT" != "$TARGET_NAME" ]; then
            mv "$CURRENT_OUT" "$TARGET_NAME"
        fi
        ;;
    *)
        echo "Error: Unsupported file extension .$EXT" >&2
        exit $E_USAGE
        ;;
esac

# move the target file back to the source directory
if [ -f "$TARGET_NAME" ]; then
    mv "$TARGET_NAME" "$SOURCE_DIR/"
    echo "Build successful: $SOURCE_DIR/$TARGET_NAME"
else
    echo "Error: Target file was not created." >&2
    exit $E_BUILDFAIL
fi

exit 0
