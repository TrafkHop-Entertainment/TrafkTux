#!/usr/bin/env bash
# BuildOptionalRepo.sh
#
# Baut aus OptionalGroups.conf die Metapakete "TrafkTuxOptional-<Gruppe>" und
# legt sie als kleines lokales pacman-Repo in airootfs/opt/TrafkTuxOptional ab
# (genau wie build-local-repo.sh sein trafktux-repo). Die Metapakete sind nur
# ein paar KB gross und enthalten KEINE Apps: nur "depends" auf Pakete aus den
# Arch-Repos plus eine Liste (/usr/share/TrafkTux/Optional/<Gruppe>.list) fuer
# AUR/Flatpak/Sonderteile, die OptionalSync.sh nach der Installation abarbeitet.
#
# Sortierung der Pakete passiert HIER automatisch:
#   pacman -Si kennt das Paket  -> depends
#   sonst im AUR vorhanden      -> Liste (AUR)
#   sonst                       -> Abbruch mit Fehlermeldung
# Dafuer vorher die Paketdatenbank aktualisieren: sudo pacman -Sy
#
# Aufruf (NICHT als root, makepkg verweigert das):
#   ./BuildOptionalRepo.sh             baut Metapakete + Repo
#   ./BuildOptionalRepo.sh --dry-run   sortiert nur und zeigt die PKGBUILDs an

set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="${SCRIPT_DIR}/OptionalGroups.conf"
REPO_NAME="TrafkTuxOptional"
REPO_DIR="${SCRIPT_DIR}/airootfs/opt/${REPO_NAME}"
LIST_TARGET="/usr/share/TrafkTux/Optional"
PKGVER="${PKGVER:-$(date +%Y.%m.%d)}"
AUR_RPC="https://aur.archlinux.org/rpc/"

die() { echo "FEHLER: $*" >&2; exit 1; }

if [[ $EUID -eq 0 ]]; then
    die "Nicht als root ausfuehren (makepkg verweigert das)."
fi

NEEDED=(pacman curl jq)
((DRY_RUN)) || NEEDED+=(makepkg repo-add)
for cmd in "${NEEDED[@]}"; do
    command -v "${cmd}" >/dev/null 2>&1 || die "'${cmd}' nicht gefunden."
done
[[ -f "${CONF}" ]] || die "${CONF} nicht gefunden."

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT

