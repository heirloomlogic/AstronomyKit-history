#!/usr/bin/env python3
"""Build the independent astronomical reference fixture archive."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import math
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "Scripts/reference-data/sources"
OUTPUT_DIR = ROOT / "Tests/AstronomyKitTests/Fixtures/IndependentReferences"
UPSTREAM_REVISION = "865d3da7d8112bbc7911238052c6af4aaf877181"
UPSTREAM_BASE = f"https://raw.githubusercontent.com/cosinekitty/astronomy/{UPSTREAM_REVISION}"

UPSTREAM_SOURCES = {
    "parse-moon-phases.js": ("generate/moonphase/parse_moon_phases.js", "19d0658653ad7a289b8f8c51fced6ad76e056f7c54133a3ae660d3333d16e263"),
    "normalize-eclipses.py": ("generate/eclipse/norm.py", "27aad287e710b6e55c13cb2ccbc6da588bcec718ba9b6fddacb47bd8896c3f6f"),
    "readme-lunar-eclipse.txt": ("generate/eclipse/readme_lunar_eclipse.txt", "9fed27ab68cf32b1d3b28f6910dc0f3645947ce75f350da33b3e419b776df170"),
    "seasons.txt": ("generate/seasons/seasons.txt", "92a0b2a5f8c67510b49f342f6f7a763cb6eee1ef32413344e71ce169a3582383"),
    "moonphases.txt": ("generate/moonphase/moonphases.txt", "959ec955d89b4d9d2366a737ecffad0ace1deafdb7d54947c94a0585b316c064"),
    "moon_nodes.txt": ("generate/moon_nodes/moon_nodes.txt", "c6140f77c8642be53687a4f7be00497c2bae6cc78ac6d9d6c61be73c06a4a1d5"),
    "moon_apsides.txt": ("generate/apsides/moon.txt", "d01d330774ce3f7ae6c912eef86adc982f833cbdf0345f6fa16cc1af7e187e8b"),
    "earth_apsides.txt": ("generate/apsides/earth.txt", "38405b56a8dce7b9a19405e29242bdf4c08e978ae48b5f14123a65b57a874cf1"),
    "riseset.txt": ("generate/riseset/riseset.txt", "92f5c1edf647c3f46d8964cfab06315fbe09cb580bc512d1418d41039424ff48"),
    "local_solar_eclipse.txt": ("generate/eclipse/local_solar_eclipse.txt", "1273c79b53122d6e5efc264b3c64e571e9a47d777103eaffbcdf5fb44c7743f0"),
    "mercury.html": ("generate/eclipse/mercury.html", "e29ff3e1ada11eaee343032f0c5b927ccf9a9b2cacad8e006a2bd6b4fc71ba40"),
    "venus.html": ("generate/eclipse/venus.html", "c06f2f10efc8554328bb51ed1725d13f1ec53a5a82a0c25089dcf1104994ca7f"),
    "solar_1701.html": ("generate/eclipse/se1701.html", "3c5c9d8e7acfdf48c023e4f7feb14272273121c0620b948cb106f90b6ed04a06"),
    "solar_2001.html": ("generate/eclipse/se2001.html", "820b7a9e4a04881ff212ee59603f03fb3ebdcb72e340414494b1fb84271efc9d"),
    "lunar_1701.html": ("generate/eclipse/le1701.html", "15ed1e6e6b1153f6c85e724258aa91e23655fecb08ac7623fd6e2b4b1d8199f7"),
    "lunar_1901.html": ("generate/eclipse/le1901.html", "587cf5bf48e1b9f17b0e2b6d72d42fc81828f62e9a9252d7f661a747b95154ca"),
    "lunar_2001.html": ("generate/eclipse/le2001.html", "cf12604099d2ed7766180139a4e79633ae361dd9030e2bd618f8b3eadaefde72"),
    "geo_moon_states.txt": ("generate/barystate/GeoMoon.txt", "e08885fca5fa56d6e89576dd71ff02fa0d96b8b100c6e692d17bebc88da860d0"),
    "geo_emb_states.txt": ("generate/barystate/GeoEMB.txt", "2e2fed5dac2fa94266660376b063659a46778606b4abf1b2e6003b69a87b0e9f"),
    # NASA SVS Moon Phase and Libration tables. EngineLibrationTests reads them directly; no fixture is built from them.
    "mooninfo_2020.txt": ("generate/libration/mooninfo_2020.txt", "e487d4f934724e477d4247b60b09c4da0b39d6d61a5fa92b4ac60a76a8adf1b1"),
    "mooninfo_2021.txt": ("generate/libration/mooninfo_2021.txt", "8e0e187f5993d4ba377da27f4f4fb524a1ad7b7324977f26e3adb01e5da28873"),
    "mooninfo_2022.txt": ("generate/libration/mooninfo_2022.txt", "2ab619bf7104b861c7205b52c4f22bcea2b64ce79631031b3726e508abffc4a2"),
    # JPL Horizons visual magnitude tables, 2010 to 2030 every two days, as Astronomy Engine pins them for ctest.c's
    # MagnitudeTest. EngineIlluminationTests reads them directly; no fixture is built from them.
    "magnitude_sun.txt": ("generate/magnitude/Sun.txt", "87c4afbd5dece1d61a97a97b27ec241d951afc4a9d8130633d79df2298230f61"),
    "magnitude_moon.txt": ("generate/magnitude/Moon.txt", "410de451d9d80a91eec51910580a6211e989436a5e900ef9a667f6312c76c8fc"),
    "magnitude_mercury.txt": ("generate/magnitude/Mercury.txt", "902e8a36d700f4c309791575bb0dc1f62ec89614a5bb1eedeb0c56bf56a9adf4"),
    "magnitude_venus.txt": ("generate/magnitude/Venus.txt", "4e26a87c6d37ce003e5851bc59b0a4abf69d7202c765d7cbbfd9cc3ee159a143"),
    "magnitude_mars.txt": ("generate/magnitude/Mars.txt", "744c38a99816e2f252bce80489c0523afba6b070fc0f45a51f543519cdc95894"),
    "magnitude_jupiter.txt": ("generate/magnitude/Jupiter.txt", "ab7bf7b239244ada7c11315522a8d8d5b3b9b3120bbb627813de725c3522ffc7"),
    "magnitude_uranus.txt": ("generate/magnitude/Uranus.txt", "fff69569917a255e3ffe97e3a3249e2e3205eddcd03abffb9c0ac533bdfa2ea5"),
    "magnitude_neptune.txt": ("generate/magnitude/Neptune.txt", "436ea40468af37f4062f126dc78e0c56910363b9368e109d8563fcffeb8a3d77"),
    "magnitude_pluto.txt": ("generate/magnitude/Pluto.txt", "7b7297188e8b2875432d8c6cb3cf691e97a1cf18e953662f8adf6f8919b286ca"),
    "astronomy-engine-license.txt": ("LICENSE", "a76df666a7db8a06f599d08e07c3ff74c4b250b50b49c43353af2bd5bb34604e"),
}

# Sources copied unchanged from their publishers, by full URL. EngineRotationAxisTests reads NAIF's PCK, its
# transcription of the IAU WGCCRE 2015 rotation elements (and the 2009 report's Earth and Moon), directly; no fixture
# is built from it.
PUBLISHER_SOURCES = {
    "nasa-lunar-2001-2100.html": ("https://eclipse.gsfc.nasa.gov/LEcat5/LE2001-2100.html", "0f640913669a640418f05c173cea0bdeca194fcac6b5b196b6b9ab1b08122792"),
    "nasa-oh2001.html": ("https://eclipse.gsfc.nasa.gov/OH/OH2001.html", "09a0c66a75942e594f7cd1d7b02c85a4e7f73594b8e64669a0a324926d6cb873"),
    "nasa-shadow-enlargement.html": ("https://eclipse.gsfc.nasa.gov/LEcat5/shadow.html", "95b466d625a292a16f3d6f1a3aa9e7e4fb5224a2e13b4fd9a5252ff5de20841f"),
    "nasa-svs-4953.html": ("https://svs.gsfc.nasa.gov/4953/", "e58a5ce4ebe1b59779dc931f374d8e44c5b299beaa9db5fea024065c39d61f8e"),
    "nasa-svs-5672.html": ("https://svs.gsfc.nasa.gov/5672/", "58c3f58627ad6846c41391280f8fbb90e5c7cff2623f229cfa465d5bc620af4e"),
    "constellations/iau-constellation-names.html": ("https://iauarchive.eso.org/public/themes/constellations/", "bdd1ddc5215aece2c8d54df5e2682a9fc032b176ced8262776e975896d4a9c88"),
    "constellations/roman1987-boundaries.dat": ("https://cdsarc.cds.unistra.fr/ftp/cats/VI/42/data.dat", "daf9e2b39ec57446d862a445276ae2ea50490ee455540972906098f5f9187957"),
    "constellations/roman1987-program.c": ("https://cdsarc.cds.unistra.fr/ftp/cats/VI/42/program.c", "d73f51bc51b102bf319d699bb764f0879e356205a31d22896bc2361e3162de76"),
    "constellations/roman1987-readme.txt": ("https://cdsarc.cds.unistra.fr/ftp/cats/VI/42/ReadMe", "b6a3e9ec21f902df084406e97d71754671c5787bee1cf49c109b3bc8cfc50ab9"),
    "naif/pck00011.tpc": ("https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/pck00011.tpc", "3dff7b1dbeceaa01f25467767d3fa25816051c85d162d1edf04acb310ee28bb1"),
    "sofa/sofa_ast_example.c": ("https://www.iausofa.org/s/sofa_ast_example.c", "9903dca63bd87e573db6a57c04945bb712f3c958a23c245db0c03a37bf31d4e9"),
    "sofa/sofa_c-20231011.tar.gz": ("https://www.iausofa.org/s/sofa_c-20231011tar.gz", "d9c10833cae8b4d9361a0ffda31ec361fd1262362025bec4d4e51a880150ace2"),
    "gaia/barnard-dr3.csv": ("https://gea.esac.esa.int/tap-server/tap/sync?REQUEST=doQuery&LANG=ADQL&FORMAT=csv&QUERY=SELECT+source_id%2Cra%2Cdec%2Cparallax%2Cpmra%2Cpmdec%2Cradial_velocity%2Cref_epoch+FROM+gaiadr3.gaia_source+WHERE+source_id%3D4472832130942575872", "d88558b5a525b77fcc5137974e323f711658af3dfb68a90156beead122fcf80e"),
}

SOFA_RELEASE_SHA256 = "d9c10833cae8b4d9361a0ffda31ec361fd1262362025bec4d4e51a880150ace2"
SOFA_RECIPE_SOURCES = (
    "ab.c", "af2a.c", "anp.c", "anpm.c", "apcg.c", "apci.c", "apci13.c", "apcs.c", "apio.c", "apio13.c",
    "atci13.c", "atciq.c", "atio13.c", "atioq.c", "bpn2xy.c", "c2ixys.c", "c2s.c", "cal2jd.c", "cp.c", "cr.c",
    "dat.c", "dtf2d.c", "eform.c", "eors.c", "epv00.c", "era00.c", "fad03.c", "fae03.c", "faf03.c", "faju03.c",
    "fal03.c", "falp03.c", "fama03.c", "fame03.c", "faom03.c", "fapa03.c", "fasa03.c", "faur03.c", "fave03.c", "fw2m.c",
    "gd2gc.c", "gd2gce.c", "ir.c", "jd2cal.c", "ld.c", "ldsun.c", "nut00a.c", "nut06a.c", "obl06.c", "pdp.c",
    "pfw06.c", "pm.c", "pmpx.c", "pn.c", "pnm06a.c", "pom00.c", "pvtob.c", "pxp.c", "refco.c", "rx.c",
    "rxp.c", "ry.c", "rz.c", "s06.c", "s2c.c", "sp00.c", "sxp.c", "taitt.c", "taiut1.c", "tf2a.c",
    "pmp.c", "ppp.c", "ppsp.c", "pv2s.c", "pvu.c", "pvstar.c", "s2pv.c", "starpm.c", "starpv.c", "tr.c", "trxp.c", "utctai.c", "utcut1.c", "xys06a.c", "zp.c",
)

SOFA_ANGULAR_EVENT_SOURCES = (
    "anpm.c", "cp.c", "cr.c", "ir.c", "numat.c", "nut80.c", "nutm80.c", "obl80.c", "pmat76.c",
    "pnm80.c", "prec76.c", "rx.c", "rxp.c", "rxr.c", "ry.c", "rz.c",
)

GENERATED_CONSTELLATION_PATH = ROOT / "Sources/AstronomyKit/Engine/Stars/Generated/ConstellationData.swift"

HORIZONS_OBSERVER_QUERIES = {
    "moon-observer": ("301", [2415020.5, 2451544.5, 2488069.5]),
    "mars-observer": ("499", [2415020.5, 2451544.5, 2488069.5]),
    "pluto-observer": ("999", [2415020.5, 2451544.5, 2488069.5]),
    "mercury-station": ("199", [2460897.5, 2460898.5, 2460899.5]),
    # Chiron from Earth's center: 1900-01-01 03:00 UT, once light time from the start of its supported span has passed,
    # then 1950, 2000, 2026-01-02, 2050 and 2100.
    "chiron-observer": ("2060;", [2415020.625, 2433282.5, 2451544.5, 2461042.5, 2469807.5, 2488069.5]),
}

# Elongation from the Sun with the side it falls on, and the apparent ecliptic longitude, of the Moon, Mercury, Venus,
# Mars and Jupiter every 46 days through 2026.
ELONGATION_DATES = [2461042.5 + 46 * k for k in range(8)]
HORIZONS_ELONGATION_QUERIES = {
    f"{name}-elongation": command
    for name, command in [("moon", "301"), ("mercury", "199"), ("venus", "299"), ("mars", "499"), ("jupiter", "599")]
}


def julian_grid(start: float, stop: float, step_hours: float) -> list[float]:
    count = round((stop - start) * 24 / step_hours)
    return [round(start + index * step_hours / 24, 9) for index in range(count + 1)]


RELATIVE_LONGITUDE_EVENTS = [
    {"body": "mars", "command": "499", "target": 0.0, "direction": 1, "startUTC": "2025-01-01T00:00:00Z", "dates": julian_grid(2460691.5, 2460691.75, 0.75)},
    {"body": "mars", "command": "499", "target": 180.0, "direction": 1, "startUTC": "2025-01-01T00:00:00Z", "dates": julian_grid(2461049.875, 2461050.125, 0.75)},
    {"body": "venus", "command": "299", "target": 0.0, "direction": -1, "startUTC": "2025-01-01T00:00:00Z", "dates": julian_grid(2460757.375, 2460757.625, 0.75)},
    {"body": "venus", "command": "299", "target": 180.0, "direction": -1, "startUTC": "2025-01-01T00:00:00Z", "dates": julian_grid(2461047.0, 2461047.25, 0.75)},
]

RELATIVE_LONGITUDE_VECTOR_QUERIES = {
    "earth-angular-events": ("399", sorted({date for event in RELATIVE_LONGITUDE_EVENTS for date in event["dates"]})),
    **{
        f"{body}-angular-events": (
            next(event["command"] for event in RELATIVE_LONGITUDE_EVENTS if event["body"] == body),
            sorted({date for event in RELATIVE_LONGITUDE_EVENTS if event["body"] == body for date in event["dates"]}),
        )
        for body in sorted({event["body"] for event in RELATIVE_LONGITUDE_EVENTS})
    },
}

MAX_ELONGATION_QUERIES = {
    "mercury-max-2025-03": {"body": "mercury", "command": "199", "startUTC": "2025-01-01T00:00:00Z", "dates": julian_grid(2460742.25, 2460743.25, 1.0)},
    "mercury-max-2025-04": {"body": "mercury", "command": "199", "startUTC": "2025-03-09T00:00:00Z", "dates": julian_grid(2460786.75, 2460787.75, 1.0)},
    "venus-max-2025-01": {"body": "venus", "command": "299", "startUTC": "2025-01-01T00:00:00Z", "dates": julian_grid(2460685.25, 2460686.25, 1.0)},
    "venus-max-2025-06": {"body": "venus", "command": "299", "startUTC": "2025-01-11T00:00:00Z", "dates": julian_grid(2460827.125, 2460828.125, 1.0)},
}

# The January 2100 lunar quarters from the apparent geocentric ecliptic longitudes (quantity 31) of the Moon and the Sun,
# requested in TT. USNO prints these quarters as minute-rounded UT labels and does not document the Delta T behind its
# 2100 values, so for these four rows the native phase suites gate on the Horizons TT roots instead (owner decision on
# #247, 2026-10-10); the USNO labels stay in lunarPhases. Each pair of samples is 60 s apart and brackets one root.
APPARENT_LUNAR_PHASE_EVENTS = [
    {"phase": "new", "targetDegrees": 0.0, "usnoSourceTime": "2100-01-10T12:57:00.000Z", "dates": [2488079.0405637105, 2488079.041258155]},
    {"phase": "firstQuarter", "targetDegrees": 90.0, "usnoSourceTime": "2100-01-18T12:35:00.000Z", "dates": [2488087.025321844, 2488087.0260162884]},
    {"phase": "full", "targetDegrees": 180.0, "usnoSourceTime": "2100-01-26T02:51:00.000Z", "dates": [2488094.619685392, 2488094.6203798363]},
    {"phase": "lastQuarter", "targetDegrees": 270.0, "usnoSourceTime": "2100-01-03T13:05:00.000Z", "dates": [2488072.045886119, 2488072.0465805633]},
]
APPARENT_LUNAR_PHASE_QUERIES = {"moon-apparent-phase-2100": "301", "sun-apparent-phase-2100": "10"}
# Owner-approved for these four rows only; native roots fall 0.66 to 0.82 s before the Horizons roots.
APPARENT_LUNAR_PHASE_TOLERANCE_SECONDS = 2.0

# Six Saturn body-center extrema from the source-bound #81/#132 diagnosis. Each reference is sampled at ±0.01 and ±0.005 TT days around the resolved root. The native port replays the unchanged sixty-second target; target 699 is the public planet-center semantic, never system barycenter 6.
SATURN_APSIS_REFERENCES = [
    ("apocenter", 2425931.53647080),
    ("pericenter", 2431340.87455362),
    ("pericenter", 2442055.64869819),
    ("pericenter", 2463565.54855741),
    ("apocenter", 2468907.28259141),
    ("pericenter", 2474345.48053982),
]
SATURN_APSIS_DATES = [
    *[round(root + offset, 8) for _, root in SATURN_APSIS_REFERENCES[:-1] for offset in (-0.01, -0.005, 0, 0.005, 0.01)],
    2474345.47053983, 2474345.47553982, 2474345.48053982, 2474345.48553982, 2474345.49053982,
]


def saturn_apsis_query() -> dict[str, str]:
    parameters = vector_query("699", "500@10", SATURN_APSIS_DATES)
    parameters.update({
        "CAL_TYPE": quoted("GREGORIAN"),
        "TIME_TYPE": quoted("TT"),
        "TLIST_TYPE": quoted("JD"),
        "VEC_TABLE": quoted("3"),
    })
    return parameters

# Saturn's sub-observer latitude, distances from the Sun and from Earth, and phase angle from Earth's center, from 2010
# to 2035, through the ring-plane crossing of 2025.
SATURN_RING_DATES = [2455197.5, 2456109.5, 2457023.5, 2457935.5, 2458849.5, 2459761.5, 2460676.5, 2460857.5, 2461587.5, 2462502.5, 2464328.5]

# The Sun, the Moon and Mars from the Asheville observer of JPLValidationTests (35.595 N, 82.5572 W, sea level), every
# three hours on 2026-01-02 and 2026-07-02 UT, without refraction and with Horizons' refraction model.
ASHEVILLE_SITE = "-82.5572,35.595,0"
HORIZONTAL_DATES = [2461042.5 + k * 0.125 for k in range(8)] + [2461223.5 + k * 0.125 for k in range(8)]
HORIZONS_HORIZONTAL_QUERIES = {
    f"{name}-asheville-{apparent.lower()}": (command, apparent)
    for name, command in [("sun", "10"), ("moon", "301"), ("mars", "499")]
    for apparent in ["AIRLESS", "REFRACTED"]
}

JUPITER_MOON_RELATIVE_TOLERANCE = 9e-4
JUPITER_MOON_TOLERANCE_JD_TDB_RANGE = (2_426_545.0, 2_476_545.0)
GALILEAN_DOMAIN_DATES = [2426544.0] + [2426545.0 + 2500.0 * k for k in range(21)] + [2476546.0]

BARYCENTRIC_OUTER_DATES = [2415020.5, 2424151.5, 2433282.5, 2442413.5, 2451544.5, 2460676.5, 2469807.5, 2478938.5, 2487704.5]
BARYCENTRIC_INNER_DATES = [2444239.5, 2447892.5, 2451544.5, 2455197.5, 2458849.5]
BARYCENTRIC_LUNAR_DATES = [2440587.5, 2446066.5, 2451544.5, 2458849.5, 2466154.5]

HORIZONS_VECTOR_QUERIES = {
    "chiron-vector": ("2060;", "500@10", [2415020.5, 2451544.5, 2488069.5]),
    # Chiron at the five anchors the engine starts from (2000 to 2040), at each midpoint between neighboring anchors,
    # where the nearest anchor changes, with a day either side, and at the ends of the supported span, 1900-01-01 and
    # 2150-01-01.
    "chiron-anchor-vector": ("2060;", "500@10", [2415020.5, 2451544.5, 2453370.0, 2453371.0, 2453372.0, 2455197.5, 2457022.5, 2457023.5, 2457024.5, 2458849.5, 2460675.0, 2460676.0, 2460677.0, 2462502.5, 2464327.5, 2464328.5, 2464329.5, 2466154.5, 2506331.5]),
    "io-vector": ("501", "500@599", [2415020.5, 2451544.5, 2488069.5]),
    "europa-vector": ("502", "500@599", [2415020.5, 2451544.5, 2488069.5]),
    "ganymede-vector": ("503", "500@599", [2415020.5, 2451544.5, 2488069.5]),
    "callisto-vector": ("504", "500@599", [2415020.5, 2451544.5, 2488069.5]),
    # The Galilean moons through the span Astronomy Engine's 9e-4 threshold was set on: both ends, every 2,500 days
    # between them, and a day outside each end, where no threshold applies.
    **{
        f"{name}-domain-vector": (command, "500@599", GALILEAN_DOMAIN_DATES)
        for name, command in [("io", "501"), ("europa", "502"), ("ganymede", "503"), ("callisto", "504")]
    },
    # The Moon outside the DE440 Moon's span and across the 32-day blends at 1900 and 2131, out to the accepted-range ends.
    "moon-vector": ("301", "500@399", [990546.0, 990910.5, 1173170.5, 1355795.5, 1538420.5, 1721045.5, 1903670.5, 2086295.5, 2268920.5, 2341970.5, 2378495.5, 2396758.5, 2414980.5, 2414996.5, 2415004.5, 2415012.5, 2415019.5, 2415021.5, 2499390.5, 2499392.5, 2499407.5, 2499422.5, 2499430.5, 2524595.5, 2634170.5, 2816795.5, 3182045.5, 3547295.5, 3912180.5, 3912544.0]),
    # Pluto's center across both 32-day blends at 1900 and 2131, at seams of the DE440 and PLU060 records and of the
    # integrated model's segments and steps inside Horizons' 1800 to 2200 span for Pluto, with samples a day apart.
    "pluto-vector": ("999", "500@10", [2393144.0, 2393145.0, 2393146.0, 2407744.0, 2407745.0, 2407746.0, 2407818.0, 2414980.5, 2414988.5, 2414996.5, 2415004.5, 2415012.5, 2415020.5, 2415021.5, 2451536.5, 2451544.5, 2451545.0, 2456292.5, 2456293.5, 2456294.5, 2499391.5, 2499399.5, 2499407.5, 2499415.5, 2499423.5, 2499431.5, 2509944.0, 2509945.0, 2509946.0]),
    # The Pluto system barycenter where Horizons has no Pluto center: the integrated model's first and last tabulated
    # states with a day either side, a segment seam in 800 CE and a step seam in 840 CE, and the ends of the extrapolation beyond the
    # table, 100 years before the first state and after the last.
    "pluto-barycenter-vector": ("9", "500@10", [1685020.5, 1721544.0, 1721545.0, 1721546.0, 2013544.0, 2013545.0, 2013546.0, 2028144.0, 2028145.0, 2028146.0, 2028218.0, 3181544.0, 3181545.0, 3181546.0, 3218069.5]),
    # The Pluto system barycenter on 1990-01-01, 2000-01-01, 2001-01-01 and 2010-01-01: the gravity simulation starts from
    # the 2000 state and steps forward and backward to the others.
    "pluto-barycenter-decade": ("9", "500@10", [2447892.5, 2451544.5, 2451910.5, 2455197.5]),
    # Barycentric states for Astronomy Engine's BaryStateTest limits (ctest.c), inside the span each limit was set on:
    # 1900 to 2099 every 25 years for the Sun, the outer planets and Pluto's center (its file holds the Pluto system
    # barycenter to 2099), 1980 to 2020 every 10 years for Mercury to Mars, and 1970 to 2040 for the Moon and the
    # Earth-Moon barycenter.
    **{
        f"{name}-barycentric-vector": (command, "500@0", dates)
        for name, command, dates in [
            ("sun", "10", BARYCENTRIC_OUTER_DATES),
            ("mercury", "199", BARYCENTRIC_INNER_DATES),
            ("venus", "299", BARYCENTRIC_INNER_DATES),
            ("earth", "399", BARYCENTRIC_INNER_DATES),
            ("mars", "499", BARYCENTRIC_INNER_DATES),
            ("jupiter", "599", BARYCENTRIC_OUTER_DATES),
            ("saturn", "699", BARYCENTRIC_OUTER_DATES),
            ("uranus", "799", BARYCENTRIC_OUTER_DATES),
            ("neptune", "899", BARYCENTRIC_OUTER_DATES),
            ("pluto", "999", BARYCENTRIC_OUTER_DATES),
            ("moon", "301", BARYCENTRIC_LUNAR_DATES),
            ("emb", "3", BARYCENTRIC_LUNAR_DATES),
        ]
    },
}

RISE_SET_ROW_COUNT = 5_909
# Limits from Astronomy Engine's C test harness, generate/ctest.c at UPSTREAM_REVISION (865d3da7): MoonPhase 90 s, LunarEclipseTest 2 min, RiseSet 1.18 min.
LUNAR_PHASE_TOLERANCE_SECONDS = 90.0
LUNAR_ECLIPSE_TOLERANCE_SECONDS = 120.0
RISE_SET_TOLERANCE_SECONDS = 70.8
# VerifyStateBody limits in the same ctest.c for barystate/GeoMoon.txt and barystate/GeoEMB.txt: relative position and velocity error.
GEOCENTRIC_STATE_TOLERANCES = {"moon": (4.086e-05, 5.347e-05), "emb": (4.076e-05, 5.335e-05)}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "AstronomyKit independent reference fixture generator"})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except OSError as error:
            last_error = error
            if attempt < 2:
                time.sleep(1 << attempt)
    raise RuntimeError(f"download failed after three attempts: {url}: {last_error}")


def quoted(value: str) -> str:
    return f"'{value}'"


def horizons_url(parameters: dict[str, str]) -> str:
    return "https://ssd.jpl.nasa.gov/api/horizons.api?" + urllib.parse.urlencode({"format": "json", **parameters})


def observer_query(command: str, julian_dates: list[float]) -> dict[str, str]:
    return {
        "COMMAND": quoted(command),
        "OBJ_DATA": quoted("NO"),
        "MAKE_EPHEM": quoted("YES"),
        "EPHEM_TYPE": quoted("OBSERVER"),
        "CENTER": quoted("500@399"),
        "TLIST": quoted(",".join(str(value) for value in julian_dates)),
        "QUANTITIES": quoted("1,3,20,31"),
        "REF_SYSTEM": quoted("ICRF"),
        "CAL_FORMAT": quoted("CAL"),
        "TIME_DIGITS": quoted("SECONDS"),
        "ANG_FORMAT": quoted("DEG"),
        "APPARENT": quoted("AIRLESS"),
        "RANGE_UNITS": quoted("AU"),
        "CSV_FORMAT": quoted("YES"),
    }


def vector_query(command: str, center: str, julian_dates: list[float]) -> dict[str, str]:
    return {
        "COMMAND": quoted(command),
        "OBJ_DATA": quoted("NO"),
        "MAKE_EPHEM": quoted("YES"),
        "EPHEM_TYPE": quoted("VECTORS"),
        "CENTER": quoted(center),
        "TLIST": quoted(",".join(str(value) for value in julian_dates)),
        "REF_SYSTEM": quoted("ICRF"),
        "REF_PLANE": quoted("FRAME"),
        "OUT_UNITS": quoted("AU-D"),
        "VEC_TABLE": quoted("2"),
        "VEC_CORR": quoted("NONE"),
        "CSV_FORMAT": quoted("YES"),
    }


def geocentric_query(command: str, quantities: str, julian_dates: list[float]) -> dict[str, str]:
    return {
        "COMMAND": quoted(command),
        "OBJ_DATA": quoted("NO"),
        "MAKE_EPHEM": quoted("YES"),
        "EPHEM_TYPE": quoted("OBSERVER"),
        "CENTER": quoted("500@399"),
        "TLIST": quoted(",".join(str(value) for value in julian_dates)),
        "QUANTITIES": quoted(quantities),
        "CAL_FORMAT": quoted("CAL"),
        "TIME_DIGITS": quoted("SECONDS"),
        "ANG_FORMAT": quoted("DEG"),
        "EXTRA_PREC": quoted("YES"),
        "CSV_FORMAT": quoted("YES"),
    }


def angular_elongation_query(command: str, julian_dates: list[float]) -> dict[str, str]:
    parameters = geocentric_query(command, "23", julian_dates)
    parameters["APPARENT"] = quoted("AIRLESS")
    return parameters


def apparent_lunar_phase_query(command: str) -> dict[str, str]:
    parameters = geocentric_query(command, "31", [date for event in APPARENT_LUNAR_PHASE_EVENTS for date in event["dates"]])
    parameters.update({
        "APPARENT": quoted("AIRLESS"),
        "RANGE_UNITS": quoted("AU"),
        "REF_SYSTEM": quoted("ICRF"),
        "TIME_TYPE": quoted("TT"),
    })
    return parameters


def horizontal_query(command: str, apparent: str, julian_dates: list[float]) -> dict[str, str]:
    return {
        "COMMAND": quoted(command),
        "OBJ_DATA": quoted("NO"),
        "MAKE_EPHEM": quoted("YES"),
        "EPHEM_TYPE": quoted("OBSERVER"),
        "CENTER": quoted("coord@399"),
        "COORD_TYPE": quoted("GEODETIC"),
        "SITE_COORD": quoted(ASHEVILLE_SITE),
        "TLIST": quoted(",".join(str(value) for value in julian_dates)),
        "QUANTITIES": quoted("4"),
        "CAL_FORMAT": quoted("CAL"),
        "TIME_DIGITS": quoted("SECONDS"),
        "ANG_FORMAT": quoted("DEG"),
        "EXTRA_PREC": quoted("YES"),
        "APPARENT": quoted(apparent),
        "CSV_FORMAT": quoted("YES"),
    }


def horizons_acquisitions() -> list[tuple[str, dict[str, str]]]:
    acquisitions = [
        (name, observer_query(command, dates))
        for name, (command, dates) in HORIZONS_OBSERVER_QUERIES.items()
    ]
    acquisitions.extend(
        (name, vector_query(command, center, dates))
        for name, (command, center, dates) in HORIZONS_VECTOR_QUERIES.items()
    )
    acquisitions.extend(
        (name, vector_query(command, "500@10", dates))
        for name, (command, dates) in RELATIVE_LONGITUDE_VECTOR_QUERIES.items()
    )
    acquisitions.extend(
        (name, horizontal_query(command, apparent, HORIZONTAL_DATES))
        for name, (command, apparent) in HORIZONS_HORIZONTAL_QUERIES.items()
    )
    acquisitions.extend(
        (name, geocentric_query(command, "23,31", ELONGATION_DATES))
        for name, command in HORIZONS_ELONGATION_QUERIES.items()
    )
    acquisitions.extend(
        (name, angular_elongation_query(event["command"], event["dates"]))
        for name, event in MAX_ELONGATION_QUERIES.items()
    )
    acquisitions.extend(
        (name, apparent_lunar_phase_query(command))
        for name, command in APPARENT_LUNAR_PHASE_QUERIES.items()
    )
    acquisitions.append(("saturn-apsis-precision", saturn_apsis_query()))
    acquisitions.append(("saturn-rings", geocentric_query("699", "14,19,20,24", SATURN_RING_DATES)))
    return acquisitions


def validate_horizons_response(name: str, data: bytes) -> None:
    try:
        envelope = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid Horizons response {name}: {error}") from error
    result = envelope.get("result")
    if not isinstance(result, str) or "$$SOE\n" not in result or "$$EOE" not in result:
        raise RuntimeError(f"Horizons response {name} has no complete result table")


def pinned_sources() -> list[tuple[str, str, str]]:
    """Each pinned source file: its path under SOURCE_DIR, its URL and its SHA-256."""
    upstream = [(name, f"{UPSTREAM_BASE}/{path}", digest) for name, (path, digest) in UPSTREAM_SOURCES.items()]
    return upstream + [(name, url, digest) for name, (url, digest) in PUBLISHER_SOURCES.items()]


def refresh_sources() -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    writes: dict[Path, bytes] = {}
    for local_name, url, expected_hash in pinned_sources():
        destination = SOURCE_DIR / local_name
        if destination.exists() and sha256(destination.read_bytes()) == expected_hash:
            continue
        data = download(url)
        actual_hash = sha256(data)
        if actual_hash != expected_hash:
            raise RuntimeError(f"source hash changed for {url}: expected {expected_hash}, got {actual_hash}")
        writes[destination] = data
    horizons_dir = SOURCE_DIR / "horizons"
    horizons_dir.mkdir(parents=True, exist_ok=True)
    for name, parameters in horizons_acquisitions():
        response = download(horizons_url(parameters))
        validate_horizons_response(name, response)
        writes[horizons_dir / f"{name}.json"] = response
        recipe = {**parameters, "_responseSHA256": sha256(response)}
        writes[horizons_dir / f"{name}.query.json"] = encoded(recipe)
    for path, data in writes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def verify_recorded_queries(directory: Path | None = None) -> None:
    """Check each recorded Horizons response in sources/jpl-validation against its recipe's SHA-256.

    Tests read these tables directly; no fixture is built from them.
    """
    directory = directory or SOURCE_DIR / "jpl-validation"
    for response_path in sorted(directory.glob("*.json")):
        if response_path.name.endswith(".query.json"):
            continue
        recipe_path = response_path.with_name(response_path.stem + ".query.json")
        if not recipe_path.exists():
            raise RuntimeError(f"recorded Horizons response without a recipe: {response_path}")
        expected = json.loads(recipe_path.read_text()).get("_responseSHA256")
        if sha256(response_path.read_bytes()) != expected:
            raise RuntimeError(f"recorded Horizons response hash mismatch: {response_path}")


def verify_sources() -> list[dict[str, str]]:
    records = []
    for local_name, url, expected_hash in pinned_sources():
        path = SOURCE_DIR / local_name
        if not path.exists():
            raise RuntimeError(f"missing source snapshot: {path}; run with --refresh")
        actual_hash = sha256(path.read_bytes())
        if actual_hash != expected_hash:
            raise RuntimeError(f"source snapshot hash mismatch for {path}: expected {expected_hash}, got {actual_hash}")
        records.append({"path": str(path.relative_to(ROOT)), "sha256": actual_hash, "url": url})
    for name, parameters in horizons_acquisitions():
        response_path = SOURCE_DIR / "horizons" / f"{name}.json"
        recipe_path = SOURCE_DIR / "horizons" / f"{name}.query.json"
        if not response_path.exists() or not recipe_path.exists():
            raise RuntimeError(f"missing Horizons response/recipe pair: {name}; run with --refresh")
        response = response_path.read_bytes()
        validate_horizons_response(name, response)
        expected_recipe = {**parameters, "_responseSHA256": sha256(response)}
        if json.loads(recipe_path.read_text()) != expected_recipe:
            raise RuntimeError(f"Horizons recipe or response hash mismatch for {name}")
    for path in sorted((SOURCE_DIR / "horizons").glob("*.json")):
        records.append({"path": str(path.relative_to(ROOT)), "sha256": sha256(path.read_bytes()), "url": "generated from the adjacent query recipe"})
    return records


def source_text(name: str) -> str:
    return (SOURCE_DIR / name).read_text()


def selected_lines(name: str, predicate) -> list[str]:
    return [line for line in source_text(name).splitlines() if predicate(line)]


def parse_rise_set() -> list[dict[str, object]]:
    pattern = re.compile(
        r"^(Sun|Moon)\s+([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s+"
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z)\s+([rs])$"
    )
    rows: list[dict[str, object]] = []
    seen_groups: set[tuple[str, float, float, int]] = set()
    current_group: tuple[str, float, float, int] | None = None
    previous_time: datetime.datetime | None = None
    previous_direction: str | None = None
    for line_number, line in enumerate(source_text("riseset.txt").splitlines(), 1):
        match = pattern.fullmatch(line)
        if match is None:
            raise RuntimeError(f"invalid rise/set record at line {line_number}: {line!r}")
        body, longitude_text, latitude_text, timestamp, direction = match.groups()
        try:
            event_time = datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%MZ")
        except ValueError as error:
            raise RuntimeError(f"invalid rise/set timestamp at line {line_number}: {timestamp}") from error
        longitude = float(longitude_text)
        latitude = float(latitude_text)
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise RuntimeError(f"invalid rise/set coordinates at line {line_number}")
        group = (body, longitude, latitude, event_time.year)
        if group != current_group:
            if group in seen_groups:
                raise RuntimeError(f"noncontiguous rise/set group at line {line_number}")
            seen_groups.add(group)
            current_group = group
            previous_time = None
            previous_direction = None
        if previous_time is not None and event_time <= previous_time:
            raise RuntimeError(f"rise/set group is not chronological at line {line_number}")
        if previous_direction == direction:
            raise RuntimeError(f"rise/set directions do not alternate at line {line_number}")
        rows.append(
            {
                "sourceLine": line_number,
                "body": body.lower(),
                "longitudeDegrees": longitude,
                "latitudeDegrees": latitude,
                "utc": timestamp,
                "direction": "rise" if direction == "r" else "set",
                "timeToleranceSeconds": RISE_SET_TOLERANCE_SECONDS,
            }
        )
        previous_time = event_time
        previous_direction = direction
    if len(rows) != RISE_SET_ROW_COUNT:
        raise RuntimeError(
            f"rise/set table has {len(rows)} records; expected {RISE_SET_ROW_COUNT}"
        )
    return rows


def parse_upstream_events() -> dict[str, list[dict[str, object]]]:
    seasons = []
    for line in selected_lines("seasons.txt", lambda item: item[:4] in {"1800", "2000", "2100"} and ("Equinox" in item or "Solstice" in item)):
        timestamp, kind = line.split()
        month = int(timestamp[5:7])
        event = {3: "marchEquinox", 6: "juneSolstice", 9: "septemberEquinox", 12: "decemberSolstice"}[month]
        seasons.append({"event": event, "utc": timestamp, "toleranceSeconds": 142.2})

    phases = []
    phase_names = {0: "new", 1: "firstQuarter", 2: "full", 3: "lastQuarter"}
    by_year_and_quarter: dict[tuple[int, int], dict[str, object]] = {}
    for line in source_text("moonphases.txt").splitlines():
        quarter_text, timestamp = line.split()
        year, quarter = int(timestamp[:4]), int(quarter_text)
        if year in {1800, 2000, 2100}:
            by_year_and_quarter.setdefault((year, quarter), {"phase": phase_names[quarter], "sourceTime": timestamp, "toleranceSeconds": LUNAR_PHASE_TOLERANCE_SECONDS})
    phases.extend(by_year_and_quarter[key] for key in sorted(by_year_and_quarter))

    nodes = []
    node_pattern = re.compile(r"^([AD]) (\S+)\s+([\d.]+)\s+([\-\d.]+)$")
    node_seen: set[tuple[int, str]] = set()
    for line in source_text("moon_nodes.txt").splitlines():
        match = node_pattern.match(line)
        if not match:
            continue
        year, kind = int(match.group(2)[:4]), match.group(1)
        key = (year, kind)
        if year in {2001, 2050, 2100} and key not in node_seen:
            node_seen.add(key)
            nodes.append({"kind": "ascending" if kind == "A" else "descending", "utc": match.group(2), "rightAscensionHours": float(match.group(3)), "declinationDegrees": float(match.group(4)), "timeToleranceSeconds": 220.86, "positionToleranceArcminutes": 1.54})

    def parse_apsides(name: str, years: set[int], moon: bool) -> list[dict[str, object]]:
        result = []
        seen: set[tuple[int, int]] = set()
        for line in source_text(name).splitlines():
            kind_text, timestamp, distance_text = line.split()
            year, kind = int(timestamp[:4]), int(kind_text)
            key = (year, kind)
            if year in years and key not in seen:
                seen.add(key)
                item: dict[str, object] = {"kind": "pericenter" if kind == 0 else "apocenter", "utc": timestamp, "timeToleranceSeconds": 2100.0 if moon else 7234.8}
                item["distanceKM" if moon else "distanceAU"] = float(distance_text)
                item["distanceToleranceKM" if moon else "distanceToleranceAU"] = 25.0 if moon else 1.2e-5
                result.append(item)
        return result

    return {
        "seasons": seasons,
        "lunarPhases": phases,
        "lunarNodes": nodes,
        "lunarApsides": parse_apsides("moon_apsides.txt", {2001, 2050, 2100}, True),
        "earthApsides": parse_apsides("earth_apsides.txt", {2001, 2050, 2100}, False),
        "riseSet": parse_rise_set(),
    }


def parse_geocentric_states() -> dict[str, list[dict[str, object]]]:
    """Every Horizons state in Astronomy Engine's GeoMoon.txt and GeoEMB.txt, with the harness's relative limits."""
    states = []
    for name, body in (("geo_moon_states.txt", "moon"), ("geo_emb_states.txt", "emb")):
        position_tolerance, velocity_tolerance = GEOCENTRIC_STATE_TOLERANCES[body]
        lines = data_lines(source_text(name))
        if len(lines) % 3:
            raise RuntimeError(f"{name}: incomplete state record")
        for index in range(0, len(lines), 3):
            julian_date = float(lines[index].split("=", 1)[0])
            position = [float(value) for value in re.findall(r"=\s*(\S+)", lines[index + 1])]
            velocity = [float(value) for value in re.findall(r"=\s*(\S+)", lines[index + 2])]
            if len(position) != 3 or len(velocity) != 3:
                raise RuntimeError(f"{name}: unreadable state at JD {julian_date}")
            states.append({"body": body, "julianDateTDB": julian_date, "positionAU": position, "velocityAUPerDay": velocity, "relativePositionTolerance": position_tolerance, "relativeVelocityTolerance": velocity_tolerance})
    return {"geocentricStates": states}


def parse_eclipses() -> dict[str, list[dict[str, object]]]:
    month = {name: index + 1 for index, name in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
    lunar_pattern = re.compile(r"^\s{2}(\d{4})\s+(\w{3})\s+(\d{2})\s+(\d{2}):(\d{2})\s+(\S+)\s+\d+\s+([+-]?\d+\.\d+)\s+(\d+\.\d+)\s+([+-]?\d+\.\d+)\s+(\d+m|-)\s+(\d+m|-)")
    lunar_kinds = {"N": "penumbral", "P": "partial", "T": "total"}
    wanted_lunar_dates = {(1800, "Apr", 9), (2000, "Jan", 21), (2001, "Jan", 9), (2001, "Jul", 5), (2001, "Dec", 30), (2099, "Apr", 5)}
    lunar = []
    for name in ("lunar_1701.html", "lunar_1901.html", "lunar_2001.html"):
        for line in source_text(name).splitlines():
            match = lunar_pattern.match(line)
            if not match or (int(match.group(1)), match.group(2), int(match.group(3))) not in wanted_lunar_dates:
                continue
            partial = 0 if match.group(10) == "-" else int(match.group(10)[:-1])
            total = 0 if match.group(11) == "-" else int(match.group(11)[:-1])
            lunar.append({"universalTime": f"{match.group(1)}-{month[match.group(2)]:02d}-{int(match.group(3)):02d}T{int(match.group(4)):02d}:{int(match.group(5)):02d}Z", "kind": lunar_kinds[match.group(6)[0]], "gammaEarthRadii": float(match.group(7)), "penumbralMagnitude": float(match.group(8)), "umbralMagnitude": float(match.group(9)), "partialSemiDurationMinutes": partial, "totalSemiDurationMinutes": total, "toleranceSeconds": LUNAR_ECLIPSE_TOLERANCE_SECONDS, "durationToleranceMinutes": LUNAR_ECLIPSE_TOLERANCE_SECONDS / 60})

    detailed_pattern = re.compile(r'name=LE(2001)(\w{3})(\d{2})([TPN])>.*?<pre>(.*?)</pre>', re.DOTALL)
    contact_pattern = re.compile(r"(Penumbral Eclipse Begins|Partial Eclipse Begins|Total Eclipse Begins|Greatest Eclipse|Total Eclipse Ends|Partial Eclipse Ends|Penumbral Eclipse Ends):\s+(\d{2}):(\d{2}):(\d{2}) UT")

    def clock_minutes(value: tuple[str, str, str]) -> float:
        return int(value[0]) * 60 + int(value[1]) + int(value[2]) / 60

    for match in detailed_pattern.finditer(source_text("nasa-oh2001.html")):
        date = f"{match.group(1)}-{month[match.group(2)]:02d}-{int(match.group(3)):02d}"
        contacts = {label: (hour, minute, second) for label, hour, minute, second in contact_pattern.findall(match.group(5))}
        reference = next((item for item in lunar if item["universalTime"].startswith(date)), None)
        if reference is None:
            continue
        greatest = contacts["Greatest Eclipse"]
        reference["universalTime"] = f"{date}T{greatest[0]}:{greatest[1]}:{greatest[2]}Z"
        if clock_minutes(contacts["Penumbral Eclipse Ends"]) <= clock_minutes(contacts["Penumbral Eclipse Begins"]):
            raise RuntimeError(f"NASA OH2001 has invalid contacts for {date}")

    modern_text = re.sub(r"<[^>]+>", "", source_text("nasa-lunar-2001-2100.html"))
    if "Danjon's enlargement method" not in modern_text:
        raise RuntimeError("modern NASA lunar catalog does not identify its shadow convention")
    modern_pattern = re.compile(r"^\s*\d+\s+(2001)\s+(\w{3})\s+(\d{2})\s+\d{2}:\d{2}:\d{2}\s+\d+\s+\d+\s+\d+\s+[TPN]\S*\s+\S+\s+[+-]?\d+\.\d+\s+\d+\.\d+\s+[+-]?\d+\.\d+\s+(\d+\.\d+)\s+(\d+\.\d+|-)\s+(\d+\.\d+|-)", re.MULTILINE)
    modern_count = 0
    for match in modern_pattern.finditer(modern_text):
        date = f"{match.group(1)}-{month[match.group(2)]:02d}-{int(match.group(3)):02d}"
        reference = next((item for item in lunar if item["universalTime"].startswith(date)), None)
        if reference is None:
            continue
        reference["penumbralSemiDurationMinutes"] = float(match.group(4)) / 2
        reference["partialSemiDurationMinutes"] = 0 if match.group(5) == "-" else float(match.group(5)) / 2
        reference["totalSemiDurationMinutes"] = 0 if match.group(6) == "-" else float(match.group(6)) / 2
        modern_count += 1

    if len(lunar) != len(wanted_lunar_dates) or modern_count != 3:
        raise RuntimeError("lunar eclipse sources are incomplete")

    solar_pattern = re.compile(r'^<a\s+href="[^"]+">\d+</a>\s+(\d{4})\s+(\w{3})\s+(\d{2})\s+(\d{2}):(\d{2}):(\d{2})\s+-?\d+\s+\S+\s+<a\s+href="[^"]+">\d+</a>\s+([PATH])\S?\s+\S+\s+\S+\s+(\d+\.\d[NS])\s+(\d+\.\d[EW])')
    solar = []
    kind_names = {"P": "partial", "A": "annular", "T": "total", "H": "total"}
    for name in ("solar_1701.html", "solar_2001.html"):
        for line in source_text(name).splitlines():
            match = solar_pattern.match(line)
            if not match or int(match.group(1)) not in {1800, 2024, 2099}:
                continue
            year = int(match.group(1))
            if any(item["terrestrialTime"].startswith(str(year)) for item in solar):
                continue
            latitude = float(match.group(8)[:-1]) * (1 if match.group(8)[-1] == "N" else -1)
            longitude = float(match.group(9)[:-1]) * (1 if match.group(9)[-1] == "E" else -1)
            solar.append({"terrestrialTime": f"{year:04d}-{month[match.group(2)]:02d}-{int(match.group(3)):02d}T{int(match.group(4)):02d}:{int(match.group(5)):02d}:{int(match.group(6)):02d}Z", "kind": kind_names[match.group(7)], "latitudeDegrees": latitude, "longitudeDegrees": longitude, "timeToleranceSeconds": 453.6, "locationToleranceDegrees": 0.247})

    transit_pattern = re.compile(r"^\s*(\d+)\s+(\w{3})\s+(\d+)\s+(\d+):(\d+)\s+\S+\s+(\d+):(\d+)\s+\S+\s+(\d+):(\d+)\s+([\d.]+)")
    transits = []
    wanted = {("mercury", 2003), ("mercury", 2019), ("mercury", 2049), ("venus", 2012), ("venus", 2117), ("venus", 2125)}
    for body in ("mercury", "venus"):
        for line in source_text(f"{body}.html").splitlines():
            match = transit_pattern.match(line)
            if not match:
                continue
            year = int(match.group(1))
            if (body, year) not in wanted:
                continue
            day, month_value = int(match.group(3)), month[match.group(2)]
            start_hour, start_minute = int(match.group(4)), int(match.group(5))
            peak_hour, peak_minute = int(match.group(6)), int(match.group(7))
            finish_hour, finish_minute = int(match.group(8)), int(match.group(9))
            start_day = day - 1 if (start_hour, start_minute) > (peak_hour, peak_minute) else day
            finish_day = day + 1 if (finish_hour, finish_minute) < (peak_hour, peak_minute) else day
            transits.append({"body": body, "startUTC": f"{year:04d}-{month_value:02d}-{start_day:02d}T{start_hour:02d}:{start_minute:02d}Z", "peakUTC": f"{year:04d}-{month_value:02d}-{day:02d}T{peak_hour:02d}:{peak_minute:02d}Z", "finishUTC": f"{year:04d}-{month_value:02d}-{finish_day:02d}T{finish_hour:02d}:{finish_minute:02d}Z", "separationArcminutes": float(match.group(10)) / 60.0, "timeToleranceSeconds": 642.6 if body == "mercury" else 546.54, "separationToleranceArcminutes": 0.2121 if body == "mercury" else 0.6772})

    local_solar = []
    wanted_observers = {(29.0181, -80.9481), (41.0341, -83.6523), (-48.2051, -70.6549)}
    local_pattern = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+([PAT])\s+(\S+)\s+(-?\d+(?:\.\d+)?)\s+(\S+)\s+(-?\d+(?:\.\d+)?)\s+(\S+)\s+(-?\d+(?:\.\d+)?)\s+(\S+)\s+(-?\d+(?:\.\d+)?)\s+(\S+)\s+(-?\d+(?:\.\d+)?)$")
    local_kind_names = {"P": "partial", "A": "annular", "T": "total"}
    for line in source_text("local_solar_eclipse.txt").splitlines():
        match = local_pattern.match(line)
        if not match:
            continue
        latitude = float(match.group(1))
        longitude = float(match.group(2))
        if (latitude, longitude) not in wanted_observers:
            continue
        item: dict[str, object] = {
            "latitudeDegrees": latitude,
            "longitudeDegrees": longitude,
            "kind": local_kind_names[match.group(3)],
            "partialBeginUTC": match.group(4),
            "partialBeginAltitudeDegrees": float(match.group(5)),
            "peakUTC": match.group(8),
            "peakAltitudeDegrees": float(match.group(9)),
            "partialEndUTC": match.group(12),
            "partialEndAltitudeDegrees": float(match.group(13)),
            "timeToleranceSeconds": 60.0,
            "altitudeToleranceDegrees": 0.5,
        }
        if match.group(6) != "-":
            item["totalBeginUTC"] = match.group(6)
            item["totalBeginAltitudeDegrees"] = float(match.group(7))
            item["totalEndUTC"] = match.group(10)
            item["totalEndAltitudeDegrees"] = float(match.group(11))
        local_solar.append(item)

    obscurations = []
    for name, universal_time, percent in (
        ("nasa-svs-4953.html", "2021-11-19T09:03Z", 99.1),
        ("nasa-svs-5672.html", "2026-08-28T04:13Z", 96.3),
    ):
        text = source_text(name)
        if f"{percent:.1f}% of the Moon" not in text:
            raise RuntimeError(f"{name}: missing published lunar obscuration")
        if name.endswith("5672.html") and "Obscuration Versus Magnitude" not in text:
            raise RuntimeError(f"{name}: missing obscuration definition")
        value = percent / 100
        obscurations.append({"universalTimeSearchSeed": universal_time, "obscuration": value, "roundingLowerBound": value - 0.0005, "roundingUpperBound": value + 0.0005, "peakToleranceSeconds": 120.0})

    return {"lunarEclipses": lunar, "lunarEclipseObscurations": obscurations, "globalSolarEclipses": solar, "localSolarEclipses": local_solar, "transits": transits}


def horizons_result(name: str) -> str:
    envelope = json.loads((SOURCE_DIR / "horizons" / f"{name}.json").read_text())
    if "result" not in envelope:
        raise RuntimeError(f"Horizons response {name} has no result")
    return envelope["result"]


def data_lines(result: str) -> list[str]:
    return result.split("$$SOE\n", 1)[1].split("$$EOE", 1)[0].strip().splitlines()


def sofa_angular_event_longitudes(samples: list[tuple[float, float, float, float]]) -> list[float]:
    archive_path = SOURCE_DIR / "sofa/sofa_c-20231011.tar.gz"
    if sha256(archive_path.read_bytes()) != SOFA_RELEASE_SHA256:
        raise RuntimeError("SOFA angular-event release hash mismatch")
    with tempfile.TemporaryDirectory() as temporary:
        source_dir = Path(temporary) / "sofa"
        source_dir.mkdir()
        archive_prefix = "sofa/20231011/c/src/"
        with tarfile.open(archive_path, "r:gz") as archive:
            for name in ("sofa.h", "sofam.h", *SOFA_ANGULAR_EVENT_SOURCES):
                source = archive.extractfile(archive.getmember(archive_prefix + name))
                if source is None:
                    raise RuntimeError(f"SOFA angular-event release has no {name}")
                (source_dir / name).write_bytes(source.read())
        executable = Path(temporary) / "sofa-angular-events"
        compiler = shlex.split(os.environ.get("CC", "cc"))
        if not compiler:
            raise RuntimeError("SOFA angular-event recipe compiler is empty")
        compilation = subprocess.run(
            compiler
            + [
                "-std=c99", "-O", f"-I{source_dir}",
                str(ROOT / "Scripts/reference-data/sofa-angular-events.c"),
                *(str(source_dir / name) for name in SOFA_ANGULAR_EVENT_SOURCES),
                "-lm", "-o", str(executable),
            ],
            capture_output=True,
            text=True,
        )
        if compilation.returncode != 0:
            raise RuntimeError(f"SOFA angular-event recipe compilation failed: {compilation.stderr.strip()}")
        input_text = "".join(f"{date:.17g} {x:.17g} {y:.17g} {z:.17g}\n" for date, x, y, z in samples)
        execution = subprocess.run([str(executable)], input=input_text, capture_output=True, text=True)
        if execution.returncode != 0:
            raise RuntimeError(f"SOFA angular-event recipe execution failed: {execution.stderr.strip()}")
    rows = [line.split() for line in execution.stdout.splitlines()]
    if len(rows) != len(samples):
        raise RuntimeError("SOFA angular-event recipe row count mismatch")
    longitudes = []
    for sample, row in zip(samples, rows):
        if len(row) != 2 or float(row[0]) != sample[0]:
            raise RuntimeError("SOFA angular-event recipe date mismatch")
        longitude = float(row[1])
        if not 0 <= longitude < 360:
            raise RuntimeError("SOFA angular-event recipe returned an invalid longitude")
        longitudes.append(longitude)
    return longitudes


def wrapped_degrees(value: float) -> float:
    return (value + 180) % 360 - 180


def validate_horizons_ut_timestamp(name: str, row_index: int, timestamp: str, julian_date_ut: float, label: str = "maximum-elongation", scale: str = "UT") -> None:
    match = re.fullmatch(r"\d{4}-[A-Z][a-z]{2}-\d{2} \d{2}:\d{2}:\d{2}\.(\d+)", timestamp)
    if match is None:
        raise RuntimeError(f"unreadable {label} timestamp in {name} row {row_index}: {timestamp!r}")
    returned = datetime.datetime.strptime(timestamp, "%Y-%b-%d %H:%M:%S.%f")
    j2000 = datetime.datetime(2000, 1, 1, 12)
    returned_seconds = (returned - j2000).total_seconds()
    requested_seconds = (julian_date_ut - 2_451_545.0) * 86_400
    displayed_precision_seconds = 10 ** -len(match.group(1))
    if abs(returned_seconds - requested_seconds) > displayed_precision_seconds / 2 + 1e-6:
        raise RuntimeError(
            f"{label} timestamp mismatch in {name} row {row_index}: "
            f"requested JD {scale} {julian_date_ut}, returned {timestamp}"
        )


def parse_angular_events() -> dict[str, list[dict[str, object]]]:
    samples: list[tuple[float, float, float, float]] = []
    sample_keys: list[tuple[str, float]] = []
    for name, (_, expected_dates) in RELATIVE_LONGITUDE_VECTOR_QUERIES.items():
        rows = []
        for line in data_lines(horizons_result(name)):
            columns = [column.strip() for column in line.split(",")]
            row = (float(columns[0]), float(columns[2]), float(columns[3]), float(columns[4]))
            rows.append(row)
            samples.append(row)
            sample_keys.append((name, row[0]))
        if [row[0] for row in rows] != expected_dates:
            raise RuntimeError(f"unexpected angular-event vector dates in {name}")
    longitude_by_key = dict(zip(sample_keys, sofa_angular_event_longitudes(samples)))

    relative_longitude_events = []
    earth_name = "earth-angular-events"
    for event in RELATIVE_LONGITUDE_EVENTS:
        body_name = f"{event['body']}-angular-events"
        offsets = []
        for date in event["dates"]:
            earth = longitude_by_key[(earth_name, date)]
            planet = longitude_by_key[(body_name, date)]
            offsets.append(wrapped_degrees(event["direction"] * (earth - planet) - event["target"]))
        brackets = [
            (index, offsets[index], offsets[index + 1])
            for index in range(len(offsets) - 1)
            if offsets[index] <= 0 < offsets[index + 1]
        ]
        if len(brackets) != 1:
            raise RuntimeError(f"expected one relative-longitude bracket for {event['body']} {event['target']}, got {brackets}")
        index, lower_offset, upper_offset = brackets[0]
        lower = event["dates"][index]
        upper = event["dates"][index + 1]
        estimate = lower + (upper - lower) * (-lower_offset) / (upper_offset - lower_offset)
        resolution = (upper - lower) * 86_400
        relative_longitude_events.append(
            {
                "body": event["body"],
                "targetRelativeLongitudeDegrees": event["target"],
                "direction": event["direction"],
                "startUTC": event["startUTC"],
                "lowerJulianDateTDB": lower,
                "upperJulianDateTDB": upper,
                "estimatedJulianDateTDB": estimate,
                "lowerOffsetDegrees": lower_offset,
                "upperOffsetDegrees": upper_offset,
                "sampleResolutionSeconds": resolution,
                "timeScaleAllowanceSeconds": 0.002,
                "timeToleranceSeconds": resolution + 0.002,
            }
        )

    maximum_elongation_events = []
    for name, event in MAX_ELONGATION_QUERIES.items():
        lines = data_lines(horizons_result(name))
        if len(lines) != len(event["dates"]):
            raise RuntimeError(f"unexpected maximum-elongation row count in {name}")
        rows = []
        for row_index, (date, line) in enumerate(zip(event["dates"], lines), start=1):
            columns = [column.strip() for column in line.split(",")]
            if columns[4] not in {"/T", "/L"}:
                raise RuntimeError(f"unexpected elongation flag {columns[4]!r} in {name}")
            validate_horizons_ut_timestamp(name, row_index, columns[0], date)
            rows.append((date, columns[0], float(columns[3]), columns[4]))
        maximum = max(row[2] for row in rows)
        maximum_indices = [index for index, row in enumerate(rows) if row[2] == maximum]
        lower_index = maximum_indices[0] - 1
        upper_index = maximum_indices[-1] + 1
        sample_index = maximum_indices[len(maximum_indices) // 2]
        if lower_index < 0 or upper_index >= len(rows):
            raise RuntimeError(f"maximum-elongation sample is not bracketed in {name}")
        lower, sample, upper = rows[lower_index], rows[sample_index], rows[upper_index]
        if lower[3] != sample[3] or upper[3] != sample[3]:
            raise RuntimeError(f"maximum-elongation side changes inside the bracket in {name}")
        resolution = round((rows[1][0] - rows[0][0]) * 86_400, 3)
        angle_tolerance = round(max(sample[2] - lower[2], sample[2] - upper[2]) + 0.0001, 7)
        time_tolerance = round(max(sample[0] - lower[0], upper[0] - sample[0]) * 86_400, 3) + 0.001
        maximum_elongation_events.append(
            {
                "body": event["body"],
                "startUTC": event["startUTC"],
                "lowerUTC": lower[1],
                "sampleUTC": sample[1],
                "upperUTC": upper[1],
                "sampledMaximumDegrees": sample[2],
                "trailsSun": sample[3] == "/T",
                "sampleResolutionSeconds": resolution,
                "timeToleranceSeconds": time_tolerance,
                "angleToleranceDegrees": angle_tolerance,
            }
        )
    return {
        "relativeLongitudeEvents": relative_longitude_events,
        "maximumElongationEvents": maximum_elongation_events,
    }


def parse_saturn_apsis_events() -> list[dict[str, object]]:
    result = horizons_result("saturn-apsis-precision")
    required = [
        "Target body name: Saturn (699)",
        "Center body name: Sun (10)",
        "Output units    : AU-D",
        "JDTT",
        "Output type     : GEOMETRIC cartesian states",
        "Reference frame : ICRF",
    ]
    if any(item not in result for item in required):
        raise RuntimeError("unexpected Saturn apsis target, center, correction, or frame")
    lines = data_lines(result)
    if len(lines) != len(SATURN_APSIS_DATES):
        raise RuntimeError("unexpected Saturn apsis precision row count")
    rows = []
    for date, line in zip(SATURN_APSIS_DATES, lines):
        columns = [column.strip() for column in line.split(",")]
        values = [float(columns[index]) for index in (0, 9, 10)]
        if not all(math.isfinite(value) for value in values) or abs(values[0] - date) > 2e-9:
            raise RuntimeError("Saturn apsis precision date or finite-value mismatch")
        rows.append((date, values[1], values[2]))
    events = []
    for index, (kind, root) in enumerate(SATURN_APSIS_REFERENCES):
        group = rows[index * 5 : index * 5 + 5]
        rates = [row[2] for row in group]
        directed = rates if kind == "pericenter" else [-rate for rate in rates]
        if not (directed[0] < 0 < directed[-1]) or group[2][0] != root:
            raise RuntimeError(f"Saturn {kind} reference does not retain its directed crossing")
        events.append({
            "body": "saturn",
            "kind": kind,
            "julianDateTT": root,
            "distanceAU": group[2][1],
            "sourceRangeRateAUPerDay": group[2][2],
            "sourceToleranceSeconds": 1.0,
            "acceptanceToleranceSeconds": 60.0,
        })
    return events


def parse_apparent_lunar_phases() -> list[dict[str, object]]:
    """Linear roots of the Moon's apparent longitude less the Sun's across each archived TT bracket."""
    dates = sorted(date for event in APPARENT_LUNAR_PHASE_EVENTS for date in event["dates"])
    longitudes: dict[tuple[str, float], float] = {}
    for name, command in APPARENT_LUNAR_PHASE_QUERIES.items():
        result = horizons_result(name)
        target = {"301": "Target body name: Moon (301)", "10": "Target body name: Sun (10)"}[command]
        for required in (target, "Center-site name: GEOCENTRIC", " Date__(TT)__HR:MN:SC.fff", "ObsEcLon"):
            if required not in result:
                raise RuntimeError(f"apparent lunar phase response {name} lacks {required!r}")
        lines = data_lines(result)
        if len(lines) != len(dates):
            raise RuntimeError(f"unexpected apparent lunar phase row count in {name}")
        for row_index, (date, line) in enumerate(zip(dates, lines), start=1):
            columns = [column.strip() for column in line.split(",")]
            validate_horizons_ut_timestamp(name, row_index, columns[0], date, label="apparent lunar phase", scale="TT")
            longitude = float(columns[3])
            if not math.isfinite(longitude) or not 0 <= longitude < 360:
                raise RuntimeError(f"invalid apparent longitude in {name} row {row_index}")
            longitudes[(command, date)] = longitude
    phases = []
    for event in APPARENT_LUNAR_PHASE_EVENTS:
        lower, upper = event["dates"]
        lower_offset, upper_offset = (
            wrapped_degrees(longitudes[("301", date)] - longitudes[("10", date)] - event["targetDegrees"])
            for date in (lower, upper)
        )
        if not lower_offset <= 0 < upper_offset:
            raise RuntimeError(f"apparent {event['phase']} samples do not bracket one ascending root")
        phases.append({
            "phase": event["phase"],
            "targetDegrees": event["targetDegrees"],
            "usnoSourceTime": event["usnoSourceTime"],
            "lowerJulianDateTT": lower,
            "upperJulianDateTT": upper,
            "lowerOffsetDegrees": lower_offset,
            "upperOffsetDegrees": upper_offset,
            "julianDateTT": lower + (upper - lower) * -lower_offset / (upper_offset - lower_offset),
            "sampleResolutionSeconds": round((upper - lower) * 86_400, 3),
            "toleranceSeconds": APPARENT_LUNAR_PHASE_TOLERANCE_SECONDS,
        })
    return phases


def jupiter_moon_relative_tolerance(julian_date_tdb: float) -> float | None:
    start, end = JUPITER_MOON_TOLERANCE_JD_TDB_RANGE
    if start <= julian_date_tdb <= end:
        return JUPITER_MOON_RELATIVE_TOLERANCE
    return None


def parse_horizons() -> dict[str, list[dict[str, object]]]:
    observations = []
    body_names = {"moon-observer": "moon", "mars-observer": "mars", "pluto-observer": "pluto", "mercury-station": "mercury", "chiron-observer": "chiron"}
    chiron_observations = []
    for name, body in body_names.items():
        for line in data_lines(horizons_result(name)):
            columns = [column.strip() for column in line.split(",")]
            (chiron_observations if body == "chiron" else observations).append({"series": name, "body": body, "utc": columns[0].replace("A.D. ", ""), "rightAscensionDegrees": float(columns[3]), "declinationDegrees": float(columns[4]), "rightAscensionRateArcsecondsPerHour": float(columns[5]), "declinationRateArcsecondsPerHour": float(columns[6]), "apparentRangeAU": float(columns[7]), "rangeRateKmPerSecond": float(columns[8]), "eclipticLongitudeDegrees": float(columns[9]), "eclipticLatitudeDegrees": float(columns[10]), "angularToleranceArcminutes": 1.5 if body in {"pluto"} else 1.0})

    vectors = []
    vector_names = {"chiron-vector": ("chiron", "sun"), "io-vector": ("io", "jupiter"), "europa-vector": ("europa", "jupiter"), "ganymede-vector": ("ganymede", "jupiter"), "callisto-vector": ("callisto", "jupiter"), "moon-vector": ("moon", "earth"), "pluto-vector": ("pluto", "sun"), "pluto-barycenter-vector": ("pluto-barycenter", "sun"), "pluto-barycenter-decade": ("pluto-barycenter-decade", "sun"), "chiron-anchor-vector": ("chiron-anchor", "sun")}
    vector_names.update({name: (name.removesuffix("-vector"), "barycenter") for name in HORIZONS_VECTOR_QUERIES if name.endswith("-barycentric-vector")})
    vector_names.update({name: (name.removesuffix("-domain-vector"), "jupiter") for name in HORIZONS_VECTOR_QUERIES if name.endswith("-domain-vector")})
    for name, (body, origin) in vector_names.items():
        for line in data_lines(horizons_result(name)):
            columns = [column.strip() for column in line.split(",")]
            julian_date_tdb = float(columns[0])
            vectors.append({"body": body, "origin": origin, "julianDateTDB": julian_date_tdb, "tdb": columns[1].replace("A.D. ", ""), "positionAU": [float(columns[2]), float(columns[3]), float(columns[4])], "velocityAUPerDay": [float(columns[5]), float(columns[6]), float(columns[7])], "relativeTolerance": jupiter_moon_relative_tolerance(julian_date_tdb) if origin == "jupiter" else None, "sanityToleranceAU": 0.01 if body == "chiron" else None})
    horizontal = []
    for name in HORIZONS_HORIZONTAL_QUERIES:
        body, _, apparent = name.split("-")
        for line in data_lines(horizons_result(name)):
            columns = [column.strip() for column in line.split(",")]
            horizontal.append({"body": body, "refracted": apparent == "refracted", "utc": columns[0], "azimuthDegrees": float(columns[3]), "elevationDegrees": float(columns[4]), "angularToleranceArcminutes": 1.0})
    elongations = []
    for name in HORIZONS_ELONGATION_QUERIES:
        for line in data_lines(horizons_result(name)):
            columns = [column.strip() for column in line.split(",")]
            if columns[4] not in {"/T", "/L"}:
                raise RuntimeError(f"unexpected elongation flag {columns[4]!r} in {name}")
            elongations.append({"body": name.removesuffix("-elongation"), "utc": columns[0], "elongationDegrees": float(columns[3]), "trailsSun": columns[4] == "/T", "eclipticLongitudeDegrees": float(columns[5]), "eclipticLatitudeDegrees": float(columns[6])})
    saturn = horizons_result("saturn-rings")
    radii = [float(value) for value in saturn.split("Target radii    :", 1)[1].split("km", 1)[0].split(",")]
    saturn_rings = []
    for line in data_lines(saturn):
        columns = [column.strip() for column in line.split(",")]
        saturn_rings.append({"utc": columns[0], "subObserverPlanetodeticLatitudeDegrees": float(columns[4]), "heliocentricDistanceAU": float(columns[5]), "geocentricDistanceAU": float(columns[7]), "phaseAngleDegrees": float(columns[9]), "equatorialRadiusKm": radii[0], "polarRadiusKm": radii[2]})
    return {"observations": observations, "chironObservations": chiron_observations, "vectors": vectors, "horizontal": horizontal, "elongations": elongations, "saturnRings": saturn_rings}


def roman_precess(right_ascension: float, declination: float, epoch_from: float, epoch_to: float) -> tuple[float, float]:
    """The Herget precession in the published VI/42 program.c, with angles returned in hours and degrees."""
    radians_per_degree = 0.17453292519943e-01
    radians_per_hour = 0.2617993878
    ra = radians_per_hour * right_ascension
    dec = radians_per_degree * declination
    projected = math.cos(dec)
    vector = (projected * math.cos(ra), projected * math.sin(ra), math.sin(dec))
    centuries = 0.001 * (epoch_to - epoch_from)
    start = 0.001 * (epoch_from - 1900)
    arcseconds = radians_per_degree / 3600
    a = arcseconds * centuries * (23042.53 + start * (139.75 + 0.06 * start) + centuries * (30.23 - 0.27 * start + 18 * centuries))
    b = arcseconds * centuries * centuries * (79.27 + 0.66 * start + 0.32 * centuries) + a
    c = arcseconds * centuries * (20046.85 - start * (85.33 + 0.37 * start) + centuries * (-42.67 - 0.37 * start - 41.8 * centuries))
    sin_a, sin_b, sin_c = math.sin(a), math.sin(b), math.sin(c)
    cos_a, cos_b, cos_c = math.cos(a), math.cos(b), math.cos(c)
    rotation = (
        (cos_a * cos_b * cos_c - sin_a * sin_b, -cos_a * sin_b - sin_a * cos_b * cos_c, -cos_b * sin_c),
        (sin_a * cos_b + cos_a * sin_b * cos_c, cos_a * cos_b - sin_a * sin_b * cos_c, -sin_b * sin_c),
        (cos_a * sin_c, -sin_a * sin_c, cos_c),
    )
    moved = tuple(sum(rotation[row][column] * vector[column] for column in range(3)) for row in range(3))
    result_ra = math.atan2(moved[1], moved[0])
    if result_ra < 0:
        result_ra += 2 * math.pi
    return result_ra / radians_per_hour, math.asin(moved[2]) / radians_per_degree


def constellation_at(right_ascension: float, declination: float, boundaries: list[dict[str, object]]) -> str:
    right_ascension %= 24
    for boundary in boundaries:
        if (
            float(boundary["declinationLowerDegrees"]) <= declination
            and float(boundary["rightAscensionLowerHours"]) <= right_ascension
            and right_ascension < float(boundary["rightAscensionUpperHours"])
        ):
            return str(boundary["symbol"])
    raise RuntimeError(f"published constellation table has no result for {right_ascension}h {declination}°")


def verify_roman_constellation_program(examples: list[tuple[str, str, str]]) -> None:
    """Compile and run VI/42 program.c against the ReadMe's eight 1950 examples."""
    compiler = shlex.split(os.environ.get("CC", "cc"))
    if not compiler:
        raise RuntimeError("CDS VI/42 program compiler is empty")
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        (directory / "data.dat").write_bytes(
            (SOURCE_DIR / "constellations/roman1987-boundaries.dat").read_bytes()
        )
        executable = directory / "roman1987-program"
        compilation = subprocess.run(
            compiler
            + [
                "-std=gnu89",
                "-include",
                "stdlib.h",
                "-include",
                "unistd.h",
                str(SOURCE_DIR / "constellations/roman1987-program.c"),
                "-lm",
                "-o",
                str(executable),
            ],
            capture_output=True,
            text=True,
        )
        if compilation.returncode != 0:
            raise RuntimeError(f"CDS VI/42 program compilation failed: {compilation.stderr.strip()}")
        input_text = "1950\n" + "".join(f"{right_ascension}{float(declination):+.4f}\n" for right_ascension, declination, _ in examples)
        execution = subprocess.run(
            [str(executable)], cwd=directory, input=input_text, capture_output=True, text=True
        )
        if execution.returncode != 0:
            raise RuntimeError(f"CDS VI/42 program execution failed: {execution.stderr.strip()}")
    actual = re.findall(r"is in Constellation:\s*([A-Za-z]{3})", execution.stdout)
    expected = [symbol for _, _, symbol in examples]
    if actual != expected:
        raise RuntimeError(f"CDS VI/42 program output mismatch: expected {expected}, got {actual}")


