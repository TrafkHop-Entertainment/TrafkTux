# TrafkTux: Optionale Pakete (Kurzdoku)

Stand: 2026-10-06. Diese Datei erklärt grob, wie die optionalen Pakete funktionieren, damit man später nicht alles neu rekonstruieren muss.

## Idee in einem Absatz

Optionale Software wird als kleine **Metapakete** (`TrafkTuxOptional-<Gruppe>`) angeboten, die in **Pamac** wie normale Pakete erscheinen. Die Metapakete liegen in einem winzigen **lokalen Repo** (`/opt/TrafkTuxOptional`), nichts wird online gehostet und nichts muss von Hand aktuell gehalten werden. Was pacman selbst installieren kann (Arch-Repos), kommt als echte Abhängigkeit. Was pacman nicht kann (AUR, Flatpak, Benutzergruppen, Direkt-Downloads), erledigt danach ein kleiner **Watcher** in der Hyprland-Session. Die Calamares-Installation selbst bleibt komplett offline und kennt die optionalen Pakete nicht.

## Bausteine

| Datei | Ort im Profil | Aufgabe |
|---|---|---|
| `OptionalGroups.conf` | Profil-Root | Definition aller Gruppen (einzige Stelle, die man normalerweise bearbeitet) |
| `BuildOptionalRepo.sh` | Profil-Root | Baut die Metapakete + Repo-DB nach `airootfs/opt/TrafkTuxOptional` |
| `pacman.conf` (airootfs) | `airootfs/etc/` | Enthält `[TrafkTuxOptional]` mit `Server = file:///opt/TrafkTuxOptional`, **kein** `[trafktux]` |
| `pacman.conf` (Profil) | Profil-Root | Unverändert, enthält `[trafktux]` mit Platzhalter (wird von `build-iso.sh` ersetzt) |
| `install-aur-packages.sh` | `airootfs/usr/local/bin/` | Installiert die vorgebauten AUR-Pakete beim Install, über eine **temporäre** pacman-Config |
| `shellprocess-cleanup.conf` | Calamares-Module | Löscht `/opt/trafktux-repo` + DB, initialisiert den Pacman-Keyring |
| `SystemUpdate.sh` | `airootfs/usr/local/lib/trafktux/` | Holt das GitHub-Repo, kopiert die Dateien ins System (Backups), löscht den Klon wieder. Von den `TrafkTuxUpdate-*`-Metapaketen oder von Hand gestartet (Rechte 755, root-eigen, in `profiledef.sh` eingetragen) |
| `OptionalSync.sh` | `airootfs/usr/local/lib/trafktux/` | Watcher/Installer für AUR, Flatpak, Gruppen, Downloads (Rechte **755**, in `profiledef.sh` eingetragen) |
| Autostart-Zeile | `hyprland.lua` | `bash /usr/local/lib/trafktux/OptionalSync.sh --watch` |

## Ablauf

**Beim ISO-Bau**
1. `sudo pacman -Sy`, dann `./BuildOptionalRepo.sh`: liest `OptionalGroups.conf`, sortiert jedes Paket selbst (in Arch-Repos laut `pacman -Si` = Abhängigkeit, sonst im AUR = Liste, sonst Abbruch), baut je Gruppe ein Metapaket und erzeugt die Repo-DB.
2. `build-iso.sh` prüft, ob `trafktux.db` und `TrafkTuxOptional.db` existieren, und baut das ISO.

**Bei der Installation (Calamares, offline)**
- `install-aur-packages.sh` kopiert die DBs in `/var/lib/pacman/sync/` und installiert die AUR-Zusatzpakete aus `/opt/trafktux-repo` mit einer temporären Config (Ziel-Config + `[trafktux]`).
- Das Cleanup löscht danach `/opt/trafktux-repo`. `/opt/TrafkTuxOptional` bleibt, Pamac braucht es.

**Beim Nutzer (Pamac)**
1. Nutzer installiert z. B. `TrafkTuxOptional-Emulators`. Pacman installiert die Abhängigkeiten und legt `/usr/share/TrafkTux/Optional/<Gruppe>.list` ab (plus ggf. `modules-load.d`-Datei, `.install` mit `systemctl enable --now`/`modprobe`).
2. Der Watcher sieht die neue Datei (Abfrage alle 5 s), wartet kurz und auf den Pacman-Lock und arbeitet die Liste ab:
   - `aur <name>` → `pamac build --no-confirm` (alle in einem Aufruf, bei Fehler einzeln). Steht das Paket inzwischen in den Arch-Repos, wird `pamac install` genommen.
   - `flatpak <id>` → `flatpak install --system` (Flathub-Remote wird bei Bedarf angelegt)
   - `group <name>` → `pkexec usermod -aG` (wirkt erst nach Neuanmeldung)
   - `pkgurl <url>` → Download + `pkexec pacman -U`
