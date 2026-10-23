"""VU1 AOT generator (#39, #40): read a PS2X_VU1_CAPTURE directory, print block statistics, emit C++.

The runtime (patch 0031) writes, per VU1 micro memory image, <hash>.bin (the image) and <hash>.txt with lines
"block 0x<pc> <pairs>" (fast blocks built by buildFastBlock) and "interp 0x<pc> <reason>" (tryEnterFastBlock
refusals). This script splits every captured block start the way buildFastBlock does (stop before a reserved op,
after the delay slot of a branch or E bit, at 256 pairs or at the end of the image), checks the pair count against
the capture and prints blocks, pairs, ops by kind, flag readers, XGKICKs and branches.

With --emit OUT_DIR it writes OUT_DIR/vu1_aot.cpp (#40, #41): one function per block that runs the whole fast block
the way run() in ps2_vu1_core.cpp would (plain pairs as in the tight loop, the others and the last pair through the
generic block step, then the block exit) as calls to Vu1Aot (src/lib/vu/ps2_vu1_aot.h) with the words, handler ids,
VI plans, shadow registers and pair kinds as constants, and a table keyed by (image hash, start pc). The runtime uses
a block only when its words, per-pair plans (DirectIds::Plan) and generic-step facts equal what is written here.
Build it in with cmake -DPS2X_VU1_AOT_DIR=OUT_DIR.
Each block is emitted twice (#48, #57): exact, and relaxed (the runtime default; PS2X_VU_EXACT=1 picks exact). The
relaxed one drops the MAC/status work of every FMAC whose flags no MAC/status reader in the whole micro image can see
(observable_flag_writes: a CFG search over all pairs, not only the captured ones); the others stay exact.

Every run compares the capture with config/vu1_manifest.txt (#43; image hash, block pc, pairs and content hash per
line, no game bytes) and warns about manifest blocks the capture lacks or whose pairs/content differ; --check makes
that exit 1. --write-manifest rewrites the manifest from the capture.

usage: vu1_gen.py [CAPTURE_DIR] [--emit OUT_DIR] [--check | --write-manifest]   (default ../dotr/vu1)
       vu1_gen.py --self-test"""
import collections, os, struct, sys

MANIFEST = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config',
                                        'vu1_manifest.txt'))
MAX_BLOCK_PAIRS = 256  # VU1Interpreter::kMaxFastBlockPairs

UPPER = {}
for i, bc in enumerate('xyzw'):
    for base, name in ((0x00, 'ADD'), (0x04, 'SUB'), (0x08, 'MADD'), (0x0C, 'MSUB'), (0x10, 'MAX'), (0x14, 'MINI'),
                       (0x18, 'MUL')):
        UPPER[base + i] = name + bc
UPPER.update({0x1C: 'MULq', 0x1D: 'MAXi', 0x1E: 'MULi', 0x1F: 'MINIi', 0x20: 'ADDq', 0x21: 'MADDq', 0x22: 'ADDi',
              0x23: 'MADDi', 0x24: 'SUBq', 0x25: 'MSUBq', 0x26: 'SUBi', 0x27: 'MSUBi', 0x28: 'ADD', 0x29: 'MADD',
              0x2A: 'MUL', 0x2B: 'MAX', 0x2C: 'SUB', 0x2D: 'MSUB', 0x2E: 'OPMSUB', 0x2F: 'MINI'})
UPPER_SPECIAL = {}
for i, bc in enumerate('xyzw'):
    for base, name in ((0x00, 'ADDA'), (0x04, 'SUBA'), (0x08, 'MADDA'), (0x0C, 'MSUBA'), (0x18, 'MULA')):
        UPPER_SPECIAL[base + i] = name + bc
UPPER_SPECIAL.update({0x10: 'ITOF0', 0x11: 'ITOF4', 0x12: 'ITOF12', 0x13: 'ITOF15', 0x14: 'FTOI0', 0x15: 'FTOI4',
                      0x16: 'FTOI12', 0x17: 'FTOI15', 0x1C: 'MULAq', 0x1D: 'ABS', 0x1E: 'MULAi', 0x1F: 'CLIP',
                      0x20: 'ADDAq', 0x21: 'MADDAq', 0x22: 'ADDAi', 0x23: 'MADDAi', 0x24: 'SUBAq', 0x25: 'MSUBAq',
                      0x26: 'SUBAi', 0x27: 'MSUBAi', 0x28: 'ADDA', 0x29: 'MADDA', 0x2A: 'MULA', 0x2C: 'SUBA',
                      0x2D: 'MSUBA', 0x2E: 'OPMULA', 0x2F: 'NOP', 0x30: 'NOP30'})