def parse_constellations() -> dict[str, list[dict[str, object]]]:
    iau_names = source_text("constellations/iau-constellation-names.html")
    names = [
        {"symbol": symbol, "name": html.unescape(re.sub(r"<[^>]+>", "", name)).strip()}
        for name, symbol in re.findall(
            r'<tr>\s*<td[^>]*>((?:(?!</td>).)*?)<a name="[a-z]+"></a>.*?</td>\s*<td[^>]*>([A-Za-z]{3})</td>',
            iau_names,
            re.DOTALL,
        )
    ]
    boundaries = []
    for line in source_text("constellations/roman1987-boundaries.dat").splitlines():
        lower, upper, declination, symbol = line.split()
        boundaries.append(
            {
                "rightAscensionLowerHours": float(lower),
                "rightAscensionUpperHours": float(upper),
                "declinationLowerDegrees": float(declination),
                "symbol": symbol,
            }
        )
    if len(names) != 88 or len({item["symbol"] for item in names}) != 88:
        raise RuntimeError("IAU constellation name table must contain 88 unique symbols")
    if len(boundaries) != 357:
        raise RuntimeError("CDS VI/42 boundary table must contain 357 rows")
    symbols = {item["symbol"] for item in names}
    if {item["symbol"] for item in boundaries} != symbols:
        raise RuntimeError("IAU constellation names and CDS boundary symbols differ")
    boundary_ties = []
    near_boundary_stars = []
    for index, boundary in enumerate(boundaries):
        lower = float(boundary["rightAscensionLowerHours"])
        upper = float(boundary["rightAscensionUpperHours"])
        declination = float(boundary["declinationLowerDegrees"])
        for kind, right_ascension in (
            ("rightAscensionLower", lower),
            ("rightAscensionUpper", upper),
            ("declinationLower", (lower + upper) / 2),
        ):
            boundary_ties.append(
                {
                    "boundaryIndex": index,
                    "kind": kind,
                    "rightAscensionHours": right_ascension % 24,
                    "declinationDegrees": declination,
                    "symbol": constellation_at(right_ascension, declination, boundaries),
                }
            )
        right_ascension_1875 = (lower + upper) / 2
        declination_1875 = min(90.0, declination + 0.01)
        right_ascension_2000, declination_2000 = roman_precess(
            right_ascension_1875, declination_1875, 1875, 2000
        )
        expected_right_ascension_1875, expected_declination_1875 = roman_precess(
            right_ascension_2000, declination_2000, 2000, 1875
        )
        near_boundary_stars.append(
            {
                "boundaryIndex": index,
                "rightAscensionHoursJ2000": right_ascension_2000,
                "declinationDegreesJ2000": declination_2000,
                "rightAscensionHoursB1875": expected_right_ascension_1875,
                "declinationDegreesB1875": expected_declination_1875,
                "symbol": constellation_at(right_ascension_1875, declination_1875, boundaries),
            }
        )
    example_pattern = re.compile(
        r"RA =\s*([0-9.]+) DEC =\s*([+-]?[0-9.]+)\s+IS IN CONSTELLATION ([A-Za-z]{3})",
        re.IGNORECASE,
    )
    published_examples = []
    example_rows = example_pattern.findall(source_text("constellations/roman1987-readme.txt"))
    verify_roman_constellation_program(example_rows)
    for right_ascension_1950, declination_1950, symbol in example_rows:
        right_ascension_1950 = float(right_ascension_1950)
        declination_1950 = float(declination_1950)
        right_ascension_2000, declination_2000 = roman_precess(
            right_ascension_1950, declination_1950, 1950, 2000
        )
        right_ascension_1875, declination_1875 = roman_precess(
            right_ascension_2000, declination_2000, 2000, 1875
        )
        published_examples.append(
            {
                "rightAscensionHoursJ2000": right_ascension_2000,
                "declinationDegreesJ2000": declination_2000,
                "rightAscensionHoursB1875": right_ascension_1875,
                "declinationDegreesB1875": declination_1875,
                "symbol": symbol,
            }
        )
    if len(published_examples) != 8:
        raise RuntimeError("CDS VI/42 ReadMe must contain eight published examples")
    return {
        "names": names,
        "boundaries": boundaries,
        "boundaryTies": boundary_ties,
        "nearBoundaryStars": near_boundary_stars,
        "publishedExamples": published_examples,
    }


