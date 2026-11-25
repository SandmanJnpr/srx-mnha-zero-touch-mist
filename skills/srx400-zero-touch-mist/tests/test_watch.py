#!/usr/bin/env python3
"""Unit tests of scripts/watch.py (SKILL.md step 6 rules). Python 3.9+, standard library only."""
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'scripts'))
import watch as W  # noqa: E402

T0 = 1700000000.0


def ev(t, secs, text=None):
    e = {'type': t, 'timestamp': T0 + secs, 'mac': '00005e005311'}
    if text:
        e['text'] = text
    return e


# node 1 of the measured onboarding, seconds from T0 (SKILL.md step 6 table), with the duplicate pairs
NODE1 = [ev('GW_ZTP_STARTED', 1669), ev('GW_ZTP_STARTED', 1673), ev('GW_ZTP_FINISHED', 1694),
         ev('GW_CONNECTED', 1777), ev('GW_CONNECTED', 1883),
         ev('GW_DISCONNECTED', 1777 + 197 + 44), ev('GW_DISCONNECTED', 1777 + 197 + 44 + 14),
         ev('GW_CONNECTED', 1777 + 197 + 44 + 193)]


class RuleTests(unittest.TestCase):
    def test_pairs_keep_the_first(self):
        d = W.dedup(NODE1)
        self.assertEqual([e['type'] for e in d if e['dup']], ['GW_ZTP_STARTED', 'GW_CONNECTED', 'GW_DISCONNECTED'])
        self.assertEqual(len([e for e in d if not e['dup']]), 5)

    def test_milestones_of_the_measured_timeline(self):
        m = W.milestones(NODE1)
        self.assertEqual(m['ztp_started'], T0 + 1669)
        self.assertEqual(m['connected'], T0 + 1777)
        self.assertEqual(m['push'], T0 + 2018)
        self.assertEqual(m['back'], T0 + 2211)

    def test_late_earlier_duplicate_moves_the_milestone(self):
        later = [ev('GW_ZTP_FINISHED', 0), ev('GW_CONNECTED', 60), ev('GW_DISCONNECTED', 300)]
        self.assertEqual(W.milestones(later)['push'], T0 + 300)
        late = later + [ev('GW_DISCONNECTED', 286)]          # arrives on a later poll, earlier timestamp
        m = W.milestones(late)
        self.assertEqual(m['push'], T0 + 286)
        self.assertTrue([e for e in W.dedup(late) if e['timestamp'] == T0 + 300][0]['dup'])

    def test_no_push_without_ztp_finished(self):
        self.assertIsNone(W.milestones([ev('GW_CONNECTED', 10), ev('GW_DISCONNECTED', 100)])['push'])

    def test_bad_events(self):
        for t in ('GW_ZTP_FAILED', 'GW_CONFIG_FAILED', 'LOCK_FAILED', 'GW_CONFIG_ERROR_ADDTL_COMMAND',
                  'GW_ZTP_PRE_SCRIPT_STARTED', 'GW_UPGRADE_STARTED'):
            self.assertTrue(W.bad_event(t), t)
        for t in ('GW_CONNECTED', 'GW_HA_SRG_STATE_CHANGED', 'GW_ZTP_FINISHED'):
            self.assertFalse(W.bad_event(t), t)

    def test_absence_windows_wait_five_minutes_past_the_end(self):
        m = dict.fromkeys(W.MILESTONES)
        self.assertEqual(W.absence_alerts(m, T0, T0 + 35 * 60 + 299), [])
        self.assertEqual([a for a, _ in W.absence_alerts(m, T0, T0 + 35 * 60 + 300)], ['no-ztp-started'])
        self.assertEqual(W.absence_alerts(m, None, T0 + 99999), [])          # no T0 yet: no T0 window
        m = W.milestones(NODE1)
        self.assertEqual(W.absence_alerts(m, T0, T0 + 99999), [])

    def test_late_push_and_not_back(self):
        m = dict.fromkeys(W.MILESTONES)
        m.update(ztp_started=T0 + 10, ztp_finished=T0 + 40, connected=T0 + 100)
        self.assertEqual([a for a, _ in W.absence_alerts(m, T0, T0 + 100 + 900 + 300)], ['no-push'])
        m['push'] = T0 + 400
        alerts = W.absence_alerts(m, T0, T0 + 400 + 660 + 300)
        self.assertEqual([a for a, _ in alerts], ['not-back'])
        self.assertIn('rolled back', alerts[0][1])
        self.assertIn('show system commit', alerts[0][1])

    def test_stats_view_leaves_uptime_out(self):
        a = W.stats_view({'status': 'connected', 'uptime': 100, 'if_stat': {'re0:mgmt-0.0': {'up': True, 'ips': ['192.0.2.5/24'], 'rx_bytes': 1}}})
        b = W.stats_view({'status': 'connected', 'uptime': 120, 'if_stat': {'re0:mgmt-0.0': {'up': True, 'ips': ['192.0.2.5/24'], 'rx_bytes': 9}}})
        self.assertEqual(a, b)
        self.assertNotEqual(a, W.stats_view({'status': 'connected', 'uptime': 0}))


