"""Viewport overlay style: line width, point handles and area fill.

These settings only exist to change what the viewport draws, and nothing about
a drawing mistake is visible from a test run of the add-on, so the geometry and
the values handed to the GPU are checked directly.
"""

import math
import types
import unittest

from tests.addon_test_utils import install_bpy_stub, install_mathutils_stub, load_addon_module


class _Scene:
    """A scene carrying only the overlay properties, like a real one does
    before or after the add-on registers them."""

    def __init__(self, **properties):
        self.__dict__.update(properties)


class OverlayStyleValueTests(unittest.TestCase):
    def setUp(self):
        install_mathutils_stub()
        install_bpy_stub()
        self.measurements = load_addon_module("scene_measurements")

    def test_defaults_apply_when_the_properties_do_not_exist_yet(self):
        """Draw handlers outlive an add-on reload by a redraw or two."""
        scene = _Scene()

        self.assertEqual(self.measurements.scene_measure_line_width(scene), self.measurements.DEFAULT_LINE_WIDTH)
        self.assertEqual(self.measurements.scene_measure_point_size(scene), self.measurements.DEFAULT_POINT_SIZE)
        self.assertTrue(self.measurements.scene_measure_points_visible(scene))
        self.assertEqual(self.measurements.scene_measure_fill_alpha(scene), self.measurements.DEFAULT_FILL_ALPHA)

    def test_values_are_clamped_to_what_the_gpu_can_draw(self):
        self.assertEqual(
            self.measurements.scene_measure_line_width(_Scene(scientia_measure_line_width=1000.0)),
            self.measurements.MAX_LINE_WIDTH,
        )
        self.assertEqual(
            self.measurements.scene_measure_line_width(_Scene(scientia_measure_line_width=-5.0)),
            self.measurements.MIN_LINE_WIDTH,
        )
        self.assertEqual(
            self.measurements.scene_measure_point_size(_Scene(scientia_measure_point_size=0.0)),
            self.measurements.MIN_POINT_SIZE,
        )

    def test_a_value_that_is_not_a_number_falls_back_to_the_default(self):
        scene = _Scene(scientia_measure_line_width="thick")

        self.assertEqual(self.measurements.scene_measure_line_width(scene), self.measurements.DEFAULT_LINE_WIDTH)

    def test_switching_the_fill_off_reports_no_opacity(self):
        scene = _Scene(scientia_measure_fill_planes=False, scientia_measure_fill_alpha=0.8)

        self.assertEqual(self.measurements.scene_measure_fill_alpha(scene), 0.0)

    def test_the_fill_opacity_is_used_when_the_fill_is_on(self):
        scene = _Scene(scientia_measure_fill_planes=True, scientia_measure_fill_alpha=0.6)

        self.assertAlmostEqual(self.measurements.scene_measure_fill_alpha(scene), 0.6)


class AreaFillGeometryTests(unittest.TestCase):
    def setUp(self):
        install_mathutils_stub()
        install_bpy_stub()
        self.tool = load_addon_module("custom_measure_tool")

    def test_a_linear_measurement_is_never_filled(self):
        """Two points enclose no area, so there is nothing to shade."""
        self.assertEqual(self.tool._area_fill_coords([(0, 0, 0), (1, 0, 0)]), ())
        self.assertEqual(self.tool._area_fill_coords([(0, 0, 0)]), ())
        self.assertEqual(self.tool._area_fill_coords([]), ())

    def test_a_three_point_plane_is_one_triangle(self):
        points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]

        self.assertEqual(self.tool._area_fill_coords(points), tuple(points))

    def test_a_polygon_is_covered_by_triangles_over_its_own_points(self):
        points = [(0, 0, 0), (2, 0, 0), (2, 2, 0), (1, 3, 0), (0, 2, 0)]

        coords = self.tool._area_fill_coords(points)

        self.assertEqual(len(coords) % 3, 0)
        self.assertEqual(len(coords) // 3, len(points) - 2, "a simple polygon needs n-2 triangles")
        for corner in coords:
            self.assertIn(corner, points, "the fill must not invent points outside the outline")

    def test_the_fan_fallback_covers_the_polygon_when_blender_is_not_there(self):
        """``mathutils.geometry`` is missing outside Blender, and the fill still
        has to come out rather than the overlay raising mid-draw."""
        points = [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)]

        coords = self.tool._fan_fill_coords(points)

        self.assertEqual(len(coords), (len(points) - 2) * 3)
        self.assertEqual(coords[:3], (points[0], points[1], points[2]))

    def test_the_fill_keeps_the_measurement_colour_and_takes_the_opacity(self):
        self.assertEqual(self.tool._fill_color((0.1, 0.65, 1.0, 1.0), 0.25), (0.1, 0.65, 1.0, 0.25))


