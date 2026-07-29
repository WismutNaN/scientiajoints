"""Plane orientation maths for polygon measurements.

The reference values are analytic: a plane is built from a known dip and dip
azimuth, and the polygon traced on it must report that attitude back.
"""

import math
import unittest

from tests.addon_test_utils import load_addon_module


def polygon_on_plane(dip_deg, azimuth_deg, radius=1.0, count=8):
    """A regular polygon lying on the plane with the given attitude."""
    dip = math.radians(dip_deg)
    azimuth = math.radians(azimuth_deg)
    normal = (
        math.sin(dip) * math.sin(azimuth),
        math.sin(dip) * math.cos(azimuth),
        math.cos(dip),
    )
    reference = (0.0, 0.0, 1.0) if abs(normal[2]) < 0.9 else (1.0, 0.0, 0.0)
    axis_u = _cross(normal, reference)
    length = math.sqrt(sum(component ** 2 for component in axis_u))
    axis_u = tuple(component / length for component in axis_u)
    axis_v = _cross(normal, axis_u)

    return [
        tuple(
            radius * (math.cos(2 * math.pi * index / count) * axis_u[axis]
                      + math.sin(2 * math.pi * index / count) * axis_v[axis])
            for axis in range(3)
        )
        for index in range(count)
    ]


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


class PlaneOrientationTests(unittest.TestCase):
    def setUp(self):
        self.geometry = load_addon_module("domain.geometry")
        self.measurements = load_addon_module("domain.measurements")

    def _record(self, points, az_real=0.0, az_model=0.0):
        raw = self.measurements.RawMeasurement(
            kind=self.measurements.MeasurementKind.PLANE,
            points=tuple(self.measurements.Point3D(*point) for point in points),
        )
        correction = self.measurements.AzimuthCorrection(az_real=az_real, az_model=az_model)
        return self.geometry.process_plane_measurement(raw, correction)

    def test_polygon_reports_the_attitude_it_was_built_from(self):
        for dip_deg, azimuth_deg in [(10, 0), (30, 90), (45, 180), (60, 270), (75, 45), (85, 315)]:
            with self.subTest(dip=dip_deg, azimuth=azimuth_deg):
                record = self._record(polygon_on_plane(dip_deg, azimuth_deg, count=7))
                self.assertAlmostEqual(record.plane_orientation.dip, dip_deg, places=6)
                self.assertAlmostEqual(record.plane_orientation.azimuth, azimuth_deg, places=6)

    def test_a_horizontal_polygon_has_zero_dip(self):
        record = self._record([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])

        self.assertAlmostEqual(record.plane_orientation.dip, 0.0, places=9)

    def test_three_points_and_many_points_agree_on_the_same_plane(self):
        points = polygon_on_plane(55.0, 200.0, count=9)

        many = self._record(points)
        three = self._record(points[:3])

        self.assertAlmostEqual(many.plane_orientation.dip, three.plane_orientation.dip, places=6)
        self.assertAlmostEqual(many.plane_orientation.azimuth, three.plane_orientation.azimuth, places=6)

    def test_tracing_direction_does_not_change_the_attitude(self):
        points = polygon_on_plane(45.0, 120.0, count=6)

        forward = self._record(points)
        backward = self._record(list(reversed(points)))

        self.assertAlmostEqual(forward.plane_orientation.dip, backward.plane_orientation.dip, places=9)
        self.assertAlmostEqual(forward.plane_orientation.azimuth, backward.plane_orientation.azimuth, places=9)

    def test_area_of_a_known_polygon(self):
        record = self._record([(0, 0, 0), (2, 0, 0), (2, 3, 0), (0, 3, 0)])

        self.assertAlmostEqual(record.area, 6.0, places=9)

    def test_area_of_a_tilted_rectangle(self):
        record = self._record([(0, 0, 0), (2, 0, 0), (2, 3, 3), (0, 3, 3)])

        self.assertAlmostEqual(record.area, 2 * math.hypot(3, 3), places=9)

    def test_azimuth_correction_adds_real_and_subtracts_model(self):
        record = self._record(polygon_on_plane(35.0, 100.0, count=6), az_real=40.0, az_model=10.0)

        self.assertAlmostEqual(record.plane_orientation.rotated_azimuth, 130.0, places=6)

    def test_out_of_plane_scatter_is_measured(self):
        """A saddle is as non-planar as four points get."""
        record = self._record([(1, 0, 1), (0, 1, -1), (-1, 0, 1), (0, -1, -1)])

        self.assertGreater(record.fit_error_relative, 0.4)

    def test_three_points_always_fit_their_plane_exactly(self):
        record = self._record([(0, 0, 0), (1, 0, 0), (0, 1, 1)])

        self.assertEqual(record.fit_error, 0.0)
        self.assertEqual(record.fit_error_relative, 0.0)


class DegeneratePlaneTests(unittest.TestCase):
    """Input that cannot define an orientation must not look trustworthy."""

    def setUp(self):
        self.geometry = load_addon_module("domain.geometry")
        self.measurements = load_addon_module("domain.measurements")

    def _record(self, points):
        raw = self.measurements.RawMeasurement(
            kind=self.measurements.MeasurementKind.PLANE,
            points=tuple(self.measurements.Point3D(*point) for point in points),
        )
        return self.geometry.process_plane_measurement(raw, self.measurements.AzimuthCorrection())

    def test_collinear_points_are_reported(self):
        record = self._record([(0, 0, 0), (1, 1, 1), (2, 2, 2), (3, 3, 3)])

        self.assertTrue(record.is_degenerate)
        self.assertIn("straight line", record.degeneracy)

    def test_coincident_points_are_reported(self):
        record = self._record([(1, 2, 3)] * 4)

        self.assertTrue(record.is_degenerate)
        self.assertIn("same position", record.degeneracy)

    def test_values_are_still_produced_for_degenerate_input(self):
        """The measurement stays in the export; only its trust changes."""
        record = self._record([(0, 0, 0), (1, 1, 1), (2, 2, 2)])

        self.assertIsNotNone(record.plane_orientation)
        self.assertIsNotNone(record.area)

    def test_a_long_thin_fracture_is_not_degenerate(self):
        """10 m by 5 cm is a normal trace, not a degenerate one."""
        record = self._record([(0, 0, 0), (10, 0, 0), (10, 0.05, 0), (0, 0.05, 0)])

        self.assertEqual(record.degeneracy, "")

    def test_a_normal_polygon_is_not_degenerate(self):
        record = self._record(polygon_on_plane(45.0, 90.0, count=6))

        self.assertEqual(record.degeneracy, "")

    def test_a_millimetre_sized_polygon_is_not_degenerate(self):
        record = self._record(polygon_on_plane(45.0, 90.0, radius=0.001, count=6))

        self.assertEqual(record.degeneracy, "")
        self.assertAlmostEqual(record.plane_orientation.dip, 45.0, places=6)


if __name__ == "__main__":
    unittest.main()
