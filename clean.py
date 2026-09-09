#!/usr/bin/env python3
"""Isolate the dominant colour (and every tone of it) plus its black outline from a noisy PNG.

Writes a flat PNG: white background, solid fill, pure-black outline -- ideal tracer input.
    ./clean.py shot.png -o clean/          ./clean.py *.png --color '#3b7ea1'
Tuning: --chroma-tol is tight (same hue), --light-tol is loose (same hue, any tone).
        --box X,Y,W,H when the background shares the shape's colour (photos, rendered CAD);
        --at X,Y to pick one region by a point on it.
        --keep 1 if the drawing is a single part; --min-area to drop bigger debris.
        Arrows are stripped by default (--no-arrows keeps them).
        --tones 3 keeps per-face shading on 3-D shapes; interior edges are kept when their
        ink reaches the perimeter, so stray specks go but 3-D construction lines stay.
"""
import argparse, os, sys
import cv2, numpy as np

CRIT = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 30, .5)

def ell(k): return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k | 1, k | 1))

def fill_holes(mask, paper, max_area):
    """Close interior gaps that are noise: too small to be real, or not paper-coloured inside."""
    n, lbl, st, _ = cv2.connectedComponentsWithStats(1 - mask, 4)
    h, w = mask.shape
    cnt = np.bincount(lbl.ravel(), minlength=n)
    pap = np.bincount(lbl.ravel(), weights=paper.ravel().astype(float), minlength=n)
    inner = (st[:, 0] > 0) & (st[:, 1] > 0) & (st[:, 0] + st[:, 2] < w) & (st[:, 1] + st[:, 3] < h)
    hit = inner & ((st[:, 4] <= max_area) | (pap / np.maximum(cnt, 1) < .5))
    hit[0] = False
    return (mask | hit[lbl]).astype(np.uint8)

def at_pt(mask, xy):
    """Keep only the region under a seed point -- for diagrams colour alone cannot separate."""
    n, lbl = cv2.connectedComponents(mask, connectivity=8)
    i = int(lbl[xy[1], xy[0]])
    return mask if i == 0 else (lbl == i).astype(np.uint8)

def keep_big(mask, min_area, keep=0):
    n, lbl, st, _ = cv2.connectedComponentsWithStats(mask, 8)
    ids = [i for i in sorted(range(1, n), key=lambda i: -st[i, 4]) if st[i, 4] >= min_area]
    sel = np.zeros(n, bool); sel[ids[:keep] if keep else ids] = True
    return sel[lbl].astype(np.uint8)

