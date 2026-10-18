#!/usr/bin/env python3
"""Replay original-component subtraction at 80 decimal digits on pinned DE441 samples."""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
from fractions import Fraction
import mpmath as mp

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'Scripts/moon-data/de441-full-component-evidence.json'
SPEC=importlib.util.spec_from_file_location('full',ROOT/'Scripts/generate-moon-de441-full.py')
full=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(full)
mp.mp.dps=80
sys.path.insert(0,str(ROOT/'Scripts/solar-numerics'))
from apparent_bounds import clock_bounds

# Frozen source recipe: first, middle and last batches in the verified DE441 layout.
# Each tuple records (first source record, count, first midpoint TDB seconds, Moon byte start, Earth byte start).
SAMPLE_BATCHES=(
    (1022640,8192,-126230270400,789807392,335490624),
    (0,8192,-959947200,2107004704,1651118784),
    (360448,7581,123610881600,2225231648,1769345728),
)
COMPONENT_FIELDS=('moonRecordBase64','earthRecordBase64')


def sample_inventory(batches,pins):
    rows=[]
    for first,count,midpoint,moon_start,earth_start in batches:
        ranges=[f'{start}-{start+count*328-1}' for start in (moon_start,earth_start)]
        for offset in (0,count//2,count-1):
            rows.append(dict(sourceRecordIndex=first+offset,midpointSecondsTDB=midpoint+offset*345600,
                             orderedRanges=ranges,byteOffsetInRanges=offset*328,rangeHashes={key:pins[key] for key in ranges}))
    return rows


def source_inventory(reader,pins):
    batches=list(full.q.batches(full.q.layout(reader)))
    selected=[]
    for metadata,first,count,ranges in (batches[0],batches[len(batches)//2],batches[-1]):
        midpoint=(metadata.start_jd_tdb+(first*4)+2-2451545)*86400
        selected.append((first,count,midpoint,ranges[0][0],ranges[1][0]))
    return sample_inventory(selected,pins)


def validate_samples(rows,pins):
    expected=sample_inventory(SAMPLE_BATCHES,pins)
    if not isinstance(rows,list) or len(rows)!=len(expected):
        raise ValueError('component sample inventory must contain the nine required records')
    for row,identity in zip(rows,expected):
        if not isinstance(row,dict) or any(row.get(key)!=value for key,value in identity.items()):
            raise ValueError('component sample identity or ordered Moon/Earth ranges differ')
        if not isinstance(row['orderedRanges'],list) or len(row['orderedRanges'])!=2:
            raise ValueError('component sample must name exactly one Moon range and one Earth range')
    return expected


def clock_enclosure():
    bounds=clock_bounds(Fraction(1461002))
    offset=bounds['offsetDays']
    if not Fraction(full.START) < -Fraction(1461002)-offset or not Fraction(full.START+full.COUNT*4) > Fraction(1461000)+offset:
        raise ValueError('source domain does not enclose the padded TT interval')
    return {key:str(value) for key,value in bounds.items()}


def calculate(rows):
    maximum=[mp.mpf(0),mp.mpf(0),mp.mpf(0)]
    for row in rows:
        moon,earth=[struct.unpack('<41d',base64.b64decode(row[k],validate=True)) for k in ('moonRecordBase64','earthRecordBase64')]
        raw=full.compose(moon,earth,row['midpointSecondsTDB']);derived=struct.unpack('<39d',raw)
        if hashlib.sha256(raw).hexdigest()!=row['derivedSHA256']: raise ValueError('derived sample digest differs')
        for axis in range(3):
            original=[mp.mpf(moon[2+axis*13+k])-mp.mpf(earth[2+axis*13+k]) for k in range(13)]
            errors=[mp.mpf(derived[axis*13+k])-original[k] for k in range(13)]
            maximum[0]=max(maximum[0],max(abs(x) for x in errors))
            for x in map(mp.mpf,[-1,-.5,0,.5,1]):
                t=[mp.mpf(1),x];u=[mp.mpf(1),2*x]
                for k in range(2,13):t.append(2*x*t[-1]-t[-2]);u.append(2*x*u[-1]-u[-2])
                maximum[1]=max(maximum[1],abs(mp.fsum(errors[k]*t[k] for k in range(13))))
                maximum[2]=max(maximum[2],abs(mp.fsum(errors[k]*k*u[k-1]/2 for k in range(1,13))))
    return dict(zip(['maxCoefficientDifferenceKm','maxAxisPositionDifferenceKm','maxAxisRateDifferenceKmPerTDBDay'],map(float,maximum)))



def check_storage_sources():
    storage=json.loads((ROOT/'Scripts/moon-data/de441-full-storage-evidence.json').read_text())
    paths=[*sorted(full.OUTPUT.glob('*.swift')),ROOT/'Sources/AstronomyKit/Engine/Moon/EngineMoonDE441Full.swift',ROOT/'Tests/AstronomyKitTests/Engine/Moon/EngineMoonDE441FullTests.swift',ROOT/'Scripts/generate-moon-de441-full.py',ROOT/'Scripts/qualify-moon-de441-full.py',full.MANIFEST,OUTPUT]
    expected={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    if storage['sourceHashes']!=expected:raise ValueError('storage capture source bindings differ')
    if storage['derivedPayloadBytes']!=full.COUNT*312 or storage['generatedSourceBytes']!=sum(p.stat().st_size for p in full.OUTPUT.glob('*.swift')):
        raise ValueError('storage payload size differs')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');parser.add_argument('--verify-source',action='store_true');parser.add_argument('--cache',type=Path,default=ROOT/'.context/issue-251/ranges');args=parser.parse_args()
    manifest=json.loads(full.MANIFEST.read_text())
    bindings={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['Scripts/qualify-moon-de441-full.py','Scripts/generate-moon-de441-full.py','Scripts/moon-data/de441-full-evidence.json','Scripts/solar-numerics/apparent_bounds.py','Scripts/model_resource.py','Sources/AstronomyKit/Engine/Gravity/Generated/DE441/PlutoDE441SunData.swift','Sources/AstronomyKit/Resources/ModelTables/pluto-de441-sun.bin','Sources/AstronomyKit/Engine/Moon/EngineTDB.swift','Sources/AstronomyKit/Engine/Moon/Generated/TDBTerms.swift']}
    if args.check or args.verify_source:
        check_storage_sources()
        result=json.loads(OUTPUT.read_text())
        pins=manifest['source']['retrievedByteRangesSHA256']
        expected=validate_samples(result['rows'],pins)
        if result['sourceHashes']!=bindings or result['measurements']!=calculate(result['rows']) or result['clockEnclosure']!=clock_enclosure():raise ValueError('component evidence differs')
        if args.verify_source:
            reader=full.q.CachedReader(args.cache,pins)
            if source_inventory(reader,pins)!=expected:raise ValueError('pinned sample recipe differs from the original SPK layout')
            for row in result['rows']:
                for index,field in enumerate(COMPONENT_FIELDS):
                    lo,hi=map(int,row['orderedRanges'][index].split('-'));data=reader.read(lo,hi-lo+1);offset=row['byteOffsetInRanges']
                    if data[offset:offset+328]!=base64.b64decode(row[field],validate=True):raise ValueError('sample differs from original source bytes')
        print('Verified nine original-component records at five phases and 80 decimal digits');return
    pins=manifest['source']['retrievedByteRangesSHA256']
    reader=full.q.CachedReader(args.cache,pins)
    rows=source_inventory(reader,pins)
    validate_samples(rows,pins)
    for row in rows:
        raw=[]
        for index,field in enumerate(COMPONENT_FIELDS):
            lo,hi=map(int,row['orderedRanges'][index].split('-'));data=reader.read(lo,hi-lo+1);offset=row['byteOffsetInRanges']
            raw.append(data[offset:offset+328]);row[field]=base64.b64encode(raw[-1]).decode()
        moon,earth=[struct.unpack('<41d',data) for data in raw]
        row['derivedSHA256']=hashlib.sha256(full.compose(moon,earth,row['midpointSecondsTDB'])).hexdigest()
    result={'schemaVersion':1,'sourceHashes':bindings,'clockEnclosure':clock_enclosure(),'selection':'First, middle and last records of the first, middle and last pinned 8192-record source batches; phases -1,-0.5,0,0.5,1.','precisionDecimalDigits':80,'measurements':calculate(rows),'rows':rows,'limitations':'Sampled arithmetic comparison against exact original binary64 component coefficients. It does not establish physical accuracy or replace the exhaustive coefficient-subtraction enclosure.'}
    OUTPUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');print(result['measurements'])


if __name__=='__main__':main()
