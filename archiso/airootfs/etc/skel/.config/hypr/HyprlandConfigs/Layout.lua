-- Layout.lua
--
-- Strukturelle Fenster-/Workspace-Anordnung: general (Gaps/Border-
-- Verhalten/aktives Layout), dwindle/master/scrolling-Parameter, Misc-
-- Verhalten sowie alle window_rule/layer_rule-Einträge. Farben &
-- Animationen dazu liegen in Looks.lua (dieselben hl.config-Keys lassen
-- sich problemlos über mehrere Aufrufe/Dateien verteilen).

-- Liest das zuletzt gespeicherte Layout aus dem Cache, Fallback "master"
local function read_saved_layout()
    local default = "master"
    local path = os.getenv("HOME") .. "/.cache/hypr/layout_switcher_state"
    local f = io.open(path, "r")
    if not f then
        return default
    end
    local content = f:read("*l")
    f:close()
    if content == nil or content == "" then
        return default
    end
    return content
end

local savedLayout = read_saved_layout()

hl.config({
    general = {
        gaps_in = 6,
        gaps_out = 8,
        border_size = 1,

        resize_on_border = true,
        extend_border_grab_area = 23,
        hover_icon_on_border = true,
        allow_tearing = false,
        layout = savedLayout,
    },
})

hl.config({
    dwindle = { preserve_split = true },
    master = { new_status = "slave" },
    misc = {
        force_default_wallpaper = 0,
        disable_hyprland_logo = true,
        animate_manual_resizes = false,
    },
})

hl.config({
    scrolling = {
        wrap_focus = true,
        column_width = 0.5,
    },
})

hl.layer_rule({
    -- match        = { namespace = "waybar" },  -- alt, TrafkTuxBar nutzt "trafktuxbar"
    match = { namespace = "trafktuxbar" },
    ignore_alpha = 0.5,
    no_anim = false,
})

hl.window_rule({
    name = "rofi-hardcut",
    match = { class = "^(Rofi|rofi)$" },
    no_anim = true,
    stay_focused = true,
})

hl.window_rule({
    name = "suppress-maximize-events",
    match = { class = ".*" },
    suppress_event = "maximize",
})

hl.window_rule({
    name = "move-hyprland-run",
    match = { class = "hyprland-run" },
    move = "20 monitor_h-120",
    float = true,
})

hl.window_rule({
    match = {
        class = "WidgetsDaemon.py",
    },
    float = true,
    pin = true,
})

-- Keine windowrule mehr für Notifications nötig: swaync zeichnet seine
-- Popups und das Control-Center als Layer-Shell-Surfaces (nicht als
-- normale Toplevel-Fenster wie zuvor Dunst), die tauchen also gar
-- nicht erst in "hyprctl clients"/hl.window_rule-Matches auf und
-- können damit auch nie ungewollt Fokus stehlen. Falls swaync auf
-- diesem System doch mal fokussierbar wirkt, ist das über
-- keyboard-interactivity im Compositor/Layer-Protokoll geregelt,
-- nicht über eine Hyprland-windowrule.
--
-- xfdesktop taucht nie als regulärer Client in "hyprctl clients" auf
-- (Desktop-Fenstertyp) - eine class-basierte Windowrule kann es also
-- gar nicht matchen. Der Fokus-Grab-Bug ist bekannt und wurde von
-- Hyprland "closed as not planned":
-- https://github.com/hyprwm/Hyprland/issues/9326
-- Fix stattdessen über FocusFixDaemon (C, siehe systemctl-Start in
-- Autostart.lua), der bei jedem neuen Fenster zwangsweise fokussiert.
