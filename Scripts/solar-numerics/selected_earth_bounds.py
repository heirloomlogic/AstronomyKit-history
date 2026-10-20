"""Exact coefficient majorants for the full-weight selected Earth trajectory."""
from fractions import Fraction as Q
from functools import lru_cache
import re
import struct

from numerics import ROOT, ENGINE, BINDINGS, source_hashes, sqrt_interval, table_payload

START, STOP = Q('-36524.5'), Q('36889.5')
AU = Q('149597870.700')
PATHS = [ENGINE + 'Planets/Generated/DE441/PlanetDE441EarthBarycenterData.swift',
         ENGINE + 'Planets/Generated/Saturn/SaturnSunData.swift',
         ENGINE + 'Planets/Generated/DE441/PlanetDE441EarthOffsetData.swift']


def check_domain(lower=START, upper=STOP):
    text = (ROOT / (ENGINE + 'Moon/EngineMoonEphemeris.swift')).read_text()
    start, stop = [Q(re.search(r'static let '+name+r' = ([^\n]+)', text)[1].replace('_', ''))
                   for name in ['fullWeightStart', 'fullWeightEnd']]
    if 'if tt >= fullWeightStart && tt <= fullWeightEnd { return (1, 0) }' not in text:
        raise ValueError('Selected full-weight branch changed')
    if not start <= lower < upper <= stop:
        raise ValueError('Altitude reception hull leaves selected Earth full-weight domain')
    source = (ROOT / 'Sources/AstronomyKit/SolarAltitudeObservation.swift').read_text()
    if 'guard coverage.contains(lowerTT), coverage.contains(upperTT)' not in source:
        raise ValueError('Altitude reception hull coverage guard changed')


