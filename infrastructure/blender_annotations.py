import logging
import sys
from typing import Iterable, Optional, Tuple

import bpy

from ..application.services import SourceReadResult, StrokeInput
from ..domain.measurements import Point3D

logger = logging.getLogger(__name__)


def _bpy():
    return sys.modules.get("bpy", bpy)


def iter_annotation_datablocks() -> Iterable[object]:
    """Yield available annotation/grease-pencil datablocks across Blender versions."""
    current_bpy = _bpy()

    if hasattr(current_bpy.data, "annotations"):
        try:
            for ann in current_bpy.data.annotations:
                yield ann
        except Exception:
            pass

    if hasattr(current_bpy.data, "grease_pencils"):
        try:
            for gp in current_bpy.data.grease_pencils:
                yield gp
        except Exception:
            pass

    try:
        scene = current_bpy.context.scene
        if scene:
            for attr in ("annotation", "annotations", "grease_pencil"):
                if hasattr(scene, attr):
                    value = getattr(scene, attr)
                    if not value:
                        continue
                    if isinstance(value, (list, tuple)):
                        for item in value:
                            if item:
                                yield item
                    else:
                        yield value
    except Exception:
        pass


def unique_id_iter(items: Iterable[object]) -> Iterable[object]:
    seen = set()
    for item in items:
        try:
            key = item.as_pointer()
        except Exception:
            key = id(item)
        if key in seen:
            continue
        seen.add(key)
        yield item


def find_annotation_layer(layer_name: str = "RulerData3D") -> Tuple[Optional[object], Optional[object]]:
    """Find an annotation/grease-pencil layer by name/info across Blender versions."""
    for datablock in unique_id_iter(iter_annotation_datablocks()):
        layers = getattr(datablock, "layers", None)
        if not layers:
            continue

        try:
            if hasattr(layers, "get"):
                layer = layers.get(layer_name)
                if layer:
                    return datablock, layer
        except Exception:
            pass

        try:
            layer = layers[layer_name]
            if layer:
                return datablock, layer
        except Exception:
            pass

        try:
            for layer in layers:
                lname = getattr(layer, "info", None) or getattr(layer, "name", None) or ""
                if str(lname) == layer_name or str(lname).startswith(layer_name):
                    return datablock, layer
        except Exception:
            pass

    return None, None


def iter_layer_strokes_with_frames(layer: object) -> Iterable[Tuple[Optional[int], object]]:
    """Yield ``(frame_number, stroke)`` from a RulerData3D-like layer.

    Blender keeps annotations per timeline frame and copies the existing
    strokes into a new frame when the current frame changes while drawing, so
    the same ruler can appear several times. The frame number travels with the
    stroke to make that visible in diagnostics instead of silently inflating
    the measurement count.
    """
    seen = set()

    def yield_unique(strokes, frame_number):
        try:
            iterator = iter(strokes)
        except TypeError:
            return

        for stroke in iterator:
            try:
                key = stroke.as_pointer()
            except Exception:
                key = id(stroke)
            if key in seen:
                continue
            seen.add(key)
            yield frame_number, stroke

    frames = getattr(layer, "frames", None)
    if frames is None:
        for container in (layer, getattr(layer, "drawing", None)):
            if container is None:
                continue
            strokes = getattr(container, "strokes", None)
            if strokes is None:
                continue
            yield from yield_unique(strokes, None)
        return

    try:
        frame_iter = iter(frames)
    except TypeError:
        logger.debug("Layer frames object is not iterable: %r", frames)
        return

    for frame in frame_iter:
        frame_number = getattr(frame, "frame_number", None)
        try:
            for container in (frame, getattr(frame, "drawing", None)):
                if container is None:
                    continue
                strokes = getattr(container, "strokes", None)
                if strokes is None:
                    continue
                yield from yield_unique(strokes, frame_number)
        except Exception as e:
            logger.debug("Failed to read strokes from frame %r: %s", frame, e)


