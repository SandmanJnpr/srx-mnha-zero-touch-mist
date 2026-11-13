---
name: srx400-zero-touch-mist
description: Drop-ship an SRX400 Multinode High Availability (MNHA) pair to a branch and let Juniper Mist onboard both nodes with zero touch (Secure ZTP through redirect.juniper.net), with nothing typed on either box. Use this skill whenever someone wants to ship SRX400 firewalls or an SRX400 MNHA pair to a site, mentions zero touch, ZTP, SZTP or drop ship with Mist, wants the Mist org objects and one Hub Profile per node built through the Mist REST API, needs Hub Profiles assigned to SRX400 serials before power-on, or wants to watch or verify a zero-touch onboarding (Mist events, push confirmed, MNHA cold sync, BGP, BFD, IPsec, DHCP). It asks the user for every value it needs, reads the Mist API token from a local file, checks the org read-only, asks for an explicit yes before every write, and stops instead of overwriting anything.
---

# SRX400 MNHA zero-touch drop ship with Juniper Mist

Take the user from "two new SRX400s and a Mist org" to two onboarded MNHA nodes, through the Mist
REST API with Python 3 (standard library only) and the client `scripts/mist_api.py`. The design is the
paper `../../docs/SRX400-MNHA-Zero-Touch-Mist.pdf`. Build exactly what these files describe; do not redesign.

| File | Use |
|---|---|
| `references/intake.md` | Every question: why, where the answer lands, how to find it, how to validate it, default |
| `references/mist-api.md` | Every API call, the client functions, read-back rules, traps |
| `scripts/mist_api.py` | The client: `mist()`, `page_total()`, `redact()`, `profile_summary()`, `safe_error()`, `write()`, `read_secret()`, `fill()`, `secret_check()`, `secret_check_pass()` |
| `org-objects.json` | The 8 org objects in create order: 7 networks, 1 application; paths relative to `/api/v1` |
| `../../mist/srx400-node1-zero-touch.json`, `../../mist/srx400-node2-zero-touch.json` | The two Hub Profiles, with placeholders |
| `answers.example.json` | Shape of the local answers file |

If `../../mist/` is not there, ask the user for the path of the cloned repository.

## Ground rules (every step)

1. **Token.** Read the Mist API token inside the request code from the file the user names (default `~/mist-api-token`, mode 600). Never print, log, echo or copy it; never ask for it in chat; never put it on a command line or in a shell variable. If the user pastes a token into the chat, tell them to delete it in Mist and create a new one.
2. **Secrets.** Root password hashes and license keys stay in local files (mode 600) that the user names. Read them with `read_secret()` only inside the one script run that needs them (the intake D2/D3 validation and the "set, N characters" counts of step 1 and step 4.2, which print only the length; step 4.2; a rule 5 reuse check; a correction PUT; the UI path files), never in any other command. Never show them (say "set, N characters"). Everything a command prints enters your context: print only `redact()` output, `profile_summary()` of device profiles, `write()` summaries and `secret_check()` results; save only those. Never print or save a whole device profile other than this skill's own redacted plan and read-backs: other profiles in the org hold their own secrets.
3. **Reads are free, writes are gated.** GET calls need no approval. Before every POST or PUT show method, path, object name and a one-line summary, then wait for an explicit "yes". One yes covers one call.
4. **Snapshot first.** Before the first write, save: the name and `modified_time` of every network, service and VPN in the org; `profile_summary()` of every gateway device profile; the whole OrgOverlay VPN object (it holds no secrets); per node, from `GET /sites/{site_id}/devices/{device_id}`, `deviceprofile_id`, `disable_auto_config` and `mist_configured`; and its `status` and `config_version` (`GET /sites/{site_id}/stats/devices/{device_id}`; record the HTTP status if it is not 200).
5. **Never overwrite.** Name clashes are case-insensitive. An existing object with the same name that equals the planned body field for field (`references/mist-api.md` section 2) is reused read-only (say so); a Hub Profile only if, in addition, `secret_check_pass()` is true on its raw GET against this node's secret files. Any other clash: stop and ask. For a network, say in the stop message that MGMT, CORP, GUEST, MEDIA, SECURITY, IOT and ICD are named in the profiles' Additional CLI (zones, NAT rule-sets), so renaming them is outside this design. Never modify or delete an object you did not create unless the user says so.
6. **One change at a time.** Read back after each write and compare. Any difference: stop and report.
7. **No device-record writes.** Never PUT `/sites/{site_id}/devices/{device_id}`: all configuration lives in the two Hub Profiles, and a device-record write makes Mist re-push a connected gateway. Assign only with the assign call.
8. **Never send** `additional_config_cmds: []` or `null` values. Additional CLI lines start with `set ` or `delete ` only.
9. **Names** match `^[A-Za-z0-9][A-Za-z0-9_-]*[A-Za-z0-9]$`, at most 32 characters. The API accepts names the Mist UI then refuses; check locally.
10. **Do not save the profiles in the Mist UI editor.** A save adds default keys and the profile no longer equals the file.
11. **Working folder.** Keep `answers.json`, `mist_api.py`, snapshots, the redacted plan, read-backs, `watch.py` and `watch.log` in one folder outside the repository clone (mode 700), e.g. `~/srx400-zero-touch/<site>/`, secrets in its `secrets/` subfolder (mode 600 files). Run every script from that folder with plain `python3 <script>`; with `python3 -I`, `sys.path.insert(0, '<working folder>')` before `import mist_api`.
12. **List reads.** Every list read (inventory, networks, services, vpns, deviceprofiles) carries `limit=1000`: Mist sends `X-Page-Total` only then. Show its row count. `page_total()` None, or larger than the rows read: the list is incomplete; stop and tell the user.

