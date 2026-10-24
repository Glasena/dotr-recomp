#!/usr/bin/env bash
# Prints a pad script (PS2X_INPUT_SCRIPT) that loads the save in ../dotr/mc0 with CONTINUE and walks the world
# map cursor across the areas, opening and closing the map's SYSTEM panel (Start) between rounds (#64).
# Never selects Save: the SYSTEM panel is only opened with Start and closed with Start, never confirmed.
# Map at ~2800. One round = 17 cursor moves + menu, 1150 VBlanks; WALK_END (default 6000) sets the length.
# Back up ../dotr/mc0/BASLUS-20515 before running and cmp it afterwards.
# Usage: PS2X_INPUT_SCRIPT="$(tools/map_walk_script.sh)" PS2X_GS_BACKEND=pgs PS2X_DUMP_FRAMES=3500 \
#   PS2X_EXIT_AT=6000 tools/test_run.sh
sc="start@1000,start@1400,down@1500,cross@1560,cross@1800"
v=2850
while [ "$v" -lt "${WALK_END:-6000}" ]; do
  for b in left left left down down down right right right right right up up up up left left; do
    sc="$sc,$b@$v"; v=$((v + 50))
  done
  sc="$sc,start@$v,start@$((v + 150))"; v=$((v + 300))
done
echo "$sc"
