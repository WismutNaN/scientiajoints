import bpy
import csv
from .geometry import Point, Vector3D, Face, Edge
import logging

logger = logging.getLogger(__name__)

class MeasurementsParser:
    def __init__(self):
        self.faces = []
        self.edges = []
        self.parse_dimensions()

    def parse_dimensions(self):
        self.faces = []
        self.edges = []
        try:
            gpencil = bpy.data.grease_pencils["Annotations"]
            layer = gpencil.layers['RulerData3D']
            logger.info("Annotations and RulerData3D layer found.")
        except KeyError:
            logger.warning("No annotations or 'RulerData3D' layer found.")
            return
        except Exception as e:
            logger.error(f"Error accessing Grease Pencil data: {e}")
            return

        try:
            for frame in layer.frames:
                for stroke in frame.strokes:
                    points = stroke.points
                    point_objects = [Point(p) for p in points]
                    if len(points) == 3:
                        self.faces.append(point_objects)
                    elif len(points) == 2:
                        self.edges.append(point_objects)
                    else:
                        logger.warning(f"Stroke with unexpected number of points: {len(points)}")
            logger.info(f"Parsed {len(self.faces)} faces and {len(self.edges)} edges.")
        except Exception as e:
            logger.error(f"Error parsing dimensions: {e}")


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
                writer.writerow(['x', 'y', 'z', 'azimuth', 'dip', 'edge_azimuth', 'edge_dip', 'rotated_azimuth', 'length'])
                for edge in processed_edges:
                    center = [edge.center.x, edge.center.y, edge.center.z]
                    angles = [edge.azimuth, edge.dip, edge.edge_azimuth, edge.edge_dip, edge.rotated_azimuth]
                    center = [round(x, 3) for x in center]
                    angles = [round(x, 2) for x in angles]
                    line = center + angles + [round(edge.length, 3)]
                    writer.writerow(line)
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
                writer.writerow(['x', 'y', 'z', 'azimuth', 'dip', 'rotated_azimuth', 'blender_degree', 'area'])
                for face in processed_faces:
                    center = [face.center.x, face.center.y, face.center.z]
                    angles = [face.azimuth, face.dip, face.rotated_azimuth, face.degree]
                    center = [round(x, 3) for x in center]
                    angles = [round(x, 2) for x in angles]
                    line = center + angles + [round(face.area, 3)]
                    writer.writerow(line)
            logger.info(f"Processed Faces exported to {filename}")
        except Exception as e:
            logger.error(f"Error exporting processed faces: {e}")


    def get_processed_edges(self, az_real=0, az_model=0):
        pre_delta = az_real - az_model
        if pre_delta < 0:
            delta = pre_delta + 360
        else:
            delta = pre_delta % 360
        processed_edges = []
        
        for edge_points in self.edges:
            if len(edge_points) >= 2:
                try:
                    edge = Edge(edge_points[0], edge_points[1])
                    rot_azimuth = edge.azimuth + delta
                    if rot_azimuth >= 360:
                        edge.rotated_azimuth = rot_azimuth - 360
                    elif rot_azimuth < 0:
                        edge.rotated_azimuth = rot_azimuth + 360
                    else:
                        edge.rotated_azimuth = rot_azimuth
                    processed_edges.append(edge)
                except Exception as e:
                    logger.error(f"Error processing edge: {e}")
            else:
                logger.warning("Edge with less than 2 points encountered during processing.")
        
        logger.info(f"Processed {len(processed_edges)} edges.")
        return processed_edges

    def get_processed_faces(self, az_real=0, az_model=0):
        pre_delta = az_real - az_model
        if pre_delta < 0:
            delta = pre_delta + 360
        else:
            delta = pre_delta % 360
        processed_faces = []
        
        for face_points in self.faces:
            if len(face_points) >= 3:
                try:
                    face = Face(face_points[0], face_points[1], face_points[2])
                    rot_azimuth = face.azimuth + delta
                    if rot_azimuth >= 360:
                        face.rotated_azimuth = rot_azimuth - 360
                    elif rot_azimuth < 0:
                        face.rotated_azimuth = rot_azimuth + 360
                    else:
                        face.rotated_azimuth = rot_azimuth
                    processed_faces.append(face)
                except Exception as e:
                    logger.error(f"Error processing face: {e}")
            else:
                logger.warning("Face with less than 3 points encountered during processing.")
        
        logger.info(f"Processed {len(processed_faces)} faces.")
        return processed_faces

    def show_save_prompt(self):
        def draw(self, context):
            self.layout.label(text="Please save the file before exporting.")

        bpy.context.window_manager.popup_menu(draw, title="File Not Saved", icon='ERROR')
        logger.warning("File not saved. Please save the Blender file before exporting.")

