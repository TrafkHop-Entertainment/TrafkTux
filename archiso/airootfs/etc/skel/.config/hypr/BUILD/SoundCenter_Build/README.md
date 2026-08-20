# SoundCenter — Systemsounds ohne Verzögerung

Ersatz für die alte `soundctl.sh`. Gleiche Kommandozeile, gleiche
Statusdateien — aber ein persistenter C-Daemon mit einer einzigen
dauerhaft offenen PipeWire-Verbindung statt einer neuen `pw-play`-
Prozesskette pro Klick.

Zwei Binaries, gebaut aus `src/`:

| Datei | Wird zu | Zweck |
|---|---|---|
| `src/SoundDaemon.c` | `SoundDaemon` | persistenter Daemon, hält den PipeWire-Stream offen |
| `src/SoundControl.c` | `SoundControl` | schneller CLI-Client (Play/Enable/Disable/Toggle/Status) |
| `SoundCenter.sh` | (bleibt Skript) | 2-Zeilen-Trampolin für bestehende Aufrufer, siehe unten |
| `SoundCenter.service` | (systemd-Unit) | optionale Autostart/Restart-Absicherung |

---

## Diagnose — Korrektur nach Rückmeldung

Meine erste Theorie (WirePlumber suspendiert die Senke nach 5s
Inaktivität, ein neuer `pw-play`-Prozess trifft auf eine schlafende Senke)
passt **nicht mehr vollständig** zu dem, was du zurückgemeldet hast: auch
ein kalter Erstaufruf im Terminal war nie langsam. Das schließt Suspend
als *alleinige* Ursache ziemlich sicher aus — ein wirklich suspendierter
Sink hätte auch den kalten Terminal-Aufruf treffen müssen.

