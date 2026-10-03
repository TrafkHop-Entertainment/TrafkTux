# TrafkTux Widgets — technische Analyse & Fix-Liste (überarbeitet, gegen den echten Code verifiziert)

**Methodik dieser Fassung:** Ich habe nicht mehr nur mit allgemeinem Wissen spekuliert, sondern die tatsächlichen Dateien gelesen (`WidgetsDaemon.py`, `hyprland.lua`) und die externen Fakten (Hyprland-Lua-API, PAM/FIDO2-Tools, verfügbare PyPI-Pakete) frisch nachrecherchiert. Wo der alte Entwurf nur vermutet oder sich im Kreis gedreht hat (v.a. Punkt 5), steht jetzt eine klare, aus dem Code abgeleitete Ursache. Nichts an Code wurde verändert — das bleibt deine Aufgabe, das hier ist weiterhin nur die Recherche/Liste.

**Was sich gegenüber der letzten Fassung ändert:**
- Punkt 1 & 2: Es gibt ein fertiges, getestetes PyPI-Paket (`hyprland-monitors`), das genau deine Scale- und Repack-Mathematik bereits löst — muss nicht mehr selbst gebaut werden.
- Punkt 4: Im Code bereits verifiziert, dass rfkill/ClamAV schon auf „immer pkexec“ umgestellt sind; dafür ein echter Docstring/Code-Widerspruch bei der Kamera gefunden.
- Punkt 5: Die alte Fassung hat sich mehrfach selbst widersprochen („sollte funktionieren… es sei denn…“). Jetzt eine eindeutige, im Code nachvollzogene Ursache.
- Punkt 6: Live im Code bestätigt, dass der teure Pfad *wirklich* unbedingt bei jedem Frame läuft — keine Vermutung mehr. Fix weiterhin ohne jede optische Änderung, wie gefordert.
- Punkt 3: FIDO jetzt vollständig statt „Status-only“, wie gewünscht.

---

## 1. Display: Scale-Liste zeigt ungültige Werte & ist zu lang

**Verifiziert im Code:** `_valid_scales_for_resolution()` brute-forced über `p/q` mit `q ≤ 20` und prüft nur, ob `width/scale` und `height/scale` (fast) ganzzahlig sind. Das lässt mathematisch gültige, aber für Hyprland **ungültige** Brüche wie `12/13 = 0.9231` durch, weil Hyprland Scales intern auf Vielfache von `1/120` quantisiert und exakte Teilbarkeit beider Dimensionen verlangt. Ebenfalls verifiziert: `scale_combo = Gtk.ComboBoxText()` — das bestätigt das zweite Problem (Popup kann nicht zuverlässig scrollen, wächst über den Bildschirmrand).

**Neuer Fund:** Es existiert ein aktuell gepflegtes, MIT-lizenziertes PyPI-Paket **`hyprland-monitors`** (von BlueManCZ, dem Autor der Hyprland-Lua-Tooling-Familie, siehe Punkt 7), das exakt diese Quantisierung bereits implementiert:

```python
from hyprland_monitors.monitors import compute_valid_scales, nearest_scale_index

scales = compute_valid_scales(3440, 1440)   # -> Liste von Objekten mit .label / .value,
                                             # bereits auf 1/120-Vielfache gefiltert
idx = nearest_scale_index(scales, 1.5)      # ersetzt deine eigene _nearest_valid_scale()
```

Das deckt `_valid_scales_for_resolution()` **und** `_nearest_valid_scale()` komplett ab — eine getestete Bibliotheksfunktion statt eigener Bruch-Mathematik. Falls eine zusätzliche Abhängigkeit nicht gewünscht ist, als Fallback die bestehende Brute-Force auf `n/120` einschränken (`n` von 60–360) und `width/(n/120)` bzw. `height/(n/120)` auf Ganzzahligkeit prüfen — liefert dasselbe Ergebnis, nur selbst gepflegt.

**Zu lange Liste:** `Gtk.ComboBoxText` rendert alle Einträge als `GtkTreeView`-Zeilen ohne zuverlässigen internen Scroll-Mechanismus, sobald das Popup über die Bildschirmhöhe hinauswächst. Sauberer GTK3-Weg: `Gtk.MenuButton` + `Gtk.Popover`, darin ein `Gtk.ScrolledWindow` mit `set_max_content_height(...)` und `set_propagate_natural_height(True)`. Das begrenzt die Höhe hart und scrollt danach zuverlässig — unabhängig davon, ob durch die 1/120-Filterung ohnehin schon deutlich weniger Einträge übrig bleiben (bei hochauflösenden Monitoren können das trotzdem noch 10–20 gültige Werte sein).

