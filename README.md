# vectorCleaning

Small tools for turning messy raster art into clean SVG.
`clean.py` → `trace.py` is a two-step pipeline; `extract_svgs.py` stands alone.

## Setup

```sh
./setup.sh      # macOS / Linux
.\setup.ps1     # Windows PowerShell
```

Each installs [uv](https://docs.astral.sh/uv/) if missing, then runs `uv sync`.
Prefix commands with `uv run`.

`trace.py` also wants the **potrace** binary (`brew install potrace` / `scoop install potrace`).
Without it, it falls back to vtracer, which uv installs.

---

## clean.py — isolate one shape from a noisy PNG

Picks the dominant colour and **every tone of it** (constant hue, any lightness or saturation),
keeps interior 3-D edges that reach the perimeter, strips arrows and leader lines, and writes a
flat PNG ready to trace.

```sh
uv run clean.py shot.png -o clean/              # batch; also takes *.png
uv run clean.py shot.png -o out.png --keep 1    # drawing is a single part
uv run clean.py iso.png  -o out.png --tones 3   # 3-D: keep 3 face tones
uv run clean.py render.png -o out.png --box 80,25,262,220 --tones 4 --ink 25   # shaded render
```

| flag | reach for it when |
|---|---|
| `--keep 1` | the drawing is one part |
| `--tones N` | 3-D shape — keep N face tones (default 1 = flat fill) |
| `--hue-tol` / `--light-tol` | it grabs a neighbouring hue / clips a shading gradient |
| `--color '#3b7ea1'` | you want to name the colour instead of auto-detecting |
| `--at X,Y` | keep only the region under a point |
| `--box X,Y,W,H` | background is the same colour as the shape (photos, renders) — GrabCut first |
| `--no-arrows` | arrows and leaders should be kept |
| `--smooth` | Gaussian sigma on the region border — fewer angle changes (default 2) |
| `--simplify` | Douglas-Peucker tolerance in px (default 1.5); DP keeps sharp corners, Visvalingam would round them |
| `--ink` | a shaded render (not line art): at the default 45 its shadows read as outlines — try 25 |
| `--outline` | `fill` = border + found lines (default), `ink` = found lines only, `tones` also contours every band |
| `--outline-width` | border thickness in px (default 3) |

Limit: an arrow lying *entirely* inside the shape isn't detected — it needs a portion outside.

## trace.py — cleaned PNG → SVG

One filled layer per tone (`tone0`, `tone1`, …) plus a black `ink` layer carrying the border and
any interior dividers and 3-D edges. Nothing paints a backdrop, so the background stays
transparent on every backend and every tone is separately selectable. The background is taken to
be whatever colour frames the image, not assumed to be white — a scan on off-white paper would
otherwise be traced as a big pale shape sitting behind everything (`--bg-tol`).

`clean.py` draws the border from the shape's own region edge, so it is closed by construction and
cannot come back broken. If a PNG arrives with no border drawn, `trace.py` adds one by stroking
the silhouette — a shape is never left bare. Only the silhouette is ever stroked: ringing each
tonal band as well makes the drawing read as a stencil.

```sh
uv run trace.py clean/shot.png -o shot.svg                  # smooth Bezier curves
uv run trace.py clean/shot.png -o shot.svg --backend polygon # fewest vertices
```

| flag | reach for it when |
|---|---|
| `--backend polygon` | you want minimum angle changes — DP polygons emitted directly, ~40x smaller, but faceted |
| `--eps` | polygon backend: Douglas-Peucker tolerance in px (default 2) |
| `--stroke` | outline width in px; default measures it from the cleaned PNG |
| `--alphamax` | potrace: 0 = polygons, >1.34 = fully smooth (default 1.0) |
| `--upscale` | supersample before tracing (default 2) |
| `--backend` | `auto` (potrace if present), `potrace`, `vtracer`, `polygon` |

potrace is dense by design (~4 px per Bezier segment) and no flag changes that, so the two
backends trade smooth curves against vertex count: on the flat test, 6714 points / 41 KB versus
174 points / 1.7 KB.

## extract_svgs.py — pull figures out of a PDF

Clusters the drawings on each page and writes every figure as its own SVG, staying vector-native.

```sh
uv run extract_svgs.py doc.pdf output 1-5
uv run extract_svgs.py doc.pdf output 3 --trace   # also vectorise embedded rasters
uv run extract_svgs.py fig.png output             # single raster -> traced SVG
```

Positional args: `<src> [out_dir] [pages]`. `src` may be `.pdf`, `.svg`, or an image.
