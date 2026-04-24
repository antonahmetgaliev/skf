"""
Generates speed-lines.gif — animated lens-flare glints on transparent background.
Two palette colours: near-white core + gold glow.
X-axis sinusoidal envelope gives elongated diamond / flare shape.
Lines are randomly distributed across the full canvas height.
"""
from PIL import Image
import math
import random

# ── canvas ───────────────────────────────────────────────────────────────────
WIDTH   = 1920
HEIGHT  = 1080

# ── animation ────────────────────────────────────────────────────────────────
FPS           = 30
LOOP_DURATION = 3.5          # longer cycle → easier to spread delays evenly
NUM_FRAMES    = int(FPS * LOOP_DURATION)
FRAME_MS      = int(1000 / FPS)

# ── palette ───────────────────────────────────────────────────────────────────
COL_CORE = (255, 252, 210)   # near-white, hot
COL_GLOW = (255, 195, 20)    # saturated gold

# ── lines ─────────────────────────────────────────────────────────────────────
# Seeded RNG so output is deterministic between runs
rng = random.Random(42)

NUM_LINES = 6
LINES = []
used_y = []
for i in range(NUM_LINES):
    # Spread lines across full height, avoid clumping (±8% exclusion zone)
    while True:
        y_frac = rng.uniform(0.04, 0.96)
        if all(abs(y_frac - u) > 0.08 for u in used_y):
            break
    used_y.append(y_frac)
    length = rng.randint(70, 160)
    delay  = i * (LOOP_DURATION / NUM_LINES) + rng.uniform(-0.1, 0.1)
    LINES.append((y_frac, length, delay % LOOP_DURATION))

# ── glow layers ───────────────────────────────────────────────────────────────
# (y_offset, peak_density, palette_index)
# Density is the peak at the centre of the x-envelope; tapers to 0 at edges.
GLOW_LAYERS = [
    ( 0, 0.98, 1),   # core  — solid bright line
    (-1, 0.70, 2),   # inner glow
    ( 1, 0.70, 2),
    (-2, 0.38, 2),   # mid glow
    ( 2, 0.38, 2),
    (-3, 0.16, 2),   # outer glow
    ( 3, 0.16, 2),
]

# Pixels with final density below this are skipped (avoids isolated dots)
MIN_DENSITY = 0.20

# ── helpers ───────────────────────────────────────────────────────────────────
TRANSPARENT_INDEX = 0

# Bayer 4×4 ordered dither
BAYER8 = [
    [ 0,  8,  2, 10],
    [12,  4, 14,  6],
    [ 3, 11,  1,  9],
    [15,  7, 13,  5],
]


def make_gif_frame(layers_map) -> Image.Image:
    """Build a palette GIF frame from a dict {(x,y): (density, pal_index)}."""
    palette_flat = [0] * (256 * 3)
    # index 0: transparent placeholder
    palette_flat[3:6]  = list(COL_CORE)   # index 1
    palette_flat[6:9]  = list(COL_GLOW)   # index 2

    idx_img = Image.new('P', (WIDTH, HEIGHT), color=TRANSPARENT_INDEX)
    idx_pix = idx_img.load()

    for (x, y), (density, pal_idx) in layers_map.items():
        threshold = BAYER8[y % 4][x % 4] / 16.0
        if density > threshold:
            idx_pix[x, y] = pal_idx

    idx_img.putpalette(palette_flat)
    return idx_img


def build_rgba_frame(t: float):
    """Return layers_map for time t — dict {(x,y): (density, pal_index)}."""
    layers_map = {}

    for y_frac, length, delay in LINES:
        y_center = int(y_frac * HEIGHT)

        t_adj    = (t - delay) % LOOP_DURATION
        progress = t_adj / LOOP_DURATION

        # Centre of the glint travels from off-left to off-right
        x_center = int(-length / 2 + progress * (WIDTH + length * 1.5))
        x_start  = x_center - length // 2
        x_end    = x_center + length // 2

        for y_off, peak_density, pal_idx in GLOW_LAYERS:
            y = y_center + y_off
            if y < 0 or y >= HEIGHT:
                continue

            span = max(x_end - x_start + 1, 1)

            for x in range(max(0, x_start), min(WIDTH, x_end + 1)):
                # sin^3 envelope: sharp falloff at tips, avoids sparse dots at edges
                t_x      = (x - x_start) / span
                sine_val = math.sin(t_x * math.pi)
                envelope = sine_val ** 3

                density = peak_density * envelope

                # Skip pixels that would render as isolated dots
                if density < MIN_DENSITY:
                    continue

                # Keep highest-density entry per pixel
                key = (x, y)
                if key not in layers_map or layers_map[key][0] < density:
                    layers_map[key] = (density, pal_idx)

    return layers_map


# ── render ────────────────────────────────────────────────────────────────────
print(f"Rendering {NUM_FRAMES} frames ({WIDTH}×{HEIGHT}px)…")

frames = []
for i in range(NUM_FRAMES):
    t = i / FPS
    lmap = build_rgba_frame(t)
    frames.append(make_gif_frame(lmap))



# ── render ────────────────────────────────────────────────────────────────────
print(f"Rendering {NUM_FRAMES} frames ({WIDTH}×{HEIGHT}px)…")

frames = []
for i in range(NUM_FRAMES):
    t = i / FPS
    lmap = build_rgba_frame(t)
    frames.append(make_gif_frame(lmap))

# ── save ──────────────────────────────────────────────────────────────────────
OUT = "speed-lines.gif"
frames[0].save(
    OUT,
    save_all=True,
    append_images=frames[1:],
    loop=0,
    duration=FRAME_MS,
    transparency=TRANSPARENT_INDEX,
    disposal=2,
)
print(f"Saved → {OUT}")
