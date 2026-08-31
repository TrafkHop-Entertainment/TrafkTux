#!/usr/bin/env bash
#
# GameScopeWineWrapper.sh
#
# Transparent gamescope wrapper for Wine. Installed distro-wide as
# /usr/local/bin/wine and /usr/local/bin/wine64 (symlinks pointing back
# to this script; PATH puts /usr/local/bin before /usr/bin, so every
# launcher - desktop icons, Lutris, Bottles, custom Rofi entries - ends
# up going through here automatically without anyone typing "gamescope"
# by hand).
#
# What it fixes for legacy DirectDraw/D3D titles running under Wine:
#   - old-style exclusive fullscreen grabs, which fight Hyprland and
#     re-trigger themselves right after Super/keybinds are used
#   - PictureInPicture.sh breaking because the window is never a normal
#     floating/tiled Hyprland window
#   - tiny native-resolution games (480p, 800x600, ...) rendering into a
#     small box in the corner while the rest of the screen stays black
#   - the same problem showing up even when "windowed mode" is selected
#
# It does NOT need a per-game resolution database: gamescope natively
# intercepts the legacy mode-switch request the game makes internally
# and upscales the result to the real output size - that's exactly what
# it was built for (see: Steam Deck).

set -u

# Windows/NTFS is case-insensitive; Linux isn't. A .lnk's stored target
# path routinely has different casing than the real file on disk (e.g.
# "MoorhuhnJagd" in the shortcut vs. the actual "Moorhuhnjagd" folder).
# Walks a relative path component-by-component under $base, matching each
# piece case-insensitively, and prints the real on-disk path if found.
resolve_case_insensitive() {
    local base="$1" rel="$2"
    local current="$base" part match
    local oldIFS="$IFS"
    IFS='/'
    for part in $rel; do
        [ -z "$part" ] && continue
        match="$(find "$current" -maxdepth 1 -iname "$part" 2>/dev/null | head -n1)"
        if [ -n "$match" ]; then
            current="$match"
        else
            IFS="$oldIFS"
            return 1
        fi
    done
    IFS="$oldIFS"
    printf '%s' "$current"
}

RealWineBin="/usr/bin/wine"
RealWine64Bin="/usr/bin/wine64"
ConfigDir="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
ConfigFile="$ConfigDir/GameScopeWrapper.conf"
ExcludeFile="$ConfigDir/GameScopeExcludes.txt"
DefaultsRegFile="/usr/share/trafktux/WineWrapperDefaults.reg"

# --- Which real binary is this shim standing in for? --------------------
CalledAs="$(basename "$0")"
case "$CalledAs" in
    wine64) RealBin="$RealWine64Bin" ;;
    *)      RealBin="$RealWineBin" ;;
esac

if [ ! -x "$RealBin" ]; then
    echo "GameScopeWineWrapper: $RealBin not found, is wine installed?" >&2
    exit 1
fi

# Already running inside a gamescope-wrapped invocation (wineserver
# helpers, a nested wine64 spawned by wine itself, ...) -> never wrap
# twice, just pass through.
if [ -n "${GameScopeWrapperActive:-}" ]; then
    exec "$RealBin" "$@"
fi

# --- Load config (plain KEY=VALUE, sourced as shell vars) ---------------
# This file is meant to be written by the Widgets settings hub - keep it
# boring shell-var syntax so nothing fancy is needed to edit it.
Enabled="true"
Filter="nearest"
Scaler="fit"
Sharpness="2"
ForceWindowsFullscreen="false"

if [ -f "$ConfigFile" ]; then
    # shellcheck disable=SC1090
    source "$ConfigFile"
fi

if [ "$Enabled" != "true" ]; then
    exec "$RealBin" "$@"
fi

