#!/usr/bin/env bash
# HyprpmSync.sh   (Ziel: /usr/local/lib/trafktux/HyprpmSync.sh, Modus 0755)
#
# Baut die Hyprland-Plugins aus /usr/share/TrafkTux/HyprpmPlugins.conf gegen die
# LAUFENDE Hyprland-Version neu auf. Was nicht baut oder sich nicht aktivieren
# laesst, wird entfernt (hyprpm remove, nicht nur deaktiviert). Was geht, bleibt.
#
# Ablauf:
#   1) hyprpm update            baut alle registrierten Repos neu
#   2) Repos, die dabei scheitern, werden entfernt
#   3) hyprpm add               fuer alle Repos der Liste (holt auch frueher
#                               entfernte Repos zurueck, sobald sie wieder bauen)
#   4) hyprpm enable            jedes Plugin; scheitert eines, fliegt das Repo raus
#   5) hyprpm reload            laedt die aktiven Plugins in die laufende Session
#
# WICHTIG: hyprpm baut immer gegen das LAUFENDE Hyprland. Nach einem Hyprland-
# Update muss man sich also erst neu anmelden, bevor dieses Skript sinnvoll ist.
# Genau das erledigt --auto: OptionalSync.sh --watch ruft es beim Login auf.
#
# Aufruf (innerhalb der Hyprland-Session, als normaler Benutzer):
#   HyprpmSync.sh --now    sofort alles neu aufbauen
#   HyprpmSync.sh --auto   nur wenn sich die laufende Hyprland-Version seit dem
#                          letzten Lauf geaendert hat, oder wenn entfernte Plugins
#                          mehr als 24 h her sind (dann Neuversuch)
#   HyprpmSync.sh --clear-error   blendet die rote Hyprland-Fehlerleiste aus
#
# Wrapper: /usr/local/bin/hyprpm leitet ein nacktes "hyprpm update" auf --now um.
#
# Fehlerleiste: Verweist die Hyprland-Config auf ein entferntes Plugin, zeigt
# Hyprland beim Start und nach jedem Config-Reload einen Fehler. Sobald ein Plugin
# entfernt wurde, ruft das Skript deshalb "hyprctl seterror disable" auf (zur Not "false"): am Ende
# jedes Laufs und bei jedem Login. Das blendet die Leiste GENERELL aus, also auch
# echte Config-Fehler. Nach einem manuellen Reload: --clear-error.
#
# Das Skript ruft immer das ECHTE hyprpm auf (/usr/bin/hyprpm), nie den Wrapper
# /usr/local/bin/hyprpm, der "hyprpm update" auf dieses Skript umleitet.
#
# Voraussetzung: sudo fuer die hyprpm-Header-Installation geht ohne Passwort
# (so wie bei der ISO).
#
# Log: ~/.local/state/TrafkTux/HyprpmSync.log

set -uo pipefail

CONF="${TRAFKTUX_HYPRPM_CONF:-/usr/share/TrafkTux/HyprpmPlugins.conf}"
STATE_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/TrafkTux"
LOG_FILE="${STATE_DIR}/HyprpmSync.log"
STAMP_FILE="${STATE_DIR}/HyprpmSync.hyprland"   # Hyprland-Version des letzten Laufs
REMOVED_FILE="${STATE_DIR}/HyprpmSync.removed"  # Repos, die zuletzt nicht gingen
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}"
RETRY_MINUTES=1440

mkdir -p "${STATE_DIR}"

# Echtes hyprpm (der Wrapper in /usr/local/bin wuerde "update" wieder hierher
# umleiten). RAW=1 ist zusaetzliche Sicherheit gegen eine Endlosschleife.
export TRAFKTUX_HYPRPM_RAW=1
HYPRPM_BIN="${TRAFKTUX_HYPRPM_REAL:-/usr/bin/hyprpm}"
[[ -x "${HYPRPM_BIN}" ]] || HYPRPM_BIN="$(command -v hyprpm || true)"

REPO_URLS=()
declare -A REPO_PLUGINS=()
declare -A REMOVED=()
KEPT=()
HP_RC=0
HP_OUT=""

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "${LOG_FILE}"; }

# Kurz und schlicht, nur ASCII. Abschalten: TRAFKTUX_OPTIONAL_NOTIFY=0
NOTIFY_ENABLED="${TRAFKTUX_OPTIONAL_NOTIFY:-1}"
notify() {
    [[ "${NOTIFY_ENABLED}" == "1" ]] || return 0
    command -v notify-send >/dev/null 2>&1 || return 0
    notify-send "$1" "${2:-}" 2>>"${LOG_FILE}" || true
    return 0
}

