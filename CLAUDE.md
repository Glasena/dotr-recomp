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
- 833 extra LOAD segments at 0x01E00000, filesz 0, memsz 0x100–0x7000: linker descriptors of the overlay modules
  (segment i = module id i+1, memsz = its image size; 762 of the 833 ids ship on disc). See "Overlay modules" (#2).
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
- Build times (issue #21, ccache + patch 0014): cold full ~39 min (968 steps); no change 0.03 s; runtime `.cpp`
  ~12 s; runtime subsystem header (`ps2_vu1.h`, GS, audio, pad, VFS) ~30 s. Generated code includes only
  `ps2_runtime_core.h`: keep new runtime internals out of it, `ps2_runtime_macros.h` and `ps2_syscalls.h`, or every
  edit rebuilds everything again. ccache lives in `../deps/bin/ccache` (README step 6). Never run two builds or two `ps2_recomp` at once: they share
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
- Patch 0015 (2026-10-21, #13): map 8.5 -> ~11 VBlanks/s (`PS2X_EXIT_AT=2300`, frames 1900-2300), frame dumps
  byte-identical. VU1: float fast path for FMAC flags, decoded pair by reference, hazard scan skipped when all
  registers are ready, memcpy XGKICK, no 64 KiB zeroing per kick. GS: small prims queued and drawn in one band-
  parallel pass (flushed by any other backend call or a VRAM read/write overlap); `GS::setDeferredRaster(true)`
  keeps the queue across GIF packets in the runtime only. Now ~65% of the game thread is the VU1 pipeline model
  itself (commit/ready-cycle bookkeeping); the next real step is a VU1 recompiler or async VU1.
- Unit tests after 0015: 444/445; the one failure (sceGsSyncVCallback async stack pool) is unrelated.
- Patch 0016 (2026-10-21, #23): VU1 block executor. Per start PC a straight-line block (ends after a branch/E-bit
  delay slot) gets static issue offsets once; it runs when no earlier result stalls it (liveIn check), with results
  written immediately (no VF/VI/ACC/store queues, no hazard scan), PATH1 caught up lazily before stores/XGKICK/exit.
  Flags/Q/P keep their pipelines. Anything else (XGKICK while PATH1 busy, budget end) falls back to the interpreter.
  Caches survive re-uploads of identical microcode (memcmp). Map ~10.7 -> ~13.4 VBlanks/s, dumps byte-identical,
  tests 444/445. `PS2X_VU_NO_BLOCKS=1` forces the interpreter for A/B. Next VU1 cost: FMAC flags (~15%), exec decode.
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

## SPU2 AutoDMA pacing and overlays (2026-10-21, #12, #19)
- Root cause of #12: KCEJEAST links libspu2 and streams BGM with AutoDMA (`_spu_FwAutoDMA` sets ADMAS 0x1F9001B0=1,
  `_spu_FiAutoDMA` re-arms each 128 KB half from the DMA4 IRQ). The IOP emulator finished every SPU2 DMA in
  words*2 cycles, so the BGM "played" at bus speed and the EE transfer queue overflowed.
- Patch 0012: with ADMAS set for the core, the DMA completes after bytes*192 IOP cycles (48 kHz 16-bit stereo).
  Now the title BGM queue stays at 0-1, the New Game BGM change clears bit 0x2000 at VBlank ~1675.
- Next blocker (#19, fixed below): at VBlank ~1870 the main thread called overlay code at 0x1E00080.
- KCEJEAST.IRX keeps its `.symtab` and `.mdebug`: `readelf -s` names every libspu2/driver function.
- Debug trick: sample guest PCs from `ps2x::test::onVBlank` via `runtime.eeScheduler().thread(id)->activeContext()`
  (`currentContext()` is null there).

## Overlay modules (2026-10-21, #19, #2)
- DATA/CMODULE.MRG (78), BMODULE.MRG (683), MMODULE.MRG (1): "MWo3" modules, header = magic, id, load 0x1E00000,
  ?, ?, ?, end, end (+0x18/+0x1C), name at +0x20, code from +0x80. `sub_001F4900` copies a 0x8000 slot to 0x1E00000
  and calls `ENTRY_TABLES[mrg][N]` (0x2B9190/0x2BA140/0x2BAEA0, via 0x292FF0) for module `<c|b|m>N.bin`.
  ~12 MB of code in total (B modules are per-card battle code), 6x the main ELF.
- `tools/overlays.py` builds a tiny ELF per module (entry-table entry added as a start), runs `ps2_recomp`
  (single-file, `output_worker_threads = 1`: the parallel single-file writer drops entries, #20) and wraps the output in
  `namespace ov_<name>` with a sorted entry table → `../dotr/overlays/cpp/ov_<name>.cpp` (762 files, 555 MB, ~20 s).
  `src/dotr_overlays.cpp` resolves 0x1E00000-0x1E08000 by the id at 0x1E00004 (after checking "MWo3").
- Patch 0013: `g_ps2OverlayFunctionResolver` hook in `hasFunction`/`lookupFunction` (table miss only); runner
  `ov_*.cpp` are built outside unity batches and PCH at -O1 -g0. Full overlay build ~35 min; they only rebuild
  when runtime headers change.
- 169 main functions are only called from overlays: `find_functions.py ... ../dotr/output ../dotr` now adds
  boundary-checked overlay J/JAL targets (3005 → 3173 functions).
- Now: New Game plays the story intro (text + portraits, 3D Stonehenge), Simon McMooran's dialogue and the NAME
  ENTRY screen (Start finishes the name), then "Play a Practice Duel" (Start) loads the tutorial duel: board, LP,
hand, Dark Magician summon with its 3D model (VBlank ~10500). Not tested further. All of this runs at ~4-7 VBlank/s (#13), so a run to VBlank 8000 takes
  ~15 min, to the duel ~25 min. Script used: `start@1000,start@1400,cross@1500`, cross every 60 from 2200 to 5600,
  `start@5750`, cross every 60 to 9100, `start@9300`, cross every 80.

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

## Next steps (2026-10-22: sharpen the tools before more VU1 work)
Order is tracked with the `priority: N` labels; the three issues are pinned on GitHub.
1. #24 (priority 1): build. Overlays rebuild on any core header edit (~33 min), `unity_0` (probably
 `register_functions.cpp`) takes 12 min serially, ccache hits 8.8%. Goal: everyday builds under 1-2 min.
2. #25 (priority 2): opt-in test mode that skips VU1 + GS rasterization on frames not dumped, so scripts reach the
 map/duel in minutes. Off for timing runs; run the full script without it now and then and compare dumps.
3. #13 (priority 3): VU1 recompiler or async VU1.
4. Then #10 (box glyphs), #14 (display env), #16, #17, #3-#5. Open an issue per new blocker.
5. Pin the PS2Recomp commit in the README (`eb8688b`, as KIexster pins theirs).
