-- 52-soundcenter-no-suspend-bluetooth.lua — für WirePlumber < 0.5 (Lua-Config).
--
-- Ergänzt 51-soundcenter-no-suspend.lua, die NUR ALSA-Sinks abdeckt
-- (siehe deren eigener Kommentar). Bluetooth läuft über einen komplett
-- separaten Regelsatz - bluez_monitor statt alsa_monitor - und war
-- bisher völlig ungedeckt.
--
-- Behebt genau das nachgewiesene Symptom: WirePlumber/BlueZ suspendiert
-- den A2DP-Transport nach ein paar Sekunden Stille; das Wiederaufwecken
-- danach dauert spürbar (bekanntes, dokumentiertes Verhalten, siehe z.B.
-- github.com/blueman-project/blueman/discussions/3095 - exakt dieses
-- Symptom: kurze Sounds nach einer Stille-Pause kommen verspätet, durch-
-- gehender Ton wie Spielmusik hält die Verbindung dagegen wach und ist
-- deshalb nicht betroffen - passt zu allen Beobachtungen von eben).
--
-- Ehrlicher Hinweis aus genau dieser Diskussion: bei manchen Bluetooth-
-- Adapter/Firmware-Kombinationen (dort: AMD-Adapter) hat selbst diese
-- Kombination die Senke nicht zuverlässig vom Suspend abgehalten - ist
-- der Standard-, gut dokumentierte erste Versuch, aber keine Garantie
-- auf 100% bei jeder Hardware.
--
-- Installieren nach: ~/.config/wireplumber/main.lua.d/
-- Danach: systemctl --user restart wireplumber
-- (ggf. das Headset einmal neu verbinden/koppeln, damit die neuen
-- Node-Properties für die bestehende Verbindung übernommen werden)

-- NUR bluez_output (Wiedergabe) - bewusst NICHT bluez_input (Mikro):
-- Beides gleichzeitig am Einschlafen zu hindern kann WirePlumber dazu
-- bringen, automatisch auf das bidirektionale HSP/HFP-Profil
-- umzuschalten (für Freisprech/Mikro gedacht, deutlich komprimierter/
-- mono statt A2DP) statt beim hochwertigeren reinen A2DP zu bleiben -
-- genau das durch dieses Fixes ausgeloest, sichtbar an "Qualität
-- miserabel" nach der ersten Version dieser Datei. Nur die Wiedergabe-
-- Senke betreffen behebt das.
bluez_monitor.rules = bluez_monitor.rules or {}

table.insert(bluez_monitor.rules, {
  matches = {
    {
      { "node.name", "matches", "bluez_output.*" },
    },
  },
  apply_properties = {
    ["session.suspend-timeout-seconds"] = 0,
    ["node.pause-on-idle"] = false,
    ["node.suspend-on-idle"] = false,
  },
})
