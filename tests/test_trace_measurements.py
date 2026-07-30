"""Trace measurements: an open polyline scored by the sum of its segments.

The distinction that matters throughout is length versus span. A trace between
two points that wanders is longer than the straight line between them, and that
difference is the whole reason the type exists.
"""

import csv
import math
import tempfile
import unittest
from pathlib import Path

from tests.addon_test_utils import install_bpy_stub, install_mathutils_stub, load_addon_module


class _TraceTestCase(unittest.TestCase):
    def setUp(self):
        # infrastructure/__init__ reaches for bpy on import, so it has to be
        # stubbed before the exporters can be loaded.
        install_mathutils_stub()
        install_bpy_stub()
        self.measurements = load_addon_module("domain.measurements")
        self.geometry = load_addon_module("domain.geometry")
        self.exporters = load_addon_module("infrastructure.exporters")
        self.no_correction = self.measurements.AzimuthCorrection()

    def trace(self, points, source_id="t1"):
        return self.measurements.RawMeasurement(
            kind=self.measurements.MeasurementKind.TRACE,
            points=tuple(self.measurements.Point3D(*point) for point in points),
            source="ScientiaScene",
            source_id=source_id,
        )

    def process(self, points, correction=None, source_id="t1"):
        return self.geometry.process_trace_measurement(
            self.trace(points, source_id), correction or self.no_correction
        )

    def write_csv(self, records):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "traces.csv"
            self.exporters.ProcessedTraceCsvWriter().write(str(path), records)
            with path.open(newline="", encoding="utf-8") as handle:
                return list(csv.DictReader(handle))


class TraceGeometryTests(_TraceTestCase):
    def test_length_is_the_sum_of_the_segments_not_the_distance_between_ends(self):
        """A straight line of the same end points would measure 4.0."""
        record = self.process(((0, 0, 0), (2, 2, 0), (4, 0, 0)))

        self.assertAlmostEqual(record.length, 2 * math.sqrt(8))
        self.assertAlmostEqual(record.span_length, 4.0)
        self.assertGreater(record.length, record.span_length)

    def test_segment_breakdown_is_reported(self):
        record = self.process(((0, 0, 0), (3, 0, 0), (3, 4, 0), (3, 4, 12)))

        self.assertEqual(record.segment_count, 3)
        self.assertEqual(record.segment_lengths, (3.0, 4.0, 12.0))
        self.assertAlmostEqual(record.mean_segment_length, 19.0 / 3.0)
        self.assertAlmostEqual(record.length, 19.0)

    def test_a_straight_trace_has_a_sinuosity_of_one(self):
        record = self.process(((0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)))

        self.assertAlmostEqual(record.length / record.span_length, 1.0)

    def test_two_points_are_a_valid_trace(self):
        record = self.process(((0, 0, 0), (0, 5, 0)))

        self.assertEqual(record.segment_count, 1)
        self.assertAlmostEqual(record.length, 5.0)

    def test_the_orientation_is_the_overall_trend_between_the_ends(self):
        """Not the trend of any one segment: a trace zigzagging north still
        trends north."""
        straight = self.process(((0, 0, 0), (0, 10, 0)))
        zigzag = self.process(((0, 0, 0), (2, 3, 0), (-2, 7, 0), (0, 10, 0)))

        self.assertAlmostEqual(
            straight.line_orientation.azimuth, zigzag.line_orientation.azimuth, places=6
        )

    def test_the_azimuth_correction_is_applied(self):
        record = self.process(
            ((0, 0, 0), (0, 10, 0)),
            self.measurements.AzimuthCorrection(az_real=30.0, az_model=0.0),
        )

        self.assertAlmostEqual(
            record.line_orientation.rotated_azimuth,
            (record.line_orientation.azimuth + 30.0) % 360,
        )

    def test_a_trace_has_no_area_or_plane_orientation(self):
        """It is a line on a surface, not a surface."""
        record = self.process(((0, 0, 0), (2, 2, 0), (4, 0, 0)))

        self.assertIsNone(record.area)
        self.assertIsNone(record.plane_orientation)
        self.assertEqual(record.kind, self.measurements.MeasurementKind.TRACE)