class PollTests(unittest.TestCase):
    def test_poll_logs_changes_alerts_once_and_survives_a_bad_answer(self):
        calls = []

        def mist(method, path, body=None):
            calls.append((method, path))
            self.assertEqual(method, 'GET')
            if '/stats/devices/' in path:
                if path.endswith('dev2'):
                    raise KeyError('bad answer')
                return 200, {'status': 'connected', 'uptime': len(calls), 'config_version': 7}
            return 200, {'results': [ev('GW_ZTP_STARTED', 5), ev('GW_CONFIG_FAILED', 50)]}
        M = types.SimpleNamespace(mist=mist, redact=lambda o: o)
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'answers.json'), 'w') as f:
                json.dump({'site': {'site_id': 's1'}, 'watch': {'t0_epoch': T0, 'watch_start_epoch': T0 - 10},
                           'nodes': {'1': {'device_id': 'dev1', 'mac': 'm1'}, '2': {'device_id': 'dev2', 'mac': 'm2'}}}, f)
            out = []
            w = W.Watch(d, out)
            w.poll(M)
            w.poll(M)
            with open(os.path.join(d, 'watch.log')) as f:
                log = f.read()
        self.assertEqual(sum(1 for x in out if 'node 1 stats' in x), 1)            # uptime change is not logged
        self.assertEqual(sum(1 for x in out if 'ALERT node 1: event GW_CONFIG_FAILED' in x), 1)
        self.assertEqual(sum(1 for x in out if 'node 2 poll failed (stats): KeyError' in x), 2)
        self.assertEqual(sum(1 for x in out if 'node 2 event GW_ZTP_STARTED' in x), 1)    # events still polled
        self.assertIn('T0+0:05', log)
        self.assertTrue(all(m == 'GET' for m, _ in calls))
        self.assertTrue(any('start=%d' % (T0 - 70) in p for _, p in calls))


class LateTwinTests(unittest.TestCase):
    def test_a_late_earlier_twin_retags_the_logged_event(self):
        polls = [[ev('GW_ZTP_FINISHED', 0), ev('GW_CONNECTED', 60), ev('GW_DISCONNECTED', 300)],
                 [ev('GW_ZTP_FINISHED', 0), ev('GW_CONNECTED', 60), ev('GW_DISCONNECTED', 300),
                  ev('GW_DISCONNECTED', 286)]]
        k = {'n': 0}

        def mist(method, path, body=None):
            if '/stats/devices/' in path:
                return 200, {'status': 'connected', 'uptime': 5}
            return 200, {'results': polls[min(k['n'], 1)]}
        M = types.SimpleNamespace(mist=mist, redact=lambda o: o)
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'answers.json'), 'w') as f:
                json.dump({'site': {'site_id': 's1'}, 'watch': {'t0_epoch': T0, 'watch_start_epoch': T0 - 10},
                           'nodes': {'1': {'device_id': 'dev1', 'mac': 'm1'}, '2': {'device_id': 'dev2', 'mac': 'm2'}}}, f)
            out = []
            w = W.Watch(d, out)
            w.poll(M)
            first = list(out)
            k['n'] = 1
            w.poll(M)
            second = out[len(first):]
        self.assertFalse([x for x in first if 'duplicate' in x], first)
        late = [x for x in second if 'node 1 event GW_DISCONNECTED' in x]
        self.assertTrue(late[0].startswith('%s node 1 event GW_DISCONNECTED' % W.stamp(T0 + 286, T0)), late)
        self.assertNotIn('duplicate', late[0])
        self.assertTrue(any('GW_DISCONNECTED at %s is now the duplicate of a pair' % W.stamp(T0 + 300, T0) in x
                            for x in second), second)
        self.assertTrue(any('milestone push %s (moved from %s)' % (W.stamp(T0 + 286, T0), W.stamp(T0 + 300, T0)) in x
                            for x in second), second)


class RobustnessTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.ans = {'site': {'site_id': 's1'}, 'watch': {'t0_epoch': T0, 'watch_start_epoch': T0 - 10},
                    'nodes': {'1': {'device_id': 'dev1', 'mac': 'm1'}, '2': {'device_id': 'dev2', 'mac': 'm2'}}}
        with open(os.path.join(self.d, 'answers.json'), 'w') as f:
            json.dump(self.ans, f)

        def mist(method, path, body=None):
            if '/stats/devices/' in path:
                return 200, {'status': 'connected', 'uptime': 5, 'if_stat': ({'x': 1}, {})}   # not a dict
            return 200, {'results': [ev('GW_ZTP_STARTED', 5)]}
        self.M = types.SimpleNamespace(mist=mist, redact=lambda o: o)

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_if_stat_that_is_not_a_dict(self):
        self.assertEqual(W.stats_view({'status': 'connected', 'if_stat': ({'a': 1}, {})})['if_stat'], {})

    def test_answers_mid_write_uses_the_last_good_copy(self):
        out = []
        w = W.Watch(self.d, out)
        w.poll(self.M)
        with open(os.path.join(self.d, 'answers.json'), 'w') as f:
            f.write('{"site": {"site_')                    # a write in progress
        w.poll(self.M)
        self.assertTrue(any('answers.json unreadable' in x and 'last good copy' in x for x in out), out)
        self.assertFalse(any('poll failed' in x for x in out), out)

    def test_once_writes_nothing_to_watch_log(self):
        out = []
        w = W.Watch(self.d, out, append=False)
        w.poll(self.M)
        self.assertTrue(out)
        self.assertFalse(os.path.exists(os.path.join(self.d, 'watch.log')))


if __name__ == '__main__':
    unittest.main()
