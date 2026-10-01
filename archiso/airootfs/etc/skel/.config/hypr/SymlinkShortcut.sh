#!/usr/bin/env bash
#
# SymlinkShortcut.sh — relative Symlinks per Thunar-Tastenkürzel erstellen,
# verschieben und reparieren. Unterstützt Mehrfachauswahl bei allen vier
# Funktionen.
# Ort: ~/.config/hypr/SymlinkShortcut.sh
#
# KEINE Benachrichtigungen mehr - alles landet nur im Debug-Log:
#   ~/.cache/hypr/symlink_debug.log
# Bei Problemen dort reinschauen (tail -f ~/.cache/hypr/symlink_debug.log
# während man in Thunar die Taste drückt).
#
# Wird von Thunars "Benutzerdefinierten Aktionen" aufgerufen (siehe uca.xml):
#   SymlinkShortcut.sh source <datei1> [datei2 ...]   -- Strg+Alt+C, Befehl: ... source %F
#   SymlinkShortcut.sh paste  <ordner>                -- Strg+Alt+V, Befehl: ... paste .
#   SymlinkShortcut.sh move   <symlink1> [symlink2..] -- Strg+Alt+X, Befehl: ... move %F
#   SymlinkShortcut.sh repair <element1> [element2..] -- Strg+Alt+Y, Befehl: ... repair %F
#
# Ablauf:
#   Strg+Alt+C  Eine oder mehrere Dateien/Ordner markieren -> alle werden als
#               Quellen in eine Warteschlange gelegt (ersetzt alte Warteschlange).
#   Strg+Alt+V  In den Zielordner wechseln (nichts markieren nötig) -> legt dort
#               für JEDE Quelle aus der Warteschlange einen RELATIVEN Symlink an.
#               Läuft gerade ein Verschiebevorgang (siehe X), wird der
#               stattdessen hier abgeschlossen (für jeden markierten Symlink).
#   Strg+Alt+X  Einen oder mehrere bestehende Symlinks markieren -> merkt sich
#               für jeden das (aufgelöste) Ziel und den aktuellen Ort. Danach
#               in den neuen Ordner wechseln und Strg+Alt+V drücken: legt jeden
#               Symlink dort mit neu berechnetem relativem Pfad an und löscht
#               die alten.
#   Strg+Alt+Y  Einen oder mehrere Ordner und/oder einzelne Symlinks markieren
#               -> bei Ordnern wird rekursiv nach kaputten Symlinks gesucht,
#               einzeln markierte Symlinks werden direkt geprüft. Für jeden
#               kaputten Symlink wird unter $HOME nach einer Datei/einem Ordner
#               mit demselben Namen gesucht. Bei GENAU EINEM Treffer wird
#               automatisch repariert, bei mehreren/keinem übersprungen.
#               Heuristik (Best Effort) über den Dateinamen - Ergebnis steht
#               im Debug-Log, nicht als Benachrichtigung.
#
# Abhängigkeiten: bash (4+), coreutils (realpath, readlink, dirname, basename),
# findutils.

set -uo pipefail
# (bewusst KEIN "-e" mehr: bei mehreren Dateien in einer Schleife soll ein
#  einzelner Fehler nicht die Verarbeitung der restlichen abbrechen. Fehler
#  werden stattdessen einzeln geloggt und gezählt.)

CACHE_DIR="$HOME/.cache/hypr"
CONFIG_DIR="$HOME/.config/hypr"
SRC_QUEUE="$CACHE_DIR/symlink_sources"     # eine Quelle pro Zeile
MOVE_QUEUE="$CACHE_DIR/symlink_moves"      # "abs_target<TAB>alter_link" pro Zeile
DEBUG_LOG="$CACHE_DIR/symlink_debug.log"
mkdir -p "$CACHE_DIR"

