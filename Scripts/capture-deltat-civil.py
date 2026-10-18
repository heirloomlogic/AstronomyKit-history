#!/usr/bin/env python3
"""Replay pinned civil UTC horizon references; network refresh is explicit."""

import argparse
import csv
import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "Scripts/deltat-data/civil-horizon"
FIXTURE = DATA / "reference.json"
SOURCE_NAMES = ("horizons", "usno")
EXPECTED_UTC = (
    "2025-06-21T10:15:03Z",
    "2025-06-21T10:15:04Z",
    "2025-06-21T18:00:00Z",
    "2025-06-22T00:49:09Z",
    "2025-06-22T00:49:10Z",
)


def finite(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite source value")
    return result


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_source(path):
    query_path = path.with_suffix(".query.json")
    query = json.loads(query_path.read_bytes())
    if query.get("_responseSHA256") != sha256(path):
        raise ValueError(f"response digest differs: {path}")
    return json.loads(path.read_bytes()), query


def jd(iso):
    instant = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return 2_440_587.5 + instant.timestamp() / 86_400


def iso(julian_date):
    instant = datetime.datetime.fromtimestamp((julian_date - 2_440_587.5) * 86_400, datetime.UTC)
    return instant.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_horizons(document, query):
    expected = {
        "COMMAND": "'10'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'coord@399'",
        "COORD_TYPE": "'GEODETIC'",
        "SITE_COORD": "'-82.5515,35.5951,0'",
        "TLIST_TYPE": "'JD'",
        "TIME_TYPE": "'UT'",
        "QUANTITIES": "'4,13,49'",
        "CAL_FORMAT": "'JD'",
        "EXTRA_PREC": "'YES'",
        "APPARENT": "'AIRLESS'",
        "CSV_FORMAT": "'YES'",
        "RANGE_UNITS": "'AU'",
    }
    for key, value in expected.items():
        if query.get(key) != value:
            raise ValueError(f"changed Horizons query convention: {key}")
    expected_jd = [jd(value) for value in EXPECTED_UTC]
    actual_jd = [finite(value) for value in query.get("TLIST", "").strip("'").split(",")]
    if len(actual_jd) != len(expected_jd) or any(abs(a - b) > 1e-9 for a, b in zip(actual_jd, expected_jd)):
        raise ValueError("changed Horizons epoch inventory")

    text = document.get("result", "")
    required = (
        "Target body name: Sun (10)                        {source: DE441}",
        "Center body name: Earth (399)                     {source: DE441}",
        "Center-site name: (user defined site below)",
        "Center geodetic : 277.4485, 35.5951, 0.0",
        "Center pole/equ : ITRF93",
        "Atmos refraction: NO (AIRLESS)",
        "Date_________JDUT",
        "Azimuth_(a-app), Elevation_(a-app),  Ang-diam,   UT1-UTC",
    )
    if document.get("error") or any(value not in text for value in required):
        raise ValueError("changed Horizons response semantics")
    if text.count("$$SOE") != 1 or text.count("$$EOE") != 1:
        raise ValueError("changed Horizons row markers")
    eop = re.search(r"^EOP file\s*:\s*(\S+)\s*$", text, re.MULTILINE)
    if eop is None or not re.fullmatch(r"eop\.\d{6}\.p\d{6}", eop.group(1)):
        raise ValueError("changed Horizons EOP metadata")
    header = next(line for line in text.splitlines() if line.startswith("Date_"))
    columns = [value.strip() for value in next(csv.reader([header]))]
    if columns != ["Date_________JDUT", "", "", "Azimuth_(a-app)", "Elevation_(a-app)", "Ang-diam", "UT1-UTC", ""]:
        raise ValueError("changed Horizons output columns")
    rows = list(csv.reader(text.split("$$SOE\n", 1)[1].split("$$EOE", 1)[0].splitlines()))
    if len(rows) != len(expected_jd):
        raise ValueError("changed Horizons row inventory")
    parsed = []
    for expected_epoch, row in zip(expected_jd, rows):
        if len(row) != 8:
            raise ValueError("changed Horizons row layout")
        epoch = finite(row[0])
        values = [finite(row[index]) for index in range(3, 7)]
        if abs(epoch - expected_epoch) > 1e-9 or not 0 <= values[0] < 360 or not -90 <= values[1] <= 90 or values[2] <= 0 or not -0.9 <= values[3] <= 0.9:
            raise ValueError("invalid Horizons source value")
        parsed.append({
            "utc": iso(epoch),
            "jdUTC": epoch,
            "azimuthDegrees": values[0],
            "altitudeDegrees": values[1],
            "angularDiameterArcseconds": values[2],
            "ut1MinusUTCSeconds": values[3],
        })
    return parsed, eop.group(1)


def parse_usno(document, query):
    url = urllib.parse.urlparse(query.get("url", ""))
    parameters = urllib.parse.parse_qs(url.query)
    if (url.scheme, url.netloc, url.path) != ("https", "aa.usno.navy.mil", "/api/rstt/oneday") or parameters != {"date": ["2025-06-21"], "coords": ["35.5951,-82.5515"], "tz": ["-4"]}:
        raise ValueError("changed USNO query")
    if document.get("apiversion") != "4.0.1" or document.get("type") != "Feature" or document.get("geometry", {}).get("type") != "Point":
        raise ValueError("changed USNO response schema")
    if document.get("geometry", {}).get("coordinates") != [-82.5515, 35.5951]:
        raise ValueError("changed USNO site")
    data = document.get("properties", {}).get("data", {})
    if [data.get(key) for key in ("year", "month", "day")] != [2025, 6, 21] or data.get("tz") != -4:
        raise ValueError("changed USNO date or time zone")
    rows = data.get("sundata", [])
    expected = [
        {"phen": "Begin Civil Twilight", "time": "05:45"},
        {"phen": "Rise", "time": "06:15"},
        {"phen": "Upper Transit", "time": "13:32"},
        {"phen": "Set", "time": "20:49"},
        {"phen": "End Civil Twilight", "time": "21:19"},
    ]
    if rows != expected:
        raise ValueError("changed USNO solar events")

    source_date = datetime.date(data["year"], data["month"], data["day"])
    events = {}
    for name, row in (("rise", rows[1]), ("set", rows[3])):
        local_time = datetime.time.fromisoformat(row["time"])
        local = datetime.datetime.combine(source_date, local_time)
        ut1 = local - datetime.timedelta(hours=data["tz"])
        jd_ut1 = 2_440_587.5 + ut1.replace(tzinfo=datetime.UTC).timestamp() / 86_400
        events[name] = {
            "localDateTime": local.isoformat(timespec="seconds"),
            "ut1DateTime": ut1.isoformat(timespec="seconds"),
            "jdUT1": jd_ut1,
        }
    return {
        "date": source_date.isoformat(),
        "timeZoneHoursFromUT1": data["tz"],
        "timeScale": "UT1",
        "events": events,
    }


def crossing(before, after):
    threshold_before = -(34 / 60 + before["angularDiameterArcseconds"] / 7_200)
    threshold_after = -(34 / 60 + after["angularDiameterArcseconds"] / 7_200)
    residual_before = before["altitudeDegrees"] - threshold_before
    residual_after = after["altitudeDegrees"] - threshold_after
    if residual_before == 0 or residual_after == 0 or residual_before * residual_after >= 0:
        raise ValueError("Horizons rows do not bracket the limb crossing")
    fraction = -residual_before / (residual_after - residual_before)
    event_jd = before["jdUTC"] + fraction * (after["jdUTC"] - before["jdUTC"])
    dut1 = before["ut1MinusUTCSeconds"] + fraction * (after["ut1MinusUTCSeconds"] - before["ut1MinusUTCSeconds"])
    return {"utc": iso(event_jd), "jdUTC": event_jd, "ut1MinusUTCSeconds": dut1, "fraction": fraction}


def compare_usno_event(usno, horizons):
    horizons_jd_ut1 = horizons["jdUTC"] + horizons["ut1MinusUTCSeconds"] / 86_400
    difference = (horizons["jdUTC"] - usno["jdUT1"]) * 86_400 + horizons["ut1MinusUTCSeconds"]
    horizons_minute = iso(horizons_jd_ut1).removesuffix("Z")[:16]
    if horizons_minute != usno["ut1DateTime"][:16]:
        raise ValueError("USNO and Horizons events differ at published minute resolution")
    return {**usno, "horizonsDifferenceSeconds": difference}


def fixture(data=None):
    data = DATA if data is None else data
    horizons_document, horizons_query = read_source(data / "horizons.json")
    usno_document, usno_query = read_source(data / "usno.json")
    rows, eop = parse_horizons(horizons_document, horizons_query)
    usno = parse_usno(usno_document, usno_query)
    sources = []
    for name in SOURCE_NAMES:
        for suffix in (".json", ".query.json"):
            path = data / f"{name}{suffix}"
            sources.append({"path": f"Scripts/deltat-data/civil-horizon/{path.name}", "sha256": sha256(path)})
    sunrise = crossing(rows[0], rows[1])
    sunset = crossing(rows[3], rows[4])
    usno["events"]["rise"] = compare_usno_event(usno["events"]["rise"], sunrise)
    usno["events"]["set"] = compare_usno_event(usno["events"]["set"], sunset)
    return {
        "schemaVersion": 1,
        "model": "iersObserved",
        "site": {"latitudeDegrees": 35.5951, "longitudeDegrees": -82.5515, "heightMeters": 0},
        "horizons": {
            "ephemeris": "DE441",
            "earthOrientationFile": eop,
            "timeScale": "UTC with source UT1-UTC",
            "refraction": "airless",
            "rows": rows,
            "horizon": rows[2],
            "sunrise": sunrise,
            "sunset": sunset,
        },
        "usno": usno,
        "sources": sources,
    }


def encoded_fixture(data=None):
    return (json.dumps(fixture(data), indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def source_url(query):
    if "url" in query:
        return query["url"]
    parameters = {key: value for key, value in query.items() if not key.startswith("_")}
    return "https://ssd.jpl.nasa.gov/api/horizons.api?" + urllib.parse.urlencode({"format": "json", **parameters})


def refresh(publish):
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory) / "civil-horizon"
        shutil.copytree(DATA, candidate)
        for name in SOURCE_NAMES:
            query_path = candidate / f"{name}.query.json"
            query = json.loads(query_path.read_bytes())
            payload = urllib.request.urlopen(source_url(query), timeout=120).read()
            json.loads(payload)
            (candidate / f"{name}.json").write_bytes(payload)
            query["_responseSHA256"] = hashlib.sha256(payload).hexdigest()
            query["_retrieved"] = datetime.date.today().isoformat()
            query_path.write_text(json.dumps(query, indent=2) + "\n")
        result = encoded_fixture(candidate)
        if publish:
            for name in SOURCE_NAMES:
                for suffix in (".json", ".query.json"):
                    (DATA / f"{name}{suffix}").write_bytes((candidate / f"{name}{suffix}").read_bytes())
            FIXTURE.write_bytes(result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--download", action="store_true")
    arguments = parser.parse_args()
    result = refresh(publish=not arguments.check) if arguments.download else encoded_fixture()
    if arguments.check:
        if FIXTURE.read_bytes() != result:
            raise SystemExit("civil UTC horizon fixture differs")
    elif not arguments.download:
        FIXTURE.write_bytes(result)
    print("civil UTC horizon references verified")


if __name__ == "__main__":
    main()
