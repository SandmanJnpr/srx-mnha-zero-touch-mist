# Intake: what to ask before building

Ask one group at a time, in order A to F, with the read-only API checks of SKILL.md step 2 in between
(A1-A2, written to `answers.json` (`mist.portal_host`, `mist.api_host`, `mist.token_file`), since
`mist_api.py` reads them at import; then 2.1-2.2; then A3 and the group A table; B with 2.3-2.4; then
2.5, C1-C2; E3; 2.6, C3-C4; C5; 2.7; then D, E (without E3), F; then the snapshot 2.8). For each item
tell the user why it is needed and how to find it, offer the default if there is one, validate the
answer, and record it in `answers.json` (field names as in `answers.example.json`). Secrets are never
typed into the chat: the user saves each one in a local file (mode 600) and gives you the path. At the
end of each group, show the group's answers as a table (secrets as "set, N characters") and get a yes
before the next group.

Profile file line numbers below are 1-based positions in `additional_config_cmds` of the repository files.

## A. Mist access

**A1. Mist portal host (cloud)**
- Ask: the host in the browser address bar when you are in the Mist portal, `manage.<cloud>.mist.com`.
- Why: the API host is `api.<cloud>.mist.com`; the wrong cloud answers 401 even to a valid token. The same `<cloud>` is the one in `ztp.<cloud>.mist.com` in the `.set` files.
- Lands in: `mist.portal_host`, `mist.api_host`.
- How to find: the Mist portal URL. `GET /self` confirms it.
- Default: none.

**A2. API token file**
- Ask: the path of a local file that holds a Mist API token, and nothing else.
- Why: every call authenticates with it. You read it from the file inside the request code; it never appears in the chat, a log or a command output.
- Lands in: `mist.token_file`.
- How to find: in Mist, person icon > My Account > API Token > Create Token. Mist shows the token once: copy it straight into the file and set the file to mode 600 (`chmod 600 <file>`). The token acts with the user's own role, which must be admin on the org for the writes.
- Default: `~/mist-api-token`.

**A3. Org**
- Ask: which org, by name, from the list `GET /self` returns.
- Why: every org path uses its `org_id`; the role there must be `admin`.
- Lands in: `mist.org_name`, `mist.org_id` (you fill the id).
- How to find: `GET /self`, entries of `privileges` with scope `org`. A token whose account reaches the org only through an `msp` entry: stop and ask for a token from an account that is admin on the org itself (this skill makes no MSP API calls).
- Default: the only org, if the token has one.

## B. Site and devices

**B1. Branch site**
- Ask: the Mist site name of the branch.
- Why: both nodes must be assigned to this site; stats, events, render and restart calls use its `site_id`. It must bind no gateway template, or the first push is not the node's own profile.
- Lands in: `site.name`, `site.site_id` (you fill the id from the inventory).
- How to find: the user; you confirm with `GET /orgs/{org_id}/inventory?type=gateway&limit=1000` and `GET /sites/{site_id}` (`gatewaytemplate_id` null).
- Default: none.

**B2. Node serials, and which box is node 1**
- Ask: the serial of each SRX400 and which one is node 1.
- Why: node 1 = ISP 1, MNHA local-id 1, activeness-priority 200, IPv4 DHCP and DHCPv6 prefix delegation on the WAN, BGP AS 65001, .2 on every tenant network. Node 2 = ISP 2, local-id 2, activeness-priority 100, IPv4 DHCP, AS 65002, .3 on every tenant network. Each serial gives the `mac` and device id for the assign, render, stats, events and restart calls.
- Lands in: `nodes.1.serial`, `nodes.2.serial`; you fill `mac` and `device_id`.
- How to find: the box label or the order. Both serials must already be in the org inventory, model SRX400, assigned to the branch site. A serial you do not find: tell the user how many inventory records you read and ask before you conclude it is not in the org.
- Default: none.

**B3. Device names**
- Ask: confirm each node's inventory `name`, which you show as the host name Mist will render. Recommend SRX400-1 for node 1 and SRX400-2 for node 2: the profiles' ge-0/0/4 and ge-0/0/5 descriptions name the peer that way ("MNHA ICL to SRX400-2" on node 1).
- Why: Mist renders the host name from the device name. The skill never writes device records, so the user sets or changes the names in Mist.
- Lands in: `nodes.<n>.mist_device_name` (you read it from the inventory).
- How to find: the inventory `name` field. An empty name is not a stop here: the user names the node in Mist before power-on, and you read it again before the assign (SKILL.md step 4.4) and at the hand-off (step 5). After the assign, step 4.5 shows the rendered `set system host-name` line.
- Default: none.

