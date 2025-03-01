import math
from mathutils import Vector
import logging

logger = logging.getLogger(__name__)

class Point:
    """Point with coordinates in 3D space."""
    def __init__(self, vector):
        try:
            if hasattr(vector, 'co'):
                self.x = vector.co.x
                self.y = vector.co.y
                self.z = vector.co.z
            else:
                self.x = vector.x
                self.y = vector.y
                self.z = vector.z
        except AttributeError as e:
            logger.error(f"Invalid vector object: {e}")
            self.x = self.y = self.z = 0.0

    def rotated(self, center, azimuth):
        """Rotate point in plan around another point by a given azimuth."""
        x_a, y_a, z_a = self.x, self.y, self.z
        x_c, y_c = center.x, center.y
        length_c_a = math.sqrt((x_c - x_a) ** 2 + (y_c - y_a) ** 2)
        x_b = length_c_a * math.cos(math.radians(azimuth))
        y_b = length_c_a * math.sin(math.radians(azimuth))
        return Point(Vector((x_b, y_b, z_a)))

    def __add__(self, other):
        return Point(Vector((self.x + other.x, self.y + other.y, self.z + other.z)))

    def __sub__(self, other):
        return Point(Vector((self.x - other.x, self.y - other.y, self.z - other.z)))

    def __str__(self):
        return '{:.3f}\t{:.3f}\t{:.3f}'.format(self.x, self.y, self.z)

class Vector3D:
    """Vector in 3D space."""
    def __init__(self, *args):
        try:
            if len(args) == 2:
                point1, point2 = args
                self.x = point2.x - point1.x
                self.y = point2.y - point1.y
                self.z = point2.z - point1.z
            elif len(args) == 3:
                self.x, self.y, self.z = args
            else:
                raise ValueError('Invalid number of arguments for Vector3D.')
        except Exception as e:
            logger.error(f"Error initializing Vector3D: {e}")
            self.x = self.y = self.z = 0.0

    def multiply_minus(self):
        """Reverse vector direction."""
        self.x = -self.x
        self.y = -self.y
        self.z = -self.z

    def edge2face(self):
        """Rotate vector by 90 degrees."""
        azimuth = self.azimuth()
        length = math.sqrt(self.x ** 2 + self.y ** 2)
        self.z = -length
        self.x = self.z * math.sin(math.radians(azimuth))
        self.y = self.z * math.cos(math.radians(azimuth))

    def length(self):
        """Length of the vector."""
        return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)

    def azimuth(self):
        """Azimuth direction in X0Y plane."""
        if self.z < 0:
            self.multiply_minus()
        azimuth = math.degrees(math.atan2(self.x, self.y)) % 360
        return azimuth

    def dip(self):
        """Dip angle of the vector."""
        horizontal_length = math.sqrt(self.x ** 2 + self.y ** 2)
        dip_angle = math.degrees(math.atan2(horizontal_length, self.z))
        return dip_angle

    def degrees_with(self, other):
        try:
            dot_product = self.x * other.x + self.y * other.y + self.z * other.z
            lengths_product = self.length() * other.length()
            angle = math.degrees(math.acos(dot_product / lengths_product))
            return angle
        except Exception as e:
            logger.error(f"Error calculating degrees between vectors: {e}")
            return 0.0

    def __mul__(self, other):
        return Vector3D(
            self.y * other.z - other.y * self.z,
            -(self.x * other.z - other.x * self.z),
            self.x * other.y - other.x * self.y
        )

    def __str__(self):
        return '{:.3f}\t{:.3f}\t{:.3f}'.format(self.x, self.y, self.z)

class Face:
    """Plane defined by three points."""
    def __init__(self, point1, point2, point3):
        try:
            self.point1 = point1
            self.point2 = point2
            self.point3 = point3
            self.center = self.calculate_center()
            self.ab = self.ab_vector()
            self.azimuth = self.ab.azimuth()
            self.dip = self.ab.dip()
            self.area = self.calculate_area()
            self.rotated_azimuth = 0.0
            self.degree = self.calculate_degree()
        except Exception as e:
            logger.error(f"Error initializing Face at center {self.calculate_center()}: {e}")

    def calculate_center(self):
        x = (self.point1.x + self.point2.x + self.point3.x) / 3
        y = (self.point1.y + self.point2.y + self.point3.y) / 3
        z = (self.point1.z + self.point2.z + self.point3.z) / 3
        return Point(Vector((x, y, z)))

    def ab_vector(self):
        a = Vector3D(self.point2, self.point1)
        b = Vector3D(self.point3, self.point1)
        return a * b

    def calculate_degree(self):
        a = Vector3D(self.point2, self.point1)
        b = Vector3D(self.point2, self.point3)
        return a.degrees_with(b)

    def calculate_area(self):
        area = self.ab.length() / 2
        return area

    def __str__(self):
        return '{}\t{:.2f}\t{:.2f}\t{:.2f}\t{:.4f}\t{:.1f}'.format(
            self.center, self.azimuth, self.dip, self.rotated_azimuth, self.area, self.degree
        )

class Edge:
    """Edge defined by two points."""
    def __init__(self, point1, point2):
        try:
            self.point1 = point1
            self.point2 = point2
            self.center = self.calculate_center()
            self.a = Vector3D(point1, point2)
            self.length = self.a.length()
            self.azimuth = self.a.azimuth()
            self.dip = self.a.dip()
            self.a.edge2face()
            self.edge_azimuth = self.a.azimuth()
            self.edge_dip = self.a.dip()
            self.rotated_azimuth = 0.0
        except Exception as e:
            logger.error(f"Error initializing Edge at center {self.calculate_center()}: {e}")

    def calculate_center(self):
        x = (self.point1.x + self.point2.x) / 2
        y = (self.point1.y + self.point2.y) / 2
        z = (self.point1.z + self.point2.z) / 2
        return Point(Vector((x, y, z)))

    def __str__(self):
        return '{}\t{:.2f}\t{:.2f}\t{:.2f}\t{:.2f}\t{:.2f}\t{:.4f}'.format(
            self.center, self.azimuth, self.dip, self.edge_azimuth, self.edge_dip, self.rotated_azimuth, self.length
        )
