#!/bin/bash

AIROOTFS_DIR="/run/media/hopx/HopxSSD/TrafkSite/Projects/TrafkTux/TrafkTux/archiso/airootfs"
BACKUP_DIR="$HOME/.trafktux-sync-backups/$(date +%Y%m%d-%H%M%S)"

DRY_RUN=0
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=1
    echo "--- DRY RUN: es wird nichts wirklich kopiert, nur angezeigt ---"
fi

# ---------------------------------------------------------------------
# Pfade, die NIEMALS synct werden - egal was im airootfs steht.
# Betrifft System-Identitaet, Zugangsdaten und Sachen, die nur fuer die
# Live-ISO/Calamares gedacht sind, nicht fuer dein echtes System.
# Bash-Glob-Pattern relativ zu airootfs (also z.B. "etc/passwd").
# ---------------------------------------------------------------------
BLACKLIST=(
    "etc/passwd"
    "etc/passwd-"
    "etc/shadow"
    "etc/shadow-"
    "etc/gshadow"
    "etc/gshadow-"
    "etc/group"
    "etc/group-"
    "etc/hostname"
    "etc/machine-id"
    "etc/fstab"
    "etc/sudoers"
    "etc/sudoers.d/*"
    "etc/ssh/ssh_host_*"
    "etc/polkit-1/rules.d/60-trafktux-calamares.rules"
    "etc/pacman.d/hooks/liveuser.hook"
    "usr/local/bin/create-liveuser.sh"
    "etc/systemd/system/getty@tty1.service.d/*"
    "etc/calamares/*"
    "root/*"
)

# ---------------------------------------------------------------------
# Ordner, die nur EINMAL synct werden (wenn bei dir noch nicht vorhanden).
# Existiert das Ziel schon, wird es NIE WIEDER angefasst/ueberschrieben -
# spart bei jedem weiteren Sync das Durchlaufen der riesigen Icon/Theme-
# Dumps, die sich eh nicht mehr aendern.
# ---------------------------------------------------------------------
SYNC_ONCE_ONLY=(
    "etc/skel/.config/clay-icons"
    "etc/skel/.themes/Colloid-Light-Dracula"
    # Kompletter hyprpm-State (Header + state.toml + .so, siehe
    # build-hyprland-plugins.sh) ist dauerhaft im airootfs abgelegt und
    # aendert sich nur wenn build-hyprland-plugins.sh neu laeuft - genau wie
    # die Icon/Theme-Dumps oben nicht bei jedem Sync neu durchsucht werden muss.
    "opt/trafktux-hyprpm-cache"
    "etc/skel/.icons"
    "etc/skel/.local/share/icons"
    "etc/pacman.conf"
)

is_blacklisted() {
    local path="$1"
    for pattern in "${BLACKLIST[@]}"; do
        # shellcheck disable=SC2053
        [[ "$path" == $pattern ]] && return 0
    done
    return 1
}

sync_once_only_match() {
    local path="$1"
    for pattern in "${SYNC_ONCE_ONLY[@]}"; do
        [[ "$path" == "$pattern"* ]] && return 0
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
SKIPPED_BLACKLIST=0
SKIPPED_MISSING=0
BACKED_UP=0

while read -r FILE; do

    REL_PATH="${FILE#$AIROOTFS_DIR/}"

    if is_blacklisted "$REL_PATH"; then
        echo "GESCHUETZT (nicht angefasst): $REL_PATH"
        SKIPPED_BLACKLIST=$((SKIPPED_BLACKLIST + 1))
        continue
    fi

    if [[ "$REL_PATH" == "etc/skel/"* ]]; then
        CLEAN_PATH="${REL_PATH#etc/skel/}"
        TARGET_PATH="$HOME/$CLEAN_PATH"
        USE_SUDO=""
    else
        TARGET_PATH="/$REL_PATH"
        USE_SUDO="sudo"
    fi

    if sync_once_only_match "$REL_PATH" && [ -e "$TARGET_PATH" ]; then
        echo "UEBERSPRUNGEN (schon vorhanden, wird nicht erneut synct): $REL_PATH"
        SKIPPED_MISSING=$((SKIPPED_MISSING + 1))
        continue
    fi

    if [[ $DRY_RUN -eq 1 ]]; then
        echo "WUERDE KOPIEREN: $FILE -> $TARGET_PATH"
        continue
    fi

    # Existierendes Ziel vor dem Ueberschreiben sichern
    if [ -e "$TARGET_PATH" ]; then
        BACKUP_TARGET="$BACKUP_DIR/$REL_PATH"
        $USE_SUDO mkdir -p "$(dirname "$BACKUP_TARGET")"
        $USE_SUDO cp -a "$TARGET_PATH" "$BACKUP_TARGET"
        BACKED_UP=$((BACKED_UP + 1))
    fi

    TARGET_DIR="$(dirname "$TARGET_PATH")"
    if [ ! -d "$TARGET_DIR" ]; then
        $USE_SUDO mkdir -p "$TARGET_DIR"
    fi

    $USE_SUDO cp -P "$FILE" "$TARGET_PATH"

    echo "Kopiert: $FILE -> $TARGET_PATH"
    COPIED=$((COPIED + 1))
done < <(find "$AIROOTFS_DIR" \( -type f -o -type l \))

SKIPPED_MISSING=$((SKIPPED_MISSING - 3301))

echo ""
echo "Kopiervorgang abgeschlossen!"
echo "  Kopiert:                 $COPIED"
echo "  Geschuetzt (Blacklist):  $SKIPPED_BLACKLIST"
echo "  Uebersprungen (fehlend): $SKIPPED_MISSING"
echo "  Gesichert vor Ueberschreiben: $BACKED_UP"
if [[ $DRY_RUN -eq 0 && $BACKED_UP -gt 0 ]]; then
    echo "  Backups liegen unter: $BACKUP_DIR"
fi

systemctl --user daemon-reload
systemctl --user restart wb-autohide.service wb-daemon.service

echo ""
echo "Tipp: mit '--dry-run' kannst du vorher unverbindlich schauen, was passieren wuerde."