# --- Figure out what's actually being launched ----------------------------
# Wine's OWN auto-generated Start Menu entries (created on install, the ones
# you see in Rofi/app launchers) call wine with a .lnk shortcut, NOT the
# .exe directly - Wine resolves the .lnk to the real target internally.
# CONFIRMED BUG: Wine's own .lnk resolution path (SHELL_execute ->
# ShellLink_InvokeCommand) loses the shortcut's working directory along the
# way (it gets read correctly once, then silently overwritten with an empty
# string before the child process is spawned). Since several of these old
# games need their own folder as CWD to find their assets, the child dies
# instantly and silently - Wine still reports "success" back up the chain.
# Fix: resolve the .lnk ourselves, cd into the target's own folder (which
# we already know from earlier debugging is what these games actually
# need), and hand Wine the .exe directly - bypassing its broken internal
# path entirely.
TargetExe=""
for Arg in "$@"; do
    case "$Arg" in
        *.exe|*.EXE) TargetExe="$(basename "$Arg")" ;;
        *.lnk|*.LNK)
            EffectivePrefixForLnk="${WINEPREFIX:-$HOME/.wine}"
            # $Arg is the Windows-style path to the .lnk itself (e.g.
            # C:\ProgramData\...\Foo.lnk) - has to be converted to the real
            # Unix path on disk before we can open() it at all. (First
            # version of this fix forgot this step entirely and always
            # failed silently here, falling back to the broken raw-.lnk
            # path every time.)
            if [ -f "$Arg" ]; then
                LnkReadPath="$Arg"
            else
                LnkReadPath="$EffectivePrefixForLnk/drive_c/$(printf '%s' "$Arg" | sed 's/^[A-Za-z]://; s/\\/\//g; s|^/||')"
            fi
            ResolvedWinPath=""
            if command -v python3 >/dev/null 2>&1 && [ -f "$LnkReadPath" ]; then
                ResolvedWinPath="$(python3 - "$LnkReadPath" <<'PYEOF'
import struct, sys
try:
    with open(sys.argv[1], "rb") as f:
        data = f.read()
    if len(data) < 76 or data[0:4] != b"\x4c\x00\x00\x00":
        sys.exit(1)
    flags = struct.unpack_from("<I", data, 20)[0]
    offset = 76
    if flags & 0x1:  # HasLinkTargetIDList
        idlist_size = struct.unpack_from("<H", data, offset)[0]
        offset += 2 + idlist_size
    if flags & 0x2:  # HasLinkInfo
        li_start = offset
        li_size = struct.unpack_from("<I", data, li_start)[0]
        li_flags = struct.unpack_from("<I", data, li_start + 8)[0]
        if li_flags & 0x1:  # VolumeIDAndLocalBasePath present
            lbp_offset = struct.unpack_from("<I", data, li_start + 16)[0]
            start = li_start + lbp_offset
            end = data.index(b"\x00", start)
            print(data[start:end].decode("latin-1"))
except Exception:
    sys.exit(1)
PYEOF
)"
            fi
            if [ -n "$ResolvedWinPath" ]; then
                RelativeWinPath="$(printf '%s' "$ResolvedWinPath" | sed 's/^[A-Za-z]://; s/\\/\//g; s|^/||')"
                ResolvedUnixPath="$EffectivePrefixForLnk/drive_c/$RelativeWinPath"
                if [ ! -f "$ResolvedUnixPath" ]; then
                    CaseMatched="$(resolve_case_insensitive "$EffectivePrefixForLnk/drive_c" "$RelativeWinPath")"
                    [ -n "$CaseMatched" ] && ResolvedUnixPath="$CaseMatched"
                fi
                ResolvedUnixDir="$(dirname "$ResolvedUnixPath")"
                ResolvedExeName="$(basename "$ResolvedUnixPath")"
                if [ -d "$ResolvedUnixDir" ] && [ -f "$ResolvedUnixPath" ]; then
                    cd "$ResolvedUnixDir" || true
                    set -- "$ResolvedExeName"
                    TargetExe="$ResolvedExeName"
                fi
            fi
            # If resolution failed for any reason, TargetExe stays whatever
            # it was - falls through to the raw .lnk pass-through below,
            # same as before (fail open, never block the launch entirely).
            [ -z "$TargetExe" ] && TargetExe="$(basename "$Arg")"
            ;;
    esac
