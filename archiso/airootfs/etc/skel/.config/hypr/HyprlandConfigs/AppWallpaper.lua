--[[
AppWallpaper.lua — hyprwinwrap-Toggle (Pictures vs. App-Fenster als
Hintergrund), siehe https://github.com/gen3vra/hyprwinwrap

EINBINDUNG: wird am Ende von HyprlandConfigs/Looks.lua per
    require("HyprlandConfigs.AppWallpaper")
geladen (visuell -> Looks-Kategorie).

appwallpaper_state.lua liegt unter HyprlandUserConfigs/ (wie
UserDisplay.lua) - reines Laufzeit-/Nutzer-spezifisches Zeug, damit ein
Distro-/Repo-Update die Datei nie anfasst/überschreibt.
WidgetsDaemon.py schreibt entsprechend dorthin (siehe
APPWALLPAPER_STATE_LUA dort).

KORREKTUR (Punkt 7, siehe Chat): state ist jetzt eine LISTE von
Eintraegen ("entries") statt eines einzelnen {enabled,class,exec,
monitor}-Zustands - mehrere Apps koennen gleichzeitig als Hintergrund
laufen (z.B. eine pro Monitor, via TrafkVerseWallpaper.c's
--class-suffix bzw. VLCs --meta-title). appwallpaper_state.lua wird
von WidgetsDaemon.py GENERIERT - Python liest diese Datei nie zurueck,
sie ist reiner Export.

`title` wird nur gesetzt, wenn ein Eintrag es explizit braucht (VLC-
Mehrfachinstanzen, siehe _vlc_exec_cmd()-Kommentar in
WidgetsDaemon.py) - sonst leer, nur nach `class` gematcht.
--]]

local ok, state = pcall(dofile, os.getenv("HOME") .. "/.config/hypr/HyprlandUserConfigs/appwallpaper_state.lua")

if not ok or type(state) ~= "table" or type(state.entries) ~= "table" then
    state = { entries = {} }
end

local hyprwinwrap_ok = hl.plugin and hl.plugin.hyprwinwrap ~= nil

if hyprwinwrap_ok then
    -- KORREKTUR (siehe Chat, per strings-Analyse von hyprwinwrap.so
    -- v1.3 bestaetigt): pos_x/pos_y/size_x/size_y sind seit v1.3 KEIN
    -- Teil des .window()-Aufrufs mehr, sondern eine separate, GLOBALE
    -- Config (plugin:hyprwinwrap:pos_x/pos_y/size_x/size_y), die fuer
    -- ALLE registrierten Fenster gleichermassen gilt - genau das
    -- wollen wir hier ohnehin (jeder Eintrag soll 0,0,100%,100% sein).
    -- Als Tabellenfeld bei .window() uebergeben wurden diese Werte
    -- bisher als unbekannte Felder stillschweigend ignoriert, wodurch
    -- gar nichts resized/versteckt/gepinnt wurde.
    hl.config({
        plugin = {
            hyprwinwrap = {
                pos_x = 0,
                pos_y = 0,
                size_x = 100,
                size_y = 100,
            },
        },
    })
    for _, entry in ipairs(state.entries) do
        if entry.class and entry.class ~= "" then
            -- float=true noetig (siehe Chat): sonst behandelt Hyprlands
            -- Tiling-Layout ein frisch geoeffnetes Fenster ohne eigenen
            -- Floating-Hint beim allerersten Commit wie ein normales
            -- tiled Fenster und gibt ihm nur einen Bruchteil des
            -- Bildschirms, bevor hyprwinwraps eigener (verzoegerter)
            -- float-Zwang zum Zug kommt.
            hl.window_rule({
                name = "appwallpaper-float-" .. entry.id,
                match = { class = entry.class },
                float = true,
            })
            -- .window() verlangt laut hyprwinwrap.so-Fehlermeldung
            -- ("requires a 'class' or 'title' field") in v1.3 nur noch
            -- class/title (+ layer fuer die Stapelreihenfolge bei
            -- mehreren gleichzeitigen Fenstern) - pos_x/size_x etc.
            -- kommen jetzt aus hl.config() oben.
            local winCfg = {
                class = entry.class,
                layer = 0,
            }
            if entry.title and entry.title ~= "" then
                winCfg.title = entry.title
            end
            hl.plugin.hyprwinwrap.window(winCfg)
        end
    end
else
    if #state.entries > 0 then
        hl.exec_cmd(
            "bash -c \"notify-send 'Hyprland' 'AppWallpaper ist aktiv, aber das hyprwinwrap-Plugin ist nicht geladen (siehe: hyprctl plugin list).' -u critical || true\""
        )
    end
end

-- Alle Eintraege zusaetzlich beim ECHTEN Hyprland-Start automatisch
-- starten (nicht bei jedem `hyprctl reload` - sonst wuerden sie bei
-- jedem Live-Toggle neu gestartet; beim Live-Toggle selbst startet
-- WidgetsDaemon.py die Prozesse direkt, siehe _appwallpaper_start_one).
hl.on("hyprland.start", function()
    for _, entry in ipairs(state.entries) do
        if entry.exec and entry.exec ~= "" then
            if entry.monitor and entry.monitor ~= "" then
                -- KORREKTUR (siehe Chat): "hyprctl dispatch focusmonitor
                -- <name>" ist die alte, positionale hyprlang-Syntax und
                -- schlaegt seit Hyprland 0.55 fehl. Direkt dispatchen,
                -- da wir schon in der Lua-Config sind.
                hl.dispatch(hl.dsp.focus({ monitor = entry.monitor }))
            end
            hl.exec_cmd("bash -c \"" .. entry.exec:gsub('"', '\\"') .. "\" &")
            if entry.class and entry.class ~= "" then
                local sel = "class:" .. entry.class
                if entry.title and entry.title ~= "" then
                    sel = sel .. ",title:" .. entry.title
                end
                -- .resize/.move per Live-Dispatch bringen nachweislich
                -- nichts (hyprwm/Hyprland#16446). hl.dsp.window.center()
                -- nimmt einen anderen, funktionierenden Codepfad (per
                -- Test bestaetigt) - WICHTIG: "class:"-Praefix im
                -- Selector ist Pflicht, sonst "No floating window
                -- found". 1s Verzoegerung, damit die App zuerst ihre
                -- eigene Groessenanpassung abgeschlossen hat.
                hl.timer(function()
                    hl.dispatch(hl.dsp.window.center({ window = sel }))
                end, { timeout = 1000, type = "oneshot" })
            end
        end
    end
end)
