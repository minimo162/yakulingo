#!/usr/bin/env python3
"""
Generate ICO file for Windows application icon.
Requires: pip install pillow
"""

from pathlib import Path


def generate_ico():
    from PIL import Image, ImageDraw

    script_dir = Path(__file__).parent
    ico_path = script_dir / "yakulingo.ico"

    # Brand color (from styles.py)
    BRAND_COLOR = (67, 85, 185, 255)  # #4355B9
    WHITE = (255, 255, 255, 255)

    # Standard Windows icon sizes
    sizes = [256, 48, 32, 16]

    # Supersampling factor for antialiased edges
    # Higher = smoother edges but slower
    SUPERSAMPLE = 4

    images = []
    for size in sizes:
        # Create larger image for supersampling (antialiased edges)
        large_size = size * SUPERSAMPLE
        large_img = Image.new("RGBA", (large_size, large_size), (0, 0, 0, 0))
        large_draw = ImageDraw.Draw(large_img)

        # Draw filled circle (brand color background) at larger size
        large_draw.ellipse([0, 0, large_size - 1, large_size - 1], fill=BRAND_COLOR)

        # Draw translate icon (simplified for small sizes)
        # Scale factor from 24x24 base to target large size
        scale = large_size / 24

        if size >= 32:
            # Full icon for larger sizes
            # "A" character shape (right side)
            a_points = [
                (17.5 * scale, 5 * scale),   # top
                (21 * scale, 17 * scale),    # bottom right
                (19 * scale, 17 * scale),    # inner right
                (18.12 * scale, 14 * scale), # notch right
                (14.88 * scale, 14 * scale), # notch left
                (14 * scale, 17 * scale),    # inner left
                (12 * scale, 17 * scale),    # bottom left
            ]
            large_draw.polygon(a_points, fill=WHITE)

            # "A" crossbar cutout
            a_bar = [
                (15.5 * scale, 12 * scale),
                (17.5 * scale, 12 * scale),
                (16.5 * scale, 9 * scale),
            ]
            large_draw.polygon(a_bar, fill=BRAND_COLOR)

            # Japanese text symbol (left side) - simplified
            # Horizontal lines
            line_width = max(1, int(1.5 * scale))
            large_draw.rectangle([4 * scale, 5 * scale, 12 * scale, 5 * scale + line_width], fill=WHITE)
            large_draw.rectangle([4 * scale, 8 * scale, 11 * scale, 8 * scale + line_width], fill=WHITE)

            # Vertical line
            large_draw.rectangle([8 * scale, 5 * scale, 8 * scale + line_width, 10 * scale], fill=WHITE)

            # Curved arrow (simplified as lines)
            large_draw.line([(5 * scale, 14 * scale), (9 * scale, 10 * scale)], fill=WHITE, width=line_width)
            large_draw.line([(9 * scale, 10 * scale), (12 * scale, 14 * scale)], fill=WHITE, width=line_width)

        else:
            # Simplified icon for 16x16
            # Just draw "文A" text representation
            line_width = max(1, int(scale))
            # Horizontal bar
            large_draw.rectangle([4 * scale, 7 * scale, 20 * scale, 7 * scale + line_width * 2], fill=WHITE)
            # Vertical bar
            large_draw.rectangle([11 * scale, 5 * scale, 13 * scale, 19 * scale], fill=WHITE)

        # Downsample with high-quality resampling for antialiased edges
        img = large_img.resize((size, size), Image.LANCZOS)
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
