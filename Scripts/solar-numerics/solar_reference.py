"""Extended-precision geometric Sun model, composed from published definitions."""
import re
import importlib.util
import struct
from functools import lru_cache
import reference as ref
from numerics import ROOT, ENGINE, table_payload

mp = ref.mp

EARTH_BARYCENTER_PATH = ENGINE + 'Planets/Generated/DE441/PlanetDE441EarthBarycenterData.swift'
EARTH_OFFSET_PATH = ENGINE + 'Planets/Generated/DE441/PlanetDE441EarthOffsetData.swift'
PLANET_SUN_PATH = ENGINE + 'Planets/Generated/Saturn/SaturnSunData.swift'
AU_KM = mp.mpf('149597870.700')


def polynomial(coefficients, t):
    return mp.fsum(mp.mpf(c) * t**i for i, c in enumerate(coefficients))


def r1(angle):
    c, s = mp.cos(angle), mp.sin(angle)
    return mp.matrix([[1, 0, 0], [0, c, s], [0, -s, c]])


def r3(angle):
    c, s = mp.cos(angle), mp.sin(angle)
    return mp.matrix([[c, s, 0], [-s, c, 0], [0, 0, 1]])


@lru_cache(maxsize=1)
def long_term_coefficients():
    # Read the independent archived ERFA definitions, not the Swift tables.
    spec = importlib.util.spec_from_file_location('vondrak_source', ROOT / 'Scripts/generate-long-term-precession.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.generate()  # Verify the pinned source archive.
    return [module.coefficients(name, prefix) for name,prefix in [('ltpequ.c','xy'),('ltpecl.c','pq')]]


def cross(a, b):
    return mp.matrix([a[(i+1)%3]*b[(i+2)%3]-a[(i+2)%3]*b[(i+1)%3] for i in range(3)])


def poles(tt):
    t = tt / 36525
    result = []
    for pol, periodic in long_term_coefficients():
        values = []
        for axis in range(2):
            value = polynomial(pol[axis], t)
            for row in periodic:
                period,cx,cy,sx,sy = map(mp.mpf, row)
                c,s = (cx,sx) if axis == 0 else (cy,sy)
                angle = 2*mp.pi*t/period
                value += c*mp.cos(angle)+s*mp.sin(angle)
            values.append(value*mp.pi/648000)
        x,y = values
        result.append(mp.matrix([x,y,mp.sqrt(1-x*x-y*y)]))
    equ, local = result
    p,q,w = local
    eps0 = mp.mpf('84381.406')*mp.pi/648000
    ecl = mp.matrix([p,-q*mp.cos(eps0)-w*mp.sin(eps0),-q*mp.sin(eps0)+w*mp.cos(eps0)])
    return equ,ecl


def obliquity(tt):
    equ,ecl = poles(tt)
    return mp.atan2(mp.norm(cross(equ,ecl)), mp.fdot(equ,ecl))


def precession(tt):
    equ,ecl = poles(tt)
    x = cross(equ,ecl)
    x /= mp.norm(x)
    y = cross(equ,x)
    return mp.matrix([list(x),list(y),list(equ)])


def complementary(tt):
    t = tt / 36525
    coefficients = [
        ['485868.249036', '1717915923.2178', '31.8792', '0.051635', '-0.00024470'],
        ['1287104.793048', '129596581.0481', '-0.5532', '0.000136', '-0.00001149'],
        ['335779.526232', '1739527262.8478', '-12.7512', '-0.001037', '0.00000417'],
        ['1072260.703692', '1602961601.2090', '-6.3706', '0.006593', '-0.00003169'],
        ['450160.398036', '-6962890.5431', '7.4722', '0.007702', '-0.00005939'],
    ]
    angles = [polynomial(c, t) * mp.pi / 648000 for c in coefficients]
    angles += [mp.mpf('3.176146697') + mp.mpf('1021.3285546211') * t,
               mp.mpf('1.753470314') + mp.mpf('628.3075849991') * t,
               (mp.mpf('0.024381750') + mp.mpf('0.00000538691') * t) * t]
    text = (ROOT / (ENGINE + 'Orientation/Generated/EquinoxComplementaryTerms.swift')).read_text()
    rows = [[mp.mpf(value.strip().replace('_', '')) for value in row.split(',')]
            for row in re.findall(r'ComplementaryTerm\(([^)]+)\)', text)]
    if len(rows) != 34 or any(len(row) != 10 for row in rows):
        raise ValueError('Complementary-series table shape changed')
    terms = []
    for i, row in enumerate(rows):
        argument = mp.fsum(n*a for n,a in zip(row[:8], angles))
        terms.append((row[8] * mp.sin(argument) + row[9] * mp.cos(argument)) * (t if i == 33 else 1))
    return mp.fsum(terms) * mp.pi / 648000


def mean_sidereal(ut, tt):
    t = tt / 36525
    correction = polynomial(['0.014506', '4612.156534', '1.3915817', '-0.00000044', '-0.000029956', '-0.0000000368'], t) / 3600
    return (ref.era(ut) + correction) % 360


def orientation(ut, tt):
    psi, deps = [a * mp.pi / 180 for a in ref.nutation(tt)]
    mean = obliquity(tt)
    nutation = r1(-mean-deps) * r3(-psi) * r1(mean)
    sidereal = (mean_sidereal(ut, tt) + (psi * mp.cos(mean) + complementary(tt)) * 180 / mp.pi) % 360
    return nutation * precession(tt), sidereal


def equatorial_earth(position):
    x, y, z = position
    return [x + mp.mpf('0.000000440360') * y - mp.mpf('0.000000190919') * z,
            -mp.mpf('0.000000479966') * x + mp.mpf('0.917482137087') * y - mp.mpf('0.397776982902') * z,
            mp.mpf('0.397776982902') * y + mp.mpf('0.917482137087') * z]


@lru_cache(maxsize=3)
def direct_table(path):
    text = (ROOT / path).read_text()
    start, days, count, coefficients = re.search(
        r'start: ([^,]+), days: ([^,]+),\s*recordCount: ([^,]+),\s*coefficientCount: ([^,]+),', text).groups()
    payload = table_payload(path, text)
    count = int(count.replace('_', ''))
    coefficients = int(coefficients.replace('_', ''))
    if len(payload) != count * 3 * coefficients * 8:
        raise ValueError(f'Direct source table shape changed: {path}')
    return mp.mpf(start), mp.mpf(days), count, coefficients, payload


def direct_state(path, tdb):
    start, days, count, coefficients, payload = direct_table(path)
    record = int(mp.floor((tdb - start) / days))
    if not 0 <= record < count:
        raise ValueError(f'Direct source table exterior: {path}')
    x = 2 * (tdb - start - record * days) / days - 1
    offset = record * 3 * coefficients * 8
    values = struct.unpack_from(f'<{3 * coefficients}d', payload, offset)
    positions, velocities = [], []
    for axis in range(3):
        terms = [ref.exact(value) for value in values[axis * coefficients:(axis + 1) * coefficients]]
        positions.append(mp.fsum(term * mp.chebyt(k, x) for k, term in enumerate(terms)))
        velocities.append(2 / days * mp.fsum(k * terms[k] * mp.chebyu(k - 1, x) for k in range(1, coefficients)))
    return mp.matrix(positions), mp.matrix(velocities)


def frame_bias(vector):
    unit = mp.pi / 648000
    return r1(-mp.mpf('84381.406') * unit) * r3(mp.mpf('0.041775') * unit) * r1(
        mp.mpf('84381.412819') * unit) * r3(-mp.mpf('0.052928') * unit) * vector


class SelectedEarth:
    def __init__(self):
        self.retained = ref.Earth()

    @staticmethod
    def weight(tt):
        start, end, days = mp.mpf('-36524.5'), mp.mpf('47846.5'), mp.mpf('32')
        if start <= tt <= end:
            return mp.mpf(1), mp.mpf(0)
        if tt <= start - days or tt >= end + days:
            return mp.mpf(0), mp.mpf(0)
        if tt < start:
            x, sign = (tt - (start - days)) / days, 1
        else:
            x, sign = (end + days - tt) / days, -1
        return x**3 * (10 + x * (-15 + 6 * x)), sign * 30 * x**2 * (1 - x)**2 / days

    @staticmethod
    def source(tt):
        import apparent_reference as apparent
        tdb = apparent.clock(tt)
        barycenter = direct_state(EARTH_BARYCENTER_PATH, tdb)
        offset = direct_state(EARTH_OFFSET_PATH, tdb)
        sun = direct_state(PLANET_SUN_PATH, tdb)
        position = frame_bias(barycenter[0] - sun[0] + offset[0]) / AU_KM
        velocity = frame_bias(barycenter[1] - sun[1] + offset[1]) * mp.diff(apparent.clock, tt) / AU_KM
        return position, velocity

    def retained_state(self, tt):
        position = mp.matrix(equatorial_earth(self.retained.position(tt)))
        velocity = mp.matrix(equatorial_earth(self.retained.velocity(tt)))
        return position, velocity

    def position(self, tt):
        retained_position, _ = self.retained_state(tt)
        weight, _ = self.weight(tt)
        if not weight:
            return retained_position
        source_position, _ = self.source(tt)
        return retained_position + weight * (source_position - retained_position)

    def velocity(self, tt):
        retained_position, retained_velocity = self.retained_state(tt)
        weight, rate = self.weight(tt)
        if not weight:
            return retained_velocity
        source_position, source_velocity = self.source(tt)
        return retained_velocity + weight * (source_velocity - retained_velocity) + rate * (
            source_position - retained_position)


class Solar:
    def __init__(self):
        self.earth = SelectedEarth()

    def observer(self, ut, tt, location=None):
        import apparent_reference as apparent
        result = mp.matrix(self.earth.position(tt)) + apparent.sun(tt)
        if location is not None:
            result += self.site(ut,tt,location)
        return result

    @staticmethod
    def site(ut,tt,location):
        rotation, sidereal = orientation(ut, tt)
        latitude, longitude, height = map(ref.exact, location)
        phi = latitude * mp.pi / 180
        theta = (sidereal + longitude) * mp.pi / 180
        polar = 1 - 1 / mp.mpf('298.25642')
        coefficient = 1 / mp.sqrt(mp.cos(phi)**2 + polar**2 * mp.sin(phi)**2)
        radius = mp.mpf('6378.1366')
        au = mp.mpf('149597870.700')
        site = mp.matrix([(radius*coefficient + height/1000) * mp.cos(phi) * mp.cos(theta) / au,
                          (radius*coefficient + height/1000) * mp.cos(phi) * mp.sin(theta) / au,
                          (radius*polar**2*coefficient + height/1000) * mp.sin(phi) / au])
        return rotation.T*site

    def observer_velocity(self,ut,tt,location=None):
        import apparent_reference as apparent
        result=mp.matrix(self.earth.velocity(tt))+mp.diff(apparent.sun,tt)
        if location is not None:
            result+=mp.diff(lambda delta:self.site(ut+delta,tt+delta,location),mp.mpf(0))
        return result

    def geocentric(self, ut, tt, model):
        import apparent_reference as apparent
        position = self.observer(ut, tt)
        velocity = self.observer_velocity(ut,tt)
        return apparent.apparent_sun(tt, position, velocity)

    def altitude(self, ut, tt, model, observer):
        import apparent_reference as apparent
        position = self.observer(ut,tt,observer)
        velocity = self.observer_velocity(ut,tt,observer)
        result = apparent.apparent_sun(tt, position, velocity)
        rotation, sidereal = orientation(ut, tt)
        latitude, longitude, height = map(ref.exact, observer)
        phi = latitude * mp.pi / 180
        theta = (sidereal + longitude) * mp.pi / 180
        direction = rotation * mp.matrix(result['vector'])
        north = [-mp.sin(phi)*mp.cos(theta), -mp.sin(phi)*mp.sin(theta), mp.cos(phi)]
        west = [mp.sin(theta), -mp.cos(theta), 0]
        zenith = [mp.cos(phi)*mp.cos(theta), mp.cos(phi)*mp.sin(theta), mp.sin(phi)]
        n, w, z = [mp.fsum(a*b for a,b in zip(axis,direction)) for axis in [north, west, zenith]]
        result['altitude'] = mp.atan2(z, mp.sqrt(n*n+w*w)) * 180 / mp.pi
        result['azimuth'] = (-mp.atan2(w,n) * 180 / mp.pi) % 360
        result['siderealDegrees'] = sidereal
        return result


def input_pair(value, scale, model, recorded_ut):
    return _input_pair(value, scale, model, recorded_ut, mp.mp.dps)


@lru_cache(maxsize=1024)
def _input_pair(value, scale, model, recorded_ut, precision):
    """Exact public scalar reference; recorded UT selects an inverse overlap branch."""
    with mp.workdps(precision):
        value = ref.exact(value)
        if scale == 'ut':
            return value, value+ref.delta_t(value,model)/86400
        if scale == 'date':
            civil = value/86400+mp.mpf('365.5')
            text = (ROOT/'Sources/AstronomyKit/UTCOffsetTable.swift').read_text()
            rows = [[mp.mpf(item) for item in row] for row in re.findall(r'Segment\(start: ([^,]+), offset: ([^,]+), rate: ([^)]+)\)',text)]
            applicable = [row for row in rows if row[0] <= civil]
            if not applicable:
                return civil, civil+ref.delta_t(civil,model)/86400
            start,offset,rate = applicable[-1]
            tt = civil+(offset+rate*(civil-start))/86400
        elif scale == 'tt':
            tt = value
        else:
            raise ValueError('Unknown public input reference')
        # Each smooth piece is strictly increasing on this measurement domain.
        # Bisect pieces separately, retaining both roots at negative overlaps.
        lower, upper = tt-mp.mpf('.02'), tt+mp.mpf('.02')
        cuts = [lower, upper]
        for year in [1860,1900,1920,1941,1961,1986,2005,2050,2150]:
            boundary = ref.year_start(year)
            if lower < boundary < upper and not (model == 'jplHorizons' and year > 2017):
                cuts.append(boundary)
        cuts.sort()
        roots = []
        for left,right in zip(cuts,cuts[1:]):
            forward = lambda u: u+ref.delta_t(u,model)/86400
            # Resolve a one-sided model endpoint with guard digits. At the
            # working precision, a tiny UT decrement can round back to the
            # boundary during decimal-year conversion and select its right piece.
            with mp.workdps(precision+30):
                inside_right = right-mp.eps*max(1,abs(right))*10000
                upper_value = forward(inside_right)
            if not forward(left) <= tt <= upper_value:
                continue
            for _ in range(4*precision+20):
                middle = (left+right)/2
                if middle == left or middle == right:
                    break
                if forward(middle) < tt:
                    left = middle
                else:
                    right = middle
            root = (left+right)/2
            if abs(forward(root)-tt) > mp.power(10,-precision+12):
                raise ValueError('Extended-precision inverse did not meet its residual check')
            roots.append(root)
        if not roots:
            return None
        return min(roots,key=lambda root:abs(root-ref.exact(recorded_ut))),tt
