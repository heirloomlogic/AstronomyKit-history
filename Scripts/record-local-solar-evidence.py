#!/usr/bin/env python3
"""Validate local event/source relations and bind actual native captures to their inputs."""
import argparse
import datetime
import importlib.util
import json
import math
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'Scripts/eclipse-data'
CAPTURE=DATA/'local-captures.json'
OUTPUT=DATA/'local-evidence.json'

def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'Scripts'/file)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
archive=load('local_source','capture-local-solar.py')
lunar=load('lunar_binding','record-eclipse-event-evidence.py')
dependencies=load('local_dependencies','evidence_dependencies.py')
EPOCH=datetime.datetime(2000,1,1,12)


def native_delta_t_days(ut):
    """Delta T in days at modeled UT1 `ut`, under the engine's Espenak-Meeus pieces and decimal year."""
    text=(EPOCH+datetime.timedelta(days=ut)).isoformat()
    rounded=(datetime.datetime.fromisoformat(text)-EPOCH).total_seconds()/86400
    return lunar.source_time_tt(text)-rounded


def hashes(capture_bytes=None):
    overrides=None if capture_bytes is None else {str(CAPTURE.relative_to(ROOT)):capture_bytes}
    return dependencies.source_hashes('local-solar',overrides=overrides)


def model_tt(ut):
    return lunar.source_time_tt((EPOCH+datetime.timedelta(days=ut)).isoformat())


def time_relation(tt,ut):
    if abs(tt-model_tt(ut))>32*max(math.ulp(tt),1e-12):raise ValueError('model TT/UT relation')


def overlap(sr,mr,d):
    if sr<=0 or mr<=0 or d<0:raise ValueError('angular geometry')
    if d>=sr+mr:return 0.0
    if d<=abs(sr-mr):return min(1,(mr/sr)**2)
    a=math.acos(max(-1,min(1,(d*d+sr*sr-mr*mr)/(2*d*sr))))
    b=math.acos(max(-1,min(1,(d*d+mr*mr-sr*sr)/(2*d*mr))))
    area=sr*sr*a+mr*mr*b-.5*math.sqrt(max(0,(-d+sr+mr)*(d+sr-mr)*(d-sr+mr)*(d+sr+mr)))
    return area/(math.pi*sr*sr)


def fraction(value,kind):
    if not 0<=value<=1 or (kind=='total' and value!=1) or (kind=='annular' and value>=1):raise ValueError('disc area/kind')


def published(rows):
    refs=json.loads((ROOT/'Tests/AstronomyKitTests/Fixtures/IndependentReferences/reference-fixtures.json').read_bytes())['localSolarEclipses']
    if len(rows)!=len(refs):raise ValueError('published count')
    residuals=[]
    for row,source in zip(rows,refs):
        if set(row)!={'latitude','longitude','kind','obscuration','physicalTT','contacts'}:raise ValueError('published schema')
        if (row['latitude'],row['longitude'],row['kind'])!=(source['latitudeDegrees'],source['longitudeDegrees'],source['kind']):raise ValueError('source observer/kind')
        fraction(row['obscuration'],row['kind'])
        names=[n for n in ['partialBegin','totalBegin','peak','totalEnd','partialEnd'] if source.get(n+'UTC') is not None]
        if [r['name'] for r in row['contacts']]!=names:raise ValueError('contact presence/order')
        for c in row['contacts']:
            if set(c)!={'name','source','sourceUT','ut','tt','altitude','formerUTCResidualSeconds'}:raise ValueError('contact schema')
            name=c['name'];text=source[name+'UTC'];ut=archive.shared.tt(text.removesuffix('Z'))
            if c['source']!=text or c['sourceUT']!=ut:raise ValueError('published UT1 source')
            time_relation(c['tt'],c['ut'])
            seconds=(c['ut']-ut)*86400;altitude=c['altitude']-source[name+'AltitudeDegrees']
            if abs(seconds)>source['timeToleranceSeconds'] or abs(altitude)>source['altitudeToleranceDegrees']:raise ValueError('published contact accuracy')
            # Former helper interpreted these modern calendar fields as UTC, fixing TT-UTC at 69.184 s; UT then follows
            # the engine's Delta T inverse, as the public AstroTime(Date) path does.
            old_tt=ut+69.184/86400;old_ut=ut
            for _ in range(4):
                old_ut=old_tt-native_delta_t_days(old_ut)
            if abs(c['formerUTCResidualSeconds']-(c['ut']-old_ut)*86400)>32*max(math.ulp(ut),1e-12)*86400:raise ValueError('former UTC diagnostic')
            if name=='peak' and row['physicalTT']!=c['tt']:raise ValueError('physical peak')
            residuals.append({'latitude':row['latitude'],'name':name,'seconds':seconds,'altitudeDegrees':altitude,'formerUTCSeconds':c['formerUTCResidualSeconds']})
        if not all(a['tt']<b['tt'] for a,b in zip(row['contacts'],row['contacts'][1:])):raise ValueError('physical ordering')
    return residuals


