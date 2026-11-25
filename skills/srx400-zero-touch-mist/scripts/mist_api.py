#!/usr/bin/env python3
"""mist_api.py: minimal Mist REST client for the srx400-zero-touch-mist skill. Python 3 standard library only.

Copy this file into the working folder, next to answers.json, and run your scripts from that folder with
plain `python3 <script>` (the script's folder is then on sys.path). With `python3 -I`, first run
`sys.path.insert(0, '<working folder>')`, then `import mist_api`.

It reads mist.api_host and mist.token_file from answers.json. The token is read from its file inside each
call and is never printed, logged or stored anywhere else. Everything a command prints enters the agent's
context: print only what redact(), profile_summary() and write() return, or the booleans and counts of
secret_check().

Read-only command line (always GET):  python3 mist_api.py <path>
It prints only the fields this skill reads, per kind of object (cli_view()): for /self the scope, org_id, msp_id,
name and role of each privileges entry; for settings, device records, events and logs the judged fields; for an
unknown path only the key names.
"""
import http.client, json, os, re, sys, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
os.umask(0o077)                                   # every file a script of the working folder writes: owner only
with open(os.path.join(HERE, 'answers.json')) as _f:
    ANS = json.load(_f)
API = 'https://' + ANS['mist']['api_host'] + '/api/v1'
API_HOST = str(ANS['mist']['api_host'])
TOKEN_FILE = os.path.expanduser(ANS['mist']['token_file'])
LAST_HEADERS = {}
API_HOST_RE = re.compile(r'^api(\.[a-z0-9-]+)?\.mist\.com$')
PORTAL_RE = re.compile(r'^manage(\.[a-z0-9-]+)?\.mist\.com$')
TOKEN_RE = re.compile(r'^[A-Za-z0-9]{20,}$')


def api_host_problem():
    """'' when mist.api_host is a Mist API host and, with a portal host recorded, the API host of that portal;
    else why not. mist() sends nothing (no token) while this is not ''."""
    if not API_HOST_RE.match(API_HOST):
        return 'mist.api_host %s is not a Mist API host (api.mist.com or api.<cloud>.mist.com)' % (API_HOST or '(empty)')
    portal = re.sub(r'^[a-z]+://', '', str(ANS['mist'].get('portal_host') or '').strip().lower()).split('/', 1)[0]
    if PORTAL_RE.match(portal) and API_HOST != 'api.' + portal[len('manage.'):]:
        return 'mist.api_host %s is not the API host of the portal %s' % (API_HOST, portal)
    return ''


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is never followed: the Authorization header goes only to the API host itself (the 3xx answer is
    returned as it is)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _token():
    """(token, length): the token when the file holds one token line (letters and digits), else None."""
    with open(TOKEN_FILE) as f:
        t = f.read().strip()
    return (t if TOKEN_RE.match(t) else None), len(t)


def mask_token(text):
    """text with the API token (if the token file can be read) and any 'Token <value>' masked."""
    text = str(text)
    try:
        t, _ = _token()
        if t:
            text = text.replace(t, '<TOKEN>')
    except (OSError, UnicodeDecodeError):
        pass
    return re.sub(r'(?i)(token )[A-Za-z0-9]{8,}', r'\1<TOKEN>', text)


