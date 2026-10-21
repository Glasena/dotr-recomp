# dotr-recomp — Yu-Gi-Oh! The Duelists of the Roses (PS2)

Static recompilation of **Yu-Gi-Oh! The Duelists of the Roses** (PS2, NTSC-U `SLUS-20515`) for PC/Linux using
[PS2Recomp](https://github.com/ran-j/PS2Recomp). Status: **exploring**, does not run yet.

This repository does **not** contain any game files (ISO, ELF, IRX, data) or C++ generated from them.
You need **your own copy** of the game.

## Layout

```text
workspace/
  PS2Recomp/      clone of https://github.com/ran-j/PS2Recomp + patches/ applied
  dotr/           SLUS_205.15 and SYSTEM.CNF extracted from your disc (outside git)
  dotr-recomp/    this repository
    patches/      fixes to PS2Recomp, applied in order
    config/       dotr.toml (recompiler config), funcmap.csv (function map)
    src/          game-specific overrides
    tools/        iso9660.py (extracts files from the ISO root, stdlib only)
                  find_functions.py (builds config/funcmap.csv from the ELF)
```

## Steps

```bash
# 1. extract the ELF from your ISO
mkdir -p ../dotr
python3 tools/iso9660.py "/path/to/your.iso" ../dotr SYSTEM.CNF SLUS_205.15

# 2. PS2Recomp with the patches
git clone https://github.com/ran-j/PS2Recomp.git ../PS2Recomp
git -C ../PS2Recomp apply "$PWD"/patches/*.patch
cmake -S ../PS2Recomp -B ../PS2Recomp/out/build-tools -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DPS2X_BUILD_RUNTIME=OFF -DPS2X_BUILD_STUDIO=OFF -DPS2X_BUILD_TEST=OFF
cmake --build ../PS2Recomp/out/build-tools

# 3. (optional) regenerate the function map; the third argument seeds it with starts from a previous output
python3 -I tools/find_functions.py ../dotr/SLUS_205.15 config/funcmap.csv [../dotr/output]

# 4. generate the C++ (run from this folder: toml paths are relative to it)
../PS2Recomp/out/build-tools/ps2xRecomp/ps2_recomp config/dotr.toml
```

On Ubuntu the runtime (`ps2xRuntime`) needs `libxinerama-dev` and `libasound2-dev`.

## License

GPL-3.0, like PS2Recomp. Yu-Gi-Oh! is a trademark of Konami; non-commercial project, not affiliated.
