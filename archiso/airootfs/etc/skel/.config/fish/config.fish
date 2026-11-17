# Starship Prompt initialisieren
starship init fish | source
fish_config theme choose trafktux

# --- LS_COLORS (Farben für ls) ---
# di (Ordner): Kraft (#fff495)
# ln (Symlinks): Baby Blau (#89CFF0)
# ex (Ausführbar): Carrot Orange (#ed9121)
# fi (Normale Dateien): Normale Textfarbe (#fffdf5)
# Archive (zip, tar): Carrot Orange
# (Bilder wie jpg/png haben wir absichtlich weggelassen, damit sie die normale Textfarbe nutzen)

set -gx LS_COLORS "di=38;2;255;244;149:ln=38;2;137;207;240:ex=38;2;237;145;33:fi=38;2;255;253;245:*.zip=38;2;237;145;33:*.tar=38;2;237;145;33:*.gz=38;2;237;145;33:*.7z=38;2;237;145;33:*.rar=38;2;237;145;33"