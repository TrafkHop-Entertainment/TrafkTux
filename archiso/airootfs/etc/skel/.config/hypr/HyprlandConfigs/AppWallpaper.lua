--[[
AppWallpaper.lua — hyprwinwrap-Toggle (Pictures vs. App-Fenster als
Hintergrund), siehe https://github.com/gen3vra/hyprwinwrap

EINBINDUNG in deine echte hyprland.lua:
    pcall(dofile, os.getenv("HOME") .. "/.config/hypr/AppWallpaper.lua")

KORREKTUR (siehe Chat): die erste Version dieser Datei hat
`hl.config({ plugin = { hyprwinwrap = { class = ... } } })` benutzt -
das war schlicht erfunden/falsch, keine echte hyprwinwrap-API. Laut
README ist die richtige (aktuelle, nicht-deprecated) API:

    hl.plugin.hyprwinwrap.window({ class, title, layer, pos_x, pos_y,
                                    size_x, size_y })

Kein Live-hyprctl-keyword-Weg vorhanden - das Fenster wird nur über
diese Lua-Config registriert. Ein Live-Toggle (während Hyprland schon
läuft) braucht daher einen `hyprctl reload`, der dieses Skript neu
ausführt und window() neu/anders aufruft (siehe
_appwallpaper_apply() in WidgetsDaemon.py).

`title` wird bewusst NICHT gesetzt - nur nach `class` gematcht, weil
der Fenstertitel (z.B. bei VLC der abgespielte Dateiname) sich ändern
kann und sonst kein Match mehr stattfände.
--]]

local ok, state = pcall(dofile, os.getenv("HOME") .. "/.config/hypr/appwallpaper_state.lua")

if not ok or type(state) ~= "table" then
    state = { enabled = false, class = "", exec = "", monitor = "" }
end

if hl.plugin and hl.plugin.hyprwinwrap ~= nil then
    if state.enabled and state.class and state.class ~= "" then
        -- hyprwinwrap selbst hat kein Monitor-Feld (siehe Chat) - die
        -- Fensterklasse wird stattdessen per normaler Hyprland-
        -- window_rule auf den gewünschten Monitor gezwungen, BEVOR
        -- hyprwinwrap sie greift. Gleicher Name bei jedem Reload ->
        -- aktualisiert die bestehende Regel statt sie zu duplizieren.
        -- Die gewrappte App bekommt KEINE Start-Parameter für ihre
        -- Auflösung (nicht jede App hat sowas - TrafkVerseScreensaver
        -- z.B. startet fix bei 960x540, ist aber normal resize-fähig).
        -- Deshalb zwingen wir die Fenstergröße selbst per window_rule
        -- auf Monitorgröße, BEVOR hyprwinwrap das Fenster greift -
        -- "size" braucht laut Hyprland-Doku ein floatendes Fenster,
        -- daher float=true mit dazu. monitor_w/monitor_h sind dynamische
        -- Hyprland-Ausdrücke (siehe Window-Rules-Doku) - kein hart
        -- codiertes 1920x1080 o.ä., funktioniert also für jede
        -- Monitor-Auflösung.
        hl.window_rule({
            name = "appwallpaper-monitor",
            match = { class = state.class },
            monitor = (state.monitor and state.monitor ~= "") and state.monitor or nil,
            float = true,
            size = { "monitor_w", "monitor_h" },
            move = { "0", "0" },
        })
        hl.plugin.hyprwinwrap.window({
            class = state.class,
            layer = 0,
            pos_x = 0,
            pos_y = 0,
            size_x = 100,
            size_y = 100,
        })
    end
else
    if state.enabled then
        hl.exec_cmd(
            "bash -c \"notify-send 'Hyprland' 'AppWallpaper ist aktiv, aber das hyprwinwrap-Plugin ist nicht geladen (siehe: hyprctl plugin list).' -u critical || true\""
        )
    end
end

-- Die App selbst nur beim ECHTEN Hyprland-Start automatisch starten
-- (nicht bei jedem `hyprctl reload`, sonst würde sie bei jedem
-- Live-Toggle neu gestartet werden). Beim Live-Toggle selbst startet
-- WidgetsDaemon.py den Prozess direkt.
hl.on("hyprland.start", function()
    if state.enabled and state.exec and state.exec ~= "" then
        hl.exec_cmd("bash -c \"" .. state.exec:gsub('"', '\\"') .. "\" &")
    end
end)
