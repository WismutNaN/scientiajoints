import math
from dataclasses import dataclass

from .measurements import (
    AzimuthCorrection,
    MeasurementKind,
    MeasurementRecord,
    Orientation,
    Point3D,
    RawMeasurement,
)


@dataclass(frozen=True)
class Vector3:
    x: float
    y: float
    z: float

    @classmethod
    def between(cls, point1: Point3D, point2: Point3D):
        return cls(point2.x - point1.x, point2.y - point1.y, point2.z - point1.z)

    def upper(self):
        if self.z < 0:
            return Vector3(-self.x, -self.y, -self.z)
        return self

    def length(self):
        return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)

    def normalized(self):
        length = self.length()
        if length <= 0:
            return Vector3(0.0, 0.0, 0.0)
        return Vector3(self.x / length, self.y / length, self.z / length)

    def horizontal_length(self):
        return math.sqrt(self.x ** 2 + self.y ** 2)

    def azimuth(self):
        v = self.upper()
        return math.degrees(math.atan2(v.x, v.y)) % 360

    def dip(self):
        """Angle from vertical (0 = vertical vector, 90 = horizontal).

        For a plane normal this equals the dip of the plane.
        """
        v = self.upper()
        return math.degrees(math.atan2(v.horizontal_length(), v.z))

    def plunge(self):
        """Angle from horizontal (0 = horizontal vector, 90 = vertical).

        This is the geological plunge of a line.
        """
        v = self.upper()
        return math.degrees(math.atan2(v.z, v.horizontal_length()))

    def cross(self, other):
        return Vector3(
            self.y * other.z - other.y * self.z,
            -(self.x * other.z - other.x * self.z),
            self.x * other.y - other.x * self.y,
        )

    def dot(self, other):
        return self.x * other.x + self.y * other.y + self.z * other.z

    def flipped(self):
        return Vector3(-self.x, -self.y, -self.z)

    def angle_with(self, other):
        lengths_product = self.length() * other.length()
        if lengths_product == 0:
            return 0.0
        dot_product = self.x * other.x + self.y * other.y + self.z * other.z
        cos_angle = max(-1.0, min(1.0, dot_product / lengths_product))
        return math.degrees(math.acos(cos_angle))

def center_of(points):
    count = len(points)
    return Point3D(
        sum(point.x for point in points) / count,
        sum(point.y for point in points) / count,
        sum(point.z for point in points) / count,
    )


def process_linear_measurement(raw: RawMeasurement, correction: AzimuthCorrection) -> MeasurementRecord:
    p1, p2 = raw.points[:2]
    line_vector = Vector3.between(p1, p2)
    line_azimuth = line_vector.azimuth()

    return MeasurementRecord(
        id=raw.source_id or _measurement_id(raw),
        kind=MeasurementKind.LINEAR,
        points=raw.points,
        center=center_of(raw.points),
        source=raw.source,
        source_id=raw.source_id,
        layer=raw.layer,
        properties=raw.properties,
        line_orientation=Orientation(
            azimuth=line_azimuth,
            dip=line_vector.plunge(),
            rotated_azimuth=correction.apply(line_azimuth),
        ),
        # Orientation of the plane perpendicular to the measured segment
        # (the segment itself is the plane normal). Spacing measurements are
        # taken perpendicular to a joint set, so matching this orientation
        # against mean joint-set orientations assigns the measurement to a set.
        edge_orientation=Orientation(
            azimuth=line_azimuth,
            dip=line_vector.dip(),
            rotated_azimuth=correction.apply(line_azimuth),
        ),
        length=line_vector.length(),
    )


def process_plane_measurement(raw: RawMeasurement, correction: AzimuthCorrection) -> MeasurementRecord:
    points = raw.points
    p1, p2, p3 = points[:3]
    normal = fit_plane_normal(points)
    azimuth = normal.azimuth()
    degree_a = Vector3.between(p2, p1)
    degree_b = Vector3.between(p2, p3)
    degree = degree_a.angle_with(degree_b) if len(points) == 3 else None
    fit_error, fit_error_relative = plane_fit_metrics(points, normal)

    return MeasurementRecord(
        id=raw.source_id or _measurement_id(raw),
        kind=MeasurementKind.PLANE,
        points=points,
        center=center_of(points),
        source=raw.source,
        source_id=raw.source_id,
        layer=raw.layer,
        properties=raw.properties,
        plane_orientation=Orientation(
            azimuth=azimuth,
            dip=normal.dip(),
            rotated_azimuth=correction.apply(azimuth),
        ),
        area=polygon_area_in_plane(points, normal),
        degree=degree,
        fit_error=fit_error,
        fit_error_relative=fit_error_relative,
        degeneracy=plane_degeneracy(points),
    )