done
TargetExeLower="$(printf '%s' "$TargetExe" | tr '[:upper:]' '[:lower:]')"

# Nothing resembling a launch target in the arguments at all (e.g.
# `wine --version`, internal `wine start /unix ...` helper calls) -> pass
# through untouched.
if [ -z "$TargetExe" ]; then
    exec "$RealBin" "$@"
fi

# Wine's own utility windows must NEVER be wrapped. This is exactly what
# caused the winecfg dialog to render with its OK/Cancel buttons clipped
# off earlier - forcing a fixed gamescope canvas onto a resizable native
# dialog is asking for the same bug all over again.
UtilityList="winecfg.exe regedit.exe wineboot.exe explorer.exe taskmgr.exe uninstaller.exe eject.exe control.exe notepad.exe wordpad.exe cmd.exe winefile.exe"
for Utility in $UtilityList; do
    if [ "$TargetExeLower" = "$Utility" ]; then
        exec "$RealBin" "$@"
    fi
done

# Per-game exclude list (one exe basename per line, case-insensitive,
# "#" comments allowed). For titles that fight with nested compositors.
if [ -f "$ExcludeFile" ]; then
    while IFS= read -r Line; do
        [ -z "$Line" ] && continue
        case "$Line" in \#*) continue ;; esac
        LineLower="$(printf '%s' "$Line" | tr '[:upper:]' '[:lower:]')"
        if [ "$LineLower" = "$TargetExeLower" ]; then
            exec "$RealBin" "$@"
        fi
    done < "$ExcludeFile"
fi

# --- One-time prefix setup ------------------------------------------------
# Imports the shipped defaults (X11 driver override + DirectInput
# MouseWarpOverride) into any prefix the very first time it's used through
# here. Hardened against a broken/missing .reg file: `wine regedit` pops a
# blocking dialog on failure, which without a timeout would hang every
# single future launch forever (this happened once during development -
# never again). Always marks as attempted regardless of outcome, so a
# broken reg file only ever costs one skipped import, never a stuck game.
EffectivePrefix="${WINEPREFIX:-$HOME/.wine}"
if [ -d "$EffectivePrefix" ]; then
    MarkerFile="$EffectivePrefix/.gamescope-wrapper-initialized"
    if [ ! -f "$MarkerFile" ]; then
        if [ -f "$DefaultsRegFile" ] && [ -r "$DefaultsRegFile" ]; then
            timeout 10 "$RealBin" regedit "$DefaultsRegFile" </dev/null >/dev/null 2>&1
        fi
        touch "$MarkerFile" 2>/dev/null
    fi
fi

# --- dgVoodoo2 auto-injection for legacy DirectDraw titles -----------------
# Some old games never request a real fullscreen mode-switch (small fixed
# windowed DirectDraw surface instead), so gamescope has nothing to scale
# for them - an architectural limit, not a gamescope bug (confirmed via two
# separate gamescope-side approaches that both failed to fix this). Games
# that statically link/import DDRAW.DLL are detected once per game folder
# and dgVoodoo2's own ddraw.dll/D3DImm.dll get dropped in next to the exe,
# which intercepts DirectDraw calls before the game ever decides what mode
# to render in. No per-game setup, no exclude list.
DgvoodooSrcDir="/usr/share/trafktux/dgvoodoo2"
FullExePath="$(pwd)/$TargetExe"
GameDir="$(dirname "$FullExePath")"
DgvoodooCheckedMarker="$GameDir/.dgvoodoo2-checked"
DgvoodooInjectedMarker="$GameDir/.dgvoodoo2-injected"

