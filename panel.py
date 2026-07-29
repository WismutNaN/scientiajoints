import math
import time

import bpy
from bpy.types import Menu, Operator, Panel
from .custom_measure_tool import active_measurement_record
from .scene_measurements import sync_scene_measurement_codes
from .parser import MeasurementsParser
from .visualization import Visualizer
import logging

logger = logging.getLogger(__name__)


class ScientiaAssignCodeOperator(Operator):
    bl_idname = "wm.scientia_measure_assign_code"
    bl_label = "Assign Measurement Code"
    bl_description = "Assign an existing code to the active measurement"
    bl_options = {'UNDO'}

    code: bpy.props.StringProperty(name="Code", default="")

    def execute(self, context):
        measurement = _active_measurement(context.scene)
        if measurement is None:
            self.report({'WARNING'}, "No active Scientia measurement.")
            return {'CANCELLED'}
        measurement.code = (self.code or "").strip()
        sync_scene_measurement_codes(context.scene)
        return {'FINISHED'}


class ScientiaClearCodeOperator(Operator):
    bl_idname = "wm.scientia_measure_clear_code"
    bl_label = "Clear Measurement Code"
    bl_description = "Move the active measurement to the No code group"
    bl_options = {'UNDO'}

    def execute(self, context):
        measurement = _active_measurement(context.scene)
        if measurement is None:
            self.report({'WARNING'}, "No active Scientia measurement.")
            return {'CANCELLED'}
        measurement.code = ""
        sync_scene_measurement_codes(context.scene)
        return {'FINISHED'}


class ScientiaMeasurementCodeMenu(Menu):
    bl_idname = "SCIENTIA_MT_measurement_codes"
    bl_label = "Measurement Codes"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        codes = list(getattr(scene, "scientia_measurement_codes", ()))
        if not codes:
            layout.label(text="No existing codes", icon="INFO")
            return
        for code in codes:
            name = (getattr(code, "name", "") or "").strip()
            if not name:
                continue
            operator = layout.operator("wm.scientia_measure_assign_code", text=name, icon="BOOKMARKS")
            operator.code = name


class MeasurementExporterPanel(Panel):
    bl_label = "ScientiaJoints"
    bl_idname = "OBJECT_PT_measurement_exporter"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'ScientiaJoints'

    def draw_header_preset(self, context):
        # Unobtrusive entry point: a single icon in the panel header opens the
        # full diagnostics report.
        row = self.layout.row(align=True)
        row.emboss = 'NONE'
        row.operator("wm.scientia_diagnostics", text="", icon='INFO')

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        _draw_dependency_banner(layout)
        _draw_visualization_buttons(layout, context)

        if hasattr(context.scene, "scientia_measurements"):
            _draw_measurement_info_panel(layout, context)
            _draw_measurement_display_panel(layout, context)

        _draw_azimuth_panel(layout, scene)
        _draw_export_panel(layout, scene)
        _draw_statistics_panel(layout, context)
        _draw_chart_settings_panel(layout, scene)


# Chart dependencies are checked by importing them, which is too slow to repeat
# on every panel redraw, so the answer is cached until something changes it.
_DEPENDENCY_CACHE_TTL_SECONDS = 5.0
_dependency_cache = {"time": 0.0, "missing": None}


def _missing_chart_packages():
    from . import dependencies

    now = time.monotonic()
    if (
        _dependency_cache["missing"] is not None
        and now - _dependency_cache["time"] < _DEPENDENCY_CACHE_TTL_SECONDS
    ):
        return _dependency_cache["missing"]

    missing = dependencies.missing_packages()
    _dependency_cache.update(time=now, missing=missing)
    return missing


def invalidate_dependency_cache():
    _dependency_cache.update(time=0.0, missing=None)