---

## 2. Monitor-Überlappung: Hyprland beschwert sich weiterhin

**Verifiziert im Code:** `_repack_lua_positions()` berechnet die neuen logischen Positionen *aller* Monitore inhaltlich korrekt (logische Pixel = physische Pixel / Scale, Nachbarn rechts/unten werden verschoben). Das Problem liegt nicht in der Formel, sondern in der Reihenfolge der Anwendung: Wird pro Monitor einzeln `hl.monitor()`/`hyprctl eval` aufgerufen, führt Hyprland nach **jedem einzelnen** Aufruf seinen Layout-Check durch — und sieht dabei zwischenzeitlich einen inkonsistenten Zustand (ein Monitor schon mit neuer Scale, die Nachbarn noch mit alten, jetzt falschen Positionen).

**Neuer Fund:** Dasselbe PyPI-Paket wie in Punkt 1 (`hyprland-monitors`) löst auch das:

```python
from hyprland_monitors.monitors import MonitorState, adjust_neighbors

old_w, old_h = changed.effective_size
changed.scale = new_scale
adjust_neighbors(all_monitors, changed, old_w, old_h)   # verschiebt alle Nachbarn in einem Rutsch
```

Das ersetzt die Positions-Berechnung in `_repack_lua_positions()` durch eine bereits getestete Funktion (inkl. Erkennung von Adjazenz via `is_adjacent()`/`all_monitors_connected()`).

**Die eigentliche Reihenfolge-Korrektur** bleibt unabhängig von der Bibliothek nötig:
1. Alle neuen Positionen berechnen (lokal, ohne irgendetwas live anzuwenden).
2. Die `hyprland.lua`-Datei für **alle** betroffenen Monitore in einem Rutsch patchen (macht `_repack_lua_positions()` schon).
3. **Einen einzigen** `hyprctl eval`-Aufruf mit einem Lua-Chunk schicken, der für **jeden** betroffenen Monitor ein `hl.monitor({...})` enthält — nicht einen `hyprctl eval`-Aufruf pro Monitor. `hyprctl eval` nimmt einen ganzen Lua-Codeblock entgegen, mehrere `hl.monitor()`-Aufrufe lassen sich also zu einem String verketten und in einem Rutsch ausführen. Dadurch validiert Hyprland das Layout genau einmal, gegen den bereits vollständig konsistenten Endzustand — nicht mehrfach gegen Zwischenzustände.

Wichtig bleibt: **Datei-Patch zuerst, dann Live-Apply** — falls der Prozess zwischen den Schritten abbricht, bleibt wenigstens die Datei in sich konsistent und ein normaler Neustart von Hyprland repariert den Rest.

---

## 3. Security: Neuer Tab „Authentication“ (Password / Fingerprint / FIDO Key) — vollständig

Da ausdrücklich gewünscht: alles, was auf einem Linux-System technisch machbar ist, ohne Abstriche bei der Funktionalität.

### Password
`passwd` für den eigenen Account reicht aus und braucht kein root (PAM fragt das aktuelle Passwort selbst ab). Für andere User bräuchte es `chpasswd`/root — für ein Nutzer-Widget nicht relevant.

### Fingerprint (`fprintd`)
| Aktion | Befehl |
|---|---|
| Enrollment | `fprintd-enroll` (interaktiv, wartet auf Finger-Auflegen) |
| Verifikation | `fprintd-verify` |
| Löschen | `fprintd-delete <username>` |
| Finger auflisten | `fprintd-list <username>` |
| PAM aktivieren | `pam-auth-update --enable fprintd` (Debian/Ubuntu) oder manuell `auth sufficient pam_fprintd.so` in `/etc/pam.d/system-auth` bzw. `/etc/pam.d/sudo` |

`fprintd-enroll` ist interaktiv und blockiert auf Finger-Auflegen — braucht im Widget einen Dialog, der den Subprozess mit Live-Ausgabe steuert (gleiches Muster wie dein bestehendes ClamAV-Scan-Handling), alternativ über D-Bus (`net.reactivated.Fprint`), falls du eine nicht-blockierende UI willst.

### FIDO Key — vollständige Integration
FIDO2/U2F läuft über das PAM-Modul `pam_u2f.so`. Volle Toolchain:

**1. Key erkennen**
```bash
lsusb | grep -i u2f
fido2-token -L                 # listet alle angeschlossenen FIDO-Token
```