def report(rows,refs):
    if len(rows)!=len(refs['events']):raise ValueError('report count')
    residuals=[]
    for row,source in zip(rows,refs['events']):
        if set(row)!={'id','kind','contacts','obscuration','sourceEpochObscuration','sourceTT','modelUT','sourceUT','sunRadius','moonRadius','separation'}:raise ValueError('report schema')
        if row['id']!=source['id'] or row['kind']!=source['kind']:raise ValueError('report identity')
        fraction(row['obscuration'],row['kind'])
        if [c['name'] for c in row['contacts']]!=[c['name'] for c in source['contacts']]:raise ValueError('report contact presence')
        for c,expected in zip(row['contacts'],source['contacts']):
            if set(c)!={'name','sourceUT','sourceTT','ut','tt','altitude'}:raise ValueError('report contact schema')
            if c['sourceUT']!=expected['ut'] or c['sourceTT']!=expected['tt']:raise ValueError('report contact source')
            time_relation(c['tt'],c['ut'])
            seconds=(c['ut']-expected['ut'])*86400;altitude=c['altitude']-expected['altitude']
            if abs(seconds)>source['timeToleranceSeconds'] or abs(altitude)>source['altitudeToleranceDegrees']:raise ValueError('report contact accuracy')
            residuals.append({'id':row['id'],'name':c['name'],'seconds':seconds,'altitudeDegrees':altitude})
        if not all(a['tt']<b['tt'] for a,b in zip(row['contacts'],row['contacts'][1:])):raise ValueError('report ordering')
        peak=next(c for c in source['contacts'] if c['name']=='peak')
        if row['sourceTT']!=peak['tt'] or row['sourceUT']!=peak['ut'] or row['sourceTT']!=row['sourceUT']+refs['deltaTSeconds']/86400:raise ValueError('area source TT anchor')
        time_relation(row['sourceTT'],row['modelUT'])
        area=overlap(row['sunRadius'],row['moonRadius'],row['separation'])
        if abs(area-row['sourceEpochObscuration'])>2e-12:raise ValueError('area geometry relation')
        if not source['lower']<=area<=source['upper']:raise ValueError('published local area interval')
    return residuals


def sequence(rows,refs):
    expected=refs['sequence']['events']
    if len(rows)!=len(expected):raise ValueError('sequence count')
    for row,source in zip(rows,expected):
        if set(row)!={'date','ut','tt','kind','obscuration','altitude','gmtPeak'}:raise ValueError('sequence schema')
        if row['date']!=source['date'] or row['gmtPeak']!=source['gmtCalendarDays']['peak'] or row['kind']!=source['localKind']:raise ValueError('sequence source identity')
        time_relation(row['tt'],row['ut']);fraction(row['obscuration'],row['kind'])
        if math.floor(row['ut']+.5)!=math.floor(row['gmtPeak']+.5) or row['altitude']<=0:raise ValueError('visible calendar identity')
    if rows[1]['tt']<=rows[0]['tt']:raise ValueError('next progress')


def peak_definition(rows,refs):
    source=next(r for r in refs['events'] if r['id']=='Acapulco, MEXICO')
    ut=next(c['ut'] for c in source['contacts'] if c['name']=='peak')
    if len(rows)!=4 or [r['mode'] for r in rows]!=[0,1,2,3]:raise ValueError('definition modes')
    for r in rows:
        if set(r)!={'mode','sourceUT','ut','tt','residualSeconds','magnitude','area'}:raise ValueError('definition schema')
        if r['sourceUT']!=ut:raise ValueError('definition source epoch')
        time_relation(r['tt'],r['ut'])
        if r['residualSeconds']!=(r['ut']-ut)*86400:raise ValueError('definition residual relation')
        if not 0<r['magnitude']<1 or not 0<r['area']<1:raise ValueError('definition fractions')
    return {'sourceDefinition':refs['maximumDefinition'],'modes':['axis-distance minimum','diameter-fraction maximum','angular-separation minimum','area maximum'],'observations':rows,'diameterMaximumMinusAxisMinimumSeconds':(rows[1]['tt']-rows[0]['tt'])*86400,'scope':'Acapulco diagnostic only. The retained axis-distance peak approximates, but is not identical to, maximum occulted diameter. This small sampled difference does not explain the larger printed-source residual.'}


