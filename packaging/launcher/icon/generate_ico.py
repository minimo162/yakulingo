#!/usr/bin/env python3
"""
Generate ICO file from SVG for Windows application icon.
Requires: pip install pillow svglib reportlab
"""

import io
from pathlib import Path


def generate_ico():
    from PIL import Image
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPM

    script_dir = Path(__file__).parent
    svg_path = script_dir / "yakulingo.svg"
    ico_path = script_dir / "yakulingo.ico"

    # Standard Windows icon sizes
    sizes = [256, 48, 32, 16]

    # Load SVG once
    drawing = svg2rlg(str(svg_path))
    if drawing is None:
        raise ValueError(f"Failed to load SVG: {svg_path}")

    # Get original size for scaling
    orig_width = drawing.width
    orig_height = drawing.height

    images = []
    for size in sizes:
        # Scale drawing to target size
        scale = size / max(orig_width, orig_height)
        drawing.width = size
        drawing.height = size
        drawing.scale(scale, scale)

        # Render to PNG bytes
        png_data = renderPM.drawToString(drawing, fmt="PNG")

        # Reset scale for next iteration
        drawing.scale(1/scale, 1/scale)
        drawing.width = orig_width
        drawing.height = orig_height

        img = Image.open(io.BytesIO(png_data))
        # Ensure RGBA mode
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        # Resize to exact size (in case of rounding issues)
        if img.size != (size, size):
            img = img.resize((size, size), Image.Resampling.LANCZOS)
        images.append(img)

    # Save as ICO with all sizes
    images[0].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:]
    )

    print(f"Generated: {ico_path}")
    print(f"Sizes: {sizes}")


if __name__ == "__main__":
    generate_ico()
