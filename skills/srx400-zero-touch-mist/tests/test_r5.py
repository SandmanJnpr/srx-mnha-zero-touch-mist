#!/usr/bin/env python3
"""Unit tests of the answer classes, read checks and client safeguards added in fix round 5 (no network: the
redirect test uses two local HTTP servers). Python 3.9+, standard library only."""
import copy
import http.server
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL, 'scripts')
sys.path.insert(0, SCRIPTS)
import build_plan as B  # noqa: E402

FIXTURE = os.path.join(HERE, 'fixtures', 'answers-doc.json')
EXAMPLE = os.path.join(SKILL, 'answers.example.json')
CLI = os.path.join(SCRIPTS, 'build_plan.py')
H = '$6$saltsalt$' + 'Q' * 86
TOKEN = 'FAKE0123456789abcdefFAKE0123456789abcdef'


def load(p):
    with open(p) as f:
        return json.load(f)


def fixture():
    return load(FIXTURE)


def real(a):
    """The fixture as a customer file: no _fixture key, ids in the forms Mist reads, a prefix that is not
    documentation space."""
    a = copy.deepcopy(a)
    a.pop('_fixture', None)
    a['mist']['org_id'] = '11111111-2222-4333-8444-555555555555'
    a['mist']['org_name'] = 'Example org'
    a['site']['site_id'] = '66666666-7777-4888-8999-000000000000'
    a['site']['timezone'] = 'UTC'
    for n, m in (('1', '020000000101'), ('2', '020000000102')):
        a['nodes'][n]['mac'] = m
        a['nodes'][n]['device_id'] = '00000000-0000-0000-1000-' + m
    p = a['hub']['paths'][0]
    p.update(hub_mac='020000000f01', hub_device_id='00000000-0000-0000-1000-020000000f01',
             hub_site_id='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee')
    a['isps']['1']['delegated_prefix'] = '2600:1f00:2000::/60'
    return a


def qs(problems):
    return [(p['kind'], p['q']) for p in problems]