def mist(method, path, body=None):
    """One API call. path is relative to /api/v1; a path that starts with /api/v1 (a 'next' link) has that prefix
    removed. Returns (http_status, parsed JSON, or the text when the body is not JSON). An HTTP error body is parsed
    too when it is JSON. An empty body gives {}. No connection, a timeout or a dropped connection gives (0, reason);
    after a write, status 0 means the write may have landed: read back before any retry. Nothing is sent, (0,
    reason), when mist.api_host is not the Mist API host of the portal or the token file does not hold one token line.
    A redirect is not followed. The response headers are kept in LAST_HEADERS (see page_total())."""
    global LAST_HEADERS
    LAST_HEADERS = {}
    if path.startswith('/api/v1/'):
        path = path[len('/api/v1'):]
    why = api_host_problem()
    if why:
        return 0, why + '; nothing was sent'
    try:
        token, n = _token()
    except (OSError, UnicodeDecodeError) as e:
        return 0, 'token file %s cannot be read (%s); nothing was sent' % (ANS['mist']['token_file'], type(e).__name__)
    if token is None:
        return 0, ('token file %s does not hold one token line of letters and digits (%d characters); nothing was '
                   'sent' % (ANS['mist']['token_file'], n))
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        'Authorization': 'Token ' + token, 'Content-Type': 'application/json'})
    try:
        try:
            with _OPENER.open(req, timeout=30) as r:
                LAST_HEADERS = {k.lower(): v for k, v in r.headers.items()}
                return r.status, _parse(r.read())
        except urllib.error.HTTPError as e:
            LAST_HEADERS = {k.lower(): v for k, v in e.headers.items()} if e.headers else {}
            return e.code, _parse(e.read())
    except urllib.error.URLError as e:
        LAST_HEADERS = {}
        return 0, mask_token(e.reason)
    except (OSError, http.client.HTTPException, ValueError, UnicodeError) as e:   # timeout, reset, a bad header
        LAST_HEADERS = {}
        return 0, mask_token('%s: %s' % (type(e).__name__, e))


def _parse(raw):
    """Response bytes to parsed JSON; {} for an empty body; the text when it is not JSON."""
    text = raw.decode(errors='replace')
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except ValueError:
        return text


def page_total():
    """X-Page-Total of the last call as an int, or None when Mist did not send it (Mist sends it only
    when the request carries `limit`). Read every list with list_all(), which pages until the rows read
    equal X-Page-Total."""
    v = LAST_HEADERS.get('x-page-total')
    return int(v) if v and v.isdigit() else None


def list_all(path, limit=1000):
    """Every row of a list read: GET path with limit=1000 and page=1, then page=2, 3, ... with the same limit
    until the unique ids read equal X-Page-Total. path is the list path with its filters (type=gateway), without
    limit and page. Returns (http_status, rows, total, complete): complete False when Mist sent no X-Page-Total,
    a page did not answer 200 with a list, or a page brought no new row before the total was reached; then the
    list is incomplete: stop and tell the user."""
    base, _, qs = path.partition('?')
    q = [(k, v) for k, v in urllib.parse.parse_qsl(qs, keep_blank_values=True) if k not in ('limit', 'page')]
    rows, seen, total, page = [], set(), None, 1
    while page <= 1000:
        status, out = mist('GET', base + '?' + urllib.parse.urlencode(q + [('limit', limit), ('page', page)]))
        if status != 200 or not isinstance(out, list):
            return status, rows, total, False
        total = page_total()
        if total is None:
            return status, rows + [r for r in out], None, False
        new = 0
        for r in out:
            k = r.get('id') if isinstance(r, dict) and r.get('id') is not None else json.dumps(r, sort_keys=True)
            if k not in seen:
                seen.add(k)
                rows.append(r)
                new += 1
        if len(seen) >= total:
            return status, rows, total, True
        if new == 0:
            return status, rows, total, False
        page += 1
    return 200, rows, total, False


def find_by_name(path, name):
    """(complete, rows of the list whose name equals name, ignoring case): the name-clash check right before a
    create (SKILL.md step 4). complete False: the list read is incomplete, so stop."""
    status, rows, total, complete = list_all(path)
    hits = [r for r in rows if isinstance(r, dict) and str(r.get('name', '')).lower() == str(name).lower()]
    return complete, hits


SECRET_KEY = re.compile(r'(?i)(psk|secret|password|passwd|passphrase|pass|pw|auth_key|community|community_name|comm|'
                        r'token|key|keys|hash)$')
