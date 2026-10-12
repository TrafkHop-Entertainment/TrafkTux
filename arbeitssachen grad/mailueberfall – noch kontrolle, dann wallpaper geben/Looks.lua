-- Looks.lua
--
-- Alles rein Optische: Cursor-Theme, Farben/Decoration, Animationen,
-- sowie die visuellen Plugins (hyprbars, hyprglass, dynamic_cursors,
-- hyprfocus, hyprexpo-Optik). Funktionale/nicht-visuelle Plugin-
-- Einstellungen (z.B. kinetic-scroll, hyprgrass-Sensitivity) liegen
-- stattdessen in Plugins.lua.

-- Cursor-Umgebungsvariablen
hl.env("XCURSOR_THEME", "TrafkTuxCursorLegacy")
hl.env("XCURSOR_SIZE", "35")
hl.env("HYPRCURSOR_THEME", "TrafkTuxCursor")
hl.env("HYPRCURSOR_SIZE", "35")
hl.env("QT_CURSOR_SIZE", "35")

hl.env("QT_QPA_PLATFORMTHEME", "qt6ct")

-- Allgemeines Aussehen (Rand-Farben + Decoration). Die strukturellen
-- general-Einstellungen (gaps, border_size, layout, ...) liegen in
-- Layout.lua - Hyprland-Config ist additiv, mehrere hl.config({general=...})
-- Aufrufe ergänzen sich wie gewohnt.
hl.config({
    general = {
        col = {
            active_border = { colors = { "rgba(fff495ee)" }, angle = 45 },
            inactive_border = "rgba(d6cd7cee)",
        },
    },

    decoration = {
        rounding = 15,
        rounding_power = 5,

        active_opacity = 0.9865,
        inactive_opacity = 0.85,

        shadow = {
            enabled = true,
            range = 4,
            render_power = 2,
            color = "rgba(fff495ff)",
        },

        blur = {
            enabled = false,
            size = 3,
            passes = 2,
            vibrancy = 0.1696,
        },
    },
})

-- Animationskurven
hl.curve("bouncyOvershot", { type = "bezier", points = { { 0.175, 0.885 }, { 0.32, 1.275 } } })
hl.curve("squishEase", { type = "bezier", points = { { 0.6, -0.28 }, { 0.735, 0.045 } } })
hl.curve("stretchySpring", { type = "spring", mass = 1, stiffness = 110, dampening = 13 })
hl.curve("smoothInOut", { type = "bezier", points = { { 0.42, 0.0 }, { 0.58, 1.0 } } })

-- Animationen
hl.animation({ leaf = "global", enabled = true, speed = 10, bezier = "default" })
hl.animation({ leaf = "windows", enabled = true, speed = 5, spring = "stretchySpring" })
hl.animation({ leaf = "windowsIn", enabled = true, speed = 4.5, spring = "stretchySpring", style = "popin 60%" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 3.5, bezier = "squishEase", style = "popin 40%" })
hl.animation({ leaf = "border", enabled = true, speed = 4, bezier = "bouncyOvershot" })
hl.animation({ leaf = "fade", enabled = true, speed = 3, bezier = "default" })
hl.animation({ leaf = "workspaces", enabled = true, speed = 5, spring = "stretchySpring", style = "slide" })

-- hyprbars: Titelleiste mit Buttons
hl.config({
    plugin = {
        hyprbars = {
            bar_height = 18,
            bar_color = "rgba(fff495ee)",
            ["col.text"] = "rgba(111111ee)",
            bar_text_size = 15,
            bar_text_font = "Noto Sans",
            bar_buttons_alignment = "right",
        },
    },
})

hl.plugin.hyprbars.add_button({
    bg_color = "rgba(ff5555ee)",
    fg_color = "rgba(111111ee)",
    size = 15,
    icon = "✕",
    action = "hyprctl dispatch 'hl.dsp.window.close()'",
})
hl.plugin.hyprbars.add_button({
    bg_color = "rgba(7091E5FF)",
    fg_color = "rgba(111111ee)",
    size = 15,
    icon = "m",
    action = "hyprctl dispatch 'hl.dsp.exec_cmd(\"hyprland-minimizer\")'",
})
hl.plugin.hyprbars.add_button({
    bg_color = "rgba(59E52AFF)",
    fg_color = "rgba(111111ee)",
    size = 15,
    icon = "FS1",
    action = "hyprctl dispatch 'hl.dsp.window.fullscreen({ mode = 1 })'",
})
hl.plugin.hyprbars.add_button({
    bg_color = "rgba(ffffffee)",
    fg_color = "rgba(111111ee)",
    size = 15,
    icon = "⇆",
    action = 'hyprctl dispatch \'hl.dsp.layout("swapwithmaster", "master")\'',
})
hl.plugin.hyprbars.add_button({
    bg_color = "rgba(FFAE5AFF)",
    fg_color = "rgba(111111ee)",
    size = 15,
    icon = "📌",
    action = "hyprctl dispatch 'hl.dsp.exec_cmd(\"~/.config/hypr/PictureInPicture.sh\")'",
})

