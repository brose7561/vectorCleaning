#!/usr/bin/env python3
"""Vectorise a cleaned PNG (flat fill + black outline) to SVG.

potrace backend: stacked bilevel layers -- silhouette, one per extra fill tone, outline on top.
Smoothest curves and smallest files for CAD-style shapes.  vtracer backend: one colour pass.
    ./trace.py clean/part.png -o part.svg          ./trace.py clean/*.png -o svg/ --backend vtracer
"""
import argparse, os, re, shutil, subprocess, sys, tempfile
import cv2, numpy as np

def ell(k): return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k | 1, k | 1))

def potrace(mask, a, tmp, tag):
    if a.upscale > 1:                                              # supersample = smoother edges
        mask = (cv2.resize(mask * 255, None, fx=a.upscale, fy=a.upscale,
                           interpolation=cv2.INTER_CUBIC) >= 128).astype(np.uint8)
    src, dst = f'{tmp}/{tag}.pbm', f'{tmp}/{tag}.svg'
    with open(src, 'wb') as f:                                     # PBM P4: 1 = black = traced
        f.write(b'P4\n%d %d\n' % (mask.shape[1], mask.shape[0]))
        f.write(np.packbits(mask, axis=1).tobytes())
    subprocess.run(['potrace', '-b', 'svg', '--flat', '-a', str(a.alphamax), '-O', str(a.opt),
                    '-t', str(a.turdsize), '-z', a.turnpolicy, '-o', dst, src],
                   check=True, capture_output=True)
    return open(dst).read()

def vtracer(src, dst, a):
    try:                                          # the pip/uv package ships a module, not a binary
        import vtracer as vt
        return vt.convert_image_to_svg_py(src, dst, colormode='color', mode=a.mode,
                                          filter_speckle=a.speckle, color_precision=8,
                                          corner_threshold=a.corner, path_precision=3)
    except ImportError:
        pass
    exe = shutil.which('vtracer') or sys.exit('need potrace, or: uv add vtracer')
    h = subprocess.run([exe, '--help'], capture_output=True, text=True)
    h = h.stdout + h.stderr                                        # flags renamed in vtracer 1.0
    args = [exe, '-i', src, '-o', dst, '--mode', a.mode]
    for names, v in ((('--filter-speckle', '--filter_speckle'), a.speckle),
                     (('--color-precision', '--color_precision'), 8),
                     (('--corner-threshold', '--corner_threshold'), a.corner),
                     (('--path-precision', '--path_precision'), 3)):
        n = next((x for x in names if x in h), None)
        if n: args += [n, str(v)]
    subprocess.run(args, check=True)

def polygon_svg(masks, a, w, h, sw):
    """Emit Douglas-Peucker polygons straight to path data -- exact control of the vertex count,
    with none of the raster round-trip that makes potrace re-fit every pixel step."""
    body, strokes, n = [], [], 0
    for m, c, name in masks:
        cs, _ = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        d = []
        for ct in cs:
            if abs(cv2.contourArea(ct)) < a.turdsize ** 2: continue
            p = cv2.approxPolyDP(ct, a.eps, True)
            if len(p) < 3: continue
            n += len(p)
            d.append('M' + ' '.join(f'{x} {y}' for x, y in p[:, 0]) + 'Z')
        if d:
            body.append(f'<path id="{name}" d="{" ".join(d)}" fill="{c}" fill-rule="evenodd"/>')
            if name == 'base': strokes.append(' '.join(d))
    if sw > 0 and strokes:
        body.append(f'<g id="outline" fill="none" stroke="#000000" stroke-width="{sw:g}" '
                    f'stroke-linejoin="round">' +
                    ''.join(f'<path d="{d}"/>' for d in strokes) + '</g>')
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n' + '\n'.join(body) + '\n</svg>\n'), n

