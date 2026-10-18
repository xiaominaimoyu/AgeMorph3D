# -*- coding: utf-8 -*-
"""Debug piece table parsing of a .doc file."""
import struct
import sys
import olefile


def debug(path):
    ole = olefile.OleFileIO(path)
    names = ['/'.join(s) for s in ole.listdir()]
    wd_name = next(n for n in names if n.lower().endswith('worddocument'))
    tbl_name = next((n for n in names if n.lower() in ('0table', '1table')), None)
    wd = ole.openstream(wd_name).read()
    tbl = ole.openstream(tbl_name).read() if tbl_name else b''
    ole.close()
    print('WordDocument len=%d, Table len=%d' % (len(wd), len(tbl)))
    nfib = struct.unpack('<H', wd[0x02:0x04])[0]
    print('nFib=0x%04X' % nfib)

    # candidate offsets for fcClx/lcbClx across FIB versions
    for off in (0x01A2, 0x01B0, 0x0420, 0x0422):
        if off + 8 <= len(wd):
            fc, lcb = struct.unpack('<II', wd[off:off + 8])
            print('  off 0x%04X: fcClx=%d lcbClx=%d (tbl has %d)' % (off, fc, lcb, len(tbl)))


if __name__ == '__main__':
    debug(sys.argv[1])
