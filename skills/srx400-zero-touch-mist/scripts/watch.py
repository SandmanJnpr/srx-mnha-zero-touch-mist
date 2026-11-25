#!/usr/bin/env python3
"""watch.py: the read-only zero-touch monitor of SKILL.md step 6. Python 3.9+, standard library only.

Copy it into the working folder next to mist_api.py and answers.json and start it just before power-on:
  nohup python3 watch.py > /dev/null 2>&1 &     polls every 20 s, appends to watch.log, writes its pid to watch.pid
  python3 watch.py --once                       one extra poll; prints its lines and writes nothing to watch.log
  kill "$(cat watch.pid)"                       stop it (SKILL.md step 8)

Every poll it reads answers.json again: site.site_id, nodes.<n>.device_id and .mac, watch.watch_start_epoch (the
events window starts 60 s before it; empty: the time watch.py started) and watch.t0_epoch (the power-on time T0 the
customer reports; empty until then). Per node it calls GET /sites/{site_id}/stats/devices/{device_id} and
GET /sites/{site_id}/devices/events/search?mac=<mac>&start=<start>&limit=200 (following next). It makes no write.

watch.log, every line through mist_api.redact(), UTC time and, once T0 is known, T0+mm:ss:
  - one line per change of status, config_status, config_version, version, ip, deviceprofile_name, uptime up or 0,
    and each interface's up flag and addresses (uptime itself is left out: it changes on every poll)
  - one line per new event (a duplicate of a pair is marked as such); when an earlier event arrives late and an
    event already logged changes role (it becomes the duplicate of the late one, or stops being one), one line says so
  - the milestones, recomputed every poll from the whole event list (sorted, pairs de-duplicated): a milestone
    that moves because an earlier event arrived late is logged again with its new time
  - ALERT lines (SKILL.md step 6), each once; a heartbeat every 5 minutes; a failed call is logged with the call
    (answers, stats or events) and a short redacted reason, not fatal: stats and events are polled apart, and an
    unreadable answers.json (a write in progress) is replaced by the last good copy
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
POLL_SECONDS = 20
HEARTBEAT_SECONDS = 300
PAIR_WINDOW = 120            # GW_ZTP_STARTED, GW_CONNECTED, GW_DISCONNECTED can each come twice, up to 2 min apart
PAIRED_TYPES = ('GW_ZTP_STARTED', 'GW_CONNECTED', 'GW_DISCONNECTED')
LATE_MARGIN = 300            # events arrive up to about 5 minutes late: alert only 5 min past a window's end
WINDOWS = [                  # (alert id, anchor, seconds after the anchor, milestone that must exist by then, text)
    ('no-ztp-started', 't0', 35 * 60, 'ztp_started', 'no GW_ZTP_STARTED by T0 + 35 min'),
    ('no-connected', 't0', 45 * 60, 'connected', 'no GW_CONNECTED by T0 + 45 min'),
    ('no-push', 'connected', 15 * 60, 'push', 'no push GW_DISCONNECTED 15 min after the first GW_CONNECTED'),
    ('not-back', 'push', 11 * 60, 'back',
     'no GW_CONNECTED 11 min after the push GW_DISCONNECTED: the unconfirmed push has rolled back by now (10 min '
     'after the push); ask for show system commit | no-more on that node and look for a rollback entry'),
]
MILESTONES = ('ztp_started', 'ztp_finished', 'connected', 'push', 'back')


# ------------------------------------------------------------------ pure rules (tests/test_watch.py)
def bad_event(t):
    """An event type that alerts at once (SKILL.md step 6)."""
    t = str(t or '')
    return 'FAILED' in t or 'ERROR_ADDTL_COMMAND' in t or t.startswith('GW_ZTP_PRE_SCRIPT_') or \
        t.startswith('GW_UPGRADE_')


def event_key(e):
    return (e.get('type'), e.get('timestamp'), e.get('text'))


def dedup(events):
    """Sorted by timestamp, each event with 'dup' True when it is the second of a pair: the same type of
    PAIRED_TYPES within PAIR_WINDOW seconds of a kept one that has no pair yet."""
    out, last = [], {}
    seen = set()
    for e in sorted(events, key=lambda x: (float(x.get('timestamp') or 0), str(x.get('type')))):
        k = event_key(e)
        if k in seen:                             # the same event read twice (paging)
            continue
        seen.add(k)
        e = dict(e)
        t, ts = e.get('type'), float(e.get('timestamp') or 0)
        e['dup'] = False
        if t in PAIRED_TYPES and t in last and not last[t]['paired'] and ts - last[t]['ts'] <= PAIR_WINDOW:
            e['dup'] = True
            last[t]['paired'] = True
        elif t in PAIRED_TYPES:
            last[t] = {'ts': ts, 'paired': False}
        out.append(e)
    return out


def milestones(events):
    """From the de-duplicated list: ztp_started, ztp_finished, connected (first GW_CONNECTED after GW_ZTP_FINISHED),
    push (first GW_DISCONNECTED after that GW_CONNECTED: Mist logs no event for the push itself) and back (first
    GW_CONNECTED after the push); each an epoch or None."""
    ev = [e for e in dedup(events) if not e['dup']]

    def first(t, after=None):
        for e in ev:
            if e.get('type') == t and (after is None or float(e['timestamp']) > after):
                return float(e['timestamp'])
        return None
    m = dict.fromkeys(MILESTONES)
    m['ztp_started'] = first('GW_ZTP_STARTED')
    m['ztp_finished'] = first('GW_ZTP_FINISHED')
    if m['ztp_finished'] is not None:
        m['connected'] = first('GW_CONNECTED', m['ztp_finished'])
    if m['connected'] is not None:
        m['push'] = first('GW_DISCONNECTED', m['connected'])
    if m['push'] is not None:
        m['back'] = first('GW_CONNECTED', m['push'])
    return m


def absence_alerts(m, t0, now):
    """[(alert id, text)] of the absence windows that have closed: the poll time is at least LATE_MARGIN past the
    window end and the milestone is still absent, or came after the window end (judged by event timestamps)."""
    out = []
    for aid, anchor, secs, need, text in WINDOWS:
        base = t0 if anchor == 't0' else m.get(anchor)
        if base is None:
            continue
        end = float(base) + secs
        got = m.get(need)
        if now >= end + LATE_MARGIN and (got is None or got > end):
            out.append((aid, text))
    return out


def stats_view(s):
    """The part of a stats answer whose change is logged: no uptime value (only up or 0)."""
    if not isinstance(s, dict):
        return {'stats': str(s)[:80]}
    ifs = {}
    raw = s.get('if_stat')
    for k, v in sorted((raw if isinstance(raw, dict) else {}).items()):
        if isinstance(v, dict):
            ifs[k] = {'up': v.get('up'), 'ips': v.get('ips')}
    return {'status': s.get('status'), 'config_status': s.get('config_status'),
            'config_version': s.get('config_version'), 'version': s.get('version'), 'ip': s.get('ip'),
            'deviceprofile_name': s.get('deviceprofile_name'), 'uptime': 'up' if s.get('uptime') else 0,
            'if_stat': ifs}


def stamp(ts, t0):
    u = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(float(ts))) + 'Z'
    if t0:
        d = int(round(float(ts) - float(t0)))
        u += ' T0%s%d:%02d' % ('+' if d >= 0 else '-', abs(d) // 60, abs(d) % 60)
    return u


# ------------------------------------------------------------------ polling (needs mist_api.py and answers.json)
def reason(ex, redact, mask=None):
    """Exception type and a short redacted reason for a failed-call log line (the API token masked first)."""
    text = str(ex)
    if mask is not None:
        text = mask(text)
    return ('%s: %s' % (type(ex).__name__, redact(text)))[:160]


class Watch(object):
    def __init__(self, folder, out=None, append=True):
        self.folder = folder
        self.log_path = os.path.join(folder, 'watch.log')
        self.started = time.time()
        self.out = out
        self.append = append                      # False for --once: print only, watch.log is the background watch's
        self.last_view, self.seen, self.ms, self.alerted = {}, {}, {}, set()
        self.flags = {}                           # per node: event key -> the dup flag it was logged with
        self.last_heartbeat = 0
        self.last_answers = None
        self.mask = None                          # mist_api.mask_token once the first poll has the module

    def answers(self):
        with open(os.path.join(self.folder, 'answers.json')) as f:
            return json.load(f)

    def log(self, line, redact):
        line = redact(line)
        if self.mask is not None:
            line = self.mask(line)
        if self.append:
            with open(self.log_path, 'a') as f:
                f.write(line + '\n')
        if self.out is not None:
            self.out.append(line)

    def events(self, M, site_id, mac, start):
        rows, path = [], '/sites/%s/devices/events/search?mac=%s&start=%d&limit=200' % (site_id, mac, start)
        for _ in range(50):
            status, out = M.mist('GET', path)
            if status != 200 or not isinstance(out, dict):
                raise RuntimeError('events: HTTP %s' % status)
            rows += out.get('results') or []
            path = out.get('next')
            if not path:
                break
        return rows

    def poll(self, M):
        now = time.time()
        self.mask = getattr(M, 'mask_token', None)
        try:
            a = self.answers()
            self.last_answers = a
        except Exception as ex:                   # answers.json mid-write or unreadable: the last good copy
            a = self.last_answers
            self.log('%s answers.json unreadable (%s); %s' % (stamp(now, None), reason(ex, M.redact, getattr(M, 'mask_token', None)),
                                                              'using the last good copy' if a else 'poll skipped'),
                     M.redact)
            if a is None:
                return
        w = a.get('watch') or {}
        t0 = w.get('t0_epoch')
        start = int(w.get('watch_start_epoch') or self.started) - 60
        site_id = a['site']['site_id']
        for n in ('1', '2'):
            nd = a['nodes'][n]
            tag = 'node %s' % n
            try:
                status, s = M.mist('GET', '/sites/%s/stats/devices/%s' % (site_id, nd['device_id']))
                view = stats_view(s) if status == 200 else {'stats_http': status}
                if view != self.last_view.get(n):
                    note = ' (before the first GW_CONNECTED: logged, not an alert)' if (
                        status != 200 and not (self.ms.get(n) or {}).get('connected')) else ''
                    self.log('%s %s stats %s%s' % (stamp(now, t0), tag, json.dumps(M.redact(view), sort_keys=True),
                                                   note), M.redact)
                    self.last_view[n] = view
            except Exception as ex:               # one bad stats answer: logged; the events are still polled
                self.log('%s %s poll failed (stats): %s' % (stamp(now, t0), tag, reason(ex, M.redact, getattr(M, 'mask_token', None))), M.redact)
            try:
                evs = self.events(M, site_id, nd['mac'], start)
                seen = self.seen.setdefault(n, set())
                flags = self.flags.setdefault(n, {})
                for e in dedup(evs):
                    k = event_key(e)
                    if k in seen:
                        if flags.get(k) != e['dup']:  # a late earlier event re-paired an event already logged
                            flags[k] = e['dup']
                            self.log('%s %s event %s at %s is now %s (an earlier event arrived late)' % (
                                stamp(now, t0), tag, e.get('type'), stamp(e.get('timestamp') or now, t0),
                                'the duplicate of a pair' if e['dup'] else 'a kept event, no longer a duplicate'),
                                M.redact)
                        continue
                    seen.add(k)
                    flags[k] = e['dup']
                    self.log('%s %s event %s%s%s' % (stamp(e.get('timestamp') or now, t0), tag, e.get('type'),
                                                     (' "%s"' % str(e.get('text'))[:200]) if e.get('text') else '',
                                                     ' (duplicate of a pair)' if e['dup'] else ''), M.redact)
                    if bad_event(e.get('type')) and ('bad', n, k) not in self.alerted:
                        self.alerted.add(('bad', n, k))
                        self.log('%s ALERT %s: event %s; no writes, no restarts; ask for show system ztp, show log '
                                 'phc.log, show dhcp client binding on its console' % (stamp(now, t0), tag,
                                                                                        e.get('type')), M.redact)
                m = milestones(evs)
                old = self.ms.get(n) or {}
                for k in MILESTONES:
                    if m[k] is not None and m[k] != old.get(k):
                        self.log('%s %s milestone %s %s%s' % (stamp(now, t0), tag, k, stamp(m[k], t0),
                                                             (' (moved from %s)' % stamp(old[k], t0)) if old.get(k)
                                                             else ''), M.redact)
                self.ms[n] = m
                for aid, text in absence_alerts(m, t0, now):
                    if (aid, n) not in self.alerted:
                        self.alerted.add((aid, n))
                        self.log('%s ALERT %s: %s; no writes, no restarts' % (stamp(now, t0), tag, text), M.redact)
            except Exception as ex:               # one bad answer or a network error: logged, the watch goes on
                self.log('%s %s poll failed (events): %s' % (stamp(now, t0), tag, reason(ex, M.redact, getattr(M, 'mask_token', None))), M.redact)
        if now - self.last_heartbeat >= HEARTBEAT_SECONDS:
            self.last_heartbeat = now
            self.log('%s heartbeat: %s' % (stamp(now, t0), '; '.join(
                'node %s %s' % (n, (self.last_view.get(n) or {}).get('status')) for n in ('1', '2'))), M.redact)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.umask(0o077)                               # watch.log and watch.pid: owner only
    folder = os.getcwd()
    sys.path.insert(0, folder)
    import mist_api as M                          # the working folder copy (it reads answers.json at import)
    out = [] if '--once' in argv else None
    w = Watch(folder, out, append=out is None)
    if out is not None:
        w.poll(M)
        print('\n'.join(out))
        return 0
    with open(os.path.join(folder, 'watch.pid'), 'w') as f:
        f.write('%d\n' % os.getpid())
    w.log('%s watch.py started, poll every %d s' % (stamp(time.time(), None), POLL_SECONDS), M.redact)
    while True:
        try:
            w.poll(M)
        except Exception as ex:                   # never ends the watch: logged, next poll in 20 s
            w.log('%s poll failed: %s' % (stamp(time.time(), None), reason(ex, M.redact, getattr(M, 'mask_token', None))), M.redact)
        time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    sys.exit(main())