def load_client(answers, token=TOKEN):
    d = tempfile.mkdtemp()
    shutil.copy(os.path.join(SCRIPTS, 'mist_api.py'), d)
    tok = os.path.join(d, 'tok')
    with open(tok, 'w') as f:
        f.write(token)
    os.chmod(tok, 0o600)
    ans = copy.deepcopy(answers)
    ans['mist']['token_file'] = tok
    with open(os.path.join(d, 'answers.json'), 'w') as f:
        json.dump(ans, f)
    spec = importlib.util.spec_from_file_location('mist_api_r5_%d' % id(d), os.path.join(d, 'mist_api.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m._dir = d
    return m


M = load_client({'mist': {'api_host': 'api.mist.com', 'portal_host': 'manage.mist.com'}})


class CustomerFileTests(unittest.TestCase):
    def test_real_file_builds(self):
        self.assertEqual(B.validate(real(fixture())), [])

    def test_copied_example_is_refused(self):
        a = load(EXAMPLE)
        a['isps']['1']['delegated_prefix'] = '2600:1f00:2000::/60'
        got = B.validate(a)
        msgs = ' '.join(p['msg'] for p in got)
        self.assertIn(('reask', 'schema'), qs(got))
        self.assertIn('example text <...>', msgs)
        self.assertIn('mist.org_id', msgs)
        self.assertIn(('reask', 'H4'), qs(got))           # the RFC 7042 documentation hub MAC
        self.assertNotIn('$6$', msgs)

    def test_ids_in_read_forms(self):
        a = real(fixture())
        a['nodes']['2']['device_id'] = '00000000-0000-0000-1000-020000000101'
        self.assertEqual(qs(B.validate(a)), [('reask', 'B2')])
        a = real(fixture())
        a['nodes']['1']['mac'] = '00005e005301'
        a['nodes']['1']['device_id'] = '00000000-0000-0000-1000-00005e005301'
        self.assertIn('documentation MAC', B.validate(a)[0]['msg'])
        a = real(fixture())
        a['site']['site_id'] = 'BRANCH-01'
        self.assertEqual(qs(B.validate(a)), [('reask', 'B1')])
        a = real(fixture())
        del a['mist']['org_id']
        self.assertEqual(qs(B.validate(a)), [('reask', 'A3')])

    def test_api_host_must_be_the_portal_api_host(self):
        a = real(fixture())
        a['mist']['api_host'] = 'api.mist.com.example.net'
        self.assertEqual(qs(B.validate(a)), [('reask', 'A1')])
        a['mist'].update(portal_host='manage.ac2.mist.com', api_host='api.mist.com')
        self.assertEqual(qs(B.validate(a)), [('reask', 'A1')])
        a['mist']['api_host'] = 'api.ac2.mist.com'
        self.assertEqual(B.validate(a), [])


class AlqTests(unittest.TestCase):
    def test_default_is_the_first_dhcp_server_network(self):
        a = fixture()
        T = B.tenant_order(a['tenants'])
        T[0]['dhcp'] = {'mode': 'none'}
        plan = B.build(a)
        d = plan['derived']
        self.assertEqual(d['alq'], T[1]['name'])
        cli = plan['profiles']['1']['additional_config_cmds']
        peer = d['nodes']['1']['alq_peer']
        self.assertIn('set routing-instances lan system services dhcp-local-server active-leasequery peer-address %s'
                      % peer, cli)
        self.assertNotEqual(peer, B.derive(fixture())['nodes']['1']['alq_peer'])

    def test_a_network_without_the_dhcp_server_is_reasked(self):
        a = fixture()
        T = B.tenant_order(a['tenants'])
        T[2]['dhcp'] = {'mode': 'none'}
        a['pair']['alq_tenant'] = T[2]['name']
        got = B.validate(a)
        self.assertEqual(qs(got), [('reask', 'T20')])
        self.assertIn('do not serve DHCP', got[0]['msg'])


class StructureStopTests(unittest.TestCase):
    def test_ipv6_from_both_isps_stops(self):
        a = fixture()
        a['isps']['2'].update(ipv6_pd=True, delegated_prefix='2001:db8:3000::/60', prefix_stable='yes')
        a['site_readiness']['isp2_dhcpv6'] = 'yes'
        a['tenants'][1]['ipv6'] = 'both'
        got = B.validate(a)
        self.assertEqual(qs(got), [('stop', 'T10')])
        self.assertIn('Alternative: IPv6 from one ISP', got[0]['msg'])
        self.assertEqual(B.exit_code(got), 2)

    def test_public_subnet_nat_routed_and_other(self):
        a = fixture()
        T = B.tenant_order(a['tenants'])
        T[1].update(subnet='192.88.99.0/26', gateway='192.88.99.1', dhcp={'mode': 'none'})
        self.assertEqual(B.validate(a), [])                       # T21 default: nat
        plan = B.build(a)
        md = B.render_plan_md(plan['derived'], plan)
        self.assertIn('source NAT to the WAN address of the node whose ISP it uses (a public subnet too: %s)'
                      % T[1]['name'], md)
        T[1]['public_nat'] = 'routed'
        self.assertEqual(qs(B.validate(a)), [('stop', 'T21')])
        T[1]['public_nat'] = 'maybe'
        self.assertEqual(qs(B.validate(a)), [('reask', 'T21')])
        T[1].update(public_nat='routed', internet=False)
        T[1].pop('preferred_isp', None)
        T[1]['ipv6'] = 'none'
        self.assertNotIn('T21', [p['q'] for p in B.validate(a)])  # no Internet: no NAT question


class FreeTextTests(unittest.TestCase):
    def test_dhcp_option_values_by_type(self):
        good = {'ip': '10.10.20.5', 'uint16': '1500', 'int32': -5, 'boolean': 'true', 'hex': '0a0B', 'string': 'abc.d-e'}
        bad = {'ip': 'not-an-ip "; x', 'uint16': '70000', 'int16': 'x', 'boolean': 'yes', 'hex': 'abc', 'string': 'a"b'}
        for typ, v in good.items():
            self.assertEqual(B.option_value_problem(typ, v), '', typ)
        for typ, v in bad.items():
            self.assertNotEqual(B.option_value_problem(typ, v), '', typ)
        a = fixture()
        a['tenants'][0]['dhcp']['options'] = {'42': {'type': 'ip', 'value': 'not-an-ip "; x'}}
        self.assertEqual(qs(B.validate(a)), [('reask', 'T16')])

    def test_reservation_name_is_a_host_label(self):
        a = fixture()
        t = B.tenant_order(a['tenants'])[0]
        t['dhcp']['fixed_bindings'] = {'020000000a01': {'ip': '10.10.10.250', 'name': 'pc 1";\nset x'}}
        self.assertEqual(qs(B.validate(a)), [('reask', 'T16')])
        t['dhcp']['fixed_bindings'] = {'020000000a01': {'ip': '10.10.10.250', 'name': 'label-printer-1'}}
        self.assertEqual(B.validate(a), [])

    def test_hub_profile_name_and_path(self):
        a = fixture()
        p = a['hub']['paths'][0]
        p.update(hub_profile_name='HUB x', path='HUB x-wan')
        self.assertIn(('reask', 'H3'), qs(B.validate(a)))

    def test_secret_keyword_network_names(self):
        for nm in ('secret', 'x-secret', 'authentication-key', 'Password'):
            a = fixture()
            a['tenants'][1]['name'] = nm
            self.assertIn(('reask', 'T1'), qs(B.validate(a)), nm)
        for nm in ('secret2', 'x_secret', 'MONKEY', 'BYPASS'):     # build, and survive the step 4.2 compare
            a = fixture()
            a['tenants'][1]['name'] = nm
            self.assertEqual(B.validate(a), [], nm)
            p = B.build(a)['profiles']['2']
            self.assertEqual(M.redact(B.fill_secrets(p, root_hash=H, license_key='JUNOS1 abc')), p, nm)


class SecretTests(unittest.TestCase):
    def plan(self, **pair):
        a = fixture()
        a['nodes']['1']['root_ssh_key_file'] = '/x'
        a['pair'].update(pair)
        return B.build(a)['profiles']['1']

    def test_angle_brackets_refused_and_never_echoed(self):
        self.assertTrue(B.check_K3('Ab<Secret9>xyz'))
        self.assertTrue(B.check_K2('KEY<1>'))
        self.assertTrue(B.check_K1('$6$salt<x>$' + 'q' * 20))
        p = self.plan(icl_encryption=True, icl_psk_file='/x')
        with self.assertRaises(ValueError) as cm:
            B.fill_secrets(p, root_hash=H, root_ssh_key='ssh-ed25519 ' + 'A' * 68, icl_psk='Ab<Secret9>xyz')
        self.assertNotIn('Secret9', str(cm.exception))

    def test_ssh_key_comment_with_an_address_fills_without_it(self):
        key = 'ssh-ed25519 ' + 'A' * 68 + ' Jane Doe <jane@corp.example>'
        self.assertEqual(B.check_K1(key, 'ssh-key'), [])
        body = B.fill_secrets(self.plan(), root_hash=H, root_ssh_key=key)
        self.assertNotIn('jane', json.dumps(body))
        self.assertIn('set system root-authentication ssh-ed25519 "ssh-ed25519 %s"' % ('A' * 68),
                      body['additional_config_cmds'])

    def test_unfilled_plan_placeholder_named_before_the_fill(self):
        p = self.plan()
        p['additional_config_cmds'].append('set system host-name <HOST>')
        with self.assertRaises(ValueError) as cm:
            B.fill_secrets(p, root_hash=H, root_ssh_key='ssh-ed25519 ' + 'A' * 68)
        self.assertIn('<HOST>', str(cm.exception))


class TokenFileTests(unittest.TestCase):
    def test_a2_checks_the_shape_without_the_value(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, 't')
            for content, ok in ((TOKEN + '\n', True), (TOKEN + '\nmy note\n', False), ('short1', False)):
                with open(f, 'w') as h:
                    h.write(content)
                os.chmod(f, 0o600)
                got = B.check_A2(f)
                self.assertEqual(got == [], ok, content)
                self.assertNotIn(TOKEN, json.dumps(got))

    def test_client_sends_nothing_with_a_two_line_token(self):
        m = load_client({'mist': {'api_host': 'api.mist.com'}}, token=TOKEN + '\nnote\n')
        st, out = m.mist('GET', '/self')
        self.assertEqual(st, 0)
        self.assertIn('nothing was sent', out)
        self.assertNotIn(TOKEN, out)
        self.assertEqual(m.mask_token('x Token %s y' % TOKEN), 'x Token <TOKEN> y')

    def test_client_refuses_a_host_that_is_not_the_portal_api_host(self):
        for host, portal in (('api.mist.com.example.net', 'manage.mist.com'), ('api.mist.com', 'manage.ac2.mist.com'),
                             ('127.0.0.1', None)):
            mist = {'api_host': host}
            if portal:
                mist['portal_host'] = portal
            m = load_client({'mist': mist})
            st, out = m.mist('GET', '/self')
            self.assertEqual(st, 0, host)
            self.assertIn('nothing was sent', out)


class _Rec(http.server.BaseHTTPRequestHandler):
    hits = []
    target = None

    def do_GET(self):
        _Rec.hits.append((self.server.server_port, self.headers.get('Authorization')))
        if _Rec.target and self.server.server_port != _Rec.target:
            self.send_response(302)
            self.send_header('Location', 'http://127.0.0.1:%d/x' % _Rec.target)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{}')

    def log_message(self, *a):
        pass


class RedirectTests(unittest.TestCase):
    def test_authorization_never_follows_a_redirect(self):
        s1 = http.server.HTTPServer(('127.0.0.1', 0), _Rec)
        s2 = http.server.HTTPServer(('127.0.0.1', 0), _Rec)
        for s in (s1, s2):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        _Rec.hits, _Rec.target = [], s2.server_port
        try:
            req = urllib.request.Request('http://127.0.0.1:%d/a' % s1.server_port,
                                         headers={'Authorization': 'Token ' + TOKEN})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                M._OPENER.open(req, timeout=5)
            self.assertEqual(cm.exception.code, 302)
            self.assertEqual([p for p, _ in _Rec.hits], [s1.server_port])
        finally:
            for s in (s1, s2):
                s.shutdown()
                s.server_close()


class RedactTests(unittest.TestCase):
    def leak(self, o, *vals):
        s = json.dumps(M.redact(o))
        for v in vals:
            self.assertNotIn(v, s)

    def test_site_vars_and_secret_lists(self):
        self.leak({'vars': {'ROOT_HASH': H, 'ADMIN_PW': 'Winter2026!', 'RADIUS_PASS': 'radpass1', 'SNMP_COMM': 'c1'}},
                  'Q' * 20, 'Winter2026!', 'radpass1', '"c1"')
        self.leak({'psk': ['p-one-1'], 'password': {'value': 'p-two-2'}}, 'p-one-1', 'p-two-2')

    def test_cli_secret_forms(self):
        self.leak({'additional_config_cmds': [
            'set system ntp authentication-key 1 type md5 value "ntpsecret1"',
            'set system login user ops authentication plain-text-password-value "opsplain1"',
            'set snmp v3 usm local-engine user u authentication-sha authentication-password "snmpauth1"',
            'set protocols ospf area 0 interface ge-0/0/1 authentication md5 1 key "ospfkey1"',
            'set access profile p client u firewall-user password s3cretFW',
            'set snmp community s3cretcomm authorization read-only']},
            'ntpsecret1', 'opsplain1', 'snmpauth1', 'ospfkey1', 's3cretFW', 's3cretcomm')

    def test_hierarchical_diff_forms_and_event_copies(self):
        diff = ('[edit system]\n+  license { keys { key "JUNOS123456 aeaqic SECRETLIC"; } }\n'
                '+  ssh-ed25519 "ssh-ed25519 AAAASECRETSSHKEY user@host";\n+  community s3cretcomm {\n')
        self.leak(diff, 'SECRETLIC', 'AAAASECRETSSHKEY', 's3cretcomm')
        ev = M.redact({'results': [{'type': 'GW_CONFIGURED', 'config_diff': diff, 'commit_log': diff,
                                    'before': {'x': 1}, 'after': {'y': 2}}]})
        self.assertTrue(ev['results'][0]['config_diff'].endswith('characters, not shown>'))
        self.assertEqual(M.event_rows([{'type': 'T', 'timestamp': 1, 'mac': 'm', 'text': 'secret "x y"',
                                        'config_diff': diff}]),
                         [{'type': 'T', 'timestamp': 1, 'mac': 'm', 'text': 'secret "<SECRET>"'}])

    def test_escaped_unterminated_unquoted_and_keyed(self):
        self.assertNotIn('words', M.redact(json.dumps('set system radius-server 10.0.0.1 secret "two words"')))
        self.assertNotIn('Q' * 20, M.redact('error near encrypted-password %s' % H))
        self.assertNotIn('aeaqic', M.safe_error('line 57: set system license keys key "JUNOS123456 aeaqic aiagij'))
        self.assertNotIn('Q' * 20, M.safe_error({'encrypted-password "%s"' % H: ['invalid']}))
        junos_escaped = 'set security ike policy P pre-shared-key ascii-text "ab\\"cd tail"'
        self.assertNotIn('tail', M.redact(json.dumps({'c': [junos_escaped]})))
        self.assertNotIn('tail', M.redact(junos_escaped))

    def test_cli_views_print_only_judged_fields(self):
        st = {'vars': {'ADMIN_PW': 'Winter2026!'}, 'juniper_srx': {'auto_upgrade': {'enabled': True, 'version': '1'}},
              'gateway_mgmt': {'root_password': 'pw-value-1', 'config_revert_timer': 4}}
        out = M.cli_view('/sites/s/setting', st)
        self.assertNotIn('Winter2026!', out)
        self.assertNotIn('pw-value-1', out)
        self.assertIn('"config_revert_timer": 4', out)
        rec = {'id': 'd', 'name': 'n', 'mac': 'm', 'vars': {'X': 'secret-value-9'}, 'mnha_config': {'enabled': True},
               'port_config': {}, 'disable_auto_config': False, 'mist_configured': True}
        out = M.cli_view('/sites/s/devices/d', rec)
        self.assertNotIn('secret-value-9', out)
        self.assertEqual(json.loads(out)['device_level_keys'], ['mnha_config', 'vars'])
        self.assertNotIn('pw-value-1', M.cli_view('/orgs/o/something', {'k': 'pw-value-1'}))
        logs = {'results': [{'message': 'device[x] manually restarted', 'site_id': 's', 'timestamp': 1,
                             'before': {'secret': 'b1'}, 'admin_name': 'Some Person'}]}
        out = M.cli_view('/orgs/o/logs', logs)
        self.assertNotIn('Some Person', out)
        self.assertNotIn('b1', out)

    def test_device_record_keys_match_build_plan(self):
        self.assertEqual(M.DEVICE_RECORD_KEYS, B.DEVICE_RECORD_KEYS)


class WritePrivateTests(unittest.TestCase):
    def test_mode_600_and_never_over_a_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, 'x.json')
            M.write_private(f, {'a': 1})
            self.assertEqual(os.stat(f).st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                M.write_private(f, 'again')


class OrgChecksTests(unittest.TestCase):
    def test_device_record(self):
        rec = {'id': 'd', 'name': 'n', 'mac': 'm', 'site_id': 's', 'mist_configured': True, 'notes': 'x',
               'port_config': {}, 'vars': None}
        self.assertEqual(B.check_device_record(rec, '1'), [])                      # disable_auto_config absent
        self.assertEqual(qs(B.check_device_record(dict(rec, disable_auto_config=True), '1')), [('precondition', 'B2')])
        self.assertEqual(qs(B.check_device_record(dict(rec, mist_configured=False), '1')), [('precondition', 'B2')])
        got = B.check_device_record(dict(rec, mnha_config={'enabled': True}, vrf_config={'enabled': True}), '2')
        self.assertIn('mnha_config, vrf_config', got[0]['msg'])

    def test_site_settings(self):
        rel = '25.4X300-D30.3-EVO'
        self.assertEqual(B.check_site_settings({}, {}, rel), [])
        on = {'juniper_srx': {'auto_upgrade': {'enabled': True}}}
        self.assertEqual(qs(B.check_site_settings(on, {}, rel)), [('precondition', 'B1')])
        pinned = {'juniper_srx': {'auto_upgrade': {'enabled': True, 'custom_versions': {'SRX400': '25.4X300-D30.3'}}}}
        self.assertEqual(B.check_site_settings(on, pinned, rel), [])               # the site value wins
        self.assertEqual(B.check_site_settings({}, {'juniper_srx': {'auto_upgrade': {'enabled': False}}}, rel), [])
        self.assertEqual(B.check_site_settings({}, {'gateway_mgmt': {'config_revert_timer': 10}}, rel), [])
        for st in ({'config_push_policy': {'no_push': True}},
                   {'config_push_policy': {'push_window': {'enabled': True}}},
                   {'gateway_mgmt': {'config_revert_timer': 4}}, {'gateway_mgmt': {'protect_re': {'enabled': True}}},
                   {'gateway_mgmt': {'root_password': 'x'}}, {'gateway_mgmt': {'disable_oob': True}}):
            got = B.check_site_settings({}, st, rel)
            self.assertEqual(qs(got), [('precondition', 'B1')], st)
            self.assertNotIn('"x"', json.dumps(got))
        self.assertEqual(B.check_site_settings({'gateway_mgmt': {'config_revert_timer': 4}},
                                               {'gateway_mgmt': {'config_revert_timer': 10}}, rel), [])

    def test_a3_through_the_org_record(self):
        o = 'org-a'
        msp = [{'scope': 'msp', 'msp_id': 'm-1', 'role': 'admin'}]
        self.assertEqual(B.check_A3_privileges(msp, o, org={'id': o, 'msp_id': 'm-1'}), [])
        self.assertEqual(qs(B.check_A3_privileges(msp, o, org={'id': o, 'msp_id': 'm-2'})), [('reask', 'A3')])
        self.assertEqual(qs(B.check_A3_privileges(msp, o)), [('reask', 'A3')])
        og = [{'scope': 'orggroup', 'orggroup_ids': ['g-1'], 'role': 'admin'}]
        self.assertEqual(B.check_A3_privileges(og, o, org={'id': o, 'orggroup_ids': ['g-1']}), [])
        og_read = [{'scope': 'orggroup', 'orggroup_ids': ['g-1'], 'role': 'read'}]
        self.assertEqual(qs(B.check_A3_privileges(og_read, o, org={'id': o, 'orggroup_ids': ['g-1']})), [('stop', 'A3')])
        site = [{'scope': 'site', 'org_id': o, 'site_id': 's', 'role': 'admin'}]
        got = B.check_A3_privileges(site, o)
        self.assertEqual(qs(got), [('stop', 'A3')])
        self.assertIn('site access', got[0]['msg'])


class PlanTextTests(unittest.TestCase):
    def test_failover_statements(self):
        plan = B.build(fixture())
        md = B.render_plan_md(plan['derived'], plan)
        self.assertIn('- no IPv6 failover:', md)
        self.assertIn('the overlay networks do not reach the hub (SRG1 does not move on a WAN loss)', md)
        self.assertIn('an upstream outage that leaves the WAN link and the lease up does not move it', md)
        self.assertIn('IPv6 has no failover', B.render_topology_md(plan['derived'], plan))


class UpdateModeTests(unittest.TestCase):
    def run_cli(self, *args):
        r = subprocess.run([sys.executable, CLI] + list(args), capture_output=True, text=True)
        return r.returncode, r.stdout

    def test_ipv6_prefix_after_onboarding_is_one_put(self):
        with tempfile.TemporaryDirectory() as d:
            a = fixture()
            a['isps']['1']['delegated_prefix'] = 'unknown'
            a['isps']['1']['pd_length'] = 60
            f = os.path.join(d, 'answers.json')
            with open(f, 'w') as h:
                json.dump(a, h)
            rc, _ = self.run_cli('--answers', f, '--out', os.path.join(d, 'plan'))
            self.assertEqual(rc, 0)
            self.assertEqual(os.stat(os.path.join(d, 'plan', 'plan.md')).st_mode & 0o077, 0)   # umask 077
            a['isps']['1']['delegated_prefix'] = '2001:db8:2000::/60'
            with open(f, 'w') as h:
                json.dump(a, h)
            rc, out = self.run_cli('--answers', f, '--out', os.path.join(d, 'plan-update'), '--update',
                                   os.path.join(d, 'plan'))
            self.assertEqual(rc, 0, out)
            with open(os.path.join(d, 'plan-update', 'update.md')) as h:
                up = h.read()
            self.assertIn('| 1 | PUT | /orgs/{org_id}/deviceprofiles/{profile_id} | SZTP-SRX400-NODE1 | '
                          'additional_config_cmds, whole values |', up)
            self.assertNotIn('| 2 | PUT', up)
            self.assertNotIn('POST', up)
            self.assertIn('+ set routing-options rib inet6.0 static route 2001:db8:2000::/60 discard', up)
            a['tenants'][0]['vlan_id'] = 11
            with open(f, 'w') as h:
                json.dump(a, h)
            rc, out = self.run_cli('--answers', f, '--out', os.path.join(d, 'plan-x'), '--update',
                                   os.path.join(d, 'plan'))
            self.assertEqual(rc, 2)
            self.assertIn('[stop] update: the org objects change', out)


class WatchMaskTests(unittest.TestCase):
    def test_reason_masks_the_token(self):
        sys.path.insert(0, SCRIPTS)
        import watch as W
        ex = ValueError("Invalid header value b'Token %s\\nnote'" % TOKEN)
        r = W.reason(ex, M.redact, M.mask_token)
        self.assertNotIn(TOKEN, r)


if __name__ == '__main__':
    unittest.main()
