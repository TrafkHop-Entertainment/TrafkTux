#!/bin/bash
# hideall.sh — Toggle: alle offenen Fenster in einen Hidden-Workspace schicken
# und beim erneuten Aufruf wieder in ihre ursprünglichen Workspaces zurückholen.
#
# Aufruf:
#   hideall.sh toggle   -> hide/restore umschalten (default, auch ohne Argument)
#   hideall.sh status   -> gibt {"class":"active"|"inactive"} aus, fuer waybar exec
#
# Funktionsweise:
#   Beim ersten Aufruf werden Adresse + Ursprungs-Workspace jedes "normalen"
#   Fensters (also nichts, das schon auf einem special:-Workspace liegt - z.B.
#   Fenster, die einzeln per hyprland-minimizer minimiert wurden, die lassen
#   wir in Ruhe) in eine State-Datei geschrieben. Danach wird jedes Fenster
#   per focus + "hyprland-minimizer" versteckt - GENAU das Muster, das
#   taskbar-click.sh fuers Rechtsklick-Minimieren benutzt (erst fokussieren,
#   dann den Befehl auf dem fokussierten Fenster feuern). Wir nutzen bewusst
#   das externe hyprland-minimizer-Binary statt eines eigenen
#   window.move-Dispatch-Calls in einen special-Workspace, weil letzterer in
#   Tests nur die Fenster im Layout durcheinandergewuerfelt hat, statt sie
#   wirklich in einen special-Workspace zu verschieben - hyprland-minimizer
#   ist dagegen bereits erwiesenermassen bei dir im Einsatz und funktioniert.
#
#   Beim zweiten Aufruf wird die State-Datei gelesen und jedes Fenster in
#   DERSELBEN Reihenfolge wie beim Verstecken per focus + window.move
#   (mit numerischer Workspace-ID - das ist der bestaetigt funktionierende
#   Call, siehe SUPER+SHIFT+Zahl in hyprland.lua) zurueck in seinen
#   urspruenglichen Workspace geschickt. Das sorgt dafuer, dass tiling
#   layouts (master/dwindle/scroller) die Fenster wieder in einer
#   aehnlichen Anordnung aufbauen. Floating-Fenster behalten ihre
#   x/y-Position ohnehin automatisch, da diese am Fenster selbst haengt und
#   durch einen Workspace-Wechsel in Hyprland nicht veraendert wird.
#
# Abhaengigkeiten: hyprctl, jq, hyprland-minimizer (muss im PATH liegen,
# so wie es schon fuer SUPER+ALT+Tab bei dir konfiguriert ist),
# notify-send (optional, nur fuer Hinweise).

set -uo pipefail

STATE_DIR="$HOME/.cache/hypr"
STATE_FILE="$STATE_DIR/hideall_state.json"

mkdir -p "$STATE_DIR"

mode="${1:-toggle}"

is_hidden() {
    [ -s "$STATE_FILE" ]
}

do_status() {
    if is_hidden; then
        echo '{"class":"active"}'
    else
        echo '{"class":"inactive"}'
    fi
}

do_hide() {
    local clients windows count

    if ! command -v hyprland-minimizer >/dev/null 2>&1; then
        notify-send "Hideall" "hyprland-minimizer nicht im PATH gefunden" -u critical || true
        return 1
    fi

    clients=$(hyprctl clients -j) || { notify-send "Hideall" "hyprctl clients fehlgeschlagen" -u critical || true; return 1; }

    # Nur Fenster, die noch nicht auf einem special:-Workspace liegen
    windows=$(echo "$clients" | jq -c '[.[] | select((.workspace.name // "") | startswith("special:") | not)]')
    count=$(echo "$windows" | jq 'length')

    if [ "$count" -eq 0 ]; then
        notify-send "Hideall" "Keine Fenster zum Verstecken" -u low || true
        return 0
    fi

    # Reihenfolge sichern: address + urspruenglicher Workspace (numerische id)
    echo "$windows" | jq -c '[.[] | {address: .address, workspace: .workspace.id}]' > "$STATE_FILE"

    echo "$windows" | jq -r '.[].address' | while read -r addr; do
        hyprctl dispatch "hl.dsp.focus({window='address:$addr'})" >/dev/null 2>&1
        hyprctl dispatch "hl.dsp.exec_cmd(\"hyprland-minimizer\")" >/dev/null 2>&1
    done
}

do_restore() {
    jq -c '.[]' "$STATE_FILE" | while read -r entry; do
        addr=$(echo "$entry" | jq -r '.address')
        ws=$(echo "$entry" | jq -r '.workspace')
        hyprctl dispatch "hl.dsp.focus({window='address:$addr'})" >/dev/null 2>&1 || continue
        hyprctl dispatch "hl.dsp.window.move({workspace=$ws})" >/dev/null 2>&1
    done
    rm -f "$STATE_FILE"
}

case "$mode" in
    status)
        do_status
        ;;
    *)
        if is_hidden; then
            do_restore
        else
            do_hide
        fi
        ;;
esac
