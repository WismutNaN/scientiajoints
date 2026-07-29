import logging
from dataclasses import dataclass, field
from typing import Optional, Tuple

from ..domain.geometry import process_linear_measurement, process_plane_measurement
from ..domain.measurements import (
    AzimuthCorrection,
    MeasurementKind,
    MeasurementProperties,
    MeasurementSet,
    ParseDiagnostics,
    Point3D,
    RawMeasurement,
)

logger = logging.getLogger(__name__)

#: Decimal places used to detect near-duplicate measurements. Three places is
#: one millimetre in a metre-scale model, small enough not to merge separate
#: fractures and large enough to catch a nudged copy.
NEAR_DUPLICATE_PRECISION = 3


@dataclass(frozen=True)
class ExportResult:
    ok: bool
    filename: Optional[str]
    message: str


@dataclass(frozen=True)
class StrokeInput:
    points: Tuple[Point3D, ...]
    source: str = "RulerData3D"
    source_id: str = ""
    layer: str = "Default"
    properties: MeasurementProperties = field(default_factory=MeasurementProperties)
    kind_hint: Optional[MeasurementKind] = None


@dataclass(frozen=True)
class SourceReadResult:
    layer_found: bool
    strokes: Tuple[StrokeInput, ...] = ()
    messages: Tuple[str, ...] = ()


class MeasurementApplicationService:
    def __init__(self, source, raw_edge_writer=None, raw_face_writer=None,
                 processed_edge_writer=None, processed_face_writer=None):
        self.source = source
        self.raw_edge_writer = raw_edge_writer
        self.raw_face_writer = raw_face_writer
        self.processed_edge_writer = processed_edge_writer
        self.processed_face_writer = processed_face_writer

    def ingest_measurements(self) -> MeasurementSet:
        source_result = self.source.read_strokes()
        if not source_result.layer_found:
            return MeasurementSet(
                raw_measurements=(),
                diagnostics=ParseDiagnostics(
                    layer_found=False,
                    messages=tuple(source_result.messages) or ("RulerData3D layer not found.",),
                ),
            )

        raw_measurements = []
        seen = set()
        near_seen = {}
        near_duplicate_pairs = []
        duplicate_count = 0
        ignored_count = 0
        messages = list(source_result.messages)

        for stroke in source_result.strokes:
            point_count = len(stroke.points)
            if stroke.kind_hint == MeasurementKind.LINEAR and point_count == 2:
                kind = MeasurementKind.LINEAR
            elif stroke.kind_hint == MeasurementKind.PLANE and point_count >= 3:
                kind = MeasurementKind.PLANE
            elif stroke.kind_hint is None and point_count == 2:
                kind = MeasurementKind.LINEAR
            elif stroke.kind_hint is None and point_count == 3:
                kind = MeasurementKind.PLANE
            else:
                ignored_count += 1
                logger.debug("Stroke with %d points ignored (expected 2, 3, or plane hint).", point_count)
                continue

            raw = RawMeasurement(
                kind=kind,
                points=stroke.points,
                source=stroke.source,
                source_id=stroke.source_id,
                layer=stroke.layer,
                properties=stroke.properties,
            )
            signature = raw.signature()
            if signature in seen:
                duplicate_count += 1
                logger.debug("Duplicate measurement skipped: %s", signature)
                continue
            seen.add(signature)

            near_signature = raw.near_signature(precision=NEAR_DUPLICATE_PRECISION)
            previous_id = near_seen.get(near_signature)
            if previous_id is None:
                near_seen[near_signature] = raw.source_id or raw.signature()
            else:
                near_duplicate_pairs.append((str(previous_id), str(raw.source_id or "")))

            raw_measurements.append(raw)

        if duplicate_count:
            message = f"Skipped {duplicate_count} duplicate ruler strokes."
            messages.append(message)
            logger.warning(message)
        if ignored_count:
            message = f"Ignored {ignored_count} unsupported ruler strokes."
            messages.append(message)
            logger.warning(message)
        if near_duplicate_pairs:
            message = (
                f"{len(near_duplicate_pairs)} measurement pairs are nearly identical and were all kept. "
                "Check them for accidental copies."
            )
            messages.append(message)
            logger.warning(message)

        return MeasurementSet(
            raw_measurements=tuple(raw_measurements),
            diagnostics=ParseDiagnostics(
                layer_found=True,
                total_strokes_count=len(source_result.strokes),
                duplicate_strokes_count=duplicate_count,
                ignored_strokes_count=ignored_count,
                messages=tuple(messages),
                near_duplicate_pairs=tuple(near_duplicate_pairs),
            ),
        )

    def process_edges(self, measurements: MeasurementSet, az_real=0, az_model=0):
        correction = AzimuthCorrection(az_real=az_real, az_model=az_model)
        return tuple(process_linear_measurement(raw, correction) for raw in measurements.edges)

    def process_faces(self, measurements: MeasurementSet, az_real=0, az_model=0):
        correction = AzimuthCorrection(az_real=az_real, az_model=az_model)
        return tuple(process_plane_measurement(raw, correction) for raw in measurements.faces)

    def export_raw_edges(self, measurements: MeasurementSet, filename: str) -> ExportResult:
        return self._write(self.raw_edge_writer, measurements.edges, filename, "Raw edges")

    def export_raw_faces(self, measurements: MeasurementSet, filename: str) -> ExportResult:
        return self._write(self.raw_face_writer, measurements.faces, filename, "Raw faces")

    def export_processed_edges(self, records, filename: str) -> ExportResult:
        return self._write(self.processed_edge_writer, records, filename, "Processed edges")

    def export_processed_faces(self, records, filename: str) -> ExportResult:
        return self._write(self.processed_face_writer, records, filename, "Processed faces")

    def _write(self, writer, rows, filename: str, label: str) -> ExportResult:
        if writer is None:
            return ExportResult(False, filename, f"{label} writer is not configured.")
        try:
            writer.write(filename, rows)
            logger.info("%s exported to %s", label, filename)
            return ExportResult(True, filename, f"{label} exported to {filename}.")
        except Exception as e:
            logger.error("Failed to export %s to %s: %s", label, filename, e)
            return ExportResult(False, filename, f"Failed to export {label.lower()}: {e}")