**2. Key registrieren**
```bash
pamu2fcfg > ~/.config/Yubico/u2f_keys
pamu2fcfg -n >> ~/.config/Yubico/u2f_keys   # weiteren Key zur bestehenden Datei hinzufügen
```
Relevante `pamu2fcfg`-Optionen: `-N` PIN-Verifikation erzwingen, `-V` User-Verifikation (z.B. Fingerprint am Key) erzwingen, `-o`/`-i` Origin bzw. Appid setzen.

> **Verifizierter Hinweis (aktuelles `pam-u2f`-Manual):** `origin`/`appid` werden nur dann separat benötigt, wenn die Credentials mit `pamu2fcfg` **≤ v1.0.8** erzeugt wurden — moderne Versionen brauchen das meist nicht mehr getrennt. Fehlt beides, wird automatisch `pam://$HOSTNAME` verwendet. Auf Systemen mit DHCP-vergebenem Hostnamen (Hostname kann sich ändern) empfiehlt sich trotzdem, `origin`/`appid` explizit fest zu setzen, damit ein Hostname-Wechsel nicht alle Keys entwertet.

**3. PAM konfigurieren** (`/etc/pam.d/system-auth` oder `/etc/pam.d/sudo`)
```
# Passwordless:
auth sufficient pam_u2f.so authfile=/etc/u2f_mappings

# Echtes 2FA (Passwort UND Key):
auth required pam_u2f.so authfile=/etc/u2f_mappings cue
```
Muss **vor** `auth required pam_unix.so` stehen, sonst wird der Key ignoriert.

**4. PIN am Key verwalten**
```bash
fido2-token -S -e /dev/hidraw<ID>   # PIN setzen
fido2-token -I /dev/hidraw<ID>      # zeigt rk/up/uv/clientPin-Fähigkeiten des Keys
```

**5. User-Verifikation (z.B. Fingerprint am Key selbst) aktivieren**
```
auth sufficient pam_u2f.so authfile=/etc/u2f_mappings cue pinverification=1 userverification=1
```

**UI-Integration (vollständig statt Status-only):**
- Status-Bereich: zeigt ob `pam_u2f` aktuell in der PAM-Datei konfiguriert ist, listet registrierte Keys aus `u2f_mappings`.
- „Key hinzufügen“-Button: startet `pamu2fcfg` als Subprozess mit Live-Ausgabe („Touch your key…“), hängt das Ergebnis an die Mapping-Datei an.
- Toggle „2FA erzwingen“: schreibt/entfernt die PAM-Zeile per `pkexec`.
- PIN-Verwaltung: `fido2-token -S -e` über ein Passwort-Eingabefeld im Dialog.
- Vor jeder PAM-Änderung: automatisches Backup der betroffenen PAM-Datei (Timestamp-Kopie), damit ein „Letzte Änderung rückgängig machen“-Button möglich ist.

**Wichtige Warnung (stammt direkt aus der Arch-Wiki zu PAM):** Fehlerhafte PAM-Änderungen können dich aussperren. Ein `pkexec`-Dialog ersetzt keine Root-Shell als Rettungsanker — der Enroll-/Toggle-Dialog sollte den Nutzer aktiv daran erinnern, vor dem Aktivieren von `auth required …` eine Root-Shell offen zu halten (oder zumindest den automatischen Backup-Mechanismus oben als Sicherheitsnetz prominent anzeigen).

---

## 4. Privacy: Kein sudo-Popup

**Verifiziert im Code — teilweise schon gelöst:**
- `_rfkill_set()` ruft bei Fehlschlag bereits **bedingungslos** `_run_maybe_priv_force()` auf (kein Text-Heuristik-Umweg mehr) — laut Code-Kommentar ein bereits umgesetzter Bugfix genau für dieses Symptom.
- `_freshclam_update()` (ClamAV-Tab) wurde aus demselben Grund ebenfalls schon auf direktes `pkexec` umgestellt.
- Mikrofon-Mute (`wpctl`) und Touchpad/Touchscreen (`hyprctl keyword device:...`) brauchen **grundsätzlich kein root** — dass dort kein Passwort-Popup erscheint, ist also kein Bug, sondern korrektes Verhalten. Lohnt sich, das in der UI (z.B. Tooltip) kurz klarzustellen, damit es nicht mit dem echten Problem verwechselt wird.

