import logging
import os

import bpy

from .application import ExportResult, MeasurementApplicationService
from .domain.measurements import MeasurementKind, MeasurementSet, ParseDiagnostics, Point3D, RawMeasurement
from .infrastructure.blender_annotations import (
    BlenderAnnotationSource,
    find_annotation_layer,
    iter_annotation_datablocks as _iter_annotation_datablocks,
    iter_layer_strokes as _iter_layer_strokes,
    stroke_points as _stroke_points,
    unique_id_iter as _unique_id_iter,
)
from .infrastructure.blender_scene_measurements import CompositeMeasurementSource, SceneMeasurementSource
from .infrastructure.exporters import (
    ProcessedEdgeCsvWriter,
    ProcessedFaceCsvWriter,
    RawEdgeTxtWriter,
    RawFaceTxtWriter,
)

logger = logging.getLogger(__name__)


class EdgeView:
    """Legacy-shaped processed edge object for UI and visualization."""

    def __init__(self, record):
        self.record = record
        self.point1 = record.points[0]
        self.point2 = record.points[1]
        self.center = record.center
        self.length = record.length
        self.azimuth = record.line_orientation.azimuth
        self.dip = record.line_orientation.dip
        self.edge_azimuth = record.edge_orientation.azimuth
        self.edge_dip = record.edge_orientation.dip
        self.rotated_azimuth = record.line_orientation.rotated_azimuth
        self.layer = record.layer
        self.name = _record_property(record, "name")
        self.code = _record_property(record, "code")
        self.description = _record_property(record, "description")
        self.color = _record_color(record)

    def __str__(self):
        return '{}\t{:.2f}\t{:.2f}\t{:.2f}\t{:.2f}\t{:.2f}\t{:.4f}'.format(
            self.center, self.azimuth, self.dip, self.edge_azimuth,
            self.edge_dip, self.rotated_azimuth, self.length
        )


class FaceView:
    """Legacy-shaped processed face object for UI and visualization."""

    def __init__(self, record):
        self.record = record
        self.point1 = record.points[0]
        self.point2 = record.points[1]
        self.point3 = record.points[2]
        self.point_count = len(record.points)
        self.center = record.center
        self.azimuth = record.plane_orientation.azimuth
        self.dip = record.plane_orientation.dip
        self.rotated_azimuth = record.plane_orientation.rotated_azimuth
        self.area = record.area
        self.degree = record.degree
        self.fit_error = record.fit_error
        self.fit_error_relative = record.fit_error_relative
        self.degeneracy = getattr(record, "degeneracy", "")
        self.layer = record.layer
        self.name = _record_property(record, "name")
        self.code = _record_property(record, "code")
        self.description = _record_property(record, "description")
        self.color = _record_color(record)

    def __str__(self):
        degree_text = "" if self.degree is None else "{:.1f}".format(self.degree)
        return '{}\t{:.2f}\t{:.2f}\t{:.2f}\t{:.4f}\t{}'.format(
            self.center, self.azimuth, self.dip,
            self.rotated_azimuth, self.area, degree_text
        )


def _default_export_path(suffix: str) -> str:
    filepath = getattr(bpy.data, "filepath", "")
    root, ext = os.path.splitext(filepath)
    if ext.lower() == ".blend":
        return f"{root}{suffix}"
    return f"{filepath}{suffix}"


def _point_signature(point: object, precision: int = 6):
    return Point3D.from_object(point).signature(precision=precision)


def _measurement_signature(points, precision: int = 6):
    return tuple(_point_signature(point, precision=precision) for point in points)


def _create_default_service():
    return MeasurementApplicationService(
        source=CompositeMeasurementSource((
            SceneMeasurementSource(),
            BlenderAnnotationSource("RulerData3D"),
        )),
        raw_edge_writer=RawEdgeTxtWriter(),
        raw_face_writer=RawFaceTxtWriter(),
        processed_edge_writer=ProcessedEdgeCsvWriter(),
        processed_face_writer=ProcessedFaceCsvWriter(),
    )


