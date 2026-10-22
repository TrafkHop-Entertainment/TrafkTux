-- Devices.lua
--
-- Eingabegeräte: Tastatur-/Touchpad-Verhalten, Cursor-Warp-Verhalten.
-- Die konkrete Touch-/Tablet-zu-Monitor-Zuordnung ist System-/
-- Hardware-spezifisch (andere Geräte-Namen auf jeder Maschine) und
-- liegt deshalb - analog zu UserDisplay.lua - in UserDeviceOutputs.lua,
-- außerhalb von HyprlandConfigs/ (siehe pcall(dofile, ...) unten).

hl.config({
    cursor = {
        no_warps = false,
    },
})

hl.config({
    input = {
        kb_layout = "de",
        follow_mouse = 0,
        float_switch_override_focus = 0,
        sensitivity = 0,
        touchpad = {
            natural_scroll = true,
        },
    },
})

-- Eigenes kb_layout (z.B. von der "Appearance & Language"-Einstellung
-- gesetzt). Lebt bewusst NICHT in HyprlandConfigs/ (also nicht im
-- Repo/Paket) - ein Systemupdate ersetzt nur hyprland.lua +
-- HyprlandConfigs/, diese Datei bleibt unangetastet. MUSS NACH dem
-- obigen hl.config({input=...}) stehen - Hyprland-Config ist additiv,
-- der zweite Aufruf überschreibt hier gezielt nur kb_layout, alle
-- anderen input-Defaults oben bleiben unangetastet. pcall(dofile, ...)
-- statt require(): siehe Begründung in Autostart.lua/Display.lua -
-- sicher, falls die Datei (noch) nicht existiert.
pcall(dofile, os.getenv("HOME") .. "/.config/hypr/HyprlandUserConfigs/UserInput.lua")

-- Bindet Touchscreen(s)/Tablett(s) an den physisch richtigen Monitor.
-- Lebt bewusst NICHT in HyprlandConfigs/ (also nicht im Repo/Paket) -
-- ein Systemupdate ersetzt nur hyprland.lua + HyprlandConfigs/, diese
-- Datei bleibt unangetastet. pcall(dofile, ...) statt require(): siehe
-- Begründung in Autostart.lua/Display.lua - sicher, falls die Datei
-- (noch) nicht existiert. Für Hintergrund/Bugfix-Details siehe die
-- Kommentare direkt in UserDeviceOutputs.lua.
pcall(dofile, os.getenv("HOME") .. "/.config/hypr/HyprlandUserConfigs/UserDeviceOutputs.lua")
