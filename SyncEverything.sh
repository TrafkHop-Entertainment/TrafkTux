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
# Zusaetzlich zu etc/skel/etc/xdg/usr/share werden IMMER auch
# etc/ufw und etc/default gescannt (SYSTEM_CONFIG_ROOTS) - das sind
# System-weite Runtime-Configs (UFW, kuenftig z.B. systemd-resolved
# fuer DNS-over-TLS), die kein Boot-relevantes Grub/Plymouth-Zeug
# sind und daher nicht hinter --full liegen sollen, aber trotzdem
# ausserhalb von etc/skel liegen. Einfach SYSTEM_CONFIG_ROOTS unten
# erweitern, wenn weitere solche Pfade dazukommen.
#
# Hat 3 Modi (kombinierbar):
#
#   1. Normal (Standard, kein Flag):
#      etc/skel, etc/xdg, usr/share, System-Configs (etc/ufw, etc/default
#      etc.) - kein Grub/Plymouth/Boot.
#
#   2. Voll (--full):
#      wie oben, PLUS das ganze Grub/Plymouth/Boot-relevante aus /etc -
#      inklusive leerer Ordner (damit die Struktur schon steht, auch
#      wenn da noch keine Dateien drin sind). Wird dabei tatsaechlich
#      was kopiert, laeuft am Ende automatisch grub-mkconfig + mkinitcpio.
#
#   3. Schnell (--fast):
#      wie der jeweils aktive Modus, PLUS die grossen Icon-/Theme-Dumps
#      (.icons, .themes, .local/share/icons, .local/share/themes,
#      .local/share/fonts) werden komplett uebersprungen. Fuer den Fall,
#      dass sich an denen eh nichts geaendert hat und man nur schnell
#      die restlichen Configs nachziehen will. Kombinierbar mit --full.
#
# Die harte Blacklist (Passwoerter, SSH-Host-Keys, sudoers, Calamares,
# ...) bleibt in JEDEM Fall tabu, egal welcher Modus - auch wenn diese
# Pfade beim aktuellen Scope eh nicht vorkommen sollten, sie bleiben
# als Sicherheitsnetz drin.
#
# Aufruf: ./sync-systemupdate.sh [--dry-run] [--full] [--fast]

AIROOTFS_DIR="/run/media/hopx/HopxSSD/TrafkSite/Projects/TrafkTux/TrafkTux/archiso/airootfs"
BACKUP_DIR="$HOME/.trafktux-sync-backups/$(date +%Y%m%d-%H%M%S)"

DRY_RUN=0
WITH_FULL=0
FAST=0

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --full) WITH_FULL=1 ;;
        --fast) FAST=1 ;;
        *)
            echo "Unbekannte Option: $arg"
            echo "Erlaubt: --dry-run, --full, --fast"
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
# Grub/Boot-relevantes - nur mit --full synct (loest danach automatisch
# grub-mkconfig + mkinitcpio aus). Prefix-Match relativ zu airootfs.
# Plymouth-Theme (usr/share/plymouth) bewusst NICHT hier drin - synct
# immer mit, egal welcher Modus, aber loest dafuer auch KEIN
# automatisches mkinitcpio -P mehr aus. Fuers schnelle Optik-Testen
# reicht eh "plymouth --show-splash" ohne frisches Initramfs; fuer den
# echten Boot-Test danach manuell "sudo mkinitcpio -P" bzw.
# "plymouth-set-default-theme -R trafktux" laufen lassen.
# ---------------------------------------------------------------------
SENSITIVE_PREFIXES=(
    "etc/grub"
    "etc/grub.d"
    "etc/plymouth"
    "etc/default/grub"
    "etc/mkinitcpio.conf"
    "etc/mkinitcpio.d"
    "boot/grub/themes"
    "etc/sddm.conf.d"
)

