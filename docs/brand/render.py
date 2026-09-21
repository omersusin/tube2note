#!/usr/bin/env python3
"""tube2note brand mark renderer (PIL, no external assets).

Concept (Dark Developer mode): a play triangle fused with transcript lines —
YouTube video in, text out. Charcoal tile, signal-red play, off-white lines.
"""
from PIL import Image, ImageDraw, ImageFont

TILE = "#161a22"
RED = "#d92d20"
INK = "#e8ecf1"
MUT = "#8b95a5"
FONT = "/system/fonts/DroidSans.ttf"


def mark(d, s, ox=0, oy=0):
    """Draw the mark in an s×s box at offset. Pure geometry, scales clean."""
    u = s / 512
    # play triangle
    d.polygon([(ox + 176 * u, oy + 132 * u), (ox + 176 * u, oy + 312 * u),
               (ox + 348 * u, oy + 222 * u)], fill=RED)
    # transcript lines
    for i, (y, x1, x2, col) in enumerate([(356, 116, 396, INK), (396, 116, 396, MUT),
                                          (436, 116, 316, MUT)]):
        d.rounded_rectangle([ox + x1 * u, oy + y * u, ox + x2 * u, oy + (y + 22) * u],
                            radius=11 * u, fill=col)


def tile(size, bg=TILE, radius=None, pad=0):
    img = Image.new("RGB", (size, size), bg)
    d = ImageDraw.Draw(img)
    mark(d, size - 2 * pad, pad, pad)
    return img


def main():
    import os
    os.makedirs("docs/brand", exist_ok=True)
    # canonical mark: charcoal tile + red play + transcript lines
    for name, size in [("docs/icon-192.png", 192), ("docs/icon-512.png", 512)]:
        tile(size, bg=TILE).save(name)
    maskable = Image.new("RGB", (512, 512), TILE)  # safe-zone padding for maskable
    md = ImageDraw.Draw(maskable)
    mark(md, 340, 86, 86)
    maskable.save("docs/icon-maskable-512.png")
    # tauri icons
    tile(512, bg=TILE).save("src-tauri/icons/icon.png")
    tile(512, bg=TILE).save("src-tauri/icons/icon.ico",
                            sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    try:
        tile(512, bg=TILE).save("src-tauri/icons/icon.icns")
    except Exception as e:
        print("icns skip:", e)
    # favicon
    tile(64, bg=TILE).save("docs/favicon-64.png")
    board()
    print("brand done")


def board():
    """Concept board: logo, construction, palette, sizes, tagline."""
    W, H = 1600, 1000
    bg = Image.new("RGB", (W, H), "#0d1017")
    d = ImageDraw.Draw(bg)
    f_big = ImageFont.truetype(FONT, 64)
    f_med = ImageFont.truetype(FONT, 34)
    f_small = ImageFont.truetype(FONT, 26)
    # 1. logo cover
    logo = tile(420, bg=TILE, radius=92)
    bg.paste(logo, (80, 90))
    d.text((80, 540), "tube2note", font=f_big, fill=INK)
    d.text((80, 620), "YouTube to Markdown", font=f_med, fill=MUT)
    # 2. construction (grid + geometry)
    cx = 640
    cons = tile(420, bg="#11141b", radius=0)
    cd = ImageDraw.Draw(cons)
    for gx in range(0, 421, 42):
        cd.line([(gx, 0), (gx, 420)], fill="#232a36")
        cd.line([(0, gx), (420, gx)], fill="#232a36")
    cd.ellipse([176 - 130, 222 - 130, 176 + 130, 222 + 130], outline=RED, width=3)
    mark(cd, 420)
    bg.paste(cons, (cx, 90))
    d.text((cx, 540), "construction: play + 3 lines on 42px grid", font=f_small, fill=MUT)
    # 3. palette
    px = 1120
    for i, (name, col) in enumerate([("charcoal", TILE), ("signal red", RED),
                                     ("ink", INK), ("muted", MUT)]):
        y = 90 + i * 110
        d.rounded_rectangle([px, y, px + 90, y + 80], radius=12, fill=col)
        d.text((px + 110, y + 20), name, font=f_med, fill=INK)
        d.text((px + 110, y + 58), col, font=f_small, fill=MUT)
    # 4. sizes row
    sy = 780
    d.text((80, sy - 50), "scales: 128 / 64 / 32 / 16", font=f_small, fill=MUT)
    x = 80
    for s in (128, 64, 32, 16):
        bg.paste(tile(s, bg=TILE, radius=max(3, int(s * 0.22))), (x, sy))
        x += s + 30
    d.text((80, 930), "tube2note brand v1 — dark developer / builder", font=f_small, fill=MUT)
    bg.save("docs/brand/board.png")


if __name__ == "__main__":
    main()
