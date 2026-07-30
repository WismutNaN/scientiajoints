import os
import platform
import sys
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path

from tests.addon_test_utils import load_addon_module


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.dependencies = load_addon_module("dependencies")

    def test_check_required_packages_reports_installed_and_missing(self):
        statuses = self.dependencies.check_required_packages((
            "sys",
            "scientiajoints_missing_test_package_zz",
        ))
        by_name = {status.name: status for status in statuses}

        self.assertTrue(by_name["sys"].installed)
        self.assertFalse(by_name["scientiajoints_missing_test_package_zz"].installed)

    def test_dependency_summary_reports_missing_package(self):
        ok, message = self.dependencies.dependency_summary(("scientiajoints_missing_test_package_zz",))

        self.assertFalse(ok)
        self.assertIn("Missing:", message)

    def test_install_required_packages_skips_pip_when_already_available(self):
        result = self.dependencies.install_required_packages(("sys",))

        self.assertTrue(result.ok)
        self.assertEqual(result.missing_after_install, ())
        self.assertIn("Dependencies already installed", result.messages[0])

    def test_panel_safe_detection_never_imports_the_package(self):
        with unittest.mock.patch.object(
            self.dependencies.importlib,
            "import_module",
            side_effect=AssertionError("must not import during UI detection"),
        ):
            statuses = self.dependencies.lightweight_package_statuses(("sys",))

        self.assertTrue(statuses[0].installed)
        self.assertFalse(statuses[0].verified)

    def test_extension_mode_only_verifies_and_never_runs_pip(self):
        runtime = self.dependencies.current_python_runtime("python.exe")
        statuses = (
            self.dependencies.DependencyStatus("matplotlib", True),
            self.dependencies.DependencyStatus("mplstereonet", True),
            self.dependencies.DependencyStatus("numpy", True),
        )
        with unittest.mock.patch.object(
            self.dependencies, "probe_python_runtime", return_value=(runtime, "")
        ), unittest.mock.patch.object(
            self.dependencies, "probe_package_imports", return_value=statuses
        ), unittest.mock.patch.object(
            self.dependencies,
            "_pip_available",
            side_effect=AssertionError("Extension mode must not run pip"),
        ):
            result = self.dependencies.install_required_packages(
                python_executable="python.exe",
                expected_runtime=runtime,
                check_only=True,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.source, "existing")


class PythonExecutableTests(unittest.TestCase):
    def setUp(self):
        self.dependencies = load_addon_module("dependencies")

    def test_explicit_python_executable_is_used(self):
        self.assertEqual(
            self.dependencies.resolve_python_executable("C:/blender/python/bin/python.exe"),
            "C:/blender/python/bin/python.exe",
        )

    def test_blender_binary_is_never_used_as_the_interpreter(self):
        """Running `blender.exe -m pip` starts a second Blender instead of pip."""
        blender_binary = str(Path(sys.exec_prefix) / "blender.exe")
        fake_bpy = types.ModuleType("bpy")
        fake_bpy.app = types.SimpleNamespace(binary_path=blender_binary)
        original = sys.modules.get("bpy")
        sys.modules["bpy"] = fake_bpy
        try:
            resolved = self.dependencies.resolve_python_executable(blender_binary)
        finally:
            if original is None:
                sys.modules.pop("bpy", None)
            else:
                sys.modules["bpy"] = original

        self.assertNotEqual(
            os.path.normcase(os.path.abspath(resolved)),
            os.path.normcase(os.path.abspath(blender_binary)),
        )

    def test_a_different_python_minor_version_is_rejected(self):
        expected = self.dependencies.PythonRuntime(
            "C:/Blender/python.exe",
            "cpython",
            (3, 13, 2),
            "cpython-313",
            64,
            "Windows",
            "AMD64",
        )
        actual = self.dependencies.PythonRuntime(
            "C:/Other/python.exe",
            "cpython",
            (3, 12, 9),
            "cpython-312",
            64,
            "Windows",
            "AMD64",
        )

        message = self.dependencies.runtime_mismatch(expected, actual)

        self.assertIn("3.12", message)
        self.assertIn("3.13", message)

    def test_runtime_probe_timeout_names_the_failing_stage(self):
        with unittest.mock.patch.object(
            self.dependencies.subprocess,
            "run",
            side_effect=self.dependencies.subprocess.TimeoutExpired(
                ("python.exe", "-c", "probe"),
                3,
            ),
        ):
            runtime, error = self.dependencies.probe_python_runtime(
                "python.exe",
                timeout=3,
            )

        self.assertIsNone(runtime)
        self.assertIn("runtime detection timed out", error)
        self.assertIn("python.exe", error)