class HandleStyleTests(unittest.TestCase):
    def setUp(self):
        install_mathutils_stub()
        install_bpy_stub()
        self.tool = load_addon_module("custom_measure_tool")
        self.tool._reset_preview()

    def _gather(self, scene, points, measurement_index=0):
        """Run the handle pass and report what each handle was gathered with."""
        batches = self.tool.HandleBatches()
        positions = [(float(index), 0.0) for index in range(len(points))]
        self.tool._gather_screen_handles(
            positions,
            batches,
            (0.1, 0.65, 1.0, 1.0),
            measurement_index,
            scene,
            len(points),
            self.tool._active_preview["hover"],
        )
        return batches

    def _sizes(self, batches):
        return sorted(radius * 2.0 for _color, radius in batches.groups)

    def test_handles_scale_with_the_configured_point_size(self):
        scene = _Scene(scientia_measure_point_size=20.0, scientia_active_measurement_index=0)

        batches = self._gather(scene, [(0, 0, 0), (1, 0, 0)])

        self.assertEqual(batches.points, 2)
        self.assertEqual(self._sizes(batches), [20.0])

    def test_the_default_point_size_keeps_the_sizes_the_overlay_always_had(self):
        points = [(0, 0, 0), (1, 0, 0)]

        active = self._gather(_Scene(scientia_active_measurement_index=0), points)
        inactive = self._gather(_Scene(scientia_active_measurement_index=5), points)

        self.assertEqual(self._sizes(active), [8.0])
        self.assertEqual(self._sizes(inactive), [6.4])

    def test_every_handle_of_one_measurement_shares_a_batch_group(self):
        """Grouping by colour and radius is what turns thousands of draw calls
        into a handful."""
        scene = _Scene(scientia_active_measurement_index=0)

        batches = self._gather(scene, [(0, 0, 0)] * 50)

        self.assertEqual(batches.points, 50)
        self.assertEqual(len(batches.groups), 1)

    def test_only_the_hinge_point_of_a_plane_is_marked(self):
        """Every handle is the same round dot now, so the middle point of a
        three-point plane needs a mark to stay distinguishable."""
        scene = _Scene(scientia_active_measurement_index=0)

        plane = self._gather(scene, [(0, 0, 0), (1, 0, 0), (0, 1, 0)])
        linear = self._gather(scene, [(0, 0, 0), (1, 0, 0)])
        polygon = self._gather(scene, [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])

        self.assertEqual(sum(len(marks) for marks in plane.marks.values()), 1)
        self.assertEqual(linear.marks, {})
        self.assertEqual(polygon.marks, {})

    def test_a_point_behind_the_view_is_skipped(self):
        scene = _Scene(scientia_active_measurement_index=0)
        batches = self.tool.HandleBatches()

        self.tool._gather_screen_handles(
            [None, (1.0, 2.0), None],
            batches,
            (1, 1, 1, 1),
            0,
            scene,
            3,
            self.tool._active_preview["hover"],
        )

        self.assertEqual(batches.points, 1)

    def test_the_default_line_width_leaves_the_outlines_untouched(self):
        self.assertEqual(self.tool._outline_width_scale(_Scene()), 1.0)