SUMMARY_KEYS = ('config_diff', 'commit_log', 'before', 'after')   # event diffs and audit copies: length only
PLACEHOLDER_VALUE = re.compile(r'^<[A-Z][A-Z0-9-]*>$')
# (keyword, kind): the value after each keyword is masked; kind names the placeholder (root, sshkey, license, icl)
# or <SECRET>. A keyword starts at a word boundary; a value that is already a placeholder stays.
SECRET_RULES = [
    (re.compile(r'encrypted-password '), '<ROOT-PASSWORD-HASH>'),
    (re.compile(r'root-authentication (ssh-(?:rsa|ed25519|ecdsa|dsa)) '), 'sshkey'),
    (re.compile(r'license keys key '), '<LICENSE-KEY>'),
    (re.compile(r'ike policy MNHA-ICL-IKE-POL pre-shared-key (?:ascii-text|hexadecimal) '), '<ICL-PSK>'),
    (re.compile(r'(?<!\w)pre-shared-key (?:ascii-text|hexadecimal) '), '<SECRET>'),
    (re.compile(r'(?<!\w)authentication-key \S+ (?:type \S+ )?value '), '<SECRET>'),
    (re.compile(r'(?<!\w)authentication-key '), '<SECRET>'),
    (re.compile(r'(?<!\w)(?:plain-text-password-value|authentication-password|privacy-password|password) '), '<SECRET>'),
    (re.compile(r'(?<!\w)secret '), '<SECRET>'),
    (re.compile(r'(?<!\w)md5 \d+ key '), '<SECRET>'),
    (re.compile(r'(?<!\w)key (?=\\?")'), '<SECRET>'),
    (re.compile(r'(?<![\w-])ssh-(?:rsa|ed25519|ecdsa|dsa) (?=\\?")'), '<SECRET>'),
    (re.compile(r'(?<!\w)community (?![{\[])'), '<SECRET>'),
]
_IN = r'(?:[^"\\]|\\/)*'   # quoted content; a quote may be JSON-escaped (\"), a slash may be (\/)
ENCRYPTED_RX = [(re.compile(r'(\\?")\$' + _IN + r'(\\?")'), r'\1<ENCRYPTED>\2'),             # a quoted $...$ string
                (re.compile(r'(?<![\w$"\\<])\$[0-9a-z]{1,2}\$[^\s"\\,\]\}]*'), '<ENCRYPTED>')]   # an unquoted one


def _skip_json_char(s, j):
    """Index after one decoded character of JSON-escaped text at s[j]."""
    if s[j] == '\\' and j + 1 < len(s):
        return j + 6 if s[j + 1] == 'u' else j + 2
    return j + 1


def _value_span(s, i):
    """(end, quote) of the value that starts at s[i]: a quoted value, plain "..." or JSON-escaped \"...\" (escapes
    inside honored; an unterminated quote runs to the end of the text), else the next run of characters without
    space, quote, backslash, comma or bracket."""
    n = len(s)
    if s.startswith('\\"', i):                    # JSON-escaped text
        j = i + 2
        while j < n:
            if s.startswith('\\"', j):
                return j + 2, '\\"'
            if s.startswith('\\\\', j):          # a Junos backslash: it escapes the next character
                j = _skip_json_char(s, j + 2) if j + 2 < n else n
                continue
            if s[j] == '"':                       # the JSON string itself ends here
                return j, '\\"'
            j = _skip_json_char(s, j)
        return n, '\\"'
    if s.startswith('"', i):
        j = i + 1
        while j < n:
            if s[j] == '\\':
                j += 2
                continue
            if s[j] == '"':
                return j + 1, '"'
            j += 1
        return n, '"'
    m = re.compile(r'[^\s"\\,\]\}]+').match(s, i)
    return (m.end() if m else i), ''


def _redact_text(s):
    for rx, kind in SECRET_RULES:
        pos = 0
        while True:
            m = rx.search(s, pos)
            if not m:
                break
            end, q = _value_span(s, m.end())
            inner = s[m.end() + len(q):end - len(q) if (q and s[end - len(q):end] == q and end - len(q) > m.end())
                      else end]
            if end == m.end() or PLACEHOLDER_VALUE.match(inner):
                pos = max(end, m.end())
                continue
            if kind == 'sshkey':
                head = s[:m.start(1)] + '<ROOT-SSH-KEY-TYPE>' + s[m.end(1):m.end()]
                rep = (q or '"') + '<ROOT-SSH-KEY>' + (q or '"')
                s = head + rep + s[end:]
                pos = len(head) + len(rep)
                continue
            rep = (q + kind + q) if q else kind
            s = s[:m.end()] + rep + s[end:]
            pos = m.end() + len(rep)
    for rx, rep in ENCRYPTED_RX:
        s = rx.sub(rep, s)
    return s


