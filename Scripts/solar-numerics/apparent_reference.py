"""Independent arbitrary-precision barycentric solar apparent-place definition.

These values measure agreement with the selected model; they are not physical
accuracy bounds. Cubics are evaluated in Hermite form, independently of native
Chebyshev reconstruction, with archived binary64 endpoint values exact.
"""
from functools import lru_cache
import re
import struct
import mpmath as mp
from numerics import ROOT, ENGINE, table_payload
from reference import exact

SUN_PATH = ENGINE + 'Gravity/Generated/DE441/PlutoDE441SunData.swift'
SUN_RESOURCE_PATH = 'Sources/AstronomyKit/Resources/ModelTables/pluto-de441-sun.bin'
PATHS = [SUN_PATH, SUN_RESOURCE_PATH, 'Scripts/model_resource.py']
TDB_PATH = 'Scripts/apparent-place-data/dtdb.c'


@lru_cache(maxsize=1)
def sun_table():
    text = (ROOT / SUN_PATH).read_text()
    start, width, count = re.search(r'start: ([^,]+), days: ([^,]+), recordCount: ([^,]+),', text).groups()
    payload = table_payload(SUN_PATH, text)
    count = int(count.replace('_', ''))
    if len(payload) != 48 * (count + 1):
        raise ValueError('Solar endpoint table shape changed')
    return mp.mpf(start), mp.mpf(width), count, payload


@lru_cache(maxsize=1)
def tdb_terms():
    source = (ROOT / TDB_PATH).read_text()
    body = source.split('static const double fairhd[787][3] = {')[1].split('};')[0]
    terms = [[mp.mpf(x.strip()) for x in row.split(',')] for row in re.findall(r'\{([^{}]+)\}', body)]
    if len(terms) != 787:
        raise ValueError('Fairhead source shape changed')
    return terms


def tdb_offset(tt):
    t = tt / 365250
    terms = tdb_terms()
    values = [mp.fsum(a * mp.sin(b*t+c) for a,b,c in terms[lo:hi])
              for lo,hi in [(0,474),(474,679),(679,764),(764,784),(784,787)]]
    result = mp.fsum(v*t**i for i,v in enumerate(values))
    for a,b,c in [('0.00065e-6','6069.776754','4.021194'),('0.00033e-6','213.299095','5.543132'),
                  ('-0.00196e-6','6208.294251','5.696701'),('-0.00173e-6','74.781599','2.435900')]:
        result += mp.mpf(a)*mp.sin(mp.mpf(b)*t+mp.mpf(c))
    return result + mp.mpf('0.03638e-6')*t*t


def clock(tt):
    return tt + tdb_offset(tt)/86400


def sun(tt):
    from solar_reference import r1, r3
    tdb = clock(tt)
    start, width, count, payload = sun_table()
    record = int(mp.floor((tdb-start)/width))
    if not 0 <= record < count:
        raise ValueError('Solar source exterior')
    u = (tdb-start-record*width)/width
    left = list(map(exact, struct.unpack_from('<6d', payload, record*48)))
    right = list(map(exact, struct.unpack_from('<6d', payload, (record+1)*48)))
    h00, h10 = 2*u**3-3*u**2+1, u**3-2*u**2+u
    h01, h11 = -2*u**3+3*u**2, u**3-u**2
    p = mp.matrix([(h00*left[i]+h10*width*left[i+3]+h01*right[i]+h11*width*right[i+3])
                   /mp.mpf('149597870.700') for i in range(3)])
    unit = mp.pi/648000
    bias = r1(-mp.mpf('84381.406')*unit)*r3(mp.mpf('0.041775')*unit)*r1(mp.mpf('84381.412819')*unit)*r3(-mp.mpf('0.052928')*unit)
    return bias*p


def norm(v):
    return mp.sqrt(mp.fsum(x*x for x in v))


def aberration(p, beta, solar_distance):
    bm = mp.sqrt(1-mp.fsum(v*v for v in beta))
    pdv = mp.fsum(a*b for a,b in zip(p,beta))
    srs = mp.mpf('1.97412574336e-8')
    q = mp.matrix([p[i]*bm+(1+pdv/(1+bm))*beta[i]+srs/solar_distance*(beta[i]-pdv*p[i]) for i in range(3)])
    return q/norm(q)


def apparent_sun(tt, observer_position, observer_velocity):
    """Converged mathematical TDB root, independent of native binary64 stopping."""
    c = mp.mpf(299792458)*86400/149597870700
    delay = mp.mpf(0)
    trace = []
    for _ in range(30):
        emission = tt-delay
        displacement = sun(emission)-observer_position
        next_delay = norm(displacement)/c-(tdb_offset(tt)-tdb_offset(emission))/86400
        trace.append({'tt': emission, 'nextTT': tt-next_delay})
        if abs(next_delay-delay) < mp.mpf('1e-60'):
            break
        delay = next_delay
    else:
        raise ValueError('Arbitrary-precision TDB root failed')
    distance = norm(displacement)
    beta = observer_velocity/mp.diff(clock, tt)/c
    corrected = aberration(displacement/distance, beta, norm(observer_position-sun(tt)))*distance
    return {'vector':list(corrected), 'trace':trace, 'lightTimeDays':distance/c}