LOWER = {0x00: 'LQ', 0x01: 'SQ', 0x04: 'ILW', 0x05: 'ISW', 0x08: 'IADDIU', 0x09: 'ISUBIU', 0x10: 'FCEQ',
         0x11: 'FCSET', 0x12: 'FCAND', 0x13: 'FCOR', 0x14: 'FSEQ', 0x15: 'FSSET', 0x16: 'FSAND', 0x17: 'FSOR',
         0x18: 'FMEQ', 0x1A: 'FMAND', 0x1B: 'FMOR', 0x1C: 'FCGET', 0x20: 'B', 0x21: 'BAL', 0x24: 'JR', 0x25: 'JALR',
         0x28: 'IBEQ', 0x29: 'IBNE', 0x2C: 'IBLTZ', 0x2D: 'IBGTZ', 0x2E: 'IBLEZ', 0x2F: 'IBGEZ'}
LOWER_DIRECT = {0x30: 'IADD', 0x31: 'ISUB', 0x32: 'IADDI', 0x34: 'IAND', 0x35: 'IOR'}
LOWER_SPECIAL = {0x30: 'MOVE', 0x31: 'MR32', 0x34: 'LQI', 0x35: 'SQI', 0x36: 'LQD', 0x37: 'SQD', 0x38: 'DIV',
                 0x39: 'SQRT', 0x3A: 'RSQRT', 0x3B: 'WAITQ', 0x3C: 'MTIR', 0x3D: 'MFIR', 0x3E: 'ILWR', 0x3F: 'ISWR',
                 0x40: 'RNEXT', 0x41: 'RGET', 0x42: 'RINIT', 0x43: 'RXOR', 0x64: 'MFP', 0x68: 'XTOP', 0x69: 'XITOP',
                 0x6C: 'XGKICK', 0x70: 'ESADD', 0x71: 'ERSADD', 0x72: 'ELENG', 0x73: 'ERLENG', 0x74: 'EATANxy',
                 0x75: 'EATANxz', 0x76: 'ESUM', 0x77: 'ERCPR', 0x78: 'ESQRT', 0x79: 'ERSQRT', 0x7A: 'ESIN',
                 0x7B: 'WAITP', 0x7C: 'EATAN', 0x7D: 'EEXP'}
BRANCHES = {0x20, 0x21, 0x24, 0x25, 0x28, 0x29, 0x2C, 0x2D, 0x2E, 0x2F}


