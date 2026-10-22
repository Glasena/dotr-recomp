#!/usr/bin/env bash
# Fast automated run: hidden window, uncapped VBlanks, scripted pad, PNG dumps, exit at a VBlank.
# Default script: boot -> skip intro movie (Start) -> title -> menu (Start) -> New Game (Cross) -> "NOW LOADING".
# Override any PS2X_* variable from the environment, e.g.
#   PS2X_INPUT_SCRIPT=start@1000,start@1400,down@1500 PS2X_DUMP_FRAMES=1600 PS2X_EXIT_AT=1600 tools/test_run.sh
# PS2X_SKIP_RENDER=1 skips VU1 and GS rasterization except for PS2X_SKIP_RENDER_WARMUP vblanks
# (default 3) before each dumped frame. Leave it unset for timing runs.
# Dumps: $PS2X_DUMP_DIR/frame_<vblank>.png (default ../dotr/test). Log: ../dotr/test_run.log.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
export PS2X_HEADLESS="${PS2X_HEADLESS:-1}"
export PS2X_UNCAPPED="${PS2X_UNCAPPED:-1}"
export PS2X_INPUT_SCRIPT="${PS2X_INPUT_SCRIPT:-start@1000,start@1400,cross@1500}"
export PS2X_DUMP_FRAMES="${PS2X_DUMP_FRAMES:-1200,1500,1700}"
export PS2X_EXIT_AT="${PS2X_EXIT_AT:-1750}"
export PS2X_DUMP_DIR="${PS2X_DUMP_DIR:-$here/../dotr/test}"
mkdir -p "$PS2X_DUMP_DIR"
log="$here/../dotr/test_run.log"
start=$SECONDS
stdbuf -o0 timeout "${TEST_TIMEOUT:-300}" "$here/../PS2Recomp/out/build-runtime/ps2xRuntime/ps2EntryRunner" \
  "$here/../dotr/SLUS_205.15" > "$log" 2>&1 || { echo "runner failed or timed out ($?), see $log"; exit 1; }
grep -a '^\[test\]' "$log"
echo "done in $((SECONDS - start)) s; log: $log"
