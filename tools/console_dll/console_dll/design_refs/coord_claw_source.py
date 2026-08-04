"""Claw shape, authored as cubic Bezier paths.

WHY BEZIERS AND NOT STACKED ELLIPSES
------------------------------------
Two previous attempts built the paw from overlapping ellipses and both read as
a blob with dots. An organic shape wants curves with control points.

It also solves the handoff: the shipping code is GDI in C, and GDI has
`PolyBezier`, which takes exactly these control points. So what is authored
here transfers 1:1 - no reinterpretation step where the look gets lost.

Curves are flattened here rather than handed to an SVG library, so the preview
is generated from the SAME numbers the C code will use.

GEOMETRY
--------
Three-quarter view, paw angled so the digits lead down-left and the back of the
paw is visible behind them. Authored in a 100x100 box; the ring maps it.
  - back mass  : upper right, the part you see "behind"
  - four digits: fanning down-left, separated by cut gaps so they read as
                 individual toes rather than one lobe
  - four claws : heavy, hooked, carrying the silhouette
"""
import math
import os
import re

from PIL import Image, ImageDraw

OUT = os.path.dirname(os.path.abspath(__file__))

# --- the shape -------------------------------------------------------------
# Back of the paw + the digit mass, one closed path.
PAW = """
M 58,14
C 74,16 88,28 90,44
C 92,58 86,68 76,73
C 70,76 64,77 58,77
C 52,78 46,78 40,76
C 33,74 27,69 24,62
C 21,55 22,46 27,38
C 33,26 45,13 58,14 Z
"""

# Digit separations - cut as background-coloured wedges over the paw mass.
GAPS = [
    "M 30,74 C 36,62 40,54 42,44 C 44,54 42,64 38,76 Z",
    "M 44,79 C 50,66 53,57 54,46 C 57,57 55,68 52,80 Z",
    "M 59,79 C 65,67 69,58 69,47 C 72,58 70,69 67,79 Z",
]

# Four claws. Each: a hooked wedge from the digit tip, tapering to a point.
CLAWS = [
    "M 26,64 C 20,72 14,80 8,88 C 12,78 15,70 20,60 C 23,60 25,62 26,64 Z",
    "M 39,77 C 35,86 31,94 27,99 C 29,89 31,81 34,73 C 36,74 38,75 39,77 Z",
    "M 53,80 C 51,89 49,96 46,100 C 47,90 48,82 49,75 C 51,76 52,78 53,80 Z",
    "M 67,79 C 67,87 66,93 64,98 C 64,89 64,82 63,75 C 65,76 66,77 67,79 Z",
]

# The furred/ragged back edge - short spikes along the upper right.
SPIKES = [(60, 13, 62, 4), (67, 14, 71, 5), (74, 17, 79, 9),
          (80, 22, 86, 16), (85, 28, 92, 24), (88, 35, 96, 33)]


def _bez(p0, p1, p2, p3, n=18):
    out = []
    for i in range(1, n + 1):
        t = i / float(n)
        u = 1 - t
        out.append((u * u * u * p0[0] + 3 * u * u * t * p1[0]
                    + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                    u * u * u * p0[1] + 3 * u * u * t * p1[1]
                    + 3 * u * t * t * p2[1] + t * t * t * p3[1]))
    return out


def flatten(dstr):
    """SVG path (M/C/Z only) -> list of points."""
    toks = re.findall(r"[MCZmcz]|-?\d+\.?\d*", dstr)
    pts, cur, i = [], (0, 0), 0
    while i < len(toks):
        t = toks[i]
        if t in "Mm":
            cur = (float(toks[i + 1]), float(toks[i + 2]))
            pts.append(cur)
            i += 3
        elif t in "Cc":
            p1 = (float(toks[i + 1]), float(toks[i + 2]))
            p2 = (float(toks[i + 3]), float(toks[i + 4]))
            p3 = (float(toks[i + 5]), float(toks[i + 6]))
            pts += _bez(cur, p1, p2, p3)
            cur = p3
            i += 7
        else:
            i += 1
    return pts


def xf(pts, cx, cy, scale, rot_deg=0.0):
    """100x100 design space -> screen, centred on (cx,cy), optional rotation."""
    a = math.radians(rot_deg)
    out = []
    for x, y in pts:
        dx, dy = (x - 50) * scale / 100.0, (y - 50) * scale / 100.0
        out.append((cx + dx * math.cos(a) - dy * math.sin(a),
                    cy + dx * math.sin(a) + dy * math.cos(a)))
    return out


def draw_claw(d, cx, cy, size, rot=0.0, bg=(14, 17, 25),
              body=(168, 180, 220), rim=(30, 36, 58), nail=(246, 250, 255)):
    """Rim first, then body, then gaps, then claws. Order is the whole trick."""
    paw = flatten(PAW)
    d.polygon(xf(paw, cx + size * 0.035, cy + size * 0.04, size, rot), fill=rim)
    d.polygon(xf(paw, cx, cy, size, rot), fill=body)
    for g in GAPS:
        d.polygon(xf(flatten(g), cx, cy, size, rot), fill=bg)
    for x0, y0, x1, y1 in SPIKES:
        p = xf([(x0, y0), (x1, y1)], cx, cy, size, rot)
        d.line(p, fill=body, width=max(1, int(size * 0.022)))
    for c in CLAWS:
        pts = flatten(c)
        d.polygon(xf(pts, cx + size * 0.02, cy + size * 0.02, size, rot),
                  fill=rim)
        d.polygon(xf(pts, cx, cy, size, rot), fill=nail)


def sheet():
    im = Image.new("RGB", (980, 300), (14, 17, 25))
    d = ImageDraw.Draw(im)
    # large, for shape; then at true HUD sizes to test legibility
    draw_claw(d, 150, 150, 240)
    for i, s in enumerate((96, 72, 56)):
        draw_claw(d, 380 + i * 150, 150, s)
    d.text((300, 265), "240px            96      72     56   (real ring is ~60)",
           fill=(120, 150, 180))
    im.save(os.path.join(OUT, "claw_sheet.png"))

    # a real .svg too, so it can be opened and edited directly
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">',
           '<rect width="100" height="100" fill="#0e1119"/>',
           '<path d="%s" fill="#a8b4dc"/>' % " ".join(PAW.split())]
    for g in GAPS:
        svg.append('<path d="%s" fill="#0e1119"/>' % " ".join(g.split()))
    for c in CLAWS:
        svg.append('<path d="%s" fill="#f6faff"/>' % " ".join(c.split()))
    svg.append("</svg>")
    open(os.path.join(OUT, "claw.svg"), "w").write("\n".join(svg))


sheet()
print("wrote claw_sheet.png and claw.svg")
