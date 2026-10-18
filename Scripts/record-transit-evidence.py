#!/usr/bin/env python3
"""Validate transit and remaining published eclipse evidence before publishing source bindings."""
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
CAPTURE=DATA/'transit-captures.json'
OUTPUT=DATA/'transit-evidence.json'
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'Scripts'/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
archive=load('transit_archive','capture-transit-references.py')
lunar=load('transit_lunar','record-eclipse-event-evidence.py')
dependencies=load('transit_dependencies','evidence_dependencies.py')
EPOCH=datetime.datetime(2000,1,1,12)
SECTIONS={'published','transit-sequence','lunar-sequence','global-sequence'}


def hashes(capture_bytes=None):
    overrides=None if capture_bytes is None else {str(CAPTURE.relative_to(ROOT)):capture_bytes}
    return dependencies.source_hashes('transits',overrides=overrides)


def relation(tt,ut):
    expected=lunar.source_time_tt((EPOCH+datetime.timedelta(days=ut)).isoformat())
    if abs(tt-expected)>32*max(math.ulp(tt),1e-12):raise ValueError('model TT/UT relation')


def native_delta_t_days(ut):
    """Delta T in days at modeled UT1 `ut`, under the engine's Espenak-Meeus pieces and decimal year."""
    text=(EPOCH+datetime.timedelta(days=ut)).isoformat()
    rounded=(datetime.datetime.fromisoformat(text)-EPOCH).total_seconds()/86400
    return lunar.source_time_tt(text)-rounded


def legacy_reference_ut(source,ut):
    # The former helper read the UT label as civil UTC: TT fixed by the leap-second offset of its year, UT from the
    # engine's Delta T inverse, which the public AstroTime(Date) path uses.
    year=int(source[:4]);offset=64.184 if year==2003 else 66.184 if year==2012 else 69.184
    tt=ut+offset/86400;value=ut
    for _ in range(4):
        value=tt-native_delta_t_days(value)
    return value


def residual(value,source,tolerance):
    difference=(value-source)*86400
    if abs(difference)>tolerance:raise ValueError('published time accuracy')
    return difference


def published(rows):
    refs=json.loads((ROOT/'Tests/AstronomyKitTests/Fixtures/IndependentReferences/reference-fixtures.json').read_bytes())['transits']
    if len(rows)!=len(refs):raise ValueError('published count')
    result=[]
    for row,source in zip(rows,refs):
        if set(row)!={'body','source','sourceUT','startUT','startTT','peakUT','peakTT','finishUT','finishTT','separation','publicPeakUT','formerUTCReferenceUT','publicFormerResidualSeconds','publicUTResidualSeconds'}:raise ValueError('published schema')
        expected={name:archive.shared.tt(source[key].removesuffix('Z')) for name,key in [('start','startUTC'),('peak','peakUTC'),('finish','finishUTC')]}
        if (row['body'],row['source'],row['sourceUT'])!=(source['body'],source['peakUTC'],expected['peak']):raise ValueError('published identity/source UT')
        seconds={}
        for name in expected:
            relation(row[name+'TT'],row[name+'UT'])
            seconds[name]=residual(row[name+'UT'],expected[name],source['timeToleranceSeconds'])
        if not row['startTT']<row['peakTT']<row['finishTT']:raise ValueError('contact order')
        separation=row['separation']-source['separationArcminutes']
        if abs(separation)>source['separationToleranceArcminutes']:raise ValueError('minimum separation accuracy')
        old=legacy_reference_ut(row['source'],row['sourceUT'])
        if abs(row['formerUTCReferenceUT']-old)>32*max(math.ulp(old),1e-12):raise ValueError('legacy UTC decoding')
        for key,reference in [('publicFormerResidualSeconds',row['formerUTCReferenceUT']),('publicUTResidualSeconds',row['sourceUT'])]:
            if row[key]!=(row['publicPeakUT']-reference)*86400:raise ValueError('public audit diagnostic relation')
        result.append({'body':row['body'],'sourceUT':row['source'],'seconds':seconds,'separationResidualArcminutes':separation,'formerPublicPeakResidualSeconds':row['publicFormerResidualSeconds'],'correctedPublicPeakResidualSeconds':row['publicUTResidualSeconds']})
    return result


