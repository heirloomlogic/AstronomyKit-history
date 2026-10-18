#!/usr/bin/env python3
"""Replay global-solar source relations and bind native observations to their inputs."""
import argparse
import datetime
import importlib.util
import json
import math
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'Scripts/eclipse-data'
CAPTURE = DATA/'global-captures.json'
OUTPUT = DATA/'global-evidence.json'


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT/'Scripts'/filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

lunar = load_module('lunar_evidence', 'record-eclipse-event-evidence.py')
archive = load_module('global_archive', 'capture-global-solar.py')
radii = load_module('global_radii', 'assess-global-solar-radii.py')
dependencies = load_module('global_dependencies', 'evidence_dependencies.py')


def hashes(capture_bytes=None):
    overrides = None if capture_bytes is None else {str(CAPTURE.relative_to(ROOT)): capture_bytes}
    return dependencies.source_hashes('global-solar', overrides=overrides)


def references():
    result = {}
    for row in json.loads((ROOT/'Tests/AstronomyKitTests/Fixtures/IndependentReferences/reference-fixtures.json').read_bytes())['globalSolarEclipses']:
        date = datetime.datetime.fromisoformat(row['terrestrialTime'].removesuffix('Z'))
        result[row['terrestrialTime']] = {'tt': (date-datetime.datetime(2000,1,1,12)).total_seconds()/86400, 'kindAtPeak': row['kind'], 'latitude': row['latitudeDegrees'], 'longitude': row['longitudeDegrees'], 'timeToleranceSeconds': row['timeToleranceSeconds'], 'locationToleranceDegrees': row['locationToleranceDegrees']}
    for row in json.loads(archive.OUTPUT.read_bytes())['events']: result[row['date']] = row
    return result


def angle(lat1, lon1, lat2, lon2):
    r = math.pi/180
    a = math.sin((lat1-lat2)*r/2)**2 + math.cos(lat1*r)*math.cos(lat2*r)*math.sin((lon1-lon2)*r/2)**2
    return 2*math.asin(math.sqrt(min(1,max(0,a))))/r


def evidence_matches(first, second, path=()):
    """Compare replayed evidence, allowing the measured one-ULP libm location difference."""
    if type(first) is not type(second):
        return False
    if isinstance(first, dict):
        return first.keys() == second.keys() and all(
            evidence_matches(first[key], second[key], path + (key,)) for key in first)
    if isinstance(first, list):
        return len(first) == len(second) and all(
            evidence_matches(a, b, path + (index,)) for index, (a, b) in enumerate(zip(first, second)))
    if isinstance(first, float):
        if not math.isfinite(first) or not math.isfinite(second):
            return False
        # This derived angle differs by one ULP between macOS and Linux libm. Source hashes, source values,
        # captures, time residuals, identities and scientific criteria remain exact.
        if len(path) == 3 and path[0] == 'residuals' and isinstance(path[1], int) and path[2] == 'locationDegrees':
            return first == second or math.nextafter(first, second) == second
    return first == second


def validate(rows):
    refs = references()
    if len(rows)!=len(refs) or {r['id'] for r in rows}!=set(refs): raise ValueError('event identities')
    residuals=[]
    for row in rows:
        expected = refs[row['id']]
        if set(row) != {'id','sourceTT','tt','ut','kind','distanceKm','physicalTT','obscuration','latitude','longitude'}: raise ValueError('event schema')
        if row['kind']!=expected['kindAtPeak'] or row['sourceTT']!=expected['tt']: raise ValueError('event source identity')
        if row['physicalTT']!=row['tt'] or row['distanceKm']<0: raise ValueError('physical peak/distance')
        date = datetime.datetime(2000,1,1,12)+datetime.timedelta(days=row['ut'])
        expected_tt = lunar.source_time_tt(date.isoformat())
        if abs(expected_tt-row['tt']) > 16*max(math.ulp(row['tt']),1e-12): raise ValueError('TT/UT relation')
        residual=abs(row['tt']-expected['tt'])*86400
        if residual>expected['timeToleranceSeconds']: raise ValueError('source peak')
        location=None
        if row['kind']=='partial':
            if any(row[k] is not None for k in ('obscuration','latitude','longitude')): raise ValueError('partial optionals')
        else:
            if not -90<=row['latitude']<=90 or not -180<row['longitude']<=180: raise ValueError('coordinates')
            if row['kind']=='total' and row['obscuration']!=1: raise ValueError('total area')
            if row['kind']=='annular' and not 0<row['obscuration']<1: raise ValueError('annular area')
            location=angle(row['latitude'],row['longitude'],expected['latitude'],expected['longitude'])
            if location>expected['locationToleranceDegrees']: raise ValueError('source location')
        residuals.append({'id':row['id'],'peakSeconds':residual,'locationDegrees':location})
    return residuals