def generate_constellation_swift(fixture: dict[str, list[dict[str, object]]]) -> str:
    names = fixture["names"]
    indices = {item["symbol"]: index for index, item in enumerate(names)}
    lines = [
        "// Generated by Scripts/reference-data/build-fixtures.py from CDS/VizieR VI/42 and the IAU constellation name table.",
        "// Do not edit this file directly.",
        "",
        "extension Engine.Constellations {",
        "    static let infos: [Info] = [",
    ]
    lines.extend(
        f'        Info(symbol: {json.dumps(item["symbol"], ensure_ascii=False)}, name: {json.dumps(item["name"], ensure_ascii=False)}),'
        for item in names
    )
    lines.extend(["    ]", "", "    static let boundaries: [Boundary] = ["])
    lines.extend(
        "        Boundary(infoIndex: {index}, rightAscensionLower: {lower}, rightAscensionUpper: {upper}, declinationLower: {declination}),".format(
            index=indices[item["symbol"]],
            lower=item["rightAscensionLowerHours"],
            upper=item["rightAscensionUpperHours"],
            declination=item["declinationLowerDegrees"],
        )
        for item in fixture["boundaries"]
    )
    lines.extend(["    ]", "}", ""])
    return "\n".join(lines)


def sofa_fixed_star_recipe_output() -> dict[str, float]:
    archive_path = SOURCE_DIR / "sofa/sofa_c-20231011.tar.gz"
    if sha256(archive_path.read_bytes()) != SOFA_RELEASE_SHA256:
        raise RuntimeError("SOFA fixed-star release hash mismatch")
    with tempfile.TemporaryDirectory() as temporary:
        source_dir = Path(temporary) / "sofa"
        source_dir.mkdir()
        archive_prefix = "sofa/20231011/c/src/"
        with tarfile.open(archive_path, "r:gz") as archive:
            for name in ("sofa.h", "sofam.h", *SOFA_RECIPE_SOURCES):
                source = archive.extractfile(archive.getmember(archive_prefix + name))
                if source is None:
                    raise RuntimeError(f"SOFA fixed-star release has no {name}")
                (source_dir / name).write_bytes(source.read())
        executable = Path(temporary) / "sofa-fixed-star-reference"
        compiler = shlex.split(os.environ.get("CC", "cc"))
        if not compiler:
            raise RuntimeError("SOFA fixed-star recipe compiler is empty")
        compilation = subprocess.run(
            compiler
            + [
                "-std=c99",
                "-O",
                f"-I{source_dir}",
                str(ROOT / "Scripts/reference-data/sofa-fixed-star-reference.c"),
                *(str(source_dir / name) for name in SOFA_RECIPE_SOURCES),
                "-lm",
                "-o",
                str(executable),
            ],
            capture_output=True,
            text=True,
        )
        if compilation.returncode != 0:
            raise RuntimeError(f"SOFA fixed-star recipe compilation failed: {compilation.stderr.strip()}")
        execution = subprocess.run([str(executable)], capture_output=True, text=True)
        if execution.returncode != 0:
            raise RuntimeError(f"SOFA fixed-star recipe execution failed: {execution.stderr.strip()}")
    output: dict[str, float] = {}
    for line in execution.stdout.splitlines():
        name, value = line.split()
        if name in output:
            raise RuntimeError(f"SOFA fixed-star recipe repeats {name}")
        output[name] = float(value)
    return output


