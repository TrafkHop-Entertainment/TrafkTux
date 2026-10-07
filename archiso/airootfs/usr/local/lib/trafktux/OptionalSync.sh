#!/usr/bin/env bash
# OptionalSync.sh   (Ziel: /usr/local/lib/trafktux/OptionalSync.sh, Modus 0755)
#
# Arbeitet die Listen der installierten TrafkTuxOptional-Metapakete ab
# (/usr/share/TrafkTux/Optional/*.list) und installiert, was pacman selbst
# nicht kann: AUR-Pakete (pamac build), Flatpaks, Benutzergruppen und
# Direkt-Downloads. Alles laeuft als normaler Benutzer; nur wenn etwas root
# braucht, fragt Pamac/pkexec per Polkit (hyprpolkitagent) nach dem Passwort.
#
# WICHTIG: Das Skript muss INNERHALB der Hyprland-Session laufen (z.B. per
# Autostart), nicht als systemd-User-Dienst. Polkit ordnet Prozesse sonst
# keiner Session zu und findet keinen Authentifizierungs-Agenten.
#
# Aufruf:
#   OptionalSync.sh --watch   Dauerlaeufer (Autostart): beobachtet den Listen-
#                             Ordner und startet bei Aenderungen die Installation
#   OptionalSync.sh --now     einmal alles Fehlende nachholen (auch zum Wiederholen)
#
# Log: ~/.local/state/TrafkTux/OptionalSync.log

set -uo pipefail

LIST_DIR="/usr/share/TrafkTux/Optional"
STATE_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/TrafkTux"
LOG_FILE="${STATE_DIR}/OptionalSync.log"
SIG_FILE="${STATE_DIR}/OptionalSync.signature"
DONE_FILE="${STATE_DIR}/OptionalSync.done"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}"
POLL_SECONDS=5
LOCK_WAIT_MAX=900
ME="$(id -un)"
SYSTEM_UPDATE="/usr/local/lib/trafktux/SystemUpdate.sh"
VERBOSE=0

mkdir -p "${STATE_DIR}"
touch "${DONE_FILE}"

FAILED=()
RELOGIN=0
TODO_REPO=(); TODO_AUR=(); TODO_FLATPAK=(); TODO_GROUP=(); TODO_URL=(); TODO_UPDATE=()

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "${LOG_FILE}"; }

# Benachrichtigungen bewusst kurz und schlicht (nur ASCII, keine Zahlen/Pfade).
# Abschalten: TRAFKTUX_OPTIONAL_NOTIFY=0 (Details stehen immer im Log).
NOTIFY_ENABLED="${TRAFKTUX_OPTIONAL_NOTIFY:-1}"

notify() {
    [[ "${NOTIFY_ENABLED}" == "1" ]] || return 0
    command -v notify-send >/dev/null 2>&1 || { log "notify-send fehlt"; return 0; }
    notify-send "$1" "${2:-}" 2>>"${LOG_FILE}" || log "Benachrichtigung fehlgeschlagen: $1"
    return 0
}

# Befehl ausfuehren, Ausgabe ins Log; stdin leer, damit Rueckfragen nicht haengen
run() {
    "$@" </dev/null 2>&1 | tee -a "${LOG_FILE}"
    return "${PIPESTATUS[0]}"
}

run_locked() {
    (
        flock -w 3600 8 || exit 1
        "$@"
    ) 8>"${RUNTIME_DIR}/TrafkTuxOptionalSync.lock"
}

signature() {
    find "${LIST_DIR}" -maxdepth 1 -name '*.list' -printf '%f %T@\n' 2>/dev/null \
        | sort | md5sum | cut -d' ' -f1
}

in_group() {
    getent group "$1" | cut -d: -f4 | tr ',' '\n' | grep -qx "${ME}"
}

dedupe() {
    local -n _arr="$1"
    local -A seen=()
    local out=() x
    for x in "${_arr[@]}"; do
        [[ -n "${seen[${x}]:-}" ]] && continue
        seen["${x}"]=1
        out+=("${x}")
    done
    _arr=("${out[@]}")
}

wait_for_pacman() {
    local waited=0
    while [[ -e /var/lib/pacman/db.lck ]]; do
        if ((waited >= LOCK_WAIT_MAX)); then
            log "Pacman-Lock bleibt bestehen, gebe auf."
            return 1
        fi
        sleep 3
        ((waited += 3))
    done
    return 0
}