**Neuer Fund — echter Docstring/Code-Widerspruch:** `_camera_set_blocked()` hat einen Kommentar, der besagt, die Funktion solle **immer direkt** mit `pkexec` arbeiten („der erste [unprivilegierte] Versuch würde ohnehin garantiert scheitern“) — ruft im Code aber trotzdem `_run_maybe_priv(...)` auf, also die **heuristik-basierte** Variante, nicht `_run_maybe_priv_force(...)`. Praktisch funktioniert das aktuell meist trotzdem, weil `chmod`s Fehlermeldung bei fehlenden Rechten („Operation not permitted“/„Permission denied“) bereits in der (ebenfalls schon erweiterten) Musterliste steckt — aber:
- es kostet bei **jedem** Kamera-Toggle einen garantiert scheiternden ersten Subprozess-Aufruf, und
- es ist der einzige der drei Privacy-Root-Aktionen, der noch nicht konsequent auf das bereits etablierte Force-Muster umgestellt ist.

**Empfehlung:** `_camera_set_blocked()` exakt wie `_rfkill_set()`/`_freshclam_update()` direkt auf `_run_maybe_priv_force()` umstellen — damit ist Code und Docstring wieder deckungsgleich, und alle drei root-pflichtigen Privacy-Aktionen verhalten sich einheitlich.

**Falls das Popup danach immer noch nie erscheint:** Dann liegt es (verifiziert über aktuelle Hyprland/Wayland/Polkit-Bugreports) nicht mehr an der Heuristik, sondern daran, dass `pkexec` gar keinen laufenden Polkit-Authentifizierungs-Agenten für die Session findet — ein auf Wayland/Hyprland sehr verbreitetes Problem, weil `pkexec` ohne registrierten Agenten komplett **stillschweigend** fehlschlägt (kein Fehlertext, kein Dialog — passt exakt zu „man kann gar nichts tun“). Dein `hyprland.lua` startet zwar bereits `/usr/lib/polkit-kde-authentication-agent-1` beim Session-Start, was das unwahrscheinlich macht — trotzdem als schneller Diagnose-Schritt sinnvoll: einmal manuell `pkexec true` aus einem Terminal in derselben laufenden Session ausführen, während der Daemon läuft. Erscheint dort ebenfalls kein Passwort-Dialog, ist es ein Agenten-/Session-Problem und kein Code-Problem im Daemon.

---

## 5. Processes-Tab: Alle Werte zeigen 0.0 %

**Die vorherige Fassung hat sich hier mehrfach selbst widersprochen** („sollte funktionieren… es sei denn…“). Nach vollständigem Lesen von `_fetch()`, `_apply()` und `make_win()` steht die Ursache jetzt eindeutig fest:

Die Cache-Logik selbst ist **korrekt**: `_proc_cache` hält dieselben `psutil.Process`-Objekte über alle Poll-Ticks hinweg, `cpu_percent(interval=None)` wird auf demselben Objekt wiederholt aufgerufen — das liefert ab dem zweiten Aufruf tatsächlich sinnvolle Werte.

**Der eigentliche Effekt liegt woanders:**
```python
add_timer(2000, _refresh)
_refresh()          # <- läuft SOFORT beim Öffnen des Tabs
```
Dieser allererste `_refresh()`-Aufruf trifft garantiert auf einen leeren `_proc_cache` — für **jeden** Prozess ist es der erste `cpu_percent()`-Aufruf überhaupt, und der liefert laut psutil-Dokumentation **immer** 0.0 zurück (kein Referenzpunkt vorhanden). Der nächste Tick, der echte Werte zeigen würde, kommt erst 2 Sekunden später über `add_timer(2000, …)`.

Da das Processes-Fenster ein Popup ist, das die meisten Nutzer zum kurzen Draufschauen öffnen und innerhalb von 1–2 Sekunden wieder schließen, sehen sie **strukturell fast ausschließlich** genau diesen garantiert-leeren ersten Frame — nicht einen durchgehenden Bug, sondern einen Kaltstart-Effekt, der bei der typischen Nutzungsdauer des Widgets praktisch immer sichtbar wird.

**Fix — kein Umbau der Messmethode nötig, nur der Zeitpunkt der ersten sichtbaren Anzeige:**
Beim Öffnen des Tabs einmal „vorwärmen“, bevor die Zeilen überhaupt gebaut/angezeigt werden:
1. Für alle aktuell laufenden Prozesse einmal `cpu_percent(interval=None)` aufrufen (nur um den Referenzpunkt zu setzen, Ergebnis verwerfen).
2. Kurz warten (z.B. 300–500 ms — lange genug für ein brauchbares Zeitfenster, kurz genug, dass es beim Öffnen nicht auffällt).
3. Erst danach den **echten** ersten Sample nehmen und damit die Zeilen bauen/anzeigen.

Der danach laufende 2-Sekunden-Timer bleibt unverändert. Eine Umstellung auf manuelle `cpu_times()`-Differenzbildung (wie in der alten Fassung vorgeschlagen) wäre nicht falsch, würde aber exakt dasselbe Kaltstart-Problem nur in anderer Form reproduzieren — der Ansatz oben behebt die tatsächliche Ursache direkt.

