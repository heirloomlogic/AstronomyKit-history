#!/usr/bin/env python3
"""Source-bound rational derivation of the partial native solar-altitude budget."""
from fractions import Fraction as Q
import precession_bounds
import apparent_bounds
import selected_earth_bounds
import argparse
import ast
import base64
import json
import re
import struct

from intervals import Interval as I, DeltaT, expression, year_start
from certify_light_time import constants as convergence_constants, C
from numerics import ROOT, ENGINE, record, sqrt_interval, upward, downward, BINDINGS, source_hashes, check_hashes, unpack


def pi_interval():
    def arctan_inverse(n):
        total = Q(0)
        for k in range(100):
            total += Q((-1)**k, (2*k+1)*n**(2*k+1))
        remainder = Q(1, 201*n**201)
        return I(total, total+remainder)
    return 16*arctan_inverse(5)-4*arctan_inverse(239)


def coefficients(text):
    return [Q(value.strip().replace('_', '')) for value in text.split(',')]


def rate(poly, t):
    return sum(k*abs(value)*t**(k-1) for k,value in enumerate(poly) if k)


def frame_rates():
    pi = pi_interval().hi
    t = Q('1.02')
    long_term = precession_bounds.enclose(t)
    obliquity = long_term['meanObliquity']
    precession = long_term['precession']
    text = (ROOT/(ENGINE+'Orientation/EngineNutation.swift')).read_text()
    arguments = text.split('luniSolarArguments: [[Double]] = [',1)[1].split('    ]',1)[0]
    luni_solar_rates = [rate(coefficients(row),t)*pi/648000 for row in re.findall(r'\[([-+0-9_., ]+)\]', arguments)]
    arguments = text.split('planetaryArguments:',1)[1].split('    ]',1)[0]
    planetary_rates = [abs(coefficients(row)[1]) for row in re.findall(r'\(([-+0-9_., ]+)\),', arguments)]
    match = re.search(r'generalPrecession = \(linear: ([0-9_.]+), quadratic: ([0-9_.]+)\)', text)
    p0,p1 = [Q(value.replace('_','')) for value in match.groups()]
    planetary_rates.append(p0+2*p1*t)
    table = (ROOT/(ENGINE+'Orientation/Generated/IAU2000ATerms.swift')).read_text()
    def rows(block, width):
        values = [Q(value) for value in unpack(block)]
        return [values[i:i+width] for i in range(0, len(values), width)]
    luni_solar_block, planetary_block = table.split('static let planetaryTerms', 1)
    luni_solar, planetary = rows(luni_solar_block, 11), rows(planetary_block, 17)
    factor, j2 = [abs(Q(re.search(r'static let '+name+r' = (\S+)\n', table)[1])) for name in ['longitudeFactor','j2Rate']]
    if len(luni_solar_rates) != 5 or len(planetary_rates) != 13 or len(luni_solar) != 678 or len(planetary) != 687:
        raise ValueError('Nutation data layout changed')
    # IAU 2000A in 0.1 microarcsecond and per century: value and rate bounds.
    longitude00, oblique00, amplitude00, obliquity_amplitude00 = Q(0), Q(0), Q(0), Q(0)
    for row in luni_solar:
        argument_rate = sum(abs(n*w) for n,w in zip(row[:5],luni_solar_rates) if n)
        ps,pst,pc,ec,ect,es = row[5:]
        p = abs(ps)+abs(pst)*t+abs(pc)
        e = abs(ec)+abs(ect)*t+abs(es)
        longitude00 += p*argument_rate+abs(pst)
        oblique00 += e*argument_rate+abs(ect)
        amplitude00 += p
        obliquity_amplitude00 += e
    for row in planetary:
        argument_rate = sum(abs(n*w) for n,w in zip(row[:13],planetary_rates) if n)
        ps,pc,es,ec = row[13:]
        longitude00 += (abs(ps)+abs(pc))*argument_rate
        oblique00 += (abs(es)+abs(ec))*argument_rate
        amplitude00 += abs(ps)+abs(pc)
        obliquity_amplitude00 += abs(es)+abs(ec)
    # The IAU 2006 factors 1 + factor + j2·t and 1 + j2·t, and their t derivative j2.
    unit = Q('1e-7')/3600
    longitude = ((longitude00*(1+factor+j2*t)+amplitude00*j2)*unit/36525)
    oblique = ((oblique00*(1+j2*t)+obliquity_amplitude00*j2)*unit/36525)
    amplitude = amplitude00*(1+factor+j2*t)*unit
    text = (ROOT/(ENGINE+'Orientation/EngineEquationOfEquinoxes.swift')).read_text()
    argument_polys = [coefficients(row) for row in re.findall(r'= turn\(([^)]+)\)',text)]
    argument_rates = [rate(poly,t)*pi/648000 for poly in argument_polys]
    for name in ['ve','e']:
        match = re.search(r'\n            '+name+r' = fmod\([^+]+\+ ([0-9_.]+) \* t,',text)
        argument_rates.append(Q(match[1].replace('_','')))
    match = re.search(r'pa = \(([0-9_.]+) \+ ([0-9_.]+) \* t\) \* t',text)
    p0,p1 = [Q(value.replace('_','')) for value in match.groups()]
    argument_rates.append(p0+2*p1*t)
    table = (ROOT/(ENGINE+'Orientation/Generated/EquinoxComplementaryTerms.swift')).read_text()
    complementary = [coefficients(row) for row in re.findall(r'ComplementaryTerm\(([^)]+)\)',table)]
    if len(argument_rates) != 8 or len(complementary) != 34:
        raise ValueError('Complementary-series data layout changed')
    complement_rate = Q(0)
    for index,row in enumerate(complementary):
        amplitude_c = abs(row[8])+abs(row[9])
        frequency = sum(abs(n*w) for n,w in zip(row[:8],argument_rates))
        complement_rate += amplitude_c*(frequency*(t if index == 33 else 1)+(1 if index == 33 else 0))/3600/36525
    text = (ROOT/(ENGINE+'Orientation/EngineEarthRotation.swift')).read_text()
    polynomial = ' '.join(text.split('let precession =',1)[1].split('let degrees',1)[0].split())
    sidereal = expression(polynomial, {'t':I(-t,t)}, {'t':1}).abs_upper()/3600/36525
    return {'precession':precession, 'meanObliquity':obliquity, 'nutationLongitude':longitude,
            'nutationObliquity':oblique, 'complementary':complement_rate, 'siderealPolynomial':sidereal,
            'precessionNutation':precession+2*obliquity+longitude+oblique,
            'siderealTT':sidereal+longitude+amplitude*obliquity*pi/180+complement_rate}