def _draw_dependency_banner(layout):
    """Tell the user in the panel why charts are unavailable.

    Without this the only sign of a failed install is a line in the system
    console, which most users never open.
    """
    from . import operators

    state = operators.install_state()
    if state.get("status") == "running":
        box = layout.box()
        box.label(text="Installing chart packages...", icon='SORTTIME')
        box.label(text="Blender stays usable; this can take a few minutes.")
        return

    missing = _missing_chart_packages()
    if not missing:
        if state.get("status") == "ok":
            invalidate_dependency_cache()
        return

    box = layout.box()
    box.label(text="Charts unavailable", icon='ERROR')
    box.label(text="Missing: " + ", ".join(missing))
    column = box.column(align=True)
    column.operator("wm.scientia_install_dependencies", icon='IMPORT')
    column.operator("wm.scientia_diagnostics", text="Diagnostics", icon='INFO')
    if state.get("status") == "failed" and state.get("message"):
        box.label(text=state["message"], icon='CANCEL')


def _draw_visualization_buttons(layout, context):
    scene = context.scene
    charts_available = not _missing_chart_packages()

    row = layout.row(align=True)
    row.enabled = charts_available

    subrow = row.row(align=True)
    subrow.operator("wm.show_histogram_image", text="Histogram", icon="SMOOTHCURVE")
    subrow.prop(scene, "real_time_update_histogram", text="", toggle=True, icon='FILE_REFRESH')

    subrow = row.row(align=True)
    subrow.operator("wm.show_stereonet_image", text="Stereonet", icon="SHADING_RENDERED")
    subrow.prop(scene, "real_time_update_stereonet", text="", toggle=True, icon='FILE_REFRESH')


def _draw_azimuth_panel(layout, scene):
    box = layout.box()
    box.prop(scene, "show_azimuth", text="Azimuth Correction", icon='TRIA_DOWN' if scene.show_azimuth else 'TRIA_RIGHT', emboss=False)
    if not scene.show_azimuth:
        return
    row = box.row(align=True)
    row.prop(scene, "az_real", text="Real")
    row.prop(scene, "az_model", text="Model")


def _draw_export_panel(layout, scene):
    box = layout.box()
    box.prop(scene, "show_export", text="Export", icon='TRIA_DOWN' if scene.show_export else 'TRIA_RIGHT', emboss=False)
    if not scene.show_export:
        return

    col = box.column(align=True)
    if not bpy.data.is_saved:
        col.label(text="Save the .blend file to enable export", icon="ERROR")
    row = col.row(align=True)
    row.operator('export.processed_edges', text='CSV Edges', icon="EXPORT")
    row.operator('export.processed_faces', text='CSV Faces', icon="EXPORT")
    row = col.row(align=True)
    row.operator('export.raw_edges', text='Raw Edges', icon="EXPORT")
    row.operator('export.raw_faces', text='Raw Faces', icon="EXPORT")


# Panels redraw on every mouse move, but statistics require a full re-parse of
# all measurement sources, so the payload is cached for a short time.
_STATS_CACHE_TTL_SECONDS = 1.0
_stats_cache = {"time": 0.0, "key": None, "payload": None}


def _statistics_payload(scene):
    key = (scene.az_real, scene.az_model)
    now = time.monotonic()
    if (
        _stats_cache["payload"] is not None
        and _stats_cache["key"] == key
        and now - _stats_cache["time"] < _STATS_CACHE_TTL_SECONDS
    ):
        return _stats_cache["payload"]

    parser = MeasurementsParser()
    processed_edges = parser.get_processed_edges(az_real=scene.az_real, az_model=scene.az_model)
    stats = Visualizer(processed_edges, []).get_edges_statistics() if processed_edges else {}
    degenerate = sum(
        1
        for record in parser.get_processed_face_records(az_real=scene.az_real, az_model=scene.az_model)
        if getattr(record, "degeneracy", "")
    )
    payload = {
        "degenerate": degenerate,
        "faces": len(parser.faces),
        "edges": len(parser.edges),
        "duplicates": parser.duplicate_strokes_count,
        "ignored": parser.ignored_strokes_count,
        "near_duplicates": len(getattr(parser, "near_duplicate_pairs", ()) or ()),
        "has_edges": bool(processed_edges),
        "stats": stats,
    }
    _stats_cache.update(time=now, key=key, payload=payload)
    return payload


def invalidate_statistics_cache():
    _stats_cache.update(time=0.0, key=None, payload=None)
    invalidate_dependency_cache()


