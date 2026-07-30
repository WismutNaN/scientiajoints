"""Generate the toolbar icons for the ScientiaJoints workspace tools.

Blender draws toolbar icons from ``.dat`` files holding flat-shaded triangles,
not from images: ``WorkSpaceTool.bl_icon`` names a file that
``bpy.app.icons.new_triangles_from_file()`` loads. The format is undocumented
but simple::

    b"VCO\\x00"                      magic
    uint8 * 4                       canvas width, height, x offset, y offset
    uint8 * 6 * triangles           x, y per vertex, three vertices per triangle
    uint8 * 12 * triangles          r, g, b, a per vertex

Coordinates live on a 0..255 canvas with the origin bottom left, and the
triangle count is implied by the file length. Both add-on icons are described
here as vector shapes and rasterised into triangles, so the artwork is edited
by changing numbers in ``ICONS`` and re-running this script rather than by
hand-editing binaries::

    python tools/build_tool_icons.py
    python tools/build_tool_icons.py --preview preview.png
    python tools/build_tool_icons.py --png --png-size 1024

``--png`` writes one transparent PNG per icon, for slides and documents: the
``.dat`` files are triangle lists no other program reads.

The palette is taken from Blender's own tool icons so the add-on does not stand
out in the toolbar: light grey outlines, a grey plane body, and a green accent
on whatever the tool actually measures.
"""

import argparse
import math
import struct
import zlib
from pathlib import Path


ICON_DIRECTORY_NAME = "icons"
MAGIC = b"VCO\x00"
CANVAS = 255

#: Sampled from ``datafiles/icons`` in a stock Blender install.
LIGHT = (229, 229, 229, 255)
GREY = (144, 144, 144, 255)
GREEN = (117, 255, 175, 255)

#: Blender renders toolbar icons at 32 px, so a stroke thinner than about 12
#: canvas units disappears at the size that matters.
STROKE = 18.0
THIN_STROKE = 11.0
HANDLE_RADIUS = 19.0


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


def disc(center, radius, color, segments=16):
    """A filled circle, used for the round point handles."""
    cx, cy = center
    ring = [
        (cx + radius * math.cos(math.tau * index / segments),
         cy + radius * math.sin(math.tau * index / segments))
        for index in range(segments)
    ]
    return fan(ring, color)


def fan(points, color):
    """Triangle fan over a convex outline."""
    return [
        ((points[0], points[index], points[index + 1]), color)
        for index in range(1, len(points) - 1)
    ]


def segment(start, end, width, color):
    """A straight stroke with square ends.

    Joins and caps are rounded separately by :func:`polyline`, which drops a
    disc on every shared point. Doing it that way keeps the maths trivial and
    costs a handful of triangles the icon can afford.
    """
    (x0, y0), (x1, y1) = start, end
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 1.0e-6:
        return []
    nx, ny = -dy / length * width / 2.0, dx / length * width / 2.0
    corners = (
        (x0 + nx, y0 + ny),
        (x1 + nx, y1 + ny),
        (x1 - nx, y1 - ny),
        (x0 - nx, y0 - ny),
    )
    return fan(corners, color)


def polyline(points, width, color, closed=False):
    """A stroke through every point, with rounded joins and caps."""
    triangles = []
    pairs = list(zip(points, points[1:]))
    if closed:
        pairs.append((points[-1], points[0]))
    for start, end in pairs:
        triangles.extend(segment(start, end, width, color))

    joins = points if closed else points[1:-1]
    for point in joins:
        triangles.extend(disc(point, width / 2.0, color, segments=10))
    return triangles


def arrow(start, end, width, head_length, head_width, color):
    """A line ending in a solid triangular head, pointing at ``end``."""
    (x0, y0), (x1, y1) = start, end
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 1.0e-6:
        return []
    ux, uy = dx / length, dy / length
    base = (x1 - ux * head_length, y1 - uy * head_length)
    px, py = -uy * head_width / 2.0, ux * head_width / 2.0

    triangles = segment(start, base, width, color)
    triangles.append((((base[0] + px, base[1] + py),
                       (base[0] - px, base[1] - py),
                       (x1, y1)), color))
    return triangles


def regular_polygon(center, radius, sides, rotation=0.0):
    cx, cy = center
    return [
        (cx + radius * math.cos(rotation + math.tau * index / sides),
         cy + radius * math.sin(rotation + math.tau * index / sides))
        for index in range(sides)
    ]


def flatten(center, points, factor):
    """Squash points towards ``center`` vertically, so a shape reads as a
    plane seen at an angle instead of a flat-on face."""
    cx, cy = center
    return [(x, cy + (y - cy) * factor) for x, y in points]


# ---------------------------------------------------------------------------
# The two icons
# ---------------------------------------------------------------------------


