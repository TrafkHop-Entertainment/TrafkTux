-- Plugins.lua
--
-- Funktionale (nicht-visuelle) Plugin-Konfiguration. Visuelle Plugins
-- (hyprbars, hyprglass, dynamic_cursors, hyprfocus, hyprexpo-Optik)
-- liegen stattdessen in Looks.lua; Keybinds/Gesten, die Plugins nutzen,
-- liegen in Controls.lua.

hl.permission("/usr/(bin|local/bin)/hyprpm", "plugin", "allow")

-- Touch-Geste: Grundsensitivität/Timing fuer hyprgrass (die eigentlichen
-- Gesten-Binds dazu liegen in Controls.lua)
--
-- HINWEIS (gemergt): frueher gab es hier ZWEI separate
-- hl.config({ plugin = { hyprgrass = {...} } })-Aufrufe mit
-- ueberschneidenden, teils widerspruechlichen Keys (sensitivity
-- wurde zweimal mit unterschiedlichen Werten gesetzt, edge_margin
-- und long_press_delay standen nur je in einem der beiden Bloecke).
-- Jetzt EIN Block mit allen vier Keys, nichts wird mehr
-- unvorhersehbar ueberschrieben/verloren.
-- long_press_delay testweise von 400 auf 700ms erhoeht - falls
-- kurze Taps weiterhin sofort als Rechtsklick durchgehen, hier
-- weiter hochdrehen.
if hl.plugin and hl.plugin.hyprgrass then
    hl.config({
        plugin = {
            hyprgrass = {
                sensitivity = 2.0,
                edge_margin = 165,
                long_press_delay = 700,
            },
        },
    })
else
    hl.exec_cmd(
        "bash -c \"notify-send 'Hyprland' 'hyprgrass nicht geladen - Touch-Gesten deaktiviert (siehe: hyprctl plugin list)' -u critical || true\""
    )
end

-- hypr-kinetic-scroll: kompositor-seitiges kinetisches (inertiales)
-- Touchpad-Scrollen, https://github.com/savonovv/hypr-kinetic-scroll
-- Einmalig manuell einrichten (macht die Lua-Config nicht selbst):
--   hyprpm add https://github.com/savonovv/hypr-kinetic-scroll
--   hyprpm update
--   hyprpm enable hypr-kinetic-scroll
if hl.plugin and hl.plugin.kinetic_scroll then
    hl.config({
        plugin = {
            kinetic_scroll = {
                enabled = 1,
                decel = 0.92,
                min_velocity = 0.5,
                interval_ms = 16,
                delta_multiplier = 1.25,
                disable_in_browser = 1,
                stop_on_target_change = 1,
                debug = 0,
                stop_on_click = 0,
                stop_on_focus = 0,
            },
        },
    })

    -- Beispiel fuer Per-App-Regeln ueber die offizielle Lua-API
    -- (statt disabled_classes im INI-Stil):
    -- hl.plugin.kinetic_scroll.disable("org.telegram.desktop")
    -- hl.plugin.kinetic_scroll.disable("steam")
else
    hl.exec_cmd(
        "bash -c \"notify-send 'Hyprland' 'hypr-kinetic-scroll nicht geladen (siehe: hyprctl plugin list)' -u critical || true\""
    )
end