def sequences(values,refs):
    expected=[r for body in ['mercury','venus'] for r in refs['transitSequences'][body]]
    rows=values['transit-sequence'];transits=[]
    if len(rows)!=len(expected):raise ValueError('transit sequence count')
    previous={}
    for row,source in zip(rows,expected):
        if set(row)!={'date','body','ut','tt','startUT','finishUT','separation'} or (row['date'],row['body'])!=(source['date'],source['body']):raise ValueError('transit sequence identity')
        relation(row['tt'],row['ut'])
        seconds={name:residual(row[key],source[sourcekey],source['timeToleranceSeconds']) for name,key,sourcekey in [('peak','ut','peakUT'),('start','startUT','startUT'),('finish','finishUT','finishUT')]}
        if not row['startUT']<row['ut']<row['finishUT'] or row['tt']<=previous.get(row['body'],-math.inf):raise ValueError('transit order/progress')
        previous[row['body']]=row['tt']
        separation=row['separation']-source['separationArcminutes']
        if abs(separation)>source['separationToleranceArcminutes']:raise ValueError('sequence separation')
        transits.append({'body':row['body'],'date':row['date'],'seconds':seconds,'separationResidualArcminutes':separation})
    rows=values['lunar-sequence'];contacts=[]
    if len(rows)!=len(refs['lunarSequence']):raise ValueError('lunar sequence count')
    for row,old,matched in zip(rows,refs['lunarSequence'],refs['danjonContacts']):
        if set(row)!={'date','kind','ut','tt','ingressUT','egressUT','semiDurationMinutes'} or (row['date'],row['kind'])!=(old['date'],old['kind']):raise ValueError('lunar identity')
        relation(row['tt'],row['ut']);residual(row['ut'],old['contactsUT']['peak'],old['timeToleranceSeconds'])
        if not row['ingressUT']<row['ut']<row['egressUT'] or abs(row['semiDurationMinutes']-(row['egressUT']-row['ingressUT'])*720)>1e-10:raise ValueError('lunar contact/duration relation')
        historical={n:(row[k]-old['contactsUT'][n])*86400 for n,k in [('penumbralBegin','ingressUT'),('penumbralEnd','egressUT')]}
        matching={n:residual(row[k],matched['contactsUT'][n],matched['timeToleranceSeconds']) for n,k in [('penumbralBegin','ingressUT'),('penumbralEnd','egressUT')]}
        contacts.append({'date':row['date'],'oh2001ResidualSeconds':historical,'oh2001Within120Seconds':{n:abs(v)<=old['timeToleranceSeconds'] for n,v in historical.items()},'danjonDiagramResidualSeconds':matching,'toleranceSeconds':120,'scope':'Independent source/model comparisons. OH2001 outcomes are reported individually under their unchanged interval; matching Danjon contacts do not establish agreement with that older convention.'})
    rows=values['global-sequence'];globals=[]
    if len(rows)!=len(refs['globalSequence']):raise ValueError('global count')
    for row,source in zip(rows,refs['globalSequence']):
        if set(row)!={'date','kind','ut','tt'} or (row['date'],row['kind'])!=(source['date'],source['kind']):raise ValueError('global identity')
        relation(row['tt'],row['ut']);globals.append({'date':row['date'],'seconds':residual(row['tt'],source['tt'],source['timeToleranceSeconds'])})
    for name in ['lunar-sequence','global-sequence']:
        if not all(a['tt']<b['tt'] for a,b in zip(values[name],values[name][1:])):raise ValueError('eclipse next progress')
    return {'transits':transits,'penumbralContacts':contacts,'global':globals}