def validate_area(rows):
    report=json.loads(archive.OUTPUT.read_bytes())['rp1301']
    if len(rows)!=3: raise ValueError('area sample count')
    for i,row in enumerate(rows):
        if set(row)!={'tt','modelUT','sourceUT','sourceDeltaTSeconds','deltaTModel','obscuration','sunRadiusRadians','moonRadiusRadians','separationRadians'}: raise ValueError('area schema')
        if row['deltaTModel']!='espenakMeeus': raise ValueError('area geometry model')
        date=datetime.datetime(2000,1,1,12)+datetime.timedelta(days=row['modelUT'])
        if abs(lunar.source_time_tt(date.isoformat())-row['tt'])>16*max(math.ulp(row['tt']),1e-12): raise ValueError('area model time relation')
        sr,mr,sep=row['sunRadiusRadians'],row['moonRadiusRadians'],row['separationRadians']
        if not 0<mr<sr or not 0<=sep<1e-12: raise ValueError('annular concentric geometry')
        if abs(row['obscuration']-(mr/sr)**2)>2e-14: raise ValueError('area is not diameter fraction')
        if i<2:
            sample=report['samples'][i]
            if row['tt']!=sample['tt'] or row['sourceUT']!=sample['ut'] or row['sourceDeltaTSeconds']!=report['deltaTSeconds']: raise ValueError('source area epoch')
            if row['tt']!=row['sourceUT']+row['sourceDeltaTSeconds']/86400: raise ValueError('source UT to geometry TT')
            if not sample['lower']<=row['obscuration']<=sample['upper']: raise ValueError('published area')
        elif row['tt']!=report['greatestTT']:
            raise ValueError('G0 epoch')
        elif row['sourceUT'] is not None or row['sourceDeltaTSeconds'] is not None:
            raise ValueError('G0 has a source TT, not a Table 4 UT observation')
    return {'nativeG0PhysicalArea':rows[2]['obscuration'], 'sourceG0SquaredMagnitudeInterval':[report['ratioLower']**2,report['ratioUpper']**2], 'g0PhysicalAreaInsideSquaredMagnitudeInterval':report['ratioLower']**2<=rows[2]['obscuration']<=report['ratioUpper']**2, 'g0PhysicalAreaResidualFromSquaredMagnitude':rows[2]['obscuration']-report['greatestMagnitude']**2, 'g0PhysicalAreaResidualBelowSquaredMagnitudeInterval':min(0,rows[2]['obscuration']-report['ratioLower']**2), 'directTable4SamplesQualified':2}


