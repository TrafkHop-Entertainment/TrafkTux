#!/usr/bin/env bash
# SystemUpdate.sh   (Ziel: /usr/local/lib/trafktux/SystemUpdate.sh, root-eigen, 0755)
#
# Holt sich das TrafkTux-Repo selbst von GitHub (flacher Teil-Klon, nur die
# benoetigten Ordner aus archiso/airootfs), kopiert die Dateien ins echte
# System und loescht den Klon am Ende wieder. Das ist die Variante von
# SyncEverything.sh fuer Endnutzer: gleiche Regeln (Blacklist, Backups,
# --fast, --full), aber ohne lokalen Archiso-Ordner.
#
# Modi (kombinierbar):
#   (kein Flag)  etc/skel, etc/xdg, usr/share, usr/local, System-Configs
#   --full       zusaetzlich Grub/Plymouth/Boot; danach grub-mkconfig + mkinitcpio
#   --fast       ueberspringt die grossen Icon-/Theme-Dumps (laedt sie auch nicht)
#   --dry-run    zeigt nur, was kopiert wuerde (braucht kein root)
#   --yes        keine Rueckfrage (fuer den Aufruf durch OptionalSync.sh)
#
# Aufruf als normaler Benutzer, NIE mit sudo:
#   bash /usr/local/lib/trafktux/SystemUpdate.sh [--fast] [--full] [--dry-run]
#
# Sicherheitsmodell: Das Skript fragt EINMAL per Polkit (pkexec) nach dem
# Passwort und laeuft danach in einem einzigen root-Prozess. Dateien nach
# $HOME (etc/skel) schreibt dieser Prozess mit abgegebenen Rechten
# (runuser), damit root nie in vom Benutzer kontrollierten Ordnern
# schreibt. Der Klon gehoert root, der Benutzer kann ihn nicht veraendern.
# Repo-URL und Branch sind fest hier drin (kein Parameter).
#
# Log: ~/.local/state/TrafkTux/SystemUpdate.log
# Backups: Benutzerdateien unter ~/.trafktux-sync-backups/<Zeit>,
#          Systemdateien unter /var/backups/TrafkTuxUpdate/<Zeit>

REPO_URL="https://github.com/TrafkHop-Entertainment/TrafkTux.git"
REPO_BRANCH="main"
AIROOTFS_SUBDIR="archiso/airootfs"

SELF="$(readlink -f "${BASH_SOURCE[0]}")"

DRY_RUN=0
WITH_FULL=0
FAST=0
YES=0
AS_ROOT=0
TEST_UID=""

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --full) WITH_FULL=1 ;;
        --fast) FAST=1 ;;
        --yes) YES=1 ;;
        --as-root) AS_ROOT=1 ;;     # intern: wird von pkexec so aufgerufen
        --uid=*) TEST_UID="${arg#--uid=}" ;;   # nur fuer Tests ohne pkexec
        -h|--help) sed -n '2,31p' "$SELF"; exit 0 ;;
        *)
            echo "Unbekannte Option: $arg"
            echo "Erlaubt: --dry-run, --full, --fast, --yes"
            exit 1
            ;;
    esac
done

die() { echo "FEHLER: $*" >&2; exit 1; }

# Testhaken: nur wirksam, wenn das Skript DIREKT als root laeuft (nicht ueber
# pkexec, das loescht die Umgebung). Leitet Systemziele in einen Testordner um.
SYSROOT="${TRAFKTUX_UPDATE_SYSROOT:-}"

# ---------------------------------------------------------------------
# Regeln (identisch zu SyncEverything.sh)
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
    "usr/local/bin/create-liveuser.sh"
    "usr/local/bin/install-aur-packages.sh"
    "usr/local/bin/install-hyprpm-plugins.sh"
    "usr/local/bin/Installation_guide"
)

# Nur mit --full
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

# Mit --fast uebersprungen (und gar nicht erst heruntergeladen)
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

# Immer gescannt (zusaetzlich zu etc/skel, etc/xdg, usr/share, usr/local)
SYSTEM_CONFIG_ROOTS=(
    "etc/ufw"
    "etc/default"
    "etc/systemd"
    "etc/NetworkManager"
    "etc/sysctl.d"
    "etc/security"
    "etc/pam.d"
    "etc/avahi"
)