# hyprpm mit automatischem "ja" auf Rueckfragen. Ergebnis in HP_RC / HP_OUT,
# die (von Farbcodes befreite) Ausgabe landet auch im Log.
hp() {
    local out
    out="$(mktemp)"
    yes 2>/dev/null | "${HYPRPM_BIN}" "$@" >"${out}" 2>&1
    HP_RC="${PIPESTATUS[1]}"
    HP_OUT="$(sed -e 's/\x1b\[[0-9;?]*[a-zA-Z]//g' -e 's/\r/\n/g' "${out}")"
    rm -f "${out}"
    printf '%s\n' "${HP_OUT}" >>"${LOG_FILE}"
    return 0
}

# Rote Fehlerleiste von Hyprland ausblenden (wird bei jedem Config-Reload neu gesetzt)
# Erst die dokumentierte Form "disable"; meldet hyprctl dabei etwas anderes als
# "ok", wird zusaetzlich "false" probiert (raeumt die Leiste nachweislich auch weg).
clear_error() {
    local out
    out="$(hyprctl seterror disable 2>&1 || true)"
    [[ "${out}" == ok* ]] || hyprctl seterror false >/dev/null 2>&1 || true
}

hypr_key() { hyprctl version 2>/dev/null | sed -n '1p'; }

wait_for_hyprland() {
    local i
    for i in $(seq 1 30); do
        [[ -n "$(hypr_key)" ]] && return 0
        sleep 2
    done
    return 1
}

network_ok() {
    if command -v nm-online >/dev/null 2>&1; then
        nm-online -q -t 30 || return 1
    fi
    curl -fsSI --max-time 15 https://github.com >/dev/null 2>&1
}