# Ordner, die bei der repair-Suche nach gleichnamigen Dateien IGNORIERT werden -
# v.a. Paketmanager-/Programm-Caches, in denen zufällig gleichnamige Dateien
# liegen (z.B. eine Datei "ef" gibt es zigfach in npm-/Steam-/Unity-Caches).
# Eigene zusätzliche Ausschlüsse: eine Zeile pro Ordnername in
#   ~/.config/hypr/symlink-repair-exclude.txt
# (Kommentarzeilen mit # werden ignoriert.)
REPAIR_EXCLUDE_FILE="$CONFIG_DIR/symlink-repair-exclude.txt"
DEFAULT_REPAIR_EXCLUDES=(
    ".cache"
    ".git"
    "node_modules"
    ".local/share/Trash"
    ".npm"
    ".local/share/pnpm"
    ".local/share/Steam"
    ".var"
    ".cargo"
    ".rustup"
    "Unity/Hub/Editor"
    ".yarn/cache"
    ".gradle"
    ".m2"
)

# Baut die find-Prune-Ausdrücke ( -path "*/x/*" -o -path "*/y/*" ... ),
# als Array, damit sie 1:1 als find-Argumente übergeben werden können.
build_repair_prune_args() {
    local -a all=("${DEFAULT_REPAIR_EXCLUDES[@]}")
    if [[ -f "$REPAIR_EXCLUDE_FILE" ]]; then
        local line
        while IFS= read -r line; do
            [[ -z "$line" || "$line" == \#* ]] && continue
            all+=("$line")
        done < "$REPAIR_EXCLUDE_FILE"
    fi
    local -a expr=("(")
    local pat first=1
    for pat in "${all[@]}"; do
        [[ $first -eq 0 ]] && expr+=("-o")
        expr+=("-path" "*/$pat/*")
        first=0
    done
    expr+=(")")
    printf '%s\n' "${expr[@]}"
}

log_debug() {
    printf '[%s] %s\n' "$(date '+%F %T')" "$*" >> "$DEBUG_LOG" 2>/dev/null
}

# --- source: eine oder mehrere Dateien/Ordner als Quelle merken ------------

cmd_source() {
    local -a files=("$@")
    if [[ ${#files[@]} -eq 0 ]]; then
        log_debug "source: keine Dateien übergeben"
        return 1
    fi

    : > "$SRC_QUEUE"
    local f abs added=0 skipped=0
    for f in "${files[@]}"; do
        if [[ -e "$f" ]]; then
            abs=$(realpath -m -- "$f")
            printf '%s\n' "$abs" >> "$SRC_QUEUE"
            added=$((added + 1))
        else
            log_debug "source: existiert nicht, übersprungen: $f"
            skipped=$((skipped + 1))
        fi
    done
    rm -f "$MOVE_QUEUE"
    log_debug "source: $added Quelle(n) gemerkt, $skipped übersprungen. Inhalt: $(tr '\n' ';' < "$SRC_QUEUE")"
}

# --- move: einen oder mehrere bestehende Symlinks zum Verschieben merken --

cmd_move() {
    local -a files=("$@")
    if [[ ${#files[@]} -eq 0 ]]; then
        log_debug "move: keine Dateien übergeben"
        return 1
    fi

    : > "$MOVE_QUEUE"
    local f abs added=0 skipped=0
    for f in "${files[@]}"; do
        if [[ -L "$f" ]]; then
            abs=$(realpath -m -- "$f")   # löst den Symlink auf -> kanonisches Ziel
            printf '%s\t%s\n' "$abs" "$f" >> "$MOVE_QUEUE"
            added=$((added + 1))
        else
            log_debug "move: kein Symlink, übersprungen: $f"
            skipped=$((skipped + 1))
        fi
    done
    rm -f "$SRC_QUEUE"
    log_debug "move: $added Symlink(s) zum Verschieben markiert, $skipped übersprungen"
}

# --- paste: Warteschlange(n) im aktuellen Ordner anlegen -------------------

cmd_paste() {
    local target_dir="${1:-}"
    if [[ -z "$target_dir" || ! -d "$target_dir" ]]; then
        log_debug "paste: kein gültiger Zielordner: $target_dir"
        return 1
    fi
    target_dir=$(realpath -m -- "$target_dir")

    local created=0 moved=0 errors=0
    local real_target old_link link_name link_path rel

    if [[ -s "$MOVE_QUEUE" ]]; then
        while IFS=$'\t' read -r real_target old_link; do
            [[ -z "$real_target" ]] && continue
            link_name=$(basename -- "$old_link")
            link_path="$target_dir/$link_name"
            if [[ ! -e "$real_target" ]]; then
                log_debug "paste(move): Ziel existiert nicht mehr: $real_target"
                errors=$((errors + 1)); continue
            fi
            if [[ -e "$link_path" || -L "$link_path" ]]; then
                log_debug "paste(move): existiert schon, übersprungen: $link_path"
                errors=$((errors + 1)); continue
            fi
            rel=$(realpath -m --relative-to="$target_dir" -- "$real_target")
            ln -s -- "$rel" "$link_path"
            rm -f -- "$old_link"
            moved=$((moved + 1))
        done < "$MOVE_QUEUE"
        rm -f "$MOVE_QUEUE"
    elif [[ -s "$SRC_QUEUE" ]]; then
        while IFS= read -r real_target; do
            [[ -z "$real_target" ]] && continue
            link_name=$(basename -- "$real_target")
            link_path="$target_dir/$link_name"
            if [[ ! -e "$real_target" ]]; then
                log_debug "paste: Quelle existiert nicht mehr: $real_target"
                errors=$((errors + 1)); continue
            fi
            if [[ -e "$link_path" || -L "$link_path" ]]; then
                log_debug "paste: existiert schon, übersprungen: $link_path"
                errors=$((errors + 1)); continue
            fi
            rel=$(realpath -m --relative-to="$target_dir" -- "$real_target")
            ln -s -- "$rel" "$link_path"
            created=$((created + 1))
        done < "$SRC_QUEUE"
    else
        log_debug "paste: keine Quelle(n) gemerkt (erst Strg+Alt+C oder Strg+Alt+X benutzen)"
        return 1
    fi

    log_debug "paste in $target_dir: erstellt=$created verschoben=$moved fehler=$errors"
}

# --- repair: einen Symlink prüfen und ggf. reparieren, Ergebnis zurückgeben

# --- repair: einen Symlink prüfen und ggf. reparieren, Ergebnis zurückgeben

# Entfernt führende "../" bzw. "./" (reine Navigation, kein Namens-Fingerabdruck).
strip_parent_refs() {
    local p="$1"
    while [[ "$p" == ../* ]]; do p="${p#../}"; done
    while [[ "$p" == ./* ]]; do p="${p#./}"; done
    printf '%s' "$p"
}

# Baut Kandidaten von SPEZIFISCH (voller Restpfad) nach UNSPEZIFISCH (nur
# Basisname), z.B. aus "Downloads/Projekt/ef" -> "Downloads/Projekt/ef",
# "Projekt/ef", "ef" - in genau dieser Reihenfolge.
build_suffix_candidates() {
    local path="$1"
    local -a parts
    IFS='/' read -ra parts <<< "$path"
    local n=${#parts[@]} i suf
    for ((i = 0; i < n; i++)); do
        suf=$(IFS=/; echo "${parts[*]:i}")
        printf '%s\n' "$suf"
    done
}

# Sucht nach einem Kandidaten-Suffix. Enthält der Kandidat noch "/", muss der
# gefundene Pfad GENAU so enden (-path); ist es nur noch ein nackter Name,
# wird wie bisher per -name gesucht (matcht auch dann, wenn der übergeordnete
# Ordner selbst umbenannt wurde - das ist der bewusste letzte Rückfall).
find_suffix_matches() {
    local suffix="$1"
    local -a prune_args matches
    mapfile -t prune_args < <(build_repair_prune_args)
    if [[ "$suffix" == */* ]]; then
        mapfile -d '' matches < <(find "$HOME" "${prune_args[@]}" -prune -o \
            -path "*/$suffix" -not -type l -print0 2>/dev/null)
    else
        mapfile -d '' matches < <(find "$HOME" "${prune_args[@]}" -prune -o \
            -name "$suffix" -not -type l -print0 2>/dev/null)
    fi
    printf '%s\0' "${matches[@]}"
}

try_repair_link() {
    local link="$1"
    if [[ -e "$link" ]]; then
        echo "ok"
        return
    fi

    local raw_target stripped link_dir suffix count match new_rel
    local -a candidates matches
    raw_target=$(readlink -- "$link")
    stripped=$(strip_parent_refs "$raw_target")
    link_dir=$(dirname -- "$link")

    mapfile -t candidates < <(build_suffix_candidates "$stripped")

    for suffix in "${candidates[@]}"; do
        mapfile -d '' matches < <(find_suffix_matches "$suffix")
        count=${#matches[@]}
        log_debug "repair-link $link: Ebene '$suffix' -> $count Treffer ${matches[*]:-}"

        if [[ $count -eq 1 ]]; then
            match=$(realpath -m -- "${matches[0]}")
            new_rel=$(realpath -m --relative-to="$link_dir" -- "$match")
            ln -sf -- "$new_rel" "$link"
            log_debug "repair-link $link: repariert über Ebene '$suffix' -> $match"
            echo "fixed"
            return
        fi
    done

    # Keine Ebene lieferte genau einen Treffer - letzter Zählerstand
    # (vom unspezifischsten Versuch, nur Basisname) entscheidet ambiguous/unresolved.
    if [[ $count -gt 1 ]]; then
        echo "ambiguous"
    else
        echo "unresolved"
    fi
}

cmd_repair() {
    local -a items=("$@")
    if [[ ${#items[@]} -eq 0 ]]; then
        log_debug "repair: keine Auswahl übergeben"
        return 1
    fi

    local fixed=0 ambiguous=0 unresolved=0 ok=0
    local item result link

    for item in "${items[@]}"; do
        if [[ ! -e "$item" && ! -L "$item" ]]; then
            log_debug "repair: existiert nicht, übersprungen: $item"
            continue
        fi

        if [[ -d "$item" ]]; then
            log_debug "repair: durchsuche Ordner rekursiv: $item"
            while IFS= read -r -d '' link; do
                result=$(try_repair_link "$link")
                case "$result" in
                    fixed) fixed=$((fixed + 1)) ;;
                    ambiguous) ambiguous=$((ambiguous + 1)) ;;
                    unresolved) unresolved=$((unresolved + 1)) ;;
                    ok) ok=$((ok + 1)) ;;
                esac
            done < <(find "$item" -type l -print0)
        elif [[ -L "$item" ]]; then
            log_debug "repair: prüfe einzelnen Symlink: $item"
            result=$(try_repair_link "$item")
            case "$result" in
                fixed) fixed=$((fixed + 1)) ;;
                ambiguous) ambiguous=$((ambiguous + 1)) ;;
                unresolved) unresolved=$((unresolved + 1)) ;;
                ok) ok=$((ok + 1)) ;;
            esac
        else
            log_debug "repair: weder Ordner noch Symlink, übersprungen: $item"
        fi
    done

    log_debug "repair fertig: repariert=$fixed mehrdeutig=$ambiguous nicht_gefunden=$unresolved bereits_ok=$ok"
}

# --- Dispatch --------------------------------------------------------------

mode="${1:-}"
[[ $# -gt 0 ]] && shift

log_debug "aufgerufen: mode=$mode args=($*) cwd=$(pwd)"

case "$mode" in
    source) cmd_source "$@" ;;
    paste)  cmd_paste  "$@" ;;
    move)   cmd_move   "$@" ;;
    repair) cmd_repair "$@" ;;
    *)
        log_debug "unbekannter Modus: $mode"
        echo "Usage: $(basename -- "$0") {source|paste|move|repair} <pfad(e)>" >&2
        exit 1
        ;;
esac
