import sys
import base64
from pathlib import Path
import xml.etree.ElementTree as ET
import pymupdf
import vtracer
from pymupdf import mupdf

MARGIN = 6
GAP = 8
FRAME = 0.8
EDGE = 0.03
GROW = 0.05
SVG = "{http://www.w3.org/2000/svg}"
HREF = "{http://www.w3.org/1999/xlink}href"
ET.register_namespace("", SVG[1:-1])
ET.register_namespace("xlink", HREF[1:-5])


def _svg(page, clip):
    buf = mupdf.fz_new_buffer(1024)
    out = mupdf.FzOutput(buf)
    dev = mupdf.fz_new_svg_device(out, clip.width, clip.height, mupdf.FZ_SVG_TEXT_AS_PATH, 1)
    shift = mupdf.FzMatrix(1, 0, 0, 1, -clip.x0, -clip.y0)
    view = mupdf.FzRect(0, 0, clip.width, clip.height)
    mupdf.fz_run_display_list(page.get_displaylist().this, dev, shift, view, mupdf.FzCookie())
    mupdf.fz_close_device(dev)
    out.fz_close_output()
    return ET.fromstring(buf.fz_buffer_extract().decode())


def _drawings(page):
    w, h = page.rect.width, page.rect.height
    inner = page.rect + (w * EDGE, h * EDGE, -w * EDGE, -h * EDGE)
    return [d for d in page.get_drawings() if inner.contains(d["rect"]) and max(d["rect"].width / w, d["rect"].height / h) < FRAME]


def _growth(rect, box):
    return (rect | box).get_area() - rect.get_area()


def _with_text(page, clusters):
    grown = list(clusters)
    for word in page.get_text("words") if clusters else []:
        box = pymupdf.Rect(word[:4])
        i = min(range(len(clusters)), key=lambda i: _growth(clusters[i], box))
        if _growth(clusters[i], box) < clusters[i].get_area() * GROW:
            grown[i] |= box
    return grown


def _figures(page):
    clusters = page.cluster_drawings(drawings=_drawings(page), x_tolerance=GAP, y_tolerance=GAP)
    for rect in _with_text(page, clusters):
        yield (rect + (-MARGIN, -MARGIN, MARGIN, MARGIN)) & page.rect


def _cull(root):
    w, h = [float(v) for v in root.get("viewBox").split()[2:]]
    for parent in root.iter():
        for use in [e for e in parent if e.tag == SVG + "use"]:
            x, y = [float(v) for v in use.get("transform")[7:-1].split(",")[4:]]
            if not (-MARGIN <= x <= w + MARGIN and -MARGIN <= y <= h + MARGIN):
                parent.remove(use)
    return root


def _traced(png, size, transform, invert):
    pix = pymupdf.Pixmap(png)
    if invert:
        pix.invert_irect()
    out = vtracer.convert_raw_image_to_svg(pix.tobytes("png"), img_format="png", colormode="binary", mode="spline", filter_speckle=4, corner_threshold=60, path_precision=1)
    group = ET.Element(SVG + "g", transform=f"{transform} scale({size[0] / pix.width},{size[1] / pix.height})")
    group.extend(ET.fromstring(out).iter(SVG + "path"))
    return group


def _placement(root, image, holder):
    if holder.tag == SVG + "mask":
        return next(e for e in root.iter() if e.get("mask") == f"url(#{holder.get('id')})"), holder
    return next((e for e in root.iter(SVG + "use") if e.get(HREF) == f"#{image.get('id')}"), image), image


def _vectorize(root):
    parents = {child: parent for parent in root.iter() for child in parent}
    for image in list(root.iter(SVG + "image")):
        png = base64.b64decode(image.get(HREF).split(",", 1)[1])
        size = float(image.get("width")), float(image.get("height"))
        user, definition = _placement(root, image, parents[image])
        traced = _traced(png, size, user.get("transform", ""), definition is not image)
        parents[user][list(parents[user]).index(user)] = traced
        if definition is not user:
            parents[definition].remove(definition)
    return root


def _standalone(png):
    pix = pymupdf.Pixmap(png)
    root = ET.Element(SVG + "svg", viewBox=f"0 0 {pix.width} {pix.height}")
    root.append(_traced(png, (pix.width, pix.height), "", False))
    return root


def _pages(doc, spec):
    first, _, last = (spec or f"1-{len(doc)}").partition("-")
    return [doc[i - 1] for i in range(int(first), int(last or first) + 1)]


def _write(path, root):
    path.write_text(ET.tostring(root, encoding="unicode"))


def extract(pdf_path, out, pages=None, trace=False):
    out.mkdir(parents=True, exist_ok=True)
    for page in _pages(pymupdf.open(pdf_path), pages):
        for i, clip in enumerate(_figures(page), 1):
            root = _cull(_svg(page, clip))
            _write(out / f"page{page.number + 1}_fig{i}.svg", _vectorize(root) if trace else root)
    return out


def run(src, out_dir="output", pages=None, trace=False):
    src, out = Path(src), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if src.suffix == ".pdf":
        return extract(src, out / src.stem, pages, trace)
    root = _vectorize(ET.fromstring(src.read_text())) if src.suffix == ".svg" else _standalone(src.read_bytes())
    _write(out / f"{src.stem}.svg", root)
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--trace"]
    print(run(*args[:3], trace="--trace" in sys.argv))
