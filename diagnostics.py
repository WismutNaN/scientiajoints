"""Self-diagnostics report for ScientiaJoints.

Collects everything a support request needs in one copyable block: Blender and
device details, the state of the chart dependencies, what the current ``.blend``
contains, the result of a short self-test, and a list of detected problems with
their probable cause. The module degrades gracefully so the report can still be
produced when the add-on is partially broken.
"""

import logging
import os
import platform
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import dependencies as deps

logger = logging.getLogger(__name__)


@dataclass
class Problem:
    severity: str  # "error" | "warning" | "info"
    title: str
    cause: str = ""
    action: str = ""


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    skipped: bool = False


@dataclass
class Report:
    sections: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    problems: list = field(default_factory=list)

    def add(self, title, lines):
        self.sections.append((title, [line for line in lines if line is not None]))

    @property
    def ok(self):
        return not any(problem.severity == "error" for problem in self.problems)


def _safe(getter, default="unavailable"):
    try:
        value = getter()
        return default if value is None else value
    except Exception as e:
        return f"{default} ({type(e).__name__}: {e})"


def _addon_version():
    try:
        from . import bl_info

        version = ".".join(str(part) for part in bl_info.get("version", ()))
        if version:
            return version
    except Exception:
        pass

    # Installed as an extension: the version lives in the manifest and Blender
    # does not keep bl_info.
    try:
        manifest = Path(__file__).resolve().parent / "blender_manifest.toml"
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if line.startswith("version ="):
                return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return "unknown"


def _install_flavour():
    """Legacy add-on directory or Blender extension."""
    package = __package__ or ""
    if package.startswith("bl_ext."):
        return f"extension ({package})"
    return f"legacy add-on ({package or 'unknown package'})"


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _blender_section():
    import bpy

    def _decode(value):
        return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)

    lines = [
        f"Blender: {_safe(lambda: bpy.app.version_string)}",
        f"Build: {_safe(lambda: _decode(bpy.app.build_hash))} {_safe(lambda: _decode(bpy.app.build_date))}",
        f"Binary: {_safe(lambda: bpy.app.binary_path)}",
        "",
        f"ScientiaJoints version: {_addon_version()}",
        f"Installed as: {_install_flavour()}",
        f"Add-on directory: {Path(__file__).resolve().parent}",
        f"Wheels bundled in this build: {len(deps.available_wheels())}",
    ]
    try:
        preferences = bpy.context.preferences
        lines.append(f"UI scale: {preferences.system.ui_scale:.2f}, DPI {preferences.system.dpi}")
        lines.append(f"Language: {preferences.view.language}")
    except Exception:
        pass
    return lines


def _environment_section():
    lines = [
        f"OS: {platform.platform()}",
        f"Machine: {platform.machine()}, CPU cores {os.cpu_count()}",
        f"Python: {sys.version.split()[0]} ({sys.executable})",
        f"Resolved interpreter for pip: {deps.resolve_python_executable()}",
    ]
    try:
        import gpu

        lines.append(f"GPU backend: {gpu.platform.backend_type_get()}")
        lines.append(f"GPU: {gpu.platform.renderer_get()} | {gpu.platform.vendor_get()}")
        lines.append(f"GPU driver: {gpu.platform.version_get()}")
    except Exception as e:
        lines.append(f"GPU: unavailable ({type(e).__name__}: {e})")

    for variable in ("HTTP_PROXY", "HTTPS_PROXY", "PIP_INDEX_URL", "PIP_CONFIG_FILE", "SSL_CERT_FILE"):
        value = os.environ.get(variable) or os.environ.get(variable.lower())
        if value:
            lines.append(f"{variable}={value}")
    return lines


