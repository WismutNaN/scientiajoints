import bpy
import csv
from typing import Iterable, Optional, Tuple

from .geometry import Point, Vector3D, Face, Edge
import logging

logger = logging.getLogger(__name__)


def _iter_annotation_datablocks() -> Iterable[object]:
    """Yield available annotation/grease-pencil datablocks across Blender versions.

    Blender 5.0+: Annotations were renamed (Grease Pencil -> Annotation) and may live in
    bpy.data.annotations, while older versions store them in bpy.data.grease_pencils.
    We also try scene-linked pointers as a fallback.
    """
    # Blender 5.0+ (renamed collection)
    if hasattr(bpy.data, "annotations"):
        try:
            for ann in bpy.data.annotations:
                yield ann
        except Exception:
            pass

    # Blender <=4.x (legacy name)
    if hasattr(bpy.data, "grease_pencils"):
        try:
            for gp in bpy.data.grease_pencils:
                yield gp
        except Exception:
            pass

    # Scene-linked pointers (varies by version)
    try:
        scene = bpy.context.scene
        if scene:
            for attr in ("annotation", "annotations", "grease_pencil"):
                if hasattr(scene, attr):
                    v = getattr(scene, attr)
                    if not v:
                        continue
                    # Some builds may store a collection, some a single datablock
                    if isinstance(v, (list, tuple)):
                        for item in v:
                            if item:
                                yield item
                    else:
                        yield v
    except Exception:
        pass


def _unique_id_iter(items: Iterable[object]) -> Iterable[object]:
    seen = set()
    for it in items:
        try:
            key = it.as_pointer()
        except Exception:
            key = id(it)
        if key in seen:
            continue
        seen.add(key)
        yield it


def find_annotation_layer(layer_name: str = "RulerData3D") -> Tuple[Optional[object], Optional[object]]:
    """Find an annotation/grease-pencil layer by name/info across Blender versions."""
    for datablock in _unique_id_iter(_iter_annotation_datablocks()):
        layers = getattr(datablock, "layers", None)
        if not layers:
            continue

        # Fast path: collection.get
        try:
            if hasattr(layers, "get"):
                layer = layers.get(layer_name)
                if layer:
                    return datablock, layer
        except Exception:
            pass

        # Legacy indexing path
        try:
            layer = layers[layer_name]
            if layer:
                return datablock, layer
        except Exception:
            pass

        # Fallback: iterate layers and compare 'info'/'name'
        try:
            for layer in layers:
                lname = getattr(layer, "info", None) or getattr(layer, "name", None) or ""
                if str(lname) == layer_name or str(lname).startswith(layer_name):
                    return datablock, layer
        except Exception:
            pass

    return None, None


def _iter_layer_strokes(layer: object) -> Iterable[object]:
    """Yield strokes from a RulerData3D-like layer across API variants."""
    # Common path (Blender 2.8-4.5 and often still valid): layer.frames -> frame.strokes
    frames = getattr(layer, "frames", None)
    if frames is not None:
        try:
            for frame in frames:
                strokes = getattr(frame, "strokes", None)
                if strokes is None:
                    continue
                for stroke in strokes:
                    yield stroke
            return
        except Exception:
            # Fall through to other layouts
            pass

    # Alternative layout (some Grease Pencil v3/renamed structures): frame.drawing.strokes
    if frames is not None:
        try:
            for frame in frames:
                drawing = getattr(frame, "drawing", None)
                if drawing is None:
                    continue
                strokes = getattr(drawing, "strokes", None)
                if strokes is None:
                    continue
                for stroke in strokes:
                    yield stroke
            return
        except Exception:
            pass


def _stroke_points(stroke: object):
    pts = getattr(stroke, "points", None)
    if pts is not None:
        return pts
    # Rare alternative naming
    pts = getattr(stroke, "points3d", None)
    if pts is not None:
        return pts
    return []