class PathBudgetTests(unittest.TestCase):
    def setUp(self):
        self.dependencies = load_addon_module("dependencies")

    @unittest.skipUnless(platform.system() == "Windows", "the path limit only applies to Windows")
    def test_a_deep_directory_has_no_budget_left(self):
        """matplotlib fails to open its data files past 260 characters."""
        deep = "C:/" + "/".join("directory" * 3 for _ in range(12))

        self.assertLess(self.dependencies.path_budget(deep), 0)

    @unittest.skipUnless(platform.system() == "Windows", "the path limit only applies to Windows")
    def test_a_short_directory_has_room_for_matplotlib(self):
        budget = self.dependencies.path_budget("C:/blender/modules")

        self.assertGreater(budget, self.dependencies.LONGEST_RELATIVE_PACKAGE_PATH)

    def test_install_target_is_rejected_when_the_path_is_too_long(self):
        target = self.dependencies.InstallTarget(
            path="C:/some/where",
            kind="target",
            on_sys_path=True,
            writable=True,
            path_budget_ok=False,
        )

        self.assertFalse(target.usable)


class OfflineWheelTests(unittest.TestCase):
    def setUp(self):
        self.dependencies = load_addon_module("dependencies")

    def test_wheels_shipped_with_the_addon_are_discovered(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "matplotlib-3.11.1-cp313-cp313-win_amd64.whl"
            wheel.write_bytes(b"not a real wheel")

            wheels = self.dependencies.available_wheels(extra=(directory,))

        self.assertIn(str(wheel), wheels)

    def test_only_wheels_matching_the_active_python_tags_are_selected(self):
        from pip._vendor.packaging.tags import Tag

        wheels = (
            "C:/addon/wheels/contourpy-1.3.3-cp313-cp313-win_amd64.whl",
            "C:/addon/wheels/contourpy-1.3.3-cp312-cp312-win_amd64.whl",
            "C:/addon/wheels/mplstereonet-0.6.3-py3-none-any.whl",
        )
        selection = self.dependencies.select_compatible_wheels(
            wheels,
            supported_tags=(
                Tag("cp313", "cp313", "win_amd64"),
                Tag("py3", "none", "any"),
            ),
        )

        self.assertEqual(len(selection.compatible), 2)
        self.assertTrue(any("cp313" in path for path in selection.compatible))
        self.assertTrue(any("py3-none-any" in path for path in selection.compatible))
        self.assertEqual(selection.incompatible, (wheels[1],))

    def test_offline_install_command_never_reaches_a_package_index(self):
        target = self.dependencies.InstallTarget(
            path="C:/blender/modules",
            kind="target",
            on_sys_path=True,
            writable=True,
            path_budget_ok=True,
        )
        command = self.dependencies._install_command(
            "python.exe",
            ("matplotlib", "mplstereonet", "contourpy"),
            target,
            ("C:/addon/wheels",),
            "",
            (),
            no_dependencies=True,
        )

        self.assertIn("--no-index", command)
        self.assertIn("--find-links", command)
        self.assertIn("--no-input", command)
        self.assertIn("--only-binary", command)
        self.assertIn("--no-deps", command)
        self.assertIn("--target", command)
        self.assertNotIn("numpy", command)

    def test_the_bundled_wheel_set_never_installs_a_second_numpy(self):
        packages = self.dependencies._bundled_wheel_packages((
            "C:/addon/wheels/matplotlib-3.11.1-cp313-cp313-win_amd64.whl",
            "C:/addon/wheels/contourpy-1.3.3-cp313-cp313-win_amd64.whl",
            "C:/addon/wheels/numpy-2.5.1-cp313-cp313-win_amd64.whl",
        ))

        self.assertEqual(packages, ("contourpy", "matplotlib"))

    def test_offline_legacy_install_reaches_pip_with_the_complete_safe_set(self):
        target = self.dependencies.InstallTarget(
            path="C:/Blender/scripts/modules",
            kind="target",
            on_sys_path=False,
            writable=True,
            path_budget_ok=True,
        )
        wheels = (
            "C:/addon/wheels/matplotlib-3.11.1-cp313-cp313-win_amd64.whl",
            "C:/addon/wheels/contourpy-1.3.3-cp313-cp313-win_amd64.whl",
            "C:/addon/wheels/numpy-2.5.1-cp313-cp313-win_amd64.whl",
        )
        commands = []
        runtime = self.dependencies.current_python_runtime("python.exe")
        probe_results = iter((
            (
                self.dependencies.DependencyStatus("matplotlib", False),
                self.dependencies.DependencyStatus("numpy", True),
            ),
            (
                self.dependencies.DependencyStatus("matplotlib", True),
                self.dependencies.DependencyStatus("numpy", True),
            ),
        ))

        def run_install(command, timeout):
            commands.append(command)
            return self.dependencies.InstallAttempt(
                source="",
                command=command,
                returncode=0,
            )

        with unittest.mock.patch.object(
            self.dependencies, "probe_python_runtime", lambda *a, **k: (runtime, "")
        ), unittest.mock.patch.object(
            self.dependencies, "probe_package_imports", lambda *a, **k: next(probe_results)
        ), unittest.mock.patch.object(
            self.dependencies, "_pip_available", lambda *args, **kwargs: (True, "pip test")
        ), unittest.mock.patch.object(
            self.dependencies, "available_wheels", lambda extra=(): wheels
        ), unittest.mock.patch.object(
            self.dependencies, "wheel_directories", lambda extra=(): ("C:/addon/wheels",)
        ), unittest.mock.patch.object(
            self.dependencies, "_run_install", run_install
        ), unittest.mock.patch.object(
            self.dependencies, "bundled_package_versions", lambda packages=(): {}
        ), unittest.mock.patch.object(
            self.dependencies, "_ensure_on_sys_path", lambda target: None
        ):
            result = self.dependencies.install_required_packages(
                packages=("matplotlib", "numpy"),
                python_executable="python.exe",
                allow_online=False,
                install_target=target,
            )

        self.assertTrue(result.ok)
        self.assertEqual(len(commands), 1)
        self.assertIn("--no-index", commands[0])
        self.assertIn("--no-deps", commands[0])
        self.assertTrue(any("matplotlib-" in part for part in commands[0]))
        self.assertTrue(any("contourpy-" in part for part in commands[0]))
        self.assertFalse(any("numpy-" in part for part in commands[0]))

    def test_user_site_is_never_used(self):
        """Blender disables the user site, so --user installs land off sys.path."""
        target = self.dependencies.InstallTarget(
            path="C:/blender/modules",
            kind="target",
            on_sys_path=True,
            writable=True,
            path_budget_ok=True,
        )
        command = self.dependencies._install_command("python.exe", ("matplotlib",), target, (), "", ())

        self.assertNotIn("--user", command)


class MinimumVersionTests(unittest.TestCase):
    """mplstereonet before 0.6.3 imports fine but cannot draw density contours:
    it uses ``np.float``, removed in numpy 1.24."""

    def setUp(self):
        self.dependencies = load_addon_module("dependencies")

    def _statuses(self, version):
        return (
            self.dependencies.DependencyStatus(
                name="mplstereonet", installed=True, version=version
            ),
        )

    def test_an_old_version_is_reported(self):
        with unittest.mock.patch.object(
            self.dependencies, "check_required_packages", lambda *a, **k: self._statuses("0.6.2")
        ):
            self.assertEqual(
                self.dependencies.outdated_packages(), (("mplstereonet", "0.6.2", "0.6.3"),)
            )

    def test_the_required_version_and_newer_are_accepted(self):
        for version in ("0.6.3", "0.6.10", "0.7", "1.0.0"):
            with self.subTest(version=version):
                with unittest.mock.patch.object(
                    self.dependencies, "check_required_packages", lambda *a, **k: self._statuses(version)
                ):
                    self.assertEqual(self.dependencies.outdated_packages(), ())

    def test_an_unreadable_version_is_not_called_old(self):
        """An unknown version is no evidence of an old one, and a false alarm
        sends users reinstalling working dependencies."""
        for version in ("", "unknown", "dev"):
            with self.subTest(version=version):
                with unittest.mock.patch.object(
                    self.dependencies, "check_required_packages", lambda *a, **k: self._statuses(version)
                ):
                    self.assertEqual(self.dependencies.outdated_packages(), ())

    def test_the_version_comes_from_the_metadata_not_the_module(self):
        """mplstereonet 0.6.3 still calls itself '0.6-dev' in code, so trusting
        __version__ reports a current install as outdated."""
        module = types.SimpleNamespace(__version__="0.6-dev", __file__="mplstereonet/__init__.py")
        with unittest.mock.patch.dict(sys.modules, {"mplstereonet": module}):
            with unittest.mock.patch("importlib.metadata.version", lambda name: "0.6.3"):
                version, location = self.dependencies._package_details("mplstereonet")

        self.assertEqual(version, "0.6.3")
        self.assertEqual(location, "mplstereonet/__init__.py")

    def test_the_module_version_is_the_fallback_when_there_is_no_metadata(self):
        module = types.SimpleNamespace(__version__="1.2.3", __file__="somewhere.py")

        def no_metadata(name):
            raise LookupError(name)

        with unittest.mock.patch.dict(sys.modules, {"mplstereonet": module}):
            with unittest.mock.patch("importlib.metadata.version", no_metadata):
                version, _location = self.dependencies._package_details("mplstereonet")

        self.assertEqual(version, "1.2.3")

    def test_the_install_command_asks_pip_for_the_minimum_version(self):
        """Without this a fresh online install can still pick up 0.6.2."""
        command = self.dependencies._install_command(
            "python.exe", ("mplstereonet", "matplotlib"), None, (), "", ()
        )

        self.assertIn("mplstereonet>=0.6.3", command)
        self.assertIn("matplotlib", command)


class FailureExplanationTests(unittest.TestCase):
    def setUp(self):
        self.dependencies = load_addon_module("dependencies")

    def _attempt(self, error):
        return self.dependencies.InstallAttempt(
            source="PyPI",
            command=("python", "-m", "pip"),
            returncode=1,
            error=error,
        )

    def test_certificate_failure_is_explained(self):
        message = self.dependencies._summarize_pip_failure(
            self._attempt("SSLError: certificate verify failed")
        )

        self.assertIn("certificate", message.lower())

    def test_timeout_is_explained(self):
        message = self.dependencies._summarize_pip_failure(
            self._attempt("pip did not finish within 600 s and was stopped.")
        )

        self.assertIn("proxy", message.lower())

    def test_permission_failure_is_explained(self):
        message = self.dependencies._summarize_pip_failure(
            self._attempt("ERROR: Could not install: Permission denied")
        )

        self.assertIn("writable", message.lower())


class AutomaticInstallPolicyTests(unittest.TestCase):
    def setUp(self):
        self.dependencies = load_addon_module("dependencies")

    def test_nothing_is_attempted_when_the_packages_are_present(self):
        self.assertFalse(self.dependencies.should_attempt_automatic_install(("sys",)))

    def test_a_recent_failed_attempt_is_not_repeated(self):
        """Retrying pip at every start is what made Blender look frozen."""
        state = {"last_attempt": 1000.0, "ok": False, "fingerprint": "same-build"}
        self.dependencies.read_install_state = lambda: state
        self.dependencies.automatic_install_fingerprint = lambda packages: "same-build"

        self.assertFalse(
            self.dependencies.should_attempt_automatic_install(
                ("scientiajoints_missing_test_package_zz",),
                now=1000.0 + 60.0,
            )
        )
        self.assertTrue(
            self.dependencies.should_attempt_automatic_install(
                ("scientiajoints_missing_test_package_zz",),
                now=1000.0 + self.dependencies.INSTALL_RETRY_INTERVAL_SECONDS + 1.0,
            )
        )

    def test_a_new_install_policy_retries_immediately(self):
        self.dependencies.read_install_state = lambda: {
            "last_attempt": 1000.0,
            "ok": False,
            "fingerprint": "old-build",
        }
        self.dependencies.automatic_install_fingerprint = lambda packages: "new-build"

        self.assertTrue(
            self.dependencies.should_attempt_automatic_install(
                ("scientiajoints_missing_test_package_zz",),
                now=1001.0,
            )
        )


class UserModulesTargetTests(unittest.TestCase):
    def setUp(self):
        self.dependencies = load_addon_module("dependencies")

    def test_blenders_canonical_user_modules_directory_is_used(self):
        calls = []

        def user_resource(resource_type, path="", create=False):
            calls.append((resource_type, path, create))
            return "C:/Blender/scripts/modules" if path else "C:/Blender/scripts"

        fake_bpy = types.SimpleNamespace(
            utils=types.SimpleNamespace(user_resource=user_resource),
        )
        with unittest.mock.patch.dict(sys.modules, {"bpy": fake_bpy}):
            directory = self.dependencies._user_scripts_modules_directory()

        self.assertEqual(Path(directory), Path("C:/Blender/scripts/modules"))
        self.assertIn(("SCRIPTS", "modules", True), calls)
        self.assertNotIn("addons", Path(directory).parts)

    def test_a_clean_user_target_can_be_chosen_before_it_was_on_sys_path(self):
        target = self.dependencies.InstallTarget(
            path="C:/Blender/scripts/modules",
            kind="target",
            on_sys_path=False,
            writable=True,
            path_budget_ok=True,
        )

        self.assertTrue(target.usable)

    def test_extension_preparation_does_not_add_a_legacy_install_target(self):
        with unittest.mock.patch.object(
            self.dependencies,
            "__package__",
            "bl_ext.user_default.scientiajoints",
        ):
            prepared = self.dependencies.prepare_background_install()

        self.assertTrue(prepared["check_only"])
        self.assertNotIn("install_target", prepared)


class BackgroundInstallTests(unittest.TestCase):
    def setUp(self):
        self.dependencies = load_addon_module("dependencies")

    def test_installation_runs_off_the_main_thread(self):
        job = self.dependencies.BackgroundInstall(("sys",))
        self.assertTrue(job.start())

        for _ in range(200):
            if not job.running:
                break
            import time

            time.sleep(0.01)

        self.assertFalse(job.running)
        self.assertIsNotNone(job.result())
        self.assertTrue(job.result().ok)


if __name__ == "__main__":
    unittest.main()
