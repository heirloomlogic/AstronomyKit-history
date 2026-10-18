#!/usr/bin/env python3
"""Run bounded AstronomyKit qualification in pinned downstream checkouts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
PINNED_DEPENDENCIES = {
    "astrology": {},
    "electional": {
        "astrologykit": {
            "location": ASTROLOGY_URL,
            "state": {"branch": "main", "revision": CONSUMERS["astrology"]["revision"]},
        },
        "swift-asn1": {
            "location": "https://github.com/apple/swift-asn1.git",
            "state": {"revision": "3b6410f7dee09eb33cdd26260c5fd47fda19b0e2", "version": "1.7.3"},
        },
        "swift-crypto": {
            "location": "https://github.com/apple/swift-crypto",
            "state": {"revision": "1c80d3aff53fedc445b60692980cb4f19a618657", "version": "5.0.1"},
        },
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def normalized_identity(value: str) -> str:
    return " ".join(value.split())


def process_snapshot() -> tuple[dict[int, list[int]], dict[int, str]]:
    result = subprocess.run(["ps", "-axo", "pid=,ppid=,lstart=,command="], check=True, capture_output=True, text=True)
    children: dict[int, list[int]] = {}
    identities: dict[int, str] = {}
    for line in result.stdout.splitlines():
        fields = line.split(None, 7)
        if len(fields) < 8:
            continue
        pid, parent = int(fields[0]), int(fields[1])
        children.setdefault(parent, []).append(pid)
        identities[pid] = normalized_identity(" ".join(fields[2:]))
    return children, identities


def process_identity(pid: int) -> str | None:
    result = subprocess.run(["ps", "-o", "lstart=,command=", "-p", str(pid)], capture_output=True, text=True)
    identity = normalized_identity(result.stdout)
    return identity or None


def descendants(pid: int) -> list[tuple[int, str]]:
    table, identities = process_snapshot()
    found: list[tuple[int, str]] = []
    pending = list(table.get(pid, []))
    while pending:
        child = pending.pop()
        identity = identities.get(child)
        if identity is not None:
            found.append((child, identity))
        pending.extend(table.get(child, []))
    return found


def retain_matching(targets: dict[int, str], identity_reader=process_identity) -> dict[int, str]:
    return {pid: identity for pid, identity in targets.items() if identity_reader(pid) == identity}


def signal_matching(targets: dict[int, str], value: signal.Signals, identity_reader=process_identity, signaler=os.kill) -> dict[int, str]:
    remaining: dict[int, str] = {}
    for pid, identity in targets.items():
        if identity_reader(pid) != identity:
            continue
        try:
            signaler(pid, value)
            remaining[pid] = identity
        except ProcessLookupError:
            pass
    return remaining


def terminate_tree(process: subprocess.Popen[str], grace_seconds: float = 5) -> list[int]:
    captured = descendants(process.pid)
    parent_identity = process_identity(process.pid)
    pending = signal_matching(dict(reversed(captured)), signal.SIGTERM)
    if parent_identity is not None:
        pending.update(signal_matching({process.pid: parent_identity}, signal.SIGTERM))
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        pending = retain_matching(pending)
        if not pending:
            break
        time.sleep(0.05)
    if pending:
        signal_matching(pending, signal.SIGKILL)
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    return [pid for pid, _ in captured]


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
    matches = re.findall(r"Test run with (\d+) tests?(?: in (\d+) suites?)? (passed|failed)", output)
    reported = ({"tests": int(matches[-1][0]), "suites": int(matches[-1][1]) if matches[-1][1] else None, "status": matches[-1][2]} if matches else None)
    status = "incomplete" if timed_out else "passed" if returncode == 0 else "failed"
    is_swift_test = (Path(command[0]).name == "swift" and len(command) > 1 and command[1] == "test") or Path(command[0]).name == "swift-test"
    evidence_error = None
    if timed_out and reported is not None and reported["status"] == "failed":
        evidence_error = "test summary reported failure before timeout"
    elif timed_out and reported is not None and reported["tests"] == 0:
        evidence_error = "zero tests executed before timeout"
    elif reported is not None and reported["status"] == "failed":
        status = "failed"
        evidence_error = "test summary reported failure"
    elif not timed_out and returncode == 0 and is_swift_test and reported is None:
        status = "failed"
        evidence_error = "missing test summary"
    elif reported is not None and reported["tests"] == 0:
        status = "failed"
        evidence_error = "zero tests executed"
    return {
        "name": name,
        "command": command,
        "status": status,
        "exitCode": returncode,
        "durationSeconds": round(time.monotonic() - started, 3),
        "reportedSummary": reported,
        "timeoutSeconds": timeout,
        "capturedDescendantCount": len(captured_descendants),
        "evidenceError": evidence_error,
        "log": str(log),
    }


def checked(command: list[str], cwd: Path | None = None, timeout: int = 300) -> str:
    result = subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip()


def clone_at(repository: str, revision: str, destination: Path) -> None:
    checked(["git", "clone", "--no-checkout", repository, str(destination)])
    checked(["git", "checkout", "--detach", revision], destination)


def expected_pins(consumer: str, candidate_revision: str) -> dict[str, dict[str, object]]:
    pins = {
        "astronomykit": {
            "location": ASTRONOMY_URL,
            "state": {"revision": candidate_revision, "version": ASTRONOMY_ALIAS_VERSION},
        }
    }
    pins.update(PINNED_DEPENDENCIES[consumer])
    return pins


def write_resolved(path: Path, origin_hash: str, pins: dict[str, dict[str, object]]) -> None:
    document = {
        "originHash": origin_hash,
        "pins": [
            {"identity": identity, "kind": "remoteSourceControl", **pins[identity]}
            for identity in sorted(pins)
        ],
        "version": 3,
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def verify_resolved(path: Path, expected: dict[str, dict[str, object]]) -> None:
    actual = {pin["identity"]: {"location": pin["location"], "state": pin["state"]} for pin in json.loads(path.read_text())["pins"]}
    if set(actual) != set(expected):
        raise RuntimeError(f"resolved pin set {sorted(actual)} does not match expected pin set {sorted(expected)}")
    for identity, pin in expected.items():
        if actual[identity] != pin:
            raise RuntimeError(f"{identity} resolved to {actual[identity]}, expected {pin}")


def resolve_dependencies(checkout: Path, consumer: str, candidate_revision: str) -> None:
    pins = expected_pins(consumer, candidate_revision)
    write_resolved(checkout / "Package.resolved", CONSUMERS[consumer]["manifestSHA256"], pins)
    checked(["swift", "package", "resolve"], checkout)
    verify_resolved(checkout / "Package.resolved", pins)


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
        resolve_dependencies(checkout, name, candidate_revision)
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


def validate_document(document: dict[str, object]) -> None:
    if document.get("schemaVersion") != 1:
        raise ValueError("schemaVersion must be 1")
    if document.get("releaseAcceptance") != "unmet":
        raise ValueError("partial qualification must leave releaseAcceptance unmet")
    if not isinstance(document.get("recordedAt"), str):
        raise ValueError("recordedAt is required")
    candidate = document.get("candidate")
    if not isinstance(candidate, dict) or not re.fullmatch(r"[0-9a-f]{40}", str(candidate.get("revision", ""))):
        raise ValueError("candidate.revision must be a full Git SHA")
    environment = document.get("environment")
    if not isinstance(environment, dict) or not environment:
        raise ValueError("environment is required")
    consumers = document.get("consumers")
    if not isinstance(consumers, list) or not consumers:
        raise ValueError("at least one consumer binding is required")
    consumer_ids = set()
    for consumer in consumers:
        if not isinstance(consumer, dict):
            raise ValueError("consumer bindings must be objects")
        settings = CONSUMERS.get(consumer.get("id"))
        if settings is None or consumer.get("revision") != settings["revision"] or consumer.get("manifestSHA256") != settings["manifestSHA256"]:
            raise ValueError(f"consumer binding is invalid: {consumer.get('id')}")
        consumer_ids.add(consumer["id"])
    expected_graphs = {consumer: expected_pins(consumer, candidate["revision"]) for consumer in consumer_ids}
    if document.get("resolvedGraphs") != expected_graphs:
        raise ValueError("resolvedGraphs must exactly match the pinned consumer dependency graphs")
    runs = document.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("at least one run is required")
    for run in runs:
        if not isinstance(run, dict):
            raise ValueError("runs must be objects")
        if run.get("consumer") not in consumer_ids or not isinstance(run.get("name"), str) or run.get("status") not in VALID_STATUSES:
            raise ValueError(f"invalid run status: {run.get('status')}")


def validate_results(path: Path) -> None:
    validate_document(json.loads(path.read_text()))


def make_results_document(candidate_revision: str, selected: list[str], runs: list[dict[str, object]], environment: dict[str, str], recorded_at: str | None = None) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "recordedAt": recorded_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "releaseAcceptance": "unmet",
        "candidate": {"revision": candidate_revision},
        "consumers": [{"id": name, **CONSUMERS[name]} for name in selected],
        "resolvedGraphs": {name: expected_pins(name, candidate_revision) for name in selected},
        "environment": environment,
        "runs": runs,
    }


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
    document = make_results_document(candidate_revision, selected, runs, {"machine": platform.machine(), "platform": platform.platform(), "swift": swift_version})
    validate_document(document)
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
