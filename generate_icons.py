"""Generate macOS template menu bar icons for cc-brain.
Template images: black on transparent. macOS handles light/dark automatically.

Strategy: Draw brain as a filled silhouette from overlapping ellipses,
then carve out the center line and fold lines in transparent."""

from PIL import Image, ImageDraw
import math


def draw_brain(img, size, color=(0, 0, 0, 255)):
    """Draw a brain silhouette using overlapping filled ellipses with carved details."""
    # Work on a larger canvas for antialiasing, then resize
    scale = 4
    big = size * scale
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)

    cx, cy = big / 2, big * 0.46
    s = big * 0.40

    # Fill the brain shape with overlapping ellipses
    # Left upper lobe
    d.ellipse([cx - s*1.05, cy - s*1.0, cx + s*0.1, cy + s*0.3], fill=color)
    # Right upper lobe
    d.ellipse([cx - s*0.1, cy - s*1.0, cx + s*1.05, cy + s*0.3], fill=color)
    # Left lower lobe
    d.ellipse([cx - s*0.85, cy - s*0.15, cx + s*0.08, cy + s*0.85], fill=color)
    # Right lower lobe
    d.ellipse([cx - s*0.08, cy - s*0.15, cx + s*0.85, cy + s*0.85], fill=color)

    # Brainstem
    stem_w = s * 0.22
    stem_top = cy + s * 0.55
    stem_bot = cy + s * 1.15
    d.polygon([
        (cx - stem_w, stem_top),
        (cx + stem_w, stem_top),
        (cx + stem_w * 0.4, stem_bot),
        (cx - stem_w * 0.4, stem_bot),
    ], fill=color)

    # Carve details using transparent lines
    clear = (0, 0, 0, 0)
    lw = max(2, round(big / 12))

    # Center line (vertical divide between hemispheres)
    d.line([cx, cy - s*0.85, cx, cy + s*0.5], fill=clear, width=lw)

    # Left hemisphere fold
    fold_cx = cx - s * 0.45
    fold_cy = cy - s * 0.05
    d.arc([fold_cx - s*0.35, fold_cy - s*0.25, fold_cx + s*0.35, fold_cy + s*0.25],
          start=20, end=160, fill=clear, width=lw)

    # Right hemisphere fold
    fold_cx = cx + s * 0.45
    d.arc([fold_cx - s*0.35, fold_cy - s*0.25, fold_cx + s*0.35, fold_cy + s*0.25],
          start=20, end=160, fill=clear, width=lw)

    # Resize down with antialiasing
    canvas = canvas.resize((size, size), Image.LANCZOS)

    # Composite onto the image
    img.paste(canvas, (0, 0), canvas)


def add_sync_badge(img, size):
    """Small filled dot in upper-right corner."""
    d = ImageDraw.Draw(img)
    r = max(2, round(size * 0.11))
    x = round(size * 0.82)
    y = round(size * 0.16)
    d.ellipse([x - r, y - r, x + r, y + r], fill=(0, 0, 0, 255))


def add_error_badge(img, size):
    """Filled dot with exclamation in upper-right corner."""
    d = ImageDraw.Draw(img)
    r = max(3, round(size * 0.14))
    x = round(size * 0.82)
    y = round(size * 0.16)
    d.ellipse([x - r, y - r, x + r, y + r], fill=(0, 0, 0, 255))
    # White exclamation
    lw = max(1, round(size / 18))
    d.line([x, y - r*0.45, x, y + r*0.1], fill=(255, 255, 255, 255), width=lw)
    dr = max(1, round(size * 0.025))
    d.ellipse([x - dr, y + r*0.35 - dr, x + dr, y + r*0.35 + dr], fill=(255, 255, 255, 255))


def generate(size, name, badge=None):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw_brain(img, size)
    if badge == "sync":
        add_sync_badge(img, size)
    elif badge == "error":
        add_error_badge(img, size)
    img.save(f"icons/{name}.png")
    print(f"  {name}.png ({size}x{size})")


if __name__ == "__main__":
    import os
    os.makedirs("icons", exist_ok=True)

    for size, suffix in [(18, ""), (36, "@2x")]:
        generate(size, f"brain-idle{suffix}")
        generate(size, f"brain-sync{suffix}", badge="sync")
        generate(size, f"brain-error{suffix}", badge="error")

    print("Done!")