class MeasurementsParser:
    """Compatibility facade over the DDD application layer.

    Public attributes and methods are intentionally kept close to the previous
    parser so existing Blender operators, visualization code, and user scripts
    keep working while ingestion/processing/export move behind use-case services.
    """

    def __init__(self, service=None):
        self.service = service or _create_default_service()
        self.faces = []
        self.edges = []
        self.measurement_set = None
        self.total_strokes_count = 0
        self.duplicate_strokes_count = 0
        self.ignored_strokes_count = 0
        self.layer_found = False
        self.diagnostic_messages = []
        self.near_duplicate_pairs = ()
        self.parse_dimensions()

    def parse_dimensions(self):
        self.faces = []
        self.edges = []
        self.measurement_set = self.service.ingest_measurements()

        diagnostics = self.measurement_set.diagnostics
        self.total_strokes_count = diagnostics.total_strokes_count
        self.duplicate_strokes_count = diagnostics.duplicate_strokes_count
        self.ignored_strokes_count = diagnostics.ignored_strokes_count
        self.layer_found = diagnostics.layer_found
        self.diagnostic_messages = list(diagnostics.messages)
        self.near_duplicate_pairs = tuple(diagnostics.near_duplicate_pairs)

        for raw in self.measurement_set.raw_measurements:
            if raw.kind == MeasurementKind.PLANE:
                self.faces.append(list(raw.points))
            elif raw.kind == MeasurementKind.LINEAR:
                self.edges.append(list(raw.points))

        logger.info("Parsed %d faces and %d edges.", len(self.faces), len(self.edges))

    def export_raw_edges(self, filename=None):
        if not bpy.data.is_saved:
            self.show_save_prompt()
            return ExportResult(False, None, "Save the Blender file before exporting raw edges.")

        self._ensure_ready()
        filename = filename or _default_export_path("_edges_raw.txt")
        return self.service.export_raw_edges(self.measurement_set, filename)

    def export_raw_faces(self, filename=None):
        if not bpy.data.is_saved:
            self.show_save_prompt()
            return ExportResult(False, None, "Save the Blender file before exporting raw faces.")

        self._ensure_ready()
        filename = filename or _default_export_path("_faces_raw.txt")
        return self.service.export_raw_faces(self.measurement_set, filename)

    def process_edges(self, az_real=0, az_model=0, filename=None):
        if not bpy.data.is_saved:
            self.show_save_prompt()
            return ExportResult(False, None, "Save the Blender file before exporting processed edges.")

        self._ensure_ready()
        filename = filename or _default_export_path("_edges_processed.csv")
        records = self.get_processed_edge_records(az_real=az_real, az_model=az_model)
        return self.service.export_processed_edges(records, filename)

    def process_faces(self, az_real=0, az_model=0, filename=None):
        if not bpy.data.is_saved:
            self.show_save_prompt()
            return ExportResult(False, None, "Save the Blender file before exporting processed faces.")

        self._ensure_ready()
        filename = filename or _default_export_path("_faces_processed.csv")
        records = self.get_processed_face_records(az_real=az_real, az_model=az_model)
        return self.service.export_processed_faces(records, filename)

    def get_processed_edge_records(self, az_real=0, az_model=0):
        self._ensure_ready()
        return self.service.process_edges(self.measurement_set, az_real=az_real, az_model=az_model)

    def get_processed_face_records(self, az_real=0, az_model=0):
        self._ensure_ready()
        return self.service.process_faces(self.measurement_set, az_real=az_real, az_model=az_model)

    def get_processed_edges(self, az_real=0, az_model=0):
        return [
            _edge_record_to_legacy_edge(record)
            for record in self.get_processed_edge_records(az_real=az_real, az_model=az_model)
        ]

    def get_processed_faces(self, az_real=0, az_model=0):
        return [
            _face_record_to_legacy_face(record)
            for record in self.get_processed_face_records(az_real=az_real, az_model=az_model)
        ]

    def show_save_prompt(self):
        logger.warning("Please save your Blender file before exporting.")
        bpy.ops.wm.save_mainfile('INVOKE_DEFAULT')

    def _ensure_ready(self):
        if not hasattr(self, "service") or self.service is None:
            self.service = _create_default_service()
        if not hasattr(self, "measurement_set") or self.measurement_set is None:
            self.measurement_set = _measurement_set_from_legacy_lists(
                getattr(self, "edges", []),
                getattr(self, "faces", []),
            )


def _edge_record_to_legacy_edge(record):
    return EdgeView(record)


def _face_record_to_legacy_face(record):
    return FaceView(record)


def _record_property(record, key, default=""):
    values = getattr(getattr(record, "properties", None), "values", {}) or {}
    return values.get(key, default)


def _record_color(record):
    values = getattr(getattr(record, "properties", None), "values", {}) or {}
    color = values.get("display_color") or values.get("color")
    if color is None:
        return None
    try:
        return tuple(float(channel) for channel in color)
    except Exception:
        return None


def _measurement_set_from_legacy_lists(edges, faces):
    raw_measurements = []
    for index, edge in enumerate(edges):
        raw_measurements.append(
            RawMeasurement(
                kind=MeasurementKind.LINEAR,
                points=tuple(Point3D.from_object(point) for point in edge),
                source="LegacyParser",
                source_id=f"legacy-edge:{index}",
            )
        )
    for index, face in enumerate(faces):
        raw_measurements.append(
            RawMeasurement(
                kind=MeasurementKind.PLANE,
                points=tuple(Point3D.from_object(point) for point in face),
                source="LegacyParser",
                source_id=f"legacy-face:{index}",
            )
        )

    return MeasurementSet(
        raw_measurements=tuple(raw_measurements),
        diagnostics=ParseDiagnostics(
            layer_found=True,
            total_strokes_count=len(raw_measurements),
        ),
    )