def _draw_statistics_panel(layout, context):
    scene = context.scene
    box = layout.box()
    box.prop(scene, "show_statistics", text="Statistics", icon='TRIA_DOWN' if scene.show_statistics else 'TRIA_RIGHT', emboss=False)
    if not scene.show_statistics:
        return

    try:
        payload = _statistics_payload(scene)
        col = box.column(align=True)
        col.label(text=f"Faces: {payload['faces']}", icon="SNAP_FACE")
        col.label(text=f"Edges: {payload['edges']}", icon="MOD_EDGESPLIT")
        if payload["duplicates"]:
            col.label(text=f"Exact copies merged: {payload['duplicates']}", icon="INFO")
        if payload["near_duplicates"]:
            col.label(text=f"Nearly identical pairs: {payload['near_duplicates']}", icon="ERROR")
        if payload["degenerate"]:
            col.label(text=f"Planes without a valid orientation: {payload['degenerate']}", icon="ERROR")
        if payload["ignored"]:
            col.label(text=f"Ignored unsupported strokes: {payload['ignored']}", icon="ERROR")

        if not payload["has_edges"]:
            col.label(text="No processed edges for statistics.")
            return

        stats = payload["stats"]
        if not stats:
            col.label(text="Edge statistics unavailable; see console.")
            return

        col.separator()
        col.label(text="Edges Statistics:", icon="SMOOTHCURVE")
        row = col.row(align=True)
        row.label(text=f"Mean {stats['Mean']:.2f}")
        row.label(text=f"Median {stats['Median']:.2f}")
        row = col.row(align=True)
        row.label(text=f"Std {stats['Std Dev']:.2f}")
        row.label(text=f"Min {stats['Min']:.2f}")
        row.label(text=f"Max {stats['Max']:.2f}")
    except Exception as e:
        box.label(text="Error calculating statistics.")
        logger.error("Error calculating statistics: %s", e, exc_info=True)


def _draw_chart_settings_panel(layout, scene):
    box = layout.box()
    box.prop(scene, "show_display_settings", text="Chart Appearance", icon='TRIA_DOWN' if scene.show_display_settings else 'TRIA_RIGHT', emboss=False)
    if not scene.show_display_settings:
        return

    col = box.column(align=True)
    col.prop(scene, "update_interval", text="Auto update interval", icon="TIME")

    col.separator()
    col.label(text="Image Size")
    row = col.row(align=True)
    row.prop(scene, "figure_width", text="Width")
    row.prop(scene, "figure_height", text="Height")

    col.separator()
    col.label(text="Stereonet")
    row = col.row(align=True)
    row.prop(scene, "stereonet_hemisphere", expand=True)
    row = col.row(align=True)
    row.prop(scene, "marker_size", text="Pole size")
    row.prop(scene, "edge_width", text="Outline")
    row = col.row(align=True)
    row.prop(scene, "marker_face_color", text="Legacy pole")
    row.prop(scene, "marker_edge_color", text="Outline")
    col.prop(scene, "density_sigma", text="Density sigma")

    col.separator()
    col.label(text="Blender View")
    row = col.row(align=True)
    row.operator("wm.toggle_light_settings", text="Light", icon="LIGHT")


def init_properties():
    bpy.types.Scene.show_statistics = bpy.props.BoolProperty(name="Show Statistics", default=False)
    bpy.types.Scene.show_export = bpy.props.BoolProperty(name="Show Export", default=False)
    bpy.types.Scene.show_azimuth = bpy.props.BoolProperty(name="Show Azimuth", default=False)
    bpy.types.Scene.show_display_settings = bpy.props.BoolProperty(name="Show Display Settings", default=False)
    bpy.types.Scene.show_measurement_info = bpy.props.BoolProperty(name="Show Measurement Info", default=True)
    bpy.types.Scene.show_measurement_display_settings = bpy.props.BoolProperty(name="Show Measurement Display", default=False)
    bpy.types.Scene.show_label_field_settings = bpy.props.BoolProperty(name="Show Label Fields", default=False)

