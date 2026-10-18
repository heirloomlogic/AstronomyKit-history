import unittest
from unittest.mock import patch
import solar_reference as solar


class SolarDefinitionTests(unittest.TestCase):
    def test_exact_public_scalar_and_civil_epoch(self):
        mp = solar.mp
        for model in ['iersObserved', 'espenakMeeus', 'jplHorizons']:
            ut, tt = solar.input_pair(0.1, 'ut', model, 0.1)
            self.assertEqual(ut, solar.ref.exact(0.1))
            self.assertEqual(tt, ut+solar.ref.delta_t(ut,model)/86400)
            civil_ut, civil_tt = solar.input_pair(0.0, 'date', model, 365.5)
            self.assertEqual(civil_tt, mp.mpf('365.5')+mp.mpf('64.184')/86400)
            self.assertLess(abs(civil_ut+solar.ref.delta_t(civil_ut,model)/86400-civil_tt), mp.mpf('1e-65'))

    def test_observed_reference_is_continuous_at_its_runtime_joins(self):
        mp = solar.mp
        observed_data = solar.ref.observed_delta_t_data()
        rows, first_predicted = observed_data[0], observed_data[4]
        # The first source-decimal Hermite endpoint and its packed binary64 row differ by 6.08e-14 seconds.
        for join, tolerance in [(rows[0], mp.mpf('1e-12')), (rows[first_predicted], mp.mpf('1e-20')), (rows[-1], mp.mpf('1e-20'))]:
            epsilon = mp.mpf('1e-30')
            before = solar.ref.delta_t(join-epsilon, 'iersObserved')
            at = solar.ref.delta_t(join, 'iersObserved')
            after = solar.ref.delta_t(join+epsilon, 'iersObserved')
            self.assertLess(abs(before-at), tolerance)
            self.assertLess(abs(after-at), tolerance)

    def test_positive_gap_has_no_mathematical_inverse(self):
        mp = solar.mp
        boundary = solar.ref.year_start(1941)
        left = boundary+solar.ref.delta_t(boundary-mp.mpf('1e-30'))/86400
        right = boundary+solar.ref.delta_t(boundary)/86400
        value = float((left+right)/2)
        self.assertGreater(solar.ref.exact(value), left)
        self.assertLess(solar.ref.exact(value), right)
        for model in ['espenakMeeus', 'jplHorizons']:
            self.assertIsNone(solar.input_pair(value, 'tt', model, float(boundary)))

    def test_erfa_published_long_term_precession_matrix(self):
        mp = solar.mp
        actual = solar.precession((mp.mpf('1666.666') - 2000) * mp.mpf('365.25'))
        expected = [
            ['0.9967044141159213819', '0.7437801893193210840e-1', '0.3237624409345603401e-1'],
            ['-0.7437802731819618167e-1', '0.9972293894454533070', '-0.1205768842723593346e-2'],
            ['-0.3237622482766575399e-1', '-0.1206286039697609008e-2', '0.9994750246704010914'],
        ]
        for i in range(3):
            for j in range(3):
                self.assertLess(abs(actual[i,j] - mp.mpf(expected[i][j])), mp.mpf('1e-14'))

    def test_sofa_complementary_terms(self):
        mp = solar.mp
        self.assertLess(abs(solar.complementary(mp.mpf('2191.5')) - mp.mpf('0.2046085004885125264e-8')), mp.mpf('1e-20'))

    def test_sofa_mean_sidereal_time(self):
        mp = solar.mp
        self.assertLess(abs(solar.mean_sidereal(mp.mpf('2191.5'), mp.mpf('2191.5')) * mp.pi / 180 - mp.mpf('1.754174971870091203')), mp.mpf('1e-12'))

    def test_full_apparent_altitude_agrees_at_extended_precision(self):
        mp = solar.mp
        altitudes = []
        for precision in [80, 110]:
            with mp.workdps(precision):
                u = solar.ref.exact(1826.505)
                tt = u + solar.ref.delta_t(u) / 86400
                result = solar.Solar().altitude(u, tt, 'espenakMeeus', [-33.87, 151.21, -10000.0])
                self.assertLess(len(result['trace']), 20)
                altitudes.append(result['altitude'])
        with mp.workdps(110):
            self.assertLess(abs(altitudes[0] - altitudes[1]), mp.mpf('1e-65'))

    def test_selected_earth_composes_all_three_bound_components(self):
        mp = solar.mp
        states = [
            (mp.matrix([11, 13, 17]), mp.matrix([19, 23, 29])),
            (mp.matrix([2, 3, 5]), mp.matrix([7, 11, 13])),
            (mp.matrix([1, 4, 9]), mp.matrix([16, 25, 36])),
        ]
        with patch.object(solar, 'direct_state', side_effect=states) as direct, patch(
            'apparent_reference.clock', side_effect=lambda value: value
        ):
            position, velocity = solar.SelectedEarth.source(mp.mpf(0))
        self.assertEqual(
            [call.args[0] for call in direct.call_args_list],
            [solar.EARTH_BARYCENTER_PATH, solar.EARTH_OFFSET_PATH, solar.PLANET_SUN_PATH])
        self.assertEqual(position, solar.frame_bias(states[0][0] - states[2][0] + states[1][0]) / solar.AU_KM)
        self.assertEqual(velocity, solar.frame_bias(states[0][1] - states[2][1] + states[1][1]) / solar.AU_KM)

    def test_selected_earth_changes_the_recorded_altitude_epoch(self):
        mp = solar.mp
        earth = solar.SelectedEarth()
        tt = mp.mpf('1826.5064275680454')
        retained, _ = earth.retained_state(tt)
        self.assertGreater(mp.norm(earth.position(tt) - retained), mp.mpf('1e-9'))

    def test_emission_clock_is_continuous_across_the_2005_delta_t_step(self):
        import apparent_reference as apparent
        mp = solar.mp
        values = []
        for precision in [80, 110]:
            with mp.workdps(precision):
                u = solar.ref.exact(1826.505)
                tt = u + solar.ref.delta_t(u) / 86400
                result = solar.Solar().geocentric(u, tt, 'espenakMeeus')
                emission = result['trace'][-1]['tt']
                boundary_tt = mp.mpf('1826.5') + solar.ref.delta_t(mp.mpf('1826.5')) / 86400
                self.assertLess(emission, boundary_tt)
                self.assertGreater(tt, boundary_tt)
                residual = apparent.clock(tt) - apparent.clock(emission) - result['lightTimeDays']
                self.assertLess(abs(residual), mp.mpf('1e-59'))
                # Changing the Delta T label cannot alter an already specified reception pair.
                other = solar.Solar().geocentric(u, tt, 'jplHorizons')
                self.assertEqual(result['vector'], other['vector'])
                values.append(result['vector'])
        with mp.workdps(110):
            self.assertLess(max(abs(a-b) for a,b in zip(*values)), mp.mpf('1e-70'))