3. Passwortabfragen kommen als GUI-Dialog (Polkit-KDE-Agent). Kurze Benachrichtigungen am Anfang/Ende, Details im Log.

Die Liste enthält nur, was noch fehlt. Bereits Installiertes wird übersprungen.

## Systemupdate-Metapakete (`TrafkTuxUpdate-*`)

Drei Metapakete starten `SystemUpdate.sh`, eine Variante von `SyncEverything.sh`, die sich die Dateien selbst von GitHub holt:

| Paket | Aufruf | Bedeutung |
|---|---|---|
| `TrafkTuxUpdate-Fast` | `--fast` | ohne Icon-/Theme-Dumps (werden auch nicht heruntergeladen) |
| `TrafkTuxUpdate-FastFull` | `--fast --full` | ohne Icons/Themes, mit Grub/Plymouth/Boot (danach `grub-mkconfig` + `mkinitcpio -P`) |
| `TrafkTuxUpdate-Full` | `--full` | alles inklusive Boot |

- **Ablauf:** Metapaket installieren, Watcher liest `update <modus>` aus der `.list`-Datei, startet `SystemUpdate.sh <flags> --yes`. Das Skript klont `TrafkHop-Entertainment/TrafkTux` (Branch `main`, flach, nur die benötigten Ordner aus `archiso/airootfs`), fragt **einmal** per Polkit (`pkexec`) nach dem Passwort, kopiert alles in einem root-Prozess und löscht den Klon.
- **Rechte:** `etc/skel` wird mit den Rechten des Benutzers nach `$HOME` geschrieben (`runuser`), der Rest als root. Das Skript verweigert `pkexec`, wenn die Datei nicht root gehört oder für andere schreibbar ist.
- **Erneut ausführen:** Das Paket in Pamac neu installieren (der Watcher erkennt die neu geschriebene `.list`) oder direkt `bash /usr/local/lib/trafktux/SystemUpdate.sh [--fast] [--full]` (nie mit `sudo`). `--dry-run` zeigt nur an, was passieren würde.
- **Backups:** Benutzerdateien unter `~/.trafktux-sync-backups/<Zeit>`, Systemdateien unter `/var/backups/TrafkTuxUpdate/<Zeit>`. Log: `~/.local/state/TrafkTux/SystemUpdate.log`.
- **Selbst-Update:** Die Updates ersetzen auch `SystemUpdate.sh` und `OptionalSync.sh` selbst (atomar). Dafür müssen die neuesten Skripte im GitHub-Repo liegen.
- **Vertrauen:** Wer das GitHub-Repo kontrolliert, kontrolliert damit alle Systeme, die das Update ausführen (es schreibt als root nach `/etc`, u. a. `pam.d`). GitHub-Konto mit 2FA schützen. Repo-URL und Branch stehen fest im Skript.
- **Auf dem eigenen Entwicklungsrechner nicht blind ausführen:** Das Update überschreibt mit dem Stand von GitHub, nicht mit deinem lokalen Arbeitsstand.
- Einen Modus ohne Flags (nur Configs, mit Icons, ohne Boot) gibt es bewusst nicht als Paket. Ein weiterer Abschnitt in `OptionalGroups.conf` mit `Update = ...` reicht dafür nicht, der Modus müsste in `OptionalSync.sh` ergänzt werden.

## Gruppen ändern oder hinzufügen

In `OptionalGroups.conf`:

```
[Gruppenname]               # Paketname: TrafkTuxOptional-Gruppenname
Description = ...           # Text in Pamac (eine Zeile, ohne Anführungszeichen)
Packages    = a b c         # Arch-Repo oder AUR, wird automatisch sortiert
Flatpaks    = id1 id2       # Flathub-IDs
Services    = x.service     # wird im .install per systemctl enable --now aktiviert
ModulesLoad = sg            # Kernelmodul laden
Groups      = libvirt       # Benutzer per pkexec zur Gruppe hinzufügen
PkgUrls     = https://...   # fertiges .pkg.tar.zst
Name        = Paketname     # optional, überschreibt TrafkTuxOptional-<Gruppe>
Update      = fast|fastfull|full   # startet SystemUpdate.sh
```

Danach: `sudo pacman -Sy`, `./BuildOptionalRepo.sh` (mit `--dry-run` nur Vorschau), ISO neu bauen. Eine neue Gruppe ist einfach ein neuer `[Abschnitt]`.

## Testen auf dem eigenen System

