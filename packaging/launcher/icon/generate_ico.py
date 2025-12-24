#!/usr/bin/env python3
"""
Generate ICO file for Windows application icon.
Requires: pip install pillow

Uses manual ICO creation with PNG-embedded images for proper transparency support.
Pillow's default ICO save may not handle transparency correctly for smaller sizes.
"""

import argparse
import struct
from io import BytesIO
from pathlib import Path


def save_ico_with_png(images: list, output_path: Path) -> None:
    """
    Create ICO file with PNG-embedded images for proper transparency.

    Windows Vista+ supports PNG-embedded ICO files, which preserve
    alpha channel transparency correctly (unlike BMP-based ICO).

    Args:
        images: List of PIL.Image objects (RGBA mode), sorted by size descending
        output_path: Output ICO file path
    """
    from PIL import Image

    num_images = len(images)

    # Prepare PNG data for each image
    png_data_list = []
    for img in images:
        buffer = BytesIO()
        img.save(buffer, format='PNG', compress_level=9)
        png_data_list.append(buffer.getvalue())

    # ICO file structure:
    # - ICONDIR header (6 bytes)
    # - ICONDIRENTRY array (16 bytes each)
    # - Image data (PNG format)

    # ICONDIR: Reserved(2) + Type(2, 1=ICO) + Count(2)
    icondir = struct.pack('<HHH', 0, 1, num_images)

    # Calculate data offset (after header and all entries)
    header_size = 6 + 16 * num_images
    offset = header_size

    # Build ICONDIRENTRY array
    entries = b''
    for i, img in enumerate(images):
        # Width/Height: 0 means 256
        width = img.width if img.width < 256 else 0
        height = img.height if img.height < 256 else 0
        data_size = len(png_data_list[i])

        # ICONDIRENTRY: Width(1) Height(1) ColorCount(1) Reserved(1)
        #               Planes(2) BitCount(2) BytesInRes(4) ImageOffset(4)
        entry = struct.pack('<BBBBHHII',
                            width, height, 0, 0,  # Width, Height, ColorCount, Reserved
                            1, 32,                 # Planes, BitCount (32-bit RGBA)
                            data_size, offset)     # BytesInRes, ImageOffset
        entries += entry
        offset += data_size

    # Write ICO file
    with open(output_path, 'wb') as f:
        f.write(icondir)
        f.write(entries)
        for data in png_data_list:
            f.write(data)


def _default_output_path() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "yakulingo" / "ui" / "yakulingo.ico"


def generate_ico(output_path: Path) -> None:
    from PIL import Image, ImageDraw

    ico_path = output_path

    # Brand color (from styles.py)
    BRAND_COLOR = (67, 85, 185, 255)  # #4355B9
    WHITE = (255, 255, 255, 255)

    # Windows icon sizes (sorted descending for ICO format).
    # Include non-standard sizes for common DPI scales (125% => 20/40px) to avoid blur.
    sizes = [256, 128, 64, 48, 40, 32, 24, 20, 16]

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
            # Compact icon for small sizes (16/20/24px, used by taskbar at common DPI scales).
            # Keep the same visual identity as the larger icons to avoid looking like a zoomed/cropped part.

            # "A" character shape (right side) - same silhouette, no inner cutout for readability.
            a_points = [
                (17.5 * scale, 5.2 * scale),   # top
                (21.0 * scale, 17.0 * scale),  # bottom right
                (19.3 * scale, 17.0 * scale),  # inner right
                (18.2 * scale, 13.8 * scale),  # notch right
                (15.0 * scale, 13.8 * scale),  # notch left
                (13.9 * scale, 17.0 * scale),  # inner left
                (12.2 * scale, 17.0 * scale),  # bottom left
            ]
            large_draw.polygon(a_points, fill=WHITE)

            # Japanese side (left) - simplified strokes (no arrow) to stay legible.
            line_width = max(1, int(1.6 * scale))
            if size >= 20:
                large_draw.rectangle(
                    [4.2 * scale, 5.4 * scale, 12.2 * scale, 5.4 * scale + line_width],
                    fill=WHITE,
                )
                large_draw.rectangle(
                    [4.2 * scale, 8.4 * scale, 11.2 * scale, 8.4 * scale + line_width],
                    fill=WHITE,
                )
                large_draw.rectangle(
                    [8.0 * scale, 5.4 * scale, 8.0 * scale + line_width, 10.4 * scale],
                    fill=WHITE,
                )
            else:
                # 16x16: even simpler to avoid blur.
                large_draw.rectangle(
                    [4.5 * scale, 7.0 * scale, 11.8 * scale, 7.0 * scale + line_width],
                    fill=WHITE,
                )

        # Downsample with high-quality resampling for antialiased edges
        img = large_img.resize((size, size), Image.LANCZOS)
        images.append(img)

    # Save as ICO with PNG-embedded images for proper transparency
    # (Pillow's default ICO save may use BMP format for smaller sizes,
    # which can cause transparency issues on some Windows versions)
    save_ico_with_png(images, ico_path)

    print(f"Generated: {ico_path}")
    print(f"Sizes: {sizes}")
    print("Using PNG-embedded format for proper transparency")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate YakuLingo Windows .ico file")
    parser.add_argument(
        "--output",
        type=Path,
        default=_default_output_path(),
        help="Output .ico path (default: yakulingo/ui/yakulingo.ico)",
    )
    args = parser.parse_args()
    generate_ico(args.output)
