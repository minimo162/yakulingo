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

    APPLE_RED = (229, 57, 53, 255)    # #E53935
    APPLE_STEM = (141, 110, 99, 255)  # #8D6E63
    APPLE_LEAF = (67, 160, 71, 255)   # #43A047

    def _bezier_point(p0, p1, p2, p3, t: float) -> tuple[float, float]:
        one_minus = 1.0 - t
        return (
            (one_minus ** 3) * p0[0]
            + 3 * (one_minus ** 2) * t * p1[0]
            + 3 * one_minus * (t ** 2) * p2[0]
            + (t ** 3) * p3[0],
            (one_minus ** 3) * p0[1]
            + 3 * (one_minus ** 2) * t * p1[1]
            + 3 * one_minus * (t ** 2) * p2[1]
            + (t ** 3) * p3[1],
        )

    def _leaf_polygon(scale: float, steps: int = 24) -> list[tuple[float, float]]:
        p0 = (34 * scale, 12 * scale)
        p1 = (42 * scale, 4 * scale)
        p2 = (54 * scale, 6 * scale)
        p3 = (56 * scale, 18 * scale)
        p4 = (46 * scale, 20 * scale)
        p5 = (38 * scale, 18 * scale)
        p6 = p0

        points = []
        for i in range(steps + 1):
            t = i / steps
            points.append(_bezier_point(p0, p1, p2, p3, t))
        for i in range(steps + 1):
            t = i / steps
            points.append(_bezier_point(p3, p4, p5, p6, t))
        return points

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

        # Draw apple icon from the SVG proportions (64x64 viewbox).
        scale = large_size / 64
        body_center = (32 * scale, 38 * scale)
        body_radius = 20 * scale
        large_draw.ellipse(
            [
                body_center[0] - body_radius,
                body_center[1] - body_radius,
                body_center[0] + body_radius,
                body_center[1] + body_radius,
            ],
            fill=APPLE_RED,
        )

        stem_rect = [
            30 * scale,
            10 * scale,
            (30 + 4) * scale,
            (10 + 12) * scale,
        ]
        stem_radius = 2 * scale
        large_draw.rounded_rectangle(stem_rect, radius=stem_radius, fill=APPLE_STEM)

        leaf_points = _leaf_polygon(scale)
        large_draw.polygon(leaf_points, fill=APPLE_LEAF)

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
