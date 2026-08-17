# Systemsounds — Setup

## 1. Dateien an den richtigen Ort legen

```bash
mkdir -p ~/.config/hypr/sounds
chmod +x ~/.config/hypr/soundctl.sh
```

`soundctl.sh` erwartet diese Dateien (alle optional — fehlt eine, passiert
einfach nichts, kein Fehler):

| Datei                                   | Wann es spielt                                    |
|------------------------------------------|-----------------------------------------------------|
| `~/.config/hypr/sounds/click.ogg`         | Buttons/Module klicken                             |
| `~/.config/hypr/sounds/toggle.ogg`        | Ein/Aus-Schalter (Dark Mode, Hideall, PIP, OSK)    |
| `~/.config/hypr/sounds/open.ogg`          | Fenster öffnet / Bubble öffnet                     |
| `~/.config/hypr/sounds/close.ogg`         | Fenster schließt / Bubble schließt                 |
| `~/.config/hypr/sounds/nav.ogg`           | Workspace-Wechsel, Fokuswechsel, Menü-Navigation   |
| `~/.config/hypr/sounds/enter.ogg`         | Auswahl bestätigt (Rofi-Menü, Widget-Aktion)       |
| `~/.config/hypr/sounds/error.ogg`         | reserviert für Fehler-Feedback                     |
| `~/.config/hypr/sounds/notify.ogg`        | reserviert für Benachrichtigungen                  |

Format: `.ogg` funktioniert mit `pw-play`/`paplay` out of the box, `.wav`
geht genauso — im Skript einfach `sound_file_for()` anpassen. Nimm kurze
(< 200ms) Klicks/Blips, sonst nervt's bei schnellem Klicken.

## 2. Player-Abhängigkeit

`soundctl.sh` probiert in dieser Reihenfolge: `pw-play` → `paplay` →
`canberra-gtk-play`. Auf PipeWire-Systemen (was du eh fährst) ist
`pw-play` normalerweise schon da.

## 3. Architektur: kein Daemon (bewusste Entscheidung)

Es gab zwischenzeitlich einen Versuch mit einem separaten C-Daemon
(`soundd`/`clickd`, dauerhaft laufend, Unix-Socket) — der hat sich in der
Praxis **nicht gelohnt**: keine echte Geschwindigkeit (der Daemon spawnt
`pw-play` bei jedem Aufruf trotzdem neu, nur mit einem zusätzlichen
`socat`/Socket-Hop drumherum — tendenziell langsamer, nicht schneller)
und neue Abhängigkeiten (systemd-Units, `input`-Gruppen-Mitgliedschaft
für JEDEN User — für eine Distro mit vielen Nutzern ein echtes
Rollout-Problem). Verworfen, kein Autostart mehr dafür in `hyprland.lua`.

Stattdessen: **direktes Spawnen**, aber mit `setsid` statt nur `&`.

**Der eigentliche Grund**, warum manche Sounds (PIP, Rofi-`enter`,
Widget-Klicks) anfangs stumm blieben: `soundctl.sh` wurde aus einem
selbst schon kurzlebigen Prozess heraus aufgerufen (`pip.sh` via
`hyprctl dispatch exec_cmd`, `bubble-menu.py` als Rofi-Script-Mode-
Subprozess). Ein bloß per `&` hintergrundgestarteter Player kann in dem
Moment sterben, in dem die Prozessgruppe des Aufrufers aufräumt — der
Elternprozess ist zu dem Zeitpunkt oft schon weg. `setsid <player>` hebt
den Player in eine komplett NEUE, unabhängige Session — er hängt danach
an nichts mehr, das mit dem Aufrufer zusammenhängt, und übersteht das
Aufräumen der Elternprozessgruppe zuverlässig. Kein Daemon nötig dafür.

## 4. An/Aus — jetzt zweistufig

- **Master-Schalter** (alles auf einmal stumm/laut): unverändert wie
  bisher — `soundctl.sh --enable` / `--disable` / `--toggle` / `--status`
  (ohne weiteres Argument), Datei `~/.cache/hypr/sounds_enabled`. Genau
  das, was der Settings-Toggle in `widgets_daemon.py` anspricht.