def redact(o, _secret=False):
    """Copy of o that is safe to show or save: no claim codes, hashes, keys, PSKs, passwords or communities. The
    root password, root SSH key, license and HA link key (MNHA-ICL-IKE-POL) lines come back as the exact
    placeholder lines of the plan profiles. The text rules also match JSON-escaped quotes (raw error text) and run
    on dict keys too. magic (the claim code) is dropped; config_diff, commit_log, before and after (event diffs,
    audit copies) become their length. Under a key whose name ends in a secret word (SECRET_KEY) every scalar, every
    scalar of a list and a direct 'value' child become <SECRET>."""
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k == 'magic':
                continue
            rk = _redact_text(k) if isinstance(k, str) else k
            if k in SUMMARY_KEYS and v not in (None, '', [], {}):
                out[rk] = '<%d characters, not shown>' % len(v if isinstance(v, str) else json.dumps(v))
            elif isinstance(k, str) and SECRET_KEY.search(k) and not isinstance(v, (dict, bool)) and v not in ('', None):
                out[rk] = ['<SECRET>' if isinstance(x, (str, int, float)) and not isinstance(x, bool) and x != ''
                           else redact(x) for x in v] if isinstance(v, list) else '<SECRET>'
            elif _secret and k == 'value' and isinstance(v, (str, int, float)) and not isinstance(v, bool) and v != '':
                out[rk] = '<SECRET>'
            else:
                out[rk] = redact(v, isinstance(k, str) and bool(SECRET_KEY.search(k)) and isinstance(v, dict))
        return out
    if isinstance(o, list):
        return [redact(v) for v in o]
    if isinstance(o, str):
        return _redact_text(o)
    return o


def profile_summary(p):
    """The only fields of a device profile that may be printed or saved outside the plan and read-back
    checks: id, name, type, modified_time, and per port_config entry its name, usage and vpn_paths keys."""
    ports = {port: {'name': c.get('name'), 'usage': c.get('usage'),
                    'vpn_paths': sorted((c.get('vpn_paths') or {}).keys())}
             for port, c in (p.get('port_config') or {}).items()}
    return {'id': p.get('id'), 'name': p.get('name'), 'type': p.get('type'),
            'modified_time': p.get('modified_time'), 'ports': ports}


def mask_values(text, secrets):
    """Replace every occurrence of each secret value in text, raw and JSON-escaped."""
    for s in secrets or ():
        if not s:
            continue
        esc = json.dumps(s)[1:-1]
        for form in {s, esc, esc.replace('/', '\\/')}:
            text = text.replace(form, '<SECRET>')
    return text


def safe_error(out, secrets=()):
    """Error body (parsed JSON or text) as safe text: every value in `secrets` masked (raw and
    JSON-escaped), then redact() on the decoded JSON (or on the text), cut to 500 characters."""
    text = mask_values(out if isinstance(out, str) else json.dumps(out), secrets)
    try:
        text = json.dumps(redact(json.loads(text)))
    except ValueError:
        text = redact(text)
    return text[:500]


PROFILE_WRITE = re.compile(r'/orgs/[^/]+/deviceprofiles(/[^/]+)?')


def write(method, path, body, secrets=()):
    """One write the user has just approved. Prints only the HTTP status, the id and name of the stored
    object (or the assign result), never the object: a stored Hub Profile holds the root hash and the
    license key. On an error (status 0 = no answer: the write may have landed, read back before any
    retry) it prints safe_error(); a profile create or
    update without `secrets` prints only the error length. A 2xx body that is not JSON prints only its
    length. Returns (http_status, raw response); keep the raw response in memory only."""
    status, out = mist(method, path, body)
    summary = {'status': status}
    if 200 <= status < 300:
        if isinstance(out, dict):
            summary.update({k: out[k] for k in ('id', 'name', 'success') if k in out})
        elif isinstance(out, str):
            summary['text_length'] = len(out)
    elif PROFILE_WRITE.fullmatch(path.split('?')[0]) and not secrets:
        summary['error_length'] = len(out if isinstance(out, str) else json.dumps(out))
    else:
        summary['error'] = safe_error(out, secrets)
    print(json.dumps(summary))
    return status, out


