#!/usr/bin/env bash
# Perceptual diff of two frame dumps (ImageMagick only; #50, gates frozen in #51). Prints one row:
#   <b> PSNR=<dB> AE=<pixels off by more than the fuzz, % of all> PHASH=<distance> <PASS|FAIL>
# and writes a montage "a | b | diff" to $3 (default: <b without .png>_diff.png). Exits 1 on FAIL.
# Gates (1x, frozen in #51). PHASH is ignored when PSNR >= 40 dB: it blows up on near-black frames (765 for a
# 0.1-dB-off fade) while such frames are equal anyway.
#   same  (default; two runs of one backend): PSNR >= 35 dB, AE(fuzz 5%) <= 1 %, PHASH <= 30.
#   cross (IMGDIFF_MODE=cross; pgs vs the CPU GS until #53): PSNR and AE on 4x4 box-averaged copies, which cancel
#         the DIMX dither and the two-circuit line blend that only pgs does; PSNR >= 20 dB, AE(fuzz 10%) <= 20 %,
#         PHASH (full size) <= 30. Seen pgs vs CPU over title/menu/map/story/duel: 24.6-45.5 dB, 0-12.7 %, <= 12.
# Calibration (both modes): colour drift of the blue field (test_long_ref vs test_long_skip 2300) passes with
#   50.5 dB / 0 % / 14 (same); a missing 3D layer (same pair, 5000) fails with 7.1 dB / 35 % / 315.
#   tools/imgdiff.sh ../dotr/test/frame_1200.png ../dotr/test_pgs/frame_1200.png
set -euo pipefail
a="$1" b="$2" out="${3:-${2%.png}_diff.png}"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
metric() { compare "$@" null: 2>&1 >/dev/null | awk '{print $1}' || true; }
if [ "${IMGDIFF_MODE:-same}" = cross ]; then
  convert "$a" -scale 25% "$tmp/a.png"
  convert "$b" -scale 25% "$tmp/b.png"
  sa="$tmp/a.png" sb="$tmp/b.png" fuzz=10% min_psnr=20 max_ae=20
else
  sa="$a" sb="$b" fuzz=5% min_psnr=35 max_ae=1
fi
psnr=$(metric -metric PSNR "$sa" "$sb")
ae=$(metric -fuzz "$fuzz" -metric AE "$sa" "$sb")
phash=$(metric -metric PHASH "$a" "$b")
px=$(identify -format '%[fx:w*h]' "$sa")
pct=$(awk -v n="$ae" -v t="$px" 'BEGIN { printf "%.3f", 100 * n / t }')
verdict=$(awk -v p="$psnr" -v e="$pct" -v h="$phash" -v mp="$min_psnr" -v me="$max_ae" \
  'BEGIN { flat = (p == "inf" || p + 0 >= 40); print ((flat || p + 0 >= mp) && e + 0 <= me && (flat || h + 0 <= 30)) ? "PASS" : "FAIL" }')
compare "$a" "$b" -compose src "$tmp/d.png" 2>/dev/null || true
montage "$a" "$b" "$tmp/d.png" -tile 3x1 -geometry +2+2 "$out"
echo "$(basename "$b") PSNR=$psnr AE=$ae (${pct}%, fuzz $fuzz) PHASH=$phash $verdict"
[ "$verdict" = PASS ]
