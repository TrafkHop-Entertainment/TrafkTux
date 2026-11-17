#!/usr/bin/env bash
# Wiimote verbinden (ohne pair): 1+2 druecken (LEDs blinken), dann dieses Skript starten.
# Funktioniert auch fuer ein ZWEITES Wiimote: bereits verbundene werden uebersprungen.
# Gibt 0 zurueck wenn verbunden. Optional: Timeout in Sekunden als $1 (Standard 25).
T="${1:-25}"
command -v bluetoothctl >/dev/null || { echo "bluetoothctl fehlt"; exit 2; }
bluetoothctl power on >/dev/null 2>&1
# --timeout haelt den Client (und damit die Suche) am Leben; ohne wuerde die Suche sofort enden
bluetoothctl --timeout "$T" scan on >/dev/null 2>&1 &
SCANPID=$!
trap 'kill $SCANPID 2>/dev/null' EXIT
end=$((SECONDS + T))
declare -A tried
while [ $SECONDS -lt $end ]; do
    for mac in $(bluetoothctl devices | awk '/Nintendo RVL-(CNT|WBC)/ {print $2}'); do
        info=$(bluetoothctl info "$mac" 2>/dev/null)
        echo "$info" | grep -q "Connected: yes" && continue          # schon verbunden (anderes Wiimote)
        # nur Geraete, die gerade gesehen werden (RSSI) - veraltete Cache-Eintraege ueberspringen
        echo "$info" | grep -q "RSSI:" || continue
        bluetoothctl trust "$mac" >/dev/null 2>&1
        if timeout 10 bluetoothctl connect "$mac" 2>&1 | grep -q "Connection successful"; then
            echo "verbunden: $mac"; exit 0
        fi
    done
    sleep 1
done
echo "Wiimote nicht gefunden - 1+2 gedrueckt halten (nicht nur druecken) und nochmal versuchen"; exit 1
