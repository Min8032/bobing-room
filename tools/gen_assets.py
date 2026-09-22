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
    2: [(0.28, 0.28), (0.72, 0.72)],
    3: [(0.28, 0.28), (0.50, 0.50), (0.72, 0.72)],
    4: [(0.28, 0.28), (0.72, 0.28), (0.28, 0.72), (0.72, 0.72)],
    5: [(0.28, 0.28), (0.72, 0.28), (0.50, 0.50), (0.28, 0.72), (0.72, 0.72)],
    6: [(0.28, 0.24), (0.28, 0.50), (0.28, 0.76),
        (0.72, 0.24), (0.72, 0.50), (0.72, 0.76)],
}
# top -> (front, right); opposites sum to 7
FACE_TRIPLE = {
    1: (2, 3), 2: (3, 1), 3: (5, 1),
    4: (2, 6), 5: (4, 3), 6: (5, 4),
}


def _rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float32)


def _rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float32)


def _sd_round_box(p, b, rad):
    q = np.abs(p) - b
    outside = np.linalg.norm(np.maximum(q, 0.0), axis=-1)
    inside = np.minimum(np.maximum(q[..., 0], np.maximum(q[..., 1], q[..., 2])), 0.0)
    return outside + inside - rad


def _pip_mask(u, v, face):
    m = np.zeros(u.shape, dtype=np.float32)
    for pu, pv in PIPS[face]:
        d = np.sqrt((u - pu) ** 2 + (v - pv) ** 2)
        m = np.maximum(m, np.clip(1.0 - d / 0.128, 0, 1))
    return m


def _render_die(top):
    """Raymarched rounded cube: glossy ivory, red 1/4, recessed pips."""
    front, right = FACE_TRIPLE[top]
    SS, W, H = 2, 280, 300
    sw, sh = W * SS, H * SS
    half = np.array([0.72, 0.72, 0.72], dtype=np.float32)
    rad = 0.17
    R = _rot_x(math.radians(-38)) @ _rot_y(math.radians(28))
    Rt = R.T

    xs = np.linspace(-1.12, 1.12, sw, dtype=np.float32)
    ys = np.linspace(1.22, -1.28, sh, dtype=np.float32)
    xx, yy = np.meshgrid(xs, ys)
    cam = np.array([0.0, 0.15, 3.55], dtype=np.float32)
    dirs = np.stack([xx, yy, np.full_like(xx, -3.15)], axis=-1)
    dirs /= np.linalg.norm(dirs, axis=-1, keepdims=True)

    t = np.full((sh, sw), 2.15, dtype=np.float32)
    alive = np.ones((sh, sw), dtype=bool)
    for _ in range(30):
        p = cam + dirs * t[..., None]
        d = _sd_round_box(p @ Rt, half, rad)
        t = np.where(alive, t + d, t)
        alive &= (d > 0.0018) & (t < 7.5)

    hit = t < 7.4
    p = cam + dirs * t[..., None]
    po = p @ Rt
    eps = 0.004
    n = np.stack([
        _sd_round_box((p + [eps, 0, 0]) @ Rt, half, rad) - _sd_round_box((p - [eps, 0, 0]) @ Rt, half, rad),
        _sd_round_box((p + [0, eps, 0]) @ Rt, half, rad) - _sd_round_box((p - [0, eps, 0]) @ Rt, half, rad),
        _sd_round_box((p + [0, 0, eps]) @ Rt, half, rad) - _sd_round_box((p - [0, 0, eps]) @ Rt, half, rad),
    ], axis=-1)
    n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-5)

    ax = np.abs(po)
    face_id = np.argmax(ax, axis=-1)
    sign = np.take_along_axis(po, face_id[..., None], -1)[..., 0]
    u = np.zeros((sh, sw), dtype=np.float32)
    v = np.zeros((sh, sw), dtype=np.float32)
    # x-face: u=y v=z ; y-face: u=x v=z ; z-face: u=x v=y
    fx, fy, fz = face_id == 0, face_id == 1, face_id == 2
    u = np.where(fx, (po[..., 1] / half[1] + 1) * 0.5, u)
    v = np.where(fx, (po[..., 2] / half[2] + 1) * 0.5, v)
    u = np.where(fy, (po[..., 0] / half[0] + 1) * 0.5, u)
    v = np.where(fy, (po[..., 2] / half[2] + 1) * 0.5, v)
    u = np.where(fz, (po[..., 0] / half[0] + 1) * 0.5, u)
    v = np.where(fz, (po[..., 1] / half[1] + 1) * 0.5, v)

    # After Ry then Rx: +Z mostly top, +X right, -Y front
    # After this camera, +Y is the visible top, +Z the front, +X the right
    face_n = np.zeros((sh, sw), dtype=np.int32)
    face_n = np.where(fy & (sign > 0), top, face_n)
    face_n = np.where(fy & (sign < 0), 7 - top, face_n)
    face_n = np.where(fz & (sign > 0), front, face_n)
    face_n = np.where(fz & (sign < 0), 7 - front, face_n)
    face_n = np.where(fx & (sign > 0), right, face_n)
    face_n = np.where(fx & (sign < 0), 7 - right, face_n)

    pip = np.zeros((sh, sw), dtype=np.float32)
    pip_red = np.zeros((sh, sw), dtype=bool)
    for fn in range(1, 7):
        sel = face_n == fn
        if not np.any(sel):
            continue
        pm = _pip_mask(u, v, fn)
        pip = np.where(sel, pm, pip)
        if fn in (1, 4):
            pip_red |= sel & (pm > 0.25)

    ivory = np.array([252, 246, 236], dtype=np.float32)
    L = np.array([0.42, 0.22, 0.88], dtype=np.float32)
    L /= np.linalg.norm(L)
    V = -dirs
    diff = np.clip(np.sum(n * L, axis=-1), 0, 1)
    halfv = V + L
    halfv /= np.maximum(np.linalg.norm(halfv, axis=-1, keepdims=True), 1e-5)
    spec = np.clip(np.sum(n * halfv, axis=-1), 0, 1) ** 42
    wrap = 0.38 + 0.62 * diff
    rgb = ivory * wrap[..., None]
    rgb += spec[..., None] * 95
    # face AO: slightly darker sides
    rgb *= np.where(fz, 1.0, np.where(fx, 0.86, 0.78))[..., None]

    red = np.array([212, 28, 30], dtype=np.float32)
    black = np.array([28, 24, 22], dtype=np.float32)
    pip_col = np.where(pip_red[..., None], red, black)
    k = np.clip(pip, 0, 1)[..., None]
    rgb = rgb * (1 - k * 0.92) + pip_col * (k * 0.92)
    rgb += (pip * spec * 40)[..., None]

    a = hit.astype(np.float32)
    rgba = np.zeros((sh, sw, 4), dtype=np.float32)
    rgba[..., :3] = np.clip(rgb, 0, 255)
    rgba[..., 3] = a * 255
    im = Image.fromarray(rgba.astype(np.uint8), 'RGBA').resize((W, H), Image.Resampling.LANCZOS)

    shadow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse([W * 0.22, H * 0.78, W * 0.80, H * 0.96], fill=(0, 0, 0, 78))
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    return Image.alpha_composite(shadow, im)


def gen_dice():
    for n in range(1, 7):
        _render_die(n).save(os.path.join(OUT, 'dice', '%d.png' % n))
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
