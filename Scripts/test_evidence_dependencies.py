#!/usr/bin/env python3
"""Adversarial checks for the recorded-evidence dependency inventory."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('evidence_dependencies_test_subject', ROOT / 'Scripts/evidence_dependencies.py')
dependencies = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dependencies)


class EvidenceDependencyTests(unittest.TestCase):
    def document(self):
        return json.loads((ROOT / 'Scripts/evidence-dependencies.json').read_bytes())

    def test_every_required_owner_has_a_complete_readable_inventory(self):
        expanded = dependencies.validate_inventory(self.document())
        self.assertEqual(set(expanded), set(dependencies.OWNER_FILES))
        for owner, recorder in dependencies.OWNER_FILES.items():
            self.assertIn(recorder, expanded[owner])
            self.assertIn('Scripts/evidence-dependencies.json', expanded[owner])
            self.assertIn('Scripts/evidence_dependencies.py', expanded[owner])

    def test_migrated_capture_owners_bind_compiled_public_test_and_fixture_snapshots(self):
        inventory = dependencies.load_inventory()
        public_sources = {str(path.relative_to(ROOT)) for path in (ROOT / 'Sources/AstronomyKit').glob('*.swift')}
        test_sources = {str(path.relative_to(ROOT)) for path in (ROOT / 'Tests/AstronomyKitTests').rglob('*.swift')}
        fixtures = {str(path.relative_to(ROOT)) for path in (ROOT / 'Tests/AstronomyKitTests/Fixtures').rglob('*') if path.is_file()}
        for owner in ['eclipse-native', 'moon-events', 'moon-full-integration', 'pluto-native']:
            owned = set(inventory[owner])
            with self.subTest(owner=owner):
                self.assertIn('Package.swift', owned)
                self.assertTrue(public_sources <= owned)
                self.assertTrue(test_sources <= owned)
                self.assertTrue(fixtures <= owned)

    def test_every_capture_owner_binds_resource_packaging_manifest(self):
        inventory = dependencies.load_inventory()
        owners = sorted(dependencies.OWNER_FILES)
        all_owned = {path for paths in inventory.values() for path in paths}
        with tempfile.TemporaryDirectory() as directory:
            shadow = Path(directory)
            for relative in all_owned:
                destination = shadow / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(ROOT / relative)
            before = {owner: dependencies.source_hashes(owner, root=shadow) for owner in owners}
            manifest = shadow / 'Package.swift'
            manifest.unlink()
            manifest.write_bytes((ROOT / 'Package.swift').read_bytes().replace(b'.copy("Resources/ModelTables")', b'.copy("Resources/ModelTables/moon-de440.bin")'))
            for owner in owners:
                with self.subTest(owner=owner):
                    self.assertIn('Package.swift', inventory[owner])
                    self.assertNotEqual(dependencies.source_hashes(owner, root=shadow)['Package.swift'], before[owner]['Package.swift'])

    def test_direct_and_transitive_edits_invalidate_but_unrelated_engine_addition_does_not(self):
        owner = 'global-solar'
        all_owned = {path for paths in dependencies.load_inventory().values() for path in paths}
        with tempfile.TemporaryDirectory() as directory:
            shadow = Path(directory)
            for relative in all_owned:
                destination = shadow / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(ROOT / relative)
            before = dependencies.source_hashes(owner, root=shadow)
            unrelated = shadow / 'Sources/AstronomyKit/Engine/Stars/NewUnrelatedEngineFile.swift'
            unrelated.parent.mkdir(parents=True, exist_ok=True)
            unrelated.write_text('enum NewUnrelatedEngineFile {}\n')
            self.assertEqual(dependencies.source_hashes(owner, root=shadow), before)
            relevant = 'Sources/AstronomyKit/Engine/Eclipses/EngineGlobalSolarEvents.swift'
            (shadow / relevant).unlink()
            (shadow / relevant).write_bytes((ROOT / relevant).read_bytes() + b'\n')
            after = dependencies.source_hashes(owner, root=shadow)
            self.assertNotEqual(after[relevant], before[relevant])
            self.assertEqual({path: digest for path, digest in after.items() if path != relevant}, {path: digest for path, digest in before.items() if path != relevant})
            direct = 'Scripts/capture-global-solar.py'
            (shadow / direct).unlink()
            (shadow / direct).write_bytes((ROOT / direct).read_bytes() + b'\n')
            after_direct = dependencies.source_hashes(owner, root=shadow)
            self.assertNotEqual(after_direct[direct], before[direct])

    def test_migrated_scientific_owners_ignore_an_unrelated_addition_and_all_bind_shared_runtime(self):
        owners = ['eclipse-native', 'galilean-runtime', 'moon-events', 'moon-full-integration', 'pluto-native']
        addition_stable = ['eclipse-native', 'moon-events', 'moon-full-integration', 'pluto-native']
        all_owned = {path for paths in dependencies.load_inventory().values() for path in paths}
        relevant = 'Sources/AstronomyKit/Engine/Foundation/EngineConstants.swift'
        with tempfile.TemporaryDirectory() as directory:
            shadow = Path(directory)
            for relative in all_owned:
                destination = shadow / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(ROOT / relative)
            before = {owner: dependencies.source_hashes(owner, root=shadow) for owner in owners}
            unrelated = shadow / 'Sources/AstronomyKit/Engine/NewUnrelatedEngineFile.swift'
            unrelated.write_text('enum NewUnrelatedEngineFile {}\n')
            for owner in addition_stable:
                with self.subTest(owner=owner, mutation='unrelated'):
                    self.assertEqual(dependencies.source_hashes(owner, root=shadow), before[owner])
            (shadow / relevant).unlink()
            (shadow / relevant).write_bytes((ROOT / relevant).read_bytes() + b'\n')
            for owner in owners:
                with self.subTest(owner=owner, mutation='relevant'):
                    self.assertNotEqual(dependencies.source_hashes(owner, root=shadow)[relevant], before[owner][relevant])

    def test_inventory_addition_invalidates_retained_bindings(self):
        owner = 'global-solar'
        all_owned = {path for paths in dependencies.load_inventory().values() for path in paths}
        with tempfile.TemporaryDirectory() as directory:
            shadow = Path(directory)
            for relative in all_owned | {'README.md'}:
                destination = shadow / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(ROOT / relative)
            before = dependencies.source_hashes(owner, root=shadow)
            inventory_path = shadow / 'Scripts/evidence-dependencies.json'
            inventory_path.unlink()
            document = self.document()
            document['owners'][owner]['paths'].append('README.md')
            inventory_path.write_text(json.dumps(document))
            after = dependencies.source_hashes(owner, root=shadow)
            self.assertIn('README.md', after)
            self.assertNotEqual(after['Scripts/evidence-dependencies.json'], before['Scripts/evidence-dependencies.json'])
            with self.assertRaisesRegex(ValueError, 'result dependencies differ'):
                dependencies.verify_retained_inputs(owner, before, root=shadow)

    def test_capture_override_is_limited_to_owned_byte_content(self):
        capture = 'Scripts/eclipse-data/global-captures.json'
        actual = dependencies.source_hashes('global-solar')
        replaced = dependencies.source_hashes('global-solar', overrides={capture: b'candidate capture'})
        self.assertNotEqual(replaced[capture], actual[capture])
        with self.assertRaisesRegex(ValueError, 'owned paths and byte values'):
            dependencies.source_hashes('global-solar', overrides={'unowned': b'value'})
        with self.assertRaisesRegex(ValueError, 'owned paths and byte values'):
            dependencies.source_hashes('global-solar', overrides={capture: 'not bytes'})

    def test_retained_rebind_rejects_changed_or_missing_result_inputs(self):
        owner = 'global-solar'
        previous = dependencies.source_hashes(owner)
        self.assertEqual(dependencies.verify_retained_inputs(owner, previous), previous)
        relevant = 'Sources/AstronomyKit/Engine/Eclipses/EngineGlobalSolarEvents.swift'
        for mutation in ['changed', 'missing']:
            altered = dict(previous)
            if mutation == 'changed':
                altered[relevant] = '0' * 64
            else:
                del altered[relevant]
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'result dependencies differ'):
                dependencies.verify_retained_inputs(owner, altered)
        replay_change = dict(previous)
        del replay_change['Scripts/evidence_dependencies.py']
        replay_change[dependencies.OWNER_FILES[owner]] = '0' * 64
        self.assertEqual(dependencies.verify_retained_inputs(owner, replay_change), previous)

    def test_retained_rebind_rejects_new_input_even_if_unlinked_history_has_the_same_bytes(self):
        owner = 'global-solar'
        current = dependencies.source_hashes(owner)
        relevant = 'Sources/AstronomyKit/Engine/Gravity/Generated/DE441/PlutoDE441SunData.swift'
        previous = dict(current)
        del previous[relevant]
        with self.assertRaisesRegex(ValueError, 'result dependencies differ'):
            dependencies.verify_retained_inputs(owner, previous)

    def test_retained_rebind_rejects_paths_removed_from_the_inventory(self):
        owner = 'global-solar'
        all_owned = {path for paths in dependencies.load_inventory().values() for path in paths}
        with tempfile.TemporaryDirectory() as directory:
            shadow = Path(directory)
            for relative in all_owned:
                destination = shadow / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(ROOT / relative)
            previous = dependencies.source_hashes(owner, root=shadow)
            inventory_path = shadow / 'Scripts/evidence-dependencies.json'
            inventory_path.unlink()
            document = self.document()
            document['groups']['engine-eclipses']['paths'].remove(
                'Sources/AstronomyKit/Engine/Eclipses/EngineGlobalSolarEvents.swift')
            inventory_path.write_text(json.dumps(document))
            dependencies.load_inventory(root=shadow)
            with self.assertRaisesRegex(ValueError, 'result dependencies differ'):
                dependencies.verify_retained_inputs(owner, previous, root=shadow)

    def test_retained_rebind_rejects_a_removed_group_owner_and_declaration(self):
        owner = 'global-solar'
        all_owned = {path for paths in dependencies.load_inventory().values() for path in paths}
        with tempfile.TemporaryDirectory() as directory:
            shadow = Path(directory)
            for relative in all_owned:
                destination = shadow / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(ROOT / relative)
            previous = dependencies.source_hashes(owner, root=shadow)
            inventory_path = shadow / 'Scripts/evidence-dependencies.json'
            inventory_path.unlink()
            document = self.document()
            document['groups']['engine-eclipses']['owners'].remove(owner)
            document['owners'][owner]['groups'].remove('engine-eclipses')
            inventory_path.write_text(json.dumps(document))
            dependencies.load_inventory(root=shadow)
            with self.assertRaisesRegex(ValueError, 'result dependencies differ'):
                dependencies.verify_retained_inputs(owner, previous, root=shadow)

    def test_transitive_runtime_dependencies_are_owned_by_every_result_they_affect(self):
        inventory = dependencies.load_inventory()
        apparent_sun = 'Sources/AstronomyKit/Engine/Gravity/Generated/DE441/PlutoDE441SunData.swift'
        apparent_evaluator = 'Sources/AstronomyKit/Engine/Gravity/EnginePlutoDE441.swift'
        moon_blend = 'Sources/AstronomyKit/Engine/Moon/EngineMoonEphemeris.swift'
        for owner in ['global-solar', 'local-solar', 'observer-events', 'planetary-events', 'pluto-observers', 'transits']:
            for dependency in [apparent_sun, apparent_evaluator]:
                with self.subTest(owner=owner, dependency=dependency):
                    self.assertIn(dependency, inventory[owner])
        self.assertIn(moon_blend, inventory['pluto-observers'])
        for owner in ['eclipse-native', 'galilean-runtime', 'moon-events', 'moon-full-integration', 'pluto-native']:
            for dependency in [
                apparent_sun,
                apparent_evaluator,
                moon_blend,
                'Sources/AstronomyKit/Engine/Bodies/Generated/Jup365/Jup365Index.swift',
            ]:
                with self.subTest(owner=owner, dependency=dependency):
                    self.assertIn(dependency, inventory[owner])
        for owner in ['eclipse-native', 'moon-events', 'moon-full-integration', 'pluto-native']:
            for dependency in [
                'Tests/AstronomyKitTests/Engine/Planets/PlanetTestSupport.swift',
                'Tests/AstronomyKitTests/JPLValidationTests.swift',
                'Tests/AstronomyKitTests/Fixtures/IndependentReferences/distance-fixtures.json',
            ]:
                with self.subTest(owner=owner, dependency=dependency):
                    self.assertIn(dependency, inventory[owner])
        for dependency in [
            'Sources/AstronomyKit/AstronomyError.swift',
            'Sources/AstronomyKit/CelestialBody.swift',
            'Sources/AstronomyKit/Coordinates.swift',
            'Sources/AstronomyKit/Position.swift',
            'Sources/AstronomyKit/NativeCoordinateValues.swift',
            'Sources/AstronomyKit/Observer.swift',
            'Sources/AstronomyKit/Time.swift',
            'Tests/AstronomyKitTests/JPLValidationTests.swift',
        ]:
            with self.subTest(owner='pluto-observers', dependency=dependency):
                self.assertIn(dependency, inventory['pluto-observers'])
        for dependency in [
            'Tests/AstronomyKitTests/Engine/Planets/PlanetTestSupport.swift',
            'Tests/AstronomyKitTests/Engine/Positions/EngineIlluminationTests.swift',
        ]:
            with self.subTest(owner='planetary-events', dependency=dependency):
                self.assertIn(dependency, inventory['planetary-events'])

    def test_rebound_document_allows_only_binding_map_changes(self):
        dependencies.verify_rebound_document({'sourceHashes': {'old': 'digest'}, 'rows': [1]}, {'sourceHashes': {'new': 'digest'}, 'rows': [1]}, 'sourceHashes')
        with self.assertRaisesRegex(ValueError, 'scientific or measured payload'):
            dependencies.verify_rebound_document({'sourceHashes': {}, 'rows': [1]}, {'sourceHashes': {}, 'rows': [2]}, 'sourceHashes')

    def test_inventory_rejects_omitted_owner_and_recorder(self):
        omitted_owner = self.document()
        del omitted_owner['owners']['transits']
        with self.assertRaisesRegex(ValueError, 'owner inventory differs'):
            dependencies.validate_inventory(omitted_owner)
        omitted_recorder = self.document()
        omitted_recorder['owners']['transits']['paths'].remove('Scripts/record-transit-evidence.py')
        with self.assertRaisesRegex(ValueError, 'omits its recorder'):
            dependencies.validate_inventory(omitted_recorder)

    def test_inventory_rejects_missing_malformed_and_duplicate_paths(self):
        mutations = []
        missing = self.document()
        missing['owners']['transits']['paths'][0] = 'Scripts/does-not-exist'
        mutations.append((missing, 'paths are missing'))
        malformed = self.document()
        malformed['owners']['transits']['paths'][0] = '../outside'
        mutations.append((malformed, 'malformed path'))
        duplicate = self.document()
        duplicate['owners']['transits']['paths'].append(duplicate['owners']['transits']['paths'][0])
        mutations.append((duplicate, 'contains duplicates'))
        overlap = self.document()
        overlap['owners']['transits']['paths'].append(overlap['groups']['binding']['paths'][0])
        mutations.append((overlap, 'expands to duplicate paths'))
        for document, message in mutations:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                dependencies.validate_inventory(document)

    def test_inventory_rejects_unknown_groups_omitted_coverage_and_malformed_json(self):
        unknown = self.document()
        unknown['owners']['transits']['groups'].append('unknown')
        with self.assertRaisesRegex(ValueError, 'unknown groups'):
            dependencies.validate_inventory(unknown)
        omitted = self.document()
        omitted['owners']['global-solar']['groups'].remove('engine-eclipses')
        with self.assertRaisesRegex(ValueError, 'required ownership coverage differs'):
            dependencies.validate_inventory(omitted)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.json'
            path.write_text('{')
            with self.assertRaisesRegex(ValueError, 'unreadable'):
                dependencies.load_inventory(inventory_path=path)
            path.write_text('{"schemaVersion": 1, "schemaVersion": 1, "groups": {}, "owners": {}}')
            with self.assertRaisesRegex(ValueError, 'duplicate key'):
                dependencies.load_inventory(inventory_path=path)


if __name__ == '__main__':
    unittest.main()