#: A plane needs the points to span two directions. When the second largest
#: eigenvalue of the scatter matrix falls this far below the largest, the
#: points lie on a line and the plane they "define" is arbitrary. A genuinely
#: elongated fracture trace, say 10 m by 5 cm, still gives a ratio near 2.5e-5,
#: so this threshold only catches genuinely degenerate input.
DEGENERATE_EIGENVALUE_RATIO = 1.0e-10
#: RMS distance from the centroid below which every point is the same point.
DEGENERATE_EXTENT = 1.0e-12


def _scatter_matrix(points):
    centroid = center_of(points)
    centered = [Vector3.between(centroid, point) for point in points]
    return centered, (
        (
            sum(vector.x * vector.x for vector in centered),
            sum(vector.x * vector.y for vector in centered),
            sum(vector.x * vector.z for vector in centered),
        ),
        (
            sum(vector.x * vector.y for vector in centered),
            sum(vector.y * vector.y for vector in centered),
            sum(vector.y * vector.z for vector in centered),
        ),
        (
            sum(vector.x * vector.z for vector in centered),
            sum(vector.y * vector.z for vector in centered),
            sum(vector.z * vector.z for vector in centered),
        ),
    )


def plane_degeneracy(points):
    """Report input that cannot define a plane orientation.

    Returns an empty string for usable input, otherwise a short reason. The
    orientation is still computed and exported: only the operator can decide
    what a degenerate measurement means, but it must not look trustworthy.
    """
    points = tuple(points)
    if len(points) < 3:
        return "fewer than three points"

    centered, matrix = _scatter_matrix(points)
    eigenvalues = _eigenvalues_symmetric_3x3(matrix)
    largest = eigenvalues[0]
    if largest <= 0 or math.sqrt(largest / len(points)) <= DEGENERATE_EXTENT:
        return "all points are at the same position"
    if eigenvalues[1] / largest < DEGENERATE_EIGENVALUE_RATIO:
        return "all points lie on one straight line"
    return ""


def fit_plane_normal(points):
    points = tuple(points)
    if len(points) < 3:
        return Vector3(0.0, 0.0, 1.0)

    centered, matrix = _scatter_matrix(points)
    if not any(vector.length() > 0 for vector in centered):
        return Vector3(0.0, 0.0, 1.0)

    normal = _smallest_eigenvector_symmetric_3x3(matrix).normalized()

    winding_normal = polygon_winding_normal(points)
    if winding_normal.length() > 0 and normal.dot(winding_normal) < 0:
        normal = normal.flipped()
    elif winding_normal.length() <= 0:
        normal = _orient_normal_upper(normal)
    return normal


def plane_fit_metrics(points, normal):
    """Measure how well the points lie in the fitted plane.

    Returns (rms, relative):
    - rms: root-mean-square distance of the points from the plane, in model
      units. Exactly 0.0 for three points (a plane always fits them).
    - relative: rms divided by the mean distance of the points from their
      centroid, so 0.1 means the scatter off the plane is ~10% of the
      measurement size. 0.0 when the points are degenerate.
    """
    points = tuple(points)
    if len(points) < 3:
        return 0.0, 0.0

    unit_normal = normal.normalized()
    if unit_normal.length() <= 0:
        return 0.0, 0.0

    centroid = center_of(points)
    centered = [Vector3.between(centroid, point) for point in points]
    if len(points) == 3:
        return 0.0, 0.0

    squared_sum = 0.0
    radius_sum = 0.0
    for vector in centered:
        distance = vector.dot(unit_normal)
        squared_sum += distance * distance
        radius_sum += vector.length()

    rms = math.sqrt(squared_sum / len(points))
    mean_radius = radius_sum / len(points)
    relative = rms / mean_radius if mean_radius > 0 else 0.0
    return rms, relative


