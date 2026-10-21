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
- Issue #6 (`pc=0x0`) fixed: the main thread was Dormant. `SetupHeap(0x1FE0000, 0x20000)` (DotR's newlib heap; the
  834 LOAD segments fill 0x1E00000-0x1FE0000) was clamped to the runtime limit 0x1F00000 → empty heap → every
  malloc returned 0 → init `sub_001001D0` failed → main returned to ra=0. Patch 0003 moves the runtime's RPC/TLS/
  boot-mode pools to 0x80000-0xBFFFF and callback stacks to 0xC0000-0xFFFFF, and lets an explicit heap reach 32 MB.
- Then SDFS (game file layer, 0x1FF480) waited forever: `sceCdCallback` was a no-op. Patch 0004 stores the callback
  (0x200170) and queues it after each `sceCdRead`.
- 98 `sceCdSearchFile` OK, SDFS loads, memory card probed, opening movie OPMV_US.PSS starts streaming.

## Movie skip and title loop (2026-10-20, #7)
- No sudo here, so no system FFmpeg; movies are skipped instead. The analyzer had missed `sceMpegIsEnd@0x0018EE58`
  and `sceMpegIsRefBuffEmpty@0x0018EE68` (now toml stubs; the recompiled IsEnd just read guest memory).
- Patch 0006: without FFmpeg, the MPEG HLE marks the decoder failed (demux keeps running, so the audio-ready check
  passes), serves 30 blank pictures (the player at 0x242600 only starts display once its 2-slot frame queue at
  0x350600 is full) and then `sceMpegIsEnd` returns 1.
- Patch 0007: `RotateThreadReadyQueue` charges 4096 EE cycles. VBlank needs both host time and EE cycles; the
  movie's threads spin on yields, which cost host time but almost no cycles, so VBlank ran at ~0.5 Hz.