- **Pro-Event-Schalter** (NEU): jedes Event einzeln an/aus, z.B. nur
  Klick-Sounds stumm, aber `nav`/`enter`/etc. weiter hörbar:
  ```bash
  soundctl.sh --disable click     # nur Klick-Sounds aus
  soundctl.sh --enable  click     # wieder an
  soundctl.sh --toggle  click     # umschalten
  soundctl.sh --status  click     # "on"/"off"
  ```
  State liegt in `~/.cache/hypr/sound_events/<event>` (Inhalt `1`/`0`,
  Default bei fehlender Datei: an). Ein Sound spielt nur, wenn **beide**
  Schalter (Master UND das jeweilige Event) an sind.

Für die Widget-UI (eigene Toggle-Buttons pro Sound-Effekt, wie du es dir
vorgestellt hattest) fehlt noch die Anbindung in `widgets_daemon.py` -
das machen wir, sobald deine überarbeitete Version davon steht. Die
Grundlage (`--enable/--disable/--toggle/--status <event>`) ist aber
schon da, ein Button muss nur noch genau diese Aufrufe machen.

## 5. Die ~0,4-7s Verzögerung — noch nicht gelöst, hier der nächste Schritt

Terminal-Test (`time bash soundctl.sh click`) ist nachweislich instant,
auch hörbar, auch mit Bluetooth-Kopfhörern. Die Verzögerung tritt nur bei
Events auf, die **aus Hyprland selbst heraus** über `hl.exec_cmd`
gefeuert werden (Fenster öffnen/schließen, Workspace-Wechsel). Zwei
Verdächtige, noch nicht unterschieden:

1. Hyprlands `exec_cmd`-Mechanismus selbst hat inhärente Latenz
   (unabhängig davon, WANN er aufgerufen wird).
2. Der Sound-Trigger konkurriert mit der Fenster-Öffnen/Schließen-
   Animation um CPU/GPU-Zeit genau in dem Moment - Verzögerung nur bei
   gleichzeitiger Kompositing-Last, nicht grundsätzlich.

**Test dafür** (keine Config-Änderung nötig, im Leerlauf ausführen -
kein Fenster gleichzeitig öffnen/schließen):

```bash
hyprctl dispatch exec "bash ~/.config/hypr/soundctl.sh click"
```

- Kommt der Sound dabei **sofort** → Verdacht 2 bestätigt (Kompositing-
  Last ist der Übeltäter, nicht unser Code oder Hyprlands exec_cmd an
  sich).
- Kommt er **auch verzögert** → Verdacht 1, dann müssen wir uns
  `hl.exec_cmd` selbst genauer anschauen bzw. einen anderen Trigger-Weg
  suchen, der nicht über den Hyprland-eigenen exec-Pfad läuft.

Sag mir das Ergebnis, dann grenzen wir von da aus weiter ein.

## 6. Was NICHT automatisch verdrahtet ist (bewusst)

- **Reine Pfeiltasten-Navigation innerhalb einer Rofi-Liste** (Hoch/Runter
  auf einen anderen Eintrag, ohne Enter): technisch nicht möglich ohne
  Rofi selbst zu patchen — Rofi ruft `bubble-menu.py` nur bei einer
  tatsächlichen Auswahl auf (Enter, Custom-Keys q/e/x), nicht bei jedem
  Tastendruck. Was stattdessen verdrahtet ist: Seite vor/zurück, Ordner
  rein/raus, App/Aktion starten - siehe `bubble-menu.py` (`_play_sound`).
- **Wirklich jeder Klick, systemweit** (auch außerhalb von
  Waybar/Widgets/Rofi, z.B. in Firefox): das war der `clickd`-Ansatz
  (rohe `/dev/input`-Events mitlesen) - aktuell zurückgestellt, siehe
  Abschnitt 3. Die Dateien (`clickd.c`, `clickd.service`) liegen noch mit
  dabei, falls wir das später nochmal aufgreifen wollen, sind aber
  NICHT in `hyprland.lua` verdrahtet.
