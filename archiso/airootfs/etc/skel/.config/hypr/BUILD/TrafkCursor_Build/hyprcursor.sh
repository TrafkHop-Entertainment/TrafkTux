#!/bin/bash
#
# Kompiliert das Hyprcursor-Theme mittels hyprcursor-util.
# Arbeitet komplett isoliert relativ zum eigenen Speicherort - liegt
# egal wo (SSD, lokale Platte, ...), solange TrafkTuxCursorPNGs/ im
# selben Verzeichnis wie dieses Script liegt.

set -e

THEME_NAME="TrafkTuxCursor"

# Alle Pfade relativ zum eigenen Speicherort - kein SSD_BASE mehr, der
# bei jedem Verschieben des Ordners von Hand angepasst werden musste.
# WICHTIG, anders als bei SoundCenter.sh: hier reicht reine Parameter-
# Expansion NICHT - dieses Script (bzw. hyprcursor-util) landet sonst
# bei "bash HyprCursor.sh" direkt aus dem eigenen Ordner heraus bei
# SCRIPT_DIR="." (relativ), und relative Pfade können nach internen
# cd's oder je nach Tool-Verhalten am falschen Ort landen. Der winzige
# Mehraufwand für den pwd-Subshell ist bei einem einmalig von Hand
# gestarteten Build-Script (Laufzeit: mehrere Sekunden) irrelevant -
# anders als beim latenzkritischen SoundCenter.sh.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PNG="$SCRIPT_DIR/TrafkTuxCursorPNGs"
WORK="$SCRIPT_DIR/HyprlandBuildtemp"
OUTPUT="$SCRIPT_DIR/Output"

# Hotspots oben links
HX=0.25
HY=0.15

# Bitmap-Groessen, fuer die wir jede Cursor-Form rendern.
# Vorher gab es nur 35 und 45 - alles dazwischen (z.B. effektive Groesse
# ~37px durch HYPRCURSOR_SIZE=35 * Monitor-Scale) musste hyprcursor
# zwischen den beiden Randgroessen interpolieren/runden. Am Cursor-
# Quellbild (pointer.png hat nur ~1px Puffer unten) wurde das als
# abgeschnittener Cursor sichtbar - am schlimmsten in der Mitte zwischen
# zwei definierten Groessen, kaum sichtbar an den Raendern (deckt sich
# mit "bei mittleren Scales schlimmer, bei kleineren/groesseren eher
# nicht"). Mehr, enger beieinanderliegende Stufen -> kleinerer maximal
# noetiger Rundungsfehler pro Stufe. 35 und 45 bleiben explizit erhalten,
# da die dort bekannt pixelgenau waren.
SIZES=(24 28 32 35 38 42 45 48 52 56 60 64)

# WICHTIGER ALS DIE GROESSEN-STAFFELUNG: pointer.png ist hochkant
# (35x45). Beim "-resize NxN" auf ein QUADRATISCHES Ziel war deshalb
# IMMER die Bildhoehe die limitierende Groesse - das Ergebnis also nach
# dem Resize schon exakt so hoch wie das Zielquadrat. "-extent" hatte
# dadurch unten quasi NIE etwas zum Auffuellen (0px Puffer, bei so gut
# wie jeder Groesse - lokal nachgemessen). Jede weitere Rundung/
# Skalierung durch den Compositor bei krummen Monitor-Scales hatte also
# gar keinen Spielraum mehr und schnitt direkt ins sichtbare Artwork.
# ARTWORK_FRAC laesst das Artwork bewusst kleiner rendern als die
# Zielflaeche, damit "-extent" auf JEDER Seite (v.a. unten) einen
# echten, garantierten Rand einbaut.
ARTWORK_FRAC=88   # Artwork füllt ~88% der Zielgröße, Rest = Sicherheitsrand

rm -rf "$WORK"
mkdir -p "$WORK/hyprcursors"

cat > "$WORK/manifest.hl" << EOF
name = $THEME_NAME
description = TrafkTux Cursor Theme for Hyprland
version = 1.0
cursors_directory = hyprcursors
EOF

