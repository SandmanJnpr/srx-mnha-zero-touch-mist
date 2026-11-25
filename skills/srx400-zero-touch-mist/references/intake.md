# Intake: the questions about the customer's proposed topology

Every question the agent asks the customer, in the groups of SKILL.md step 1 (the order and the read-only
checks between the groups are in that step). The customer needs no drawing: the agent asks, derives the
rest, and shows the topology and plan that `scripts/build_plan.py` generates (SKILL.md step 3).

Per question: **Ask** (the wording to use; `<...>` is filled from earlier answers or reads; outside code
this file writes it `\<...\>` so that it shows on GitHub, and both forms mean the same), **Why**,
**Default**, **How to find**, **Validation** (the check in `scripts/build_plan.py`; `validate()` runs them
all), **Lands in** (the `answers.json` path, then where it ends up in the org objects and profiles) and
**Answers** (each answer class and what happens).

## How answers are handled

| Outcome | What the agent does |
|---|---|
| build | Record the answer in `answers.json` and go on. A build answer is either the structure the reference pair runs (proven on hardware) or one that `build_plan.py` builds beyond it: `plan.md` lists each of those in its first section under "Beyond the reference design", and the agent names them before the plan's yes (SKILL.md step 3.2) |
| re-ask | Say why and what is accepted (the validator message says it), ask the same question again |
| stop | Give the stop message (quoted below; `build_plan.py` prints it with exit status 2) with its alternative. A stop is either a limit of the platform, of zero touch or of Mist, or an option this design does not build (the message says "not supported by this design", "a different design" or "these profiles do not build"). Nothing is written to Mist until the answer changes |
| precondition | The org or the site must change first (claim, assign, zeroize, cable, hub change). The customer acts; the agent checks again read-only, then goes on |

Every `build_plan.py` message starts with the question ID it belongs to. Two planned IPv4 ranges that
overlap (`check_overlaps()`, run on every range answered so far) carry the ID of the range asked later
(W3, then M1, I1, T3, H5) and name both ranges: ask again whichever of the two the customer wants to
change. `X` is a requested HA form or probe (stop, see "Requests at any point"). `schema` means
`answers.json` lost its shape or still holds example text `<...>`.

Answer classes that apply to every question:

| Class | Example | What the agent does |
|---|---|---|
| Accepts the default | "yes", "default", "keep" | Build with the default named in the question |
| Does not know | "not sure" | Say how to find it (How to find), offer the default if there is one, ask again |
| Free text that maps to one class | "24 hours" (T9), "the ISP router does DHCP" (W1) | Normalize it (86400; `dhcp-untagged`) and show the normalized value in the group table |
| Free text that maps to no class | "whatever works" | Ask again with the accepted forms |
| A secret pasted in the chat | a token, hash or key in a message | Do not use it. Tell the customer to replace it (a token: delete it in Mist and create a new one), save the new one in a file and give the path; ask again |
| Changes an earlier answer | "make GUEST VLAN 35" at E1 | Validate it again with every answer that depends on it (overlaps, derived defaults, the plan), show the group table again |
| Answers a question not yet asked | "node 2's ISP is on ge-0/0/6" during B | Record it; confirm it when that question comes |

Record every answer, accepted defaults included, in `answers.json`. It starts as
`{"schema": "srx400-zero-touch-mist.answers.v2"}` and holds only the answers given and the values read from Mist,
in the shape of `answers.example.json`; never copy `answers.example.json` (a shape reference: `validate()` refuses
its example text `<...>` and read values that are not in the forms Mist gives them, under the question that reads
them: A3, B1, B2, H4). A key left out takes the default named below (`build_plan.py` applies the same defaults).
For a secret record only its file path. At the end of each group show the group's answers as a table (secrets as
"set, N characters") and get a yes. Never add a `_fixture` key: it belongs to the repository's test files only. An
`answers.json` that already exists in the working folder is never overwritten: the agent keeps every key it holds (a
`_fixture` key included), shows its recorded answers group by group for a yes, asks only what is missing or has a
problem, and reads the Mist values again (SKILL.md step 1).

## A. Mist access

**A1. Mist cloud**
- Ask: "Which Mist cloud is your org on? Copy the host from the browser address bar while you are in the Mist portal, for example `manage.mist.com` or `manage.<cloud>.mist.com`."
- Why: the API host is `api.<cloud>.mist.com`; the wrong cloud answers 401 even to a valid token.
- Default: none.
- How to find: the Mist portal URL. `GET /self` confirms it.
- Validation: `check_A1()`; a pasted URL keeps only its host; `api_host()` gives the API host, and `validate()` re-asks a recorded `mist.api_host` that is not it (`mist_api.py` sends nothing to any other host and follows no redirect).
- Lands in: `mist.portal_host`, `mist.api_host` (read by `mist_api.py` at import).
- Answers: a portal host of any Mist cloud, or a pasted portal URL: build, with the API host derived from it. An `api.` host or a host that is not Mist's: re-ask. `GET /self` answers 401: ask A1 again before suspecting the token.

**A2. API token file**
- Ask: "In Mist, create an API token (person icon > My Account > API Token > Create Token) on an account that is admin of the org. Mist shows it once: save it in a local file that holds only the token, run `chmod 600 <file>`, and tell me the path. Do not paste the token here."
- Why: every call authenticates with it; the agent reads it only inside the request code.
- Default: `~/mist-api-token`.
- How to find: the file the customer saved.
- Validation: `check_A2(path)` (the file exists, only its owner can read it, and it holds one token line of letters and digits; the message gives its length at most, never the value).
- Lands in: `mist.token_file`.
- Answers: a file, mode 600, that holds only the token: build. No file at the path, readable by others, or more than the token in it (a note line): re-ask. A token pasted in the chat: tell the customer to delete it in Mist and create a new one.

**A3. Org**
- Ask: "Your token reaches these orgs: \<list from GET /self\>. Which one should I build in?"
- Why: every org path uses its `org_id`; org networks, applications and Hub Profiles need an admin.
- Default: the only org, if the token has one.
- How to find: `GET /self`, its `privileges` (SKILL.md step 2.2: `python3 mist_api.py /self` prints `scope`, `org_id`, `msp_id`, `name` and `role` of each entry, and `orggroup_ids` when set); an MSP admin token lists its orgs to pick from with `GET /msps/{msp_id}/orgs`, `{msp_id}` from its `msp` entry; the proof is `GET /orgs/{org_id}` of the chosen org (its `msp_id` and `orggroup_ids`).
- Validation: `check_A3_privileges(privileges, org_id, org=<GET /orgs/{org_id}>)`.
- Lands in: `mist.org_name`, `mist.org_id` (you fill it), `mist.access` (`org-admin` | `msp-admin`).
- Answers: org admin: build (proven). Admin of the MSP whose id the org's `msp_id` carries, or admin of an org group in the org's `orggroup_ids`: build, beyond the reference design (`plan.md` lists it); writes stay on `/orgs/{org_id}`. An org the token cannot reach (also an MSP admin of another MSP): re-ask. Role write, read, helpdesk, installer or observer: stop, "A3: this token has role \<role\> on the org; the org networks, applications and Hub Profiles need an org admin (Super User). Alternative: create the token from an account with the admin role on this org". Site or site-group access only: stop, "A3: this token has only \<site | site-group\> access to the org (role \<role\>); the org networks, applications and Hub Profiles need an org admin (Super User). Alternative: create the token from an account with the admin role on this org".

## B. Site and devices

