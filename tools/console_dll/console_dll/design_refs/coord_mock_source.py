"""Creature HUD mockup v2 - design sketchpad.

Changes from v1, all from the owner's direction:
  * colour is keyed to the HEALTH VALUE, not to position along the bar.
    100 = vivid orange, ~50 = vivid pink/magenta, 0 = deep purple.
  * the HP number is GONE.
  * segments are SKEWED parallelograms, not upright rectangles.
  * the bar ends in a chevron point rather than a cut corner.
  * the ring is BROKEN into arcs with gaps, double-walled.
  * a thin secondary bar sits under the main one.
  * the claw is rebuilt: heel back-right, four toes front-left, heavy nails.
"""
import math
import os

from PIL import Image, ImageDraw

S = 2
W, H = 1280 * S, 112 * S
OUT = os.path.dirname(os.path.abspath(__file__))

BG = (16, 20, 28)
CY = (120, 232, 255)
CY_DIM = (44, 96, 122)

PAD = (176, 186, 224)
PAD_RIM = (26, 30, 48)
PAD_HI = (232, 240, 255)
NAIL = (248, 250, 255)
NAIL_RIM = (18, 20, 34)

SEGS = 30
SKEW = 9 * S              # horizontal lean of each segment
CLAW_ROT = -45.0


def rot(px, py, cx, cy, deg):
    a = math.radians(deg)
    dx, dy = px - cx, py - cy
    return (cx + dx * math.cos(a) - dy * math.sin(a),
            cy + dx * math.sin(a) + dy * math.cos(a))


def ell(d, cx, cy, rx, ry, fill, rotdeg=0.0, steps=44):
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        pts.append(rot(cx + rx * math.cos(t), cy + ry * math.sin(t),
                       cx, cy, rotdeg))
    d.polygon(pts, fill=fill)


def health_ramp(hp):
    """Colour of the bar for a given health value. Orange = healthy."""
    stops = [(0.00, (70, 20, 120)),      # deep purple
             (0.25, (120, 30, 165)),     # purple
             (0.50, (232, 45, 165)),     # vivid pink / pink-purple
             (0.75, (255, 95, 110)),     # pink pushing to warm
             (1.00, (255, 150, 30))]     # vivid orange
    t = max(0.0, min(1.0, hp / 100.0))
    for i in range(len(stops) - 1):
        a, ca = stops[i]
        b, cb = stops[i + 1]
        if a <= t <= b:
            f = (t - a) / (b - a)
            return tuple(int(ca[j] + (cb[j] - ca[j]) * f) for j in range(3))
    return stops[-1][1]