make_cursor() {
  local shape=$1
  local img=$2
  local overrides=$3

  mkdir -p "$WORK/hyprcursors/$shape"

  for size in "${SIZES[@]}"; do
    local inner=$(( size * ARTWORK_FRAC / 100 ))
    [ "$inner" -lt 1 ] && inner=1
    magick "$PNG/$img" -resize ${inner}x${inner} -gravity North -background none -extent ${size}x${size} "$WORK/hyprcursors/$shape/image${size}.png"
  done

  {
    echo "resize_algorithm = bilinear"
    echo "hotspot_x = $HX"
    echo "hotspot_y = $HY"
    for size in "${SIZES[@]}"; do
      echo "define_size = $size, image${size}.png"
    done
    [ -n "$overrides" ] && echo "define_override = $overrides"
  } > "$WORK/hyprcursors/$shape/meta.hl"
}

make_wait() {
  mkdir -p "$WORK/hyprcursors/wait"

  for size in "${SIZES[@]}"; do
    local inner=$(( size * ARTWORK_FRAC / 100 ))
    [ "$inner" -lt 1 ] && inner=1
    for i in $(seq 1 44); do
      magick "$PNG/wait${i}.png" -resize ${inner}x${inner} -gravity North -background none -extent ${size}x${size} "$WORK/hyprcursors/wait/image${size}_${i}.png"
    done
  done

  {
    echo "resize_algorithm = bilinear"
    echo "hotspot_x = $HX"
    echo "hotspot_y = $HY"
    for size in "${SIZES[@]}"; do
      for i in $(seq 1 44); do
        echo "define_size = $size, image${size}_${i}.png, 50"
      done
    done
    echo "define_override = watch;progress;half-busy;left_ptr_watch;0426c94ea35c87780ff01dc239897213;08e8e1c95fe2fc01f976f1e063a24ccd"
  } > "$WORK/hyprcursors/wait/meta.hl"
}

make_cursor "default"       "pointer.png"       "left_ptr;arrow;top_left_arrow;help;context-menu;cell;crosshair;alias;copy;zoom-in;zoom-out;dnd-copy;dnd-link;question_arrow;center_ptr;right_ptr;plus;cross;tcross;target;dotbox"
make_cursor "openhand"      "openhand.png"      "left_ptr_fallback"
make_cursor "link"          "link.png"          "pointer;hand2;pointing_hand;e29285e634086352946a0e7090d73106"
make_cursor "grab-straight" "grab-straight.png" "grab;hand1;grabbing;closedhand;fleur;move;dnd-move;all-scroll;ew-resize;ns-resize;size_hor;size_ver;sb_h_double_arrow;sb_v_double_arrow;col-resize;row-resize;split_h;split_v;n-resize;e-resize;s-resize;w-resize;sb_up_arrow;sb_down_arrow;sb_left_arrow;sb_right_arrow;top_side;bottom_side;left_side;right_side;top_tee;bottom_tee;left_tee;right_tee"
make_cursor "grab-diagonal" "grab-diagonal.png" "nwse-resize;nesw-resize;size_fdiag;size_bdiag;fd_double_arrow;bd_double_arrow;ne-resize;nw-resize;se-resize;sw-resize;top_left_corner;top_right_corner;bottom_left_corner;bottom_right_corner;ll_angle;lr_angle;ul_angle;ur_angle"
make_cursor "text"          "text.png"          "xterm;ibeam;vertical-text"
make_cursor "not-allowed"   "not-allowed.png"   "crossed_circle;forbidden;03b6e0fcb3499374a867c041f52298f0;circle;no-drop;dnd-no-drop;dnd-none"
make_cursor "X"             "X.png"             "X_cursor"
make_wait

# Loescht nur den Hyprcursor-Ordner im Output vor dem Neubau
rm -rf "$OUTPUT/$THEME_NAME/hyprcursors" "$OUTPUT/$THEME_NAME/manifest.hl"

mkdir -p "$OUTPUT"
hyprcursor-util --create "$WORK" --output "$OUTPUT"

rm -rf "$WORK"

echo "Hyprcursor-Theme fertig kompiliert unter: $OUTPUT/$THEME_NAME"
