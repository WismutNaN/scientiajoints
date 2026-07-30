"""Build the ScientiaJoints release archives.

Two formats are produced, because they fail in different situations and a user
who cannot install one can fall back to the other:

``legacy``
    ``Edit > Preferences > Add-ons > Install from Disk``. Every file lives
    under a single ``ScientiaJoints/`` directory, which is the Python package
    name Blender imports. Bundled non-numpy wheels, if present, are installed
    by the add-on with ``pip --no-index --no-deps`` so Blender keeps its own
    numpy.

``extension``
    Blender 4.2+ extension. ``blender_manifest.toml`` sits at the archive root
    and lists the bundled wheels, so Blender unpacks matplotlib and
    mplstereonet itself: no pip, no package index, no network, and a short
    install path that stays clear of the Windows path length limit.
"""

import argparse
import ast
import hashlib
import re
from pathlib import Path
import zipfile

try:
    from .version import check_version
except ImportError:  # Run as a script, not imported as ``tools.build_release``.
    from version import check_version


PACKAGE_NAME = "ScientiaJoints"
MANIFEST_NAME = "blender_manifest.toml"
WHEELS_DIRECTORY_NAME = "wheels"

#: Packages every Blender build already ships. Shipping them again risks a
#: second copy with a different ABI.
BLENDER_BUNDLED_PACKAGES = frozenset({"numpy"})
REQUIRED_WHEEL_DISTRIBUTIONS = frozenset({"matplotlib", "mplstereonet"})

REQUIRED_ROOT_FILES = (
    "__init__.py",
    "custom_measure_tool.py",
    "dependencies.py",
    "diagnostics.py",
    "operators.py",
    "panel.py",
    "parser.py",
    "scene_measurements.py",
    "visualization.py",
    "requirements.txt",
)
OPTIONAL_ROOT_FILES = (
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
)
PACKAGE_DIRECTORIES = (
    "application",
    "domain",
    "infrastructure",
)

#: Toolbar artwork loaded by ``custom_measure_tool.tool_icon``. Without it the
#: workspace tools fall back to the built-in ruler icon, so the files have to
#: travel with the add-on. Regenerate with ``tools/build_tool_icons.py``.
ICON_DIRECTORY_NAME = "icons"
REQUIRED_ICONS = (
    "scientiajoints.measure.dat",
    "scientiajoints.polygon_measure.dat",
    "scientiajoints.trace_measure.dat",
)
REQUIRED_MODULE_SYMBOLS = {
    "operators.py": (
        "ExportRawEdgesOperator",
        "ExportRawFacesOperator",
        "ExportProcessedEdgesOperator",
        "ExportProcessedFacesOperator",
        "ShowHistogramImageOperator",
        "ShowStereonetImageOperator",
        "RealTimeHistogramUpdateOperator",
        "RealTimeStereonetUpdateOperator",
        "ScientiaDiagnosticsOperator",
        "ScientiaDiagnosticsRunTestsOperator",
        "ScientiaInstallDependenciesOperator",
        "ToggleLightSettingsOperator",
        "run_startup_diagnostics",
        "start_dependency_install",
    ),
    "custom_measure_tool.py": (
        "ScientiaMeasureDragOperator",
        "ScientiaPolygonMeasureOperator",
        "ScientiaTraceMeasureOperator",
        "register_measure_tool",
        "reset_tool_state",
    ),
    "panel.py": (
        "MeasurementExporterPanel",
        "init_properties",
    ),
    "dependencies.py": (
        "check_required_packages",
        "install_required_packages",
        "BackgroundInstall",
    ),
    "diagnostics.py": (
        "SELF_TEST_COUNT",
        "self_test_cases",
        "add_self_test_results",
        "build_report",
        "format_report",
    ),
}
ARCHIVE_TIMESTAMP = (2020, 1, 1, 0, 0, 0)

#: Wheel platform tag -> Blender platform identifier.
WHEEL_PLATFORM_TO_BLENDER = (
    (re.compile(r"^win_amd64$"), "windows-x64"),
    (re.compile(r"^win_arm64$"), "windows-arm64"),
    (re.compile(r"^(many)?linux.*_(x86_64|amd64)$"), "linux-x64"),
    (re.compile(r"^(many)?linux.*_aarch64$"), "linux-arm64"),
    (re.compile(r"^macosx_.*_(arm64|universal2)$"), "macos-arm64"),
    (re.compile(r"^macosx_.*_x86_64$"), "macos-x64"),
)


