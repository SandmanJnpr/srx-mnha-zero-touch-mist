#!/usr/bin/env python3
"""mist_api.py: minimal Mist REST client for the srx400-zero-touch-mist skill. Python 3 standard library only.

Copy this file into the working folder, next to answers.json, and run your scripts from that folder with
plain `python3 <script>` (the script's folder is then on sys.path). With `python3 -I`, first run
`sys.path.insert(0, '<working folder>')`, then `import mist_api`.

It reads mist.api_host and mist.token_file from answers.json. The token is read from its file inside each
call and is never printed, logged or stored anywhere else. Everything a command prints enters the agent's
context: print only what redact(), profile_summary() and write() return, or the booleans and counts of
secret_check().

Read-only command line (always GET, output redacted):  python3 mist_api.py /self
(for /self it prints only scope, org_id, name and role of each privileges entry, and their count).
"""
import http.client, json, os, re, sys, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ANS = json.load(open(os.path.join(HERE, 'answers.json')))
API = 'https://' + ANS['mist']['api_host'] + '/api/v1'
TOKEN_FILE = os.path.expanduser(ANS['mist']['token_file'])
LAST_HEADERS = {}


def mist(method, path, body=None):
    """One API call. path is relative to /api/v1; a path that starts with /api/v1 (a 'next' link)
    has that prefix removed. Returns (http_status, parsed JSON, or the text when the body is not JSON).
    An HTTP error body is parsed too when it is JSON. An empty body gives {}. No connection, a timeout
    or a dropped connection gives (0, reason); after a write, status 0 means the write may have landed:
    read back before any retry. The response headers are kept in LAST_HEADERS (see page_total())."""
    global LAST_HEADERS
    if path.startswith('/api/v1/'):
        path = path[len('/api/v1'):]
    token = open(TOKEN_FILE).read().strip()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        'Authorization': 'Token ' + token, 'Content-Type': 'application/json'})
    try:
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                LAST_HEADERS = {k.lower(): v for k, v in r.headers.items()}
                return r.status, _parse(r.read())
        except urllib.error.HTTPError as e:
            LAST_HEADERS = {k.lower(): v for k, v in e.headers.items()} if e.headers else {}
            return e.code, _parse(e.read())
    except urllib.error.URLError as e:
        LAST_HEADERS = {}
        return 0, str(e.reason)
    except (OSError, http.client.HTTPException) as e:   # read timeout, connection reset or dropped
        LAST_HEADERS = {}
        return 0, '%s: %s' % (type(e).__name__, e)


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
    when the request carries `limit`). A list read whose page_total() is None, or larger than the rows
    it returned, is incomplete: stop and tell the user."""
    v = LAST_HEADERS.get('x-page-total')
    return int(v) if v and v.isdigit() else None


SECRET_KEY = re.compile(r'(?i)(psk|secret|password|passphrase|auth_key|community|community_name|token|key)$')
_IN = r'(?:[^"\\]|\\/)*'   # quoted content; a quote may be JSON-escaped (\"), a slash may be (\/)
SECRET_RX = [
    (re.compile(r'(encrypted-password \\?")' + _IN + r'(\\?")'), r'\1<ROOT-PASSWORD-HASH>\2'),
    (re.compile(r'(license keys key \\?")' + _IN + r'(\\?")'), r'\1<LICENSE-KEY>\2'),
    (re.compile(r'(\\?")\$' + _IN + r'(\\?")'), r'\1<ENCRYPTED>\2'),
    (re.compile(r'(pre-shared-key (?:ascii-text|hexadecimal) )("[^"]*"|\S+)'), r'\1"<SECRET>"'),
    (re.compile(r'(authentication-key )("[^"]*"|\S+)'), r'\1"<SECRET>"'),
    (re.compile(r'(\bsecret )("[^"]*"|\S+)'), r'\1"<SECRET>"'),
    (re.compile(r'(\bsnmp (?:.* )?community )("[^"]*"|\S+)'), r'\1"<SECRET>"'),
]


def redact(o):
    """Copy of o that is safe to show or save: no claim codes, hashes, keys, PSKs or communities. The
    root password and license lines come back as the exact placeholder lines of the repository files.
    The string rules also match JSON-escaped quotes (raw error text)."""
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k == 'magic':
                continue
            if SECRET_KEY.search(k) and isinstance(v, (str, int, float)) and not isinstance(v, bool) and v != '':
                out[k] = '<SECRET>'
            else:
                out[k] = redact(v)
        return out
    if isinstance(o, list):
        return [redact(v) for v in o]
    if isinstance(o, str):
        for rx, rep in SECRET_RX:
            o = rx.sub(rep, o)
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
    when the content cannot go inside a quoted Additional CLI line. Prints nothing."""
    v = open(os.path.expanduser(path)).read().strip()
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
    cmds = []
    for line in p['additional_config_cmds']:
        line = line.replace('<ROOT-PASSWORD-HASH>', root_hash)
        if license_key:
            line = line.replace('<LICENSE-KEY>', license_key)
        cmds.append(line)
    p['additional_config_cmds'] = cmds
    left = sorted(set(PLACEHOLDER_RX.findall(json.dumps(p))))
    if left:
        raise ValueError('placeholders left: %s' % left)
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


if __name__ == '__main__':
    path = sys.argv[1]
    status, out = mist('GET', path)
    print(status, 'x-page-total=%s' % page_total())
    base = path.split('?')[0]
    if not 200 <= status < 300 or isinstance(out, str):
        print(safe_error(out))
    elif base.rstrip('/') == '/self':
        privs = [{k: e.get(k) for k in ('scope', 'org_id', 'name', 'role')} for e in out.get('privileges', [])]
        print('privileges=%d' % len(privs))
        print(json.dumps(privs, indent=1))
    elif '/config_cmd' in base:
        print(json.dumps({'cli_lines': len(out.get('cli', [])), '_errors': redact(out.get('_errors'))}))
    elif '/deviceprofiles' in base:
        rows = out if isinstance(out, list) else [out]
        print(json.dumps([profile_summary(p) for p in rows], indent=1))
    else:
        if isinstance(out, list):
            print('rows=%d' % len(out))
        print(json.dumps(redact(out), indent=1))
