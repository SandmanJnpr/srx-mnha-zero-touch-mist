#!/usr/bin/env python3
"""Unit tests of scripts/mist_api.py: redact(), list_all() paging and read_secret() (no network: mist() is replaced
by a local function). Python 3.9+, standard library only."""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), 'scripts', 'mist_api.py')


def load_client():
    """mist_api reads answers.json next to itself at import: load a copy from a scratch folder."""
    d = tempfile.mkdtemp()
    shutil.copy(SRC, d)
    with open(os.path.join(d, 'answers.json'), 'w') as f:
        json.dump({'mist': {'api_host': 'api.mist.com', 'token_file': os.path.join(d, 'no-token')}}, f)
    spec = importlib.util.spec_from_file_location('mist_api_copy', os.path.join(d, 'mist_api.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    shutil.rmtree(d)
    return m


M = load_client()
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'scripts'))
import build_plan as B  # noqa: E402
PLAN_SSH = 'set system root-authentication <ROOT-SSH-KEY-TYPE> "<ROOT-SSH-KEY>"'


class RedactTests(unittest.TestCase):
    def test_root_ssh_key_line_becomes_the_plan_line(self):
        for line in ('set system root-authentication ssh-ed25519 "ssh-ed25519 %s admin@host"' % ('A' * 68),
                     'set system root-authentication ssh-rsa "ssh-rsa AAAAB3NzaC1yc2E/+= admin"',
                     'set system root-authentication ssh-ecdsa "ecdsa-sha2-nistp256 %s"' % ('B' * 60)):
            self.assertEqual(M.redact(line), PLAN_SSH)
        self.assertEqual(M.redact(PLAN_SSH), PLAN_SSH)

    def test_escaped_json_text(self):
        raw = json.dumps({'cli': ['set system root-authentication ssh-ed25519 "ssh-ed25519 %s x"' % ('C' * 68)]})
        self.assertEqual(json.loads(M.redact(raw)), {'cli': [PLAN_SSH]})
        self.assertNotIn('C' * 68, M.redact(raw))

    def test_profile_read_back_equals_plan_lines(self):
        body = {'additional_config_cmds': ['set system root-authentication encrypted-password "$6$abcdefgh$%s"' % ('x' * 86),
                                           'set system license keys key "EXAMPLE-KEY"',
                                           'set system root-authentication ssh-ed25519 "ssh-ed25519 %s a"' % ('D' * 68)],
                'magic': 'CLAIMCODE'}
        r = M.redact(body)
        self.assertEqual(r, {'additional_config_cmds': ['set system root-authentication encrypted-password "<ROOT-PASSWORD-HASH>"',
                                                        'set system license keys key "<LICENSE-KEY>"', PLAN_SSH]})


class IclKeyRedactTests(unittest.TestCase):
    def test_icl_key_line_becomes_the_plan_line(self):
        plan_line = 'set security ike policy MNHA-ICL-IKE-POL pre-shared-key ascii-text "<ICL-PSK>"'
        for psk in ('abcd1234XYZ', '$abc$12345678', 'a/b+c=1234', 'x' * 255):
            line = plan_line.replace('<ICL-PSK>', psk)
            self.assertEqual(M.redact(line), plan_line)
            raw = M.redact(json.dumps({'c': [line]}))
            self.assertNotIn(psk, raw)
            self.assertEqual(json.loads(raw)['c'], [plan_line])
        self.assertEqual(M.redact('set security ike policy OTHER pre-shared-key ascii-text "abcd1234"'),
                         'set security ike policy OTHER pre-shared-key ascii-text "<SECRET>"')

    def test_step_4_2_compare_with_ha_link_encryption(self):
        """redact() of the filled body equals the plan profile when X2 = yes (SKILL.md step 4.2)."""
        with open(os.path.join(HERE, 'fixtures', 'answers-doc.json')) as f:
            a = json.load(f)
        a['pair'].update(icl_encryption=True, icl_psk_file='/x/icl.psk')
        plan = B.build(a)
        for n in ('1', '2'):
            prof = plan['profiles'][n]
            self.assertIn('<ICL-PSK>', json.dumps(prof))
            body = B.fill_secrets(prof, root_hash='$6$abcdefgh$' + 'q' * 86, license_key='EXAMPLE-KEY-%s' % n
                                  if '<LICENSE-KEY>' in json.dumps(prof) else None, icl_psk='Icl-Key-0123456789')
            self.assertEqual(M.redact(body), prof)


