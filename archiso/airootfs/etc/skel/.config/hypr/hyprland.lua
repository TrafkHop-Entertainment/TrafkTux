-- Hyprland-Konfiguration (Lua API)
--
-- Aufgeteilt in HyprlandConfigs/, jede Datei per require() geladen. Jede
-- require()-Datei läuft laut Hyprland-Doku in einem eigenen Scope - Fehler
-- in einer Datei stoppen also nicht die anderen. Deshalb gibt es bewusst
-- KEINE geteilten Variablen zwischen den Dateien (z.B. mainMod lebt nur in
-- Controls.lua) - jede Datei ist in sich abgeschlossen.
--
-- Reihenfolge ist weitgehend egal (jede Datei ist unabhängig), bis auf
-- AppWallpaper/DeviceOutputs: die werden - wie im alten Monolithen, wo sie
-- per dofile() ganz am Ende standen - bewusst zuletzt geladen (siehe unten
-- in Looks.lua bzw. Devices.lua).

require("HyprlandConfigs.Looks")
require("HyprlandConfigs.Display")
require("HyprlandConfigs.Layout")
require("HyprlandConfigs.Devices")
require("HyprlandConfigs.Controls")
require("HyprlandConfigs.Plugins")
require("HyprlandConfigs.Autostart")
