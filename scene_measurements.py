import json
import uuid

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)


MEASUREMENT_KIND_ITEMS = (
    ("LINEAR", "Linear", "Two-point distance measurement"),
    ("PLANE", "Plane", "Three-point plane measurement"),
    ("POLYLINE", "Polyline", "Closed multi-point outline fitted to an averaged plane"),
    ("TRACE", "Trace", "Open multi-point polyline along a fracture trace, measured by total length"),
)

#: Blender icons for the kind toggles, in one place so the tool header and the
#: sidebar cannot drift apart. Chosen for what they look like at 16 px: a
#: dimension between two points, a flat quad, and a zigzag polyline.
LINEAR_ICON = "DRIVER_DISTANCE"
PLANE_ICON = "MESH_PLANE"
TRACE_ICON = "MOD_SIMPLIFY"

DEFAULT_MEASUREMENT_COLOR = (0.1, 0.65, 1.0, 1.0)
ACTIVE_MEASUREMENT_COLOR = (1.0, 0.9, 0.2, 1.0)

#: Viewport overlay style. The defaults reproduce the sizes the overlay used
#: before they were adjustable, so an existing scene looks unchanged.
DEFAULT_LINE_WIDTH = 2.0
MIN_LINE_WIDTH = 0.5
MAX_LINE_WIDTH = 10.0
DEFAULT_POINT_SIZE = 8.0
MIN_POINT_SIZE = 2.0
MAX_POINT_SIZE = 24.0
DEFAULT_FILL_ALPHA = 0.25
DEFAULT_LABEL_SIZE = 12.0
MIN_LABEL_SIZE = 6.0
MAX_LABEL_SIZE = 48.0

#: Per-redraw budgets for the screen-space overlay. Lines and fills are built
#: once and cached, but handles and labels live in screen space and have to be
#: rebuilt every frame, so their cost is what decides whether a large scene
#: stays interactive. Past a few thousand handles nothing on screen is legible
#: anyway; drawing them only spends frame time to produce a smear.
DEFAULT_MAX_HANDLE_POINTS = 2000
DEFAULT_MAX_LABELS = 200


#: Bumped whenever the measurement collection changes shape or contents.
#: The viewport overlay caches world-space geometry and needs to know when to
#: throw it away; hashing every point of every measurement per redraw would
#: cost as much as rebuilding, so the mutating helpers say so instead.
_revision = 0


def bump_measurement_revision():
    global _revision
    _revision += 1
    return _revision


def measurement_revision():
    return _revision


def _on_measurement_code_update(self, context):
    code = (getattr(self, "code", "") or "").strip()
    scene = getattr(self, "id_data", None) or getattr(context, "scene", None)
    if scene is not None:
        if code:
            ensure_scene_measurement_code(scene, code)
        sync_scene_measurement_codes(scene)


class ScientiaMeasurementPoint(bpy.types.PropertyGroup):
    co: FloatVectorProperty(
        name="Point",
        size=3,
        default=(0.0, 0.0, 0.0),
        subtype='XYZ',
    )


class ScientiaMeasurementLayer(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", default="Default")
    visible: BoolProperty(name="Visible", default=True)
    color: FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=4,
        default=DEFAULT_MEASUREMENT_COLOR,
        min=0.0,
        max=1.0,
    )


class ScientiaMeasurementCode(bpy.types.PropertyGroup):
    name: StringProperty(name="Code", default="")
    visible: BoolProperty(name="Visible", default=True)
    color: FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=4,
        default=DEFAULT_MEASUREMENT_COLOR,
        min=0.0,
        max=1.0,
    )


class ScientiaMeasurement(bpy.types.PropertyGroup):
    uuid: StringProperty(name="ID", default="")
    name: StringProperty(name="Name", default="")
    kind: EnumProperty(name="Kind", items=MEASUREMENT_KIND_ITEMS, default="LINEAR")
    layer: StringProperty(name="Layer", default="Default")
    visible: BoolProperty(name="Visible", default=True)
    selected: BoolProperty(name="Selected", default=False)
    color: FloatVectorProperty(
        name="Color",
        subtype='COLOR',
        size=4,
        default=DEFAULT_MEASUREMENT_COLOR,
        min=0.0,
        max=1.0,
    )
    code: StringProperty(name="Code", default="", update=_on_measurement_code_update)
    description: StringProperty(name="Description", default="")
    properties_json: StringProperty(name="Properties JSON", default="{}")
    points: CollectionProperty(type=ScientiaMeasurementPoint)


