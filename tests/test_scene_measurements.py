import types
import unittest

from tests.addon_test_utils import install_bpy_stub, load_addon_module


class FakeCollection(list):
    def __init__(self, item_factory):
        super().__init__()
        self._item_factory = item_factory

    def add(self):
        item = self._item_factory()
        self.append(item)
        return item

    def remove(self, index):
        del self[index]


def code_item(name="", visible=True, color=(0.1, 0.65, 1.0, 1.0)):
    return types.SimpleNamespace(name=name, visible=visible, color=color)


class SceneMeasurementTests(unittest.TestCase):
    def setUp(self):
        install_bpy_stub()
        self.scene_measurements = load_addon_module("scene_measurements")

    def test_sync_codes_removes_unused_and_adds_missing(self):
        codes = FakeCollection(lambda: code_item())
        codes.extend([
            code_item("J1", visible=False, color=(0.9, 0.1, 0.1, 1.0)),
            code_item("STALE", visible=True, color=(0.1, 0.9, 0.1, 1.0)),
        ])
        scene = types.SimpleNamespace(
            scientia_measurement_codes=codes,
            scientia_measurements=[
                types.SimpleNamespace(code="J1"),
                types.SimpleNamespace(code="J2"),
                types.SimpleNamespace(code=""),
            ],
            scientia_measure_default_color=(0.2, 0.3, 0.4, 1.0),
        )

        self.scene_measurements.sync_scene_measurement_codes(scene)

        self.assertEqual([item.name for item in codes], ["J1", "J2"])
        self.assertFalse(codes[0].visible)
        self.assertEqual(codes[0].color, (0.9, 0.1, 0.1, 1.0))
        self.assertEqual(codes[1].color, (0.2, 0.3, 0.4, 1.0))

    def test_sync_codes_tracks_code_renames(self):
        codes = FakeCollection(lambda: code_item())
        codes.extend([code_item("WRONG"), code_item("J3")])
        scene = types.SimpleNamespace(
            scientia_measurement_codes=codes,
            scientia_measurements=[types.SimpleNamespace(code="J3")],
            scientia_measure_default_color=(0.2, 0.3, 0.4, 1.0),
        )

        self.scene_measurements.sync_scene_measurement_codes(scene)

        self.assertEqual([item.name for item in codes], ["J3"])


if __name__ == "__main__":
    unittest.main()