def evidence(captures,bindings):
    if set(captures)!={'debug','release','resources','buildReceipts','runtimeBaseRevision','toolchain','releaseExecutableBytes','releaseObjectBytes'}:raise ValueError('capture schema')
    refs=archive.build({n:(archive.SOURCE/n).read_bytes() for n in archive.SOURCES},{n:json.loads((archive.SOURCE/(n+'.query.json')).read_bytes()) for n in archive.SOURCES})
    if refs!=json.loads(archive.OUTPUT.read_bytes()):raise ValueError('reference replay')
    if not lunar.finite(captures):raise ValueError('nonfinite capture')
    for config in ['debug','release']:
        if set(captures[config])!={'published','report','sequence','peak-definition'}:raise ValueError('measurement sections')
        published(captures[config]['published']);report(captures[config]['report'],refs);sequence(captures[config]['sequence'],refs);peak_definition(captures[config]['peak-definition'],refs)
    if not lunar.near(captures['debug'],captures['release']):raise ValueError('configuration disagreement')
    resource=captures['resources']
    if set(resource)!={'coldSeconds','nextSeconds','nextCount','peakBeforeBytes','peakAfterColdBytes','peakAfterWorkloadBytes','checksum','host'}:raise ValueError('resource schema')
    if resource['coldSeconds']<0 or resource['nextSeconds']<0 or resource['nextCount']!=19 or not resource['host']:raise ValueError('resource observations')
    if not 0<resource['peakBeforeBytes']<=resource['peakAfterColdBytes']<=resource['peakAfterWorkloadBytes']:raise ValueError('RSS ordering')
    if not re.fullmatch('[0-9a-f]{40}',captures['runtimeBaseRevision']) or not captures['toolchain']:raise ValueError('runtime provenance')
    if captures['releaseExecutableBytes']<=0 or set(captures['releaseObjectBytes'])!={'EngineLocalSolarEvents.o'} or captures['releaseObjectBytes']['EngineLocalSolarEvents.o']<=0:raise ValueError('binary observations')
    builds={c:lunar.build_seconds(captures['buildReceipts'][c]) for c in ['debug','release']}
    if any(not math.isfinite(v) or v<0 for v in builds.values()):raise ValueError('build duration')
    return {'schemaVersion':1,'runtimeBaseRevision':captures['runtimeBaseRevision'],'sourceHashes':bindings,'toolchain':captures['toolchain'],'eclipseWiseContacts':published(captures['release']['published']),'rp1301Contacts':report(captures['release']['report'],refs),'localAreaSamples':[{'id':r['id'],'sourceEpochArea':r['sourceEpochObscuration'],'searchPeakArea':r['obscuration'],'interval':[s['lower'],s['upper']]} for r,s in zip(captures['release']['report'],refs['events'])],'sequence':captures['release']['sequence'],'peakDefinition':peak_definition(captures['release']['peak-definition'],refs),'centralMidpointDifferencesSeconds':{r['id']:((next(c['tt'] for c in r['contacts'] if c['name']=='totalBegin')+next(c['tt'] for c in r['contacts'] if c['name']=='totalEnd'))/2-next(c['tt'] for c in r['contacts'] if c['name']=='peak'))*86400 for r in captures['release']['report'] if r['kind']!='partial'},'resources':resource,'releaseObjectBytes':captures['releaseObjectBytes'],'releaseExecutableBytes':captures['releaseExecutableBytes'],'buildSeconds':builds,'limitations':'Native sampled local circumstances, which the public facade uses since the #96 cutover. EclipseWise original map timestamps are UT1 despite legacy UTC keys. RP1301 areas are direct printed local values with conditional rounding intervals; they do not resolve the finer global G0 ratio or 1986 limb qualifications. Washington proves consecutive visible calendar identities under a historical published model, not a modern timing/area allowance. Resource values are host observations, not portable gates.'}


def capture(directory):
    directory=Path(directory)
    objects=ROOT/'.build/out/Intermediates.noindex/AstronomyKit.build/Release/AstronomyKit-t.build/Objects-normal/arm64'
    executable=ROOT/'.build/out/Products/Release/AstronomyKitTests.xctest/Contents/MacOS/AstronomyKitTests'
    return {**{c:{n:json.loads((directory/c/(n+'.json')).read_bytes()) for n in ['published','report','sequence','peak-definition']} for c in ['debug','release']},'resources':json.loads((directory/'resources/resources.json').read_bytes()),'buildReceipts':{c:re.search(r'Build complete! \([^\n]+',(directory/f'full-{c}.log').read_text()).group(0) for c in ['debug','release']},'runtimeBaseRevision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'toolchain':subprocess.check_output(['swift','--version'],text=True).strip(),'releaseExecutableBytes':executable.stat().st_size,'releaseObjectBytes':{'EngineLocalSolarEvents.o':(objects/'EngineLocalSolarEvents.o').stat().st_size}}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--capture',type=Path);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    if args.capture and args.check:parser.error('capture and check are exclusive')
    values=capture(args.capture) if args.capture else json.loads(CAPTURE.read_bytes())
    data=archive.shared.encoded(values);result=archive.shared.encoded(evidence(values,hashes(data if args.capture else None)))
    if args.check:
        if OUTPUT.read_bytes()!=result:raise SystemExit('local solar evidence differs')
    else:
        if not args.capture:
            previous=json.loads(OUTPUT.read_bytes());candidate=json.loads(result)
            dependencies.verify_retained_inputs('local-solar',previous['sourceHashes'])
            dependencies.verify_rebound_document(previous,candidate,'sourceHashes')
        archive.shared.publish({**({CAPTURE:data} if args.capture else {}),OUTPUT:result})
    print('local solar evidence and all recorded relations match')

if __name__=='__main__':main()
