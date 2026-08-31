#!/bin/bash
#
# trafktux-generate-buckets.sh
#
# Erzeugt aus den 169-Referenz-Assets (assets/169/) weitere Aspect-Ratio-
# Buckets per zentriertem Crop/Pad. Es wird NICHTS gestreckt und NICHTS
# vom eigentlichen Artwork skaliert - die Hoehe bleibt fuer alle Buckets
# bei der 1080px-Referenz, nur die Breite (und damit wieviel transparenter
# Rand links/rechts dazukommt oder wegfaellt) aendert sich je Aspect Ratio.
# Das funktioniert nur, weil die Komposition symmetrisch um die
# Canvas-Mitte (x=960) aufgebaut ist - lasst das also bitte auch bei
# kuenftigen Layern so.
#
# Bewusst NICHT dabei: 1:1 (11). Der Logo-Layer (Layer0, 1438px breit,
# theme.txt) braucht mehr Breite als ein 1080px-Quadrat hergibt, ohne
# echtes Downscale des Contents wuerde da was abgeschnitten. Da 1:1 als
# echtes Monitor-Seitenverhaeltnis quasi nicht vorkommt, hab ich das erstmal
# ausgelassen - sag Bescheid, falls du's trotzdem willst, das ist dann ein
# eigener (kleiner) Rechenweg.
#
# Voraussetzung: ImageMagick (`magick`) installiert.
# Ausfuehren im Theme-Root (da wo `assets/`, `fonts/`, `theme.txt` liegen).

set -euo pipefail

if command -v magick >/dev/null 2>&1; then
    IM_CMD="magick"
elif command -v convert >/dev/null 2>&1; then
    IM_CMD="convert"
else
    echo "Fehler: weder 'magick' noch 'convert' gefunden. ImageMagick installieren (pacman -S imagemagick)." >&2
    exit 1
fi

SRC="assets/169"
REF_W=1920
REF_H=1080

BM_TOP=526; BM_LEFT=780; BM_WIDTH=360; BM_HEIGHT=360

# Bucket-Name -> Zielbreite (Hoehe bleibt immer 1080)
declare -A BUCKETS=(
  [43]=1440     # 4:3
  [32]=1620     # 3:2
  [1610]=1728   # 16:10
  [219]=2520    # 21:9
  [329]=3840    # 32:9 (super-ultrawide)
)

pct() { awk -v v="$1" -v ref="$2" 'BEGIN { printf "%.0f", v / ref * 100 }'; }

emit_image() {
  # Jedes Layer ist eine volle Screen-Canvas fuer sein Aspect Ratio - die
  # Blase/das Logo sitzt schon an der richtigen Stelle IM Bild. Also immer
  # 100%/100%, kein Sub-Positioning, kein Bounding-Box-Kram - genau wie
  # Layer1/Layer5 das schon die ganze Zeit richtig gemacht haben.
  local fname="$1" bucket="$2"
  cat <<EOF
+image {
    top = 0%
    left = 0%
    width = 100%
    height = 100%
    file = "assets/$bucket/$fname"
}

EOF
}

emit_bootmenu() {
  cat <<EOF
+boot_menu {
    left = $(pct "$BM_LEFT" "$REF_W")%
    top = $(pct "$BM_TOP" "$REF_H")%
    width = $(pct "$BM_WIDTH" "$REF_W")%
    height = $(pct "$BM_HEIGHT" "$REF_H")%
    item_height = $BM_HEIGHT
    item_width = $BM_WIDTH
    item_spacing = 0
    item_padding = 0
    icon_width = 0
    icon_height = 0
    item_icon_space = 0

    item_font = "Noto Sans Bold 22"
    selected_item_font = "Noto Sans Bold 22"

    item_color = "#f6f3d5"
    selected_item_color = "#fff495"

    scrollbar = false
}

EOF
}

for bucket in "${!BUCKETS[@]}"; do
  Wt=${BUCKETS[$bucket]}
  outdir="assets/$bucket"
  mkdir -p "$outdir"
  echo "== Bucket $bucket (${Wt}x1080) =="

  for fname in GrubLayer4.png GrubLayer2.png GrubLayer0.png; do
    "$IM_CMD" "$SRC/$fname" -background none -gravity center -extent "${Wt}x1080" "$outdir/$fname"
  done

  # theme_<bucket>.txt liegt bewusst im Theme-Root (neben theme.txt), NICHT
  # in assets/<bucket>/ - so zeigen alle Pfade nur nach unten, nie zur
  # Seite/hoch, kein "../" noetig.
  theme="theme_${bucket}.txt"
  {
    echo "# TrafkTux GRUB Theme - Aspect-Ratio-Variante: $bucket (automatisch erzeugt aus 169-Referenz)"
    echo "# Zentriertes Crop/Pad, kein Content-Scaling. Bucket-Assets: assets/$bucket/"
    echo
    echo "title-text: \"\""
    echo "desktop-color: \"#23163b\""
    echo "desktop-image: \"assets/GrubLayer5.png\""
    echo
    emit_image "GrubLayer4.png" "$bucket"
    emit_bootmenu
    emit_image "GrubLayer2.png" "$bucket"
    emit_image "GrubLayer0.png" "$bucket"
    # Layer1 (Vignette) ist bucket-unabhaengig, aber bewusst in % statt
    # fixer 1920x1080-Pixel geschrieben, damit es auf JEDER Aufloesung
    # den ganzen Screen abdeckt statt nur eine feste Pixelbox.
    cat <<'EOF'
+image {
    top = 0%
    left = 0%
    width = 100%
    height = 100%
    file = "assets/GrubLayer1.png"
}
EOF
  } > "$theme"

  echo "  -> $outdir/ (3 PNGs) + ./theme_${bucket}.txt"
done

echo
echo "Fertig. GrubLayer1.png und GrubLayer5.png bleiben unveraendert im Theme-Root"
echo "(assets/) liegen - die sind bucket-unabhaengig, nicht in die Bucket-Ordner kopieren."
echo
echo "Hinweis: falls dir in der bestehenden 169/theme_169.txt Layer1 noch als feste"
echo "1920x1080-Pixelbox drinsteht (statt 100%/100%), lohnt sich dieselbe Aenderung"
echo "dort auch - sonst deckt die Vignette nur auf genau 1920x1080 den ganzen Schirm ab."
