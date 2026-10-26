#!/bin/bash
#
# Baut aus den Quell-PNGs ein klassisches Xcursor-Theme.
# Arbeitet komplett isoliert auf der SSD.
#
# Benoetigt: imagemagick (magick), xorg-xcursorgen

set -e

THEME_NAME="TrafkTuxCursorLegacy"

# SSD Pfade definieren
SSD_BASE="/run/media/hopx/HopxSSD/TrafkSite/Projects/TrafkTux/TrafkTux/HOME FOLDER/.config/hypr/TrafkCursor_Build"
PNG="$SSD_BASE/TrafkTuxCursorPNGs"
WORK="$SSD_BASE/XcursorBuildtemp"
OUTPUT="$SSD_BASE/Output"
OUT="$OUTPUT/$THEME_NAME"

# Hotspot-Fraktionen (0..1 relativ zur Bildgroesse)
HX=0.25
HY=0.15

# Groessen fuer das libXcursor Theme
SIZES=(24 32 35 45 48 64)

rm -rf "$WORK"
mkdir -p "$WORK/imgs"

# Loescht nur Xcursor-Spezifisches im Zielordner auf der SSD
rm -rf "$OUT/cursors" "$OUT/index.theme"
mkdir -p "$OUT/cursors"

render_size() {
  local img=$1 size=$2 out=$3
  magick "$PNG/$img" -resize ${size}x${size} -gravity North -background none -extent ${size}x${size} "$out"
}

hotspot() {
  awk -v s="$1" -v f="$2" 'BEGIN{printf "%d", (s*f)+0.5}'
}

make_alias() {
  local canonical=$1 aliases=$2
  [ -z "$aliases" ] && return
  local IFS=';'
  for n in $aliases; do
    ln -sf "$canonical" "$OUT/cursors/$n"
  done
}

make_cursor() {
  local shape=$1 img=$2 aliases=$3
  local cfg="$WORK/${shape}.cfg"
  : > "$cfg"

  for size in "${SIZES[@]}"; do
    local pngfile="$WORK/imgs/${shape}_${size}.png"
    local rel_pngfile="imgs/${shape}_${size}.png"
    render_size "$img" "$size" "$pngfile"
    local hx hy
    hx=$(hotspot "$size" "$HX")
    hy=$(hotspot "$size" "$HY")
    # Wir schreiben den relativen Pfad in die Config
    echo "$size $hx $hy $rel_pngfile" >> "$cfg"
  done

  # Wir wechseln kurzfristig in den WORK Ordner, um den Befehl auszufuehren
  (cd "$WORK" && xcursorgen "${shape}.cfg" "$OUT/cursors/$shape")
  make_alias "$shape" "$aliases"
}

make_wait() {
  local shape="wait"
  local cfg="$WORK/${shape}.cfg"
  : > "$cfg"

  for size in "${SIZES[@]}"; do
    local hx hy
    hx=$(hotspot "$size" "$HX")
    hy=$(hotspot "$size" "$HY")
    for i in $(seq 1 44); do
      local pngfile="$WORK/imgs/wait_${size}_${i}.png"
      local rel_pngfile="imgs/wait_${size}_${i}.png"
      render_size "wait${i}.png" "$size" "$pngfile"
      # Wir schreiben den relativen Pfad in die Config
      echo "$size $hx $hy $rel_pngfile 50" >> "$cfg"
    done
  done

  # Wir wechseln kurzfristig in den WORK Ordner, um den Befehl auszufuehren
  (cd "$WORK" && xcursorgen "${shape}.cfg" "$OUT/cursors/$shape")
  make_alias "$shape" "watch;progress;half-busy;left_ptr_watch;0426c94ea35c87780ff01dc239897213;08e8e1c95fe2fc01f976f1e063a24ccd"
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

cat > "$OUT/index.theme" << EOF
[Icon Theme]
Name=$THEME_NAME
Inherits=Adwaita
EOF

rm -rf "$WORK"

echo "Xcursor-Theme fertig auf SSD generiert unter: $OUT"
