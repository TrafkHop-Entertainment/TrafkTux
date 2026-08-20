-- Hyprland-Konfiguration (Lua API)

-- Liest das zuletzt gespeicherte Layout aus dem Cache, Fallback "master"
local function read_saved_layout()
local default = "master"
local path = os.getenv("HOME") .. "/.cache/hypr/layout_switcher_state"
local f = io.open(path, "r")
if not f then return default end
    local content = f:read("*l")
    f:close()
    if content == nil or content == "" then return default end
        return content
        end

        local savedLayout = read_saved_layout()

        hl.monitor({
            output   = "eDP-1",
            mode     = "1920x1200@60",
            position = "0x0",
            scale    = 1.07,
        })

        -- Programme & Befehle
        local terminal       = "xfce4-terminal"
        local fileManager    = "thunar"
        local menu           = "rofi -show drun"
        local openwindows    = "rofi -show window"
        -- Rofi Script Mode: EIN dauerhaftes Rofi-Fenster statt Neustart pro Klick.
        -- bubble-menu.py wird von Rofi selbst bei jeder Auswahl erneut aufgerufen
        -- (liest Info/State über ROFI_INFO/ROFI_DATA), kein Fenster-Schließen mehr
        -- beim Blättern -> kein hyprfocus-Trigger mehr, kein Daemon/FIFO mehr nötig.
        -- WICHTIG: -show-icons, -no-custom, -x11 und alle -kb-* Bindungen müssen
        -- HIER auf der echten rofi-Kommandozeile stehen (nicht mehr in Python),
        -- da Rofi jetzt direkt von Hyprland gestartet wird statt von bubble-menu.py.
        -- $HOME statt ~, da ~ innerhalb der verschachtelten -modi-Anführungszeichen
        -- von Bash nicht expandiert wird, $HOME aber schon.
        --
        -- Zentrierungs-Fix (-monitor $(...)): Rofi kennt im nativen Wayland-Modus
        -- seinen Output erst NACHDEM die erste Layer-Surface gemappt wurde,
        -- "location: center" wird aber schon vorher berechnet -> der allererste
        -- Start eines neuen Rofi-Prozesses landet potenziell auf dem falschen
        -- Monitor (egal ob per Hyprland-Bind oder Waybar-Klick gestartet).
        -- Statt Rofis eigener (racy) Output-Erkennung zu vertrauen, wird der
        -- fokussierte Monitor per hyprctl+jq VOR dem Start ermittelt und Rofi
        -- explizit mitgegeben - direkt inline, kein separates Skript nötig.
        local launcher_cmd   = "rofi -show bubble -modi \"bubble:$HOME/.config/rofi/RofiTrafkBubbleMenus --menu AppLauncher --x11\" -theme $HOME/.config/rofi/AppLauncher/theme.rasi -show-icons -no-custom -x11 -monitor \"$(hyprctl monitors -j | jq -r '.[] | select(.focused) | .name')\" -kb-row-up 'Up,Control+p,w' -kb-row-down 'Down,Control+n,s' -kb-row-left 'Control+Page_Up,a' -kb-row-right 'Control+Page_Down,d' -kb-accept-entry 'Control+j,Control+m,Return,KP_Enter,space,less' -kb-custom-1 'q' -kb-custom-2 'e' -kb-custom-3 'x'"
        local powermenu_cmd  = "rofi -show bubble -modi \"bubble:$HOME/.config/rofi/RofiTrafkBubbleMenus --menu PowerMenu --x11\" -theme $HOME/.config/rofi/PowerMenu/theme.rasi -show-icons -no-custom -x11 -monitor \"$(hyprctl monitors -j | jq -r '.[] | select(.focused) | .name')\" -kb-row-up 'Up,Control+p,w' -kb-row-down 'Down,Control+n,s' -kb-row-left 'Control+Page_Up,a' -kb-row-right 'Control+Page_Down,d' -kb-accept-entry 'Control+j,Control+m,Return,KP_Enter,space,less' -kb-custom-1 'q' -kb-custom-2 'e' -kb-custom-3 'x'"

        -- Cursor-Umgebungsvariablen
        hl.env("XCURSOR_THEME", "TrafkTuxCursorLegacy")
        hl.env("XCURSOR_SIZE", "35")
        hl.env("HYPRCURSOR_THEME", "TrafkTuxCursor")
        hl.env("HYPRCURSOR_SIZE", "35")
        hl.env("QT_CURSOR_SIZE", "35")

        hl.env("QT_QPA_PLATFORMTHEME", "qt6ct")

        -- Autostart
        hl.on("hyprland.start", function()
        hl.exec_cmd("bash -c 'hyprctl setcursor TrafkTuxCursor 35' &")
        hl.exec_cmd("gsettings set org.gnome.desktop.interface cursor-theme 'TrafkTuxCursorLegacy'")
        hl.exec_cmd("gsettings set org.gnome.desktop.interface cursor-size 35")
        hl.exec_cmd("bash -c 'hyprctl plugin list | grep -q hyprbars || (hyprpm reload -n && sleep 1 && hyprctl reload)'")
        hl.exec_cmd("xfdesktop")
        hl.exec_cmd("bash ~/.config/hypr/Wallpapers.sh")
        hl.exec_cmd("killall waybar; waybar")
        hl.exec_cmd("dunst")
        hl.exec_cmd("hypridle")
        hl.exec_cmd("/usr/lib/polkit-kde-authentication-agent-1")
        hl.exec_cmd("nm-applet --indicator")
        hl.exec_cmd("blueman-applet")
        hl.exec_cmd("wl-paste --watch cliphist store")
        hl.exec_cmd("wl-clip-persist --clipboard regular")
        hl.exec_cmd("swayosd-server")
        hl.exec_cmd("systemctl --user start WidgetsDaemon.service WaybarAutohideDaemon.service FocusFixDaemon.service ScreenRotationDaemon.service SoundCenter.service")
        hl.exec_cmd("cp ~/.config/rofi/assets/bubble-normal.png /tmp/bubble-normal.png")
        hl.exec_cmd("cp ~/.config/rofi/assets/bubble-selected.png /tmp/bubble-selected.png")
        -- Kein Daemon-Autostart mehr nötig: launcher_cmd/powermenu_cmd starten
        -- Rofi im Script-Mode jetzt bei jedem Aufruf direkt selbst.
        end)

        -- Systemsounds: Compositor-Ebene (Fenster öffnen/schließen, Workspace-
        -- Wechsel). SoundCenter.sh prüft selbst den globalen An/Aus-Zustand,
        -- hier wird also blind gefeuert. "&" wichtig, sonst blockiert
        -- exec_cmd auf pw-play/paplay. Gilt NICHT für Klicks innerhalb von
        -- Rofi/Waybar/Widgets - die sieht Hyprland gar nicht.
        local SOUNDCTL = "bash $HOME/.config/hypr/SoundCenter.sh"

        hl.on("window.open_early", function()
            hl.exec_cmd(SOUNDCTL .. " Open &")
        end)

        hl.on("window.close", function()
            hl.exec_cmd(SOUNDCTL .. " Close &")
        end)

        hl.on("workspace.active", function()
            hl.exec_cmd(SOUNDCTL .. " FocusChange &")
        end)

        -- Fokuswechsel (Fenster A -> Fenster B, OHNE Workspace-Wechsel,
        -- z.B. Alt+Tab, Klick oder - da follow_mouse = 1 aktiv ist -
        -- auch reine Mausbewegung über ein anderes Fenster).
        hl.on("window.active", function()
            hl.exec_cmd(SOUNDCTL .. " FocusChange &")
        end)


        -- Allgemeines Aussehen & Verhalten
        hl.config({
            general = {
                gaps_in     = 6,
                gaps_out    = 8,
                border_size = 1,

                col = {
                    active_border   = { colors = {"rgba(fff495ee)"}, angle = 45 },
                  inactive_border = "rgba(d6cd7cee)",
                },

                resize_on_border        = true,
                extend_border_grab_area = 23,
                hover_icon_on_border    = true,
                allow_tearing           = false,
                layout                  = savedLayout,
            },

            decoration = {
                rounding       = 15,
                rounding_power = 5,

                active_opacity   = 0.9865,
                inactive_opacity = 0.85,

                shadow = {
                    enabled      = true,
                    range        = 4,
                    render_power = 2,
                    color        = "rgba(fff495ff)",
                },

                blur = {
                    enabled  = false,
                  size     = 3,
                  passes   = 2,
                  vibrancy = 0.1696,
                },
            },
        })

        -- Animationskurven
        hl.curve("bouncyOvershot", { type = "bezier", points = { {0.175, 0.885}, {0.32, 1.275} } })
        hl.curve("squishEase",     { type = "bezier", points = { {0.6, -0.28},  {0.735, 0.045} } })
        hl.curve("stretchySpring", { type = "spring", mass = 1, stiffness = 110, dampening = 13 })
        hl.curve("smoothInOut",    { type = "bezier", points = { {0.42, 0.0},   {0.58, 1.0} } })

        -- Animationen
        hl.animation({ leaf = "global",     enabled = true, speed = 10,  bezier = "default" })
        hl.animation({ leaf = "windows",    enabled = true, speed = 5,   spring = "stretchySpring" })
        hl.animation({ leaf = "windowsIn",  enabled = true, speed = 4.5, spring = "stretchySpring", style = "popin 60%" })
        hl.animation({ leaf = "windowsOut", enabled = true, speed = 3.5, bezier = "squishEase",     style = "popin 40%" })
        hl.animation({ leaf = "border",     enabled = true, speed = 4,   bezier = "bouncyOvershot" })
        hl.animation({ leaf = "fade",       enabled = true, speed = 3,   bezier = "default" })
        hl.animation({ leaf = "workspaces", enabled = true, speed = 5,   spring = "stretchySpring", style = "slide" })

        -- Layout- & sonstige Einstellungen
        hl.config({
            dwindle = { preserve_split = true },
            master  = { new_status = "slave" },
            misc = {
                force_default_wallpaper = 0,
                    disable_hyprland_logo   = true,
                    animate_manual_resizes  = false,
            },
        })

        hl.config({
            cursor = {
                no_warps = false,
            },
        })

        hl.layer_rule({
            match        = { namespace = "waybar" },
            ignore_alpha = 0.5,
            no_anim      = false,
        })

        hl.config({
            xwayland = {
                force_zero_scaling = true,
            },
        })

        hl.permission("/usr/(bin|local/bin)/hyprpm", "plugin", "allow")

        -- Touch-Geste: Wisch von unten nach oben pingt den waybar-autohide-Daemon an
        if hl.plugin and hl.plugin.hyprgrass then
            hl.config({
                plugin = {
                    hyprgrass = {
                        sensitivity = 8,
                        edge_margin = 165,
                    },
                },
            })

            hl.plugin.hyprgrass.bind({
                pattern = { kind = "edge", origin = "d", direction = "u" },
                action = hl.dsp.exec_cmd(
                    "bash -c 'p=/tmp/waybar-autohide.pid; [ -f \"$p\" ] && kill -RTMIN $(cat \"$p\")'"
                ),
            })
            else
                hl.exec_cmd("bash -c \"notify-send 'Hyprland' 'hyprgrass nicht geladen - Touch-Gesten deaktiviert (siehe: hyprctl plugin list)' -u critical || true\"")
                end

                -- hyprbars: Titelleiste mit Buttons
                hl.config({
                    plugin = {
                        hyprbars = {
                            bar_height            = 18,
                            bar_color             = "rgba(fff495ee)",
                          ["col.text"]          = "rgba(111111ee)",
                          bar_text_size         = 15,
                          bar_text_font         = "Noto Sans",
                          bar_buttons_alignment = "right",
                        },
                    },
                })

                hl.plugin.hyprbars.add_button({
                    bg_color = "rgba(ff5555ee)",
                                              fg_color = "rgba(111111ee)",
                                              size     = 15,
                                              icon     = "✕",
                                              action   = "hyprctl dispatch 'hl.dsp.window.close()'",
                })
                hl.plugin.hyprbars.add_button({
                    bg_color = "rgba(ffffffee)",
                                              fg_color = "rgba(111111ee)",
                                              size     = 15,
                                              icon     = "m",
                                              action   = "hyprctl dispatch 'hl.dsp.exec_cmd(\"hyprland-minimizer\")'",
                })
                hl.plugin.hyprbars.add_button({
                    bg_color = "rgba(ffffffee)",
                                              fg_color = "rgba(111111ee)",
                                              size     = 15,
                                              icon     = "FS1",
                                              action   = "hyprctl dispatch 'hl.dsp.window.fullscreen({ mode = 1 })'",
                })
                hl.plugin.hyprbars.add_button({
                    bg_color = "rgba(ffffffee)",
                                              fg_color = "rgba(111111ee)",
                                              size     = 15,
                                              icon     = "⇆",
                                              action   = "hyprctl dispatch 'hl.dsp.layout(\"swapwithmaster\", \"master\")'",
                })
                hl.plugin.hyprbars.add_button({
                    bg_color = "rgba(ffffffee)",
                                              fg_color = "rgba(111111ee)",
                                              size     = 15,
                                              icon     = "📌",
                                              action   = "hyprctl dispatch 'hl.dsp.exec_cmd(\"~/.config/hypr/PictureInPicture.sh\")'",
                })

                hl.window_rule({
                    name         = "rofi-hardcut",
                    match        = { class = "^(Rofi|rofi)$" },
                               no_anim      = true,
                               stay_focused = true,
                })

                -- Eingabe
                hl.config({
                    input = {
                        kb_layout    = "de",
                        follow_mouse = 0,
                        float_switch_override_focus = 0,
                        sensitivity  = 0,
                        touchpad = {
                            natural_scroll = true,
                        },
                    },
                })

                hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })

                local mainMod = "SUPER"

                -- Programme starten
                hl.bind(mainMod .. " + space", hl.dsp.exec_cmd(terminal))
                hl.bind(mainMod .. " + F",     hl.dsp.exec_cmd(fileManager))

                hl.bind(mainMod .. " + tab",    hl.dsp.exec_cmd(launcher_cmd))
                hl.bind(mainMod .. " + escape", hl.dsp.exec_cmd(powermenu_cmd))

                -- Fenstersteuerung (code:49 = Taste über Tab, DE-Layout: ^)
                hl.bind(mainMod .. " + SHIFT + code:49", hl.dsp.window.fullscreen({ mode = 0 }))
                hl.bind(mainMod .. " + code:49",         hl.dsp.window.fullscreen({ mode = 1 }))
                hl.bind(mainMod .. " + ALT + code:49",   hl.dsp.exec_cmd("hyprland-minimizer"))
                hl.bind(mainMod .. " + CTRL + code:49",  hl.dsp.exec_cmd("hyprctl dispatch 'hl.dsp.exec_cmd(\"~/.config/hypr/PictureInPicture.sh\")'"))

                -- Waybar-Autohide dauerhaft sperren/entsperren
                hl.bind(mainMod .. " + ALT + tab", hl.dsp.exec_cmd(
                    "bash -c 'p=/tmp/waybar-autohide.pid; [ -f \"$p\" ] && kill -RTMIN+1 $(cat \"$p\")'"
                ), { description = "Waybar-Autohide sperren/entsperren" })

                hl.bind(mainMod .. " + R", function()
                    hl.exec_cmd("xfce4-terminal -e 'bash /run/media/hopx/HopxSSD/TrafkSite/Projects/TrafkTux/TrafkTux/SyncEverything.sh --fast'")
                end, { description = "Sync with system" })

                hl.bind(mainMod .. " + SHIFT + R", function()
                    hl.exec_cmd("xfce4-terminal -e 'bash /run/media/hopx/HopxSSD/TrafkSite/Projects/TrafkTux/TrafkTux/SyncEverything.sh --fast --full'")
                end, { description = "Sync with system" })

                hl.bind(mainMod .. " + ALT + R", function()
                    hl.exec_cmd("xfce4-terminal -e 'bash /run/media/hopx/HopxSSD/TrafkSite/Projects/TrafkTux/TrafkTux/SyncEverything.sh --full'")
                end, { description = "Sync with system" })

                -- Kein eigener Sound-Aufruf mehr an dieser Stelle: HideAll.sh
                -- feuert seinen "Minimize"-Sound inzwischen selbst, einmal am
                -- Ende von do_hide - nachdem tatsächlich versteckt wurde,
                -- nicht schon beim bloßen Tastendruck (der bis zu 1s vorher
                -- liegen kann, siehe HideAll.sh's Polling-Kommentar). Ein
                -- zweiter Aufruf hier würde denselben Sound nur doppelt
                -- (und zu früh) auslösen.
                hl.bind(mainMod .. " + H", hl.dsp.exec_cmd("bash ~/.config/waybar/Scripts/HideAll.sh toggle &"), { description = "Alle Fenster verstecken/wiederherstellen" })

                hl.config({
                    scrolling = {
                        wrap_focus   = false,
                        column_width = 0.5,
                    },
                })



-- Gibt den Monitor in der angegebenen Richtung zurück (nur horizontal)
local function get_monitor_in_direction(current_monitor, direction)
    local monitors = hl.get_monitors()
    local best = nil
    for _, m in ipairs(monitors) do
        if direction == "right" and m.x > current_monitor.x then
            if not best or m.x < best.x then best = m end
        elseif direction == "left" and m.x < current_monitor.x then
            if not best or m.x > best.x then best = m end
        end
    end
    return best
end



-- ============================================================
-- Scrolling: native focus r/l + Monitorwechsel
-- ============================================================
local function scrolling_focus(direction)
    local ws = hl.get_active_workspace()
    if not ws or ws.tiled_layout ~= "scrolling" then return end

    -- hl.get_windows({filters}) statt hl.get_workspace_windows(ws) (letzteres
    -- existiert nicht in der hl.*-API) - filtert direkt nach floating=false,
    -- liefert also gleich nur die getilten Fenster.
    --
    -- Floatende (inkl. gepinnter PIP) werden hier bewusst NICHT mit
    -- reingemischt: die erreicht man gezielt über SUPER+q/e/x/<
    -- (floatingDiagonal, s.u.), das funktioniert von jedem Fenster aus,
    -- getilt oder floatend. wasd bleibt dadurch rein "normale" Navigation.
    local wins = hl.get_windows({ workspace = ws.id, floating = false })
    local active = hl.get_active_window()

    -- Wenn der aktuelle Monitor/Workspace leer ist, direkt rüber springen
    if not wins or #wins == 0 or not active then
        local current_mon = hl.get_active_monitor()
        local target_mon = get_monitor_in_direction(current_mon, direction)
        if target_mon then
            hl.dispatch(hl.dsp.focus({ monitor = target_mon.name }))
        end
        return
    end

    -- Robuster Helfer: Findet die X-Koordinate des Fensters sicher heraus.
    local function get_x(w)
        if type(w.at) == "table" and type(w.at.x) == "number" then return w.at.x end
        if type(w.at) == "table" and type(w.at[1]) == "number" then return w.at[1] end
        if type(w.position) == "table" and type(w.position.x) == "number" then return w.position.x end
        if type(w.x) == "number" then return w.x end
        return 0
    end

    -- Ist das aktive Fenster selbst nicht Teil des getilten Scroller-Baums
    -- (z.B. weil es floatend ist)? Dann von der passenden Seite einsteigen,
    -- statt hängen zu bleiben.
    local activeInTiled = false
    for _, w in ipairs(wins) do
        if w.address == active.address then
            activeInTiled = true
            break
        end
    end

    if not activeInTiled then
        local entry = (direction == "right") and wins[1] or wins[#wins]
        if entry then
            hl.dispatch(hl.dsp.focus({ window = entry }))
        end
        return
    end

    local active_x = get_x(active)
    local is_edge = true

    if direction == "right" then
        -- Prüfen, ob IRGENDEIN Fenster auf diesem Workspace physisch weiter rechts liegt
        for _, win in ipairs(wins) do
            if get_x(win) > active_x then
                is_edge = false
                break
            end
        end
    else -- left
        -- Prüfen, ob IRGENDEIN Fenster auf diesem Workspace physisch weiter links liegt
        for _, win in ipairs(wins) do
            if get_x(win) < active_x then
                is_edge = false
                break
            end
        end
    end

    if is_edge then
        -- Monitor wechseln (ohne Prüfung, ob der Ziel-Monitor Fenster hat!)
        local current_mon = hl.get_active_monitor()
        local target_mon = get_monitor_in_direction(current_mon, direction)
        if target_mon then
            hl.dispatch(hl.dsp.focus({ monitor = target_mon.name }))
        end
    else
        -- Es gibt noch versteckte Fenster auf diesem Monitor -> normal Scroller-Fokus nutzen
        local cmd = (direction == "right") and "focus r" or "focus l"
        hl.dispatch(hl.dsp.layout(cmd))
    end
end

-- ============================================================
-- Monocle: cyclenext/prev + Monitorwechsel
-- ============================================================
local function monocle_focus(direction)
    local ws = hl.get_active_workspace()
    if not ws or ws.tiled_layout ~= "monocle" then return end

    local active = hl.get_active_window()
    if not active then return end

    -- NUR getilte Fenster dieses Workspace als Cycle-Kandidaten. Floatende
    -- (inkl. gepinnter, z.B. PIP) mischen wir bewusst nicht rein - sonst
    -- springt das lineare Durchcyclen ungewollt zu einem floatenden Fenster
    -- statt zum eigentlich anvisierten Tiling-Nachbarn. Floatende erreicht
    -- man in Monocle gezielt über SUPER+q/e/x/< (floatingDiagonal, s.u.).
    local all = hl.get_windows({ workspace = ws.id, floating = false })

    if #all == 0 then
        local current_mon = hl.get_active_monitor()
        local target_mon = get_monitor_in_direction(current_mon, direction)
        if target_mon then
            hl.dispatch(hl.dsp.focus({ monitor = target_mon.name }))
        end
        return
    end

    -- Über .address statt Referenzgleichheit (==) vergleichen: zwei separat
    -- abgefragte Fensterobjekte fürs selbe Fenster sind nicht zwangsläufig
    -- dasselbe Lua-Table-Objekt.
    local idx
    for i, win in ipairs(all) do
        if win.address == active.address then
            idx = i
            break
        end
    end

    if not idx then
        -- Aktives Fenster ist nicht in der Liste (Sonderfall) -> von der
        -- passenden Seite einsteigen statt gar nichts zu tun.
        local entry = (direction == "right") and all[1] or all[#all]
        if entry then
            hl.dispatch(hl.dsp.focus({ window = entry }))
        end
        return
    end

    if direction == "right" then
        if idx == #all then
            local current_mon = hl.get_active_monitor()
            local target_mon = get_monitor_in_direction(current_mon, "right")
            if target_mon then
                hl.dispatch(hl.dsp.focus({ monitor = target_mon.name }))
            end
        else
            hl.dispatch(hl.dsp.focus({ window = all[idx + 1] }))
        end
    else -- left
        if idx == 1 then
            local current_mon = hl.get_active_monitor()
            local target_mon = get_monitor_in_direction(current_mon, "left")
            if target_mon then
                hl.dispatch(hl.dsp.focus({ monitor = target_mon.name }))
            end
        else
            hl.dispatch(hl.dsp.focus({ window = all[idx - 1] }))
        end
    end
end



local function get_pos(w)
    if type(w.at) == "table" and type(w.at.x) == "number" then return w.at.x, w.at.y end
    if type(w.at) == "table" and type(w.at[1]) == "number" then return w.at[1], w.at[2] end
    if type(w.position) == "table" and type(w.position.x) == "number" then return w.position.x, w.position.y end
    return 0, 0
end

local function get_center(w)
    local x, y = get_pos(w)
    local sx = (type(w.size) == "table" and type(w.size.x) == "number") and w.size.x or 0
    local sy = (type(w.size) == "table" and type(w.size.y) == "number") and w.size.y or 0
    return x + sx / 2, y + sy / 2
end

-- DEBUG-SCHALTER: bei true feuert bei jedem SUPER+wasd/q/e/x/<-Versuch eine
-- kurze Notification mit dem genauen Ergebnis der Floating-Navigation
-- (wie viele Kandidaten, welches Ziel, Wraparound ja/nein, oder ob gar
-- keine Kandidaten da waren/auf natives movefocus zurückgefallen wurde).
-- Gleiches Debug-Prinzip wie schon beim opentest.log weiter oben in dieser
-- Datei: am echten Compositor nachvollziehen statt nochmal blind raten.
-- Nach dem Testen wieder auf false setzen.
-- Prüft das Flag-File aus LayoutSwitcher.sh: ist der "floating"-Pseudo-Modus
-- gerade aktiv? Das zugrunde liegende general.layout/tiled_layout bleibt beim
-- Wechsel in "floating" BEWUSST unverändert (siehe Kommentar in
-- LayoutSwitcher.sh) - "floating" ist kein eigenes Hyprland-Layout, sondern
-- floatet nur die Fenster, während z.B. "scrolling" darunter weiterläuft.
-- Genau DESHALB darf skipFloatFirst in focusOrCycle NICHT nur an
-- tiled_layout == "monocle"/"scrolling" hängen: sonst wird im Floating-Modus
-- fälschlich angenommen, man sei in echtem Scroller-/Monocle-Tiling, und die
-- floatende wasd-Navigation wird übersprungen, obwohl man gerade NUR
-- floatende Fenster vor sich hat (das war der gemeldete "a/d geht gar
-- nicht"-Bug). Live pro Tastendruck neu gelesen (kein Caching, kein Reload
-- nötig), damit's sofort nach Mod+Alt+4 wirkt.
local FLOATING_MODE_FLAG = os.getenv("HOME") .. "/.cache/hypr/floating_mode_active"

local function is_floating_mode_active()
    local f = io.open(FLOATING_MODE_FLAG, "r")
    if not f then return false end
    f:close()
    return true
end

local DEBUG_FLOAT_NAV = false
-- Log-Datei zusaetzlich zur (zu schnell verschwindenden) Notification: bei
-- jedem debug_float_nav()-Aufruf wird die Zeile MIT Zeitstempel angehaengt,
-- damit man sie in Ruhe per "cat" oder "tail -f" nachlesen kann statt sie
-- vom Bildschirm abfotografieren zu muessen, bevor sie weg ist.
local FLOAT_NAV_LOG = os.getenv("HOME") .. "/floatnav_debug.log"

local function debug_float_nav(msg)
    if not DEBUG_FLOAT_NAV then return end
    hl.notification.create({ text = "[FloatNav] " .. msg, timeout = 2500, icon = "info" })
    local f = io.open(FLOAT_NAV_LOG, "a")
    if f then
        f:write(os.date("%H:%M:%S") .. "  " .. msg .. "\n")
        f:close()
    end
end

-- Richtungsvektoren: 0 = Achse frei (Kardinalrichtung), -1/1 = Achse
-- erzwungen (bei Diagonalen beide Achsen erzwungen -> echter Quadrant).
local FLOAT_DIRS = {
    left      = { dx = -1, dy = 0  },
    right     = { dx = 1,  dy = 0  },
    up        = { dx = 0,  dy = -1 },
    down      = { dx = 0,  dy = 1  },
    upleft    = { dx = -1, dy = -1 },
    upright   = { dx = 1,  dy = -1 },
    downleft  = { dx = -1, dy = 1  },
    downright = { dx = 1,  dy = 1  },
}

local function floating_focus_direction(active, direction)
    local spec = FLOAT_DIRS[direction]
    if not spec then return false end

    local ws = hl.get_active_workspace()
    local wsId = ws and ws.id
    local acx, acy = get_center(active)

    -- Klassen, die zwar floating sind, aber nie ein sinnvolles Navigationsziel
    -- sind (Notification-Popups etc.) - dieselbe Ausnahme wie in
    -- LayoutSwitcher.sh:unfloat_current_workspace (siehe Kommentar dort: dunst
    -- ist floating/nicht gepinnt, poppt aber unvorhersehbar auf und wuerde
    -- sonst mainMod+wasd/q/e/x/< kapern, sobald gerade eine Notification zu
    -- sehen ist).
    local NAV_EXCLUDED_CLASSES = { dunst = true }

    local function is_navigable_float(w)
        local class = w.class and w.class:lower() or ""
        return not NAV_EXCLUDED_CLASSES[class]
    end

    local candidates = {}
    for _, w in pairs(hl.get_windows()) do
        if w.address ~= active.address and w.floating and is_navigable_float(w) then
            local sameWs = wsId ~= nil and w.workspace and w.workspace.id == wsId
            if w.pinned or sameWs then
                table.insert(candidates, w)
            end
        end
    end
    if #candidates == 0 then
        debug_float_nav("Richtung=" .. direction .. ": 0 floatende Kandidaten auf diesem Workspace (inkl. gepinnter) - falle auf natives movefocus zurück")
        return false
    end

    local function matches(dx, dy)
        if spec.dx < 0 and dx >= 0 then return false end
        if spec.dx > 0 and dx <= 0 then return false end
        if spec.dy < 0 and dy >= 0 then return false end
        if spec.dy > 0 and dy <= 0 then return false end
        return true
    end

    -- Kardinalrichtung (nur eine Achse erzwungen): primäre Achse zählt am
    -- meisten, Abweichung auf der freien Achse wird stark bestraft, sonst
    -- gewinnt leicht ein diagonal weit abseits liegendes Fenster gegen ein
    -- gut ausgerichtetes - genau das beschriebene "springt quer"-Problem.
    -- Diagonalrichtung (beide Achsen erzwungen): reiner Abstand reicht,
    -- der Quadrant ist durch matches() schon erzwungen.
    local function score(dx, dy)
        if spec.dx ~= 0 and spec.dy ~= 0 then
            return math.sqrt(dx * dx + dy * dy)
        elseif spec.dx ~= 0 then
            return math.abs(dx) + math.abs(dy) * 3
        else
            return math.abs(dy) + math.abs(dx) * 3
        end
    end

    local best, bestScore = nil, nil
    for _, w in ipairs(candidates) do
        local cx, cy = get_center(w)
        local dx, dy = cx - acx, cy - acy
        if matches(dx, dy) then
            local s = score(dx, dy)
            if not bestScore or s < bestScore then
                best, bestScore = w, s
            end
        end
    end

    local wrapped = false
    if not best then
        -- Wraparound: nichts mehr in der Richtung -> auf die
        -- gegenüberliegende Seite springen (Extremwert der Gegenrichtung
        -- auf jeder erzwungenen Achse).
        wrapped = true
        local bestWrap
        for _, w in ipairs(candidates) do
            local cx, cy = get_center(w)
            local dx, dy = cx - acx, cy - acy
            local val = -(spec.dx * dx + spec.dy * dy)
            if not bestWrap or val > bestWrap then
                bestWrap, best = val, w
            end
        end
    end

    if best then
        debug_float_nav("Richtung=" .. direction .. ": " .. #candidates .. " Kandidaten, Ziel=" ..
            (best.class or "?") .. " " .. (best.address or "?") ..
            (wrapped and " (per Wraparound, kein Fenster direkt in der Richtung)" or ""))
        hl.dispatch(hl.dsp.focus({ window = best }))
        return true
    end
    debug_float_nav("Richtung=" .. direction .. ": " .. #candidates .. " Kandidaten, aber KEINER hat gepasst (auch Wraparound leer) - falle auf natives movefocus zurück")
    return false
end

local function focusOrCycle(direction)
    return function()
        local ws = hl.get_active_special_workspace() or hl.get_active_workspace()
        local layout = ws and ws.tiled_layout

        -- In ECHTEM Monocle/Scroller-Tiling ist wasd bewusst NUR die normale
        -- (getilte) Navigation - floatende Fenster (inkl. PIP) erreicht man
        -- dort gezielt über SUPER+q/e/x/< (floatingDiagonal). Grund: beim
        -- linearen Durchcyclen will man nicht ungewollt zu einem
        -- floatenden Fenster abspringen, weg vom eigentlich anvisierten
        -- Nachbarn im Stapel.
        --
        -- WICHTIG: der "floating"-Pseudo-Modus (LayoutSwitcher.sh floating)
        -- ändert general.layout/tiled_layout BEWUSST NICHT - das zuletzt
        -- aktive Tiling-Layout bleibt darunter "geparkt" (z.B. scrolling).
        -- Ohne die is_floating_mode_active()-Prüfung würde obige Bedingung
        -- also fälschlich glauben, man sei in echtem Scroller-/Monocle-
        -- Tiling, und die floatende wasd-Navigation würde übersprungen,
        -- obwohl man gerade NUR floatende Fenster vor sich hat - genau der
        -- gemeldete "a/d im Floating-Layout geht gar nicht"-Bug (siehe Log:
        -- kein einziger Fallback-Log-Eintrag bei links/rechts während
        -- active.floating=true und layout=scrolling).
        --
        -- Im default/dwindle/master-Layout (und jetzt auch im Floating-
        -- Modus) bleibt die ursprüngliche Priorität erhalten: ist das aktive
        -- Fenster floatend, erst räumliche Floating-Navigation versuchen
        -- (das war der ursprüngliche "PIP mit wasd fokussieren"-Wunsch) und
        -- nur bei fehlendem Ziel auf normale Navigation durchfallen.
        local skipFloatFirst = (layout == "monocle" or layout == "scrolling") and not is_floating_mode_active()

        local active = hl.get_active_window()
        debug_float_nav("focusOrCycle Start: layout=" .. tostring(layout) .. " skipFloatFirst=" .. tostring(skipFloatFirst) ..
            " floatingMode=" .. tostring(is_floating_mode_active()) ..
            " active.floating=" .. tostring(active and active.floating))

        if not skipFloatFirst and active and active.floating then
            if floating_focus_direction(active, direction) then
                return
            end
        elseif skipFloatFirst then
            debug_float_nav("Richtung=" .. direction .. ": floating_focus_direction uebersprungen, weil layout=" .. tostring(layout) .. " (monocle/scrolling)")
        elseif not (active and active.floating) then
            debug_float_nav("Richtung=" .. direction .. ": aktives Fenster ist NICHT floatend (oder gar nicht ermittelbar) -> floating_focus_direction wird nicht versucht")
        end

        if not ws then return end

        if layout == "scrolling" and (direction == "left" or direction == "right") then
            scrolling_focus(direction)
            return
        end

        if layout == "monocle" and (direction == "left" or direction == "right") then
            monocle_focus(direction)
            return
        end

        debug_float_nav("Richtung=" .. direction .. ": lande beim nativen hl.dsp.focus({direction=...}) (letzter Fallback)")
        hl.dispatch(hl.dsp.focus({ direction = direction }))
    end
end

                            -- Workspaces zyklisch (1-9, mit Wraparound), jetzt auf SHIFT
                            -- verschoben - bare q/e sind jetzt für Diagonal-Fokus (floating)
                            -- frei, passend zu den bestehenden Eck-Snap-Tasten q/e/x/<
                            -- (SUPER+CTRL+...) weiter unten.
                            hl.bind(mainMod .. " + SHIFT + q", function()
                                local ws = hl.get_active_workspace()
                                if not ws or not ws.id then return end
                                local target = ws.id - 1
                                if target < 1 then target = 9 end
                                hl.dispatch(hl.dsp.focus({ workspace = target }))
                            end)
                            hl.bind(mainMod .. " + SHIFT + e", function()
                                local ws = hl.get_active_workspace()
                                if not ws or not ws.id then return end
                                local target = ws.id + 1
                                if target > 9 then target = 1 end
                                hl.dispatch(hl.dsp.focus({ workspace = target }))
                            end)

                            hl.bind(mainMod .. " + a", focusOrCycle("left"))
                            hl.bind(mainMod .. " + d", focusOrCycle("right"))
                            hl.bind(mainMod .. " + w", focusOrCycle("up"))
                            hl.bind(mainMod .. " + s", focusOrCycle("down"))

                            -- Diagonal-Fokus zwischen floating Fenstern (inkl. PIP), bei
                            -- Tiling ohne Wirkung. Selbe Tastenzuordnung wie die
                            -- bestehenden Eck-Snap-Bindings (SUPER+CTRL+q/e/</x), nur ohne
                            -- CTRL und für Fokus statt Snap: q=oben-links, e=oben-rechts,
                            -- x=unten-rechts, <=unten-links.
                            local function floatingDiagonal(direction)
                                return function()
                                    -- Bewusst OHNE "active.floating"-Guard: sonst kommt man von
                                    -- einem getilten Fenster nie zu einem floatenden rüber (genau
                                    -- der gemeldete Bug). floating_focus_direction braucht nur
                                    -- Position/Größe des aktiven Fensters als Ausgangspunkt - das
                                    -- haben getilte Fenster genauso wie floatende.
                                    local active = hl.get_active_window()
                                    if active then
                                        floating_focus_direction(active, direction)
                                    end
                                end
                            end
                            hl.bind(mainMod .. " + q",    floatingDiagonal("upleft"))
                            hl.bind(mainMod .. " + e",    floatingDiagonal("upright"))
                            hl.bind(mainMod .. " + x",    floatingDiagonal("downright"))
                            hl.bind(mainMod .. " + less", floatingDiagonal("downleft"))

                            -- Touch: 2-Finger-Wisch links/rechts für Fokuswechsel
                            if hl.plugin and hl.plugin.hyprgrass then
                                hl.plugin.hyprgrass.bind({
                                    pattern = { kind = "swipe", fingers = 2, direction = "r" },
                                    action = focusOrCycle("right"),
                                })

                                hl.plugin.hyprgrass.bind({
                                    pattern = { kind = "swipe", fingers = 2, direction = "l" },
                                    action = focusOrCycle("left"),
                                })
                                end

                                -- Layout wechseln
                                hl.bind(mainMod .. " + ALT + 1", hl.dsp.exec_cmd("bash ~/.config/hypr/LayoutSwitcher.sh master"))
                                hl.bind(mainMod .. " + ALT + 2", hl.dsp.exec_cmd("bash ~/.config/hypr/LayoutSwitcher.sh dwindle"))
                                hl.bind(mainMod .. " + ALT + 3", hl.dsp.exec_cmd("bash ~/.config/hypr/LayoutSwitcher.sh scroller"))
                                hl.bind(mainMod .. " + ALT + 4", hl.dsp.exec_cmd("bash ~/.config/hypr/LayoutSwitcher.sh floating"))
                                hl.bind(mainMod .. " + ALT + 5", hl.dsp.exec_cmd("bash ~/.config/hypr/LayoutSwitcher.sh bigscreen"))

                                -- Workspaces per Zahlentaste
                                for i = 1, 9 do
                                    local key = i % 10
                                    hl.bind(mainMod .. " + " .. key,         hl.dsp.focus({ workspace = i }))
                                    hl.bind(mainMod .. " + SHIFT + " .. key, hl.dsp.window.move({ workspace = i }))
                                    end

                                    hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag(),   { mouse = true })
                                    hl.bind(mainMod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

                                    -- Medientasten
                                    hl.bind("XF86AudioRaiseVolume",  hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), { locked = true, repeating = true })
                                    hl.bind("XF86AudioLowerVolume",  hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"),      { locked = true, repeating = true })
                                    hl.bind("XF86AudioMute",         hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"),     { locked = true, repeating = true })
                                    hl.bind("XF86MonBrightnessUp",   hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%+"),                  { locked = true, repeating = true })
                                    hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%-"),                  { locked = true, repeating = true })

                                    hl.bind("XF86AudioPlay", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
                                    hl.bind("XF86AudioNext", hl.dsp.exec_cmd("playerctl next"),       { locked = true })
                                    hl.bind("XF86AudioPrev", hl.dsp.exec_cmd("playerctl previous"),   { locked = true })

                                    -- Screenshots
                                    hl.bind(mainMod .. " + Print",         hl.dsp.exec_cmd('grim -g "$(slurp -d)" - | wl-copy'))
                                    hl.bind(mainMod .. " + SHIFT + Print", hl.dsp.exec_cmd('bash -c "mkdir -p ~/Screenshots && grim -g \\"$(slurp -d)\\" ~/Pictures/$(date +%Y%m%d_%H%M%S).png"'))

                                    hl.window_rule({
                                        name           = "suppress-maximize-events",
                                        match          = { class = ".*" },
                                        suppress_event = "maximize",
                                    })

                                    hl.window_rule({
                                        name  = "move-hyprland-run",
                                        match = { class = "hyprland-run" },
                                        move  = "20 monitor_h-120",
                                        float = true,
                                    })

                                    -- hyprglass: Liquid-Glass-Effekt (Blur, Refraktion, Fresnel-Glow) auf Fenstern/Layern
                                    if hl.plugin.hyprglass then
                                        local hg = hl.plugin.hyprglass

                                        hg.config({
                                            enabled       = true,
                                            default_theme = "dark",

                                            blur_strength        = 0,
                                            blur_iterations      = 0,
                                            refraction_strength  = 1,
                                            chromatic_aberration = 0.15,
                                            fresnel_strength     = 1,
                                            specular_strength    = 1,
                                            glass_opacity        = 1,
                                            edge_thickness       = 0.35,
                                            lens_distortion      = 1,

                                            dark = {
                                                brightness        = 1,
                                                contrast          = 1,
                                                saturation        = 1,
                                                vibrancy          = 1,
                                                vibrancy_darkness = 1,
                                                adaptive_dim      = 0,
                                                adaptive_boost    = 0,
                                            },
                                            light = {
                                                brightness        = 1,
                                                contrast          = 1,
                                                saturation        = 1,
                                                vibrancy          = 1,
                                                vibrancy_darkness = 1,
                                                adaptive_dim      = 0,
                                                adaptive_boost    = 0,
                                            },

                                            layers = { enabled = true },
                                        })

                                        -- wb-daemon: die kleinen Bubble-Widgets (Settings, Lautstärke,
                                        -- Netzwerk, ...) aus WidgetsDaemon.py sollen den Glass-Effekt
                                        -- NICHT bekommen - der sichtbare "Rahmen" darauf war genau dieser
                                        -- Effekt, nicht ein GTK-Fokus-/Hover-Rahmen.
                                        hg.layer("wb-daemon", { exclude = true })
                                        end

                                        -- hypr-dynamic-cursors: physikalisch simulierter Cursor + Shake-to-Find
                                        if hl.plugin.dynamic_cursors then
                                            hl.config({ plugin = { dynamic_cursors = {

                                                enabled   = true,
                                                mode      = "tilt",
                                                threshold = 1,

                                                rotate = {
                                                    length = 45,
                                                    offset = 0.0,
                                                },

                                                tilt = {
                                                    limit      = 850,
                                                    activation = "negative_quadratic",
                                                    window     = 85,
                                                    full       = 45,
                                                },

                                                stretch = {
                                                    limit      = 3000,
                                                    activation = "quadratic",
                                                    window     = 100,
                                                },

                                                shake = {
                                                    enabled = false,

                                                    threshold = 5.0,
                                                    base      = 1.0,
                                                    speed     = 1.0,
                                                    influence = 1.0,
                                                    limit     = 0.0,
                                                    timeout   = 3500,

                                                    effects = true,
                                                    ipc     = true,
                                                },

                                                hyprcursor = {
                                                    nearest    = 2,
                                                    enabled    = true,
                                                    resolution = -1,
                                                    fallback   = "clientside",
                                                },
                                            }}})
                                            end

                                            -- hyprfocus: Animation beim Fensterfokuswechsel
                                            hl.config({ plugin = { hyprfocus = {

                                                keyboard_focus_animation = "slide",
                                                mouse_focus_animation   = "slide",

                                                only_on_monitor_change = false,
                                                fade_opacity  = 0.65,
                                                slide_height  = -5,

                                            }}})
                                            hl.animation({ leaf = "hyprfocusIn",  enabled = true, speed = 1.5, bezier = "smoothInOut" })
                                            hl.animation({ leaf = "hyprfocusOut", enabled = true, speed = 1.5, bezier = "smoothInOut" })

                                            -- hyprexpo: Expose-artige Workspace-Übersicht im Grid
                                            if hl.plugin.hyprexpo then
                                                hl.config({ plugin = { hyprexpo = {

                                                    columns  = 3,
                                                    gaps_in  = 23,
                                                    gaps_out = 35,

                                                    bg_col = "rgb(23163B)",

                                                          workspace_method = "first 1",

                                                          gesture_distance = 200,
                                                          cancel_key       = "escape",
                                                          show_cursor       = 1,

                                                          keynav_enable        = 1,
                                                          keynav_wrap_h        = 1,
                                                          keynav_wrap_v        = 1,
                                                          keynav_reading_order = 0,

                                                          border_width          = 5,
                                                          border_color_current  = "rgb(5a3998)",
                                                          border_color_focus    = "rgb(fff495)",
                                                          border_color_hover    = "rgb(fff495)",
                                                          tile_rounding         = 65,

                                                          label_enable    = 1,
                                                          label_text_mode = "index",
                                                }}})

                                                -- Submap für Tastatur-Navigation innerhalb der Übersicht
                                                hl.define_submap("hyprexpo", function()
                                                hl.bind("w", function() hl.plugin.hyprexpo.kb_focus("up") end)
                                                hl.bind("a", function() hl.plugin.hyprexpo.kb_focus("left") end)
                                                hl.bind("s", function() hl.plugin.hyprexpo.kb_focus("down") end)
                                                hl.bind("d", function() hl.plugin.hyprexpo.kb_focus("right") end)
                                                hl.bind("up",    function() hl.plugin.hyprexpo.kb_focus("up") end)
                                                hl.bind("down",  function() hl.plugin.hyprexpo.kb_focus("down") end)
                                                hl.bind("left",  function() hl.plugin.hyprexpo.kb_focus("left") end)
                                                hl.bind("right", function() hl.plugin.hyprexpo.kb_focus("right") end)

                                                local function confirm()
                                                hl.plugin.hyprexpo.kb_confirm()
                                                hl.dispatch(hl.dsp.submap("reset"))
                                                end
                                                hl.bind("return", confirm)
                                                hl.bind("space", confirm)
                                                hl.bind("less", confirm)

                                                local function cancel()
                                                hl.plugin.hyprexpo.expo("cancel")
                                                hl.dispatch(hl.dsp.submap("reset"))
                                                end
                                                hl.bind("escape", cancel)
                                                hl.bind("x", cancel)

                                                for i = 1, 9 do
                                                    hl.bind(tostring(i), function() hl.plugin.hyprexpo.kb_selecti(i) end)
                                                    end

                                                    hl.bind("catchall", hl.dsp.no_op())
                                                    end)

                                                -- Öffnet die Übersicht und wechselt gleichzeitig in die Submap
                                                hl.bind(mainMod .. " + CTRL + tab", function()
                                                hl.plugin.hyprexpo.expo("toggle")
                                                hl.dispatch(hl.dsp.submap("hyprexpo"))
                                                end)
                                                end

                                                hl.window_rule({
                                                    match = {
                                                        class = "WidgetsDaemon.py",
                                                    },
                                                    float = true,
                                                    pin = true,
                                                })





                                                -- ============================================================
                                                -- Dynamische Fenster-Snaps (Floating)
                                                -- ============================================================

                                                -- Prüft, ob das aktuelle Fenster im Floating-Modus ist
                                                local function is_window_floating()
                                                local win = hl.get_active_window()
                                                return win and win.floating or false
                                                end

                                                -- Holt die Geometrie des Monitors, auf dem das aktive Fenster liegt.
                                                -- WICHTIG: monitor.width/height sind physische Pixel; move/resize erwarten
                                                -- logische (durch den Monitor-scale geteilte) Koordinaten. Ohne die Division
                                                -- landen/skalieren Fenster bei scale != 1 falsch (ragen z.B. über den Rand).
                                                local function get_active_monitor_geometry()
                                                local win = hl.get_active_window()
                                                if not win or not win.monitor then return nil end
                                                    local mon = win.monitor
                                                    local scale = mon.scale or 1
                                                    return {
                                                        x = mon.x,
                                                        y = mon.y,
                                                        width = mon.width / scale,
                                                        height = mon.height / scale,
                                                    }
                                                    end

                                                    -- Außenabstand für Snaps, analog zu gaps_out in der Tiling-Config (Zeile ~77)
                                                    local SNAP_GAP = 15
                                                    -- Höhe der hyprbars-Titelleiste (siehe plugin.hyprbars.bar_height weiter oben in
                                                    -- dieser Datei) - wird oben zusätzlich abgezogen, sonst kollidiert die Titelleiste
                                                    -- mit dem oberen Bildschirmrand bzw. reserved-Bereichen.
                                                    local HYPRBARS_HEIGHT = 15

                                                    -- ============================================================
                                                    -- Floating-"Layout": neue Fenster sollen floaten, solange
                                                    -- zuletzt LayoutSwitcher.sh floating gewählt wurde
                                                    -- ============================================================
                                                    -- "floating" ist kein general.layout-Wert (siehe LayoutSwitcher.sh):
                                                    -- es floatet nur die gerade offenen Fenster, general.layout bleibt
                                                    -- unverändert. Neue Fenster brauchen deshalb ein eigenes Flag-File
                                                    -- (is_floating_mode_active(), global definiert bei DEBUG_FLOAT_NAV
                                                    -- weiter oben), das LayoutSwitcher.sh setzt/löscht.
                                                    --
                                                    -- Klassen, die NIE von der automatischen Größen-Klemmung betroffen
                                                    -- sein sollen: Rofi und Dunst sind beide floatend, aber ihre Größe
                                                    -- wird von ihnen selbst (Theme/Notification-Inhalt) bestimmt - ein
                                                    -- erzwungenes Runterklemmen auf 35% der Monitorbreite macht sie
                                                    -- sichtbar kaputt/verzerrt ("scuffed"). Gleiche Prüfmethode wie
                                                    -- NAV_EXCLUDED_CLASSES weiter oben.
                                                    local SIZE_CLAMP_EXCLUDED_CLASSES = { dunst = true, rofi = true }

                                                    local function is_size_clamp_excluded(win)
                                                        local class = win.class and win.class:lower() or ""
                                                        return SIZE_CLAMP_EXCLUDED_CLASSES[class] or false
                                                    end

                                                    -- ============================================================
                                                    -- Max-Größe für floatende Fenster: 35% der (logischen) Monitorgröße
                                                    -- ============================================================
                                                    -- Greift nur in genau zwei Fällen (nicht deklarativ per
                                                    -- window_rule max_size, weil das beim ERSTEN Floaten laut
                                                    -- dokumentierten Hyprland-Bugs nicht zuverlässig zieht):
                                                    -- 1. window.open, wenn der Floating-Modus aktiv ist (Hook unten)
                                                    -- 2. Layout-Wechsel auf "floating" - LayoutSwitcher.sh ruft dafür
                                                    --    hlClampFloatingWindow direkt und synchron auf (s.u.)
                                                    -- Verkleinert nur, vergrößert nie.
                                                    local FLOAT_MAX_FRACTION = 0.35

                                                    local function clamp_floating_window(win)
                                                        if not win or not win.floating or not win.monitor then return end
                                                        if is_size_clamp_excluded(win) then return end
                                                        local mon = win.monitor
                                                        local scale = mon.scale or 1
                                                        local maxW = math.floor((mon.width / scale) * FLOAT_MAX_FRACTION)
                                                        local maxH = math.floor((mon.height / scale) * FLOAT_MAX_FRACTION)

                                                        local curW = win.size and win.size.x or 0
                                                        local curH = win.size and win.size.y or 0
                                                        if curW <= 0 or curH <= 0 then return end

                                                        local newW = math.min(curW, maxW)
                                                        local newH = math.min(curH, maxH)

                                                        if newW ~= curW or newH ~= curH then
                                                            hl.dispatch(hl.dsp.window.resize({
                                                                x = newW, y = newH,
                                                                window = "address:" .. win.address,
                                                            }))
                                                        end
                                                    end

                                                    -- Extern per "hyprctl eval" aufrufbar (nutzt "hyprctl eval" wieder
                                                    -- denselben persistenten Lua-State, den hyprland.lua geladen hat -
                                                    -- gleiches Prinzip wie die hl.dispatch(...)-Aufrufe im Skript
                                                    -- selbst). LayoutSwitcher.sh ruft das synchron auf, statt sich auf
                                                    -- ein extern getriggertes Event zu verlassen (Fall 2 oben).
                                                    _G.hlClampFloatingWindow = clamp_floating_window

                                                    hl.on("window.open", function(win)
                                                        if not win then return end

                                                        -- Selektor-Format "address:0x..." wie im LayoutSwitcher-Skript.
                                                        -- action="set" statt "toggle": wir wollen zwingend floaten.
                                                        if is_floating_mode_active() and not win.floating and not is_size_clamp_excluded(win) then
                                                            hl.dispatch(hl.dsp.window.float({
                                                                action = "set",
                                                                window = "address:" .. win.address,
                                                            }))
                                                        end

                                                        -- Frisches Fensterobjekt nachladen: "win" aus dem Event kann
                                                        -- nach dem obigen float-Dispatch veraltet sein (floating/size).
                                                        local fresh = hl.get_window("address:" .. win.address) or win
                                                        clamp_floating_window(fresh)
                                                    end)

                                                    -- Bewusst KEIN window.update_rules-Hook für die Klemmung: das
                                                    -- Event feuert bei jeder Änderung eines dynamischen
                                                    -- Match-Kriteriums (auch Titel/Fokus, nicht nur floating) und
                                                    -- würde bei JEDEM manuellen Float-Toggle mitklemmen - nicht nur
                                                    -- bei den zwei oben genannten Fällen. Fall 2 läuft deshalb
                                                    -- ausschließlich über hlClampFloatingWindow aus LayoutSwitcher.sh.

                                                    -- Snap: bewegt und resized das aktive Fenster auf Bruchteile des Monitors,
-- mit SNAP_GAP Rand zu Bildschirmkanten und zwischen Snap-Zonen.
local function snap_window_fraction(x_frac, y_frac, w_frac, h_frac)
local geo = get_active_monitor_geometry()
if not geo then return end
    -- Rohe Zielrechteck-Grenzen in Bruchteilen des Monitors
    local raw_x = geo.x + geo.width * x_frac
    local raw_y = geo.y + geo.height * y_frac
    local raw_w = geo.width * w_frac
    local raw_h = geo.height * h_frac

    -- Gap: außen (an Monitorkante) volle SNAP_GAP, an "inneren" Kanten (zwischen
    -- zwei Snap-Zonen) SNAP_GAP/2 auf jeder Seite, macht insgesamt auch SNAP_GAP.
    -- Oben zusätzlich HYPRBARS_HEIGHT, damit Platz für die Fenster-Titelleiste bleibt.
    local left_gap   = (x_frac <= 0) and SNAP_GAP or (SNAP_GAP / 2)
    local right_gap  = (x_frac + w_frac >= 1) and SNAP_GAP or (SNAP_GAP / 2)
    local top_gap    = ((y_frac <= 0) and SNAP_GAP or (SNAP_GAP / 2)) + HYPRBARS_HEIGHT
    local bottom_gap = (y_frac + h_frac >= 1) and SNAP_GAP or (SNAP_GAP / 2)

    local x = math.floor(raw_x + left_gap)
    local y = math.floor(raw_y + top_gap)
    local w = math.floor(raw_w - left_gap - right_gap)
    local h = math.floor(raw_h - top_gap - bottom_gap)

    if w < 1 then w = 1 end
        if h < 1 then h = 1 end

            -- Native Lua-Dispatcher statt os.execute/hyprctl (kein Shell-Roundtrip, kein Parsing-Risiko)
            -- Erst resize (verkleinern), DANN move: verhindert dass Hyprland die Zielposition
            -- an den Bildschirmrand klemmt, während das Fenster noch die alte (größere) Größe hat.
            hl.dispatch(hl.dsp.window.resize({ x = w, y = h }))
            hl.dispatch(hl.dsp.window.move({ x = x, y = y, relative = false }))
            end

            -- ============================================================
            -- 1. Fenster resize mit SUPER + SHIFT + wasd (50 px Schritte)
            -- ============================================================
            -- repeating = true: Taste gedrückt halten wiederholt den Resize-Schritt
            hl.bind(mainMod .. " + SHIFT + s", function()
            local win = hl.get_active_window()
            if win then hl.dispatch(hl.dsp.window.resize({ x = win.size.x, y = win.size.y - 50 })) end
                end, { repeating = true })

            hl.bind(mainMod .. " + SHIFT + w", function()
            local win = hl.get_active_window()
            if win then hl.dispatch(hl.dsp.window.resize({ x = win.size.x, y = win.size.y + 50 })) end
                end, { repeating = true })

            hl.bind(mainMod .. " + SHIFT + a", function()
            local win = hl.get_active_window()
            if win then hl.dispatch(hl.dsp.window.resize({ x = win.size.x - 50, y = win.size.y })) end
                end, { repeating = true })

            hl.bind(mainMod .. " + SHIFT + d", function()
            local win = hl.get_active_window()
            if win then hl.dispatch(hl.dsp.window.resize({ x = win.size.x + 50, y = win.size.y })) end
                end, { repeating = true })

            -- ============================================================
            -- 2. Fensterposition tauschen (swap) mit SUPER + CTRL + wasd
            --    (Tiling → swapwindow/swapcol, Floating → Seiten-Snap)
            -- ============================================================
            -- Layoutbewusster Swap: im Scroller-Layout behält "swapcol" die Fenstergrößen,
-- der generische window.swap tauscht sie fälschlich mit.
local function tiled_swap(direction)
local ws = hl.get_active_workspace()
local layout = ws and ws.tiled_layout
if layout == "scrolling" and (direction == "left" or direction == "right") then
    hl.dispatch(hl.dsp.layout("swapcol " .. (direction == "left" and "l" or "r")))
    else
        hl.dispatch(hl.dsp.window.swap({ direction = direction }))
        end
        end

        hl.bind(mainMod .. " + CTRL + w", function()
        if is_window_floating() then
            snap_window_fraction(0, 0, 1, 0.5)   -- oben (volle Breite, halbe Höhe)
        else
            tiled_swap("up")
            end
            end)

        hl.bind(mainMod .. " + CTRL + s", function()
        if is_window_floating() then
            snap_window_fraction(0, 0.5, 1, 0.5) -- unten
            else
                tiled_swap("down")
                end
                end)

        hl.bind(mainMod .. " + CTRL + a", function()
        if is_window_floating() then
            snap_window_fraction(0, 0, 0.5, 1)   -- links (halbe Breite, volle Höhe)
        else
            tiled_swap("left")
            end
            end)

        hl.bind(mainMod .. " + CTRL + d", function()
        if is_window_floating() then
            snap_window_fraction(0.5, 0, 0.5, 1) -- rechts
            else
                tiled_swap("right")
                end
                end)

        -- ============================================================
        -- 3. Floating-Snaps für die 4 Ecken mit SUPER + CTRL + q/e/x/<
        -- ============================================================
        -- Nur bei floatenden Fenstern: snap_window_fraction() resized/moved
        -- direkt und hart, das würde bei getilten Fenstern das Tiling-Layout
        -- durcheinanderbringen. Analog zum Floating-Check bei den
        -- Seiten-Snaps (SUPER+CTRL+wasd) weiter oben - dort gab's dieselbe
        -- Prüfung schon, hier fehlte sie versehentlich.
        local function cornerSnap(x_frac, y_frac, w_frac, h_frac)
            return function()
                if is_window_floating() then
                    snap_window_fraction(x_frac, y_frac, w_frac, h_frac)
                end
            end
        end
        hl.bind(mainMod .. " + CTRL + q",    cornerSnap(0, 0, 0.5, 0.5))     -- oben links
        hl.bind(mainMod .. " + CTRL + e",    cornerSnap(0.5, 0, 0.5, 0.5))   -- oben rechts
        hl.bind(mainMod .. " + CTRL + less", cornerSnap(0, 0.5, 0.5, 0.5))   -- unten links
        hl.bind(mainMod .. " + CTRL + x",    cornerSnap(0.5, 0.5, 0.5, 0.5)) -- unten rechts


        hl.window_rule({
            name     = "dunst-no-focus",
            match    = { class = "^(Dunst|dunst)$" },
                       float    = true,
                       no_focus = true,
        })

        -- xfdesktop taucht nie als regulärer Client in "hyprctl clients" auf
        -- (Desktop-Fenstertyp) - eine class-basierte Windowrule kann es also
        -- gar nicht matchen. Der Fokus-Grab-Bug ist bekannt und wurde von
        -- Hyprland "closed as not planned":
        -- https://github.com/hyprwm/Hyprland/issues/9326
        -- Fix stattdessen über FocusFixDaemon (C, siehe systemctl-Start oben),
        -- der bei jedem neuen Fenster zwangsweise fokussiert.