def clear_properties():
    for name in (
        "show_statistics",
        "show_export",
        "show_azimuth",
        "show_display_settings",
        "show_measurement_info",
        "show_measurement_display_settings",
        "show_label_field_settings",
    ):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)


def _draw_measurement_info_panel(layout, context):
    scene = context.scene
    box = layout.box()
    box.prop(scene, "show_measurement_info", text="Measurement Info", icon='TRIA_DOWN' if scene.show_measurement_info else 'TRIA_RIGHT', emboss=False)
    if not scene.show_measurement_info:
        return

    row = box.row(align=True)
    row.label(text=f"Measurements: {len(scene.scientia_measurements)}", icon="EMPTY_AXIS")
    row.operator("wm.scientia_measure_deselect", text="", icon="RESTRICT_SELECT_ON")
    row.operator("wm.scientia_measure_delete_active", text="", icon="TRASH")

    measurement = _active_measurement(scene)
    if measurement is None:
        box.label(text="No active measurement.", icon="INFO")
        return

    record = active_measurement_record(scene)
    col = box.column(align=True)
    row = col.row(align=True)
    row.prop(measurement, "code", text="Code")
    row.menu("SCIENTIA_MT_measurement_codes", text="", icon="DOWNARROW_HLT")
    row.operator("wm.scientia_measure_clear_code", text="", icon="X")

    row = col.row(align=True)
    row.prop(measurement, "name", text="Name")

    col.prop(measurement, "description", text="Description")

    if record is None:
        col.label(text="Calculated values unavailable.", icon="ERROR")
        return

    if record.kind.value == "linear":
        _draw_linear_record_info(col, record)
    elif record.kind.value == "plane":
        _draw_plane_record_info(col, record)


def _draw_measurement_display_panel(layout, context):
    scene = context.scene
    box = layout.box()
    box.prop(
        scene,
        "show_measurement_display_settings",
        text="Measurement Display",
        icon='TRIA_DOWN' if scene.show_measurement_display_settings else 'TRIA_RIGHT',
        emboss=False,
    )
    if not scene.show_measurement_display_settings:
        return

    col = box.column(align=True)
    row = col.row(align=True)
    row.prop(scene, "scientia_measure_show_linear", text="Linear", toggle=True, icon="MOD_EDGESPLIT")
    row.prop(scene, "scientia_measure_show_planes", text="Planes", toggle=True, icon="SNAP_FACE")

    col.separator()
    row = col.row(align=True)
    row.prop(scene, "scientia_measure_show_labels", text="Labels", toggle=True)
    row.prop(scene, "scientia_measure_label_background", text="Background", toggle=True)
    row = col.row(align=True)
    row.prop(scene, "scientia_measure_reuse_last_code", text="Reuse Code", toggle=True)
    row.prop(scene, "scientia_measure_snap_by_default", text="Snap", toggle=True)
    row = col.row(align=True)
    row.prop(scene, "scientia_measure_show_all_handles", text="All Handles", toggle=True)

    _draw_label_field_settings(col, scene)

    col.separator()
    row = col.row(align=True)
    row.label(text="Active", icon="RESTRICT_SELECT_OFF")
    row.prop(scene, "scientia_measure_active_color", text="")

    col.separator()
    _draw_code_style_row(col, "No code", scene, "scientia_measure_no_code_visible", "scientia_measure_default_color")

    codes = getattr(scene, "scientia_measurement_codes", ())
    for code in codes:
        _draw_code_style_row(col, code.name or "<empty>", code, "visible", "color")


