#!/usr/bin/env python3
"""Validate and hash the maintained dependency inventories for recorded evidence."""

import hashlib
import json
import re
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
OWNER_FILES = {
    'eclipse-native': 'Scripts/record-eclipse-event-evidence.py',
    'galilean-residuals': 'Scripts/galilean-residuals.py',
    'galilean-runtime': 'Scripts/measure-galilean-jup365-runtime.py',
    'global-solar': 'Scripts/record-global-solar-evidence.py',
    'local-solar': 'Scripts/record-local-solar-evidence.py',
    'moon-events': 'Scripts/generate-moon-events.py',
    'moon-full-integration': 'Scripts/record-moon-full-integration.py',
    'observer-events': 'Scripts/record-observer-event-evidence.py',
    'planetary-events': 'Scripts/record-planetary-event-evidence.py',
    'pluto-native': 'Scripts/record-pluto-de441-evidence.py',
    'pluto-observers': 'Scripts/capture-pluto-observers.py',
    'transits': 'Scripts/record-transit-evidence.py',
}
BINDING_FILES = {
    'Scripts/evidence-dependencies.json',
    'Scripts/evidence_dependencies.py',
    'Scripts/test_evidence_dependencies.py',
}
def _unique_strings(values, context):
    if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value for value in values):
        raise ValueError(f'{context} must be a nonempty string list')
    if len(values) != len(set(values)):
        raise ValueError(f'{context} contains duplicates')
    return values


def _path(value, context):
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or value == '.' or '..' in path.parts:
        raise ValueError(f'{context} contains a malformed path: {value!r}')
    return value


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'dependency inventory contains a duplicate key: {key}')
        result[key] = value
    return result


def validate_inventory(document, root=ROOT, required_owners=OWNER_FILES):
    if not isinstance(document, dict) or set(document) != {'schemaVersion', 'groups', 'owners'}:
        raise ValueError('dependency inventory schema differs')
    if document['schemaVersion'] != 1 or not isinstance(document['groups'], dict) or not isinstance(document['owners'], dict):
        raise ValueError('dependency inventory header differs')
    groups = document['groups']
    owners = document['owners']
    if set(owners) != set(required_owners):
        raise ValueError('dependency owner inventory differs')
    if not groups or any(not isinstance(name, str) or not name for name in groups):
        raise ValueError('dependency group inventory differs')

    group_paths = {}
    group_owners = {}
    globally_grouped = set()
    for name, definition in groups.items():
        if not isinstance(definition, dict) or set(definition) != {'owners', 'paths'}:
            raise ValueError(f'dependency group schema differs: {name}')
        paths = [_path(value, f'group {name}') for value in _unique_strings(definition['paths'], f'group {name}')]
        owners_for_group = _unique_strings(definition['owners'], f'group owners for {name}')
        unknown_owners = set(owners_for_group) - set(required_owners)
        if unknown_owners:
            raise ValueError(f'dependency group uses unknown owners: {sorted(unknown_owners)!r}')
        overlap = globally_grouped.intersection(paths)
        if overlap:
            raise ValueError(f'dependency paths occur in multiple groups: {sorted(overlap)!r}')
        globally_grouped.update(paths)
        group_paths[name] = paths
        group_owners[name] = owners_for_group

    expanded = {}
    for owner, definition in owners.items():
        if not isinstance(definition, dict) or set(definition) != {'groups', 'paths'}:
            raise ValueError(f'dependency owner schema differs: {owner}')
        owner_groups = _unique_strings(definition['groups'], f'owner groups for {owner}')
        unknown = set(owner_groups) - set(groups)
        if unknown:
            raise ValueError(f'dependency owner uses unknown groups: {sorted(unknown)!r}')
        required_groups = {name for name, covered in group_owners.items() if owner in covered}
        if set(owner_groups) != required_groups:
            raise ValueError(f'dependency required ownership coverage differs: {owner}')
        direct = [_path(value, f'owner paths for {owner}') for value in _unique_strings(definition['paths'], f'owner paths for {owner}')]
        paths = [path for group in owner_groups for path in group_paths[group]] + direct
        if len(paths) != len(set(paths)):
            raise ValueError(f'dependency owner expands to duplicate paths: {owner}')
        if required_owners[owner] not in paths:
            raise ValueError(f'dependency owner omits its recorder: {owner}')
        missing = [path for path in paths if not (root / path).is_file()]
        if missing:
            raise ValueError(f'dependency paths are missing for {owner}: {missing!r}')
        expanded[owner] = tuple(sorted(paths))
    return expanded


def load_inventory(root=ROOT, inventory_path=None):
    path = inventory_path or root / 'Scripts/evidence-dependencies.json'
    try:
        document = json.loads(path.read_bytes(), object_pairs_hook=_reject_duplicates)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f'dependency inventory is unreadable: {path}') from error
    return validate_inventory(document, root=root)


def paths(owner, root=ROOT):
    inventory = load_inventory(root=root)
    try:
        return inventory[owner]
    except KeyError as error:
        raise ValueError(f'unknown dependency owner: {owner}') from error


def source_hashes(owner, root=ROOT, overrides=None):
    owned = paths(owner, root=root)
    replacements = {} if overrides is None else overrides
    if not isinstance(replacements, dict) or any(path not in owned or not isinstance(data, bytes) for path, data in replacements.items()):
        raise ValueError('dependency hash overrides must contain owned paths and byte values')
    return {
        path: hashlib.sha256(replacements[path] if path in replacements else (root / path).read_bytes()).hexdigest()
        for path in owned
    }


def _validate_hashes(hashes, context):
    if not isinstance(hashes, dict) or any(not isinstance(path, str) or _path(path, context) != path or not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None for path, digest in hashes.items()):
        raise ValueError(f'{context} are malformed')


def verify_retained_inputs(owner, previous_hashes, root=ROOT):
    """Require unchanged result inputs before replay tools rebind archived measurements."""
    _validate_hashes(previous_hashes, 'previous dependency bindings')
    current = source_hashes(owner, root=root)
    all_paths = set(previous_hashes) | set(current)
    replay_tools = BINDING_FILES | {OWNER_FILES[owner]} | {path for path in all_paths if path.startswith('Scripts/test_') and path.endswith('.py')}
    changed = []
    for path in sorted(all_paths - replay_tools):
        if previous_hashes.get(path) != current.get(path):
            changed.append(path)
    if changed:
        raise ValueError(f'retained result dependencies differ for {owner}: {changed!r}')
    return current


def verify_rebound_document(previous, candidate, binding_key):
    if not isinstance(previous, dict) or not isinstance(candidate, dict) or binding_key not in previous or binding_key not in candidate:
        raise ValueError('rebound evidence schema differs')
    prior_payload = {key: value for key, value in previous.items() if key != binding_key}
    candidate_payload = {key: value for key, value in candidate.items() if key != binding_key}
    if prior_payload != candidate_payload:
        raise ValueError('rebound evidence changed scientific or measured payload')