PLACEHOLDER_RX = re.compile(r'<(?!\*_to_\*>)[^<>\s]+>')   # any <...> except the Junos wildcard <*_to_*>
ROOT_LINE = re.compile(r'^set system root-authentication encrypted-password "([^"]*)"$')
LICENSE_LINE = re.compile(r'^set system license keys key "([^"]*)"$')


def read_secret(path, kind):
    """Read one secret file ('root' or 'license'), stripped. Raises ValueError, without the value,
    when group or others can read the file (chmod 600) or when the content cannot go inside a quoted
    Additional CLI line. Prints nothing."""
    p = os.path.expanduser(path)
    if os.stat(p).st_mode & 0o077:
        raise ValueError('%s file %s: readable by group or others; run chmod 600 on it, then confirm' % (kind, path))
    with open(p) as f:
        v = f.read().strip()
    if kind == 'root':
        ok = v.startswith('$') and not re.search(r'[\s"]', v)
    else:
        ok = bool(v) and not re.search(r'[\r\n"]', v)
    if not ok:
        raise ValueError('%s file %s: not usable (%d characters)' % (kind, path, len(v)))
    return v


def fill(plan_profile, root_hash, license_key=None):
    """In-memory copy of a redacted plan profile with this node's secrets in place. Raises ValueError,
    with the placeholder names only, when any <...> other than <*_to_*> is left."""
    p = json.loads(json.dumps(plan_profile))
    known = {'<ROOT-PASSWORD-HASH>'} | ({'<LICENSE-KEY>'} if license_key else set())
    left = sorted(set(PLACEHOLDER_RX.findall(json.dumps(p))) - known)   # checked before the fill: names only
    if left:
        raise ValueError('placeholders left: %s' % left)
    cmds = []
    for line in p['additional_config_cmds']:
        line = line.replace('<ROOT-PASSWORD-HASH>', root_hash)
        if license_key:
            line = line.replace('<LICENSE-KEY>', license_key)
        cmds.append(line)
    p['additional_config_cmds'] = cmds
    return p


def secret_check(profile, root_hash, license_key=None):
    """Checks a filled body or a raw read-back against this node's secret values. Returns booleans and
    counts only (safe to print). placeholders_left counts every <...> other than <*_to_*>. Pass =
    placeholders_left 0, root_lines 1, root_equal True (a non-empty hash that starts with $), license_lines
    1 with license_equal True for a node with a key, license_lines 0 for a node without."""
    cmds = profile.get('additional_config_cmds', [])
    roots, lics = [], []
    for line in cmds:
        m = ROOT_LINE.match(line)
        if m:
            roots.append(m.group(1))
        m = LICENSE_LINE.match(line)
        if m:
            lics.append(m.group(1))
    text = json.dumps(profile)
    return {
        'placeholders_left': len(PLACEHOLDER_RX.findall(text)),
        'root_lines': len(roots),
        'root_equal': (len(roots) == 1 and bool(root_hash) and root_hash.startswith('$')
                       and roots[0] == root_hash),
        'license_lines': len(lics),
        'license_equal': (len(lics) == 1 and lics[0] == license_key) if license_key else len(lics) == 0,
    }


def secret_check_pass(result, has_license):
    """result is what secret_check() returned: secret_check_pass(secret_check(body, root, key), bool(key))."""
    return (result['placeholders_left'] == 0 and result['root_lines'] == 1 and result['root_equal']
            and result['license_lines'] == (1 if has_license else 0) and result['license_equal'])