if [ -f "$FullExePath" ] && [ -d "$DgvoodooSrcDir" ] && [ ! -f "$DgvoodooCheckedMarker" ]; then
    if command -v strings >/dev/null 2>&1 \
        && strings -a "$FullExePath" 2>/dev/null | grep -qi "ddraw\.dll"; then
        if [ ! -f "$GameDir/ddraw.dll" ] \
            && [ -f "$DgvoodooSrcDir/ddraw.dll" ] \
            && [ -f "$DgvoodooSrcDir/d3dim.dll" ]; then
            cp "$DgvoodooSrcDir/ddraw.dll" "$GameDir/ddraw.dll" 2>/dev/null
            cp "$DgvoodooSrcDir/d3dim.dll" "$GameDir/d3dim.dll" 2>/dev/null
            [ -f "$GameDir/ddraw.dll" ] && touch "$DgvoodooInjectedMarker" 2>/dev/null
        fi
    fi
    touch "$DgvoodooCheckedMarker" 2>/dev/null
fi

if [ -f "$DgvoodooInjectedMarker" ]; then
    # Tell Wine to prefer the game-folder ("native") DLLs we just placed
    # over its own builtin ddraw/d3dim implementation for this launch.
    export WINEDLLOVERRIDES="ddraw,d3dim=n,b${WINEDLLOVERRIDES:+;$WINEDLLOVERRIDES}"
fi

# --- Determine the real output resolution to hand to gamescope -----------
OutputWidth="1920"
OutputHeight="1080"
if command -v hyprctl >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
    MonitorJson="$(hyprctl monitors -j 2>/dev/null)"
    if [ -n "$MonitorJson" ]; then
        ReadWidth="$(printf '%s' "$MonitorJson" | jq -r '[.[] | select(.focused == true)][0].width // empty')"
        ReadHeight="$(printf '%s' "$MonitorJson" | jq -r '[.[] | select(.focused == true)][0].height // empty')"
        [ -n "$ReadWidth" ] && OutputWidth="$ReadWidth"
        [ -n "$ReadHeight" ] && OutputHeight="$ReadHeight"
    fi
fi

# --- Launch ----------------------------------------------------------------
if ! command -v gamescope >/dev/null 2>&1; then
    # gamescope missing for whatever reason -> fail open, run natively
    # rather than blocking the game from starting at all.
    exec "$RealBin" "$@"
fi

# The naive approach - handing gamescope the game process directly and
# trusting its default "exit when the wrapped process exits" behavior -
# breaks in two well-known ways with real games:
#   1. Old titles routinely ignore the polite window-close request, so
#      closing the gamescope window (or the game's own Exit button, which
#      often hangs mid-teardown under Wine) leaves everything running.
#   2. Two-stage launchers (update check -> spawn real game as a NEW
#      process -> launcher exits) trick gamescope into tearing the whole
#      session down the moment the launcher exits, killing the real game
#      before it even gets going (observed with LS22).
# Fix: a small supervisor script becomes gamescope's direct child instead.
# It launches the real command, and after that returns, actively polls for
# any surviving/newly-appeared game-like process before letting the
# session end - and force-kills everything on any termination signal, so
# closing the window always works regardless of whether the game itself
# cooperates.
LaunchScript="$(mktemp /tmp/gamescope-launch-XXXXXX.sh)"
cat > "$LaunchScript" <<'SUPERVISOR_EOF'
#!/usr/bin/env bash
# Ignore lists: Wine's own always-on background helpers, never the actual
# game, so they must never count as "a game is still running".
IgnorePattern='winedevice\.exe|explorer\.exe|services\.exe|plugplay\.exe|rpcss\.exe|svchost\.exe|wineboot\.exe|start\.exe|conhost\.exe|winemenubuilder\.exe'

