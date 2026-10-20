"""Mutation controls for the original-component precision replay."""
import base64
import copy
import importlib.util
import json
import hashlib
import io
import shutil
import struct
import sys
import tempfile
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock
from pathlib import Path
import unittest

SPEC=importlib.util.spec_from_file_location('qualification_full',Path(__file__).with_name('qualify-moon-de441-full.py'))
q=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(q)


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.evidence=json.loads(q.OUTPUT.read_text())

    def test_saved_measurements_replay(self):
        self.assertEqual(q.calculate(self.evidence['rows']),self.evidence['measurements'])

    def test_storage_document_records_verified_mapped_resources_without_relabelling_measurements(self):
        previous=json.loads(q.STORAGE.read_text())
        result=q.storage_document(previous)
        q.check_storage_sources(result)
        self.assertEqual(2,result['schemaVersion'])
        self.assertEqual(q.full.COUNT*312,result['resourcePayloadBytes'])
        self.assertNotIn('derivedPayloadBytes',result)
        for key in ['captureBaseRevision','finalDebug','finalRelease','releaseMeasurement','releaseMeasurementProcess']:
            self.assertEqual(previous[key],result[key])

    def test_storage_snapshot_rejects_corrupt_mapped_chunk(self):
        with tempfile.TemporaryDirectory() as directory:
            resources=Path(directory)
            names=[f'{q.full.RESOURCE_PREFIX}{index:03}.bin' for index in range((q.full.COUNT+q.full.CHUNK-1)//q.full.CHUNK)]
            for name in names:
                (resources/name).symlink_to(q.RESOURCE_DIRECTORY/name)
            target=resources/names[0]
            target.unlink()
            shutil.copyfile(q.RESOURCE_DIRECTORY/names[0],target)
            data=bytearray(target.read_bytes());data[0]^=1;target.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'digest differs'):
                q.storage_snapshot(resources)

    def test_storage_snapshot_rejects_extra_mapped_chunk(self):
        with tempfile.TemporaryDirectory() as directory:
            resources=Path(directory)
            for index in range((q.full.COUNT+q.full.CHUNK-1)//q.full.CHUNK):
                name=f'{q.full.RESOURCE_PREFIX}{index:03}.bin'
                (resources/name).symlink_to(q.RESOURCE_DIRECTORY/name)
            (resources/f'{q.full.RESOURCE_PREFIX}extra.bin').write_bytes(b'extra')
            with self.assertRaisesRegex(ValueError,'inventory differs'):
                q.storage_snapshot(resources)

    def test_storage_guard_binds_package_and_runtime_loader(self):
        candidate=q.storage_document(json.loads(q.STORAGE.read_text()))
        original=Path.read_bytes
        for target in [q.ROOT/'Package.swift',q.ROOT/'Sources/AstronomyKit/Engine/Foundation/EngineMappedResource.swift']:
            with self.subTest(path=target):
                def changed(path,*args,**kwargs):
                    data=original(path,*args,**kwargs)
                    return data+b'\n' if path==target else data
                with mock.patch.object(Path,'read_bytes',changed),self.assertRaisesRegex(ValueError,'source bindings'):
                    q.check_storage_sources(candidate)

    def test_original_component_mutation_rejected(self):
        rows=copy.deepcopy(self.evidence['rows']);raw=bytearray(base64.b64decode(rows[0]['moonRecordBase64']));raw[23]^=1
        rows[0]['moonRecordBase64']=base64.b64encode(raw).decode()
        with self.assertRaises(ValueError):q.calculate(rows)

    def test_midpoint_and_derived_digest_mutations_rejected(self):
        for field,value in [('midpointSecondsTDB',0),('derivedSHA256','0'*64)]:
            rows=copy.deepcopy(self.evidence['rows']);rows[0][field]=value
            with self.assertRaises(ValueError):q.calculate(rows)

    def run_source_verification(self, candidate):
        # Rebind the ordinary arithmetic/source receipt so the control reaches source verification.
        candidate['measurements']=q.calculate(candidate['rows'])
        candidate['sourceHashes']={p:hashlib.sha256((q.ROOT/p).read_bytes()).hexdigest() for p in q.COMPONENT_BINDINGS}
        original_read=Path.read_text
        def read_text(path,*args,**kwargs):
            return json.dumps(candidate) if path==q.OUTPUT else original_read(path,*args,**kwargs)
        source_ranges={}
        for row in self.evidence['rows']:
            for key,field in zip(row['orderedRanges'],('moonRecordBase64','earthRecordBase64')):
                lo,hi=map(int,key.split('-'))
                data=source_ranges.setdefault((lo,hi-lo+1),bytearray(hi-lo+1))
                offset=row['byteOffsetInRanges'];data[offset:offset+328]=base64.b64decode(row[field])
        reads=[]
        reader=SimpleNamespace(read=lambda start,count: reads.append((start,count)) or bytes(source_ranges[(start,count)]))
        pairs=[]
        for row,count in [(self.evidence['rows'][0],362472),(self.evidence['rows'][3],368029)]:
            first=row['sourceRecordIndex']; starts=[int(key.split('-')[0]) for key in row['orderedRanges']]
            components=[SimpleNamespace(first_word=start//8+1-first*41) for start in starts]
            metadata=SimpleNamespace(start_jd_tdb=2451545+row['midpointSecondsTDB']/86400-2-first*4)
            pairs.append((*components,metadata,{'firstRecord':first,'recordCount':count}))
        with mock.patch.object(Path,'read_text',read_text),mock.patch.object(q,'check_storage_sources'),mock.patch.object(q.full.q,'CachedReader',return_value=reader),mock.patch.object(q.full.q,'layout',return_value=pairs),mock.patch.object(sys,'argv',['qualify','--verify-source']),redirect_stdout(io.StringIO()):
            q.main()
        return reads

    def alter_component(self, candidate, field):
        for row in candidate['rows']:
            values=list(struct.unpack('<41d',base64.b64decode(row[field])));values[2]+=1
            row[field]=base64.b64encode(struct.pack('<41d',*values)).decode()
            moon,earth=[struct.unpack('<41d',base64.b64decode(row[k])) for k in ('moonRecordBase64','earthRecordBase64')]
            row['derivedSHA256']=hashlib.sha256(q.full.compose(moon,earth,row['midpointSecondsTDB'])).hexdigest()

    def test_source_verification_reads_both_components_of_all_nine_samples(self):
        self.assertEqual(len(self.run_source_verification(copy.deepcopy(self.evidence))),18)

    def test_rebound_component_digest_still_requires_original_source_bytes(self):
        for field in ('moonRecordBase64','earthRecordBase64'):
            with self.subTest(field=field):
                candidate=copy.deepcopy(self.evidence);self.alter_component(candidate,field)
                with self.assertRaisesRegex(ValueError,'original source bytes'):self.run_source_verification(candidate)

    def test_source_verification_rejects_missing_extra_or_duplicate_samples(self):
        original=self.evidence['rows']
        for rows in [[],original[:-1],original+[original[0]],[original[0]]*9,original[::-1]]:
            with self.subTest(count=len(rows)):
                candidate=copy.deepcopy(self.evidence);candidate['rows']=copy.deepcopy(rows)
                with self.assertRaises(ValueError):self.run_source_verification(candidate)

    def test_source_verification_rejects_truncated_or_extended_range_pairs(self):
        for count in [0,1,3]:
            with self.subTest(count=count):
                candidate=copy.deepcopy(self.evidence)
                for row in candidate['rows']:
                    row['orderedRanges']=row['orderedRanges'][:count] if count<2 else row['orderedRanges']+['not-a-range']
                if count<2:self.alter_component(candidate,'moonRecordBase64' if count==0 else 'earthRecordBase64')
                with self.assertRaises(ValueError):self.run_source_verification(candidate)

    def test_source_verification_rejects_wrong_component_roles_and_sample_identity(self):
        for mutation in ['duplicate-range','reverse-ranges','index','offset','midpoint','missing-pin','extra-pin']:
            with self.subTest(mutation=mutation):
                candidate=copy.deepcopy(self.evidence);row=candidate['rows'][0]
                if mutation=='duplicate-range':
                    row['orderedRanges'][1]=row['orderedRanges'][0];row['earthRecordBase64']=row['moonRecordBase64'];row['derivedSHA256']=hashlib.sha256(bytes(312)).hexdigest()
                elif mutation=='reverse-ranges':
                    row['orderedRanges'].reverse();row['moonRecordBase64'],row['earthRecordBase64']=row['earthRecordBase64'],row['moonRecordBase64']
                    moon,earth=[struct.unpack('<41d',base64.b64decode(row[k])) for k in ('moonRecordBase64','earthRecordBase64')]
                    row['derivedSHA256']=hashlib.sha256(q.full.compose(moon,earth,row['midpointSecondsTDB'])).hexdigest()
                elif mutation=='index':row['sourceRecordIndex']+=1
                elif mutation=='offset':row['byteOffsetInRanges']+=328
                elif mutation=='midpoint':row['midpointSecondsTDB']+=345600
                elif mutation=='missing-pin':row['rangeHashes'].pop(row['orderedRanges'][0])
                else:row['rangeHashes'][self.evidence['rows'][3]['orderedRanges'][0]]=self.evidence['rows'][3]['rangeHashes'][self.evidence['rows'][3]['orderedRanges'][0]]
                with self.assertRaises(ValueError):self.run_source_verification(candidate)


if __name__=='__main__':unittest.main()