def evidence(captures, bindings):
    source_references=archive.build({name:(archive.SOURCE/name).read_bytes() for name in archive.SOURCES}, {name:json.loads((archive.SOURCE/(name+'.query.json')).read_bytes()) for name in archive.SOURCES}, archive.CATALOG.read_bytes())
    if source_references!=json.loads(archive.OUTPUT.read_bytes()): raise ValueError('global source references differ')
    if not lunar.finite(captures): raise ValueError('nonfinite captures')
    for config in ['debug','release']:
        validate(captures[config]['published']);validate_area(captures[config]['area'])
    if not lunar.near(captures['debug'],captures['release']): raise ValueError('Debug/Release disagreement')
    r=captures['resources']
    if set(r)!={'coldSeconds','nextSeconds','nextCount','peakBeforeBytes','peakAfterColdBytes','peakAfterWorkloadBytes','checksum','host'}: raise ValueError('resource schema')
    if r['coldSeconds']<0 or r['nextSeconds']<0 or r['nextCount']!=99 or not r['host']: raise ValueError('resource observations')
    if not 0<=r['peakBeforeBytes']<=r['peakAfterColdBytes']<=r['peakAfterWorkloadBytes']: raise ValueError('RSS order')
    if not __import__('re').fullmatch('[0-9a-f]{40}',captures['runtimeBaseRevision']) or not captures['toolchain']: raise ValueError('runtime metadata')
    if set(captures['releaseObjectBytes'])!={'EngineGlobalSolarEvents.o','EngineGeoidIntersection.o'} or captures['releaseExecutableBytes']<=0 or any(v<=0 for v in captures['releaseObjectBytes'].values()): raise ValueError('binary sizes')
    comparison=radii.build(json.loads((DATA/'radius-vectors.json').read_bytes()))
    if comparison != json.loads((DATA/'radius-comparison.json').read_bytes()): raise ValueError('radius comparison')
    source_boundary=source_references['boundary1986']
    boundary=next(r for r in comparison if r['tt']==source_boundary['tt'] and r['case']=='k2-959.63')
    builds={c:lunar.build_seconds(captures['buildReceipts'][c]) for c in ['debug','release']}
    if any(not math.isfinite(v) or v<0 for v in builds.values()):raise ValueError('build duration')
    return {'schemaVersion':1,'runtimeBaseRevision':captures['runtimeBaseRevision'],'sourceHashes':bindings,'toolchain':captures['toolchain'],'residuals':validate(captures['release']['published']),'annularArea':validate_area(captures['release']['area']),'boundary1986':{'source':source_boundary,'sourcePathType':source_boundary['pathType'],'sourcePrintedMagnitude':source_boundary['magnitude'],'smoothDiscAtSourceEpoch':boundary,'qualification':'diagnostic only; rounded magnitude does not resolve kind; observed beaded-annular limb not modeled'},'resources':r,'buildSeconds':builds,'releaseObjectBytes':captures['releaseObjectBytes'],'releaseExecutableBytes':captures['releaseExecutableBytes'],'limitations':'Sampled native geometry and published events, which the public facade uses since the #96 cutover. RP1301 direct Table 4 areas pass conditional rounding intervals. G0 is a mixed-k Besselian magnitude, so its square is retained only as a diagnostic beside physical single-radius area. No radius was fitted. Host costs are observations, not portable gates.'}


def capture(directory):
    directory=Path(directory)
    objects=ROOT/'.build/out/Intermediates.noindex/AstronomyKit.build/Release/AstronomyKit-t.build/Objects-normal/arm64'
    executable=ROOT/'.build/out/Products/Release/AstronomyKitTests.xctest/Contents/MacOS/AstronomyKitTests'
    return {**{c:{name:json.loads((directory/c/(name+'.json')).read_bytes()) for name in ['published','area']} for c in ['debug','release']},'resources':json.loads((directory/'resources/resources.json').read_bytes()),'buildReceipts':{c:__import__('re').search(r'Build complete! \([^\n]+',(directory/f'full-{c}.log').read_text()).group(0) for c in ['debug','release']},'runtimeBaseRevision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'toolchain':subprocess.check_output(['swift','--version'],text=True).strip(),'releaseExecutableBytes':executable.stat().st_size,'releaseObjectBytes':{name:(objects/name).stat().st_size for name in ['EngineGlobalSolarEvents.o','EngineGeoidIntersection.o']}}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--capture',type=Path);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    if args.capture and args.check:parser.error('capture and check are exclusive')
    values=capture(args.capture) if args.capture else json.loads(CAPTURE.read_bytes())
    data=archive.encoded(values)
    result=archive.encoded(evidence(values,hashes(data if args.capture else None)))
    if args.check:
        if not evidence_matches(json.loads(OUTPUT.read_bytes()), json.loads(result)):raise SystemExit('global solar evidence differs')
    else:
        if not args.capture:
            previous=json.loads(OUTPUT.read_bytes());candidate=json.loads(result)
            dependencies.verify_retained_inputs('global-solar',previous['sourceHashes'],capture_revision=values['runtimeBaseRevision'])
            dependencies.verify_rebound_document(previous,candidate,'sourceHashes')
        archive.publish({**({CAPTURE: data} if args.capture else {}), OUTPUT: result})
    print('global solar evidence and recorded relations match')

if __name__=='__main__':main()
