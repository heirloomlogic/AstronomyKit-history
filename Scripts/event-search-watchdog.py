#!/usr/bin/env python3

import argparse
import collections
import os
import re
import signal
import subprocess
import sys


TEST_SELECTORS = (
    "AstronomyKitTests.EngineObserverEventsTests/fuzzGuards()",
    "AstronomyKitTests.EngineObserverEventsTests/invalidInputs()",
    "AstronomyKitTests.EngineAngularEventTests/invalidInputs()",
    "AstronomyKitTests.EngineLunarEventTests/invalidInputs()",
    "AstronomyKitTests.EnginePlanetaryEventTests/invalidInputs()",
    "AstronomyKitTests.RiseSetTests/ExtremeInputTests/nonFiniteLimit(limitDays:)",
    "AstronomyKitTests.RiseSetTests/ExtremeInputTests/stalledStart(ut:)",
    "AstronomyKitTests.RiseSetTests/ExtremeInputTests/nonFiniteStart(ut:)",
    "AstronomyKitTests.AltitudeSearchTests/nonFiniteLimit(limitDays:)",
    "AstronomyKitTests.AltitudeSearchTests/windowReachingStallPoint(sign:limitDays:)",
    "AstronomyKitTests.ApsisTests/PlanetApsisTests/bruteForceNonFiniteStart(body:ut:)",
    "AstronomyKitTests.RelativeLongitudeTests/ExtremeInputTests/nonFiniteTarget(angle:)",
    "AstronomyKitTests.LunarNodeTests/unsteppableStartThrows(ut:)",
    "AstronomyKitTests.SeasonsTests/InputValidation/yearAboveInt32Throws()",
    "AstronomyKitTests.SeasonsTests/InputValidation/intMinYearThrows()",
    "AstronomyKitTests.SearchTests/sunLongitudeNonFiniteTarget(target:)",
    "AstronomyKitTests.SearchCallbackContractTests/finiteNonconvergence(model:)",
    "AstronomyKitTests.SearchCallbackContractTests/nonfiniteCallback(model:value:)",
    "AstronomyKitTests.SearchCallbackContractTests/nonfiniteStart(model:base:)",
    "AstronomyKitTests.SearchCallbackContractTests/stepFailsToConverge(model:)",
    "AstronomyKitTests.SearchCallbackContractTests/unusableTolerance(model:tolerance:)",
)


class WatchdogExpired(RuntimeError):
    pass


def run_with_deadline(command, timeout_seconds):
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        output, _ = process.communicate()
        rendered = " ".join(command)
        raise WatchdogExpired(
            f"child exceeded {timeout_seconds:g}-second deadline: {rendered}\n{output}"
        ) from None
    if process.returncode != 0:
        rendered = " ".join(command)
        raise RuntimeError(
            f"child exited with exit status {process.returncode}: {rendered}\n{output}"
        )
    return output


def validate_inventory(listed_selectors):
    manifest_counts = collections.Counter(TEST_SELECTORS)
    repeated_manifest = sorted(name for name, count in manifest_counts.items() if count != 1)
    if repeated_manifest:
        raise ValueError(f"duplicate selectors in watchdog manifest: {repeated_manifest}")
    listed_counts = collections.Counter(listed_selectors)
    missing = sorted(set(TEST_SELECTORS) - set(listed_selectors))
    if missing:
        raise ValueError(f"missing watchdog selectors from Swift test inventory: {missing}")
    duplicated = sorted(name for name in TEST_SELECTORS if listed_counts[name] != 1)
    if duplicated:
        raise ValueError(f"duplicate watchdog selectors in Swift test inventory: {duplicated}")


def require_one_test(output, selector):
    if re.search(r"Test run with 1 test in [0-9]+ suites? passed", output) is None:
        raise ValueError(f"watchdog filter did not run exactly one test: {selector}")


def arguments():
    parser = argparse.ArgumentParser(
        description="Run malformed and non-progress event-search regressions in killable child process groups."
    )
    parser.add_argument("-c", "--configuration", choices=("debug", "release"), default="debug")
    parser.add_argument("--scratch-path", default=".build/event-search-watchdog")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=30)
    return parser.parse_args()


def main():
    args = arguments()
    if not args.timeout_seconds > 0:
        raise ValueError("timeout must be positive")
    base = [
        "swift",
        "test",
        "-c",
        args.configuration,
        "--scratch-path",
        args.scratch_path,
    ]
    inventory_command = base + (["--skip-build"] if args.skip_build else []) + ["list"]
    inventory = subprocess.run(
        inventory_command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).stdout.splitlines()
    validate_inventory([line.strip() for line in inventory if line.startswith("AstronomyKitTests.")])
    for selector in TEST_SELECTORS:
        print(f"watchdog: {selector}", flush=True)
        output = run_with_deadline(
            base + ["--skip-build", "--filter", selector.split("(", 1)[0]],
            args.timeout_seconds,
        )
        require_one_test(output, selector)
        print(output, end="" if output.endswith("\n") else "\n")
    print(
        f"watchdog: {len(TEST_SELECTORS)} malformed/non-progress event-search regressions passed",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
