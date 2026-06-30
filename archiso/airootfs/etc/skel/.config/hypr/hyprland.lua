-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
-- COPYRIGHT (C) TRAFKHOP ENTERTAINMENT                    --
-- CONFIGURATION FOR HYPRLAND WM (LUA API)                --
-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --

hl.monitor({
    output   = "eDP-1",
    mode     = "1920x1200@60",
    position = "0x0",
    scale    = 1.2,
})

local terminal    = "kitty"
local fileManager = "thunar"
local menu        = "rofi -show drun"
local openwindows = "rofi -show window"
local launcher  = "python3 ~/.config/rofi/bubble-menu.py --menu launcher"
local powermenu = "python3 ~/.config/rofi/bubble-menu.py --menu powermenu"

-- Alte X11/GTK/XWayland Fallbacks bleiben beim XCursor-Theme
hl.env("XCURSOR_THEME", "TrafkTuxCursor")
hl.env("XCURSOR_SIZE", "35")

-- Native Wayland/Hyprland Apps bekommen das konvertierte Theme!
hl.env("HYPRCURSOR_THEME", "TrafkTuxCursor-Hypr")
hl.env("HYPRCURSOR_SIZE", "35")

hl.env("QT_CURSOR_SIZE", "35")
-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
-- AUTOSTART                                              --
-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --

hl.on("hyprland.start", function()
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

hl.exec_cmd("hyprctl setcursor TrafkTuxCursor 35")

end)

hl.config({
    general = {
        gaps_in     = 8,
        gaps_out    = 15,
        border_size = 0,

        col = {
            active_border   = { colors = {"rgba(fff495ee)"}, angle = 45 },
          inactive_border = "rgba(d6cd7cee)",
        },

        resize_on_border = true,
        extend_border_grab_area = 15,
        hover_icon_on_border = true,
        allow_tearing    = false,
        layout           = "master",
    },

    decoration = {
        rounding       = 15,
        rounding_power = 5,

        active_opacity   = 1.0,
        inactive_opacity = 0.85,

        shadow = {
            enabled      = true,
            range        = 8,
            render_power = 2,
            color        = "rgba(fff495ff)",
        },

        blur = {
            enabled   = false,
            size      = 5,
            passes    = 2,
            vibrancy  = 0.1696,
        },
    },
})

hl.curve("bouncyOvershot", { type = "bezier", points = { {0.175, 0.885}, {0.32, 1.275} } })
hl.curve("squishEase",      { type = "bezier", points = { {0.6, -0.28},  {0.735, 0.045} } })
hl.curve("stretchySpring",  { type = "spring", mass = 1, stiffness = 110, dampening = 13 })

hl.animation({ leaf = "global",        enabled = true,  speed = 10,   bezier = "default" })
hl.animation({ leaf = "windows",       enabled = true,  speed = 5,    spring = "stretchySpring" })
hl.animation({ leaf = "windowsIn",     enabled = true,  speed = 4.5,  spring = "stretchySpring", style = "popin 60%" })
hl.animation({ leaf = "windowsOut",    enabled = true,  speed = 3.5,  bezier = "squishEase",     style = "popin 40%" })
hl.animation({ leaf = "border",        enabled = true,  speed = 4,    bezier = "bouncyOvershot" })
hl.animation({ leaf = "fade",          enabled = true,  speed = 3,    bezier = "default" })
hl.animation({ leaf = "workspaces",    enabled = true,  speed = 5,    spring = "stretchySpring", style = "slide" })

hl.config({
    dwindle = { preserve_split = true },
    master  = { new_status = "slave" },
    misc    = {
        force_default_wallpaper  = 0,
            disable_hyprland_logo    = true,
            animate_manual_resizes   = false,
    },
})

hl.config({
    plugin = {
        hyprbars = {
            bar_height            = 18,
            bar_color             = "rgba(fff495ee)",
          ["col.text"]          = "rgba(111111ee)",
          bar_text_size         = 15,
          bar_text_font         = "Noto Sans",
          bar_buttons_alignment = "right",
        }
    }
})