def shade(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def arc_ring(d, cx, cy, r, width, gaps):
    """A ring broken into arcs. `gaps` is a list of (start_deg, end_deg) holes."""
    for a0 in range(0, 360, 2):
        a1 = a0 + 2
        mid = (a0 + a1) * 0.5
        if any(g0 <= mid <= g1 for g0, g1 in gaps):
            continue
        d.arc([cx - r, cy - r, cx + r, cy + r], a0, a1, fill=CY, width=width)


def draw_claw(d, cx, cy, R):
    """Panther paw, rotated so toes lead down-left and the heel shows behind."""
    # heel pad: wide, flat, set back up-right
    ha = math.radians(-42)
    hx = cx + math.cos(ha) * 15 * S
    hy = cy + math.sin(ha) * 15 * S
    for dx, dy, col in ((2.2 * S, 2.6 * S, PAD_RIM), (0, 0, PAD),
                        (-1.8 * S, -2.2 * S, PAD_HI)):
        ell(d, hx + dx, hy + dy, 19 * S, 13 * S, col, R - 20)

    # four toes on an arc leading down-left, with heavy curved nails
    for i, ang in enumerate((150, 116, 82, 48)):
        a = math.radians(ang)
        tx = cx + math.cos(a) * 26 * S
        ty = cy + math.sin(a) * 26 * S
        rr = (8.0, 10.0, 10.0, 8.0)[i] * S
        for dx, dy, col in ((1.5 * S, 1.8 * S, PAD_RIM), (0, 0, PAD),
                            (-1.3 * S, -1.5 * S, PAD_HI)):
            ell(d, tx + dx, ty + dy, rr, rr * 0.9, col, R)
        # nail: a curved wedge sweeping outward and hooking
        nl = 17 * S
        base = rr * 0.85
        p0 = (tx + math.cos(a + 0.34) * base, ty + math.sin(a + 0.34) * base)
        p1 = (tx + math.cos(a - 0.34) * base, ty + math.sin(a - 0.34) * base)
        tip = (tx + math.cos(a - 0.42) * nl, ty + math.sin(a - 0.42) * nl)
        bow = (tx + math.cos(a + 0.16) * nl * 0.80,
               ty + math.sin(a + 0.16) * nl * 0.80)
        poly = [p0, bow, tip, p1]
        d.polygon([(px + 1.4 * S, py + 1.6 * S) for px, py in poly],
                  fill=NAIL_RIM)
        d.polygon(poly, fill=NAIL)


def render(hp, path):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    cy = H * 0.50
    cx = 80 * S
    r_in = 42 * S
    r_out = 57 * S

    x0 = cx + r_out * 0.30
    x1 = W - 78 * S
    top = cy - 26 * S
    bot = cy + 16 * S
    tip = x1 + 30 * S                  # chevron point

    # ---- main bar frame: chevron right end, stepped top ------------------
    step_x = x0 + (x1 - x0) * 0.30
    frame = [(x0, top + 9 * S), (step_x, top + 9 * S), (step_x + 10 * S, top),
             (x1, top), (tip, (top + bot) * 0.5), (x1, bot), (x0, bot)]
    d.polygon(frame, fill=(11, 14, 21), outline=CY)

    # ---- skewed segments -------------------------------------------------
    base = health_ramp(hp)
    inner0, inner1 = x0 + 7 * S, x1 - 4 * S
    seg_w = (inner1 - inner0) / SEGS
    lit = int(round(SEGS * hp / 100.0))
    for i in range(SEGS):
        sx = inner0 + i * seg_w
        t_up = top + (9 * S if sx < step_x else 0) + 5 * S
        t_dn = bot - 5 * S
        # each segment leans right: a parallelogram
        quad = [(sx + SKEW, t_up), (sx + seg_w - 2.5 * S + SKEW, t_up),
                (sx + seg_w - 2.5 * S, t_dn), (sx, t_dn)]
        if i < lit:
            # deeper at the left of the filled run, full colour at the tip
            f = 0.55 + 0.45 * (i / max(1.0, lit - 1.0))
            d.polygon(quad, fill=shade(base, f))
        else:
            d.polygon(quad, fill=(28, 32, 44))

    # ---- thin secondary bar beneath --------------------------------------
    sy0, sy1 = bot + 6 * S, bot + 13 * S
    d.polygon([(x0 + 18 * S, sy0), (x1 - 40 * S, sy0),
               (x1 - 26 * S, (sy0 + sy1) * 0.5), (x1 - 40 * S, sy1),
               (x0 + 18 * S, sy1)], fill=(13, 17, 25), outline=CY_DIM)
    fillw = (x1 - 60 * S - x0 - 20 * S) * (hp / 100.0)
    d.rectangle([x0 + 20 * S, sy0 + 2 * S, x0 + 20 * S + fillw, sy1 - 2 * S],
                fill=shade(base, 0.65))

    # ---- diagonal tick accents above the step ----------------------------
    for k in range(4):
        tx = step_x + 26 * S + k * 11 * S
        d.line([(tx, top - 5 * S), (tx + 7 * S, top - 15 * S)],
               fill=CY_DIM, width=int(2.5 * S))

    # ---- broken double ring ----------------------------------------------
    arc_ring(d, cx, cy, r_out, int(3 * S),
             gaps=[(-18, 18), (70, 96), (160, 190), (250, 276)])
    arc_ring(d, cx, cy, r_in, int(2.5 * S), gaps=[(38, 58), (200, 224)])
    d.ellipse([cx - r_in + 3, cy - r_in + 3, cx + r_in - 3, cy + r_in - 3],
              fill=(13, 16, 24))

    draw_claw(d, cx, cy, CLAW_ROT)

    im.resize((W // S, H // S), Image.LANCZOS).save(
        os.path.join(OUT, path.replace(".png", "_1x.png")))
    im.save(os.path.join(OUT, path))


for hp in (100, 68, 34, 12):
    render(hp, "v2_%03d.png" % hp)

# stack them so all four states are visible at once
ims = [Image.open(os.path.join(OUT, "v2_%03d.png" % h))
       for h in (100, 68, 34, 12)]
sheet = Image.new("RGB", (1500, H * 4), BG)
for i, m in enumerate(ims):
    sheet.paste(m.crop((0, 0, 1500, H)), (0, i * H))
sheet.save(os.path.join(OUT, "v2_sheet.png"))
print("wrote v2_sheet.png (100 / 68 / 34 / 12)")