**B4. Release and factory state**
- Ask: are both nodes on Junos OS Evolved 25.4X300-D30.3, in their factory-default state?
- Why: this is the release and starting state of this design. A node running another configuration does not take these profiles cleanly (Mist does not delete chassis high-availability lines).
- Lands in: `site_readiness.release_factory_default`.
- How to find: on the node's console, `show version | no-more` shows `Junos: 25.4X300-D30.3-EVO`. A node that has run any other configuration is returned to factory default on its console before shipping with `request system zeroize ztp-option secure-enable`, with only the console cable connected. The node reboots straight into ZTP: with a cable to a DHCP server and the Internet it onboards wherever it is, so WAN, LAN and mgmt-0 stay unplugged until it is at the site.
- Default: none; a "no" stops the build until it is a yes.

## C. Hub and overlay

**C1. Overlay present**
- Ask: confirm the VPN `OrgOverlay` (hub and spoke) exists.
- Why: the spoke profiles join the hub's overlay path; IOT reaches the hub site through it. The VPN must be named exactly `OrgOverlay`: the IOT network, the profiles' traffic steering path and their Additional CLI (node 1 lines 115, 116, 121 and 122, node 2 lines 105, 106, 111 and 112: `vpn_OrgOverlay`, `OrgOverlay_overlay`, `OrgOverlay_advertise`, names Mist derives from the VPN name) use it. A hub-and-spoke VPN with another name stops the build.
- Lands in: a prerequisite; you confirm with `GET /orgs/{org_id}/vpns?limit=1000`.
- How to find: you read it with `GET /orgs/{org_id}/vpns?limit=1000` (SKILL.md step 2.5).
- Default: none; without it, stop (paper section 7 step 1).

**C2. Hub overlay path**
- Ask: confirm the path you read from `GET /orgs/{org_id}/vpns?limit=1000` (or pick one when there are several).
- Why: the WAN port's `vpn_paths` key and the OrgOverlay traffic steering path name the hub path as `<path>.OrgOverlay`. In this design the hub WAN port is named `wan` (path `HUB-wan`), and the DPD lines name `wan_to_<hub-MAC>_wan`. A path key that does not end in `-wan`, or a hub WAN port whose `name` is not `wan` (SKILL.md step 2.6): stop.
- Lands in: both profiles, `port_config["ge-0/0/2"].vpn_paths` key and `path_preferences.OrgOverlay.paths[0].name`; `hub.path`, `hub.spoke_path_key`.
- How to find: the keys of `paths` in the OrgOverlay VPN; each is `<hub profile name>-<hub WAN port name>`.
- Default: `HUB-wan`, giving `HUB-wan.OrgOverlay`.

**C3. Hub MAC: `<hub-MAC>`**
- Ask: confirm the hub is connected with its own Hub Profile (hub role), and confirm the hub MAC you found.
- Why: the two DPD lines name the IKE gateway Mist generates, `wan_to_<hub-MAC>_wan`.
- Lands in: node 1 lines 113 and 114, node 2 lines 103 and 104; `hub.hub_mac`.
- How to find: from SKILL.md step 2.6, the inventory `mac` of the one device that carries the hub profile, and that it is connected: 12 lowercase hex digits, no separators. None, more than one, or not connected: stop. After the assign, `config_cmd` shows the same name.
- Default: none.

**C4. Hub import accepts IOT**
- Ask: does the hub's overlay import filter accept 10.10.60.0/24?
- Why: IOT routes to the hub over the overlay; a hub that drops them leaves no return path.
- Lands in: `hub.import_accepts_iot`; a prerequisite on the hub, which this skill does not change.
- How to find: you read the hub's render read-only (SKILL.md step 2.6: `GET /sites/{hub site_id}/devices/{hub device id}/config_cmd`) and show, after `redact()`, only the lines that contain both `vpn_OrgOverlay protocols bgp` and ` import `, and the `policy-options policy-statement` lines of each policy they name (the tokens after ` import `, `[` and `]` removed). In this design the hub's overlay import rejected 10.255.0.0/16 orlonger and accepted the rest. The user answers from those lines; the hub's configuration is the user's.
- Default: none; a "no" stops the build.

