#!/usr/bin/env bash
#
# SymlinkShortcut.sh — relative Symlinks per Thunar-Tastenkürzel erstellen,
# verschieben und reparieren.
# Ort: ~/.config/hypr/SymlinkShortcut.sh
#
# Wird NICHT von Hand aufgerufen, sondern von Thunars "Benutzerdefinierte
# Aktionen" (siehe ThunarCustomActions.uca.xml + Anleitung). Thunar übergibt
# die markierte Datei (%f) bzw. den offenen Ordner (%d) direkt als Argument -
# kein Zwischenspeicher, kein Strg+C nötig.
#
# Aufruf (so ruft Thunar es auf):
#   SymlinkShortcut.sh source <markierte Datei>      -- Strg+Alt+C
#   SymlinkShortcut.sh paste  <offener Ordner>        -- Strg+Alt+V
#   SymlinkShortcut.sh move   <markierter Symlink>    -- Strg+Alt+X
#   SymlinkShortcut.sh repair <offener Ordner>        -- Strg+Alt+Y
#
# Ablauf:
#   Strg+Alt+C  Datei/Ordner markieren -> merkt sich den Pfad als Quelle.
#   Strg+Alt+V  In den Zielordner wechseln (nichts markieren nötig) ->
#               legt dort einen RELATIVEN Symlink auf die gemerkte Quelle an.
#               Läuft gerade ein Verschiebevorgang (siehe X), wird der
#               stattdessen hier abgeschlossen.
#   Strg+Alt+X  Bestehenden Symlink markieren -> merkt sich dessen (aufgelöstes)
#               Ziel und seinen aktuellen Ort. Danach in den neuen Ordner
#               wechseln und Strg+Alt+V drücken: legt den Symlink dort mit neu
#               berechnetem relativem Pfad an und löscht den alten.
#   Strg+Alt+Y  In einen (evtl. verschobenen) Ordner wechseln -> durchsucht ihn
#               rekursiv nach kaputten Symlinks. Für jeden wird unter $HOME
#               nach einer Datei/einem Ordner mit demselben Namen gesucht.
#               Bei GENAU EINEM Treffer wird automatisch repariert, bei
#               mehreren/keinem übersprungen. Heuristik (Best Effort) über den
#               Dateinamen, kein Hexenwerk - Notification zeigt das Ergebnis.
#
# Abhängigkeiten: bash, coreutils (realpath, readlink, dirname, basename),
# findutils, libnotify (notify-send).

set -euo pipefail

CACHE_DIR="$HOME/.cache/hypr"
SRC_FILE="$CACHE_DIR/symlink_source"
MOVE_FILE="$CACHE_DIR/symlink_move"
mkdir -p "$CACHE_DIR"

# --- Hilfsfunktionen ---------------------------------------------------

notify() {
    # $1 = Titel, $2 = Text, $3 = optional "critical"
    if [[ "${3:-}" == "critical" ]]; then
        notify-send -u critical -a "Symlink" -- "$1" "$2"
    else
        notify-send -a "Symlink" -- "$1" "$2"
    fi
}

# --- Kommandos -----------------------------------------------------------

cmd_source() {
    local path="${1:-}"
    if [[ -z "$path" || ! -e "$path" ]]; then
        notify "Symlink: Quelle" "Keine gültige Datei übergeben:\n$path" critical
        exit 1
    fi
    path=$(realpath -m -- "$path")

    rm -f "$MOVE_FILE"
    printf '%s' "$path" > "$SRC_FILE"
    notify "Quelle gemerkt" "$path"
}

cmd_move() {
    local path="${1:-}"
    if [[ -z "$path" || ! -L "$path" ]]; then
        notify "Symlink verschieben" "Das ist kein Symlink:\n$path" critical
        exit 1
    fi

    # realpath löst den Symlink standardmäßig auf -> kanonisches, absolutes Ziel.
    local abs_target
    abs_target=$(realpath -m -- "$path")

    rm -f "$SRC_FILE"
    printf '%s\n%s\n' "$abs_target" "$path" > "$MOVE_FILE"
    notify "Symlink zum Verschieben markiert" "$path\nZiel: $abs_target\n\nJetzt im neuen Ordner Strg+Alt+V drücken."
}