class HandleGeometryTests(unittest.TestCase):
    """The merged vertex buffers the handle batches turn into."""

    def setUp(self):
        install_mathutils_stub()
        install_bpy_stub()
        self.tool = load_addon_module("custom_measure_tool")

    def test_a_disc_is_a_closed_fan_of_the_configured_segment_count(self):
        coords = self.tool._disc_vertices([([(0.0, 0.0)], 4.0)])

        self.assertEqual(len(coords), self.tool.HANDLE_CIRCLE_SEGMENTS * 3)
        self.assertEqual(len(coords) % 3, 0)

    def test_a_ring_is_a_closed_loop_of_line_segments(self):
        coords = self.tool._ring_vertices([([(0.0, 0.0)], 4.0)])

        self.assertEqual(len(coords), self.tool.HANDLE_CIRCLE_SEGMENTS * 2)

    def test_every_centre_contributes_the_same_amount_of_geometry(self):
        one = self.tool._disc_vertices([([(0.0, 0.0)], 4.0)])
        three = self.tool._disc_vertices([([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)], 4.0)])

        self.assertEqual(len(three), len(one) * 3)

    def test_discs_stay_within_their_radius_of_their_centre(self):
        coords = self.tool._disc_vertices([([(100.0, 50.0)], 4.0)])

        for x, y in coords:
            self.assertLessEqual(math.hypot(x - 100.0, y - 50.0), 4.0 + 1e-4)

    def test_no_centres_produces_no_geometry(self):
        self.assertEqual(len(self.tool._disc_vertices([])), 0)
        self.assertEqual(len(self.tool._disc_vertices([([], 4.0)])), 0)


class VisibleMeasurementTests(unittest.TestCase):
    """Which measurements the overlay spends a frame on, and in what order."""

    def setUp(self):
        install_mathutils_stub()
        install_bpy_stub()
        self.tool = load_addon_module("custom_measure_tool")
        self.tool._reset_preview()
        self.tool.clear_geometry_cache()

    def _scene(self, count=6, **properties):
        properties.setdefault("scientia_active_measurement_index", 1)
        measurements = [_Measurement(((index, 0, 0), (index, 1, 0))) for index in range(count)]
        return _Scene(scientia_measurements=measurements, **properties)

    def _visible(self, scene):
        view3d_utils = types.SimpleNamespace(
            location_3d_to_region_2d=lambda region, region_data, point: types.SimpleNamespace(x=0.0, y=0.0),
        )
        context = types.SimpleNamespace(region=None, region_data=None)
        return self.tool._visible_measurements(scene, context, view3d_utils, {})

    def test_the_active_and_hovered_measurement_always_come_first(self):
        """No budget may drop the measurement being edited or picked."""
        self.tool._active_preview["hover"] = (4, "point", 0)

        entries = self._visible(self._scene())

        self.assertEqual([entry.index for entry in entries[:2]], [1, 4])
        self.assertTrue(all(entry.always for entry in entries[:2]))
        self.assertFalse(any(entry.always for entry in entries[2:]))

    def test_no_measurement_appears_twice(self):
        self.tool._active_preview["hover"] = (1, "point", 0)

        entries = self._visible(self._scene())

        indices = [entry.index for entry in entries]
        self.assertEqual(len(indices), len(set(indices)))

    def test_the_budget_caps_how_many_measurements_are_considered(self):
        scene = self._scene(
            count=500, scientia_measure_max_handle_points=10, scientia_measure_max_labels=4
        )

        entries = self._visible(scene)

        self.assertLessEqual(len(entries), 10, "a tight budget must not walk the whole scene")

    def test_switching_handles_off_still_yields_the_active_measurement(self):
        scene = self._scene(scientia_measure_show_points=False, scientia_measure_max_labels=0)

        entries = self._visible(scene)

        self.assertEqual(entries[0].index, 1)
        self.assertTrue(entries[0].always)

    def test_a_measurement_with_no_points_is_skipped(self):
        scene = self._scene(count=3)
        scene.scientia_measurements[2] = _Measurement(())

        indices = [entry.index for entry in self._visible(scene)]

        self.assertNotIn(2, indices)