## Step 1: Intake

Ask the questions in `references/intake.md`, one group at a time, with the step 2 reads in between, in
this order: A1-A2, written to `answers.json` (`mist.portal_host`, `mist.api_host`, `mist.token_file`:
`mist_api.py` reads them at import); then 2.1-2.2; then A3 and the group A table; group B with 2.3-2.4;
group C with 2.5-2.7; groups D, E and F; then 2.8. Confirm every value you can from those reads instead of asking the user to recite IDs. Record the
answers in `answers.json` shaped like `answers.example.json`; for a secret record only its file path.
Validate each answer as `intake.md` says. At the end of each group show the answers as a table (secrets
as "set, N characters") and get a yes. A "no" in group F, or a hub that does not accept the IOT
subnet: stop until the answer is a yes.

## Step 2: Access and read-only checks

1. API host from the portal host: `manage.<x>.mist.com` becomes `api.<x>.mist.com` (`manage.mist.com` becomes `api.mist.com`). Copy `scripts/mist_api.py` into the working folder (rule 11).
2. `GET /self` (base URL `https://api.<x>.mist.com/api/v1`). On 200 list the `privileges` entries with scope `org` (name, role); the user picks the org by name; the role must be `admin`. No scope `org` entry with role `admin` for the wanted org (for example only an `msp` entry): stop and ask for a token from an account that is admin on that org itself; make no MSP API calls. A 401 almost always means the wrong cloud: re-check the portal host before suspecting the token.
3. `GET /orgs/{org_id}/inventory?type=gateway&limit=1000`. For both serials record `mac`, `id` (device id), `site_id`, `model`, `name`, `connected`, `deviceprofile_id`. Never show `magic` (the claim code). Stop if a serial is missing (first show how many records you read and ask) or has no site, a `model` is not SRX400, the two sites differ, a node is connected (it must start factory default, not from another configuration), or a node already has a `deviceprofile_id` (show that profile's name; go on only if the user says to replace it). Then `GET /sites/{site_id}/devices/{device_id}` per node: `disable_auto_config` false and `mist_configured` true, as in this design (Mist pushes nothing to a node it does not manage), and no device-level override key (the list in `references/mist-api.md` section 3) on the device record; otherwise stop and tell the user (this skill writes no device records). Show each node's `name` as the host name Mist will render; an empty name: the user names the node in Mist before power-on and you read it again (steps 4.4 and 5). Count the connected gateways (for step 3.5).
4. `GET /sites/{site_id}`: show the site name and `timezone`. `gatewaytemplate_id` must be null; otherwise stop. `GET /sites/{site_id}/setting`: if `auto_upgrade.enabled` is true, show its day and time and ask the user to keep power-on and the hour after it out of that window.
5. `GET /orgs/{org_id}/vpns?limit=1000`: a VPN named exactly `OrgOverlay`, type `hub_spoke`, must exist (intake C1: the profiles use names Mist derives from it). Each key of its `paths` is `<hub profile name>-<hub WAN port name>` (default `HUB-wan`); the spoke uses `<path>.OrgOverlay`. One key: confirm it. Several: ask which is the hub's WAN path. No `OrgOverlay`, no path, or a path key that does not end in `-wan` (intake C2): stop (the hub and overlay come first, paper section 7 step 1).
6. `GET /orgs/{org_id}/deviceprofiles?type=gateway&limit=1000` (always with `type=gateway`; print only `profile_summary()` of each): clash check for the two profile names. Find the hub profile: for each profile and each `port_config` entry with `usage` `wan`, build profile `name` + `-` + the entry's `name`; the hub profile is the one where this equals the path key of 2.5 (never split the path key on `-`); the matched `port_config` entry's `name` must be `wan`, otherwise stop (intake C2). Then the hub device: exactly one inventory record whose `deviceprofile_id` is the hub profile's id, and it is connected; none or several: stop. Its `mac` is `<hub-MAC>`. Show it and get a yes. For intake C4, `GET /sites/{hub site_id}/devices/{hub device id}/config_cmd` held in memory: print, after `redact()`, only the lines that contain `vpn_OrgOverlay protocols bgp` and ` import `, and the `policy-options policy-statement <name>` lines of every policy those lines name (policy names are the tokens after ` import `, with `[` and `]` removed). The user answers C4 from them; this skill makes no change to the hub.
7. `GET /orgs/{org_id}/networks?limit=1000` and `GET /orgs/{org_id}/services?limit=1000`: for every name in `org-objects.json`, mark create, reuse or stop (rule 5). If IOT or HUB-SITE-NETS is reused, ask the user to confirm that no other site advertises 10.10.60.0/24 over OrgOverlay; a "no" stops the build.
8. Take and save the snapshot (rule 4).

## Step 3: Plan

1. Org objects: `org-objects.json` in step order, with the hub site prefixes (intake C5) as the `addresses` of HUB-SITE-NETS.
2. Hub Profiles: load both files (127 Additional CLI lines on node 1, 117 on node 2). In each file set:
   - `name`: the profile name (default `SZTP-SRX400-NODE1`, `SZTP-SRX400-NODE2`);
   - `oob_ip_config.ip`: that node's mgmt-0 address;
   - `<hub-MAC>` in the two DPD lines, giving `wan_to_<hub-MAC>_wan`;
   - path not `HUB-wan`: the key under `port_config["ge-0/0/2"].vpn_paths` and `path_preferences.OrgOverlay.paths[0].name` become `<path>.OrgOverlay`;
   - node 1 IPv6, 11 lines: with `net` = the /60 of intake E2 and `s = list(net.subnets(new_prefix=64))` (Python `ipaddress`), `s[n]` replaces `2001:db8:2000:n::/64` and its address `::2` for n = 1, 2, 4, 5, 6 (ae0 units 0, 20, 40, 50, 60), and `net` replaces `2001:db8:2000::/60` in the discard route;
   - license (intake D3): keep node 2's line only if node 2 has a key, otherwise remove it; a node 1 key adds `set system license keys key "<LICENSE-KEY>"` right after node 1's root password line;
   - leave `<ROOT-PASSWORD-HASH>` and `<LICENSE-KEY>` as they are: this redacted plan is what you save and show.
3. Checks, all must pass: no `<NODE1-MGMT-IP>`, `<NODE2-MGMT-IP>` or `<hub-MAC>` left; node 1's 5 ae0 addresses, 5 router-advertisement prefixes and discard route equal `s[1]`, `s[2]`, `s[4]`, `s[5]`, `s[6]` (address `::2`) and `net`, and no `2001:db8:2000` text is left; the only other angle-bracket text is the Junos wildcard `<*_to_*>` (keep it) and the two secret placeholders; every name valid (rule 9); every Additional CLI line starts with `set ` or `delete `; every name the profiles reference exists in the org or in the plan: MGMT, CORP, GUEST, MEDIA, SECURITY, IOT, ICD, HUB-SITE-NETS and the `<path>.OrgOverlay` path (the service `any` is built into Mist and needs no org object).
4. Save the redacted plan. Show a table: # | method | path | object | create or reuse | summary, ending with the two assign calls.
5. Tell the user: in this design, creating the org networks, the application and the two profiles made Mist re-push (commit confirmed) the assigned, connected gateways about 45 to 55 s later, and the only change on them was the NTP server address; treat it as a push to every gateway in the org. Show the count of connected gateways from step 2.3. Get a yes to the plan, then go to step 4.

## Step 4: Apply (before either node is powered on)

Each numbered call is one write: show it, get a yes, make it with `write()`, read it back (`references/mist-api.md` section 2).

1. `POST /orgs/{org_id}/networks` for MGMT, CORP, GUEST, MEDIA, SECURITY, IOT and ICD (skip reused ones), then `POST /orgs/{org_id}/services` for HUB-SITE-NETS. Read each back from the list GET.
2. `POST /orgs/{org_id}/deviceprofiles`, node 1 then node 2. Show name, line count, mgmt-0 address, hub MAC, path, IPv6 /60, root hash "set, N characters", license "set, N characters" or "none", and get the yes. Then run ONE Python script per node that does all of this in one process and prints only the `write()` summary, booleans and counts: `read_secret()` the node's files; `body = fill(plan, root_hash, license_key)`; `secret_check_pass(secret_check(body, root_hash, license_key), has_license)` must be true, otherwise stop with no POST; `write('POST', path, body, secrets=(root_hash, license_key))`; the raw `GET /orgs/{org_id}/deviceprofiles/{profile_id}`; `secret_check()` on it; the redacted compare (no key added, missing or changed; `additional_config_cmds` equal). Never write a filled body or a raw read-back to disk.
3. Take the snapshot again: only the new objects differ. Anything else changed: stop and report.
4. Assign, one node at a time. Right before each assign, `GET /orgs/{org_id}/inventory?type=gateway&limit=1000` and `GET /sites/{site_id}/devices/{device_id}` again: the MAC belongs to that node's serial, `model` SRX400, `connected` false, `site_id` the branch site, `name` not empty, `disable_auto_config` false, `mist_configured` true, no device-level override key, `deviceprofile_id` null or the profile the user agreed to replace; otherwise stop. Then `POST /orgs/{org_id}/deviceprofiles/{profile_id}/assign` with `{"macs":["<node mac>"]}`, expect `{"success":["<node mac>"]}`. Read back `GET /sites/{site_id}/devices/{device_id}`: `deviceprofile_id` is the profile id.
5. Render check, read-only: `GET /sites/{site_id}/devices/{device_id}/config_cmd` per node, held in memory: `_errors` is `[]`; `set chassis high-availability local-id 1` (node 1) or `2` (node 2) present; IKE gateway names taken only from lines matching `^set security ike gateway (\S+) external-interface ge-0/0/2\.0$`: exactly one, equal to the name in the two DPD lines (`wan_to_<hub-MAC>_wan`); at least one line starting `set groups top routing-instances vpn_OrgOverlay protocols bgp group OrgOverlay_overlay neighbor `; none of the placeholders of step 3.3 left (the Junos wildcard `<*_to_*>` stays). Print counts and true/false only, plus the rendered host name line (it starts `set system host-name`). Any failed check: stop, no site hand-off; correct the profile with the gated PUT (`references/mist-api.md` section 4), then run this step again. If `config_cmd` does not answer 200 with a `cli` list, report the status and ask the user whether to go on with the profile read-back alone; the IKE gateway name check then moves to step 7.4.
6. The user can see the assignment in Mist at Organization > WAN > Hub Profiles > <profile> > Applies To Devices (view only: do not click Save, rule 10).

**Mist UI path for the profiles.** It replaces steps 4.2 and 4.4 only; step 4.1 runs first by API. You write the two filled files to `<working folder>/secrets/` (mode 600), the only place a filled body may be saved, and never print them. After your pre-assign checks of step 4.4, the user imports each file at Organization > WAN > Hub Profiles > Import Profile, typing the planned name exactly in the Name field (default `SZTP-SRX400-NODE1`, `SZTP-SRX400-NODE2`), and assigns it at Applies To Devices (paper section 7 steps 6 and 7). You then find each profile by name in `GET /orgs/{org_id}/deviceprofiles?type=gateway&limit=1000`, run the raw `secret_check()` and the redacted compare in one script (report any key the import added and ask the user), read back the assignment, and with a yes delete the filled files. Then step 4.3 after both imports: each UI import also updates the VPN OrgOverlay (`modified_time` changes, content unchanged), so compare the VPN by content without the four keys of `references/mist-api.md` section 2, not by `modified_time`. Then step 4.5.

## Step 5: Site hand-off

First re-read both inventory records and device records: `deviceprofile_id` is the node's new profile, `connected` false, `site_id` the branch site, `name` not empty, `disable_auto_config` false, `mist_configured` true, no device-level override key; otherwise stop. Tell the user not to move, release or unassign either node from now on: a node moved to another site gets a new device record with no profile. Then give the user this list for the site, naming each node by its serial, and get a yes on each line:
- Both nodes on Junos OS Evolved 25.4X300-D30.3, factory default (check on the console: `show version | no-more` shows `Junos: 25.4X300-D30.3-EVO`). A node that has run any other configuration: on its console, before shipping, with only the console cable connected, `request system zeroize ztp-option secure-enable`. The node reboots straight into ZTP: with a cable to a DHCP server and the Internet it onboards wherever it is, so keep WAN, LAN and mgmt-0 unplugged until it is at the site.
- ISP DHCP on each node's ge-0/0/2: address, default route and DNS; 10-minute lease; no option 143. ISP 1 also answers DHCPv6 on node 1's ge-0/0/2 with IA_NA and IA_PD and delegates the /60 of intake E2.
- LAN switch: one LAG per node, LACP active, no force-up; MGMT (VLAN 10) untagged, VLANs 20, 30, 40, 50 and 60 tagged; every VLAN bridged between the two LAGs.
- Cabling, node 1 (serial <node 1 serial>) and node 2 (serial <node 2 serial>): ge-0/0/2 to the node's own ISP (ISP 1 on node 1), ge-0/0/3 to its own LAG, ge-0/0/4 to the peer's ge-0/0/4 (ICL), ge-0/0/5 to the peer's ge-0/0/5 (transit link).
- mgmt-0 unplugged on both nodes: ZTP tries DHCP on mgmt-0 first, and factory mgmt-0 runs a DHCP server. It goes in only in step 7.
- Power on node 1 (serial <node 1 serial>) and node 2 (serial <node 2 serial>) and type nothing on them. Start `watch.py` (step 6) just before power-on; the user reports the power-on time, which you record in UTC as T0.

## Step 6: Watch

No writes and no action on the boxes. Write `watch.py` in the working folder and start it in the background just before power-on (for example `nohup python3 watch.py &`); read `watch.log` every few minutes and report changes to the user. Per node, every 20 s, `watch.py` calls `GET /sites/{site_id}/stats/devices/{device_id}` (status, config_status, config_version, version, uptime, ip, if_stat) and `GET /sites/{site_id}/devices/events/search?mac=<mac>&start=<start>&limit=200` (follow `next`), where `<start>` is the epoch at which `watch.py` started minus 60 s, and appends to `watch.log`, through `redact()`, one line per change with the UTC time and, once the user has reported T0, the elapsed time from T0, plus a heartbeat every 5 minutes. A non-200 stats answer before the node's first GW_CONNECTED is logged, not an alert.

Event rules: sort by `timestamp`. GW_ZTP_STARTED, GW_CONNECTED and GW_DISCONNECTED can each come twice, up to 2 minutes apart: keep the first of each pair. Mist logs no event for the push itself: the push is marked by the first GW_DISCONNECTED after the first GW_CONNECTED that follows GW_ZTP_FINISHED, and the node is back after its push at the first GW_CONNECTED after that GW_DISCONNECTED. Events can arrive up to about 5 minutes late: judge every window by event timestamps, not by arrival.

Measured in this design (push and push confirmed from `show system commit`):

| Interval | Node 1 | Node 2 |
|---|---|---|
| GW_ZTP_STARTED to GW_ZTP_FINISHED | 0:25 | 0:27 |
| GW_ZTP_FINISHED to GW_CONNECTED | 1:23 | 1:24 |
| GW_CONNECTED to the push (commit confirmed) | 3:17 | 3:15 |
| Push to GW_DISCONNECTED | 0:44 | 0:40 |
| GW_DISCONNECTED to GW_CONNECTED (off Mist) | 3:13 | 2:48 |
| Push to push confirmed | 5:38 | 4:40 |

Counted from the zeroize, which includes the zeroize reboot (paper section 5), GW_ZTP_STARTED came at 27:49 on node 1 and 18:14 on node 2, and GW_CONNECTED at 29:37 and 20:05 (node 1 booted 8 min 41 s slower). Then the BACKUP node logs GW_HA_SRG_STATE_CHANGED (HOLD to BACKUP) and GW_HA_SRG_HEALTH_UP, and GW_BGP_NEIGHBOR_UP shows the transit-link BGP peer up. About 3 minutes off Mist after the push is normal: the ISP answers the new Junos DHCP client once the ZTP lease expires. Do nothing inside the 10-minute commit confirmed window.

Alert the user at once on: an event type that contains FAILED or ERROR_ADDTL_COMMAND (GW_ZTP_FAILED, GW_CONFIG_FAILED, LOCK_FAILED and the like) or starts with GW_ZTP_PRE_SCRIPT_ or GW_UPGRADE_. Absence alerts: no GW_ZTP_STARTED by T0 + 35 min; no GW_CONNECTED by T0 + 45 min; no push GW_DISCONNECTED 15 min after the first GW_CONNECTED; no GW_CONNECTED 11 min after the push GW_DISCONNECTED (an unconfirmed push rolls back 10 minutes after the push). Raise an absence alert only when the poll time is at least 5 minutes past the window end and the event is still absent. On an alert: no writes and no restarts. Tell the user, and ask for read-only checks on the node's console if someone at the site can log in: `show system ztp`, `show log phc.log`, `show dhcp client binding` (paper section 2.2).

A node is done watching when it is back on Mist after its push: go to step 7 for that node. `watch.py` keeps running until step 8. `config_status` (NO_CHANGE, INPROGRESS, AWAITING_CONFIRM, COMMITED, FAILED) does not prove a push, and the stats can show an old `config_version` or `rebooting` for minutes. Judge by the events and by the show commands of step 7.

## Step 7: Verify

The user runs the commands on each node, in the node's Remote Shell in Mist or on its console, and reports the result. The configuration holds the root hash: never ask for it in chat. Relay every command exactly as written in the code blocks.

1. Push: `show system commit | no-more`: an entry by root via netconf `commit confirmed, rollback in 10mins` with `version=<config_version>`, followed by a later netconf commit that confirms it; no rollback entry.
2. Cold sync: `show chassis high-availability information | no-more`: peer on ge-0/0/4.0 Conn State UP, SRG1 ACTIVE on one node and BACKUP on the other, Cold Sync Status COMPLETE. In this design cold sync was still not COMPLETE 20 to 24 minutes after the later node's push was confirmed. Propose a restart only when it is still not COMPLETE 20 minutes after the later node's push is confirmed:
   - a. Before each restart (BACKUP, then ACTIVE), the newest `show system commit` entry on that node does not show `rollback pending` (a reboot then rolls the push back).
   - b. With a yes: `POST /sites/{site_id}/devices/{device_id}/restart`, body `{}`, for the BACKUP. Expect GW_RESTART_BY_USER, GW_CONNECTED about 6.5 min later, and a re-push of the same config_version (rollback pending until Mist confirms it). Mist can show `rebooting` for about 10 minutes after the restart, minutes after GW_CONNECTED.
   - c. About 12 minutes after that GW_CONNECTED, check again. Still not COMPLETE: check a on the ACTIVE, then with a yes the same restart for the ACTIVE. SRG1 moves to the other node and stays (no preemption). In this design both reboots were needed; cold sync was COMPLETE 5 min 30 s after the ACTIVE node's reboot. Repeat check 1 after each reboot.
3. mgmt-0: a node that passes 1 and 2 gets its mgmt-0 plugged in; it answers at its mgmt-0 address from the out-of-band subnet.
4. Both nodes (paper section 6). Commands, in this order:

```
show version | no-more
show system ztp | no-more
show configuration | display set | match "jdhcp-group|junosDHCPPool|phone-home" | no-more
show chassis high-availability information detail | no-more
show bgp summary | no-more
show bfd session | no-more
show security ike security-associations detail | no-more
show security ipsec security-associations | no-more
show dhcp client binding detail | no-more
show dhcp server binding routing-instance lan detail | no-more
show system license | no-more
show system alarms | no-more
show system core-dumps | no-more
```

Node 1 also:

```
show dhcpv6 client binding detail | no-more
```

| Check | Expect |
|---|---|
| Version | Junos: 25.4X300-D30.3-EVO |
| ZTP | ZtpState CONFIG_COMMIT_ABORTED (the expected end state), ZtpInterface ge-0/0/2, ZtpPlatformDefault Secure |
| Factory lines | No output |
| MNHA detail | CS RTO sync 1 of 1 SPUs completed, ae0 Up, Failure Events: NONE, Peer ICD Conn State UP |
| BGP | 2 peers Established: 10.255.2.2 (node 1) or 10.255.2.1 (node 2) in lan.inet.0, the hub in vpn_OrgOverlay.inet.0 |
| BFD | 4 sessions Up, 1000 ms, multiplier 3 |
| IKE, IPsec | IKEv2 SA UP on gateway wan_to_<hub-MAC>_wan, local ge-0/0/2.0; one IPsec tunnel |
| WAN DHCP | ge-0/0/2.0 BOUND, lease 10 minutes; node 1 DHCPv6 BOUND, IA_NA IA_PD, the /60 as Client IP Prefix |
| LAN DHCP | The same client on both nodes (Active Leasequery) |
| License | The node's key if its profile carries one, else none installed |
| Alarms, cores | 0 alarms; no core files |

5. Mist audit: `GET /orgs/{org_id}/logs?start=<T0>&limit=50` (follow `next`): the entries whose `site_id` is the branch site or whose `message` names a node MAC are only the restarts the user approved.
6. Tenants: a host on IOT gets an address in 10.10.60.10-10.10.60.200; it and a host on GUEST ping their gateway (10.10.60.1, 10.10.30.1) and an Internet address, 5 of 5 each.

Report PASS only when checks 1 to 6 match; otherwise report the failing check and its output.

Optional, for information only (not part of PASS): if the user saves a node's `show configuration | display set | no-more` to a local file (mode 600; it holds the root hash), diff it against `config_cmd` with a script that redacts before printing. Expected differences: the Mist agent block (groups mist-script, user mist, outbound-ssh, ephemeral db, extensions, syslog files, pki ca-profiles, scripts), the NTP server address, the notation of groups apbr, lo0.1 and st0.0, the version line, and the render-only `deactivate interfaces ge-0/0/3 unit 0`. Report any other line.

## Step 8: Close out

Stop `watch.py`. List the objects you created, by name (ids stay in the working folder). Remind the user that the API token stays valid until they delete it in Mist. With a yes, delete the secret files and any filled copies; otherwise leave them at mode 600. Everything else in the working folder is redacted.

## Pointers

- Paper `../../docs/SRX400-MNHA-Zero-Touch-Mist.pdf`: 3.1 checklist, 4 profile settings, 5 measured onboarding, 6 verification, 7 deployment steps, 8 reference files and placeholders.
- `../../junos/srx400-node{1,2}-zero-touch.set`: each node's configuration after onboarding, display set form.
- `references/intake.md`, `references/mist-api.md`, `scripts/mist_api.py`.
