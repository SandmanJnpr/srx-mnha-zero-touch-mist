#!/usr/bin/env python3
"""Unit tests of fix round 6: the SRX settings check before and after B4, an unknown WAN range (R9), the release
rule of B4, the T10 'both' message, the hardware-validation list of the plan, the W4 message, and the SKILL.md /
intake.md / README.md statements those rules depend on. Python 3.9+, standard library only, no network."""
import copy
import hashlib
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(SKILL))
SCRIPTS = os.path.join(SKILL, 'scripts')
sys.path.insert(0, SCRIPTS)
import build_plan as B  # noqa: E402

FIXTURE = os.path.join(HERE, 'fixtures', 'answers-doc.json')


def load(p):
    with open(p) as f:
        return json.load(f)


def read(p):
    with open(p) as f:
        return f.read()


def fixture():
    return load(FIXTURE)


def qs(problems):
    return [(p['kind'], p['q']) for p in problems]


def iot(a):
    """The overlay network of the fixture (a hub-site relay server is reachable from it)."""
    return [t for t in a['tenants'] if t.get('overlay') is True][0]


def hw(a):
    return B.hardware_status(B.build(a)['derived'])


class SiteSettingsAfterB4(unittest.TestCase):
    PIN = {'juniper_srx': {'auto_upgrade': {'enabled': True, 'custom_versions': {'SRX400': '25.4X300-D30.3'}}}}

    def test_pin_before_b4_is_a_b4_problem_not_a_precondition(self):
        got = B.check_site_settings({}, self.PIN, None)
        self.assertEqual(qs(got), [('reask', 'B4')])
        self.assertIn('25.4X300-D30.3', got[0]['msg'])

    def test_pin_judged_with_the_release(self):
        self.assertEqual(B.check_site_settings({}, self.PIN, '25.4X300-D30.3-EVO'), [])
        self.assertEqual(qs(B.check_site_settings({}, self.PIN, '25.4X300-D30.5')), [('precondition', 'B1')])

    def test_unpinned_auto_upgrade_is_a_precondition_before_and_after_b4(self):
        on = {'juniper_srx': {'auto_upgrade': {'enabled': True}}}
        self.assertEqual(qs(B.check_site_settings(on, {}, None)), [('precondition', 'B1')])
        self.assertEqual(qs(B.check_site_settings(on, {}, '25.4X300-D30.3')), [('precondition', 'B1')])


class UnknownWanRange(unittest.TestCase):
    def test_unknown_needs_r9_on_that_isp_only(self):
        a = fixture()
        a['isps']['2']['wan_subnet'] = 'unknown'
        got = B.validate(a)
        self.assertEqual(qs(got), [('reask', 'R')])
        self.assertIn('site_readiness.isp2_wan_range_clear', got[0]['msg'])
        self.assertIn('192.168.2.0/24', got[0]['msg'])            # ge-0/0/3 is the LAN member on node 2
        a['site_readiness']['isp2_wan_range_clear'] = 'yes'
        self.assertEqual(B.validate(a), [])

    def test_no_sends_the_customer_back_to_w3(self):
        a = fixture()
        a['isps']['1']['wan_subnet'] = None
        a['site_readiness']['isp1_wan_range_clear'] = 'no'
        self.assertEqual(qs(B.validate(a)), [('reask', 'W3')])

    def test_factory_subnet_named_only_when_ge3_has_a_role(self):
        a = fixture()
        a['isps']['1']['wan_subnet'] = None
        for n in ('1', '2'):
            a['nodes'][n]['ports'].update(lan=['ge-0/0/6'], lan_lacp=True)
        got = B.validate(a)
        self.assertEqual(qs(got), [('reask', 'R')])
        self.assertNotIn('192.168.2.0/24', got[0]['msg'])

    def test_a_known_range_still_runs_the_checks(self):
        a = fixture()
        a['isps']['1']['wan_subnet'] = '192.168.2.0/24'
        a['site_readiness']['isp1_wan_range_clear'] = 'yes'      # a confirmation never hides a known range
        self.assertIn(('stop', 'W3'), qs(B.validate(a)))

    def test_plan_says_the_customer_checked_it(self):
        a = fixture()
        a['isps']['1']['wan_subnet'] = 'unknown'
        a['site_readiness']['isp1_wan_range_clear'] = 'yes'
        md = B.render_plan_md(B.build(a)['derived'], B.build(a))
        self.assertIn('unknown: you confirmed (R9)', md)