class LabelLayoutTests(unittest.TestCase):
    """Labels sit centred on the measurement they name, at a configurable size,
    on a rounded plate."""

    def setUp(self):
        install_mathutils_stub()
        install_bpy_stub()
        self.measurements = load_addon_module("scene_measurements")
        self.tool = load_addon_module("custom_measure_tool")

    def test_the_line_height_follows_the_text_size(self):
        default = self.measurements.DEFAULT_LABEL_SIZE

        self.assertAlmostEqual(self.tool._label_line_height(default), 14.0)
        self.assertAlmostEqual(self.tool._label_line_height(default * 2), 28.0)

    def test_the_label_size_is_clamped_and_defaults_like_the_other_style_values(self):
        self.assertEqual(
            self.measurements.scene_measure_label_size(_Scene()), self.measurements.DEFAULT_LABEL_SIZE
        )
        self.assertEqual(
            self.measurements.scene_measure_label_size(_Scene(scientia_measure_label_size=500.0)),
            self.measurements.MAX_LABEL_SIZE,
        )

    def test_the_block_is_centred_on_the_anchor_not_hanging_off_it(self):
        position = types.SimpleNamespace(x=100.0, y=200.0)

        block = self.tool._label_block(position, [40.0, 60.0], 2, 14.0)

        self.assertEqual((block.center_x, block.center_y), (100.0, 200.0))
        self.assertEqual(block.width, 60.0, "the block is as wide as its widest line")
        self.assertEqual(block.height, 28.0)
        self.assertAlmostEqual(block.top - block.height * 0.5, 200.0)

    def test_a_single_line_label_still_straddles_the_anchor(self):
        position = types.SimpleNamespace(x=0.0, y=0.0)

        block = self.tool._label_block(position, [30.0], 1, 14.0)

        self.assertAlmostEqual(block.top, 7.0)
        self.assertAlmostEqual(block.top - block.height, -7.0)

    def test_an_empty_label_does_not_produce_a_negative_box(self):
        block = self.tool._label_block(types.SimpleNamespace(x=0.0, y=0.0), [], 0, 14.0)

        self.assertEqual(block.width, 0.0)
        self.assertGreater(block.height, 0.0)

    def test_the_plate_corners_are_rounded_within_the_rectangle(self):
        coords = self.tool._rounded_rect_coords(0.0, 0.0, 100.0, 40.0, 8.0)

        self.assertEqual(len(coords) % 3, 0)
        for x, y in coords:
            self.assertTrue(0.0 <= x <= 100.0 and 0.0 <= y <= 40.0, "the plate must stay in its box")
        corners = ((0.0, 0.0), (100.0, 0.0), (100.0, 40.0), (0.0, 40.0))
        for corner in corners:
            self.assertNotIn(corner, coords, "a rounded plate has no square corner vertex")

    def test_a_radius_bigger_than_the_plate_is_capped_instead_of_inverting_it(self):
        coords = self.tool._rounded_rect_coords(0.0, 0.0, 20.0, 10.0, 999.0)

        for x, y in coords:
            self.assertTrue(0.0 <= x <= 20.0 and 0.0 <= y <= 10.0)

    def test_a_zero_radius_falls_back_to_a_plain_rectangle(self):
        coords = self.tool._rounded_rect_coords(0.0, 0.0, 10.0, 10.0, 0.0)

        self.assertEqual(len(coords), 6, "two triangles, no corner fans")
        self.assertIn((0.0, 0.0), coords)