-- hyprglass: Liquid-Glass-Effekt (Blur, Refraktion, Fresnel-Glow) auf Fenstern/Layern
if hl.plugin.hyprglass then
    local hg = hl.plugin.hyprglass

    hg.config({
        enabled = true,
        default_theme = "dark",

        blur_strength = 0,
        blur_iterations = 0,
        refraction_strength = 1,
        chromatic_aberration = 0.15,
        fresnel_strength = 1,
        specular_strength = 1,
        glass_opacity = 1,
        edge_thickness = 0.35,
        lens_distortion = 1,

        dark = {
            brightness = 1,
            contrast = 1,
            saturation = 1,
            vibrancy = 1,
            vibrancy_darkness = 1,
            adaptive_dim = 0,
            adaptive_boost = 0,
        },
        light = {
            brightness = 1,
            contrast = 1,
            saturation = 1,
            vibrancy = 1,
            vibrancy_darkness = 1,
            adaptive_dim = 0,
            adaptive_boost = 0,
        },

        layers = { enabled = true },
    })

    -- wb-daemon: die kleinen Bubble-Widgets (Settings, Lautstärke,
    -- Netzwerk, ...) aus WidgetsDaemon.py sollen den Glass-Effekt
    -- NICHT bekommen - der sichtbare "Rahmen" darauf war genau dieser
    -- Effekt, nicht ein GTK-Fokus-/Hover-Rahmen.
    hg.layer("wb-daemon", { exclude = true })
    hg.layer("trafktuxbar", { exclude = true })
    hg.layer("TrafkTuxLauncher", { exclude = true })

    -- swaync: gleicher Grund wie bei wb-daemon oben - der Glow um die
    -- Notification-Blase kam von hyprglass, nicht von style.css. swaync
    -- läuft als zwei getrennte Layer-Shell-Surfaces (Popups + Control-
    -- Center), beide müssen ausgeschlossen werden.
    hg.layer("swaync-notification-window", { exclude = true })
    hg.layer("swaync-control-center", { exclude = true })
end

-- hypr-dynamic-cursors: physikalisch simulierter Cursor + Shake-to-Find
if hl.plugin.dynamic_cursors then
    hl.config({
        plugin = {
            dynamic_cursors = {

                enabled = true,
                mode = "tilt",
                threshold = 1,

                rotate = {
                    length = 45,
                    offset = 0.0,
                },

                tilt = {
                    limit = 850,
                    activation = "negative_quadratic",
                    window = 85,
                    full = 45,
                },

                stretch = {
                    limit = 3000,
                    activation = "quadratic",
                    window = 100,
                },

                shake = {
                    enabled = false,

                    threshold = 5.0,
                    base = 0.1,
                    speed = 1.0,
                    influence = 1.0,
                    limit = 0.0,
                    timeout = 3500,

                    effects = true,
                    ipc = true,
                },

                hyprcursor = {
                    nearest = 2,
                    enabled = true,
                    resolution = -1,
                    fallback = "clientside",
                },
            },
        },
    })
end

-- Eigene dynamic_cursors/shake-Overrides (z.B. von der "Appearance &
-- Language"-Einstellung gesetzt). Lebt bewusst NICHT in HyprlandConfigs/
-- (also nicht im Repo/Paket) - ein Systemupdate ersetzt nur hyprland.lua
-- + HyprlandConfigs/, diese Datei bleibt unangetastet. MUSS NACH dem
-- obigen dynamic_cursors-Block stehen - Hyprland-Config ist additiv,
-- der Override hier ersetzt gezielt nur enabled/shake.enabled, alle
-- anderen Felder oben (rotate/tilt/stretch/hyprcursor/...) bleiben
-- unangetastet. pcall(dofile, ...) statt require(): siehe Begründung in
-- Autostart.lua/Display.lua - sicher, falls die Datei (noch) nicht
-- existiert.
pcall(dofile, os.getenv("HOME") .. "/.config/hypr/HyprlandUserConfigs/UserLooks.lua")

-- hyprfocus: Animation beim Fensterfokuswechsel
hl.config({
    plugin = {
        hyprfocus = {

            keyboard_focus_animation = "slide",
            mouse_focus_animation = "slide",

            only_on_monitor_change = false,
            fade_opacity = 0.65,
            slide_height = -5,
        },
    },
})
hl.animation({ leaf = "hyprfocusIn", enabled = true, speed = 1.5, bezier = "smoothInOut" })
hl.animation({ leaf = "hyprfocusOut", enabled = true, speed = 1.5, bezier = "smoothInOut" })

-- hyprexpo: Expose-artige Workspace-Übersicht im Grid (nur die Optik;
-- Tastatur-Submap & der Öffnen-Bind liegen aus funktionalen Gründen in
-- Controls.lua, dort nochmal eigenständig per "if hl.plugin.hyprexpo"
-- abgesichert)
if hl.plugin and hl.plugin.hyprexpo then
    hl.config({
        plugin = {
            hyprexpo = {

                columns = 3,
                gaps_in = 23,
                gaps_out = 35,

                bg_col = "rgb(23163B)",

                workspace_method = "first 1",

                gesture_distance = 200,
                cancel_key = "escape",
                show_cursor = 1,

                keynav_enable = 1,
                keynav_wrap_h = 1,
                keynav_wrap_v = 1,
                keynav_reading_order = 0,

                border_width = 5,
                border_color_current = "rgb(5a3998)",
                border_color_focus = "rgb(fff495)",
                border_color_hover = "rgb(fff495)",
                tile_rounding = 65,

                label_enable = 1,
                label_text_mode = "index",
            },
        },
    })
end

-- AppWallpaper (hyprwinwrap-Toggle: App-Fenster statt Pictures als
-- Hintergrund) ist rein visuell und gehört deshalb thematisch hierher.
-- Bewusst ganz am Ende dieser Datei, damit sie exakt wie im alten
-- Monolithen zuletzt ausgeführt wird (relevant für die window_rule, die
-- sie selbst registriert).
require("HyprlandConfigs.AppWallpaper")