# Liest alle Listen und merkt sich nur, was noch fehlt
collect_todo() {
    TODO_REPO=(); TODO_AUR=(); TODO_FLATPAK=(); TODO_GROUP=(); TODO_URL=(); TODO_UPDATE=()
    local f kind value mtime
    for f in "${LIST_DIR}"/*.list; do
        [[ -f "${f}" ]] || continue
        # shellcheck disable=SC2094
        while read -r kind value _; do
            [[ -z "${kind}" || "${kind}" == \#* ]] && continue
            case "${kind}" in
                aur)
                    pacman -Qq "${value}" >/dev/null 2>&1 && continue
                    # Falls ein frueheres AUR-Paket inzwischen in den Arch-Repos ist
                    if pacman -Si "${value}" >/dev/null 2>&1; then
                        TODO_REPO+=("${value}")
                    else
                        TODO_AUR+=("${value}")
                    fi
                    ;;
                flatpak)
                    flatpak info "${value}" >/dev/null 2>&1 || TODO_FLATPAK+=("${value}")
                    ;;
                group)
                    in_group "${value}" || TODO_GROUP+=("${value}")
                    ;;
                pkgurl)
                    grep -qxF "pkgurl ${value}" "${DONE_FILE}" || TODO_URL+=("${value}")
                    ;;
                update)
                    # Laeuft erneut, sobald die .list-Datei neu geschrieben wurde
                    # (Paket neu installiert/aktualisiert), erkennbar an der mtime.
                    mtime="$(stat -c %Y "${f}" 2>/dev/null || echo 0)"
                    grep -qxF "update ${value} ${f##*/} ${mtime}" "${DONE_FILE}" \
                        || TODO_UPDATE+=("${value}|${f##*/}|${mtime}")
                    ;;
            esac
        done < "${f}"
    done
    dedupe TODO_REPO; dedupe TODO_AUR; dedupe TODO_FLATPAK; dedupe TODO_GROUP; dedupe TODO_URL; dedupe TODO_UPDATE
}

