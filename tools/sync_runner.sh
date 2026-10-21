#!/usr/bin/env bash
# Sync generated code (../dotr/output, overlay modules from ../dotr/overlays/cpp) and game overrides (src/) into the
# PS2Recomp runner.
# Copies only files whose content changed, so builds stay incremental. Adapted from Tobiichi-Port.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/../dotr/output"
RUNNER="$ROOT/../PS2Recomp/ps2xRuntime/src/runner"
INCLUDE="$ROOT/../PS2Recomp/ps2xRuntime/include"
copy_if_changed() { cmp -s "$1" "$2" || cp "$1" "$2"; }
shopt -s nullglob
declare -A keep
for f in "$OUT"/*.cpp "$ROOT"/../dotr/overlays/cpp/*.cpp "$ROOT"/src/*.cpp; do
    keep["$(basename "$f")"]=1
    copy_if_changed "$f" "$RUNNER/$(basename "$f")"
done
for f in "$OUT"/*.h "$ROOT"/src/*.h; do copy_if_changed "$f" "$INCLUDE/$(basename "$f")"; done
for f in "$RUNNER"/*.cpp; do [ -n "${keep[$(basename "$f")]:-}" ] || rm "$f"; done
echo "runner: $(ls "$RUNNER" | wc -l) sources"
