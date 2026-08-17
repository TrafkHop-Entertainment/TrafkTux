#!/bin/bash
pinned=$(hyprctl activewindow -j | jq -r '.pinned')

if [ "$pinned" = "true" ]; then
    hyprctl eval "hl.dispatch(hl.dsp.window.pin())"
    hyprctl eval "hl.dispatch(hl.dsp.window.float({ action = 'toggle' }))"
else
    floating=$(hyprctl activewindow -j | jq -r '.floating')
    if [ "$floating" = "false" ]; then
        hyprctl eval "hl.dispatch(hl.dsp.window.float({ action = 'toggle' }))"
    fi
    hyprctl eval "hl.dispatch(hl.dsp.window.pin())"
fi