class LabelAnchorTests(unittest.TestCase):
    """Where the label of an area measurement hangs. On the corner point the
    plane hinges on, the text lands beside the shape it describes."""

    def setUp(self):
        install_mathutils_stub()
        install_bpy_stub()
        self.tool = load_addon_module("custom_measure_tool")
        from mathutils import Vector

        self.Vector = Vector

    def _points(self, *coordinates):
        return [self.Vector(coordinate) for coordinate in coordinates]

    def test_a_triangle_label_sits_at_the_centroid(self):
        points = self._points((0, 0, 0), (6, 0, 0), (0, 6, 0))

        anchor = self.tool._plane_label_anchor(points, _Scene(scientia_measure_label_at_center=True))

        self.assertEqual(tuple(anchor), (2.0, 2.0, 0.0))

    def test_switching_it_off_restores_the_hinge_corner(self):
        points = self._points((0, 0, 0), (6, 0, 0), (0, 6, 0))

        anchor = self.tool._plane_label_anchor(points, _Scene(scientia_measure_label_at_center=False))

        self.assertEqual(tuple(anchor), (6.0, 0.0, 0.0), "the middle point is the hinge")

    def test_it_is_on_by_default(self):
        points = self._points((0, 0, 0), (6, 0, 0), (0, 6, 0))

        self.assertEqual(tuple(self.tool._plane_label_anchor(points, _Scene())), (2.0, 2.0, 0.0))

    def test_the_centre_is_weighted_by_area_not_by_corner_count(self):
        """A long thin spur carries corners but almost no area; averaging the
        corners drags the label off the body of the shape."""
        points = self._points((0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0), (0.0, 10.2, 0), (0, 10.4, 0))

        centre = self.tool._area_center(points)
        corner_average = self.tool._average_point(points)

        self.assertAlmostEqual(centre.x, 5.0, places=1)
        self.assertAlmostEqual(centre.y, 5.0, places=1)
        self.assertLess(centre.y, corner_average.y)

    def test_a_square_centres_on_its_middle(self):
        points = self._points((0, 0, 0), (4, 0, 0), (4, 4, 0), (0, 4, 0))

        centre = self.tool._area_center(points)

        self.assertAlmostEqual(centre.x, 2.0)
        self.assertAlmostEqual(centre.y, 2.0)

    def test_a_tilted_plane_keeps_its_centre_on_the_surface(self):
        points = self._points((0, 0, 0), (6, 0, 6), (0, 6, 0))

        centre = self.tool._area_center(points)

        self.assertEqual(tuple(centre), (2.0, 2.0, 2.0))

    def test_a_degenerate_outline_falls_back_instead_of_dividing_by_zero(self):
        """Three points on one line enclose no area, and the label still has to
        go somewhere."""
        collinear = self._points((0, 0, 0), (1, 0, 0), (2, 0, 0))
        coincident = self._points((3, 3, 3), (3, 3, 3), (3, 3, 3))

        self.assertEqual(tuple(self.tool._area_center(collinear)), (1.0, 0.0, 0.0))
        self.assertEqual(tuple(self.tool._area_center(coincident)), (3.0, 3.0, 3.0))

    def test_a_linear_measurement_still_labels_at_its_midpoint(self):
        label, anchor = self.tool._measurement_label(self._points((0, 0, 0), (4, 2, 0)), None, None)

        self.assertEqual(tuple(anchor), (2.0, 1.0, 0.0))


class _Measurement:
    def __init__(self, points, kind="PLANE", code="", color=(0.1, 0.65, 1.0, 1.0)):
        self.points = tuple(types.SimpleNamespace(co=point) for point in points)
        self.kind = kind
        self.code = code
        self.color = color


class _RecordingGPU(types.ModuleType):
    """A gpu module that records the state changes and batches it is asked for."""

    def __init__(self, batches):
        super().__init__("gpu")
        self.batches = batches
        self.line_widths = []
        self.point_sizes = []
        outer = self

        class _State:
            @staticmethod
            def blend_set(mode):
                pass

            @staticmethod
            def line_width_set(width):
                outer.line_widths.append(width)

            @staticmethod
            def point_size_set(size):
                outer.point_sizes.append(size)

        class _Shader:
            @staticmethod
            def bind():
                pass

            @staticmethod
            def uniform_float(name, value):
                outer.batches[-1]["color"] = value

        self.state = _State
        self.shader = types.SimpleNamespace(from_builtin=lambda name: _Shader)