SOFA_FIXED_STAR_RECIPE_KEYS = {
    "utcJD": "utJulianDate",
    "ttJD": "ttJulianDate",
    "rightAscensionHours": "rightAscensionHours",
    "declinationDegrees": "declinationDegrees",
    "distanceLightYears": "distanceLightYears",
    "j2000RAHours": "j2000RightAscensionHours",
    "j2000DecDegrees": "j2000DeclinationDegrees",
    "ofDateRAHours": "ofDateRightAscensionHours",
    "ofDateDecDegrees": "ofDateDeclinationDegrees",
    "eclipticLongitudeDegrees": "eclipticLongitudeDegrees",
    "eclipticLatitudeDegrees": "eclipticLatitudeDegrees",
    "azimuthDegrees": "azimuthDegrees",
    "altitudeDegrees": "unrefractedAltitudeDegrees",
    "topocentricRAHours": "topocentricRightAscensionHours",
    "topocentricDecDegrees": "topocentricDeclinationDegrees",
    "sofaStarpmRARadians": "sofaStarpmRightAscensionRadians",
    "sofaStarpmDecRadians": "sofaStarpmDeclinationRadians",
    "barnardJ2000RAHours": "barnardJ2000RightAscensionHours",
    "barnardJ2000DecDegrees": "barnardJ2000DeclinationDegrees",
    "barnardHipparcosEpochRAHours": "barnardHipparcosEpochRightAscensionHours",
    "barnardHipparcosEpochDecDegrees": "barnardHipparcosEpochDeclinationDegrees",
    "barnardCatalogDirectionX": "barnardCatalogDirectionX",
    "barnardCatalogDirectionY": "barnardCatalogDirectionY",
    "barnardCatalogDirectionZ": "barnardCatalogDirectionZ",
    "barnardPmpxSSBDirectionX": "barnardPmpxSSBDirectionX",
    "barnardPmpxSSBDirectionY": "barnardPmpxSSBDirectionY",
    "barnardPmpxSSBDirectionZ": "barnardPmpxSSBDirectionZ",
    "barnardPmpxObserverDirectionX": "barnardPmpxObserverDirectionX",
    "barnardPmpxObserverDirectionY": "barnardPmpxObserverDirectionY",
    "barnardPmpxObserverDirectionZ": "barnardPmpxObserverDirectionZ",
}


