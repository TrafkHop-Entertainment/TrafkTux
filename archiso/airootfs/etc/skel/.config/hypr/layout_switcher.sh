#!/usr/bin/env bash
ACTION=$(echo "$1" | tr '[:upper:]' '[:lower:]')

# Hebt Floating für alle aktuell gefloateten Fenster auf dem aktiven Workspace auf,
# damit beim Wechsel zu einem Tiling-Layout keine Fenster im Floati#!/usr/bin/env bash
ACTION=$(echo "$1" | tr '[:upper:]' '[:lower:]')

# Persistiert das zuletzt aktiv gesetzte Tiling-Layout, damit hyprland.lua
# beim nächsten "hyprctl reload" den Wert wieder einlesen und general.layout
# darauf setzen kann, statt ihn auf den hartkodierten Default zurückzusetzen.
# "floating" wird bewusst NICHT gespeichert: das ist kein general.layout-Wert,
# sondern toggelt nur den Floating-Status der Fenster - das zugrunde liegende
# Tiling-Layout bleibt dabei unverändert.
STATE_DIR="$HOME/.cache/hypr"
STATE_FILE="$STATE_DIR/layout_switcher_state"
mkdir -p "$STATE_DIR"

save_layout_state() {
    echo "$1" > "$STATE_FILE"
}

# Hebt Floating für alle aktuell gefloateten Fenster auf dem aktiven Workspace auf,
# damit beim Wechsel zu einem Tiling-Layout keine Fenster im Floating-Modus "kleben bleiben".
unfloat_current_workspace() {
    CURRENT_WS=$(hyprctl activeworkspace -j | jq '.id')
    hyprctl clients -j | jq -r ".[] | select(.workspace.id == $CURRENT_WS and .floating == true and .pinned != true) | .address" | while read -r addr; do
        hyprctl eval "hl.dispatch(hl.dsp.window.float({ action = 'toggle', window = 'address:$addr' }))"
    done
}

# Hebt einen manuell gesetzten Fullscreen-/Maximize-Zustand (z.B. von Mod+Space
# oder Mod+Shift+Space, siehe hyprland.lua) auf allen Fenstern des aktiven
# Workspace auf. Das ist nötig, BEVOR wir ins Monocle-Layout wechseln: ein
# Fenster, das noch "hart" auf fullscreen-Modus 1 oder 2 steht, würde sich
# sonst mit Monocles eigener Fokus-folgt-Logik überschneiden -> mögliches
# Resultat wäre ein "eingefrorenes" maximiertes Fenster, das nicht mehr
# wechselt, obwohl der Fokus längst auf einem anderen Fenster liegt.
#
# Wir lesen pro Fenster den AKTUELLEN Modus aus und dispatchen exakt diesen
# Modus erneut gezielt an die Fensteradresse zurück. "fullscreen" ist ein
# Toggle-Dispatcher: der gleiche Modus an dasselbe Fenster garantiert ein
# "Aus" statt eines Moduswechsels (z.B. maximize -> fullscreen).
clear_fullscreen_current_workspace() {
    local ws
    ws=$(hyprctl activeworkspace -j | jq '.id')
    [ -z "$ws" ] && return 0

    hyprctl clients -j | jq -r --argjson ws "$ws" '
        .[] | select(.workspace.id == $ws) |
        (.fullscreen // 0) as $raw |
        (if ($raw | type) == "boolean" then (if $raw then 1 else 0 end) else $raw end) as $mode |
        select($mode != 0) | "\(.address) \($mode)"
    ' | while read -r addr mode; do
        hyprctl eval "hl.dispatch(hl.dsp.window.fullscreen({ mode = $mode, window = 'address:$addr' }))"
    done
}

case "$ACTION" in
    master|dwindle)
        unfloat_current_workspace
        hyprctl eval "hl.config({ general = { layout = '$ACTION' } })"
        save_layout_state "$ACTION"
        ;;
    scroller|scrolling)
        unfloat_current_workspace
        hyprctl eval "hl.config({ general = { layout = 'scrolling' } })"
        save_layout_state "scrolling"
        ;;
    floating)
        CURRENT_WS=$(hyprctl activeworkspace -j | jq '.id')
        hyprctl clients -j | jq -r ".[] | select(.workspace.id == $CURRENT_WS and .floating == false) | .address" | while read -r addr; do
            hyprctl eval "hl.dispatch(hl.dsp.window.float({ action = 'toggle', window = 'address:$addr' }))"
        done
        ;;
    bigscreen|monocle)
        # Natives Monocle-Layout: genau EIN gekacheltes Fenster ist immer
        # maximiert, und es ist immer das aktuell aktive Fenster - das
        # Layout hört intern auf die window.active-Events des Compositors
        # und synct sich dadurch von selbst mit dem Fokus, unabhängig davon,
        # ob der Fokuswechsel über Tastatur, Maus oder hyprctl ausgelöst
        # wurde.
        #
        # Floating-Fenster und Popups (Dialoge, Rofi, swayosd-OSD,
        # Benachrichtigungen, ...) gehören grundsätzlich NIE zu den "tiled
        # targets" eines Layouts. Monocle rührt sie deshalb gar nicht erst
        # an, sie werden ganz normal schwebend weitergerendert - exakt das
        # gewünschte "außer floating/Popups"-Verhalten, ganz ohne dass wir
        # das hier selbst nachbauen oder einen Hintergrund-Daemon brauchen.
        #
        # Sind alle Fenster des Workspace floating, bleibt der Tiling-
        # Bereich leer (kein Absturz, kein Bug - es gibt schlicht kein
        # gekacheltes Fenster, das maximiert werden könnte).
        clear_fullscreen_current_workspace
        hyprctl eval "hl.config({ general = { layout = 'monocle' } })"
        save_layout_state "monocle"
        ;;
