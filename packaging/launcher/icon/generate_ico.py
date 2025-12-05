#!/usr/bin/env python3
"""
Generate ICO file from SVG for Windows application icon.
Requires: pip install pillow cairosvg
"""

import io
from pathlib import Path


def generate_ico():
    try:
        from PIL import Image
        import cairosvg
    except ImportError:
        print("Installing required packages...")
        import subprocess
        subprocess.run(["pip", "install", "pillow", "cairosvg"], check=True)
        from PIL import Image
        import cairosvg

    script_dir = Path(__file__).parent
    svg_path = script_dir / "yakulingo.svg"
    ico_path = script_dir / "yakulingo.ico"

    # Standard Windows icon sizes
    sizes = [256, 48, 32, 16]

    images = []
    for size in sizes:
        # Convert SVG to PNG at each size
        png_data = cairosvg.svg2png(
            url=str(svg_path),
            output_width=size,
            output_height=size
        )
        img = Image.open(io.BytesIO(png_data))
        # Ensure RGBA mode
        if img.mode != "RGBA":
            img = img.convert("RGBA")
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
