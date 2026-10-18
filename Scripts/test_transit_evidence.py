import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'Scripts'/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
archive=load('transit_archive_test','capture-transit-references.py')
recorder=load('transit_record_test','record-transit-evidence.py')

class TransitSourceTests(unittest.TestCase):
    def setUp(self):self.blobs={n:(archive.SOURCE/n).read_bytes() for n in archive.SOURCES}

    def test_replay_and_source_observables(self):
        result=archive.build(self.blobs)
        self.assertEqual(archive.shared.encoded(result),archive.OUTPUT.read_bytes())
        self.assertEqual([r['date'] for r in result['transitSequences']['venus']],['2012-06-06','2117-12-11','2125-12-08'])
        self.assertEqual(result['danjonContacts'][2]['penumbralBeginUT'],'08:27:35')
        self.assertEqual(result['danjonContacts'][2]['penumbralEndUT'],'12:31:07')
        self.assertNotEqual(result['lunarSequence'][2]['contactsUT']['penumbralBegin'],result['danjonContacts'][2]['contactsUT']['penumbralBegin'])

    def test_source_semantics_reject_refreshed_wrong_content(self):
        mutations=[('mercury.html',b'geocentric Universal Time',b'geocentric Terrestrial Time'),('venus.html',b'closest to the center of the Sun as seen from the center of Earth',b'closest to shadow axis'),('mercury.html',b'2006 Nov 08',b'2007 Nov 08'),('nasa-oh2001.html',b'enlarged by 2%',b'enlarged by 3%'),('solar_2001.html',b'2024 Oct 02',b'2024 Oct 03'),('solar_2001.html',b'TD of',b'UT of')]
        for name,old,new in mutations:
            with self.subTest(name=name):
                self.assertIn(old,self.blobs[name]);blobs=dict(self.blobs);blobs[name]=blobs[name].replace(old,new)
                digests=dict(archive.DIGESTS);digests[name]=hashlib.sha256(blobs[name]).hexdigest()
                with mock.patch.dict(archive.DIGESTS,digests,clear=True),self.assertRaises(ValueError):archive.build(blobs)

    def test_radius_units_values_recipes_and_digest(self):
        blobs={b:(archive.RADIUS_SOURCE/(b+'fact.html')).read_bytes() for b in archive.RADII}
        recipes={b:json.loads((archive.RADIUS_SOURCE/(b+'fact.html.query.json')).read_bytes()) for b in archive.RADII}
        for body in blobs:
            for field in recipes[body]:
                wrong=copy.deepcopy(recipes);wrong[body][field]='wrong'
                with self.assertRaises(ValueError):archive.radius_conventions(blobs,wrong)
            wrong=dict(blobs);wrong[body]=wrong[body].replace(b'Volumetric mean radius (km)',b'Equatorial radius (m)')
            self.assertNotEqual(wrong[body],blobs[body]);radii=dict(archive.RADII);radii[body]=(hashlib.sha256(wrong[body]).hexdigest(),radii[body][1]);updated=copy.deepcopy(recipes);updated[body]['sha256']=radii[body][0]
            with mock.patch.dict(archive.RADII,radii,clear=True),self.assertRaises(ValueError):archive.radius_conventions(wrong,updated)

    def test_manual_diagrams_require_reviewed_transcription_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            for source in archive.RADIUS_SOURCE.iterdir():
                if source.is_file(): (p/source.name).write_bytes(source.read_bytes())
            with mock.patch.object(archive,'RADIUS_SOURCE',p):
                self.assertEqual(len(archive.diagram_contacts()),3)
                transcript=p/'lunar-diagram-transcription.json';old=transcript.read_bytes();transcript.write_bytes(old.replace(b'08:27:35',b'08:28:35'))
                with self.assertRaises(ValueError):archive.diagram_contacts()
                transcript.write_bytes(old)
                pdf=p/'LE2001Dec30N.pdf';pdf.write_bytes(pdf.read_bytes()+b'changed')
                with self.assertRaises(ValueError):archive.diagram_contacts()