def _dependency_section(problems):
    lines = []
    too_old = {name: required for name, _, required in deps.outdated_packages()}
    for status in deps.check_required_packages():
        if status.installed and status.name in too_old:
            lines.append(f"{status.name}: TOO OLD {status.version} (need {too_old[status.name]})")
            lines.append(f"  installed by: {deps.package_install_method(status)}")
            lines.append(f"  file: {status.location}")
        elif status.installed:
            lines.append(f"{status.name}: OK {status.version or ''}".rstrip())
            lines.append(f"  installed by: {deps.package_install_method(status)}")
            lines.append(f"  file: {status.location}")
        elif status.error:
            lines.append(f"{status.name}: BROKEN - {status.error}")
        else:
            lines.append(f"{status.name}: NOT INSTALLED")

    lines.append("")
    lines.append("Install directories:")
    for candidate in deps.install_target_candidates():
        remaining = deps.path_budget(candidate.path)
        flags = []
        flags.append("writable" if candidate.writable else "READ-ONLY")
        flags.append("on sys.path" if candidate.on_sys_path else "NOT on sys.path")
        flags.append(f"{remaining} chars left of the Windows path limit")
        lines.append(f"  {candidate.path} [{', '.join(flags)}]")

    wheels = deps.available_wheels()
    lines.append(f"Bundled wheels: {len(wheels)} in {deps.addon_wheels_directory()}")
    for wheel in wheels[:20]:
        lines.append(f"  {Path(wheel).name}")

    target = deps.choose_install_target()
    lines.append(f"Directory the add-on would install into: {target.path if target else 'none usable'}")

    state = deps.read_install_state()
    if state.get("last_attempt"):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(state["last_attempt"]))
        lines.append(f"Last install run by the add-on: {stamp}, ok={state.get('ok')}")
        if state.get("source"):
            lines.append(f"  source used: {state['source']}")
        if state.get("target"):
            lines.append(f"  installed into: {state['target']}")
        if state.get("missing"):
            lines.append(f"  still missing: {', '.join(state['missing'])}")
    else:
        lines.append("Last install run by the add-on: never")

    _collect_dependency_problems(problems)
    return lines


def _collect_dependency_problems(problems):
    statuses = deps.check_required_packages()

    for name, installed, required in deps.outdated_packages():
        problems.append(
            Problem(
                "warning",
                f"{name} {installed} is older than the {required} this add-on needs",
                cause="An earlier ScientiaJoints release, or a separate pip install, left an old "
                      "copy behind. mplstereonet before 0.6.3 uses a numpy alias that no longer "
                      "exists, so the stereonet draws poles but no density contours.",
                action="Install the current release; it carries the newer package. The add-on works "
                       "around the problem meanwhile, so the stereonet is not blank.",
            )
        )

    missing = [status for status in statuses if not status.installed]
    if not missing:
        return

    for status in missing:
        if not status.error:
            problems.append(
                Problem(
                    "error",
                    f"{status.name} is not installed",
                    cause="The package was never installed into Blender's Python, or the install "
                          "directory is not on sys.path.",
                    action="Press Install dependencies in the ScientiaJoints panel, or install the "
                           "extension build that carries the packages inside the archive.",
                )
            )
            continue

        if "FileNotFoundError" in status.error:
            problems.append(
                Problem(
                    "error",
                    f"{status.name} is installed but cannot open its own data files",
                    cause="The Windows 260 character path limit. The files exist but Blender's Python "
                          "cannot open them.",
                    action="Reinstall the packages into a shorter path, or use the extension build "
                           "which stores them under a short directory.",
                )
            )
        elif "numpy" in status.error.lower() and ("size changed" in status.error or "incompat" in status.error.lower()):
            problems.append(
                Problem(
                    "error",
                    f"{status.name} was built against a different numpy",
                    cause="A second numpy copy was installed next to the one Blender bundles.",
                    action="Delete the installed numpy from the install directory listed above and "
                           "reinstall the dependencies.",
                )
            )
        else:
            problems.append(
                Problem(
                    "error",
                    f"{status.name} fails to import",
                    cause=status.error,
                    action="Reinstall the dependencies; keep the full report for a support request.",
                )
            )

    target = deps.choose_install_target()
    if target is None:
        problems.append(
            Problem(
                "error",
                "No usable directory to install packages into",
                cause="Every candidate directory is read-only, missing from sys.path, or too deep for "
                      "the Windows path limit.",
                action="Run Blender as the same user that owns the configuration directory, or install "
                       "the extension build.",
            )
        )
    else:
        remaining = deps.path_budget(target.path)
        if remaining < deps.LONGEST_RELATIVE_PACKAGE_PATH:
            problems.append(
                Problem(
                    "warning",
                    "The install directory is close to the Windows path limit",
                    cause=f"Only {remaining} characters remain; matplotlib needs about "
                          f"{deps.LONGEST_RELATIVE_PACKAGE_PATH}.",
                    action="Move the Blender configuration directory to a shorter path.",
                )
            )


