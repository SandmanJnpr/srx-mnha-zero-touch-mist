#!/usr/bin/env python3
"""build_plan.py: answers.json (schema v2) -> the Mist org objects, one Hub Profile per SRX400 node, and the
topology and plan the agent shows to the customer before any write. Python 3.9+, standard library only.

Command line:
  python3 build_plan.py --answers answers.json --out <folder>   validate, then write the plan folder
  python3 build_plan.py --answers answers.json --check          validate only (nothing is written)
  add --json to print the problems as JSON

Exit status: 0 = valid (and the folder is written); 1 = answers to ask again, or org/site preconditions;
2 = a stop: the design cannot be built as answered (the message says what the customer can do instead).

The plan folder holds:
  org-objects.json                the org networks and the application, in create order (paths relative to /api/v1)
  node1-profile.json, node2-profile.json
                                  the two Hub Profiles; secrets stay as placeholders (<ROOT-PASSWORD-HASH>,
                                  <LICENSE-KEY>, and when used <ROOT-SSH-KEY-TYPE>, <ROOT-SSH-KEY>, <ICL-PSK>);
                                  fill them in memory at the write only (mist_api.fill() or fill_secrets() here)
  topology.txt                    ASCII diagram of the pair, the ISPs, the LAN switch and the hub
  topology.md                     the same as a Mermaid flowchart, plus the network and steering tables
  plan.md                         every value of the plan: networks, VLANs, subnets, VIPs, node addresses, DHCP,
                                  preferred ISP, IPv6, overlay, ports, internal addressing, AS numbers, constants

As a module:
  import build_plan as B
  problems = B.validate(answers)          # [] when valid; each problem is {q, kind, msg}
  plan = B.build(answers)                 # {'org_objects', 'profiles': {'1', '2'}, 'derived'}
  B.write_plan(answers, out_dir)          # validate + build + write the folder; returns (problems, plan)

Every Additional CLI line comes from templates/hub-profile.template.json: the lines of the two reference profiles
(../../mist/srx400-node{1,2}-zero-touch.json) with their values replaced by tokens, plus the entries that extend the
design for other answers (preemption, HA link encryption, extra steering excepts, root SSH key, the no-hub forms).
This script fills the tokens, repeats per item and keeps or drops whole entries.
No secret is read here: the answers file holds only paths, and the plan shows them as "file given" / "none".
"""
import copy
import ipaddress as ip
import itertools
import json
import os
import re
import sys
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
TEMPLATE_PATH = os.path.join(SKILL, 'templates', 'hub-profile.template.json')
SCHEMA = 'srx400-zero-touch-mist.answers.v2'

# ------------------------------------------------------------------ constants
NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]*[A-Za-z0-9]$')       # Mist name rule, <= 32
TENANT_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_-]*[A-Za-z0-9]$')         # + starts with a letter, 2..24
RESERVED = {'icd', 'ha', 'wan', 'lan', 'xnode', 'junos-host', 'trust', 'untrust', 'any', 'all',
            'hub-site-nets', 'mgmt_junos', 'master', 'default', 'internet', 'to-icd', 'icd-internet',
            'allow-to-hub', 'mnha-node-local', 'apbr', 'top'}
SFP = ['ge-0/0/0', 'ge-0/0/1']                                         # 1G SFP cages
COPPER = ['ge-0/0/%d' % i for i in range(2, 10)]
ALL_PORTS = SFP + COPPER
FACTORY_SERVER = 'ge-0/0/3'                                            # factory DHCP server 192.168.2.1/24
PORT_RE = re.compile(r'^ge-0/0/[0-9]$')
RFC1918 = [ip.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
FACTORY_GE3 = ip.ip_network('192.168.2.0/24')
MIST_RESERVED = ip.ip_network('100.64.0.0/10')                         # Mist overlay tunnel and loopback space
SPECIAL4 = [ip.ip_network(n) for n in ('0.0.0.0/8', '127.0.0.0/8', '169.254.0.0/16', '224.0.0.0/4',
                                        '240.0.0.0/4', '192.0.0.0/24', '192.0.2.0/24', '198.51.100.0/24',
                                        '203.0.113.0/24', '198.18.0.0/15')]
DOC6 = [ip.ip_network(n) for n in ('2001:db8::/32', '3fff::/20')]       # RFC 3849, RFC 9637
GUA6 = ip.ip_network('2000::/3')
HOST_RE = re.compile(r'^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)'
                     r'(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$')
LABEL_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$')  # one host label (DHCP reservation name)
HASH_RE = re.compile(r'^\$(1|5|6)\$[^\s"$<>]{1,16}\$[^\s"<>]{8,}$')
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')   # Mist org, site ids
MAC_RE = re.compile(r'^[0-9a-f]{12}$')                                 # Mist MAC: 12 lowercase hex digits
DOC_MAC_RE = re.compile(r'^00005e0053[0-9a-f]{2}$')                     # RFC 7042 documentation MACs
EXAMPLE_RX = re.compile(r'<[^<>]*>')                                   # example text of answers.example.json
SECRET_WORD_NAMES = {'secret', 'password', 'authentication-key', 'encrypted-password', 'plain-text-password-value',
                     'authentication-password', 'privacy-password'}    # zone names redact() would read as a secret
DEVICE_RECORD_KEYS = {'name', 'mac', 'serial', 'notes', 'model', 'type', 'hw_rev', 'map_id', 'tag_id', 'tag_uuid',
                      'evpn_scope', 'evpntopo_id', 'st_ip_base', 'adopted', 'bundled_mac', 'managed',
                      'mist_configured', 'disable_auto_config', 'deviceprofile_id', 'site_id', 'org_id', 'id',
                      'created_time', 'modified_time', 'x', 'y', 'height', 'orientation', 'locked', 'image1_url',
                      'image2_url', 'image3_url'}                       # identity and placement keys of a device record
SSHKEY_RE = re.compile(r'^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/=]{40,}( [^"\n]*)?$')
MAX_TENANTS = 32       # one SRG1 virtual IP per network; this design builds at most 32 per SRG (no grid-id)
MAX_HUB_PATHS = 4
DHCP_OPTION_TYPES = {'boolean', 'int16', 'int32', 'ip', 'string', 'uint16', 'uint32', 'hex'}
DHCP_OPTION_RESERVED = {1, 3, 6, 12, 15, 50, 51, 52, 53, 54, 55, 61, 82}   # set by the design or by the protocol
SSH_KEY_STATEMENT = {'ssh-ed25519': 'ssh-ed25519', 'ssh-rsa': 'ssh-rsa', 'ecdsa-sha2-nistp256': 'ssh-ecdsa',
                     'ecdsa-sha2-nistp384': 'ssh-ecdsa', 'ecdsa-sha2-nistp521': 'ssh-ecdsa'}   # key type -> Junos keyword
LEASE_MAX_SECONDS = 780   # W4: a held ISP lease of at most 13 minutes keeps node 1's push confirm about 1.5 min
                          # inside the 10-minute commit confirm window (derived from the push timeline measured with a
                          # 10-minute lease, SKILL.md step 6; 11 to 13 minutes: beyond the reference design)
LEASE_PROVEN_SECONDS = 600   # the held lease the reference pair ran
SECURITY_SERVICE_NAMES = {'idp': 'IDP', 'appid': 'AppID', 'secintel': 'SecIntel', 'geoip': 'GeoIP',
                          'url-filtering': 'URL filtering'}
RELEASE_BASE = '25.4X300-D30.3'   # the release the reference design is proven on (B4)
RELEASE_RE = re.compile(r'^25\.4X300-D(\d+)(\.\d+)?$')
FACTORY_GE3_TEXT = '192.168.2.0/24'
IPV6_SOURCES = ('none', 'isp1', 'isp2', 'both')
ACCESS_BUILD = ('org-admin', 'msp-admin')
ACCESS_STOP = ('write', 'read', 'helpdesk', 'installer', 'observer', 'org-write', 'org-read')
HA_MODE = 'mnha-hybrid'
WAN_NAME = 'wan'                     # spoke WAN port name: zone wan, path wan, IKE gateway prefix
SECRET_PLACEHOLDERS = ('<ROOT-PASSWORD-HASH>', '<ROOT-SSH-KEY-TYPE>', '<ROOT-SSH-KEY>', '<LICENSE-KEY>', '<ICL-PSK>')
PLACEHOLDER_RX = re.compile(r'<(?!\*_to_\*>)[^<>\s]+>')                # any <...> except the Junos wildcard <*_to_*>

STOP_MSG = {   # exact stop messages (one per structural stop); validate() adds the answer that triggered it
    'model': 'this design is for an SRX400 pair',
    'access': 'the org networks, applications and Hub Profiles need an org admin (Super User). Alternative: create '
              'the token from an account with the admin role on this org',
    'two_wans': 'each node needs its own DHCP lease; a second WAN per node is a different design (one DHCP default '
                'per node is what the transit-link BGP exports). Alternative: one ISP per node',
    'lag_across': 'MNHA nodes are separate devices, so each node has its own LAG (one LAG per firewall on the LAN '
                  'switch, LACP active)',
    'hub_outside': 'a hub outside Mist cannot terminate the Mist overlay; build without a hub (H1 = no). '
                   'Alternative: a tunnel to that concentrator is a separate change to the Hub Profiles once both '
                   'nodes pass verification; this skill does not build it',
    'tenants': 'SRG1 carries one virtual IP per network, and without grid-id the virtual MAC is derived from the '
               'SRG and the virtual IP index; this design builds at most 32 per SRG. Alternative: merge networks to '
               '32 or fewer',
    'via_hub': 'Internet through the hub needs a per-tenant routing instance that these profiles do not build; '
               'choose local Internet or no Internet plus hub prefixes',
    'ipv6_only': 'each tenant needs an IPv4 subnet (the redundant gateway is an IPv4 virtual IP); give it one '
                 'and IPv6 on top',
    'probe': 'in hybrid mode the default probe toward VIP 1 is the form that survived both an ICL cut and '
             'active-node death; an explicit probe is not built. Alternative: keep the default probe (nothing to '
             'configure)',
    'security_services': 'not in the zero-touch push: add them to the Hub Profiles after both nodes pass '
                         'verification (signature packages and ATP enrollment do not exist on a factory-default box '
                         'at the first push)',
    'ha_form': 'this skill builds one two-node MNHA hybrid pair (SRG1); other HA forms are different designs '
               '(MNHA routing or switching mode, SRG0 active/active, a second SRG, chassis cluster, one node, three '
               'nodes). Alternative: this pair as built: SRG1 active on node 1 and backup on node 2, both ISPs in use '
               'through the per-network ISP steering',
    'ipv6_both': 'IPv6 from both ISPs is not supported by this design: it serves IPv6 per node, so each node would '
                 'advertise its own ISP\'s /64 on the same VLAN, and the design has no source-based IPv6 routing that '
                 'sends a packet to the ISP that owns its source address; a host that uses the other node as its IPv6 '
                 'router would lose IPv6 (that ISP drops a source it does not own). Alternative: IPv6 from one ISP for '
                 'this network (isp1 or isp2)',
    'public_routed': 'a public subnet routed without NAT needs its ISP to route that subnet to one node, and the other '
                     'ISP drops a source it does not own, so the per-network ISP backup cannot carry it; this design '
                     'source-NATs every Internet network to the WAN address of the node it leaves by. Alternative: '
                     'source NAT to the WAN address (answer nat)',
}


# ------------------------------------------------------------------ problems
def P(q, kind, msg):
    return {'q': q, 'kind': kind, 'msg': '%s: %s' % (q, msg)}


def R(q, msg):
    return P(q, 'reask', msg)


def S(q, msg):
    return P(q, 'stop', msg)


def C(q, msg):
    return P(q, 'precondition', msg)


def _net4(s, lo=8, hi=30):
    """Strict IPv4 network with lo <= prefix <= hi, or raise ValueError."""
    n = ip.ip_network(str(s).strip(), strict=True)
    if n.version != 4 or not (lo <= n.prefixlen <= hi):
        raise ValueError('need an IPv4 network /%d to /%d with the host bits zero' % (lo, hi))
    return n


def in_rfc1918(n):
    return any(n.subnet_of(r) for r in RFC1918)


def special4(n):
    """Reason string if n is special-use IPv4 space the design cannot route, else ''."""
    if n.overlaps(MIST_RESERVED):
        return 'overlaps 100.64.0.0/10, which Mist uses for the overlay tunnel and loopback addresses'
    for s in SPECIAL4:
        if n.overlaps(s):
            return 'overlaps special-use range %s' % s
    return ''


def _bool(v):
    return isinstance(v, bool)


def no_subnet(v):
    """T3 not answered (None, empty) or answered "none" (no IPv4 subnet), in any case."""
    return v is None or (isinstance(v, str) and v.strip().lower() in ('', 'none'))


# ------------------------------------------------------------------ derivations shared by validate() and build()
def tenant_order(tenants):
    """T = [the untagged network] + the others in answer order; no untagged network: answer order."""
    u = [t for t in tenants if t.get('untagged') is True]
    return u[:1] + [t for t in tenants if t.get('untagged') is not True]


def legacy_order(T):
    """Order of the Internet policy network list and the dhcpd_config keys: [t2, t3, t1, t4..tn]."""
    if len(T) < 3:
        return list(T[1:]) + list(T[:1])
    return [T[1], T[2], T[0]] + list(T[3:])


def node_ip(t, n):
    """Node n (1 or 2, int or str) address on network t: tenants[].node_ips {"1": .., "2": ..} when given, else the
    n-th host that is not the gateway."""
    n = int(n)
    o = t.get('node_ips') or {}
    if not isinstance(o, dict):
        raise TypeError('node_ips is not {"1": <address>, "2": <address>}')
    if o.get(str(n)):
        return ip.ip_address(o[str(n)])
    net, gw = ip.ip_network(t['subnet']), ip.ip_address(t['gateway'])
    k = 0
    for h in net.hosts():
        if h == gw:
            continue
        k += 1
        if k == n:
            return h
    raise ValueError('no free host for node %s' % n)


def dhcp_default(t):
    """T7 default: network+10 .. network+min(200, size-2); None if it does not fit."""
    net, gw = ip.ip_network(t['subnet']), ip.ip_address(t['gateway'])
    s, e = net.network_address + 10, net.network_address + min(200, net.num_addresses - 2)
    if s > e or not (s in net and e in net):
        return None
    reserved = {gw, node_ip(t, 1), node_ip(t, 2)}
    if any(s <= r <= e for r in reserved):
        return None
    return str(s), str(e)


def internal_layout(block):
    """/24 #0: ICL /30; #1: loopbacks .1/.2 (and the mgmt-0 placeholder /25); #2: transit-link /30; #3: signal routes."""
    b24 = list(itertools.islice(ip.ip_network(block).subnets(new_prefix=24), 4))
    icl = next(b24[0].subnets(new_prefix=30))
    icd = next(b24[2].subnets(new_prefix=30))
    oob_placeholder = list(b24[1].subnets(new_prefix=25))[1]
    return {'icl_net': icl, 'icl': [icl.network_address + 1, icl.network_address + 2],
            'lo0': [b24[1].network_address + 1, b24[1].network_address + 2],
            'icd_net': icd, 'icd': [icd.network_address + 1, icd.network_address + 2],
            'signal': [b24[3].network_address + 1, b24[3].network_address + 2],
            'oob_placeholder': oob_placeholder}


def ipv6_source(t):
    """tenants[].ipv6 as one of none / isp1 / isp2 / both (a boolean true from older files means isp1)."""
    v = t.get('ipv6')
    if v is True:
        return 'isp1'
    if v in (False, None):
        return 'none'
    return v


def ipv6_isps(t):
    s = ipv6_source(t)
    return {'none': [], 'isp1': ['1'], 'isp2': ['2'], 'both': ['1', '2']}.get(s, []) if isinstance(s, str) else []


def dhcp_mode(t):
    d = t.get('dhcp') or {}
    if not isinstance(d, dict):
        return None                              # check_tenant re-asks T6
    if 'mode' in d:
        return d['mode']
    return 'server' if d.get('enabled', True) else 'none'


def internet(t):
    return t.get('internet', True) is True


def pd_length(isp):
    p = isp.get('delegated_prefix')
    if p and p != 'unknown':
        return ip.ip_network(p, strict=False).prefixlen
    return int(isp.get('pd_length') or 60)


def ipv6_index(t, vip_index):
    return t['ipv6_index'] if t.get('ipv6_index') is not None else vip_index


def ssh_tenants(T):
    """Networks whose zone accepts SSH: tenants[].ssh; when no network says, the first network (t1) only."""
    if any('ssh' in t for t in T):
        return [t for t in T if t.get('ssh') is True]
    return T[:1]


def alq_tenant(a, T):
    """T20: the named network; by default the first network in T order where the firewalls serve DHCP (the binding
    sync runs between the two DHCP servers); None when no network uses the firewalls' DHCP server."""
    name = (a.get('pair') or {}).get('alq_tenant')
    for t in T:
        if name and str(t['name']).lower() == str(name).lower():
            return t
    for t in T:
        if dhcp_mode(t) == 'server':
            return t
    return None


def hub_paths(hub):
    """hub.paths; a hub given with single path fields is read as one path. A paths value that is not a list is
    returned as it is (check_hub re-asks H3)."""
    if hub.get('paths'):
        return hub['paths']
    if hub.get('path'):
        return [{k: hub.get(k) for k in ('path', 'hub_profile_name', 'hub_wan_port_name', 'hub_device_id',
                                          'hub_site_id', 'hub_mac', 'hub_device_name')}]
    return []


def norm_portal(portal_host):
    """Accept a pasted portal URL: keep the host only."""
    h = str(portal_host or '').strip().lower()
    h = re.sub(r'^[a-z]+://', '', h)
    return h.split('/', 1)[0]


def api_host(portal_host):
    return 'api.' + norm_portal(portal_host)[len('manage.'):]


# ------------------------------------------------------------------ defaults (schema v2)
def normalize(answers):
    """Deep copy with every optional key at its documented default. Wrong types are kept as given, so that
    validate() still reports them."""
    a = copy.deepcopy(answers)
    for k in ('mist', 'site', 'nodes', 'isps', 'services', 'hub', 'pair', 'mgmt', 'internal', 'site_readiness'):
        if not isinstance(a.get(k), dict):
            a[k] = {} if a.get(k) is None else a[k]
    a.setdefault('tenants', [])
    a.setdefault('profiles_method', 'api')
    a.setdefault('security_services', [])
    if a.get('existing') is None:
        a['existing'] = {}
    if isinstance(a['existing'], dict):
        a['existing'].setdefault('reuse', [])    # step 3.1: org objects and profiles equal to the plan, reused
    for n in ('1', '2'):
        nd = a['nodes'].setdefault(n, {})
        if not isinstance(nd, dict):
            continue
        nd.setdefault('profile_name', 'SZTP-SRX400-NODE%s' % n)
        p = nd.setdefault('ports', {})
        if isinstance(p, dict):
            p.setdefault('wan', 'ge-0/0/2')
            p.setdefault('lan', ['ge-0/0/3'])
            if isinstance(p['lan'], str):
                p['lan'] = [p['lan']]
            p.setdefault('lan_lacp', True)
            p.setdefault('lan_lag_across_nodes', False)
            p.setdefault('icl', 'ge-0/0/4')
            p.setdefault('icd', 'ge-0/0/5')
        isp = a['isps'].setdefault(n, {})
        if isinstance(isp, dict):
            isp.setdefault('label', 'ISP %s' % n)
            isp.setdefault('handoff', 'dhcp-untagged')
            isp.setdefault('ipv6_pd', False)
            if 'lease_behaviour' in isp:         # also reads the key lease_behaviour
                old = isp.pop('lease_behaviour')
                isp.setdefault('lease_behavior', old)
            ws = isp.get('wan_subnet')
            if isinstance(ws, str) and ws.strip().lower() == 'unknown':
                isp['wan_subnet'] = None         # W3 "unknown" = null
    a['isps'].setdefault('same_upstream', None)  # W5: null until answered (asked only when both WAN ranges are the same)
    a['services'].setdefault('dns_servers', ['8.8.8.8', '1.1.1.1'])
    a['services'].setdefault('ntp_servers', ['pool.ntp.org'])
    a['hub'].setdefault('present', False)
    a['hub'].setdefault('in_mist', True)
    a['pair'].setdefault('alq_tenant', None)
    a['pair'].setdefault('preemption', False)
    a['pair'].setdefault('icl_encryption', False)
    a['pair'].setdefault('ha_mode', HA_MODE)
    a['pair'].setdefault('activeness_probe', 'default')
    a['mgmt'].setdefault('mode', 'static')
    a['internal'].setdefault('block', '10.255.0.0/16')
    a['internal'].setdefault('icd_asn', {'1': '65001', '2': '65002'})
    tl = a['tenants'] if isinstance(a['tenants'], list) else []
    if tl and all(isinstance(t, dict) for t in tl) and not any('untagged' in t for t in tl):
        tl[0]['untagged'] = True                 # T12 default: the first network listed is untagged
    for t in tl:
        if not isinstance(t, dict):
            continue
        t.setdefault('internet', True)
        if t.get('internet') is True and t.get('preferred_isp') is None:
            t['preferred_isp'] = 1               # T5 default: ISP 1
        if t.get('gateway') in (None, ''):       # T4 default: the first host of the subnet
            try:
                t['gateway'] = str(next(_net4(t.get('subnet'), 8, 29).hosts()))
            except (ValueError, TypeError, StopIteration):
                pass
        t.setdefault('reach', [])               # T11 (overlay) has no stored default: absent = not asked yet, read as no
        t.setdefault('ipv6_index', None)
        t.setdefault('node_ips', None)
        if 'ipv6' not in t and not no_subnet(t.get('subnet')):
            # T10 default: from the preferred ISP when it delegates (only once T3 is answered: T10 comes after it)
            pi = t.get('preferred_isp')
            isp = a['isps'].get(str(pi)) if pi in (1, 2) else None
            t['ipv6'] = ('isp%s' % pi) if (isinstance(isp, dict) and isp.get('ipv6_pd') is True
                                            and t.get('internet') is True) else 'none'
        d = t.setdefault('dhcp', {})
        if not isinstance(d, dict):
            continue
        if 'mode' not in d:
            d['mode'] = 'server' if d.get('enabled', True) else 'none'
        if d['mode'] == 'server':
            if 'start' not in d or 'end' not in d:
                try:
                    dd = dhcp_default(t)
                    if dd:
                        d.setdefault('start', dd[0])
                        d.setdefault('end', dd[1])
                except (ValueError, TypeError, KeyError):
                    pass
            if 'dns_servers' not in d and a['services'].get('dns_servers') and t.get('internet') is True:
                d['dns_servers'] = list(a['services']['dns_servers'])   # T8 default: S1 (Internet networks only)
            d.setdefault('lease_time', 86400)
            d.setdefault('options', {})
            d.setdefault('fixed_bindings', {})
            d.setdefault('dns_suffix', [])
        d.setdefault('relay_servers', [])
    return a


# ------------------------------------------------------------------ A. Mist access, B. site and devices
def check_A1(portal_host):
    h = norm_portal(portal_host)
    if not re.match(r'^manage(\.[a-z0-9-]+)?\.mist\.com$', h):
        return [R('A1', 'give the portal host from the browser address bar, manage.<cloud>.mist.com or manage.mist.com')]
    return []


TOKEN_RE = re.compile(r'^[A-Za-z0-9]{20,}$')                            # a Mist API token: one line, letters and digits


def check_A2(path):
    """Token file: exists, mode 600, and holds one token line (letters and digits). The token is read only to check
    its shape; the message gives its length at most, never the value."""
    p = os.path.expanduser(str(path or ''))
    if not os.path.isfile(p):
        return [R('A2', 'no file at that path; save the token in a local file and give its path')]
    if os.stat(p).st_mode & 0o077:
        return [R('A2', 'the token file must be readable only by you: chmod 600 <file>, then confirm')]
    try:
        with open(p) as f:
            raw = f.read()
    except (OSError, UnicodeDecodeError):
        return [R('A2', 'the token file cannot be read as text; save only the token in it')]
    tok = raw.strip()
    if not TOKEN_RE.match(tok):
        return [R('A2', 'the token file must hold only the token: one line of letters and digits (it holds %d '
                  'characters on %d lines); save only the token in it' % (len(tok), len(tok.splitlines()) or 1))]
    return []


def check_A3(access):
    if access in (None, '') or access in ACCESS_BUILD:
        return []
    if access in ACCESS_STOP:
        return [S('A3', 'this token has role %s on the org; %s' % (access, STOP_MSG['access']))]
    return [R('A3', 'token access: org-admin or msp-admin (as GET /self lists the privileges)')]


def _orggroups(p):
    v = p.get('orggroup_ids')
    if isinstance(v, list):
        return set(map(str, v))
    return {str(p['orggroup_id'])} if p.get('orggroup_id') else set()


def check_A3_privileges(privileges, org_id, msp_orgs=None, org=None):
    """privileges = GET /self 'privileges'; org = GET /orgs/{org_id} (its msp_id and orggroup_ids; read it for an
    msp or orggroup entry). Org admin builds; an MSP admin builds when the org's msp_id is that entry's msp_id (or,
    with msp_orgs = {msp_id: [org ids]} from GET /msps/{msp_id}/orgs, when the org is listed); an org-group admin
    builds when the org is in one of its org groups. Any other role on the org stops; site or site-group access
    only stops; no access re-asks."""
    privs = [p for p in privileges or [] if isinstance(p, dict)]
    orgs = [p for p in privs if p.get('scope') == 'org' and p.get('org_id') == org_id]
    if any(p.get('role') == 'admin' for p in orgs):
        return []
    org = org if isinstance(org, dict) else None
    org_msp = (org or {}).get('msp_id')
    msp = [p for p in privs if p.get('scope') == 'msp']
    holds = [p for p in msp if (org_msp and p.get('msp_id') == org_msp)
             or org_id in ((msp_orgs or {}).get(p.get('msp_id')) or [])]
    og_ids = set(map(str, (org or {}).get('orggroup_ids') or []))
    og = [p for p in privs if p.get('scope') == 'orggroup']
    ogh = [p for p in og if og_ids & _orggroups(p)]
    if any(p.get('role') == 'admin' for p in holds + ogh):
        return []
    role = (orgs or holds or ogh or [{}])[0].get('role')
    if orgs or holds or ogh:
        return [S('A3', 'this token has role %s on the org; %s' % (role, STOP_MSG['access']))]
    sites = [p for p in privs if p.get('scope') in ('site', 'sitegroup') and p.get('org_id') == org_id]
    if sites:
        return [S('A3', 'this token has only %s access to the org (role %s); %s' % (
            'site' if sites[0].get('scope') == 'site' else 'site-group', sites[0].get('role'), STOP_MSG['access']))]
    if (msp or og) and org is None and msp_orgs is None:
        return [R('A3', 'the token has MSP or org-group privileges: read GET /orgs/{org_id} for the chosen org and pass '
                  'it as org (its msp_id and orggroup_ids show whether the token administers it)')]
    return [R('A3', 'the token has no access to that org; pick an org from the list GET /self returns')]


def article(word):
    """'an' before a model name read with a vowel sound (SRX345 = "ess-ar-ex", EX4100, MX304), else 'a'."""
    return 'an' if str(word or '')[:1].upper() in 'AEFHILMNORSX' else 'a'


def check_B2(s1, s2, models=(None, None)):
    errs = []
    for k, s in (('node 1', s1), ('node 2', s2)):
        if not re.match(r'^[A-Za-z0-9]{6,20}$', str(s or '').strip()):
            errs.append(R('B2', '%s serial: 6 to 20 letters and digits, as on the box label' % k))
    if str(s1).strip().upper() == str(s2).strip().upper():
        errs.append(R('B2', 'the two serials must differ'))
    for k, m in zip(('1', '2'), models):
        if m not in (None, '') and str(m).upper() != 'SRX400':
            errs.append(S('B2', 'node %s is %s %s; %s' % (k, article(m), m, STOP_MSG['model'])))
    return errs


def release_rank(r):
    """(D number, maintenance number) of a 25.4X300 release, -EVO stripped; None when it is not one. D30 = (30, 0)."""
    m = RELEASE_RE.match(_norm_release(r))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)[1:]) if m.group(2) else 0


