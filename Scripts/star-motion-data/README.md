# Catalog-motion qualification

`gaia-dr3.csv` is the exact response to `gaia-dr3.query.json` from the ESA Gaia Archive DR3 TAP service. It contains Gaia DR3 source IDs 4472832130942575872 and 5853498713190525696, commonly identified as Barnard's star and Proxima Centauri. The qualification keys rows only by source ID. The values are published catalog inputs: barycentric ICRS right ascension and declination at TCB Julian year 2016.0, parallax in milliarcseconds, `pmra = dRA/dt*cos(declination)` and `pmdec = dDec/dt` in milliarcseconds per Julian year, and the catalog's barycentric spectroscopic radial velocity in kilometers per second. They are not independently observed future positions or exact kinematic truth.

`sofa-reference.json` comes from unchanged IAU SOFA 2023-10-11 `pmsafe`, `starpm`, `pmpx`, and `tdbtcb` routines compiled from the pinned source archive. The grid propagates both catalog rows to TDB Julian years 1991.25, 2016, 2050, and 2100 after converting each target coordinate to TCB. The separate 2050 clock comparison measures the difference from the unsupported shortcut that treats the numerical TCB catalog epoch as if it were TDB; it is explanatory sampled evidence, not an uncertainty bound. A synthetic `pmpx` reference records the observer-dependent reception-time correction for a star at 10 light-years with 1,000 milliarcseconds per Julian year of right-ascension motion and an observer displaced by one astronomical unit along the ICRS x-axis. It checks the public composition independently of the Gaia rows and is not an accuracy claim for the synthetic star.

The Gaia DR3 documentation states that Gaia data are open and free provided users credit ESA/Gaia/DPAC and gives the requested mission and release citations. AstronomyKit retains that credit and does not imply endorsement. See [Gaia DR3 source data model](https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html) and [credit and citation instructions](https://gea.esac.esa.int/archive/documentation/GDR3/Miscellaneous/sec_credit_and_citation_instructions/).

```sh
python3 Scripts/capture-sofa-star-motion.py --refresh  # explicitly retrieve the pinned Gaia query; validates before replacement
python3 Scripts/capture-sofa-star-motion.py --capture  # compile pinned SOFA and stage a complete replacement report
python3 Scripts/capture-sofa-star-motion.py --check    # verify identities, provenance, finite values, and bound owner hashes
python3 -m unittest Scripts/test_capture_sofa_star_motion.py
```
