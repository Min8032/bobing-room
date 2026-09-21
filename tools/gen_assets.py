# -*- coding: utf-8 -*-
"""Generate wooden table, realistic red bowl, 3D dice, and roll sfx."""
import math
import os
import random
import struct
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

OUT = os.path.join(os.path.dirname(__file__), '..', 'assets')
os.makedirs(os.path.join(OUT, 'dice'), exist_ok=True)
os.makedirs(os.path.join(OUT, 'sfx'), exist_ok=True)


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    return tuple(int(lerp(c1[i], c2[i], t)) for i in range(3))


def gen_table():
    W, H = 720, 1280
    rng = np.random.default_rng(7)
    y = np.arange(H)[:, None].astype(np.float32)
    x = np.arange(W)[None, :].astype(np.float32)
    dark = np.array([128, 78, 42], dtype=np.float32)
    light = np.array([196, 142, 86], dtype=np.float32)
    # plank stripes (horizontal boards)
    plank = np.mod(y + 8 * np.sin(x / 90.0), 86)
    seam = np.exp(-((plank - 2) ** 2) / 4.0)  # dark seam between planks
    # grain along each plank
    n1 = rng.random((H, max(W // 10, 36))).astype(np.float32)
    n1 = np.repeat(n1, int(np.ceil(W / n1.shape[1])), axis=1)[:, :W]
    n1 = np.asarray(Image.fromarray((n1 * 255).astype(np.uint8), 'L').filter(
        ImageFilter.GaussianBlur(0.8))).astype(np.float32) / 255.0
    grain = 0.5 + 0.5 * np.sin((x / 14.0) + n1 * 9 + y / 40.0)
    t = np.clip(0.42 + 0.28 * n1 + 0.18 * grain - 0.28 * seam, 0, 1)
    rgb = dark + (light - dark) * t[..., None]
    vx = (x / W - 0.5) * 2
    vy = (y / H - 0.5) * 2
    vig = np.clip(1.0 - 0.16 * (vx * vx + vy * vy), 0.72, 1)
    rgb *= vig[..., None]
    img = Image.fromarray(rgb.clip(0, 255).astype(np.uint8), 'RGB')
    img.save(os.path.join(OUT, 'table.jpg'), quality=86)
    print('table.jpg')


def gen_bowl():
    """Look-into ceramic bowl: sharp rim, inner walls, large soft floor. No outer halo."""
    S = 900
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    cx, cy = S / 2.0, S / 2.0
    R = S * 0.478
    dx = (xx - cx) / R
    dy = (yy - cy) / R
    r = np.sqrt(dx * dx + dy * dy)
    nx = dx / np.maximum(r, 1e-4)
    ny = dy / np.maximum(r, 1e-4)
    ang = np.arctan2(ny, nx)

    # floor ellipse: slightly below center, ~58% of opening (room for 6 dice)
    bx, by = cx, cy + R * 0.06
    brx, bry = R * 0.58, R * 0.50
    fr = np.sqrt(((xx - bx) / brx) ** 2 + ((yy - by) / bry) ** 2)

    ndotl = np.clip(-nx * 0.48 - ny * 0.58, 0, 1)

    c_floor = np.array([236, 88, 70], dtype=np.float32)
    c_floor_edge = np.array([200, 48, 40], dtype=np.float32)
    c_wall = np.array([186, 32, 28], dtype=np.float32)
    c_wall_lit = np.array([220, 62, 50], dtype=np.float32)
    c_rim = np.array([228, 96, 78], dtype=np.float32)
    c_rim_hi = np.array([255, 176, 150], dtype=np.float32)

    rim_w = np.clip((r - 0.955) / 0.045, 0, 1)
    # soft floor membership (no hard egg outline)
    floor_w = np.clip(1.0 - fr, 0, 1)
    floor_w = floor_w * floor_w * (3 - 2 * floor_w)
    wall_w = np.clip(1.0 - floor_w - rim_w, 0, 1)

    floor_col = c_floor + (c_floor_edge - c_floor) * np.clip(fr, 0, 1)[..., None]
    wall_col = c_wall + (c_wall_lit - c_wall) * ndotl[..., None]
    rim_col = c_rim + (c_rim_hi - c_rim) * ndotl[..., None]
    rgb = floor_col * floor_w[..., None] + wall_col * wall_w[..., None] + rim_col * rim_w[..., None]

    # inner-wall glossy arc, upper-left
    spec_ang = np.exp(-((ang + 2.20) ** 2) / 0.48)
    spec_r = np.exp(-((r - 0.82) ** 2) / 0.012)
    rgb += (spec_ang * spec_r * wall_w * 110)[..., None]
    rgb = np.clip(rgb, 0, 255)

    # crisp disk; RGB zeroed outside so no colored halo
    alpha = np.clip((1.0 - r) * R * 3.2, 0, 255)
    rgb[alpha < 1] = 0
    out = np.dstack([rgb, alpha]).astype(np.uint8)
    Image.fromarray(out, 'RGBA').save(os.path.join(OUT, 'bowl.png'))
    print('bowl.png')


def draw_pips(draw, face, mapper, color, rad):
    spots = {
        1: [(0.50, 0.50)],
        2: [(0.30, 0.30), (0.70, 0.70)],
        3: [(0.30, 0.30), (0.50, 0.50), (0.70, 0.70)],
        4: [(0.30, 0.30), (0.70, 0.30), (0.30, 0.70), (0.70, 0.70)],
        5: [(0.30, 0.30), (0.70, 0.30), (0.50, 0.50), (0.30, 0.70), (0.70, 0.70)],
        6: [(0.30, 0.26), (0.30, 0.50), (0.30, 0.74),
            (0.70, 0.26), (0.70, 0.50), (0.70, 0.74)],
    }
    for u, v in spots[face]:
        x, y = mapper(u, v)
        draw.ellipse([x - rad, y - rad, x + rad, y + rad], fill=color)


def gen_dice():
    """Proper isometric cube: top diamond + two side parallelograms."""
    sides = {1: (2, 3), 2: (1, 3), 3: (1, 2), 4: (5, 2), 5: (6, 3), 6: (5, 4)}
    W, H = 240, 250
    # isometric metrics
    hw, hh, depth = 78, 39, 72
    ox, oy = W / 2.0, 52.0   # NORTH corner of top diamond

    def top_map(u, v):
        # u right-on-face → southeast; v down-on-face → southwest
        x = ox + u * hw - v * hw
        y = oy + u * hh + v * hh
        return x, y

    north = top_map(0.0, 0.0)
    east = top_map(1.0, 0.0)
    west = top_map(0.0, 1.0)
    south = top_map(1.0, 1.0)
    # drop the south/west/east corners down for side faces
    south_d = (south[0], south[1] + depth)
    west_d = (west[0], west[1] + depth)
    east_d = (east[0], east[1] + depth)

    def left_map(u, v):
        # left face: west→south (u), down (v)
        x = west[0] + (south[0] - west[0]) * u + (west_d[0] - west[0]) * v
        y = west[1] + (south[1] - west[1]) * u + (west_d[1] - west[1]) * v
        return x, y

    def right_map(u, v):
        x = east[0] + (south[0] - east[0]) * u + (east_d[0] - east[0]) * v
        y = east[1] + (south[1] - east[1]) * u + (east_d[1] - east[1]) * v
        return x, y

    c_top, c_left, c_right = (252, 250, 246), (188, 180, 172), (220, 214, 206)
    c_edge = (168, 162, 154)

    for n in range(1, 7):
        im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        lf, rf = sides[n]
        d.polygon([west, south, south_d, west_d], fill=c_left)
        d.polygon([east, south, south_d, east_d], fill=c_right)
        d.polygon([north, east, south, west], fill=c_top)
        d.line([north, east, south, west, north], fill=c_edge, width=2)
        d.line([south, south_d], fill=c_edge, width=2)
        d.line([west, west_d, south_d, east_d, east], fill=c_edge, width=2)

        red, black = (214, 40, 40), (40, 40, 42)
        draw_pips(d, n, top_map, red if n in (1, 4) else black, 9)
        draw_pips(d, lf, left_map, red if lf in (1, 4) else black, 6)
        draw_pips(d, rf, right_map, red if rf in (1, 4) else black, 6)

        shadow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.ellipse([ox - 78, H - 52, ox + 86, H - 8], fill=(0, 0, 0, 80))
        shadow = shadow.filter(ImageFilter.GaussianBlur(7))
        Image.alpha_composite(shadow, im).save(os.path.join(OUT, 'dice', '%d.png' % n))
    print('dice 1-6')


def gen_sfx():
    sr = 22050
    dur = 0.90
    n = int(sr * dur)
    samples = np.zeros(n, dtype=np.float32)
    rng = np.random.default_rng(21)

    def clack(t0, amp=0.5, f=1200.0, decay=55.0):
        length = int(0.055 * sr)
        start = int(t0 * sr)
        t = np.arange(length) / sr
        noise = rng.uniform(-1, 1, length) * np.exp(-t * decay * 1.4)
        tone = np.sin(2 * math.pi * f * t) * np.exp(-t * decay)
        click = np.sin(2 * math.pi * (f * 2.3) * t) * np.exp(-t * decay * 1.8) * 0.4
        burst = amp * (0.55 * noise + 0.35 * tone + click)
        end = min(start + length, n)
        samples[start:end] += burst[: end - start]

    # six dice hitting the bowl, slightly staggered
    for i in range(6):
        clack(0.02 + i * 0.032, amp=0.32 + float(rng.random()) * 0.18,
              f=850 + float(rng.random()) * 900, decay=48 + float(rng.random()) * 20)
    # bounces
    clack(0.30, 0.50, 1050, 42)
    clack(0.42, 0.38, 1280, 50)
    clack(0.54, 0.22, 1480, 58)
    clack(0.64, 0.12, 1600, 70)

    # soft bowl resonance
    t = np.arange(n) / sr
    bowl = 0.06 * np.sin(2 * math.pi * 220 * t) * np.exp(-t * 6)
    samples += bowl

    samples = np.clip(samples, -1, 1)
    pcm = (samples * 28000).astype(np.int16)
    path = os.path.join(OUT, 'sfx', 'roll.wav')
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    print('sfx/roll.wav')


if __name__ == '__main__':
    gen_table()
    gen_bowl()
    gen_dice()
    gen_sfx()
    print('done')