- Now: intro skipped in a few s, then `system/system0.grp` + `BGM/0002.pcm` load and the title loop runs (attract
  replays the intro after ~20 s; Enter = Start stops that), but the screen was black (#8, fixed below).
  Replaying the movie fails an IOP heap allocation (#9).
- Driving the window: `xdotool` (Enter = Start, X = Cross) and `import -window <id>` work (`xwd` gives black).
- Patch 0005 (diagnostics): tick log lists every EE thread (status/wait/pc); a thread falling to pc=0 prints its last
  32 dispatches (`[ee:thread-pc0]`). Changing `ps2_runtime.h` rebuilds everything (~10 min).

## Title screen and main menu (2026-10-21, #8)
- Root cause of the black title: the analyzer stubs only some libvifpk helpers (`sceVif1PkAddGsAD`,
  `sceVif1PkCloseGifTag`, GIF variants). Their HLE wrote the open DMA tag's QWC eagerly on every pointer move, and
  the game's recompiled terminate (0x187608) then did the SDK `+=`, doubling QWC. The VIF1 chain walker went off
  phase into GS data (a fake REF tag) and DIRECT data never matched the draws.
- Then every pixel failed ZTST=GEQUAL: z buffer stayed at 0xFFFFFF because the HLE `sceGsSetDefClear` was a no-op
  and `sceGsSwapDBuff` never sent the DBuff clear packet (and `sceGsSetDefDBuff` read ztest/zpsm/clear from the
  stack instead of t0-t2).
- Patch 0008: terminate adds QWC like the SDK (no eager count), real `sceGsSetDefClear`, `sceGsSetDefDBuff` args
  + clear seeding, `sceGsSwapDBuff` applies the clear, `sceGsPutDrawEnv` sends the tagged packet (arg is the GIFtag,
  not the env). Upstream test updated, not run (ps2xTest build needs elfio headers).
- Now: title screen and main menu render and accept input. NEW GAME -> #10. `sceSifFreeIopHeap@0x001829B0` is now
  a toml stub; #9 needs IOP RAM ownership tracking (see the issue comment).
- Debug trick that found it: temporary `fprintf` in a runner copy of a generated function
  (`ps2xRuntime/src/runner/sub_*.cpp`, ~1 min rebuild; `tools/sync_runner.sh` restores it).

## New Game and the IOP sound driver (2026-10-21, #10, #9)
- Root cause of #10: `IopMemory::allocate` bumped a cursor and never reused freed blocks. On the post-movie sound
  reset KCEJEAST.IRX frees and re-allocates its 0xC1800 stream buffer; that allocation returned 0, so the EE streamed
  BGM and the `system0.grp` bank to IOP 0x0-0xA6320, overwriting the IOP modules. The KCEJEAST RPC server (0x4A08C)
  then hit a Reserved Instruction, every reply became an echo of the request, and New Game waited forever for the BGM
  change (status bit 0x2000 at EE 0x400000) behind a full black fade.
- Patch 0009: first-fit IOP heap (+ real `maxFreeMemory`, unit test in `iop_import_tests`) and IOP
  `RegisterVblankHandler` delivery (KCEJEAST drives its bank upload from a vblank handler). Also fixes #9.
- Now: title shows PRESS START BUTTON, BGM streams/fades, New Game loads the map and `BGM/0024.pcm`, but the map stays
  behind the fade: the BGM transfer queue overflows because SPU2 streaming isn't paced (#12). 3D runs ~1.3 fps (#13);
  black/green frames come from the HLE swap's display env (#14).
- Note: SPU2 STATX bit 0x80 must stay set after a DMA start (KCEJEAST's IRQ 0x28 handler polls for it set).
- Debug tricks used: temporary hooks in `PS2Runtime::dispatchGuestBranch` (first-call log, call histogram, guest-pc
  sampling profiler, RAM dumps, word watch) and VRAM dumps decoded with the runtime's `ps2_gs_psmt*.h` swizzle headers.

## Real movie playback (2026-10-21, #11)
- FFmpeg 7.1 built from source (README step 5, no nasm so `--disable-x86asm`, shared libs) into `../deps/ffmpeg`.
  Upstream's Linux branch already uses pkg-config; `-DCMAKE_PREFIX_PATH=../deps/ffmpeg` is enough, no patch. The
  runner gets an RPATH to it. The `build-runtime` cache now has FFmpeg ON.
- OPMV_US.PSS plays with real frames; Start (Enter key, via xdotool keydown/keyup) skips it to the title, then
  Enter → menu → Cross (`X`) on New Game works. The stream is 114.6 s (pack SCR).
- Screenshots: use `tools/test_run.sh` (below), not xdotool/import.

## Performance (2026-10-21, #13, #15)
- Profiling: no perf installed, but `apt-get download linux-tools-5.15.0-117` + `dpkg-deb -x` gives a working
  user-space `perf` (paranoid=2, no root). `perf record -F 999 -p PID`, `perf report --comm GameThread`.
- Measure with the runtime's `[perf] vblank/s=… swap/s=…` stderr line (every 5 s; 60/s = full speed, DotR swaps 30).
- Hotspots found: (1) `PS2X_ENABLE_AGRESSIVE_LOGS` (upstream default ON) logs+flushes every recompiled function call
  to `ps2_log.txt` (GBs) -> now OFF in the README configure line. (2) Software GS rasterizer (WritePixel/
  SampleTexture) is single-threaded: menu draws ~1.75 Mpixel/frame. (3) VU1 interpreter scanned ~50 pipeline slots
  every cycle.
- Patch 0010: sprites/triangles >= 4096 px rasterized by 8-row bands on hw/2 threads (synchronous, per-thread
  texture page cache, caller's FP rounding mode); VU1 commit visits only queued entries (bitmasks) and skips
  cycles before the next ready one; VU/GS sources at -O3; small VU1 helpers inlined (header change = full rebuild);
  bilinear lerp without libm `lround`; `[perf]` rate line.
- vblank/s (swap/s) before -> after: movie 22 -> 52-60 (intro reaches the title in ~2 min instead of ~8.5),
  title 54 (27) -> 60 (30), menu 19 (9.5) -> 47 (23.5), map 2.9 (1.45) -> 7 (3.5).
- Map is still VU1-interpreter bound (~75% of the game thread): needs a VU1 recompiler or async VU1 (#13 open).
  Exception-based EE thread switches cost ~14% in movies (#16). One upstream GS unit test fails before and after (#17).

## Automated test mode (2026-10-21, #18) — agents MUST use this, never manual screenshots
- `tools/test_run.sh`: hidden window, no audio, uncapped VBlanks, scripted pad, PNG dumps, exit. Default script:
  `start@1000` skips the movie, title at 1200, `start@1400` → menu (1500), `cross@1500` New Game → "NOW LOADING"
  (1700), exit 1750. ~23 s wall clock; two runs gave bit-identical dumps. Dumps: `../dotr/test/frame_<N>.png`,
  log: `../dotr/test_run.log` (only `[test]` lines are echoed). Look at dumps with the Read tool (`montage` to tile).
- Env (patch 0011, all off by default): `PS2X_HEADLESS=1`, `PS2X_UNCAPPED=1` (EE deadlines ignore wall clock),
  `PS2X_INPUT_SCRIPT=button@vblank,...` (held 10 VBlanks; up/down/left/right/start/select/cross/circle/square/
  triangle/l1/r1/l2/r2/l3/r3), `PS2X_DUMP_FRAMES=n,...`, `PS2X_DUMP_DIR`, `PS2X_EXIT_AT=n`. The script honours
  overrides, e.g. `PS2X_INPUT_SCRIPT=... PS2X_DUMP_FRAMES=... PS2X_EXIT_AT=... tools/test_run.sh`.
- Uncapped only helps where the host is faster than the PS2 (boot ~105 VBlank/s); movie/title/menu are CPU-bound
  near 50–60/s and the map ~7/s, so keep scripts short past New Game.

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
1. #12 (SPU2 stream pacing for New Game), #13 (VU1 still the 3D ceiling), #14 (display env), #16, #17. Open an issue
   per new blocker.
2. Possible patch: compile `register_functions.cpp` at -O0 outside the unity build (it only runs at startup).
3. Pin the PS2Recomp commit in the README (`eb8688b`, as KIexster pins theirs).
4. Open issues #2–#5.