-- Buttons separat mit add_button definieren
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
                              icon     = "FS1",
                              action   = "hyprctl dispatch 'hl.dsp.window.fullscreen({ mode = 1 })'",
})
hl.plugin.hyprbars.add_button({
    bg_color = "rgba(ffffffee)",
                              fg_color = "rgba(111111ee)",
                              size     = 12,
                              icon     = "FS0",
                              action   = "hyprctl dispatch 'hl.dsp.window.fullscreen({ mode = 0 })'",
})
hl.plugin.hyprbars.add_button({
    bg_color = "rgba(ffffffee)",
                              fg_color = "rgba(111111ee)",
                              size     = 12,
                              icon     = "⇆",
                              action   = "hyprctl dispatch 'hl.dsp.layout(\"swapwithmaster\", \"master\")'",
})

hl.config({
    input = {
        kb_layout    = "de",
        follow_mouse = 0,
        sensitivity  = 0,
        touchpad     = {
            natural_scroll = true,
        },
    },
})

hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })

local mainMod = "SUPER"

hl.bind(mainMod .. " + space",  hl.dsp.exec_cmd(terminal))
hl.bind(mainMod .. " + F",      hl.dsp.exec_cmd(fileManager))
hl.bind(mainMod .. " + tab",    hl.dsp.exec_cmd(openwindows))
hl.bind(mainMod .. " + SHIFT + tab", hl.dsp.exec_cmd(launcher))
hl.bind(mainMod .. " + escape",         hl.dsp.exec_cmd(powermenu))
hl.bind(mainMod .. " + SHIFT + code:49", hl.dsp.window.fullscreen({ mode = 0 }))
hl.bind(mainMod .. " + code:49",         hl.dsp.window.fullscreen({ mode = 1 }))



local function focusOrCycle(direction, monocleAction)
return function()
local ws = hl.get_active_special_workspace() or hl.get_active_workspace()
if ws ~= nil and ws.tiled_layout == "monocle" then
    hl.dispatch(hl.dsp.layout(monocleAction))
    else
        hl.dispatch(hl.dsp.focus({ direction = direction }))
        end
        end
        end

        hl.bind(mainMod .. " + a", focusOrCycle("left",  "cycleprev"))
        hl.bind(mainMod .. " + d", focusOrCycle("right", "cyclenext"))
        hl.bind(mainMod .. " + w", focusOrCycle("up",    "cycleprev"))
        hl.bind(mainMod .. " + s", focusOrCycle("down",  "cyclenext"))

        hl.bind(mainMod .. " + ALT + 1", hl.dsp.exec_cmd("bash ~/.config/hypr/layout_switcher.sh master"))
        hl.bind(mainMod .. " + ALT + 2", hl.dsp.exec_cmd("bash ~/.config/hypr/layout_switcher.sh dwindle"))
        hl.bind(mainMod .. " + ALT + 3", hl.dsp.exec_cmd("bash ~/.config/hypr/layout_switcher.sh scroller"))
        hl.bind(mainMod .. " + ALT + 4", hl.dsp.exec_cmd("bash ~/.config/hypr/layout_switcher.sh floating"))
        hl.bind(mainMod .. " + ALT + 5", hl.dsp.exec_cmd("bash ~/.config/hypr/layout_switcher.sh bigscreen"))

        for i = 1, 9 do
            local key = i % 10
            hl.bind(mainMod .. " + " .. key,         hl.dsp.focus({ workspace = i }))
            hl.bind(mainMod .. " + SHIFT + " .. key, hl.dsp.window.move({ workspace = i }))
            end

            hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag(),   { mouse = true })
            hl.bind(mainMod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

            hl.bind("XF86AudioRaiseVolume",  hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), { locked = true, repeating = true })
            hl.bind("XF86AudioLowerVolume",  hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"),      { locked = true, repeating = true })
            hl.bind("XF86AudioMute",         hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"),     { locked = true, repeating = true })
            hl.bind("XF86MonBrightnessUp",   hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%+"),                  { locked = true, repeating = true })
            hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%-"),                  { locked = true, repeating = true })

            hl.bind("XF86AudioPlay", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
            hl.bind("XF86AudioNext", hl.dsp.exec_cmd("playerctl next"),        { locked = true })
            hl.bind("XF86AudioPrev", hl.dsp.exec_cmd("playerctl previous"),    { locked = true })

            hl.bind(mainMod .. " + Print",         hl.dsp.exec_cmd('grim -g "$(slurp -d)" - | wl-copy'))
            hl.bind(mainMod .. " + SHIFT + Print", hl.dsp.exec_cmd('bash -c "mkdir -p ~/Pictures && grim -g \\"$(slurp -d)\\" ~/Pictures/$(date +%Y%m%d_%H%M%S).png"'))

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