class MeasurementsParser:
    def __init__(self):
        self.faces = []
        self.edges = []
        self.parse_dimensions()

    def parse_dimensions(self):
        self.faces = []
        self.edges = []

        datablock, layer = find_annotation_layer("RulerData3D")
        if layer is None:
            # Helpful diagnostic: list known annotation datablocks and their layer names
            try:
                debug_blocks = []
                for db in _unique_id_iter(_iter_annotation_datablocks()):
                    db_name = getattr(db, "name", "<no-name>")
                    layer_names = []
                    layers = getattr(db, "layers", None)
                    if layers:
                        try:
                            for ly in layers:
                                lname = getattr(ly, "info", None) or getattr(ly, "name", None) or ""
                                layer_names.append(str(lname))
                        except Exception:
                            layer_names.append("<layers-iteration-failed>")
                    debug_blocks.append((db_name, layer_names))
                logger.warning(
                    "No annotations or 'RulerData3D' layer found. Available annotation datablocks/layers: %s",
                    debug_blocks
                )
            except Exception:
                logger.warning("No annotations or 'RulerData3D' layer found.")
            return

        logger.info("Ruler layer found in datablock '%s'.", getattr(datablock, "name", "<unknown>"))

        try:
            for stroke in _iter_layer_strokes(layer):
                points = _stroke_points(stroke)
                point_objects = [Point(p) for p in points]

                if len(points) == 3:
                    self.faces.append(point_objects)
                elif len(points) == 2:
                    self.edges.append(point_objects)
                else:
                    # Ruler strokes sometimes store extra points (e.g., arc/angle helpers).
                    # We keep the behavior explicit to avoid silently corrupting geometry.
                    logger.debug("Stroke with %d points ignored (expected 2 or 3).", len(points))

            logger.info("Parsed %d faces and %d edges.", len(self.faces), len(self.edges))
        except Exception as e:
            logger.error("Error parsing dimensions: %s", e, exc_info=True)

    def export_raw_edges(self, filename=None):
        if not bpy.data.is_saved:
            self.show_save_prompt()
            return

        if filename is None:
            filename = bpy.data.filepath.replace('.blend', '_edges_raw.txt')

        try:
            with open(filename, 'w', encoding='utf-8') as file:
                file.write('EDGES POINTS {}\n'.format(len(self.edges)))
                for edge in self.edges:
                    if len(edge) >= 2:
                        file.write('{}\t{}\n'.format(edge[0], edge[1]))
                    else:
                        logger.warning("Edge with less than 2 points encountered.")
            logger.info(f"Raw Edges exported to {filename}")
        except Exception as e:
            logger.error(f"Error exporting raw edges: {e}")

    def export_raw_faces(self, filename=None):
        if not bpy.data.is_saved:
            self.show_save_prompt()
            return

        if filename is None:
            filename = bpy.data.filepath.replace('.blend', '_faces_raw.txt')

        try:
            with open(filename, 'w', encoding='utf-8') as file:
                file.write('FACES POINTS {}\n'.format(len(self.faces)))
                for face in self.faces:
                    if len(face) >= 3:
                        file.write('{}\t{}\t{}\n'.format(face[0], face[1], face[2]))
                    else:
                        logger.warning("Face with less than 3 points encountered.")
            logger.info(f"Raw Faces exported to {filename}")
        except Exception as e:
            logger.error(f"Error exporting raw faces: {e}")

    def process_edges(self, az_real=0, az_model=0, filename=None):
        if not bpy.data.is_saved:
            self.show_save_prompt()
            return

        processed_edges = self.get_processed_edges(az_real, az_model)

        if filename is None:
            filename = bpy.data.filepath.replace('.blend', '_edges_processed.csv')

        try:
            with open(filename, 'w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file, delimiter=',')
                writer.writerow(['x', 'y', 'z', 'azimuth', 'dip', 'edge_azimuth', 'edge_dip',
                                 'rotated_azimuth', 'length'])
                for edge in processed_edges:
                    writer.writerow([edge.center.x, edge.center.y, edge.center.z,
                                     edge.azimuth, edge.dip, edge.edge_azimuth,
                                     edge.edge_dip, edge.rotated_azimuth, edge.length])
            logger.info(f"Processed Edges exported to {filename}")
        except Exception as e:
            logger.error(f"Error exporting processed edges: {e}")

    def process_faces(self, az_real=0, az_model=0, filename=None):
        if not bpy.data.is_saved:
            self.show_save_prompt()
            return

        processed_faces = self.get_processed_faces(az_real, az_model)

        if filename is None:
            filename = bpy.data.filepath.replace('.blend', '_faces_processed.csv')

        try:
            with open(filename, 'w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file, delimiter=',')
                writer.writerow(['x', 'y', 'z', 'azimuth', 'dip', 'rotated_azimuth', 'area', 'degree'])
                for face in processed_faces:
                    writer.writerow([face.center.x, face.center.y, face.center.z,
                                     face.azimuth, face.dip, face.rotated_azimuth,
                                     face.area, face.degree])
            logger.info(f"Processed Faces exported to {filename}")
        except Exception as e:
            logger.error(f"Error exporting processed faces: {e}")

    def get_processed_edges(self, az_real=0, az_model=0):
        processed_edges = []
        for edge_points in self.edges:
            if len(edge_points) < 2:
                continue
            edge = Edge(edge_points[0], edge_points[1])

            # Rotation correction (model -> real)
            edge.rotated_azimuth = (edge.azimuth + az_real - az_model) % 360
            processed_edges.append(edge)
        return processed_edges

    def get_processed_faces(self, az_real=0, az_model=0):
        processed_faces = []
        for face_points in self.faces:
            if len(face_points) < 3:
                continue
            face = Face(face_points[0], face_points[1], face_points[2])

            # Rotation correction (model -> real)
            face.rotated_azimuth = (face.azimuth + az_real - az_model) % 360
            processed_faces.append(face)
        return processed_faces

    def show_save_prompt(self):
        logger.warning("Please save your Blender file before exporting.")
        bpy.ops.wm.save_mainfile('INVOKE_DEFAULT')
