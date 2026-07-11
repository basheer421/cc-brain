"""Convert Phosphor Icons brain SVGs to macOS menu bar template PNGs.
Two states: filled (active/syncing) and outline (idle/error).
Black on transparent — macOS handles light/dark via template mode."""

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw

ICONS_DIR = Path(__file__).parent / "icons"


def _parse_svg_paths(svg_file):
    tree = ET.parse(svg_file)
    root = tree.getroot()
    ns = {"svg": "http://www.w3.org/2000/svg"}
    paths = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "path" and "d" in elem.attrib:
            paths.append(elem.attrib["d"])
    return paths


def _svg_to_png(svg_file, output_path, size):
    """Render SVG to PNG at target size using cairosvg if available, else Pillow."""
    try:
        import cairosvg
        cairosvg.svg2png(
            url=str(svg_file),
            write_to=str(output_path),
            output_width=size,
            output_height=size,
        )
        # cairosvg renders with currentColor — need to make it black on transparent
        img = Image.open(output_path).convert("RGBA")
        # Replace any color with black, keep alpha
        pixels = img.load()
        for y in range(img.height):
            for x in range(img.width):
                r, g, b, a = pixels[x, y]
                if a > 0:
                    pixels[x, y] = (0, 0, 0, a)
        img.save(output_path)
        return True
    except ImportError:
        pass
    return False


def _svg_to_png_pillow(svg_file, output_path, size, padding_pct=0.1):
    """Fallback: rasterize SVG path data using Pillow.
    Parses the SVG path 'd' attribute and draws filled paths."""
    from PIL.ImageDraw import Draw

    # Parse path commands from SVG
    svg_content = Path(svg_file).read_text()
    # Extract path d attributes
    d_matches = re.findall(r'd="([^"]+)"', svg_content)
    if not d_matches:
        print(f"  WARNING: No paths found in {svg_file}")
        return

    # Use a large render size then downscale for antialiasing
    render = size * 8
    padding = int(render * padding_pct)
    canvas = Image.new("RGBA", (render, render), (0, 0, 0, 0))

    # Parse SVG viewBox for coordinate mapping
    vb_match = re.search(r'viewBox="([^"]+)"', svg_content)
    if vb_match:
        vb = list(map(float, vb_match.group(1).split()))
    else:
        vb = [0, 0, 256, 256]

    scale = (render - 2 * padding) / max(vb[2], vb[3])
    ox, oy = padding - vb[0] * scale, padding - vb[1] * scale

    for d in d_matches:
        points = _parse_path_to_points(d, scale, ox, oy)
        if len(points) >= 3:
            draw = Draw(canvas)
            draw.polygon(points, fill=(0, 0, 0, 255))

    img = canvas.resize((size, size), Image.LANCZOS)
    img.save(output_path)


def _parse_path_to_points(d, scale, ox, oy):
    """Minimal SVG path parser — handles M, L, C, Z, Q, A and relative variants.
    Returns a list of (x, y) points sampled from the path."""
    points = []
    cx, cy = 0, 0
    sx, sy = 0, 0  # subpath start

    tokens = re.findall(r'[MmLlHhVvCcSsQqTtAaZz]|[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', d)

    i = 0
    cmd = 'M'

    def num():
        nonlocal i
        if i < len(tokens):
            val = float(tokens[i])
            i += 1
            return val
        return 0

    def add(x, y):
        nonlocal cx, cy
        cx, cy = x, y
        points.append((x * scale + ox, y * scale + oy))

    while i < len(tokens):
        t = tokens[i]
        if t.isalpha():
            cmd = t
            i += 1
        # Otherwise repeat previous command

        if cmd == 'M':
            add(num(), num())
            sx, sy = cx, cy
            cmd = 'L'
        elif cmd == 'm':
            add(cx + num(), cy + num())
            sx, sy = cx, cy
            cmd = 'l'
        elif cmd == 'L':
            add(num(), num())
        elif cmd == 'l':
            add(cx + num(), cy + num())
        elif cmd == 'H':
            add(num(), cy)
        elif cmd == 'h':
            add(cx + num(), cy)
        elif cmd == 'V':
            add(cx, num())
        elif cmd == 'v':
            add(cx, cy + num())
        elif cmd in ('C', 'c'):
            rel = cmd == 'c'
            for _ in range(3):
                dx, dy = num(), num()
                if rel:
                    dx += cx; dy += cy
                # Only add the endpoint (3rd pair)
            add(dx, dy)
        elif cmd in ('S', 's'):
            rel = cmd == 's'
            for _ in range(2):
                dx, dy = num(), num()
                if rel:
                    dx += cx; dy += cy
            add(dx, dy)
        elif cmd in ('Q', 'q'):
            rel = cmd == 'q'
            for _ in range(2):
                dx, dy = num(), num()
                if rel:
                    dx += cx; dy += cy
            add(dx, dy)
        elif cmd in ('T', 't'):
            dx, dy = num(), num()
            if cmd == 't':
                dx += cx; dy += cy
            add(dx, dy)
        elif cmd in ('A', 'a'):
            for _ in range(5):
                num()  # rx, ry, rotation, large-arc, sweep
            dx, dy = num(), num()
            if cmd == 'a':
                dx += cx; dy += cy
            add(dx, dy)
        elif cmd in ('Z', 'z'):
            add(sx, sy)
        else:
            i += 1

    return points


def generate(svg_file, output_name, size):
    output_path = ICONS_DIR / f"{output_name}.png"
    if not _svg_to_png(svg_file, output_path, size):
        _svg_to_png_pillow(svg_file, output_path, size)
    print(f"  {output_name}.png ({size}x{size})")


if __name__ == "__main__":
    # Try cairosvg first for best quality
    try:
        import cairosvg
        print("Using cairosvg for rendering")
    except ImportError:
        print("cairosvg not found, using Pillow fallback (install cairosvg for better quality)")

    outline_svg = ICONS_DIR / "brain-outline.svg"
    fill_svg = ICONS_DIR / "brain-fill.svg"

    # Remove old generated PNGs
    for f in ICONS_DIR.glob("*.png"):
        f.unlink()

    for size, suffix in [(18, ""), (36, "@2x")]:
        generate(outline_svg, f"brain-idle{suffix}", size)
        generate(fill_svg, f"brain-active{suffix}", size)

    print("Done!")