def measure_icon():
    """Distance and plane tool: a plane through three handles, with the
    measured segment highlighted.

    Deliberately unlike ``ops.view3d.ruler`` (a ticked protractor): the point
    handles and the triangle say "three picked points build a plane", which is
    what this tool does and the built-in ruler does not.
    """
    a = (40.0, 60.0)
    b = (215.0, 100.0)
    c = (118.0, 214.0)

    triangles = []
    triangles.extend(fan([a, b, c], GREY))
    triangles.extend(polyline([a, b, c], THIN_STROKE, LIGHT, closed=True))
    triangles.extend(segment(a, b, STROKE, GREEN))
    for point in (a, b, c):
        triangles.extend(disc(point, HANDLE_RADIUS, LIGHT))
    return triangles


def polygon_plane_icon():
    """Polygon tool: a closed outline of picked points with the averaged
    plane normal rising out of it.

    Shares the grey plane body and light handles with :func:`measure_icon` so
    the pair reads as one add-on, and the normal arrow marks the difference:
    this tool returns an orientation fitted to every point, not a distance.
    """
    center = (112.0, 86.0)
    outline = flatten(center, regular_polygon(center, 92.0, 5, rotation=math.tau / 4.0), 0.60)

    triangles = []
    triangles.extend(fan(outline, GREY))
    triangles.extend(polyline(outline, THIN_STROKE, LIGHT, closed=True))
    for point in outline:
        triangles.extend(disc(point, HANDLE_RADIUS * 0.75, LIGHT))
    # Drawn last: the normal is what tells the two ScientiaJoints icons apart,
    # so nothing may cover it.
    triangles.extend(arrow(center, (192.0, 222.0), STROKE, 48.0, 56.0, GREEN))
    return triangles


def trace_icon():
    """Trace tool: an open polyline with a handle on every vertex.

    The two ends stay apart and nothing is filled, which is exactly what
    separates a trace from the polygon next to it in the toolbar. The green
    marks the run of the line itself, because its length is what the tool
    measures.
    """
    points = [
        (34.0, 74.0),
        (86.0, 150.0),
        (128.0, 86.0),
        (176.0, 158.0),
        (222.0, 108.0),
    ]

    triangles = []
    triangles.extend(polyline(points, STROKE, GREEN))
    for point in points:
        triangles.extend(disc(point, HANDLE_RADIUS * 0.8, LIGHT))
    return triangles


ICONS = {
    "scientiajoints.measure": measure_icon,
    "scientiajoints.polygon_measure": polygon_plane_icon,
    "scientiajoints.trace_measure": trace_icon,
}


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def encode(triangles):
    """Pack triangles into the ``.dat`` byte layout described in the module
    docstring."""
    def clamp(value):
        return max(0, min(255, int(round(value))))

    coordinates = bytearray()
    colors = bytearray()
    for points, color in triangles:
        if len(points) != 3:
            raise ValueError(f"Expected a triangle, got {len(points)} points")
        for x, y in points:
            coordinates.append(clamp(x))
            coordinates.append(clamp(y))
        for _ in range(3):
            colors.extend(bytes(color))

    return MAGIC + bytes((CANVAS, CANVAS, 0, 0)) + bytes(coordinates) + bytes(colors)


def build_icons(icon_directory):
    """Write every icon and return the paths, newest content and all."""
    icon_directory = Path(icon_directory)
    icon_directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, builder in sorted(ICONS.items()):
        path = icon_directory / f"{name}.dat"
        path.write_bytes(encode(builder()))
        written.append(path)
    return tuple(written)


# ---------------------------------------------------------------------------
# Raster output: previews, and PNGs to drop into a slide
# ---------------------------------------------------------------------------

#: Samples per pixel along each axis when rendering a PNG. The rasteriser
#: below decides one sample per pixel, so smooth edges come from rendering
#: large and averaging down.
SUPERSAMPLE = 4

#: Largest canvas the pure Python rasteriser is asked to fill. It tests every
#: pixel of every triangle in a Python loop, so cost grows with the square of
#: the edge: 8192 takes minutes. Supersampling is reduced instead of the output
#: size, which costs nothing visible - an edge is already sub-pixel smooth once
#: the icon is a thousand pixels across. 4096 keeps the full four samples per
#: pixel at the 1024 export that a slide actually needs.
MAX_RASTER_EDGE = 4096