load_conf() {
    local url plugins
    [[ -f "${CONF}" ]] || { log "Plugin-Liste fehlt: ${CONF}"; return 1; }
    while read -r url plugins; do
        [[ -z "${url}" || "${url}" == \#* ]] && continue
        [[ -n "${plugins}" ]] || { log "Keine Plugins bei ${url}, uebersprungen."; continue; }
        REPO_URLS+=("${url}")
        REPO_PLUGINS["${url}"]="${plugins}"
    done < "${CONF}"
    ((${#REPO_URLS[@]})) || { log "Plugin-Liste ist leer."; return 1; }
}

# Passt der von hyprpm gemeldete Name zu einem Repo der Liste?
# (Repo-Name = Ende der URL, oder einer der Plugin-Namen)
repo_matches() {
    local url="$1" name="${2,,}" base p
    base="${url##*/}"; base="${base%.git}"
    [[ "${base,,}" == "${name}" ]] && return 0
    for p in ${REPO_PLUGINS[${url}]}; do
        [[ "${p,,}" == "${name}" ]] && return 0
    done
    return 1
}

remove_repo() {
    log "Entferne ${1}"
    hp remove "$1"
}

enable_plugin() {
    hp enable "$1"
    ((HP_RC == 0)) && return 0
    grep -qi 'already' <<<"${HP_OUT}" && return 0
    return 1
}

sync_plugins() {
    wait_for_hyprland || { log "Es laeuft kein Hyprland. Das Skript muss in der Session laufen."; return 1; }
    load_conf || return 1
    network_ok || { log "Kein Netz, nichts geaendert."; notify "Hyprland Plugins" "Kein Internet"; return 1; }

    local key
    key="$(hypr_key)"
    log "Laufendes Hyprland: ${key}"
    notify "Hyprland Plugins" "Bauen laeuft"

    # 1) alles Registrierte neu bauen
    log "hyprpm update"
    hp update
    local update_rc="${HP_RC}" fail_line=""
    fail_line="$(grep -E 'failed to update the following repositories:' <<<"${HP_OUT}" | tail -n1 || true)"

    if ((update_rc != 0)) && [[ -z "${fail_line}" ]]; then
        # Unbekannter Fehler (z.B. Header nicht ladbar): nichts anfassen
        log "hyprpm update fehlgeschlagen, Grund unklar. Es wurde NICHTS entfernt."
        notify "Hyprland Plugins" "Fehlgeschlagen, siehe Log"
        return 1
    fi

    # 2) gescheiterte Repos entfernen
    local names=() name url matched
    if [[ -n "${fail_line}" ]]; then
        fail_line="${fail_line#*: }"
        fail_line="${fail_line//,/ }"
        read -r -a names <<<"${fail_line}"
    fi
    for name in "${names[@]}"; do
        matched=0
        for url in "${REPO_URLS[@]}"; do
            if repo_matches "${url}" "${name}"; then
                remove_repo "${url}"
                REMOVED["${url}"]=1
                matched=1
                break
            fi
        done
        if ((!matched)); then
            log "Repo ${name} (nicht in der Liste) ging nicht, entferne es."
            remove_repo "${name}"
        fi
    done

    # 3) alle Repos der Liste (erneut) hinzufuegen. Der Rueckgabewert ist egal:
    #    bereits vorhandene Repos melden einen Fehler. Entscheidend ist 4).
    for url in "${REPO_URLS[@]}"; do
        [[ -n "${REMOVED[${url}]:-}" ]] && continue
        log "hyprpm add ${url}"
        hp add "${url}"
    done

    # 4) Plugins aktivieren. Geht eines nicht, fliegt das ganze Repo raus.
    local plugin ok
    for url in "${REPO_URLS[@]}"; do
        [[ -n "${REMOVED[${url}]:-}" ]] && continue
        ok=1
        for plugin in ${REPO_PLUGINS[${url}]}; do
            if enable_plugin "${plugin}"; then
                log "aktiv: ${plugin}"
            else
                log "nicht aktivierbar: ${plugin}"
                ok=0
                break
            fi
        done
        if ((ok)); then
            KEPT+=("${url##*/}")
        else
            remove_repo "${url}"
            REMOVED["${url}"]=1
        fi
    done

    # 5) in die laufende Session laden
    log "hyprpm reload"
    hp reload -n

    # Merken, was los war
    local removed_names=()
    : > "${REMOVED_FILE}"
    for url in "${REPO_URLS[@]}"; do
        if [[ -n "${REMOVED[${url}]:-}" ]]; then
            removed_names+=("${url##*/}")
            echo "${url}" >> "${REMOVED_FILE}"
        fi
    done
    echo "${key}" > "${STAMP_FILE}"

    log "Behalten: ${KEPT[*]:-nichts}"
    if ((${#removed_names[@]})); then
        log "Entfernt (bauen nicht auf dieser Hyprland-Version): ${removed_names[*]}"
        notify "Hyprland Plugins" "Entfernt: ${removed_names[*]}"
        clear_error
    else
        log "Alle Plugins aktiv."
        notify "Hyprland Plugins" "Fertig"
    fi
    return 0
}

auto_needed() {
    local key stamp
    key="$(hypr_key)"
    [[ -n "${key}" ]] || return 1

    # Erster Lauf ueberhaupt: den vorhandenen Zustand als passend annehmen
    # (ISO/aktuelles System) und nur die Version merken.
    if [[ ! -f "${STAMP_FILE}" ]]; then
        echo "${key}" > "${STAMP_FILE}"
        return 1
    fi

    stamp="$(cat "${STAMP_FILE}" 2>/dev/null || true)"
    [[ "${key}" != "${stamp}" ]] && return 0

    # Gleiche Version, aber es fehlen Plugins: gelegentlich neu versuchen
    if [[ -s "${REMOVED_FILE}" ]] \
        && [[ -n "$(find "${STAMP_FILE}" -mmin "+${RETRY_MINUTES}" 2>/dev/null)" ]]; then
        return 0
    fi
    return 1
}

main() {
    exec 7>"${RUNTIME_DIR}/TrafkTuxHyprpmSync.lock"
    case "${1:---now}" in
        --now)
            flock -w 3600 7 || exit 1
            sync_plugins
            ;;
        --auto)
            flock -n 7 || exit 0
            wait_for_hyprland || exit 0
            # Fehlerleiste wegen entfernter Plugins bei jedem Login wegraeumen
            if [[ -s "${REMOVED_FILE}" ]]; then
                sleep 3
                clear_error
            fi
            auto_needed || exit 0
            if command -v nm-online >/dev/null 2>&1 && ! nm-online -q -t 60; then
                exit 0   # kein Netz beim Login: beim naechsten Mal wieder
            fi
            log "Hyprland-Version hat sich geaendert (oder Neuversuch), baue Plugins neu."
            sync_plugins
            ;;
        --clear-error)
            clear_error
            ;;
        -h|--help)
            sed -n '2,41p' "$0"
            ;;
        *)
            echo "Unbekannte Option: $1 (siehe --help)" >&2
            exit 2
            ;;
    esac
}

main "$@"