def polygon_winding_normal(points):
    points = tuple(points)
    if len(points) < 3:
        return Vector3(0.0, 0.0, 0.0)

    nx = ny = nz = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        nx += (point.y - next_point.y) * (point.z + next_point.z)
        ny += (point.z - next_point.z) * (point.x + next_point.x)
        nz += (point.x - next_point.x) * (point.y + next_point.y)
    return Vector3(nx, ny, nz)


def polygon_area_in_plane(points, normal):
    points = tuple(points)
    if len(points) < 3:
        return 0.0

    unit_normal = normal.normalized()
    if unit_normal.length() <= 0:
        return 0.0

    reference = Vector3(0.0, 0.0, 1.0)
    if abs(unit_normal.dot(reference)) > 0.9:
        reference = Vector3(1.0, 0.0, 0.0)
    axis_u = unit_normal.cross(reference).normalized()
    axis_v = unit_normal.cross(axis_u).normalized()
    centroid = center_of(points)

    projected = []
    for point in points:
        vector = Vector3.between(centroid, point)
        projected.append((vector.dot(axis_u), vector.dot(axis_v)))

    area = 0.0
    for index, (x1, y1) in enumerate(projected):
        x2, y2 = projected[(index + 1) % len(projected)]
        area += x1 * y2 - x2 * y1
    return abs(area) * 0.5


def _orient_normal_upper(normal):
    if normal.z < 0:
        return normal.flipped()
    if normal.z == 0 and (normal.y < 0 or (normal.y == 0 and normal.x < 0)):
        return normal.flipped()
    return normal


def _eigenvalues_symmetric_3x3(matrix):
    """Eigenvalues in descending order."""
    diagonal, _vectors = _jacobi_symmetric_3x3(matrix)
    return tuple(sorted(diagonal, reverse=True))


def _smallest_eigenvector_symmetric_3x3(matrix):
    diagonal, vectors = _jacobi_symmetric_3x3(matrix)
    column = min(range(3), key=lambda index: diagonal[index])
    return Vector3(vectors[0][column], vectors[1][column], vectors[2][column])


def _jacobi_symmetric_3x3(matrix):
    """Cyclic Jacobi eigen decomposition of a symmetric 3x3 matrix.

    Returns (diagonal, vectors) where ``vectors`` holds the eigenvectors as
    columns. Verified against ``numpy.linalg.svd`` on random point sets.
    """
    a = [[float(matrix[row][col]) for col in range(3)] for row in range(3)]
    vectors = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]

    for _step in range(36):
        p, q = 0, 1
        max_value = abs(a[p][q])
        for candidate_p, candidate_q in ((0, 2), (1, 2)):
            value = abs(a[candidate_p][candidate_q])
            if value > max_value:
                p, q = candidate_p, candidate_q
                max_value = value
        if max_value <= 1.0e-12:
            break

        if a[p][p] == a[q][q]:
            angle = math.pi / 4
        else:
            angle = 0.5 * math.atan2(2.0 * a[p][q], a[q][q] - a[p][p])
        cosine = math.cos(angle)
        sine = math.sin(angle)

        app = a[p][p]
        aqq = a[q][q]
        apq = a[p][q]
        a[p][p] = cosine * cosine * app - 2.0 * sine * cosine * apq + sine * sine * aqq
        a[q][q] = sine * sine * app + 2.0 * sine * cosine * apq + cosine * cosine * aqq
        a[p][q] = 0.0
        a[q][p] = 0.0

        for index in range(3):
            if index in (p, q):
                continue
            aip = a[index][p]
            aiq = a[index][q]
            a[index][p] = cosine * aip - sine * aiq
            a[p][index] = a[index][p]
            a[index][q] = sine * aip + cosine * aiq
            a[q][index] = a[index][q]

        for index in range(3):
            vip = vectors[index][p]
            viq = vectors[index][q]
            vectors[index][p] = cosine * vip - sine * viq
            vectors[index][q] = sine * vip + cosine * viq

    return tuple(a[index][index] for index in range(3)), vectors


def _measurement_id(raw: RawMeasurement):
    signature = "_".join(
        "{:.6f}:{:.6f}:{:.6f}".format(point.x, point.y, point.z)
        for point in raw.points
    )
    return f"{raw.source}:{raw.kind.value}:{signature}"
