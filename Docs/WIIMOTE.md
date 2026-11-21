# Wiimote in TrafkPad (v4)

Verbinden: 1+2 druecken (LEDs blinken), dann Settings -> Devices -> Wiimote -> Connect oder `~/.config/TrafkTuxPad/wiimote-connect.sh`. Nach jedem Login sucht `wiimote-autoconnect.sh` (aus Autostart.lua) 5 Minuten lang mit Notification; abschaltbar mit `wii_autoconnect = false` bzw. im Autostart-Widget.
Voraussetzung: `/etc/bluetooth/input.conf` mit `ClassicBondedOnly=false` (liegt im archiso, `airootfs/etc/bluetooth/input.conf`), danach `sudo systemctl restart bluetooth`.

Belegung (Basis / mit Home):
- A = Linksklick, B (Zielknopf) = Rechtsklick, 1 = Space, 2 = X, + = Enter, - = Esc, Steuerkreuz = Pfeile
- Home = Home-Ebene (wie am Pad)
- Nunchuk: Stick = WASD (bzw. Maus bei mouse_stick=left), Z = Q, C = E
- IR-Zeiger: absolute Maus aus der Sensorleiste (Mitte der zwei Punkte, geglaettet)
- Toggle an/aus: + und - gleichzeitig 1 s halten (Standard, im Widget unter Combos aenderbar; Keys wii_toggle_combo, toggle_hold_ms)
- Zeigermodus wechseln: 1 und 2 gleichzeitig 0,6 s halten (Standard, Combos; Keys wii_mode_combo, wii_mode_hold_ms)
- Die Wiimote hat im Mapping-Editor eine eigene Belegung (Layout-Schluessel `wbase.` / `whome.`, interne Namen: A-Taste = L2, B = R2, 1 = A, 2 = B, + = START, - = SELECT, Z = L1, C = R1)

Zeiger kalibrieren: Settings -> Controller -> Wiimote -> Calibrate (oder `TrafkPad --ctl "wii-cal start"`), dann auf die obere linke Bildschirmecke zeigen + A, danach untere rechte Ecke + A. `wii-cal reset` = Standard.

Drehung: der Rollwinkel der Wiimote (Winkel zwischen den zwei IR-Punkten) wird abgezogen, damit Zeigen nach oben bei -90 Grad Drehung weiter nach oben geht (`wii_roll = true`). Bei genau +-90 Grad beim ersten Sichtkontakt ist die Richtung nicht eindeutig.

Config-Keys (TrafkPad.conf): wii_roll, wii_autoconnect, wii_pointer, wii_flip_x, wii_flip_y (Standard false), wii_nunchuk_flip_y (true/false)

Zeigermodi (fuer Spiele mit Mausfang):
- abs = absoluter Zeiger (Desktop), rel = Delta wie eine Maus, joy = Abstand zur Bildschirmmitte = Geschwindigkeit
- Umschalten: Tastenkombi (Standard 1 + 2 halten), Widget (Switch now) oder `TrafkPad --ctl "wii-mode toggle"` (auch abs/rel/joy/auto). Die Kombi wechselt zwischen `wii_mode` (normal) und `wii_alt_mode` (Spielmodus); jede Aenderung in den Einstellungen setzt auf `wii_mode` zurueck.
- Keine automatische Erkennung mehr (`wii_apps` entfaellt).
- Keys: wii_mode, wii_alt_mode (rel|joy), wii_rel_scale

Mapping-Editor / Layouts: siehe README (Controller). Layout-Datei: `base.A = space`, `home.R1 = ctrl+shift+t`, `base.DU = scroll:up`, `stick.home = scroll`.

Mapping- oder Combos-Tab offen = alle Pad-/Wiimote-Eingaben gesperrt und nur angezeigt (Socket-Befehl `padmon`, der Editor meldet sich alle 90 ms, sonst gilt nach 0,8 s wieder alles normal). `TrafkPad --ctl version` zeigt den Protokollstand (muss 4 sein).