def clean(path, a):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None: sys.exit(f"cannot read {path}")
    if img.dtype == np.uint16: img = (img >> 8).astype(np.uint8)
    if img.ndim == 2: img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:                                          # composite over white
        al = img[:, :, 3:4] / 255.0
        img = (img[:, :, :3] * al + 255 * (1 - al)).astype(np.uint8)
    img = img[:, :, :3]
    if a.median > 1: img = cv2.medianBlur(img, a.median | 1)        # kill salt-and-pepper
    if a.bilateral: img = cv2.bilateralFilter(img, a.bilateral, 40, 10)   # denoise, keep edges

    if a.box:                          # photos/renders: background shares the shape's own colour,
        x, y, bw, bh = (int(v) for v in a.box.split(','))   # so cut it out geometrically first
        gm = np.zeros(img.shape[:2], np.uint8); z = np.zeros((1, 65), np.float64)
        cv2.grabCut(img, gm, (x, y, bw, bh), z, z.copy(), 6, cv2.GC_INIT_WITH_RECT)
        img[keep_big(((gm == 1) | (gm == 3)).astype(np.uint8), 0, 1) == 0] = 255

    lab = cv2.cvtColor(img.astype(np.float32) / 255, cv2.COLOR_BGR2LAB)   # L 0-100, a/b +-127
    L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
    chroma = np.hypot(A, B)
    ink   = (L <= a.ink) & (chroma <= 22)                          # dark and neutral = outline
    paper = (L >= a.paper) & (chroma <= 14)                        # background
    cand  = ~ink & ~paper

    xy = tuple(int(v) for v in a.at.split(',')) if a.at else None
    if xy:                                                         # sample the tone at the seed
        t = np.median(lab[max(0, xy[1] - 3):xy[1] + 4, max(0, xy[0] - 3):xy[0] + 4].reshape(-1, 3), 0)
    elif a.color:                                                  # explicit target colour
        h = a.color.lstrip('#'); rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
        t = cv2.cvtColor(np.float32([[rgb[::-1]]]) / 255, cv2.COLOR_BGR2LAB)[0, 0]
    else:                                                          # k-means, lightness damped
        px = lab[cand]
        if len(px) < 64: sys.exit(f"{path}: no coloured pixels survived the filters")
        px = px[::max(1, len(px) // 150000)]
        f = np.ascontiguousarray(np.c_[px[:, 1], px[:, 2], px[:, 0] * a.lweight], np.float32)
        lb = cv2.kmeans(f, min(a.clusters, len(f)), None, CRIT, 4, cv2.KMEANS_PP_CENTERS)[1].ravel()
        t = np.median(px[lb == np.bincount(lb).argmax()], 0)        # robust centre of the biggest

    dh = np.abs(np.angle(np.exp(1j * (np.arctan2(B, A) - np.arctan2(t[2], t[1]))))) * 57.2958
    fill = ((((dh <= a.hue_tol) & (chroma >= a.min_chroma)) |       # one hue, any saturation...
             (np.hypot(A - t[1], B - t[2]) <= a.chroma_tol)) &      # ...or a near-neutral match
            (np.abs(L - t[0]) <= a.light_tol) & cand).astype(np.uint8)   # ...and any lightness
    if a.open:  fill = cv2.morphologyEx(fill, cv2.MORPH_OPEN,  ell(a.open))   # specks out
    if a.close: fill = cv2.morphologyEx(fill, cv2.MORPH_CLOSE, ell(a.close))  # gaps sealed
    tone0 = fill.copy()                                             # pixels that truly matched
    area = a.min_area * img.shape[0] * img.shape[1] if a.min_area < 1 else a.min_area

    nib = (ink & (cv2.dilate(fill, ell(2 * a.reach + 1)) > 0)).astype(np.uint8)   # ink on the shape
    sil = keep_big(((fill | nib) > 0).astype(np.uint8), area, a.keep)   # group faces into whole parts
    if xy: sil = at_pt(sil, xy)                                     # the part the user pointed at
    sil = fill_holes(sil, paper, a.fill_holes * img.shape[0] * img.shape[1]
                     if a.fill_holes < 1 else a.fill_holes)
    sealed = cv2.morphologyEx(sil, cv2.MORPH_CLOSE, ell(a.seal))
    sil = (sil | (sealed & ink)).astype(np.uint8)   # swallow thick ink lying on the shape
    nib &= sil

    # An internal 3-D edge is real if its ink eventually reaches the perimeter; a stray speck is not.
    bg = (sil == 0).astype(np.uint8)          # real background only: outside + genuine holes;
    peri = (nib & (cv2.dilate(bg, ell(3)) > 0)).astype(np.uint8)   # noise specks were filled above
    if not peri.any(): peri = keep_big(nib, 0, 1)                   # part runs off the page

    rm = np.zeros(ink.shape, bool)
    if a.arrows:               # an arrow betrays itself outside the shape: fit that line and
        far = cv2.morphologyEx((ink & (sil == 0)).astype(np.uint8),   # open first: noise specks
                               cv2.MORPH_OPEN, ell(3))                # chain arrows into one blob
        m, lb, st, _ = cv2.connectedComponentsWithStats(far, 8)
        d = cv2.distanceTransform(ink.astype(np.uint8), cv2.DIST_L2, 3)
        wid = float(np.median(d[d > 0])) if (d > 0).any() else 1.0
        YY, XX = np.mgrid[0:ink.shape[0], 0:ink.shape[1]].astype(np.float32)
        for i in range(1, m):
            x, y, bw, bh, ar = st[i]
            if ar < a.arrow_out or max(bw, bh) < a.arrow_len or ar > .35 * bw * bh:
                continue                                            # keep it long and thin
            c = (lb == i).astype(np.uint8)
            if not (cv2.dilate(c, ell(2 * a.reach + 5)) & sil).any():
                continue                                # never reaches the shape, so never crosses it
            p = np.column_stack(np.nonzero(c)[::-1]).astype(np.float32)
            vx, vy, x0, y0 = cv2.fitLine(p, cv2.DIST_L2, 0, .01, .01).ravel()
            corr = max(6.0, 2 * float(np.median(d[lb == i])) + 3)
            sp = (p[:, 0] - x0) * vx + (p[:, 1] - y0) * vy         # its own span along the shaft
            rm |= ((np.abs((YY - y0) * vx - (XX - x0) * vy) <= corr) &
                   ((XX - x0) * vx + (YY - y0) * vy >= sp.min() - a.arrow_len) &
                   ((XX - x0) * vx + (YY - y0) * vy <= sp.max() + a.arrow_len) & (sil > 0))
        rm &= nib > 0
        if rm.any():                                    # the head travels with its shaft
            rm |= (d > 1.6 * wid) & (cv2.dilate(rm.astype(np.uint8), ell(31)) > 0) & (nib > 0)
        nib = (nib & ~rm).astype(np.uint8)

    grp = cv2.dilate(nib, ell(2 * a.link + 1)) if a.link else nib   # bridge hairline breaks
    n, lbl = cv2.connectedComponents(grp, connectivity=8)
    ok = np.zeros(n, bool); ok[np.unique(lbl[peri > 0])] = True; ok[0] = False
    line = (nib * ok[lbl]).astype(np.uint8)
    if a.mend and rm.any():                     # rejoin the outline only where an arrow cut it
        line |= (cv2.morphologyEx(line, cv2.MORPH_CLOSE, ell(a.mend)) &
                 (cv2.dilate(rm.astype(np.uint8), ell(a.mend)) > 0))                         # perimeter + interior edges
    fill = (sil & ~line.astype(bool)).astype(np.uint8)              # faces; rejected ink absorbed
    bad = (fill & ~tone0.astype(bool)).astype(np.uint8)             # absorbed ink / patched noise
    if bad.any(): img = cv2.inpaint(img, bad, 3, cv2.INPAINT_TELEA)  # take the surrounding face tone

    out = np.full_like(img, 255)
    if a.keep_tones:
        out[fill > 0] = img[fill > 0]
    elif a.tones > 1:                                               # keep the 3-D face shading
        px = img[fill > 0]
        v = np.ascontiguousarray(px, np.float32)
        lb = cv2.kmeans(v, min(a.tones, len(v)), None, CRIT, 3, cv2.KMEANS_PP_CENTERS)[1].ravel()
        for i in np.unique(lb): px[lb == i] = np.median(px[lb == i], 0)
        out[fill > 0] = px
    else:
        out[fill > 0] = cv2.cvtColor(np.float32([[t]]), cv2.COLOR_LAB2BGR)[0, 0] * 255
    out[line > 0] = 0
    return out

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument('inputs', nargs='+')
p.add_argument('-o', '--out', default='clean', help='output dir, or a .png for a single input')
p.add_argument('--box', help='X,Y,W,H around the shape: GrabCut away same-coloured background')
p.add_argument('--at', help="X,Y on the shape: takes its tone and keeps only that region")
p.add_argument('--color', help='hex target instead of auto-detecting the dominant colour')
p.add_argument('--hue-tol', type=float, default=14, help='hue degrees kept (default 14)')
p.add_argument('--min-chroma', type=float, default=8, help='below this, match on a/b distance')
p.add_argument('--no-arrows', dest='arrows', action='store_false', help='keep arrows/leaders')
p.add_argument('--arrow-out', type=int, default=40, help='px of ink outside the shape = an arrow')
p.add_argument('--mend', type=int, default=15, help='px of outline gap rejoined after a cut')
p.add_argument('--arrow-len', type=int, default=60, help='min length of an arrow shaft')
p.add_argument('--head', type=float, default=3.0, help='arrowhead = this x the stroke width')
p.add_argument('--chroma-tol', type=float, default=12, help='hue/chroma spread kept (default 12)')
p.add_argument('--light-tol', type=float, default=40, help='lightness spread kept (default 40)')
p.add_argument('--clusters', type=int, default=6)
p.add_argument('--lweight', type=float, default=.25, help='lightness weight in clustering')
p.add_argument('--ink', type=float, default=45, help='L* below this is outline ink')
p.add_argument('--paper', type=float, default=82, help='L* above this is background')
p.add_argument('--median', type=int, default=3)
p.add_argument('--bilateral', type=int, default=7, help='0 disables')
p.add_argument('--open', type=int, default=3)
p.add_argument('--close', type=int, default=5)
p.add_argument('--min-area', type=float, default=4e-4, help='<1 = fraction of the image')
p.add_argument('--fill-holes', type=float, default=2e-3,
               help='patch interior holes up to this size, <1 = fraction (0 disables)')
p.add_argument('--reach', type=int, default=3, help='px the outline may sit from the fill')
p.add_argument('--seal', type=int, default=15, help='px of thick ink absorbed into the shape')
p.add_argument('--link', type=int, default=2, help='px of gap an interior line may jump')
p.add_argument('--tones', type=int, default=1, help='quantise the fill to N tones (3-D shading)')
p.add_argument('--keep', type=int, default=0, help='keep only the N largest parts (0 = all)')
p.add_argument('--keep-tones', action='store_true', help='do not flatten the fill to one colour')
a = p.parse_args()

single = len(a.inputs) == 1 and a.out.lower().endswith('.png')
if not single: os.makedirs(a.out, exist_ok=True)
for src in a.inputs:
    dst = a.out if single else os.path.join(a.out, os.path.splitext(os.path.basename(src))[0] + '.png')
    cv2.imwrite(dst, clean(src, a))
    print(dst)