def release_proven(r):
    """True for the release the reference design is proven on (25.4X300-D30.3); a later 25.4X300 release builds beyond
    the reference design (hardware_status())."""
    return release_rank(r) == release_rank(RELEASE_BASE)


def check_B4(release, factory_default):
    errs = []
    r = str(release or '').strip()
    if r.endswith('-EVO'):
        r = r[:-4]
    m = RELEASE_RE.match(r)
    if r.lower() == 'unknown' or not r:
        errs.append(R('B4', 'on the console, show version | no-more prints the Junos line; give that release'))
    elif not m:
        errs.append(S('B4', '%s is not a Junos OS Evolved 25.4X300 release for SRX400. Install %s on the console '
                      'before shipping' % (r, RELEASE_BASE)))
    elif int(m.group(1)) < 30:
        errs.append(S('B4', '%s has no MNHA DHCP (managed-services dhcp and Active Leasequery arrive in D30). '
                      'Install %s on the console before shipping' % (r, RELEASE_BASE)))
    elif release_rank(r) < release_rank(RELEASE_BASE):
        errs.append(S('B4', '%s is older than %s, the release this design runs on. Install %s on the console before '
                      'shipping' % (r, RELEASE_BASE, RELEASE_BASE)))
    if factory_default == 'no':
        errs.append(C('B4', 'on the console, with only the console cable connected, run request system zeroize '
                      'ztp-option secure-enable; keep WAN, LAN and mgmt-0 unplugged until the box is at the site'))
    elif factory_default not in ('yes',):
        errs.append(R('B4', 'answer yes or no: is each node in its factory-default state?'))
    return errs


def check_B_inventory(rec1, rec2):
    """Org-state preconditions from GET inventory / device records (read-only)."""
    errs = []
    for n, r in (('1', rec1), ('2', rec2)):
        if not r:
            errs.append(C('B2', 'node %s serial is not in the org inventory: claim it into this org and assign it '
                          'to the branch site, then tell me' % n))
            continue
        if str(r.get('model', '')).upper() != 'SRX400':
            errs.append(S('B2', 'node %s is %s %s; %s' % (n, article(r.get('model')), r.get('model'),
                                                          STOP_MSG['model'])))
        if not r.get('site_id'):
            errs.append(C('B1', 'node %s is not assigned to a site: assign it to the branch site, then tell me' % n))
        if r.get('connected'):
            errs.append(C('B4', 'node %s is connected to Mist: it must start factory default: on the console, with '
                          'only the console cable connected, run request system zeroize ztp-option secure-enable; '
                          'keep WAN, LAN and mgmt-0 unplugged until the box is at the site' % n))
        if not r.get('name'):
            errs.append(C('B3', 'node %s has no name in Mist: name it (Mist renders the host name from it)' % n))
    if rec1 and rec2 and rec1.get('site_id') and rec1.get('site_id') != rec2.get('site_id'):
        errs.append(C('B1', 'the two nodes sit in different sites; assign both to the branch site'))
    return errs


def _empty(v):
    return v is None or v == '' or v == [] or v == {}


def check_device_record(rec, n):
    """GET /sites/{site_id}/devices/{device_id} of node n (SKILL.md steps 2.3, 4.4, 5). Mist pushes to the node only
    when it manages it: disable_auto_config absent or false, mist_configured true. Every key other than the
    identity and placement keys (DEVICE_RECORD_KEYS) that holds a value is a device-level setting Mist renders on
    top of the Hub Profile (port_config, mnha_config, vrf_config, vars, additional_config_cmds and the like)."""
    if not isinstance(rec, dict):
        return [C('B2', 'node %s: no device record read; read GET /sites/{site_id}/devices/{device_id} again' % n)]
    errs = []
    if rec.get('disable_auto_config') is True:
        errs.append(C('B2', 'node %s: disable_auto_config is true on its Mist device record, so Mist pushes no '
                      'configuration to it: set it back to false in Mist (this skill writes no device records), then '
                      'tell me' % n))
    if rec.get('mist_configured') is not True:
        errs.append(C('B2', 'node %s: mist_configured is not true on its Mist device record, so Mist does not manage '
                      'its configuration: let Mist manage it, then tell me' % n))
    extra = sorted(k for k, v in rec.items() if k not in DEVICE_RECORD_KEYS and not _empty(v))
    if extra:
        errs.append(C('B2', 'node %s: its Mist device record carries device-level settings (%s), which Mist renders on '
                      'top of the Hub Profile: remove them from the device in Mist (this skill writes no device '
                      'records), then tell me' % (n, ', '.join(extra))))
    return errs


def _norm_release(r):
    r = str(r or '').strip()
    return r[:-4] if r.upper().endswith('-EVO') else r


def check_site_settings(org_setting, site_setting, release):
    """GET /orgs/{org_id}/setting and GET /sites/{site_id}/setting (SKILL.md step 2.4), held in memory. A site value
    takes the place of the org value. Preconditions: SRX firmware auto-upgrade on first onboarding
    (juniper_srx.auto_upgrade) unless pinned to the B4 release for SRX400; config_push_policy no_push or a push
    window; gateway_mgmt config_revert_timer other than 10 (the design's commit confirmed window), protect_re on,
    a root_password, disable_oob."""
    o = org_setting if isinstance(org_setting, dict) else {}
    s = site_setting if isinstance(site_setting, dict) else {}
    errs = []
    rel = _norm_release(release)
    srx_s, srx_o = s.get('juniper_srx') or {}, o.get('juniper_srx') or {}
    au, scope = (srx_s.get('auto_upgrade'), 'site') if isinstance(srx_s.get('auto_upgrade'), dict) else \
        (srx_o.get('auto_upgrade'), 'org')
    if isinstance(au, dict) and au.get('enabled') is True:
        cv = au.get('custom_versions') if isinstance(au.get('custom_versions'), dict) else {}
        target = cv.get('SRX400') or au.get('version')      # custom_versions first, then version, else Mist's default
        if target and not rel:
            # B4 not answered yet (group 3): the pin is judged once the release is known (SKILL.md step 1 group 4
            # runs this check again with it); no B1 precondition before that
            errs.append(R('B4', 'SRX firmware auto-upgrade on first onboarding is on (juniper_srx.auto_upgrade, %s '
                          'setting) and pins SRX400 to %s: answer B4, then run check_site_settings again with that '
                          'release (it builds only when the two are the same)' % (scope, target)))
        elif not (rel and _norm_release(target) == rel):
            errs.append(C('B1', 'SRX firmware auto-upgrade on first onboarding is on (juniper_srx.auto_upgrade, %s '
                          'setting, target %s): Mist would upgrade both SRX400s during zero touch. Turn it off in the '
                          'org and site settings, or pin SRX400 to %s (custom_versions), then tell me'
                          % (scope, target or 'the Mist default version', rel or 'the B4 release')))
    for where, st in (('site', s), ('org', o)):
        cp = st.get('config_push_policy') or {}
        if cp.get('no_push') is True:
            errs.append(C('B1', 'config_push_policy.no_push is on in the %s setting: Mist pushes no configuration, so '
                          'zero touch never gets the Hub Profiles. Turn it off, then tell me' % where))
        if isinstance(cp.get('push_window'), dict) and cp['push_window'].get('enabled') is True:
            errs.append(C('B1', 'config_push_policy.push_window is on in the %s setting: Mist pushes only inside that '
                          'window, and the first push must follow the call-home. Turn it off for the onboarding, then '
                          'tell me' % where))
    gm_s, gm_o = s.get('gateway_mgmt') or {}, o.get('gateway_mgmt') or {}

    def gm(k):
        return gm_s[k] if k in gm_s else gm_o.get(k)
    t = gm('config_revert_timer')
    if t not in (None, 10):
        errs.append(C('B1', 'gateway_mgmt.config_revert_timer is %s: this design is built for the default 10-minute '
                      'commit confirmed window (the W4 lease limit, the step 6 alerts and the step 7 checks). Set it '
                      'back to 10 (or remove it), then tell me' % t))
    if isinstance(gm('protect_re'), dict) and gm('protect_re').get('enabled') is True:
        errs.append(C('B1', 'gateway_mgmt.protect_re is on: Mist adds a control-plane filter beside the Hub Profiles '
                      'that can drop the HA link, transit-link BGP and BFD traffic of this design. Turn it off, then '
                      'tell me'))
    if not _empty(gm('root_password')):
        errs.append(C('B1', 'gateway_mgmt.root_password is set: Mist renders that root password beside the Hub '
                      'Profile\'s root authentication. Remove it (the Hub Profiles carry the root authentication), then '
                      'tell me'))
    if gm('disable_oob') is True:
        errs.append(C('B1', 'gateway_mgmt.disable_oob is on: Mist disables the management interface mgmt-0 that the '
                      'Hub Profiles address and the step 7 checks use. Turn it off, then tell me'))
    return errs


# ------------------------------------------------------------------ P. ports
def check_ports(nodes):
    errs = []
    p1, p2 = nodes['1']['ports'], nodes['2']['ports']
    for n, p in (('1', p1), ('2', p2)):
        if isinstance(p.get('wan'), list):
            if len(p['wan']) > 1:
                errs.append(S('W1', 'node %s has %d WAN links; %s' % (n, len(p['wan']), STOP_MSG['two_wans'])))
                continue
            p['wan'] = p['wan'][0] if p['wan'] else None
        if p.get('lan_lag_across_nodes') is True:
            errs.append(S('P3', 'node %s: one LAG across both firewalls (MC-LAG / ESI-LAG); %s' % (n, STOP_MSG['lag_across'])))
        lan = p.get('lan') or []
        if not isinstance(lan, list) or not all(isinstance(x, str) for x in lan):
            errs.append(R('P3', 'node %s: LAN ports as a list of port names (one to seven ports)' % n))
            continue
        allp = [p.get('wan'), p.get('icl'), p.get('icd')] + list(lan)
        for x in allp:
            if str(x).lower() in ('mgmt-0', 'fxp0', 're0:mgmt-0'):
                errs.append(R('P1', 'node %s: mgmt-0 is the out-of-band port only; pick ge-0/0/0 .. ge-0/0/9' % n))
            elif not PORT_RE.match(str(x)):
                errs.append(R('P1', 'node %s: %s is not an SRX400 port; ports are ge-0/0/0 .. ge-0/0/9' % (n, x)))
        if p.get('wan') == FACTORY_SERVER:
            errs.append(S('P2', 'node %s: ge-0/0/3 runs the factory DHCP server, not a DHCP client, so zero touch '
                          'cannot get the ISP lease there. Use any other port for the WAN' % n))
        if not (1 <= len(lan) <= 7):
            errs.append(R('P3', 'node %s: one to seven LAN ports' % n))
        if len(set(lan)) != len(lan):
            errs.append(R('P3', 'node %s: a LAN port is listed twice' % n))
        lacp = p.get('lan_lacp', True)
        if not _bool(lacp):
            errs.append(R('P3', 'node %s: LACP on the LAN link: yes or no' % n))
        elif not lacp:
            if len(lan) != 1:
                errs.append(R('P3', 'node %s: without LACP the LAN is one port; give one port or use LACP' % n))
            elif lan and lan[0] == FACTORY_SERVER:
                errs.append(S('P3', 'node %s: without LACP the factory DHCP server on ge-0/0/3 would hand out '
                              '192.168.2.x leases on the LAN before the push. Use LACP on ge-0/0/3 or another '
                              'port for a plain LAN link' % n))
        if len(set(map(str, allp))) != len(allp):
            errs.append(R('P1', 'node %s: WAN, LAN, ICL and transit ports must all differ' % n))
    for role, q in (('icl', 'P4'), ('icd', 'P5')):
        a, b = p1.get(role), p2.get(role)
        if (a == FACTORY_SERVER) != (b == FACTORY_SERVER):
            errs.append(S(q, '%s: ge-0/0/3 on one node and %s on the other: at factory default the ge-0/0/3 DHCP '
                          'server would give the peer port a second default route during zero touch. Use '
                          'ge-0/0/3 on both ends or on neither' % (role.upper(), b if a == FACTORY_SERVER else a)))
    return errs