**C5. Hub site prefixes**
- Ask: the prefixes of the hub site that IOT may reach over the overlay.
- Why: application HUB-SITE-NETS, used by the policy allow-to-hub (IOT to the hub site, path OrgOverlay).
- Validate: each prefix sits inside 10.0.0.0/8, 172.16.0.0/12 or 192.168.0.0/16 (the TO-PEER-ISP filter keeps only those destinations on the active node; any other destination is sent to the peer's ISP, paper section 4.3) and overlaps none of 10.10.10.0/24, 10.10.20.0/24, 10.10.30.0/24, 10.10.40.0/24, 10.10.50.0/24, 10.10.60.0/24 and 10.255.0.0/16. Otherwise stop.
- Lands in: `org-objects.json` step 8 `addresses`; `hub.site_prefixes`.
- How to find: the hub site's address plan.
- Default: `10.200.0.0/16`.

## D. Per-node values

**D1. mgmt-0 addresses: `<NODE1-MGMT-IP>`, `<NODE2-MGMT-IP>`**
- Ask: the out-of-band management network (a /24) and each node's IPv4 address on it.
- Why: mgmt-0 gets a static address with no gateway and the management VRF off, so the WAN DHCP default stays the only default route. mgmt-0 is plugged in only after the node passes the push and cold sync checks.
- Validate: the network is a /24; both addresses are host addresses inside it and differ; neither falls in 10.10.10.0/24 to 10.10.60.0/24, 10.255.0.0/16 or the hub prefixes (C5). Otherwise stop.
- Lands in: `oob_ip_config.ip` of each profile (netmask `/24` is already set); `site.oob_mgmt_network`, `nodes.<n>.mgmt_ip`.
- How to find: the site's out-of-band management plan.
- Default: none.

**D2. Root password hash, per node: `<ROOT-PASSWORD-HASH>`**
- Ask: the path of a local file holding that node's encrypted root password string, and nothing else. Both nodes can point to the same file if the user wants the same password.
- Why: a factory-default SRX400 has no root password; the first push sets it.
- Validate (`read_secret(path, 'root')`): after stripping, the value starts with `$` and holds no whitespace and no `"`. Otherwise stop. Report only "set, N characters".
- Lands in: node 1 line 124, node 2 line 113: `set system root-authentication encrypted-password "<ROOT-PASSWORD-HASH>"`; `nodes.<n>.root_hash_file`. Filled in memory only at the profile POST.
- How to find: on a Junos device that already has the wanted root password, `show configuration system root-authentication | display set | no-more`; the value is the quoted string after `encrypted-password`. Save only that string in the file, mode 600.
- Default: none.

**D3. License keys: `<LICENSE-KEY>`**
- Ask, for each node: does it have its own license key? For each yes, the path of a local file holding only that key.
- Why: the push installs it. A key is bound to one chassis serial: each node gets only its own key, and a node without one gets no license line.
- Validate (`read_secret(path, 'license')`): after stripping, one line with no `"`, the key as it appears in `set system license keys key "..."`. Otherwise stop. Report only "set, N characters".
- Lands in: node 2 line 114 `set system license keys key "<LICENSE-KEY>"` (removed when node 2 has no key); for a node 1 key, the same line added right after node 1's line 124; `nodes.<n>.license_key_file` (`null` for none).
- How to find: the license certificate for that serial.
- Default: none; ask about each node.

## E. Tenant plan and IPv6

**E1. Tenant plan**
- Show this plan and ask the user to confirm it as is. The skill builds exactly this plan: these addresses sit in the org networks, both profiles' native settings and their Additional CLI. A site that needs other VLANs or subnets is outside this skill: stop.

| Network | VLAN | Subnet | Gateway (SRG1 virtual IP) | Node 1 | Node 2 | Preferred ISP |
|---|---|---|---|---|---|---|
| MGMT | 10, untagged | 10.10.10.0/24 | 10.10.10.1 | 10.10.10.2 | 10.10.10.3 | ISP 1 |
| CORP | 20 | 10.10.20.0/24 | 10.10.20.1 | .2 | .3 | ISP 1 |
| GUEST | 30 | 10.10.30.0/24 | 10.10.30.1 | .2 | .3 | ISP 2 |
| MEDIA | 40 | 10.10.40.0/24 | 10.10.40.1 | .2 | .3 | ISP 1 |
| SECURITY | 50 | 10.10.50.0/24 | 10.10.50.1 | .2 | .3 | ISP 1 |
| IOT | 60 | 10.10.60.0/24 | 10.10.60.1 | .2 | .3 | ISP 1; hub site over the overlay |
| ICD (transit link, ge-0/0/5) | none | 10.255.2.0/30 | none | 10.255.2.1 | 10.255.2.2 | |

Also set in both profiles (the user confirms them with the plan): ICL on ge-0/0/4 10.255.0.0/30 (node 1 .1, node 2 .2); loopbacks 10.255.1.1 (node 1) and 10.255.1.2 (node 2); SRG1 signal routes 10.255.3.1 (active) and 10.255.3.2 (backup); transit-link BGP AS 65001 (node 1) and 65002 (node 2); DNS servers 8.8.8.8 and 1.1.1.1, also handed to the DHCP clients of every tenant; NTP pool.ntp.org; DHCP pools .10 to .200, lease 86400 s. A site that cannot reach public DNS, or already uses 10.255.0.0/16, is outside this design: stop.
- Lands in: `org-objects.json` steps 1 to 7; `tenant_plan`.
- Default: this plan.

**E2. Node 1 IPv6 prefix**
- Ask: the IPv6 /60 that ISP 1 delegates to node 1.
- Why: node 1 runs DHCPv6 with prefix delegation and puts one /64 from the /60 on ae0 units 0, 20, 40, 50 and 60 (MGMT, CORP, MEDIA, SECURITY, IOT; GUEST is IPv4 only), with router advertisements and a discard route for the /60.
- Validate: `ipaddress.ip_network(answer, strict=True)` is a /60 and does not sit inside 2001:db8::/32 (the documentation range of the file's example `2001:db8:2000::/60`). Otherwise ask again.
- Lands in: node 1 lines 95 to 105 (5 ae0 addresses, 5 router-advertisement prefixes, 1 discard route); `ipv6.node1_delegated_prefix`. /64 number 1, 2, 4, 5 and 6 of the /60 for units 0, 20, 40, 50 and 60, node address `::2`.
- How to find: ISP 1.
- Default: none. Without a delegated /60 from ISP 1 this design does not apply: stop.

**E3. Profile names**
- Ask, before SKILL.md step 2.6 (its clash check uses these names): keep the default names?
- Why: a name that already exists in the org stops the build unless SKILL.md rule 5 allows reuse (decided at step 3.3); the Mist UI refuses names over 32 characters or with characters other than letters, digits, `_` and `-`. On the Mist UI path the user types this exact name in the Name field of Import Profile.
- Lands in: `name` of each profile; `nodes.<n>.profile_name`.
- Default: `SZTP-SRX400-NODE1`, `SZTP-SRX400-NODE2`.

**E4. Repository path**
- Ask only if `../../mist/` (relative to `SKILL.md`) is missing: the path of the cloned repository.
- Lands in: `repo_path`.
- Default: two levels above `SKILL.md`.

## F. Site readiness (a yes for each; a "no" stops the build until it is a yes)

Lands in (whole group): `site_readiness.*`, `t0_power_on_utc`, `t0_epoch`, `watch_start_epoch`.

**F1. ISP DHCP, each node's ge-0/0/2**: an address, a default route and DNS; a 10-minute lease; no ZTP option (no option 143). ZTP uses the default route and DNS to reach redirect.juniper.net and Mist. After its push a node stays off Mist until its ZTP lease expires on the ISP server; this design uses a 10-minute lease.

**F1b. ISP 1 DHCPv6, node 1's ge-0/0/2**: ISP 1 answers DHCPv6 with IA_NA and IA_PD and always delegates the /60 given in E2. Node 1's profile runs the DHCPv6 client on ge-0/0/2 and carries five /64s from that /60.

**F2. LAN switch**: each node's ge-0/0/3 on its own LAG, LACP active, no force-up; MGMT (VLAN 10) untagged and VLANs 20, 30, 40, 50, 60 tagged; every VLAN bridged between the two LAGs. The factory port runs a DHCP server and no LACP, so the LAG keeps it off the LAN until the push builds ae0. The virtual IPs and the Active Leasequery peers need every VLAN on both nodes.

**F3. Cabling**: ge-0/0/2 to the node's own ISP (ISP 1 on node 1, ISP 2 on node 2); ge-0/0/3 to its own LAG; ge-0/0/4 to the peer's ge-0/0/4 (ICL, MNHA); ge-0/0/5 to the peer's ge-0/0/5 (transit link, eBGP). All cabled before power-on, so MNHA forms with no site visit.

**F4. mgmt-0 unplugged** on both nodes until each passes the push and cold sync checks. ZTP tries DHCP on mgmt-0 first, and factory mgmt-0 has a static address and a DHCP server.

**F5. Power-on**: who powers on both nodes (named by serial) and tells you the time; you record it in UTC as T0. You start `watch.py` just before power-on, so its event search starts 60 s before it. Nobody types on either box.