class ReleaseRule(unittest.TestCase):
    def test_proven_release_builds(self):
        for r in ('25.4X300-D30.3', '25.4X300-D30.3-EVO'):
            self.assertEqual(B.check_B4(r, 'yes'), [], r)

    def test_older_d30_releases_stop(self):
        for r in ('25.4X300-D30.2-EVO', '25.4X300-D30.1', '25.4X300-D30'):
            got = B.check_B4(r, 'yes')
            self.assertEqual(qs(got), [('stop', 'B4')], r)
            self.assertIn('older than 25.4X300-D30.3', got[0]['msg'])
            self.assertIn('Install 25.4X300-D30.3', got[0]['msg'])

    def test_later_release_builds_with_hardware_validation_pending(self):
        for r in ('25.4X300-D30.4', '25.4X300-D31.1-EVO', '25.4X300-D40.2'):
            self.assertEqual(B.check_B4(r, 'yes'), [], r)
            a = fixture()
            a['release'] = r
            self.assertEqual(B.validate(a), [])
            self.assertTrue(any(x.startswith('release ') for x in hw(a)), r)
        self.assertFalse(any(x.startswith('release ') for x in hw(fixture())))

    def test_release_before_d30_still_stops(self):
        self.assertEqual(qs(B.check_B4('25.4X300-D20.1', 'yes')), [('stop', 'B4')])


class IPv6BothMessage(unittest.TestCase):
    def test_message_is_a_design_limit_with_the_alternative(self):
        a = fixture()
        a['tenants'][1]['ipv6'] = 'both'
        got = [p for p in B.validate(a) if p['q'] == 'T10']
        self.assertEqual(qs(got), [('stop', 'T10')])
        self.assertIn('not supported by this design', got[0]['msg'])
        self.assertIn('Alternative: IPv6 from one ISP for this network', got[0]['msg'])
        self.assertIn(B.STOP_MSG['ipv6_both'], read(os.path.join(SKILL, 'references', 'intake.md')))


class HardwareStatus(unittest.TestCase):
    def test_reference_structure_lists_nothing(self):
        self.assertEqual(hw(fixture()), [])
        p = B.build(fixture())
        md = B.render_plan_md(p['derived'], p)
        self.assertIn('## Reference design', md)
        self.assertIn('Your answers use only the proven structure', md)
        self.assertIn('25.4X300-D30.3', md)

    def test_second_hardware_run_forms_list_nothing(self):
        # the second hardware run: four networks, HA link ge-0/0/5 and transit link ge-0/0/4 on both nodes
        a = fixture()
        a['tenants'] = [t for t in a['tenants'] if t['name'] not in ('MEDIA', 'SECURITY')]
        for n in ('1', '2'):
            a['nodes'][n]['ports'].update(icl='ge-0/0/5', icd='ge-0/0/4')
        self.assertEqual(B.validate(a), [])
        self.assertEqual(hw(a), [])

    def test_other_counts_and_ports_are_listed(self):
        a = fixture()
        a['tenants'] = [t for t in a['tenants'] if t['name'] != 'MEDIA']
        self.assertEqual(B.validate(a), [])
        self.assertTrue(any('5 networks' in x for x in hw(a)))
        a = fixture()
        a['nodes']['1']['ports'].update(icl='ge-0/0/5', icd='ge-0/0/4')
        self.assertEqual(B.validate(a), [])
        self.assertTrue(any('ports other than the defaults' in x for x in hw(a)))

    def test_each_needs_hw_answer_is_listed(self):
        cases = [
            (lambda a: a['pair'].update(preemption=True), 'preemption'),
            (lambda a: iot(a)['dhcp'].update(mode='relay', relay_servers=['10.200.0.53']), 'DHCP relay'),
            (lambda a: a['tenants'].pop(), '5 networks'),
            (lambda a: a.update(profiles_method='ui-import'), 'imported in the Mist UI'),
            (lambda a: a['site'].update(gatewaytemplate_id='11111111-2222-3333-4444-555555555555'), 'gateway template'),
            (lambda a: a['mist'].update(access='msp-admin'), 'MSP'),
            (lambda a: a['nodes']['1']['ports'].update(wan='ge-0/0/6'), 'ports other than the defaults'),
            (lambda a: a['isps']['1'].update(lease_seconds=720), 'holds its address for 12 minutes'),
            (lambda a: a['isps']['2'].update(lease_behavior='new-address'), 'new address at once'),
        ]
        for fn, want in cases:
            a = fixture()
            fn(a)
            self.assertEqual(B.validate(a), [], want)
            got = hw(a)
            self.assertTrue(any(want in x for x in got), (want, got))

    def test_icl_encryption_and_plan_section(self):
        a = fixture()
        a['pair'].update(icl_encryption=True, icl_psk_file='/tmp/none-psk')
        self.assertEqual(B.validate(a), [])
        p = B.build(a)
        md = B.render_plan_md(p['derived'], p)
        self.assertIn('Beyond the reference design', md)
        self.assertIn('HA link encryption', md)
        self.assertNotIn('hardware-proven', md)

    def test_relay_note_in_plan(self):
        a = fixture()
        iot(a)['dhcp'] = {'mode': 'relay', 'relay_servers': ['10.200.0.53']}
        self.assertEqual(B.validate(a), [])
        p = B.build(a)
        md = B.render_plan_md(p['derived'], p)
        self.assertIn('both relay each client request', md)