class ThreeDimensionalFillTests(unittest.TestCase):
    """The fill is only useful if the 3D pass actually emits it for stored
    measurements, which is a separate question from the geometry being right."""

    def setUp(self):
        install_mathutils_stub()
        self.bpy, _ = install_bpy_stub()
        self.tool = load_addon_module("custom_measure_tool")
        self.tool._reset_preview()
        self.tool._reset_polygon_preview()

    def _draw(self, **scene_properties):
        # A four-point polygon rather than a three-point plane: the angle arc a
        # plane also draws needs vector maths the mathutils stub does not have,
        # and the fill dispatch under test is the same for both.
        batches = []
        scene = _Scene(
            scientia_measurements=[_Measurement(((0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)))],
            scientia_active_measurement_index=-1,
            **scene_properties,
        )
        self.bpy.context.scene = scene

        gpu = _RecordingGPU(batches)
        batch_module = types.ModuleType("gpu_extras.batch")

        def batch_for_shader(shader, primitive, content, indices=None):
            batches.append({"type": primitive, "coords": list(content["pos"])})
            return types.SimpleNamespace(draw=lambda shader: None)

        batch_module.batch_for_shader = batch_for_shader
        gpu_extras = types.ModuleType("gpu_extras")
        gpu_extras.batch = batch_module
        import sys as _sys

        _sys.modules.update({"gpu": gpu, "gpu_extras": gpu_extras, "gpu_extras.batch": batch_module})
        self.tool._draw_measurements_3d()
        return gpu, batches

    def test_an_area_measurement_is_filled_at_the_configured_opacity(self):
        _gpu, batches = self._draw(scientia_measure_fill_planes=True, scientia_measure_fill_alpha=0.4)

        fills = [batch for batch in batches if batch["type"] == "TRIS"]
        self.assertEqual(len(fills), 1)
        self.assertEqual(len(fills[0]["coords"]), 6, "a quad is two triangles")
        self.assertAlmostEqual(fills[0]["color"][3], 0.4)

    def test_the_fill_is_drawn_under_the_outline(self):
        _gpu, batches = self._draw(scientia_measure_fill_planes=True)

        kinds = [batch["type"] for batch in batches]
        self.assertLess(kinds.index("TRIS"), kinds.index("LINES"))

    def test_switching_the_fill_off_emits_no_triangles_at_all(self):
        _gpu, batches = self._draw(scientia_measure_fill_planes=False)

        self.assertEqual([batch for batch in batches if batch["type"] == "TRIS"], [])

    def test_the_configured_line_width_reaches_the_gpu(self):
        gpu, _batches = self._draw(scientia_measure_line_width=6.0)

        self.assertIn(6.0, gpu.line_widths)


class _FakeLayout:
    """Records the property names a panel draws, ignoring the layout calls."""

    def __init__(self, drawn):
        self.drawn = drawn
        self.enabled = True

    def prop(self, owner, name, **kwargs):
        self.drawn.append(name)

    def row(self, **kwargs):
        return _FakeLayout(self.drawn)

    def column(self, **kwargs):
        return _FakeLayout(self.drawn)

    def separator(self, **kwargs):
        pass

    def label(self, **kwargs):
        pass


class OverlayStylePanelTests(unittest.TestCase):
    """A property name typed wrong in the panel raises only when a user opens
    the section, which is not where it should be found."""

    def setUp(self):
        install_mathutils_stub()
        install_bpy_stub()
        self.measurements = load_addon_module("scene_measurements")
        self.panel = load_addon_module("panel")

    def _draw(self, expanded):
        drawn = []
        scene = _Scene(
            show_overlay_style_settings=expanded,
            scientia_measure_show_points=True,
            scientia_measure_fill_planes=True,
            scientia_measure_show_labels=True,
        )
        self.panel._draw_overlay_style_settings(_FakeLayout(drawn), scene)
        return drawn

    def test_the_collapsed_section_draws_only_its_own_header(self):
        self.assertEqual(self._draw(expanded=False), ["show_overlay_style_settings"])

    def test_every_setting_the_section_offers_is_a_registered_property(self):
        registered = set(self.measurements.scene_measurement_scene_properties())

        drawn = self._draw(expanded=True)

        self.assertIn("show_overlay_style_settings", drawn)
        for name in drawn:
            if name.startswith("scientia_"):
                self.assertIn(name, registered, f"{name} is drawn but never registered")

    def test_the_section_exposes_every_style_setting(self):
        self.assertEqual(
            [name for name in self._draw(expanded=True) if name.startswith("scientia_")],
            [
                "scientia_measure_line_width",
                "scientia_measure_label_size",
                "scientia_measure_label_at_center",
                "scientia_measure_show_points",
                "scientia_measure_point_size",
                "scientia_measure_fill_planes",
                "scientia_measure_fill_alpha",
                "scientia_measure_max_handle_points",
                "scientia_measure_max_labels",
            ],
        )

    def test_the_panel_toggle_is_cleaned_up_on_unregister(self):
        """A leftover Scene property survives the add-on and confuses the next
        version that defines it differently."""
        import inspect

        source = inspect.getsource(self.panel.clear_properties)

        self.assertIn("show_overlay_style_settings", source)


if __name__ == "__main__":
    unittest.main()
