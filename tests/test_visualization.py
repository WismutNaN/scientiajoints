import os
import types
import unittest

from tests.addon_test_utils import (
    has_modules,
    install_bpy_stub,
    install_mathutils_stub,
    load_addon_module,
)


class VisualizationTests(unittest.TestCase):
    def setUp(self):
        install_mathutils_stub()
        self.bpy, _save_calls = install_bpy_stub()
        load_addon_module("parser")
        self.visualization = load_addon_module("visualization")

    def empty_context(self):
        scene = types.SimpleNamespace(
            az_real=0.0,
            az_model=0.0,
            figure_width=6.0,
            figure_height=6.0,
            marker_size=2.0,
            edge_width=0.4,
            marker_face_color=(1.0, 1.0, 1.0),
            marker_edge_color=(0.0, 0.0, 0.0),
            density_sigma=1.2,
            stereonet_hemisphere="UPPER",
        )
        self.bpy.context.scene = scene
        return types.SimpleNamespace(scene=scene)

    def test_empty_data_returns_no_images(self):
        visualizer = self.visualization.Visualizer([], [])

        histogram_path, stats = visualizer.plot_edges_histogram()
        stereonet_path = visualizer.plot_faces_stereonet()

        self.assertIsNone(histogram_path)
        self.assertEqual(stats, {})
        self.assertIsNone(stereonet_path)

    def test_marker_color_uses_measurement_color_when_available(self):
        self.assertEqual(
            self.visualization._marker_color((0.2, 0.3, 0.4, 1.0), (1.0, 1.0, 1.0)),
            (0.2, 0.3, 0.4, 1.0),
        )
        self.assertEqual(
            self.visualization._marker_color(None, (1.0, 1.0, 1.0)),
            (1.0, 1.0, 1.0),
        )

    def test_update_functions_return_false_when_no_image_is_created(self):
        context = self.empty_context()

        self.assertFalse(self.visualization.update_histogram_image(context, report_errors=False))
        self.assertFalse(self.visualization.update_stereonet_image(context, report_errors=False))

    @unittest.skipUnless(has_modules("matplotlib", "numpy"), "matplotlib/numpy are not installed")
    def test_histogram_smoke(self):
        edge = types.SimpleNamespace(length=1.0)
        visualizer = self.visualization.Visualizer([edge], [])

        histogram_path, stats = visualizer.plot_edges_histogram()

        self.assertTrue(histogram_path)
        self.assertTrue(os.path.exists(histogram_path))
        self.assertAlmostEqual(stats["Mean"], 1.0, places=6)

    @unittest.skipUnless(has_modules("matplotlib", "mplstereonet"), "matplotlib/mplstereonet are not installed")
    def test_stereonet_smoke(self):
        import matplotlib

        matplotlib.use("Agg", force=True)
        faces = [
            types.SimpleNamespace(rotated_azimuth=0.0, dip=0.0),
            types.SimpleNamespace(rotated_azimuth=90.0, dip=45.0),
            types.SimpleNamespace(rotated_azimuth=180.0, dip=90.0),
        ]

        visualizer = self.visualization.Visualizer([], faces)
        # The density contours are the point of the stereonet, and a failure
        # there is only logged: the image still comes out, with poles and no
        # density, which is how a broken mplstereonet went unnoticed.
        with self.assertNoLogs(self.visualization.logger, level="WARNING"):
            stereonet_path = visualizer.plot_faces_stereonet()

        self.assertTrue(stereonet_path)
        self.assertTrue(os.path.exists(stereonet_path))

    @unittest.skipUnless(has_modules("numpy"), "numpy is not installed")
    def test_the_numpy_aliases_mplstereonet_needs_are_restored_and_removed_again(self):
        """mplstereonet up to 0.6.2 writes ``dtype=np.float``, gone since numpy
        1.24. Density contours failed with numpy 2.x until this put it back."""
        import numpy as np

        before = {name: hasattr(np, name) for name in ("float", "int")}

        with self.visualization._numpy_legacy_aliases():
            self.assertIs(np.float, float)
            self.assertIs(np.int, int)

        for name, existed in before.items():
            self.assertEqual(hasattr(np, name), existed, f"np.{name} was left behind")

    @unittest.skipUnless(has_modules("numpy"), "numpy is not installed")
    def test_an_alias_numpy_still_defines_is_left_alone(self):
        import numpy as np

        np.float = "not ours"
        try:
            with self.visualization._numpy_legacy_aliases():
                self.assertEqual(np.float, "not ours")
            self.assertEqual(np.float, "not ours")
        finally:
            del np.float


if __name__ == "__main__":
    unittest.main()
