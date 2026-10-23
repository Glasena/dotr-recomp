#!/usr/bin/env bash
# Perceptual diff of two frame dumps (ImageMagick only; #50). Prints one row:
#   <b> PSNR=<dB> AE=<pixels off by more than ~5/255 (fuzz 2%), % of all> PHASH=<distance> <PASS|FAIL>
# and writes a montage "a | b | diff" to $3 (default: <b without .png>_diff.png).
# Gates (1x): PSNR >= 35 dB, AE <= 1 %, PHASH <= 30; exits 1 when one fails.
# Calibration: blue-field colour drift = 50.5 dB / 0 / 14; a missing 3D layer = 7.1 dB / 35 % / 315.
#   tools/imgdiff.sh ../dotr/test/frame_1200.png ../dotr/test_pgs/frame_1200.png
set -euo pipefail
a="$1" b="$2" out="${3:-${2%.png}_diff.png}"
metric() { compare "$@" null: 2>&1 >/dev/null | awk '{print $1}' || true; }
psnr=$(metric -metric PSNR "$a" "$b")
ae=$(metric -fuzz 2% -metric AE "$a" "$b")
phash=$(metric -metric PHASH "$a" "$b")
px=$(identify -format '%[fx:w*h]' "$a")
pct=$(awk -v n="$ae" -v t="$px" 'BEGIN { printf "%.3f", 100 * n / t }')
verdict=$(awk -v p="$psnr" -v e="$pct" -v h="$phash" \
  'BEGIN { print ((p == "inf" || p + 0 >= 35) && e + 0 <= 1 && h + 0 <= 30) ? "PASS" : "FAIL" }')
compare "$a" "$b" -compose src /tmp/imgdiff_$$.png 2>/dev/null || true
montage "$a" "$b" /tmp/imgdiff_$$.png -tile 3x1 -geometry +2+2 "$out"
rm -f /tmp/imgdiff_$$.png
echo "$(basename "$b") PSNR=$psnr AE=$ae (${pct}%) PHASH=$phash $verdict"
[ "$verdict" = PASS ]
