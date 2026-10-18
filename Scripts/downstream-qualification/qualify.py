#!/usr/bin/env python3
"""Run bounded AstronomyKit qualification in pinned downstream checkouts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import time


CONSUMERS = {
    "astrology": {
        "repository": "https://github.com/heirloomlogic/AstrologyKit",
        "revision": "347eddf5bc69837fff9f986a074d577032d7aae3",
        "manifestSHA256": "0fdcb5635e0df53cf3891718e6dde29246176928aed06d3b854b31965abc736a",
    },
    "electional": {
        "repository": "https://github.com/heirloomlogic/ElectionalKit",
        "revision": "b9cd413e5db3a64304d2afcb5e1bbe42e1910925",
        "manifestSHA256": "09bd04c7506ee5142601e69a4e388bda5ce06a50f20e28441725e42fbfe01d4b",
    },
}
ASTRONOMY_URL = "https://github.com/heirloomlogic/AstronomyKit"
ASTROLOGY_URL = "https://github.com/heirloomlogic/AstrologyKit"
ASTRONOMY_ALIAS_VERSION = "3.2.0+upstream-2.1.19"
VALID_STATUSES = {"passed", "failed", "incomplete", "blocked"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def process_table() -> dict[int, list[int]]:
    result = subprocess.run(["ps", "-axo", "pid=,ppid="], check=True, capture_output=True, text=True)
    children: dict[int, list[int]] = {}
    for line in result.stdout.splitlines():
        pid, parent = (int(value) for value in line.split())
        children.setdefault(parent, []).append(pid)
    return children


def descendants(pid: int) -> list[int]:
    table = process_table()
    found: list[int] = []
    pending = list(table.get(pid, []))
    while pending:
        child = pending.pop()
        found.append(child)
        pending.extend(table.get(child, []))
    return found


def terminate_tree(process: subprocess.Popen[str], grace_seconds: float = 5) -> list[int]:
    captured = descendants(process.pid)
    targets = list(reversed(captured)) + [process.pid]
    for pid in targets:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        living = []
        for pid in targets:
            try:
                os.kill(pid, 0)
                living.append(pid)
            except ProcessLookupError:
                pass
        if not living:
            return captured
        time.sleep(0.05)
    for pid in targets:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    return captured


def run_command(name: str, command: list[str], cwd: Path, logs: Path, timeout: float, environment: dict[str, str] | None = None) -> dict[str, object]:
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{name}.log"
    env = os.environ.copy()
    env["TZ"] = "UTC"
    env.update(environment or {})
    started = time.monotonic()
    timed_out = False
    captured_descendants: list[int] = []
    with log.open("w") as stream:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True, text=True)
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = None
            captured_descendants = terminate_tree(process)
    output = log.read_text(errors="replace")
    matches = re.findall(r"Test run with (\d+) tests? in (\d+) suites? (passed|failed)", output)
    reported = ({"tests": int(matches[-1][0]), "suites": int(matches[-1][1]), "status": matches[-1][2]} if matches else None)
    status = "incomplete" if timed_out else "passed" if returncode == 0 else "failed"
    if reported is not None and reported["tests"] == 0:
        status = "failed"
    return {
        "name": name,
        "command": command,
        "status": status,
        "exitCode": returncode,
        "durationSeconds": round(time.monotonic() - started, 3),
        "reportedSummary": reported,
        "timeoutSeconds": timeout,
        "capturedDescendantCount": len(captured_descendants),
        "log": str(log),
    }


def checked(command: list[str], cwd: Path | None = None, timeout: int = 300) -> str:
    result = subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip()


def clone_at(repository: str, revision: str, destination: Path) -> None:
    checked(["git", "clone", "--no-checkout", repository, str(destination)])
    checked(["git", "checkout", "--detach", revision], destination)


def verify_resolved(path: Path, expected: dict[str, str]) -> None:
    pins = {pin["identity"]: pin["state"].get("revision") for pin in json.loads(path.read_text())["pins"]}
    for identity, revision in expected.items():
        if pins.get(identity) != revision:
            raise RuntimeError(f"{identity} resolved to {pins.get(identity)}, expected {revision}")


def prepare(candidate: Path, workspace: Path, selected: list[str]) -> tuple[str, dict[str, Path]]:
    candidate_revision = checked(["git", "rev-parse", "HEAD"], candidate)
    workspace.mkdir(parents=True, exist_ok=False)
    mirrors = workspace / "mirrors"
    mirrors.mkdir()
    astronomy_mirror = mirrors / "AstronomyKit.git"
    checked(["git", "clone", "--bare", str(candidate), str(astronomy_mirror)])
    checked(["git", "tag", "--force", ASTRONOMY_ALIAS_VERSION, candidate_revision], astronomy_mirror)
    consumer_paths: dict[str, Path] = {}
    astrology_mirror: Path | None = None
    if "electional" in selected:
        astrology_mirror = mirrors / "AstrologyKit.git"
        checked(["git", "clone", "--bare", ASTROLOGY_URL, str(astrology_mirror)])
        checked(["git", "update-ref", "refs/heads/main", CONSUMERS["astrology"]["revision"]], astrology_mirror)
    for name in selected:
        settings = CONSUMERS[name]
        checkout = workspace / name
        clone_at(settings["repository"], settings["revision"], checkout)
        actual_hash = sha256(checkout / "Package.swift")
        if actual_hash != settings["manifestSHA256"]:
            raise RuntimeError(f"{name} Package.swift SHA-256 {actual_hash} does not match {settings['manifestSHA256']}")
        checked(["swift", "package", "config", "set-mirror", "--original", ASTRONOMY_URL, "--mirror", astronomy_mirror.as_uri()], checkout)
        if astrology_mirror is not None and name == "electional":
            checked(["swift", "package", "config", "set-mirror", "--original", ASTROLOGY_URL, "--mirror", astrology_mirror.as_uri()], checkout)
        checked(["swift", "package", "update"], checkout)
        expected = {"astronomykit": candidate_revision}
        if name == "electional":
            expected["astrologykit"] = CONSUMERS["astrology"]["revision"]
        verify_resolved(checkout / "Package.resolved", expected)
        consumer_paths[name] = checkout
    return candidate_revision, consumer_paths


def cases(name: str, checkout: Path, logs: Path, include_full: bool) -> list[dict[str, object]]:
    swift = ["swift"]
    if name == "astrology":
        result = [
            ("build-debug", swift + ["build", "--build-tests"], 180, {}),
            ("build-release-tests", swift + ["build", "-c", "release", "--build-tests"], 180, {}),
            ("consumer", swift + ["test", "--skip-build", "--filter", "AstrologyKitConsumerTests"], 120, {}),
            ("fixed-stars", swift + ["test", "--skip-build", "--filter", "FixedStarLongitudesTests"], 120, {}),
            ("polar", swift + ["test", "--skip-build", "--filter", "PolarEdgeRegressionTests"], 120, {}),
            ("analytic-motion", swift + ["test", "--skip-build", "--filter", "AnalyticEventMotionTests"], 120, {}),
            ("multi-decade", swift + ["test", "--skip-build", "--filter", "MultiDecadePositionValidationTests"], 120, {}),
            ("event-service", swift + ["test", "--skip-build", "--filter", "ElectionEventServiceTests"], 120, {}),
        ]
        if include_full:
            result.insert(2, ("full-debug", swift + ["test"], 660, {}))
    else:
        one_day = str(logs / "window-one-day.json")
        seven_day = str(logs / "window-seven-day.json")
        result = [
            ("build-debug", swift + ["build", "--build-tests"], 180, {}),
            ("consumer", swift + ["test", "--skip-build", "--filter", "ElectionalKitConsumerTests"], 120, {}),
            ("published", swift + ["test", "--skip-build", "--filter", "PublishedElectionTests"], 120, {}),
            ("assessment", swift + ["test", "--skip-build", "--filter", "ElectionAssessmentTests"], 120, {}),
            ("horizon", swift + ["test", "--skip-build", "--filter", "ElectionSearchHorizonTests"], 120, {}),
            ("benchmark-one-day", swift + ["test", "--skip-build", "--filter", "ElectionSearchBenchmarkTests.daytimeSearch"], 180, {"ELECTIONAL_SEARCH_BENCHMARK_DAYS": "1"}),
            ("benchmark-seven-day", swift + ["test", "--skip-build", "--filter", "ElectionSearchBenchmarkTests.daytimeSearch"], 240, {"ELECTIONAL_SEARCH_BENCHMARK_DAYS": "7"}),
            ("window-one-day", swift + ["test", "--skip-build", "--filter", "TerrestrialWindowAcceptanceTests.emitWorkload"], 180, {"ASTROLOGY_WINDOW_DAYS": "1", "ASTROLOGY_WINDOW_OUTPUT": one_day}),
            ("window-seven-day", swift + ["test", "--skip-build", "--filter", "TerrestrialWindowAcceptanceTests.emitWorkload"], 240, {"ASTROLOGY_WINDOW_DAYS": "7", "ASTROLOGY_WINDOW_OUTPUT": seven_day}),
        ]
    return [run_command(case_name, command, checkout, logs, timeout, environment) for case_name, command, timeout, environment in result]


def validate_results(path: Path) -> None:
    document = json.loads(path.read_text())
    if document.get("schemaVersion") != 1:
        raise ValueError("schemaVersion must be 1")
    if document.get("releaseAcceptance") != "unmet":
        raise ValueError("partial qualification must leave releaseAcceptance unmet")
    for consumer in document.get("consumers", []):
        settings = CONSUMERS.get(consumer.get("id"))
        if settings is None or consumer.get("revision") != settings["revision"] or consumer.get("manifestSHA256") != settings["manifestSHA256"]:
            raise ValueError(f"consumer binding is invalid: {consumer.get('id')}")
    for run in document.get("runs", []):
        if run.get("status") not in VALID_STATUSES:
            raise ValueError(f"invalid run status: {run.get('status')}")


def run(args: argparse.Namespace) -> None:
    selected = list(CONSUMERS) if args.consumer == "all" else [args.consumer]
    candidate = args.candidate.resolve()
    workspace = args.workspace.resolve()
    output = args.output.resolve()
    candidate_revision, paths = prepare(candidate, workspace, selected)
    runs: list[dict[str, object]] = []
    for name in selected:
        for result in cases(name, paths[name], workspace / "logs" / name, args.include_full):
            result["consumer"] = name
            runs.append(result)
            print(json.dumps({"consumer": name, **result}), flush=True)
    swift_version = checked(["swift", "--version"])
    document = {
        "schemaVersion": 1,
        "candidateRevision": candidate_revision,
        "consumers": [{"id": name, **CONSUMERS[name]} for name in selected],
        "environment": {"machine": platform.machine(), "platform": platform.platform(), "swift": swift_version},
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--candidate", type=Path, required=True)
    run_parser.add_argument("--workspace", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--consumer", choices=["all", *CONSUMERS], default="all")
    run_parser.add_argument("--include-full", action="store_true")
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("results", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        run(args)
    else:
        validate_results(args.results)


if __name__ == "__main__":
    main()
