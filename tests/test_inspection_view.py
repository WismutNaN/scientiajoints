"""The rock inspection view: what the Light button switches to and back from.

The lighting itself is verified against a running Blender; what is checked here
is the logic that has to cope with a colour management config that may or may
not offer the looks it would like.
"""

import types
import unittest

from tests.addon_test_utils import install_bpy_stub, install_mathutils_stub, load_addon_module


def _view_settings(looks):
    """A stand-in for Scene.view_settings offering ``looks``."""
    return types.SimpleNamespace(
        look="None",
        bl_rna=types.SimpleNamespace(
            properties={
                "look": types.SimpleNamespace(
                    enum_items=[types.SimpleNamespace(identifier=name) for name in looks]
                )
            }
        ),
    )


class ContrastLookTests(unittest.TestCase):
    def setUp(self):
        install_mathutils_stub()
        install_bpy_stub()
        self.operators = load_addon_module("operators")

    def test_a_punchy_look_is_preferred(self):
        looks = ["None", "AgX - Base Contrast", "AgX - Punchy", "AgX - Greyscale"]

        self.assertEqual(self.operators._find_contrast_look(_view_settings(looks)), "AgX - Punchy")

    def test_high_contrast_is_the_next_choice(self):
        looks = ["None", "AgX - Medium High Contrast", "AgX - High Contrast"]

        self.assertEqual(
            self.operators._find_contrast_look(_view_settings(looks)), "AgX - High Contrast"
        )

    def test_a_config_without_looks_asks_for_nothing(self):
        """A background Blender reports no looks at all, and the mode still has
        to work; the lighting is what carries the contrast."""
        self.assertEqual(self.operators._find_contrast_look(_view_settings(["None"])), "")

    def test_an_unreadable_look_property_is_not_fatal(self):
        broken = types.SimpleNamespace(look="None", bl_rna=types.SimpleNamespace(properties={}))

        self.assertEqual(self.operators._find_contrast_look(broken), "")


class InspectionSettingsTests(unittest.TestCase):
    """The values exist to make relief readable, so their direction matters more
    than their exact size."""

    def setUp(self):
        install_mathutils_stub()
        install_bpy_stub()
        self.operators = load_addon_module("operators")

    def test_the_sun_grazes_the_surface_rather_than_facing_it(self):
        """A light near the camera flattens relief; a low one shadows it."""
        self.assertGreater(self.operators.RAKING_LIGHT_ELEVATION_DEGREES, 0.0)
        self.assertLess(self.operators.RAKING_LIGHT_ELEVATION_DEGREES, 45.0)

    def test_the_sun_stays_stronger_than_the_ambient_fill(self):
        """Ambient sets the base brightness so the texture reads everywhere, and
        the sun has to stay above it or there is no relief left - only an even
        wash with no shadow to show a fracture by."""
        self.assertGreater(self.operators.INSPECTION_WORLD_STRENGTH, 0.0)
        self.assertGreater(
            self.operators.RAKING_LIGHT_ENERGY, self.operators.INSPECTION_WORLD_STRENGTH
        )

    def test_the_surface_is_matte_and_barely_specular(self):
        """A highlight on wet rock hides the texture the structure is read from."""
        self.assertGreater(self.operators.INSPECTION_ROUGHNESS, 0.75)
        self.assertEqual(self.operators.INSPECTION_METALLIC, 0.0)
        self.assertLess(self.operators.INSPECTION_SPECULAR, 0.2)

    def test_the_shadows_are_crisp_enough_for_a_hairline_fracture(self):
        self.assertLess(self.operators.RAKING_LIGHT_ANGLE_DEGREES, 2.0)

    def test_the_light_is_named_so_it_is_obvious_where_it_came_from(self):
        self.assertIn("ScientiaJoints", self.operators.RAKING_LIGHT_NAME)


if __name__ == "__main__":
    unittest.main()
