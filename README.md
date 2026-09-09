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
keeps the black outline plus interior 3-D edges that reach the perimeter, strips arrows and
leader lines, and writes a flat PNG ready to trace.

```sh
uv run clean.py shot.png -o clean/              # batch; also takes *.png
uv run clean.py shot.png -o out.png --keep 1    # drawing is a single part
uv run clean.py iso.png  -o out.png --tones 3   # 3-D: keep 3 face tones
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

Limit: an arrow lying *entirely* inside the shape isn't detected — it needs a portion outside.

## trace.py — cleaned PNG → SVG

Stacks bilevel layers: silhouette, one per extra tone, black outline on top.

```sh
uv run trace.py clean/shot.png -o shot.svg
uv run trace.py clean/*.png -o svg/ --backend vtracer
```

| flag | reach for it when |
|---|---|
| `--alphamax` | 0 = polygons, >1.34 = fully smooth (default 1.0) |
| `--upscale` | supersample before tracing (default 2) |
| `--backend` | `auto` (potrace if present), `potrace`, `vtracer` |

## extract_svgs.py — pull figures out of a PDF

Clusters the drawings on each page and writes every figure as its own SVG, staying vector-native.

```sh
uv run extract_svgs.py doc.pdf output 1-5
uv run extract_svgs.py doc.pdf output 3 --trace   # also vectorise embedded rasters
uv run extract_svgs.py fig.png output             # single raster -> traced SVG
```

Positional args: `<src> [out_dir] [pages]`. `src` may be `.pdf`, `.svg`, or an image.
