#!/bin/bash
# sync-arbeitsskript.sh
#
# Schneller/sicherer Alltags-Sync: synct NUR airootfs/etc/skel/.config
# nach ~/.config. Sonst nichts - kein restliches etc/, kein opt/, kein
# usr/ (das ist alles nur fuer den ISO-Build relevant, nicht fuer dein
# laufendes System).
#
#   - clay-icons und der TrafkCursor_Build-Ordner werden IMMER
#     uebersprungen, ganz ohne nachzuschauen ob's bei dir schon
#     existiert (dauert ewig, aendert sich eh kaum) - dafuer gibt's
#     sync-systemupdate.sh.
#
# Aufruf: ./sync-arbeitsskript.sh [--dry-run]

AIROOTFS_DIR="/run/media/hopx/HopxSSD/TrafkSite/Projects/TrafkTux/TrafkTux/archiso/airootfs"
CONFIG_SRC="$AIROOTFS_DIR/etc/skel/.config"
BACKUP_DIR="$HOME/.trafktux-sync-backups/$(date +%Y%m%d-%H%M%S)"

DRY_RUN=0
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=1
    echo "--- DRY RUN: es wird nichts wirklich kopiert, nur angezeigt ---"
fi

# ---------------------------------------------------------------------
# Werden hier IMMER uebersprungen, relativ zu .config. Prefix-Match.
# ---------------------------------------------------------------------
ONCE_ONLY_PREFIXES=(
    "clay-icons"
    "hypr/TrafkCursor_Build"
)

matches_prefix_list() {
    local path="$1"
    shift
    local list=("$@")
    for prefix in "${list[@]}"; do
        [[ "$path" == "$prefix" || "$path" == "$prefix"/* ]] && return 0
    done
    return 1
}

echo "WARNUNG: Dieses Skript KOPIERT Dateien aus deinem Archiso-Ordner in dein lokales System."
if [[ $DRY_RUN -eq 0 ]]; then
    read -p "Willst du fortfahren? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

COPIED=0
SKIPPED_ONCE_ONLY=0
BACKED_UP=0

while read -r FILE; do

    REL_PATH="${FILE#$CONFIG_SRC/}"
    TARGET_PATH="$HOME/.config/$REL_PATH"

    if matches_prefix_list "$REL_PATH" "${ONCE_ONLY_PREFIXES[@]}"; then
       # echo "UEBERSPRUNGEN (Icons/Cursor, siehe sync-systemupdate.sh): $REL_PATH"
        SKIPPED_ONCE_ONLY=$((SKIPPED_ONCE_ONLY + 1))
        continue
    fi

    if [[ $DRY_RUN -eq 1 ]]; then
        echo "WUERDE KOPIEREN: $FILE -> $TARGET_PATH"
        continue
    fi

    # Existierendes Ziel vor dem Ueberschreiben sichern
    if [ -e "$TARGET_PATH" ]; then
        BACKUP_TARGET="$BACKUP_DIR/.config/$REL_PATH"
        mkdir -p "$(dirname "$BACKUP_TARGET")"
        cp -a "$TARGET_PATH" "$BACKUP_TARGET"
        BACKED_UP=$((BACKED_UP + 1))
    fi

    TARGET_DIR="$(dirname "$TARGET_PATH")"
    [ -d "$TARGET_DIR" ] || mkdir -p "$TARGET_DIR"

    cp -P "$FILE" "$TARGET_PATH"

    echo "Kopiert: $FILE -> $TARGET_PATH"
    COPIED=$((COPIED + 1))
done < <(find "$CONFIG_SRC" \( -type f -o -type l \))

echo ""
echo "Kopiervorgang abgeschlossen!"
echo "  Kopiert:                       $COPIED"
echo "  Uebersprungen (Icons/Cursor):  $SKIPPED_ONCE_ONLY"
echo "  Gesichert vor Ueberschreiben:  $BACKED_UP"
if [[ $DRY_RUN -eq 0 && $BACKED_UP -gt 0 ]]; then
    echo "  Backups liegen unter: $BACKUP_DIR"
fi

if [[ $DRY_RUN -eq 0 ]]; then
    systemctl --user daemon-reload
    systemctl --user restart wb-autohide.service wb-daemon.service
fi

echo ""
echo "Tipp: mit '--dry-run' kannst du vorher unverbindlich schauen, was passieren wuerde."
echo "Fuer .icons/.local/.themes/dotfiles oder Grub/Plymouth/Boot: sync-systemupdate.sh benutzen."
