#!/bin/bash
# Click handler for the hyprland/workspaces workspace-taskbar icons.
# Called by waybar as: taskbar-click.sh {address} {button}
#
# button values follow GdkEventButton.button: 1 = left, 2 = middle, 3 = right
# https://api.gtkd.org/gdk.c.types.GdkEventButton.button.html

address="$1"
button="$2"

case "$button" in
    1)
        # Left click: focus this window (switches workspace if needed)
        hyprctl dispatch "hl.dsp.focus({window='address:$address'})"
        ;;
    2)
        # Middle click: close this window
        hyprctl dispatch "hl.dsp.window.close({window='address:$address'})"
        ;;
    3)
        # Right click: minimize this window (send to special:minimized).
        # hyprland-minimizer (bound to SUPER+ALT+tab in hyprland.lua) acts on
        # the focused window, so we focus the clicked one first, then fire it.
        hyprctl dispatch "hl.dsp.focus({window='address:$address'})"
        hyprctl dispatch "hl.dsp.exec_cmd(\"hyprland-minimizer\")"
        ;;
esac