if __name__ == '__main__':
    unittest.main()


class SelectedEarthDerivativeTests(unittest.TestCase):
    def test_first_native_capture_row_has_real_finite_altitude(self):
        mp = solar.mp
        tt = mp.mpf('-36524.5')
        ut = tt-solar.ref.delta_t(tt)/86400
        result = solar.Solar().altitude(ut, tt, 'espenakMeeus', [0.0, 0.0, 0.0])
        self.assertTrue(mp.isfinite(result['altitude']))
        self.assertLessEqual(abs(result['altitude']), 90)

    def test_selected_earth_velocity_at_real_seams_and_adjacent_inputs(self):
        import math
        mp = solar.mp
        earth = solar.ref.Earth()
        # Both coverage joins and representative interior record joins. The
        # numerical oracle takes the selected side, independently of k U_k.
        count = int(mp.ceil((earth.stop-earth.start)/earth.width))
        for index in [0, 1, count//2, count-1, count]:
            boundary = float(earth.stop if index == count else earth.start+index*earth.width)
            for value in [math.nextafter(boundary,-math.inf), boundary, math.nextafter(boundary,math.inf)]:
                with self.subTest(index=index,value=value):
                    tt = solar.ref.exact(value)
                    velocity = earth.velocity(tt)
                    expected = mp.diff(lambda delta:mp.matrix(earth.position(tt+delta)),mp.mpf(0),direction=1)
                    self.assertLess(mp.norm(mp.matrix(velocity)-expected),mp.mpf('1e-60'))
                    self.assertLess(mp.norm(velocity),mp.mpf('.02'))

    def test_every_earth_record_selects_its_right_hand_derivative(self):
        from unittest.mock import patch
        import math
        mp = solar.mp
        earth = solar.ref.Earth()
        count = int(mp.ceil((earth.stop-earth.start)/earth.width))
        # Give each actual table interval a distinct linear derivative. This
        # exhausts all dispatch seams without reusing the selector as oracle.
        earth.degree = 1
        earth.coefficients = [value for segment in range(count) for axis in range(3)
                              for value in [float(segment),float((segment+1)*4)]]
        with patch.object(earth,'series',side_effect=lambda tt:[tt,tt,tt]):
            for index in range(count+1):
                boundary = float(earth.stop if index == count else earth.start+index*earth.width)
                for value,segment in [(math.nextafter(boundary,-math.inf),index-1),
                                      (boundary,index),(math.nextafter(boundary,math.inf),index)]:
                    expected = segment+1 if 0<=segment<count else 1
                    actual = earth.velocity(solar.ref.exact(value))
                    self.assertEqual(list(actual),[mp.mpf(expected)]*3)
