"""Independent high-precision definitions; values are measurements, never interval bounds."""
from functools import lru_cache
import base64
import re
import struct
import mpmath as mp

from numerics import ROOT, ENGINE, earth_model, unpack

mp.mp.dps = 80


def exact(value):
    numerator, denominator = value.as_integer_ratio()
    return mp.mpf(numerator) / denominator


def year_start(year):
    y = year - 1
    return mp.mpf(365 * y + y // 4 - y // 100 + y // 400) - mp.mpf("730119.5")


def decimal_year(ut):
    year = 2000 + int(mp.floor(ut / mp.mpf("365.2425")))
    while year_start(year) > ut:
        year -= 1
    while year_start(year + 1) <= ut:
        year += 1
    return year + (ut - year_start(year)) / (year_start(year + 1) - year_start(year))


@lru_cache(maxsize=1)
def observed_delta_t_data():
    """The generated observed-model values, promoted to extended precision."""
    text = (ROOT / (ENGINE + "Foundation/Generated/DeltaTObservedTable.swift")).read_text()
    first_mjd = int(re.search(r"static let firstMJD = ([0-9_]+)", text)[1].replace("_", ""))
    first_predicted = int(re.search(r"static let firstPredictedRow = ([0-9_]+)", text)[1].replace("_", ""))
    block = text.split("static let rows: Rows = {", 1)[1]
    count = int(re.search(r"count: ([0-9_]+)", block)[1].replace("_", ""))
    payload = base64.b64decode("".join(block.split('"""', 2)[1].split()), validate=True)
    packed = struct.unpack(f"<{count}d", payload)
    if count % 3 or len(packed) != count:
        raise ValueError("Observed Delta T row layout changed")
    first_ut = mp.mpf(first_mjd) - mp.mpf("51544.5")
    delta_t = [mp.mpf(int(packed[index])) / 1e7 for index in range(0, count, 3)]
    dut = [mp.mpf(int(packed[index])) / 1e7 for index in range(1, count, 3)]
    row_ut = [first_ut + index + value / 86400 for index, value in enumerate(dut)]
    segments = [[mp.mpf(value.replace("_", "")) for value in row] for row in re.findall(
        r"Segment\(start: ([^,]+), end: ([^,]+), a0: ([^,]+), a1: ([^,]+), a2: ([^,]+), a3: ([^)]+)\)", text
    )]
    names = ["lodRate", "lodAmplitude", "lodPeriod", "lodPhase", "lodEpoch"]
    constants = {name: mp.mpf(re.search(rf"static let {name} = (\S+)", text)[1].replace("_", "")) for name in names}
    return row_ut, delta_t, segments, constants, first_predicted


def observed_delta_t(ut):
    """IERS/Table S15/HMNAO model evaluated independently at high precision."""
    row_ut, delta_t, segments, constants, _ = observed_delta_t_data()

    def lod_integral(year):
        t = (year - constants["lodEpoch"]) / 100
        phase = 2 * mp.pi * (t + constants["lodPhase"]) / constants["lodPeriod"]
        return mp.mpf("36.525") * (
            constants["lodRate"] * t * t / 2
            + constants["lodAmplitude"] * constants["lodPeriod"] / (2 * mp.pi) * mp.cos(phase)
        )

    year = 2000 + ut / mp.mpf("365.25")
    if ut < row_ut[0]:
        if year < segments[0][0]:
            return segments[0][2] + lod_integral(year) - lod_integral(segments[0][0])
        segment = next(row for row in reversed(segments) if row[0] <= year)
        start, end, a0, a1, a2, a3 = segment
        t = (year - start) / (end - start)
        return a0 + t * (a1 + t * (a2 + t * a3))
    if ut > row_ut[-1]:
        return delta_t[-1] + lod_integral(year) - lod_integral(2000 + row_ut[-1] / mp.mpf("365.25"))
    low, high = 0, len(row_ut) - 1
    while high - low > 1:
        middle = (low + high) // 2
        if row_ut[middle] <= ut:
            low = middle
        else:
            high = middle
    fraction = (ut - row_ut[low]) / (row_ut[low + 1] - row_ut[low])
    return delta_t[low] + fraction * (delta_t[low + 1] - delta_t[low])


def delta_t(ut, model="espenakMeeus"):
    """The selected native Delta T definition at extended precision."""
    if model == "iersObserved":
        return observed_delta_t(ut)
    if model == "jplHorizons":
        ut = min(ut, 17 * mp.mpf("365.24217"))
    elif model != "espenakMeeus":
        raise ValueError("Unknown Delta T model")
    y = decimal_year(ut)
    if not 1800 <= y < 2201:
        raise ValueError("Reference Delta T domain is 1800 through 2200")
    pieces = [
        (1860, 1800, ["13.72", "-0.332447", "0.0068612", "0.0041116", "-0.00037436", "0.0000121272", "-0.0000001699", "0.000000000875"]),
        (1900, 1860, ["7.62", "0.5737", "-0.251754", "0.01680668", "-0.0004473624", mp.mpf(1)/233174]),
        (1920, 1900, ["-2.79", "1.494119", "-0.0598939", "0.0061966", "-0.000197"]),
        (1941, 1920, ["21.20", "0.84493", "-0.076100", "0.0020936"]),
        (1961, 1950, ["29.07", "0.407", -mp.mpf(1)/233, mp.mpf(1)/2547]),
        (1986, 1975, ["45.45", "1.067", -mp.mpf(1)/260, -mp.mpf(1)/718]),
        (2005, 2000, ["63.86", "0.3345", "-0.060374", "0.0017275", "0.000651814", "0.00002373599"]),
        (2050, 2000, ["62.92", "0.32217", "0.005589"]),
    ]
    for stop, origin, coefficients in pieces:
        if y < stop:
            return mp.fsum(mp.mpf(coefficient) * (y - origin)**k for k, coefficient in enumerate(coefficients))
    result = -20 + 32 * ((y - 1820) / 100)**2
    return result - mp.mpf("0.5628") * (2150 - y) if y < 2150 else result


def era(ut):
    """IAU 2000 ERA: one linear angle, reduced only after extended evaluation."""
    return mp.fmod(mp.mpf("0.7790572732640") + mp.mpf("1.00273781191135448") * ut, 1) * 360


@lru_cache(maxsize=None)
def nutation_tables(root=ROOT):
    """The generated IAU 2000A rows and the IAU 2006 factors, read as exact integers and decimals."""
    text = (root / (ENGINE + "Orientation/Generated/IAU2000ATerms.swift")).read_text()
    def rows(block, width):
        values = unpack(block)
        if len(values) % width or not all(value.is_integer() for value in values):
            raise ValueError("IAU 2000A table shape changed")
        return [tuple(int(value) for value in values[i:i + width]) for i in range(0, len(values), width)]
    luni_solar_block, planetary_block = text.split("static let planetaryTerms", 1)
    luni_solar, planetary = rows(luni_solar_block, 11), rows(planetary_block, 17)
    factors = [re.search(r"static let " + name + r" = (\S+)\n", text) for name in ["longitudeFactor", "j2Rate"]]
    if len(luni_solar) != 678 or len(planetary) != 687 or not all(factors):
        raise ValueError("IAU 2000A table shape changed")
    return tuple(luni_solar), tuple(planetary), tuple(match[1] for match in factors)


def nutation(tt, root=ROOT):
    """IAU 2006/2000A (SOFA nut06a definition), all published terms, in degrees."""
    t = tt / 36525
    arcsecond = mp.pi / 648000
    def power_series(coefficients):
        return mp.fsum(mp.mpf(c) * t**k for k, c in enumerate(coefficients)) * arcsecond
    # l, l', F, D and Omega: IERS 2003 for l, F and Omega, MHB2000 for l' and D.
    delaunay = [power_series(c) for c in [
        ["485868.249036", "1717915923.2178", "31.8792", "0.051635", "-0.00024470"],
        ["1287104.79305", "129596581.0481", "-0.5532", "0.000136", "-0.00001149"],
        ["335779.526232", "1739527262.8478", "-12.7512", "-0.001037", "0.00000417"],
        ["1072260.70369", "1602961601.2090", "-6.3706", "0.006593", "-0.00003169"],
        ["450160.398036", "-6962890.5431", "7.4722", "0.007702", "-0.00005939"]]]
    # l, F, D, Omega and Neptune from MHB2000, Mercury to Uranus from IERS 2003, then p_A.
    planets = [mp.mpf(a) + mp.mpf(b) * t for a, b in [
        ("2.35555598", "8328.6914269554"), ("1.627905234", "8433.466158131"), ("5.198466741", "7771.3771468121"),
        ("2.18243920", "-33.757045"), ("4.402608842", "2608.7903141574"), ("3.176146697", "1021.3285546211"),
        ("1.753470314", "628.3075849991"), ("6.203480913", "334.0612426700"), ("0.599546497", "52.9690962641"),
        ("0.874016757", "21.3299104960"), ("5.481293872", "7.4781598567"), ("5.321159000", "3.8127774000")]]
    planets.append((mp.mpf("0.024381750") + mp.mpf("0.00000538691") * t) * t)
    luni_solar, planetary, factors = nutation_tables(root)
    longitude_factor, j2_rate = map(mp.mpf, factors)
    longitude, obliquity = [], []
    for row in luni_solar:
        cos, sin = mp.cos_sin(mp.fsum(n * a for n, a in zip(row[:5], delaunay) if n))
        ps, pst, pc, ec, ect, es = row[5:]
        longitude.append((ps + pst * t) * sin + pc * cos)
        obliquity.append((ec + ect * t) * cos + es * sin)
    for row in planetary:
        cos, sin = mp.cos_sin(mp.fsum(n * a for n, a in zip(row[:13], planets) if n))
        ps, pc, es, ec = row[13:]
        longitude.append(ps * sin + pc * cos)
        obliquity.append(es * sin + ec * cos)
    j2 = j2_rate * t
    unit = mp.mpf("1e-7") / 3600
    return [mp.fsum(longitude) * unit * (1 + longitude_factor + j2), mp.fsum(obliquity) * unit * (1 + j2)]


def polynomial(coefficients, x):
    """Definition sum(a_k T_k), using cos(k acos(x)), independent of Clenshaw."""
    angle = mp.acos(x)
    return mp.fsum(a * mp.cos(k * angle) for k, a in enumerate(coefficients))


class Earth:
    def __init__(self, root=ROOT):
        self.degree, width, start, stop, values = earth_model(root)
        self.width = mp.mpf(width.numerator) / width.denominator
        self.start = mp.mpf(start.numerator) / start.denominator
        self.stop = mp.mpf(stop.numerator) / stop.denominator
        self.coefficients = values
        text = (root / (ENGINE + "Planets/Generated/VSOP87BTerms.swift")).read_text().split("static let earth = Model(", 1)[1].split("static let mars = Model(", 1)[0]
        counts_text = text.split("termCounts:", 1)[1].split("terms:", 1)[0]
        self.counts = [[int(n.replace("_", "")) for n in re.findall(r"[\d_]+", row)]
                       for row in re.findall(r"\[([^\[\]]+)\]", counts_text)]
        self.terms = unpack(text)
        if len(self.counts) != 3 or 3 * sum(map(sum, self.counts)) != len(self.terms):
            raise ValueError("VSOP87B Earth table shape changed")

    def series(self, tt):
        """Bretagnon-Francou VSOP87B definition, with shipped binary64 coefficients exact."""
        t = tt / 365250
        coordinates, index = [], 0
        for counts in self.counts:
            powers = []
            for alpha, count in enumerate(counts):
                terms = []
                for _ in range(count):
                    a, b, c = map(exact, self.terms[index:index + 3])
                    index += 3
                    terms.append(a * mp.cos(b + c * t))
                powers.append(mp.fsum(terms) * t**alpha)
            coordinates.append(mp.fsum(powers))
        lon, lat, radius = coordinates
        return [radius * mp.cos(lat) * mp.cos(lon), radius * mp.cos(lat) * mp.sin(lon), radius * mp.sin(lat)]

    def position(self, tt):
        if not self.start <= tt < self.stop:
            return self.series(tt)
        segment = int(mp.floor((tt - self.start) / self.width))
        x = 2 * (tt - (self.start + segment * self.width)) / self.width - 1
        n = self.degree + 1
        return [polynomial([exact(v) for v in self.coefficients[(segment * 3 + axis) * n:(segment * 3 + axis + 1) * n]], x)
                for axis in range(3)]

    def velocity(self, tt):
        """Derivative of the selected trajectory, not of a jump between models."""
        if not self.start <= tt < self.stop:
            return mp.diff(lambda value: mp.matrix(self.series(value)), tt)
        segment = int(mp.floor((tt-self.start)/self.width))
        x = 2*(tt-(self.start+segment*self.width))/self.width-1
        n = self.degree+1
        # dT_k(x)/dx = k U_(k-1)(x), evaluated independently of native Clenshaw.
        return [2/self.width*mp.fsum(k*exact(self.coefficients[(segment*3+axis)*n+k])*mp.chebyu(k-1,x)
                                    for k in range(1,n)) for axis in range(3)]