def verify_sofa_fixed_star_recipe_output(reference: dict[str, object]) -> None:
    output = sofa_fixed_star_recipe_output()
    if output.keys() != SOFA_FIXED_STAR_RECIPE_KEYS.keys():
        raise RuntimeError("SOFA fixed-star recipe output fields mismatch")
    for output_name, reference_name in SOFA_FIXED_STAR_RECIPE_KEYS.items():
        actual = output[output_name]
        expected = float(reference[reference_name])
        if not math.isfinite(actual) or not math.isfinite(expected):
            raise RuntimeError(f"SOFA fixed-star recipe output mismatch for {reference_name}: expected {expected}, got {actual}")
        tolerance = 8 * max(math.ulp(actual), math.ulp(expected))
        if abs(actual - expected) > tolerance:
            raise RuntimeError(f"SOFA fixed-star recipe output mismatch for {reference_name}: expected {expected}, got {actual}")


def parse_sofa_fixed_stars() -> list[dict[str, object]]:
    reference = json.loads(source_text("sofa/fixed-star-reference.json"))
    recipe_path = ROOT / "Scripts/reference-data/sofa-fixed-star-reference.c"
    if reference.pop("_recipeSHA256") != sha256(recipe_path.read_bytes()):
        raise RuntimeError("SOFA fixed-star recipe hash mismatch")
    if reference.pop("_sofaReleaseSHA256") != SOFA_RELEASE_SHA256:
        raise RuntimeError("SOFA fixed-star release hash mismatch")
    verify_sofa_fixed_star_recipe_output(reference)
    if reference["sampledToleranceArcseconds"] < 2 * reference["sampledMaximumResidualArcseconds"]:
        raise RuntimeError("SOFA fixed-star tolerance must be at least twice the sampled maximum residual")
    return [reference]


