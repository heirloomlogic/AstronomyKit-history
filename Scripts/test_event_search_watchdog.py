import importlib.util
import pathlib
import sys
import unittest


SCRIPT = pathlib.Path(__file__).with_name("event-search-watchdog.py")


def load_module():
    spec = importlib.util.spec_from_file_location("event_search_watchdog", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load event-search-watchdog.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class EventSearchWatchdogTests(unittest.TestCase):
    def test_genuine_nonprogress_process_is_killed_at_deadline(self):
        watchdog = load_module()
        with self.assertRaises(watchdog.WatchdogExpired):
            watchdog.run_with_deadline(
                [sys.executable, "-c", "while True: pass"], timeout_seconds=0.2
            )

    def test_inventory_rejects_missing_and_duplicate_selectors(self):
        watchdog = load_module()
        selectors = list(watchdog.TEST_SELECTORS)
        watchdog.validate_inventory(selectors)
        with self.assertRaisesRegex(ValueError, "missing"):
            watchdog.validate_inventory(selectors[:-1])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            watchdog.validate_inventory(selectors + selectors[:1])

    def test_failed_child_is_not_reported_as_success(self):
        watchdog = load_module()
        with self.assertRaisesRegex(RuntimeError, "exit status 7"):
            watchdog.run_with_deadline(
                [sys.executable, "-c", "raise SystemExit(7)"], timeout_seconds=5
            )

    def test_empty_swift_filter_is_rejected(self):
        watchdog = load_module()
        with self.assertRaisesRegex(ValueError, "did not run exactly one test"):
            watchdog.require_one_test("warning: No matching test cases were run\n", "missing")
        watchdog.require_one_test(
            "Test run with 1 test in 1 suite passed after 0.001 seconds.\n", "present"
        )


if __name__ == "__main__":
    unittest.main()
