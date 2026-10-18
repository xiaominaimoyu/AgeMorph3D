# -*- coding: utf-8 -*-
"""Scan Table stream for valid Pcdt (piece table) candidates."""
import struct
import sys
import olefile


def scan(path):
    ole = olefile.OleFileIO(path)
    names = ['/'.join(s) for s in ole.listdir()]
    wd_name = next(n for n in names if n.lower().endswith('worddocument'))
    tbl_name = next((n for n in names if n.lower() in ('0table', '1table')), None)
    wd = ole.openstream(wd_name).read()
    tbl = ole.openstream(tbl_name).read() if tbl_name else b''
    ole.close()
    print('WordDocument len=%d, Table len=%d' % (len(wd), len(tbl)))

    # scan for Pcdt: byte 0x02 followed by uint32 lcb with (lcb-4)%12==0
    candidates = []
    for pos in range(len(tbl) - 5):
        if tbl[pos] == 2:
            lcb = struct.unpack('<I', tbl[pos + 1:pos + 5])[0]
            if lcb >= 16 and (lcb - 4) % 12 == 0 and pos + 5 + lcb <= len(tbl):
                candidates.append((pos, lcb))
    print('Pcdt candidates: %d' % len(candidates))
    for pos, lcb in candidates:
        pcdt = tbl[pos + 5:pos + 5 + lcb]
        n = (lcb - 4) // 12
        cps = struct.unpack('<%dI' % (n + 1), pcdt[0:4 * (n + 1)])
        # validate: CPs non-decreasing, total chars matches doc text size roughly
        ok_cp = all(cps[i] <= cps[i + 1] for i in range(n))
        pcd_off = 4 * (n + 1)
        fcs = []
        comps = []
        for i in range(n):
            pcd = pcdt[pcd_off + i * 8: pcd_off + i * 8 + 8]
            val1, val2 = struct.unpack('<II', pcd)
            fc = val2 & 0x3FFFFFFF
            comp = (val2 >> 31) & 1
            fcs.append(fc)
            comps.append(comp)
        ok_fc = all(0 <= f < len(wd) for f in fcs)
        total_chars = cps[-1] - cps[0]
        print('  pos=%d lcb=%d n=%d cpOK=%s fcOK=%s totalChars=%d comps=%s fc0=%d fcMax=%d' % (
            pos, lcb, n, ok_cp, ok_fc, total_chars, set(comps), fcs[0] if fcs else -1,
            max(fcs) if fcs else -1))


if __name__ == '__main__':
    scan(sys.argv[1])
