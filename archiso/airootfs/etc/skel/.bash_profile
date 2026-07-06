export XCURSOR_THEME="TrafkTuxCursor"
export XCURSOR_SIZE="35"

if [ -z "$DISPLAY" ] && [ "$XDG_VTNR" -eq 1 ]; then
    exec Hyprland
fi
