-- Display.lua
--
-- Monitor-Setup & alles, was direkt mit der Bildschirmausgabe/Skalierung
-- zu tun hat.
--
-- Diese Datei selbst ist BEWUSST generisch/system-unabhängig (Teil des
-- Repos, wird also bei jedem Distro-Update überschrieben). Dein
-- tatsächliches, konkretes Monitor-Setup (z.B. dein eDP-1) gehört NICHT
-- hier rein, sondern in UserDisplay.lua - eine separate Datei
-- AUSSERHALB von HyprlandConfigs/ (siehe pcall(dofile, ...) unten),
-- damit ein Systemupdate sie nie anfasst. Ist gedacht, später von
-- deiner Settings-App automatisch geschrieben zu werden.

-- Erst das konkrete Nutzer-Setup laden, falls vorhanden. WICHTIG:
-- bewusst VOR dem generischen Fallback weiter unten - genau wie in
-- jeder gewöhnlichen hyprland.conf sollten konkrete Monitor-Regeln vor
-- einer Wildcard-"Catch-all"-Regel stehen, damit die Wildcard nur
-- greift, was nicht schon konkret benannt wurde.
--
-- require() würde hier bei fehlender Datei hart abbrechen (siehe
-- Hyprland-Doku: "require()'s protective behavior does not apply to
-- module loading"); pcall(dofile, ...) ist deshalb der richtige,
-- sichere Weg für eine Datei, die (z.B. bei einer frischen Install vor
-- dem ersten Settings-App-Lauf) noch gar nicht existieren muss.
pcall(dofile, os.getenv("HOME") .. "/.config/hypr/HyprlandUserConfigs/UserDisplay.lua")

-- Generischer Fallback für JEDEN Monitor, der nicht in UserDisplay.lua
-- konkret eingetragen ist: beste verfügbare Auflösung bei bestmöglicher
-- Wiederholrate, automatisch platziert.
--
-- "highres"/"highrr" sind offizielle Hyprland-Mode-Keywords (siehe
-- https://wiki.hypr.land/Configuring/Basics/Monitors/ sowie
-- https://github.com/hyprwm/Hyprland/issues/6735, wo beide im Kontext
-- bestätigt werden): "highres" wählt die höchste verfügbare Auflösung,
-- "highrr" die höchste Wiederholrate (bei der höchsten Auflösung).
-- Alternative wäre "preferred" (vom Monitor per EDID gemeldeter
-- bevorzugter Modus) - "highres" greift laut Community-Berichten
-- i.d.R. zuverlässiger als "preferred".
--
-- UNSICHERHEIT (bitte einmal gegentesten): für die alte hyprlang-Syntax
-- ist der leere Name als Wildcard gut belegt (z.B.
-- "monitor = , highres, auto, 1"). Ein von Dritten verifiziertes
-- Lua-Beispiel für genau diese Wildcard-Zeile (output = "") konnte ich
-- trotz Suche nicht finden - die Felder selbst (output/mode/position/
-- scale) sind aber 1:1 die dokumentierte hl.monitor()-API. Nach
-- "hyprctl reload" einmal mit einem nicht in UserDisplay.lua
-- eingetragenen Zweitmonitor prüfen ("hyprctl monitors"); greift die
-- Wildcard nicht, einfach jeden echten Monitor einzeln in
-- UserDisplay.lua eintragen (macht deine Settings-App ohnehin).
hl.monitor({
    output = "",
    mode = "highres",
    position = "auto",
    scale = "auto",
})

hl.config({
    xwayland = {
        force_zero_scaling = true,
    },
})