class TraceExportTests(_TraceTestCase):
    def test_the_csv_reports_the_total_and_the_segment_breakdown(self):
        rows = self.write_csv([
            self.process(((0, 0, 0), (3, 0, 0), (3, 4, 0)), source_id="a"),
            self.process(((0, 0, 0), (0, 1, 0)), source_id="b"),
        ])

        self.assertEqual(len(rows), 2)
        for column in ("length", "segment_count", "mean_segment_length", "span_length", "sinuosity"):
            self.assertIn(column, rows[0])
        self.assertAlmostEqual(float(rows[0]["length"]), 7.0)
        self.assertEqual(int(rows[0]["segment_count"]), 2)
        self.assertAlmostEqual(float(rows[0]["mean_segment_length"]), 3.5)
        self.assertAlmostEqual(float(rows[0]["min_segment_length"]), 3.0)
        self.assertAlmostEqual(float(rows[0]["max_segment_length"]), 4.0)
        self.assertAlmostEqual(float(rows[0]["span_length"]), 5.0)
        self.assertAlmostEqual(float(rows[0]["sinuosity"]), 1.4)

    def test_a_zero_length_trace_exports_without_dividing_by_zero(self):
        rows = self.write_csv([self.process(((0, 0, 0), (0, 0, 0)))])

        self.assertEqual(rows[0]["sinuosity"], "", "a zero span has no sinuosity to report")


class _Scene:
    def __init__(self, **properties):
        self.__dict__.update(properties)


class _Measurement:
    def __init__(self, kind, point_count=4):
        self.kind = kind
        self.points = tuple(object() for _ in range(point_count))
        self.code = ""


class TraceOverlayTests(unittest.TestCase):
    """How the viewport treats a trace differently from the shapes it sits
    between in the toolbar."""

    def setUp(self):
        install_mathutils_stub()
        install_bpy_stub()
        self.tool = load_addon_module("custom_measure_tool")

    def test_a_trace_outline_never_closes(self):
        """Its two ends are two ends, not a gap waiting to be joined."""
        points = [(0, 0, 0), (1, 0, 0), (2, 1, 0), (3, 0, 0)]

        self.assertFalse(self.tool._measurement_is_polygon(_Measurement("TRACE"), points))
        self.assertTrue(self.tool._measurement_is_polygon(_Measurement("POLYLINE"), points))

    def test_traces_have_their_own_visibility_toggle(self):
        trace = _Measurement("TRACE")

        hidden = _Scene(scientia_measure_show_traces=False)
        shown = _Scene(scientia_measure_show_traces=True)

        self.assertFalse(self.tool._measurement_kind_visible(hidden, trace))
        self.assertTrue(self.tool._measurement_kind_visible(shown, trace))

    def test_hiding_traces_leaves_the_other_kinds_alone(self):
        scene = _Scene(
            scientia_measure_show_traces=False,
            scientia_measure_show_linear=True,
            scientia_measure_show_planes=True,
        )

        self.assertTrue(self.tool._measurement_kind_visible(scene, _Measurement("LINEAR", 2)))
        self.assertTrue(self.tool._measurement_kind_visible(scene, _Measurement("POLYLINE")))
        self.assertFalse(self.tool._measurement_kind_visible(scene, _Measurement("TRACE")))

    def test_hiding_planes_leaves_traces_alone(self):
        """A trace has as many points as a polygon; the kind has to decide, not
        the point count."""
        scene = _Scene(scientia_measure_show_planes=False, scientia_measure_show_traces=True)

        self.assertFalse(self.tool._measurement_kind_visible(scene, _Measurement("POLYLINE")))
        self.assertTrue(self.tool._measurement_kind_visible(scene, _Measurement("TRACE")))

    def test_the_trace_tool_is_the_polygon_tool_without_closing(self):
        """The two share every bit of interaction, so the differences are worth
        pinning down."""
        polygon = self.tool.ScientiaPolygonMeasureOperator
        trace = self.tool.ScientiaTraceMeasureOperator

        self.assertTrue(issubclass(trace, polygon))
        self.assertTrue(polygon.closes)
        self.assertFalse(trace.closes)
        self.assertEqual(polygon.measurement_kind, "POLYLINE")
        self.assertEqual(trace.measurement_kind, "TRACE")
        self.assertEqual(trace.minimum_points, 2, "two points already make a trace")
        self.assertEqual(polygon.minimum_points, 3)

    def test_the_trace_tool_has_its_own_toolbar_entry_and_icon(self):
        tool = self.tool.ScientiaTraceMeasureWorkSpaceTool

        self.assertEqual(tool.bl_idname, "scientiajoints.trace_measure")
        self.assertIn(tool.bl_idname, self.tool.TOOL_IDNAMES)
        self.assertNotEqual(tool.bl_icon, self.tool.FALLBACK_TOOL_ICON)
        self.assertTrue(Path(tool.bl_icon + ".dat").is_file())

    def test_every_tool_has_a_distinct_icon(self):
        icons = [tool.bl_icon for tool in self.tool._WORKSPACE_TOOLS]

        self.assertEqual(len(set(icons)), len(icons))


if __name__ == "__main__":
    unittest.main()