# Einzelne Dateien direkt in etc/
SYSTEM_CONFIG_FILES=(
    "etc/resolv.conf"
)

is_blacklisted() {
    local path="$1" pattern
    for pattern in "${BLACKLIST[@]}"; do
        # shellcheck disable=SC2053
        [[ "$path" == $pattern ]] && return 0
    done
    return 1
}

matches_prefix_list() {
    local path="$1" prefix
    shift
    for prefix in "$@"; do
        [[ "$path" == "$prefix" || "$path" == "$prefix"/* ]] && return 0
    done
    return 1
}

# ---------------------------------------------------------------------
# Ziel bestimmen: etc/skel -> $USER_HOME (Rechte des Benutzers),
# alles andere -> echtes System (root).
# ---------------------------------------------------------------------
resolve_target() {
    local rel_path="$1"
    if [[ "$rel_path" == "etc/skel/"* ]]; then
        TARGET_PATH="$USER_HOME/${rel_path#etc/skel/}"
        BACKUP_BASE="$BACKUP_USER"
        if (( AS_ROOT )); then
            AS=(runuser -u "$USER_NAME" --)
        else
            AS=()
        fi
    else
        TARGET_PATH="${SYSROOT}/$rel_path"
        BACKUP_BASE="$BACKUP_SYS"
        AS=()
    fi
}

cleanup() {
    [[ -n "${CLONE_DIR:-}" && -d "${CLONE_DIR}" ]] && rm -rf "${CLONE_DIR}"
}

# ---------------------------------------------------------------------
# Flacher Teil-Klon: nur die Ordner, die der Sync wirklich braucht.
# Im --fast Modus werden die Icon-/Theme-Dumps gar nicht erst geladen.
# Faellt auf einen kompletten flachen Klon zurueck, falls das scheitert.
# ---------------------------------------------------------------------
clone_repo() {
    CLONE_DIR="$(mktemp -d /var/tmp/TrafkTuxUpdate.XXXXXX)" || die "Kein Temp-Ordner."
    chmod 755 "$CLONE_DIR"
    trap cleanup EXIT
    trap 'exit 130' INT TERM

    local base="/${AIROOTFS_SUBDIR}" p
    local patterns=()
    for p in etc/skel etc/xdg usr/share usr/local \
             "${SYSTEM_CONFIG_ROOTS[@]}" "${SYSTEM_CONFIG_FILES[@]}"; do
        patterns+=("$base/$p")
    done
    if (( WITH_FULL )); then
        for p in "${SENSITIVE_PREFIXES[@]}"; do patterns+=("$base/$p"); done
    fi
    if (( FAST )); then
        for p in "${HEAVY_PREFIXES[@]}"; do patterns+=("!$base/$p"); done
    fi

    echo "==> Lade Repo (Teil-Klon, Branch ${REPO_BRANCH})..."
    local repo="$CLONE_DIR/repo"
    if git clone --quiet --depth 1 --branch "$REPO_BRANCH" --filter=blob:none \
            --no-checkout "$REPO_URL" "$repo" \
        && git -C "$repo" sparse-checkout set --no-cone "${patterns[@]}" \
        && git -C "$repo" checkout --quiet; then
        :
    else
        echo "Teil-Klon fehlgeschlagen, versuche kompletten flachen Klon (groesser)..."
        rm -rf "$repo"
        git clone --quiet --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$repo" \
            || die "git clone fehlgeschlagen (Internet?)."
    fi

    AIROOTFS_DIR="$repo/$AIROOTFS_SUBDIR"
    [[ -d "$AIROOTFS_DIR" ]] || die "$AIROOTFS_SUBDIR im Repo nicht gefunden."
}

# ---------------------------------------------------------------------
# find-Kommando: im --fast Modus werden die HEAVY_PREFIXES per -prune
# von der Traversierung ausgeschlossen.
# ---------------------------------------------------------------------
build_find_cmd() {
    FIND_CMD=(find "${SCAN_ROOTS[@]}")

    local prune_paths=() prefix
    if (( FAST )); then
        for prefix in "${HEAVY_PREFIXES[@]}"; do
            prune_paths+=("$AIROOTFS_DIR/$prefix")
        done
    fi

    if (( ${#prune_paths[@]} > 0 )); then
        FIND_CMD+=("(")
        local first=1 p
        for p in "${prune_paths[@]}"; do
            (( first == 0 )) && FIND_CMD+=("-o")
            FIND_CMD+=("-path" "$p" "-o" "-path" "$p/*")
            first=0
        done
        FIND_CMD+=(")" "-prune" "-o" "(" "-type" "f" "-o" "-type" "l" ")" "-print")
    else
        FIND_CMD+=("(" "-type" "f" "-o" "-type" "l" ")")
    fi
}

process_file() {
    local FILE="$1"
    local REL_PATH="${FILE#"$AIROOTFS_DIR"/}"

    if is_blacklisted "$REL_PATH"; then
        echo "GESCHUETZT (Blacklist): $REL_PATH"
        SKIPPED_BLACKLIST=$((SKIPPED_BLACKLIST + 1))
        return
    fi

    local IS_SENS=0
    if matches_prefix_list "$REL_PATH" "${SENSITIVE_PREFIXES[@]}"; then
        IS_SENS=1
        if (( WITH_FULL == 0 )); then
            echo "UEBERSPRUNGEN (Grub/Plymouth/Boot, --full nicht gesetzt): $REL_PATH"
            SKIPPED_SENSITIVE=$((SKIPPED_SENSITIVE + 1))
            return
        fi
    fi

    resolve_target "$REL_PATH"

    if (( DRY_RUN )); then
        echo "WUERDE KOPIEREN: $REL_PATH -> $TARGET_PATH"
        return
    fi

    # Existierendes Ziel vor dem Ueberschreiben sichern
    if [ -e "$TARGET_PATH" ] || [ -L "$TARGET_PATH" ]; then
        local BACKUP_TARGET="$BACKUP_BASE/$REL_PATH"
        "${AS[@]}" mkdir -p "$(dirname "$BACKUP_TARGET")"
        "${AS[@]}" cp -a "$TARGET_PATH" "$BACKUP_TARGET"
        BACKED_UP=$((BACKED_UP + 1))
    fi

    local TARGET_DIR
    TARGET_DIR="$(dirname "$TARGET_PATH")"
    [ -d "$TARGET_DIR" ] || "${AS[@]}" mkdir -p "$TARGET_DIR"

    # Atomarer Replace (siehe SyncEverything.sh): laufende Prozesse behalten
    # die alte Inode, neue Aufrufe sehen sofort die neue Datei. Wichtig, weil
    # dieses Skript und OptionalSync.sh sich dabei auch selbst ersetzen.
    "${AS[@]}" cp -P "$FILE" "${TARGET_PATH}.new.$$"
    "${AS[@]}" mv -f "${TARGET_PATH}.new.$$" "$TARGET_PATH"

    echo "Kopiert: $REL_PATH -> $TARGET_PATH"
    COPIED=$((COPIED + 1))
    (( IS_SENS )) && SENSITIVE_COPIED=$((SENSITIVE_COPIED + 1))
}

# ---------------------------------------------------------------------
# Eigentlicher Sync (laeuft im root-Prozess, bzw. bei --dry-run als Benutzer)
# ---------------------------------------------------------------------
run_update() {
    local TS
    TS="$(date +%Y%m%d-%H%M%S)"
    BACKUP_USER="$USER_HOME/.trafktux-sync-backups/$TS"
    BACKUP_SYS="${SYSROOT}/var/backups/TrafkTuxUpdate/$TS"

    (( DRY_RUN )) && echo "--- DRY RUN: es wird nichts wirklich kopiert, nur angezeigt ---"
    if (( WITH_FULL )); then
        echo "--- VOLLER Modus: Grub/Plymouth/Boot-relevantes wird MIT synct ---"
    else
        echo "--- Normaler Modus: Grub/Plymouth/Boot-relevantes wird NICHT angefasst ---"
    fi
    (( FAST )) && echo "--- SCHNELL-Modus: Icon-/Theme-Dumps werden UEBERSPRUNGEN ---"

    clone_repo

    COPIED=0
    SKIPPED_BLACKLIST=0
    SKIPPED_SENSITIVE=0
    SKIPPED_HEAVY=0
    BACKED_UP=0
    SENSITIVE_COPIED=0

    local prefix SRC_DIR DIR REL_DIR
    # Voller Modus: zuerst die Ordnerstruktur unter den Boot-Pfaden anlegen
    if (( DRY_RUN == 0 && WITH_FULL == 1 )); then
        for prefix in "${SENSITIVE_PREFIXES[@]}"; do
            SRC_DIR="$AIROOTFS_DIR/$prefix"
            [ -d "$SRC_DIR" ] || continue
            while IFS= read -r DIR; do
                REL_DIR="${DIR#"$AIROOTFS_DIR"/}"
                resolve_target "$REL_DIR"
                [ -d "$TARGET_PATH" ] || "${AS[@]}" mkdir -p "$TARGET_PATH"
            done < <(find "$SRC_DIR" -type d)
        done
    fi

    SCAN_ROOTS=(
        "$AIROOTFS_DIR/etc/skel"
        "$AIROOTFS_DIR/etc/xdg"
        "$AIROOTFS_DIR/usr/share"
        "$AIROOTFS_DIR/usr/local"
    )
    for prefix in "${SYSTEM_CONFIG_ROOTS[@]}"; do
        [ -e "$AIROOTFS_DIR/$prefix" ] && SCAN_ROOTS+=("$AIROOTFS_DIR/$prefix")
    done
    if (( WITH_FULL )); then
        for prefix in "${SENSITIVE_PREFIXES[@]}"; do
            [ -e "$AIROOTFS_DIR/$prefix" ] && SCAN_ROOTS+=("$AIROOTFS_DIR/$prefix")
        done
    fi

    if (( FAST )); then
        for prefix in "${HEAVY_PREFIXES[@]}"; do
            echo "UEBERSPRUNGEN (Icon/Theme-Dump, --fast gesetzt): $prefix/"
            SKIPPED_HEAVY=$((SKIPPED_HEAVY + 1))
        done
    fi

    local FILE
    build_find_cmd
    while IFS= read -r FILE; do
        process_file "$FILE"
    done < <("${FIND_CMD[@]}")

    local rel_file SRC_FILE
    for rel_file in "${SYSTEM_CONFIG_FILES[@]}"; do
        SRC_FILE="$AIROOTFS_DIR/$rel_file"
        if [ -e "$SRC_FILE" ] || [ -L "$SRC_FILE" ]; then
            process_file "$SRC_FILE"
        fi
    done

    echo ""
    echo "Systemupdate abgeschlossen!"
    echo "  Kopiert:                           $COPIED"
    echo "  Geschuetzt (Blacklist):            $SKIPPED_BLACKLIST"
    echo "  Uebersprungen (Grub/Plymouth):     $SKIPPED_SENSITIVE"
    echo "  Uebersprungen (Icon/Theme-Ordner): $SKIPPED_HEAVY"
    echo "  Gesichert vor Ueberschreiben:      $BACKED_UP"
    if (( DRY_RUN == 0 && BACKED_UP > 0 )); then
        echo "  Backups: $BACKUP_USER (Benutzerdateien)"
        echo "           $BACKUP_SYS (Systemdateien)"
    fi

    if (( DRY_RUN == 0 && WITH_FULL == 1 && SENSITIVE_COPIED > 0 )) && [[ -z "$SYSROOT" ]]; then
        echo ""
        echo "Grub/Plymouth/Boot-Sachen wurden geaendert - baue Grub-Config und Initramfs neu..."
        grub-mkconfig -o /boot/grub/grub.cfg
        mkinitcpio -P
        echo "Starte trafktux-grub-theme-sync.service, um Bucket/GRUB_GFXMODE zu pruefen..."
        systemctl restart trafktux-grub-theme-sync.service
    fi
}

# ---------------------------------------------------------------------
# root-Prozess (wird nur von pkexec bzw. direkt als root im Test gestartet)
# ---------------------------------------------------------------------
root_main() {
    (( EUID == 0 )) || die "--as-root nur als root."

    # Das Skript selbst muss root gehoeren und darf fuer andere nicht
    # schreibbar sein, sonst waere pkexec hier ein Rechte-Schlupfloch.
    local owner perms
    owner="$(stat -c %u "$SELF")"
    perms="$(stat -c %a "$SELF")"
    [[ "$owner" == "0" ]] || die "$SELF gehoert nicht root."
    (( (8#$perms & 8#022) == 0 )) || die "$SELF ist fuer Gruppe/andere schreibbar ($perms)."

    local uid
    if [[ -n "${PKEXEC_UID:-}" ]]; then
        uid="$PKEXEC_UID"
    else
        uid="$TEST_UID"      # nur ohne pkexec (Test)
    fi
    [[ "$uid" =~ ^[0-9]+$ ]] || die "Benutzer nicht ermittelbar (nur per pkexec starten)."
    (( uid > 0 )) || die "root als Ziel-Benutzer nicht erlaubt."

    USER_NAME="$(getent passwd "$uid" | cut -d: -f1)"
    USER_HOME="${TRAFKTUX_UPDATE_TESTHOME:-$(getent passwd "$uid" | cut -d: -f6)}"
    [[ -n "$USER_NAME" && -d "$USER_HOME" ]] || die "Benutzer/Home fuer UID $uid nicht gefunden."
    [[ -n "${PKEXEC_UID:-}" ]] && USER_HOME="$(getent passwd "$uid" | cut -d: -f6)"

    echo "Systemupdate fuer Benutzer: $USER_NAME ($USER_HOME)"
    run_update
}

# ---------------------------------------------------------------------
# Aufruf als normaler Benutzer
# ---------------------------------------------------------------------
user_main() {
    (( EUID != 0 )) || die "Nicht als root/sudo starten. Das Skript fragt selbst per Polkit nach dem Passwort."
    command -v git >/dev/null 2>&1 || die "git fehlt."
    command -v pkexec >/dev/null 2>&1 || die "pkexec (polkit) fehlt."

    local owner perms
    owner="$(stat -c %u "$SELF")"
    perms="$(stat -c %a "$SELF")"
    [[ "$owner" == "0" ]] || die "$SELF gehoert nicht root (Besitzer-UID $owner). Aus Sicherheitsgruenden verweigere ich pkexec."
    (( (8#$perms & 8#022) == 0 )) || die "$SELF ist fuer Gruppe/andere schreibbar ($perms)."

    local state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/TrafkTux"
    local log_file="$state_dir/SystemUpdate.log"
    mkdir -p "$state_dir"

    exec 9>"${XDG_RUNTIME_DIR:-/tmp}/TrafkTuxSystemUpdate.lock"
    flock -n 9 || die "Es laeuft bereits ein Systemupdate."

    echo "WARNUNG: Dieses Skript holt das TrafkTux-Repo von GitHub und KOPIERT Dateien"
    echo "in dein System (Konfigurationen, Skripte, Themes). Backups werden angelegt."
    if (( YES == 0 )) && [[ -t 0 ]]; then
        read -p "Willst du fortfahren? (y/n) " -n 1 -r
        echo
        [[ $REPLY =~ ^[Yy]$ ]] || exit 1
    fi

    local flags=()
    (( WITH_FULL )) && flags+=(--full)
    (( FAST )) && flags+=(--fast)

    pkexec /usr/bin/bash "$SELF" --as-root "${flags[@]}" 2>&1 | tee -a "$log_file"
    local rc="${PIPESTATUS[0]}"
    if (( rc != 0 )); then
        echo "Systemupdate fehlgeschlagen (Code $rc). Log: $log_file" >&2
        exit "$rc"
    fi

    # Nach dem Kopieren: Benutzer-Dienste neu laden/starten, damit neue Binaries aktiv werden
    systemctl --user daemon-reload
    systemctl --user restart \
        ScreenRotationDaemon.service \
        WidgetsDaemon.service \
        WaybarAutohideDaemon.service \
        FocusFixDaemon.service
    echo "Fertig."
}

if (( AS_ROOT )); then
    root_main
elif (( DRY_RUN )); then
    # Trockenlauf: kein root noetig, alles nur als Benutzer lesen/anzeigen
    USER_NAME="$(id -un)"
    USER_HOME="$HOME"
    command -v git >/dev/null 2>&1 || die "git fehlt."
    run_update
else
    user_main
fi
