-- Hyprland-Konfiguration (Lua API)

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

        local terminal    = "kitty"
        local fileManager = "thunar"
        local menu        = "rofi -show drun"
        local openwindows = "rofi -show window"
        -- --x11 ist wichtig: rofis natives Wayland-Backend implementiert nur
        -- wl_pointer, kein wl_touch (offener Upstream-Bug). Über XWayland
        -- emuliert Hyprland Touch->Pointer automatisch, deshalb hier fest an.
        local launcher  = "python3 ~/.config/rofi/bubble-menu.py --menu launcher --x11"
        local powermenu = "python3 ~/.config/rofi/bubble-menu.py --menu powermenu --x11"

        hl.env("XCURSOR_THEME", "TrafkTuxCursor")
        hl.env("XCURSOR_SIZE", "35")
        hl.env("HYPRCURSOR_THEME", "TrafkTuxCursor")
        hl.env("HYPRCURSOR_SIZE", "35")
        hl.env("QT_CURSOR_SIZE", "35")

        -- -- -- -- -- -- -- -- -- -- --
        -- AUTOSTART                  --
        -- -- -- -- -- -- -- -- -- -- --

        hl.on("hyprland.start", function()
        hl.exec_cmd("bash -c 'hyprctl setcursor TrafkTuxCursor 35' &")
        hl.exec_cmd("bash -c 'hyprctl plugin list | grep -q hyprbars || (hyprpm reload -n && sleep 1 && hyprctl reload)'")
        hl.exec_cmd("bash ~/.config/hypr/random_wallpaper.sh")
        hl.exec_cmd("killall waybar; waybar")
        hl.exec_cmd("killall waybar_autohide; ~/.config/waybar/scripts/waybar_autohide")
        hl.exec_cmd("dunst")
        hl.exec_cmd("hypridle")
        hl.exec_cmd("/usr/lib/polkit-kde-authentication-agent-1")
        hl.exec_cmd("nm-applet --indicator")
        hl.exec_cmd("blueman-applet")
        hl.exec_cmd("wl-paste --watch cliphist store")
        hl.exec_cmd("wl-clip-persist --clipboard regular")
        hl.exec_cmd("swayosd-server")
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

                resize_on_border        = true,
                extend_border_grab_area = 15,
                hover_icon_on_border    = true,
                allow_tearing           = false,
                layout                  = savedLayout,
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
                    enabled  = false,
                    size     = 5,
                    passes   = 2,
                    vibrancy = 0.1696,
                },
            },
        })

        hl.curve("bouncyOvershot", { type = "bezier", points = { {0.175, 0.885}, {0.32, 1.275} } })
        hl.curve("squishEase",     { type = "bezier", points = { {0.6, -0.28},  {0.735, 0.045} } })
        hl.curve("stretchySpring", { type = "spring", mass = 1, stiffness = 110, dampening = 13 })

        hl.animation({ leaf = "global",     enabled = true, speed = 10,  bezier = "default" })
        hl.animation({ leaf = "windows",    enabled = true, speed = 5,   spring = "stretchySpring" })
        hl.animation({ leaf = "windowsIn",  enabled = true, speed = 4.5, spring = "stretchySpring", style = "popin 60%" })
        hl.animation({ leaf = "windowsOut", enabled = true, speed = 3.5, bezier = "squishEase",     style = "popin 40%" })
        hl.animation({ leaf = "border",     enabled = true, speed = 4,   bezier = "bouncyOvershot" })
        hl.animation({ leaf = "fade",       enabled = true, speed = 3,   bezier = "default" })
        hl.animation({ leaf = "workspaces", enabled = true, speed = 5,   spring = "stretchySpring", style = "slide" })

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
            no_anim      = true,
        })

        hl.permission("/usr/(bin|local/bin)/hyprpm", "plugin", "allow")

        if hl.plugin and hl.plugin.hyprgrass then
            hl.config({
                plugin = {
                    hyprgrass = {
                        sensitivity = 15,
                        edge_margin = 165,
                    },
                },
            })

            -- Wisch vom unteren Bildschirmrand nach oben -> pingt den
            -- waybar-autohide-Daemon per Realtime-Signal an.
            hl.plugin.hyprgrass.bind({
                pattern = { kind = "edge", origin = "d", direction = "u" },
                action = hl.dsp.exec_cmd(
                    "bash -c 'p=/tmp/waybar-autohide.pid; [ -f \"$p\" ] && kill -RTMIN $(cat \"$p\")'"
                ),
            })
            else
                hl.exec_cmd("bash -c \"notify-send 'Hyprland' 'hyprgrass nicht geladen - Touch-Gesten deaktiviert (siehe: hyprctl plugin list)' -u critical || true\"")
                end

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
                                              size     = 12,
                                              icon     = "📌",
                                              action   = "hyprctl dispatch 'hl.dsp.exec_cmd(\"~/.config/hypr/pip.sh\")'",
                })

                hl.config({
                    input = {
                        kb_layout    = "de",
                        follow_mouse = 0,
                        sensitivity  = 0,
                        touchpad = {
                            natural_scroll = true,
                        },
                    },
                })

                hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })

                local mainMod = "SUPER"

                hl.bind(mainMod .. " + space",           hl.dsp.exec_cmd(terminal))
                hl.bind(mainMod .. " + F",               hl.dsp.exec_cmd(fileManager))
                hl.bind(mainMod .. " + SHIFT + tab",     hl.dsp.exec_cmd(openwindows))
                hl.bind(mainMod .. " + tab",             hl.dsp.exec_cmd(launcher))
                hl.bind(mainMod .. " + escape",          hl.dsp.exec_cmd(powermenu))
                hl.bind(mainMod .. " + SHIFT + code:49", hl.dsp.window.fullscreen({ mode = 0 }))
                hl.bind(mainMod .. " + code:49",         hl.dsp.window.fullscreen({ mode = 1 }))
                hl.bind(mainMod .. " + ALT + tab",       hl.dsp.exec_cmd("hyprland-minimizer"))

                hl.bind(mainMod .. " + R", hl.dsp.exec_cmd('kitty -e bash -c "/run/media/hopx/HopxSSD/TrafkSite/Projects/TrafkTux/TrafkTux/syncwithsystem.sh"'), { description = "Sync with system" })

                hl.config({
                    scrolling = {
                        wrap_focus   = true,
                        column_width = 0.5,
                    },
                })

                -- Fokus-Wechsel, der nie "stecken bleibt":
                -- - Im Monocle-Layout gibt es keine räumliche Nachbarschaft, also cyclen wir.
                -- - Im Scrolling-Layout (hyprscroller) nutzen wir dessen eigene "focus l/r"-
                --   Nachricht, weil die scrolling.wrap_focus-Option respektiert und am Ende
                --   des Tapes wieder umspringt.
                -- - In allen anderen Layouts (Master, Dwindle, ...) wird für links/rechts
                --   ebenfalls gecycled statt hl.dsp.focus({direction=...}) zu nutzen: der
                --   generische Directional-Focus springt am Rand oft zurück zum vorherigen
                --   Fenster statt weiterzuwandern, wodurch man zwischen zwei Fenstern hin-
                --   und herpingpongt statt durchzuwechseln. cyclenext/cycleprev läuft immer
                --   linear durch alle Fenster.
                local function focusOrCycle(direction, cycleAction)
                return function()
                local ws = hl.get_active_special_workspace() or hl.get_active_workspace()

                if ws ~= nil and ws.tiled_layout == "scrolling" and (direction == "left" or direction == "right") then
                    local dir = (direction == "left") and "l" or "r"
                    hl.dispatch(hl.dsp.layout("focus " .. dir))
                    elseif direction == "left" or direction == "right" then
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

                            -- Touch: 2-Finger-Wisch links/rechts (irgendwo auf dem Screen, nicht Edge-
                            -- gebunden). Ein 1-Finger-Edge-Swipe startet direkt auf dem Fenster am
                            -- Bildschirmrand, wodurch der Touch zuerst als Klick auf dieses Fenster
                            -- durchgereicht wird, statt als Geste erkannt zu werden - man bleibt also
                            -- an genau diesem Fenster "kleben". 2 Finger sind dagegen nie ein normaler
                            -- Klick und funktionieren an jeder Stelle des Bildschirms.
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
                                    hl.bind("XF86AudioNext", hl.dsp.exec_cmd("playerctl next"),       { locked = true })
                                    hl.bind("XF86AudioPrev", hl.dsp.exec_cmd("playerctl previous"),   { locked = true })

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
