# -*- coding: utf-8 -*-
"""Extract text from legacy .doc (Word 97-2003 binary / Word 95) files.

Handles the PCD layout variant where fc is the uint32 at PCD bytes 2-5
(seen in files with nFib=0x00C1), falling back to the standard layout
(fc at bytes 4-7, fn at bit 31 of bytes 0-3) when the first yields garbage.
"""
import struct
import sys
import olefile


def _cjk_ratio(s):
    if not s:
        return 0.0
    cjk = sum(1 for ch in s if '\u4e00' <= ch <= '\u9fff' or ch in '，。、；：（）')
    return cjk / len(s)


def _read_streams(path):
    ole = olefile.OleFileIO(path)
    names = ['/'.join(s) for s in ole.listdir()]
    wd_name = next((n for n in names if n.lower().endswith('worddocument')), None)
    tbl_name = next((n for n in names if n.lower() in ('0table', '1table')), None)
    if wd_name is None:
        ole.close()
        raise RuntimeError('WordDocument stream not found')
    wd = ole.openstream(wd_name).read()
    tbl = ole.openstream(tbl_name).read() if tbl_name else b''
    ole.close()
    return wd, tbl


def _find_pcdt(tbl):
    """Locate PlcPcd data inside the Table stream (CLX -> Pcdt)."""
    best = None
    for pos in range(len(tbl) - 21):
        if tbl[pos] != 2:
            continue
        lcb = struct.unpack('<I', tbl[pos + 1:pos + 5])[0]
        if lcb < 16 or (lcb - 4) % 12 != 0 or pos + 5 + lcb > len(tbl):
            continue
        pcdt = tbl[pos + 5:pos + 5 + lcb]
        n = (lcb - 4) // 12
        cps = struct.unpack('<%dI' % (n + 1), pcdt[0:4 * (n + 1)])
        if any(cps[i] > cps[i + 1] for i in range(n)):
            continue
        if cps[0] != 0 or cps[-1] < 50:
            continue
        pcd_off = 4 * (n + 1)
        pieces = []
        ok = True
        for i in range(n):
            pcd = pcdt[pcd_off + i * 8: pcd_off + i * 8 + 8]
            if len(pcd) < 8:
                ok = False
                break
            v_mid = struct.unpack('<I', pcd[2:6])[0]
            v_lo = struct.unpack('<I', pcd[0:4])[0]
            v_hi = struct.unpack('<I', pcd[4:8])[0]
            # variant A (word95): fc = u32 at bytes 2-5, fn at bytes 6-7
            fc_a = v_mid & 0x3FFFFFFF
            fn_a = pcd[7]
            # variant B (standard): fn = bit31 of bytes0-3, fc = u32 at bytes 4-7
            fn_b = (v_lo >> 31) & 1
            fc_b = v_hi & 0x3FFFFFFF
            pieces.append((cps[i], cps[i + 1], fc_a, fn_a, fc_b, fn_b))
        if not ok:
            continue
        if best is None or n > best[1]:
            best = (pieces, n)
    if best is None:
        raise RuntimeError('no valid piece table found')
    return best[0]


def _decode_piece(wd, cp_start, cp_end, fc, fn):
    nchars = cp_end - cp_start
    if fn:
        raw = wd[fc:fc + nchars]
        return raw.decode('cp1252', errors='replace')
    raw = wd[fc:fc + nchars * 2]
    return raw.decode('utf-16-le', errors='replace')


def extract_doc_text(path):
    wd, tbl = _read_streams(path)
    pieces = _find_pcdt(tbl)
    # decide variant by CJK ratio of first non-empty piece
    score_a = score_b = 0.0
    for cp0, cp1, fc_a, fn_a, fc_b, fn_b in pieces:
        if cp1 - cp0 < 5:
            continue
        ta = _decode_piece(wd, cp0, cp1, fc_a, fn_a)
        tb = _decode_piece(wd, cp0, cp1, fc_b, fn_b)
        score_a = max(score_a, _cjk_ratio(ta))
        score_b = max(score_b, _cjk_ratio(tb))
        break
    use_a = score_a >= score_b
    out = []
    for cp0, cp1, fc_a, fn_a, fc_b, fn_b in pieces:
        fc, fn = (fc_a, fn_a) if use_a else (fc_b, fn_b)
        out.append(_decode_piece(wd, cp0, cp1, fc, fn))
    return ''.join(out)


def main():
    path = sys.argv[1]
    text = extract_doc_text(path)
    text = (text.replace('\r', '\n').replace('\x07', ' | ')
                .replace('\x0b', '\\n').replace('\x01', ''))
    sys.stdout.write(text)


if __name__ == '__main__':
    main()
