import json
import uuid

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)


MEASUREMENT_KIND_ITEMS = (
    ("LINEAR", "Linear", "Two-point distance measurement"),
    ("PLANE", "Plane", "Three-point plane measurement"),
    ("POLYLINE", "Polyline", "Multi-point measurement for future averaged planes"),
)

DEFAULT_MEASUREMENT_COLOR = (0.1, 0.65, 1.0, 1.0)
ACTIVE_MEASUREMENT_COLOR = (1.0, 0.9, 0.2, 1.0)


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
        "scientia_measure_show_all_handles",
        "scientia_measure_show_linear",
        "scientia_measure_show_planes",
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
    bpy.types.Scene.scientia_measure_show_all_handles = BoolProperty(name="All Point Handles", default=False)
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


def set_scene_measurement_points(measurement, points, kind=None):
    measurement.points.clear()
    for point in points:
        item = measurement.points.add()
        item.co = (float(point[0]), float(point[1]), float(point[2]))
    if kind is None:
        # Editing a point must not silently change POLYLINE into PLANE.
        current = str(getattr(measurement, "kind", "") or "")
        if current == "POLYLINE" and len(points) >= 3:
            kind = "POLYLINE"
        else:
            kind = kind_from_point_count(len(points))
    measurement.kind = kind


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