cmd_paste() {
    local target_dir="${1:-}"
    if [[ -z "$target_dir" || ! -d "$target_dir" ]]; then
        notify "Symlink erstellen" "Kein gültiger Zielordner:\n$target_dir" critical
        exit 1
    fi
    target_dir=$(realpath -m -- "$target_dir")

    local real_target link_name is_move=0 old_link=""
    if [[ -s "$MOVE_FILE" ]]; then
        is_move=1
        real_target=$(sed -n '1p' "$MOVE_FILE")
        old_link=$(sed -n '2p' "$MOVE_FILE")
        link_name=$(basename -- "$old_link")
    elif [[ -s "$SRC_FILE" ]]; then
        real_target=$(cat "$SRC_FILE")
        link_name=$(basename -- "$real_target")
    else
        notify "Symlink erstellen" "Keine Quelle gemerkt.\nErst Strg+Alt+C (neuer Symlink) oder Strg+Alt+X (verschieben) benutzen." critical
        exit 1
    fi

    if [[ ! -e "$real_target" ]]; then
        notify "Symlink erstellen" "Die Zieldatei gibt es nicht mehr:\n$real_target" critical
        exit 1
    fi

    local link_path rel_target
    link_path="$target_dir/$link_name"

    if [[ -e "$link_path" || -L "$link_path" ]]; then
        notify "Symlink erstellen" "Existiert schon:\n$link_path" critical
        exit 1
    fi

    rel_target=$(realpath -m --relative-to="$target_dir" -- "$real_target")
    ln -s -- "$rel_target" "$link_path"

    if [[ $is_move -eq 1 ]]; then
        rm -f -- "$old_link"
        rm -f "$MOVE_FILE"
        notify "Symlink verschoben" "$link_path\n-> $rel_target"
    else
        notify "Symlink erstellt" "$link_path\n-> $rel_target"
    fi
}

cmd_repair() {
    local folder="${1:-}"
    if [[ -z "$folder" || ! -d "$folder" ]]; then
        notify "Symlinks reparieren" "Kein gültiger Ordner:\n$folder" critical
        exit 1
    fi
    folder=$(realpath -m -- "$folder")

    local fixed=0 ambiguous=0 unresolved=0

    while IFS= read -r -d '' link; do
        # Funktionierende Symlinks in Ruhe lassen.
        [[ -e "$link" ]] && continue

        local raw_target base link_dir count match new_rel
        local -a matches
        raw_target=$(readlink -- "$link")
        base=$(basename -- "$raw_target")
        link_dir=$(dirname -- "$link")

        mapfile -d '' matches < <(find "$HOME" \
            \( -path "*/.cache/*" -o -path "*/.git/*" -o -path "*/node_modules/*" -o -path "*/.Trash*" \) -prune -o \
            -name "$base" -not -type l -print0 2>/dev/null)
        count=${#matches[@]}

        if [[ $count -eq 1 ]]; then
            match=$(realpath -m -- "${matches[0]}")
            new_rel=$(realpath -m --relative-to="$link_dir" -- "$match")
            ln -sf -- "$new_rel" "$link"
            fixed=$((fixed + 1))
        elif [[ $count -gt 1 ]]; then
            ambiguous=$((ambiguous + 1))
        else
            unresolved=$((unresolved + 1))
        fi
    done < <(find "$folder" -type l -print0)

    notify "Symlinks repariert – $folder" "Repariert: $fixed\nMehrdeutig (übersprungen): $ambiguous\nNicht gefunden: $unresolved"
}

# --- Dispatch --------------------------------------------------------------

case "${1:-}" in
    source) cmd_source "${2:-}" ;;
    paste)  cmd_paste  "${2:-}" ;;
    move)   cmd_move   "${2:-}" ;;
    repair) cmd_repair "${2:-}" ;;
    *)
        echo "Usage: $(basename -- "$0") {source|paste|move|repair} <pfad>" >&2
        exit 1
        ;;
esac