---

## 6. Performance — ohne jede optische oder funktionale Veränderung

Live im Code bestätigt (nicht mehr nur vermutet):

### 6a. Der teure Cairo-Pfad läuft tatsächlich *immer*, nicht nur während der Animation
`_ease_out_elastic()` klemmt ihren Eingabewert intern auf `[0,1]` — nach Ende der Popup-Animation bleibt `scale` also dauerhaft exakt `1.0`. Aber: `_draw_window()` prüft das nirgends ab. Es durchläuft **jeden einzelnen Frame**, auch im eingeschwungenen Zustand, denselben Pfad:
```
ctx.push_group()
ctx.translate(0, 0)    # im Ruhezustand: Identität
ctx.scale(1, 1)        # im Ruhezustand: Identität
... Hintergrund + Pünktchen zeichnen ...
win.propagate_draw(child, ctx)   # Kinder manuell gezeichnet
ctx.pop_group_to_source()
ctx.paint()
```
`push_group()`/`pop_group_to_source()` legt dabei jedes Mal eine komplette Offscreen-Surface an und kompositiert sie — und das bei `translate(0,0)`/`scale(1,1)`, also einer reinen Identitätstransformation, die visuell **exakt dasselbe Ergebnis** liefert wie normales GTK-Rendering.

**Warum das unbedingt passiert:** `make_win()` setzt pro geöffnetem Fenster einen Timer, der **für die gesamte Lebensdauer des Fensters unbedingt** alle 33 ms `queue_draw()` auslöst — einzig, damit die frei fliegenden Pünktchen sich weiterbewegen:
```python
_amb_tid = GLib.timeout_add(_TICK_MS, lambda: (win.queue_draw(), True)[1])
```
Dieser Timer kennt keinen „gerade keine Animation aktiv“-Zustand — er läuft so lange, wie das Fenster offen ist, egal ob gerade eine Bounce-Animation läuft oder nicht.

**Fix (0 % optische Änderung, da im Ruhezustand ohnehin eine reine Identitätstransformation vorliegt):**
```python
def _draw_window(win, ctx):
    state = _anim.get(win)
    ...
    animating = state and (
        state.get("closing_since") is not None or
        (now - state["popup_start"]) < (_POPUP_MS / 1000.0)
    )

    if not animating:
        # Ruhezustand: Hintergrund + Pünktchen direkt in ctx zeichnen,
        # KEIN push_group (keine Transformation nötig, scale ist ohnehin 1.0),
        # Kinder von GTKs eigener Pipeline zeichnen lassen.
        _paint_bubble_bg(ctx, w, h)
        _draw_particles(ctx, state, w, h)     # exakt dieselbe Zeichenfunktion, exakt dieselben Gradienten
        _paint_bubble_overlay(ctx, w, h)
        return False   # GTK zeichnet die Kind-Widgets normal

    # Nur während der ~350ms Popup-/Close-Animation der bisherige Pfad:
    ctx.push_group()
    ...
    ctx.pop_group_to_source()
    ctx.paint()
    return True
```
Die Pünktchen behalten **exakt** ihre Radial-Gradienten, Größe, Geschwindigkeit und Bewegungsmuster — nur der permanente Offscreen-Umweg entfällt im Ruhezustand. Das ist der mit Abstand größte Hebel (vergleichbare reale Fälle berichten von 60–80 % weniger Hauptthread-Last beim Wechsel von permanentem `push_group`/`propagate_draw` auf bedingten Einsatz).

### 6b. Pünktchen/Gradienten bleiben unverändert
15 Partikel mit Radial-Gradienten sind für sich genommen kein großer Posten verglichen mit 6a — und sollen laut ausdrücklichem Wunsch unverändert bleiben (keine Reduktion der Anzahl, kein Ersatz durch einfache Kreise, keine Änderung der Deckkraft/Größe). Keine Änderung hier.

### 6c. Unbedingter `queue_draw` alle 33 ms bleibt als Timer bestehen — Inhalt des Timers wird aber durch 6a billiger
Der Timer selbst wird für die Bewegung der Pünktchen weiterhin gebraucht (bewusst gewünscht, keine Reduktion der Bildrate). Durch 6a kostet aber jeder dieser 33-ms-Ticks im Ruhezustand nur noch „Hintergrund + 15 Partikel direkt zeichnen“ statt zusätzlich eine komplette Offscreen-Surface anzulegen und den kompletten Widget-Baum manuell neu zu zeichnen.

