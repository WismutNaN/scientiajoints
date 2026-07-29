"""Protection against measurements being counted twice.

Blender stores annotations per timeline frame and copies the existing strokes
into a new frame when the current frame changes while the ruler is in use, so
the same fracture can appear several times in the layer.
"""

import types
import unittest
import unittest.mock

from tests.addon_test_utils import install_bpy_stub, install_mathutils_stub, load_addon_module


class _Source:
    def __init__(self, strokes, layer_found=True):
        self.strokes = strokes
        self.layer_found = layer_found

    def read_strokes(self):
        return self.result_type(self.layer_found, strokes=tuple(self.strokes))


class DuplicateIngestionTests(unittest.TestCase):
    def setUp(self):
        self.services = load_addon_module("application.services")
        self.measurements = load_addon_module("domain.measurements")

    def _ingest(self, strokes):
        source = _Source(strokes)
        source.result_type = self.services.SourceReadResult
        return self.services.MeasurementApplicationService(source).ingest_measurements()

    def _stroke(self, points, source_id):
        return self.services.StrokeInput(
            points=tuple(self.measurements.Point3D(*point) for point in points),
            source_id=source_id,
        )

    def test_an_identical_copy_is_dropped(self):
        result = self._ingest([
            self._stroke([(0, 0, 0), (1, 0, 0)], "frame-1"),
            self._stroke([(0, 0, 0), (1, 0, 0)], "frame-2"),
        ])

        self.assertEqual(len(result.raw_measurements), 1)
        self.assertEqual(result.diagnostics.duplicate_strokes_count, 1)
        self.assertEqual(result.diagnostics.near_duplicate_pairs, ())

    def test_a_nudged_copy_is_kept_but_reported(self):
        """A copy that was moved afterwards is real data or a mistake; only the
        operator can tell, so it is reported instead of silently dropped."""
        result = self._ingest([
            self._stroke([(0, 0, 0), (1, 0, 0)], "original"),
            self._stroke([(0.0001, 0, 0), (1.0001, 0, 0)], "nudged"),
        ])

        self.assertEqual(len(result.raw_measurements), 2)
        self.assertEqual(result.diagnostics.duplicate_strokes_count, 0)
        self.assertEqual(result.diagnostics.near_duplicate_pairs, (("original", "nudged"),))
        self.assertTrue(
            any("nearly identical" in message for message in result.diagnostics.messages),
            result.diagnostics.messages,
        )

    def test_a_reversed_copy_is_reported_as_a_near_duplicate(self):
        result = self._ingest([
            self._stroke([(0, 0, 0), (1, 0, 0)], "original"),
            self._stroke([(1, 0, 0), (0, 0, 0)], "reversed"),
        ])

        self.assertEqual(result.diagnostics.near_duplicate_pairs, (("original", "reversed"),))

    def test_genuinely_separate_measurements_are_not_reported(self):
        result = self._ingest([
            self._stroke([(0, 0, 0), (1, 0, 0)], "one"),
            self._stroke([(0, 5, 0), (1, 5, 0)], "two"),
        ])

        self.assertEqual(len(result.raw_measurements), 2)
        self.assertEqual(result.diagnostics.near_duplicate_pairs, ())


class AnnotationFrameTests(unittest.TestCase):
    def setUp(self):
        self.bpy, _ = install_bpy_stub()
        install_mathutils_stub()
        self.annotations = load_addon_module("infrastructure.blender_annotations")

    def _layer_with_frames(self, frames):
        def stroke(points):
            return types.SimpleNamespace(
                points=[types.SimpleNamespace(co=types.SimpleNamespace(x=x, y=y, z=z)) for x, y, z in points]
            )

        return types.SimpleNamespace(
            frames=[
                types.SimpleNamespace(frame_number=number, strokes=[stroke(points) for points in strokes])
                for number, strokes in frames
            ]
        )

    def test_strokes_carry_their_frame_number(self):
        layer = self._layer_with_frames([
            (1, [[(0, 0, 0), (1, 0, 0)]]),
            (25, [[(0, 0, 0), (1, 0, 0)]]),
        ])

        frames = [frame for frame, _stroke in self.annotations.iter_layer_strokes_with_frames(layer)]

        self.assertEqual(frames, [1, 25])

    def test_the_summary_reports_every_frame_that_holds_measurements(self):
        layer = self._layer_with_frames([
            (1, [[(0, 0, 0), (1, 0, 0)]]),
            (25, [[(0, 0, 0), (1, 0, 0)]]),
        ])
        finder = lambda name="RulerData3D": (types.SimpleNamespace(name="Annotations"), layer)

        with unittest.mock.patch.object(self.annotations, "find_annotation_layer", finder):
            summary = self.annotations.annotation_layer_summary()

        self.assertTrue(summary["found"])
        self.assertEqual(summary["stroke_count"], 2)
        self.assertEqual(summary["frame_count"], 2)
        self.assertEqual(summary["frame_numbers"], (1, 25))


class MeasurementNameTests(unittest.TestCase):
    def setUp(self):
        install_bpy_stub()
        self.scene_measurements = load_addon_module("scene_measurements")

    def test_names_stay_unique_after_a_deletion(self):
        """Numbering by collection length repeats a name once anything is
        deleted, which produces two rows with the same name in the CSV."""
        scene = types.SimpleNamespace(
            scientia_measurements=[
                types.SimpleNamespace(name="M1"),
                types.SimpleNamespace(name="M3"),
            ]
        )

        name = self.scene_measurements.next_measurement_name(scene)

        self.assertNotIn(name, {"M1", "M3"})


if __name__ == "__main__":
    unittest.main()