def _rasterize(triangles, size):
    """Scanline-fill the triangles into an RGBA buffer, origin top left.

    Pixels no triangle covers are left fully transparent, which is what makes
    a transparent PNG possible; the preview composites them onto its own
    background afterwards.
    """
    pixels = [[[0, 0, 0, 0] for _ in range(size)] for _ in range(size)]
    for points, color in triangles:
        scaled = [(x * size / CANVAS, y * size / CANVAS) for x, y in points]
        (ax, ay), (bx, by), (cx, cy) = scaled
        area = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(area) < 1.0e-9:
            continue
        x_range = range(max(0, int(min(x for x, _ in scaled))),
                        min(size, int(max(x for x, _ in scaled)) + 2))
        y_range = range(max(0, int(min(y for _, y in scaled))),
                        min(size, int(max(y for _, y in scaled)) + 2))
        for py in y_range:
            for px in x_range:
                x, y = px + 0.5, py + 0.5
                u = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / area
                v = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / area
                if u < 0.0 or v < 0.0 or u + v > 1.0:
                    continue
                pixels[size - 1 - py][px] = [color[0], color[1], color[2], 255]
    return pixels


def _downsample(pixels, size, factor):
    """Average a supersampled buffer down, keeping the alpha honest.

    Colour is averaged over the covered samples only. Averaging it over the
    transparent ones as well would drag every edge towards black, the classic
    dark halo around a transparent PNG placed on a light slide.
    """
    result = []
    for y in range(size):
        row = []
        for x in range(size):
            red = green = blue = covered = 0
            for sub_y in range(factor):
                for sub_x in range(factor):
                    sample = pixels[y * factor + sub_y][x * factor + sub_x]
                    if sample[3]:
                        red += sample[0]
                        green += sample[1]
                        blue += sample[2]
                        covered += 1
            if covered:
                row.append([red // covered, green // covered, blue // covered,
                            covered * 255 // (factor * factor)])
            else:
                row.append([0, 0, 0, 0])
        result.append(row)
    return result


def _png_bytes(rows, width, height, color_type):
    """A PNG file: color_type 2 is RGB, 6 is RGBA."""
    def chunk(tag, payload):
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + chunk(b"IEND", b""))


def _over(pixel, background):
    """Composite one RGBA pixel onto an opaque background."""
    alpha = pixel[3] / 255.0
    return [int(round(pixel[index] * alpha + background[index] * (1.0 - alpha))) for index in range(3)]


def affordable_supersample(size, supersample=SUPERSAMPLE):
    """How much supersampling ``size`` can have within :data:`MAX_RASTER_EDGE`."""
    return max(1, min(supersample, MAX_RASTER_EDGE // max(1, size)))


def render(builder, size, supersample=SUPERSAMPLE):
    """One icon as an antialiased RGBA pixel buffer."""
    supersample = affordable_supersample(size, supersample)
    if supersample <= 1:
        return _rasterize(builder(), size)
    return _downsample(_rasterize(builder(), size * supersample), size, supersample)


def write_preview(path, size=64, background=(58, 58, 58), supersample=SUPERSAMPLE):
    """Render every icon side by side into a PNG, for eyeballing changes."""
    strips = [render(builder, size, supersample) for _, builder in sorted(ICONS.items())]
    rows = [
        b"\x00" + bytes(
            value
            for strip in strips
            for pixel in strip[row]
            for value in _over(pixel, background)
        )
        for row in range(size)
    ]
    Path(path).write_bytes(_png_bytes(rows, size * len(strips), size, 2))
    return Path(path)


def write_pngs(directory, size=512, supersample=SUPERSAMPLE):
    """Write each icon as a standalone PNG with a transparent background.

    This is the format to drop into a slide or a document: the ``.dat`` files
    Blender loads are triangle lists no other program reads.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, builder in sorted(ICONS.items()):
        pixels = render(builder, size, supersample)
        rows = [b"\x00" + bytes(value for pixel in row for value in pixel) for row in pixels]
        path = directory / f"{name}.png"
        path.write_bytes(_png_bytes(rows, size, size, 6))
        written.append(path)
    return tuple(written)


def main():
    addon_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--icon-directory",
        type=Path,
        default=addon_root / ICON_DIRECTORY_NAME,
        help="Where the .dat files are written",
    )
    parser.add_argument("--preview", type=Path, help="Also render a PNG contact sheet here")
    parser.add_argument("--preview-size", type=int, default=64, help="Preview cell size in pixels")
    parser.add_argument(
        "--png",
        type=Path,
        nargs="?",
        const=addon_root / ICON_DIRECTORY_NAME / "png",
        help="Also write one transparent PNG per icon into this directory, for slides and documents",
    )
    parser.add_argument("--png-size", type=int, default=512, help="Edge length of each PNG, in pixels")
    args = parser.parse_args()

    for path in build_icons(args.icon_directory):
        print(f"Wrote {path} ({path.stat().st_size} bytes)")
    if args.preview:
        print(f"Wrote {write_preview(args.preview, size=args.preview_size)}")
    if args.png:
        for path in write_pngs(args.png, size=args.png_size):
            print(f"Wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
