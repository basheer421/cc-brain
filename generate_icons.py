"""Generate macOS template menu bar icons for cc-brain.
Two states: filled brain (active/syncing) and outline brain (idle/error).
Black on transparent — macOS handles light/dark via template mode."""

from PIL import Image, ImageDraw


def _brain_filled(d, big, color=(0, 0, 0, 255)):
    """Solid filled brain silhouette."""
    cx, cy = big / 2, big * 0.44
    s = big * 0.38

    # Two upper lobes
    d.ellipse([cx - s*1.05, cy - s*1.05, cx + s*0.1, cy + s*0.25], fill=color)
    d.ellipse([cx - s*0.1, cy - s*1.05, cx + s*1.05, cy + s*0.25], fill=color)
    # Two lower lobes
    d.ellipse([cx - s*0.85, cy - s*0.15, cx + s*0.08, cy + s*0.85], fill=color)
    d.ellipse([cx - s*0.08, cy - s*0.15, cx + s*0.85, cy + s*0.85], fill=color)
    # Brainstem
    sw = s * 0.2
    d.polygon([
        (cx - sw, cy + s*0.55), (cx + sw, cy + s*0.55),
        (cx + sw*0.35, cy + s*1.15), (cx - sw*0.35, cy + s*1.15),
    ], fill=color)

    # Carve center line and folds
    clear = (0, 0, 0, 0)
    lw = max(2, round(big / 14))
    d.line([cx, cy - s*0.9, cx, cy + s*0.45], fill=clear, width=lw)
    for sign in [-1, 1]:
        fcx = cx + sign * s * 0.45
        fcy = cy - s * 0.05
        d.arc([fcx - s*0.3, fcy - s*0.22, fcx + s*0.3, fcy + s*0.22],
              start=15, end=165, fill=clear, width=lw)


def _brain_outline(d, big, color=(0, 0, 0, 255)):
    """Outline-only brain — same shape, stroked instead of filled."""
    cx, cy = big / 2, big * 0.44
    s = big * 0.38
    lw = max(2, round(big / 11))

    # Upper lobes
    d.arc([cx - s*1.05, cy - s*1.05, cx + s*0.1, cy + s*0.25],
          start=135, end=15, fill=color, width=lw)
    d.arc([cx - s*0.1, cy - s*1.05, cx + s*1.05, cy + s*0.25],
          start=165, end=45, fill=color, width=lw)
    # Lower lobes
    d.arc([cx - s*0.85, cy - s*0.15, cx + s*0.08, cy + s*0.85],
          start=180, end=10, fill=color, width=lw)
    d.arc([cx - s*0.08, cy - s*0.15, cx + s*0.85, cy + s*0.85],
          start=170, end=0, fill=color, width=lw)

    # Center line
    d.line([cx, cy - s*0.9, cx, cy + s*0.45], fill=color, width=lw)

    # Folds
    for sign in [-1, 1]:
        fcx = cx + sign * s * 0.45
        fcy = cy - s * 0.05
        d.arc([fcx - s*0.3, fcy - s*0.22, fcx + s*0.3, fcy + s*0.22],
              start=15, end=165, fill=color, width=lw)

    # Brainstem
    sw = s * 0.2
    d.line([cx - sw, cy + s*0.55, cx - sw*0.35, cy + s*1.15], fill=color, width=lw)
    d.line([cx + sw, cy + s*0.55, cx + sw*0.35, cy + s*1.15], fill=color, width=lw)
    d.line([cx - sw*0.35, cy + s*1.15, cx + sw*0.35, cy + s*1.15], fill=color, width=lw)


def generate(size, name, style="filled"):
    scale = 4
    big = size * scale
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)

    if style == "filled":
        _brain_filled(d, big)
    else:
        _brain_outline(d, big)

    img = canvas.resize((size, size), Image.LANCZOS)
    img.save(f"icons/{name}.png")
    print(f"  {name}.png ({size}x{size})")


if __name__ == "__main__":
    import os
    os.makedirs("icons", exist_ok=True)

    # Remove old icons
    for f in os.listdir("icons"):
        if f.endswith(".png"):
            os.remove(f"icons/{f}")

    for size, suffix in [(18, ""), (36, "@2x")]:
        generate(size, f"brain-active{suffix}", style="filled")
        generate(size, f"brain-idle{suffix}", style="outline")

    print("Done!")