1. `./BuildOptionalRepo.sh`, dann `sudo rsync -a --delete airootfs/opt/TrafkTuxOptional/ /opt/TrafkTuxOptional/`
2. In `/etc/pacman.conf` ganz unten:
   ```
   [TrafkTuxOptional]
   SigLevel = Optional TrustAll
   Server = file:///opt/TrafkTuxOptional
   ```
3. `sudo pacman -Sy`, dann Metapaket in Pamac installieren.
4. Watcher ohne Metapaket testen: Datei `/usr/share/TrafkTux/Optional/Test.list` mit einer Zeile wie `flatpak org.vinegarhq.Vinegar` anlegen und danach wieder löschen.
5. Alles nachholen/wiederholen: `bash /usr/local/lib/trafktux/OptionalSync.sh --now` (als normaler Benutzer, **nie mit sudo**).

`SyncEverything.sh` kopiert `OptionalSync.sh` und den Autostart automatisch. `etc/pacman.conf` und die Calamares-Dateien werden bewusst nicht gesynct.

## Wichtige Entscheidungen und Fallstricke

- **Keine `optdepends` für AUR/Flatpak.** Pamac zeigt sie sonst als auswählbare Pakete an, und die Auswahl scheitert mit "Ziel nicht gefunden". Die Liste steht stattdessen in der Paketbeschreibung.
- **Watcher läuft in der Hyprland-Session**, nicht als systemd-User-Dienst. Nur so ordnet Polkit ihn der Session zu und findet den Passwort-Dialog. Nie mit `sudo` starten, `pamac build` verweigert root.
- **`OptionalSync.sh` braucht Rechte 755.** `SyncEverything.sh` übernimmt die Rechte der Quelldatei, `600` dort führt dazu, dass der Autostart still ins Leere läuft.
- **Benachrichtigungen kurz halten.** Lange Texte mit Zahlen/Klammern und ein eigener App-Name haben `swaync` offenbar zum Absturz gebracht (Ursache nicht belegt). Abschaltbar mit `TRAFKTUX_OPTIONAL_NOTIFY=0`.
- **Metapakete haben das Build-Datum als Version.** Das lokale Repo ändert sich nur mit einem neuen ISO bzw. System-Update.
- **Entfernen eines Metapakets deinstalliert AUR-Apps und Flatpaks nicht**, nur die Pacman-Abhängigkeiten werden aufgeräumt. Die Queue kennt kein Deinstallieren.
- **Gruppen** gelten erst nach Neuanmeldung. `docker` wird bewusst nicht vergeben (praktisch root), `input` nur für TheClicker.
- **Nicht paketierbar:** DaVinci Resolve (manueller Download). `Learning` installiert nur Docker, der Juice-Shop-Container ist kein Paket.
- **Namen:** PascalCase nur für eigene Skripte und Namen, nicht in Arch-/Pamac-Config.
- `gimp` ist schon vorinstalliert und steht deshalb nicht in `Work`.
- Die Testing-Repos (`core-testing` usw.) sind in der `pacman.conf` aktiv und stehen vor den stabilen. Falls nicht gewollt, dort ändern.

## Fehlersuche

| Symptom | Prüfen |
|---|---|
| Nach der Installation passiert nichts | `pgrep -af OptionalSync` (muss als dein Benutzer laufen), `ls -l /usr/local/lib/trafktux/OptionalSync.sh` (755?), Log |
| Watcher läuft nicht | Neu starten: `setsid -f bash /usr/local/lib/trafktux/OptionalSync.sh --watch >/dev/null 2>&1` |
| Wo steht, was passiert ist | `~/.local/state/TrafkTux/OptionalSync.log` |
| Keine Benachrichtigung | Läuft `swaync`? `notify-send "Test" "Hallo"` |
| Build bricht ab | Meldung von `BuildOptionalRepo.sh`; `--dry-run` zeigt die Sortierung |
| Pacman meldet Signaturfehler im installierten System | Keyring-Init im Cleanup gelaufen? (`pacman-key --init`, `--populate archlinux`) |

## Noch zu prüfen

- Kompletter Durchlauf im ISO: Bau, Installation in der VM, danach `/opt/trafktux-repo` weg, `/opt/TrafkTuxOptional` da, `pacman -Syu` ohne Signaturfehler, Metapakete in Pamac sichtbar.
- `TrafkTuxUpdate-*` in der VM/auf einem Testsystem komplett durchlaufen lassen (Polkit-Dialog, Backups, bei `FastFull`/`Full` auch `grub-mkconfig` und `mkinitcpio -P`).
- Gruppen mit vielen AUR-Paketen (z. B. `Emulators`) einmal komplett durchlaufen lassen.
