#!/bin/bash
#
# Kompiliert das Hyprcursor-Theme mittels hyprcursor-util.
# Arbeitet komplett isoliert auf der SSD.

set -e

THEME_NAME="TrafkTuxCursor"

# SSD Pfade definieren
SSD_BASE="/run/media/hopx/HopxSSD/TrafkSite/Projects/TrafkTux/TrafkTux/HOME FOLDER/.config/hypr/TrafkCursor_Build"
PNG="$SSD_BASE/TrafkTuxCursorPNGs"
WORK="$SSD_BASE/HyprlandBuildtemp"
OUTPUT="$SSD_BASE/Output"

# Hotspots oben links
HX=0.25
HY=0.15

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

  magick "$PNG/$img" -resize 35x35 -gravity North -background none -extent 35x35 "$WORK/hyprcursors/$shape/image35.png"
  magick "$PNG/$img" -resize 45x45 -gravity North -background none -extent 45x45 "$WORK/hyprcursors/$shape/image45.png"

  {
    echo "resize_algorithm = bilinear"
    echo "hotspot_x = $HX"
    echo "hotspot_y = $HY"
    echo "define_size = 35, image35.png"
    echo "define_size = 45, image45.png"
    [ -n "$overrides" ] && echo "define_override = $overrides"
  } > "$WORK/hyprcursors/$shape/meta.hl"
}

make_wait() {
  mkdir -p "$WORK/hyprcursors/wait"

  for i in $(seq 1 44); do
    magick "$PNG/wait${i}.png" -resize 35x35 -gravity North -background none -extent 35x35 "$WORK/hyprcursors/wait/image35_${i}.png"
    magick "$PNG/wait${i}.png" -resize 45x45 -gravity North -background none -extent 45x45 "$WORK/hyprcursors/wait/image45_${i}.png"
  done

  {
    echo "resize_algorithm = bilinear"
    echo "hotspot_x = $HX"
    echo "hotspot_y = $HY"
    for i in $(seq 1 44); do
      echo "define_size = 35, image35_${i}.png, 50"
    done
    for i in $(seq 1 44); do
      echo "define_size = 45, image45_${i}.png, 50"
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

# Loescht nur Hyprcursor-Ordner auf der SSD vor dem Neubau
rm -rf "$OUTPUT/$THEME_NAME/hyprcursors" "$OUTPUT/$THEME_NAME/manifest.hl"

mkdir -p "$OUTPUT"
hyprcursor-util --create "$WORK" --output "$OUTPUT"

rm -rf "$WORK"

echo "Hyprcursor-Theme fertig auf SSD kompiliert unter: $OUTPUT/$THEME_NAME"