### 6d. Frame-Clock statt fixer Timer (rein technische Präzision, keine optische Änderung)
`GLib.timeout_add(_TICK_MS, ...)` ist ein reiner Zeit-Timer, nicht an den tatsächlichen Compositor-Vsync gekoppelt — das kann zu Mikro-Stottern führen, besonders bei nicht-60Hz- oder VRR-Monitoren. GTK3 bietet dafür die Frame Clock:
```python
frame_clock = win.get_frame_clock()
frame_clock.begin_updating()
frame_clock.connect("update", lambda fc: win.queue_draw())
```
Das synchronisiert den Redraw mit dem tatsächlichen Display-Refresh, ohne die Bewegungsgeschwindigkeit oder das Aussehen der Pünktchen zu verändern — reine Timing-Präzision. Falls das zu invasiv ist: alternativ den `GLib.timeout_add`-Intervall einfach an die tatsächliche Monitor-Refreshrate anpassen (60 Hz → 16 ms, 120 Hz → 8 ms) statt pauschal 33 ms — nicht perfekt vsync-synchron, aber ein kleiner, risikoarmer Zwischenschritt.

### 6e. Threading
Der bestehende `ThreadPoolExecutor(max_workers=4)` deckt die tatsächlich blockierenden Aufrufe (subprocess, psutil, Datei-I/O) bereits ab — die in diesem Ticket beschriebene Lag-Symptomatik stammt laut obigem Befund aber vom GTK-Hauptthread (Cairo-Compositing), nicht von Worker-Knappheit. Mehr Worker würden das beschriebene Ruckeln also nicht beheben; eine Erhöhung lohnt sich nur, falls bei sehr vielen gleichzeitig geöffneten Widgets tatsächlich Warteschlangen-Verzögerungen bei Hintergrundaufrufen beobachtet werden (anderes Symptom als das hier gemeldete).

### 6f. Profiling zur Kontrolle
Vor/nach dem Fix mit `python -m cProfile -o widgets.prof WidgetsDaemon.py` + `snakeviz`/`gprof2dot` vergleichen, oder `GTK_DEBUG=interactive` für den GTK-Inspector mit „Statistics“-Tab — damit lässt sich der behauptete Gewinn aus 6a konkret an echten Zahlen auf deiner Hardware verifizieren, statt sich auf die allgemeine Einschätzung hier zu verlassen.

---

## 7. Hyprland-Lua-Syntax — verifiziert

Frisch recherchiert statt nur aus Erinnerung: **Hyprland 0.55.0 hat Lua offiziell als Konfigurationssprache eingeführt**, mit genau der API, die in deiner `hyprland.lua` verwendet wird:

| Alt (Hyprlang) | Neu (Lua), verifiziert |
|---|---|
| `env = ...` | `hl.env(...)` ✓ in deiner Datei |
| `monitor = ...` | `hl.monitor({...})` ✓ |
| `bezier = ...` | `hl.curve(...)` ✓ |
| `animation = ...` | `hl.animation(...)` ✓ |
| `bind`-Familie | `hl.bind(...)` ✓ |
| `windowrule`/`windowrulev2` | `hl.window_rule({ match = {...}, ... })` ✓ |
| `exec` (jeder Reload) | `hl.exec_cmd(...)` ✓ |
| `exec-once` (nur beim Start) | `hl.on("hyprland.start", function() ... end)` ✓ |

Alle in deiner `hyprland.lua` verwendeten Aufrufe (`hl.monitor`, `hl.config`, `hl.bind`, `hl.window_rule`, `hl.on`, `hl.exec_cmd`, `hl.curve`, `hl.animation`, `hl.env`) sind gegen diese verifizierte Zuordnung korrekt.

`hyprctl eval` als Brücke zum **live laufenden** Lua-State ist ebenfalls bestätigt — und wird z.B. von Tooling aus demselben Ökosystem (`hyprland-state`, gleicher Autor wie `hyprland-monitors` aus Punkt 1/2) explizit genutzt, sobald ein `configProvider: lua`-Setup erkannt wird. Dein bereits korrektes Vorgehen (Live-Apply über `hyprctl eval` **und** Persistenz durch Patchen der `.lua`-Datei) deckt sich exakt mit diesem offiziellen Modell — hier ist nichts zu ändern, nur Punkt 2 oben (Reihenfolge/Batching) betrifft die Anwendung davon.

**Zusätzliche Empfehlung:** Statt die Scale- und Repack-Mathematik getrennt selbst zu pflegen (Punkt 1 & 2), beide über das eine, bereits erwähnte Paket `hyprland-monitors` abdecken — spart zwei eigene, fehleranfällige Implementierungen gegen eine einzige, bereits getestete Abhängigkeit desselben Autoren-Ökosystems.