class TransitEvidenceTests(unittest.TestCase):
    def setUp(self):self.values=json.loads(recorder.CAPTURE.read_bytes())

    def test_every_recorded_section_and_binding_replays(self):
        self.assertEqual(archive.shared.encoded(recorder.evidence(self.values,recorder.hashes())),recorder.OUTPUT.read_bytes())
        bindings=recorder.hashes()
        for relative in ['Sources/AstronomyKit/Transit.swift','Sources/AstronomyKit/CelestialBody.swift','Sources/AstronomyKit/CivilTime.swift','Sources/AstronomyKit/UTCOffsetTable.swift','Sources/CLibAstronomy/astronomy.c','Tests/AstronomyKitTests/AuditValidationTests.swift','Tests/AstronomyKitTests/IndependentReferenceFixtures.swift','Scripts/reference-data/build-fixtures.py']:
            self.assertIn(relative,bindings)
        for relative in ['Sources/AstronomyKit/Engine/Eclipses/EngineTransitEvents.swift','Sources/AstronomyKit/Engine/Events/EngineLunarEvents.swift','Sources/AstronomyKit/Engine/Positions/EngineApparentPlace.swift','Sources/AstronomyKit/Engine/Moon/Generated/TDBTerms.swift']:
            self.assertIn(relative,bindings)
        for unrelated in ['Sources/AstronomyKit/Engine/Bodies/EngineJupiterMoonsJup365.swift','Sources/AstronomyKit/Engine/Stars/EngineStar.swift','Sources/AstronomyKit/Engine/Gravity/EngineChiron.swift']:
            self.assertNotIn(unrelated,bindings)
        contacts=recorder.evidence(self.values,bindings)['sequences']['penumbralContacts']
        self.assertEqual(contacts[2]['oh2001Within120Seconds'],{'penumbralBegin':False,'penumbralEnd':False})

    def test_objective_time_identity_contact_and_separation_relations(self):
        mutations=[('published',0,'sourceUT',1),('published',0,'peakUT',1),('published',0,'peakTT',1),('published',0,'startUT',1),('published',0,'separation',1),('published',0,'publicUTResidualSeconds',1),('published',0,'formerUTCReferenceUT',1),('transit-sequence',1,'tt',1),('transit-sequence',1,'date','wrong'),('lunar-sequence',0,'ingressUT',1),('lunar-sequence',0,'semiDurationMinutes',1),('global-sequence',0,'ut',1),('global-sequence',0,'kind','wrong')]
        for section,index,field,delta in mutations:
            with self.subTest(section=section,field=field):
                values=copy.deepcopy(self.values);row=values['debug'][section][index];row[field]=row[field]+delta if isinstance(delta,int) else delta
                with self.assertRaises(ValueError):recorder.evidence(values,{})
                values['release']=copy.deepcopy(values['debug'])
                with self.assertRaises(ValueError):recorder.evidence(values,{})

    def test_missing_extra_nonfinite_and_build_observations(self):
        for section in recorder.SECTIONS:
            values=copy.deepcopy(self.values);del values['debug'][section]
            with self.assertRaises(ValueError):recorder.evidence(values,{})
        for mutate in [lambda c:c['resources'].update(nextCount=0),lambda c:c['resources'].update(coldSeconds=-1),lambda c:c.update(runtimeBaseRevision='wrong'),lambda c:c.update(releaseExecutableBytes=0),lambda c:c['buildReceipts'].update(debug='not a build'),lambda c:c['debug']['published'][0].update(separation=float('nan'))]:
            values=copy.deepcopy(self.values);mutate(values)
            with self.assertRaises((ValueError,RuntimeError,AttributeError)):recorder.evidence(values,{})

    def test_two_file_ordinary_publish_error_restores_set(self):
        real_replace=os.replace
        for fail_at in [1,2]:
            with tempfile.TemporaryDirectory() as tmp:
                paths=[Path(tmp)/'captures',Path(tmp)/'evidence'];paths[0].write_bytes(b'old-capture');paths[1].write_bytes(b'old-evidence');count=0
                def replace(a,b):
                    nonlocal count
                    count+=1
                    if count==fail_at:raise OSError('injected publication failure')
                    return real_replace(a,b)
                with mock.patch.object(archive.shared.os,'replace',side_effect=replace),self.assertRaises(OSError):archive.shared.publish({p:b'new' for p in paths})
                self.assertEqual([p.read_bytes() for p in paths],[b'old-capture',b'old-evidence'])

if __name__=='__main__':unittest.main()