class LeaseMessage(unittest.TestCase):
    def test_w4_stop_is_derived_from_the_measured_timeline(self):
        a = fixture()
        a['isps']['1']['lease_seconds'] = 900
        got = [p for p in B.validate(a) if p['q'] == 'W4']
        self.assertEqual(qs(got), [('stop', 'W4')])
        self.assertNotIn('would stay off Mist past', got[0]['msg'])
        self.assertIn('5 min 38 s', got[0]['msg'])
        self.assertIn(got[0]['msg'].split(': ', 1)[1].split('ISP 1 holds')[0], read(os.path.join(SKILL, 'references',
                                                                                                   'intake.md')))


class TextStatements(unittest.TestCase):
    SK = read(os.path.join(SKILL, 'SKILL.md'))
    IN = read(os.path.join(SKILL, 'references', 'intake.md'))
    API = read(os.path.join(SKILL, 'references', 'mist-api.md'))
    RD = read(os.path.join(REPO, 'README.md')) if os.path.exists(os.path.join(REPO, 'README.md')) else ''

    def test_existing_answers_file_is_never_overwritten(self):
        self.assertIn('already holds an\n`answers.json`', self.SK)
        self.assertIn('never overwrite, recreate or\nreplace it', self.SK)
        self.assertIn('`_fixture` key included', self.SK)
        self.assertIn('is never overwritten', self.IN)

    def test_other_gateways_events_use_their_own_site(self):
        self.assertIn('/sites/{gw_site_id}/devices/events/search?mac=<gw mac>', self.SK)
        self.assertIn('/sites/{gw_site_id}/devices/events/search?mac=<gw mac>', self.API)
        self.assertNotIn("read each connected gateway's events since the first write (`GET /sites/{site_id}", self.SK)

    def test_settings_check_runs_again_after_b4(self):
        self.assertIn('| 4 | B3, B4; then read both settings again and run `B.check_site_settings(', self.SK)
        self.assertIn("B.check_site_settings(org_setting, site_setting, answers['release'])` empty", self.SK)

    def test_claims(self):
        for t in (self.SK, self.RD):
            if not t:
                continue
            self.assertIn('roven on hardware', t)
            self.assertIn('25.4X300-D30.3', t)
            for w in ('hardware-proven', 'validation pending', 'mock'):
                self.assertNotIn(w, t)
        self.assertIn('25.4X300-D30.3: build (proven)', self.IN)
        self.assertIn('A D30 release older than D30.3: stop', self.IN)
        self.assertNotIn('D30.2', self.IN)

    # sha256 prefixes of the words the public text never uses (agent product names, test-setting words, UK spelling),
    # kept as hashes so that this file does not spell them either
    BANNED = {'c857d09db23e6822', 'c70eca6b0f88f44d', '7d3194f79e645c42', '053ea4804ef1bb33', '5d72436256ada538', '10182ab855ff7727', '18889a721a537ee1', 'a51146d38077ff99', '089b71123d238bd4', '8178ac72b28d77fc'}

    def test_public_text_rules(self):
        for t in (self.SK, self.IN, self.API, self.RD):
            self.assertIsNone(re.search(r'not\s+tested', t))
            words = {w.lower() for w in re.findall(r'[A-Za-z]+', t)}
            self.assertEqual([w for w in words if hashlib.sha256(w.encode()).hexdigest()[:16] in self.BANNED], [])


if __name__ == '__main__':
    unittest.main()
