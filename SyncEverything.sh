#!/bin/bash
# sync-systemupdate.sh
#
# Systemupdate-Sync: synct das komplette airootfs/etc/skel (also
# .config, .icons, .local, .themes, .bash_profile, .gtkrc-2.0) nach
# $HOME. Wird IMMER komplett synct, auch Icon-/Cursor-/Theme-Dumps -
# keine Einmalig-Ausnahme mehr, alles wird wie jede andere Datei
# behandelt (inkl. Backup vor dem Ueberschreiben, falls schon
# vorhanden). Dauert dafuer bei den grossen Icon-Ordnern entsprechend
# laenger als frueher.
#
# Hat 2 Modi:
#
#   1. Normal (Standard, kein Flag):
#      nur etc/skel, kein Grub/Plymouth/Boot.
#
#   2. Voll (--full):
#      wie oben, PLUS das ganze Grub/Plymouth/Boot-relevante aus /etc -
#      inklusive leerer Ordner (damit die Struktur schon steht, auch
#      wenn da noch keine Dateien drin sind). Wird dabei tatsaechlich
#      was kopiert, laeuft am Ende automatisch grub-mkconfig + mkinitcpio.
#
# Die harte Blacklist (Passwoerter, SSH-Host-Keys, sudoers, Calamares,
# ...) bleibt in JEDEM Fall tabu, egal welcher Modus - auch wenn diese
# Pfade beim aktuellen Scope eh nicht vorkommen sollten, sie bleiben
# als Sicherheitsnetz drin.
#
# Aufruf: ./sync-systemupdate.sh [--dry-run] [--full]

AIROOTFS_DIR="/run/media/hopx/HopxSSD/TrafkSite/Projects/TrafkTux/TrafkTux/archiso/airootfs"
BACKUP_DIR="$HOME/.trafktux-sync-backups/$(date +%Y%m%d-%H%M%S)"

DRY_RUN=0
WITH_FULL=0

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --full) WITH_FULL=1 ;;
        *)
            echo "Unbekannte Option: $arg"
            echo "Erlaubt: --dry-run, --full"
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------
# Pfade, die NIEMALS synct werden, egal welcher Modus. Bash-Glob-
# Pattern relativ zu airootfs (also z.B. "etc/passwd"). Reines
# Sicherheitsnetz, betrifft beim aktuellen Scope normalerweise nichts.
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
    "etc/calamares/*"
)

# ---------------------------------------------------------------------
# Grub/Plymouth/Boot-relevantes - nur mit --full synct. Prefix-Match
# relativ zu airootfs (alles darunter zaehlt mit). Ergaenze die Liste
# einfach, falls euer Projekt weitere bootloader-/initramfs-relevante
# Pfade bekommt.
# ---------------------------------------------------------------------
SENSITIVE_PREFIXES=(
    "etc/grub"
    "etc/plymouth"
    "etc/default/grub"
    "etc/mkinitcpio.conf"
    "etc/mkinitcpio.d"
)

is_blacklisted() {
    local path="$1"
    for pattern in "${BLACKLIST[@]}"; do
        # shellcheck disable=SC2053
        [[ "$path" == $pattern ]] && return 0
    done
    return 1
}

