#!/bin/bash

AIROOTFS_DIR="/run/media/hopx/HopxSSD/TrafkSite/Projects/TrafkTux/TrafkTux/archiso/airootfs"

echo "WARNUNG: Dieses Skript KOPIERT Dateien aus deinem Archiso-Ordner in dein lokales System."
read -p "Willst du fortfahren? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

find "$AIROOTFS_DIR" -type f | while read -r FILE; do
    
    REL_PATH="${FILE#$AIROOTFS_DIR/}"
    
    if [[ "$REL_PATH" == "etc/skel/"* ]]; then
        CLEAN_PATH="${REL_PATH#etc/skel/}"
        TARGET_PATH="$HOME/$CLEAN_PATH"
        USE_SUDO=""
    else
        TARGET_PATH="/$REL_PATH"
        USE_SUDO="sudo"
    fi

    TARGET_DIR="$(dirname "$TARGET_PATH")"

    if [ ! -d "$TARGET_DIR" ]; then
        $USE_SUDO mkdir -p "$TARGET_DIR"
    fi

    $USE_SUDO cp "$FILE" "$TARGET_PATH"

    echo "Kopiert: $FILE -> $TARGET_PATH"
done

echo "Kopiervorgang abgeschlossen!"