# ---------------------------------------------------------------------
# Grosse Icon-/Theme-/Cursor-Dumps - werden nur mit --fast uebersprungen
# (in JEDEM anderen Fall, egal ob normal oder --full, ganz normal mit
# synct). Prefix-Match relativ zu airootfs. Ergaenze die Liste einfach,
# falls euer Projekt weitere grosse Dump-Ordner bekommt. Deckt auch das
# ab, was frueher sync-arbeitsskript.sh (clay-icons, TrafkCursor_Build)
# uebersprungen hat.
# ---------------------------------------------------------------------
HEAVY_PREFIXES=(
    "etc/skel/.icons"
    "etc/skel/.themes"
    "etc/skel/.local/share/icons"
    "etc/skel/.local/share/themes"
    "etc/skel/.local/share/fonts"
    "etc/skel/.config/clay-icons"
    "etc/skel/.config/hypr/TrafkCursor_Build"
    "usr/share/icons"
)

# ---------------------------------------------------------------------
# System-weite Runtime-Configs (KEIN Boot-Zeug, also nicht hinter
# --full versteckt) die ausserhalb von etc/skel/etc/xdg/usr/share
# liegen. Werden IMMER gescannt, in jedem Modus. Achtung: die
# BLACKLIST oben hat trotzdem Vorrang (z.B. falls hier mal versehentlich
# ein Pfad reinrutscht der Passwoerter/Keys enthaelt).
#
# Aktuell drin: etc/ufw (UFW-Firewall-Konfiguration), etc/default
# (u.a. etc/default/ufw - Achtung, etc/default/grub liegt zwar
# technisch auch hier drunter, ist aber oben in SENSITIVE_PREFIXES
# explizit gelistet und wird daher trotzdem nur mit --full mitgenommen,
# die beiden Listen ueberschneiden sich hier bewusst nicht destruktiv),
# etc/systemd (u.a. resolved.conf fuer DNS-over-TLS, sowie die
# system/*.service Symlinks - keine Secrets drin, daher unproblematisch)
# und etc/NetworkManager (u.a. conf.d/dns.conf, das NM anweist DNS an
# systemd-resolved abzugeben statt /etc/resolv.conf selbst zu schreiben).
# Neu dazu: etc/sysctl.d (u.a. 99-trafktux-hardening.conf mit den
# sysctl-Haertungen - kernel/net/fs Settings, keine Secrets drin),
# etc/security (u.a. pwquality.conf - die Passwort-Policy selbst,
# keine Secrets) und etc/pam.d (u.a. die "passwd"-Datei die
# pam_pwquality einbindet - ACHTUNG: liegt zwar im selben Ordner wie
# potenziell sensible PAM-Stacks, aber etc/pam.d/* enthaelt selbst nie
# Passwoerter/Hashes, nur Regeln WIE Auth ablaeuft - unproblematisch
# fuer den Sync).
#
# Einfach weiter erweitern falls kuenftig noch mehr System-Configs
# dazukommen.
# ---------------------------------------------------------------------
SYSTEM_CONFIG_ROOTS=(
    "etc/ufw"
    "etc/default"
    "etc/systemd"
    "etc/NetworkManager"
    "etc/sysctl.d"
    "etc/security"
    "etc/pam.d"
)

