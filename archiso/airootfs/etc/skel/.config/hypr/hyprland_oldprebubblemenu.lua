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
        scale    = 1.2,
})

-- Programme & Befehle
local terminal       = "kitty"
local fileManager    = "thunar"
local menu           = "rofi -show drun"
local openwindows    = "rofi -show window"
local launcher_cmd   = "sh -c 'echo \"show\" > \"${XDG_RUNTIME_DIR:-/tmp}/rofi-bubble-launcher.fifo\"'"
local powermenu_cmd  = "sh -c 'echo \"show\" > \"${XDG_RUNTIME_DIR:-/tmp}/rofi-bubble-powermenu.fifo\"'"
local launcher       = "python3 ~/.config/rofi/bubble-menu.py --menu launcher --x11"
local powermenu      = "python3 ~/.config/rofi/bubble-menu.py --menu powermenu --x11"

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
        hl.exec_cmd("bash ~/.config/hypr/random_wallpaper.sh")
        hl.exec_cmd("killall waybar; waybar")
        hl.exec_cmd("dunst")
        hl.exec_cmd("hypridle")
        hl.exec_cmd("/usr/lib/polkit-kde-authentication-agent-1")
        hl.exec_cmd("nm-applet --indicator")
        hl.exec_cmd("blueman-applet")
        hl.exec_cmd("wl-paste --watch cliphist store")
        hl.exec_cmd("wl-clip-persist --clipboard regular")
        hl.exec_cmd("swayosd-server")
        hl.exec_cmd("systemctl --user start wb-daemon.service wb-autohide.service")
        hl.exec_cmd("cp ~/.config/rofi/assets/bubble-normal.png /tmp/bubble-normal.png")
        hl.exec_cmd("cp ~/.config/rofi/assets/bubble-selected.png /tmp/bubble-selected.png")
        hl.exec_cmd("python3 ~/.config/rofi/bubble-menu.py --menu launcher --daemon --x11 &")
        hl.exec_cmd("python3 ~/.config/rofi/bubble-menu.py --menu powermenu --daemon --x11 &")
end)

-- Allgemeines Aussehen & Verhalten
hl.config({
        general = {
            gaps_in     = 8,
            gaps_out    = 15,
            border_size = 0,

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
                range        = 8,
                render_power = 2,
                color        = "rgba(fff495ff)",
            },

            blur = {
                enabled  = false,
                size     = 5,
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
            no_warps = true,
        },
})

hl.layer_rule({
        match        = { namespace = "waybar" },
        ignore_alpha = 0.5,
        no_anim      = false,
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
                bar_height            = 15,
                bar_color             = "rgba(fff495ee)",
                ["col.text"]          = "rgba(111111ee)",
                bar_text_size         = 12,
                bar_text_font         = "Noto Sans",
                bar_buttons_alignment = "right",
            },
        },
})

