"""Build a function-map CSV (PS2Recomp ghidra_output format: name,start,end,size) for the stripped DotR ELF.
Adapted from Tobiichi-Port tools/waffle/find_functions.py (God of War).
Starts = entry point
       + functions already known to the recompiler (OUTPUT_DIR file names, optional)
       + JAL targets
       + J targets, data pointers (minus jump tables) and lui/addiu|ori-built addresses that sit on a function
         boundary (right after `jr $ra`/`j` + delay slot, optionally followed by nop padding).
Ends = next start (clamped to the end of code).
       + J/JAL targets in the overlay modules on a boundary (DISC_DIR/DATA/*MODULE.MRG, optional): ~170 main functions are only
         called from overlays.
usage: find_functions.py ELF CSV [OUTPUT_DIR [DISC_DIR]]
tools/overlays.py imports find_starts/write_csv for the overlay modules."""
import os, re, struct, sys

JR_RA, NOP = 0x03E00008, 0


def ends_function(w):
    return w == JR_RA or (w >> 26) == 2      # `jr $ra` or tail-call `j`


def find_starts(d, file_base, entry, text_start, text_end, data_ranges, known=(), candidates=()):
    """d: bytes, file_base: vaddr - file offset. known: sure starts; candidates: kept if on a function boundary.
    Returns the sorted function starts in [text_start, text_end)."""
    def word(addr):
        return struct.unpack_from('<I', d, addr - file_base)[0]

    def on_boundary(addr):
        a = addr - 4
        while a >= text_start and word(a) == NOP and a >= addr - 64:
            if a - 4 >= text_start and ends_function(word(a - 4)):   # the nop was the delay slot
                return True
            a -= 4
        return a - 4 >= text_start and ends_function(word(a - 4))     # `a` is a non-nop delay slot

    def is_text_ptr(w):
        return text_start <= w < text_end and w % 4 == 0

    starts = {entry} | set(known)
    jal, jmp = set(), set()
    for a in range(text_start, text_end, 4):
        w = word(a)
        op = w >> 26
        if op in (2, 3):
            t = ((a + 4) & 0xF0000000) | ((w & 0x03FFFFFF) << 2)
            if text_start <= t < text_end:
                (jal if op == 3 else jmp).add(t)

    # Runs of >=3 adjacent text pointers spanning <4 KB are switch jump tables: their targets are case
    # labels inside one function, not function starts.
    ptrs = set()
    for lo, hi in data_ranges:
        run = []
        for a in range(lo, hi + 4, 4):
            w = word(a) if a < hi else 0
            if is_text_ptr(w):
                run.append(w)
                continue
            if not (len(run) >= 3 and max(run) - min(run) < 0x1000):
                ptrs.update(run)
            run = []

    # Addresses materialized in code (lui rX, hi ; addiu/ori rY, rX, lo within a few instructions), e.g. function
    # pointers stored into tables at runtime.
    built = set()
    for a in range(text_start, text_end, 4):
        w = word(a)
        if w >> 26 != 0x0F:  # lui
            continue
        rt, hi = (w >> 16) & 31, (w & 0xFFFF) << 16
        for b in range(a + 4, min(a + 32, text_end), 4):
            x = word(b)
            op, rs = x >> 26, (x >> 21) & 31
            if rs == rt and op in (0x09, 0x0D):  # addiu / ori
                lo = x & 0xFFFF
                value = (hi + (lo - 0x10000 if op == 0x09 and lo & 0x8000 else lo)) & 0xFFFFFFFF
                if is_text_ptr(value):
                    built.add(value)
                break

    starts |= jal
    starts |= {t for t in jmp | ptrs | built | set(candidates) if on_boundary(t)}
    stats = f'known {len(known)}, jal {len(jal)}, ptr-candidates {len(ptrs)}, code-built {len(built)}'
    return sorted(s for s in starts if text_start <= s < text_end), stats


def write_csv(csv, starts, text_end):
    with open(csv, 'w') as f:
        f.write('Name,Start,End,Size\n')
        for i, s in enumerate(starts):
            e = starts[i + 1] if i + 1 < len(starts) else text_end
            f.write(f'sub_{s:08X},0x{s:08X},0x{e:08X},{e - s}\n')


if __name__ == '__main__':
    elf, csv = sys.argv[1:3]
    outdir = sys.argv[3] if len(sys.argv) > 3 else None
    known, from_overlays = set(), set()
    if outdir and os.path.isdir(outdir):
        for name in os.listdir(outdir):
            m = re.match(r'(?:sub|entry)_([0-9A-Fa-f]{8})', name)
            if m:
                known.add(int(m.group(1), 16))
    if len(sys.argv) > 4:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from overlays import modules
        for _, _, _, blob in modules(sys.argv[4]):
            for (w,) in struct.iter_unpack('<I', blob[:len(blob) & ~3]):
                if (w >> 26) in (2, 3):
                    t = (w & 0x03FFFFFF) << 2
                    if 0x100000 <= t < 0x286968:
                        from_overlays.add(t)
    # SLUS_205.15 has a single merged WAX section 0x100000-0x30FF00 (code + data). Code ends at 0x286968; after it
    # come VU microcode, data, and libkernel's 0x8007xxxx kernel patch blobs (0x28C258), which are not EE game code.
    TEXT_START, TEXT_END = 0x100000, 0x286968
    starts, stats = find_starts(open(elf, 'rb').read(), 0x100000 - 0x6900, 0x100008, TEXT_START, TEXT_END,
                                [(0x286968, 0x30FF00)], known, from_overlays)
    write_csv(csv, starts, TEXT_END)
    print(f'{stats}, total starts {len(starts)}')