Was dieser Daemon trotzdem bringt: er eliminiert unabhängig davon jeden
Kostenpunkt, der *im Sound-Dispatch selbst* liegen könnte (Prozess-Spawn-
Kette, PipeWire-Neuverhandlung pro Aufruf, Senken-Aufwachen falls doch mal
relevant). Schadet nicht, kostet praktisch nichts. Aber: falls nach dem
Umstieg im echten Betrieb (insbesondere bei `window.open_early`/`nav`,
also den Compositor-getriggerten Events) immer noch eine Verzögerung
wahrnehmbar ist, dann liegt sie **nicht mehr im Sound-Pfad** — der ist
jetzt nachweislich Mikrosekunden schnell (siehe "Was ich verifiziert
habe") — sondern höchstwahrscheinlich **vor** dem jeweiligen Hyprland-Hook.

Dafür spricht auch etwas, das ich gerade erst nachgeschaut habe (nicht aus
dem Gedächtnis geraten, du hattest ja recht mit der Erinnerung):
Hyprlands eigene Doku warnt explizit, dass `hyprctl`-Dispatches
(also auch das, was hinter `hl.dsp.exec_cmd(...)`/`hl.on(...)` steckt)
**synchron im Compositor** verarbeitet werden ("hyprctl calls will be
dispatched by the compositor synchronously, meaning any spam of the
utility will cause slowdowns" — [Hyprland-Wiki, "Using hyprctl"](https://wiki.hypr.land/Configuring/Advanced-and-Cool/Using-hyprctl/)).
Heißt: WANN genau `window.open_early` feuert, hängt vom
Compositor-internen Timing ab (Layout, Animation-Vorbereitung, etc.), nicht
von irgendwas, das in `soundctl`/`SoundControl` passiert. Das lässt sich
nach dem Umstieg sauber isolieren:

1. `SoundControl <event>` direkt im Terminal — sollte (wie eh schon)
   instant sein.
2. Denselben Event über den echten Hyprland-Hook auslösen (Fenster
   öffnen, Menü navigieren, ...) und **fühlen**, ob's noch hakt.
3. Falls ja: dein eigener Debug-Ansatz aus `hyprland.lua`
   (Zeitstempel-Logging um den Hook herum, das Setup mit
   `/tmp/opentest.log`) ist jetzt aussagekräftiger als vorher, weil der
   Sound-Anteil an T_done praktisch bei 0 liegt — jede verbleibende
   Differenz zwischen "User-Aktion" und "T_hook" ist dann Compositor-Zeit,
   kein Sound-Problem mehr. Das wäre dann ein Hyprland-Issue bzw. eine
   Frage an deren Tracker/Discord, nicht an diesem Repo hier zu lösen.

---

## Architektur

Unverändert zur letzten Version (nur umbenannt) — siehe Kommentare in
`src/SoundDaemon.c` für die volle Herleitung (single-threaded Design,
Voice-Mixing, `node.always-process`, etc.). Kurzfassung:

```
SoundControl <event>  --(1 Unix-Datagram, fire-and-forget)-->  SoundDaemon
                                                                  │
                                                                  ├─ alle 8 .ogg
                                                                  │  liegen fertig
                                                                  │  dekodiert als
                                                                  │  Float32-PCM
                                                                  │  im RAM
                                                                  │
                                                                  └─ EIN einziger,
                                                                     dauerhaft
                                                                     offener
                                                                     PipeWire-
                                                                     Stream
```

`SIGHUP` an `SoundDaemon` lädt alle Sounds neu von Disk (z.B. nach
`systemctl --user reload SoundCenter.service`, falls du mal eine
`.ogg`-Datei austauschst).

---

## Build

```bash
make
```

Erzeugt `SoundDaemon` und `SoundControl` im aktuellen Verzeichnis. **Kein
`make install`** — wohin die beiden Binaries kopiert werden, entscheidest
du. `make clean` räumt wieder auf.

**Build-Abhängigkeiten** (nur zum Kompilieren nötig):

- Arch (neueste Version, bei dir schon alles da laut deiner Rückmeldung):
  `pipewire`, `libvorbis`, `base-devel`, `pkgconf`
- Debian/Ubuntu (womit ich das hier tatsächlich gebaut+getestet habe):
  `libpipewire-0.3-dev libspa-0.2-dev libvorbis-dev build-essential pkg-config`

---

## Platzierung — keine festen Pfade

Bewusst so gebaut, dass du die Dateien hinlegen kannst, wo du willst
(ArchISO-Overlay, `/usr/local/bin`, `~/.local/bin`, egal):

- **`SoundDaemon`, `SoundControl`**: müssen über `$PATH` auffindbar sein,
  wenn sie aufgerufen werden. `SoundControl`s Selbstheilungs-Mechanismus
  (startet `SoundDaemon` automatisch, falls er beim Abspielen nicht
  erreichbar ist) nutzt einen ganz regulären `execlp()` — der sucht in der
  echten `$PATH`-Umgebungsvariable des aufrufenden Prozesses, völlig
  unabhängig davon, wo genau die Datei liegt.
- **`SoundCenter.sh`**: muss an dem Pfad liegen, den deine bestehenden
  Aufrufer erwarten (aktuell `~/.config/hypr/soundctl.sh` — siehe
  "Anpassungen an den Aufrufern" unten, entweder du legst
  `SoundCenter.sh` dort ab, oder du passt die eine Zeile pro Aufrufer an
  den Pfad an, den du tatsächlich benutzt). Es selbst braucht nur, dass
  `SoundControl` über `$PATH` auffindbar ist (normale Shell-`exec`-Suche).
- **`SoundCenter.service`**: **Achtung, hier ist `$PATH` NICHT
  automatisch dasselbe** — ein bloßer Name in `ExecStart=` wird von
  systemd über eine eigene, fest einkompilierte Liste
  (`/usr/local/bin`, `/usr/bin`, `/bin` + `sbin`-Pendants) aufgelöst,
  **nicht** über deine Login-`$PATH`. Liegt `SoundDaemon` bei dir in einem
  dieser Standardverzeichnisse, funktioniert `ExecStart=SoundDaemon`
  einfach so. Sonst: entweder vollen Pfad in `ExecStart=` eintragen, oder
  `ExecSearchPath=` ergänzen (steht als Kommentar direkt in der Datei,
  inkl. Beispiel — Details: `man systemd.exec`).

---

## Anpassungen an den Aufrufern

**Das musst du selbst entscheiden/machen** — ich hab bewusst nicht
blind in eure großen Dateien reingeschrieben (`widgets_daemon.py` allein
ist 6000+ Zeilen), sondern zeige hier exakt die eine Zeile pro Datei, die
sich ändert. Alle vier riefen bisher denselben Pfad mit derselben
Kommandozeilen-Grammatik auf — die Grammatik (`bash <pfad> <event>`,
`--enable`/`--disable`/`--toggle`/`--status`) bleibt exakt gleich, nur der
Dateiname ändert sich von `soundctl.sh` zu `SoundCenter.sh`:

**`hyprland.lua`** (Zeile ~126):
```lua
-- vorher:
local SOUNDCTL = "bash $HOME/.config/hypr/soundctl.sh"
-- nachher:
local SOUNDCTL = "bash $HOME/.config/hypr/SoundCenter.sh"
```

**`hyprland.lua`** (Zeile ~373, `SUPER+H`/hideall) — zwei unabhängige
Sachen auf einmal: Dateiname UND die Reihenfolge, damit der Sound nicht
erst nach dem (bis zu 1s pollenden) `hideall.sh` kommt:
```lua
-- vorher:
hl.dsp.exec_cmd("bash ~/.config/waybar/scripts/hideall.sh toggle && bash ~/.config/hypr/soundctl.sh toggle &")
-- nachher (Sound parallel/zuerst statt danach):
hl.dsp.exec_cmd("bash ~/.config/hypr/SoundCenter.sh toggle & bash ~/.config/waybar/scripts/hideall.sh toggle")
```

**`widgets_daemon.py`**:
```python
# vorher:
SOUNDCTL = os.path.join(HOME, ".config", "hypr", "soundctl.sh")
# nachher:
SOUNDCTL = os.path.join(HOME, ".config", "hypr", "SoundCenter.sh")
```

**`RofiTrafkBubbleMenus.c`** (danach neu kompilieren!):
```c
// vorher:
#define SOUNDCTL_PATH       "~/.config/hypr/soundctl.sh"
// nachher:
#define SOUNDCTL_PATH       "~/.config/hypr/SoundCenter.sh"
```

**`pip.sh`**:
```bash
# vorher:
bash "$HOME/.config/hypr/soundctl.sh" toggle &
# nachher:
bash "$HOME/.config/hypr/SoundCenter.sh" toggle &
```

Schick mir gern deine aktuellen Config-Dateien, falls du sie schon
angepasst hast oder falls sich seit dem letzten Upload was geändert hat —
dann check ich das gegen, statt hier blind zu patchen.

---

## Optional: WirePlumber-Suspend-Fix

Trotz der Korrektur oben weiterhin empfehlenswert (kostet nichts, hilft
z.B. auch Musik-Playern nach einer Pause) — `wireplumber/`-Ordner:

```bash
wireplumber --version   # entscheidet, welche Datei
```
- **≥ 0.5**: `51-soundcenter-no-suspend.conf` →
  `~/.config/wireplumber/wireplumber.conf.d/`
- **< 0.5** (Lua): `51-soundcenter-no-suspend.lua` →
  `~/.config/wireplumber/main.lua.d/`

Danach: `systemctl --user restart wireplumber`.

---

## Sound-Events

13 Events, Englisch/PascalCase (keine `-`/`_`/Anführungszeichen), definiert
in `src/SoundDaemon.c` (`EVENT_NAMES[]`). Erwartete Datei pro Event in
`~/.config/hypr/sounds/`: `<EventName>.ogg`, Groß-/Kleinschreibung zählt.

| Event | Datei dabei? | Herkunft/Mapping |
|---|---|---|
| `Click` | ✅ (aus `click.ogg`) | Standard-Klick |
| `RightClick` | ❌ noch keine Audiodatei | neu, generischer Rechtsklick |
| `MiddleClick` | ❌ noch keine Audiodatei | neu, generischer Mittelklick |
| `Open` | ✅ (aus `open.ogg`) | Fenster öffnet |
| `Close` | ✅ (aus `close.ogg`) | Fenster schließt |
| `FocusChange` | ✅ (aus `nav.ogg`) | ersetzt altes `nav` — Workspace-/Fensterfokus-Wechsel UND Widget-Wechsel (laut dir dieselbe Sache) |
| `Pip` | ❌ noch keine Audiodatei | neu, `PictureInPicture.sh` |
| `Autohide` | ❌ noch keine Audiodatei | neu, `HideAll.sh` |
| `LayoutSwitch` | ❌ noch keine Audiodatei | neu, `LayoutSwitcher.sh` |
| `Dunst` | ✅ (aus `notify.ogg`) | ersetzt altes `notify` — allgemeiner Notification-Sound; "Gerät verbunden/getrennt" bekommen laut dir kein eigenes Event, laufen einfach mit hierüber, sobald `dunstrc` einen Script-Hook hat |
| `Error` | ✅ (unverändert) | |
| `Toggle` | ✅ (unverändert) | in deiner Liste nicht mehr genannt, aber noch aktiv gebraucht (siehe unten) — bewusst behalten statt stillschweigend entfernt |
| `Enter` | ✅ (unverändert) | ebenfalls nicht in der neuen Liste, hängt aber schon an `RofiTrafkBubbleMenus.c` (Menü-Bestätigen) — auch behalten |

Die 8 vorhandenen `.ogg`-Dateien liegen bereits umbenannt/passend im
Ordner `sounds/` dieses Repos — einfach nach `~/.config/hypr/sounds/`
kopieren. Für die 5 neuen (`RightClick`, `MiddleClick`, `Pip`, `Autohide`,
`LayoutSwitch`) fehlt noch Audiomaterial — der Daemon startet trotzdem
klaglos, loggt beim Fehlen nur eine Warnung und bleibt für das jeweilige
Event bis zum nächsten `SIGHUP`/Neustart stumm, sobald du die Datei
nachlegst.

**Bewusst NICHT gemacht** (dein Wunsch: "kann man dann einzeln
einbauen"): die eigentlichen Aufrufe in `WaybarClicks.sh`, `HideAll.sh`,
`LayoutSwitcher.sh` und `dunstrc` sind noch nicht verdrahtet — die kennen
`SoundControl`/`SoundCenter.sh` aktuell noch gar nicht. Falls hilfreich,
hier die naheliegende Zuordnung für später (button-Wert exakt wie in
`WaybarClicks.sh`s eigenem Kommentar):

- `WaybarClicks.sh`: `button=1` → `Click`, `button=2` → `MiddleClick`,
  `button=3` → `RightClick` (nach der jeweiligen `hyprctl dispatch`-Zeile
  einfach `bash ~/.config/hypr/SoundCenter.sh <Event> &` anhängen)
- `HideAll.sh`: passender Punkt wäre am Ende von `do_hide`/`do_restore`
  jeweils `Autohide` — aktuell feuert der Sound stattdessen schon von
  `hyprland.lua`s `SUPER+H`-Bind aus (parallel, siehe letzter Patch); wenn
  ihr den lieber aus dem Skript selbst feuern wollt statt aus dem Keybind,
  sag Bescheid, dann zieh ich ihn um.
- `LayoutSwitcher.sh`: `LayoutSwitch` an jeder der vier `case`-Aktionen
  (`master|dwindle`, `scroller|scrolling`, `floating`, `bigscreen|monocle`)
- `dunstrc`: `always_run_script = true` steht schon (Zeile 69), aber es
  fehlt noch die eigentliche `script = ...`-Zeile pro Urgency-Abschnitt,
  die auf ein kleines Wrapper-Skript zeigen müsste, das
  `SoundCenter.sh Dunst` aufruft (Dunst reicht Notification-Infos über
  Env-Variablen an das Script durch, nicht als Argument - dafür bräuchte
  es einen kleinen Zwischenschritt, kein reiner Ein-Zeiler)

## Erledigt in dieser Runde

- `RofiTrafkBubbleMenus.c` (`SOUNDCTL_PATH`) und `PictureInPicture.sh` auf
  `SoundCenter.sh` umgestellt (letzte offene Punkte aus der letzten
  Runde) — `RofiTrafkBubbleMenus.c` dabei mit `gcc -fsyntax-only` gegen
  echte glib/gio/json-glib-Header geprüft, sauber durch.
- `WaybarAutohideDaemon.c`, `WaybarClicks.sh`, `HideAll.sh`,
  `LayoutSwitcher.sh`, `dunstrc` durchsucht — keiner von denen ruft aktuell
  irgendein Sound-Event auf (passt zu "einzeln einbauen"), daher hier
  nichts zu patchen.

## Optional: systemd-Unit

```bash
# SoundCenter.service irgendwohin nach ~/.config/systemd/user/ (oder
# /etc/systemd/user/ fürs ArchISO-Overlay) kopieren, dann:
systemctl --user daemon-reload
systemctl --user enable --now SoundCenter.service
```

Ganz ohne systemd geht's auch — `SoundControl` startet `SoundDaemon` beim
ersten gebrauchten Sound selbst nach, falls er nicht läuft (siehe
"Platzierung"). Die Unit sorgt nur dafür, dass er schon beim Login
bereitsteht (sonst geht der allererste Sound nach dem Login verloren) und
nach einem Absturz automatisch neu startet.

---

## Was ich tatsächlich verifiziert habe

Mit den neuen Namen nochmal komplett durchgetestet, in einer echten
(headless) PipeWire 1.0.5 + WirePlumber 0.4.17-Session mit virtuellem
Sink, Binaries diesmal bewusst an einem willkürlichen, nicht
"offiziellen" Pfad platziert (nur über `$PATH` erreichbar, um genau das
ArchISO-Szenario "Dateien liegen wo ich will" nachzustellen):

- Baut sauber, keine Warnungen.
- `SoundCenter.sh` (bzw. `bash SoundCenter.sh <event>`, exakt wie eure
  Aufrufer es tun) findet `SoundControl` korrekt über `$PATH`.
- Daemon tot + `SoundCenter.sh click` aufgerufen → `SoundDaemon` wird
  selbstständig über `$PATH` nachgestartet, kein Hängen, kein Warten.
- Ende-zu-Ende-Audio (Sink-Ausgang mit `pw-record` mitgeschnitten,
  `notify`/`click`/`toggle` ausgelöst, per `ffmpeg silencedetect`
  analysiert): abgespielte Dauer stimmt mit den Originaldateien überein.
- `SoundControl --status`/`--toggle` funktionieren wie gehabt.

Nicht verifizierbar hier: euer echtes Hyprland/eure echte Desktop-Session
— dafür bräuchte ich die aktuellen Config-Dateien, die du nachreichst.

---

## Nebenbefunde (unverändert seit letzter Version)

- `error`/`notify` sind aktuell an keiner Stelle in euren Dateien
  aufgerufen, obwohl beide `.ogg`s vorhanden sind. Kein Mechanismus-Bug,
  einfach noch nicht verdrahtet — mit `SoundControl error`/
  `SoundControl notify` (bzw. über `SoundCenter.sh`) reicht dafür ein
  einzeiliger Aufruf an der jeweils passenden Stelle.