esac
ng-Modus "kleben bleiben".
unfloat_current_workspace() {
    CURRENT_WS=$(hyprctl activeworkspace -j | jq '.id')
    hyprctl clients -j | jq -r ".[] | select(.workspace.id == $CURRENT_WS and .floating == true) | .address" | while read -r addr; do
        hyprctl eval "hl.dispatch(hl.dsp.window.float({ action = 'toggle', window = 'address:$addr' }))"
    done
}

# Hebt einen manuell gesetzten Fullscreen-/Maximize-Zustand (z.B. von Mod+Space
# oder Mod+Shift+Space, siehe hyprland.lua) auf allen Fenstern des aktiven
# Workspace auf. Das ist nötig, BEVOR wir ins Monocle-Layout wechseln: ein
# Fenster, das noch "hart" auf fullscreen-Modus 1 oder 2 steht, würde sich
# sonst mit Monocles eigener Fokus-folgt-Logik überschneiden -> mögliches
# Resultat wäre ein "eingefrorenes" maximiertes Fenster, das nicht mehr
# wechselt, obwohl der Fokus längst auf einem anderen Fenster liegt.
#
# Wir lesen pro Fenster den AKTUELLEN Modus aus und dispatchen exakt diesen
# Modus erneut gezielt an die Fensteradresse zurück. "fullscreen" ist ein
# Toggle-Dispatcher: der gleiche Modus an dasselbe Fenster garantiert ein
# "Aus" statt eines Moduswechsels (z.B. maximize -> fullscreen).
clear_fullscreen_current_workspace() {
    local ws
    ws=$(hyprctl activeworkspace -j | jq '.id')
    [ -z "$ws" ] && return 0

    hyprctl clients -j | jq -r --argjson ws "$ws" '
        .[] | select(.workspace.id == $ws) |
        (.fullscreen // 0) as $raw |
        (if ($raw | type) == "boolean" then (if $raw then 1 else 0 end) else $raw end) as $mode |
        select($mode != 0) | "\(.address) \($mode)"
    ' | while read -r addr mode; do
        hyprctl eval "hl.dispatch(hl.dsp.window.fullscreen({ mode = $mode, window = 'address:$addr' }))"
    done
}

case "$ACTION" in
    master|dwindle)
        unfloat_current_workspace
        hyprctl eval "hl.config({ general = { layout = '$ACTION' } })"
        ;;
    scroller|scrolling)
        unfloat_current_workspace
        hyprctl eval "hl.config({ general = { layout = 'scrolling' } })"
        ;;
    floating)
        CURRENT_WS=$(hyprctl activeworkspace -j | jq '.id')
        hyprctl clients -j | jq -r ".[] | select(.workspace.id == $CURRENT_WS and .floating == false) | .address" | while read -r addr; do
            hyprctl eval "hl.dispatch(hl.dsp.window.float({ action = 'toggle', window = 'address:$addr' }))"
        done
        ;;
    bigscreen|monocle)
        # Natives Monocle-Layout: genau EIN gekacheltes Fenster ist immer
        # maximiert, und es ist immer das aktuell aktive Fenster - das
        # Layout hört intern auf die window.active-Events des Compositors
        # und synct sich dadurch von selbst mit dem Fokus, unabhängig davon,
        # ob der Fokuswechsel über Tastatur, Maus oder hyprctl ausgelöst
        # wurde.
        #
        # Floating-Fenster und Popups (Dialoge, Rofi, swayosd-OSD,
        # Benachrichtigungen, ...) gehören grundsätzlich NIE zu den "tiled
        # targets" eines Layouts. Monocle rührt sie deshalb gar nicht erst
        # an, sie werden ganz normal schwebend weitergerendert - exakt das
        # gewünschte "außer floating/Popups"-Verhalten, ganz ohne dass wir
        # das hier selbst nachbauen oder einen Hintergrund-Daemon brauchen.
        #
        # Sind alle Fenster des Workspace floating, bleibt der Tiling-
        # Bereich leer (kein Absturz, kein Bug - es gibt schlicht kein
        # gekacheltes Fenster, das maximiert werden könnte).
        clear_fullscreen_current_workspace
        hyprctl eval "hl.config({ general = { layout = 'monocle' } })"
        ;;
esac
