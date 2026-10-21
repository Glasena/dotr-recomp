<div align="center">

# dotr-recomp

**Yu-Gi-Oh! The Duelists of the Roses — PS2 static recompilation for PC/Linux**

![status](https://img.shields.io/badge/status-exploring-orange)
![platform](https://img.shields.io/badge/platform-Linux-blue)
![license](https://img.shields.io/badge/license-GPL--3.0-green)
![assets](https://img.shields.io/badge/game%20assets-not%20included-red)

</div>

---

> [!IMPORTANT]
> This repository contains **no game code, no game data and no copyrighted assets**: no ISO, ELF, IRX, textures,
> audio or C++ generated from them. It contains only original tooling, configuration and patches.
> **To use it you must own a legitimate copy of the game and dump it yourself.** Nothing here helps obtain the game
> by any other means, and requests for game files will be ignored.

## About

A static recompilation of **Yu-Gi-Oh! The Duelists of the Roses** (PS2, NTSC-U `SLUS-20515`) built on
[PS2Recomp](https://github.com/ran-j/PS2Recomp). The MIPS R5900 code of *your* copy of the game is translated into
C++ on *your* machine and linked against a runtime that emulates the PS2 hardware.

**Status:** exploring. The recompiler produces code for all 3005 discovered functions; it does not run yet.

## Layout

```text
workspace/
  PS2Recomp/      clone of https://github.com/ran-j/PS2Recomp + patches/ applied
  dotr/           SLUS_205.15 and SYSTEM.CNF extracted from your disc (outside git)
  dotr-recomp/    this repository
    patches/      fixes to PS2Recomp, applied in order
    config/       dotr.toml (recompiler config), funcmap.csv (function map)
    src/          game-specific code (dotr_overlays.cpp: picks the recompiled overlay module at 0x1E00000)
    tools/        iso9660.py (extracts files from the ISO root, stdlib only)
                  find_functions.py (builds config/funcmap.csv from the ELF)
                  overlays.py (recompiles the overlay modules in DATA/*MODULE.MRG one by one)
                  sync_runner.sh (copies generated code into the PS2Recomp runner)
                  test_run.sh (headless scripted run with PNG frame dumps)
```

## Building

```bash
# 1. extract the ELF from your own disc image
mkdir -p ../dotr
python3 tools/iso9660.py "/path/to/your.iso" ../dotr SYSTEM.CNF SLUS_205.15

# 2. PS2Recomp with the patches
git clone https://github.com/ran-j/PS2Recomp.git ../PS2Recomp
git -C ../PS2Recomp apply "$PWD"/patches/*.patch
cmake -S ../PS2Recomp -B ../PS2Recomp/out/build-tools -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DPS2X_BUILD_RUNTIME=OFF -DPS2X_BUILD_STUDIO=OFF -DPS2X_BUILD_TEST=OFF
cmake --build ../PS2Recomp/out/build-tools

# 3. (optional) regenerate the function map; the third argument seeds it with starts from a previous output, the
#    fourth (extracted disc) adds main functions that only overlay modules call
python3 -I tools/find_functions.py ../dotr/SLUS_205.15 config/funcmap.csv [../dotr/output [../dotr]]

# 4. generate the C++ (run from this folder: toml paths are relative to it)
../PS2Recomp/out/build-tools/ps2xRecomp/ps2_recomp config/dotr.toml

# 4b. recompile the overlay modules (762 modules, ~20 s; writes ../dotr/overlays/cpp/ov_*.cpp)
python3 -I tools/iso9660.py "/path/to/your.iso" ../dotr --all   # the whole disc, DATA/*.MRG included
python3 -I tools/overlays.py ../dotr ../dotr/overlays ../PS2Recomp/out/build-tools/ps2xRecomp/ps2_recomp

# 5. (optional, for the intro/story movies) build a minimal FFmpeg into ../deps/ffmpeg; no root needed
mkdir -p ../deps/src && curl -L https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz | tar xJ -C ../deps/src
(cd ../deps/src/ffmpeg-7.1 && ./configure --prefix="$(realpath ../../ffmpeg)" --enable-shared --disable-static \
  --disable-programs --disable-doc --disable-x86asm --disable-everything --disable-network --disable-autodetect \
  --disable-avdevice --disable-avfilter --enable-decoder=mpeg1video,mpeg2video --enable-parser=mpegvideo \
  --enable-demuxer=mpegps,mpegvideo --enable-protocol=file && make -j"$(nproc)" install)

# 6. copy the generated code into the runtime and build it
tools/sync_runner.sh
cmake -S ../PS2Recomp -B ../PS2Recomp/out/build-runtime -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DPS2X_BUILD_RECOMP=OFF -DPS2X_BUILD_ANALYZER=OFF -DPS2X_BUILD_TEST=OFF -DPS2X_BUILD_STUDIO=OFF \
  -DPS2X_ENABLE_DEBUG_UI=OFF -DPS2X_ENABLE_AGRESSIVE_LOGS=OFF -DPS2X_ENABLE_FFMPEG=ON \
  -DCMAKE_PREFIX_PATH="$(realpath ../deps/ffmpeg)"
cmake --build ../PS2Recomp/out/build-runtime --target ps2EntryRunner
```

`PS2X_ENABLE_AGRESSIVE_LOGS` defaults to ON upstream: it makes every recompiled function write and flush a line to
`ps2_log.txt` (gigabytes in minutes) and slows the whole game, so keep it OFF unless you need that trace. The runtime
prints `[perf] vblank/s=… swap/s=…` to stderr every 5 s (60 VBlanks/s is full speed; DotR swaps at 30/s).

The runtime finds FFmpeg through pkg-config, which searches `CMAKE_PREFIX_PATH`; the binary gets an RPATH to
`../deps/ffmpeg/lib`, so no `LD_LIBRARY_PATH` is needed. Without FFmpeg, pass `-DPS2X_ENABLE_FFMPEG=OFF` instead:
movies are then skipped with blank frames (patch 0006). In-game, Start (keyboard Enter) skips the intro movie.

On Ubuntu the runtime needs `sudo apt install libxinerama-dev libasound2-dev`.

## Legal

- **No affiliation.** This is an unofficial, non-commercial fan project for preservation, interoperability and
  research. It is not affiliated with, endorsed, sponsored or approved by Konami, Sony Interactive Entertainment or
  any other rights holder.
- **Trademarks.** Yu-Gi-Oh!, The Duelists of the Roses and Konami are trademarks of Konami Holdings Corporation
  and/or Kazuki Takahashi / Studio Dice / Shueisha. PlayStation and PS2 are trademarks of Sony Interactive
  Entertainment. They are used here only to identify the game this tooling is compatible with.
- **No copyrighted material.** The repository ships no part of the game. Files in `config/` hold only addresses and
  settings derived by analysis, needed for interoperability with a copy the user already owns. Generated code,
  dumps and assets must never be committed or redistributed; `.gitignore` blocks them.
- **Your responsibility.** You are responsible for complying with the laws of your country, including those on
  copying and dumping software you own. Do not use this project to pirate the game.
- **No warranty.** The software is provided "as is", without warranty of any kind, as stated in the GPL-3.0. The
  authors are not liable for any damage or claim arising from its use.
- **Takedown.** If you are a rights holder and believe something here infringes your rights, please open an issue
  and it will be reviewed and removed promptly if appropriate.

## Credits and license

- [**PS2Recomp**](https://github.com/ran-j/PS2Recomp) by ran-j and contributors — recompiler and runtime (GPL-3.0).
- [**Tobiichi-Port**](https://github.com/YYOzcan/Tobiichi-Port) (God of War PS2 recomp) — `tools/find_functions.py`
  is adapted from its function finder, and its docs guided the approach (GPL-3.0).
- *Yu-Gi-Oh! The Duelists of the Roses* © Konami. This project is not affiliated with or endorsed by Konami.
  No game content is distributed.

The original code in this repository is released under the **GPL-3.0** license, consistent with PS2Recomp.
See [`LICENSE`](LICENSE). This license covers only this project's own code, not the game.
