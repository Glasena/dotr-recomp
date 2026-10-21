# Context for new sessions

Recomp of Yu-Gi-Oh! The Duelists of the Roses (PS2, USA, `SLUS_205.15`) with PS2Recomp. See README.md for layout.
Everything in the repo (code, comments, docs, commit messages) is written in English.

## Rules
- Nothing from the game in git: ISO, ELF, IRX, generated code. They live in `../dotr/`.
- Generic PS2Recomp fixes become a file in `patches/` (upstream has 132 open PRs and merges ~3/month; don't depend
  on it). DotR-specific fixes go in `src/`.
- Never re-enable the "Potential self-modifying code" patches that `ps2_analyzer` suggests (they become NOPs). In God
  of War they were ordinary `sw` into WAX `.data` and broke loading. DotR's 21 were already removed from
  `config/dotr.toml`.
- Commits must not expose the author's personal email: the repo-local `user.email` is a GitHub noreply address.

## What is known about the ELF (2026-10-20)
- Entry 0x100008. Code+data in one PT_LOAD at 0x100000 (file offset 0x6900), filesz 0x20FF00, memsz 0x251300.
  Single merged WAX section, no .text/.data split.
- Code ends at 0x286968. After it: VU microcode (0x286980…), data, and libkernel's 0x8007xxxx kernel patch blobs
  at 0x28C258 (string "PsIIlibkernel 2430"); not EE game code.
- No symbols (`.symtab` empty although `file` says "not stripped").
- 834 extra LOAD segments, all at 0x01E00000, filesz 0, memsz 0x100–0x7000, unnamed sections.
  **Nature not verified**: may be code overlays loaded from disc, VU microcode or a linker artifact.
- IOP: PADMAN, MCMAN/MCSERV, LIBSD, SDRDRV, SIO2MAN, KCEJEAST (Konami module), IOPRP.IMG.
- `ps2_analyzer` (fallback without Ghidra): 263 lib functions to stub, 293 with no runtime handler, 6 jump tables.

## Function map (step 1, done 2026-10-20)
`tools/find_functions.py` (adapted from Tobiichi-Port `tools/waffle/find_functions.py`; KIexster's repo only ships
the CSV) → `config/funcmap.csv` (`Name,Start,End,Size`, header line is skipped by the loader). 3005 functions:
JAL targets + boundary-checked J targets, data pointers and lui/addiu|ori addresses, minus jump tables.
`ps2_recomp` run: 3005 functions, 2816 recompiled, 189 stubs, 0 errors, 108 warnings (all "unresolved JR/JALR …
promoted N fallback entries", i.e. jump tables/indirect jumps handled by fallback).
- 74 of the 263 toml stubs are not map starts (uncalled SDK functions, folded into the previous function).
- Log says "No BSS found, gp=0x0" (merged section); check `$gp` setup when the runtime starts.

## Runtime build and first boot (2026-10-20)
Pipeline (README "Building"): `ps2_recomp config/dotr.toml` → `tools/sync_runner.sh` → build `ps2EntryRunner` in
`../PS2Recomp/out/build-runtime` (RelWithDebInfo, FFmpeg/debug UI off) → run
`../PS2Recomp/out/build-runtime/ps2xRuntime/ps2EntryRunner "$PWD/../dotr/SLUS_205.15"`. Use `stdbuf -o0` when
logging to a file, or the runtime output is lost on timeout. Logs go to `../dotr/*.log`.
- Build times: full ~20 min; stub/toml change ~10–15 min (the batch with the 4.9 MB `register_functions.cpp`
  takes ~8 min alone); runtime `.cpp` change ~1 min. Never run two builds or two `ps2_recomp` at once: they share
  `../PS2Recomp` and `../dotr/output`.
- First boot: window/audio up, guest sets `gp=0x317ef0`, SIF init, then hung in `sub_00191A58` retrying
  `sceSifBindRpc(0x8000059A)` (libcdvd, between sceCdInit and sceCdMmode). Stubbed as
  `sceCdDiskReady@0x00191A58`: boot code at 0x200058 loops until it returns 2 (SCECdComplete). A first guess
  (sceCdChangeThreadPriority, returns 1) made it spin there instead.
- Then it looped forever loading `cdrom0:\IOP\SDRDRV.IRX` (no HLE provider). `cdrom0:` maps to the ELF's folder, so
  the whole disc is now extracted into `../dotr/` (`tools/iso9660.py ISO ../dotr --all`: IOP/, DATA/, SOUND/,
  MOVIE/). With the real IRX, all 7 modules load in the IOP emulator (SDR driver 4.0.1 prints), EE sends DMA to GIF
  and writes GS registers, then the tick log shows `pc=0x0 ra=0x0` forever (issue #6). Nothing drawn yet.
- The runtime's HLE IOP only serves libsd, mcserv and dbcman RPC IDs; libcdvd works through EE-side stubs, so any
  CD function the analyzer missed hangs like this one.

## Backlog
GitHub Issues on Glasena/dotr-recomp (`gh issue list`). Close with `Fixes #N` in the commit message.

## Reference: God of War PS2 (playable, Oct 2026)
`../Tobiichi-Port` (clone). Useful docs in `docs/waffle/`, mainly `elf-and-recompilation.md` and
`runtime-changes.md`. KIexster's pipeline: github.com/KIexster/god-of-war-recomp (68 patches in `patches/`).
- Recompiler bugs they fixed: 64-bit branches testing 32 bits, SQRT.S/RSQRT.S/DIV.S, CVT.W.S truncation.
  Part of it is already upstream (#272).
- Runtime reserved pools inside the game heap → corruption; they relocated them via `GuestReservedLayout`.
- Missing functions show at runtime as `[guest-branch:missing-target] … target=0x…`; fix = improve
  find_functions.py, regenerate, full rebuild.

## Next steps
1. Issue #6: `pc=0x0` after IOP modules load and first DMA/GS writes. Open an issue per new blocker.
2. Possible patch 0003: compile `register_functions.cpp` at -O0 outside the unity build (it only runs at startup).
3. Pin the PS2Recomp commit in the README (`eb8688b`, as KIexster pins theirs).
4. Open issues #2–#5.
