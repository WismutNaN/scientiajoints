import unittest

from tests.addon_test_utils import load_addon_module


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.measurements = load_addon_module("domain.measurements")
        self.geometry = load_addon_module("domain.geometry")

    def point(self, x, y, z):
        return self.measurements.Point3D(x, y, z)

    def raw_edge(self, p1, p2):
        return self.measurements.RawMeasurement(
            kind=self.measurements.MeasurementKind.LINEAR,
            points=(p1, p2),
        )

    def raw_face(self, p1, p2, p3):
        return self.measurements.RawMeasurement(
            kind=self.measurements.MeasurementKind.PLANE,
            points=(p1, p2, p3),
        )

    def correction(self):
        return self.measurements.AzimuthCorrection()

    def assertAlmostAngle(self, actual, expected):
        self.assertAlmostEqual(actual % 360, expected % 360, places=6)

    def test_vector_azimuth_and_dip_are_non_mutating(self):
        vector = self.geometry.Vector3(1, 0, -1)
        before = (vector.x, vector.y, vector.z)

        self.assertAlmostAngle(vector.azimuth(), 270)
        self.assertAlmostEqual(vector.dip(), 45.0, places=6)
        self.assertEqual((vector.x, vector.y, vector.z), before)

    def test_horizontal_and_vertical_faces(self):
        horizontal = self.geometry.process_plane_measurement(
            self.raw_face(self.point(0, 0, 0), self.point(1, 0, 0), self.point(0, 1, 0)),
            self.correction(),
        )
        self.assertAlmostAngle(horizontal.plane_orientation.azimuth, 0)
        self.assertAlmostEqual(horizontal.plane_orientation.dip, 0.0, places=6)
        self.assertAlmostEqual(horizontal.area, 0.5, places=6)

        vertical = self.geometry.process_plane_measurement(
            self.raw_face(self.point(0, 0, 0), self.point(1, 0, 0), self.point(0, 0, 1)),
            self.correction(),
        )
        self.assertAlmostAngle(vertical.plane_orientation.azimuth, 180)
        self.assertAlmostEqual(vertical.plane_orientation.dip, 90.0, places=6)
        self.assertAlmostEqual(vertical.area, 0.5, places=6)

    def test_inclined_face_orientation(self):
        face = self.geometry.process_plane_measurement(
            self.raw_face(self.point(0, 0, 0), self.point(0, 1, 0), self.point(1, 0, -1)),
            self.correction(),
        )

        self.assertAlmostAngle(face.plane_orientation.azimuth, 90)
        self.assertAlmostEqual(face.plane_orientation.dip, 45.0, places=6)
        self.assertAlmostEqual(face.area, 0.7071067811865476, places=6)

    def test_polygon_face_uses_best_fit_plane_and_boundary_area(self):
        raw = self.measurements.RawMeasurement(
            kind=self.measurements.MeasurementKind.PLANE,
            points=(
                self.point(0, 0, 0),
                self.point(0, 1, 0),
                self.point(1, 1, -1),
                self.point(1, 0, -1),
            ),
        )

        face = self.geometry.process_plane_measurement(raw, self.correction())

        self.assertAlmostAngle(face.plane_orientation.azimuth, 90)
        self.assertAlmostEqual(face.plane_orientation.dip, 45.0, places=6)
        self.assertAlmostEqual(face.area, 2 ** 0.5, places=6)
        self.assertIsNone(face.degree)

    def test_noisy_polygon_fit_averages_to_horizontal_plane(self):
        raw = self.measurements.RawMeasurement(
            kind=self.measurements.MeasurementKind.PLANE,
            points=(
                self.point(-1, -1, 0.1),
                self.point(1, -1, -0.1),
                self.point(1, 1, 0.1),
                self.point(-1, 1, -0.1),
            ),
        )

        face = self.geometry.process_plane_measurement(raw, self.correction())

        self.assertAlmostEqual(face.plane_orientation.dip, 0.0, places=6)
        self.assertAlmostEqual(face.area, 4.0, places=2)

    def test_edge_length_orientation_and_perpendicular_plane(self):
        edge = self.geometry.process_linear_measurement(
            self.raw_edge(self.point(0, 0, 0), self.point(1, 0, -1)),
            self.correction(),
        )

        self.assertAlmostEqual(edge.length, 2 ** 0.5, places=6)
        self.assertAlmostAngle(edge.line_orientation.azimuth, 270)
        # Line dip is the plunge: 0 for horizontal, 90 for vertical.
        self.assertAlmostEqual(edge.line_orientation.dip, 45.0, places=6)
        # Edge orientation is the plane perpendicular to the segment
        # (the segment is its normal).
        self.assertAlmostAngle(edge.edge_orientation.azimuth, 270)
        self.assertAlmostEqual(edge.edge_orientation.dip, 45.0, places=6)

    def test_line_dip_is_plunge_and_edge_plane_is_perpendicular(self):
        import math

        edge = self.geometry.process_linear_measurement(
            self.raw_edge(self.point(0, 0, 0), self.point(2, 0, -1)),
            self.correction(),
        )

        expected_plunge = math.degrees(math.atan2(1, 2))
        self.assertAlmostEqual(edge.line_orientation.dip, expected_plunge, places=6)
        # The perpendicular plane dips by the complement of the plunge.
        self.assertAlmostAngle(edge.edge_orientation.azimuth, 270)
        self.assertAlmostEqual(edge.edge_orientation.dip, 90.0 - expected_plunge, places=6)

    def test_horizontal_and_vertical_line_plunge(self):
        horizontal = self.geometry.process_linear_measurement(
            self.raw_edge(self.point(0, 0, 0), self.point(1, 0, 0)),
            self.correction(),
        )
        vertical = self.geometry.process_linear_measurement(
            self.raw_edge(self.point(0, 0, 0), self.point(0, 0, 1)),
            self.correction(),
        )

        self.assertAlmostEqual(horizontal.line_orientation.dip, 0.0, places=6)
        self.assertAlmostEqual(vertical.line_orientation.dip, 90.0, places=6)

    def test_three_point_plane_has_zero_fit_error(self):
        face = self.geometry.process_plane_measurement(
            self.raw_face(self.point(0, 0, 0), self.point(1, 0, 0), self.point(0, 1, 5)),
            self.correction(),
        )

        self.assertEqual(face.fit_error, 0.0)
        self.assertEqual(face.fit_error_relative, 0.0)

    def test_planar_polygon_has_zero_fit_error(self):
        raw = self.measurements.RawMeasurement(
            kind=self.measurements.MeasurementKind.PLANE,
            points=(
                self.point(0, 0, 0),
                self.point(0, 1, 0),
                self.point(1, 1, -1),
                self.point(1, 0, -1),
            ),
        )

        face = self.geometry.process_plane_measurement(raw, self.correction())

        self.assertAlmostEqual(face.fit_error, 0.0, places=9)

    def test_noisy_polygon_reports_fit_error(self):
        raw = self.measurements.RawMeasurement(
            kind=self.measurements.MeasurementKind.PLANE,
            points=(
                self.point(-1, -1, 0.1),
                self.point(1, -1, -0.1),
                self.point(1, 1, 0.1),
                self.point(-1, 1, -0.1),
            ),
        )

        face = self.geometry.process_plane_measurement(raw, self.correction())

        self.assertAlmostEqual(face.fit_error, 0.1, places=6)
        self.assertAlmostEqual(face.fit_error_relative, 0.1 / (2.01 ** 0.5), places=6)

    def test_degenerate_vector_angle_is_zero(self):
        zero = self.geometry.Vector3(0, 0, 0)
        north = self.geometry.Vector3(0, 1, 0)

        self.assertEqual(zero.angle_with(north), 0.0)


if __name__ == "__main__":
    unittest.main()