class ListAllTests(unittest.TestCase):
    def fake(self, rows, broken_page=None, no_total=False):
        calls = []

        def mist(method, path):
            calls.append(path)
            q = dict(urllib.parse.parse_qsl(path.split('?', 1)[1]))
            lim, pg = int(q['limit']), int(q['page'])
            M.LAST_HEADERS = {} if no_total else {'x-page-total': str(len(rows))}
            if pg == broken_page:
                return 500, {'detail': 'x'}
            return 200, rows[(pg - 1) * lim:pg * lim]
        return mist, calls

    def test_pages_until_the_total(self):
        rows = [{'id': 'id-%d' % i, 'name': 'NET%04d' % i} for i in range(1041)]
        mist, calls = self.fake(rows)
        old, M.mist = M.mist, mist
        try:
            st, got, total, complete = M.list_all('/orgs/o/networks?limit=1000')
            self.assertEqual((st, len(got), total, complete), (200, 1041, 1041, True))
            self.assertEqual(len(calls), 2)
            self.assertTrue(all('limit=1000' in c for c in calls) and 'page=2' in calls[1])
            self.assertEqual(M.list_all('/orgs/o/deviceprofiles?type=gateway')[1][0]['id'], 'id-0')
            self.assertIn('type=gateway', calls[-1])
            ok, hits = M.find_by_name('/orgs/o/networks', 'net1040')
            self.assertEqual((ok, [h['id'] for h in hits]), (True, ['id-1040']))
            M.mist = self.fake(rows, broken_page=2)[0]
            self.assertFalse(M.list_all('/orgs/o/networks')[3])
            M.mist = self.fake(rows, no_total=True)[0]
            self.assertFalse(M.list_all('/orgs/o/networks')[3])
        finally:
            M.mist = old


class SelfPrivilegesTests(unittest.TestCase):
    def test_msp_entry_prints_its_msp_id_and_feeds_the_a3_check(self):
        out = {'name': 'admin', 'email': 'x', 'privileges': [
            {'scope': 'msp', 'msp_id': 'msp-1', 'name': 'Example MSP', 'role': 'admin', 'views': ['x']},
            {'scope': 'org', 'org_id': 'org-9', 'name': 'Other org', 'role': 'read'}]}
        privs = M.self_privileges(out)
        self.assertEqual(privs[0], {'scope': 'msp', 'org_id': None, 'msp_id': 'msp-1', 'name': 'Example MSP',
                                    'role': 'admin'})
        self.assertEqual(set(privs[1]), {'scope', 'org_id', 'msp_id', 'name', 'role'})
        msp_orgs = {p['msp_id']: ['org-a'] for p in privs if p['scope'] == 'msp'}    # GET /msps/{msp_id}/orgs
        self.assertEqual(B.check_A3_privileges(privs, 'org-a', msp_orgs), [])
        self.assertEqual(B.check_A3_privileges(privs, 'org-b', msp_orgs)[0]['kind'], 'reask')
        with open(SRC) as f:
            self.assertIn('privs = self_privileges(out)', f.read())            # what python3 mist_api.py /self prints


class ReadSecretTests(unittest.TestCase):
    def test_mode_600_required(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, 'k')
            with open(f, 'w') as h:
                h.write('LICENSE-KEY-1\n')
            os.chmod(f, 0o644)
            with self.assertRaises(ValueError) as cm:
                M.read_secret(f, 'license')
            self.assertIn('chmod 600', str(cm.exception))
            self.assertNotIn('LICENSE-KEY-1', str(cm.exception))
            os.chmod(f, 0o600)
            self.assertEqual(M.read_secret(f, 'license'), 'LICENSE-KEY-1')


if __name__ == '__main__':
    unittest.main()