def scene_measurement_property_classes():
    return (
        ScientiaMeasurementPoint,
        ScientiaMeasurementLayer,
        ScientiaMeasurementCode,
        ScientiaMeasurement,
    )


def scene_measurement_scene_properties():
    return (
        "scientia_measurements",
        "scientia_measurement_layers",
        "scientia_measurement_codes",
        "scientia_active_measurement_index",
        "scientia_active_measurement_layer_index",
        "scientia_measure_show_labels",
        "scientia_measure_label_background",
        "scientia_measure_reuse_last_code",
        "scientia_measure_snap_by_default",
        "scientia_measure_line_width",
        "scientia_measure_show_points",
        "scientia_measure_point_size",
        "scientia_measure_fill_planes",
        "scientia_measure_fill_alpha",
        "scientia_measure_label_size",
        "scientia_measure_label_at_center",
        "scientia_measure_max_handle_points",
        "scientia_measure_max_labels",
        "scientia_measure_show_linear",
        "scientia_measure_show_planes",
        "scientia_measure_show_traces",
        "scientia_measure_no_code_visible",
        "scientia_measure_default_color",
        "scientia_measure_active_color",
        "scientia_label_show_code",
        "scientia_label_show_name",
        "scientia_label_show_description",
        "scientia_label_linear_distance",
        "scientia_label_linear_angle",
        "scientia_label_linear_azimuth",
        "scientia_label_linear_raw_azimuth",
        "scientia_label_linear_dx",
        "scientia_label_linear_dy",
        "scientia_label_linear_dz",
        "scientia_label_linear_horizontal",
        "scientia_label_plane_dip",
        "scientia_label_plane_azimuth",
        "scientia_label_plane_raw_azimuth",
        "scientia_label_plane_angle",
        "scientia_label_plane_area",
        "scientia_label_plane_fit_error",
        "scientia_label_trace_length",
        "scientia_label_trace_span",
        "scientia_label_trace_segments",
        "scientia_label_trace_mean_segment",
        "scientia_label_trace_sinuosity",
        "scientia_label_trace_azimuth",
    )


