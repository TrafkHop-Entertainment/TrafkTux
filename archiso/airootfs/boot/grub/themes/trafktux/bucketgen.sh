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
# Bewusst NICHT dabei: 1:1 (11). Der Logo-Layer (GrubLayer1.png, 1438px
# breit, theme.txt) braucht mehr Breite als ein 1080px-Quadrat hergibt,
# ohne echtes Downscale des Contents wuerde da was abgeschnitten. Da 1:1
# als echtes Monitor-Seitenverhaeltnis quasi nicht vorkommt, hab ich das
# erstmal ausgelassen - sag Bescheid, falls du's trotzdem willst, das ist
# dann ein eigener (kleiner) Rechenweg.
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

BM_TOP=540; BM_LEFT=780; BM_WIDTH=360; BM_HEIGHT=360
BM_FONT="Noto Sans Bold 28"

# Bucket-Name -> Zielbreite (Hoehe bleibt immer 1080). 169 mit dabei
# (Wt=REF_W), damit theme_169.txt vom selben Code-Pfad erzeugt wird wie
# alle anderen - keine getrennt gepflegte Datei mehr, die aus dem Tritt
# geraten kann.
declare -A BUCKETS=(
  [169]=1920    # 16:9 (Referenz)
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
  # item_width proportional zur jeweiligen Bucket-Breite berechnen (nicht
  # der feste BM_WIDTH-Pixelwert direkt) - der passte nur beim 169-Bucket
  # zufaellig zur Container-Breite, bei anderen Bucket-Breiten driftet er
  # sonst auseinander. item_height bleibt fix, weil die Referenzhoehe
  # (1080) bei jedem Bucket gleich bleibt.
  local Wt="$1"
  local item_width_px
  item_width_px=$(awk -v w="$BM_WIDTH" -v refw="$REF_W" -v wt="$Wt" 'BEGIN { printf "%.0f", w * wt / refw }')
  cat <<EOF
+boot_menu {
    left = $(pct "$BM_LEFT" "$REF_W")%
    top = $(pct "$BM_TOP" "$REF_H")%
    width = $(pct "$BM_WIDTH" "$REF_W")%
    height = $(pct "$BM_HEIGHT" "$REF_H")%
    item_height = $BM_HEIGHT
    item_width = $item_width_px
    item_spacing = 0
    item_padding = 0
    icon_width = 0
    icon_height = 0
    item_icon_space = 0

    item_font = "$BM_FONT"
    selected_item_font = "$BM_FONT"

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

  if [ "$bucket" = "169" ]; then
    echo "  (169 = Referenz selbst, PNGs bleiben unveraendert)"
  else
    for fname in GrubLayer4.png GrubLayer3.png GrubLayer1.png; do
      "$IM_CMD" "$SRC/$fname" -background none -gravity center -extent "${Wt}x1080" "$outdir/$fname"
    done
  fi

  # theme_<bucket>.txt liegt jetzt IM Bucket-Ordner (reine Ablage-Frage) -
  # der Inhalt bleibt trotzdem Root-relativ ("assets/<bucket>/..."), weil
  # GRUB diese Datei nie direkt von hier laedt, sondern der Sync-Service
  # sie 1:1 nach theme.txt im Theme-Root kopiert - und von DORT muessen
  # die Pfade stimmen.
  theme="$outdir/theme_${bucket}.txt"
  {
    echo "# TrafkTux GRUB Theme - Aspect-Ratio-Variante: $bucket (automatisch erzeugt aus 169-Referenz)"
    echo "# Zentriertes Crop/Pad, kein Content-Scaling. Bucket-Assets: assets/$bucket/"
    echo
    echo "title-text: \"\""
    echo "desktop-color: \"#23163b\""
    echo "desktop-image: \"assets/GrubLayer5.png\""
    echo
    # Reihenfolge: erstes Element = am weitesten VORNE (bestaetigt durch
    # eigenen v17-Fix-Kommentar: "Logo lag hinter der Vignette -> Reihenfolge
    # Logo/Vignette getauscht", danach Logo vor Vignette deklariert = Logo
    # vor der Vignette). Logo also vor Vignette, Glas-Highlight vor Text vor
    # Blase. (Neue Benennung: Layer1=Logo, Layer2=Vignette[geteilt],
    # Layer3=Glas-Highlight, Layer4=Blase, Layer5=Hintergrund[geteilt])
    emit_image "GrubLayer1.png" "$bucket"
    cat <<'LAYER2EOF'
+image {
    top = 0%
    left = 0%
    width = 100%
    height = 100%
    file = "assets/GrubLayer2.png"
}

LAYER2EOF
    emit_image "GrubLayer3.png" "$bucket"
    emit_bootmenu "$Wt"
    emit_image "GrubLayer4.png" "$bucket"
  } > "$theme"

  echo "  -> $outdir/ (3 PNGs + theme_${bucket}.txt)"
done

echo
echo "Fertig. GrubLayer2.png (Vignette) und GrubLayer5.png (Hintergrund) bleiben"
echo "unveraendert im Theme-Root (assets/) liegen - geteilt ueber alle Buckets,"
echo "nicht in die Bucket-Ordner kopieren."

if [ ! -f theme.txt ]; then
  cp assets/169/theme_169.txt theme.txt
  echo
  echo "theme.txt gab's noch nicht, hab sie mit assets/169/theme_169.txt vorbelegt (Erststart-Default)."
else
  echo
  echo "theme.txt existiert schon - lass ich in Ruhe, das ist Sache des Sync-Service."
  echo "(Falls du hier bewusst zuruecksetzen willst: assets/169/theme_169.txt nach theme.txt"
  echo "kopieren und trafktux-grub-theme-sync.service neu starten.)"
fi