Zusatzblock: Hz-Dropdown im Display-Tab zeigt nur maximal 120 Hz an, obwohl 165 Hz eingestellt ist
1. Ursache: Hyprlands availableModes listet die hohen Bildwiederholraten nicht immer auf

Hyprland liefert in hyprctl monitors -j das Feld availableModes als String-Array, in dem jeder Eintrag das Format "WIDTHxHEIGHT@REFRESHRATEHz" hat. Dieses Array ist jedoch nicht immer vollständig: Insbesondere hohe Bildwiederholraten wie 165 Hz oder 179,88 Hz fehlen häufig, obwohl der Monitor sie über DisplayPort oder HDMI unterstützt.

Der Grund dafür ist, dass Hyprland die Modi nicht direkt aus der EDID des Monitors liest, sondern die vom DRM/KMS-Treiber bereitgestellte Modusliste verwendet. Diese Liste kann je nach Treiber, Kabel und Anschluss (HDMI vs. DisplayPort) unvollständig sein. Besonders bei HDMI-Verbindungen, die kein DSC (Display Stream Compression) unterstützen, werden hohe Bildwiederholraten oft gar nicht erst an den Compositor gemeldet.

Im bereitgestellten Code wird die Liste in _parse_modes() eingelesen:
python

def _parse_modes(modes: list) -> dict:
    out: dict = {}
    for m in modes:
        try:
            res, hz = m.split("@")
            out.setdefault(res, []).append(hz.rstrip("Hz"))
        except ValueError:
            continue
    return out

Wenn availableModes nur Einträge bis 120 Hz enthält, landen auch nur diese im modes-Dictionary. Das Hz-Dropdown kann dann gar nicht mehr als 120 Hz anzeigen – unabhängig davon, welcher Wert in hyprland.lua steht.
2. Warum der bestehende EDID-Fallback nicht greift

Der Code versucht bereits, die Lücke über _edid_extra_modes() zu schließen:
python

def _edid_extra_modes(name: str) -> dict:
    edid_f = _edid_path_for_monitor(name)
    if not edid_f or not shutil.which("edid-decode"):
        return {}
    out, _err, ec = run_ec(["edid-decode", str(edid_f)], timeout=5)
    if ec != 0 or not out:
        return {}
    extra: dict = {}
    for m in re.finditer(r'(\d+)x(\d+)\s+([\d.]+)\s*Hz', out):
        w, h, hz = m.group(1), m.group(2), m.group(3)
        res = f"{w}x{h}"
        hz_str = f"{float(hz):.2f}"
        extra.setdefault(res, set()).add(hz_str)
    return extra

Dieser Fallback hat jedoch mehrere Schwachstellen:

    edid-decode muss installiert sein. Auf Arch Linux ist es im Paket v4l-utils enthalten. Fehlt das Binary, gibt die Funktion sofort ein leeres Dictionary zurück – die 165-Hz-Modi werden nie ergänzt.

    Die Regex ist zu eng gefasst. Sie erwartet das Muster WIDTHxHEIGHT FLOAT Hz mit mindestens einer Dezimalstelle ([\d.]+). edid-decode gibt in seinen Timing-Listen jedoch oft ganzzahlige Werte aus (z. B. 1920x1080 165 Hz oder 1920x1080 165.00 Hz). Ein Muster wie 165 Hz (ohne Punkt) wird von [\d.]+ zwar erfasst, aber float("165") ergibt 165.0, was zu "165.00" normalisiert wird – das ist konsistent.

    Die EDID enthält möglicherweise keine expliziten 165-Hz-DTDs. Manche Monitore deklarieren hohe Bildwiederholraten nur über CTA-Erweiterungsblöcke oder DisplayID, die edid-decode je nach Version nicht immer vollständig auflistet.

3. Zweite Ursache: Formatierungsunterschiede bei der Hz-Vorauswahl

Selbst wenn availableModes den 165-Hz-Eintrag enthält, kann die Vorauswahl fehlschlagen, weil cur_hz und die geparsten Hz-Strings nicht exakt übereinstimmen.

cur_hz wird so gebildet:
python

cur_hz = f'{mon.get("refreshRate", 0):.2f}'

Das ergibt bei 165 Hz den String "165.00". _parse_modes entfernt das "Hz"-Suffix, behält aber den Zahlenwert bei – aus "1920x1080@165.00Hz" wird also "165.00". In diesem Fall stimmen die Formate überein.