def _file_section(context, problems):
    import bpy

    lines = []
    saved = bool(getattr(bpy.data, "is_saved", False))
    lines.append(f"Blend file: {'saved' if saved else 'NOT SAVED'}")
    if saved:
        lines.append(f"Path: {bpy.data.filepath}")
        lines.append(f"Path length: {len(bpy.data.filepath)} characters")
    else:
        problems.append(
            Problem(
                "warning",
                "The .blend file is not saved",
                cause="Exports are written next to the .blend file, so there is nowhere to write.",
                action="Save the file before exporting.",
            )
        )

    scene = getattr(context, "scene", None)
    if scene is None:
        lines.append("Scene: unavailable")
        return lines

    lines.append(f"Scene: {scene.name}, frame {scene.frame_current}")
    try:
        units = scene.unit_settings
        lines.append(
            f"Units: {units.system}, scale_length {units.scale_length}, length unit {units.length_unit}"
        )
    except Exception:
        pass
    lines.append(f"Azimuth correction: real {scene.az_real:.2f}, model {scene.az_model:.2f}")
    lines.append(f"Stereonet hemisphere: {getattr(scene, 'stereonet_hemisphere', 'unknown')}")
    return lines


def _measurement_section(context, problems):
    lines = []
    scene = getattr(context, "scene", None)

    scene_measurements = list(getattr(scene, "scientia_measurements", ()) or ()) if scene else []
    lines.append(f"Scientia scene measurements: {len(scene_measurements)}")
    kinds = {}
    for measurement in scene_measurements:
        kinds[str(measurement.kind)] = kinds.get(str(measurement.kind), 0) + 1
    for kind, count in sorted(kinds.items()):
        lines.append(f"  {kind}: {count}")

    codes = list(getattr(scene, "scientia_measurement_codes", ()) or ()) if scene else []
    if codes:
        lines.append("Codes: " + ", ".join(f"{code.name}{'' if code.visible else ' (hidden)'}" for code in codes))

    lines.extend(_annotation_lines(problems))

    try:
        from .parser import MeasurementsParser

        parser = MeasurementsParser()
        lines.append(
            f"Parsed: {len(parser.edges)} linear, {len(parser.faces)} plane, "
            f"{parser.total_strokes_count} source strokes"
        )
        if parser.duplicate_strokes_count:
            lines.append(f"Exact duplicates skipped: {parser.duplicate_strokes_count}")
        if parser.ignored_strokes_count:
            lines.append(f"Unsupported strokes ignored: {parser.ignored_strokes_count}")
        for message in parser.diagnostic_messages:
            lines.append(f"  {message}")
        _collect_measurement_problems(parser, problems)
        _collect_degenerate_problems(parser, problems, lines)
    except Exception as e:
        lines.append(f"Parser failed: {type(e).__name__}: {e}")
        problems.append(
            Problem(
                "error",
                "Measurement parsing failed",
                cause=f"{type(e).__name__}: {e}",
                action="Report this with the full diagnostics text.",
            )
        )

    return lines


def _annotation_lines(problems):
    lines = []
    try:
        from .infrastructure.blender_annotations import annotation_layer_summary

        summary = annotation_layer_summary("RulerData3D")
    except Exception as e:
        return [f"Ruler annotations: unavailable ({type(e).__name__}: {e})"]

    if not summary.get("found"):
        lines.append("Ruler annotations: RulerData3D layer not present")
        return lines

    lines.append(
        f"Ruler annotations: {summary['stroke_count']} strokes across {summary['frame_count']} frame(s) "
        f"{summary['frame_numbers']}"
    )
    if summary["frame_count"] > 1:
        problems.append(
            Problem(
                "warning",
                "Ruler measurements exist on several timeline frames",
                cause="Blender stores annotations per frame and copies them when the current frame "
                      "changes, so the viewport shows one frame while export reads all of them.",
                action="Identical copies are removed automatically. If a copy was moved afterwards it "
                       "survives as a separate measurement: check the frames listed above.",
            )
        )
    return lines