def self_privileges(out):
    """The only part of GET /self printed: per privileges entry its scope, org_id, msp_id, name and role (an msp
    entry's msp_id is the {msp_id} of GET /msps/{msp_id}/orgs, SKILL.md step 2.2)."""
    rows = []
    for e in (out.get('privileges') or []) if isinstance(out, dict) else []:
        if isinstance(e, dict):
            r = {k: e.get(k) for k in ('scope', 'org_id', 'msp_id', 'name', 'role')}
            for k in ('orggroup_ids', 'site_id', 'sitegroup_ids'):
                if e.get(k):
                    r[k] = e[k]
            rows.append(r)
    return rows


DEVICE_RECORD_KEYS = {'name', 'mac', 'serial', 'notes', 'model', 'type', 'hw_rev', 'map_id', 'tag_id', 'tag_uuid',
                      'evpn_scope', 'evpntopo_id', 'st_ip_base', 'adopted', 'bundled_mac', 'managed',
                      'mist_configured', 'disable_auto_config', 'deviceprofile_id', 'site_id', 'org_id', 'id',
                      'created_time', 'modified_time', 'x', 'y', 'height', 'orientation', 'locked', 'image1_url',
                      'image2_url', 'image3_url'}   # the same set as build_plan.DEVICE_RECORD_KEYS


def _empty(v):
    return v is None or v == '' or v == [] or v == {}


def event_rows(events):
    """The only fields of device events printed or reported: type, timestamp, mac and a short redacted text."""
    return [{'type': e.get('type'), 'timestamp': e.get('timestamp'), 'mac': e.get('mac'),
             'text': (redact(str(e['text']))[:200] if e.get('text') else None)}
            for e in events or [] if isinstance(e, dict)]


def log_rows(logs):
    """The only fields of org audit log entries printed or reported: timestamp, site_id, a short redacted message."""
    return [{'timestamp': e.get('timestamp'), 'site_id': e.get('site_id'),
             'message': redact(str(e.get('message') or ''))[:200]} for e in logs or [] if isinstance(e, dict)]


def device_summary(rec):
    """A device record: identity, the two management flags and the names of the device-level settings it carries
    (keys outside DEVICE_RECORD_KEYS that hold a value; never their values)."""
    out = {k: rec.get(k) for k in ('id', 'name', 'mac', 'serial', 'model', 'site_id', 'deviceprofile_id',
                                   'disable_auto_config', 'mist_configured')}
    out['device_level_keys'] = sorted(k for k, v in rec.items() if k not in DEVICE_RECORD_KEYS and not _empty(v))
    return out


def setting_summary(st):
    """An org or site setting: only what SKILL.md step 2.4 judges (juniper_srx.auto_upgrade, config_push_policy,
    gateway_mgmt config_revert_timer, protect_re, root_password set or not, disable_oob) and the top-level key names."""
    au = (st.get('juniper_srx') or {}).get('auto_upgrade') or {}
    cp = st.get('config_push_policy') or {}
    gm = st.get('gateway_mgmt') or {}
    return {'keys': sorted(st),
            'juniper_srx.auto_upgrade': {'enabled': au.get('enabled'), 'version': au.get('version'),
                                         'custom_versions.SRX400': (au.get('custom_versions') or {}).get('SRX400')}
            if au else None,
            'config_push_policy': {'no_push': cp.get('no_push'),
                                   'push_window.enabled': (cp.get('push_window') or {}).get('enabled')} if cp else None,
            'gateway_mgmt': {'config_revert_timer': gm.get('config_revert_timer'),
                             'protect_re.enabled': (gm.get('protect_re') or {}).get('enabled'),
                             'root_password': 'set' if gm.get('root_password') else None,
                             'disable_oob': gm.get('disable_oob')} if gm else None}