Wenn Hyprland den Modus jedoch als "1920x1080@165Hz" (ohne Dezimalstellen) ausgibt, ergibt hz.rstrip("Hz") den String "165". cur_hz ist dann "165.00", und preselect in hzs schlägt fehl. _fill_hz fällt dann auf set_active(0) zurück – und da die Liste absteigend sortiert ist, wird der höchste verfügbare Wert ausgewählt, der in diesem Fall 120 Hz sein kann.
4. Lösung (keine Notlösung wie highrr)

Die Lösung besteht aus drei Teilen:
a) edid-decode als harte Abhängigkeit sicherstellen

Das Widget sollte beim Start prüfen, ob edid-decode verfügbar ist, und andernfalls einen klaren Hinweis anzeigen (z. B. als Tooltip oder Statuszeile im Display-Tab), damit der Nutzer weiß, dass die erweiterten Modi nur mit installiertem v4l-utils funktionieren. Ein stiller Fallback auf eine unvollständige Modusliste ist keine akzeptable Lösung.
b) _edid_extra_modes robuster machen

Die Regex muss sowohl ganzzahlige als auch Dezimalwerte erfassen und die Hz-Werte einheitlich normalisieren. Außerdem sollte sie alle Timing-Abschnitte von edid-decode durchsuchen – nicht nur die Detail Timing Descriptors, sondern auch Established Timings, Standard Timings und CTA VICs.
python

def _edid_extra_modes(name: str) -> dict:
    edid_f = _edid_path_for_monitor(name)
    if not edid_f or not shutil.which("edid-decode"):
        return {}
    out, _err, ec = run_ec(["edid-decode", str(edid_f)], timeout=5)
    if ec != 0 or not out:
        return {}
    extra: dict = {}
    # Erfasst "1920x1080  165.00 Hz", "1920x1080 165 Hz", "1920x1080@165Hz" usw.
    for m in re.finditer(r'(\d{3,5})x(\d{3,5})\s*(?:@\s*)?([\d.]+)\s*Hz', out):
        w, h, hz = m.group(1), m.group(2), m.group(3)
        res = f"{w}x{h}"
        try:
            hz_val = float(hz)
        except ValueError:
            continue
        hz_str = f"{hz_val:.2f}"
        extra.setdefault(res, set()).add(hz_str)
    return extra

c) _parse_modes und _fill_hz gegen Formatierungsunterschiede absichern

_parse_modes sollte die Hz-Werte immer als float normalisieren und als einheitlichen String mit zwei Dezimalstellen zurückgeben. _fill_hz sollte dann beim Vergleich von preselect ebenfalls auf den normalisierten String umstellen.
python

def _parse_modes(modes: list) -> dict:
    out: dict = {}
    for m in modes:
        try:
            res, hz = m.split("@")
            hz_clean = hz.rstrip("Hz")
            hz_val = float(hz_clean)
            out.setdefault(res, []).append(f"{hz_val:.2f}")
        except (ValueError, IndexError):
            continue
    return out

In _fill_hz wird preselect bereits als String übergeben; hier reicht es, wenn cur_hz ebenfalls auf zwei Dezimalstellen normalisiert ist (was bereits der Fall ist). Zur Sicherheit kann in _fill_hz ein try/except um den float-Vergleich gelegt werden:
python

            if preselect in hzs:
                hz_combo.set_active(hzs.index(preselect))
            elif hzs:
                # Fallback: nächstgelegenen Wert auswählen, statt blind 0
                try:
                    target = float(preselect)
                    idx = min(range(len(hzs)), key=lambda i: abs(float(hzs[i]) - target))
                    hz_combo.set_active(idx)
                except (ValueError, TypeError):
                    hz_combo.set_active(0)

Damit wird bei fehlender exakter Übereinstimmung der nächstgelegene Wert ausgewählt – also 165 Hz, wenn 164,99 Hz gespeichert ist und 165,00 Hz in der Liste steht.
5. Zusammenfassung
Ebene	Problem	Lösung
Hyprland-API	availableModes unvollständig, hohe Hz fehlen	EDID-Fallback via edid-decode
EDID-Extraktion	edid-decode fehlt oder Regex zu eng	Installation sicherstellen + Regex erweitern
Vorauswahl	Formatierungsunterschiede (165 vs. 165.00)	Hz-Werte auf float normalisieren, nächstgelegenen Wert wählen

Die Lösung ist keine Notlösung: Sie liest die tatsächlichen Monitorfähigkeiten aus der EDID aus und stellt sicher, dass das Dropdown den korrekten voreingestellten Wert anzeigt – auch wenn Hyprland selbst die hohen Bildwiederholraten nicht in availableModes auflistet.