def _collect_degenerate_problems(parser, problems, lines):
    try:
        records = parser.get_processed_face_records()
    except Exception:
        return

    degenerate = [record for record in records if getattr(record, "degeneracy", "")]
    if not degenerate:
        return

    lines.append(f"Planes without a valid orientation: {len(degenerate)}")
    for record in degenerate[:10]:
        name = _record_name(record)
        lines.append(f"  {name}: {record.degeneracy}")

    problems.append(
        Problem(
            "warning",
            f"{len(degenerate)} plane measurements cannot define an orientation",
            cause="The points of these measurements are collinear or coincide, so the dip and "
                  "azimuth they report are arbitrary.",
            action="Find them by name in the list above, then re-measure or delete them. The values "
                   "are still exported, with the reason in the 'degeneracy' CSV column.",
        )
    )


def _record_name(record):
    values = getattr(getattr(record, "properties", None), "values", {}) or {}
    return values.get("name") or getattr(record, "source_id", "") or "<unnamed>"


def _collect_measurement_problems(parser, problems):
    if parser.duplicate_strokes_count:
        problems.append(
            Problem(
                "info",
                f"{parser.duplicate_strokes_count} duplicate strokes were skipped",
                cause="Blender copied ruler strokes into another annotation frame.",
                action="No action needed; the export contains one copy of each measurement.",
            )
        )
    near = getattr(parser, "near_duplicate_pairs", ()) or ()
    if near:
        problems.append(
            Problem(
                "warning",
                f"{len(near)} measurement pairs are nearly identical",
                cause="Two measurements sit within the near-duplicate tolerance of each other. A copied "
                      "ruler stroke that was nudged afterwards looks like this.",
                action="Check the listed measurements and delete the accidental copies.",
            )
        )


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def run_self_tests():
    checks = []
    checks.append(_check_geometry())
    checks.append(_check_deduplication())
    checks.append(_check_export_roundtrip())
    checks.append(_check_matplotlib())
    checks.append(_check_stereonet())
    checks.append(_check_overlay())
    return [check for check in checks if check is not None]


def _check_geometry():
    try:
        from .domain.geometry import process_plane_measurement
        from .domain.measurements import AzimuthCorrection, MeasurementKind, Point3D, RawMeasurement

        # A plane dipping 45 degrees towards the east.
        raw = RawMeasurement(
            kind=MeasurementKind.PLANE,
            points=(Point3D(0.0, 0.0, 0.0), Point3D(0.0, 1.0, 0.0), Point3D(1.0, 0.0, -1.0)),
        )
        record = process_plane_measurement(raw, AzimuthCorrection())
        dip = record.plane_orientation.dip
        azimuth = record.plane_orientation.rotated_azimuth
        ok = abs(dip - 45.0) < 0.5 and abs(azimuth - 90.0) < 0.5
        return CheckResult(
            "Plane orientation math",
            ok,
            f"dip {dip:.2f} (expected 45.00), azimuth {azimuth:.2f} (expected 90.00)",
        )
    except Exception as e:
        return CheckResult("Plane orientation math", False, f"{type(e).__name__}: {e}")


def _check_deduplication():
    try:
        from .application.services import MeasurementApplicationService, SourceReadResult, StrokeInput
        from .domain.measurements import Point3D

        points = (Point3D(0.0, 0.0, 0.0), Point3D(1.0, 0.0, 0.0))

        class _Source:
            def read_strokes(self):
                return SourceReadResult(
                    True,
                    strokes=(
                        StrokeInput(points=points, source_id="a"),
                        StrokeInput(points=points, source_id="b"),
                    ),
                )

        measurement_set = MeasurementApplicationService(_Source()).ingest_measurements()
        ok = len(measurement_set.raw_measurements) == 1 and measurement_set.diagnostics.duplicate_strokes_count == 1
        return CheckResult(
            "Duplicate protection",
            ok,
            f"{len(measurement_set.raw_measurements)} kept, "
            f"{measurement_set.diagnostics.duplicate_strokes_count} duplicate removed",
        )
    except Exception as e:
        return CheckResult("Duplicate protection", False, f"{type(e).__name__}: {e}")


