# 2026 SVS lunar-obscuration source comparison

NASA SVS 5672 says that 96.3% of the Moon's disc is inside Earth's umbra at greatest eclipse on 2026-08-28. This artifact preserves that published datum and the repository's unchanged conditional nearest-0.1-percentage-point interval of `[0.9625, 0.9635]`. It does not establish an accuracy tolerance or a production defect.

## Result

The exact SVS convention cannot be reproduced from the published source material. The SVS page identifies DE421, LOLA, and the Five Millennium Canon of Lunar Eclipses as datasets, then says it does not retain further dataset details. It does not publish the state vectors, full-precision peak epoch, radii, limb treatment, projection, overlap algorithm, full-precision result, or rounding rule used for 96.3%.

The offline replay verifies its issue-owned NASA and JPL source snapshots, extracts the one Horizons row at JD TT 2461280.676452763, and independently applies the documented circular Danjon tangent-plane geometry. Its standard-library result is `0.962481599215371`, within `1.1e-14` of the archived 80-digit calculation `0.962481599215360765...`. The pinned native Debug and Release result is `0.9624960076659318`. Both remain below `0.9625`, so neither reproduces the conditional SVS print interval.

| Evidence | Ephemeris and epoch | Quantity | Result |
| --- | --- | --- | --- |
| [NASA SVS 5672](https://svs.gsfc.nasa.gov/5672/) | Names DE421; prints greatest eclipse as 04:13 UT | Moon-disc area inside the umbra | 96.3% |
| [NASA Five Millennium Catalog](https://eclipse.gsfc.nasa.gov/LEcat5/LE2001-2100.html) | VSOP87 Sun, ELP-2000/82 Moon; 04:14:04 UT | Umbral magnitude, a diameter fraction | 0.9299 |
| [JPL Horizons](https://ssd.jpl.nasa.gov/horizons/) replay | DE441 apparent ICRF directions; JD TT 2461280.676452763 | Circular Danjon Moon-disc area | 0.962481599215371 |
| Pinned native capture | Repository apparent-input model at its selected peak | Circular Danjon Moon-disc area | 0.9624960076659318 |

## Direct DE421 replay

`de421_replay.py` reads ten canonical byte ranges from JPL/NAIF's 16,790,528-byte `de421.bsp` release, interpolates its type-2 ICRF Earth, Moon, and Sun records, and compares 20 declared peak and shadow combinations. At the retained native peak, simultaneous DE421 geometry with the Five Millennium Catalog's printed `Ru = 1.01 * Pm - Ss + Ps` formula gives `0.9615818523835685`. The same calculation from an independently archived DE441 Horizons vector gives `0.9615818677584221`, a difference of `-0.0000000153748536` in obscuration. Replacing the geometric DE441 vectors with the previously archived apparent directions and ranges changes obscuration by `+0.0008997314569489`. These are differences between specified calculations, not uncertainty estimates or proof of the SVS implementation.

The peak choices are also too small to account for the print discrepancy. Inside the fixed plus-or-minus 300-second event window, the bracketed local minimum of DE421 tangent-plane axis distance occurs `39.4235238` seconds after the retained native peak, and the bracketed local angular-separation minimum occurs `1.2395024` seconds before that. The source matrix applies the catalog's published 75-second Delta T to its 04:14:04 UT peak and, as an explicitly labeled hypothesis, to the SVS 04:13 printed minute. Evaluating the two endpoints of the documented two-millisecond TDB-minus-TT amplitude gives a sampled obscuration span of `8.4e-9`; this endpoint sensitivity is not a certified interval bound.

The shadow rows use four formulas published on NASA's shadow-convention page: un-enlarged geometry, the Five Millennium Catalog's decimal `1.01` Danjon factor, its expanded `1 + 1/85 - 1/594` explanation, and the contrasting Chauvenet formula. At the retained epoch they produce obscurations from `0.9462267972` to `0.9654880746`; none of the 20 declared rows falls inside `[0.9625, 0.9635]`. This finite result does not rule out an undisclosed SVS convention. No row was selected or adjusted for proximity to 96.3%.

The archived LOLA product page establishes a 1737.4 km reference sphere and identifies global 64- and 128-pixel-per-degree elevation products in the MOON_PA DE421 frame. The replay uses that reference sphere. SVS does not identify a LOLA product version, lunar orientation, limb extraction, mesh, projection, shadow mask, or covered-area algorithm, so the replay does not claim to apply topography to the 96.3% calculation.

The catalog's 0.9299 cannot be substituted for the SVS area percentage: NASA defines lunar umbral magnitude as the fraction of the Moon's diameter covered by the umbra, while SVS explicitly defines 96.3% as covered area. The catalog's VSOP87/ELP-2000/82 model and 04:14:04 UT peak also cannot establish the DE421 visualization's states or its printed 04:13 minute. The DE441 Horizons calculation is an independent arithmetic control on specified inputs, not evidence of DE421 agreement.

## Reproduce

Run the deterministic offline checks from the repository root:

```sh
python3 Scripts/svs-lunar-obscuration/replay.py --check
python3 Scripts/svs-lunar-obscuration/de421_replay.py --check
python3 -m unittest Scripts/svs-lunar-obscuration/test_replay.py Scripts/svs-lunar-obscuration/test_de421_replay.py
```

To verify the retained byte ranges against the complete primary kernel, download the canonical source to a path outside the repository and run `python3 Scripts/svs-lunar-obscuration/capture_de421.py --check-source /path/to/de421.bsp`. The check requires the exact full-file length and SHA-256 before it compares all extracted ranges. `--capture` is the supported publication path when the source identity or range inventory intentionally changes; it stages and verifies the complete replacement before publishing it.

`source-receipts.json` binds local snapshots of the SVS page, Five Millennium Catalog page, Horizons queries and responses, independent 80-digit comparison, and native Debug/Release capture to SHA-256 digests at base revision `3c31e2d56eb4e887554ea185f5f75bdb78b3a674`. The replay has no path dependency on other evidence-owner directories. The NASA pages were checked live on 2026-10-13. The catalog bytes still matched the snapshot; the SVS page bytes had changed while the datum, dataset list, and missing-detail disclaimer remained present, so the replay retains the reviewed base snapshot rather than silently replacing it.

`results.json` is generated only by `replay.py --write`. `--check` rejects source-byte drift, query-response mismatches, missing source statements, changes to the derived comparison, and an unexpected match to the printed interval. The unit tests also reject confusing diameter magnitude with area obscuration, substituting the catalog time for the SVS printed minute, or treating DE441 as the named DE421 source model.

## Qualification boundary

Under the replay's fixed simultaneous-geometry inputs, the DE421-versus-DE441 difference is about 260 times smaller than the `0.0000039923340682` native shortfall, and the tested peak interpretations do not restore the print interval. The replay demonstrates a larger apparent-versus-geometric model difference and a larger spread among published shadow formulas, but the missing SVS inputs prevent attribution to either. The lunar limb/topography, exact peak, projection, overlap arithmetic, full-precision value, and rounding remain unresolved. Issue #275 should remain open unless those source conventions become available. The existing datum, interval, known-issue assertion, runtime, and broader #93 eclipse decisions remain unchanged.

NASA authored the source pages and JPL Horizons responses. This repository stores factual extracts and hashes with attribution; see [NASA's media usage guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/) for reuse conditions. AstronomyKit's replay code and transformed result remain under the repository license.