# ---------------------------------------------------------------------
# Einzelne Top-Level-Dateien (KEINE Ordner!) die trotzdem immer mit
# synct werden sollen. Der find-basierte Scan oben erfasst nur Dateien
# INNERHALB von SCAN_ROOTS-Ordnern - eine einzelne Datei direkt in
# etc/ (wie etc/resolv.conf, i.d.R. ein Symlink auf
# /run/systemd/resolve/stub-resolv.conf fuer DNS-over-TLS) faellt sonst
# komplett durchs Raster, selbst wenn sie inhaltlich zu den System-
# Configs gehoert. Werden wie SYSTEM_CONFIG_ROOTS immer gescannt (auch
# ohne --full), die BLACKLIST hat aber trotzdem Vorrang.
# ---------------------------------------------------------------------
SYSTEM_CONFIG_FILES=(
    "etc/resolv.conf"
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

# ---------------------------------------------------------------------
# Baut das find-Kommando als Array. Im --fast Modus werden die
# HEAVY_PREFIXES Ordner per "-prune" komplett von der Traversierung
# ausgeschlossen, statt (wie vorher) jede einzelne Datei darin erst
# aufzulisten und danach pro Datei wieder zu verwerfen - bei grossen
# Icon-/Theme-Dumps (oder gleich ganz usr/share) potenziell zehntausende
# Dateien, die find/bash sonst unnoetig anfassen. Ergebnis ist exakt
# dieselbe Dateimenge wie vorher, nur ohne den Umweg ueber "auflisten,
# dann pro Datei wegwerfen".
# ---------------------------------------------------------------------
build_find_cmd() {
    FIND_CMD=(find "${SCAN_ROOTS[@]}")

    local prune_paths=()
    if [[ $FAST -eq 1 ]]; then
        for prefix in "${HEAVY_PREFIXES[@]}"; do
            prune_paths+=("$AIROOTFS_DIR/$prefix")
        done
    fi

    if [[ ${#prune_paths[@]} -gt 0 ]]; then
        FIND_CMD+=("(")
        local first=1
        for p in "${prune_paths[@]}"; do
            [[ $first -eq 0 ]] && FIND_CMD+=("-o")
            FIND_CMD+=("-path" "$p" "-o" "-path" "$p/*")
            first=0
        done
        FIND_CMD+=(")" "-prune" "-o" "(" "-type" "f" "-o" "-type" "l" ")" "-print")
    else
        FIND_CMD+=("(" "-type" "f" "-o" "-type" "l" ")")
    fi
}

[[ $DRY_RUN -eq 1 ]] && echo "--- DRY RUN: es wird nichts wirklich kopiert, nur angezeigt ---"
if [[ $WITH_FULL -eq 1 ]]; then
    echo "--- VOLLER Modus: Grub/Plymouth/Boot-relevantes wird MIT synct ---"
else
    echo "--- Normaler Modus: Grub/Plymouth/Boot-relevantes wird NICHT angefasst (--full fuer alles) ---"
fi
if [[ $FAST -eq 1 ]]; then
    echo "--- SCHNELL-Modus: Icon-/Theme-Dumps (.icons, .themes, ...) werden UEBERSPRUNGEN ---"
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
SKIPPED_HEAVY=0
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
# Zu durchsuchende Wurzeln: immer etc/skel, etc/xdg, usr/share und die
# SYSTEM_CONFIG_ROOTS (etc/ufw, etc/default, ...) - im vollen Modus
# zusaetzlich die tatsaechlich existierenden Grub/Plymouth/Boot-Pfade.
# ---------------------------------------------------------------------
SCAN_ROOTS=(
    "$AIROOTFS_DIR/etc/skel"
    "$AIROOTFS_DIR/etc/xdg"
    "$AIROOTFS_DIR/usr/share"
)
for prefix in "${SYSTEM_CONFIG_ROOTS[@]}"; do
    SRC_PATH="$AIROOTFS_DIR/$prefix"
    [ -e "$SRC_PATH" ] && SCAN_ROOTS+=("$SRC_PATH")
done
if [[ $WITH_FULL -eq 1 ]]; then
    for prefix in "${SENSITIVE_PREFIXES[@]}"; do
        SRC_PATH="$AIROOTFS_DIR/$prefix"
        [ -e "$SRC_PATH" ] && SCAN_ROOTS+=("$SRC_PATH")
    done
fi

if [[ $FAST -eq 1 ]]; then
    for prefix in "${HEAVY_PREFIXES[@]}"; do
        [ -e "$AIROOTFS_DIR/$prefix" ] || continue
        echo "UEBERSPRUNGEN (Icon/Theme-Dump, --fast gesetzt): $prefix/"
        SKIPPED_HEAVY=$((SKIPPED_HEAVY + 1))
    done
fi

# ---------------------------------------------------------------------
# Verarbeitet eine einzelne Quelldatei (Blacklist-Check, Sensitive-
# Check, Dry-Run-Ausgabe, Backup, Kopieren, Zaehlung). Genutzt sowohl
# fuer die find-Ergebnisse aus SCAN_ROOTS als auch fuer die einzelnen
# SYSTEM_CONFIG_FILES (z.B. etc/resolv.conf) - beide sollen exakt
# dieselbe Behandlung bekommen, daher hier zusammengefasst statt
# doppelt geschrieben.
# ---------------------------------------------------------------------
process_file() {
    local FILE="$1"
    local REL_PATH="${FILE#$AIROOTFS_DIR/}"

    if is_blacklisted "$REL_PATH"; then
        echo "GESCHUETZT (Blacklist): $REL_PATH"
        SKIPPED_BLACKLIST=$((SKIPPED_BLACKLIST + 1))
        return
    fi

    local IS_SENS=0
    if matches_prefix_list "$REL_PATH" "${SENSITIVE_PREFIXES[@]}"; then
        IS_SENS=1
        if [[ $WITH_FULL -eq 0 ]]; then
            echo "UEBERSPRUNGEN (Grub/Plymouth/Boot, --full nicht gesetzt): $REL_PATH"
            SKIPPED_SENSITIVE=$((SKIPPED_SENSITIVE + 1))
            return
        fi
    fi

    resolve_target "$REL_PATH"

    if [[ $DRY_RUN -eq 1 ]]; then
        echo "WUERDE KOPIEREN: $FILE -> $TARGET_PATH"
        return
    fi

    # Existierendes Ziel vor dem Ueberschreiben sichern
    if [ -e "$TARGET_PATH" ]; then
        BACKUP_TARGET="$BACKUP_DIR/$REL_PATH"
        $USE_SUDO mkdir -p "$(dirname "$BACKUP_TARGET")"
        $USE_SUDO cp -a "$TARGET_PATH" "$BACKUP_TARGET"
        BACKED_UP=$((BACKED_UP + 1))
    fi

    local TARGET_DIR="$(dirname "$TARGET_PATH")"
    if [ ! -d "$TARGET_DIR" ]; then
        $USE_SUDO mkdir -p "$TARGET_DIR"
    fi

    $USE_SUDO cp -P "$FILE" "$TARGET_PATH"

    echo "Kopiert: $FILE -> $TARGET_PATH"
    COPIED=$((COPIED + 1))
    if [[ $IS_SENS -eq 1 ]]; then
        SENSITIVE_COPIED=$((SENSITIVE_COPIED + 1))
    fi
}

while read -r FILE; do
    process_file "$FILE"
done < <(build_find_cmd && "${FIND_CMD[@]}")

# ---------------------------------------------------------------------
# Einzelne Top-Level-Dateien aus SYSTEM_CONFIG_FILES (z.B.
# etc/resolv.conf) - werden von find/SCAN_ROOTS nicht erfasst (siehe
# Kommentar oben bei SYSTEM_CONFIG_FILES), daher separat behandelt.
# Nur wenn die Datei/der Symlink im airootfs tatsaechlich existiert.
# ---------------------------------------------------------------------
for rel_file in "${SYSTEM_CONFIG_FILES[@]}"; do
    SRC_FILE="$AIROOTFS_DIR/$rel_file"
    if [ -e "$SRC_FILE" ] || [ -L "$SRC_FILE" ]; then
        process_file "$SRC_FILE"
    fi
done

echo ""
echo "Systemupdate abgeschlossen!"
echo "  Kopiert:                        $COPIED"
echo "  Geschuetzt (Blacklist):         $SKIPPED_BLACKLIST"
echo "  Uebersprungen (Grub/Plymouth):  $SKIPPED_SENSITIVE"
echo "  Uebersprungen (Icon/Theme-Ordner): $SKIPPED_HEAVY"
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
echo "Mit '--fast' werden die grossen Icon-/Theme-Dumps uebersprungen (kombinierbar mit --full)."