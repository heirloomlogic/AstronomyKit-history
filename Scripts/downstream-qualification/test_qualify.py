import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest


SCRIPT = Path(__file__).with_name("qualify.py")
SPEC = importlib.util.spec_from_file_location("downstream_qualify", SCRIPT)
assert SPEC and SPEC.loader
QUALIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALIFY)


class QualificationTests(unittest.TestCase):
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

    def test_resolved_revisions_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            resolved = Path(temporary) / "Package.resolved"
            resolved.write_text(json.dumps({"pins": [{"identity": "astronomykit", "state": {"revision": "candidate"}}]}))
            QUALIFY.verify_resolved(resolved, {"astronomykit": "candidate"})
            with self.assertRaisesRegex(RuntimeError, "expected other"):
                QUALIFY.verify_resolved(resolved, {"astronomykit": "other"})


if __name__ == "__main__":
    unittest.main()