def trace(src, dst, a):
    img = cv2.imread(src, cv2.IMREAD_UNCHANGED)
    if img is None: sys.exit(f'cannot read {src}')
    if img.dtype == np.uint16: img = (img >> 8).astype(np.uint8)
    if a.backend == 'vtracer' or (a.backend == 'auto' and not shutil.which('potrace')):
        return vtracer(src, dst, a)
    h, w = img.shape[:2]
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img[:, :, :3]
    ink   = bgr.max(2) <= a.ink                                    # outline baked in by clean.py
    solid = (bgr.min(2) < a.paper).astype(np.uint8)                # everything not background
    d = cv2.distanceTransform(ink.astype(np.uint8), cv2.DIST_L2, 3)
    sw = max(2.0, 2 * float(np.percentile(d[d > 0], 85))) if (d > 0).any() else 2.0
    #  a shaded render carries no ink to measure, but it still needs its silhouette drawn
    if a.stroke >= 0: sw = a.stroke
    body = solid.astype(bool) & ~ink
    cols = np.zeros((0, 3), np.uint8)
    if body.any():                                                 # one layer per flat tone
        u, n = np.unique(bgr[body].reshape(-1, 3), axis=0, return_counts=True)
        cols = (u[np.argsort(-n)] if len(u) <= 32 else               # >32 = not quantised, use median
                np.median(bgr[body], 0).reshape(1, 3))[:a.max_tones]
    hx = lambda c: '#%02x%02x%02x' % (int(c[2]), int(c[1]), int(c[0]))
    reg = [(np.all(bgr == c, 2) & body).astype(np.uint8) for c in cols]   # the hairline separator
    #  keeps same-tone pieces apart, so interior dividers survive as their own contours
    masks = [(solid, hx(cols[0]) if len(cols) else '#808080', 'base')]
    masks += [(m, hx(c), f'tone{i}') for i, (m, c) in enumerate(zip(reg, cols)) if i]
    if ink.any():                       # real ink only: dividers and 3-D edges, drawn as fill
        masks += [(ink.astype(np.uint8), '#000000', 'ink')]

    if a.backend == 'polygon':
        svg, n = polygon_svg(masks, a, w, h, sw)
        open(dst, 'w').write(svg)
        return n

    with tempfile.TemporaryDirectory() as tmp:
        layers = [(potrace(m, a, tmp, name), c, name) for m, c, name in masks]
    vb = re.search(r'viewBox="([^"]+)"', layers[0][0])
    vb = vb.group(1) if vb else f'0 0 {w * a.upscale} {h * a.upscale}'
    out = [f'<?xml version="1.0" encoding="UTF-8"?>',
           f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="{vb}">']
    strokes = []
    for txt, c, name in layers:                                    # potrace's <g> keeps its transform
        gs = '\n'.join(re.sub(r'\s+(?:fill|stroke)="[^"]*"', '', g) for g in re.findall(r'<g\b.*?</g>', txt, re.S))
        if not gs.strip(): continue
        out.append(f'<g id="{name}" fill="{c}">\n{gs}\n</g>')
        if name == 'base': strokes.append(gs)
    if sw > 0 and strokes:      # the outline IS the fill boundary: stroke the very same paths, so
        u = sw * a.upscale * 10                 # it aligns exactly and cannot come back broken
        out.append(f'<g id="outline" fill="none" stroke="#000000" stroke-width="{u:g}" '
                   f'stroke-linejoin="round">\n' + '\n'.join(strokes) + '\n</g>')
    out.append('</svg>')
    open(dst, 'w').write('\n'.join(out) + '\n')

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument('inputs', nargs='+')
p.add_argument('-o', '--out', default='svg', help='output dir, or a .svg for a single input')
p.add_argument('--backend', choices=['auto', 'potrace', 'vtracer', 'polygon'], default='auto')
p.add_argument('--eps', type=float, default=2.0, help='polygon backend: Douglas-Peucker px')
p.add_argument('--alphamax', type=float, default=1.0, help='0 = polygons, >1.34 = all smooth')
p.add_argument('--opt', type=float, default=0.2, help='potrace curve-joining tolerance')
p.add_argument('--turdsize', type=int, default=2, help='drop specks up to N px')
p.add_argument('--turnpolicy', default='minority')
p.add_argument('--upscale', type=int, default=2, help='supersample before tracing')
p.add_argument('--ink', type=int, default=90, help='max channel value counted as outline')
p.add_argument('--paper', type=int, default=250, help='min channel value counted as background')
p.add_argument('--stroke', type=float, default=-1,
               help='outline width in px; -1 = measure it from the cleaned PNG, 0 = none')
p.add_argument('--max-tones', type=int, default=6, help='max flat fill tones to layer')
p.add_argument('--mode', default='spline', help='vtracer: spline|polygon|pixel')
p.add_argument('--speckle', type=int, default=4, help='vtracer speckle filter')
p.add_argument('--corner', type=int, default=60, help='vtracer corner threshold')
a = p.parse_args()

single = len(a.inputs) == 1 and a.out.lower().endswith('.svg')
if not single: os.makedirs(a.out, exist_ok=True)
for src in a.inputs:
    dst = a.out if single else os.path.join(a.out, os.path.splitext(os.path.basename(src))[0] + '.svg')
    trace(src, dst, a)
    print(dst)