**B1. Branch site**
- Ask: "What is the Mist site name of the branch? Both firewalls must already be assigned to it."
- Why: the profiles are assigned to the devices of that site; stats, events, render and restart calls use its `site_id`.
- Default: none.
- How to find: the customer; you confirm it from the inventory `site_id` of both serials, `GET /sites/{site_id}`, `GET /orgs/{org_id}/setting` and `GET /sites/{site_id}/setting` (SKILL.md steps 2.3, 2.4).
- Validation: `check_B_inventory(rec1, rec2)`; `check_site_settings(org_setting, site_setting, release)` (a site value takes the place of the org value), run in group 3 and again after B4 with the B4 release, before the writes (SKILL.md step 3.3) and at the hand-off (step 5).
- Lands in: `site.name`, `site.site_id`, `site.timezone`, `site.gatewaytemplate_id` (read).
- Answers: a site with no gateway template: build. A site that binds a gateway template: build, beyond the reference design (an assigned Hub Profile is meant to take the template's place; the render check of SKILL.md step 4.5 checks it before the hand-off). A node in no site: precondition, "B1: node \<n\> is not assigned to a site: assign it to the branch site, then tell me". The nodes in two sites: precondition, "B1: the two nodes sit in different sites; assign both to the branch site". Settings that change the zero-touch push: precondition, the customer changes them, you read both settings again: SRX firmware auto-upgrade on first onboarding (`juniper_srx.auto_upgrade` enabled) unless `custom_versions` pins SRX400 to the B4 release (Mist would upgrade both nodes during zero touch; a pin read before B4 is answered shows as a B4 problem and is judged after B4); `config_push_policy` `no_push` or an enabled `push_window`; `gateway_mgmt` `config_revert_timer` other than 10 (the 10-minute commit confirmed window of W4, step 6 and step 7), `protect_re` enabled, a `root_password`, or `disable_oob`. The AP firmware window (`auto_upgrade` of the site setting) does not upgrade gateways and is not judged.

**B2. Serials and node 1**
- Ask: "What are the two serial numbers, and which firewall is node 1? Node 1 uses ISP 1, is the preferred active firewall (priority 200: when SRG1 forms, node 1 becomes active; without preemption a node that joins while its peer is active joins as backup) and, by default, takes the second address on every network; node 2 takes the third."
- Why: each serial gives the MAC and device id for the assign, render, stats, events and restart calls; node 1 or node 2 sets the role.
- Default: none.
- How to find: the box labels. Both serials must be in the org inventory.
- Validation: `check_B2()` (6 to 20 letters and digits, different); `check_B_inventory()` on the inventory records; `check_device_record(rec, n)` on each node's device record (`disable_auto_config` absent or false, `mist_configured` true, no device-level setting); `validate()` checks the read `mac` (12 lowercase hex digits, not a documentation MAC) and `device_id` (`00000000-0000-0000-1000-<mac>`).
- Lands in: `nodes.<n>.serial`; you fill `model`, `mac`, `device_id` (never show the claim code `magic`).
- Answers: two SRX400 serials of the inventory, either one as node 1: build. The same serial twice, or a malformed serial: re-ask. A serial not in the inventory (first say how many records you read): precondition, "B2: node \<n\> serial is not in the org inventory: claim it into this org and assign it to the branch site, then tell me". Another model: stop, "B2: node \<n\> is an \<model\>; this design is for an SRX400 pair" (`a` before a model read without a vowel sound). A node that already carries a Hub Profile: show its name and ask whether to replace it; yes: build; no: stop until the customer chooses. A device record with `disable_auto_config` true, `mist_configured` not true, or device-level settings (keys such as `port_config`, `mnha_config`, `vrf_config`, `vars` with a value): precondition, the customer changes it in Mist (this skill writes no device records), as `check_device_record()` says.

**B3. Device names**
- Ask: "Mist renders the host names from the device names: node 1 `<name>`, node 2 `<name>`. Keep them?"
- Why: the agent never writes device records; the customer names the devices in Mist. The HA link and transit-link port descriptions name the peer by its node number (SRX400-1, SRX400-2), whatever the device names are.
- Default: the current names; recommend SRX400-1 and SRX400-2 (the names the port descriptions use). Give the recommendation when you ask.
- How to find: the inventory `name`.
- Validation: `check_B_inventory()` (name not empty).
- Lands in: `nodes.<n>.mist_device_name` (read).
- Answers: names set: build. An empty name: precondition, "B3: node \<n\> has no name in Mist: name it (Mist renders the host name from it)"; the build goes on, and you read the name again before the assign (SKILL.md step 4.4) and at the hand-off (step 5).

**B4. Release and factory state**
- Ask: "Which Junos release is on each firewall (on the console, `show version | no-more` prints the Junos line), and is each firewall in its factory-default state?"
- Why: the design is proven on Junos OS Evolved 25.4X300-D30.3, the only release it has run on (managed-services dhcp and Active Leasequery come with D30), and starts from factory default (Mist does not delete chassis high-availability lines a node already has).
- Default: none.
- How to find: `show version | no-more` on the console shows `Junos: 25.4X300-D30.3-EVO`.
- Validation: `check_B4(release, factory_default)`; `check_B_inventory()` (a node connected to Mist).
- Lands in: `release`, `site_readiness.factory_default`.
- Answers: 25.4X300-D30.3: build (proven). A later 25.4X300 release (D30.4 and on, D31 and on): build, beyond the reference design (`plan.md` names the release). Release unknown: re-ask (show version on the console). A release before D30: stop, "B4: \<release\> has no MNHA DHCP (managed-services dhcp and Active Leasequery arrive in D30). Install 25.4X300-D30.3 on the console before shipping". A D30 release older than D30.3: stop, "B4: \<release\> is older than 25.4X300-D30.3, the release this design runs on. Install 25.4X300-D30.3 on the console before shipping". Not a 25.4X300 release: stop, "B4: \<release\> is not a Junos OS Evolved 25.4X300 release for SRX400. Install 25.4X300-D30.3 on the console before shipping". Not factory default, or the node is connected to Mist: precondition, "B4: on the console, with only the console cable connected, run request system zeroize ztp-option secure-enable; keep WAN, LAN and mgmt-0 unplugged until the box is at the site" (the node reboots straight into zero touch and onboards wherever it has a DHCP server and the Internet).

## P. Ports (per node)

Ports are ge-0/0/0 to ge-0/0/9; ge-0/0/0 and ge-0/0/1 take a 1G SFP optic. mgmt-0 is the out-of-band port only.

**P1. Same layout on both nodes**
- Ask: "Do both firewalls use the same ports for the same roles? The usual layout: ge-0/0/2 to the ISP, ge-0/0/3 to the LAN switch as a LAG with LACP (one LAG per firewall on the switch, LACP active), ge-0/0/4 cabled straight to the other firewall's HA port, ge-0/0/5 cabled straight to the other firewall's transit port. Say yes to use it, or tell me the ports of each firewall and whether the switch runs LACP."
- Why: each node's profile names only its own ports.
- Default: yes (ge-0/0/2, ge-0/0/3, ge-0/0/4, ge-0/0/5 on both).
- Validation: `check_ports()`.
- Lands in: `nodes.<n>.ports.{wan,lan,lan_lacp,icl,icd}`.
- Answers: yes: build (proven), P2 to P5 take the defaults (LAN ge-0/0/3 with LACP). Other ports, or no LACP on the switch: ask P2 to P5 (any port other than the defaults builds beyond the reference design). A port that is not ge-0/0/0 to ge-0/0/9, mgmt-0, or one port for two roles: re-ask.

**P2. WAN port** (per node)
- Ask: "Which port on node \<n\> is cabled to ISP \<n\>?"
- Why: zero touch gets its first lease on a factory DHCP-client port; the WAN port and the WAN DHCP and DHCPv6 lines name it.
- Default: ge-0/0/2.
- Validation: `check_ports()`.
- Lands in: `nodes.<n>.ports.wan` (the WAN `port_config` entry, the WAN DHCP and DHCPv6 lines, the IKE gateway's external interface).
- Answers: ge-0/0/2: build (proven). ge-0/0/0, ge-0/0/1 or ge-0/0/4 to ge-0/0/9, the same or different per node: build, beyond the reference design (the zero-touch lease on that port). ge-0/0/3: stop, "P2: node \<n\>: ge-0/0/3 runs the factory DHCP server, not a DHCP client, so zero touch cannot get the ISP lease there. Use any other port for the WAN". Two WAN ports on one node: stop (W1).

**P3. LAN ports and LACP** (per node)
- Ask: "Which port or ports on node \<n\> are cabled to the LAN switch, and does the switch run LACP on them (one LAG per firewall)? LACP is recommended: it keeps the factory port settings off your LAN until the configuration arrives."
- Why: the LAN carries every network VLAN, the virtual IPs and the DHCP binding sync; LACP keeps the factory DHCP server on ge-0/0/3 off the LAN until the push builds ae0.
- Default: ge-0/0/3, LACP yes.
- Validation: `check_ports()`.
- Lands in: `nodes.<n>.ports.lan`, `nodes.<n>.ports.lan_lacp` (the LAN `port_config` entry; every line that names the LAN interface: `ae0` with LACP, the port itself without).
- Answers: ge-0/0/3 alone with LACP: build (proven). Another port, or two to seven ports, with LACP: build, beyond the reference design. One port without LACP, not ge-0/0/3: build, beyond the reference design (the plain port replaces ae0). No port, more than seven, a port listed twice, or several ports without LACP: re-ask. ge-0/0/3 without LACP: stop, "P3: node \<n\>: without LACP the factory DHCP server on ge-0/0/3 would hand out 192.168.2.x leases on the LAN before the push. Use LACP on ge-0/0/3 or another port for a plain LAN link". One LAG across both firewalls (MC-LAG, ESI-LAG): record `nodes.<n>.ports.lan_lag_across_nodes` true; stop, "P3: node \<n\>: one LAG across both firewalls (MC-LAG / ESI-LAG); MNHA nodes are separate devices, so each node has its own LAG (one LAG per firewall on the LAN switch, LACP active)".

**P4. HA link (ICL)** (per node)
- Ask: "Which port on each firewall is the HA link, cabled directly to the other firewall?"
- Why: MNHA control and forwarding run over it.
- Default: ge-0/0/4 on both.
- Validation: `check_ports()`.
- Lands in: `nodes.<n>.ports.icl` (the ICL interface, the HA zone and the peer-id lines).
- Answers: ge-0/0/4 on both, or ge-0/0/5 on both with the transit link (P5) on ge-0/0/4: build (proven). Any other free port, the same or different per node, ge-0/0/3 on both ends included: build, beyond the reference design (SKILL.md step 4.5 confirms that the render leaves ge-0/0/3 unit 0 active; if it does not, the role moves off ge-0/0/3). ge-0/0/3 on one end only: stop, "P4: ICL: ge-0/0/3 on one node and \<port\> on the other: at factory default the ge-0/0/3 DHCP server would give the peer port a second default route during zero touch. Use ge-0/0/3 on both ends or on neither".

**P5. Transit link (ICD)** (per node)
- Ask: "Which port on each firewall is the transit link, cabled directly to the other firewall? It carries each network's traffic to the other firewall's ISP."
- Why: the eBGP default exchange and the cross-node Internet path.
- Default: ge-0/0/5 on both.
- Validation: `check_ports()`.
- Lands in: `nodes.<n>.ports.icd` (the transit-link `port_config` entry).
- Answers: as P4 (ge-0/0/5 on both, or ge-0/0/4 on both with the HA link on ge-0/0/5, is the proven form); the stop message starts "P5: ICD: ...".

## W. ISPs (ISP n is cabled to node n)

**W1. Hand-off**
- Ask: "How does ISP \<n\> hand over the Internet to node \<n\>: DHCP on an untagged Ethernet port, a static address, PPPoE, or a tagged VLAN? (Or: node \<n\> has no ISP of its own.)"
- Why: a factory-default SRX400 sends only untagged DHCP; zero touch needs that lease to reach Mist.
- Default: DHCP, untagged.
- How to find: the ISP contract or the ISP router.
- Validation: `check_W()`, `check_ports()`.
- Lands in: `isps.<n>.handoff` (`dhcp-untagged`, `static`, `pppoe`, `dhcp-tagged`, `none`).
- Answers: DHCP untagged, also from an ISP router in front: build. Not one of the forms: re-ask. While W1 stops for ISP n, keep the W2 to W4 answers of ISP n that the customer gives in `answers.json`; once W1 changes to a form that builds, confirm them in the group table. Static, PPPoE or tagged VLAN: stop, "W1: ISP \<n\> uses \<a static address | PPPoE | an 802.1Q-tagged VLAN\>. A factory-default SRX400 only sends untagged DHCP, so zero touch cannot reach Mist. Alternative: put an ISP router in front that hands the firewall an untagged DHCP lease (its LAN range is then the WAN subnet), or onboard this pair another way". No ISP on the node: stop, "W1: ISP \<n\> uses no WAN on this node. A factory-default SRX400 only sends untagged DHCP, so zero touch cannot reach Mist. Alternative: give node \<n\> its own DHCP lease (a second port on the ISP router or a small switch)". Two ISPs on one node (also an LTE backup): record `isps.<n>.wan_count` 2 (or two WAN ports); stop, "W1: node \<n\> has 2 WAN links; each node needs its own DHCP lease; a second WAN per node is a different design (one DHCP default per node is what the transit-link BGP exports). Alternative: one ISP per node".

**W2. ISP label**
- Ask: "What should I call ISP \<n\> in the plan (for example the provider's name)?"
- Why: readability of the plan only.
- Default: "ISP \<n\>".
- Validation: printable text, up to 40 characters.
- Lands in: `isps.<n>.label` (plan only).
- Answers: any label: build.

**W3. WAN address range**
- Ask: "If you know it, which address range does ISP \<n\> (or its router) hand out? Otherwise say unknown."
- Why: overlap checks against the networks, the internal block and the out-of-band network, and against the factory ge-0/0/3 subnet.
- Default: unknown.
- Validation: `check_W()` (/8 to /30, host bits zero), `check_overlaps()`; unknown: `check_R()` asks R9.
- Lands in: `isps.<n>.wan_subnet` (checks and plan only; no configuration line; unknown = `null`, the literal `"unknown"` is read the same way).
- Answers: a range that overlaps nothing: build. Unknown: the generator cannot check that range against the factory ge-0/0/3 subnet or the planned ranges, so R9 asks the customer to check it before the build (a yes builds; the range itself, given later at W3, runs the checks). 192.168.2.0/24 on a node with no role on ge-0/0/3: build. Malformed, or overlapping a planned range: re-ask. 192.168.2.0/24 while ge-0/0/3 is cabled on that node: stop, "W3: ISP \<n\> hands out \<range\>, which overlaps the factory ge-0/0/3 subnet 192.168.2.0/24 that is up on node \<n\> during zero touch. Alternative: change the ISP router LAN range, or move node \<n\> roles off ge-0/0/3".

**W4. DHCP after the first push**
- Ask: "When the configuration arrives, the firewall asks ISP \<n\> for an address again as a new DHCP client. Does the ISP give it an address at once (it has more than one to give), or does it hold its one address until the first lease ends? If it holds it, how long is the lease?"
- Why: Mist confirms the push only once the node is back on Mist, and the push rolls back 10 minutes after it is made.
- Default: none.
- How to find: the ISP, or the lease time on the ISP router.
- Validation: `check_W()`.
- Lands in: `isps.<n>.lease_behavior` (`held` | `new-address`), `isps.<n>.lease_seconds` (onboarding only; no configuration line).
- Answers: held for 10 minutes or less: build (proven). Held for 11 to 13 minutes, or a new address at once: build, beyond the reference design. Held, length unknown, or not known at all: re-ask. Held longer than 13 minutes: stop, "W4: ISP \<n\> holds the one address for \<m\> minutes. After the first push the firewall asks again as a new DHCP client and gets an address only when the zero-touch lease ends; Mist confirms the push once the node is back on Mist, and an unconfirmed push rolls back 10 minutes after it is made. With a 10-minute lease node 1 was back on Mist 3 min 57 s and the push confirmed 5 min 38 s after the push; each extra minute of lease adds about a minute, so a lease longer than 13 minutes leaves less than a minute before the rollback (at 15 minutes the confirm comes after it). Alternative: ask the ISP for a lease of 13 minutes or less for the install, or an ISP router that hands out a second address". The 13-minute limit is derived from that measured timeline (SKILL.md step 6), not from a platform limit: 13 minutes leaves node 1's confirm about a minute and a half before the rollback.

**W5. Same upstream** (asked only when both WAN ranges are the same)
- Ask: "Both ISPs hand out the same range: is it one upstream router feeding both firewalls (yes), or two separate ISP routers that use the same range, for example both on 192.168.0.0/24 (no)?"
- Why: with one upstream, steering splits the load only and the plan says there is no ISP diversity; two routers with the same range are no overlap, since each WAN subnet stays on its own node.
- Default: none.
- Validation: `check_W()`; while W5 is not answered, `check_overlaps()` holds back the overlap of the two WAN ranges.
- Lands in: `isps.same_upstream` (`true` | `false`; `null` until answered).
- Answers: yes: build, beyond the reference design; the plan says there is no ISP diversity. No (two separate routers): build. Not answered: re-ask.

## V. IPv6 (per ISP)

IPv6 is per node: the node whose ISP delegates a prefix serves IPv6 (SLAAC) on the networks that take it,
with a static /64 per network and a discard route for the prefix. Each network takes IPv6 from one ISP, and
IPv6 has no failover: while the serving node or its ISP is down, that network has no IPv6 (its IPv4 moves to the
other node).

**V1. Prefix delegation**
- Ask: "Does ISP \<n\> delegate an IPv6 prefix to node \<n\> (DHCPv6 prefix delegation)?"
- Why: decides the DHCPv6 client on that node's WAN port and the IPv6 lines on its networks.
- Default: no (IPv4 only).
- How to find: the ISP.
- Validation: `check_V()`.
- Lands in: `isps.<n>.ipv6_pd` (the WAN port's DHCPv6 client and the IPv6 lines of node n).
- Answers: yes or no for each ISP, also no for both (IPv4 only): build. Not yes or no: re-ask. No delegation while a network asks for IPv6 from that ISP: re-ask T10.

**V2. Delegated prefix** (V1 = yes)
- Ask: "Which prefix does ISP \<n\> delegate (for example a /60)? If you will only know it after the firewall connects, say unknown and give the prefix length."
- Why: each IPv6 network gets a static /64 from it; the discard route covers it.
- Default: none (length 60 when unknown).
- Validation: `check_V()`: /48 to /64, global unicast, host bits zero, not a documentation prefix (2001:db8::/32, 3fff::/20), the two ISPs' prefixes do not overlap.
- Lands in: `isps.<n>.delegated_prefix`, `isps.<n>.pd_length`.
- Answers: a /60: build (proven). A /48 to /64 prefix of another length: build, beyond the reference design. Unknown with a length of 48 to 64: build, beyond the reference design, in two phases: the profile carries the DHCPv6 prefix-delegation lines only, and the /64 lines follow once the prefix is known (SKILL.md step 7.7). A documentation prefix, a ULA, longer than /64 or shorter than /48, host bits set, or overlapping the other ISP's prefix: re-ask. A /64 with more IPv6 networks than fit: re-ask T18.

**V3. Prefix stability** (V1 = yes)
- Ask: "Does ISP \<n\> keep delegating the same prefix, also after a reboot or a lost lease?"
- Why: the /64s are static lines on 25.4X300-D30.3.
- Default: none.
- Validation: `check_V()`.
- Lands in: `isps.<n>.prefix_stable` (`yes` | `no` | `accept-manual-update`).
- Answers: yes: build. It can change and the customer updates the profiles when it does (`accept-manual-update`): build, beyond the reference design; a new prefix is applied as in SKILL.md step 7.7. Not answered: re-ask. It can change: stop, "V3: ISP \<n\> may change the delegated prefix. On 25.4X300-D30.3 the dynamic form (update-router-advertisement) fails (at most 3 interfaces, no route to the /64s), so the LAN /64s are static lines. Choose: IPv4 only for now, or static /64s from today's prefix and you update the profiles when the ISP changes it (answer accept-manual-update)".

## S. Site services

**S1. DNS servers for the firewalls**
- Ask: "Which DNS servers should the firewalls themselves use? They must answer on the Internet (public resolvers), or say: use the ISP's DNS."
- Why: the firewalls resolve the Mist cloud from their default routing table, out the WAN.
- Default: 8.8.8.8, 1.1.1.1.
- Validation: `check_S1()`.
- Lands in: `services.dns_servers` (`dns_servers` of both profiles; `[]` = the DNS servers the ISP DHCP gives); also the default client DNS of every network (T8).
- Answers: one to three public IPv4 resolvers: build. The ISP's DNS: build, beyond the reference design. A private resolver (clients can still get internal DNS per network, T8), an IPv6 resolver, more than three, or a duplicate: re-ask.

**S2. NTP servers**
- Ask: "Which NTP servers should the firewalls use (host names or public IPv4 addresses)?"
- Why: the firewalls reach them out the WAN, like DNS.
- Default: pool.ntp.org.
- Validation: `check_S2()`.
- Lands in: `services.ntp_servers` (`ntp_servers` of both profiles).
- Answers: one to three host names or public IPv4 addresses: build. A private address, or neither an address nor a host name: re-ask.

## H. Hub and overlay

**H1. Hub**
- Ask: "Should any of the branch networks reach a hub site over a Mist overlay (a hub firewall in this org with its own Hub Profile)?"
- Why: decides the overlay and the routing form: with a hub the LAN sits in routing instance `lan` and the pair joins the hub-and-spoke VPN; without one the LAN uses the default routing instance and no overlay is built.
- Default: no.
- Validation: `check_hub()`.
- Lands in: `hub.present`, `hub.in_mist`.
- Answers: yes (H2 to H7 follow): build (proven with one overlay network). No: build, beyond the reference design (the default routing instance). A hub with no overlay network (the pair joins the VPN only): build, beyond the reference design (SKILL.md step 4.5 confirms that Mist renders routing instance `lan` for it before the hand-off, and stops otherwise). Not yes or no: re-ask. A hub outside Mist (another vendor's concentrator): record `hub.present` true and `hub.in_mist` false; stop, "H1: a hub outside Mist cannot terminate the Mist overlay; build without a hub (H1 = no). Alternative: a tunnel to that concentrator is a separate change to the Hub Profiles once both nodes pass verification; this skill does not build it", then ask whether to go on without a hub. The customer then builds without a hub: record `hub.present` false (`in_mist` then does not matter).

**H2. VPN** (hub = yes)
- Ask: "Which hub-and-spoke VPN should the pair join? This org has: \<names from GET vpns\>."
- Why: Mist derives `vpn_<VPN>`, `<VPN>_overlay` and `<VPN>_advertise` from the name; the profiles name them.
- Default: the only hub-and-spoke VPN.
- How to find: `GET /orgs/{org_id}/vpns?limit=1000` (SKILL.md step 2.5).
- Validation: `check_hub()` (type hub_spoke; letters, digits, `_` and `-`, up to 32).
- Lands in: `hub.vpn_name`, `hub.vpn_type` (the WAN port's `vpn_paths` key, the overlay path preference, the overlay networks' `vpn_access`, the overlay lines).
- Answers: a hub-and-spoke VPN of the org, any name: build (a name other than OrgOverlay: beyond the reference design). A mesh VPN or an invalid name: re-ask. No hub-and-spoke VPN in the org: precondition (build the hub and its VPN first), or answer H1 = no.

**H3. Hub path(s)**
- Ask: "Which path(s) of \<VPN\> should the pair use? I read: \<path keys\>. With more than one, the order you give is the preference order."
- Why: each path key is `<hub profile name>-<hub WAN port name>`; the spoke key is `<path>.<VPN>`; Mist names the IKE gateway `wan_to_<hub MAC>_<hub WAN port name>`.
- Default: the only path.
- How to find: the `paths` keys of the VPN (step 2.5); the hub profile and its WAN port from step 2.6.
- Validation: `check_hub()` (1 to 4 paths; each equals the hub profile name, `-`, the hub WAN port name; no path twice).
- Lands in: `hub.paths[].{path,hub_profile_name,hub_wan_port_name}`.
- Answers: one path with hub WAN port name `wan`: build (proven). Two to four paths (a hub with two WANs, or two hubs), or another hub WAN port name: build, beyond the reference design. Five or more, a path listed twice, or a path that is not `<hub profile name>-<hub WAN port name>`: re-ask.

**H4. Hub device** (read and confirm)
- Ask: "The hub for \<path\> is \<device name\>, MAC \<mac\>, connected. Correct?"
- Why: the dead-peer-detection lines name the Mist-generated IKE gateway, which carries the hub MAC.
- Default: what the read finds.
- How to find: step 2.6: the one inventory record that carries the hub profile.
- Validation: `check_hub()` (12 lowercase hex digits).
- Lands in: `hub.paths[].{hub_device_id,hub_site_id,hub_mac,hub_device_name}`, all four from the step 2.6 read (the plan names the hub profile and the device).
- Answers: one connected hub device per path: build. None, several, or not connected: precondition, "H4: path \<path\>: no single connected hub device carries its Hub Profile; connect the hub first".

**H5. Hub-site prefixes** (at least one overlay network; asked after the last T11, SKILL.md step 1 group 9)
- Ask: "Which hub-site prefixes should the overlay networks reach? The hub render shows these overlay lines: \<redacted lines\>."
- Why: they become the application HUB-SITE-NETS of the allow-to-hub policy.
- Default: none.
- How to find: the hub site's address plan; the `<VPN>_advertise` lines of the hub render (step 2.6) help.
- Validation: `check_hub()` (1 to 20 IPv4 prefixes, not 100.64.0.0/10 or special-use space), `check_overlaps()`.
- Lands in: `hub.site_prefixes` (HUB-SITE-NETS `addresses`; a prefix outside RFC 1918 also adds an except line to the steering filter).
- Answers: private prefixes: build. Public prefixes: build, beyond the reference design. None while a network uses the overlay, a prefix in 100.64.0.0/10 or special-use space, or one that overlaps a planned range: re-ask. An H5 problem that names a T8 or T17 server (asked earlier, settled here): it clears once a prefix holds that server and its network uses the overlay; otherwise ask that T8 or T17 again.

**H6. Hub accepts the overlay networks** (at least one overlay network; asked after H5)
- Ask: "These are the hub's overlay import lines: \<redacted lines\>. Does the hub accept \<overlay network names and subnets, from T1 and T3\>?"
- Why: a hub that drops them leaves no return path; the hub's configuration is the customer's and the agent does not change it.
- How to find: step 2.6 shows the import lines and the policies they name.
- Validation: `check_hub()`.
- Lands in: `hub.import_accepts_overlay_tenants`.
- Answers: yes: build. Unknown: re-ask after showing the lines again. No: precondition, "H6: the hub drops the overlay tenants' routes: change the hub's overlay import, or set those tenants' overlay answer to no".

**H7. Unique overlay subnets** (at least one overlay network; asked after H6)
- Ask: "Is each overlay network's subnet unique across all sites on this overlay?"
- Why: two sites that advertise the same subnet break the return path.
- Validation: `check_hub()`.
- Lands in: `hub.overlay_tenant_subnets_unique`.
- Answers: yes: build. No or not answered: re-ask (give those networks unique subnets).

With a hub, the agent also reads the overlay AS from the hub render (`routing-options autonomous-system`, step 2.6) into `hub.overlay_as`; I2 checks against it.

## M. Management (mgmt-0)

mgmt-0 never carries a default route in the main routing table (it would take the Mist connection off the
WAN), and it stays unplugged until the node passes verification.

**M1. Out-of-band network**
- Ask: "Is there an out-of-band management network for the firewalls' mgmt-0 ports? Give the network; or say it also has a gateway; or say it uses DHCP; or say none."
- Why: mgmt-0 gets its address from the Hub Profile.
- Default: a static network with no gateway.
- Validation: `check_M()` (/16 to /30, host bits zero, not special-use; a malformed network gets the accepted forms of the Ask again), `check_overlaps()`.
- Lands in: `mgmt.mode` (`static` | `static-gw` | `dhcp` | `none`), `mgmt.oob_network` (`oob_ip_config`; with a gateway or DHCP the management VRF is on).
- Answers: a static network, or none (mgmt-0 gets an internal placeholder address and stays unplugged): build. A network with a gateway (M4), or DHCP: build, beyond the reference design (the management VRF). /31 or /32, special-use space, an overlap with a planned range, or another mode: re-ask.

**M2, M3. mgmt-0 addresses** (static, static-gw)
- Ask: "mgmt-0 address of node 1? Of node 2?"
- Validation: `check_M()`.
- Lands in: `nodes.<n>.mgmt_ip` (`oob_ip_config.ip`).
- Answers: two different host addresses of the network: build. Outside the network, or the same twice: re-ask.

**M4. Out-of-band gateway** (static-gw)
- Ask: "Gateway address of the out-of-band network?"
- Validation: `check_M()`.
- Lands in: `mgmt.gateway` (`oob_ip_config.gateway`, `use_mgmt_vrf` true).
- Answers: another host address of the network: build. A node's address or outside the network: re-ask.

## I. Internal addressing (the default is offered; only "is it free?" is asked)

**I1. Internal block**
- Ask: "The firewalls use 10.255.0.0/16 internally (HA link, loopbacks, transit link, HA signal routes); it is never advertised. Is it free at this site\<, and on the overlay (only with a hub)\>? If not, give another private /22 or larger."
- Why: /24 number 0 holds the HA link /30, number 1 the loopbacks, number 2 the transit-link /30, number 3 the SRG1 signal routes.
- Default: 10.255.0.0/16.
- Validation: `check_I1()`, `check_overlaps()`.
- Lands in: `internal.block` (the HA link, loopback, transit-link and signal-route addresses of both profiles and the org network ICD).
- Answers: the default or another RFC 1918 block of /22 or larger: build. /23 or longer, public, or overlapping a planned range: re-ask.

**I2. Transit-link AS numbers**
- Ask: "The transit link runs eBGP with private AS 65001 (node 1) and 65002 (node 2). Are they free to use?\< The overlay of this org uses AS \<overlay AS\> (only with a hub).\>"
- Default: 65001 and 65002.
- Validation: `check_I2()`.
- Lands in: `internal.icd_asn.{1,2}` (`bgp_config.ICD` local and peer AS).
- Answers: two different private AS numbers, 2-byte (64512-65534), also the overlay AS value when there is no hub: build; 4-byte (4200000000-4294967294): build, beyond the reference design. Equal, public, or equal to the overlay AS: re-ask.

## T. Networks (tenants)

Each network is an org network, a security zone, a VLAN unit on the LAN interface, an SRG1 virtual IP (its
gateway) and, by default, a DHCP scope. T order: the untagged network first, then the others in the order
given; virtual IP n is the network in position n.

**T0. Network list**
- Ask: "Which networks (VLANs) does the branch need behind the firewalls? Give each a name; I then ask the details one network at a time."
- Default: none.
- Validation: `check_tenants()`.
- Lands in: `tenants[]`.
- Answers: 4 or 6 networks: build (proven). 1 to 3, 5 or 7 to 32 networks: build, beyond the reference design (every per-network block repeats). None: re-ask. 33 or more: stop, "T0: \<count\> networks: SRG1 carries one virtual IP per network, and without grid-id the virtual MAC is derived from the SRG and the virtual IP index; this design builds at most 32 per SRG. Alternative: merge networks to 32 or fewer".

Per network `<name>`, in this order:

**T1. Name**
- Ask: "Name of network \<k\>?"
- Why: the org network, the zone and the Mist names `<name>_to_wan`.
- Validation: `check_tenant()`: 2 to 24 letters, digits, `_` and `-`, starting with a letter, ending with a letter or digit; unique ignoring case; not a name the design or Mist uses (ICD, HA, wan, lan, XNODE, Internet and the like, `vpn_...`, the VPN name).
- Lands in: `tenants[k].name` (org network name, zone, profile keys).
- Answers: a valid unique name: build. A duplicate (any case), a reserved name, longer than 24 characters, starting with a digit, or a Junos secret keyword or a name ending in `-<keyword>` (secret, password, authentication-key, encrypted-password, plain-text-password-value, authentication-password, privacy-password: the step 4.2 read-back compare would mask its zone lines): re-ask. A name that exists in the org (SKILL.md step 2.7, decided at step 3.1 before the plan is shown): equal to the planned network: build, reused read-only (`existing.reuse`); with other settings: re-ask (another name), or answer so that the network equals the existing one.

**T2. VLAN ID**
- Ask: "VLAN ID of \<name\> on the LAN switch?"
- Validation: 1 to 4094, unique.
- Lands in: `tenants[k].vlan_id` (network `vlan_id`, the unit and `vlan-id` on the LAN interface).
- Answers: 1 to 4094, unique: build. A duplicate, 0 or 4095: re-ask.

**T3. Subnet**
- Ask: "IPv4 subnet of \<name\> (for example 10.20.0.0/24)?"
- Why: every network needs its gateway and two node addresses, so /29 or larger.
- Validation: /8 to /29, host bits zero, not 100.64.0.0/10 (Mist overlay addressing) or special-use space, no overlap.
- Lands in: `tenants[k].subnet` (network `subnet`, node addresses, the steering filter).
- Answers: a private /8 to /29: build. A public routable subnet: build, beyond the reference design (an except line keeps traffic to it off the peer-ISP steering; with Internet access T21 asks how it leaves). /30 or longer, 100.64.0.0/10, special-use or documentation space, host bits set, or an overlap with another network, the WAN ranges, the out-of-band network or the internal block (reported under T3): re-ask. Not answered yet (no `subnet` recorded): a re-ask, never the stop below. No IPv4 subnet (record `subnet` `"none"`; with IPv6 recorded and no subnet the same): stop, "T3: tenant \<k\> (\<name\>): \<IPv6 only | no IPv4 subnet\>; each tenant needs an IPv4 subnet (the redundant gateway is an IPv4 virtual IP); give it one and IPv6 on top".

**T4. Gateway**
- Ask: "Gateway address the clients of \<name\> use? It becomes the shared virtual IP that moves with the active firewall."
- Default: the first host of the subnet.
- Validation: a host address of the subnet.
- Lands in: `tenants[k].gateway` (network `gateway`, SRG1 virtual IP, DHCP router).
- Answers: any host address: build. Left out: the first host. Outside the subnet, or the network address: re-ask.

**T13. Node addresses**
- Ask: "Each firewall also needs its own address on \<name\>: I will use \<n1\> (node 1) and \<n2\> (node 2). OK, or give two others?"
- Default: the first two hosts that are not the gateway.
- Validation: two distinct hosts of the subnet, not the gateway.
- Lands in: `tenants[k].node_ips` (`null` = the default, else `{"1": "<node 1 address>", "2": "<node 2 address>"}`; `ip_configs` of each profile, the Active Leasequery peer).
- Answers: the default or two other hosts: build. The gateway, outside the subnet, the same twice, or another shape than the object above: re-ask. Ask T13 (and T7) only after T3 and T4 of that network, with the addresses filled in.

**T14. Internet access**
- Ask: "Does \<name\> have Internet access?"
- Default: yes.
- Validation: yes or no.
- Lands in: `tenants[k].internet` (network `internet_access`, the Internet, To-ICD and NAT lists, the steering).
- Answers: yes: build. No: build, beyond the reference design (T5 is not asked). No while the network has IPv6 (T10) or a public client DNS server (T8): re-ask that question. Not yes or no: re-ask. Internet through the hub (backhaul): record `internet` as `via-hub`; stop, "T14: tenant \<k\> (\<name\>): Internet through the hub needs a per-tenant routing instance that these profiles do not build; choose local Internet or no Internet plus hub prefixes".

**T21. Public subnet NAT** (asked only when T3 is a public subnet and T14 = yes)
- Ask: "\<subnet\> is a public subnet. Should its hosts reach the Internet with source NAT to the firewall's WAN address, as the private networks do (default), or be routed without NAT at their own addresses?"
- Why: in this design every network leaves with source NAT to the WAN address of the node whose ISP it uses; a routed public subnet would need its ISP to route it to one node, and the other ISP drops a source it does not own.
- Default: `nat`.
- Validation: `check_tenant()`.
- Lands in: `tenants[k].public_nat` (`nat` | `routed`; plan only: `plan.md` states the source NAT).
- Answers: nat: build. Routed without NAT: stop, "T21: tenant \<k\> (\<name\>): \<subnet\>; a public subnet routed without NAT needs its ISP to route that subnet to one node, and the other ISP drops a source it does not own, so the per-network ISP backup cannot carry it; this design source-NATs every Internet network to the WAN address of the node it leaves by. Alternative: source NAT to the WAN address (answer nat)". Another value: re-ask.

**T5. Preferred ISP** (T14 = yes; not asked for T14 = no or Internet through the hub)
- Ask: "Which ISP should \<name\> use for the Internet? The other ISP is its IPv4 backup: the network moves to it when the node of its preferred ISP loses its WAN link or its DHCP lease. An upstream outage that leaves the link and the lease up does not move it. IPv6 has no backup (V)."
- Default: ISP 1.
- Validation: 1 or 2.
- Lands in: `tenants[k].preferred_isp` (the steering filter on the node of the other ISP).
- Answers: 1 or 2, a mix of both: build (proven). Every network on one ISP: build, beyond the reference design. Left out: ISP 1. 3, "either" or load sharing: re-ask (each network has one home ISP; the other is its backup). `plan.md` states when the backup takes over and the source NAT.

**T6. DHCP**
- Ask: "Who gives addresses on \<name\>: the firewalls (DHCP server), a DHCP server elsewhere (relay), or nobody (static addresses)?"
- Default: the firewalls.
- Validation: server, relay or none.
- Lands in: `tenants[k].dhcp.mode` (`dhcpd_config.<name>`; with at least one server network, the MNHA DHCP lines and the binding sync).
- Answers: server on any network: build. Relay or none, on some or all networks: build, beyond the reference design (with relay both nodes are on the VLAN and both relay each client request, each with its own address on the network as the relay address; `plan.md` says so). Another value: re-ask.

**T7. DHCP range** (server)
- Ask: "DHCP range for \<name\>? I suggest \<start\>-\<end\>."
- Default: network +10 to network +200 (to the last host in a smaller subnet), when that range fits and leaves out the gateway and both node addresses; otherwise no suggestion.
- Validation: inside the subnet, start not after end, the gateway and node addresses left out.
- Lands in: `tenants[k].dhcp.start`, `.end` (`ip_start`, `ip_end`).
- Answers: the suggestion or another range inside: build. A range with the gateway or a node address, start after end, or outside the subnet: re-ask. No suggestion fits and no range given: re-ask.

**T8. Client DNS** (server)
- Ask: "Which DNS servers should \<name\>'s clients get?"
- Default: the firewalls' DNS (S1); no default for a network without Internet access (T14 = no), or with the ISP's DNS at S1.
- Validation: 1 to 3 IPv4 unicast addresses; a private server must be reachable from this network (its own subnet, a network it may reach (T15), or a hub prefix when it uses the overlay); a public server needs Internet access. With a hub, a private server outside the planned networks shows as an H5 problem until H5 and T11 are answered (it can be a hub-site server).
- Lands in: `tenants[k].dhcp.dns_servers`.
- Answers: public resolvers; a server in its own subnet (also a public one); a hub-site server for an overlay network; a server in a network it may reach: build. A private server it cannot reach, a public one without Internet access, more than three, or a multicast address: re-ask.

**T9. Lease time** (server)
- Ask: "DHCP lease time for \<name\>?"
- Default: 86400 s (one day).
- Validation: 600 s to 2592000 s (30 days).
- Lands in: `tenants[k].dhcp.lease_time`.
- Answers: inside the range: build. Shorter than 10 minutes or longer than 30 days: re-ask.

**T16. DHCP extras** (server)
- Ask: "Any extras for \<name\>: a DNS domain name for clients, reserved addresses (device MAC and IP), or DHCP options (code, type, value)?"
- Default: none.
- Validation: domain names; option codes 2 to 254 except 3, 6, 12, 15, 50 to 55, 61 and 82, with a type (boolean, hex, int16, int32, ip, string, uint16, uint32) and a value that fits it (`option_value_problem()`: ip one IPv4 address; the integer types in range; boolean true or false; hex an even number of hex digits; string up to 255 printable characters without quotes, backslashes, `<` or `>`); reservations with a 12-hex-digit MAC on a free host address, each MAC and address once, a name of one host label (letters, digits and `-`, up to 63 characters).
- Lands in: `tenants[k].dhcp.dns_suffix` (a list of domains), `.options` (`{"<code>": {"type": "<type>", "value": "<value>"}}`), `.fixed_bindings` (`{"<12-hex MAC>": {"ip": "<address>", "name": "<name>"}}`).
- Answers: none: build. Valid domains, options and reservations: build, beyond the reference design. A reserved option code (DNS servers and domain have their own questions), a missing type or value, a value that does not fit its type, a reservation on the gateway or a node address, a bad MAC, a reservation name that is not one host label, a bad domain, or another shape than the ones above: re-ask.

**T17. Relay servers** (relay)
- Ask: "Address of the DHCP server (or servers) to relay to?"
- Validation: 1 to 4 IPv4 unicast addresses outside the network's own subnet, reachable as in T8 (a hub-site server is settled at H5, as in T8).
- Lands in: `tenants[k].dhcp.relay_servers` (`dhcpd_config.<name>` type relay).
- Answers: reachable servers, a hub-site server for an overlay network included: build. None, one inside its own subnet, or a private server it cannot reach: re-ask.

**T10. IPv6** (asked only when the network has Internet access (T14 = yes) and an ISP delegates a prefix; otherwise record `none`)
- Ask: "Should \<name\> get IPv6 from ISP 1, from ISP 2, or none? IPv6 comes from one node's ISP and has no failover."
- Default: from its preferred ISP when that ISP delegates and the network has Internet access, else none.
- Validation: the chosen ISP delegates (V1); the network has Internet access.
- Lands in: `tenants[k].ipv6` (`none` | `isp1` | `isp2`: the /64 address, router advertisement and IPv6 Internet policy on the serving node).
- Answers: ISP 1 on a network that prefers ISP 1: build (proven). ISP 2, or ISP 1 on a network that prefers ISP 2 (IPv4 then leaves by the preferred ISP, IPv6 by the other): build, beyond the reference design; IPv6 has no failover (`plan.md` says so): while the serving node or its ISP is down, the network has no IPv6. From both: stop, "T10: tenant \<k\> (\<name\>): IPv6 from both ISPs is not supported by this design: it serves IPv6 per node, so each node would advertise its own ISP's /64 on the same VLAN, and the design has no source-based IPv6 routing that sends a packet to the ISP that owns its source address; a host that uses the other node as its IPv6 router would lose IPv6 (that ISP drops a source it does not own). Alternative: IPv6 from one ISP for this network (isp1 or isp2)". From an ISP without delegation, a network without Internet access, or another value: re-ask.

**T18. /64 number** (asked only when the default does not fit, or the customer asks)
- Ask: "Which /64 of the ISP \<n\> prefix should \<name\> use (0 to \<max\>)?"
- Default: the network's position in T order.
- Validation: fits the delegated length; unique per prefix.
- Lands in: `tenants[k].ipv6_index` (`null` = the default).
- Answers: a number that fits and is free: build, beyond the reference design (the default number builds as proven). Beyond the prefix (for example 16 in a /60) or used twice: re-ask.

**T11. Overlay** (asked only with a hub)
- Ask: "Should \<name\> reach the hub site over the overlay?"
- Default: no.
- Validation: yes or no; a hub is present.
- Why: the hub prefers the SRG1-active node; SRG1 monitors the LAN interface and does not move on a WAN loss, so while that node's ISP is down the overlay networks do not reach the hub, until the ISP is back or SRG1 moves to the other node (`plan.md` says so).
- Lands in: `tenants[k].overlay` (network `vpn_access`, the allow-to-hub policy, the overlay export; the local-preference policy is named after the first overlay network: `<name>-LP`).
- Answers: yes on one network: build (proven). Yes on two or more, or on none (attach only, H1): build, beyond the reference design. Yes with no hub, or not yes or no: re-ask.

**T15. Reach other networks**
- Ask: "Should \<name\> reach any of the other networks? By default each network reaches only itself, the Internet and, if chosen, the hub."
- Default: none.
- Validation: names of other networks.
- Lands in: `tenants[k].reach` (path preference `LAN-<B>` and service policy `To-<B>` per network B).
- Answers: none: build. Other networks: build, beyond the reference design. Itself, or a name that is not one of the networks: re-ask.

Once, after the list:

**T12. Untagged network**
- Ask: "Which network is untagged (native VLAN) on the LAN link, if any?"
- Default: the first network listed.
- Validation: at most one.
- Lands in: `tenants[k].untagged` (the LAN port's `port_network`, unit 0, position 1 in T order).
- Answers: any one network: build. None (every network tagged; no `port_network`, no `native-vlan-id`): build, beyond the reference design. Two or more: re-ask.

**T19. SSH to the firewalls**
- Ask: "From which networks may admins open SSH to the firewalls themselves? Default: \<first network in T order\> only. (mgmt-0 always accepts SSH.)"
- Validation: yes or no per network.
- Lands in: `tenants[k].ssh` (one host-inbound ssh line per network).
- Answers: the default: build. Several networks, or none (SSH on mgmt-0 only): build, beyond the reference design. Not yes or no: re-ask.

**T20. DHCP binding sync network** (asked only if the firewalls serve DHCP on a network)
- Ask: "The two firewalls keep their DHCP leases in sync over one network where they serve DHCP, which both LAN links carry. Default: \<first network in T order where the firewalls serve DHCP\>. OK?"
- Validation: one of the networks where the firewalls serve DHCP (T6 server): the sync runs between the two DHCP servers, and Mist opens the DHCP host-inbound service only on those networks' zones.
- Lands in: `pair.alq_tenant` (`null` = the default; the Active Leasequery peer is the other node's address on it).
- Answers: the default: build. Another network where the firewalls serve DHCP: build, beyond the reference design. A network with DHCP relay or none, or a name that is not one of the networks: re-ask.

## X. Pair behavior (defaults stated, asked once)

**X1. Preemption**
- Ask: "After a failover, should the active role return to node 1 automatically once node 1 is healthy (preemption)? Default no: it stays where it is until you fail it back by hand. With preemption on, MNHA refuses a manual SRG1 failover (moving the role by hand needs preemption off)."
- Default: no.
- Validation: `check_X()`.
- Lands in: `pair.preemption` (an SRG1 preemption line on both nodes).
- Answers: no: build (proven). Yes: build, beyond the reference design (SKILL.md step 7.2 reads the time SRG1 takes to return). Not yes or no: re-ask.

**X2. HA link encryption**
- Ask: "Encrypt the HA link between the firewalls? It is a direct cable; default no."
- Default: no.
- Validation: `check_X()`; yes needs K3.
- Lands in: `pair.icl_encryption` (IKE and IPsec on the HA link, vpn-profile on the peer).
- Answers: no: build (proven). Yes with a key file (K3): build, beyond the reference design (the HA link encryption lines and the two ha-link-encryption show commands of SKILL.md step 7.4). Yes without a key file: re-ask K3. Not yes or no: re-ask.

## K. Secrets (paths only)

The customer saves each secret in a local file (mode 600) and gives the path; both nodes may point to the
same file. The agent reads a value only inside the one script that needs it (SKILL.md rule 2), checks it
there and prints only "set, N characters" or the check's message (which never holds the value).

**K1. Root authentication** (per node)
- Ask: "For each firewall, the path of a local file (chmod 600) that holds the encrypted root password string, or a file with an SSH public key for root (or both). Both firewalls may use the same file."
- Why: a factory-default SRX400 has no root password, and Junos refuses a commit without root authentication.
- How to find: on any Junos device with the wanted password, `show configuration system root-authentication | display set | no-more`; the value is the quoted string after `encrypted-password`. Save only that string.
- Validation: `read_secret(path, 'root')` for a hash file (it also refuses a file that group or others can read: re-ask after `chmod 600`), then `check_K1(value)`; for a key file `read_secret(path, 'license')` (the one-line rule), then `check_K1(value, 'ssh-key')`. `validate()` checks that each node has at least one of the two files.
- Lands in: `nodes.<n>.root_hash_file`, `nodes.<n>.root_ssh_key_file` (`<ROOT-PASSWORD-HASH>`, `<ROOT-SSH-KEY-TYPE>` and `<ROOT-SSH-KEY>` in the profile until the write).
- Answers: a hash file (`$6$`, `$5$` or `$1$`), a key file (one `ssh-ed25519`, `ssh-rsa` or `ecdsa-sha2-nistp256`/`384`/`521` line; an ECDSA key goes in as `root-authentication ssh-ecdsa`; the comment after the key data is not sent), or both, the same or different per node: build (a hash file on both: proven; a key file: beyond the reference design). No file, a file that others can read, a plain password, or a malformed value: re-ask.

**K2. License key** (per node)
- Ask: "Does each firewall have its own license key? For each yes, the path of a file that holds only that key."
- Why: the push installs it. A key is bound to one chassis serial: each node gets only its own key, and a node without one gets no license line.
- How to find: the license certificate for that serial.
- Validation: `read_secret(path, 'license')`, then `check_K2(value)` (one line, no quotes, `<` or `>`).
- Lands in: `nodes.<n>.license_key_file` (`null` for none; `<LICENSE-KEY>` right after that node's root line).
- Answers: none or node 2: build. Node 1 or both: build, beyond the reference design. A file with several lines or quotes, or one that others can read: re-ask.

**K3. HA link key** (X2 = yes)
- Ask: "Path of a file that holds the HA link pre-shared key (8 to 255 characters, no spaces, quotes, backslashes, `<` or `>`). The key sits in the Additional CLI of both Hub Profiles, where every account that can read the org's Hub Profiles can read it, as the root hash and the license key."
- Validation: `read_secret(path, 'license')`, then `check_K3(value)`.
- Lands in: `pair.icl_psk_file` (`<ICL-PSK>` in the HA link encryption lines of both nodes).
- Answers: 8 to 255 printable characters: build. Shorter, longer, with spaces, quotes, backslashes, `<` or `>`, or a file that others can read: re-ask.

## N. Names and method

**N1. Profile names**
- Ask: "Keep the profile names SZTP-SRX400-NODE1 and SZTP-SRX400-NODE2?"
- Why: a name that already exists in the org is reused only when that profile equals the plan (SKILL.md rule 5); the Mist UI refuses names over 32 characters or with characters other than letters, digits, `_` and `-`. On the UI path the customer types this exact name in the Name field of Import Profile.
- Default: `SZTP-SRX400-NODE1`, `SZTP-SRX400-NODE2`.
- Validation: `check_N1()`; the clash list of SKILL.md step 2.6.
- Lands in: `nodes.<n>.profile_name`; you fill `nodes.<n>.profile_id` after the create.
- Answers: the defaults or other valid, different names: build. A dot or other character, more than 32 characters, or the same name twice: re-ask. A name that exists in the org: reuse when it equals the plan and its secrets match this node's files (decided at step 3.1, before the plan is shown; recorded in `existing.reuse`); otherwise re-ask for another name.

**N2. Build method**
- Ask: "Should I create the two profiles through the API, or will you import them at Organization > WAN > Hub Profiles > Import Profile?"
- Default: API.
- Lands in: `profiles_method` (`api` | `ui-import`).
- Answers: API: build (proven). UI import (SKILL.md step 4, Mist UI path): build, beyond the reference design. Anything else: re-ask.

**N3. Repository path** (asked only if `scripts/build_plan.py`, `templates/` or `../../docs/SRX400-MNHA-Zero-Touch-Mist.pdf` is not found from `SKILL.md`, for example when the skill folder was copied out of the clone)
- Ask: "Path of the cloned repository?"
- Lands in: `repo_path`.
- Answers: a path that holds the skill files, the paper and the reference files: build; the agent reads the paper and the reference files from there. A wrong path: re-ask.

## R. Site readiness (a yes for each)

A "no" is a precondition: the build waits until it is a yes, "R: site_readiness.\<key\> is no: the build
waits until it is yes". "Unknown": say how to check, ask again. Lands in `site_readiness.<key>`.

- **R1** `isp_dhcp`: "Each ISP answers DHCP on its firewall's WAN port with an address, a default route and DNS, and sends no ZTP option (no option 143)." Zero touch uses that default route and DNS to reach redirect.juniper.net and Mist.
- **R2** `isp<n>_dhcpv6` (each delegating ISP): "ISP \<n\> answers DHCPv6 on node \<n\>'s WAN port with an address (IA_NA) and the delegated prefix (IA_PD)."
- **R3** `modem_accepts_new_mac`: "The ISP modem or router accepts a new device MAC (no lock to the previous router's MAC), or it has been power-cycled or released." A factory-default box cannot clone a MAC before its first push.
- **R4** `lan_switch`: "The LAN switch has \<a LAG with LACP active and no force-up, or a plain port\> for each firewall, on node 1's \<LAN ports\> and node 2's \<LAN ports\>, with \<untagged network\> untagged and \<tagged VLANs\> tagged, and every VLAN on both firewalls' links." Filled from the P3, T2 and T12 answers. The virtual IPs and the binding sync need every VLAN on both nodes.
- **R5** `cabling`: "Cabled as you gave the ports, before power-on: on each firewall the WAN port \<P2\> to its own ISP, the LAN ports \<P3\> to the switch, the HA link \<P4\> to the other firewall's HA link port, the transit link \<P5\> to the other firewall's transit-link port." Filled from the P answers; step 5 checks the cabling again against `plan/topology.txt`. MNHA then forms with no site visit.
- **R6** `mgmt0_unplugged`: "mgmt-0 is unplugged on both firewalls until they pass verification." Zero touch tries mgmt-0 first, and factory mgmt-0 has a static address and a DHCP server.
- **R7** `device_names_set`: "Both devices carry their names in Mist."
- **R8** power-on (no yes needed): "Who powers on both firewalls (named by serial) and tells me the time?" You record it in UTC as T0 (`watch.t0_power_on_utc`, `watch.t0_epoch`); `watch.py` starts just before power-on (`watch.watch_start_epoch`). Nobody types on either box.
- **R9** `isp<n>_wan_range_clear` (each ISP whose range W3 left unknown): "ISP \<n\>'s address range is unknown, so I cannot check it. Before the build, check the address a laptop gets on ISP \<n\>'s hand-off (or the ISP router's LAN settings): is it outside 192.168.2.0/24 (asked only when ge-0/0/3 has a role on node \<n\>: the factory ge-0/0/3 subnet is up there during zero touch) and outside every planned range (\<networks, internal block, out-of-band network, hub prefixes\>)?" A yes builds (`plan.md` says the customer checked it). No: give the range at W3, so the checks run on it (the W3 stop or re-ask follows). Giving the range at W3 instead of a yes also settles R9.

## E1. Plan confirmation

- Ask (SKILL.md step 3.2): show `topology.txt` and `plan.md` from the plan folder: "Build exactly this?"
- Answers: yes: the writes begin, each one shown and confirmed on its own. A change ("GUEST on ISP 1"): back to that question, validate the answers that depend on it, build the plan again and show it again. No, or not sure, with no change named: ask which part to change, naming the question IDs of each plan section; nothing is written. Still no: stop; the plan folder stays and the run resumes at SKILL.md step 3.2.

## Requests at any point (not asked)

The customer may ask for these at any time; at the end of group 10 ask once whether they expect anything else in
the first push (SKILL.md step 1). Record them so the stop is on file, give the stop message and go on only when
the request is withdrawn.

| ID | Request | Record | Stop message |
|---|---|---|---|
| S3 | IDP, AppID, SecIntel, GeoIP or URL filtering in the first push | `security_services` (`idp`, `appid`, `secintel`, `geoip`, `url-filtering`) | "S3: \<list\> requested in the first push; not in the zero-touch push: add them to the Hub Profiles after both nodes pass verification (signature packages and ATP enrollment do not exist on a factory-default box at the first push)" |
| X | Another HA form: MNHA routing or switching mode, SRG0 active/active, chassis cluster, one node, three nodes | `pair.ha_mode` (`mnha-routing`, `mnha-switching`, `srg0-active-active`, `chassis-cluster`, `single-node`, `three-nodes`; the design is `mnha-hybrid`) | "X: HA form \<form\> requested; this skill builds one two-node MNHA hybrid pair (SRG1); other HA forms are different designs (MNHA routing or switching mode, SRG0 active/active, a second SRG, chassis cluster, one node, three nodes). Alternative: this pair as built: SRG1 active on node 1 and backup on node 2, both ISPs in use through the per-network ISP steering" |
| X | A second or third services-redundancy group | `pair.srg_count` | "X: \<count\> services-redundancy groups requested; this skill builds one two-node MNHA hybrid pair (SRG1); ..." (as above) |
| X | An explicit activeness probe | `pair.activeness_probe` `explicit` (the design is `default`) | "X: activeness probe explicit requested; in hybrid mode the default probe toward VIP 1 is the form that survived both an ICL cut and active-node death; an explicit probe is not built. Alternative: keep the default probe (nothing to configure)" |

## Derived values (never asked)

| Value | From |
|---|---|
| T order, virtual IP n | the untagged network first, then the others in answer order |
| DHCP binding sync network (T20 default) | the first network in T order where the firewalls serve DHCP |
| VLAN unit | 0 for the untagged network, else its VLAN ID, on `ae0` (LACP) or the plain LAN port |
| HA link, loopbacks, transit link, signal routes | the internal block (I1): node 1 .1, node 2 .2 |
| MNHA ids | local-id n, peer-id the other node; activeness-priority 200 (node 1, preferred active), 100 (node 2) |
| Transit-link BGP neighbor | the peer's transit-link address and AS |
| Steering on node n | the Internet networks whose preferred ISP is the other node's ISP |
| IPv6 /64 | /64 number (T18, default the T order position) of the delegated prefix; node 1 `::2`, node 2 `::3` |
| Overlay names | spoke key `<path>.<VPN>`; IKE gateway `wan_to_<hub MAC>_<hub WAN port name>`; `vpn_<VPN>`, `<VPN>_overlay`, `<VPN>_advertise`; `<first overlay network>-LP` |
| Org objects, in create order | the networks in T order, then ICD, then HUB-SITE-NETS (with a hub and at least one overlay network) |
| Reused objects | `existing.reuse`: the planned networks, application and profiles that already exist equal to the plan (SKILL.md step 3.1); `plan.md` marks them `reuse (no write)` |
| mgmt-0 placeholder (M1 none) | the upper /25 of the internal block's /24 number 1, hosts 1 and 2 |
| Routing form | with a hub: routing instance `lan`; without: the default routing instance |
