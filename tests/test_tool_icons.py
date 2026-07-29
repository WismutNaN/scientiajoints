"""The toolbar artwork for the two workspace tools.

Blender silently falls back to a blank icon when a ``.dat`` file is missing or
malformed - it prints to the console and carries on - so nothing in the running
add-on tells you the icons broke. These tests do.
"""

import tempfile
import unittest
from pathlib import Path

from tests.addon_test_utils import install_bpy_stub, install_mathutils_stub, load_addon_module
from tools.build_release import ICON_DIRECTORY_NAME, REQUIRED_ICONS
from tools.build_tool_icons import CANVAS, ICONS, MAGIC, build_icons, encode


ADDON_ROOT = Path(__file__).resolve().parents[1]
ICON_DIRECTORY = ADDON_ROOT / ICON_DIRECTORY_NAME

#: Magic, canvas header, then 6 coordinate and 12 colour bytes per triangle.
HEADER_SIZE = 8
TRIANGLE_SIZE = 18


class ToolIconFormatTests(unittest.TestCase):
    def test_every_shipped_icon_parses_as_blender_triangle_data(self):
        for icon_name in REQUIRED_ICONS:
            with self.subTest(icon=icon_name):
                data = (ICON_DIRECTORY / icon_name).read_bytes()

                self.assertEqual(data[:4], MAGIC)
                self.assertEqual(tuple(data[4:8]), (CANVAS, CANVAS, 0, 0))
                self.assertEqual((len(data) - HEADER_SIZE) % TRIANGLE_SIZE, 0)
                self.assertGreater(len(data), HEADER_SIZE)

    def test_the_shipped_icons_match_their_source(self):
        """The .dat files are build output; a change to the drawing code that
        was never re-run would ship stale artwork."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            for path in build_icons(temporary_directory):
                with self.subTest(icon=path.name):
                    self.assertEqual(path.read_bytes(), (ICON_DIRECTORY / path.name).read_bytes())

    def test_the_build_requires_exactly_the_icons_that_are_drawn(self):
        self.assertEqual(set(REQUIRED_ICONS), {f"{name}.dat" for name in ICONS})

    def test_a_triangle_needs_three_points(self):
        with self.assertRaisesRegex(ValueError, "triangle"):
            encode([(((0, 0), (10, 10)), (255, 255, 255, 255))])


class ToolIconWiringTests(unittest.TestCase):
    def test_the_workspace_tools_point_at_the_custom_icons(self):
        """A typo in bl_icon costs nothing at import time and quietly restores
        the built-in ruler icon these replaced."""
        install_mathutils_stub()
        install_bpy_stub()
        module = load_addon_module("custom_measure_tool")

        icons = (
            module.ScientiaMeasureWorkSpaceTool.bl_icon,
            module.ScientiaPolygonMeasureWorkSpaceTool.bl_icon,
        )

        self.assertEqual(len(set(icons)), 2, "the two tools must not share one icon")
        for icon in icons:
            with self.subTest(icon=icon):
                self.assertNotEqual(icon, module.FALLBACK_TOOL_ICON)
                self.assertTrue(Path(icon + ".dat").is_file())

    def test_a_missing_icon_falls_back_to_a_built_in_one(self):
        install_mathutils_stub()
        install_bpy_stub()
        module = load_addon_module("custom_measure_tool")

        self.assertEqual(module.tool_icon("scientiajoints.nothing"), module.FALLBACK_TOOL_ICON)


if __name__ == "__main__":
    unittest.main()