def _check_export_roundtrip():
    try:
        from .domain.geometry import process_linear_measurement
        from .domain.measurements import AzimuthCorrection, MeasurementKind, Point3D, RawMeasurement
        from .infrastructure.exporters import ProcessedEdgeCsvWriter

        record = process_linear_measurement(
            RawMeasurement(
                kind=MeasurementKind.LINEAR,
                points=(Point3D(0.0, 0.0, 0.0), Point3D(3.0, 4.0, 0.0)),
            ),
            AzimuthCorrection(),
        )
        directory = tempfile.mkdtemp(prefix="scientia-selftest-")
        path = Path(directory) / "selftest_edges.csv"
        ProcessedEdgeCsvWriter().write(str(path), [record])
        content = path.read_text(encoding="utf-8").splitlines()
        path.unlink(missing_ok=True)
        Path(directory).rmdir()
        ok = len(content) == 2 and content[0].startswith("x,y,z")
        return CheckResult("CSV export", ok, f"{len(content)} lines written to a temporary file")
    except Exception as e:
        return CheckResult("CSV export", False, f"{type(e).__name__}: {e}")


def _check_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt

        figure = plt.figure(figsize=(1, 1))
        figure.add_subplot(111).plot([0, 1], [0, 1])
        directory = tempfile.mkdtemp(prefix="scientia-selftest-")
        path = Path(directory) / "selftest.png"
        figure.savefig(str(path))
        plt.close(figure)
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        Path(directory).rmdir()
        return CheckResult("matplotlib rendering", size > 0, f"{matplotlib.__version__}, wrote {size} bytes")
    except Exception as e:
        return CheckResult("matplotlib rendering", False, f"{type(e).__name__}: {e}")


def _check_stereonet():
    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        import mplstereonet

        figure, axes = mplstereonet.subplots(figsize=(1, 1))
        axes.pole([0.0], [45.0])
        plt.close(figure)
        return CheckResult("mplstereonet projection", True, "a pole was projected successfully")
    except Exception as e:
        return CheckResult("mplstereonet projection", False, f"{type(e).__name__}: {e}")


def _check_overlay():
    try:
        import bpy

        from . import custom_measure_tool

        active = custom_measure_tool.overlay_is_active()
        registered = hasattr(bpy.types, "OBJECT_PT_measurement_exporter")
        return CheckResult(
            "Viewport overlay and panel",
            active and registered,
            f"overlay {'active' if active else 'INACTIVE'}, panel {'registered' if registered else 'MISSING'}",
        )
    except Exception as e:
        return CheckResult("Viewport overlay and panel", False, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def build_report(context=None, run_tests=True):
    import bpy

    context = context or bpy.context
    report = Report()
    problems = report.problems

    report.add("Blender", _safe_lines(_blender_section))
    report.add("Environment", _safe_lines(_environment_section))
    report.add("Dependencies", _safe_lines(lambda: _dependency_section(problems)))
    report.add("File", _safe_lines(lambda: _file_section(context, problems)))
    report.add("Measurements", _safe_lines(lambda: _measurement_section(context, problems)))

    if run_tests:
        report.checks = run_self_tests()
        for check in report.checks:
            if check.passed or check.skipped:
                continue
            problems.append(
                Problem(
                    "error",
                    f"Self-test failed: {check.name}",
                    cause=check.detail,
                    action="Include this report when asking for support.",
                )
            )

    return report


def _safe_lines(getter):
    try:
        return list(getter())
    except Exception as e:
        logger.debug("Diagnostics section failed: %s", e, exc_info=True)
        return [f"unavailable ({type(e).__name__}: {e})"]


def format_report(report):
    lines = [
        "ScientiaJoints diagnostics",
        time.strftime("%Y-%m-%d %H:%M:%S"),
        "=" * 60,
    ]
    for title, section_lines in report.sections:
        lines.append("")
        lines.append(f"[{title}]")
        lines.extend(f"  {line}" for line in section_lines)

    if report.checks:
        lines.append("")
        lines.append("[Self-test]")
        for check in report.checks:
            mark = "SKIP" if check.skipped else ("PASS" if check.passed else "FAIL")
            lines.append(f"  {mark}  {check.name}: {check.detail}")

    lines.append("")
    lines.append("[Detected problems]")
    if not report.problems:
        lines.append("  None. Every check passed.")
    else:
        for index, problem in enumerate(report.problems, start=1):
            lines.append(f"  {index}. [{problem.severity.upper()}] {problem.title}")
            if problem.cause:
                lines.append(f"     Cause: {problem.cause}")
            if problem.action:
                lines.append(f"     Action: {problem.action}")

    return "\n".join(lines)


def report_text(context=None, run_tests=True):
    return format_report(build_report(context=context, run_tests=run_tests))
