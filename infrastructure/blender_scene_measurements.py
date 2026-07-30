import logging
import sys

import bpy

from ..application.services import SourceReadResult, StrokeInput
from ..domain.measurements import MeasurementKind, MeasurementProperties, Point3D
from ..scene_measurements import measurement_custom_properties, scene_measurement_code_visible

logger = logging.getLogger(__name__)


def _bpy():
    return sys.modules.get("bpy", bpy)


class SceneMeasurementSource:
    """Read ScientiaJoints measurements stored directly on bpy.types.Scene."""

    def __init__(self, scene_getter=None):
        self.scene_getter = scene_getter

    def _scene(self):
        if self.scene_getter is not None:
            return self.scene_getter()
        return getattr(_bpy().context, "scene", None)

    def read_strokes(self) -> SourceReadResult:
        scene = self._scene()
        if scene is None or not hasattr(scene, "scientia_measurements"):
            return SourceReadResult(False)

        strokes = []
        measurements = getattr(scene, "scientia_measurements", ())
        hidden_count = 0

        for index, measurement in enumerate(measurements):
            # Visibility is a viewport filter only. Hiding a code group or a
            # layer to declutter the viewport must never silently shrink an
            # export, so hidden measurements are counted and still read.
            if not scene_measurement_code_visible(scene, getattr(measurement, "code", "")):
                hidden_count += 1
            layer = getattr(measurement, "layer", "Default") or "Default"

            points = []
            for point in getattr(measurement, "points", ()):
                co = getattr(point, "co", None)
                if co is None or len(co) < 3:
                    continue
                points.append(Point3D(float(co[0]), float(co[1]), float(co[2])))

            if not points:
                continue

            source_id = getattr(measurement, "uuid", "") or f"scene-measurement:{index}"
            properties = MeasurementProperties(measurement_custom_properties(measurement))
            strokes.append(
                StrokeInput(
                    points=tuple(points),
                    source="ScientiaScene",
                    source_id=source_id,
                    layer=layer,
                    properties=properties,
                    kind_hint=_measurement_kind_hint(measurement, len(points)),
                )
            )

        messages = ()
        if hidden_count:
            messages = (
                f"{hidden_count} Scientia measurements are hidden in the viewport; "
                "they are still processed and exported.",
            )

        if strokes:
            logger.info("Read %d Scientia scene measurements.", len(strokes))
            return SourceReadResult(True, strokes=tuple(strokes), messages=messages)
        return SourceReadResult(False)


class CompositeMeasurementSource:
    """Merge multiple measurement sources while keeping missing optional sources quiet."""

    def __init__(self, sources):
        self.sources = tuple(sources)

    def read_strokes(self) -> SourceReadResult:
        strokes = []
        messages = []
        missing_messages = []
        layer_found = False

        for source in self.sources:
            result = source.read_strokes()
            if result.layer_found:
                layer_found = True
                strokes.extend(result.strokes)
                messages.extend(result.messages)
            else:
                missing_messages.extend(result.messages)

        if not layer_found:
            messages.extend(missing_messages)

        return SourceReadResult(layer_found, strokes=tuple(strokes), messages=tuple(messages))


def _measurement_kind_hint(measurement, point_count):
    kind = str(getattr(measurement, "kind", "") or "").upper()
    if kind == "LINEAR" and point_count == 2:
        return MeasurementKind.LINEAR
    if kind == "TRACE" and point_count >= 2:
        return MeasurementKind.TRACE
    if kind in {"PLANE", "POLYLINE"} and point_count >= 3:
        return MeasurementKind.PLANE
    return None
