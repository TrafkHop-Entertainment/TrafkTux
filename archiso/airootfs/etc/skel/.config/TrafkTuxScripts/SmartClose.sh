#!/usr/bin/env bash
set -u

TargetAddress="${1:-}"

if [ -z "$TargetAddress" ]; then
    ActiveWindowJson="$(hyprctl -j activewindow 2>/dev/null)"
    TargetAddress="$(printf '%s' "$ActiveWindowJson" | jq -r '.address // empty')"
    TargetClass="$(printf '%s' "$ActiveWindowJson"   | jq -r '.class   // empty')"
else
    TargetClass="$(hyprctl -j clients 2>/dev/null \
        | jq -r --arg a "$TargetAddress" '.[] | select(.address == $a) | .class' \
        | head -n1)"
fi

if [ -z "$TargetAddress" ]; then
    exit 0
fi

# Nicht-gamescope: nur der höfliche close(), wie bisher.
if [ "$TargetClass" != "gamescope" ]; then
    hyprctl dispatch "hl.dsp.window.close({ window = 'address:$TargetAddress' })" >/dev/null 2>&1
    exit 0
fi

hyprctl dispatch "hl.dsp.window.close({ window = 'address:$TargetAddress' })" >/dev/null 2>&1

(
    sleep 2.5
    if hyprctl -j clients 2>/dev/null \
        | jq -e --arg a "$TargetAddress" '.[] | select(.address == $a)' >/dev/null; then
        hyprctl dispatch "hl.dsp.window.kill({ window = 'address:$TargetAddress' })" >/dev/null 2>&1
    fi
) &
disown