def fnv1a(data, h=1469598103934665603):
    for b in data:
        h = ((h ^ b) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h


def special(word):
    return (word & 3) | ((word >> 4) & 0x7C)


def upper_name(upper):
    """Mnemonic, or None when decodeUpperUsage() marks it reserved."""
    op = upper & 0x3F
    return UPPER.get(op) if op < 0x3C else UPPER_SPECIAL.get(special(upper))


def lower_name(lower, ibit):
    """Mnemonic, or None when decodeLowerUsage() marks it reserved (VU1). With the I bit the word is an immediate."""
    if ibit:
        return 'LOI'
    if lower in (0, 0x8000033C):
        return 'NOP'
    op_hi = (lower >> 25) & 0x7F
    if op_hi != 0x40:
        return LOWER.get(op_hi)
    if (lower & 0x3F) < 0x3C:
        return LOWER_DIRECT.get(lower & 0x3F)
    return LOWER_SPECIAL.get(special(lower))


def decode(image, pair):
    lower, upper = struct.unpack_from('<2I', image, pair * 8)
    ibit, ebit = bool(upper & 0x80000000), bool(upper & 0x40000000)
    lo = lower_name(lower, ibit)
    return dict(lower=lower, upper=upper, ibit=ibit, ebit=ebit, dbit=bool(upper & 0x10000000),
                tbit=bool(upper & 0x08000000), up=upper_name(upper), lo=lo,
                branch=not ibit and lo is not None and (lower >> 25) in BRANCHES,
                flag_reader=not ibit and 0x14 <= (lower >> 25) <= 0x1B and (lower >> 25) != 0x15)


def split_block(image, start_pair):
    """The pairs buildFastBlock(start_pair) covers."""
    pairs, owner = [], False
    count = len(image) // 8
    while start_pair + len(pairs) < count and len(pairs) < MAX_BLOCK_PAIRS:
        d = decode(image, start_pair + len(pairs))
        if d['up'] is None or d['lo'] is None:
            break
        pairs.append(d)
        if owner:
            break
        owner = d['branch'] or d['ebit']
    return pairs


def upper_id(upper):
    """vu1UpperHandlerId()."""
    op = upper & 0x3F
    if (upper & 0x7FF) in (0x2FF, 0x33C) or op >= 0x3C:
        return 0x40 + special(upper)
    return 0xC0 if op > 0x2F else op


def lower_id(lower, ibit):
    """vu1LowerHandlerId(), NOP for an I-bit immediate."""
    if ibit or lower in (0, 0x8000033C):
        return 0
    op_hi = (lower >> 25) & 0x7F
    if op_hi != 0x40:
        return 1 + op_hi
    return 0x140 + special(lower) if (lower & 0x3F) >= 0x3C else 0x100 + (lower & 0x3F)


def lane(c):
    return 1 << (3 - c)


def upper_vf_write(upper):
    """Register decodeUpperUsage() writes (0 for none)."""
    op, dest = upper & 0x3F, (upper >> 21) & 0xF
    if not dest:
        return 0
    if op <= 0x2F:
        return (upper >> 6) & 0x1F
    if op >= 0x3C and (0x10 <= special(upper) <= 0x17 or special(upper) == 0x1D):
        return (upper >> 16) & 0x1F
    return 0


def lower_usage(lower):
    """decodeLowerUsage() reduced to (VF registers read, VF register written, VI write mask, delaysNextBranchRead)."""
    if lower in (0, 0x8000033C):
        return set(), 0, 0, False
    op_hi, dest = (lower >> 25) & 0x7F, (lower >> 21) & 0xF
    vf_t, vf_s = (lower >> 16) & 0x1F, (lower >> 11) & 0x1F
    vi_t, vi_s, vi_d = (lower >> 16) & 0xF, (lower >> 11) & 0xF, (lower >> 6) & 0xF
    lanes_s, lanes_t = lane((lower >> 21) & 3), lane((lower >> 23) & 3)
    reads, write, vi, delays = set(), 0, 0, False
    if op_hi == 0x00:
        write = vf_t if dest else 0
    elif op_hi == 0x01:
        reads = {vf_s} if dest else set()
    elif op_hi in (0x04, 0x14, 0x16, 0x17, 0x18, 0x1A, 0x1B, 0x1C, 0x21, 0x25):
        vi = 1 << vi_t
    elif op_hi in (0x08, 0x09):
        vi, delays = 1 << vi_t, True
    elif op_hi in (0x10, 0x12, 0x13):
        vi = 2
    elif op_hi == 0x40:
        direct, sp = lower & 0x3F, special(lower)
        if direct in (0x30, 0x31, 0x34, 0x35):
            vi, delays = 1 << vi_d, True
        elif direct == 0x32:
            vi, delays = 1 << vi_t, True
        elif direct < 0x3C:
            pass
        elif sp in (0x30, 0x31):
            reads = {vf_s} if (sp == 0x31 or dest) else set()
            write = vf_t if dest else 0
        elif sp in (0x34, 0x36):
            vi, delays, write = 1 << vi_s, True, (vf_t if dest else 0)
        elif sp in (0x35, 0x37):
            vi, delays, reads = 1 << vi_t, True, ({vf_s} if dest else set())
        elif sp in (0x38, 0x3A):
            reads = {vf_s, vf_t}
        elif sp == 0x39:
            reads = {vf_t}
        elif sp == 0x3C:
            reads, vi, delays = {vf_s}, 1 << vi_t, True
        elif sp in (0x3D, 0x40, 0x41, 0x64):
            write = vf_t if dest else 0
        elif sp in (0x3E, 0x68, 0x69):
            vi = 1 << vi_t
        elif sp in (0x42, 0x43) or 0x70 <= sp <= 0x7D and sp != 0x7B:
            reads = {vf_s}
    del lanes_s, lanes_t  # every read above has nonzero lanes; only the register matters here
    return reads, write, vi & 0xFFFE, delays


def plan(d):
    """DirectIds::Plan of a decoded pair: upperId, lowerId, viReg, plain, recordVi, plus the generic-step facts the
    runtime also checks: upper VF shadow register and kind bits (kAotXgkick 1, kAotBranch 2, E 4, D 8, T 16)."""
    reads, write, vi, delays = (set(), 0, 0, False) if d['ibit'] else lower_usage(d['lower'])
    up = upper_vf_write(d['upper'])
    shadow = up if up != 0 and (up in reads or write == up) else 0
    vi_reg = (vi & -vi).bit_length() - 1 if vi else 0
    xgkick = not d['ibit'] and d['lo'] == 'XGKICK'
    plain = not (d['branch'] or xgkick or d['ebit'] or d['dbit'] or d['tbit'] or shadow)
    kind = xgkick | d['branch'] << 1 | d['ebit'] << 2 | d['dbit'] << 3 | d['tbit'] << 4
    return upper_id(d['upper']), lower_id(d['lower'], d['ibit']), vi_reg, plain, vi_reg != 0 and delays, shadow, kind


def is_fmac_flag_writer(d):
    """Vu1Aot's direct FMAC ops (vu1fast::isDirectFmacId: ADD/SUB/MUL/MADD/MSUB/OPMSUB and their ACC forms) with a
    nonzero dest: the only ops whose MAC/status flag write the relaxed variant drops."""
    uid = upper_id(d['upper'])
    op = uid - 0x40 if uid >= 0x40 else uid
    fmac = uid < 0x80 and (op <= 0x0F or 0x18 <= op <= 0x1C or (0x1E <= op <= 0x2E and op not in (0x1F, 0x2B)))
    return fmac and (d['upper'] >> 21) & 0xF != 0


def flag_reads(d):
    """(reads MAC or the Z/S/U/O status bits, reads sticky status bits) of a pair's lower op. FSAND bits 0x30 (D/I)
    only change with DIV/SQRT/RSQRT, which stay exact."""
    if d['ibit'] or d['lo'] not in ('FSEQ', 'FSAND', 'FSOR', 'FMEQ', 'FMAND', 'FMOR'):
        return False, False
    if d['lo'] == 'FSAND':
        imm = ((d['lower'] >> 10) & 0x800) | (d['lower'] & 0x7FF)
        return imm & 0xF != 0, imm & 0xFC0 != 0
    return True, d['lo'] != 'FMEQ' and d['lo'] not in ('FMAND', 'FMOR')


def successors(image):
    """Pair -> next pairs over the whole image, over-approximated: always the next pair, plus the target after a
    branch delay slot; None (anywhere) after a JR/JALR delay slot, an E-bit delay slot (the next program may start
    anywhere with the flags this one left), a D/T bit or a reserved pair."""
    count = len(image) // 8
    succ = [{(p + 1) % count} for p in range(count)]
    for p in range(count):
        d = decode(image, p)
        slot = (p + 1) % count
        if d['up'] is None or d['lo'] is None or d['dbit'] or d['tbit']:
            succ[p] = None
        elif d['ebit'] or (d['branch'] and d['lo'] in ('JR', 'JALR')):
            succ[slot] = None
        elif d['branch'] and succ[slot] is not None:
            imm = d['lower'] & 0x7FF
            succ[slot].add((slot + (imm - 0x800 if imm & 0x400 else imm)) % count)
    return succ


def observable_flag_writes(image):
    """Pairs of the whole image whose FMAC MAC/status write some reader can see; the relaxed variant keeps exactly
    those (#57). A reader sees the newest write ready by its issue (4 cycles after the write's), so a later write at
    least 4 pairs before the reader on the path hides every older one (pairs issue >= 1 cycle apart). Search state
    on entering a pair: pairs since the first write after the one tested (0 = none yet), dead at 4. A sticky-bit
    reader sees every write: then all are kept. Returns (kept pair set, summary)."""
    count = len(image) // 8
    pairs = [decode(image, p) for p in range(count)]
    reads = [flag_reads(d) for d in pairs]
    writers = [p for p, d in enumerate(pairs) if d['up'] is not None and is_fmac_flag_writer(d)]
    readers = [p for p in range(count) if reads[p][0] or reads[p][1]]
    summary = f'{len(readers)} MAC/status readers, {sum(r[1] for r in reads)} of them read sticky bits'
    if not readers:
        return set(), summary + ', no flag write kept'
    if any(r[1] for r in reads):
        return set(writers), summary + f', all {len(writers)} flag writes kept'
    succ = successors(image)
    writes = [p in set(writers) for p in range(count)]
    # live[p][s]: entering pair p in state s, a reader can still see the tested write. Least fixpoint.
    live = [[False] * 4 for _ in range(count)]

    def out_state(p, s):
        n = (1 if writes[p] else 0) if s == 0 else s + 1
        return None if n >= 4 else n

    def reaches(p, s):
        n = out_state(p, s)
        if n is None:
            return False
        return succ[p] is None or any(live[t][n] for t in succ[p])

    changed = True
    while changed:
        changed = False
        for p in range(count - 1, -1, -1):
            for s in range(4):
                if not live[p][s] and (reads[p][0] or reaches(p, s)):
                    live[p][s] = changed = True
    kept = {w for w in writers if succ[w] is None or any(live[t][0] for t in succ[w])}
    return kept, summary + f', {len(kept)} of {len(writers)} flag writes kept'


def block_body(pairs, plans, kept=()):
    """Statements of a generated block function template (Vu1Aot in ps2_vu1_aot.h; R = relaxed, #48/#57):
    plain pairs as in the tight loop, the others and the last pair through the generic block step. Pairs whose
    index is in `kept` (a flag write some reader may see) are exact in both variants."""
    lines, last, synced = [], len(pairs) - 1, True
    for k, (d, p) in enumerate(zip(pairs, plans)):
        ops = f'0x{p[0]:x}, 0x{d["upper"]:08x}u, 0x{p[1]:x}, 0x{d["lower"]:08x}u, {p[2]}, {str(p[4]).lower()}'
        mode = 'false' if k in kept else 'R'
        if p[3] and k != last:
            lines.append(f'    A::pair<{mode}, {ops}>(v, r, {k});')
            lines.append(f'    if (A::stopped(v)) return A::stop(v, r, {k + 1});')
            synced = False
            continue
        if not synced:
            lines.append(f'    A::sync(v, r, {k});')
        step = f'A::after(v, r, A::step<{mode}, {ops}, {p[5]}, {p[6]}>(v, r, {k}), {k}, {len(pairs)})'
        if k == last:
            lines.append(f'    return {step};')
        else:
            lines.append(f'    if ((st = {step}) >= 0) return st;')
            lines.append('    if (A::stopped(v)) return kAotStop;')
        synced = True
    return lines


def emit(capture_dir, out_dir):
    body, table = [], []
    for h, image, blocks, _ in load(capture_dir):
        kept, summary = observable_flag_writes(image)
        print(f'image {h}: {summary}')
        body.append(f'// image {h}: {summary}')
        for pc in sorted(blocks):
            pairs = split_block(image, pc // 8)
            plans = [plan(d) for d in pairs]
            name = f'b_{h}_{pc:04x}'
            info = ', '.join(f'{{0x{d["lower"]:08x}u, 0x{d["upper"]:08x}u, 0x{p[0]:x}, 0x{p[1]:x}, {p[2]}, '
                             f'{str(p[3]).lower()}, {str(p[4]).lower()}, {p[5]}, {p[6]}}}' for d, p in zip(pairs, plans))
            body.append(f'const Vu1AotPair {name}_info[] = {{{info}}};')
            body.append('\n'.join([f'template <bool R> int {name}(VU1Interpreter &v, Vu1AotRun &r)', '{',
                                   '    [[maybe_unused]] int st;'] +
                                  block_body(pairs, plans, {p - pc // 8 for p in kept}) + ['}']))
            key = fnv1a(image[pc:pc + 8 * len(pairs)], pc // 8)
            table.append(f'    {{0x{h}ull, 0x{pc:04x}u, {len(pairs)}u, 0x{key:016x}ull, {name}_info, {name}<false>, {name}<true>}},')
    os.makedirs(out_dir, exist_ok=True)
    text = '\n'.join([
        '// Generated by dotr-recomp tools/vu1_gen.py from a PS2X_VU1_CAPTURE directory. Game data: not for git.',
        '#include "ps2_vu1_aot.h"', '', 'namespace', '{', 'using A = Vu1Aot;', ''] + body + [
        '}', '', 'extern const Vu1AotBlock g_vu1AotBlocks[] = {'] + table + [
        '};', f'extern const uint32_t g_vu1AotBlockCount = {len(table)}u;', ''])
    path = os.path.join(out_dir, 'vu1_aot.cpp')
    old = open(path).read() if os.path.exists(path) else None
    if old != text:  # keep the timestamp when nothing changed, so ninja does not rebuild it
        open(path, 'w').write(text)
    print(f'wrote {path}: {len(table)} blocks')


def load(capture_dir):
    for name in sorted(os.listdir(capture_dir)):
        if not name.endswith('.bin'):
            continue
        h = name[:-4]
        image = open(os.path.join(capture_dir, name), 'rb').read()
        assert fnv1a(image) == int(h, 16), f'{name}: hash does not match its bytes'
        blocks, interp = {}, collections.Counter()
        txt = os.path.join(capture_dir, h + '.txt')
        for line in open(txt) if os.path.exists(txt) else ():
            kind, pc, value = line.split()
            if kind == 'block':
                blocks[int(pc, 16)] = int(value)
            else:
                interp[value] += 1
        yield h, image, blocks, interp


def stats(h, image, blocks, interp):
    ops, kinds, contents = collections.Counter(), collections.Counter(), set()
    total = 0
    for pc, recorded in sorted(blocks.items()):
        pairs = split_block(image, pc // 8)
        assert len(pairs) == recorded, f'{h} block 0x{pc:04x}: split {len(pairs)} pairs, capture says {recorded}'
        contents.add(fnv1a(image[pc:pc + 8 * len(pairs)], pc // 8))  # the PS2X_VU_STATS block key
        total += len(pairs)
        for d in pairs:
            ops['upper ' + d['up']] += 1
            ops['lower ' + d['lo']] += 1
            for k in ('branch', 'flag_reader', 'ebit', 'ibit', 'dbit', 'tbit'):
                kinds[k] += d[k]
            kinds['xgkick'] += d['lo'] == 'XGKICK'
            kinds['fsset'] += d['lo'] == 'FSSET'
    print(f'image {h}: {len(image) // 8} pairs, blocks {len(blocks)} ({len(contents)} distinct contents), '
          f'{total} pairs ({total / max(len(blocks), 1):.1f}/block)')
    print('  ' + ', '.join(f'{k} {kinds[k]}' for k in ('branch', 'xgkick', 'flag_reader', 'fsset', 'ebit', 'ibit',
                                                        'dbit', 'tbit')))
    print('  interpreter entry pcs by reason: ' + (', '.join(f'{r} {n}' for r, n in interp.most_common()) or 'none'))
    for side in ('upper', 'lower'):
        row = sorted(((n, op[6:]) for op, n in ops.items() if op.startswith(side)), reverse=True)
        print(f'  {side} ops: ' + ' '.join(f'{op}={n}' for n, op in row))
    return len(blocks), total


def manifest_rows(captures):
    """(image hash, pc, pairs, content hash) per captured block; captures as yielded by load()."""
    rows = []
    for h, image, blocks, _ in captures:
        for pc in sorted(blocks):
            n = len(split_block(image, pc // 8))
            rows.append((h, pc, n, fnv1a(image[pc:pc + 8 * n], pc // 8)))
    return rows


def manifest_lines(rows):
    return [f'{h} 0x{pc:04x} {n} {key:016x}' for h, pc, n, key in rows]


def manifest_problems(manifest, rows):
    """Manifest lines (comments allowed) the capture rows lack or contradict."""
    have = {(h, pc): (n, key) for h, pc, n, key in rows}
    problems = []
    for line in manifest:
        if not line.strip() or line.startswith('#'):
            continue
        h, pc, n, key = line.split()
        got = have.get((h, int(pc, 16)))
        if got is None:
            problems.append(f'{h} block {pc}: in the manifest, not in the capture')
        elif got != (int(n), int(key, 16)):
            problems.append(f'{h} block {pc}: manifest {n} pairs {key}, capture {got[0]} pairs {got[1]:016x}')
    return problems


def self_test():
    nop_upper, ebit = 0x000002FF, 0x40000000
    b_op = 0x20 << 25
    image = struct.pack('<12I', 0, nop_upper, b_op, nop_upper, 0, nop_upper,  # NOP, B, delay slot
                        0, nop_upper | ebit, 0, nop_upper,                      # E bit, delay slot
                        0x7F << 25, nop_upper)                                 # reserved lower
    assert [len(split_block(image, p)) for p in range(6)] == [3, 2, 3, 2, 1, 0]
    assert fnv1a(b'') == 1469598103934665603
    # IADDI vi1 (delays the next branch read), MOVE.xyzw vf1, vf2 under an upper writing vf2 (shadow), B, delay slot
    iaddi = (0x40 << 25) | (1 << 16) | 0x32
    move = (0x40 << 25) | (0xF << 21) | (1 << 16) | (2 << 11) | 0x33C
    add_vf2 = (0xF << 21) | (2 << 6) | 0x28
    image = struct.pack('<8I', iaddi, nop_upper, move, add_vf2, b_op, nop_upper, 0, nop_upper)
    plans = [plan(d) for d in split_block(image, 0)]
    assert [p[2:] for p in plans] == [(1, True, True, 0, 0), (0, False, False, 2, 0), (0, False, False, 0, 2),
                                      (0, True, False, 0, 0)]
    assert plans[1][:2] == (0x28, 0x170) and plans[0][1] == 0x132
    body = block_body(split_block(image, 0), plans)
    assert [l.split('<')[0].strip() for l in body] == [
        'A::pair', 'if (A::stopped(v)) return A::stop(v, r, 1);', 'A::sync(v, r, 1);', 'if ((st = A::after(v, r, A::step',
        'if (A::stopped(v)) return kAotStop;', 'if ((st = A::after(v, r, A::step', 'if (A::stopped(v)) return kAotStop;',
        'return A::after(v, r, A::step'], body
    rows = manifest_rows([('00', image, {0: 4, 8: 3}, None)])
    lines = manifest_lines(rows)
    assert [l.split()[:3] for l in lines] == [['00', '0x0000', '4'], ['00', '0x0008', '3']]
    assert manifest_problems(['# comment', ''] + lines, rows) == []
    assert manifest_problems(lines, rows[1:]) == ['00 block 0x0000: in the manifest, not in the capture']
    bad = manifest_rows([('00', image[:8] + struct.pack('<I', iaddi + 1) + image[12:], {8: 3}, None)])
    assert manifest_problems(lines, rows[:1] + bad)[0].startswith('00 block 0x0008: manifest 3 pairs')
    # Flag proof: ADD, ADD, 4 NOPs, FSAND S, E bit, delay slot. The second ADD is 5 pairs before the reader, so it
    # hides the first one; a sticky FSAND sees both; without a reader nothing is kept.
    add = (0xF << 21) | (2 << 16) | (1 << 11) | (3 << 6) | 0x28
    fsand = lambda imm: (0x16 << 25) | (2 << 16) | ((imm & 0x800) << 10) | (imm & 0x7FF)
    prog = lambda reader: struct.pack('<18I', 0, add, 0, add, 0, nop_upper, 0, nop_upper, 0, nop_upper, 0, nop_upper,
                                      reader, nop_upper, 0, nop_upper | ebit, 0, nop_upper)
    assert observable_flag_writes(prog(fsand(2)))[0] == {1}
    assert observable_flag_writes(prog(fsand(0x40)))[0] == {0, 1}
    assert observable_flag_writes(prog(0))[0] == set()
    print('self-test ok')


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        self_test()
        sys.exit()
    args = sys.argv[1:]
    out = None
    check, write = '--check' in args, '--write-manifest' in args
    args = [a for a in args if a not in ('--check', '--write-manifest')]
    if '--emit' in args:
        i = args.index('--emit')
        out = args[i + 1]
        del args[i:i + 2]
    capture = args[0] if args else os.path.join(os.path.dirname(__file__), '..', '..', 'dotr', 'vu1')
    n_blocks = n_pairs = 0
    for item in load(capture):
        b, p = stats(*item)
        n_blocks, n_pairs = n_blocks + b, n_pairs + p
    print(f'total: {n_blocks} blocks, {n_pairs} pairs')
    rows = manifest_rows(load(capture))
    if write:
        open(MANIFEST, 'w').write('\n'.join([
            '# VU1 fast blocks of a PS2X_VU1_CAPTURE run, written by tools/vu1_gen.py --write-manifest (#43). No game',
            '# bytes: image fnv1a, block start pc, pairs, fnv1a of the block\'s words seeded with its start pair index.']
            + manifest_lines(rows)) + '\n')
        print(f'wrote {MANIFEST}: {len(rows)} blocks')
    problems = manifest_problems(open(MANIFEST).read().splitlines(), rows) if os.path.exists(MANIFEST) else []
    for p in problems:
        print('warning: ' + p, file=sys.stderr)
    if problems:
        print(f'warning: capture differs from {MANIFEST} in {len(problems)} blocks', file=sys.stderr)
    if out:
        emit(capture, out)
    if check and problems:
        sys.exit(1)