def discover_version(addon_root):
    """The version to build, refusing to package a source tree that disagrees
    with itself. See ``tools/version.py`` for where the number is set."""
    return check_version(addon_root)


def release_files(addon_root):
    addon_root = Path(addon_root).resolve()
    missing = [name for name in REQUIRED_ROOT_FILES if not (addon_root / name).is_file()]
    if missing:
        raise FileNotFoundError("Missing required add-on files: " + ", ".join(missing))

    paths = [addon_root / name for name in REQUIRED_ROOT_FILES]
    paths.extend(addon_root / name for name in OPTIONAL_ROOT_FILES if (addon_root / name).is_file())

    for directory_name in PACKAGE_DIRECTORIES:
        directory = addon_root / directory_name
        if not directory.is_dir():
            raise FileNotFoundError(f"Missing required package directory: {directory}")
        paths.extend(path for path in directory.rglob("*.py") if path.is_file())

    icon_directory = addon_root / ICON_DIRECTORY_NAME
    missing_icons = [name for name in REQUIRED_ICONS if not (icon_directory / name).is_file()]
    if missing_icons:
        raise FileNotFoundError(
            "Missing tool icons (run `python tools/build_tool_icons.py`): " + ", ".join(missing_icons)
        )
    paths.extend(path for path in sorted(icon_directory.glob("*.dat")) if path.is_file())

    return tuple(sorted(paths, key=lambda path: path.relative_to(addon_root).as_posix()))


def wheel_files(addon_root, include_bundled_packages=True):
    """Wheels shipped with the add-on.

    ``include_bundled_packages=False`` drops wheels for packages Blender ships
    itself. Both release formats use that: Blender already has numpy, and a
    second copy in either site-packages or the legacy user target can shadow
    Blender's copy and break binary add-ons. The legacy installer passes the
    complete remaining wheel set with ``--no-deps``.
    """
    directory = Path(addon_root).resolve() / WHEELS_DIRECTORY_NAME
    if not directory.is_dir():
        return ()
    wheels = sorted(path for path in directory.glob("*.whl") if path.is_file())
    if not include_bundled_packages:
        wheels = [path for path in wheels if _wheel_distribution(path) not in BLENDER_BUNDLED_PACKAGES]
    return tuple(wheels)


def _wheel_distribution(path):
    return Path(path).name.split("-", 1)[0].replace("_", "-").lower()


def blender_platforms_for_wheels(wheels):
    """Blender platform identifiers covered by the given wheel files."""
    platforms = set()
    for wheel in wheels:
        tag = Path(wheel).stem.rsplit("-", 1)[-1]
        if tag == "any":
            continue
        for pattern, blender_platform in WHEEL_PLATFORM_TO_BLENDER:
            if pattern.match(tag):
                platforms.add(blender_platform)
                break
        else:
            raise ValueError(f"Unknown wheel platform tag '{tag}' in {Path(wheel).name}")
    return tuple(sorted(platforms))


# ---------------------------------------------------------------------------
# Legacy add-on archive
# ---------------------------------------------------------------------------


def build_release(addon_root, output_path):
    """Build the legacy ``Install from Disk`` archive."""
    addon_root = Path(addon_root).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    entries = []
    for source_path in release_files(addon_root):
        entries.append((f"{PACKAGE_NAME}/{source_path.relative_to(addon_root).as_posix()}", source_path))
    for wheel in wheel_files(addon_root, include_bundled_packages=False):
        entries.append((f"{PACKAGE_NAME}/{WHEELS_DIRECTORY_NAME}/{wheel.name}", wheel))

    _write_archive(output_path, entries)
    validate_release(output_path)
    return output_path


