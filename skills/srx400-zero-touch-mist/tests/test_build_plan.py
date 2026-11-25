#!/usr/bin/env python3
"""Unit tests of scripts/build_plan.py. Python 3.9+, standard library only.

Run from the skill folder:  python3 -m unittest -v
                       or:  python3 -m unittest tests.test_build_plan -v

The fixture tests/fixtures/answers-doc.json holds the reference design with documentation values. With its
mgmt-0 addresses and hub MAC replaced by the placeholders of the repository files, the generator must give
../../mist/srx400-node1-zero-touch.json, srx400-node2-zero-touch.json and org-objects.json exactly.
"""
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(SKILL))
sys.path.insert(0, os.path.join(SKILL, 'scripts'))
import build_plan as B  # noqa: E402

FIXTURE = os.path.join(HERE, 'fixtures', 'answers-doc.json')
CLI = os.path.join(SKILL, 'scripts', 'build_plan.py')


def load(p):
    with open(p) as f:
        return json.load(f)


def read(p):
    with open(p) as f:
        return f.read()


def fixture():
    return load(FIXTURE)


def with_placeholders(a):
    a = copy.deepcopy(a)
    a['nodes']['1']['mgmt_ip'] = '<NODE1-MGMT-IP>'
    a['nodes']['2']['mgmt_ip'] = '<NODE2-MGMT-IP>'
    a['hub']['paths'][0]['hub_mac'] = '<hub-MAC>'
    return a


def tenant(a, name):
    return [t for t in a['tenants'] if t['name'] == name][0]


def cli(plan, n):
    return plan['profiles'][n]['additional_config_cmds']


def problems(a):
    return B.validate(a)


