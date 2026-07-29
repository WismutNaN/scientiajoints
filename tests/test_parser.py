import types
import unittest

from tests.addon_test_utils import install_bpy_stub, install_mathutils_stub, load_addon_module


class FakePoint:
    def __init__(self, x, y, z):
        self.co = types.SimpleNamespace(x=x, y=y, z=z)


class FakeStroke:
    def __init__(self, point_count):
        self.points = [FakePoint(i, i + 1, i + 2) for i in range(point_count)]


class FakeLayer:
    def __init__(self, frames, name="RulerData3D"):
        self.name = name
        self.info = name
        self.frames = frames


class FakeLayers(list):
    def get(self, name):
        for layer in self:
            if getattr(layer, "name", None) == name or getattr(layer, "info", None) == name:
                return layer
        return None

    def __getitem__(self, key):
        if isinstance(key, str):
            layer = self.get(key)
            if layer is None:
                raise KeyError(key)
            return layer
        return super().__getitem__(key)


class FakeDatablock:
    def __init__(self, layers, name="Annotations"):
        self.name = name
        self.layers = FakeLayers(layers)


class ParserTests(unittest.TestCase):
    def setUp(self):
        install_mathutils_stub()
        self.bpy, self.save_calls = install_bpy_stub()
        self.parser = load_addon_module("parser")

    def datablock_with_layer(self, layer):
        return FakeDatablock([layer])

    def test_find_annotation_layer_uses_bpy_data_annotations(self):
        layer = FakeLayer([])
        datablock = self.datablock_with_layer(layer)
        self.bpy.data.annotations = [datablock]

        found_db, found_layer = self.parser.find_annotation_layer("RulerData3D")

        self.assertIs(found_db, datablock)
        self.assertIs(found_layer, layer)

    def test_find_annotation_layer_uses_legacy_grease_pencils(self):
        layer = FakeLayer([])
        datablock = self.datablock_with_layer(layer)
        self.bpy.data.annotations = []
        self.bpy.data.grease_pencils = [datablock]

        found_db, found_layer = self.parser.find_annotation_layer("RulerData3D")

        self.assertIs(found_db, datablock)
        self.assertIs(found_layer, layer)

    def test_find_annotation_layer_uses_scene_fallback(self):
        layer = FakeLayer([])
        datablock = self.datablock_with_layer(layer)
        self.bpy.data.annotations = []
        self.bpy.data.grease_pencils = []
        self.bpy.context.scene = types.SimpleNamespace(annotation=datablock)

        found_db, found_layer = self.parser.find_annotation_layer("RulerData3D")

        self.assertIs(found_db, datablock)
        self.assertIs(found_layer, layer)

    def test_parse_dimensions_from_frame_strokes(self):
        layer = FakeLayer([
            types.SimpleNamespace(strokes=[FakeStroke(2), FakeStroke(3), FakeStroke(4)]),
        ])
        self.bpy.data.annotations = [self.datablock_with_layer(layer)]

        measurements = self.parser.MeasurementsParser()

        self.assertEqual(len(measurements.edges), 1)
        self.assertEqual(len(measurements.faces), 1)

    def test_parse_dimensions_from_frame_drawing_strokes(self):
        layer = FakeLayer([
            types.SimpleNamespace(drawing=types.SimpleNamespace(strokes=[FakeStroke(2), FakeStroke(3)])),
        ])
        self.bpy.data.annotations = [self.datablock_with_layer(layer)]

        strokes = list(self.parser._iter_layer_strokes(layer))
        measurements = self.parser.MeasurementsParser()

        self.assertEqual(len(strokes), 2)
        self.assertEqual(len(measurements.edges), 1)
        self.assertEqual(len(measurements.faces), 1)

    def test_duplicate_measurements_across_frames_are_skipped(self):
        layer = FakeLayer([
            types.SimpleNamespace(strokes=[FakeStroke(2)]),
            types.SimpleNamespace(strokes=[FakeStroke(2)]),
            types.SimpleNamespace(drawing=types.SimpleNamespace(strokes=[FakeStroke(3)])),
            types.SimpleNamespace(drawing=types.SimpleNamespace(strokes=[FakeStroke(3)])),
        ])
        self.bpy.data.annotations = [self.datablock_with_layer(layer)]

        measurements = self.parser.MeasurementsParser()

        self.assertEqual(measurements.total_strokes_count, 4)
        self.assertEqual(measurements.duplicate_strokes_count, 2)
        self.assertEqual(len(measurements.edges), 1)
        self.assertEqual(len(measurements.faces), 1)

    def test_unsupported_stroke_sizes_are_ignored(self):
        layer = FakeLayer([
            types.SimpleNamespace(strokes=[FakeStroke(1), FakeStroke(4), FakeStroke(2)]),
        ])
        self.bpy.data.annotations = [self.datablock_with_layer(layer)]

        measurements = self.parser.MeasurementsParser()

        self.assertEqual(len(measurements.edges), 1)
        self.assertEqual(len(measurements.faces), 0)
        self.assertEqual(measurements.ignored_strokes_count, 2)

    def test_missing_layer_is_reported_in_diagnostics(self):
        measurements = self.parser.MeasurementsParser()

        self.assertFalse(measurements.layer_found)
        self.assertIn("RulerData3D layer not found.", measurements.diagnostic_messages)

    def test_scene_measurements_are_parsed_without_ruler_layer(self):
        def measurement(points, uuid, layer="Default", code="", description="", color=(0.1, 0.6, 1.0, 1.0), kind=None):
            return types.SimpleNamespace(
                uuid=uuid,
                name=uuid,
                kind=kind or ("LINEAR" if len(points) == 2 else "PLANE"),
                layer=layer,
                visible=True,
                color=color,
                code=code,
                description=description,
                properties_json="{}",
                points=[types.SimpleNamespace(co=point) for point in points],
            )

        self.bpy.data.annotations = []
        self.bpy.data.grease_pencils = []
        scene = types.SimpleNamespace(
            scientia_measurement_codes=[
                types.SimpleNamespace(name="J1", visible=True, color=(0.9, 0.1, 0.1, 1.0)),
                types.SimpleNamespace(name="J2", visible=True, color=(0.1, 0.9, 0.1, 1.0)),
            ],
            scientia_measurements=[
                measurement(((0, 0, 0), (1, 0, 0)), "edge-1", code="J1", description="spacing"),
                measurement(((0, 0, 0), (1, 0, 0), (0, 1, 0)), "face-1", code="J2", description="joint set"),
                measurement(((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)), "poly-1", code="J2", kind="POLYLINE"),
            ],
        )
        for item in scene.scientia_measurements:
            item.id_data = scene
        self.bpy.context.scene = scene

        measurements = self.parser.MeasurementsParser()

        self.assertTrue(measurements.layer_found)
        self.assertEqual(len(measurements.edges), 1)
        self.assertEqual(len(measurements.faces), 2)
        raw_by_id = {raw.source_id: raw for raw in measurements.measurement_set.raw_measurements}
        self.assertEqual(raw_by_id["edge-1"].properties.values["code"], "J1")
        self.assertEqual(raw_by_id["edge-1"].properties.values["description"], "spacing")
        self.assertEqual(raw_by_id["edge-1"].properties.values["display_color"], (0.9, 0.1, 0.1, 1.0))
        self.assertEqual(raw_by_id["face-1"].properties.values["code"], "J2")
        self.assertEqual(len(raw_by_id["poly-1"].points), 4)

    def test_scene_measurements_hidden_by_code_are_still_exported(self):
        def measurement(points, uuid, code):
            return types.SimpleNamespace(
                uuid=uuid,
                name=uuid,
                layer="Default",
                visible=True,
                color=(0.1, 0.6, 1.0, 1.0),
                code=code,
                description="",
                properties_json="{}",
                points=[types.SimpleNamespace(co=point) for point in points],
            )

        self.bpy.data.annotations = []
        self.bpy.data.grease_pencils = []
        self.bpy.context.scene = types.SimpleNamespace(
            scientia_measurement_codes=[
                types.SimpleNamespace(name="VISIBLE", visible=True, color=(1, 0, 0, 1)),
                types.SimpleNamespace(name="HIDDEN", visible=False, color=(0, 1, 0, 1)),
            ],
            scientia_measurements=[
                measurement(((0, 0, 0), (1, 0, 0)), "edge-1", "VISIBLE"),
                measurement(((0, 0, 0), (0, 1, 0)), "edge-2", "HIDDEN"),
            ],
        )

        measurements = self.parser.MeasurementsParser()

        self.assertTrue(measurements.layer_found)
        # Code visibility only filters the viewport overlay; both measurements
        # must reach the export.
        self.assertEqual(len(measurements.edges), 2)
        self.assertEqual(
            [raw.source_id for raw in measurements.measurement_set.raw_measurements],
            ["edge-1", "edge-2"],
        )
        self.assertTrue(
            any("hidden in the viewport" in message for message in measurements.diagnostic_messages),
            measurements.diagnostic_messages,
        )

    def test_scene_measurements_without_code_use_scene_default_color_and_visibility(self):
        def measurement(points, uuid):
            return types.SimpleNamespace(
                uuid=uuid,
                name=uuid,
                layer="Default",
                visible=True,
                color=(0.1, 0.6, 1.0, 1.0),
                code="",
                description="",
                properties_json="{}",
                points=[types.SimpleNamespace(co=point) for point in points],
            )

        self.bpy.data.annotations = []
        self.bpy.data.grease_pencils = []
        scene = types.SimpleNamespace(
            scientia_measure_no_code_visible=True,
            scientia_measure_default_color=(0.8, 0.2, 0.2, 1.0),
            scientia_measurement_codes=[],
            scientia_measurements=[
                measurement(((0, 0, 0), (1, 0, 0)), "edge-1"),
            ],
        )
        for item in scene.scientia_measurements:
            item.id_data = scene
        self.bpy.context.scene = scene

        measurements = self.parser.MeasurementsParser()

        self.assertEqual(len(measurements.edges), 1)
        raw = measurements.measurement_set.raw_measurements[0]
        self.assertEqual(raw.properties.values["display_color"], (0.8, 0.2, 0.2, 1.0))

        scene.scientia_measure_no_code_visible = False
        measurements = self.parser.MeasurementsParser()

        # Hiding the "no code" group hides the overlay, not the data.
        self.assertEqual(len(measurements.edges), 1)


if __name__ == "__main__":
    unittest.main()
