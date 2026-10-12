--[[
AppWallpaper.lua — hyprwinwrap-Toggle (Pictures vs. App-Fenster als
Hintergrund), siehe https://github.com/gen3vra/hyprwinwrap

EINBINDUNG: wird am Ende von HyprlandConfigs/Looks.lua per
    require("HyprlandConfigs.AppWallpaper")
geladen (visuell -> Looks-Kategorie). Alt, als Referenz: frueher per
    pcall(dofile, os.getenv("HOME") .. "/.config/hypr/AppWallpaper.lua")
ganz am Ende der monolithischen hyprland.lua eingebunden.

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

KORREKTUR (siehe Chat): appwallpaper_state.lua liegt jetzt in
HyprlandUserConfigs/ statt direkt in hypr/ - dieselbe Konvention wie
UserDisplay.lua (siehe Display.lua): reines Laufzeit-/Nutzer-
spezifisches Zeug gehört dort rein, damit ein Distro-/Repo-Update die
Datei nie anfasst/überschreibt. WidgetsDaemon.py schreibt entsprechend
mitgezogen nach demselben neuen Pfad (siehe APPWALLPAPER_STATE_LUA
dort).
--]]

local ok, state = pcall(dofile, os.getenv("HOME") .. "/.config/hypr/HyprlandUserConfigs/appwallpaper_state.lua")

if not ok or type(state) ~= "table" then
    state = { enabled = false, class = "", exec = "", monitor = "" }
end

if hl.plugin and hl.plugin.hyprwinwrap ~= nil then
    if state.enabled and state.class and state.class ~= "" then
        -- KORREKTUR (siehe Chat): die window_rule, die hier frueher
        -- stand, hatte DREI Teile - float, size, monitor. size und
        -- monitor bringen nachweislich nichts: hyprwinwrap greift das
        -- Fenster in seinem eigenen commit-Listener, BEVOR Hyprlands
        -- normaler window_rule-Layout-Pfad fuer dieses (durch
        -- hyprwinwrap sofort versteckte/aus dem normalen Rendering
        -- genommene) Fenster je zum Zug kommt (siehe Kommentar bei
        -- _trafkverse_exec_cmd() in WidgetsDaemon.py, wo das fuer die
        -- Groesse bereits per --width/--height-Flag an die App selbst
        -- umgangen wurde; der Zielmonitor wird jetzt per
        -- hl.dsp.focus({monitor=...}) VOR dem App-Start erzwungen,
        -- siehe unten).
        --
        -- float=true dagegen IST weiterhin noetig und wurde faelschlich
        -- mitentfernt: TrafkVerseScreensaver (SDL_WINDOW_RESIZABLE, kein
        -- eigener Floating-Hint) wird von Hyprlands Tiling-Layout beim
        -- ALLERERSTEN Buffer-Commit sonst wie ein normales tiled
        -- Fenster behandelt und bekommt dabei nur den gerade freien
        -- Bruchteil des Bildschirms (z.B. ~1/3 bei 2 bereits offenen
        -- Fenstern) - hyprwinwraps eigener float+resize-Zwang feuert
        -- laut dessen README erst "ein paar ms nach dem Oeffnen" und
        -- kommt damit fuer diesen ersten (zu klein committeten) Buffer
        -- offenbar zu spaet. VLC bekommt ueblicherweise schon von sich
        -- aus (eigene Fenstertyp-Hints bzw. eine gaengige eigene
        -- windowrule=float,class:vlc) den Floating-Status und tiled
        -- deshalb gar nicht erst - daher fiel der Bug dort nicht auf.
        --
        -- state.class ist seit dem --wallpaper-Flag-Fix (siehe Chat)
        -- eine EIGENE Klasse ("TrafkVerseScreensaverWallpaper" statt
        -- der normalen "TrafkVerseScreensaver"), die TrafkVerseScreensaver
        -- nur dann setzt, wenn WidgetsDaemon.py es mit --wallpaper
        -- startet - ein ganz normaler/manueller Start der App bleibt
        -- dadurch von dieser window_rule/hyprwinwrap-Registrierung
        -- unberührt.
        hl.window_rule({
            name = "appwallpaper-float",
            match = { class = state.class },
            float = true,
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
        -- Zielmonitor zuerst fokussieren (siehe Kommentar weiter oben,
        -- "KORREKTUR") - sonst oeffnet sich die App auf dem beim Login
        -- zufaellig fokussierten Monitor statt auf state.monitor, und
        -- hyprwinwraps size_x/size_y=100 decken dann zwar 100% EINES
        -- Monitors ab, aber nicht unbedingt den gewuenschten.
        if state.monitor and state.monitor ~= "" then
            -- KORREKTUR (siehe Chat): "hyprctl dispatch focusmonitor
            -- <name>" ist die alte, positionale hyprlang-Syntax und
            -- schlaegt seit Hyprland 0.55 fehl (hyprctl dispatch nimmt
            -- nur noch einen hl.dsp.*-Lua-Ausdruck entgegen). Da wir
            -- hier schon in der Lua-Config sind, direkt dispatchen -
            -- kein hyprctl/Shell-Umweg noetig.
            hl.dispatch(hl.dsp.focus({ monitor = state.monitor }))
        end
        hl.exec_cmd("bash -c \"" .. state.exec:gsub('"', '\\"') .. "\" &")
        -- KORREKTUR (siehe Chat): .resize/.move per Live-Dispatch
        -- bringen nachweislich nichts (hyprwm/Hyprland#16446). Fuer
        -- TrafkVerseScreensaver liegt der Fix jetzt client-seitig in
        -- TrafkVerseScreensaver.c (SDL_SetWindowMinimumSize/
        -- MaximumSize). Fuer Apps ohne eigene Groessen-Vorgabe (z.B.
        -- VLC) nimmt hl.dsp.window.center() nachweislich einen ANDEREN,
        -- funktionierenden Codepfad (per Nutzer-Test bestaetigt) -
        -- WICHTIG: der Window-Selector braucht das "class:"-Praefix,
        -- sonst "No floating window found". 1s Verzoegerung per
        -- hl.timer(), damit die App zuerst ihre eigene Groessenanpassung
        -- abgeschlossen hat, bevor zentriert wird.
        if state.class and state.class ~= "" then
            local klass = state.class
            hl.timer(function()
                hl.dispatch(hl.dsp.window.center({ window = "class:" .. klass }))
            end, { timeout = 1000, type = "oneshot" })
        end
    end
end)