def squared_norm(axes):
    """T_i T_j = (T_(i+j) + T_|i-j|)/2, retaining exact cancellation."""
    # Binary64 coefficients are dyadic; a common denominator keeps cancellation exact
    # while doing the quadratic convolution with integers.
    import math
    denominator = math.lcm(*(a.denominator for axis in axes for a in axis))
    count = max(map(len, axes))
    result = [0] * (2 * count - 1)
    for axis in axes:
        integers = [a.numerator*(denominator//a.denominator) for a in axis]
        for i, a in enumerate(integers):
            for j, b in enumerate(integers):
                result[i+j] += a*b
                result[abs(i-j)] += a*b
    return [Q(a, 2*denominator**2) for a in result]


def record_bounds(axes, days):
    squared = squared_norm(axes)
    remainder = sum(map(abs, squared[1:]))
    speed2 = sum(sum(k*k*abs(a) for k, a in enumerate(axis))**2 for axis in axes) * 4/days**2
    acceleration2 = sum(sum(Q(k*k*(k*k-1), 3)*abs(a) for k, a in enumerate(axis))**2
                        for axis in axes) * 16/days**4
    return {'radiusLower': sqrt_interval(max(Q(0), squared[0]-remainder))[0],
            'radiusUpper': sqrt_interval(squared[0]+remainder)[1],
            'speed': sqrt_interval(speed2)[1], 'acceleration': sqrt_interval(acceleration2)[1]}


def join_bounds(left, right, days):
    position = [sum(a*(-1)**k for k, a in enumerate(r))-sum(l) for l, r in zip(left, right)]
    velocity = [(sum(a*(-1)**(k-1)*k*k for k, a in enumerate(r) if k)
                 -sum(a*k*k for k, a in enumerate(l)))*2/days for l, r in zip(left, right)]
    return tuple(sqrt_interval(sum(x*x for x in vector))[1] for vector in [position, velocity])


def table(path, lower, upper):
    text = (ROOT/path).read_text()
    start, days, count, size = re.search(
        r'start: ([^,]+), days: ([^,]+),\s*recordCount: ([^,]+),\s*coefficientCount: ([^,]+),', text).groups()
    start, days, count, size = Q(start), Q(days), int(count.replace('_', '')), int(size.replace('_', ''))
    payload = table_payload(path, text)
    if len(payload) != count*3*size*8:
        raise ValueError('Selected Earth coefficient payload shape changed')
    first, last = (lower-start)//days, (upper-start)//days
    if not 0 <= first <= last < count:
        raise ValueError('Selected Earth clock-padded domain leaves source coverage')
    maxima = {key: Q(0) for key in ['radiusUpper', 'speed', 'acceleration', 'positionJoin', 'velocityJoin']}
    minimum, previous = None, None
    for record in range(first, last+1):
        values = struct.unpack_from(f'<{3*size}d', payload, record*3*size*8)
        axes = [[Q(a) for a in values[axis*size:(axis+1)*size]] for axis in range(3)]
        bounds = record_bounds(axes, days)
        minimum = bounds['radiusLower'] if minimum is None else min(minimum, bounds['radiusLower'])
        for key in ['radiusUpper', 'speed', 'acceleration']:
            maxima[key] = max(maxima[key], bounds[key])
        if previous is not None:
            for key, value in zip(['positionJoin', 'velocityJoin'], join_bounds(previous, axes, days)):
                maxima[key] = max(maxima[key], value)
        previous = axes
    return {**maxima, 'radiusLower': minimum, 'firstRecord': Q(first), 'lastRecord': Q(last),
            'days': days, 'start': start, 'coefficientCount': Q(size)}


def derive():
    check_domain()
    import apparent_bounds
    paths = BINDINGS + apparent_bounds.PATHS + [__file__,
        'Scripts/solar-numerics/intervals.py', 'Sources/AstronomyKit/SolarAltitudeObservation.swift']
    return _derive(tuple(source_hashes(ROOT, paths).items()))


@lru_cache(maxsize=1)
def _derive(fingerprint):
    import apparent_bounds
    from intervals import equatorial_matrix
    check_domain()
    clock = apparent_bounds.clock_bounds(max(abs(START), abs(STOP)))
    components = [table(path, START-clock['offsetDays'], STOP+clock['offsetDays']) for path in PATHS]
    matrix = equatorial_matrix()
    gram = [[sum(matrix[k][i]*matrix[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    departure = max(sum(abs(x-(i == j)) for j, x in enumerate(row)) for i, row in enumerate(gram))
    # Public selected EQJ -> retained frame transpose -> EQJ is M M^T.
    norm_hi, norm_lo = 1+departure, 1-departure
    earth, sun, offset = components
    radius_lower = (earth['radiusLower']-sun['radiusUpper']-offset['radiusUpper'])/AU*norm_lo
    radius_upper = sum(c['radiusUpper'] for c in components)/AU*norm_hi
    rate = 1+clock['rateDeparture']
    speed_tdb = sum(c['speed'] for c in components)/AU*norm_hi
    speed = speed_tdb*rate
    acceleration = sum(c['acceleration'] for c in components)/AU*norm_hi*rate**2 + speed_tdb*clock['accelerationPerDay']
    if components[2]['start'] != Q('-36560.5') or any(
            (c['start']-components[2]['start']) % 4 or c['days'] % 4 for c in components):
        raise ValueError('Selected Earth common four-TDB-day join grid changed')
    # Within a <1 TT day hull each component has at most one source join.
    # The triangle sum also covers simultaneous joins of distinct components.
    spacing = min(c['days'] for c in components)/rate
    position_join = sum(c['positionJoin'] for c in components)/AU*norm_hi
    velocity_join = sum(c['velocityJoin'] for c in components)/AU*norm_hi*rate
    if radius_lower <= 0 or norm_lo <= 0 or spacing <= Q('3.999999'):
        raise ValueError('Selected Earth radius, frame or source join enclosure failed')
    return {'radiusMinimumAU': radius_lower, 'radiusMaximumAU': radius_upper,
            'speedAUPerTTDay': speed, 'accelerationAUPerTTDay2': acceleration,
            'joinMaximumAU': position_join, 'velocityJoinAUPerTTDay': velocity_join,
            'minimumComponentJoinSpacingTTDays': spacing, 'frameRoundTripNormUpper': norm_hi,
            'frameRoundTripNormLower': norm_lo, 'components': components, 'clock': clock}
