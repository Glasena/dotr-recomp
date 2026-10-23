# Context for new sessions

Recomp of Yu-Gi-Oh! The Duelists of the Roses (PS2, USA, `SLUS_205.15`) with PS2Recomp. See README.md for layout.
Everything in the repo (code, comments, docs, commit messages) is written in English.

## Rules
- Nothing from the game in git: ISO, ELF, IRX, generated code. They live in `../dotr/`.
- Generic PS2Recomp fixes become a file in `patches/` (upstream has 132 open PRs and merges ~3/month; don't depend
  on it). DotR-specific fixes go in `src/`.
- Before committing a new patch, apply 0001..N in order to a clean `git worktree add --detach <scratch> eb8688b`
  and `cmp` its files against `../PS2Recomp`. An earlier export (0019) was cut against a different tree and broke
  every later VU1 patch on a fresh checkout.
- Never re-enable the "Potential self-modifying code" patches that `ps2_analyzer` suggests (they become NOPs). In God
  of War they were ordinary `sw` into WAX `.data` and broke loading. DotR's 21 were already removed from
  `config/dotr.toml`.
- Commits must not expose the author's personal email: the repo-local `user.email` is a GitHub noreply address.
- Iterate on the fast path from #24 and #25. A runtime `.cpp` edit rebuilds that file and the link (~25 s).
  `ninja -n` first: if `ov_*.cpp` or the generated runner would rebuild, move the change into a `.cpp`. Editing
  `ps2_guest_abi.h`, `ps2_runtime_macros.h` or `runtime/ps2_address.h` is the slow path (~45 min) and only when the
  change cannot live anywhere else. One build at a time. `PS2X_SKIP_RENDER=1` only to reach a later frame; timing
  and dump comparisons leave it off (`PS2X_DUMP_FRAMES=1900,2100,2300 PS2X_EXIT_AT=2300` is about a minute).

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
- Build times: see "Build times (#24)". Generated code and overlays include only `ps2_guest_abi.h` +
  `ps2_runtime_macros.h` (+ `ps2_syscalls.h`/`ps2_stubs.h` in stub files): keep runtime internals out of them, or every
  edit rebuilds everything (~45 min). ccache lives in `../deps/bin/ccache` (README step 6). Never run two builds or two
  `ps2_recomp` at once: they share `../PS2Recomp` and `../dotr/output`.
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
- Patch 0019 (2026-10-22, #13): fast-block pairs call the already-decoded upper/lower op (handler id beside the
  code cache). The interpreter and `PS2X_VU_NO_DIRECT=1` still go through `execUpper`/`execLower`. Map after
  VBlank ~1800: ~14.1 VBlanks/s (5 s samples 12.6–15.0; 1900–2300 ~14.5) vs ~13.4. Frames 1900/2100/2300
  byte-identical to `test_before`. Tests 444/445 (same pre-existing GS callback failure). Next slice: FMAC
  flag updates on the fast-block path.