hl.plugin.hyprbars.add_button({
        bg_color = "rgba(ff5555ee)",
        fg_color = "rgba(111111ee)",
        size     = 12,
        icon     = "✕",
        action   = "hyprctl dispatch 'hl.dsp.window.close()'",
})
hl.plugin.hyprbars.add_button({
        bg_color = "rgba(ffffffee)",
        fg_color = "rgba(111111ee)",
        size     = 12,
        icon     = "m",
        action   = "hyprctl dispatch 'hl.dsp.exec_cmd(\"hyprland-minimizer\")'",
})
hl.plugin.hyprbars.add_button({
        bg_color = "rgba(ffffffee)",
        fg_color = "rgba(111111ee)",
        size     = 10,
        icon     = "FS1",
        action   = "hyprctl dispatch 'hl.dsp.window.fullscreen({ mode = 1 })'",
})
hl.plugin.hyprbars.add_button({
        bg_color = "rgba(ffffffee)",
        fg_color = "rgba(111111ee)",
        size     = 8,
        icon     = "⇆",
        action   = "hyprctl dispatch 'hl.dsp.layout(\"swapwithmaster\", \"master\")'",
})
hl.plugin.hyprbars.add_button({
        bg_color = "rgba(ffffffee)",
        fg_color = "rgba(111111ee)",
        size     = 12,
        icon     = "📌",
        action   = "hyprctl dispatch 'hl.dsp.exec_cmd(\"~/.config/hypr/pip.sh\")'",
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
hl.bind(mainMod .. " + CTRL + code:49",  hl.dsp.exec_cmd("hyprctl dispatch 'hl.dsp.exec_cmd(\"~/.config/hypr/pip.sh\")'"))

-- Waybar-Autohide dauerhaft sperren/entsperren
hl.bind(mainMod .. " + ALT + tab", hl.dsp.exec_cmd(
        "bash -c 'p=/tmp/waybar-autohide.pid; [ -f \"$p\" ] && kill -RTMIN+1 $(cat \"$p\")'"
    ), { description = "Waybar-Autohide sperren/entsperren" })

hl.bind(mainMod .. " + R", hl.dsp.exec_cmd('kitty -e bash -c "/run/media/hopx/HopxSSD/TrafkSite/Projects/TrafkTux/TrafkTux/syncwithsystem.sh"'), { description = "Sync with system" })

hl.bind(mainMod .. " + H", hl.dsp.exec_cmd("bash ~/.config/waybar/scripts/hideall.sh toggle"), { description = "Alle Fenster verstecken/wiederherstellen" })

hl.config({
        scrolling = {
            wrap_focus   = true,
            column_width = 0.5,
        },
})

-- Fokus-Wechsel: layoutabhängig zwischen movefocus und cycle wählen
local function focusOrCycle(direction, cycleAction)
    return function()
        local ws = hl.get_active_special_workspace() or hl.get_active_workspace()

        if ws ~= nil and ws.tiled_layout == "scrolling" and (direction == "left" or direction == "right") then
            local dir = (direction == "left") and "l" or "r"
            hl.dispatch(hl.dsp.layout("focus " .. dir))
        elseif ws ~= nil and ws.tiled_layout == "monocle" and (direction == "left" or direction == "right") then
            hl.dispatch(hl.dsp.layout(cycleAction))
        else
            hl.dispatch(hl.dsp.focus({ direction = direction }))
        end
    end
end

hl.bind(mainMod .. " + a", focusOrCycle("left",  "cycleprev"))
hl.bind(mainMod .. " + d", focusOrCycle("right", "cyclenext"))
hl.bind(mainMod .. " + w", focusOrCycle("up",    "cycleprev"))
hl.bind(mainMod .. " + s", focusOrCycle("down",  "cyclenext"))

-- Touch: 2-Finger-Wisch links/rechts für Fokuswechsel
if hl.plugin and hl.plugin.hyprgrass then
    hl.plugin.hyprgrass.bind({
            pattern = { kind = "swipe", fingers = 2, direction = "r" },
            action = focusOrCycle("right", "cyclenext"),
    })

    hl.plugin.hyprgrass.bind({
            pattern = { kind = "swipe", fingers = 2, direction = "l" },
            action = focusOrCycle("left", "cycleprev"),
    })
end

-- Layout wechseln
hl.bind(mainMod .. " + ALT + 1", hl.dsp.exec_cmd("bash ~/.config/hypr/layout_switcher.sh master"))
hl.bind(mainMod .. " + ALT + 2", hl.dsp.exec_cmd("bash ~/.config/hypr/layout_switcher.sh dwindle"))
hl.bind(mainMod .. " + ALT + 3", hl.dsp.exec_cmd("bash ~/.config/hypr/layout_switcher.sh scroller"))
hl.bind(mainMod .. " + ALT + 4", hl.dsp.exec_cmd("bash ~/.config/hypr/layout_switcher.sh floating"))
hl.bind(mainMod .. " + ALT + 5", hl.dsp.exec_cmd("bash ~/.config/hypr/layout_switcher.sh bigscreen"))

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
    -- Netzwerk, ...) aus widgets_daemon.py sollen den Glass-Effekt
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
                        enabled = true,

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

                mode = "slide",

                only_on_monitor_change = false,
                fade_opacity = 0.65,
                slide_height = -5,

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
        class = "widgets_daemon.py",
    },
    float = true,
    pin = true,
})
