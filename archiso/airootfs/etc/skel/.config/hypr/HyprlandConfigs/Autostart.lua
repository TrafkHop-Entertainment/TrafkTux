-- Autostart.lua
--
-- Alles, was beim Hyprland-Start (einmalig) ausgeführt wird, plus die
-- Compositor-Event-Hooks für Systemsounds (die feuern zwar laufend,
-- gehören inhaltlich aber zum selben "Hintergrunddienste"-Themenblock).

hl.on("hyprland.start", function()
    hl.exec_cmd("bash -c 'hyprctl setcursor TrafkTuxCursor 35' &")
    hl.exec_cmd("gsettings set org.gnome.desktop.interface cursor-theme 'TrafkTuxCursorLegacy'")
    hl.exec_cmd("gsettings set org.gnome.desktop.interface cursor-size 35")
    hl.exec_cmd("bash -c 'hyprctl plugin list | grep -q hyprbars || (hyprpm reload -n && sleep 1 && hyprctl reload)'")
    hl.exec_cmd(
        "bash -c 'hyprctl plugin list | grep -q kinetic-scroll || (hyprpm reload -n && sleep 1 && hyprctl reload)'"
    )
    hl.exec_cmd("xfdesktop")
    hl.exec_cmd("bash /usr/local/lib/trafktux/OptionalSync.sh --watch")
    hl.exec_cmd("bash ~/.config/hypr/Wallpapers.sh")
    -- TrafkTuxBar ersetzt waybar (siehe TrafkTuxBar.c/.jsonc) - alte
    -- waybar-Zeile vorerst nur auskommentiert, nicht geloescht.
    -- hl.exec_cmd("killall waybar; waybar")
    --
    -- WICHTIG - Reihenfolge: erst die Assets nach /tmp kopieren, DANACH
    -- erst TrafkTuxBar starten. Vorher stand der Start-Befehl vor den
    -- cp-Zeilen - TrafkTuxBar laedt /tmp/Bar.png und die Blasen-Bilder
    -- aber SYNCHRON beim Start (bubble_assets_load()/nine_slice_load()
    -- in main()) und beendet sich sofort mit EXIT_FAILURE, wenn eine der
    -- Dateien noch fehlt. Da alle hl.exec_cmd()-Aufrufe hier nebenlaeufig
    -- feuern, war das ein reiner Zufalls-Wettlauf: mal war der (winzige)
    -- cp schneller fertig als GTK hochgefahren ist, mal nicht. Jetzt erst
    -- kopieren, dann erst starten - kein Rennen mehr moeglich.
    -- Assets liegen jetzt unter ~/.config/Assets/ (gleiche Dateinamen,
    -- neuer Ordner - vorher ~/.config/rofi/assets/).
    -- BUGFIX: hier wurden Glow1/Glow2 bisher als reine Kopien von
    -- TrafkBubble1/2 (normal) nach /tmp kopiert - das hat bei JEDEM
    -- Hyprland-Start die echten Glow-Bilder in /tmp überschrieben,
    -- weshalb die ausgewählte Blase optisch nie anders aussah als die
    -- unselektierte. Jetzt werden die echten TrafkBubbleGlow1/2.png
    -- kopiert.
    hl.exec_cmd("cp ~/.config/Assets/bubble-normal.png /tmp/bubble-normal.png")
    hl.exec_cmd("cp ~/.config/Assets/bubble-selected.png /tmp/bubble-selected.png")
    hl.exec_cmd("cp ~/.config/Assets/TrafkBubble1.png /tmp/TrafkBubble1.png")
    hl.exec_cmd("cp ~/.config/Assets/TrafkBubble2.png /tmp/TrafkBubble2.png")
    hl.exec_cmd("cp ~/.config/Assets/TrafkBubbleGlow1.png /tmp/TrafkBubbleGlow1.png")
    hl.exec_cmd("cp ~/.config/Assets/TrafkBubbleGlow2.png /tmp/TrafkBubbleGlow2.png")
    hl.exec_cmd("cp ~/.config/Assets/Right.png /tmp/Right.png")
    hl.exec_cmd("cp ~/.config/Assets/Left.png /tmp/Left.png")
    -- Bar.png liegt direkt in deinem TrafkTuxBar-Ordner.
    hl.exec_cmd("cp ~/.config/TrafkTuxBar/Bar.png /tmp/Bar.png")
    hl.exec_cmd("killall TrafkTuxBar; ~/.config/TrafkTuxBar/TrafkTuxBar &")
    -- TrafkTuxLauncher-Daemon: haelt AppLauncher- und PowerMenu-Fenster
    -- fertig gebaut & versteckt im Hintergrund, launcher_cmd/powermenu_cmd
    -- in Controls.lua schicken nur noch ein "zeig dich"-Signal per Unix-
    -- Socket - kein GTK-Neustart mehr pro Tastendruck, dadurch quasi
    -- instant.
    -- Muss NACH den cp-Zeilen oben stehen (lädt /tmp/Trafk*.png beim
    -- Start synchron, genau wie TrafkTuxBar - selbes Wettlauf-Problem,
    -- selbe Lösung: erst kopieren, dann starten).
    hl.exec_cmd("killall TrafkTuxLauncher; ~/.config/TrafkTuxLauncher/TrafkTuxLauncher --daemon &")
    -- SwaySyncWatchdog.sh statt direktem swaync-Aufruf: startet swaync wie
    -- bisher, startet es aber automatisch neu, falls es abstuerzt (siehe
    -- SwaySyncWatchdog.sh fuer Details/Stop-Befehl).
    hl.exec_cmd("setsid -f bash $HOME/.config/swaync/SwaySyncWatchdog.sh >/dev/null 2>&1 &")
    hl.exec_cmd("hypridle")
    hl.exec_cmd("/usr/lib/polkit-kde-authentication-agent-1")
    hl.exec_cmd("nm-applet --indicator")
    hl.exec_cmd("blueman-applet")
    hl.exec_cmd("wl-paste --watch cliphist store")
    hl.exec_cmd("wl-clip-persist --clipboard regular")
    hl.exec_cmd("swayosd-server")
    -- WaybarAutohideDaemon.service entfernt: TrafkTuxBar bringt sein
    -- eigenes Autohide mit, kein separater Daemon mehr noetig.
    -- hl.exec_cmd("systemctl --user start WidgetsDaemon.service WaybarAutohideDaemon.service FocusFixDaemon.service ScreenRotationDaemon.service SoundCenter.service")
    hl.exec_cmd(
        "systemctl --user start WidgetsDaemon.service FocusFixDaemon.service ScreenRotationDaemon.service SoundCenter.service"
    )
    hl.exec_cmd("sudo systemctl restart trafktux-grub-theme-sync.service")
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

-- Nutzer-Autostart (z.B. von deiner Settings-App generiert). Lebt
-- bewusst NICHT in HyprlandConfigs/ (also nicht im Repo/Paket), damit
-- ein Systemupdate diese Datei nie anfasst. pcall(dofile, ...) statt
-- require(): require() würde bei fehlender Datei hart abbrechen (siehe
-- Hyprland-Doku), pcall(dofile, ...) ist dagegen sicher, falls die
-- Datei (noch) nicht existiert.
pcall(dofile, os.getenv("HOME") .. "/.config/hypr/HyprlandUserConfigs/UserAutostart.lua")