def write_private(path, data):
    """Write data (a str, or an object written as JSON) to a new file that only the owner can read (mode 600, created
    with that mode; an existing file is refused). The Mist UI path's filled files go through it (SKILL.md step 4)."""
    fd = os.open(os.path.expanduser(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(data if isinstance(data, str) else json.dumps(data, indent=2) + '\n')


def cli_view(path, out):
    """What `python3 mist_api.py <path>` prints for a 200 answer: per kind of object only the fields this skill reads;
    anything else only its key names."""
    base = path.split('?')[0].rstrip('/')
    seg = [x for x in base.split('/') if x]
    rows = out if isinstance(out, list) else None
    one = lambda f: [f(x) for x in rows if isinstance(x, dict)] if rows is not None else f(out)
    if base == '/self':
        privs = self_privileges(out)
        return 'privileges=%d\n%s' % (len(privs), json.dumps(privs, indent=1))
    if '/config_cmd' in base:
        return json.dumps({'cli_lines': len(out.get('cli', [])), '_errors': redact(out.get('_errors'))})
    if '/deviceprofiles' in base:
        return json.dumps([profile_summary(p) for p in (rows if rows is not None else [out])], indent=1)
    if seg[-1:] == ['setting']:
        return json.dumps(setting_summary(out), indent=1)
    if seg[-2:] == ['events', 'search']:
        return json.dumps({'total': out.get('total'), 'next': bool(out.get('next')),
                           'results': event_rows(out.get('results'))}, indent=1)
    if seg[-1:] == ['logs']:
        return json.dumps({'total': out.get('total'), 'next': bool(out.get('next')),
                           'results': log_rows(out.get('results'))}, indent=1)
    if seg[-1:] == ['inventory']:
        return json.dumps(one(lambda r: {k: r.get(k) for k in ('serial', 'mac', 'id', 'site_id', 'model', 'name',
                                                                 'type', 'connected', 'deviceprofile_id')}), indent=1)
    if len(seg) == 4 and seg[0] == 'sites' and seg[2] == 'devices':
        return json.dumps(device_summary(out), indent=1)
    if seg[:1] == ['sites'] and 'stats' in seg:
        return json.dumps(one(lambda r: dict({k: r.get(k) for k in ('id', 'status', 'config_status', 'config_version',
                                                                     'version', 'uptime', 'ip', 'deviceprofile_name')},
                                             if_stat={i: {'up': (x or {}).get('up'), 'ips': (x or {}).get('ips')}
                                                      for i, x in (r.get('if_stat') or {}).items()
                                                      if isinstance(x, dict)})), indent=1)
    if 'gatewaytemplates' in seg and len(seg) == 4:
        return json.dumps({'name': out.get('name'), 'port_config': sorted(out.get('port_config') or {}),
                           'ip_configs': sorted(out.get('ip_configs') or {})}, indent=1)
    if len(seg) == 2 and seg[0] == 'sites':
        return json.dumps({k: out.get(k) for k in ('id', 'name', 'timezone', 'gatewaytemplate_id')}, indent=1)
    if len(seg) == 2 and seg[0] == 'orgs':
        return json.dumps({k: out.get(k) for k in ('id', 'name', 'msp_id', 'orggroup_ids')}, indent=1)
    if seg[-1:] in (['networks'], ['services'], ['vpns']) or seg[:1] == ['msps']:
        if seg[:1] == ['msps'] and rows is not None:
            return json.dumps([{k: r.get(k) for k in ('id', 'name', 'msp_id', 'orggroup_ids')} for r in rows
                               if isinstance(r, dict)], indent=1)
        return json.dumps(redact(out), indent=1)
    if rows is not None:
        return json.dumps({'rows': len(rows), 'keys': sorted({k for r in rows if isinstance(r, dict) for k in r})})
    return json.dumps({'keys': sorted(out) if isinstance(out, dict) else type(out).__name__})


if __name__ == '__main__':
    path = sys.argv[1]
    status, out = mist('GET', path)
    if status == 200 and isinstance(out, list):  # a list read: every page (list_all)
        status, out, total, complete = list_all(path)
        print(status, 'x-page-total=%s rows=%d complete=%s' % (total, len(out), complete))
    else:
        print(status, 'x-page-total=%s' % page_total())
    if not 200 <= status < 300 or isinstance(out, str):
        print(safe_error(out))
    else:
        print(cli_view(path, out))
