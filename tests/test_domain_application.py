import unittest

from tests.addon_test_utils import load_addon_module


class FakeSource:
    def __init__(self, read_result):
        self.read_result = read_result

    def read_strokes(self):
        return self.read_result


class MemoryWriter:
    def __init__(self):
        self.calls = []

    def write(self, filename, rows):
        self.calls.append((filename, tuple(rows)))


class DomainApplicationTests(unittest.TestCase):
    def setUp(self):
        self.measurements = load_addon_module("domain.measurements")
        self.domain_geometry = load_addon_module("domain.geometry")
        self.services = load_addon_module("application.services")

    def point(self, x, y, z):
        return self.measurements.Point3D(x, y, z)

    def test_domain_processes_linear_measurement(self):
        raw = self.measurements.RawMeasurement(
            kind=self.measurements.MeasurementKind.LINEAR,
            points=(self.point(0, 0, 0), self.point(0, 1, 0)),
            source_id="edge-1",
        )
        correction = self.measurements.AzimuthCorrection(az_real=10, az_model=350)

        record = self.domain_geometry.process_linear_measurement(raw, correction)

        self.assertEqual(record.id, "edge-1")
        self.assertAlmostEqual(record.length, 1.0, places=6)
        self.assertAlmostEqual(record.line_orientation.azimuth, 0.0, places=6)
        self.assertAlmostEqual(record.line_orientation.rotated_azimuth, 20.0, places=6)

    def test_domain_processes_plane_measurement(self):
        raw = self.measurements.RawMeasurement(
            kind=self.measurements.MeasurementKind.PLANE,
            points=(self.point(0, 0, 0), self.point(1, 0, 0), self.point(0, 1, 0)),
            source_id="face-1",
        )
        correction = self.measurements.AzimuthCorrection(az_real=5, az_model=10)

        record = self.domain_geometry.process_plane_measurement(raw, correction)

        self.assertEqual(record.id, "face-1")
        self.assertAlmostEqual(record.area, 0.5, places=6)
        self.assertAlmostEqual(record.plane_orientation.dip, 0.0, places=6)
        self.assertAlmostEqual(record.plane_orientation.rotated_azimuth, 355.0, places=6)

    def test_application_ingests_and_deduplicates_source_strokes(self):
        read_result = self.services.SourceReadResult(
            layer_found=True,
            strokes=(
                self.services.StrokeInput(points=(self.point(0, 0, 0), self.point(0, 1, 0))),
                self.services.StrokeInput(points=(self.point(0, 0, 0), self.point(0, 1, 0))),
                self.services.StrokeInput(points=(self.point(0, 0, 0),)),
            ),
        )
        service = self.services.MeasurementApplicationService(source=FakeSource(read_result))

        measurement_set = service.ingest_measurements()

        self.assertEqual(len(measurement_set.edges), 1)
        self.assertEqual(measurement_set.diagnostics.total_strokes_count, 3)
        self.assertEqual(measurement_set.diagnostics.duplicate_strokes_count, 1)
        self.assertEqual(measurement_set.diagnostics.ignored_strokes_count, 1)

    def test_application_accepts_multi_point_plane_only_with_kind_hint(self):
        polygon_points = (
            self.point(0, 0, 0),
            self.point(1, 0, 0),
            self.point(1, 1, 0),
            self.point(0, 1, 0),
        )
        read_result = self.services.SourceReadResult(
            layer_found=True,
            strokes=(
                self.services.StrokeInput(points=polygon_points),
                self.services.StrokeInput(points=polygon_points, kind_hint=self.measurements.MeasurementKind.PLANE),
            ),
        )
        service = self.services.MeasurementApplicationService(source=FakeSource(read_result))

        measurement_set = service.ingest_measurements()

        self.assertEqual(len(measurement_set.faces), 1)
        self.assertEqual(len(measurement_set.faces[0].points), 4)
        self.assertEqual(measurement_set.diagnostics.ignored_strokes_count, 1)

    def test_application_export_uses_configured_writer(self):
        read_result = self.services.SourceReadResult(
            layer_found=True,
            strokes=(self.services.StrokeInput(points=(self.point(0, 0, 0), self.point(0, 1, 0))),),
        )
        writer = MemoryWriter()
        service = self.services.MeasurementApplicationService(
            source=FakeSource(read_result),
            raw_edge_writer=writer,
        )
        measurement_set = service.ingest_measurements()

        result = service.export_raw_edges(measurement_set, "edges.txt")

        self.assertTrue(result.ok)
        self.assertEqual(writer.calls[0][0], "edges.txt")
        self.assertEqual(len(writer.calls[0][1]), 1)


if __name__ == "__main__":
    unittest.main()
