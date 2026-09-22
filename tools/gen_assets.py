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


PIPS = {
    1: [(0.50, 0.50)],
    2: [(0.26, 0.26), (0.74, 0.74)],
    3: [(0.26, 0.26), (0.50, 0.50), (0.74, 0.74)],
    4: [(0.26, 0.26), (0.74, 0.26), (0.26, 0.74), (0.74, 0.74)],
    5: [(0.26, 0.26), (0.74, 0.26), (0.50, 0.50), (0.26, 0.74), (0.74, 0.74)],
    6: [(0.26, 0.22), (0.26, 0.50), (0.26, 0.78),
        (0.74, 0.22), (0.74, 0.50), (0.74, 0.78)],
}
def _sd_round_rect(x, y, hw, hh, rad):
    ax = np.abs(x) - hw + rad
    ay = np.abs(y) - hh + rad
    return np.hypot(np.maximum(ax, 0), np.maximum(ay, 0)) + np.minimum(np.maximum(ax, ay), 0) - rad


def _render_die_2d(face):
    """Kenney-style top-down tile: ivory plastic, crisp inset pips."""
    S = 512
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    cx = cy = (S - 1) * 0.5
    x = (xx - cx) / (S * 0.42)
    y = (yy - cy) / (S * 0.42)
    d = _sd_round_rect(x, y, 0.92, 0.92, 0.22)
    inside = d < 0
    edge = np.clip(1.0 - np.abs(d) / 0.055, 0, 1)

    eps = 0.004
    nx = _sd_round_rect(x + eps, y, 0.92, 0.92, 0.22) - _sd_round_rect(x - eps, y, 0.92, 0.92, 0.22)
    ny = _sd_round_rect(x, y + eps, 0.92, 0.92, 0.22) - _sd_round_rect(x, y - eps, 0.92, 0.92, 0.22)
    nlen = np.maximum(np.hypot(nx, ny), 1e-4)
    nx, ny = nx / nlen, ny / nlen
    light = np.clip(-nx * 0.55 - ny * 0.62, 0, 1)

    rng = np.random.default_rng(40 + face)
    grain = rng.random((S, S)).astype(np.float32)
    grain = np.asarray(Image.fromarray((grain * 255).astype(np.uint8), 'L').filter(
        ImageFilter.GaussianBlur(0.7))).astype(np.float32) / 255.0
    tex = 0.96 + 0.05 * grain + 0.025 * np.sin(xx / 7.0 + grain * 4)

    ivory = np.array([248, 239, 224], dtype=np.float32)
    shade = 0.90 + 0.10 * light
    gloss = np.clip(0.10 - 0.16 * ((x + 0.28) ** 2 + (y + 0.32) ** 2), 0, 1)
    rgb = ivory * (shade * tex)[..., None]
    rgb += gloss[..., None] * 46
    rgb *= (1.0 - edge * 0.22)[..., None]

    u = (x + 1) * 0.5
    v = (y + 1) * 0.5
    pip_r = 0.118 if face != 1 else 0.132
    pip = np.zeros((S, S), dtype=np.float32)
    for pu, pv in PIPS[face]:
        dist = np.hypot(u - pu, v - pv)
        pip = np.maximum(pip, np.clip((pip_r - dist) / 0.012, 0, 1))
    pip_col = np.array([196, 24, 28] if face in (1, 4) else [32, 26, 24], dtype=np.float32)
    well = np.clip(pip, 0, 1)
    rgb = rgb * (1 - well * 0.96)[..., None] + pip_col * (well * 0.96)[..., None]
    # tiny pip highlight
    hi = np.zeros((S, S), dtype=np.float32)
    for pu, pv in PIPS[face]:
        dist = np.hypot(u - pu + 0.018, v - pv + 0.018)
        hi = np.maximum(hi, np.clip(1.0 - dist / (pip_r * 0.38), 0, 1))
    rgb += (hi * well * 38)[..., None]

    a = np.clip(0.5 - d / 0.012, 0, 1)
    rgba = np.zeros((S, S, 4), dtype=np.float32)
    rgba[..., :3] = np.clip(rgb, 0, 255)
    rgba[..., 3] = a * 255
    die = Image.fromarray(rgba.astype(np.uint8), 'RGBA')

    canvas = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    sh = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    m = int(S * 0.10)
    sd.rounded_rectangle([m + 8, m + 18, S - m + 6, S - m + 14], radius=int(S * 0.16), fill=(0, 0, 0, 70))
    sh = sh.filter(ImageFilter.GaussianBlur(10))
    return Image.alpha_composite(sh, die)


def gen_dice():
    for n in range(1, 7):
        _render_die_2d(n).save(os.path.join(OUT, 'dice', '%d.png' % n))
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