- Patch 0028 (2026-10-22, #36): `PS2X_VU_STATS=1` prints VU1 coverage every 5 s (`[vu-stats:*]` on stderr; test
  mode's `_Exit` skips the atexit summary). Map to VBlank 2300: 99.75% of pairs on fast blocks, the rest liveIn
  stalls (96%) and XGKICK busy (4%); one 16 KB image loaded once, every MSCAL at pc 0 (internal dispatcher), 143
  distinct blocks / 1283 pairs, ~14 pairs per block. A capture set covers the map easily (#13 step 1).
- Patch 0029 (2026-10-22, #37): fast-block tight loop. Per pair, a plan beside the handler ids (words, ids, VI
  dest, plain bit); runs of plain pairs (no branch/XGKICK/E-D-T bit/VF shadow, not the block's last pair) skip the
  generic step and write PC/cycles once. 83% of map pairs (`tight loop` in `PS2X_VU_STATS`). Game thread 1900->2300:
  111.1G -> 96.0G instructions, cycles -9.6%; wall 15.1 -> 13.9 s in the same (busy) session, ~+8-10%. Dumps and
  `PS2X_VU_FLAG_CHECK` (0 mismatches) unchanged. Left in VU1: FMAC math (`directAddSubMul` ~19% of the game thread),
  `g_loadUpper` normalizing every operand for non-FMAC uppers (~6%), flag writes (~5%).
- Patch 0030 (2026-10-22, #38): FMAC math as `fmacMath<op, toAcc>` instances (`kFmacMath` by handler id: op,
  source and kind compile-time, SSE operand normalize, blended dest write); `g_loadUpper` normalizes only the operands
  a handler reads (needs derived from the expression text, forced `constexpr`: a runtime string scan cost 1%).
  Game thread 1900->2300, interleaved: 96.0G -> 86.7G instructions (-9.7%), cycles ~41.4G -> ~38.6G (-7%), wall
  ~14.2 -> ~13.9 s (noise ±1 s). Dumps/flag check unchanged. Now: `run` with the inlined FMAC tail ~23%,
  `fmacMath` ~8%, flag queue lambda ~5%, other upper handlers ~6%, `g_loadUpper` ~3%, IOP ~14%.
- Patch 0031 (2026-10-22, #39): `PS2X_VU1_CAPTURE=<dir>` (use `../dotr/vu1`) writes `<fnv1a>.bin` per VU1 image
  and `<fnv1a>.txt`, a sorted set of `block 0x<pc> <pairs>` / `interp 0x<pc> <reason>` lines, rewritten and merged
  on each new line (idempotent, runs merge). `tools/vu1_gen.py [dir]` re-splits the blocks like `buildFastBlock`,
  checks the pair counts and prints ops/branches/XGKICKs/flag readers; no code yet (#40). Map to 2300: 143 blocks,
  1283 pairs, as `PS2X_VU_STATS`. Capture off: same dumps, same instructions.
- Patch 0032 (2026-10-22, #40): `vu1_gen.py ../dotr/vu1 --emit ../dotr/vu1/gen` writes `vu1_aot.cpp`, the
  fast-block tight-loop runs as `Vu1Aot::pair<>` calls with words/ids/VI plans as constants (`src/lib/vu/
  ps2_vu1_aot.h`, friend of VU1Interpreter; touching `ps2_vu1.h` rebuilds ~36 runtime files, no overlays).
  CMake `-DPS2X_VU1_AOT_DIR=<abs gen dir>` adds it (rebuild ~25 s). Blocks bind by (image, pc) only when words and
  `DirectIds::Plan` match. `PS2X_VU_NO_AOT=1` off, `PS2X_VU_AOT_VERIFY=1` compares with the tight loop (0 of 22M
  runs differ to 2300). Generated = 83.6% of pairs (all tight-loop pairs). Map 1900->2300 interleaved: 86.8G ->
  77.9G instructions (-10%), cycles ~39.3G -> ~36.9G (-6%), wall ~14.0 -> ~13.0 s. Dumps/flag check unchanged.
- Patch 0033 (2026-10-23, #41 stage a): each generated function now runs a whole fast block from pair 0: plain
  pairs as before, the rest (branch, XGKICK, delay slot, E/D/T, upper VF shadow) and the last pair through
  `Vu1Aot::step<>` (run()'s generic step with constants), then the block exit (`Vu1Aot::leave`). Binding also checks
  shadow reg and pair kind. run()'s loop is split into `loopTop`/`stepBody` lambdas; `PS2X_VU_AOT_VERIFY` now runs
  the generated code, then run()'s own steps for the same number of fast pairs, and compares (incl. ready cycles).
  Generated = 99.7% of pairs (all fast pairs); verify 0 mismatches in 17.8M blocks to 2300 (a broken branch
  immediate is caught). Map 1900->2300 vs post-#40: ~77.9G -> ~75.0G instructions (-3.7%), cycles ~35.8G ->
  ~35.3G (noise), wall ~12.7 s both: the generic step was not the cost; block transitions are next.
- Patch 0034 (2026-10-23, #41 stage b): after a block's exit, the generated code runs run()'s loop top itself
  (`Vu1Aot::enterNext`: commit, `tryEnterFastBlock`, elision reset) when the block at the PC is built and bound,
  and run() drives `Vu1AotRun::next` until a block stops, ends or the next entry is refused (then run() skips its
  own retry). Verify compares whole chains (0 mismatches in 262K chains to 2300). 98.3% of blocks are entered
  without returning to run(). Map vs stage a: ~75.0G -> ~74.7G instructions, cycles/wall in noise. Transitions
  left: `tryEnterFastBlock` (liveIn loop) + `exitFastBlock` + `enterNext` ~5-6% of the game thread.
- Patch 0035 (2026-10-23, #41 stage c): a chained entry right after a block ran to its end
  (`Vu1Aot::enterChained`) resolves the successor's liveIn once per (block, successor) pair (cached in
  `DirectIds::chains`, two slots per block, cleared with the fast blocks): lanes the predecessor leaves pending
  pass/fail statically, lanes it does not write are checked only when the old `m_regReadyMax` is past the entry;
  other checks as `tryEnterFastBlock`, which stays the fallback. Non-elided FMAC flag writes are queued inline
  (`Vu1Aot::queueFlags`). Map 1900->2300, 3 interleaved runs: post-#40 77.9G -> 73.6G instructions (-5.5%),
  cycles ~36.3G -> ~34.6G (-4.6%), wall ~13.0 s both (noise). Dumps, verify, flag check unchanged. GameThread now:
  generated bodies 9%, inlined FMAC 19%, non-FMAC upper ops via tables 13%, lower ops/stores/PATH1 7%, flag
  commit 5%, transitions ~5%, IOP 14%, EE 8% -> next is #44 (specialize the table handlers), not more chaining.
- Patch 0036 (2026-10-23, #42): VU1 differential test, README step 9 (`ctest -R vu1_diff`, ~4 s). Random programs
  (every FMAC kind, masks, broadcast, Q/I, flag readers, branches, a counted loop, XGKICK, LOI, Inf/NaN/denormal
  inputs) run once per engine in a child process (the switches are env statics); VF/VI/ACC/Q/P/I/R/flags/pc/
  cycles/data are compared with the interpreter: 10000 programs for the fast block, 120 for the generated code
  (`vu1_gen.py` on a capture of those programs, ~2 min compile). Breaking the flag-elision window (`>=` -> `>`)
  fails 698 / 5 programs. Known, reported: #45 (end cycles), #46 (OPMSUB lanes), #47 (generated-code hang, skipped).
  `ps2x_vu1_diff --list P` / `--repro P FILE` print and rerun one program for a minimal repro.
- Patch 0027 (2026-10-22, #35): `perf --call-graph dwarf` found the map/hash share was `IopKernel::beginNextReady`/
  `nextWakeCycle` walking the thread `std::map` on every idle IOP step (~7.5%) and the GIF_STAT lookup in
  `advanceEeTimers` (~2.1%). Kernel caches "nothing ready until cycle W" behind a version bumped by every public
  mutator; GIF_STAT node pointer cached. IOP `runCycles` 14.9% -> 9.3% of the game thread; map 1900->2300
  15.8 s -> 14.65 s (~25.3 -> ~27.3 VBlanks/s). Dumps and log identical, IOP tests pass.
- Patch 0022 (2026-10-22, #30): fast-block MADD/MSUB (vector, broadcast, Q/I) and OPMSUB into VF with SSE (0020/0021
  did ADD/SUB/MUL). Map samples after VBlank ~1800: ~14.6 VBlanks/s (14.1-15.0) vs ~14.2; dumps byte-identical.
- Patch 0023 (2026-10-22, #31): the same SSE path for the ACC forms (ADDA/SUBA/MULA/MADDA/MSUBA, broadcast, Q/I,
  OPMULA). Map after VBlank ~1800: ~14.5 VBlanks/s (13.2-15.5, two runs) vs ~14.6: no measurable gain. Dumps identical.
- Patch 0024 (2026-10-22, #32): `GSThreadedBackend` (ported from Tobiichi-Port) runs `GSCpuBackend` on a
  `GSThread`; readers (VRAM, snapshot, Present, l2h, Sync/FINISH, clear) drain the queue, then call inline. Map
  after VBlank ~1800: ~18.5 VBlanks/s (17.9-19.4, two runs) vs ~14.4 with `PS2X_GS_THREAD=0`. Dumps 1900/2100/2300
  identical to `test_before`; default 1200/1500/1700 identical on/off. `PS2X_GS_SYNC_STATS=1`: the game thread
  waits mostly on `queue-full` (~1 s per 5 s): the band-parallel raster (fork-join, bands idle ~60%) is now the
  limit, not the syncs. Presentation waits are on the main thread.
- Patch 0025 (2026-10-22, #33): ~62k fork-joins per 5 s were the cost (LoadClut flushed the queue on every TEX0,
  large prims each got their own fork-join). Now LoadClut flushes only when the CLUT changes or reads a queued
  target, large prims are queued too (~4.7k fork-joins), each rasterizer claims 4 bands per thread from an atomic
  counter, and the `GSThread` queue holds 32 chunks. Map 1900->2300 wall: ~21.7 VBlanks/s (20.5-22.9, three runs)
  vs ~17.1 for the 0024 binary in the same session; `queue-full` ~1 s -> ~0 per 5 s, the waits left are
  `sync-present`/`present` (~1.3 s per 5 s, the frame's raster tail). Raster threads 3-10 all land at ~20-21.5:
  the raster is no longer the limit. `PS2X_GS_RASTER_THREADS`/`PS2X_GS_RASTER_BANDS` override the counts.
- Patch 0026 (2026-10-22, #34): fast-block FMAC flags. An SSE classifier gives exact Z/S (and product sticky)
  for 99.98% of FMACs (normal results, ADD/SUB zero sums, zero-operand products); the rest keeps the long-double
  path. MAC/status writes that no FMAND/FMEQ/FMOR/FSAND/FSEQ/FSOR sees before the next FMAC write in the block are
  not queued (88% of FMACs; sticky bits carried to the next queued write; ones still visible at block exit are
  queued then; FSSET blocks keep all). Map 1900->2300: ~25.6 VBlanks/s (15.3/15.9 s) vs ~22.3 for the 0025
  binary (17.5/18.5 s, same session); `PS2X_VU_NO_FLAG_ELIDE=1` 17.4 s. `PS2X_VU_FLAG_CHECK=1` runs the real
  pipeline with the old model and the new one in a shadow, comparing MAC/status/clip at each reader and block
  exit: 0 mismatches over 127.9M FMACs to VBlank 2300 (a broken analysis gives 336k). Dumps identical.

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
  `ov_*.cpp` are built outside unity batches and PCH at -O1 -g0. Full overlay build ~30 min; since patch 0017 they
  only rebuild when the guest ABI headers change.
- 169 main functions are only called from overlays: `find_functions.py ... ../dotr/output ../dotr` now adds
  boundary-checked overlay J/JAL targets (3005 → 3173 functions).
- Now: New Game plays the story intro (text + portraits, 3D Stonehenge), Simon McMooran's dialogue and the NAME
  ENTRY screen (Start finishes the name), then "Play a Practice Duel" (Start) loads the tutorial duel: board, LP,
hand, Dark Magician summon with its 3D model (VBlank ~10500). Not tested further. All of this runs at ~4-7 VBlank/s (#13), so a run to VBlank 8000 takes
  ~15 min, to the duel ~25 min. Script used: `start@1000,start@1400,cross@1500`, cross every 60 from 2200 to 5600,
  `start@5750`, cross every 60 to 9100, `start@9300`, cross every 80.

## Build times (2026-10-22, #24)
- Patch 0017: `ps2_guest_abi.h` = R5900Context + address map (`runtime/ps2_address.h`) + `ps2_guest::` free functions
  forwarding to PS2Runtime (incomplete type there); emitters write `ps2_guest::X(runtime, ...)`; each generated file
  declares only its direct callees (no `ps2_recompiled_functions.h`); `register_functions.cpp` out of unity at -O0
  (881 s -> 11 s); runner unity build and PCH default OFF. `tools/overlays.py` emits only the ABI includes.
- ccache root cause: CMake's GCC PCH command `-include`s the `.gch` it writes, so ccache hashes the previous,
  non-reproducible `.gch`: the PCH and all 3189 files using it always missed. Without PCH a touch of
  `ps2_runtime_macros.h` is 100% hits (34 s; 598 s with PCH). Cost: compiling the main generated code from scratch
  takes 967 s instead of 598 s.
- Before -> after (12 threads): no-op 0.1 s -> 0.1 s; runtime `.cpp` 18 s -> 25 s (link ~15 s, ~4000 objects now);
  `ps2_runtime_core.h` edit (new PS2Runtime member) 46.5 min -> 44 s; `ps2_syscalls.h` edit (full rebuild) -> 56 s;
  regeneration, identical 28 s -> 25 s, one function merged in `funcmap.csv` 20.7 min -> 41 s; cold full ~46 min ->
  ~40-45 min. Still a full rebuild (~45 min): real edits to `ps2_guest_abi.h`, `ps2_runtime_macros.h`,
  `runtime/ps2_address.h`. `gold` links slower than bfd here (28 s vs 10-15 s).
- Configure through real paths (`/home/.../workspace/PS2Recomp`), not a symlinked checkout: paths end up in every
  compile command and a different spelling rebuilds everything.

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

## Skip-render test mode (2026-10-22, #25)
- Patch 0018, off by default: `PS2X_SKIP_RENDER=1`. On vblanks that are not among the
  `PS2X_SKIP_RENDER_WARMUP` (default 3) ticks before a `PS2X_DUMP_FRAMES` entry, VU1 `execute`/`resume` return
  immediately and GS primitive submits / framebuffer clears are skipped. VIF unpacks, MPG, DIRECT, GIF register
  writes and IMAGE/CLUT uploads still run. Leave the flag off for timing runs (#13).
- Waits: VIF and VU1 are synchronous, so a skipped program is already idle when the EE resumes (VPU_STAT VDS1/VTS1
  stay clear). Each skipped program also sets GS CSR FINISH, because the PATH1 packet that would have written it
  never runs. SIGNAL is not synthesized (it carries an id). DotR's story path does not stall on these.
- Flag off: default `tools/test_run.sh` dumps (1200, 1500, 1700) are bit-identical to the pre-change runner.
- Flag on, same script: 1200 and 1700 bit-identical; 1500 differs by 352 pixels (menu cursor jewels). Wall clock
  21 s → 13 s. Raising warmup to 30 or 120 does not change that frame; warmup 5000 (nothing skipped before the
  dump) matches. The jewel colors are chosen from state built on skipped frames.
- Long script (CLAUDE's New Game → practice duel presses) with the flag on reaches VBlank 10600 in 110 s
  (~70–140 VBlank/s; the same script without the flag takes 290 s just to VBlank 5010, ~12 VBlank/s once the 3D
  scene starts). Dumps: story text at 2300 (same sentence; 6102 pixels of the blue field differ), name prompt at
  5000 (same dialogue; the Stonehenge background is missing, 35% of pixels), duel UI at 10500 (LP, Dark Magician
  card, empty 3D view). Warmup 30 is byte-identical to warmup 3 on those three frames: a few real frames do not
  rebuild a VU-rendered layer that was produced on skipped frames. Not for performance numbers.

## Next steps (2026-10-22)
Order is tracked with the `priority: N` labels; #13 is pinned on GitHub.
1. #13 (priority 3) is the parent. #22 (async VU1) did not help: the EE waits on the kick. #23 (patch 0016) and
   patch 0019 are in (~14.1 VBlanks/s). #27 (SSE FMAC on fast blocks, children #28-#31, patches 0020-0023) is
   all in with identical dumps, but the map only went ~14.1 -> ~14.5 VBlanks/s, so #27 stays open: the FMAC
   math is not the remaining cost. Profile before the next VU1 step. Do not port PCSX2 microVU.
   Patch 0024 (#32, raster thread) took the map to ~18.5, patch 0025 (#33, raster batching/balance) to ~21.7;
   the game thread now waits only at present (~1.3 s per 5 s). Patch 0026 (#34, FMAC flag classification and
   dead-write elision) took it to ~25.6, patch 0027 (#35, IOP idle cache) to ~27.3. What is left outside VU1 is
   real IOP instruction work (~9%, incl. `servicePendingDmaInterrupts` per IOP instruction ~1.8%). Profile the game
   thread again before the next VU1 step. #36 (stats) and #37 (tight pair loop, patch 0029) are in; next per the
   #13 plan was step 3, SSE FMAC handlers + lazy operand loads (#38, patch 0030, in); step 4, capture + stats
   generator (#39, patch 0031), and step 5, AOT tight-loop runs (#40, patch 0032), are in. #41 (whole blocks in
   generated code, chained blocks, resolved chained entries: patches 0033-0035) is in, but the map only got ~5%
   cheaper: the cost is per pair in the table handlers. Next is #44 (specialize non-FMAC upper and common lower
   ops in generated code), then profile again.
2. Then #10 (box glyphs), #14 (display env), #16, #17, #3-#5. Open an issue per new blocker.
3. Pin the PS2Recomp commit in the README (`eb8688b`, as KIexster pins theirs).