def evidence(captures,bindings):
    if set(captures)!={'debug','release','resources','buildReceipts','runtimeBaseRevision','toolchain','releaseExecutableBytes','releaseObjectBytes'} or not lunar.finite(captures):raise ValueError('capture schema/nonfinite')
    refs=archive.build({n:(archive.SOURCE/n).read_bytes() for n in archive.SOURCES})
    if refs!=json.loads(archive.OUTPUT.read_bytes()):raise ValueError('reference replay')
    for config in ['debug','release']:
        if set(captures[config])!=SECTIONS:raise ValueError('capture sections')
        published(captures[config]['published']);sequences(captures[config],refs)
    if not lunar.near(captures['debug'],captures['release']):raise ValueError('configuration disagreement')
    r=captures['resources']
    if set(r)!={'coldSeconds','nextSeconds','nextCount','peakBeforeBytes','peakAfterColdBytes','peakAfterWorkloadBytes','checksum','host'} or r['nextCount']!=19 or min(r['coldSeconds'],r['nextSeconds'])<0 or not r['host']:raise ValueError('resource observation schema')
    if not 0<r['peakBeforeBytes']<=r['peakAfterColdBytes']<=r['peakAfterWorkloadBytes']:raise ValueError('RSS order')
    if not re.fullmatch('[0-9a-f]{40}',captures['runtimeBaseRevision']) or not captures['toolchain']:raise ValueError('runtime provenance')
    if captures['releaseExecutableBytes']<=0 or set(captures['releaseObjectBytes'])!={'EngineTransitEvents.o'} or captures['releaseObjectBytes']['EngineTransitEvents.o']<=0:raise ValueError('binary observation')
    builds={c:lunar.build_seconds(captures['buildReceipts'][c]) for c in ['debug','release']}
    if any(not math.isfinite(v) or v<0 for v in builds.values()):raise ValueError('build observation')
    return {'schemaVersion':1,'runtimeBaseRevision':captures['runtimeBaseRevision'],'sourceHashes':bindings,'published':published(captures['release']['published']),'sequences':sequences(captures['release'],refs),'radiusConventions':refs['radiusConventions'],'resources':r,'releaseObjectBytes':captures['releaseObjectBytes'],'releaseExecutableBytes':captures['releaseExecutableBytes'],'buildSeconds':builds,'toolchain':captures['toolchain'],'limitations':'Sampled independent UT contacts/angular minima and published next identities, not full-domain accuracy. Physical spheres use NASA fact-sheet mean radii; these are not attributed to the Meeus catalog. Apparent vectors retain engine light-time/aberration conventions. OH2001 December penumbral contacts remain outside 120 s; matching Danjon diagrams are separately qualified. Global G0/1986 and local peak limitations remain in their evidence owners. The public facade runs on these searches since the #96 cutover; host costs are not portable gates.'}


def capture(directory):
    directory=Path(directory)
    objects=ROOT/'.build/out/Intermediates.noindex/AstronomyKit.build/Release/AstronomyKit-t.build/Objects-normal/arm64'
    executable=ROOT/'.build/out/Products/Release/AstronomyKitTests.xctest/Contents/MacOS/AstronomyKitTests'
    return {**{c:{n:json.loads((directory/c/(n+'.json')).read_bytes()) for n in sorted(SECTIONS)} for c in ['debug','release']},'resources':json.loads((directory/'resources/resources.json').read_bytes()),'buildReceipts':{c:re.search(r'Build complete! \([^\n]+',(directory/f'full-{c}.log').read_text()).group(0) for c in ['debug','release']},'runtimeBaseRevision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'toolchain':subprocess.check_output(['swift','--version'],text=True).strip(),'releaseExecutableBytes':executable.stat().st_size,'releaseObjectBytes':{'EngineTransitEvents.o':(objects/'EngineTransitEvents.o').stat().st_size}}

def main():
    p=argparse.ArgumentParser();p.add_argument('--capture',type=Path);p.add_argument('--check',action='store_true');args=p.parse_args()
    if args.capture and args.check:p.error('capture and check are exclusive')
    values=capture(args.capture) if args.capture else json.loads(CAPTURE.read_bytes())
    data=archive.shared.encoded(values);result=archive.shared.encoded(evidence(values,hashes(data if args.capture else None)))
    if args.check:
        if OUTPUT.read_bytes()!=result:raise SystemExit('transit evidence differs')
    else:
        if not args.capture:
            previous=json.loads(OUTPUT.read_bytes());candidate=json.loads(result)
            dependencies.verify_retained_inputs('transits',previous['sourceHashes'])
            dependencies.verify_rebound_document(previous,candidate,'sourceHashes')
        archive.shared.publish({**({CAPTURE:data} if args.capture else {}),OUTPUT:result})
    print('transit evidence and all recorded relations match')
if __name__=='__main__':main()
