# Umstellung auf Daemon + Events

## 1. Dateien platzieren

```bash
mkdir -p ~/.config/waybar/scripts
cp widgets_daemon.py widgets_client.py waybar_autohide.py ~/.config/waybar/scripts/
chmod +x ~/.config/waybar/scripts/*.py
```

## 2. Alte Auto-Starts entfernen

In deiner Hyprland-Config (`~/.config/hypr/hyprland.conf`) alle Zeilen
löschen/auskommentieren, die `waybar-autohide.sh` oder `widgets.py`
direkt starten (`exec-once = ...`). Die Steuerung läuft jetzt über
systemd, nicht mehr über Hyprland-`exec-once`.

## 3. systemd-Units installieren

```bash
mkdir -p ~/.config/systemd/user
cp wb-daemon.service wb-autohide.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now wb-daemon.service
systemctl --user enable --now wb-autohide.service
```

Beide starten damit automatisch bei jedem Login und laufen dauerhaft
im Hintergrund (das ist Absicht — genau das eliminiert den
Prozessstart-Overhead).

Status/Logs prüfen:
```bash
systemctl --user status wb-daemon.service
journalctl --user -u wb-daemon.service -f
tail -f /tmp/waybar-autohide.log
```

## 4. Waybar-Config anpassen

Überall, wo bisher z.B. so etwas stand:

```jsonc
"on-click": "python3 ~/.config/waybar/scripts/widgets.py --widget volume"
```

jetzt stattdessen den Client aufrufen:

```jsonc
"on-click": "python3 ~/.config/waybar/scripts/widgets_client.py volume"
```

Für jeden Widget-Typ entsprechend (`network`, `bluetooth`,
`brightness`, `akku`, `clock`).

**Noch etwas schneller**, falls `socat` oder `ncat` installiert ist
(spart den Python-Interpreter-Start des Clients komplett, ca. 10-15ms
weniger):

```jsonc
"on-click": "socat - UNIX-CONNECT:/tmp/wb-daemon.sock <<< volume"
```

Waybar danach neu laden (`killall -SIGUSR2 waybar` oder Waybar neu
starten).

## 5. Testen

```bash
# Daemon läuft?
ls -l /tmp/wb-daemon.sock

# Latenz einzeln messen:
time python3 ~/.config/waybar/scripts/widgets_client.py volume
```

Der `time`-Wert hier ist realistisch nah an dem, was du beim Klick in
Waybar spürst — bei einem warmgelaufenen Daemon sollte das im
niedrigen zweistelligen ms-Bereich liegen.

## Was sich inhaltlich NICHT geändert hat

- Alle Widget-Layouts, CSS, Farben, Verhalten von
  volume/network/bluetooth/brightness/akku/clock: unverändert, 1:1
  aus deiner v5 übernommen.
- Autohide-Schwellwerte (`TRIG_PX=5`, `HIDE_PX=65`): unverändert
  übernommen, jetzt aber am Kopf von `waybar_autohide.py` als
  benannte Konstanten statt Bash-Variablen.

## Bekannte Stolpersteine

- **`GtkLayerShell` fehlt**: Falls `waybar_autohide.py` beim Start
  loggt, dass GtkLayerShell nicht verfügbar ist, fehlt das
  `gir1.2-gtklayershell-0.1`-Paket (bzw. Äquivalent deiner
  Distro) — ohne das lässt sich die Trigger-Zone nicht zuverlässig
  am Bildschirmrand verankern.
- **Autohide-Zone vs. Waybar-Layer**: Ich habe die Trigger-Zone auf
  `Layer.BOTTOM` gesetzt (unter Waybar). Falls deine Waybar-Config
  selbst auf einem niedrigeren Layer läuft als `TOP`/`OVERLAY`, kann
  es zu Konflikten kommen — dann in `waybar_autohide.py` den Layer
  anpassen (siehe Kommentar in `_make_window`).
- **Mehrere Monitore**: `GtkLayerShell` wählt ohne explizite
  `set_monitor()`-Angabe meist den fokussierten Monitor. Falls du
  die Trigger-Zone auf einen bestimmten Monitor pinnen willst, sag
  Bescheid, das ist ein kleiner Zusatz.
