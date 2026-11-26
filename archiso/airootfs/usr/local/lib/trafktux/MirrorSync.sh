#!/usr/bin/env bash
# MirrorSync.sh   (Ziel: /usr/local/lib/trafktux/MirrorSync.sh, root-eigen, 0755)
#
# Sortiert die pacman-Mirrorlist (/etc/pacman.d/mirrorlist) nach Geschwindigkeit.
# Alle Repos (core, extra, multilib) lesen diese eine Datei.
#
# Ablauf: reflector laeuft als normaler Benutzer und schreibt in eine
# Temp-Datei. Erst danach fragt pkexec EINMAL nach dem Passwort; der root-Teil
# prueft die Datei, sichert die alte Mirrorlist und tauscht sie aus.
#
# Optionen von reflector: Wenn /etc/xdg/reflector/reflector.conf existiert, wird
# sie uebernommen (z.B. --country). Immer erzwungen: --sort rate und --save auf
# die Temp-Datei. Ohne Konfig: 40 zuletzt synchronisierte https-Mirror testen,
# die 15 schnellsten behalten.
#
# Aufruf als normaler Benutzer, NIE mit sudo:
#   bash /usr/local/lib/trafktux/MirrorSync.sh
#
# Backups: /var/backups/TrafkTuxUpdate/mirrorlist-<Zeit>   (die letzten 5)
# Log:     ~/.local/state/TrafkTux/MirrorSync.log

set -uo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
MIRRORLIST="/etc/pacman.d/mirrorlist"
REFLECTOR_CONF="/etc/xdg/reflector/reflector.conf"
BACKUP_DIR="/var/backups/TrafkTuxUpdate"
MIN_SERVERS=3

# ---------------------------------------------------------------------------
# root-Teil: wird von pkexec aufgerufen (--apply <Datei>)
# ---------------------------------------------------------------------------
apply_as_root() {
    local src="$1" work ts
    [[ "${EUID}" -eq 0 ]] || { echo "Nur als root." >&2; exit 1; }
    [[ -f "${src}" && ! -L "${src}" ]] || { echo "Ungueltige Datei." >&2; exit 1; }

    work="$(mktemp)"
    trap 'rm -f "${work}"' EXIT
    cp -- "${src}" "${work}"

    # Nur Kommentare, Leerzeilen und "Server = http(s)://..." zulassen
    if grep -qvE '^(#.*|[[:space:]]*|Server = https?://[A-Za-z0-9._:/$%~+-]+)$' "${work}"; then
        echo "Mirrorlist enthaelt unerwartete Zeilen, abgebrochen." >&2
        exit 1
    fi
    if (($(grep -c '^Server = ' "${work}") < MIN_SERVERS)); then
        echo "Weniger als ${MIN_SERVERS} Mirror, abgebrochen." >&2
        exit 1
    fi

    ts="$(date +%Y%m%d-%H%M%S)"
    mkdir -p "${BACKUP_DIR}"
    if [[ -f "${MIRRORLIST}" ]]; then
        cp -a -- "${MIRRORLIST}" "${BACKUP_DIR}/mirrorlist-${ts}"
    fi
    install -Dm644 "${work}" "${MIRRORLIST}"

    # Nur die letzten 5 Sicherungen behalten
    # shellcheck disable=SC2012
    ls -1t "${BACKUP_DIR}"/mirrorlist-* 2>/dev/null | tail -n +6 | xargs -r rm -f --
    echo "Mirrorlist ersetzt (Sicherung: ${BACKUP_DIR}/mirrorlist-${ts})"
}

if [[ "${1:-}" == "--apply" ]]; then
    apply_as_root "${2:-}"
    exit $?
fi

# ---------------------------------------------------------------------------
# Benutzer-Teil
# ---------------------------------------------------------------------------
STATE_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/TrafkTux"
LOG_FILE="${STATE_DIR}/MirrorSync.log"
mkdir -p "${STATE_DIR}"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "${LOG_FILE}"; }

NOTIFY_ENABLED="${TRAFKTUX_OPTIONAL_NOTIFY:-1}"
notify() {
    [[ "${NOTIFY_ENABLED}" == "1" ]] || return 0
    command -v notify-send >/dev/null 2>&1 || return 0
    notify-send "$1" "${2:-}" 2>>"${LOG_FILE}" || true
    return 0
}

if [[ "${EUID}" -eq 0 ]]; then
    echo "Bitte als normaler Benutzer starten, nicht mit sudo." >&2
    exit 1
fi

if ! command -v reflector >/dev/null 2>&1; then
    log "reflector fehlt, installiere es."
    pkexec pacman -S --needed --noconfirm reflector </dev/null 2>&1 | tee -a "${LOG_FILE}"
    command -v reflector >/dev/null 2>&1 || { log "reflector konnte nicht installiert werden."; exit 1; }
fi

TMP="$(mktemp)"
trap 'rm -f "${TMP}"' EXIT

args=()
if [[ -f "${REFLECTOR_CONF}" ]]; then
    args+=("@${REFLECTOR_CONF}")
else
    args+=(--protocol https --latest 40 --number 15)
fi
args+=(--sort rate --connection-timeout 5 --download-timeout 5 --save "${TMP}")

log "Teste Mirror (kann ein paar Minuten dauern)."
notify "Mirrorlist" "Test laeuft"
if ! reflector "${args[@]}" </dev/null 2>&1 | tee -a "${LOG_FILE}"; then
    log "reflector fehlgeschlagen, Mirrorlist bleibt unveraendert."
    notify "Mirrorlist" "Fehlgeschlagen, siehe Log"
    exit 1
fi
# zur Sicherheit zusaetzlich die Datei selbst pruefen
if (($(grep -c '^Server = ' "${TMP}" 2>/dev/null || echo 0) < MIN_SERVERS)); then
    log "reflector hat zu wenige Mirror geliefert, Mirrorlist bleibt unveraendert."
    notify "Mirrorlist" "Fehlgeschlagen, siehe Log"
    exit 1
fi

if pkexec /usr/bin/bash "${SELF}" --apply "${TMP}" 2>&1 | tee -a "${LOG_FILE}" \
    && grep -qxF "$(grep -m1 '^Server = ' "${TMP}")" "${MIRRORLIST}"; then
    log "Fertig. Schnellster Mirror: $(grep -m1 '^Server = ' "${MIRRORLIST}")"
    notify "Mirrorlist" "Fertig"
else
    log "Mirrorlist konnte nicht ersetzt werden."
    notify "Mirrorlist" "Fehlgeschlagen, siehe Log"
    exit 1
fi