def observed_model_bounds():
    """Rate, magnitude, and arithmetic guards from the observed model's sources."""
    path = ROOT/(ENGINE+'Foundation/Generated/DeltaTObservedTable.swift')
    text = path.read_text()
    first_mjd = int(re.search(r'static let firstMJD = ([0-9_]+)', text)[1].replace('_', ''))
    rows_block = text.split('static let rows: Rows = {', 1)[1]
    payload = base64.b64decode(''.join(rows_block.split('"""', 2)[1].split()), validate=True)
    count = int(re.search(r'count: ([0-9_]+)', rows_block)[1].replace('_', ''))
    packed = struct.unpack(f'<{count}d', payload)
    if count % 3 or len(packed) != count:
        raise ValueError('Observed Delta T row layout changed')
    first_ut = Q(first_mjd) - Q('51544.5')
    delta_t, row_ut = [], []
    for index in range(count // 3):
        dt = packed[3*index] / 1.0e7
        dut = packed[3*index+1] / 1.0e7
        ut = float(first_ut + index) + dut / 86400.0
        delta_t.append(Q(dt))
        row_ut.append(Q(ut))
    daily_rate = max(abs((after-before)/(stop-start)) for before,after,start,stop in
                     zip(delta_t,delta_t[1:],row_ut,row_ut[1:]))

    segments = []
    for row in re.findall(r'Segment\(start: ([^,]+), end: ([^,]+), a0: ([^,]+), a1: ([^,]+), a2: ([^,]+), a3: ([^)]+)\)', text):
        segments.append(tuple(Q(float(value.replace('_', ''))) for value in row))
    if not segments or segments[-1][1] < 1961:
        raise ValueError('Observed Delta T spline layout changed')
    domain_years = [Q(2000)+Q(value)/Q('365.25') for value in [-37000, 37000]]
    historical_rates = []
    historical_magnitudes = []
    for start,end,a0,a1,a2,a3 in segments:
        if end < domain_years[0] or start > domain_years[1]:
            continue
        candidates = [Q(0), Q(1)]
        if a3:
            vertex = -a2/(3*a3)
            if 0 < vertex < 1:
                candidates.append(vertex)
        historical_rates.append(max(abs(a1+2*a2*t+3*a3*t*t) for t in candidates)/(end-start)/Q('365.25'))
        historical_magnitudes.append(abs(a0)+abs(a1)+abs(a2)+abs(a3))

    constants = {}
    for name in ['lodRate', 'lodAmplitude', 'lodPeriod', 'lodPhase', 'lodEpoch']:
        constants[name] = Q(float(re.search(rf'static let {name} = (\S+)', text)[1].replace('_', '')))
    t_max = max(abs((year-constants['lodEpoch'])/100) for year in domain_years)
    extrapolated_rate = (abs(constants['lodRate'])*t_max+abs(constants['lodAmplitude']))/1000
    integral_magnitude = Q('36.525')*(Q(1,2)*abs(constants['lodRate'])*t_max*t_max+
                                             abs(constants['lodAmplitude'])*constants['lodPeriod']/(2*pi_interval().lo))
    magnitude = max(max(delta_t), -min(delta_t), max(historical_magnitudes),
                    max(abs(delta_t[-1]-2*integral_magnitude), abs(delta_t[-1]+2*integral_magnitude)))
    rate = max(daily_rate, max(historical_rates), extrapolated_rate)
    source = (ROOT/(ENGINE+'Foundation/EngineDeltaTObserved.swift')).read_text()
    expressions = [
        'before + f * (after - before)',
        'segment.a0 + t * (segment.a1 + t * (segment.a2 + t * segment.a3))',
        '36.525 * (tidal + fluctuation)',
    ]
    if any(value not in source for value in expressions):
        raise ValueError('Observed Delta T evaluation graph changed')
    # The largest native branch has fewer than 64 basic operations. This
    # majorant covers its time arguments, values, coefficients, and the two
    # long-term integrals. The cos result is bounded by one here; libm
    # evaluation error remains an explicit exclusion of the altitude budget.
    epsilon = Q(1, 2**53)
    gamma64 = 64*epsilon/(1-64*epsilon)
    arithmetic_majorant = Q(37000)+magnitude+max(historical_magnitudes)+max(abs(value) for value in delta_t)+2*integral_magnitude
    arithmetic_error = gamma64*arithmetic_majorant
    forward_error = arithmetic_error/86400+epsilon*abs(magnitude/86400)+epsilon*(Q(37000)+abs(magnitude/86400))
    if rate >= 2 or magnitude >= 25000:
        raise ValueError(f'Observed Delta T source bounds changed: rate={rate}, magnitude={magnitude}')
    if arithmetic_error >= Q('1e-8') or forward_error >= Q('1e-10'):
        raise ValueError('Observed Delta T arithmetic guard assumptions changed')
    return {'dailyRateSecondsPerDay':daily_rate, 'historicalRateSecondsPerDay':max(historical_rates),
            'extrapolatedRateSecondsPerDay':extrapolated_rate, 'rateSecondsPerDay':rate,
            'magnitudeSeconds':magnitude, 'arithmeticErrorSeconds':arithmetic_error,
            'derivedForwardArithmeticErrorDays':forward_error, 'roundingFactors':64,
            'rowCount':count//3, 'splineSegmentCount':len(segments)}


def classification_guard():
    delta = DeltaT()
    bounds = [1898,1900,1920,1941,1961,1986,2005,2050,2102]
    majorants, derivatives, operation_counts = [], [], []
    for begin,end in zip(bounds,bounds[1:]):
        y = I(begin,end)
        derivatives.append(delta.derivative_at_year(y,begin).abs_upper())
        for stop,origin,result in delta.pieces:
            if begin < stop:
                u = expression(origin, {'y':y})
                text = re.sub(r'p\.u(\d+)',r'(u**\1)',result.replace('_',''))
                tree = ast.parse(text,mode='eval')
                def majorant(node):
                    if isinstance(node,ast.Constant):
                        return abs(Q(ast.get_source_segment(text,node)))
                    if isinstance(node,ast.Name):
                        return {'u':u.abs_upper(),'y':y.abs_upper()}[node.id]
                    if isinstance(node,ast.UnaryOp):
                        return majorant(node.operand)
                    if isinstance(node,ast.BinOp):
                        left,right = majorant(node.left),majorant(node.right)
                        if isinstance(node.op,(ast.Add,ast.Sub)): return left+right
                        if isinstance(node.op,ast.Mult): return left*right
                        if isinstance(node.op,ast.Pow): return left**int(right)
                        if isinstance(node.op,ast.Div) and isinstance(node.right,ast.Constant): return left/right
                    raise ValueError('Unsupported DeltaT majorant expression')
                majorants.append(majorant(tree.body))
                # Expanded powers require at most n multiplications, including
                # the input subtraction. Count every literal and tree operation.
                count = sum(1 for node in ast.walk(tree) if isinstance(node,(ast.Constant,ast.BinOp)))
                count += sum(node.right.value for node in ast.walk(tree) if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Pow))
                count += 10  # origin arithmetic and the shared Powers products
                operation_counts.append(count)
                break
    if max(majorants) >= 5000 or max(derivatives) >= 20 or max(operation_counts) >= 100:
        raise ValueError('Native DeltaT classification guard assumptions changed')
    source = (ROOT/(ENGINE+'Foundation/EngineDeltaT.swift')).read_text()
    if 'min(decimal, (year + 1).nextDown)' not in source:
        raise ValueError('Decimal-year boundary clamp changed')
    expected_powers = ['u2 = u * u', 'u3 = u * u2', 'u4 = u2 * u2', 'u5 = u2 * u3', 'u6 = u3 * u3', 'u7 = u3 * u4']
    if any(line not in source for line in expected_powers):
        raise ValueError('DeltaT Powers multiplication graph changed')
    epsilon = Q(1,2**53)
    gamma100 = 100*epsilon/(1-100*epsilon)
    delta_error = gamma100*5000+20*Q('1e-12')+Q(20,365)*Q('2e-12')
    forward_error = delta_error/86400+epsilon*Q(5000,86400)+epsilon*(37000+Q(5000,86400))
    if delta_error >= Q('1e-10') or forward_error >= Q('5e-12'):
        raise ValueError('Classification guard no longer encloses forward TT')
    return {'guardDays':Q('1e-9'),'derivedForwardErrorDays':forward_error,
            'deltaTErrorSeconds':delta_error,'majorantSeconds':max(majorants),
            'derivativeSecondsPerYear':max(derivatives),'roundingFactors':max(operation_counts)}


def derive():
    convergence = convergence_constants()
    light = json.loads((ROOT/'Scripts/solar-numerics/derived-light-convergence.json').read_text())
    check_hashes(ROOT, light['sourceSHA256'])
    guard = classification_guard()
    observed = observed_model_bounds()
    if observed['derivedForwardArithmeticErrorDays'] >= guard['guardDays']:
        raise ValueError('Observed Delta T forward error exceeds the classification guard')
    earth = selected_earth_bounds.derive()
    rmin = earth['radiusMinimumAU']
    v, p = earth['speedAUPerTTDay'], earth['joinMaximumAU']
    a, m = 1+convergence['deltaTSlopeSecondsPerDay']/86400, 1-convergence['deltaTSlopeSecondsPerDay']/86400
    observed_a = 1+observed['rateSecondsPerDay']/86400
    observed_m = 1-observed['rateSecondsPerDay']/86400
    k = convergence['k']
    delta = DeltaT()
    magnitude = max(delta.at_year(I(year,year+1),year).abs_upper() for year in range(1898,2102))
    source = (ROOT/(ENGINE+'Orientation/EngineObserver.swift')).read_text()
    observer_a = Q(re.search(r'equatorialRadiusKilometers = ([0-9_.]+)',source)[1].replace('_',''))
    constants_source = (ROOT/(ENGINE+'Foundation/EngineConstants.swift')).read_text()
    au = Q(re.search(r'kilometersPerAU = ([0-9_.]+)', constants_source)[1].replace('_',''))
    site = (observer_a+10)/au
    # This margin bounds all composed perturbations below; verify it after deriving them.
    rho = rmin-site-Q('.00001')
    deg_per_rad = 180/pi_interval().lo
    rates = frame_rates()
    era_source = (ROOT/(ENGINE+'Orientation/EngineEarthRotation.swift')).read_text().replace('_','')
    era_terms = re.search(r'let turns = ([0-9.]+) \+ ([0-9.]+) \* ut \+ fmod\(ut, 1.0\)', era_source)
    if not era_terms or 'Engine.normalized(360 * fmod(turns, 1.0), period: 360)' not in era_source:
        raise ValueError('ERA arithmetic expression changed')
    era_offset, era_rate = map(Q, era_terms.groups())
    omega = 360*(1+era_rate)
    orientation = apparent_bounds.orientation_bounds()
    site_speed = site*orientation['siteSpeedPerRadius']
    site_acceleration = site*orientation['siteAccelerationPerRadius']
    solar_speed = convergence['V']
    solar_acceleration = convergence['solarAccelerationTT']
    clock_q = convergence['clockRateDeparture']
    clock_second = convergence['solarAccelerationPerDay']
    earth_acceleration = earth['accelerationAUPerTTDay2']
    observer_speed = v+solar_speed+site_speed
    observer_acceleration = earth_acceleration+solar_acceleration+site_acceleration
    beta_upper = observer_speed/(1-clock_q)/C
    beta_rate = (observer_acceleration/(1-clock_q)+observer_speed*clock_second/(1-clock_q)**2)/C
    if beta_upper >= Q('.001'):
        raise ValueError('Relativistic map beta enclosure changed')
    # For |beta|<.001 and h=SRS/s, bound the unnormalized eraAb norm from below.
    srs=Q('1.97412574336e-8')
    h=srs/rho
    inverse_gamma=sqrt_interval(1-beta_upper**2)[0]
    unnormalized_min=inverse_gamma-beta_upper*(1+beta_upper)-2*h*beta_upper
    p_lipschitz=(1+beta_upper**2+2*h*beta_upper)/unnormalized_min
    beta_lipschitz=(beta_upper/inverse_gamma+1+2*beta_upper+beta_upper**3/inverse_gamma+2*h)/unnormalized_min
    if p_lipschitz>=2 or beta_lipschitz>=4 or unnormalized_min<=0:
        raise ValueError('Relativistic normalization derivative enclosure changed')
    distance_lipschitz=2*beta_upper*srs/rho**2/unnormalized_min
    propagation=1+solar_speed/(C*(1-k))
    ut_relative=site_speed*propagation
    tt_relative=(v+2*solar_speed+site_speed)*propagation
    ut_beta_rate=site_acceleration/(1-clock_q)/C
    ut_sensitivity=deg_per_rad*(2*ut_relative/rho+4*ut_beta_rate+distance_lipschitz*site_speed)+omega
    tt_sensitivity=deg_per_rad*(2*tt_relative/rho+4*beta_rate+distance_lipschitz*(v+site_speed))+rates['precessionNutation']+rates['siderealTT']
    velocity_join=earth['velocityJoinAUPerTTDay']
    join_degrees=deg_per_rad*(2*p/rho+4*velocity_join/(1-clock_q)/C+distance_lipschitz*p)
    u = Q(1,2**53)
    gamma = lambda n: n*u/(1-n*u)
    domain = Q(37000)
    forward = gamma(2)*(domain+magnitude/86400)
    observed_forward = gamma(2)*(domain+observed['magnitudeSeconds']/86400)
    tolerance = 4*u*domain
    inverse_residual = tolerance/(1-u)+forward
    inverse_days = inverse_residual/m
    observed_inverse_days = (tolerance/(1-u)+observed_forward)/observed_m
    inverse_jump_days = convergence['D']/m
    # Foundation adds its epoch offset, then civilDays subtracts J2000 and divides.
    civil = gamma(3)*(domain+Q(978307200+946728000,86400))
    table = (ROOT/'Sources/AstronomyKit/UTCOffsetTable.swift').read_text()
    segments = [coefficients(','.join(row)) for row in re.findall(r'Segment\(start: ([^,]+), offset: ([^,]+), rate: ([^)]+)\)',table)]
    civil_tt = Q(0)
    for start,offset,slope in segments:
        span = domain+abs(start)
        magnitude_offset = abs(offset)+abs(slope)*span
        error = gamma(8)*(domain+(magnitude_offset+abs(slope)*span)/86400)
        civil_tt = max(civil_tt, civil*(1+abs(slope)/86400)+error)
    light_days = convergence['successfulRootErrorDays']
    light_au = solar_speed*light_days
    light_jump_au = Q(0)  # Emission uses TT/TDB directly, with no Delta T branch conversion.
    era_angle = gamma(8)*(era_offset+era_rate*domain+1)*360+u*360
    values = {
        'civilCalendarDays':civil,
        'civilToTTDays':civil_tt,
        'civilToTTDegrees':(ut_sensitivity/m+tt_sensitivity)*civil_tt,
        'civilToUTDegrees':(ut_sensitivity+tt_sensitivity*a)*civil,
        'forwardTTDegrees':tt_sensitivity*forward,
        'ttInverseDegrees':ut_sensitivity*inverse_days,
        'lightTimeDegrees':deg_per_rad*2*light_au/rho+join_degrees,
        'eraDegrees':era_angle*(1+2*site*propagation/rho+4*site_speed/(1-clock_q)/C+distance_lipschitz*site),
        'joinDegrees':join_degrees,
        'arrivalJumpInverseDegrees':ut_sensitivity*inverse_jump_days,
        'arrivalJumpForwardDegrees':tt_sensitivity*convergence['D'],
        'lightTimeJumpDegrees':deg_per_rad*light_jump_au/rho,
        'arrivalUncertaintyBaseDays':inverse_days+civil+civil_tt/m,
        'arrivalUncertaintyDays':inverse_days+inverse_jump_days+civil+civil_tt/m,
        'forwardTTDays':forward,
        'classificationGuardDays':guard['guardDays'],
        'classificationInverseGuardDays':guard['guardDays']/m,
        'deltaTJumpDays':convergence['D'],
        'ttImageSlope':a,
        'backdateMaxDays':convergence['T'],
        'utSensitivityDegreesPerDay':ut_sensitivity,
        'ttSensitivityDegreesPerDay':tt_sensitivity,
        'observedCivilToTTDegrees':(ut_sensitivity/observed_m+tt_sensitivity)*civil_tt,
        'observedCivilToUTDegrees':(ut_sensitivity+tt_sensitivity*observed_a)*civil,
        'observedForwardTTDegrees':tt_sensitivity*observed_forward,
        'observedTTInverseDegrees':ut_sensitivity*observed_inverse_days,
        'observedArrivalUncertaintyDays':observed_inverse_days+civil+civil_tt/observed_m,
        'observedClassificationInverseGuardDays':guard['guardDays']/observed_m,
        'observedTTImageSlope':observed_a,
        'observedDeltaTRateSecondsPerDay':observed['rateSecondsPerDay'],
        'observedForwardUncertaintyDegreesPerSecond':tt_sensitivity/86400,
        'observedInverseUncertaintyDegreesPerSecond':ut_sensitivity/(86400*observed_m),
    }
    max_earth_perturbation = light_au+light_jump_au+v*a/(1-k)*values['arrivalUncertaintyDays']
    observed_max_earth_perturbation = light_au+v*observed_a/(1-k)*values['observedArrivalUncertaintyDays']
    if max(max_earth_perturbation, observed_max_earth_perturbation) >= Q('.00001') or max(
        values['arrivalUncertaintyDays'], values['observedArrivalUncertaintyDays']) >= Q('.00001'):
        raise ValueError('The denominator or classification margin is insufficient')
    if 2*max(values['arrivalUncertaintyDays'], values['observedArrivalUncertaintyDays'])+convergence['T'] >= 1:
        raise ValueError('Time hull can span multiple selected source joins in one component')
    paths = sorted(set(BINDINGS + precession_bounds.PATHS + apparent_bounds.PATHS + [
        'Scripts/solar-numerics/derive_altitude.py', 'Scripts/solar-numerics/intervals.py',
        'Scripts/solar-numerics/certify_light_time.py', 'Scripts/solar-numerics/selected_earth_bounds.py',
        'Scripts/solar-numerics/derived-light-convergence.json',
        'Sources/AstronomyKit/Time.swift', 'Sources/AstronomyKit/Observer.swift',
        'Sources/AstronomyKit/Position.swift', 'Sources/AstronomyKit/SolarAltitudeObservation.swift',
        ENGINE+'Foundation/EngineDeltaTObserved.swift', ENGINE+'Foundation/Generated/DeltaTObservedTable.swift',
        *[ENGINE+path for path in [
            'Positions/EngineGeocentric.swift', 'Positions/EngineEquatorial.swift',
            'Orientation/EngineObserver.swift', 'Orientation/EngineFrameRotations.swift',
            'Orientation/EnginePrecession.swift', 'Orientation/EngineEquationOfEquinoxes.swift',
            'Orientation/Generated/EquinoxComplementaryTerms.swift', 'Orientation/EngineHorizon.swift',
            'Orientation/EngineRefraction.swift', 'Orientation/EngineRotations.swift']],
    ]))
    return {'kind':'native-partial-altitude-derivation', 'schemaVersion':1, 'sourceSHA256':source_hashes(ROOT,paths),
            'dependency':'Selected Earth majorants are reconstructed; the finite convergence artifact must also pass its full check command',
            'excludedAltitudeErrors':['polynomial evaluation and fit','frame and sidereal arithmetic','horizon transform and libm','DeltaT evaluation and time-coordinate arithmetic','solar interpolation, TT/TDB and relativistic-map arithmetic','source ephemeris and physical-model errors'],
            'terms':{key:record(value) for key,value in values.items()},
            'classificationGuard':{key:str(value) for key,value in guard.items()},
            'selectedEarth':{**{key:str(value) for key,value in earth.items() if key not in ['components', 'clock']},
                'components':{path:{key:str(value) for key,value in component.items()}
                              for path,component in zip(selected_earth_bounds.PATHS,earth['components'])},
                'clock':{key:str(value) for key,value in earth['clock'].items()}},
            'intermediate': {'deltaTMagnitudeSeconds':str(magnitude),
                             'observedDeltaT':{key:str(value) for key,value in observed.items()},
                             'topocentricRadiusMarginAU':str(rho),
                             'maxEarthPerturbationAU':str(max_earth_perturbation),
                             'observedMaxEarthPerturbationAU':str(observed_max_earth_perturbation),
                             'ratesDegreesPerDay':{key:str(value) for key,value in rates.items()},
                             'apparentComposition':{key:str(value) for key,value in {'betaUpper':beta_upper,'betaRate':beta_rate,
                                'directionLipschitz':p_lipschitz,'betaLipschitz':beta_lipschitz,
                                'distanceLipschitz':distance_lipschitz,'unnormalizedMinimum':unnormalized_min,
                                'earthAccelerationAUPerTTDay2':earth_acceleration,'velocityJoinAUPerTTDay':velocity_join,
                                'siteSpeedAUPerTTDay':site_speed,'siteAccelerationAUPerTTDay2':site_acceleration}.items()},
                             'orientationBounds':{key:str(value) for key,value in orientation.items()}}}


def render(result):
    fixed = {'polynomialStart':float(selected_earth_bounds.START),'polynomialStop':float(selected_earth_bounds.STOP),'polynomialSegmentDays':8.0,
             'observerHeightMeters':10000.0,'inverseToleranceFloorDays':1e-12,
             'inverseTolerancePerDay':4.440892098500626e-16,'classificationUTLimit':37000.0}
    lines = ['// Generated by Scripts/solar-numerics/derive_altitude.py; do not edit.',
             '// Partial arithmetic bounds are rounded outward. Classification guards are not altitude terms.',
             'enum SolarAltitudeBounds {']
    for key,value in fixed.items():
        lines.append(f'    static let {key} = {value!r}')
    for key,value in result['terms'].items():
        lines.append(f"    static let {key} = {value['binary64']!r}")
    years = [1900,1920,1941,1961,1986,2005,2050]
    lines.append('    static let modelStepUTs: [Double] = ['+', '.join(repr(float(year_start(year))) for year in years)+']')
    lines += ['    struct Gap {', '        let lower: Double', '        let upper: Double',
              '        let lowerEnclosure: Double', '        let upperEnclosure: Double', '    }',
              '    static let positiveGaps: [Gap] = [']
    delta = DeltaT()
    for year in years:
        left = I(year_start(year))+delta.at_year(I(year),year-1)/86400
        right = I(year_start(year))+delta.at_year(I(year),year)/86400
        if right.lo > left.hi:
            if upward(left.lo) != upward(left.hi) or upward(right.lo) != upward(right.hi):
                raise ValueError('A model-gap endpoint needs a tighter exact enclosure')
            lines += ['        Gap(', f'            lower: {upward(left.hi)!r}, upper: {upward(right.hi)!r}, lowerEnclosure: {downward(left.lo)!r},', f'            upperEnclosure: {upward(right.hi)!r}),']
    lines += ['    ]','}','']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args()
    result = derive()
    artifact = ROOT/'Scripts/solar-numerics/derived-altitude.json'
    swift = ROOT/'Sources/AstronomyKit/SolarAltitudeBounds.swift'
    serialized = json.dumps(result,indent=2,sort_keys=True)+'\n'
    rendered = render(result)
    if args.check:
        if artifact.read_text() != serialized or swift.read_text() != rendered:
            raise SystemExit('Native altitude derivation or generated Swift constants are stale')
        print('Native partial altitude derivation and generated constants verified')
    else:
        artifact.write_text(serialized)
        swift.write_text(rendered)
        print(artifact)


if __name__ == '__main__':
    main()