# Scoped strictly to THIS launch's own descendant process tree (not a
# system-wide scan) - so two games running simultaneously in separate
# gamescope sessions never interfere with each other's close-detection.
CollectDescendants() {
    local parent="$1" pid
    for pid in $(ps -eo pid=,ppid= 2>/dev/null | awk -v p="$parent" '$2==p{print $1}'); do
        echo "$pid"
        CollectDescendants "$pid"
    done
}

AnyGameProcessAlive() {
    local pid cmd
    for pid in $(CollectDescendants "$$"); do
        cmd="$(ps -o cmd= -p "$pid" 2>/dev/null)"
        [ -z "$cmd" ] && continue
        if printf '%s' "$cmd" | grep -iE '\.exe($|[[:space:]])' | grep -qviE "$IgnorePattern"; then
            return 0
        fi
    done
    return 1
}

ForceKillEverything() {
    local pid
    for pid in $(CollectDescendants "$$"); do
        kill -9 "$pid" 2>/dev/null
    done
    exit 0
}
trap ForceKillEverything TERM INT HUP

# Hyprland's kill/force-kill sends its signal directly to gamescope (the
# actual window-owning process from its point of view) - not to us. If
# gamescope doesn't reliably forward that signal down to its own children
# (observed: it doesn't, always), our TERM/INT trap above never fires no
# matter what Hyprland does. Fix: watch our own parent (gamescope) directly
# and self-destruct the instant it's gone, for ANY reason - no signal
# forwarding required.
(
    ParentPid="$PPID"
    while kill -0 "$ParentPid" 2>/dev/null; do
        sleep 1
    done
    ForceKillEverything
) &
WatchdogPid=$!

# Run the actual game command.
"$@" &
LauncherPid=$!
wait "$LauncherPid"

# The initial process is gone. Give a short window for a relaunched real
# game process to appear (covers the "launcher spawns game, exits itself"
# pattern) before giving up entirely.
Waited=0
while [ "$Waited" -lt 15 ]; do
    AnyGameProcessAlive && break
    sleep 1
    Waited=$((Waited + 1))
done

# If something is running (whether it was there all along or just
# appeared), stay alive and keep the gamescope session open for as long
# as it keeps running.
while AnyGameProcessAlive; do
    sleep 1
done

# Normal, clean exit path - the watchdog subshell would otherwise be left
# running forever as an orphan once this script exits.
kill "$WatchdogPid" 2>/dev/null
SUPERVISOR_EOF
chmod +x "$LaunchScript"
trap 'rm -f "$LaunchScript"' EXIT

export GameScopeWrapperActive="1"
# Disables gamescope's Vulkan WSI interception layer for the wrapped game.
# Confirmed root cause of a real crash (Paradise Beach, and likely other
# titles using less common texture formats): gamescope's WSI hook chokes
# on certain formats even when Wine's own wined3d renderer handles them
# fine on its own (reproduced with wined3d forced to its OpenGL backend
# too - the crash is specifically in gamescope's interception, not Wine).
# Confirmed fix: with this disabled, the exact same game/format combo runs
# through gamescope without crashing. Global default, not per-game - the
# WSI layer mainly buys gamescope some Vulkan-level present optimizations
# that legacy titles running through wined3d don't meaningfully benefit
# from anyway.
export ENABLE_GAMESCOPE_WSI=0
ExtraGamescopeFlags=()
if [ "$ForceWindowsFullscreen" = "true" ]; then
    ExtraGamescopeFlags+=("--force-windows-fullscreen")
fi
gamescope \
    -W "$OutputWidth" -H "$OutputHeight" \
    -F "$Filter" -S "$Scaler" --fsr-sharpness "$Sharpness" \
    -b \
    "${ExtraGamescopeFlags[@]}" \
    -- bash "$LaunchScript" "$RealBin" "$@"
GamescopeExitCode=$?
rm -f "$LaunchScript"
exit "$GamescopeExitCode"