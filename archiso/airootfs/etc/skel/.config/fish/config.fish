# Starship Prompt initialisieren
starship init fish | source
fish_config theme choose trafktux

# --- LS_COLORS (Farben für ls) ---
# Dark:  di = Kraft (#fff495), fi = #fffdf5, ln = Baby Blau, ex/Archive = Carrot Orange
# Light: di = Trafk (#5a3998), fi = Trafk-darkest (#1A0D34), ln = dunkleres Blau, ex/Archive = Carrot Orange
set -g _trafk_ls_dark  "di=38;2;255;244;149:ln=38;2;137;207;240:ex=38;2;237;145;33:fi=38;2;255;253;245:*.zip=38;2;237;145;33:*.tar=38;2;237;145;33:*.gz=38;2;237;145;33:*.7z=38;2;237;145;33:*.rar=38;2;237;145;33"
set -g _trafk_ls_light "di=38;2;90;57;152:ln=38;2;58;124;165:ex=38;2;237;145;33:fi=38;2;26;13;52:*.zip=38;2;237;145;33:*.tar=38;2;237;145;33:*.gz=38;2;237;145;33:*.7z=38;2;237;145;33:*.rar=38;2;237;145;33"

# --- Light/Dark-Umschaltung für Starship + ls ---
# Vor jedem Prompt prüfen (fish >= 4.1 setzt $fish_terminal_color_theme).
# Fallback: dark.
function _trafk_apply_mode --on-event fish_prompt
    set -l mode dark
    if set -q fish_terminal_color_theme
        set mode $fish_terminal_color_theme
    end

    if test "$mode" = light
        set -gx STARSHIP_CONFIG $HOME/.config/starship-light.toml
        set -gx LS_COLORS $_trafk_ls_light
    else
        set -e STARSHIP_CONFIG    # -> Standard: ~/.config/starship.toml
        set -gx LS_COLORS $_trafk_ls_dark
    end
end
