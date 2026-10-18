import importlib.util
import json
import os
from pathlib import Path
import signal
import tempfile
import time
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("qualify.py")
SPEC = importlib.util.spec_from_file_location("downstream_qualify", SCRIPT)
assert SPEC and SPEC.loader
QUALIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALIFY)


class QualificationTests(unittest.TestCase):
    def test_written_results_round_trip_through_shared_schema(self) -> None:
        document = QUALIFY.make_results_document(
            "a" * 40,
            ["astrology"],
            [{"consumer": "astrology", "name": "build", "status": "passed"}],
            {"machine": "arm64", "platform": "test", "swift": "test"},
            recorded_at="2026-10-18T00:00:00Z",
        )
        QUALIFY.validate_document(document)
        self.assertEqual(document["candidate"]["revision"], "a" * 40)
        self.assertEqual(document["releaseAcceptance"], "unmet")
        self.assertEqual(document["resolvedGraphs"]["astrology"], QUALIFY.expected_pins("astrology", "a" * 40))

    def test_minimal_result_document_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            QUALIFY.validate_document({"schemaVersion": 1, "releaseAcceptance": "unmet"})

    def test_result_document_rejects_unpinned_dependency_graph(self) -> None:
        document = QUALIFY.make_results_document(
            "a" * 40,
            ["electional"],
            [{"consumer": "electional", "name": "build", "status": "passed"}],
            {"machine": "arm64"},
        )
        del document["resolvedGraphs"]["electional"]["swift-crypto"]
        with self.assertRaisesRegex(ValueError, "resolvedGraphs"):
            QUALIFY.validate_document(document)

    def test_successful_swift_test_requires_nonzero_reported_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "swift"
            executable.write_text("#!/bin/sh\nprintf 'Test run with 0 tests passed after 0.001 seconds.\\n'\n")
            executable.chmod(0o755)
            result = QUALIFY.run_command("zero", ["swift", "test", "--filter", "Missing"], root, root, 2, {"PATH": f"{root}:{os.environ['PATH']}"})
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["reportedSummary"]["tests"], 0)

    def test_successful_non_test_command_needs_no_test_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = QUALIFY.run_command("build", ["python3", "-c", "pass"], root, root, 2)
            self.assertEqual(result["status"], "passed")
            self.assertIsNone(result["reportedSummary"])

    def test_failed_summary_cannot_be_recorded_as_passed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "swift"
            executable.write_text("#!/bin/sh\nprintf 'Test run with 1 test in 1 suite failed after 0.001 seconds.\\n'\n")
            executable.chmod(0o755)
            result = QUALIFY.run_command("failed", ["swift", "test"], root, root, 2, {"PATH": f"{root}:{os.environ['PATH']}"})
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["evidenceError"], "test summary reported failure")

    def test_timeout_terminates_detached_descendant_before_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child_pid_path = root / "child.pid"
            child = "import os,time,pathlib; pathlib.Path(os.environ['CHILD_PID']).write_text(str(os.getpid())); time.sleep(60)"
            parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]],start_new_session=True); time.sleep(60)"
            result = QUALIFY.run_command("timeout", ["python3", "-c", parent, child], root, root, 0.5, {"CHILD_PID": str(child_pid_path)})
            self.assertEqual(result["status"], "incomplete")
            self.assertGreaterEqual(result["capturedDescendantCount"], 1)
            child_pid = int(child_pid_path.read_text())
            for _ in range(20):
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail(f"detached child {child_pid} survived timeout cleanup")

    def test_committed_results_are_partial_and_revision_bound(self) -> None:
        results = Path(__file__).with_name("results.json")
        QUALIFY.validate_results(results)
        document = json.loads(results.read_text())
        self.assertEqual(document["candidate"]["revision"], "68d80a16b150a2c22d972cdf7db0bbe75e0ff3d3")
        self.assertIn("incomplete", {run["status"] for run in document["runs"]})
        self.assertIn("failed", {run["status"] for run in document["runs"]})

    def test_disappeared_process_identity_cannot_revive(self) -> None:
        pending = {42: "original"}
        pending = QUALIFY.retain_matching(pending, lambda _: None)
        self.assertEqual(pending, {})
        pending = QUALIFY.retain_matching(pending, lambda _: "original")
        self.assertEqual(pending, {})

    def test_reused_process_identity_is_not_signalled(self) -> None:
        signals = []
        remaining = QUALIFY.signal_matching({42: "original"}, signal.SIGKILL, lambda _: "replacement", lambda pid, value: signals.append((pid, value)))
        self.assertEqual(remaining, {})
        self.assertEqual(signals, [])

    def test_resolved_graph_must_match_every_pin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            resolved = Path(temporary) / "Package.resolved"
            expected = QUALIFY.expected_pins("electional", "candidate")
            QUALIFY.write_resolved(resolved, QUALIFY.CONSUMERS["electional"]["manifestSHA256"], expected)
            QUALIFY.verify_resolved(resolved, expected)
            document = json.loads(resolved.read_text())
            document["pins"] = document["pins"][:-1]
            resolved.write_text(json.dumps(document))
            with self.assertRaisesRegex(RuntimeError, "pin set"):
                QUALIFY.verify_resolved(resolved, expected)

    def test_resolution_uses_persisted_pins_without_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)
            commands = []
            with mock.patch.object(QUALIFY, "checked", side_effect=lambda command, cwd=None, timeout=300: commands.append(command) or ""):
                QUALIFY.resolve_dependencies(checkout, "astrology", "candidate")
            self.assertEqual(commands, [["swift", "package", "resolve"]])
            self.assertEqual({pin["identity"] for pin in json.loads((checkout / "Package.resolved").read_text())["pins"]}, {"astronomykit"})

    def test_electional_transitive_pin_revisions_are_preserved(self) -> None:
        pins = QUALIFY.expected_pins("electional", "candidate")
        self.assertEqual(pins["swift-crypto"]["state"]["revision"], "1c80d3aff53fedc445b60692980cb4f19a618657")
        self.assertEqual(pins["swift-asn1"]["state"]["revision"], "3b6410f7dee09eb33cdd26260c5fd47fda19b0e2")


if __name__ == "__main__":
    unittest.main()
