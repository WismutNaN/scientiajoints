"""Draw the ScientiaJoints logo.

Not a toolbar icon: Blender never loads this, so it is only ever a PNG. It
reuses the shape helpers from ``build_tool_icons`` so the logo and the tool
icons stay visibly one family - same flat style, same green accent on whatever
is being measured.

    python tools/build_logo.py                       # docs/logo.png at 512 px
    python tools/build_logo.py --size 1024 --output docs/logo-large.png

A square canvas with a rounded tile reads well as a GitHub avatar and as a
README banner image; the padding keeps it from touching a circular crop.
"""

import argparse
import math
from pathlib import Path

from build_tool_icons import (
    CANVAS,
    disc,
    fan,
    flatten,
    polyline,
    regular_polygon,
    write_png,
)

#: The tile behind the artwork. Dark slate so the light rock face and the green
#: traces both carry, on a white README and a dark one alike.
TILE_COLOR = (38, 42, 50, 255)
ROCK_COLOR = (150, 152, 158, 255)
ROCK_EDGE_COLOR = (206, 208, 214, 255)
TRACE_COLOR = (117, 255, 175, 255)
POINT_COLOR = (245, 246, 250, 255)

TILE_RADIUS = 46.0
TILE_MARGIN = 10.0
TRACE_WIDTH = 11.0
ROCK_EDGE_WIDTH = 7.0
POINT_RADIUS = 12.0


def _rounded_tile(x0, y0, x1, y1, radius, segments=8):
    """Triangles covering a rounded rectangle: middle band plus four corners."""
    triangles = []
    triangles.extend(fan(
        [(x0 + radius, y0), (x1 - radius, y0), (x1 - radius, y1), (x0 + radius, y1)],
        TILE_COLOR,
    ))
    triangles.extend(fan(
        [(x0, y0 + radius), (x0 + radius, y0 + radius), (x0 + radius, y1 - radius), (x0, y1 - radius)],
        TILE_COLOR,
    ))
    triangles.extend(fan(
        [(x1 - radius, y0 + radius), (x1, y0 + radius), (x1, y1 - radius), (x1 - radius, y1 - radius)],
        TILE_COLOR,
    ))

    quarter = math.pi * 0.5
    corners = (
        ((x1 - radius, y1 - radius), 0.0),
        ((x0 + radius, y1 - radius), quarter),
        ((x0 + radius, y0 + radius), math.pi),
        ((x1 - radius, y0 + radius), math.pi * 1.5),
    )
    for (cx, cy), start in corners:
        ring = [
            (cx + math.cos(start + quarter * index / segments) * radius,
             cy + math.sin(start + quarter * index / segments) * radius)
            for index in range(segments + 1)
        ]
        triangles.extend(fan([(cx, cy)] + ring, TILE_COLOR))
    return triangles


def logo():
    """A rock face seen at an angle, with two measured fracture traces on it.

    The subject is what the add-on is for: fractures picked out on a rock mass
    surface. The face is a flattened hexagon rather than a rectangle so it reads
    as a surface in space instead of a page, and the traces are open polylines
    with their vertices marked, which is exactly what the tools produce.
    """
    triangles = []
    triangles.extend(_rounded_tile(
        TILE_MARGIN, TILE_MARGIN, CANVAS - TILE_MARGIN, CANVAS - TILE_MARGIN, TILE_RADIUS
    ))

    face_center = (128.0, 118.0)
    face = flatten(face_center, regular_polygon(face_center, 88.0, 6, rotation=math.tau / 12.0), 0.72)
    triangles.extend(fan(face, ROCK_COLOR))
    triangles.extend(polyline(face, ROCK_EDGE_WIDTH, ROCK_EDGE_COLOR, closed=True))

    # Two traces, kept in separate bands: crossing them would read as a mesh
    # rather than as two measurements.
    traces = (
        ((56.0, 122.0), (100.0, 156.0), (150.0, 124.0), (200.0, 158.0)),
        ((74.0, 76.0), (124.0, 92.0), (176.0, 72.0)),
    )
    for trace in traces:
        triangles.extend(polyline(list(trace), TRACE_WIDTH, TRACE_COLOR))
    for trace in traces:
        for point in trace:
            triangles.extend(disc(point, POINT_RADIUS, POINT_COLOR, segments=14))
    return triangles


def main():
    repository_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=repository_root / "docs" / "logo.png")
    parser.add_argument("--size", type=int, default=512, help="Edge length in pixels")
    args = parser.parse_args()

    path = write_png(args.output, logo, size=args.size)
    print(f"Wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