def capture_sofa_fixed_star_reference() -> None:
    path = SOURCE_DIR / "sofa/fixed-star-reference.json"
    reference = json.loads(path.read_text())
    output = sofa_fixed_star_recipe_output()
    for output_name, reference_name in SOFA_FIXED_STAR_RECIPE_KEYS.items():
        reference[reference_name] = output[output_name]
    reference["_recipeSHA256"] = sha256((ROOT / "Scripts/reference-data/sofa-fixed-star-reference.c").read_bytes())
    path.write_bytes(encoded(reference))


def build_archive(constellations: dict[str, list[dict[str, object]]] | None = None) -> dict[str, object]:
    if constellations is None:
        constellations = parse_constellations()
    archive: dict[str, object] = {
        "schemaVersion": 7,
        "provenance": source_catalog(),
        "fixedStars": parse_sofa_fixed_stars(),
        "constellations": constellations["names"],
        "constellationBoundaries": constellations["boundaries"],
        "constellationBoundaryTies": constellations["boundaryTies"],
        "constellationNearBoundaryStars": constellations["nearBoundaryStars"],
        "constellationPublishedExamples": constellations["publishedExamples"],
    }
    archive.update(parse_upstream_events())
    archive.update(parse_eclipses())
    archive.update(parse_horizons())
    archive.update(parse_angular_events())
    archive["saturnApsides"] = parse_saturn_apsis_events()
    archive["apparentLunarPhases"] = parse_apparent_lunar_phases()
    archive.update(parse_geocentric_states())
    return archive


