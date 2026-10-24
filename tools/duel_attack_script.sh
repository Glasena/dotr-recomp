#!/usr/bin/env bash
# Prints a pad script (PS2X_INPUT_SCRIPT) from boot to the tutorial duel's first battles (#59).
# Duel at ~10000, Celtic Guardian summoned ~12400; it attacks Baby Dragon at ~15060-15500 (battle scene,
# pink floor glow). Later tutorial battles: ~16700-16900, ~17500-17800, ~18300-18600, ~19500-19700 (DUEL_END=20000).
# Usage: PS2X_INPUT_SCRIPT="$(tools/duel_attack_script.sh)" PS2X_DUMP_FRAMES=15080,15400 PS2X_EXIT_AT=15401 \
#   tools/test_run.sh   (pgs: ~4 min to 15400)
sc="start@1000,start@1400,cross@1500"
for v in $(seq 2200 60 5600); do sc="$sc,cross@$v"; done
sc="$sc,start@5750"
for v in $(seq 5810 60 9100); do sc="$sc,cross@$v"; done
sc="$sc,start@9300"
for v in $(seq 9380 80 "${DUEL_END:-16000}"); do sc="$sc,cross@$v"; done
echo "$sc"