class GoldenTests(unittest.TestCase):
    """The reference answers give the repository files, line for line (needs the clone: ../../mist)."""

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(os.path.join(REPO, 'mist', 'srx400-node1-zero-touch.json')):
            raise unittest.SkipTest('the repository files ../../mist are not next to this skill folder (a copied '
                                    'skill folder): run the tests in the clone')

    def test_fixture_is_valid(self):
        self.assertEqual(problems(fixture()), [])

    def test_profiles_equal_repository_files(self):
        plan = B.build(with_placeholders(fixture()))
        for n in ('1', '2'):
            ref = load(os.path.join(REPO, 'mist', 'srx400-node%s-zero-touch.json' % n))
            self.assertEqual(plan['profiles'][n], ref)
            self.assertEqual(json.dumps(plan['profiles'][n], indent=2), json.dumps(ref, indent=2))   # key order too

    def test_profiles_with_values_equal_files_with_placeholders_filled(self):
        a = fixture()
        plan = B.build(a)
        for n in ('1', '2'):
            text = read(os.path.join(REPO, 'mist', 'srx400-node%s-zero-touch.json' % n))
            text = text.replace('<NODE%s-MGMT-IP>' % n, a['nodes'][n]['mgmt_ip'])
            text = text.replace('<hub-MAC>', a['hub']['paths'][0]['hub_mac'])
            self.assertEqual(plan['profiles'][n], json.loads(text))

    def test_org_objects_equal_repository_file(self):
        plan = B.build(fixture())
        self.assertEqual(plan['org_objects'], load(os.path.join(SKILL, 'org-objects.json')))

    def test_line_counts_and_formula(self):
        plan = B.build(fixture())
        self.assertEqual([len(cli(plan, n)) for n in ('1', '2')], [127, 117])
        for n in ('1', '2'):
            self.assertEqual(B.line_count_formula(plan['derived'], n), len(cli(plan, n)))

    def test_template_lines_come_from_repository_files(self):
        ref = set()
        for n in ('1', '2'):
            ref |= set(load(os.path.join(REPO, 'mist', 'srx400-node%s-zero-touch.json' % n))['additional_config_cmds'])
        tpl = B.load_template()
        for e in tpl['cli']:
            if not re.search(r'n[12]:\d', e['source']):
                continue
            for line in e['lines']:
                rx = re.compile('^' + re.sub(r'\\\{[a-z0-9_]+\\\}', '.+?', re.escape(line)) + '$')
                self.assertTrue(any(rx.match(x) for x in ref), line)

    def test_every_line_is_set_or_delete_and_unique(self):
        plan = B.build(fixture())
        for n in ('1', '2'):
            lines = cli(plan, n)
            self.assertTrue(all(x.startswith('set ') or x.startswith('delete ') for x in lines))
            self.assertEqual(len(set(lines)), len(lines))

    def test_build_is_deterministic(self):
        a = fixture()
        self.assertEqual(B.build(a)['profiles'], B.build(a)['profiles'])

    def test_secret_placeholders_and_fill(self):
        plan = B.build(fixture())
        self.assertEqual(B.secret_placeholders(plan['profiles']['1']), ['<ROOT-PASSWORD-HASH>'])
        self.assertEqual(B.secret_placeholders(plan['profiles']['2']), ['<ROOT-PASSWORD-HASH>', '<LICENSE-KEY>'])
        h = '$6$abcdefgh$' + 'x' * 86
        p = B.fill_secrets(plan['profiles']['2'], root_hash=h, license_key='EXAMPLE-KEY')
        self.assertIn('set system root-authentication encrypted-password "%s"' % h, p['additional_config_cmds'])
        self.assertIn('set system license keys key "EXAMPLE-KEY"', p['additional_config_cmds'])
        self.assertEqual(B.PLACEHOLDER_RX.findall(json.dumps(p)), [])
        with self.assertRaises(ValueError):
            B.fill_secrets(plan['profiles']['2'], root_hash=h)          # no license value
        self.assertIn('<LICENSE-KEY>', json.dumps(plan['profiles']['2']))   # the plan itself is untouched

    def test_cli_writes_the_plan_folder(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'plan')
            r = subprocess.run([sys.executable, CLI, '--answers', FIXTURE, '--out', out], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(sorted(os.listdir(out)), ['node1-profile.json', 'node2-profile.json', 'org-objects.json',
                                                        'plan.md', 'topology.md', 'topology.txt'])
            self.assertEqual(load(os.path.join(out, 'node1-profile.json'))['name'], 'SZTP-SRX400-NODE1')
            md = read(os.path.join(out, 'topology.md'))
            self.assertIn('```mermaid', md)
            plan = read(os.path.join(out, 'plan.md'))
            for s in ('10.10.60.0/24', '10.10.60.1', 'VLAN', 'ISP 2', '2001:db8:2000:1::/64', 'AS 65001', 'HUB-SITE-NETS',
                      '10.255.0.0/16', 'Active Leasequery'):
                self.assertIn(s, plan)


class ValidationTests(unittest.TestCase):
    """Every invalid answer class is caught with a clear message; platform limits stop."""

    def expect(self, mutate, kind, q, text=None):
        a = fixture()
        mutate(a)
        res = problems(a)
        hit = [p for p in res if p['kind'] == kind and p['q'] == q and (text is None or text in p['msg'])]
        self.assertTrue(hit, 'expected [%s] %s %r, got %s' % (kind, q, text, res))
        return res

    # addressing
    def test_overlapping_tenant_subnets(self):
        def m(a):
            tenant(a, 'CORP').update(subnet='10.10.0.0/16', gateway='10.10.20.1')
        self.expect(m, 'reask', 'T3', 'overlaps')

    def test_duplicate_vlan(self):
        self.expect(lambda a: tenant(a, 'CORP').update(vlan_id=10), 'reask', 'T2', 'VLAN IDs must be unique')

    def test_vlan_out_of_range(self):
        self.expect(lambda a: tenant(a, 'CORP').update(vlan_id=4095), 'reask', 'T2')

    def test_invalid_tenant_names(self):
        for bad in ('1CORP', 'ICD', 'vpn_x', 'A' * 25, 'has space', 'x'):
            self.expect(lambda a, bad=bad: tenant(a, 'CORP').update(name=bad), 'reask', 'T1')

    def test_duplicate_tenant_name_ignoring_case(self):
        self.expect(lambda a: tenant(a, 'CORP').update(name='mgmt'), 'reask', 'T1', 'unique')

    def test_gateway_not_in_subnet(self):
        self.expect(lambda a: tenant(a, 'CORP').update(gateway='10.10.21.1'), 'reask', 'T4')

    def test_subnet_too_small_or_host_bits(self):
        self.expect(lambda a: tenant(a, 'CORP').update(subnet='10.10.20.0/30'), 'reask', 'T3')
        self.expect(lambda a: tenant(a, 'CORP').update(subnet='10.10.20.5/24'), 'reask', 'T3')

    def test_subnet_in_mist_overlay_space(self):
        def m(a):
            tenant(a, 'GUEST').update(subnet='100.64.30.0/24', gateway='100.64.30.1')
            tenant(a, 'GUEST')['dhcp'].update(start='100.64.30.10', end='100.64.30.200')
        self.expect(m, 'reask', 'T3', '100.64.0.0/10')

    def test_dhcp_range_outside_subnet(self):
        self.expect(lambda a: tenant(a, 'CORP')['dhcp'].update(end='10.10.21.20'), 'reask', 'T7')

    def test_dhcp_range_covers_vip_or_node(self):
        self.expect(lambda a: tenant(a, 'CORP')['dhcp'].update(start='10.10.20.1'), 'reask', 'T7', 'must not include')
        self.expect(lambda a: tenant(a, 'CORP')['dhcp'].update(start='10.10.20.3'), 'reask', 'T7', 'must not include')

    def test_dhcp_start_after_end(self):
        self.expect(lambda a: tenant(a, 'CORP')['dhcp'].update(start='10.10.20.200', end='10.10.20.10'), 'reask', 'T7')

    def test_internal_block_overlaps_tenant(self):
        self.expect(lambda a: a['internal'].update(block='10.10.0.0/16'), 'reask', 'T3', 'internal block')

    def test_internal_block_too_small_or_public(self):
        self.expect(lambda a: a['internal'].update(block='10.255.0.0/23'), 'reask', 'I1')
        self.expect(lambda a: a['internal'].update(block='198.18.0.0/16'), 'reask', 'I1')

    def test_wan_range_overlaps_tenant(self):
        self.expect(lambda a: a['isps']['1'].update(wan_subnet='10.10.20.0/24'), 'reask', 'T3', 'ISP 1 WAN subnet')

    def test_oob_overlaps_tenant(self):
        def m(a):
            a['mgmt']['oob_network'] = '10.10.10.0/24'
            a['nodes']['1']['mgmt_ip'], a['nodes']['2']['mgmt_ip'] = '10.10.10.140', '10.10.10.141'
        self.expect(m, 'reask', 'T3', 'out-of-band network')

    def test_overlap_reported_before_the_later_groups(self):
        """During group 9 (K and R not answered yet) an overlap is still reported, under T3."""
        a = fixture()
        tenant(a, 'CORP').update(subnet='10.10.0.0/16', gateway='10.10.20.1')
        for n in ('1', '2'):
            a['nodes'][n].update(root_hash_file=None, license_key_file=None)
        a['site_readiness'] = {}
        res = problems(a)
        self.assertTrue(any(p['q'] == 'T3' and 'overlaps' in p['msg'] for p in res), res)
        self.assertTrue(any(p['q'] == 'K1' for p in res))
        self.assertEqual(B.check_overlaps(a)[0]['q'], 'T3')

    def test_overlap_labels_follow_the_later_question(self):
        a = fixture()
        a['hub']['site_prefixes'] = ['10.255.0.0/16']
        self.assertEqual([p['q'] for p in B.check_overlaps(a)], ['H5'])
        a = fixture()
        a['mgmt']['oob_network'] = '10.255.1.0/24'
        a['nodes']['1']['mgmt_ip'], a['nodes']['2']['mgmt_ip'] = '10.255.1.140', '10.255.1.141'
        self.assertEqual([p['q'] for p in B.check_overlaps(a)], ['I1'])
        a = fixture()
        a['isps']['1']['wan_subnet'] = '192.168.100.0/28'
        self.assertEqual([p['q'] for p in B.check_overlaps(a)], ['M1'])

    def test_wan_subnet_unknown_is_null(self):
        a = fixture()
        for n in ('1', '2'):
            a['isps'][n]['wan_subnet'] = 'unknown'
        # r6: an unknown range is checked by the customer (intake R9) before the build
        self.assertEqual(sorted(p['msg'].split(':')[1].strip() for p in problems(a)),
                         ['site_readiness.isp1_wan_range_clear', 'site_readiness.isp2_wan_range_clear'])
        for n in ('1', '2'):
            a['site_readiness']['isp%s_wan_range_clear' % n] = 'yes'
        self.assertEqual(problems(a), [])
        a['isps']['1']['wan_subnet'] = 'Unknown'
        self.assertEqual(problems(a), [])

    def test_held_lease_ceiling_13_minutes(self):
        a = fixture()
        a['isps']['1']['lease_seconds'] = 780
        self.assertEqual(problems(a), [])
        res = self.expect(lambda a: a['isps']['1'].update(lease_seconds=900), 'stop', 'W4', 'for 15 minutes')
        self.assertIn('a lease of 13 minutes or less', [p for p in res if p['q'] == 'W4'][0]['msg'])

    def test_lease_key_spelling_lease_behaviour_is_read(self):
        a = fixture()
        for n in ('1', '2'):
            a['isps'][n]['lease_behaviour'] = a['isps'][n].pop('lease_behavior')
        self.assertEqual(problems(a), [])
        self.assertEqual(B.build(a)['profiles'], B.build(fixture())['profiles'])

    def test_release_and_factory_state_are_asked(self):
        self.expect(lambda a: a.pop('release'), 'reask', 'B4', 'show version')
        self.expect(lambda a: a['site_readiness'].pop('factory_default'), 'reask', 'B4', 'factory-default')

    def test_reserved_dhcp_option_52(self):
        self.expect(lambda a: tenant(a, 'CORP')['dhcp'].update(options={'52': {'type': 'int16', 'value': '1'}}),
                    'reask', 'T16', 'not 3, 6, 12, 15, 50-55')

    def test_five_hub_paths_and_eight_lan_ports(self):
        def five(a):
            p = a['hub']['paths'][0]
            a['hub']['paths'] = [dict(p, path='HUB-wan%d' % k, hub_wan_port_name='wan%d' % k) for k in range(1, 6)]
        self.expect(five, 'reask', 'H3', 'one to 4 hub paths')
        self.expect(lambda a: a['nodes']['1']['ports'].update(
            lan=['ge-0/0/0', 'ge-0/0/1', 'ge-0/0/3', 'ge-0/0/6', 'ge-0/0/7', 'ge-0/0/8', 'ge-0/0/9', 'ge-0/0/4']),
            'reask', 'P3', 'one to seven LAN ports')

    def test_no_internet_network_needs_no_preferred_isp(self):
        def m(a):
            tenant(a, 'MEDIA').update(internet=False, ipv6='none')
            tenant(a, 'MEDIA')['dhcp']['dns_servers'] = ['10.10.40.53']
            tenant(a, 'MEDIA').pop('preferred_isp')
        a = fixture()
        m(a)
        self.assertEqual(problems(a), [])
        B.build(a)
        self.expect(lambda a: tenant(a, 'CORP').update(preferred_isp=3), 'reask', 'T5')

    # IPv6
    def test_ipv6_prefix_too_small_for_the_tenants(self):
        def m(a):
            a['isps']['1'].update(delegated_prefix='2001:db8:2000::/64', pd_length=64)
        self.expect(m, 'reask', 'T18', 'does not fit')

    def test_ipv6_index_beyond_a_60(self):
        self.expect(lambda a: tenant(a, 'CORP').update(ipv6_index=16), 'reask', 'T18', '0 to 15')

    def test_ipv6_same_64_twice(self):
        self.expect(lambda a: tenant(a, 'CORP').update(ipv6_index=1), 'reask', 'T18', 'same /64 number')

    def test_documentation_prefix_refused_for_customers(self):
        self.expect(lambda a: a.pop('_fixture'), 'reask', 'V2', 'documentation prefix')

    def test_ipv6_from_isp_without_delegation(self):
        self.expect(lambda a: tenant(a, 'GUEST').update(ipv6='isp2'), 'reask', 'T10')

    def test_ipv6_prefix_may_change_stops(self):
        self.expect(lambda a: a['isps']['1'].update(prefix_stable='no'), 'stop', 'V3')

    # ports
    def test_ports_reused_across_roles(self):
        self.expect(lambda a: a['nodes']['1']['ports'].update(wan='ge-0/0/4'), 'reask', 'P1', 'must all differ')

    def test_mgmt0_and_unknown_ports(self):
        self.expect(lambda a: a['nodes']['1']['ports'].update(wan='mgmt-0'), 'reask', 'P1', 'mgmt-0')
        self.expect(lambda a: a['nodes']['2']['ports'].update(icd='ge-0/0/12'), 'reask', 'P1', 'not an SRX400 port')

    def test_wan_on_factory_dhcp_server_port_stops(self):
        self.expect(lambda a: a['nodes']['1']['ports'].update(wan='ge-0/0/3', lan=['ge-0/0/6']), 'stop', 'P2')

    def test_plain_lan_on_ge3_stops(self):
        self.expect(lambda a: a['nodes']['1']['ports'].update(lan_lacp=False), 'stop', 'P3')

    def test_icl_ge3_on_one_end_stops(self):
        self.expect(lambda a: a['nodes']['1']['ports'].update(icl='ge-0/0/3', lan=['ge-0/0/6']), 'stop', 'P4')

    def test_lan_member_count(self):
        self.expect(lambda a: a['nodes']['1']['ports'].update(lan=[]), 'reask', 'P3')
        self.expect(lambda a: a['nodes']['1']['ports'].update(lan=['ge-0/0/6', 'ge-0/0/7'], lan_lacp=False), 'reask', 'P3')

    def test_lag_across_both_nodes_stops(self):
        self.expect(lambda a: a['nodes']['1']['ports'].update(lan_lag_across_nodes=True), 'stop', 'P3', 'its own LAG')

    def test_two_wans_on_one_node_stop(self):
        self.expect(lambda a: a['nodes']['1']['ports'].update(wan=['ge-0/0/2', 'ge-0/0/6']), 'stop', 'W1')
        self.expect(lambda a: a['isps']['2'].update(wan_count=2), 'stop', 'W1')

    # tenants, counts
    def test_more_tenants_than_allowed_stops(self):
        def m(a):
            base = a['tenants'][1]
            a['tenants'] = [a['tenants'][0]]
            for k in range(1, 33):
                t = copy.deepcopy(base)
                t.update(name='T%02d' % k, vlan_id=100 + k, subnet='10.20.%d.0/24' % k, gateway='10.20.%d.1' % k,
                         ipv6='none', ssh=False)
                t['dhcp'].update(start='10.20.%d.10' % k, end='10.20.%d.200' % k)
                a['tenants'].append(t)
        self.expect(m, 'stop', 'T0', '33 networks: SRG1 carries one virtual IP per network')

    def test_no_tenant(self):
        self.expect(lambda a: a.update(tenants=[]), 'reask', 'T0')

    def test_two_untagged(self):
        self.expect(lambda a: tenant(a, 'CORP').update(untagged=True), 'reask', 'T12')

    def test_preferred_isp_either(self):
        self.expect(lambda a: tenant(a, 'CORP').update(preferred_isp='either'), 'reask', 'T5')

    def test_ipv6_only_tenant_stops(self):
        self.expect(lambda a: tenant(a, 'CORP').update(subnet=None), 'stop', 'T3', 'IPv4 subnet')

    def test_internet_via_hub_stops(self):
        self.expect(lambda a: tenant(a, 'IOT').update(internet='via-hub'), 'stop', 'T14')

    def test_private_client_dns_unreachable(self):
        self.expect(lambda a: tenant(a, 'CORP')['dhcp'].update(dns_servers=['10.200.0.53']), 'reask', 'T8')

    def test_reach_unknown_tenant(self):
        self.expect(lambda a: tenant(a, 'CORP').update(reach=['PRINTERS']), 'reask', 'T15')

    def test_overlay_without_hub(self):
        self.expect(lambda a: a['hub'].update(present=False), 'reask', 'T11')

    # ISP, services, hub
    def test_static_pppoe_tagged_wan_stop(self):
        for h in ('static', 'pppoe', 'dhcp-tagged', 'none'):
            self.expect(lambda a, h=h: a['isps']['2'].update(handoff=h), 'stop', 'W1')

    def test_long_held_lease_stops(self):
        self.expect(lambda a: a['isps']['1'].update(lease_seconds=3600), 'stop', 'W4')

    def test_private_firewall_dns(self):
        self.expect(lambda a: a['services'].update(dns_servers=['10.200.0.53']), 'reask', 'S1')

    def test_hub_outside_mist_stops(self):
        self.expect(lambda a: a['hub'].update(in_mist=False), 'stop', 'H1')

    def test_hub_path_name_rule(self):
        self.expect(lambda a: a['hub']['paths'][0].update(path='HUB-wan2'), 'reask', 'H3')

    def test_hub_import_drops_tenants(self):
        self.expect(lambda a: a['hub'].update(import_accepts_overlay_tenants='no'), 'precondition', 'H6')

    def test_asn_equal_or_overlay(self):
        self.expect(lambda a: a['internal'].update(icd_asn={'1': '65001', '2': '65001'}), 'reask', 'I2')
        self.expect(lambda a: a['internal'].update(icd_asn={'1': '65000', '2': '65002'}), 'reask', 'I2', 'overlay AS')

    # pair, platform, secrets, names
    def test_platform_stops(self):
        cases = [
            (lambda a: a['pair'].update(activeness_probe='explicit'), 'X'),
            (lambda a: a['pair'].update(ha_mode='chassis-cluster'), 'X'),
            (lambda a: a['pair'].update(srg_count=3), 'X'),
            (lambda a: a.update(security_services=['idp']), 'S3'),
            (lambda a: a.update(security_services=['secintel', 'url-filtering']), 'S3'),
            (lambda a: a['nodes']['2'].update(model='SRX345'), 'B2'),
            (lambda a: a['mist'].update(access='write'), 'A3'),
            (lambda a: a.update(release='25.4X300-D10.2'), 'B4'),
            (lambda a: a.update(release='24.4R2'), 'B4'),
        ]
        for m, q in cases:
            self.expect(m, 'stop', q)

    def test_root_authentication_required(self):
        self.expect(lambda a: a['nodes']['1'].update(root_hash_file=None), 'reask', 'K1')

    def test_icl_encryption_needs_key_file(self):
        self.expect(lambda a: a['pair'].update(icl_encryption=True), 'reask', 'K3')

    def test_profile_names(self):
        self.expect(lambda a: a['nodes']['2'].update(profile_name='sztp-srx400-node1'), 'reask', 'N1')
        self.expect(lambda a: a['nodes']['1'].update(profile_name='P' * 33), 'reask', 'N1')

    def test_readiness_no_is_a_precondition(self):
        self.expect(lambda a: a['site_readiness'].update(cabling='no'), 'precondition', 'R')

    def test_security_services_named_in_the_stop(self):
        res = self.expect(lambda a: a.update(security_services=['idp', 'secintel']), 'stop', 'S3')
        self.assertTrue([p for p in res if p['q'] == 'S3'][0]['msg'].startswith('S3: IDP, SecIntel requested'))

    def test_secret_value_checks(self):
        self.assertEqual(B.check_K1('$6$abcdefgh$' + 'A' * 86), [])
        self.assertEqual(B.check_K1('Secret123')[0]['q'], 'K1')
        self.assertEqual(B.check_K1('ssh-ed25519 ' + 'A' * 68 + ' admin', 'ssh-key'), [])
        self.assertEqual(B.check_K1('ecdsa-sha2-nistp256 ' + 'A' * 68, 'ssh-key'), [])
        self.assertEqual(B.check_K1('ssh-dss ' + 'A' * 68, 'ssh-key')[0]['q'], 'K1')
        self.assertEqual(B.check_K2('KEY1\nKEY2')[0]['q'], 'K2')
        self.assertEqual(B.check_K3('abc123')[0]['q'], 'K3')

    def test_ipv6_only_needs_the_t3_answer(self):
        """A network named at T0 whose subnet is not asked yet is a T3 re-ask, never the IPv6-only stop."""
        a = fixture()
        a['tenants'].append({'name': 'SCANNERS'})
        res = problems(a)
        self.assertFalse([p for p in res if p['kind'] == 'stop'], res)
        self.assertTrue([p for p in res if p['q'] == 'T3' and 'SCANNERS' in p['msg'] and 'not answered yet' in p['msg']])
        a['tenants'] = [{'name': 'SCANNERS'}, {'name': 'PHONES'}]       # right after T0: T2 and T3 not asked yet
        self.assertEqual({(p['kind'], p['q']) for p in problems(a) if p['q'].startswith('T')},
                         {('reask', 'T2'), ('reask', 'T3')})
        self.expect(lambda a: tenant(a, 'CORP').update(subnet='none'), 'stop', 'T3', 'IPv4 subnet')
        self.expect(lambda a: tenant(a, 'GUEST').update(subnet='none'), 'stop', 'T3', 'no IPv4 subnet')

    def test_no_internet_network_gets_no_s1_dns_default(self):
        a = fixture()
        t = tenant(a, 'MEDIA')
        t.update(internet=False, ipv6='none')
        t.pop('preferred_isp')
        t['dhcp'].pop('dns_servers')
        res = [p for p in problems(a) if p['q'] == 'T8']
        self.assertEqual(len(res), 1, res)
        self.assertIn('one to three DNS servers', res[0]['msg'])             # asked at T8, not refused as public
        self.assertEqual(B.normalize(fixture())['tenants'][1]['dhcp']['dns_servers'], ['8.8.8.8', '1.1.1.1'])

    def test_wrong_answer_shapes_are_reasks_not_tracebacks(self):
        cases = [
            (lambda a: tenant(a, 'CORP').update(node_ips=['10.10.20.250', '10.10.20.251']), 'T13'),
            (lambda a: tenant(a, 'CORP').update(node_ips='10.10.20.250'), 'T13'),
            (lambda a: tenant(a, 'CORP').update(node_ips={'node1': '10.10.20.250'}), 'T13'),
            (lambda a: tenant(a, 'CORP')['dhcp'].update(fixed_bindings={'00005e005302': '10.10.20.250'}), 'T16'),
            (lambda a: a['hub'].update(paths={'HUB-wan': {}}), 'H3'),
            (lambda a: a['hub'].update(paths='HUB-wan'), 'H3'),
            (lambda a: a['hub'].update(paths=['HUB-wan']), 'H3'),
            (lambda a: tenant(a, 'CORP').update(ipv6=['isp1']), 'T10'),
            (lambda a: tenant(a, 'CORP').update(ipv6_index=[1]), 'T18'),
            (lambda a: tenant(a, 'CORP').update(dhcp='server'), 'T6'),
            (lambda a: tenant(a, 'CORP').update(reach=7), 'T15'),
            (lambda a: tenant(a, 'CORP').update(name=None), 'T1'),
            (lambda a: a['nodes']['1']['ports'].update(lan=[{'port': 'ge-0/0/3'}]), 'P3'),
            (lambda a: a['services'].update(dns_servers=[['8.8.8.8']]), 'S1'),
            (lambda a: a['hub'].update(site_prefixes=7), 'H5'),
            (lambda a: a['nodes']['1'].update(profile_name=None), 'N1'),
            (lambda a: a.update(mist='manage.mist.com'), 'schema'),
            (lambda a: a.update(site_readiness='yes'), 'schema'),
            (lambda a: a.update(_fixture='yes'), 'V2'),
        ]
        for mut, q in cases:
            a = fixture()
            mut(a)
            res = problems(a)
            self.assertTrue([p for p in res if p['q'] == q and p['kind'] == 'reask'], (q, res))
        self.assertEqual(problems(['not', 'an', 'object'])[0]['q'], 'schema')

    def test_node_ip_takes_string_node_keys(self):
        t = tenant(fixture(), 'MGMT')
        self.assertEqual((B.node_ip(t, '1'), B.node_ip(t, '2')), (B.node_ip(t, 1), B.node_ip(t, 2)))
        self.assertEqual(str(B.node_ip(t, '2')), '10.10.10.3')

    def test_bounds(self):
        def prefixes(k):
            return lambda a: a['hub'].update(site_prefixes=['10.%d.0.0/16' % (200 + i) for i in range(k)])
        a = fixture()
        prefixes(20)(a)
        self.assertEqual(problems(a), [])
        self.expect(prefixes(21), 'reask', 'H5', 'one to twenty')
        a = fixture()
        a['services'].update(dns_servers=['8.8.8.8', '1.1.1.1', '9.9.9.9'], ntp_servers=['pool.ntp.org', '0.pool.ntp.org',
                                                                                         '1.pool.ntp.org'])
        self.assertEqual(problems(a), [])
        self.expect(lambda a: a['services'].update(dns_servers=['8.8.8.8', '1.1.1.1', '9.9.9.9', '8.8.4.4']),
                    'reask', 'S1')
        self.expect(lambda a: a['services'].update(ntp_servers=['a.pool.ntp.org', 'b.pool.ntp.org', 'c.pool.ntp.org',
                                                                'd.pool.ntp.org']), 'reask', 'S2')
        for lt, ok in ((600, True), (599, False), (2592000, True), (2592001, False)):
            a = fixture()
            tenant(a, 'CORP')['dhcp']['lease_time'] = lt
            self.assertEqual(not [p for p in problems(a) if p['q'] == 'T9'], ok, lt)
        a = fixture()                                                           # V2: /48 to /64
        a['isps']['1'].update(delegated_prefix='2001:db8:2000::/48', pd_length=48)
        self.assertEqual(problems(a), [])
        self.expect(lambda a: a['isps']['1'].update(delegated_prefix='2001:db8::/47', pd_length=47), 'reask', 'V2')
        self.assertEqual(B.check_K1('$5$abcdefgh$' + 'B' * 43), [])
        self.assertEqual(B.check_K1('$1$abcdefgh$' + 'C' * 22), [])

    def test_model_stop_wording(self):
        res = self.expect(lambda a: a['nodes']['2'].update(model='SRX345'), 'stop', 'B2', 'node 2 is an SRX345')
        self.assertEqual(B.check_B2('AA0000000001', 'AA0000000002', (None, 'QFX5120'))[0]['msg'],
                         'B2: node 2 is a QFX5120; ' + B.STOP_MSG['model'])

    def test_cli_unreadable_answers_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'a.json')
            with open(p, 'w') as f:
                f.write('{"schema": "srx400-zero-touch-mist.answers.v2", "nodes": {')
            r = subprocess.run([sys.executable, CLI, '--answers', p, '--check'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertTrue(r.stdout.startswith('[reask] schema: '), r.stdout)
            self.assertEqual(r.stderr, '')

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            for mut, code in ((lambda a: None, 0), (lambda a: tenant(a, 'CORP').update(vlan_id=10), 1),
                              (lambda a: a['isps']['1'].update(handoff='pppoe'), 2)):
                a = fixture()
                mut(a)
                p = os.path.join(d, 'a.json')
                with open(p, 'w') as f:
                    json.dump(a, f)
                r = subprocess.run([sys.executable, CLI, '--answers', p, '--check'], capture_output=True, text=True)
                self.assertEqual(r.returncode, code, r.stdout)


class StructureTests(unittest.TestCase):
    """Answers other than the reference ones change only the entries the design ties to them."""

    def build(self, mutate):
        a = fixture()
        mutate(a)
        self.assertEqual(problems(a), [])
        plan = B.build(a)
        for n in ('1', '2'):
            self.assertEqual(B.line_count_formula(plan['derived'], n), len(cli(plan, n)))
        return a, plan

    def test_no_hub(self):
        def m(a):
            a['hub']['present'] = False
            for t in a['tenants']:
                t['overlay'] = False
        a, plan = self.build(m)
        for n in ('1', '2'):
            text = '\n'.join(cli(plan, n))
            self.assertNotIn('routing-instances lan', text)
            self.assertNotIn('lan.inet.0', text)
            self.assertIn('set protocols bgp group ICD family inet unicast rib-group ICD-RIB', text)
            self.assertIn('set system services dhcp-local-server active-leasequery peer-address', text)
            self.assertNotIn('dead-peer-detection', text)
            self.assertEqual(plan['profiles'][n]['port_config']['ge-0/0/2']['vpn_paths'], {})
            self.assertNotIn('allow-to-hub', [s['name'] for s in plan['profiles'][n]['service_policies']])
        self.assertNotIn('HUB-SITE-NETS', [o['body']['name'] for o in plan['org_objects']])
        self.assertEqual([len(cli(plan, n)) for n in ('1', '2')], [115, 105])

    def test_hub_without_overlay_tenants(self):
        def m(a):
            tenant(a, 'IOT')['overlay'] = False
            a['hub']['site_prefixes'] = []
        a, plan = self.build(m)
        p = plan['profiles']['1']
        self.assertIn('HUB-wan.OrgOverlay', p['port_config']['ge-0/0/2']['vpn_paths'])
        self.assertNotIn('OrgOverlay', p['path_preferences'])
        self.assertFalse(any('MNHA-ACTIVE' in x or '-LP' in x for x in p['additional_config_cmds']))
        self.assertNotIn('HUB-SITE-NETS', [o['body']['name'] for o in plan['org_objects']])

    def test_custom_node_addresses(self):
        def m(a):
            tenant(a, 'CORP')['node_ips'] = {'1': '10.10.20.250', '2': '10.10.20.251'}
            tenant(a, 'MGMT')['node_ips'] = {'1': '10.10.10.250', '2': '10.10.10.251'}     # the T20 network
        a, plan = self.build(m)
        self.assertEqual(plan['profiles']['1']['ip_configs']['CORP']['ip'], '10.10.20.250')
        self.assertEqual(plan['profiles']['2']['ip_configs']['CORP']['ip'], '10.10.20.251')
        self.assertIn('active-leasequery peer-address 10.10.10.251', '\n'.join(cli(plan, '1')))
        self.assertIn('active-leasequery peer-address 10.10.10.250', '\n'.join(cli(plan, '2')))
        a = fixture()
        tenant(a, 'CORP')['node_ips'] = {'1': '10.10.20.1', '2': '10.10.20.251'}
        self.assertTrue([p for p in problems(a) if p['q'] == 'T13'])         # the gateway is not a node address

    def test_public_subnet_and_public_hub_prefix_add_excepts(self):
        def m(a):
            t = tenant(a, 'CORP')
            t.update(subnet='192.88.99.0/26', gateway='192.88.99.1', ipv6='none')     # IANA 6to4 relay space: no
            t['dhcp'].update(start='192.88.99.10', end='192.88.99.60')               # one's network, not RFC 1918
            a['hub']['site_prefixes'] = ['10.200.0.0/16', '192.88.99.64/26']
            tenant(a, 'GUEST')['preferred_isp'] = 2
        a, plan = self.build(m)
        text = '\n'.join(cli(plan, '1'))
        for x in ('192.88.99.0/26', '192.88.99.64/26'):
            self.assertIn('set firewall family inet filter TO-PEER-ISP term to-peer from destination-address %s except'
                          % x, text)

    def test_icd_as_equal_to_the_overlay_as_without_hub(self):
        def m(a):
            a['hub']['present'] = False
            for t in a['tenants']:
                t['overlay'] = False
            a['internal']['icd_asn'] = {'1': '65000', '2': '65002'}
        a, plan = self.build(m)
        self.assertEqual(plan['profiles']['1']['bgp_config']['ICD']['local_as'], '65000')

    def test_untagged_network_that_is_not_listed_first(self):
        def m(a):
            tenant(a, 'MGMT')['untagged'] = False
            tenant(a, 'GUEST')['untagged'] = True
        a, plan = self.build(m)
        self.assertEqual(plan['derived']['T'][0]['name'], 'GUEST')
        self.assertIn('set chassis high-availability services-redundancy-group 1 virtual-ip 1 ip 10.10.30.1/24',
                      cli(plan, '1'))
        self.assertIn('set chassis high-availability services-redundancy-group 1 virtual-ip 1 interface ae0.0',
                      cli(plan, '1'))
        self.assertEqual(plan['profiles']['1']['port_config']['ge-0/0/3']['port_network'], 'GUEST')

    def test_sfp_wan_and_ge3_on_both_ends(self):
        def m(a):
            for n, w in (('1', 'ge-0/0/0'), ('2', 'ge-0/0/1')):
                a['nodes'][n]['ports'].update(wan=w, lan=['ge-0/0/6'], icd='ge-0/0/3')
        a, plan = self.build(m)
        for n, w in (('1', 'ge-0/0/0'), ('2', 'ge-0/0/1')):
            p = plan['profiles'][n]
            self.assertEqual(list(p['port_config']), [w, 'ge-0/0/6', 'ge-0/0/3'])
            self.assertIn('set interfaces %s unit 0 family inet dhcp force-discover' % w, p['additional_config_cmds'])

        def icl(a):
            for n in ('1', '2'):
                a['nodes'][n]['ports'].update(lan=['ge-0/0/6'], icl='ge-0/0/3')
        a, plan = self.build(icl)
        self.assertIn('set chassis high-availability peer-id 2 interface ge-0/0/3.0', cli(plan, '1'))

    def test_factory_subnet_on_the_wan_without_a_ge3_role(self):
        def m(a):
            for n in ('1', '2'):
                a['nodes'][n]['ports'].update(lan=['ge-0/0/6'])
            a['isps']['1']['wan_subnet'] = '192.168.2.0/24'
        self.build(m)
        a = fixture()
        a['isps']['1']['wan_subnet'] = '192.168.2.0/24'                     # ge-0/0/3 is the LAN: stop
        self.assertTrue([p for p in problems(a) if p['kind'] == 'stop' and p['q'] == 'W3'])

    def test_no_untagged_tenant(self):
        a, plan = self.build(lambda a: tenant(a, 'MGMT').update(untagged=False))
        lan = plan['profiles']['1']['port_config']['ge-0/0/3']
        self.assertNotIn('port_network', lan)
        self.assertIn('set chassis high-availability services-redundancy-group 1 virtual-ip 1 interface ae0.10',
                      cli(plan, '1'))

    def test_every_tenant_prefers_isp1(self):
        a, plan = self.build(lambda a: tenant(a, 'GUEST').update(preferred_isp=1))
        self.assertFalse(any('TO-PEER-ISP' in x for x in cli(plan, '1')))
        self.assertTrue(any('TO-PEER-ISP' in x for x in cli(plan, '2')))
        self.assertIn('set routing-instances XNODE instance-type forwarding', cli(plan, '1'))

    def test_plain_lan_port(self):
        def m(a):
            for n in ('1', '2'):
                a['nodes'][n]['ports'].update(lan=['ge-0/0/6'], lan_lacp=False)
        a, plan = self.build(m)
        p = plan['profiles']['1']
        self.assertFalse(p['port_config']['ge-0/0/6']['aggregated'])
        self.assertNotIn('ae_disable_lacp', p['port_config']['ge-0/0/6'])
        self.assertFalse(any('ae0' in x for x in p['additional_config_cmds']))
        self.assertIn('set chassis high-availability services-redundancy-group 1 monitor interface ge-0/0/6',
                      p['additional_config_cmds'])
        with tempfile.TemporaryDirectory() as d:
            B.write_plan(a, d)
            for f in ('topology.txt', 'plan.md'):
                text = read(os.path.join(d, f))
                self.assertIn('ge-0/0/6 (plain port, no LACP)', text)
                self.assertNotIn('ge-0/0/6 = ge-0/0/6', text)

    def test_four_hub_paths(self):
        def m(a):
            p = a['hub']['paths'][0]
            a['hub']['paths'] = [p] + [dict(p, path='HUB-wan%d' % k, hub_wan_port_name='wan%d' % k) for k in (2, 3, 4)]
        a, plan = self.build(m)
        p = plan['profiles']['1']
        self.assertEqual(len(p['port_config']['ge-0/0/2']['vpn_paths']), 4)
        self.assertEqual(len([x for x in p['additional_config_cmds'] if 'dead-peer-detection' in x]), 8)
        self.assertEqual([x['name'] for x in p['path_preferences']['OrgOverlay']['paths']],
                         ['HUB-wan.OrgOverlay', 'HUB-wan2.OrgOverlay', 'HUB-wan3.OrgOverlay', 'HUB-wan4.OrgOverlay'])

    def test_seven_member_lag(self):
        lan = ['ge-0/0/0', 'ge-0/0/1', 'ge-0/0/3', 'ge-0/0/6', 'ge-0/0/7', 'ge-0/0/8', 'ge-0/0/9']
        a, plan = self.build(lambda a: a['nodes']['1']['ports'].update(lan=lan))
        p = plan['profiles']['1']
        self.assertIn(','.join(lan), p['port_config'])
        self.assertTrue(p['port_config'][','.join(lan)]['aggregated'])

    def test_four_relay_servers(self):
        srv = ['10.200.1.10', '10.200.1.11', '10.200.1.12', '10.200.1.13']
        a, plan = self.build(lambda a: tenant(a, 'IOT')['dhcp'].update(mode='relay', relay_servers=srv))
        self.assertEqual(plan['profiles']['1']['dhcpd_config']['IOT'], {'type': 'relay', 'servers': srv})

    def test_two_member_lag(self):
        a, plan = self.build(lambda a: a['nodes']['1']['ports'].update(lan=['ge-0/0/3', 'ge-0/0/6']))
        self.assertIn('ge-0/0/3,ge-0/0/6', plan['profiles']['1']['port_config'])
        self.assertIn('ge-0/0/3', plan['profiles']['2']['port_config'])

    def test_other_ports_per_node(self):
        def m(a):
            a['nodes']['2']['ports'] = {'wan': 'ge-0/0/9', 'lan': ['ge-0/0/8'], 'lan_lacp': True, 'icl': 'ge-0/0/6',
                                        'icd': 'ge-0/0/7'}
        a, plan = self.build(m)
        p2 = plan['profiles']['2']
        self.assertEqual(list(p2['port_config']), ['ge-0/0/9', 'ge-0/0/8', 'ge-0/0/7'])
        self.assertIn('set chassis high-availability peer-id 1 interface ge-0/0/6.0', p2['additional_config_cmds'])
        self.assertIn('set interfaces ge-0/0/9 unit 0 family inet dhcp force-discover', p2['additional_config_cmds'])
        self.assertIn('set chassis high-availability peer-id 2 interface ge-0/0/4.0', cli(plan, '1'))

    def test_ipv6_from_isp2(self):
        def m(a):
            a['isps']['2'].update(ipv6_pd=True, delegated_prefix='2001:db8:3000::/60', pd_length=60, prefix_stable='yes')
            a['site_readiness']['isp2_dhcpv6'] = 'yes'
            tenant(a, 'GUEST')['ipv6'] = 'isp2'
        a, plan = self.build(m)
        p2 = plan['profiles']['2']
        self.assertEqual(p2['port_config']['ge-0/0/2']['ip_config'], {'type': 'dhcp', 'type6': 'dhcp'})
        self.assertIn('set interfaces ae0 unit 30 family inet6 address 2001:db8:3000:3::3/64', p2['additional_config_cmds'])
        self.assertIn('set routing-options rib inet6.0 static route 2001:db8:3000::/60 discard', p2['additional_config_cmds'])

    def test_ipv6_prefix_unknown(self):
        a, plan = self.build(lambda a: a['isps']['1'].update(delegated_prefix='unknown', pd_length=56))
        lines = cli(plan, '1')
        self.assertIn('set interfaces ge-0/0/2 unit 0 family inet6 dhcpv6-client prefix-delegating preferred-prefix-length 56', lines)
        self.assertFalse(any('family inet6 address' in x or 'router-advertisement' in x or 'discard' in x for x in lines))

    def test_two_hub_paths(self):
        def m(a):
            a['hub']['paths'].append(dict(a['hub']['paths'][0], path='HUB-wan2', hub_wan_port_name='wan2'))
        a, plan = self.build(m)
        p = plan['profiles']['1']
        self.assertEqual(sorted(p['port_config']['ge-0/0/2']['vpn_paths']), ['HUB-wan.OrgOverlay', 'HUB-wan2.OrgOverlay'])
        self.assertEqual(len([x for x in p['additional_config_cmds'] if 'dead-peer-detection' in x]), 4)
        self.assertEqual([x['name'] for x in p['path_preferences']['OrgOverlay']['paths']],
                         ['HUB-wan.OrgOverlay', 'HUB-wan2.OrgOverlay'])

    def test_other_vpn_and_hub_port_names(self):
        def m(a):
            a['hub']['vpn_name'] = 'Corp-Overlay'
            a['hub']['paths'][0].update(path='HUB-inet', hub_wan_port_name='inet')
        a, plan = self.build(m)
        lines = cli(plan, '1')
        self.assertIn('set security ike gateway wan_to_00005e005301_inet dead-peer-detection always-send', lines)
        self.assertIn('set routing-instances vpn_Corp-Overlay protocols bgp group Corp-Overlay_overlay export Corp-Overlay_advertise', lines)
        self.assertEqual(plan['org_objects'][5]['body']['vpn_access'], {'Corp-Overlay': {'routed': True, 'no_readvertise_to_overlay': True}})

    def test_preemption_and_icl_encryption(self):
        a, plan = self.build(lambda a: a['pair'].update(preemption=True, icl_encryption=True, icl_psk_file='~/psk'))
        lines = cli(plan, '1')
        i = lines.index('set chassis high-availability services-redundancy-group 1 activeness-priority 200')
        self.assertEqual(lines[i + 1], 'set chassis high-availability services-redundancy-group 1 preemption')
        self.assertEqual(len([x for x in lines if 'MNHA-ICL' in x]), 14)
        self.assertIn('<ICL-PSK>', B.secret_placeholders(plan['profiles']['1']))

    def test_root_ssh_key(self):
        a, plan = self.build(lambda a: a['nodes']['1'].update(root_hash_file=None, root_ssh_key_file='~/root.pub'))
        self.assertIn('set system root-authentication <ROOT-SSH-KEY-TYPE> "<ROOT-SSH-KEY>"', cli(plan, '1'))
        p = B.fill_secrets(plan['profiles']['1'], root_ssh_key='ssh-ed25519 ' + 'A' * 68 + ' admin')
        # the comment after the key data is not sent (r5): Junos does not need it
        self.assertIn('set system root-authentication ssh-ed25519 "ssh-ed25519 %s"' % ('A' * 68), p['additional_config_cmds'])
        p = B.fill_secrets(plan['profiles']['1'], root_ssh_key='ssh-rsa ' + 'B' * 68)
        self.assertIn('set system root-authentication ssh-rsa "ssh-rsa %s"' % ('B' * 68), p['additional_config_cmds'])
        for t in ('256', '384', '521'):
            p = B.fill_secrets(plan['profiles']['1'], root_ssh_key='ecdsa-sha2-nistp%s %s admin' % (t, 'C' * 68))
            self.assertIn('set system root-authentication ssh-ecdsa "ecdsa-sha2-nistp%s %s"' % (t, 'C' * 68),
                          p['additional_config_cmds'])
        with self.assertRaises(ValueError):
            B.fill_secrets(plan['profiles']['1'], root_ssh_key='ssh-dss ' + 'D' * 68)

    def test_license_on_both_nodes(self):
        a, plan = self.build(lambda a: a['nodes']['1'].update(license_key_file='~/k1'))
        lines = cli(plan, '1')
        i = lines.index('set system root-authentication encrypted-password "<ROOT-PASSWORD-HASH>"')
        self.assertEqual(lines[i + 1], 'set system license keys key "<LICENSE-KEY>"')

    def test_inter_tenant_reach(self):
        a, plan = self.build(lambda a: tenant(a, 'CORP').update(reach=['SECURITY']))
        p = plan['profiles']['1']
        self.assertEqual(p['path_preferences']['LAN-SECURITY'], {'strategy': 'ordered', 'paths': [{'type': 'local', 'networks': ['SECURITY']}]})
        pol = [s for s in p['service_policies'] if s['name'] == 'To-SECURITY'][0]
        self.assertEqual((pol['tenants'], pol['path_preference']), (['CORP'], 'LAN-SECURITY'))

    def test_dhcp_relay_and_none(self):
        def m(a):
            tenant(a, 'IOT')['dhcp'].update(mode='relay', relay_servers=['10.200.1.10'])
            tenant(a, 'SECURITY')['dhcp']['mode'] = 'none'
        a, plan = self.build(m)
        d = plan['profiles']['1']['dhcpd_config']
        self.assertEqual(d['IOT'], {'type': 'relay', 'servers': ['10.200.1.10']})
        self.assertNotIn('SECURITY', d)

    def test_dhcp_off_everywhere(self):
        a, plan = self.build(lambda a: [t['dhcp'].update(mode='none') for t in a['tenants']])
        self.assertEqual(plan['profiles']['1']['dhcpd_config'], {'enabled': False})
        text = '\n'.join(cli(plan, '1'))
        for s in ('active-leasequery', 'managed-services dhcp', 'dhcp-service', 'no-unicast-replies'):
            self.assertNotIn(s, text)

    def test_tenant_without_internet(self):
        def m(a):
            tenant(a, 'MEDIA').update(internet=False, ipv6='none')
            tenant(a, 'MEDIA')['dhcp']['dns_servers'] = ['10.10.40.53']
        a, plan = self.build(m)
        self.assertEqual(plan['org_objects'][3]['body']['internet_access'], {'enabled': False})
        p = plan['profiles']['2']
        self.assertNotIn('MEDIA', [s for s in p['service_policies'] if s['name'] == 'Internet'][0]['tenants'])
        self.assertNotIn('set security nat source rule-set LAN_to_ICD from zone MEDIA', p['additional_config_cmds'])
        self.assertNotIn('set interfaces ae0 unit 40 family inet filter input TO-PEER-ISP', p['additional_config_cmds'])

    def test_plan_views(self):
        with tempfile.TemporaryDirectory() as d:
            a = fixture()
            a['profiles_method'] = 'ui-import'
            a['mgmt'].update(mode='static-gw', oob_network='172.31.253.128/25', gateway='172.31.253.254')
            a['nodes']['1']['mgmt_ip'], a['nodes']['2']['mgmt_ip'] = '172.31.253.129', '172.31.253.130'
            self.assertEqual(problems(a), [])
            B.write_plan(a, d)
            plan, topo = read(os.path.join(d, 'plan.md')), read(os.path.join(d, 'topology.txt'))
        self.assertIn('UI Import Profile (you)', plan)
        self.assertIn('UI Applies To Devices (you)', plan)
        self.assertNotIn('| POST | /orgs/{org_id}/deviceprofiles |', plan)
        self.assertIn('secrets/ (mode 600)', plan)
        self.assertIn('172.31.253.254', topo)                       # wrapped, not cut
        self.assertIn('preferred active', topo)
        self.assertNotIn('at start', plan + topo)
        with tempfile.TemporaryDirectory() as d:
            a = fixture()
            a['hub']['present'] = False
            for t in a['tenants']:
                t.update(overlay=False, ipv6='none')
            a['isps']['1'].update(ipv6_pd=False)
            self.assertEqual(problems(a), [])
            B.write_plan(a, d)
            plan = read(os.path.join(d, 'plan.md'))
        self.assertNotIn('| Overlay | node-local', plan)
        self.assertNotIn('| IPv6 | SLAAC', plan)
        self.assertIn('| POST | /orgs/{org_id}/deviceprofiles |', plan)

    def test_named_objects(self):
        plan = B.build(fixture())
        orgnames = {o['body']['name'] for o in plan['org_objects']}
        for n in ('1', '2'):
            no = B.named_objects(plan['profiles'][n])
            self.assertEqual(no['networks'], ['CORP', 'GUEST', 'ICD', 'IOT', 'MEDIA', 'MGMT', 'SECURITY'])
            self.assertEqual(no['services'], ['HUB-SITE-NETS'])
            self.assertTrue(set(no['networks'] + no['services']) <= orgnames)

    def test_mgmt_variants(self):
        a, plan = self.build(lambda a: (a['mgmt'].update(mode='static-gw', gateway='192.168.100.1')))
        self.assertEqual(plan['profiles']['1']['oob_ip_config'],
                         {'type': 'static', 'ip': '192.168.100.11', 'netmask': '/24', 'gateway': '192.168.100.1', 'use_mgmt_vrf': True})

        def none(a):
            a['mgmt'].update(mode='none', oob_network=None)
            for n in ('1', '2'):
                a['nodes'][n]['mgmt_ip'] = None
        a, plan = self.build(none)
        self.assertEqual(plan['profiles']['2']['oob_ip_config'],
                         {'type': 'static', 'ip': '10.255.1.130', 'netmask': '/25', 'use_mgmt_vrf': False})
        a, plan = self.build(lambda a: a['mgmt'].update(mode='dhcp'))
        self.assertEqual(plan['profiles']['1']['oob_ip_config'], {'type': 'dhcp', 'use_mgmt_vrf': True})

    def test_custom_internal_block_and_asn(self):
        a, plan = self.build(lambda a: a['internal'].update(block='172.31.252.0/22', icd_asn={'1': '4200000001', '2': '4200000002'}))
        lines = cli(plan, '2')
        self.assertIn('set chassis high-availability local-id local-ip 172.31.252.2', lines)
        self.assertIn('set chassis high-availability services-redundancy-group 1 active-signal-route 172.31.255.1', lines)
        self.assertEqual(plan['profiles']['2']['bgp_config']['ICD']['neighbors'], {'172.31.254.1': {'neighbor_as': '4200000001'}})
        self.assertEqual(plan['org_objects'][6]['body']['subnet'], '172.31.254.0/30')

    def test_one_and_thirty_two_tenants(self):
        def one(a):
            a['tenants'] = [tenant(a, 'MGMT')]
            a['tenants'][0]['overlay'] = True
        a, plan = self.build(one)
        self.assertFalse(any('TO-PEER-ISP' in x for x in cli(plan, '1')))

        def many(a):
            base = tenant(a, 'CORP')
            a['tenants'] = [tenant(a, 'MGMT'), tenant(a, 'IOT')]
            for k in range(1, 31):
                t = copy.deepcopy(base)
                t.update(name='NET%02d' % k, vlan_id=100 + k, subnet='10.20.%d.0/24' % k, gateway='10.20.%d.1' % k,
                         ipv6='none', ssh=False, preferred_isp=1 + k % 2)
                t['dhcp'].update(start='10.20.%d.10' % k, end='10.20.%d.200' % k)
                a['tenants'].append(t)
        a, plan = self.build(many)
        self.assertEqual(len([x for x in cli(plan, '1') if ' use-virtual-mac' in x]), 32)


class AnswerDefaultsAndEdgeTests(unittest.TestCase):
    """A key left out takes the intake default; answer classes that build; problems carry the right question."""

    def same_plan(self, left_out, written):
        a, b = fixture(), fixture()
        left_out(a)
        written(b)
        self.assertEqual(problems(a), [])
        self.assertEqual(problems(b), [])
        pa, pb = B.build(a), B.build(b)
        self.assertEqual(pa['profiles'], pb['profiles'])
        self.assertEqual(pa['org_objects'], pb['org_objects'])

    def test_t5_left_out_is_isp_1(self):
        self.same_plan(lambda a: tenant(a, 'GUEST').pop('preferred_isp'),
                       lambda a: tenant(a, 'GUEST').update(preferred_isp=1))

    def test_t4_left_out_is_the_first_host(self):
        self.same_plan(lambda a: tenant(a, 'CORP').pop('gateway'),
                       lambda a: tenant(a, 'CORP').update(gateway='10.10.20.1'))

    def test_t5_not_asked_for_internet_via_hub(self):
        a = fixture()
        tenant(a, 'MEDIA').update(internet='via-hub')
        tenant(a, 'MEDIA').pop('preferred_isp')
        qs = [(p['kind'], p['q']) for p in problems(a)]
        self.assertIn(('stop', 'T14'), qs)
        self.assertNotIn(('reask', 'T5'), qs)

    def test_hub_outside_mist_then_no_hub_builds(self):
        a = fixture()
        a['hub'].update(present=False, in_mist=False)
        for t in a['tenants']:
            t['overlay'] = False
        self.assertEqual(problems(a), [])

    def test_w5_no_two_routers_with_the_same_range_build(self):
        a = fixture()
        a['isps']['1']['wan_subnet'] = a['isps']['2']['wan_subnet'] = '192.168.0.0/24'
        a['isps']['same_upstream'] = None
        self.assertEqual([(p['kind'], p['q']) for p in problems(a)], [('reask', 'W5')])   # no W3 overlap re-ask
        a['isps']['same_upstream'] = False
        self.assertEqual(problems(a), [])
        a['isps']['same_upstream'] = True
        self.assertEqual(problems(a), [])
        with tempfile.TemporaryDirectory() as d:
            for v, text in ((True, 'no ISP diversity'), (False, 'each WAN subnet stays on its own node')):
                a['isps']['same_upstream'] = v
                B.write_plan(a, d)
                self.assertIn(text, read(os.path.join(d, 'plan.md')))

    def test_m1_message_lists_the_accepted_forms(self):
        for v in (None, '192.168.100.0/31', 'not-a-network'):
            a = fixture()
            a['mgmt']['oob_network'] = v
            m = [p['msg'] for p in problems(a) if p['q'] == 'M1']
            self.assertTrue(m and 'network/length' in m[0] and 'say none' in m[0], m)
            self.assertNotIn('does not appear', m[0])

    def test_t17_hub_server_waits_for_h5(self):
        a = fixture()
        t = tenant(a, 'IOT')
        t['dhcp'] = {'mode': 'relay', 'relay_servers': ['10.200.0.10']}
        t.pop('overlay')
        a['hub'].pop('site_prefixes')
        qs = [(p['q'], p['msg']) for p in problems(a)]
        self.assertFalse([m for q, m in qs if q == 'T17'], qs)
        self.assertTrue([m for q, m in qs if q == 'H5' and '10.200.0.10' in m], qs)
        t['overlay'] = False                      # T11 = no: the server is unreachable, T17 again
        self.assertTrue([p for p in problems(a) if p['q'] == 'T17'])
        t['overlay'] = True
        a['hub']['site_prefixes'] = ['10.200.0.0/16']
        self.assertEqual(problems(a), [])

    def test_icl_psk_with_a_backslash_is_refused(self):
        self.assertEqual(B.check_K3('abcd1234'), [])
        self.assertEqual([p['q'] for p in B.check_K3('abcd\\1234')], ['K3'])

    def test_msp_admin_needs_the_org_in_its_msp(self):
        priv = [{'scope': 'msp', 'msp_id': 'm-1', 'role': 'admin'}]
        self.assertEqual(B.check_A3_privileges(priv, 'org-a', {'m-1': ['org-a', 'org-b']}), [])
        self.assertEqual([p['kind'] for p in B.check_A3_privileges(priv, 'org-c', {'m-1': ['org-a']})], ['reask'])
        both = priv + [{'scope': 'org', 'org_id': 'org-c', 'role': 'write'}]
        self.assertEqual([p['kind'] for p in B.check_A3_privileges(both, 'org-c', {'m-1': ['org-a']})], ['stop'])
        self.assertEqual([p['q'] for p in B.check_A3_privileges(priv, 'org-a')], ['A3'])
        write = [{'scope': 'msp', 'msp_id': 'm-1', 'role': 'write'}]
        self.assertEqual([p['kind'] for p in B.check_A3_privileges(write, 'org-a', {'m-1': ['org-a']})], ['stop'])

    def test_b4_connected_node_gets_the_zeroize_command(self):
        rec = {'model': 'SRX400', 'site_id': 's', 'connected': True, 'name': 'n'}
        m = [p['msg'] for p in B.check_B_inventory(rec, dict(rec, connected=False))][0]
        self.assertIn('request system zeroize ztp-option secure-enable', m)
        self.assertIn('keep WAN, LAN and mgmt-0 unplugged', m)

    def test_existing_reuse_in_the_writes_table(self):
        a = fixture()
        a['existing'] = {'reuse': ['corp', 'ICD']}
        self.assertEqual(problems(a), [])
        with tempfile.TemporaryDirectory() as d:
            B.write_plan(a, d)
            md = read(os.path.join(d, 'plan.md'))
        rows = [l for l in md.splitlines() if l.startswith('| ') and '/orgs/{org_id}/networks' in l]
        self.assertTrue(any('| CORP |' in l and 'reuse (no write)' in l for l in rows), rows)
        self.assertTrue(any('| ICD |' in l and 'reuse (no write)' in l for l in rows), rows)
        self.assertTrue(any('| GUEST |' in l and '| POST |' in l for l in rows), rows)
        a['existing'] = {'reuse': ['NOT-PLANNED']}
        self.assertEqual([p['q'] for p in problems(a)], ['schema'])

    def test_plan_wording(self):
        a = fixture()
        a['isps']['1']['delegated_prefix'] = 'unknown'
        tenant(a, 'CORP')['dhcp'] = {'mode': 'relay', 'relay_servers': ['10.10.10.5']}
        tenant(a, 'CORP')['reach'] = ['MGMT']
        a['hub']['paths'][0]['hub_device_name'] = 'HUB-1'
        self.assertEqual(problems(a), [])
        with tempfile.TemporaryDirectory() as d:
            B.write_plan(a, d)
            md, topo = read(os.path.join(d, 'plan.md')), read(os.path.join(d, 'topology.txt'))
        self.assertIn('one profile update for this node adds', md)
        self.assertNotIn('per node adds', md)
        self.assertIn('a node that joins while its peer is ACTIVE joins as BACKUP', md)
        self.assertNotIn('first node through its push', md)
        self.assertIn('| CORP | relay to 10.10.10.5 | - | - | - | - | - | - |', md)
        self.assertIn('hub profile HUB, device HUB-1 (MAC', topo)


if __name__ == '__main__':
    unittest.main()