def source_catalog() -> dict[str, dict[str, str]]:
    upstream = f"https://github.com/cosinekitty/astronomy/tree/{UPSTREAM_REVISION}/generate"
    mit_license = "Upstream transformation files retain the Astronomy Engine MIT license archived with these fixtures"
    government_license = "U.S. government factual output is public domain; transformed files also retain the archived Astronomy Engine MIT license"
    jpl_license = "NASA/JPL factual output; acknowledge NASA and do not imply endorsement; the copied files also retain the archived Astronomy Engine MIT license"
    nasa_license = "NASA factual data may be reproduced with acknowledgment and without implied endorsement; transformed files also retain the archived Astronomy Engine MIT license"
    return {
        "cdsConstellations": {"version": "VI/42, corrected 1999-12-30; archived IAU name table", "frame": "mean equator and equinox of B1875", "origin": "celestial sphere", "units": "sidereal hours and degrees", "timeScale": "not applicable; positions are precessed between named equinoxes", "aberration": "none", "refraction": "none", "domain": "all 88 IAU constellations, all 357 VI/42 southern boundary segments and their exact right-ascension and declination ties", "license": "Published catalog data and program by Nancy Grace Roman through CDS/VizieR, with official names and abbreviations from the IAU; source and service attribution retained", "url": "https://cdsarc.cds.unistra.fr/viz-bin/ReadMe/VI/42", "recipe": "Pinned VI/42 ReadMe, boundary table and C program plus the archived IAU constellation name table. build-fixtures.py compiles and runs the published program on all eight ReadMe examples, parses every row, reproduces the published Herget precession for J2000 samples, and generates the native Swift table."},
        "sofaFixedStar": {"version": "SOFA 2023-10-11; Gaia DR3", "frame": "ICRS/J2000, IAU 2006/2000A true equator and ecliptic of date, and topocentric horizon", "origin": "Solar-system barycenter for propagated catalog motion, Sun center for the legacy catalog definition, Earth center for geocentric coordinates, and the published geodetic site for topocentric coordinates", "units": "sidereal hours, degrees, radians, milliarcseconds, kilometres per second, metres, Julian dates, parallax-derived light-years, and arcseconds", "timeScale": "Gaia catalog epoch J2016.0 TCB, target Julian epochs represented as TT, and UTC, TT, and UT1 with UT1-UTC set to zero for the static row", "aberration": "SOFA iauStarpm catalog propagation and iauAtci13 relativistic annual aberration and light deflection", "refraction": "none", "domain": "SOFA's published iauStarpm validation row, Gaia DR3 Barnard's star propagated to J2000 and Hipparcos J1991.25, and one static star and instant from SOFA's official astrometry example", "license": "IAU SOFA software and data terms and ESA Gaia Archive factual output; attribution retained and no endorsement implied", "url": "https://www.iausofa.org/2023_1011_C.html", "recipe": "The pinned Gaia TAP row supplies Barnard's star catalog data. The official sofa_ast_example.c is pinned unchanged; sofa-fixed-star-reference.c generates fixed-star-reference.json against SOFA release 2023-10-11, including starpm propagation. The 0.5 arcsec static-row limit is twice the 0.246 arcsec sampled maximum rounded up, a regression margin rather than a published accuracy."},
        "jplObserver": {"serviceVersion": "recorded in every archived response", "frame": "ICRF/J2000 equatorial and IAU76/80 true ecliptic and equinox of date", "origin": "Earth center 500@399", "units": "degrees, arcseconds/hour, AU, and km/s", "timeScale": "UT/UTC calendar output", "aberration": "apparent AIRLESS observer solution with down-leg light time and response-listed corrections", "refraction": "none (AIRLESS)", "domain": "1900, 2000, and 2100 samples, plus a three-day 2025 Mercury station bracket and 2060 Chiron at 1900-01-01 03:00 UT, 1950, 2000, 2026-01-02, 2050 and 2100", "license": "NASA/JPL factual output; acknowledge NASA and do not imply endorsement", "url": "https://ssd.jpl.nasa.gov/horizons/manual.html", "recipe": "Adjacent *.query.json files contain every Horizons API parameter and the response SHA-256"},
        "jplHorizontal": {"serviceVersion": "recorded in every archived response", "frame": "topocentric apparent horizon: azimuth east of north and elevation", "origin": "geodetic site 35.595 N, 82.5572 W, height 0 (coord@399)", "units": "degrees", "timeScale": "UTC calendar output", "aberration": "apparent position with light time, gravitational deflection and stellar aberration", "refraction": "none (AIRLESS) and Horizons' yellow-light refraction model (REFRACTED)", "domain": "the Sun, the Moon and Mars every three hours on 2026-01-02 and 2026-07-02 UT, above and below the horizon", "license": "NASA/JPL factual output; acknowledge NASA and do not imply endorsement", "url": "https://ssd.jpl.nasa.gov/horizons/manual.html", "recipe": "Adjacent *.query.json files contain every Horizons API parameter and the response SHA-256"},
        "jplApparentLunarPhases": {"serviceVersion": "recorded in every archived response", "frame": "Earth-centered IAU76/80 apparent ecliptic and equinox of date", "origin": "Earth center 500@399", "units": "Julian dates TT, degrees, and seconds", "timeScale": "TT (TIME_TYPE=TT); roots are TT Julian dates and need no Delta T", "aberration": "Horizons quantity 31: light time, gravitational deflection, and stellar aberration", "refraction": "none (AIRLESS)", "domain": "the four January 2100 lunar quarters whose USNO labels are in lunarPhases, one 60-second TT bracket each", "license": "NASA/JPL factual output; acknowledge NASA and do not imply endorsement", "url": "https://ssd.jpl.nasa.gov/horizons/manual.html", "recipe": "Adjacent *.query.json files contain every Horizons API parameter and the response SHA-256. build-fixtures.py takes the Moon's apparent longitude less the Sun's at each sample and linearly interpolates the target crossing; the 2-second allowance is an owner decision for these four rows on #247, against native residuals of 0.66 to 0.82 seconds"},
        "jplElongation": {"serviceVersion": "recorded in every archived response", "frame": "geocentric Sun-observer-target angle and IAU76/80 ecliptic of date", "origin": "Earth center 500@399", "units": "degrees", "timeScale": "UTC calendar output", "aberration": "apparent positions with light time, gravitational deflection and stellar aberration", "refraction": "none", "domain": "the Moon, Mercury, Venus, Mars and Jupiter every 46 days from 2026-01-02 UT", "license": "NASA/JPL factual output; acknowledge NASA and do not imply endorsement", "url": "https://ssd.jpl.nasa.gov/horizons/manual.html", "recipe": "Adjacent *.query.json files contain every Horizons API parameter and the response SHA-256"},
        "jplAngularEvents": {"serviceVersion": "recorded in every archived response", "frame": "simultaneous geometric ICRF vectors transformed by official SOFA IAU 1976/1980 precession-nutation to true ecliptic of date for relative longitude; apparent full-sky Sun-observer-target angle for maximum elongation", "origin": "Sun center 500@10 for Earth, Mars, and Venus vectors; Earth center 500@399 for Mercury and Venus elongation", "units": "Julian dates TDB, UTC calendar timestamps, degrees, and seconds", "timeScale": "TDB for geometric vectors and UTC for apparent elongation tables; the 0.002-second TDB-minus-TT bound is included in relative-longitude allowances", "aberration": "none for VEC_CORR=NONE relative-longitude vectors; Horizons apparent light time, gravitational deflection, and stellar aberration for S-O-T elongation", "refraction": "none (AIRLESS)", "domain": "Mars opposition and superior conjunction, Venus inferior and superior conjunction, and two successive maximum elongations for each of Mercury and Venus in 2025", "license": "NASA/JPL factual output and IAU SOFA software/data terms; attribution retained and no endorsement implied", "url": "https://ssd.jpl.nasa.gov/horizons/manual.html", "recipe": "Adjacent *.query.json files contain every Horizons API parameter and response SHA-256. build-fixtures.py applies Scripts/reference-data/sofa-angular-events.c to simultaneous geometric vectors, derives sign-change or sampled-maximum brackets, and records the source sampling resolution as an allowance rather than a published accuracy."},
        "jplSaturnApsides": {"serviceVersion": "recorded in the archived response", "frame": "geometric ICRF vectors", "origin": "Saturn body center 699 relative to Sun body center 500@10", "units": "Julian dates TT, AU, AU/day, and seconds", "timeScale": "TT", "aberration": "none (VEC_CORR=NONE)", "refraction": "not applicable", "domain": "six failure-selected Saturn body-center extrema from 1929 through 2062, each sampled at five instants over ±0.01 TT day", "license": "NASA/JPL factual output; acknowledge NASA and do not imply endorsement", "url": "https://ssd.jpl.nasa.gov/horizons/manual.html", "recipe": "The adjacent query records target 699, Sun-center origin, TT, geometric correction, exact sample epochs, and response SHA-256. These are failure-selected diagnostics from #81/#132, not a new accuracy holdout."},
        "jplSaturnRings": {"serviceVersion": "recorded in every archived response", "frame": "Saturn's planetodetic sub-observer latitude on the IAU pole and ellipsoid Horizons lists, its distances from the Sun and from Earth, and the Sun-target-observer angle", "origin": "Earth center 500@399", "units": "degrees, AU and km", "timeScale": "UTC calendar output", "aberration": "apparent sub-observer point with light time; S-T-O as Horizons defines it", "refraction": "none", "domain": "11 dates from 2010 to 2035, through the 2025 ring-plane crossing", "license": "NASA/JPL factual output; acknowledge NASA and do not imply endorsement", "url": "https://ssd.jpl.nasa.gov/horizons/manual.html", "recipe": "Adjacent *.query.json files contain every Horizons API parameter and the response SHA-256"},
        "jplVectors": {"serviceVersion": "recorded in every archived response", "frame": "geometric ICRF/J2000 vectors", "origin": "Sun center 500@10 for Chiron, Pluto (999) and the Pluto system barycenter (9); Jupiter center 500@599 for Galilean moons; Earth center 500@399 for the Moon; the solar system barycenter 500@0 for the Sun, the planets, Pluto (999), the Moon and the Earth-Moon barycenter (3)", "units": "AU and AU/day", "timeScale": "TDB", "aberration": "none (VEC_CORR=NONE)", "refraction": "not applicable to geometric vectors", "domain": "JPL vectors sampled at 1900, 2000, and 2100; Astronomy Engine's 9e-4 Galilean-moon threshold covers only JD 2426545.0 through 2476545.0, where the Galilean moons are also sampled at both ends and every 2,500 days between, with a day outside each end; the Moon at 30 dates from 2002 BCE to 6000 CE, eleven of them within 40 days of 1900-01-01 or 2131-01-01; Pluto at 29 dates from 1840 to 2159, through both 32-day blends at 1900 and 2131 and across record, segment and step seams, and the Pluto system barycenter at 15 dates from 100 BCE to 4098 CE, where Horizons has no Pluto center, and at 4 dates from 1990 to 2010 for the gravity simulation; barycentric states inside the spans of Astronomy Engine's BaryStateTest files: the Sun, Jupiter to Neptune and Pluto every 25 years from 1900 to 2099, Mercury to Mars every 10 years from 1980 to 2020, and the Moon and the Earth-Moon barycenter at 5 dates from 1970 to 2040; Chiron at its five anchors from 2000 to 2040, around the four midpoints between them, and at 1900-01-01 and 2150-01-01", "license": "NASA/JPL factual output; acknowledge NASA and do not imply endorsement", "url": "https://ssd.jpl.nasa.gov/horizons/manual.html", "recipe": "Adjacent *.query.json files contain every Horizons API parameter and the response SHA-256"},
        "usnoSeasonsAndPhases": {"version": UPSTREAM_REVISION, "frame": "geocentric seasonal and lunar-phase event definitions from USNO APIs", "origin": "Earth center", "units": "calendar timestamps", "timeScale": "source timestamps are serialized with Z; the pinned C harness passes them to Astronomy_MakeTime as UT coordinates and compares lunar-quarter TT values derived with its default Espenak-Meeus Delta T model", "aberration": "not separately configurable or documented in the archived API output", "refraction": "not applicable to geocentric event times", "domain": "pinned table contains one year every ten years from 1800 through 2100; sampled at 1800, 2000, and 2100", "license": government_license, "url": "https://aa.usno.navy.mil/data/api", "recipe": f"Pinned parser, C validation harness, engine source, and table under {upstream}/moonphase, {upstream}/ctest.c, and the matching source/c tree"},
        "espenakMoonNodes": {"version": UPSTREAM_REVISION, "frame": "geocentric equator and equinox of date as consumed by the pinned harness", "origin": "Earth center", "units": "UTC calendar timestamps, right ascension hours, and declination degrees", "timeScale": "UTC as serialized by the pinned transformation", "aberration": "not documented by the source table", "refraction": "not applicable to geocentric node events", "domain": "published table 2001 through 2100; sampled at 2001, 2050, and 2100", "license": f"Fred Espenak table with attribution; {mit_license}", "url": "http://astropixels.com/ephemeris/moon/moonnodes2001.html", "recipe": f"Pinned README, parser, and table under {upstream}/moon_nodes"},
        "astronomyEngineGeocentricStates": {"version": UPSTREAM_REVISION, "frame": "geometric ICRF/J2000 vectors", "origin": "Earth center 500@399; the Moon (301) and the Earth-Moon barycenter (3)", "units": "AU and AU/day", "timeScale": "TDB; the pinned C harness passes each Julian date to Astronomy_TerrestrialTime as TT", "aberration": "none (geometric states)", "refraction": "not applicable to geometric vectors", "domain": "JPL Horizons (DE441) states every 8 days from 1970-01-01 to 2040-01-01 TDB, all of them; the harness's relative limits cover exactly this domain", "license": jpl_license, "url": f"{upstream}/barystate", "recipe": "Pinned GeoMoon.txt and GeoEMB.txt are parsed directly; each carries its own Horizons header, and ctest.c VerifyStateBody supplies the limits"},
        "astronomyEngineApsides": {"version": UPSTREAM_REVISION, "frame": "scalar Earth-Moon and Sun-Earth distances; no orientation frame", "origin": "Earth center for lunar distance and Sun center for Earth distance", "units": "UTC-like calendar timestamps, km, and AU", "timeScale": "calendar strings are interpreted as UT/UTC by the pinned harness; original acquisition metadata is absent", "aberration": "not documented in the pinned tables", "refraction": "not applicable to scalar apsis distances", "domain": "pinned lunar and Earth tables beginning in 2001; sampled at 2001, 2050, and 2100", "license": mit_license, "url": f"{upstream}/apsides", "recipe": "Pinned moon.txt and earth.txt are parsed directly; evidence is classified as third-party parity because upstream does not retain the original acquisition recipe"},
        "usnoRiseSet": {"version": UPSTREAM_REVISION, "frame": "topocentric apparent horizon", "origin": "named terrestrial longitude and latitude", "units": "calendar timestamps treated as UT coordinates and geographic degrees", "timeScale": "the pinned C harness passes every timestamp to Astronomy_MakeTime as a UT coordinate, derives TT with the default Espenak-Meeus model, and compares event TT", "aberration": "included in the USNO apparent-position service", "refraction": "USNO standard apparent-horizon refraction", "domain": "all 5,909 pinned rows in 17 body/location/year groups from 1750 through 2050; the USNO service documents years 1700 through 2100", "license": government_license, "url": "https://aa.usno.navy.mil/data/RS_OneYear", "recipe": f"Pinned acquisition instructions, full table, C validation harness, and engine source under {upstream}/riseset, {upstream}/ctest.c, and the matching source/c tree"},
        "nasaLunarEclipses": {"version": f"{UPSTREAM_REVISION}; NASA OH2001 and Five Millennium Catalog archived 2026-10-09", "frame": "geocentric Earth-shadow geometry", "origin": "Earth center", "units": "UT calendar timestamps, TD catalog durations, eclipse magnitudes, Earth equatorial radii, and minutes", "timeScale": "Observer's Handbook peaks are UT coordinates; the modern catalog publishes phase durations beside TD greatest-eclipse coordinates, whose coordinates are not reinterpreted as UT", "aberration": "not separately configurable in the published catalog", "refraction": "not applicable to geocentric eclipse geometry", "domain": "NASA catalog centuries represented by archived pages, sampled at 1800, 2000, 2001, and 2099; UT peaks for the three 2001 lunar eclipses come from NASA's Observer's Handbook, while their phase durations come from the Danjon-based Five Millennium Catalog", "license": nasa_license, "url": "https://eclipse.gsfc.nasa.gov/LEcat5/LE2001-2100.html", "recipe": f"Pinned catalog pages, NASA OH2001 and Five Millennium Catalog sources, NASA's shadow-convention page, source key, normalizer, C validation harness, and engine source under {upstream}/eclipse, {upstream}/ctest.c, and the matching source/c tree"},
        "nasaLunarEclipseObscuration": {"version": "NASA SVS 4953 released 2021-11-04; NASA SVS 5672 updated 2026-08-25", "frame": "geocentric Earth-shadow geometry rendered on the Moon's apparent disc", "origin": "Earth center", "units": "fraction of the Moon's disc area and Universal Time calendar labels", "timeScale": "the pages label greatest eclipse in Universal Time; the printed minute identifies the published event and is not asserted as an exact TT or UTC coordinate", "aberration": "not separately configurable in the published visualizations", "refraction": "not applicable to geocentric eclipse geometry", "domain": "deep partial lunar eclipses on 2021-11-19 and 2026-08-28", "license": nasa_license, "url": "https://svs.gsfc.nasa.gov/5672/", "recipe": "Pinned complete NASA SVS pages 4953 and 5672. Each directly publishes the Moon-disc area inside the umbra at greatest eclipse. Assuming nearest-0.1-percentage-point rounding, inclusive bounds add and subtract 0.0005 from the printed fraction without assuming a tie rule. Both pages come from one NASA SVS publisher and DE421/LOLA model family, and neither publishes its exact rounding rule, radii, or full-precision area algorithm. The inferred intervals are not NASA uncertainty bounds or a new accuracy policy."},
        "nasaGlobalSolarEclipses": {"version": UPSTREAM_REVISION, "frame": "geocentric shadow-axis geometry with terrestrial greatest-eclipse location", "origin": "Earth center and catalog surface coordinates", "units": "TD calendar timestamps and geographic degrees", "timeScale": "Terrestrial Dynamical Time (TD)", "aberration": "not separately configurable in the published catalog", "refraction": "not applicable to global shadow geometry", "domain": "NASA catalog centuries represented by archived pages; sampled at 1800, 2024, and 2099", "license": nasa_license, "url": "https://eclipse.gsfc.nasa.gov/solar.html", "recipe": f"Pinned catalog pages and source key under {upstream}/eclipse"},
        "nasaPlanetaryTransits": {"version": UPSTREAM_REVISION, "frame": "geocentric Sun-planet contact geometry", "origin": "Earth center", "units": "UT calendar timestamps and arcseconds converted to arcminutes", "timeScale": "UT", "aberration": "not separately configurable in the published catalog", "refraction": "not applicable to geocentric transit contacts", "domain": "Mercury 1601 through 2300 and Venus 2000 BCE through 4000 CE; sampled from 2003 through 2125", "license": nasa_license, "url": "https://eclipse.gsfc.nasa.gov/transit/catalog/", "recipe": f"Pinned Mercury and Venus catalog pages under {upstream}/eclipse"},
        "eclipseWiseLocalSolar": {"version": UPSTREAM_REVISION, "frame": "topocentric apparent solar altitude at local contacts", "origin": "named terrestrial longitude and latitude", "units": "UT1 calendar timestamps (legacy UTC keys and Z suffix) and degrees", "timeScale": "UT1 as explicitly labeled by the original 2024 Google map pages; decode calendar fields without UTC conversion", "aberration": "included in the published local circumstances", "refraction": "source altitude convention retained; below-horizon altitudes are not asserted", "domain": "published cases retained by the pinned table; three 2024 geometries sampled", "license": f"EclipseWise/Fred Espenak table with attribution; {mit_license}", "url": "https://www.eclipsewise.com/solar/SEgmapx/2001-2100/SE2024Apr08Tgmapx.html", "recipe": f"Pinned local_solar_eclipse.txt under {upstream}/eclipse, unchanged bytes. Its linked Google maps publish UT1 using DE430: April Delta T 69.2 s and October 70.7 s (SE2024Oct02Agmapx.html). These differ from the older April SEcirc calculator DE406/71.3 s. Source labels were verified through browser-readable primary text; direct HTTP capture returned 403. Archive time fields retain legacy UTC names, not UTC semantics."},
    }


def encoded(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def write_or_check(path: Path, data: bytes, check: bool) -> None:
    if check:
        if not path.exists() or path.read_bytes() != data:
            raise RuntimeError(f"generated output is stale: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="download pinned source snapshots and fresh JPL responses")
    parser.add_argument("--check", action="store_true", help="verify sources and generated files without writing")
    parser.add_argument("--capture-sofa-fixed-star", action="store_true", help="capture the pinned SOFA fixed-star recipe output")
    args = parser.parse_args()
    if args.capture_sofa_fixed_star:
        capture_sofa_fixed_star_reference()
    if args.refresh:
        refresh_sources()
    sources = verify_sources()
    verify_recorded_queries()
    constellations = parse_constellations()
    archive = build_archive(constellations)
    archive_data = encoded(archive)
    write_or_check(OUTPUT_DIR / "reference-fixtures.json", archive_data, args.check)
    constellation_data = generate_constellation_swift(constellations).encode()
    write_or_check(GENERATED_CONSTELLATION_PATH, constellation_data, args.check)
    print(f"verified {len(sources)} source artifacts and archive {sha256(archive_data)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, KeyError, IndexError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