def _draw_label_field_settings(layout, scene):
    layout.separator()
    layout.prop(
        scene,
        "show_label_field_settings",
        text="Label Fields",
        icon='TRIA_DOWN' if scene.show_label_field_settings else 'TRIA_RIGHT',
        emboss=False,
    )
    if not scene.show_label_field_settings:
        return

    row = layout.row(align=True)
    row.prop(scene, "scientia_label_show_code", text="Code", toggle=True)
    row.prop(scene, "scientia_label_show_name", text="Name", toggle=True)
    row.prop(scene, "scientia_label_show_description", text="Description", toggle=True)

    layout.label(text="Linear")
    row = layout.row(align=True)
    row.prop(scene, "scientia_label_linear_distance", text="Distance", toggle=True)
    row.prop(scene, "scientia_label_linear_angle", text="Angle", toggle=True)
    row = layout.row(align=True)
    row.prop(scene, "scientia_label_linear_azimuth", text="Az", toggle=True)
    row.prop(scene, "scientia_label_linear_raw_azimuth", text="Raw Az", toggle=True)
    row = layout.row(align=True)
    row.prop(scene, "scientia_label_linear_dx", text="dX", toggle=True)
    row.prop(scene, "scientia_label_linear_dy", text="dY", toggle=True)
    row.prop(scene, "scientia_label_linear_dz", text="dZ", toggle=True)
    row = layout.row(align=True)
    row.prop(scene, "scientia_label_linear_horizontal", text="Horizontal", toggle=True)

    layout.label(text="Plane")
    row = layout.row(align=True)
    row.prop(scene, "scientia_label_plane_dip", text="Dip", toggle=True)
    row.prop(scene, "scientia_label_plane_azimuth", text="Az", toggle=True)
    row = layout.row(align=True)
    row.prop(scene, "scientia_label_plane_raw_azimuth", text="Raw Az", toggle=True)
    row.prop(scene, "scientia_label_plane_angle", text="Point Angle", toggle=True)
    row.prop(scene, "scientia_label_plane_area", text="Area", toggle=True)
    row = layout.row(align=True)
    row.prop(scene, "scientia_label_plane_fit_error", text="Fit Error", toggle=True)


def _draw_code_style_row(layout, label, owner, visible_property, color_property):
    row = layout.row(align=True)
    visible = getattr(owner, visible_property, True)
    row.prop(owner, visible_property, text="", icon='HIDE_OFF' if visible else 'HIDE_ON')
    row.label(text=label)
    row.prop(owner, color_property, text="")


def _draw_linear_record_info(layout, record):
    line = record.line_orientation
    p1, p2 = record.points[:2]
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    dz = p2.z - p1.z
    horizontal = math.sqrt(dx * dx + dy * dy)

    row = layout.row(align=True)
    row.label(text=f"Distance {record.length:.3f}")
    row.label(text=f"Angle {line.dip:.1f}")
    row = layout.row(align=True)
    row.label(text=f"Az {line.rotated_azimuth:.1f}")
    row.label(text=f"Raw {line.azimuth:.1f}")
    row = layout.row(align=True)
    row.label(text=f"dx {dx:.3f}")
    row.label(text=f"dy {dy:.3f}")
    row.label(text=f"dz {dz:.3f}")
    layout.label(text=f"Horizontal {horizontal:.3f}")


def _draw_plane_record_info(layout, record):
    plane = record.plane_orientation
    degeneracy = getattr(record, "degeneracy", "")
    if degeneracy:
        box = layout.box()
        box.label(text="Orientation is arbitrary", icon="ERROR")
        box.label(text=degeneracy)

    row = layout.row(align=True)
    row.label(text=f"Dip {plane.dip:.1f}")
    row.label(text=f"Az {plane.rotated_azimuth:.1f}")
    row = layout.row(align=True)
    row.label(text=f"Raw {plane.azimuth:.1f}")
    point_count = len(getattr(record, "points", ()) or ())
    if record.degree is None:
        row.label(text=f"Points {point_count}")
    else:
        row.label(text=f"Angle {record.degree:.1f}")
    row = layout.row(align=True)
    row.label(text=f"Area {record.area:.4f}")
    if point_count > 3 and record.fit_error is not None:
        relative = record.fit_error_relative or 0.0
        icon = "ERROR" if relative > 0.1 else "CHECKMARK"
        layout.label(
            text=f"Fit error {record.fit_error:.4f} ({relative * 100:.1f}%)",
            icon=icon,
        )


def _active_measurement(scene):
    measurements = getattr(scene, "scientia_measurements", None)
    if measurements is None:
        return None
    index = getattr(scene, "scientia_active_measurement_index", -1)
    if index < 0 or index >= len(measurements):
        return None
    return measurements[index]
