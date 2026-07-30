import sys
import types
import unittest
import unittest.mock

from tests.addon_test_utils import install_bpy_stub, load_addon_module


class DiagnosticsResponsivenessTests(unittest.TestCase):
    def setUp(self):
        install_bpy_stub()
        self.operators = load_addon_module("operators")

    def _context(self):
        window_manager = types.SimpleNamespace(
            invoke_popup=lambda operator, width: {"RUNNING_MODAL"},
        )
        return types.SimpleNamespace(window_manager=window_manager)

    def _fake_diagnostics(self, calls):
        module = types.ModuleType("ScientiaJoints.diagnostics")

        def build_report(context, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(problems=[], checks=[])

        module.build_report = build_report
        module.format_report = lambda report: "quick report"
        return module

    def test_opening_the_info_popup_never_runs_the_slow_self_tests(self):
        calls = []
        fake = self._fake_diagnostics(calls)
        self.operators.dependencies_are_installing = lambda: False

        with unittest.mock.patch.dict(
            sys.modules,
            {"ScientiaJoints.diagnostics": fake},
        ), unittest.mock.patch.object(
            self.operators,
            "_fresh_diagnostics_module",
            return_value=fake,
        ):
            result = self.operators.ScientiaDiagnosticsOperator().invoke(
                self._context(),
                types.SimpleNamespace(),
            )

        self.assertEqual(result, {"RUNNING_MODAL"})
        self.assertEqual(calls, [{"run_tests": False, "dependency_installing": False}])

    def test_dependency_probes_are_paused_while_the_legacy_installer_runs(self):
        calls = []
        fake = self._fake_diagnostics(calls)
        self.operators.dependencies_are_installing = lambda: True
        operator = self.operators.ScientiaDiagnosticsOperator()
        operator.run_self_tests = True

        with unittest.mock.patch.dict(
            sys.modules,
            {"ScientiaJoints.diagnostics": fake},
        ), unittest.mock.patch.object(
            self.operators,
            "_fresh_diagnostics_module",
            return_value=fake,
        ):
            self.assertTrue(operator._collect_report(self._context(), run_tests=True))

        self.assertEqual(calls, [{"run_tests": False, "dependency_installing": True}])

    def test_popup_operator_execute_never_starts_hidden_tests(self):
        operator = self.operators.ScientiaDiagnosticsOperator()
        operator._collect_report = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Close must not collect or run tests")
        )

        self.assertEqual(operator.execute(self._context()), {"FINISHED"})

    def test_mixed_version_diagnostics_reports_reinstall_instead_of_crashing(self):
        stale = types.SimpleNamespace()
        self.operators.dependencies_are_installing = lambda: False
        with unittest.mock.patch.object(
            self.operators,
            "_fresh_diagnostics_module",
            return_value=stale,
        ):
            result = self.operators.ScientiaDiagnosticsRunTestsOperator().execute(
                self._context()
            )

        self.assertEqual(result, {"CANCELLED"})
        self.assertEqual(self.operators._diagnostics_test_state["status"], "failed")
        self.assertIn(
            "different versions",
            self.operators._diagnostics_test_state["message"],
        )


if __name__ == "__main__":
    unittest.main()