# ------------------------------------------------------------------ W. ISPs
def ge3_cabled(nodes, n):
    """ge-0/0/3 (the factory DHCP server 192.168.2.1/24) has a role on node n: LAN member, HA link or transit link."""
    ports = (nodes.get(n) or {}).get('ports') or {}
    return FACTORY_SERVER in ([ports.get('icl'), ports.get('icd')] + list(ports.get('lan') or []))


def check_W(isps, nodes):
    errs = []
    for n in ('1', '2'):
        i = isps[n]
        h = i.get('handoff')
        if h in ('static', 'pppoe', 'dhcp-tagged', 'none'):
            what = {'static': 'a static address', 'pppoe': 'PPPoE', 'dhcp-tagged': 'an 802.1Q-tagged VLAN',
                    'none': 'no WAN on this node'}[h]
            alt = ('give node %s its own DHCP lease (a second port on the ISP router or a small switch)' % n
                   if h == 'none' else
                   'put an ISP router in front that hands the firewall an untagged DHCP lease (its LAN range is '
                   'then the WAN subnet), or onboard this pair another way')
            errs.append(S('W1', 'ISP %s uses %s. A factory-default SRX400 only sends untagged DHCP, so zero touch '
                          'cannot reach Mist. Alternative: %s' % (n, what, alt)))
        elif h != 'dhcp-untagged':
            errs.append(R('W1', 'ISP %s hand-off: DHCP on an untagged port, static, PPPoE, tagged VLAN, or none' % n))
        wc = i.get('wan_count', 1)
        if isinstance(wc, int) and not isinstance(wc, bool) and wc > 1:
            errs.append(S('W1', 'node %s has %d WAN links; %s' % (n, wc, STOP_MSG['two_wans'])))
        ws = i.get('wan_subnet')
        if ws:
            try:
                w = _net4(ws, 8, 30)
                if w.overlaps(FACTORY_GE3) and ge3_cabled(nodes, n):
                    errs.append(S('W3', 'ISP %s hands out %s, which overlaps the factory ge-0/0/3 subnet '
                                  '192.168.2.0/24 that is up on node %s during zero touch. Alternative: change the ISP '
                                  'router LAN range, or move node %s roles off ge-0/0/3' % (n, w, n, n)))
            except (ValueError, TypeError) as e:
                errs.append(R('W3', 'ISP %s address range: %s, or say unknown' % (n, e)))
        lb = i.get('lease_behavior')
        secs = i.get('lease_seconds')
        if lb == 'held':
            if not isinstance(secs, int) or isinstance(secs, bool) or secs <= 0:
                errs.append(R('W4', 'ISP %s holds the address: how long is its lease, in minutes?' % n))
            elif secs > LEASE_MAX_SECONDS:
                errs.append(S('W4', 'ISP %s holds the one address for %s minutes. After the first push the firewall '
                              'asks again as a new DHCP client and gets an address only when the zero-touch lease '
                              'ends; Mist confirms the push once the node is back on Mist, and an unconfirmed push '
                              'rolls back 10 minutes after it is made. With a 10-minute lease node 1 was back on Mist '
                              '3 min 57 s and the push confirmed 5 min 38 s after the push; each extra minute of lease '
                              'adds about a minute, so a lease longer than %d minutes leaves less than a minute before '
                              'the rollback (at 15 minutes the confirm comes after it). Alternative: ask the ISP for a '
                              'lease of %d minutes or less for the install, or an ISP router that hands out a second '
                              'address' % (n, ('%d' % (secs // 60)) if secs % 60 == 0 else '%.1f' % (secs / 60.0),
                                           LEASE_MAX_SECONDS // 60, LEASE_MAX_SECONDS // 60)))
        elif lb not in ('new-address',):
            errs.append(R('W4', 'ISP %s: after the push, does it give the firewall an address at once (new-address) or '
                          'hold the one address until the first lease ends (held)? Ask the ISP if unsure' % n))
    if isps['1'].get('wan_subnet') and str(isps['1'].get('wan_subnet')).strip() == str(isps['2'].get('wan_subnet')).strip():
        if not _bool(isps.get('same_upstream')):      # yes: one upstream; no: two ISP routers with the same range
            errs.append(R('W5', 'both ISPs hand out the same range: is it one upstream for both nodes (yes/no)?'))
    return errs


# ------------------------------------------------------------------ S. site services
def check_S1(dns):
    if dns == []:
        return []                                # the ISP's DNS from DHCP
    if not (isinstance(dns, list) and 1 <= len(dns) <= 3):
        return [R('S1', 'one to three DNS server addresses, or say: use the ISP DNS')]
    errs = []
    for d in dns:
        try:
            a = ip.ip_address(str(d).strip())
            if a.version != 4:
                errs.append(R('S1', '%s: give IPv4 resolvers (a node without IPv6 WAN cannot reach it)' % d))
            elif not a.is_global:
                errs.append(R('S1', '%s: the firewalls resolve the Mist cloud with these servers from their default '
                              'routing table, out the WAN; give public resolvers (clients can still get internal DNS '
                              'per tenant)' % d))
        except (ValueError, TypeError):
            errs.append(R('S1', '%s is not an IPv4 address' % d))
    if len(set(map(str, dns))) != len(dns):
        errs.append(R('S1', 'duplicate DNS server'))
    return errs


def check_S2(ntp):
    if not (isinstance(ntp, list) and 1 <= len(ntp) <= 3):
        return [R('S2', 'one to three NTP servers (host names or public IPv4 addresses)')]
    errs = []
    for s in ntp:
        s = str(s).strip()
        try:
            a = ip.ip_address(s)
            if a.version != 4 or not a.is_global:
                errs.append(R('S2', '%s: the firewalls reach NTP out the WAN; use a public IPv4 address or a host '
                              'name' % s))
        except ValueError:
            if not HOST_RE.match(s):
                errs.append(R('S2', '%s is neither an IPv4 address nor a host name' % s))
    return errs


# ------------------------------------------------------------------ V. IPv6 per ISP
def check_V(isps, allow_documentation=False):
    errs = []
    for n in ('1', '2'):
        i = isps[n]
        if not _bool(i.get('ipv6_pd', False)):
            errs.append(R('V1', 'ISP %s IPv6 prefix delegation: yes or no' % n))
            continue
        if not i.get('ipv6_pd'):
            continue
        p = i.get('delegated_prefix')
        if p in (None, ''):
            errs.append(R('V2', 'ISP %s: give the delegated prefix, or say unknown' % n))
            continue
        if p == 'unknown':
            L = i.get('pd_length', 60)
            if not (isinstance(L, int) and not isinstance(L, bool) and 48 <= L <= 64):
                errs.append(R('V2', 'ISP %s: which prefix length does it delegate (48 to 64)?' % n))
        else:
            try:
                net = ip.ip_network(str(p).strip(), strict=True)
            except ValueError:
                errs.append(R('V2', 'ISP %s: not a valid IPv6 prefix (network/length, host bits zero)' % n))
                continue
            if net.version != 6 or not (48 <= net.prefixlen <= 64):
                errs.append(R('V2', 'ISP %s: give an IPv6 prefix of length /48 to /64' % n))
            elif not net.subnet_of(GUA6):
                errs.append(R('V2', 'ISP %s: the delegated prefix must be global unicast (inside 2000::/3)' % n))
            elif not allow_documentation and any(net.subnet_of(d) for d in DOC6):
                errs.append(R('V2', 'ISP %s: %s is an IPv6 documentation prefix; give the prefix the ISP really '
                              'delegates' % (n, net)))
        st = i.get('prefix_stable')
        if st == 'no':
            errs.append(S('V3', 'ISP %s may change the delegated prefix. On 25.4X300-D30.3 the dynamic form '
                          '(update-router-advertisement) fails (at most 3 interfaces, no route to the /64s), so the '
                          'LAN /64s are static lines. Choose: IPv4 only for now, or static /64s from today\'s prefix '
                          'and you update the profiles when the ISP changes it (answer accept-manual-update)' % n))
        elif st not in ('yes', 'accept-manual-update'):
            errs.append(R('V3', 'ISP %s: does the delegated prefix stay the same (yes / no / accept-manual-update)?' % n))
    a, b = isps['1'].get('delegated_prefix'), isps['2'].get('delegated_prefix')
    if isps['1'].get('ipv6_pd') is True and isps['2'].get('ipv6_pd') is True and a and b and 'unknown' not in (a, b):
        try:
            if ip.ip_network(a).overlaps(ip.ip_network(b)):
                errs.append(R('V2', 'the two ISP prefixes overlap; give each ISP\'s own prefix'))
        except ValueError:
            pass
    return errs


# ------------------------------------------------------------------ H. hub and overlay
def check_hub(hub, overlay_count):
    errs = []
    if not _bool(hub.get('present')):
        return [R('H1', 'is there a hub (a Mist Hub Profile in this org that tenants reach over the overlay): yes or no?')]
    if not hub['present']:
        return []                                 # no hub: in_mist does not matter
    if hub.get('in_mist') is False:
        return [S('H1', STOP_MSG['hub_outside'])]
    if hub.get('vpn_type') not in (None, 'hub_spoke'):
        errs.append(R('H2', 'VPN %s is type %s; pick a hub-and-spoke VPN of this org' % (hub.get('vpn_name'), hub.get('vpn_type'))))
    vn = str(hub.get('vpn_name') or '')
    if not (len(vn) <= 32 and NAME_RE.match(vn)):
        errs.append(R('H2', 'VPN name as Mist lists it (letters, digits, _ and -, up to 32)'))
    paths = hub_paths(hub)
    if not isinstance(paths, list) or not all(isinstance(p, dict) for p in paths):
        errs.append(R('H3', 'hub paths as a list, one {path, hub_profile_name, hub_wan_port_name, hub_device_id, '
                      'hub_site_id, hub_mac, hub_device_name} per path (answers.example.json)'))
        paths = []
    elif not (1 <= len(paths) <= MAX_HUB_PATHS):
        errs.append(R('H3', 'pick one to %d hub paths of the VPN' % MAX_HUB_PATHS))
    seen = set()
    for p in paths:
        if not re.match(r'^[0-9a-f]{12}$', str(p.get('hub_mac', ''))):
            errs.append(C('H4', 'path %s: no single connected hub device carries its Hub Profile; connect the hub '
                          'first' % p.get('path')))
        pn = str(p.get('hub_wan_port_name') or '')
        if not NAME_RE.match(pn):
            errs.append(R('H3', 'path %s: the hub WAN port name is read from the hub profile' % p.get('path')))
        hp = p.get('hub_profile_name')
        if not (isinstance(hp, str) and len(hp) <= 32 and NAME_RE.match(hp)):
            errs.append(R('H3', 'path %s: the hub profile name as Mist lists it (letters, digits, _ and -, up to 32)'
                          % p.get('path')))
        if not (isinstance(p.get('path'), str) and NAME_RE.match(p['path'])):
            errs.append(R('H3', 'path %s: a path key of the VPN as Mist lists it (letters, digits, _ and -)'
                          % p.get('path')))
        elif p.get('path') != '%s-%s' % (hp, pn):
            errs.append(R('H3', 'path %s does not equal <hub profile name>-<hub WAN port name>' % p.get('path')))
        if str(p.get('path')) in seen:
            errs.append(R('H3', 'path %s is listed twice' % p.get('path')))
        seen.add(str(p.get('path')))
    if overlay_count:
        pref = hub.get('site_prefixes')
        if not (isinstance(pref, list) and 1 <= len(pref) <= 20):
            errs.append(R('H5', 'one to twenty hub-site prefixes that the overlay tenants reach'))
        else:
            for x in pref:
                try:
                    n = _net4(x, 8, 32)
                    why = special4(n)
                    if why:
                        errs.append(R('H5', '%s %s' % (x, why)))
                except (ValueError, TypeError) as e:
                    errs.append(R('H5', '%s: %s' % (x, e)))
        if hub.get('import_accepts_overlay_tenants') == 'no':
            errs.append(C('H6', 'the hub drops the overlay tenants\' routes: change the hub\'s overlay import, or '
                          'set those tenants\' overlay answer to no'))
        elif hub.get('import_accepts_overlay_tenants') != 'yes':
            errs.append(R('H6', 'after the hub lines I showed: does the hub accept the overlay tenants (yes/no)?'))
        if hub.get('overlay_tenant_subnets_unique') == 'no':
            errs.append(R('H7', 'another site advertises an overlay tenant subnet; give those tenants unique subnets'))
        elif hub.get('overlay_tenant_subnets_unique') != 'yes':
            errs.append(R('H7', 'is each overlay tenant subnet unique on the overlay (yes/no)?'))
    return errs


# ------------------------------------------------------------------ T. tenants (networks)
def _check_dns_reach(t, lbl, servers, a, T, q='T8'):
    """Client DNS servers / relay servers that are private must be reachable from that network."""
    errs = []
    hub = a.get('hub') or {}
    hubnets = []
    h5_open = hub.get('present') is True and hub.get('site_prefixes') is None    # H5 not answered yet
    ov_open = 'overlay' not in t or t.get('overlay') is True                      # T11 not answered yet, or yes
    if hub.get('present') is True and isinstance(hub.get('site_prefixes'), list):
        for x in hub['site_prefixes']:
            try:
                hubnets.append(ip.ip_network(x))
            except (ValueError, TypeError):
                pass
    reach = {str(x).lower() for x in (t.get('reach') if isinstance(t.get('reach'), list) else [])}
    for x in servers:
        try:
            ad = ip.ip_address(x)
        except (ValueError, TypeError):
            continue
        own = ad in ip.ip_network(t['subnet'])
        other = []
        for u in T:
            try:
                if u is not t and ad in ip.ip_network(u['subnet']):
                    other.append(u)
            except (ValueError, TypeError, KeyError):
                pass
        in_hub = any(ad in h for h in hubnets)
        if own:                                   # its own subnet (also when that subnet is public)
            continue
        if other and str(other[0]['name']).lower() in reach:
            continue
        if in_hub and t.get('overlay') is True:
            continue
        if other or in_hub:
            pass                                  # a planned subnet it may not reach: unreachable below
        elif ad.is_global:
            if not internet(t):
                errs.append(R(q, '%s: %s is on the Internet, but this tenant has no Internet access' % (lbl, x)))
            continue
        if h5_open and ov_open and not other:     # can still be a hub-site server: settled at H5
            errs.append(R('H5', '%s: %s server %s is private and outside the networks it reaches: it builds once this '
                          'network uses the overlay (T11 yes) and a hub-site prefix (H5) holds it; otherwise change the '
                          '%s answer' % (lbl, q, x, q)))
            continue
        errs.append(R(q, '%s: %s is private and this tenant cannot reach it (not its own subnet, not a tenant it '
                      'may reach, not a hub prefix over the overlay)' % (lbl, x)))
    return errs


OPTION_INT_RANGE = {'int16': (-32768, 32767), 'uint16': (0, 65535), 'int32': (-2147483648, 2147483647),
                    'uint32': (0, 4294967295)}


def option_value_problem(typ, value):
    """T16: why a DHCP option value does not fit its type ('' when it does). ip: one IPv4 address; int16, uint16,
    int32, uint32: an integer in range; boolean: true or false; hex: an even number of hex digits; string: up to 255
    printable characters without quotes, backslashes or angle brackets."""
    v = value
    if typ == 'ip':
        try:
            if ip.ip_address(str(v).strip()).version == 4 and str(v).strip() == str(v):
                return ''
        except ValueError:
            pass
        return 'one IPv4 address'
    if typ in OPTION_INT_RANGE:
        lo, hi = OPTION_INT_RANGE[typ]
        try:
            n = int(str(v), 10) if not isinstance(v, bool) else None
        except ValueError:
            n = None
        return '' if (n is not None and lo <= n <= hi) else 'an integer from %d to %d' % (lo, hi)
    if typ == 'boolean':
        return '' if (v is True or v is False or str(v).lower() in ('true', 'false')) else 'true or false'
    if typ == 'hex':
        return '' if (isinstance(v, str) and re.match(r'^([0-9A-Fa-f]{2})+$', v)) else 'an even number of hex digits'
    if typ == 'string':
        ok = isinstance(v, str) and 1 <= len(v) <= 255 and v.isprintable() and not re.search(r'["\\<>]', v)
        return '' if ok else 'up to 255 printable characters, no quotes, backslashes, < or >'
    return 'unknown type'


def check_tenant(t, pos, a, T):
    """Every T check of one network. A check that needs the subnet (or the gateway and node addresses) is skipped
    while that answer is missing or invalid: its own re-ask comes first; the other checks still run."""
    errs = []
    nm = t.get('name') if isinstance(t.get('name'), str) else ''
    lbl = 'tenant %d (%s)' % (pos, nm or '?')
    if not (2 <= len(nm) <= 24 and TENANT_RE.match(nm)):
        errs.append(R('T1', '%s: 2 to 24 letters, digits, _ and -, starting with a letter, ending with a letter or '
                      'digit (Mist derives <name>_to_wan from it)' % lbl))
    if nm.lower() in RESERVED or nm.lower().startswith('vpn_'):
        errs.append(R('T1', '%s: the name is used by the design or by Mist; pick another' % lbl))
    elif nm.lower() in SECRET_WORD_NAMES or any(nm.lower().endswith('-' + w) for w in SECRET_WORD_NAMES):
        errs.append(R('T1', '%s: %s is or ends in a Junos secret keyword; the read-back check would mask the zone '
                      'lines that carry it; pick another name' % (lbl, nm)))
    v = t.get('vlan_id')
    if not (isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 4094):
        errs.append(R('T2', '%s: VLAN ID 1 to 4094' % lbl))
    net = gw = n1 = n2 = None
    sub = t.get('subnet')
    answered_none = isinstance(sub, str) and sub.strip().lower() == 'none'
    if answered_none or (no_subnet(sub) and 'ipv6' in t and ipv6_source(t) not in ('none',)):
        # T3 answered "no IPv4 subnet" (recorded as "none"), or IPv6 recorded with no subnet: the IPv6-only stop.
        # A subnet that is simply not answered yet is a T3 re-ask (normalize() sets no T10 default without it).
        errs.append(S('T3', '%s: %s; %s' % (lbl, 'IPv6 only' if ipv6_source(t) not in ('none',) else 'no IPv4 subnet',
                                            STOP_MSG['ipv6_only'])))
    elif no_subnet(sub):
        errs.append(R('T3', '%s: not answered yet: the IPv4 subnet, /8 to /29 (a tenant needs the gateway and two node '
                      'addresses)' % lbl))
    else:
        try:
            net = _net4(sub, 8, 29)
        except (ValueError, TypeError) as e:
            errs.append(R('T3', '%s: %s (a tenant needs the gateway and two node addresses: /29 or larger)' % (lbl, e)))
    if net is not None:
        why = special4(net)
        if why:
            errs.append(R('T3', '%s: %s %s' % (lbl, net, why)))
        elif not in_rfc1918(net) and t.get('internet', True) is True:
            pn = t.get('public_nat', 'nat')
            if pn == 'routed':
                errs.append(S('T21', '%s: %s; %s' % (lbl, net, STOP_MSG['public_routed'])))
            elif pn != 'nat':
                errs.append(R('T21', '%s: %s is a public subnet: source NAT to the WAN address (nat) or routed '
                              'without NAT (routed)?' % (lbl, net)))
        try:
            g = ip.ip_address(t.get('gateway'))
            if g not in net or g in (net.network_address, net.broadcast_address):
                errs.append(R('T4', '%s: the gateway must be a host address of %s' % (lbl, net)))
            else:
                gw = g
        except (ValueError, TypeError):
            errs.append(R('T4', '%s: the gateway is not an IPv4 address' % lbl))
    ni = t.get('node_ips')
    if ni is not None and not (isinstance(ni, dict) and set(map(str, ni)) <= {'1', '2'}):
        errs.append(R('T13', '%s: node addresses as {"1": <node 1 address>, "2": <node 2 address>}, or null for the '
                      'default' % lbl))
    elif gw is not None:
        try:
            a1, a2 = node_ip(t, 1), node_ip(t, 2)
            if len({gw, a1, a2}) != 3 or any(x not in net or x in (net.network_address, net.broadcast_address)
                                             for x in (a1, a2)):
                errs.append(R('T13', '%s: node addresses must be two distinct hosts of %s other than the gateway'
                              % (lbl, net)))
            else:
                n1, n2 = a1, a2
        except (ValueError, TypeError, StopIteration):
            errs.append(R('T13', '%s: node addresses invalid' % lbl))
    hosts_ok = n1 is not None                     # subnet, gateway and node addresses all valid
    inet = t.get('internet', True)
    if inet is True and (t.get('preferred_isp') not in (1, 2) or isinstance(t.get('preferred_isp'), bool)):
        errs.append(R('T5', '%s: preferred ISP is 1 or 2 (the other ISP is its backup)' % lbl))
    if inet == 'via-hub':
        errs.append(S('T14', '%s: %s' % (lbl, STOP_MSG['via_hub'])))
    elif not _bool(inet):
        errs.append(R('T14', '%s: Internet access: yes or no' % lbl))
    mode = dhcp_mode(t)
    d = t.get('dhcp') or {}
    if not isinstance(d, dict):
        errs.append(R('T6', '%s: DHCP answers as {mode, start, end, dns_servers, ...} (answers.example.json)' % lbl))
    elif mode not in ('server', 'relay', 'none'):
        errs.append(R('T6', '%s: DHCP: the firewalls serve it, relay it to a server, or none' % lbl))
    elif mode == 'server':
        if hosts_ok:
            try:
                s, e = ip.ip_address(d.get('start')), ip.ip_address(d.get('end'))
                if not (s in net and e in net and s <= e) or s == net.network_address or e == net.broadcast_address:
                    errs.append(R('T7', '%s: the DHCP range must sit inside %s, start <= end' % (lbl, net)))
                elif any(s <= r <= e for r in (gw, n1, n2)):
                    errs.append(R('T7', '%s: the DHCP range must not include the gateway %s or the node addresses %s, '
                                  '%s' % (lbl, gw, n1, n2)))
            except (ValueError, TypeError):
                errs.append(R('T7', '%s: DHCP start and end must be IPv4 addresses (no default range fits %s)'
                              % (lbl, net)))
        dns = d.get('dns_servers')
        if not (isinstance(dns, list) and 1 <= len(dns) <= 3):
            errs.append(R('T8', '%s: one to three DNS servers for the clients' % lbl))
        else:
            for x in dns:
                try:
                    ad = ip.ip_address(x)
                    if ad.version != 4 or ad.is_multicast or ad.is_loopback or ad.is_unspecified:
                        errs.append(R('T8', '%s: %s is not a usable IPv4 unicast address' % (lbl, x)))
                except (ValueError, TypeError):
                    errs.append(R('T8', '%s: %s is not an IPv4 address' % (lbl, x)))
            if net is not None:
                errs += _check_dns_reach(t, lbl, dns, a, T)
        lt = d.get('lease_time')
        if not (isinstance(lt, int) and not isinstance(lt, bool) and 600 <= lt <= 2592000):
            errs.append(R('T9', '%s: lease time in seconds, 600 (10 minutes) to 2592000 (30 days)' % lbl))
        sfx = d.get('dns_suffix') or []
        if not isinstance(sfx, list):
            errs.append(R('T16', '%s: DNS domains as a list' % lbl))
            sfx = []
        for x in sfx:
            if not HOST_RE.match(str(x)):
                errs.append(R('T16', '%s: DNS domain %s is not a domain name' % (lbl, x)))
        opts = d.get('options') or {}
        if not isinstance(opts, dict):
            errs.append(R('T16', '%s: DHCP options as {code: {type, value}}' % lbl))
            opts = {}
        for code, o in opts.items():
            try:
                c = int(code)
            except ValueError:
                c = -1
            if not (1 <= c <= 254) or c in DHCP_OPTION_RESERVED:
                errs.append(R('T16', '%s: DHCP option %s: codes 2-254, not 3, 6, 12, 15, 50-55, 61, 82 (the design or '
                              'the protocol sets those; use the DNS answers for 6 and 15)' % (lbl, code)))
            elif not isinstance(o, dict) or o.get('type') not in DHCP_OPTION_TYPES or o.get('value') in (None, ''):
                errs.append(R('T16', '%s: DHCP option %s needs a type (%s) and a value' %
                              (lbl, code, ', '.join(sorted(DHCP_OPTION_TYPES)))))
            else:
                why = option_value_problem(o['type'], o['value'])
                if why:
                    errs.append(R('T16', '%s: DHCP option %s (%s): %s' % (lbl, code, o['type'], why)))
        seen, macs = set(), set()
        fb = d.get('fixed_bindings') or {}
        if not isinstance(fb, dict):
            errs.append(R('T16', '%s: reservations as {MAC: {ip, name}}' % lbl))
            fb = {}
        for mac, b in fb.items():
            m = re.sub(r'[^0-9a-f]', '', str(mac).lower())
            if len(m) != 12:
                errs.append(R('T16', '%s: reservation %s: MAC address must have 12 hex digits' % (lbl, mac)))
                continue
            if m in macs:
                errs.append(R('T16', '%s: reservation %s: MAC address listed twice' % (lbl, mac)))
            macs.add(m)
            if not isinstance(b, dict):
                errs.append(R('T16', '%s: reservation %s: reservations as {MAC: {ip, name}}' % (lbl, mac)))
                continue
            bn = b.get('name')
            if bn not in (None, '') and not (isinstance(bn, str) and LABEL_RE.match(bn)):
                errs.append(R('T16', '%s: reservation %s: the name is one host label (letters, digits and -, up to 63 '
                              'characters)' % (lbl, mac)))
            if not hosts_ok:
                continue
            try:
                rip = ip.ip_address(b.get('ip'))
                if rip not in net or rip in (gw, n1, n2, net.network_address, net.broadcast_address) or rip in seen:
                    errs.append(R('T16', '%s: reservation %s: a free host address of %s (not the gateway or a node, '
                                  'not used twice)' % (lbl, mac, net)))
                seen.add(rip)
            except (ValueError, TypeError):
                errs.append(R('T16', '%s: reservation %s: IPv4 address missing' % (lbl, mac)))
    elif mode == 'relay':
        srv = d.get('relay_servers')
        if not (isinstance(srv, list) and 1 <= len(srv) <= 4):
            errs.append(R('T17', '%s: one to four DHCP server addresses to relay to' % lbl))
        else:
            for x in srv:
                try:
                    ad = ip.ip_address(x)
                    if ad.version != 4 or (net is not None and ad in net) or not (ad.is_private or ad.is_global) \
                            or ad.is_multicast or ad.is_loopback or ad.is_unspecified:
                        errs.append(R('T17', '%s: %s must be an IPv4 unicast address outside the tenant\'s own subnet'
                                      % (lbl, x)))
                except (ValueError, TypeError):
                    errs.append(R('T17', '%s: %s is not an IPv4 address' % (lbl, x)))
            if net is not None:
                errs += _check_dns_reach(t, lbl, srv, a, T, q='T17')
    src = ipv6_source(t)
    if not isinstance(src, str) or src not in IPV6_SOURCES:
        errs.append(R('T10', '%s: IPv6: none, from ISP 1 or from ISP 2' % lbl))
    elif src == 'both':
        errs.append(S('T10', '%s: %s' % (lbl, STOP_MSG['ipv6_both'])))
    elif src != 'none':
        if not internet(t):
            errs.append(R('T10', '%s: IPv6 here is Internet access over the ISP prefix; a tenant without Internet '
                          'gets no IPv6' % lbl))
        for n in ipv6_isps(t):
            isp = a['isps'][n]
            if isp.get('ipv6_pd') is not True:
                errs.append(R('T10', '%s: IPv6 from ISP %s needs ISP %s prefix delegation (V1)' % (lbl, n, n)))
                continue
            try:
                L = pd_length(isp)
            except (ValueError, TypeError):
                continue
            idx = ipv6_index(t, pos)
            if not (isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx < 2 ** (64 - L)):
                errs.append(R('T18', '%s: /64 number %s does not fit in the ISP %s /%d (0 to %d); give a free '
                              'number' % (lbl, idx, n, L, 2 ** (64 - L) - 1)))
    ov = t.get('overlay', False)
    if not _bool(ov):
        errs.append(R('T11', '%s: overlay to the hub: yes or no' % lbl))
    elif ov and (a.get('hub') or {}).get('present') is not True:
        errs.append(R('T11', '%s: overlay needs a hub (H1 = yes); answer no or add the hub' % lbl))
    if 'ssh' in t and not _bool(t['ssh']):
        errs.append(R('T19', '%s: SSH to the firewalls from this tenant: yes or no' % lbl))
    if 'untagged' in t and not _bool(t['untagged']):
        errs.append(R('T12', '%s: untagged (native VLAN) on the LAN link: yes or no' % lbl))
    names = {str(u.get('name')).lower() for u in T}
    reach = t.get('reach') or []
    if not isinstance(reach, list):
        errs.append(R('T15', '%s: the networks it may reach, as a list' % lbl))
        reach = []
    for r in reach:
        if str(r).lower() == nm.lower():
            errs.append(R('T15', '%s: a tenant reaches its own subnet already; list other tenants' % lbl))
        elif str(r).lower() not in names:
            errs.append(R('T15', '%s: %s is not one of the tenants' % (lbl, r)))
    return errs


def check_tenants(a):
    tenants = a.get('tenants')
    if not isinstance(tenants, list) or len(tenants) == 0:
        return [R('T0', 'at least one tenant network: the pair needs a LAN to protect and a VLAN for its gateway')]
    if not all(isinstance(t, dict) for t in tenants):
        return [R('T0', 'each tenant is an object with its answers')]
    if len(tenants) > MAX_TENANTS:
        return [S('T0', '%d networks: %s' % (len(tenants), STOP_MSG['tenants']))]
    errs = []
    unt = [t for t in tenants if t.get('untagged') is True]
    if len(unt) > 1:
        errs.append(R('T12', 'at most one tenant is untagged (native VLAN) on the LAN link'))
    T = tenant_order(tenants)
    for pos, t in enumerate(T, 1):
        try:
            errs += check_tenant(t, pos, a, T)
        except Exception as e:                    # an answer shape no check foresaw: re-ask, never a traceback
            errs.append(R('schema', 'tenant %d (%s): an answer of this network does not have the shape of '
                          'answers.example.json (%s); record it again in that shape' % (pos, t.get('name'),
                                                                                        type(e).__name__)))
    names = [str(t.get('name', '')).lower() for t in T]
    if len(set(names)) != len(names):
        errs.append(R('T1', 'tenant names must be unique (ignoring case)'))
    vpn = str((a.get('hub') or {}).get('vpn_name') or '').lower()
    if vpn and vpn in names and (a.get('hub') or {}).get('present') is True:
        errs.append(R('T1', 'a tenant may not carry the VPN name %s (Mist names the overlay zone after it)' % vpn))
    vl = [t.get('vlan_id') for t in T]
    if len(set(map(str, vl))) != len(vl):
        errs.append(R('T2', 'VLAN IDs must be unique'))
    for n in ('1', '2'):
        seen = {}
        for pos, t in enumerate(T, 1):
            if n in ipv6_isps(t):
                idx = ipv6_index(t, pos)
                if not isinstance(idx, int) or isinstance(idx, bool):
                    continue                      # check_tenant re-asks T18
                if idx in seen:
                    errs.append(R('T18', 'tenants %s and %s use the same /64 number %s of the ISP %s prefix'
                                  % (seen[idx], t.get('name'), idx, n)))
                seen[idx] = t.get('name')
    alq = (a.get('pair') or {}).get('alq_tenant')
    servers = [t for t in T if dhcp_mode(t) == 'server']
    if alq and str(alq).lower() not in names:
        errs.append(R('T20', '%s is not one of the tenants' % alq))
    elif alq and servers and not any(str(t.get('name')).lower() == str(alq).lower() for t in servers):
        errs.append(R('T20', '%s: the firewalls do not serve DHCP on it; the binding sync runs between the two DHCP '
                      'servers: pick a network where the firewalls serve DHCP (%s)' % (
                          alq, ', '.join(str(t.get('name')) for t in servers))))
    return errs


# ------------------------------------------------------------------ M. management, I. internal
def check_M(mgmt, ip1, ip2):
    mode = mgmt.get('mode', 'static')
    if mode not in ('static', 'static-gw', 'dhcp', 'none'):
        return [R('M1', 'out-of-band network: give it (static), say it has a gateway, say it uses DHCP, or say none')]
    if mode in ('dhcp', 'none'):
        return []
    errs = []
    try:
        n = _net4(mgmt.get('oob_network'), 16, 30)
        why = special4(n)
        if why:
            errs.append(R('M1', 'the out-of-band network %s' % why))
    except (ValueError, TypeError):
        return [R('M1', 'out-of-band network: give it as network/length, /16 to /30 with the host bits zero (for '
                  'example 192.168.100.0/24), say it has a gateway, say it uses DHCP, or say none')]
    try:
        a1, a2 = ip.ip_address(ip1), ip.ip_address(ip2)
        for k, x in (('M2', a1), ('M3', a2)):
            if x not in n or x in (n.network_address, n.broadcast_address):
                errs.append(R(k, '%s is not a host address of %s' % (x, n)))
        if a1 == a2:
            errs.append(R('M2', 'the two mgmt-0 addresses must differ'))
        if mode == 'static-gw':
            g = ip.ip_address(mgmt.get('gateway'))
            if g not in n or g in (a1, a2, n.network_address, n.broadcast_address):
                errs.append(R('M4', 'the gateway must be another host address of %s' % n))
    except (ValueError, TypeError):
        errs.append(R('M2', 'mgmt-0 addresses (and the gateway) must be IPv4 addresses'))
    return errs


def check_I1(block):
    try:
        n = _net4(block, 8, 22)
    except (ValueError, TypeError) as e:
        return [R('I1', '%s (a /22 or larger block)' % e)]
    if not in_rfc1918(n):
        return [R('I1', 'the internal block must be RFC 1918 (it is never advertised; the default is 10.255.0.0/16)')]
    return []


def check_I2(asn, overlay_as=None):
    try:
        a1, a2 = int(asn['1']), int(asn['2'])
    except (KeyError, TypeError, ValueError):
        return [R('I2', 'two AS numbers, node 1 and node 2')]
    errs = []
    for x in (a1, a2):
        if not (64512 <= x <= 65534 or 4200000000 <= x <= 4294967294):
            errs.append(R('I2', '%d: use a private AS number (64512-65534 or 4200000000-4294967294)' % x))
    if a1 == a2:
        errs.append(R('I2', 'the two AS numbers must differ (eBGP between the nodes)'))
    if overlay_as is not None and str(overlay_as) in (str(a1), str(a2)):
        errs.append(R('I2', '%s is the overlay AS Mist uses in this org; pick two other private AS numbers' % overlay_as))
    return errs


# ------------------------------------------------------------------ X. pair, K. secrets, N. names, R. readiness
def check_X(pair):
    errs = []
    for k, q in (('preemption', 'X1'), ('icl_encryption', 'X2')):
        if k in (pair or {}) and not _bool(pair[k]):
            errs.append(R(q, '%s: yes or no' % k.replace('_', ' ')))
    mode = (pair or {}).get('ha_mode', HA_MODE)
    if mode != HA_MODE:
        errs.append(S('X', 'HA form %s requested; %s' % (mode, STOP_MSG['ha_form'])))
    srg = (pair or {}).get('srg_count', 1)
    if srg not in (1, None):
        errs.append(S('X', '%s services-redundancy groups requested; %s' % (srg, STOP_MSG['ha_form'])))
    probe = (pair or {}).get('activeness_probe', 'default')
    if probe not in ('default', None):
        errs.append(S('X', 'activeness probe %s requested; %s' % (probe, STOP_MSG['probe'])))
    return errs


def check_K1(value, kind='encrypted-password'):
    """On the value read_secret() returned (never printed)."""
    v = (value or '').strip()
    if kind == 'ssh-key':
        if not SSHKEY_RE.match(v):
            return [R('K1', 'the file must hold one SSH public key line (ssh-ed25519, ssh-rsa or ecdsa-sha2-...)')]
        return []
    if not HASH_RE.match(v):
        return [R('K1', 'the file must hold only the encrypted root password string ($6$..., $5$... or $1$...), not '
                  'a plain password; copy it from show configuration system root-authentication on a Junos device')]
    return []


def check_K2(value):
    v = (value or '').strip()
    if not v or '\n' in v or re.search(r'["<>]', v):
        return [R('K2', 'the file must hold only the license key, one line, no quotes, < or >')]
    return []


def check_K3(value):
    v = (value or '').strip()
    if not (8 <= len(v) <= 255) or re.search(r'["\\<>\s]', v) or not v.isprintable():
        return [R('K3', 'the ICL pre-shared key: 8 to 255 printable characters, no spaces, quotes or backslashes, '
                  'and no < or >')]
    return []


def check_N1(n1, n2):
    errs = []
    for k, s in (('node 1', n1), ('node 2', n2)):
        if not (isinstance(s, str) and len(s) <= 32 and NAME_RE.match(s)):
            errs.append(R('N1', '%s profile name: up to 32 letters, digits, _ and -, starting and ending with a letter '
                          'or digit' % k))
    if str(n1).lower() == str(n2).lower():
        errs.append(R('N1', 'the two profile names must differ'))
    return errs


OVERLAP_ORDER = ['W3', 'M1', 'I1', 'T3', 'H5']   # the order the intake asks the ranges (SKILL.md step 1)


def planned_ranges(a):
    """[(label, question ID, network)] of every planned IPv4 range already answered and parseable: networks (T3),
    the internal block (I1), the out-of-band network (M1), the hub prefixes (H5) and the WAN subnets (W3). A range
    that does not parse is left out here: its own check asks it again."""
    out = []

    def add(label, q, v, strict=True):
        try:
            n = ip.ip_network(str(v).strip(), strict=strict)
            if n.version == 4:
                out.append((label, q, n))
        except (ValueError, TypeError):
            pass
    for t in a.get('tenants') if isinstance(a.get('tenants'), list) else []:
        if isinstance(t, dict) and not no_subnet(t.get('subnet')):
            add('tenant %s' % t.get('name'), 'T3', t['subnet'])
    if (a.get('internal') or {}).get('block'):
        add('internal block', 'I1', a['internal']['block'])
    m = a.get('mgmt') or {}
    if m.get('mode', 'static') in ('static', 'static-gw') and m.get('oob_network'):
        add('out-of-band network', 'M1', m['oob_network'])
    hub = a.get('hub') or {}
    if hub.get('present') is True and isinstance(hub.get('site_prefixes'), list):
        for p in hub['site_prefixes']:
            add('hub prefix %s' % p, 'H5', p)
    for n in ('1', '2'):
        isp = (a.get('isps') or {}).get(n)
        if isinstance(isp, dict) and isp.get('wan_subnet'):
            add('ISP %s WAN subnet' % n, 'W3', isp['wan_subnet'])
    return out


def check_overlaps(a):
    """No two planned IPv4 ranges overlap (networks, internal block, out-of-band, hub prefixes, WAN subnets). Runs on
    the ranges answered so far (call it after T3, W3, I1, M1 and H5); each overlap carries the question ID of the
    range asked later (W3 < M1 < I1 < T3 < H5), and the message names both ranges."""
    try:
        a = normalize(a)                          # idempotent; a raw answers file is read with its defaults
    except Exception:                             # unreadable shape: validate() reports it as schema
        return []
    nets = planned_ranges(a)
    errs = []
    same_up = (a.get('isps') or {}).get('same_upstream') is True
    for i in range(len(nets)):
        for j in range(i + 1, len(nets)):
            if nets[i][1] == 'W3' and nets[j][1] == 'W3' and (same_up or nets[i][2] == nets[j][2]):
                continue                          # the same range on both ISPs: W5 decides (yes and no both build)
            if nets[i][2].overlaps(nets[j][2]):
                q = max(nets[i][1], nets[j][1], key=OVERLAP_ORDER.index)
                errs.append(R(q, '%s (%s) overlaps %s (%s); change one of them' %
                              (nets[i][0], nets[i][2], nets[j][0], nets[j][2])))
    return errs


def _example_paths(o, path=''):
    """JSON paths of every key or string value that still holds example text <...> (answers.example.json)."""
    out = []
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ('_fixture', '_about'):
                continue
            p = '%s.%s' % (path, k) if path else str(k)
            if EXAMPLE_RX.search(str(k)):
                out.append(p)
            out += _example_paths(v, p)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            out += _example_paths(v, '%s[%d]' % (path, i))
    elif isinstance(o, str) and EXAMPLE_RX.search(o):
        out.append(path)
    return out


def check_reads(a):
    """The values the agent reads from Mist (SKILL.md step 2), in the forms Mist gives them, and no example text:
    org_id and site_id (UUIDs), each node's mac (12 lowercase hex digits, not a documentation MAC) and device_id
    (00000000-0000-0000-1000-<mac>), and per hub path hub_mac, hub_device_id and hub_site_id. A value not read yet
    is a problem of its question (A3, B1, B2, H4): expected until that group is asked."""
    errs = []
    ex = _example_paths(a)
    if ex:
        errs.append(R('schema', 'answers.json holds example text <...> at %s: answers.json starts empty and holds only '
                      'the answers given and the values read from Mist (never a copy of answers.example.json); record '
                      'those values' % ', '.join(ex[:8])))
    m = a.get('mist') or {}
    if not UUID_RE.match(str(m.get('org_id') or '')):
        errs.append(R('A3', 'mist.org_id: not read yet, or not an org id as GET /self lists it: record the org the '
                      'customer picks'))
    s = a.get('site') or {}
    if not UUID_RE.match(str(s.get('site_id') or '')):
        errs.append(R('B1', 'site.site_id: not read yet, or not a site id as the inventory lists it (SKILL.md step '
                      '2.3)'))
    for n in ('1', '2'):
        nd = (a.get('nodes') or {}).get(n) or {}
        mac = str(nd.get('mac') or '')
        if not MAC_RE.match(mac):
            errs.append(R('B2', 'nodes.%s.mac: not read yet, or not 12 lowercase hex digits as the inventory lists it'
                          % n))
        elif DOC_MAC_RE.match(mac):
            errs.append(R('B2', 'nodes.%s.mac %s is a documentation MAC address: record the MAC the inventory lists '
                          'for that serial' % (n, mac)))
        elif nd.get('device_id') != '00000000-0000-0000-1000-' + mac:
            errs.append(R('B2', 'nodes.%s.device_id: not read yet, or not the inventory id of that MAC '
                          '(00000000-0000-0000-1000-<mac>)' % n))
    hub = a.get('hub') or {}
    if hub.get('present') is True and hub.get('in_mist') is not False:
        paths = hub_paths(hub)
        for p in paths if isinstance(paths, list) else []:
            if not isinstance(p, dict):
                continue
            hm = str(p.get('hub_mac') or '')
            if MAC_RE.match(hm) and DOC_MAC_RE.match(hm):
                errs.append(R('H4', 'path %s: hub MAC %s is a documentation MAC address: record the hub device\'s '
                              'inventory MAC (SKILL.md step 2.6)' % (p.get('path'), hm)))
            elif MAC_RE.match(hm) and (p.get('hub_device_id') != '00000000-0000-0000-1000-' + hm
                                       or not UUID_RE.match(str(p.get('hub_site_id') or ''))):
                errs.append(R('H4', 'path %s: hub_device_id and hub_site_id: not read yet, or not the inventory '
                              'record of hub MAC %s (SKILL.md step 2.6)' % (p.get('path'), hm)))
    return errs


READINESS = ['isp_dhcp', 'modem_accepts_new_mac', 'lan_switch', 'cabling', 'mgmt0_unplugged', 'device_names_set']


def wan_range_unknown(a, n):
    """W3 answered unknown (or not answered) for ISP n: the generator cannot check that range, so the customer
    checks it before the build (site_readiness.isp<n>_wan_range_clear, intake R9)."""
    i = (a.get('isps') or {}).get(n) or {}
    return not i.get('wan_subnet')


def check_R(a):
    r = a.get('site_readiness') or {}
    errs = []
    keys = list(READINESS)
    for n in ('1', '2'):
        if a['isps'][n].get('ipv6_pd') is True:
            keys.append('isp%s_dhcpv6' % n)
    for k in keys:
        v = r.get(k)
        if v == 'no':
            errs.append(C('R', 'site_readiness.%s is no: the build waits until it is yes' % k))
        elif v != 'yes':
            errs.append(R('R', 'site_readiness.%s: yes or no' % k))
    for n in ('1', '2'):
        if not wan_range_unknown(a, n):
            continue
        k = 'isp%s_wan_range_clear' % n
        what = ('not in the factory ge-0/0/3 subnet %s (ge-0/0/3 has a role on node %s) and ' % (FACTORY_GE3_TEXT, n)
                if ge3_cabled(a['nodes'], n) else '')
        v = r.get(k)
        if v == 'no':
            errs.append(R('W3', 'ISP %s: site_readiness.%s is no: give the range ISP %s hands out (W3), so that the '
                          'overlap checks can run on it' % (n, k, n)))
        elif v != 'yes':
            errs.append(R('R', 'site_readiness.%s: ISP %s range is unknown (W3), so the generator cannot check it: '
                          'yes once the address range ISP %s hands out is checked (a laptop on that hand-off, or the '
                          'ISP router\'s LAN settings) and is %soverlaps none of the planned ranges (networks, '
                          'internal block, out-of-band network, hub prefixes); or give the range at W3' % (k, n, n, what)))
    return errs


def check_security_services(req):
    if req in (None, [], ''):
        return []
    if not isinstance(req, list):
        req = [req]
    names = [SECURITY_SERVICE_NAMES.get(str(x).lower(), str(x)) for x in req]
    return [S('S3', '%s requested in the first push; %s' % (', '.join(names), STOP_MSG['security_services']))]


# ------------------------------------------------------------------ validate everything
def validate(answers, fixture=None):
    """Every check of the intake on one answers file. Returns [] when it builds; else [{q, kind, msg}] with kind
    reask (ask that question again), stop (the design cannot be built as answered; the message names the
    alternative) or precondition (the org or the site must change first). fixture=None honors
    answers['_fixture']['allow_documentation_ipv6_prefix'] (repository test files only): it accepts documentation
    IPv6 prefixes and leaves out check_reads() (the test files carry example ids and documentation MACs)."""
    if not isinstance(answers, dict):
        return [R('schema', 'the answers file must hold one JSON object shaped like answers.example.json')]
    if fixture is None:
        fx = answers.get('_fixture')
        fixture = isinstance(fx, dict) and bool(fx.get('allow_documentation_ipv6_prefix'))
    try:
        a = normalize(answers)
    except Exception as e:                        # unreadable shape
        return [R('schema', 'the answers file does not have the v2 shape (%s)' % type(e).__name__)]
    out = []
    if a.get('schema') not in (None, SCHEMA):
        out.append(R('schema', 'answers file schema is %s; this script reads %s' % (a.get('schema'), SCHEMA)))
    bad = [k for k in ('mist', 'site', 'nodes', 'isps', 'services', 'hub', 'pair', 'mgmt', 'internal',
                       'site_readiness') if not isinstance(a.get(k), dict)]
    if bad:
        return out + [R('schema', '%s must be an object (answers.example.json)' % ', '.join(bad))]
    for k in ('nodes', 'isps'):
        if not all(isinstance(a[k].get(n), dict) for n in ('1', '2')):
            return out + [R('schema', '%s.1 and %s.2 must both be present' % (k, k))]
    if not all(isinstance(a['nodes'][n].get('ports'), dict) for n in ('1', '2')):
        return out + [R('P1', 'nodes.<n>.ports must hold wan, lan, lan_lacp, icl and icd')]
    G = lambda q, fn, *args: _guard(q, fn, *args)
    out += G('A1', check_A1, a['mist'].get('portal_host'))
    if not check_A1(a['mist'].get('portal_host')) and a['mist'].get('api_host') not in (None, '') and \
            a['mist'].get('api_host') != api_host(a['mist'].get('portal_host')):
        out.append(R('A1', 'mist.api_host %s is not the API host of the portal %s (%s): the token goes only to the '
                     'API host of the customer\'s own Mist cloud' % (a['mist'].get('api_host'),
                                                                     norm_portal(a['mist'].get('portal_host')),
                                                                     api_host(a['mist'].get('portal_host')))))
    out += G('A3', check_A3, a['mist'].get('access'))
    out += G('B2', check_B2, a['nodes']['1'].get('serial'), a['nodes']['2'].get('serial'),
             (a['nodes']['1'].get('model'), a['nodes']['2'].get('model')))
    out += G('B4', check_B4, a.get('release'), a['site_readiness'].get('factory_default'))
    out += G('P1', check_ports, a['nodes'])
    out += G('W1', check_W, a['isps'], a['nodes'])
    out += G('S1', check_S1, a['services'].get('dns_servers'))
    out += G('S2', check_S2, a['services'].get('ntp_servers'))
    out += G('V1', check_V, a['isps'], fixture)
    out += G('S3', check_security_services, a.get('security_services'))
    T = tenant_order(a['tenants']) if isinstance(a['tenants'], list) and all(isinstance(t, dict) for t in a['tenants']) else []
    out += G('H1', check_hub, a['hub'], sum(1 for t in T if t.get('overlay') is True))
    out += G('T0', check_tenants, a)
    out += G('M1', check_M, a['mgmt'], a['nodes']['1'].get('mgmt_ip'), a['nodes']['2'].get('mgmt_ip'))
    out += G('I1', check_I1, a['internal'].get('block'))
    out += G('I2', check_I2, a['internal'].get('icd_asn'),
             a['hub'].get('overlay_as') if a['hub'].get('present') is True else None)
    out += G('X1', check_X, a['pair'])
    out += G('N1', check_N1, a['nodes']['1'].get('profile_name'), a['nodes']['2'].get('profile_name'))
    for n in ('1', '2'):
        nd = a['nodes'][n]
        if not (nd.get('root_hash_file') or nd.get('root_ssh_key_file')):
            out.append(R('K1', 'node %s: Junos refuses a commit without root authentication: give the file with the '
                         'encrypted root password (or an SSH public key for root)' % n))
    if a['pair'].get('icl_encryption') is True and not a['pair'].get('icl_psk_file'):
        out.append(R('K3', 'ICL encryption needs the file with the pre-shared key'))
    if a.get('profiles_method', 'api') not in ('api', 'ui-import'):
        out.append(R('N2', 'build the profiles by API or by Hub Profile import in the Mist UI'))
    out += G('T3', check_overlaps, a)
    out += G('R', check_R, a)
    out += G('schema', check_existing, a, T)
    if not fixture:
        out += G('schema', check_reads, a)
    return out


def _guard(q, fn, *args):
    """Run one check; an answer shape it does not foresee is a re-ask of its question (never a traceback)."""
    try:
        return fn(*args)
    except Exception as e:
        return [R(q, 'an answer of this question does not have the shape of answers.example.json (%s in %s); '
                  'record it again in that shape' % (type(e).__name__, fn.__name__))]


def planned_names(a, T):
    """Names of the planned org objects and profiles (the names existing.reuse may hold)."""
    names = [str(t.get('name')) for t in T] + ['ICD']
    if (a.get('hub') or {}).get('present') is True and any(t.get('overlay') is True for t in T):
        names.append('HUB-SITE-NETS')
    return names + [str(a['nodes'][n].get('profile_name')) for n in ('1', '2')]


def check_existing(a, T):
    """existing.reuse: the planned objects that already exist in the org equal to the plan (SKILL.md step 3.1)."""
    ex = a.get('existing')
    reuse = ex.get('reuse') if isinstance(ex, dict) else None
    if not isinstance(reuse, list):
        return [R('schema', 'existing.reuse: a list of planned object names (the objects the org already holds equal '
                  'to the plan)')]
    known = {x.lower() for x in planned_names(a, T)}
    return [R('schema', 'existing.reuse: %s is not a planned object or profile name' % x)
            for x in reuse if str(x).lower() not in known]


def reused(a, name):
    return str(name).lower() in {str(x).lower() for x in ((a.get('existing') or {}).get('reuse') or [])}


def exit_code(problems):
    if not problems:
        return 0
    return 2 if any(p['kind'] == 'stop' for p in problems) else 1


# ------------------------------------------------------------------ template engine
class _Omit(object):
    pass


OMIT = _Omit()
TOKEN_RX = re.compile(r'\{([a-z0-9_]+)\}')


def load_template(path=None):
    with open(path or TEMPLATE_PATH) as f:
        return json.load(f)


def subst(obj, ctx):
    """Copy of a template object with {tokens} filled from ctx. A string that is exactly one token takes the
    value as it is (list, dict, number); a None value drops the key. Other strings get str() values."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            r = subst(v, ctx)
            if r is not OMIT:
                out[k] = r
        return out
    if isinstance(obj, list):
        return [x for x in (subst(v, ctx) for v in obj) if x is not OMIT]
    if isinstance(obj, str):
        m = TOKEN_RX.fullmatch(obj)
        if m:
            v = ctx[m.group(1)]
            return OMIT if v is None else copy.deepcopy(v)
        return TOKEN_RX.sub(lambda mm: str(ctx[mm.group(1)]), obj)
    return copy.deepcopy(obj)


def fill_line(line, ctx):
    def val(m):
        v = ctx[m.group(1)]
        if v is None:
            raise ValueError('template token {%s} has no value for this plan' % m.group(1))
        return str(v)
    return TOKEN_RX.sub(val, line)


# ------------------------------------------------------------------ derive (every derived value)
def derive(answers):
    """All derived values of the plan, from a valid answers file. T order = the untagged tenant first, then the
    others in answer order (VIP n = T position n). The Internet policy tenant list and the dhcpd_config keys keep
    the reference order [t2, t3, t1, t4..] filtered to the tenants they hold."""
    a = normalize(answers)
    T = tenant_order(a['tenants'])
    lay = internal_layout(a['internal']['block'])
    hub = a['hub']
    hub_on = hub.get('present') is True
    paths = hub_paths(hub) if hub_on else []
    ssh = {t['name'] for t in ssh_tenants(T)}
    alq = alq_tenant(a, T)
    rows = []
    for pos, t in enumerate(T, 1):
        net = ip.ip_network(t['subnet'])
        d = t.get('dhcp') or {}
        r = {'pos': pos, 'name': t['name'], 'vlan_id': t['vlan_id'], 'untagged': t.get('untagged') is True,
             'unit': 0 if t.get('untagged') is True else t['vlan_id'], 'subnet': str(net), 'plen': net.prefixlen,
             'gateway': str(ip.ip_address(t['gateway'])), 'node_ip': {'1': str(node_ip(t, 1)), '2': str(node_ip(t, 2))},
             'preferred_isp': t.get('preferred_isp'), 'internet': internet(t), 'dhcp_mode': dhcp_mode(t), 'dhcp': d,
             'overlay': hub_on and t.get('overlay') is True, 'ssh': t['name'] in ssh,
             'reach': [u['name'] for u in T if str(u['name']).lower() in {str(x).lower() for x in t.get('reach') or []}],
             'v6': {}, 'public': not in_rfc1918(net)}
        for n in ipv6_isps(t):
            isp = a['isps'][n]
            idx = ipv6_index(t, pos)
            p = isp.get('delegated_prefix')
            if p and p != 'unknown':
                pn = ip.ip_network(p)
                s64 = ip.ip_network((int(pn.network_address) + idx * (1 << 64), 64))
                r['v6'][n] = {'index': idx, 'net': str(s64), 'addr': str(s64.network_address + 1 + int(n))}
            else:
                r['v6'][n] = {'index': idx, 'net': None, 'addr': None}
        rows.append(r)
    ot = [r for r in rows if r['overlay']]
    srv = any(r['dhcp_mode'] == 'server' for r in rows)
    extra = [r['subnet'] for r in rows if r['public']]
    if hub_on and ot:
        extra += [str(ip.ip_network(p)) for p in hub.get('site_prefixes') or [] if not in_rfc1918(ip.ip_network(p))]
    vpn = hub.get('vpn_name') if hub_on else None
    d = {'a': a, 'T': rows, 'layout': lay, 'hub_on': hub_on, 'paths': paths, 'vpn': vpn,
         'overlay_tenants': [r['name'] for r in ot], 'lp_policy': (ot[0]['name'] + '-LP') if ot else None,
         'hub_prefixes': [str(ip.ip_network(p)) for p in hub.get('site_prefixes') or []] if (hub_on and ot) else [],
         'ike_gateways': ['%s_to_%s_%s' % (WAN_NAME, p.get('hub_mac'), p.get('hub_wan_port_name')) for p in paths],
         'spoke_paths': ['%s.%s' % (p.get('path'), vpn) for p in paths],
         'extra_excepts': extra, 'dhcp_server': srv, 'alq': alq['name'] if (alq and srv) else None,
         'routing_form': 'VR lan (overlay)' if hub_on else 'default routing instance (no overlay)', 'nodes': {}}
    for n in ('1', '2'):
        peer = '2' if n == '1' else '1'
        i, j = int(n) - 1, int(peer) - 1
        nd = a['nodes'][n]
        p = nd['ports']
        isp = a['isps'][n]
        pd = isp.get('ipv6_pd') is True
        pd_known = pd and isp.get('delegated_prefix') not in (None, 'unknown')
        steered = [r for r in rows if r['internet'] and str(r['preferred_isp']) == peer]
        d['nodes'][n] = {
            'n': n, 'peer': peer, 'serial': nd.get('serial'), 'host': nd.get('mist_device_name'),
            'profile_name': nd['profile_name'], 'wan_port': p['wan'], 'lan': list(p['lan']),
            'lan_lacp': p.get('lan_lacp', True) is True, 'lan_if': 'ae0' if p.get('lan_lacp', True) is True else p['lan'][0],
            'lan_key': ','.join(p['lan']), 'icl_port': p['icl'], 'icd_port': p['icd'],
            'icl_local': str(lay['icl'][i]), 'icl_peer': str(lay['icl'][j]),
            'lo0_local': str(lay['lo0'][i]), 'lo0_peer': str(lay['lo0'][j]),
            'icd_local': str(lay['icd'][i]), 'icd_peer': str(lay['icd'][j]),
            'signal_active': str(lay['signal'][0]), 'signal_backup': str(lay['signal'][1]),
            'priority': 200 if n == '1' else 100, 'asn': str(a['internal']['icd_asn'][n]),
            'peer_asn': str(a['internal']['icd_asn'][peer]),
            'steered': [r['name'] for r in steered], 'steered_rows': steered,
            'ipv6_pd': pd, 'ipv6_prefix_known': pd_known,
            'pd_prefix': str(ip.ip_network(isp['delegated_prefix'])) if pd_known else None,
            'pd_length': pd_length(isp) if pd else None,
            'v6_rows': [r for r in rows if n in r['v6']] if pd else [],
            'alq_peer': str(node_ip(alq, int(peer))) if (alq and srv) else None,
            'root_password': bool(nd.get('root_hash_file')), 'root_ssh_key': bool(nd.get('root_ssh_key_file')),
            'license': bool(nd.get('license_key_file')), 'mgmt_ip': nd.get('mgmt_ip'),
        }
    return d


PROVEN_TEXT = ('the reference design of the paper on an SRX400 pair, Junos OS Evolved %s: both nodes from factory '
               'default to their Hub Profiles with nothing typed, MNHA formed, and the verification of paper section 6 '
               'passed. Its structure: six networks, one untagged; per-network ISP preference on both ISPs; DHCP from '
               'the firewalls on every network; a hub on one path of a hub-and-spoke VPN with one overlay network; '
               'IPv6 from ISP 1 on ISP-1 networks (/60, prefix known and stable); the default ports (WAN ge-0/0/2, a '
               'one-port LACP LAN on ge-0/0/3, HA link ge-0/0/4, transit link ge-0/0/5); ISP leases held for 10 '
               'minutes; mgmt-0 static without a gateway; a root password hash on both nodes and a license key on '
               'node 2; preemption and HA link encryption off; an org admin token; profiles created by API; no site '
               'gateway template. Also run on the same pair and release: four networks with the HA link on ge-0/0/5 '
               'and the transit link on ge-0/0/4, built by this skill from the intake to the verification' % RELEASE_BASE)


def hardware_status(d):
    """The structures of this plan beyond the reference design (the pair did not run them); the generator builds them
    from the same reference lines. [] = the plan uses only the reference structure (values differ, the lines and keys
    are those of the reference pair). plan.md lists them under 'Beyond the reference design' and SKILL.md step 3.2
    names them before the yes."""
    a, T = d['a'], d['T']
    out = []

    def add(x):
        if x not in out:
            out.append(x)
    if len(T) not in (4, 6):
        add('%d network%s (the pair ran 4 and 6)' % (len(T), '' if len(T) == 1 else 's'))
    if [r['name'] for r in T if r['public']]:
        add('a public network subnet with source NAT (%s)' % ', '.join(r['name'] for r in T if r['public']))
    if not any(r['untagged'] for r in T):
        add('no untagged network')
    ssh = [r['name'] for r in T if r['ssh']]
    if ssh != [T[0]['name']]:
        add('SSH to the firewalls from %s' % (', '.join(ssh) if ssh else 'no network (mgmt-0 only)'))
    if d['alq'] and d['alq'] != T[0]['name']:
        add('DHCP binding sync on %s (not the first network)' % d['alq'])
    inet = [r for r in T if r['internet']]
    prefs = {r['preferred_isp'] for r in inet}
    if inet and prefs != {1, 2}:
        add('every Internet network prefers ISP %s (no steering on one node)' % '/'.join(str(x) for x in sorted(prefs)))
    if len(inet) != len(T):
        add('a network without Internet access (%s)' % ', '.join(r['name'] for r in T if not r['internet']))
    if any(r['reach'] for r in T):
        add('reach between networks (%s)' % ', '.join('%s to %s' % (r['name'], '/'.join(r['reach']))
                                                      for r in T if r['reach']))
    relay = [r['name'] for r in T if r['dhcp_mode'] == 'relay']
    if relay:
        add('DHCP relay (%s): both nodes are on the VLAN and both relay a client request' % ', '.join(relay))
    if any(r['dhcp_mode'] == 'none' for r in T):
        add('a network without DHCP (%s)' % ', '.join(r['name'] for r in T if r['dhcp_mode'] == 'none'))
    if any(r['dhcp_mode'] == 'server' and any((r['dhcp'] or {}).get(k) for k in ('options', 'fixed_bindings', 'dns_suffix'))
           for r in T):
        add('DHCP options, reservations or client domain names')
    v6 = [r for r in T if r['v6']]
    if any('1' in r['v6'] and r['preferred_isp'] == 2 for r in v6):
        add('IPv6 from ISP 1 on a network that prefers ISP 2')
    if a['isps']['2'].get('ipv6_pd') is True or any('2' in r['v6'] for r in v6):
        add('IPv6 prefix delegation from ISP 2 (IPv6 served by node 2)')
    for n in ('1', '2'):
        nd = d['nodes'][n]
        if nd['ipv6_pd'] and (nd['pd_length'] != 60 or any(t.get('ipv6_index') is not None for t in a['tenants']
                                                            if isinstance(t, dict))):
            add('IPv6 delegation length /%s or a /64 number of your own' % nd['pd_length'])
        if nd['ipv6_pd'] and not nd['ipv6_prefix_known']:
            add('IPv6 prefix known only after onboarding (two-step build, SKILL.md step 7.7)')
        if nd['ipv6_pd'] and a['isps'][n].get('prefix_stable') == 'accept-manual-update':
            add('a delegated prefix that can change, updated by hand (SKILL.md step 7.7)')
    hub = a['hub']
    if not d['hub_on']:
        add('no hub (default routing instance, no overlay)')
    else:
        if len(d['overlay_tenants']) == 0:
            add('a hub with no overlay network (the pair joins the VPN only; SKILL.md step 4.5 checks the render)')
        elif len(d['overlay_tenants']) > 1:
            add('%d overlay networks' % len(d['overlay_tenants']))
        if hub.get('vpn_name') != 'OrgOverlay' or any(x.get('hub_wan_port_name') != 'wan' for x in d['paths']):
            add('a VPN name other than OrgOverlay or a hub WAN port name other than wan')
        if len(d['paths']) > 1:
            add('%d hub paths' % len(d['paths']))
        if any(not in_rfc1918(ip.ip_network(x)) for x in d['hub_prefixes']):
            add('a public hub-site prefix')
    proven_ports = ({'wan': 'ge-0/0/2', 'lan': ['ge-0/0/3'], 'icl': 'ge-0/0/4', 'icd': 'ge-0/0/5'},
                    {'wan': 'ge-0/0/2', 'lan': ['ge-0/0/3'], 'icl': 'ge-0/0/5', 'icd': 'ge-0/0/4'})
    port_sets = [{k: a['nodes'][n]['ports'].get(k) for k in proven_ports[0]} for n in ('1', '2')]
    if port_sets[0] != port_sets[1] or port_sets[0] not in proven_ports or \
            any(a['nodes'][n]['ports'].get('lan_lacp', True) is not True for n in ('1', '2')):
        add('ports other than the defaults (the zero-touch lease on the WAN port of P2, the roles of P3 to P5)')
    for n in ('1', '2'):
        pt = a['nodes'][n]['ports']
        if len(pt.get('lan') or []) > 1:
            add('a LAN LAG of more than one port')
        if pt.get('lan_lacp', True) is False:
            add('a plain LAN port without LACP')
    if a['isps'].get('same_upstream') is True:
        add('one upstream router for both ISPs')
    for n in ('1', '2'):
        i = a['isps'][n]
        if i.get('lease_behavior') == 'held' and isinstance(i.get('lease_seconds'), int) and \
                LEASE_PROVEN_SECONDS < i['lease_seconds'] <= LEASE_MAX_SECONDS:
            add('ISP %s holds its address for %d minutes (the 13-minute limit is derived from the timeline measured '
                'with 10 minutes)' % (n, i['lease_seconds'] // 60))
        if i.get('lease_behavior') == 'new-address':
            add('ISP %s gives a new address at once after the push' % n)
    asn = a['internal']['icd_asn']
    try:
        if any(int(asn[k]) > 65535 for k in ('1', '2')):
            add('4-byte transit-link AS numbers')
    except (ValueError, TypeError, KeyError):
        pass
    if a['mgmt'].get('mode', 'static') in ('static-gw', 'dhcp'):
        add('mgmt-0 %s (management VRF)' % ('with a gateway' if a['mgmt']['mode'] == 'static-gw' else 'by DHCP'))
    if d['nodes']['1']['license']:
        add('a license key on node 1')
    if any(d['nodes'][n]['root_ssh_key'] for n in ('1', '2')):
        add('a root SSH key%s' % ('' if all(d['nodes'][n]['root_password'] for n in ('1', '2'))
                                  else ' (a node without a root password hash)'))
    if a['pair'].get('preemption') is True:
        add('preemption (SRG1 returns to node 1; SKILL.md step 7.2 reads the time it takes)')
    if a['pair'].get('icl_encryption') is True:
        add('HA link encryption (its lines and the two ha-link-encryption show commands of SKILL.md step 7.4)')
    if not release_proven(a.get('release')):
        add('release %s (the design ran on %s)' % (_norm_release(a.get('release')), RELEASE_BASE))
    if a['site'].get('gatewaytemplate_id'):
        add('a site gateway template (the Hub Profiles are meant to take its place; SKILL.md step 4.5 checks the render)')
    if a['mist'].get('access') == 'msp-admin':
        add('an MSP or org-group admin token (API access only)')
    if a.get('profiles_method') == 'ui-import':
        add('profiles imported in the Mist UI')
    if a['services'].get('dns_servers') == []:
        add('firewall DNS from the ISP')
    return out


# ------------------------------------------------------------------ build: Additional CLI
def _iter_items(name, d, nd):
    rows = d['T']
    if name == 'tenants_t1_last':
        return [{'name': r['name']} for r in rows[1:] + rows[:1]]
    if name == 'ssh_tenants':
        return [{'name': r['name']} for r in rows if r['ssh']]
    if name == 'vip_tenants':
        return [{'vip': r['pos'], 'gateway': r['gateway'], 'plen': r['plen'], 'unit': r['unit']} for r in rows]
    if name == 'steered_tenants':
        return [{'subnet': r['subnet'], 'unit': r['unit']} for r in nd['steered_rows']]
    if name == 'extra_excepts':
        return [{'prefix': x} for x in d['extra_excepts']]
    if name == 'internet_tenants':
        return [{'name': r['name']} for r in rows if r['internet']]
    if name == 'ipv6_tenants':
        n = nd['n']
        return [{'name': r['name'], 'unit': r['unit'], 'v6_addr': r['v6'][n]['addr'], 'v6_net': r['v6'][n]['net']}
                for r in nd['v6_rows']]
    if name == 'hub_paths':
        return [{'ike_gateway': g} for g in d['ike_gateways']]
    raise KeyError('unknown iterator %s' % name)


def _conditions(d, nd):
    a = d['a']
    return {
        'dhcp_server': d['dhcp_server'], 'preemption': a['pair'].get('preemption') is True,
        'icl_encryption': a['pair'].get('icl_encryption') is True, 'steering': bool(nd['steered_rows']),
        'internet_any': any(r['internet'] for r in d['T']), 'ipv6_pd': nd['ipv6_pd'],
        'ipv6_prefix_known': nd['ipv6_prefix_known'], 'hub': d['hub_on'], 'overlay_any': bool(d['overlay_tenants']),
        'root_password': nd['root_password'], 'root_ssh_key': nd['root_ssh_key'], 'license': nd['license'],
    }


def build_cli(d, n, template, trace=None):
    """Additional CLI lines of node n. trace (a list) receives the template entry index of every line."""
    nd = d['nodes'][n]
    ctx = {'n': n, 'peer': nd['peer'], 'icl_port': nd['icl_port'], 'icl_local': nd['icl_local'],
           'icl_peer': nd['icl_peer'], 'lo0_local': nd['lo0_local'], 'lo0_peer': nd['lo0_peer'],
           'signal_active': nd['signal_active'], 'signal_backup': nd['signal_backup'], 'priority': nd['priority'],
           'lan_if': nd['lan_if'], 'wan_port': nd['wan_port'], 'pd_length': nd['pd_length'],
           'pd_prefix': nd['pd_prefix'], 'alq_peer': nd['alq_peer'], 'vpn': d['vpn'], 'lp_policy': d['lp_policy']}
    cond = _conditions(d, nd)
    out = []
    for k, e in enumerate(template['cli']):
        if not all(cond[c] for c in e.get('when', [])):
            continue
        lines = e['lines_no_hub'] if (not d['hub_on'] and 'lines_no_hub' in e) else e['lines']
        items = _iter_items(e['each'], d, nd) if e.get('each') else [{}]
        for it in items:
            c = dict(ctx)
            c.update(it)
            for ln in lines:
                out.append(fill_line(ln, c))
                if trace is not None:
                    trace.append(k)
    return out


# ------------------------------------------------------------------ build: native keys
def build_profile(d, n, template, trace=None):
    a = d['a']
    nat = template['native']
    nd = d['nodes'][n]
    rows = d['T']
    hub_on = d['hub_on']
    vpn_paths = {sp: copy.deepcopy(nat['vpn_path']) for sp in d['spoke_paths']} if hub_on else {}
    wan = subst(nat['wan_port'], {'wan_type6': 'dhcp' if nd['ipv6_pd'] else None, 'vpn_paths': vpn_paths})
    untagged = [r['name'] for r in rows if r['untagged']]
    lan = subst(nat['lan_port_lacp'] if nd['lan_lacp'] else nat['lan_port_plain'],
                {'lan_networks': [r['name'] for r in rows if not r['untagged']],
                 'port_network': untagged[0] if untagged else None})
    icd = subst(nat['icd_port'], {'peer': nd['peer']})
    port_config = {nd['wan_port']: wan, nd['lan_key']: lan, nd['icd_port']: icd}

    ip_configs = {}
    for r in rows:
        ip_configs[r['name']] = subst(nat['ip_config'], {'ip': r['node_ip'][n], 'plen': r['plen']})
    ip_configs['ICD'] = subst(nat['ip_config'], {'ip': nd['icd_local'], 'plen': 30})

    by_name = {r['name']: r for r in rows}
    dh_rows = [by_name[t] for t in [x['name'] for x in legacy_order(rows)]
               if by_name[t]['dhcp_mode'] in ('server', 'relay')]
    if dh_rows:
        dhcpd = {'enabled': True}
        for r in dh_rows:
            dd = r['dhcp']
            if r['dhcp_mode'] == 'server':
                fb = {}
                for mac, b in (dd.get('fixed_bindings') or {}).items():
                    m = re.sub(r'[^0-9a-f]', '', str(mac).lower())
                    fb[m] = {k: v for k, v in (('ip', b.get('ip')), ('name', b.get('name'))) if v not in (None, '')}
                opts = {str(c): {'type': o['type'], 'value': o['value']} for c, o in (dd.get('options') or {}).items()}
                dhcpd[r['name']] = subst(nat['dhcpd_local'], {
                    'start': dd['start'], 'end': dd['end'], 'gateway': r['gateway'],
                    'dns_servers': list(dd['dns_servers']), 'options': opts, 'lease_time': dd['lease_time'],
                    'fixed_bindings': fb, 'dns_suffix': list(dd.get('dns_suffix') or []) or None})
            else:
                dhcpd[r['name']] = subst(nat['dhcpd_relay'], {'servers': list(dd['relay_servers'])})
    else:
        dhcpd = {'enabled': False}

    pp = {'wan': copy.deepcopy(nat['path_wan']), 'ICD': copy.deepcopy(nat['path_icd'])}
    if hub_on and d['overlay_tenants']:
        pp[d['vpn']] = subst(nat['path_vpn'], {'vpn_path_list': [subst(nat['path_vpn_item'], {'spoke_path': sp})
                                                                 for sp in d['spoke_paths']]})
    dests = [r for r in rows if any(r['name'] in x['reach'] for x in rows)]
    for r in dests:
        pp['LAN-' + r['name']] = subst(nat['path_local'], {'dest': r['name']})

    sp = []
    pol = lambda name, tenants, services, path: subst(nat['service_policy'], {
        'name': name, 'tenants': tenants, 'services': services, 'path': path})
    if hub_on and d['overlay_tenants']:
        sp.append(pol('allow-to-hub', list(d['overlay_tenants']), ['HUB-SITE-NETS'], d['vpn']))
    inet_legacy = [x['name'] for x in legacy_order(rows) if x['internet']]
    if inet_legacy:
        sp.append(pol('Internet', inet_legacy, ['any'], 'wan'))
        sp.append(pol('To-ICD', [r['name'] for r in rows if r['internet']], ['any'], 'ICD'))
    sp.append(pol('ICD-Internet', ['ICD'], ['any'], 'wan'))
    for r in dests:
        sp.append(pol('To-' + r['name'], [x['name'] for x in rows if r['name'] in x['reach']], ['any'],
                      'LAN-' + r['name']))

    bgp = {'ICD': subst(nat['bgp_icd'], {'local_as': nd['asn'],
                                         'neighbors': {nd['icd_peer']: {'neighbor_as': nd['peer_asn']}}})}
    m = a['mgmt']
    mode = m.get('mode', 'static')
    if mode == 'static':
        oob = subst(nat['oob_static'], {'ip': nd['mgmt_ip'], 'plen': ip.ip_network(m['oob_network']).prefixlen})
    elif mode == 'static-gw':
        oob = subst(nat['oob_static_gw'], {'ip': nd['mgmt_ip'], 'plen': ip.ip_network(m['oob_network']).prefixlen,
                                           'gateway': m['gateway']})
    elif mode == 'dhcp':
        oob = copy.deepcopy(nat['oob_dhcp'])
    else:
        ph = d['layout']['oob_placeholder']
        oob = subst(nat['oob_static'], {'ip': str(ph.network_address + int(n)), 'plen': ph.prefixlen})

    vals = {'port_config': port_config, 'ip_configs': ip_configs, 'dhcpd_config': dhcpd, 'path_preferences': pp,
            'service_policies': sp, 'bgp_config': bgp, 'routing_policies': copy.deepcopy(nat['routing_policies']),
            'gateway_mgmt': copy.deepcopy(nat['gateway_mgmt']), 'oob_ip_config': oob,
            'ntp_servers': list(a['services']['ntp_servers']), 'dns_servers': list(a['services']['dns_servers']),
            'ospf_config': copy.deepcopy(nat['ospf_config']),
            'additional_config_cmds': build_cli(d, n, template, trace),
            'router_id': nat['router_id'], 'name': nd['profile_name'], 'type': nat['type']}
    for k in nat['empty_objects']:
        vals[k] = {}
    return {k: vals[k] for k in nat['key_order']}


# ------------------------------------------------------------------ build: org objects
def build_org_objects(d, template):
    org = template['org']
    out = []
    for r in d['T']:
        body = subst(org['network_tenant'], {
            'name': r['name'], 'vlan_id': r['vlan_id'], 'subnet': r['subnet'], 'gateway': r['gateway'],
            'internet_access': copy.deepcopy(org['internet_on'] if r['internet'] else org['internet_off']),
            'vpn_access': {d['vpn']: copy.deepcopy(org['vpn_access_item'])} if r['overlay'] else None})
        out.append({'method': 'POST', 'path': org['networks_path'], 'body': body})
    out.append({'method': 'POST', 'path': org['networks_path'],
                'body': subst(org['network_icd'], {'icd_subnet': str(d['layout']['icd_net'])})})
    if d['hub_on'] and d['overlay_tenants']:
        out.append({'method': 'POST', 'path': org['services_path'],
                    'body': subst(org['service_hub'], {'addresses': list(d['hub_prefixes'])})})
    return [dict([('step', k)] + list(o.items())) for k, o in enumerate(out, 1)]


def build(answers, template=None):
    """Org objects and both Hub Profiles from a valid answers file (validate() first)."""
    template = template or load_template()
    d = derive(answers)
    return {'org_objects': build_org_objects(d, template),
            'profiles': {n: build_profile(d, n, template) for n in ('1', '2')}, 'derived': d}


def line_count_formula(d, n):
    """Additional CLI line count from the design formula (cross-check of build_cli)."""
    a = d['a']
    nd = d['nodes'][n]
    rows = d['T']
    N, s = len(rows), sum(1 for r in rows if r['ssh'])
    srv = 1 if d['dhcp_server'] else 0
    pre = 1 if a['pair'].get('preemption') is True else 0
    enc = 1 if a['pair'].get('icl_encryption') is True else 0
    k = len(nd['steered_rows'])
    x = len(d['extra_excepts'])
    m = sum(1 for r in rows if r['internet'])
    pd = 1 if nd['ipv6_pd'] else 0
    v = len(nd['v6_rows'])
    hub = 1 if d['hub_on'] else 0
    p = len(d['paths'])
    ot = 1 if d['overlay_tenants'] else 0
    r_n = (1 if nd['root_password'] else 0) + (1 if nd['root_ssh_key'] else 0)
    key = 1 if nd['license'] else 0
    j = ((3 + 3 * v) if nd['ipv6_prefix_known'] else 2) if pd else 0
    return ((N + s) + (srv + 1) + (17 + pre + 3 * N + srv + 14 * enc) + 12 + (5 + ((2 * k + 9 + x) if k else 0))
            + ((m + 3) if m else 0) + 1 + 8 * srv + 1 + j + hub * (4 + 2 * p + 6 * ot) + pd + (r_n + key) + 3)


# ------------------------------------------------------------------ secrets (in memory, at the write only)
def ssh_key_statement(root_ssh_key):
    """Junos root-authentication keyword for an SSH public key line: ssh-ed25519 and ssh-rsa keep their key type,
    ecdsa-sha2-nistp256/384/521 is ssh-ecdsa. None for no key; ValueError (no key text) for another type."""
    if not root_ssh_key:
        return None
    t = root_ssh_key.split()[0]
    if t not in SSH_KEY_STATEMENT:
        raise ValueError('<ROOT-SSH-KEY-TYPE>: key type is not ssh-ed25519, ssh-rsa or ecdsa-sha2-nistp256/384/521')
    return SSH_KEY_STATEMENT[t]


def ssh_key_value(root_ssh_key):
    """The key that goes into the root-authentication line: key type and key data; the comment after them is not
    sent (Junos does not need it, and it may hold text such as <name@host>)."""
    if not root_ssh_key:
        return None
    return ' '.join(root_ssh_key.split()[:2])


def fill_secrets(profile, root_hash=None, root_ssh_key=None, license_key=None, icl_psk=None):
    """In-memory copy of a plan profile with this node's secrets in place (values from read_secret(); never
    printed). Raises ValueError, with placeholder names only, when a placeholder has no usable value or the plan
    profile holds any <...> other than the secret placeholders and <*_to_*> (checked before the fill, so a secret
    value is never part of the message)."""
    p = json.loads(json.dumps(profile))
    left = sorted(set(PLACEHOLDER_RX.findall(json.dumps(p))) - set(SECRET_PLACEHOLDERS))
    if left:
        raise ValueError('placeholders left: %s' % left)
    vals = {'<ROOT-PASSWORD-HASH>': root_hash, '<LICENSE-KEY>': license_key, '<ICL-PSK>': icl_psk,
            '<ROOT-SSH-KEY>': ssh_key_value(root_ssh_key), '<ROOT-SSH-KEY-TYPE>': ssh_key_statement(root_ssh_key)}
    cmds = []
    for line in p['additional_config_cmds']:
        for ph, v in vals.items():
            if ph in line:
                if not v or re.search(r'["\n\r<>]', v):
                    raise ValueError('no usable value for %s' % ph)
                line = line.replace(ph, v)
        cmds.append(line)
    p['additional_config_cmds'] = cmds
    rest = [ph for ph in SECRET_PLACEHOLDERS if ph in json.dumps(p)]
    if rest:
        raise ValueError('placeholders left: %s' % rest)
    return p


def named_objects(profile):
    """The org objects a Hub Profile names (SKILL.md step 3.3): {'networks': [...], 'services': [...]}, sorted.
    Networks: the keys of ip_configs and dhcpd_config (without 'enabled'), port_config networks and port_network,
    service_policies tenants, path_preferences paths networks, bgp_config networks. Services: service_policies
    services other than 'any'."""
    nets, svcs = set(), set()
    nets |= set((profile.get('ip_configs') or {}).keys())
    nets |= {k for k in (profile.get('dhcpd_config') or {}) if k != 'enabled'}
    for pc in (profile.get('port_config') or {}).values():
        nets |= set(pc.get('networks') or [])
        if pc.get('port_network'):
            nets.add(pc['port_network'])
    for sp in profile.get('service_policies') or []:
        nets |= set(sp.get('tenants') or [])
        svcs |= {x for x in sp.get('services') or [] if x != 'any'}
    for pp in (profile.get('path_preferences') or {}).values():
        for path in pp.get('paths') or []:
            nets |= set(path.get('networks') or [])
    for b in (profile.get('bgp_config') or {}).values():
        nets |= set(b.get('networks') or [])
    return {'networks': sorted(nets), 'services': sorted(svcs)}


def secret_placeholders(profile):
    """The secret placeholders a plan profile carries (names only)."""
    text = '\n'.join(profile.get('additional_config_cmds', []))
    return [ph for ph in SECRET_PLACEHOLDERS if ph in text]


# ------------------------------------------------------------------ views
def _box(lines, w):
    """ASCII box of width w; a row longer than the box wraps onto the next rows (never cut)."""
    out = ['+' + '-' * (w - 2) + '+']
    for s in lines:
        rows = textwrap.wrap(s, w - 4, subsequent_indent='  ', break_on_hyphens=False) or ['']
        for r in rows:
            out.append('| ' + r.ljust(w - 4) + ' |')
    out.append('+' + '-' * (w - 2) + '+')
    return out


def lan_label(nd):
    """'ae0 = ge-0/0/3 (LACP)' for a LAG, 'ge-0/0/6 (plain port, no LACP)' for a plain LAN port."""
    if nd['lan_lacp']:
        ports = ', '.join(nd['lan']) if len(nd['lan']) <= 2 else '%d ports %s..%s' % (len(nd['lan']), nd['lan'][0],
                                                                                       nd['lan'][-1])
        return '%s = %s (LACP)' % (nd['lan_if'], ports)
    return '%s (plain port, no LACP)' % nd['lan_if']


def _mgmt_text(d, n):
    a = d['a']
    m = a['mgmt']
    mode = m.get('mode', 'static')
    nd = d['nodes'][n]
    if mode == 'none':
        ph = d['layout']['oob_placeholder']
        return '%s/%d placeholder, unplugged' % (ph.network_address + int(n), ph.prefixlen)
    if mode == 'dhcp':
        return 'DHCP, management VRF'
    plen = ip.ip_network(m['oob_network']).prefixlen
    if mode == 'static-gw':
        return '%s/%d gw %s, mgmt VRF' % (nd['mgmt_ip'], plen, m['gateway'])
    return '%s/%d, no gateway' % (nd['mgmt_ip'], plen)


def _isp_text(a, n):
    i = a['isps'][n]
    if i.get('ipv6_pd') is True:
        v6 = 'IPv6 PD ' + (i.get('delegated_prefix') if i.get('delegated_prefix') != 'unknown'
                           else '/%s after onboarding' % i.get('pd_length', 60))
    else:
        v6 = 'IPv4 only'
    return '%s (DHCP, %s)' % (i.get('label') or 'ISP %s' % n, v6)


def hub_text(p):
    """'hub profile <name>, device <name> (MAC <mac>)'; without the device name (H4): 'hub profile <name> (MAC <mac>)'."""
    dev = (', device %s' % p['hub_device_name']) if p.get('hub_device_name') else ''
    return 'hub profile %s%s (MAC %s)' % (p.get('hub_profile_name'), dev, p.get('hub_mac'))


def _dhcp_text(r):
    dd = r['dhcp']
    if r['dhcp_mode'] == 'server':
        return '%s-%s' % (dd['start'], dd['end'])
    if r['dhcp_mode'] == 'relay':
        return 'relay to ' + ', '.join(dd.get('relay_servers') or [])
    return 'none (static addresses)'


def _v6_text(r):
    if not r['v6']:
        return 'none'
    return '; '.join('ISP %s %s' % (k, v['net'] or '/64 number %d (after onboarding)' % v['index'])
                     for k, v in sorted(r['v6'].items()))


def render_topology_txt(d, plan):
    a = d['a']
    W, MW = 46, 28
    n1, n2 = d['nodes']['1'], d['nodes']['2']
    lines1 = {n: len(plan['profiles'][n]['additional_config_cmds']) for n in ('1', '2')}
    L = ['SRX400 MNHA pair, site %s: topology of the plan (nothing is written yet)' % (a['site'].get('name') or '?'), '']
    L.append('  ' + _isp_text(a, '1').ljust(W + MW + 4) + _isp_text(a, '2'))
    L.append('  ' + ('|  %s (wan)' % n1['wan_port']).ljust(W + MW + 4) + '|  %s (wan)' % n2['wan_port'])

    def box(nd, n):
        return _box(['node %s  SRX400  SN %s' % (n, nd['serial']), 'host %s' % (nd['host'] or '(name it in Mist)'),
                     'profile %s, %d lines' % (nd['profile_name'], lines1[n]),
                     'SRG1 priority %d (%s)' % (nd['priority'], 'preferred active' if n == '1' else 'preferred backup'),
                     'lo0 %s   AS %s' % (nd['lo0_local'], nd['asn']), 'mgmt-0 %s' % _mgmt_text(d, n)], W)
    b1, b2 = box(n1, '1'), box(n2, '2')
    mid = ['', 'ICL %s-%s' % (n1['icl_port'], n2['icl_port']), '%s/30' % d['layout']['icl_net'].network_address,
           '=' * MW, 'ICD %s-%s' % (n1['icd_port'], n2['icd_port']),
           '%s/30 eBGP' % d['layout']['icd_net'].network_address, '-' * MW, '']
    for k in range(len(b1)):
        L.append('  ' + b1[k] + '  ' + (mid[k] if k < len(mid) else '').center(MW) + '  ' + b2[k])

    L.append('  ' + ('   ' + lan_label(n1)).ljust(W + MW + 4) + '   ' + lan_label(n2))
    L.append('  ' + '        \\'.ljust(W + MW + 4) + '        /')
    unt = [r for r in d['T'] if r['untagged']]
    tag = [str(r['vlan_id']) for r in d['T'] if not r['untagged']]
    L.append('          LAN switch: one %s per node, every VLAN on both; untagged: %s; tagged: %s' % (
        'LAG' if (n1['lan_lacp'] and n2['lan_lacp']) else 'link',
        ('%s (VLAN %d)' % (unt[0]['name'], unt[0]['vlan_id'])) if unt else 'none', ' '.join(tag) or 'none'))
    for r in d['T']:
        L.append('            VLAN %-4d %-24s %-18s VIP %-15s ISP %s%s' % (
            r['vlan_id'], r['name'], r['subnet'], r['gateway'], r['preferred_isp'] if r['internet'] else '-',
            '  overlay' if r['overlay'] else ''))
    if d['hub_on']:
        for p, ike, sp in zip(d['paths'], d['ike_gateways'], d['spoke_paths']):
            L.append('  Overlay: VPN %s, path %s -> %s, IKE gateway %s' % (d['vpn'], p.get('path'), hub_text(p), ike))
        if d['overlay_tenants']:
            L.append('    %s -> %s over the overlay; the hub prefers the SRG1-active node (policy %s, local-preference 200)'
                     % (', '.join(d['overlay_tenants']), ', '.join(d['hub_prefixes']), d['lp_policy']))
        else:
            L.append('    no network uses the overlay yet (tunnels up, no network route advertised)')
    else:
        L.append('  No hub: no overlay; the LAN, the transit link and DHCP stay in the default routing instance')
    return '\n'.join(L) + '\n'


def tenant_table(d):
    L = ['| VIP | Network | VLAN | Subnet | Gateway (VIP) | Node 1 | Node 2 | Preferred ISP | Internet | DHCP | IPv6 /64 | Overlay | SSH | May reach |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in d['T']:
        L.append('| %d | %s | %d%s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
            r['pos'], r['name'], r['vlan_id'], ' untagged' if r['untagged'] else '', r['subnet'], r['gateway'],
            r['node_ip']['1'], r['node_ip']['2'], ('ISP %d' % r['preferred_isp']) if r['internet'] else '-',
            'yes' if r['internet'] else 'no', _dhcp_text(r), _v6_text(r), 'yes' if r['overlay'] else 'no',
            'yes' if r['ssh'] else 'no', ', '.join(r['reach']) or '-'))
    return L


def steering_lines(d):
    L = []
    for n in ('1', '2'):
        nd = d['nodes'][n]
        if nd['steered']:
            L.append('- node %s sends %s to ISP %s over the transit link (%sbackup: its own ISP)' %
                     (n, ', '.join(nd['steered']), nd['peer'], 'IPv4 ' if any(r['v6'] for r in d['T']) else ''))
        else:
            L.append('- node %s: no network prefers ISP %s; no steering filter on node %s' % (n, nd['peer'], n))
    return L


def backup_lines(d):
    """How the ISP backup and the source NAT work (plan.md, Internet steering)."""
    rows = [r for r in d['T'] if r['internet']]
    if not rows:
        return []
    pub = [r['name'] for r in rows if r['public']]
    v6 = ' (IPv4 only; IPv6 has no failover, see IPv6)' if any(r['v6'] for r in d['T']) else ''
    return ['- backup%s: a network moves to the other ISP when the node of its preferred ISP loses its WAN link or its '
            'DHCP lease (its default route); an upstream outage that leaves the WAN link and the lease up does not move '
            'it' % v6, '- source NAT: every network with Internet access leaves with source NAT to the WAN address of the node '
            'whose ISP it uses%s' % ((' (a public subnet too: %s)' % ', '.join(pub)) if pub else '')]


def render_mermaid(d):
    a = d['a']
    n1, n2 = d['nodes']['1'], d['nodes']['2']
    q = lambda s: '"' + str(s).replace('"', "'") + '"'
    M = ['flowchart TB']
    for n in ('1', '2'):
        M.append('  ISP%s[%s]' % (n, q(_isp_text(a, n))))
    for n, x in (('1', n1), ('2', n2)):
        M.append('  N%s[%s]' % (n, q('node %s SRX400 %s<br/>%s<br/>SRG1 priority %d<br/>lo0 %s AS %s<br/>mgmt-0 %s' %
                                     (n, x['serial'], x['profile_name'], x['priority'], x['lo0_local'], x['asn'],
                                      _mgmt_text(d, n)))))
        M.append('  ISP%s ---|%s| N%s' % (n, q(x['wan_port'] + ' wan'), n))
    M.append('  N1 ===|%s| N2' % q('ICL %s - %s<br/>%s/30' % (n1['icl_port'], n2['icl_port'], d['layout']['icl_net'].network_address)))
    M.append('  N1 ---|%s| N2' % q('ICD %s - %s<br/>%s/30 eBGP' % (n1['icd_port'], n2['icd_port'], d['layout']['icd_net'].network_address)))
    tl = '<br/>'.join('%s VLAN %d%s %s VIP %s ISP %s%s' % (r['name'], r['vlan_id'], ' untagged' if r['untagged'] else '',
                                                          r['subnet'], r['gateway'],
                                                          r['preferred_isp'] if r['internet'] else '-',
                                                          ' overlay' if r['overlay'] else '') for r in d['T'])
    M.append('  SW[%s]' % q('LAN switch<br/>' + tl))
    for n, x in (('1', n1), ('2', n2)):
        M.append('  N%s ---|%s| SW' % (n, q(('%s = %s' % (x['lan_if'], ', '.join(x['lan']))) if x['lan_lacp'] else
                                             '%s plain port' % x['lan_if'])))
    if d['hub_on']:
        M.append('  HUB[%s]' % q('%s<br/>VPN %s<br/>%s' % ('<br/>'.join(hub_text(p) for p in d['paths']),
                                                         d['vpn'], ', '.join(d['hub_prefixes']) or 'no network prefix')))
        M.append('  N1 -.-|%s| HUB' % q('overlay ' + (', '.join(d['overlay_tenants']) or '(no network)')))
        M.append('  N2 -.-|%s| HUB' % q('overlay'))
    return '\n'.join(M) + '\n'


def render_topology_md(d, plan):
    a = d['a']
    L = ['# Topology: site %s' % (a['site'].get('name') or '?'), '',
         'Generated from the answers; nothing is written to Mist until you confirm the plan.', '',
         '```mermaid', render_mermaid(d).rstrip('\n'), '```', '',
         '## Networks (T order: the untagged network first; VIP n = SRG1 virtual IP n)', '']
    L += tenant_table(d)
    L += ['', '## Internet steering', '',
          'Each network leaves by its preferred ISP whichever node is active; the other ISP is its backup when the '
          'preferred ISP\'s node loses its WAN link or its DHCP lease.', '']
    L += steering_lines(d)
    if any(d['nodes'][n]['ipv6_pd'] for n in ('1', '2')):
        L += ['', 'IPv6 has no failover: each network\'s IPv6 comes from one node and its ISP; while that node or its ISP '
              'is down, the network has no IPv6 (its IPv4 moves to the other node).']
    L += ['', '## Diagram (text)', '', '```', render_topology_txt(d, plan).rstrip('\n'), '```', '']
    return '\n'.join(L)


FIXED_CONSTANTS = [
    ('Platform', 'SRX400 pair, Junos OS Evolved 25.4X300-D30.3 (proven) or a later 25.4X300 release'),
    ('HA form', 'MNHA hybrid, one SRG1, deployment-type hybrid, use-virtual-mac, monitor interface = the LAN interface'),
    ('Liveness', 'HA link and peer-forwarding liveness 1000 ms x 3'),
    ('Activeness probe', 'none configured (hybrid default probe toward virtual IP 1)'),
    ('DHCP on MNHA', 'managed-services dhcp, Active Leasequery timeout 60 / idle-timeout 10, five dhcp-service limits, '
                     'overrides no-unicast-replies (when the firewalls serve DHCP)'),
    ('HA link', '/30 + lo0 /32 + static route to the peer lo0; zone HA (HA link unit + lo0.0), policy allow-ha'),
    ('Steering', 'delete apply-groups apbr; forwarding instance XNODE (0/0 next-table inet.0, preference 200); '
                 'rib-group ICD-RIB; filter TO-PEER-ISP (RFC 1918, multicast and broadcast stay local); '
                 'source NAT rule-set LAN_to_ICD'),
    ('Transit link', 'org network ICD (no Mist services, no Internet); eBGP group ICD exchanging 0.0.0.0/0 only '
                     '(ICD-IMPORT / ICD-EXPORT); path preferences wan and ICD; service policies Internet, To-ICD, '
                     'ICD-Internet; IDP off'),
    ('WAN port', 'name wan, broadband, DHCP, source NAT, speed test, probe profile broadband; DHCP client '
                 'retransmission-attempt 50000, retransmission-interval 64, force-discover'),
    ('Overlay', 'node-local IKE group <*_to_*>; dead-peer-detection always-send; overlay BGP BFD 1000 ms x 3; '
                'the SRG1-active node exports the overlay networks with local-preference 200'),
    ('IPv6', 'SLAAC (router advertisements), a static /64 per network from the delegated prefix, discard route for '
             'the prefix, IPv6 Internet policy per network'),
    ('System', 'ssh protocol-version v2; chassis alarm management-ethernet link-down ignore; ping on every network zone'),
]


def render_plan_md(d, plan):
    a = d['a']
    n1, n2 = d['nodes']['1'], d['nodes']['2']
    lay = d['layout']
    pr = plan['profiles']
    L = ['# Plan: site %s' % (a['site'].get('name') or '?'), '',
         'Build exactly this? Nothing is written to Mist until you say yes; then each write is shown and needs its '
         'own yes. Any change goes back to its question.', '']
    hw = hardware_status(d)
    L += ['## Reference design', '', '- Proven on hardware: ' + PROVEN_TEXT + '.']
    if hw:
        L += ['- Beyond the reference design: your answers build these from the same reference lines; step 7 '
              'verifies the pair:'] + ['  - %s' % x for x in hw]
    else:
        L += ['- Your answers use only the proven structure: the values differ (names, VLANs, subnets, addresses), '
              'the lines and keys are those of the proven pair.']
    L.append('')
    L += ['## Firewalls and ports', '', '| Item | Node 1 | Node 2 |', '|---|---|---|']
    rows = [
        ('Serial', n1['serial'], n2['serial']),
        ('Mist device name (host name)', n1['host'] or '(name it in Mist)', n2['host'] or '(name it in Mist)'),
        ('Hub Profile', '%s, %d Additional CLI lines' % (n1['profile_name'], len(pr['1']['additional_config_cmds'])),
         '%s, %d Additional CLI lines' % (n2['profile_name'], len(pr['2']['additional_config_cmds']))),
        ('SRG1 priority', '200 (preferred active)', '100 (preferred backup)'),
        ('WAN port (ISP)', '%s (ISP 1)' % n1['wan_port'], '%s (ISP 2)' % n2['wan_port']),
        ('LAN', lan_label(n1), lan_label(n2)),
        ('HA link (ICL)', '%s, %s/30' % (n1['icl_port'], n1['icl_local']), '%s, %s/30' % (n2['icl_port'], n2['icl_local'])),
        ('Transit link (ICD)', '%s, %s/30, AS %s' % (n1['icd_port'], n1['icd_local'], n1['asn']),
         '%s, %s/30, AS %s' % (n2['icd_port'], n2['icd_local'], n2['asn'])),
        ('Loopback (MNHA forwarding)', '%s/32' % n1['lo0_local'], '%s/32' % n2['lo0_local']),
        ('mgmt-0', _mgmt_text(d, '1'), _mgmt_text(d, '2')),
        ('Root authentication', ', '.join(x for x, f in (('password file', n1['root_password']), ('SSH key file', n1['root_ssh_key'])) if f) or 'missing',
         ', '.join(x for x, f in (('password file', n2['root_password']), ('SSH key file', n2['root_ssh_key'])) if f) or 'missing'),
        ('License key', 'file given' if n1['license'] else 'none', 'file given' if n2['license'] else 'none'),
    ]
    L += ['| %s | %s | %s |' % r for r in rows]
    L += ['', '## ISPs', '', '| ISP | Node | Hand-off | WAN range | After the push | IPv6 delegation |', '|---|---|---|---|---|---|']
    for n in ('1', '2'):
        i = a['isps'][n]
        lease = ('holds its address, lease %d min' % (i.get('lease_seconds', 0) // 60)) if i.get('lease_behavior') == 'held' \
            else 'gives a new address at once'
        v6 = 'no'
        if i.get('ipv6_pd') is True:
            v6 = ('%s' % i['delegated_prefix']) if i.get('delegated_prefix') != 'unknown' else \
                '/%s, prefix known after onboarding (second step)' % i.get('pd_length', 60)
            if i.get('prefix_stable') == 'accept-manual-update':
                v6 += '; you update the profiles if the ISP changes it'
        L.append('| %s | node %s | DHCP, untagged | %s | %s | %s |' % (
            i.get('label') or 'ISP ' + n, n, i.get('wan_subnet') or
            'unknown: you confirmed (R9) it is clear of %sthe planned ranges; the generator could not check it' %
            ('192.168.2.0/24 and ' if ge3_cabled(a['nodes'], n) else ''), lease, v6))
    if a['isps'].get('same_upstream') is True:
        L += ['', 'Both ISPs are one upstream: steering splits the load, there is no ISP diversity.']
    elif a['isps'].get('same_upstream') is False and a['isps']['1'].get('wan_subnet') and \
            str(a['isps']['1'].get('wan_subnet')).strip() == str(a['isps']['2'].get('wan_subnet')).strip():
        L += ['', 'Both ISP routers hand out the same range; each WAN subnet stays on its own node.']
    L += ['', '## Networks (T order: the untagged network first; VIP n = SRG1 virtual IP n)', '']
    L += tenant_table(d)
    L += ['', '## DHCP per network', '', '| Network | Mode | Range | Client DNS | Lease | Domain | Options | Reservations |',
          '|---|---|---|---|---|---|---|---|']
    for r in d['T']:
        dd = r['dhcp']
        if r['dhcp_mode'] == 'server':
            L.append('| %s | firewalls (server) | %s-%s | %s | %d s | %s | %s | %s |' % (
                r['name'], dd['start'], dd['end'], ', '.join(dd['dns_servers']), dd['lease_time'],
                ', '.join(dd.get('dns_suffix') or []) or '-',
                ', '.join('%s %s=%s' % (c, o['type'], o['value']) for c, o in (dd.get('options') or {}).items()) or '-',
                ', '.join('%s %s' % (m, b.get('ip')) for m, b in (dd.get('fixed_bindings') or {}).items()) or '-'))
        elif r['dhcp_mode'] == 'relay':
            L.append('| %s | relay to %s | - | - | - | - | - | - |' % (r['name'], ', '.join(dd['relay_servers'])))
        else:
            L.append('| %s | none (static addresses) | - | - | - | - | - | - |' % r['name'])
    relay = [r['name'] for r in d['T'] if r['dhcp_mode'] == 'relay']
    if relay:
        L += ['', 'DHCP relay (%s): both nodes are on the VLAN, so both relay each client request, each with its own '
              'address on that network as the relay address; the DHCP server answers both (beyond '
              'the reference design, see the first section).' % ', '.join(relay)]
    L += ['', '## Internet steering', '']
    L += steering_lines(d)
    if d['extra_excepts']:
        L.append('- kept off the steering besides RFC 1918, multicast and broadcast: ' + ', '.join(d['extra_excepts']))
    L += backup_lines(d)
    L += ['', '## IPv6', '']
    any6 = False
    for n in ('1', '2'):
        nd = d['nodes'][n]
        if nd['ipv6_pd']:
            any6 = True
            L.append('- node %s: DHCPv6 prefix delegation on %s (/%s); serves %s; node address ::%d on each /64' % (
                n, nd['wan_port'], nd['pd_length'], ', '.join(r['name'] for r in nd['v6_rows']) or 'no network',
                1 + int(n)))
            if not nd['ipv6_prefix_known']:
                L.append('  - second step after onboarding: you report the bound prefix; then one profile update for '
                         'this node adds the /64, router-advertisement, discard and policy lines')
    if any6:
        L.append('- no IPv6 failover: each network\'s IPv6 is served by one node over that node\'s ISP; while that '
                 'node or its ISP is down, the network has no IPv6 (its IPv4 moves to the other node)')
    else:
        L.append('- IPv4 only')
    L += ['', '## Hub and overlay', '']
    if d['hub_on']:
        for p, ike, sp in zip(d['paths'], d['ike_gateways'], d['spoke_paths']):
            L.append('- VPN %s, path %s (spoke key %s) -> %s, IKE gateway %s' % (
                d['vpn'], p.get('path'), sp, hub_text(p), ike))
        if d['overlay_tenants']:
            L.append('- overlay networks: %s; hub prefixes (application HUB-SITE-NETS): %s; policy %s gives the '
                     'SRG1-active node local-preference 200' % (', '.join(d['overlay_tenants']),
                                                                 ', '.join(d['hub_prefixes']), d['lp_policy']))
            L.append('- while the ISP of the SRG1-active node is down, the overlay networks do not reach the hub (SRG1 '
                     'does not move on a WAN loss); they reach it again when that ISP is back or SRG1 moves to the '
                     'other node')
        else:
            L.append('- no network uses the overlay (tunnels and BGP up, no network advertised)')
    else:
        L.append('- no hub: no overlay; routing form: default routing instance')
    L += ['', '## Derived values', '', '| Item | Value |', '|---|---|']
    pair = a['pair']
    drows = [
        ('Internal block', '%s (/24 #0 HA link, #1 loopbacks, #2 transit link, #3 SRG1 signal routes); never advertised' % a['internal']['block']),
        ('HA link (ICL)', '%s/30: node 1 %s, node 2 %s' % (lay['icl_net'].network_address, n1['icl_local'], n2['icl_local'])),
        ('Loopbacks', 'node 1 %s/32, node 2 %s/32' % (n1['lo0_local'], n2['lo0_local'])),
        ('Transit link (ICD, eBGP)', '%s: node 1 %s AS %s, node 2 %s AS %s' %
         (lay['icd_net'], n1['icd_local'], n1['asn'], n2['icd_local'], n2['asn'])),
        ('SRG1 signal routes', 'active %s, backup %s' % (n1['signal_active'], n1['signal_backup'])),
        ('MNHA', 'hybrid, SRG1, node 1 priority 200, node 2 priority 100, preemption %s, HA link encryption %s' %
         ('on (SRG1 returns to node 1 once node 1 is healthy; MNHA refuses a manual SRG1 failover while '
          'preemption is on)'
          if pair.get('preemption') is True else
          'off (a node that joins while its peer is ACTIVE joins as BACKUP; the role stays until failed back by '
          'hand)',
          'on (pre-shared key file given)' if pair.get('icl_encryption') is True
          else 'off')),
        ('DHCP binding sync', ('Active Leasequery on %s (peer = the other node\'s %s address: node 1 -> %s, node 2 -> %s)'
                               % (d['alq'], d['alq'], n1['alq_peer'], n2['alq_peer'])) if d['alq'] else
         'none (no network uses the firewalls\' DHCP server)'),
        ('Routing form', d['routing_form']),
        ('SSH to the firewalls', 'from %s, and on mgmt-0' % (', '.join(r['name'] for r in d['T'] if r['ssh']) or 'no network')),
        ('DNS / NTP (firewalls)', '%s / %s' % (', '.join(a['services']['dns_servers']) or 'from the ISP (DHCP)',
                                               ', '.join(a['services']['ntp_servers']))),
    ]
    L += ['| %s | %s |' % r for r in drows]
    L += ['', '## Fixed design values (not asked)', '', '| Item | Value |', '|---|---|']
    any_pd = any(d['nodes'][n]['ipv6_pd'] for n in ('1', '2'))
    L += ['| %s | %s |' % r for r in FIXED_CONSTANTS
          if not ((r[0] == 'Overlay' and not d['hub_on']) or (r[0] == 'IPv6' and not any_pd))]
    L += ['', '## Writes, in order (each one shown and confirmed on its own)', '',
          '| # | Method | Path | Object | Summary |', '|---|---|---|---|---|']
    k = 0
    REUSE = 'reuse (no write)'
    for o in plan['org_objects']:
        k += 1
        b = o['body']
        summ = ('application, %s' % ', '.join(b['addresses'])) if o['path'].endswith('/services') else \
            ('network %s%s' % (b.get('subnet'), (', VLAN %s' % b['vlan_id']) if 'vlan_id' in b else ''))
        if reused(a, b['name']):
            L.append('| %d | %s | %s | %s | exists equal to the plan: reused read-only, %s |' % (
                k, REUSE, o['path'], b['name'], summ))
        else:
            L.append('| %d | POST | %s | %s | %s |' % (k, o['path'], b['name'], summ))
    phs = ', '.join(sorted(set(secret_placeholders(pr['1']) + secret_placeholders(pr['2'])))) or 'no secret'
    if a.get('profiles_method') == 'ui-import':
        for n in ('1', '2'):
            k += 1
            if reused(a, pr[n]['name']):
                L.append('| %d | %s | /orgs/{org_id}/deviceprofiles | %s | exists equal to the plan with this node\'s '
                         'secrets: reused read-only |' % (k, REUSE, pr[n]['name']))
            else:
                L.append('| %d | UI Import Profile (you) | Organization > WAN > Hub Profiles > Import Profile | %s | Hub '
                         'Profile node %s, %d Additional CLI lines; type the name exactly |' % (
                             k, pr[n]['name'], n, len(pr[n]['additional_config_cmds'])))
            k += 1
            L.append('| %d | UI Applies To Devices (you) | Organization > WAN > Hub Profiles > %s > Applies To Devices '
                     '| %s | assign to node %s, serial %s |' % (k, pr[n]['name'], pr[n]['name'], n,
                                                               d['nodes'][n]['serial']))
        L += ['', 'One node at a time, node 1 first: you import the profile, I read it back, then you assign it '
              '(Applies To Devices) and I read the assignment back; then node 2. '
              'Secrets stay in your files: the profiles carry %s; the two filled files for the import go to '
              '<working folder>/secrets/ (mode 600) and are deleted, with your yes, after both read-backs and '
              'assignments.' % phs, '']
    else:
        for n in ('1', '2'):
            k += 1
            if reused(a, pr[n]['name']):
                L.append('| %d | %s | /orgs/{org_id}/deviceprofiles | %s | exists equal to the plan with this node\'s '
                         'secrets: reused read-only |' % (k, REUSE, pr[n]['name']))
            else:
                L.append('| %d | POST | /orgs/{org_id}/deviceprofiles | %s | Hub Profile node %s, %d Additional CLI '
                         'lines |' % (k, pr[n]['name'], n, len(pr[n]['additional_config_cmds'])))
        for n in ('1', '2'):
            k += 1
            L.append('| %d | POST | /orgs/{org_id}/deviceprofiles/{profile_id}/assign | %s | assign to node %s, serial '
                     '%s |' % (k, pr[n]['name'], n, d['nodes'][n]['serial']))
        L += ['', 'Secrets stay in your files: the profiles carry %s until the write, which fills them in memory.' %
              phs, '']
    return '\n'.join(L)


# ------------------------------------------------------------------ write the plan folder
def write_plan(answers, out_dir, fixture=None, template=None):
    problems = validate(answers, fixture)
    if problems:
        return problems, None
    plan = build(answers, template)
    d = plan['derived']
    os.makedirs(out_dir, exist_ok=True)

    def dump(name, obj):
        with open(os.path.join(out_dir, name), 'w') as f:
            json.dump(obj, f, indent=2)
            f.write('\n')

    def text(name, s):
        with open(os.path.join(out_dir, name), 'w') as f:
            f.write(s)
    dump('org-objects.json', plan['org_objects'])
    dump('node1-profile.json', plan['profiles']['1'])
    dump('node2-profile.json', plan['profiles']['2'])
    text('topology.txt', render_topology_txt(d, plan))
    text('topology.md', render_topology_md(d, plan))
    text('plan.md', render_plan_md(d, plan))
    return [], plan


def plan_update(old_dir, plan):
    """Compare a new plan with the plan folder already built in Mist (SKILL.md steps 4.5 and 7.7). Returns
    (problems, changes): problems when the org objects or a profile name differ (that is a new build, not an update);
    changes = per node {'name', 'keys': [changed top-level keys], 'added': [lines], 'removed': [lines]}."""
    def load(name):
        with open(os.path.join(old_dir, name)) as f:
            return json.load(f)
    try:
        old_org = load('org-objects.json')
        old = {n: load('node%s-profile.json' % n) for n in ('1', '2')}
    except (OSError, ValueError) as e:
        return [R('update', '%s is not a plan folder this script wrote (%s)' % (old_dir, type(e).__name__))], {}
    probs, changes = [], {}
    if old_org != plan['org_objects']:
        a = {o['body']['name'] for o in old_org}
        b = {o['body']['name'] for o in plan['org_objects']}
        diff = sorted((a ^ b) | {o['body']['name'] for o in plan['org_objects']
                                 if o['body']['name'] in a and o not in old_org})
        probs.append(S('update', 'the org objects change (%s): this is a new build, not an update of the two Hub '
                       'Profiles; go back to step 3 with the customer' % (', '.join(diff) or 'order')))
    for n in ('1', '2'):
        new_p, old_p = plan['profiles'][n], old[n]
        if new_p.get('name') != old_p.get('name'):
            probs.append(S('update', 'node %s: the profile name changes (%s -> %s): a new profile, not an update'
                           % (n, old_p.get('name'), new_p.get('name'))))
            continue
        keys = sorted(k for k in set(new_p) | set(old_p) if new_p.get(k) != old_p.get(k))
        if any(k not in new_p for k in keys):
            probs.append(S('update', 'node %s: the key(s) %s would be removed; a PUT cannot remove a key (never send '
                           'null): a new build, not an update' % (n, ', '.join(k for k in keys if k not in new_p))))
            continue
        oc, nc = list(old_p.get('additional_config_cmds') or []), list(new_p.get('additional_config_cmds') or [])
        added, removed = list(nc), []
        for ln in oc:
            if ln in added:
                added.remove(ln)
            else:
                removed.append(ln)
        changes[n] = {'name': new_p['name'], 'keys': keys, 'added': added if 'additional_config_cmds' in keys else [],
                      'removed': removed if 'additional_config_cmds' in keys else [],
                      'lines': len(nc)}
    return probs, changes


def render_update_md(d, plan, changes):
    a = d['a']
    L = ['# Update: site %s' % (a['site'].get('name') or '?'), '',
         'Update the two Hub Profiles that are already in Mist? Only the writes below are made: the org objects and '
         'the assignments stay as they are, and each write is shown and needs its own yes. Mist then pushes the '
         'changed configuration to the node (commit confirmed).', '']
    k = 0
    rows = []
    for n in ('1', '2'):
        c = changes.get(n) or {'keys': []}
        L += ['## Node %s: %s' % (n, plan['profiles'][n]['name']), '']
        if not c['keys']:
            L += ['- no change', '']
            continue
        L.append('- changed keys: %s' % ', '.join(c['keys']))
        for key in c['keys']:
            if key == 'additional_config_cmds':
                L.append('- Additional CLI: %d lines added, %d removed (%d lines in all)' % (
                    len(c['added']), len(c['removed']), c['lines']))
                L += ['', '```'] + ['+ ' + x for x in c['added']] + ['- ' + x for x in c['removed']] + ['```']
            else:
                L += ['', '`%s` (whole new value):' % key, '', '```',
                      json.dumps(plan['profiles'][n][key], indent=1), '```']
        L.append('')
        k += 1
        rows.append('| %d | PUT | /orgs/{org_id}/deviceprofiles/{profile_id} | %s | %s, whole values |' % (
            k, c['name'], ', '.join(c['keys'])))
    L += ['## Writes, in order (each one shown and confirmed on its own)', '']
    if rows:
        L += ['| # | Method | Path | Object | Summary |', '|---|---|---|---|---|'] + rows
    else:
        L.append('No change: nothing to write.')
    L += ['', 'Secrets stay in your files: the profiles carry placeholders until the write, which fills them in memory.',
          '']
    return '\n'.join(L)


def main(argv=None):
    import argparse
    os.umask(0o077)                               # the plan folder and its files: owner only
    ap = argparse.ArgumentParser(description='Validate answers.json (schema v2) and build the Mist plan folder.')
    ap.add_argument('--answers', required=True, help='answers.json (schema v2)')
    ap.add_argument('--out', help='plan folder to write (created if needed)')
    ap.add_argument('--check', action='store_true', help='validate only')
    ap.add_argument('--json', action='store_true', help='print the problems as JSON')
    ap.add_argument('--update', metavar='PLAN', help='the plan folder already built in Mist: with --out, also write '
                    'update.md (only the changed keys of each Hub Profile and their PUT), SKILL.md steps 4.5 and 7.7')
    args = ap.parse_args(argv)
    try:
        with open(os.path.expanduser(args.answers)) as f:
            answers = json.load(f)
    except (OSError, ValueError) as e:
        print('[reask] schema: %s is not a readable JSON file (%s)' % (args.answers, type(e).__name__))
        print('1 problem(s): reask')
        return 1
    if args.check or not args.out:
        problems, plan = validate(answers), None
    else:
        problems, plan = write_plan(answers, os.path.expanduser(args.out))
    if args.json:
        print(json.dumps(problems, indent=1))
    else:
        for p in problems:
            print('[%s] %s' % (p['kind'], p['msg']))
    if problems:
        kinds = sorted({p['kind'] for p in problems})
        print('%d problem(s): %s' % (len(problems), ', '.join(kinds)))
        return exit_code(problems)
    if plan and args.update:
        up, changes = plan_update(os.path.expanduser(args.update), plan)
        for p in up:
            print('[%s] %s' % (p['kind'], p['msg']))
        if up:
            print('%d problem(s): %s' % (len(up), ', '.join(sorted({p['kind'] for p in up}))))
            return exit_code(up)
        with open(os.path.join(os.path.expanduser(args.out), 'update.md'), 'w') as f:
            f.write(render_update_md(plan['derived'], plan, changes))
        print('valid; wrote %s with update.md: %d PUT (%s)' % (args.out, sum(1 for c in changes.values() if c['keys']),
                                                              '; '.join('node %s %s' % (n, ', '.join(c['keys']) or 'no change')
                                                                        for n, c in sorted(changes.items()))))
        return 0
    if plan:
        pr = plan['profiles']
        print('valid; wrote %s' % args.out)
        print('  org-objects.json: %d objects (%s)' % (len(plan['org_objects']),
                                                       ', '.join(o['body']['name'] for o in plan['org_objects'])))
        for n in ('1', '2'):
            print('  node%s-profile.json: %s, %d Additional CLI lines, secret placeholders %s' % (
                n, pr[n]['name'], len(pr[n]['additional_config_cmds']), ', '.join(secret_placeholders(pr[n])) or 'none'))
        print('  topology.txt, topology.md, plan.md')
        hw = hardware_status(plan['derived'])
        print('  beyond the reference design: %s' % ('%d item(s), listed in plan.md' % len(hw) if hw else
                                                    'none (only the proven structure)'))
    else:
        print('valid')
    return 0


if __name__ == '__main__':
    sys.exit(main())