# Alle Pakete in EINEM pamac-Aufruf (wenige Passwortabfragen). Schlaegt das fehl,
# werden die uebrigen einzeln versucht.
pamac_batch() {
    local sub="$1"; shift
    (($#)) || return 0
    wait_for_pacman || { FAILED+=("$@"); return 1; }
    log "pamac ${sub}: $*"
    run pamac "${sub}" --no-confirm "$@" && return 0

    log "Sammel-Aufruf fehlgeschlagen, versuche die Pakete einzeln."
    local p
    for p in "$@"; do
        pacman -Qq "${p}" >/dev/null 2>&1 && continue
        wait_for_pacman || { FAILED+=("${p}"); continue; }
        run pamac "${sub}" --no-confirm "${p}" || FAILED+=("${p}")
    done
}

sync_flatpaks() {
    ((${#TODO_FLATPAK[@]})) || return 0
    if ! flatpak remotes --system 2>/dev/null | grep -qw flathub; then
        log "Flathub-Remote hinzufuegen"
        run flatpak remote-add --system --if-not-exists flathub \
            https://dl.flathub.org/repo/flathub.flatpakrepo \
            || { FAILED+=("flathub-remote"); return 1; }
    fi
    log "flatpak install: ${TODO_FLATPAK[*]}"
    run flatpak install --system --noninteractive -y flathub "${TODO_FLATPAK[@]}" && return 0

    local id
    for id in "${TODO_FLATPAK[@]}"; do
        flatpak info "${id}" >/dev/null 2>&1 && continue
        run flatpak install --system --noninteractive -y flathub "${id}" || FAILED+=("${id}")
    done
}

sync_groups() {
    local g
    for g in "${TODO_GROUP[@]}"; do
        log "Benutzer ${ME} zur Gruppe ${g} hinzufuegen"
        if run pkexec usermod -aG "${g}" "${ME}"; then
            RELOGIN=1
        else
            FAILED+=("Gruppe:${g}")
        fi
    done
}

sync_pkgurls() {
    local url tmp file
    for url in "${TODO_URL[@]}"; do
        tmp="$(mktemp -d)"
        file="${tmp}/${url##*/}"
        log "Lade ${url}"
        if run curl -fsSL --retry 3 -o "${file}" "${url}" \
            && wait_for_pacman \
            && run pkexec pacman -U --noconfirm "${file}"; then
            echo "pkgurl ${url}" >> "${DONE_FILE}"
        else
            FAILED+=("${url##*/}")
        fi
        rm -rf "${tmp}"
    done
}

# Systemupdate-Metapakete (TrafkTuxUpdate-*): holt das Repo und kopiert die
# Dateien ins System. Fragt selbst per Polkit nach dem Passwort.
sync_updates() {
    local entry mode name mtime
    local flags=()
    for entry in "${TODO_UPDATE[@]}"; do
        IFS='|' read -r mode name mtime <<<"${entry}"
        case "${mode}" in
            fast)     flags=(--fast) ;;
            fastfull) flags=(--fast --full) ;;
            full)     flags=(--full) ;;
            *)
                log "Unbekannter Update-Modus: ${mode}"
                FAILED+=("update:${mode}")
                continue
                ;;
        esac
        log "Systemupdate (${mode})"
        if run bash "${SYSTEM_UPDATE}" "${flags[@]}" --yes; then
            echo "update ${mode} ${name} ${mtime}" >> "${DONE_FILE}"
        else
            FAILED+=("update:${mode}")
        fi
    done
}

sync_once() {
    FAILED=(); RELOGIN=0
    collect_todo

    local total=$((${#TODO_REPO[@]} + ${#TODO_AUR[@]} + ${#TODO_FLATPAK[@]} \
        + ${#TODO_GROUP[@]} + ${#TODO_URL[@]} + ${#TODO_UPDATE[@]}))
    if ((total == 0)); then
        ((VERBOSE)) && log "Nichts zu tun."
        return 0
    fi

    if ((${#TODO_REPO[@]} + ${#TODO_AUR[@]} > 0)) && ! command -v pamac >/dev/null 2>&1; then
        log "pamac nicht gefunden."
        notify "Optionale Pakete" "pamac fehlt"
        return 1
    fi
    if ((${#TODO_REPO[@]} + ${#TODO_AUR[@]} + ${#TODO_FLATPAK[@]} + ${#TODO_URL[@]} + ${#TODO_UPDATE[@]} > 0)); then
        if command -v nm-online >/dev/null 2>&1 && ! nm-online -q -t 30; then
            log "Kein Netz."
            notify "Optionale Pakete" "Kein Internet"
            return 1
        fi
    fi

    log "Zu erledigen: repo=${#TODO_REPO[@]} aur=${#TODO_AUR[@]} flatpak=${#TODO_FLATPAK[@]} gruppen=${#TODO_GROUP[@]} urls=${#TODO_URL[@]} updates=${#TODO_UPDATE[@]}"
    notify "Optionale Pakete" "Installation laeuft"

    pamac_batch install "${TODO_REPO[@]}"
    pamac_batch build "${TODO_AUR[@]}"
    sync_flatpaks
    sync_groups
    sync_pkgurls
    sync_updates

    if ((${#FAILED[@]})); then
        log "Fehlgeschlagen: ${FAILED[*]}"
        notify "Optionale Pakete" "Teilweise fehlgeschlagen, siehe Log"
        return 1
    fi

    local msg="Alles installiert."
    ((RELOGIN)) && msg="${msg} Bitte neu anmelden, damit die neuen Gruppen aktiv werden."
    log "${msg}"
    if ((RELOGIN)); then
        notify "Optionale Pakete" "Fertig, bitte neu anmelden"
    else
        notify "Optionale Pakete" "Fertig"
    fi
    return 0
}

watch_loop() {
    exec 9>"${RUNTIME_DIR}/TrafkTuxOptionalWatch.lock"
    flock -n 9 || exit 0

    local last current
    last="$(cat "${SIG_FILE}" 2>/dev/null || true)"
    while true; do
        current="$(signature)"
        if [[ "${current}" != "${last}" ]]; then
            sleep 5   # pacman fertig schreiben lassen
            current="$(signature)"
            run_locked sync_once && echo "${current}" > "${SIG_FILE}"
            last="${current}"
        fi
        sleep "${POLL_SECONDS}"
    done
}

case "${1:---now}" in
    --watch)
        watch_loop
        ;;
    --now)
        VERBOSE=1
        if run_locked sync_once; then
            signature > "${SIG_FILE}"
        else
            exit 1
        fi
        ;;
    -h|--help)
        sed -n '2,22p' "$0"
        ;;
    *)
        echo "Unbekannte Option: $1 (siehe --help)" >&2
        exit 2
        ;;
esac