def iter_layer_strokes(layer: object) -> Iterable[object]:
    """Yield strokes from a RulerData3D-like layer across API variants."""
    for _frame_number, stroke in iter_layer_strokes_with_frames(layer):
        yield stroke


def annotation_layer_summary(layer_name: str = "RulerData3D") -> dict:
    """Describe the ruler layer for the diagnostics report."""
    datablock, layer = find_annotation_layer(layer_name)
    if layer is None:
        return {"found": False, "stroke_count": 0, "frame_count": 0, "frame_numbers": ()}

    frame_numbers = []
    stroke_count = 0
    for frame_number, _stroke in iter_layer_strokes_with_frames(layer):
        stroke_count += 1
        if frame_number is not None and frame_number not in frame_numbers:
            frame_numbers.append(frame_number)

    return {
        "found": True,
        "datablock": getattr(datablock, "name", "<unknown>"),
        "stroke_count": stroke_count,
        "frame_count": len(frame_numbers) or (1 if stroke_count else 0),
        "frame_numbers": tuple(sorted(frame_numbers)),
    }


def stroke_points(stroke: object):
    points = getattr(stroke, "points", None)
    if points is not None:
        return points
    points = getattr(stroke, "points3d", None)
    if points is not None:
        return points
    return []


class BlenderAnnotationSource:
    def __init__(self, layer_name: str = "RulerData3D"):
        self.layer_name = layer_name

    def read_strokes(self) -> SourceReadResult:
        datablock, layer = find_annotation_layer(self.layer_name)
        if layer is None:
            message = self._missing_layer_message()
            short_message = f"{self.layer_name} layer not found."
            logger.warning(message)
            return SourceReadResult(False, messages=(short_message, message))

        logger.info(
            "Ruler layer found in datablock '%s'.",
            getattr(datablock, "name", "<unknown>"),
        )

        strokes = []
        frame_numbers = []
        for index, (frame_number, stroke) in enumerate(iter_layer_strokes_with_frames(layer)):
            points = tuple(Point3D.from_object(point) for point in stroke_points(stroke))
            frame_tag = "-" if frame_number is None else str(frame_number)
            if frame_number is not None and frame_number not in frame_numbers:
                frame_numbers.append(frame_number)
            try:
                source_id = f"{self.layer_name}:f{frame_tag}:{stroke.as_pointer()}"
            except Exception:
                source_id = f"{self.layer_name}:f{frame_tag}:stroke:{index}"
            strokes.append(
                StrokeInput(
                    points=points,
                    source=self.layer_name,
                    source_id=source_id,
                    layer="Default",
                )
            )

        messages = ()
        if len(frame_numbers) > 1:
            messages = (
                "Ruler annotations exist on {} timeline frames ({}). Identical copies are removed, "
                "but a copy that was moved afterwards stays as a separate measurement.".format(
                    len(frame_numbers),
                    ", ".join(str(number) for number in sorted(frame_numbers)),
                ),
            )
            logger.warning(messages[0])

        return SourceReadResult(True, strokes=tuple(strokes), messages=messages)

    def _missing_layer_message(self):
        try:
            debug_blocks = []
            for datablock in unique_id_iter(iter_annotation_datablocks()):
                db_name = getattr(datablock, "name", "<no-name>")
                layer_names = []
                layers = getattr(datablock, "layers", None)
                if layers:
                    try:
                        for layer in layers:
                            lname = getattr(layer, "info", None) or getattr(layer, "name", None) or ""
                            layer_names.append(str(lname))
                    except Exception:
                        layer_names.append("<layers-iteration-failed>")
                debug_blocks.append((db_name, layer_names))
            return (
                f"No annotations or '{self.layer_name}' layer found. "
                f"Available annotation datablocks/layers: {debug_blocks}"
            )
        except Exception:
            return f"No annotations or '{self.layer_name}' layer found."
