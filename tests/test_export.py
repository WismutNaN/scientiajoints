import csv
import tempfile
import unittest
from pathlib import Path

from tests.addon_test_utils import Vector, install_bpy_stub, install_mathutils_stub, load_addon_module


class ExportTests(unittest.TestCase):
    def setUp(self):
        install_mathutils_stub()
        self.temp_dir = tempfile.TemporaryDirectory()
        blend_path = str(Path(self.temp_dir.name) / "scene.blend")
        self.bpy, self.save_calls = install_bpy_stub(is_saved=True, filepath=blend_path)
        self.parser_module = load_addon_module("parser")

    def tearDown(self):
        self.temp_dir.cleanup()

    def point(self, x, y, z):
        return self.parser_module.Point3D.from_object(Vector((x, y, z)))

    def measurements(self):
        measurements = self.parser_module.MeasurementsParser.__new__(self.parser_module.MeasurementsParser)
        measurements.edges = [[self.point(0, 0, 0), self.point(0, 1, 0)]]
        measurements.faces = [[self.point(0, 0, 0), self.point(1, 0, 0), self.point(0, 1, 0)]]
        return measurements

    def test_export_raw_edges_writes_txt_and_returns_success(self):
        output = Path(self.temp_dir.name) / "edges_raw.txt"

        result = self.measurements().export_raw_edges(str(output))

        self.assertTrue(result.ok)
        self.assertEqual(result.filename, str(output))
        content = output.read_text(encoding="utf-8").splitlines()
        self.assertEqual(content[0], "EDGES POINTS 1")
        self.assertIn("0.000\t0.000\t0.000", content[1])
        self.assertIn("0.000\t1.000\t0.000", content[1])

    def test_export_raw_faces_writes_txt_and_returns_success(self):
        output = Path(self.temp_dir.name) / "faces_raw.txt"

        result = self.measurements().export_raw_faces(str(output))

        self.assertTrue(result.ok)
        self.assertEqual(result.filename, str(output))
        content = output.read_text(encoding="utf-8").splitlines()
        self.assertEqual(content[0], "FACES POINTS 1")
        self.assertIn("1.000\t0.000\t0.000", content[1])

    def test_export_raw_polygon_faces_preserves_all_points(self):
        output = Path(self.temp_dir.name) / "polygon_faces_raw.txt"
        measurements = self.measurements()
        measurements.faces = [[
            self.point(0, 0, 0),
            self.point(1, 0, 0),
            self.point(1, 1, 0),
            self.point(0, 1, 0),
        ]]

        result = measurements.export_raw_faces(str(output))

        self.assertTrue(result.ok)
        content = output.read_text(encoding="utf-8").splitlines()
        self.assertIn("\t4\t", content[1])
        self.assertIn("[[0.0,0.0,0.0],[1.0,0.0,0.0],[1.0,1.0,0.0],[0.0,1.0,0.0]]", content[1])

    def test_process_edges_writes_csv_and_rotation(self):
        output = Path(self.temp_dir.name) / "edges_processed.csv"

        result = self.measurements().process_edges(az_real=10, az_model=350, filename=str(output))

        self.assertTrue(result.ok)
        with output.open(newline="", encoding="utf-8") as file:
            rows = list(csv.reader(file))

        self.assertEqual(
            rows[0],
            [
                "x",
                "y",
                "z",
                "azimuth",
                "dip",
                "edge_azimuth",
                "edge_dip",
                "rotated_azimuth",
                "length",
                "id",
                "source",
                "source_id",
                "layer",
                "name",
                "code",
                "description",
                "attributes_json",
            ],
        )
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(float(rows[1][7]), 20.0, places=6)
        self.assertAlmostEqual(float(rows[1][8]), 1.0, places=6)

    def test_process_faces_writes_csv(self):
        output = Path(self.temp_dir.name) / "faces_processed.csv"

        result = self.measurements().process_faces(az_real=5, az_model=10, filename=str(output))

        self.assertTrue(result.ok)
        with output.open(newline="", encoding="utf-8") as file:
            rows = list(csv.reader(file))

        self.assertEqual(
            rows[0],
            [
                "x",
                "y",
                "z",
                "azimuth",
                "dip",
                "rotated_azimuth",
                "area",
                "degree",
                "point_count",
                "fit_error",
                "fit_error_relative",
                "degeneracy",
                "id",
                "source",
                "source_id",
                "layer",
                "name",
                "code",
                "description",
                "attributes_json",
            ],
        )
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(float(rows[1][5]), 355.0, places=6)
        self.assertAlmostEqual(float(rows[1][6]), 0.5, places=6)

    def test_processed_edge_export_includes_metadata(self):
        output = Path(self.temp_dir.name) / "edge_metadata.csv"
        domain = load_addon_module("domain.measurements")
        geometry = load_addon_module("domain.geometry")
        exporters = load_addon_module("infrastructure.exporters")

        raw = domain.RawMeasurement(
            kind=domain.MeasurementKind.LINEAR,
            points=(domain.Point3D(0, 0, 0), domain.Point3D(1, 0, 0)),
            source="ScientiaScene",
            source_id="edge-1",
            layer="Layer A",
            properties=domain.MeasurementProperties({
                "name": "E1",
                "code": "J1",
                "description": "main set",
                "roughness": "high",
            }),
        )
        record = geometry.process_linear_measurement(raw, domain.AzimuthCorrection())

        exporters.ProcessedEdgeCsvWriter().write(str(output), [record])

        with output.open(newline="", encoding="utf-8") as file:
            rows = list(csv.reader(file))
        self.assertEqual(rows[1][-5:-1], ["Layer A", "E1", "J1", "main set"])
        self.assertEqual(rows[1][-1], '{"roughness": "high"}')

    def test_unsaved_file_returns_failure_and_invokes_save_prompt(self):
        self.bpy.data.is_saved = False
        output = Path(self.temp_dir.name) / "should_not_exist.txt"

        result = self.measurements().export_raw_edges(str(output))

        self.assertFalse(result.ok)
        self.assertIsNone(result.filename)
        self.assertFalse(output.exists())
        self.assertEqual(len(self.save_calls), 1)


if __name__ == "__main__":
    unittest.main()