def validate_release(archive_path):
    archive_path = Path(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        entries = {name: archive.read(name) for name in names}

    required_init = f"{PACKAGE_NAME}/__init__.py"
    if required_init not in names:
        raise ValueError(f"Release archive must contain {required_init}")
    if "__init__.py" in names:
        raise ValueError("Release archive must not contain a top-level __init__.py")
    if any(not name.startswith(f"{PACKAGE_NAME}/") for name in names):
        raise ValueError(f"Every release entry must be inside {PACKAGE_NAME}/")
    if MANIFEST_NAME in names or f"{PACKAGE_NAME}/{MANIFEST_NAME}" in names:
        raise ValueError(
            "The legacy archive must not carry a Blender extension manifest; "
            "Blender would try to install it as an extension."
        )
    _validate_common(names, entries)

    required_entries = {f"{PACKAGE_NAME}/{name}" for name in REQUIRED_ROOT_FILES}
    required_entries.update(
        f"{PACKAGE_NAME}/{directory}/__init__.py" for directory in PACKAGE_DIRECTORIES
    )
    missing_entries = sorted(required_entries.difference(names))
    if missing_entries:
        raise ValueError("Release archive is missing: " + ", ".join(missing_entries))


# ---------------------------------------------------------------------------
# Extension archive
# ---------------------------------------------------------------------------


def build_extension(addon_root, output_path, include_bundled_packages=False):
    """Build the Blender 4.2+ extension archive with bundled wheels."""
    addon_root = Path(addon_root).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    manifest_path = addon_root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing {manifest_path}")

    wheels = wheel_files(addon_root, include_bundled_packages=include_bundled_packages)
    manifest = render_manifest(
        manifest_path.read_text(encoding="utf-8"),
        version=discover_version(addon_root),
        wheels=wheels,
    )

    entries = [(MANIFEST_NAME, manifest.encode("utf-8"))]
    for source_path in release_files(addon_root):
        entries.append((source_path.relative_to(addon_root).as_posix(), source_path))
    for wheel in wheels:
        entries.append((f"{WHEELS_DIRECTORY_NAME}/{wheel.name}", wheel))

    _write_archive(output_path, entries)
    validate_extension(output_path)
    return output_path


def render_manifest(template, version, wheels):
    """Fill the manifest version, wheel list and platform list."""
    lines = [
        line
        for line in template.splitlines()
        if not line.startswith(("version =", "wheels =", "platforms ="))
    ]

    generated = [f'version = "{version}"']
    if wheels:
        wheel_entries = ", ".join(f'"./{WHEELS_DIRECTORY_NAME}/{Path(wheel).name}"' for wheel in wheels)
        generated.append(f"wheels = [{wheel_entries}]")
        platforms = blender_platforms_for_wheels(wheels)
        if platforms:
            generated.append("platforms = [" + ", ".join(f'"{name}"' for name in platforms) + "]")

    # Insert right after the id line so the generated fields stay together.
    for index, line in enumerate(lines):
        if line.startswith("id ="):
            return "\n".join(lines[: index + 1] + generated + lines[index + 1:]) + "\n"
    return "\n".join(lines + generated) + "\n"


def validate_extension(archive_path):
    archive_path = Path(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        entries = {name: archive.read(name) for name in names}

    if MANIFEST_NAME not in names:
        raise ValueError(f"Extension archive must contain {MANIFEST_NAME} at its root")
    if "__init__.py" not in names:
        raise ValueError("Extension archive must contain __init__.py at its root")
    if any(name.startswith(f"{PACKAGE_NAME}/") for name in names):
        raise ValueError(
            "Extension archive entries must be at the archive root, "
            f"not inside {PACKAGE_NAME}/"
        )
    _validate_common(names, entries)

    missing_entries = sorted(set(REQUIRED_ROOT_FILES).difference(names))
    if missing_entries:
        raise ValueError("Extension archive is missing: " + ", ".join(missing_entries))

    manifest = entries[MANIFEST_NAME].decode("utf-8")
    for field in ("schema_version", "id", "version", "name", "tagline", "maintainer", "type", "license"):
        if not re.search(rf"^{field} = ", manifest, flags=re.MULTILINE):
            raise ValueError(f"Extension manifest is missing the '{field}' field")

    declared = re.findall(r'"\./(wheels/[^"]+)"', manifest)
    missing_wheels = sorted(set(declared).difference(names))
    if missing_wheels:
        raise ValueError("Manifest lists wheels that are not in the archive: " + ", ".join(missing_wheels))

    packaged_wheels = {name for name in names if name.startswith(f"{WHEELS_DIRECTORY_NAME}/")}
    undeclared = sorted(packaged_wheels.difference(declared))
    if undeclared:
        raise ValueError(
            "The archive contains wheels the manifest does not declare, so Blender would ignore them: "
            + ", ".join(undeclared)
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _write_archive(output_path, entries):
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for archive_path, source in entries:
            info = zipfile.ZipInfo(archive_path, date_time=ARCHIVE_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            data = source if isinstance(source, bytes) else Path(source).read_bytes()
            archive.writestr(info, data)


def _validate_common(names, entries):
    if any("__pycache__" in name or name.endswith((".pyc", ".pyo")) for name in names):
        raise ValueError("Release archive contains Python cache files")

    packaged_wheels = [Path(name).name for name in names if "/wheels/" in f"/{name}"]
    distributions = {_wheel_distribution(name) for name in packaged_wheels}
    missing_distributions = sorted(REQUIRED_WHEEL_DISTRIBUTIONS.difference(distributions))
    if missing_distributions:
        raise ValueError(
            "Release archive is not independently installable; missing wheels for: "
            + ", ".join(missing_distributions)
        )
    duplicated_bundled = sorted(BLENDER_BUNDLED_PACKAGES.intersection(distributions))
    if duplicated_bundled:
        raise ValueError(
            "Release archive must use Blender's bundled packages instead of shipping: "
            + ", ".join(duplicated_bundled)
        )

    for icon_name in REQUIRED_ICONS:
        archive_name = next(
            (name for name in names if name.endswith(f"{ICON_DIRECTORY_NAME}/{icon_name}")),
            None,
        )
        if archive_name is None:
            raise ValueError(f"Release archive is missing {ICON_DIRECTORY_NAME}/{icon_name}")
        if not entries[archive_name].startswith(b"VCO\x00"):
            raise ValueError(f"{archive_name} is not a Blender triangle icon")

    for name, source in entries.items():
        if name.endswith(".py"):
            compile(source, name, "exec")

    for module_name, expected_symbols in REQUIRED_MODULE_SYMBOLS.items():
        archive_name = next(
            (name for name in names if name == module_name or name.endswith(f"/{module_name}")),
            None,
        )
        if archive_name is None:
            raise ValueError(f"Release archive is missing {module_name}")
        module = ast.parse(entries[archive_name], filename=archive_name)
        symbols = {
            node.name
            for node in module.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in module.body:
            if isinstance(node, ast.Assign):
                symbols.update(
                    target.id for target in node.targets
                    if isinstance(target, ast.Name)
                )
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                symbols.add(node.target.id)
        missing_symbols = sorted(set(expected_symbols).difference(symbols))
        if missing_symbols:
            raise ValueError(
                f"{archive_name} is incompatible; missing symbols: " + ", ".join(missing_symbols)
            )


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    addon_root = Path(__file__).resolve().parents[1]
    version = discover_version(addon_root)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--format",
        choices=("legacy", "extension", "both"),
        default="both",
        help="Which archives to build (default: both)",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=addon_root / "dist",
        help="Destination directory",
    )
    parser.add_argument("--output", type=Path, help="Explicit output path; only valid for a single format")
    parser.add_argument(
        "--extension-includes-numpy",
        action="store_true",
        help="Also ship numpy in the extension (only for Blender builds without it)",
    )
    args = parser.parse_args()

    if args.output and args.format == "both":
        parser.error("--output cannot be combined with --format both")

    wheels = wheel_files(addon_root)
    if wheels:
        total = sum(path.stat().st_size for path in wheels) / 1024 / 1024
        print(f"Bundling {len(wheels)} wheel(s), {total:.1f} MB, platforms: "
              f"{', '.join(blender_platforms_for_wheels(wheels)) or 'any'}")
    else:
        print("No wheels in wheels/; run tools/fetch_wheels.py to make offline installation possible.")

    built = []
    if args.format in ("legacy", "both"):
        output = args.output or args.output_directory / f"{PACKAGE_NAME}-{version}.zip"
        built.append(("legacy add-on", build_release(addon_root, output)))
    if args.format in ("extension", "both"):
        output = args.output or args.output_directory / f"{PACKAGE_NAME}-{version}-extension.zip"
        built.append((
            "extension",
            build_extension(addon_root, output, include_bundled_packages=args.extension_includes_numpy),
        ))

    for label, path in built:
        size = Path(path).stat().st_size / 1024 / 1024
        print(f"\nBuilt {label}: {path}")
        print(f"  Size:   {size:.1f} MB")
        print(f"  SHA256: {file_sha256(path)}")


if __name__ == "__main__":
    main()
