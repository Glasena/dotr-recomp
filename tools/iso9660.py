# Minimal ISO 9660 reader: list root dir, extract named files.
# usage: iso9660.py <iso> [outdir name...]
import os
import struct
import sys

S = 2048


def records(f, lba, size):
    f.seek(lba * S)
    data = f.read(size)
    i = 0
    while i < len(data):
        n = data[i]
        if n == 0:  # records never span sectors; skip padding
            i = (i // S + 1) * S
            continue
        r = data[i:i + n]
        ext, = struct.unpack_from('<I', r, 2)
        sz, = struct.unpack_from('<I', r, 10)
        flags = r[25]
        name = r[33:33 + r[32]].decode('latin1').split(';')[0]
        if name not in ('\x00', '\x01'):
            yield name, ext, sz, bool(flags & 2)
        i += n


def main():
    iso = sys.argv[1]
    with open(iso, 'rb') as f:
        f.seek(16 * S)
        pvd = f.read(S)
        assert pvd[1:6] == b'CD001', 'not ISO 9660'
        root = pvd[156:190]
        lba, = struct.unpack_from('<I', root, 2)
        size, = struct.unpack_from('<I', root, 10)
        entries = list(records(f, lba, size))
        if len(sys.argv) < 4:
            for name, ext, sz, d in entries:
                print(f"{'D' if d else ' '} {sz:>12} {name}")
            return
        out, wanted = sys.argv[2], set(sys.argv[3:])
        for name, ext, sz, d in entries:
            if name in wanted and not d:
                f.seek(ext * S)
                with open(os.path.join(out, name), 'wb') as o:
                    o.write(f.read(sz))
                print('extracted', name, sz)


if __name__ == '__main__':
    main()