def define_scene_measurement_properties():
    bpy.types.Scene.scientia_measurements = CollectionProperty(type=ScientiaMeasurement)
    bpy.types.Scene.scientia_measurement_layers = CollectionProperty(type=ScientiaMeasurementLayer)
    bpy.types.Scene.scientia_measurement_codes = CollectionProperty(type=ScientiaMeasurementCode)
    bpy.types.Scene.scientia_active_measurement_index = IntProperty(name="Active Measurement", default=-1)
    bpy.types.Scene.scientia_active_measurement_layer_index = IntProperty(name="Active Layer", default=0)
    bpy.types.Scene.scientia_measure_show_labels = BoolProperty(name="Labels", default=True)
    bpy.types.Scene.scientia_measure_label_background = BoolProperty(name="Label Background", default=True)
    bpy.types.Scene.scientia_measure_reuse_last_code = BoolProperty(name="Reuse Previous Code", default=True)
    bpy.types.Scene.scientia_measure_snap_by_default = BoolProperty(name="Snap by Default", default=False)
    bpy.types.Scene.scientia_measure_line_width = FloatProperty(
        name="Line Width",
        description="Thickness of measurement lines and point outlines, in pixels",
        default=DEFAULT_LINE_WIDTH,
        min=MIN_LINE_WIDTH,
        max=MAX_LINE_WIDTH,
        step=10,
        precision=1,
    )
    bpy.types.Scene.scientia_measure_show_points = BoolProperty(
        name="All Points",
        description="Draw a handle on every point of every measurement. Switch off to keep the "
                    "handles of the active and hovered measurement only, which is quicker to draw "
                    "and less cluttered on a dense scene; a measurement always stays editable",
        default=True,
    )
    bpy.types.Scene.scientia_measure_point_size = FloatProperty(
        name="Point Size",
        description="Diameter of the point handles, in pixels",
        default=DEFAULT_POINT_SIZE,
        min=MIN_POINT_SIZE,
        max=MAX_POINT_SIZE,
        step=25,
        precision=1,
    )
    bpy.types.Scene.scientia_measure_fill_planes = BoolProperty(
        name="Fill Areas",
        description="Fill plane and polygon measurements with a translucent surface, so an area "
                    "reads as a surface instead of an outline",
        default=True,
    )
    bpy.types.Scene.scientia_measure_label_size = FloatProperty(
        name="Label Size",
        description="Text size of the measurement labels, in pixels",
        default=DEFAULT_LABEL_SIZE,
        min=MIN_LABEL_SIZE,
        max=MAX_LABEL_SIZE,
        step=25,
        precision=1,
    )
    bpy.types.Scene.scientia_measure_label_at_center = BoolProperty(
        name="Label at Area Center",
        description="Put the label of a plane or polygon measurement in the middle of its surface. "
                    "Switch off to keep it on the corner point the measurement hinges on",
        default=True,
    )
    bpy.types.Scene.scientia_measure_max_handle_points = IntProperty(
        name="Handle Budget",
        description="How many point handles the viewport draws per redraw. The ones nearest the "
                    "middle of the view are kept, along with the active and hovered measurement. "
                    "Raise it if you need to see more at once, lower it if the viewport lags",
        default=DEFAULT_MAX_HANDLE_POINTS,
        min=0,
        soft_max=20000,
    )
    bpy.types.Scene.scientia_measure_max_labels = IntProperty(
        name="Label Budget",
        description="How many labels the viewport draws per redraw, nearest the middle of the view "
                    "first. Labels are the most expensive part of the overlay and the first to "
                    "become unreadable when they overlap",
        default=DEFAULT_MAX_LABELS,
        min=0,
        soft_max=5000,
    )
    bpy.types.Scene.scientia_measure_fill_alpha = FloatProperty(
        name="Fill Opacity",
        description="Opacity of the area fill. 0 is invisible, 1 hides the geometry behind it",
        default=DEFAULT_FILL_ALPHA,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    bpy.types.Scene.scientia_measure_show_linear = BoolProperty(
        name="Show Linear Measurements",
        description="Show 2-point distance measurements in the viewport (display only; export is not affected)",
        default=True,
    )
    bpy.types.Scene.scientia_measure_show_planes = BoolProperty(
        name="Show Plane Measurements",
        description="Show plane and polygon measurements in the viewport (display only; export is not affected)",
        default=True,
    )
    bpy.types.Scene.scientia_measure_show_traces = BoolProperty(
        name="Show Trace Measurements",
        description="Show open trace polylines in the viewport (display only; export is not affected)",
        default=True,
    )
    bpy.types.Scene.scientia_measure_no_code_visible = BoolProperty(name="No Code Visible", default=True)
    bpy.types.Scene.scientia_measure_default_color = FloatVectorProperty(
        name="No Code Color",
        subtype='COLOR',
        size=4,
        default=DEFAULT_MEASUREMENT_COLOR,
        min=0.0,
        max=1.0,
    )
    bpy.types.Scene.scientia_measure_active_color = FloatVectorProperty(
        name="Active Measurement Color",
        subtype='COLOR',
        size=4,
        default=ACTIVE_MEASUREMENT_COLOR,
        min=0.0,
        max=1.0,
    )
    bpy.types.Scene.scientia_label_show_code = BoolProperty(name="Code", default=False)
    bpy.types.Scene.scientia_label_show_name = BoolProperty(name="Name", default=False)
    bpy.types.Scene.scientia_label_show_description = BoolProperty(name="Description", default=False)
    bpy.types.Scene.scientia_label_linear_distance = BoolProperty(name="Distance", default=True)
    bpy.types.Scene.scientia_label_linear_angle = BoolProperty(name="Angle", default=False)
    bpy.types.Scene.scientia_label_linear_azimuth = BoolProperty(name="Azimuth", default=False)
    bpy.types.Scene.scientia_label_linear_raw_azimuth = BoolProperty(name="Raw Azimuth", default=False)
    bpy.types.Scene.scientia_label_linear_dx = BoolProperty(name="Delta X", default=False)
    bpy.types.Scene.scientia_label_linear_dy = BoolProperty(name="Delta Y", default=False)
    bpy.types.Scene.scientia_label_linear_dz = BoolProperty(name="Delta Z", default=False)
    bpy.types.Scene.scientia_label_linear_horizontal = BoolProperty(name="Horizontal", default=False)
    bpy.types.Scene.scientia_label_plane_dip = BoolProperty(name="Dip", default=True)
    bpy.types.Scene.scientia_label_plane_azimuth = BoolProperty(name="Dip Azimuth", default=True)
    bpy.types.Scene.scientia_label_plane_raw_azimuth = BoolProperty(name="Raw Azimuth", default=False)
    bpy.types.Scene.scientia_label_plane_angle = BoolProperty(name="Point Angle", default=False)
    bpy.types.Scene.scientia_label_plane_area = BoolProperty(name="Area", default=False)
    bpy.types.Scene.scientia_label_plane_fit_error = BoolProperty(
        name="Fit Error",
        description="Show the RMS distance of polygon points from the fitted plane on the measurement label",
        default=True,
    )
    bpy.types.Scene.scientia_label_trace_length = BoolProperty(
        name="Trace Length",
        description="Show the summed length of every segment of the trace",
        default=True,
    )
    bpy.types.Scene.scientia_label_trace_span = BoolProperty(
        name="End-to-End Distance",
        description="Show the straight 3D distance from the first trace point to the last",
        default=True,
    )
    bpy.types.Scene.scientia_label_trace_segments = BoolProperty(name="Segments", default=False)
    bpy.types.Scene.scientia_label_trace_mean_segment = BoolProperty(name="Mean Segment", default=False)
    bpy.types.Scene.scientia_label_trace_sinuosity = BoolProperty(
        name="Sinuosity",
        description="Trace length divided by the straight distance between its ends: how far it wanders",
        default=False,
    )
    bpy.types.Scene.scientia_label_trace_azimuth = BoolProperty(name="Trace Azimuth", default=False)


def ensure_default_scene_measure_layer(scene):
    layers = getattr(scene, "scientia_measurement_layers", None)
    if layers is None:
        return None
    if len(layers) == 0:
        layer = layers.add()
        layer.name = "Default"
        layer.visible = True
        layer.color = DEFAULT_MEASUREMENT_COLOR
        scene.scientia_active_measurement_layer_index = 0
        return layer
    index = max(0, min(scene.scientia_active_measurement_layer_index, len(layers) - 1))
    scene.scientia_active_measurement_layer_index = index
    return layers[index]


def active_scene_measure_layer_name(scene):
    layer = ensure_default_scene_measure_layer(scene)
    return layer.name if layer else "Default"


def active_scene_measure_layer_color(scene):
    layer = ensure_default_scene_measure_layer(scene)
    return tuple(layer.color) if layer else DEFAULT_MEASUREMENT_COLOR


def scene_measure_default_color(scene):
    return tuple(getattr(scene, "scientia_measure_default_color", DEFAULT_MEASUREMENT_COLOR))


def scene_measure_active_color(scene):
    return tuple(getattr(scene, "scientia_measure_active_color", ACTIVE_MEASUREMENT_COLOR))


def _clamped_float(scene, name, default, minimum, maximum):
    """Read an overlay style value defensively.

    The viewport draw handlers run on every redraw, including before the
    properties exist - an add-on reload leaves the handler registered for a
    moment longer than the Scene properties - and a value out of range would
    ask the GPU for a line width it cannot draw.
    """
    try:
        value = float(getattr(scene, name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def scene_measure_line_width(scene):
    return _clamped_float(
        scene, "scientia_measure_line_width", DEFAULT_LINE_WIDTH, MIN_LINE_WIDTH, MAX_LINE_WIDTH
    )


def scene_measure_point_size(scene):
    return _clamped_float(
        scene, "scientia_measure_point_size", DEFAULT_POINT_SIZE, MIN_POINT_SIZE, MAX_POINT_SIZE
    )


def scene_measure_points_visible(scene):
    return bool(getattr(scene, "scientia_measure_show_points", True))


def scene_measure_label_size(scene):
    return _clamped_float(
        scene, "scientia_measure_label_size", DEFAULT_LABEL_SIZE, MIN_LABEL_SIZE, MAX_LABEL_SIZE
    )


def scene_measure_label_at_center(scene):
    return bool(getattr(scene, "scientia_measure_label_at_center", True))


def scene_measure_fill_alpha(scene):
    """Opacity for area fills, or 0 when the fill is switched off."""
    if not getattr(scene, "scientia_measure_fill_planes", True):
        return 0.0
    return _clamped_float(scene, "scientia_measure_fill_alpha", DEFAULT_FILL_ALPHA, 0.0, 1.0)


def ensure_scene_measurement_code(scene, code, color=None):
    code = (code or "").strip()
    if not code or not hasattr(scene, "scientia_measurement_codes"):
        return None
    for item in scene.scientia_measurement_codes:
        if item.name == code:
            return item
    item = scene.scientia_measurement_codes.add()
    item.name = code
    item.visible = True
    item.color = color or scene_measure_default_color(scene)
    return item


def sync_scene_measurement_codes(scene):
    codes = getattr(scene, "scientia_measurement_codes", None)
    measurements = getattr(scene, "scientia_measurements", None)
    if codes is None or measurements is None:
        return

    used_codes = []
    for measurement in measurements:
        code = (getattr(measurement, "code", "") or "").strip()
        if code and code not in used_codes:
            used_codes.append(code)

    used_set = set(used_codes)
    for index in reversed(range(len(codes))):
        name = (getattr(codes[index], "name", "") or "").strip()
        if not name or name not in used_set:
            codes.remove(index)

    existing = {(getattr(item, "name", "") or "").strip() for item in codes}
    for code in used_codes:
        if code not in existing:
            ensure_scene_measurement_code(scene, code)


def scene_measurement_code_color(scene, code):
    code = (code or "").strip()
    if not code:
        return scene_measure_default_color(scene)
    if not hasattr(scene, "scientia_measurement_codes"):
        return None
    for item in scene.scientia_measurement_codes:
        if item.name == code:
            return tuple(item.color)
    return None


def scene_measurement_code_styles(scene):
    """``{code: (color, visible)}`` for every defined fracture code.

    The lookups below scan the code collection, which is fine for a panel row
    and quadratic for a viewport redraw that asks once per measurement. Callers
    that walk every measurement build this once instead.
    """
    styles = {}
    for item in getattr(scene, "scientia_measurement_codes", ()) or ():
        styles[item.name] = (tuple(item.color), bool(getattr(item, "visible", True)))
    return styles


def scene_measurement_code_visible(scene, code):
    code = (code or "").strip()
    if not code:
        return getattr(scene, "scientia_measure_no_code_visible", True)
    if not hasattr(scene, "scientia_measurement_codes"):
        return True
    for item in scene.scientia_measurement_codes:
        if item.name == code:
            return getattr(item, "visible", True)
    return True


def previous_scene_measurement_code(scene):
    if not getattr(scene, "scientia_measure_reuse_last_code", True):
        return ""
    measurements = getattr(scene, "scientia_measurements", None)
    if measurements is None or len(measurements) == 0:
        return ""
    index = getattr(scene, "scientia_active_measurement_index", -1)
    if index < 0 or index >= len(measurements):
        index = len(measurements) - 1
    return (getattr(measurements[index], "code", "") or "").strip()


def kind_from_point_count(point_count):
    if point_count == 2:
        return "LINEAR"
    if point_count == 3:
        return "PLANE"
    return "POLYLINE"


def kind_accepts_point_count(kind, point_count):
    """Whether moving coordinates can keep an existing semantic kind.

    Point edits do not change topology.  In particular, a trace is still an
    open trace after one of its points moves; classifying it again only from
    the number of points silently turns it into a line, plane, or polygon.
    """
    kind = str(kind or "").upper()
    if kind == "LINEAR":
        return point_count == 2
    if kind == "PLANE":
        return point_count == 3
    if kind == "POLYLINE":
        return point_count >= 3
    if kind == "TRACE":
        return point_count >= 2
    return False


def set_scene_measurement_points(measurement, points, kind=None):
    measurement.points.clear()
    for point in points:
        item = measurement.points.add()
        item.co = (float(point[0]), float(point[1]), float(point[2]))
    if kind is None:
        # Coordinate-only edits preserve every compatible semantic type.
        # A real topology change (the linear tool pulling a third point out of
        # a two-point line) still deliberately falls back to point-count
        # classification and becomes a plane.
        current = str(getattr(measurement, "kind", "") or "").upper()
        kind = current if kind_accepts_point_count(current, len(points)) else kind_from_point_count(len(points))
    measurement.kind = kind
    bump_measurement_revision()


def next_measurement_name(scene, prefix="M"):
    """First free ``M<n>`` name.

    Numbering by collection length repeats a name after any deletion, which
    produces two different measurements sharing a name in the exported CSV.
    """
    used = {
        (getattr(item, "name", "") or "").strip()
        for item in getattr(scene, "scientia_measurements", ())
    }
    index = max(1, len(used))
    while f"{prefix}{index}" in used:
        index += 1
    return f"{prefix}{index}"


def add_scene_measurement(scene, points, kind=None, layer=None, color=None, name=None):
    ensure_default_scene_measure_layer(scene)
    measurement = scene.scientia_measurements.add()
    measurement.uuid = uuid.uuid4().hex
    measurement.kind = kind or kind_from_point_count(len(points))
    measurement.layer = layer or active_scene_measure_layer_name(scene)
    measurement.visible = True
    measurement.selected = True
    measurement.color = color or scene_measure_default_color(scene)
    measurement.name = name or next_measurement_name(scene)
    measurement.code = previous_scene_measurement_code(scene)
    measurement.description = ""
    measurement.properties_json = "{}"
    if measurement.code:
        ensure_scene_measurement_code(scene, measurement.code)
    set_scene_measurement_points(measurement, points, kind=measurement.kind)

    scene.scientia_active_measurement_index = len(scene.scientia_measurements) - 1
    for index, item in enumerate(scene.scientia_measurements):
        item.selected = index == scene.scientia_active_measurement_index
    bump_measurement_revision()
    return measurement


def delete_active_scene_measurement(scene):
    measurements = getattr(scene, "scientia_measurements", None)
    if measurements is None or len(measurements) == 0:
        return False
    index = getattr(scene, "scientia_active_measurement_index", -1)
    if index < 0 or index >= len(measurements):
        return False
    measurements.remove(index)
    scene.scientia_active_measurement_index = min(index, len(measurements) - 1)
    sync_scene_measurement_codes(scene)
    bump_measurement_revision()
    return True


def scene_measurement_points(measurement):
    return tuple(tuple(point.co) for point in measurement.points)


def measurement_custom_properties(measurement):
    try:
        values = json.loads(measurement.properties_json or "{}")
        if not isinstance(values, dict):
            values = {}
    except Exception:
        values = {}
    scene = getattr(measurement, "id_data", None)
    code = getattr(measurement, "code", "")
    code_color = scene_measurement_code_color(scene, code) if scene is not None else None
    color = code_color or tuple(getattr(measurement, "color", DEFAULT_MEASUREMENT_COLOR))

    values.setdefault("name", measurement.name)
    values.setdefault("code", code)
    values.setdefault("description", getattr(measurement, "description", ""))
    values.setdefault("layer", getattr(measurement, "layer", "Default"))
    values.setdefault("color", tuple(getattr(measurement, "color", DEFAULT_MEASUREMENT_COLOR)))
    values.setdefault("display_color", tuple(color))
    return values
