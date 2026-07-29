import tempfile
import unittest
from pathlib import Path
import zipfile

from tools.build_release import (
    REQUIRED_ICONS,
    blender_platforms_for_wheels,
    build_extension,
    build_release,
    discover_version,
    render_manifest,
    validate_extension,
    validate_release,
    wheel_files,
)
from tools.version import check_version, read_bl_info_version, read_version, set_version


ADDON_ROOT = Path(__file__).resolve().parents[1]


def _write_version_sources(addon_root, manifest_version, bl_info_version):
    """A throwaway add-on root carrying just the two files that hold a version."""
    (addon_root / "blender_manifest.toml").write_text(
        f'id = "scientiajoints"\nversion = "{manifest_version}"\n',
        encoding="utf-8",
    )
    (addon_root / "__init__.py").write_text(
        '    "version": ({}),\n'.format(", ".join(bl_info_version.split(".")))
        + 'raise RuntimeError("must not import")\n',
        encoding="utf-8",
    )
    return addon_root


class ReleasePackageTests(unittest.TestCase):
    def test_version_is_read_without_importing_blender_addon(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            addon_root = _write_version_sources(Path(temporary_directory), "9.8.7", "9.8.7")

            self.assertEqual(discover_version(addon_root), "9.8.7")

    def test_a_drifted_version_copy_stops_the_build(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            addon_root = _write_version_sources(Path(temporary_directory), "9.8.7", "1.2.3")

            with self.assertRaisesRegex(ValueError, "tools/version.py 9.8.7"):
                discover_version(addon_root)

    def test_archive_name_does_not_change_internal_python_package(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive_path = Path(temporary_directory) / "ScientiaJoints 3.zip"
            build_release(ADDON_ROOT, archive_path)

            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()

        self.assertIn("ScientiaJoints/__init__.py", names)
        self.assertNotIn("__init__.py", names)
        self.assertTrue(all(name.startswith("ScientiaJoints/") for name in names))
        self.assertFalse(any("/tests/" in name for name in names))
        self.assertFalse(any("/docs/" in name for name in names))
        self.assertFalse(any("__pycache__" in name for name in names))

    def test_both_archives_ship_the_tool_icons(self):
        """Without the .dat files the workspace tools fall back to the built-in
        ruler icon, which is exactly what the custom artwork replaced."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            release_path = Path(temporary_directory) / "release.zip"
            extension_path = Path(temporary_directory) / "extension.zip"
            build_release(ADDON_ROOT, release_path)
            build_extension(ADDON_ROOT, extension_path)

            with zipfile.ZipFile(release_path) as archive:
                legacy_names = archive.namelist()
            with zipfile.ZipFile(extension_path) as archive:
                extension_names = archive.namelist()

        for icon_name in REQUIRED_ICONS:
            self.assertIn(f"ScientiaJoints/icons/{icon_name}", legacy_names)
            self.assertIn(f"icons/{icon_name}", extension_names)

    def test_validation_rejects_a_corrupt_tool_icon(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            release_path = Path(temporary_directory) / "release.zip"
            broken_path = Path(temporary_directory) / "broken.zip"
            build_release(ADDON_ROOT, release_path)

            with zipfile.ZipFile(release_path) as source, zipfile.ZipFile(broken_path, "w") as target:
                for info in source.infolist():
                    data = source.read(info.filename)
                    if info.filename.endswith(f"icons/{REQUIRED_ICONS[0]}"):
                        data = b"not an icon"
                    target.writestr(info, data)

            with self.assertRaisesRegex(ValueError, "not a Blender triangle icon"):
                validate_release(broken_path)

    def test_validation_rejects_incompatible_module_api(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            release_path = Path(temporary_directory) / "release.zip"
            broken_path = Path(temporary_directory) / "broken.zip"
            build_release(ADDON_ROOT, release_path)

            with zipfile.ZipFile(release_path) as source, zipfile.ZipFile(broken_path, "w") as target:
                for info in source.infolist():
                    data = source.read(info.filename)
                    if info.filename == "ScientiaJoints/operators.py":
                        data = data.replace(
                            b"def run_startup_diagnostics(",
                            b"def removed_startup_diagnostics(",
                            1,
                        )
                    target.writestr(info, data)

            with self.assertRaisesRegex(ValueError, "run_startup_diagnostics"):
                validate_release(broken_path)


class ExtensionPackageTests(unittest.TestCase):
    """The extension build is what makes the add-on installable offline.

    Blender unpacks the bundled wheels itself, so no pip run, no package index
    and no proxy is involved.
    """

    def test_the_manifest_and_modules_sit_at_the_archive_root(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive_path = Path(temporary_directory) / "extension.zip"
            build_extension(ADDON_ROOT, archive_path)

            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()

        self.assertIn("blender_manifest.toml", names)
        self.assertIn("__init__.py", names)
        self.assertIn("infrastructure/blender_annotations.py", names)
        self.assertFalse(any(name.startswith("ScientiaJoints/") for name in names))

    def test_every_bundled_wheel_is_declared_in_the_manifest(self):
        """Blender ignores wheels the manifest does not list."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive_path = Path(temporary_directory) / "extension.zip"
            build_extension(ADDON_ROOT, archive_path)

            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                manifest = archive.read("blender_manifest.toml").decode("utf-8")

        for name in names:
            if name.startswith("wheels/"):
                self.assertIn(f'"./{name}"', manifest)

    def test_numpy_is_not_shipped_because_blender_bundles_it(self):
        """A second numpy is the usual cause of the binary incompatibility
        errors that look like random matplotlib crashes."""
        wheels = wheel_files(ADDON_ROOT, include_bundled_packages=False)

        self.assertFalse([path for path in wheels if path.name.lower().startswith("numpy-")])

    def test_the_legacy_archive_keeps_numpy_for_offline_pip(self):
        """`pip --target` resolves without looking at installed packages, so an
        offline install fails when numpy is missing from the wheel directory."""
        wheels = wheel_files(ADDON_ROOT, include_bundled_packages=True)
        if not wheels:
            self.skipTest("no wheels fetched; run tools/fetch_wheels.py")

        self.assertTrue([path for path in wheels if path.name.lower().startswith("numpy-")])

    def test_wheel_platform_tags_map_to_blender_platforms(self):
        platforms = blender_platforms_for_wheels((
            "matplotlib-3.11.1-cp313-cp313-win_amd64.whl",
            "matplotlib-3.11.1-cp313-cp313-manylinux2014_x86_64.whl",
            "matplotlib-3.11.1-cp313-cp313-macosx_11_0_arm64.whl",
            "mplstereonet-0.6.2-py3-none-any.whl",
        ))

        self.assertEqual(platforms, ("linux-x64", "macos-arm64", "windows-x64"))

    def test_an_unknown_wheel_platform_stops_the_build(self):
        with self.assertRaisesRegex(ValueError, "Unknown wheel platform"):
            blender_platforms_for_wheels(("matplotlib-3.11.1-cp313-cp313-solaris_sparc.whl",))

    def test_the_built_manifest_carries_the_release_version(self):
        manifest = render_manifest(
            'schema_version = "1.0.0"\nid = "scientiajoints"\nversion = "0.0.0"\nname = "ScientiaJoints"\n',
            version="9.8.7",
            wheels=(),
        )

        self.assertIn('version = "9.8.7"', manifest)
        self.assertNotIn('version = "0.0.0"', manifest)

    def test_validation_rejects_an_undeclared_wheel(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "extension.zip"
            broken_path = Path(temporary_directory) / "broken.zip"
            build_extension(ADDON_ROOT, source_path)

            with zipfile.ZipFile(source_path) as source, zipfile.ZipFile(broken_path, "w") as target:
                for info in source.infolist():
                    target.writestr(info, source.read(info.filename))
                target.writestr("wheels/sneaky-1.0-py3-none-any.whl", b"x")

            with self.assertRaisesRegex(ValueError, "does not declare"):
                validate_extension(broken_path)

    def test_the_legacy_archive_never_carries_an_extension_manifest(self):
        """Blender would try to install it as an extension and fail."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "release.zip"
            broken_path = Path(temporary_directory) / "broken.zip"
            build_release(ADDON_ROOT, source_path)

            with zipfile.ZipFile(source_path) as source, zipfile.ZipFile(broken_path, "w") as target:
                for info in source.infolist():
                    target.writestr(info, source.read(info.filename))
                target.writestr("ScientiaJoints/blender_manifest.toml", b"schema_version = \"1.0.0\"")

            with self.assertRaisesRegex(ValueError, "extension manifest"):
                validate_release(broken_path)


class VersionTests(unittest.TestCase):
    """`tools/version.py` is the single point the add-on version is set from."""

    def test_the_shipped_sources_agree_on_one_version(self):
        self.assertEqual(check_version(ADDON_ROOT), read_version(ADDON_ROOT))

    def test_setting_the_version_updates_the_manifest_and_bl_info(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            addon_root = _write_version_sources(Path(temporary_directory), "1.0.0", "1.0.0")

            set_version(addon_root, "4.12.7")

            self.assertEqual(read_version(addon_root), "4.12.7")
            self.assertEqual(read_bl_info_version(addon_root), "4.12.7")
            self.assertEqual(check_version(addon_root), "4.12.7")

    def test_a_malformed_version_is_refused_before_anything_is_written(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            addon_root = _write_version_sources(Path(temporary_directory), "1.0.0", "1.0.0")

            with self.assertRaisesRegex(ValueError, "3.4.0"):
                set_version(addon_root, "v3.4")

            self.assertEqual(read_version(addon_root), "1.0.0")


if __name__ == "__main__":
    unittest.main()