matches_prefix_list() {
    local path="$1"
    shift
    local list=("$@")
    for prefix in "${list[@]}"; do
        [[ "$path" == "$prefix" || "$path" == "$prefix"/* ]] && return 0
    done
    return 1
}

resolve_target() {
    local rel_path="$1"
    if [[ "$rel_path" == "etc/skel/"* ]]; then
        local clean_path="${rel_path#etc/skel/}"
        TARGET_PATH="$HOME/$clean_path"
        USE_SUDO=""
    else
        TARGET_PATH="/$rel_path"
        USE_SUDO="sudo"
    fi
}

[[ $DRY_RUN -eq 1 ]] && echo "--- DRY RUN: es wird nichts wirklich kopiert, nur angezeigt ---"
if [[ $WITH_FULL -eq 1 ]]; then
    echo "--- VOLLER Modus: Grub/Plymouth/Boot-relevantes wird MIT synct ---"
else
    echo "--- Normaler Modus: Grub/Plymouth/Boot-relevantes wird NICHT angefasst (--full fuer alles) ---"
fi

echo "WARNUNG: Dieses Skript KOPIERT Dateien aus deinem Archiso-Ordner in dein lokales System."
echo "Synct das komplette etc/skel (mehr als das Arbeitsskript, das nur .config macht)."
if [[ $DRY_RUN -eq 0 ]]; then
    read -p "Willst du fortfahren? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

COPIED=0
SKIPPED_BLACKLIST=0
SKIPPED_SENSITIVE=0
BACKED_UP=0
SENSITIVE_COPIED=0

# ---------------------------------------------------------------------
# Im vollen Modus zuerst die komplette Ordnerstruktur unter den
# Grub/Plymouth/Boot-Pfaden anlegen - auch leere Ordner, damit du sie
# spaeter nicht manuell nachziehen musst.
# ---------------------------------------------------------------------
if [[ $DRY_RUN -eq 0 && $WITH_FULL -eq 1 ]]; then
    for prefix in "${SENSITIVE_PREFIXES[@]}"; do
        SRC_DIR="$AIROOTFS_DIR/$prefix"
        [ -d "$SRC_DIR" ] || continue
        while read -r DIR; do
            REL_DIR="${DIR#$AIROOTFS_DIR/}"
            resolve_target "$REL_DIR"
            [ -d "$TARGET_PATH" ] || $USE_SUDO mkdir -p "$TARGET_PATH"
        done < <(find "$SRC_DIR" -type d)
    done
fi

# ---------------------------------------------------------------------
# Zu durchsuchende Wurzeln: immer etc/skel, im vollen Modus zusaetzlich
# die tatsaechlich existierenden Grub/Plymouth/Boot-Pfade.
# ---------------------------------------------------------------------
SCAN_ROOTS=("$AIROOTFS_DIR/etc/skel")
if [[ $WITH_FULL -eq 1 ]]; then
    for prefix in "${SENSITIVE_PREFIXES[@]}"; do
        SRC_PATH="$AIROOTFS_DIR/$prefix"
        [ -e "$SRC_PATH" ] && SCAN_ROOTS+=("$SRC_PATH")
    done
fi

while read -r FILE; do

    REL_PATH="${FILE#$AIROOTFS_DIR/}"

    if is_blacklisted "$REL_PATH"; then
        echo "GESCHUETZT (Blacklist): $REL_PATH"
        SKIPPED_BLACKLIST=$((SKIPPED_BLACKLIST + 1))
        continue
    fi

    IS_SENS=0
    if matches_prefix_list "$REL_PATH" "${SENSITIVE_PREFIXES[@]}"; then
        IS_SENS=1
        if [[ $WITH_FULL -eq 0 ]]; then
            echo "UEBERSPRUNGEN (Grub/Plymouth/Boot, --full nicht gesetzt): $REL_PATH"
            SKIPPED_SENSITIVE=$((SKIPPED_SENSITIVE + 1))
            continue
        fi
    fi

    resolve_target "$REL_PATH"

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
    if [[ $IS_SENS -eq 1 ]]; then
        SENSITIVE_COPIED=$((SENSITIVE_COPIED + 1))
    fi
done < <(find "${SCAN_ROOTS[@]}" \( -type f -o -type l \))

echo ""
echo "Systemupdate abgeschlossen!"
echo "  Kopiert:                        $COPIED"
echo "  Geschuetzt (Blacklist):         $SKIPPED_BLACKLIST"
echo "  Uebersprungen (Grub/Plymouth):  $SKIPPED_SENSITIVE"
echo "  Gesichert vor Ueberschreiben:   $BACKED_UP"
if [[ $DRY_RUN -eq 0 && $BACKED_UP -gt 0 ]]; then
    echo "  Backups liegen unter: $BACKUP_DIR"
fi

if [[ $DRY_RUN -eq 0 && $WITH_FULL -eq 1 && $SENSITIVE_COPIED -gt 0 ]]; then
    echo ""
    echo "Grub/Plymouth/Boot-Sachen wurden geaendert - baue Grub-Config und Initramfs neu..."
    # Passe das an falls ihr statt Grub systemd-boot o.ae. nutzt.
    sudo grub-mkconfig -o /boot/grub/grub.cfg
    sudo mkinitcpio -P
fi

if [[ $DRY_RUN -eq 0 ]]; then
    systemctl --user daemon-reload
    systemctl --user restart wb-autohide.service wb-daemon.service
fi

echo ""
echo "Tipp: mit '--dry-run' kannst du vorher unverbindlich schauen, was passieren wuerde."
echo "Mit '--full' wird auch Grub/Plymouth/Boot mit synct (inkl. leerer Ordner)."