# ---------------------------------------------------------------------------
# OptionalGroups.conf einlesen
# ---------------------------------------------------------------------------
declare -A CFG=()
GROUP_NAMES=()
current=""
while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "${line}" ]] && continue

    if [[ "${line}" =~ ^\[([A-Za-z0-9._+-]+)\]$ ]]; then
        current="${BASH_REMATCH[1]}"
        GROUP_NAMES+=("${current}")
    elif [[ "${line}" =~ ^([A-Za-z]+)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
        [[ -n "${current}" ]] || die "Eintrag vor der ersten [Gruppe]: ${line}"
        CFG["${current}|${BASH_REMATCH[1]}"]="${BASH_REMATCH[2]}"
    else
        die "Zeile nicht lesbar: ${line}"
    fi
done < "${CONF}"

((${#GROUP_NAMES[@]})) || die "Keine Gruppen in ${CONF} gefunden."

cfg() { printf '%s' "${CFG["$1|$2"]:-}"; }

# ---------------------------------------------------------------------------
# Pakete sortieren: Arch-Repos -> REPO_PKGS, AUR -> AUR_PKGS
# ---------------------------------------------------------------------------
classify() {
    REPO_PKGS=()
    AUR_PKGS=()
    local p missing=() args=() found=""

    for p in "$@"; do
        if pacman -Si "${p}" >/dev/null 2>&1; then
            REPO_PKGS+=("${p}")
        else
            missing+=("${p}")
        fi
    done

    ((${#missing[@]})) || return 0

    for p in "${missing[@]}"; do
        args+=(--data-urlencode "arg[]=${p}")
    done
    found="$(curl -fsSG "${AUR_RPC}" \
        --data-urlencode "v=5" --data-urlencode "type=info" "${args[@]}" \
        | jq -r '.results[].Name')" || die "AUR-Abfrage fehlgeschlagen (Internet?)."

    for p in "${missing[@]}"; do
        if grep -qxF -- "${p}" <<<"${found}"; then
            AUR_PKGS+=("${p}")
        else
            die "'${p}' (Gruppe ${CURRENT_GROUP}) ist weder in den Arch-Repos (pacman -Sy vergessen?) noch im AUR."
        fi
    done
}

# Entfernt Zeichen, die ein PKGBUILD-String nicht vertraegt
sanitize() {
    local s="$1"
    s="${s//\"/}"
    s="${s//\'/}"
    s="${s//\$/}"
    s="${s//\`/}"
    s="${s//\\/}"
    printf '%s' "${s}"
}

quoted() { local x; for x in "$@"; do printf "'%s' " "${x}"; done; }

# ---------------------------------------------------------------------------
# Ein Metapaket erzeugen
# ---------------------------------------------------------------------------
SUMMARY=()

make_group() {
    local g="$1"
    CURRENT_GROUP="${g}"
    local pkgname
    pkgname="$(cfg "${g}" Name)"
    pkgname="${pkgname:-${REPO_NAME}-${g}}"
    [[ "${pkgname}" =~ ^[A-Za-z0-9@._+-]+$ ]] || die "Ungueltiger Paketname '${pkgname}' (Gruppe ${g})."
    local dir="${WORK_DIR}/${pkgname}"
    local desc packages=() flatpaks=() services=() modules=() groups=() urls=() updates=()
    local extras=() list_lines=() p f s m gr u

    desc="$(sanitize "$(cfg "${g}" Description)")"
    desc="${desc:-${g}}"
    read -r -a packages <<<"$(cfg "${g}" Packages)"
    read -r -a flatpaks <<<"$(cfg "${g}" Flatpaks)"
    read -r -a services <<<"$(cfg "${g}" Services)"
    read -r -a modules  <<<"$(cfg "${g}" ModulesLoad)"
    read -r -a groups   <<<"$(cfg "${g}" Groups)"
    read -r -a urls     <<<"$(cfg "${g}" PkgUrls)"
    read -r -a updates  <<<"$(cfg "${g}" Update)"

    for u in "${updates[@]}"; do
        [[ "${u}" =~ ^(fast|fastfull|full)$ ]] || die "Update=${u} (Gruppe ${g}) ungueltig, erlaubt: fast, fastfull, full."
    done

    echo "==> ${pkgname}"
    classify "${packages[@]}"

    for p in "${AUR_PKGS[@]}"; do
        extras+=("${p}")
        list_lines+=("aur ${p}")
    done
    for f in "${flatpaks[@]}"; do
        extras+=("${f} (Flatpak)")
        list_lines+=("flatpak ${f}")
    done
    for u in "${urls[@]}"; do
        extras+=("${u##*/}")
        list_lines+=("pkgurl ${u}")
    done
    for gr in "${groups[@]}"; do
        extras+=("Gruppe ${gr}")
        list_lines+=("group ${gr}")
    done
    for u in "${updates[@]}"; do
        extras+=("Systemupdate ${u}")
        list_lines+=("update ${u}")
    done

    # AUR/Flatpak/Gruppen sind keine echten Abhaengigkeiten. Als "optdepends"
    # wuerde Pamac sie als auswaehlbare Pakete anbieten (und beim Auswaehlen mit
    # "Ziel nicht gefunden" abbrechen). Deshalb stehen sie nur in der Beschreibung.
    if ((${#extras[@]})); then
        local joined
        printf -v joined '%s, ' "${extras[@]}"
        desc="$(sanitize "${desc} | Wird danach automatisch ergaenzt: ${joined%, }")"
    fi

    local depends=("${REPO_PKGS[@]}")
    ((${#flatpaks[@]})) && depends+=(flatpak)

    mkdir -p "${dir}"
    local sources=()

    if ((${#list_lines[@]})); then
        {
            echo "# TrafkTuxOptional-${g}: wird von OptionalSync.sh gelesen"
            printf '%s\n' "${list_lines[@]}"
        } > "${dir}/Optional.list"
        sources+=("Optional.list")
    fi

    if ((${#modules[@]})); then
        printf '%s\n' "${modules[@]}" > "${dir}/ModulesLoad.conf"
        sources+=("ModulesLoad.conf")
    fi

    local install_line=""
    if ((${#services[@]})) || ((${#modules[@]})); then
        {
            echo "post_install() {"
            for m in "${modules[@]}"; do echo "    modprobe ${m} 2>/dev/null || true"; done
            for s in "${services[@]}"; do echo "    systemctl enable --now ${s} || true"; done
            echo "}"
            echo "post_upgrade() { post_install; }"
        } > "${dir}/${pkgname}.install"
        install_line="install=${pkgname}.install"
    fi

    {
        echo "# Automatisch erzeugt von BuildOptionalRepo.sh - nicht von Hand bearbeiten"
        echo "pkgname=${pkgname}"
        echo "pkgver=${PKGVER}"
        echo "pkgrel=1"
        echo "pkgdesc=\"${desc}\""
        echo "arch=('any')"
        echo "url='https://trafkhop-entertainment.github.io/TrafkSite'"
        echo "license=('custom')"
        echo "depends=($(quoted "${depends[@]}"))"
        [[ -n "${install_line}" ]] && echo "${install_line}"
        echo "source=($(quoted "${sources[@]}"))"
        echo "sha256sums=($(for _ in "${sources[@]}"; do printf "'SKIP' "; done))"
        echo ""
        echo "package() {"
        if ((${#list_lines[@]})); then
            echo "    install -Dm644 \"\${srcdir}/Optional.list\" \"\${pkgdir}${LIST_TARGET}/${g}.list\""
        fi
        if ((${#modules[@]})); then
            echo "    install -Dm644 \"\${srcdir}/ModulesLoad.conf\" \"\${pkgdir}/usr/lib/modules-load.d/${pkgname}.conf\""
        fi
        echo "    true"
        echo "}"
    } > "${dir}/PKGBUILD"

    SUMMARY+=("$(printf '%-34s repo: %-2d  AUR: %-2d  Flatpak: %-2d  Sonstiges: %d' \
        "${pkgname}" "${#REPO_PKGS[@]}" "${#AUR_PKGS[@]}" "${#flatpaks[@]}" \
        "$((${#urls[@]} + ${#groups[@]} + ${#updates[@]}))")")

    if ((DRY_RUN)); then
        cat "${dir}/PKGBUILD"
        [[ -f "${dir}/Optional.list" ]] && { echo "--- Optional.list"; cat "${dir}/Optional.list"; }
        [[ -f "${dir}/${pkgname}.install" ]] && { echo "--- ${pkgname}.install"; cat "${dir}/${pkgname}.install"; }
        echo
    else
        (
            cd "${dir}"
            PKGDEST="${REPO_DIR}" PKGEXT=".pkg.tar.zst" makepkg -fdC --noconfirm
        )
    fi
}

# ---------------------------------------------------------------------------
# Hauptablauf
# ---------------------------------------------------------------------------
if ((!DRY_RUN)); then
    mkdir -p "${REPO_DIR}"
    rm -f "${REPO_DIR}"/*
fi

CURRENT_GROUP=""
for g in "${GROUP_NAMES[@]}"; do
    make_group "${g}"
done

if ((!DRY_RUN)); then
    echo "==> Erzeuge Repo-Datenbank..."
    repo-add -q "${REPO_DIR}/${REPO_NAME}.db.tar.gz" "${REPO_DIR}"/*.pkg.tar.zst
    rm -f "${REPO_DIR}"/*.old
fi

echo ""
echo "Zusammenfassung:"
printf '  %s\n' "${SUMMARY[@]}"
echo ""
if ((DRY_RUN)); then
    echo "Dry-run: nichts gebaut."
else
    echo "Fertig. Repo liegt in: ${REPO_DIR}"
fi
