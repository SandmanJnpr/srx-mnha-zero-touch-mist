---
name: srx400-zero-touch-mist
description: Drop-ship an SRX400 Multinode High Availability (MNHA) pair to a branch and let Juniper Mist onboard both nodes with zero touch (Secure ZTP), with nothing typed on either box. Use it whenever someone wants to ship SRX400 firewalls or an SRX400 MNHA pair to a site, mentions zero touch, ZTP, SZTP or drop ship with Mist, wants Mist org networks and Hub Profiles built for an SRX400 pair, or wants to watch or verify a zero-touch onboarding. It asks the customer about their proposed topology and configuration (ports, ISPs, networks with VLAN, subnet, gateway, DHCP and preferred ISP, hub and overlay, IPv6, DNS, NTP, management, internal addressing), derives the rest, shows the topology and plan for a yes, builds the Mist org objects and one Hub Profile per SRX400 node from the answers, assigns them to the serials before power-on, watches the zero-touch call-home and verifies. It reads the API token from a local file, checks the org read-only, asks for a yes before every write and never overwrites.
---

# SRX400 MNHA zero-touch drop ship with Juniper Mist

Take the customer from "two new SRX400s and a Mist org" to two onboarded MNHA nodes built from the
customer's own proposed topology, through the Mist REST API with Python 3.9 or later (standard library
only). The design is the paper `../../docs/SRX400-MNHA-Zero-Touch-Mist.pdf`. The customer answers the
questions of `references/intake.md`; `scripts/build_plan.py` validates the answers, derives every other
value and writes the org objects and one Hub Profile per node from the reference lines in
`templates/hub-profile.template.json`. Build what the answers produce; do not redesign beyond the answers
(no line, key or object that `build_plan.py` does not write).

Proven on hardware (an SRX400 pair, Junos OS Evolved 25.4X300-D30.3):
- The reference design of the paper: both nodes went from factory default to their Hub Profiles with nothing typed
  and passed the paper's verification. With the paper's answers `build_plan.py` writes exactly those objects
  (`org-objects.json`, `../../mist/`; `tests/` checks it).
- A second run of this skill end to end, from the intake questions to step 7, with four networks and the HA link
  and transit link ports swapped (HA link ge-0/0/5, transit link ge-0/0/4): both nodes onboarded with nothing typed,
  MNHA formed with cold sync COMPLETE, and every network reached its gateway and the Internet by its preferred ISP.

Every other answer builds from the same reference lines (`tests/` checks the generator). `build_plan.py` lists each
structure beyond the reference design in `plan.md` under "Beyond the reference design" (for example another network
count, no hub, DHCP relay, IPv6 from ISP 2, other ports, preemption, HA link encryption, a release after
25.4X300-D30.3); step 3.2 names them to the customer before the yes, and step 7 verifies the pair. Never present
them as run on hardware.

| File | Use |
|---|---|
| `references/intake.md` | Every question: wording, why, default, how to find, validation, where it lands, how each answer is handled (build, re-ask, stop with its message, precondition) |
| `references/mist-api.md` | Every API call, the client functions, read-back rules, traps |
| `scripts/mist_api.py` | The client: `mist()`, `page_total()`, `list_all()`, `find_by_name()`, `redact()`, `profile_summary()`, `event_rows()`, `log_rows()`, `safe_error()`, `write()`, `write_private()`, `read_secret()`, `fill()`, `secret_check()`, `secret_check_pass()`, `self_privileges()`; `python3 mist_api.py <path>` prints only the fields this skill reads (`cli_view()`) |
| `scripts/build_plan.py` | `python3 <skill folder>/scripts/build_plan.py --answers answers.json --out plan` (validate, then write the plan folder: `org-objects.json`, `node1-profile.json`, `node2-profile.json`, `topology.txt`, `topology.md`, `plan.md`); `--check` validates only; `--update <plan folder already built>` also writes `update.md` (steps 4.5, 7.7); exit 0 valid, 1 re-ask or precondition, 2 stop. As a module: `validate()`, `build()`, `write_plan()`, `hardware_status()` (the plan's structures beyond the reference design), `fill_secrets()`, `secret_placeholders()`, `named_objects()`, `line_count_formula()`, `PLACEHOLDER_RX`, and the intake checks `check_A2()`, `check_A3_privileges()`, `check_B_inventory()`, `check_device_record()`, `check_site_settings()`, `check_overlaps()`, `check_K1()`, `check_K2()`, `check_K3()` |
| `scripts/watch.py` | The step 6 monitor: copy it into the working folder, start it just before power-on; read-only, writes `watch.log` |
| `templates/hub-profile.template.json` | The reference lines and keys `build_plan.py` fills; never edit it |
| `answers.example.json` | Shape of `answers.json` (schema v2); never copied (step 1) |
| `org-objects.json`, `../../mist/srx400-node1-zero-touch.json`, `../../mist/srx400-node2-zero-touch.json` | The reference design output: what `build_plan.py` writes for the paper's values, placeholders kept (`tests/` checks it). For reading only, never a write body: the bodies come from the plan folder |

If `scripts/build_plan.py`, `templates/` or `../../docs/SRX400-MNHA-Zero-Touch-Mist.pdf` is missing (for example the skill folder was copied out of the clone), ask for the path of the cloned repository (intake N3) and read the paper and the reference files from there.

## Ground rules (every step)

1. **Token.** Read the Mist API token inside the request code from the file the customer names (default `~/mist-api-token`, mode 600). Never print, log, echo or copy it; never ask for it in chat; never put it on a command line or in a shell variable. If the customer pastes a token into the chat, tell them to delete it in Mist and create a new one.
2. **Secrets.** Root password hashes, root SSH keys, license keys and the HA link key stay in local files (mode 600) that the customer names. Read them with `read_secret()` only inside the one script run that needs them (the intake K1-K3 checks, which print only the check's message and "set, N characters"; step 4.2; a rule 5 reuse check; a correction PUT, the IPv6 update of step 7.7 included; the UI path files), never in any other command. Never show them (say "set, N characters"). Everything a command prints enters your context: print only what `python3 mist_api.py <path>` prints, `profile_summary()` of device profiles, `event_rows()` of events, `log_rows()` of audit logs, `write()` summaries, `secret_check()` results, `build_plan.py` output and the booleans and counts of your checks; save only those. Never print or save a whole device profile other than this skill's own plan folder and redacted read-backs: other profiles in the org hold their own secrets.
3. **Reads are free, writes are gated.** GET calls need no approval. Before every POST or PUT show method, path, object name and a one-line summary, then wait for an explicit "yes". One yes covers one call.
4. **Snapshot first.** Before the first write, save: the name and `modified_time` of every network, service and VPN in the org; `profile_summary()` of every gateway device profile; with a hub, the whole VPN object the pair joins (it holds no secrets); per node, from `GET /sites/{site_id}/devices/{device_id}`, `deviceprofile_id`, `disable_auto_config` and `mist_configured`; and its `status` and `config_version` (`GET /sites/{site_id}/stats/devices/{device_id}`; record the HTTP status if it is not 200).
5. **Never overwrite.** Name clashes are case-insensitive. An existing object with the same name that equals the planned body field for field (`references/mist-api.md` section 2) is reused read-only (say so); a Hub Profile only if, in addition, its raw GET equals the planned body filled with this node's secret files (step 4.2). Any other clash: a customer network name goes back to T1 (another name, or answers equal to the existing network); a profile name goes back to N1; ICD or HUB-SITE-NETS (design names the profiles use): stop and ask. Never modify or delete an object you did not create unless the customer says so.
6. **One change at a time.** Read back after each write and compare. Any difference: stop and report.
7. **No device-record writes.** Never PUT `/sites/{site_id}/devices/{device_id}`: all configuration lives in the two Hub Profiles, and a device-record write makes Mist re-push a connected gateway. Assign only with the assign call.
8. **Never send** `additional_config_cmds: []` or `null` values. Additional CLI lines start with `set ` or `delete ` only.
9. **Names.** Profile names, network names and the application name match `^[A-Za-z0-9][A-Za-z0-9_-]*[A-Za-z0-9]$`, at most 32 characters (network names: 2 to 24, starting with a letter, intake T1). The API accepts names the Mist UI then refuses; `build_plan.py` checks them. Path keys such as `<path>.<VPN>` are Mist's own and keep their dot.
10. **Do not save the profiles in the Mist UI editor.** A save adds default keys and the profile no longer equals the plan.
11. **Working folder.** Keep `answers.json`, `mist_api.py`, the plan folder `plan/`, snapshots, redacted read-backs, `watch.py` (copied from `scripts/`), `watch.log` and `watch.pid` in one folder outside the repository clone (mode 700), e.g. `~/srx400-zero-touch/<site>/` (the clone's `.gitignore` lists these names). Importing `mist_api` sets the process umask to 077; write any file that holds a secret with `write_private()` (mode 600 from the start). Secret files stay where the customer saved them, for example in the working folder's `secrets/` subfolder (mode 600 files); never copy them. The UI path's filled files go in `secrets/` too. Run every script from that folder with plain `python3 <script>`; with `python3 -I`, `sys.path.insert(0, '<working folder>')` before `import mist_api`. A script that also uses `build_plan` adds `sys.path.append('<skill folder>/scripts')` after that (so `import mist_api` stays the working folder copy), then `import build_plan as B`.
12. **List reads.** Every list read (inventory, networks, services, vpns, deviceprofiles) goes through `list_all()` of `mist_api.py`: it reads `limit=1000` (Mist sends `X-Page-Total` only with `limit`), then `&page=2`, `&page=3`, ... with the same limit until the unique ids read equal `X-Page-Total`. Show the row count and the total. `list_all()` returns `complete` false (no `X-Page-Total`, a page that does not answer 200, or a page with no new row before the total): the list is incomplete; stop and tell the customer. The one exception is the MSP org list of step 2.2: only a list to pick from (the proof is `GET /orgs/{org_id}`), so an incomplete one is shown as read.
13. **Waits happen inside your turn.** When a step says to wait (the watch of step 6, a cold sync, a restart), wait in your own run: one blocking command per wait (for example `python3 watch.py --once` in a loop with `sleep`, or `sleep` in short steps), each command under about 9 minutes, repeated until the wait is over. End your turn only to ask the customer something; if you must end it while waiting, say exactly what the customer types to resume (for example "continue").

## Step 1: Intake (the customer's proposed topology)

Ask the questions of `references/intake.md` one group at a time, in this order, with the step 2 reads
where shown. Confirm every value you can from those reads instead of asking the customer to recite IDs.
Start `answers.json` as `{"schema": "srx400-zero-touch-mist.answers.v2"}` and record in it only the answers
given and the values read, shaped like `answers.example.json`; never copy that file (`validate()` refuses its
example text `<...>`). For a secret record only its file path. If the working folder already holds an
`answers.json` (an interrupted run, or a file the customer or a test run prepared): never overwrite, recreate or
replace it. Read it and keep every key it holds (never drop one; a `_fixture` key included: it marks a repository
test run; never add one and never remove one; tell the customer when the file carries it), add a `schema` key only if
it has none, and run `--check`; then go through the groups in order, show each group's recorded answers as that
group's table for a yes instead of asking them again, ask only the questions with no recorded answer or with a
problem, and make the step 2 reads again: their values replace the read values the file holds (reads always come
from Mist). Write `answers.json` atomically every time (a temporary file in the working folder, then
`os.replace()` onto `answers.json`): `watch.py` reads it while it runs. After each group run `python3 <skill folder>/scripts/build_plan.py --answers answers.json --check`
and act on the problems whose question ID belongs to the groups asked so far (re-ask, precondition or
stop, as `intake.md` says; problems of questions not yet asked, also later ones of the current group, are expected). A stop is the exception: give
it as soon as `--check` shows it, even ahead of its question (the customer answered ahead). `--check` also runs
`B.check_overlaps()` on every range answered so far: an overlap carries the ID of the range asked later
(W3, M1, I1, T3 or H5) and names both ranges, so it shows up right after the group that asked that range.
At the end of each group show the answers as a table (secrets as "set, N characters") and get a yes.

| # | Ask | Reads |
|---|---|---|
| 1 | A1, A2; write the `mist` block of `answers.json` (`portal_host`, `api_host`, `token_file`: `mist_api.py` reads them at import); run `B.check_A2(token_file)` before the first API read (`--check` does not look at the token file) | 2.1, 2.2 |
| 2 | A3 | |
| 3 | B1, B2 | 2.3, 2.4 |
| 4 | B3, B4; then read both settings again and run `B.check_site_settings(org_setting, site_setting, release)` with the B4 release (a B4 problem it gave in group 3 is settled here) | 2.4 settings |
| 5 | P (ports), W (ISPs), V (IPv6), S (DNS, NTP) | |
| 6 | H1; with a hub, H2 | 2.5 |
| 7 | With a hub: H3, H4 | 2.6 |
| 8 | M (mgmt-0), I (internal block, AS numbers) | |
| 9 | T0; per network T1, T2, T3, T4, T13 (and T7 later) with the addresses of T3 and T4 filled in, T14, T21 (only when T3 is a public subnet and T14 = yes), T5 (only when T14 = yes), T6 to T9, T16, T17, T10 (only when T14 = yes and at least one ISP delegates; otherwise record `ipv6` none), T18, T11, T15; then T12, T19, T20; then, when at least one network uses the overlay (T11 = yes), H5, H6 and H7, with the overlay networks' names and subnets filled into the H6 wording and the step 2.6 hub lines shown again. A T8 or T17 server at the hub site shows as an H5 problem until H5 is answered: settle it at H5 | 2.7 |
| 10 | X (pair behavior), K (secret file paths), N (profile names, method); then ask once whether anything else is expected in the first push, such as security services or another HA form (intake "Requests at any point") | 2.6 for the N1 clash list: with a hub, reuse the group 7 read and read again only if the profile names changed; without a hub, its first read |
| 11 | R (site readiness; R9 for each ISP whose range W3 left unknown) | 2.8 |

A stop answer: give the stop message and wait; nothing goes further until the answer changes. A
precondition: the customer acts, you read again, then go on. A request for something the design does not
build (intake "Requests at any point"): record it and stop.

## Step 2: Access and read-only checks

1. API host from the portal host: `manage.<x>.mist.com` becomes `api.<x>.mist.com` (`manage.mist.com` becomes `api.mist.com`). Copy `scripts/mist_api.py` into the working folder (rule 11).
2. `GET /self` (base URL `https://api.<x>.mist.com/api/v1`). On 200 list the `privileges` entries (what `python3 mist_api.py /self` prints); the customer picks the org by name and you record its `org_id`. For an `msp` entry the orgs to pick from are `GET /msps/{msp_id}/orgs?limit=1000` (`{msp_id}` is that entry's `msp_id`; rule 12 exception). Then `GET /orgs/{org_id}` of the chosen org held in memory (`python3 mist_api.py /orgs/{org_id}` prints its id, name, `msp_id` and `orggroup_ids`) and `B.check_A3_privileges(privileges, org_id, org=<that record>)`: an org admin, the admin of the MSP whose id the org's `msp_id` carries, or the admin of an org group in its `orggroup_ids` builds, and every later call uses `/orgs/{org_id}` and `/sites/...`; any other role on the org, or site-level access only: stop (intake A3). A 401 almost always means the wrong cloud: re-check A1 before suspecting the token.
3. `GET /orgs/{org_id}/inventory?type=gateway&limit=1000`. For both serials record `mac`, `id` (device id), `site_id`, `model`, `name`, `connected`, `deviceprofile_id`. Never show `magic` (the claim code). Run `B.check_B_inventory(rec1, rec2)` and handle its problems as intake B1 to B4 say (a serial you do not find: first show how many records you read; a B4 precondition found here, a node connected to Mist, goes in the group 3 table and is acted on at B4). A node that already has a `deviceprofile_id`: the inventory holds only the id; show that profile's name from `python3 mist_api.py /orgs/{org_id}/deviceprofiles/<deviceprofile_id>` (it prints only `profile_summary()`); go on only if the customer says to replace it. Then `GET /sites/{site_id}/devices/{device_id}` per node, held in memory (`python3 mist_api.py` on that path prints `device_summary()`), and `B.check_device_record(rec, n)`: `disable_auto_config` absent or false and `mist_configured` true (Mist pushes nothing to a node it does not manage), and no device-level setting (a key outside the identity and placement keys that holds a value); a problem is a precondition the customer fixes in Mist (this skill writes no device records). Show each node's `name` as the host name Mist will render. From the same inventory read, list the connected gateways of the org (`connected` true: name, `mac`, `site_id`) and count how many of them carry a `deviceprofile_id` (step 3.5 reads the list again before the writes).
4. `GET /sites/{site_id}`: show the site name and `timezone`; record `gatewaytemplate_id`. When it is set, `GET /orgs/{org_id}/gatewaytemplates/{gatewaytemplate_id}` held in memory: print only its `name`, the keys of its `port_config` and the keys of its `ip_configs`; an assigned Hub Profile is meant to take its place on both nodes, step 4.5 checks the render, and `plan.md` lists the template under "Beyond the reference design". `GET /orgs/{org_id}/setting` and `GET /sites/{site_id}/setting` held in memory (`python3 mist_api.py` on each prints only `setting_summary()`): `B.check_site_settings(org_setting, site_setting, release)` (here in group 3 `release` is still `None`: a pinned auto-upgrade then shows as a B4 problem, expected until group 4 runs the check again with the B4 release): SRX firmware auto-upgrade on first onboarding not pinned to that release, a push freeze or push window, a commit confirmed timer other than 10 minutes, `protect_re`, a gateway `root_password` or `disable_oob` is a B1 precondition (intake B1).
5. With a hub: `GET /orgs/{org_id}/vpns?limit=1000`: list the VPNs of type `hub_spoke` by name (H2). Each key of the chosen VPN's `paths` is `<hub profile name>-<hub WAN port name>`; the spoke uses `<path>.<VPN>` (H3). No hub-and-spoke VPN: precondition (the hub and its VPN come first, paper section 7 step 1), or H1 = no.
6. `GET /orgs/{org_id}/deviceprofiles?type=gateway&limit=1000` (always with `type=gateway`; print only `profile_summary()` of each). Record the profiles whose name equals a planned profile name (N1); a clash is decided at step 3.1. With a hub, for each chosen path: for each profile and each `port_config` entry with `usage` `wan`, build profile `name` + `-` + the entry's `name`; the hub profile is the one where this equals the path key (never split the path key on `-`); the entry's `name` is the hub WAN port name. Then the hub device: exactly one inventory record whose `deviceprofile_id` is the hub profile's id, and it is connected; none or several: precondition (H4). Its `mac` is the hub MAC. Show it and get a yes; record `hub.paths[].{hub_device_id, hub_site_id, hub_mac, hub_device_name}` (intake H4: the plan names the hub device). Then `GET /sites/{hub site_id}/devices/{hub device id}/config_cmd` held in memory: print, after `redact()`, only the lines that contain both `vpn_<VPN> protocols bgp` and ` import `, the `policy-options policy-statement <name>` lines of every policy those lines name (the tokens after ` import `, with `[` and `]` removed), the `policy-options policy-statement <VPN>_advertise` lines and the `routing-options autonomous-system` line (the overlay AS, `hub.overlay_as`). The customer answers H5 and H6 from them; this skill makes no change to the hub.
7. `GET /orgs/{org_id}/networks?limit=1000` and `GET /orgs/{org_id}/services?limit=1000`: record every existing name that equals a planned name (the network names, ICD, and HUB-SITE-NETS when a network uses the overlay). The bodies are compared at step 3.1 (rule 5).
8. Take and save the snapshot (rule 4).

## Step 3: Plan

1. Complete `answers.json`: every answer and accepted default, the values read in step 2, secrets as paths only (`validate()` refuses example text and read values not in Mist's forms). From the working folder run `python3 <skill folder>/scripts/build_plan.py --answers answers.json --out plan`. Exit 0: the plan folder is written. Exit 1 or 2: nothing is written; each printed line is `[<kind>] <question ID>: <message>`: ask that question again, act on the precondition, or give the stop message and wait; then run it again.
   Then decide each clash recorded at 2.6 and 2.7 (rule 5), before the customer sees the plan, in one script that prints only names and true/false: a network or the application equal to its body in `plan/org-objects.json` field for field (`references/mist-api.md` section 2), or a profile whose raw GET equals the plan profile filled with this node's secrets (the step 4.2 compare): record its name in `existing.reuse` of `answers.json`; any other clash: a network name goes back to T1, a profile name to N1, ICD or HUB-SITE-NETS: stop and ask (rule 5). Run `build_plan.py --out plan` again after any change: `plan.md` then marks each reused object `reuse (no write)`. With no clash recorded, `existing.reuse` is `[]` and no script runs (step 3.3 checks the names again).
2. Show `plan/topology.txt` and `plan/plan.md` to the customer in full (they hold no secrets: the profiles carry placeholders, and the plan says only which secret files were given). When its first section lists items under "Beyond the reference design", say before the question that those parts differ from the pair this design ran on, and that each can be changed to its reference form (the question that sets it) if the customer prefers. Ask "Build exactly this?" (intake E1). A change goes back to its question: validate the answers that depend on it, run step 3.1 again (the clash decision included) and show the new plan.
3. Checks, in one script that prints only counts and true/false; all must pass: `B.validate(answers)` is empty; `B.build(answers)` equals the three JSON files of the plan folder; per profile, the `additional_config_cmds` count equals `B.line_count_formula(plan['derived'], n)`, every line starts with `set ` or `delete `, and the only angle-bracket text left is `B.secret_placeholders(profile)` and the Junos wildcard `<*_to_*>`; every network and application the profiles name (`B.named_objects(profile)`: the keys of `ip_configs` and `dhcpd_config`, `port_config` `networks` and `port_network`, `service_policies` `tenants` and `services`, `path_preferences` path `networks`, `bgp_config` `networks`) is in `plan/org-objects.json` (a create, or a reuse when it is in `existing.reuse`); with a hub, every `<path>.<VPN>` key is a path of the VPN read at step 2.5; and the network, service and gateway profile lists read again now (rule 12) hold no planned name other than those in `existing.reuse`; and both settings read again now give `B.check_site_settings(org_setting, site_setting, answers['release'])` empty. A failed check goes back to step 3.1.
4. The plan folder is the redacted plan you save. Show a table: # | method | path | object | create or reuse | summary, in the order of the writes table of `plan.md`, ending with the two assign calls.
5. Tell the customer: in this design, each create of an org network, the application or a profile made Mist re-push (commit confirmed) the connected gateways of the org about 45 to 55 s later, and the only change on them was the NTP server address; treat every create of step 4 as a push to every connected gateway, so the pushes can repeat across the writes. Read the inventory again now (`list_all()`, rule 12): its connected gateways (by name, and how many carry a Hub Profile) are the ones you name here and whose events step 4 reads; record each one's `mac` and its own `site_id` from that inventory record (most sit in other sites than the branch). Suggest running steps 4.1 and 4.2 in a change window for them. Get a yes to the plan, then go to step 4.

## Step 4: Apply (before either node is powered on)

Each numbered call is one write: show it, get a yes, make it with `write()`, read it back (`references/mist-api.md` section 2). With connected gateways in the org (the step 3.5 read): 2 minutes after the last write of step 4.1, and again 2 minutes after the second profile write of step 4.2 (on the Mist UI path: after the customer's second import), read each connected gateway's events since the first write, in that gateway's own site (`GET /sites/{gw_site_id}/devices/events/search?mac=<gw mac>&start=<first write epoch - 60>&limit=200`, `{gw_site_id}` = the `site_id` its inventory record carries (step 3.5), not the branch site; follow `next`) and report only `event_rows()` of them (type, time, MAC, short redacted text; never `config_diff` or `commit_log`); an event type that contains FAILED: stop and tell the customer.

1. `POST /orgs/{org_id}/networks` for each network body of `plan/org-objects.json`, in step order (the customer's networks, then ICD; skip reused ones), then `POST /orgs/{org_id}/services` for HUB-SITE-NETS when the plan has it. Right before each POST, `find_by_name()` on its list path: the list is complete and holds no object with that name (any case); otherwise stop, no POST, and go back to step 3.1. Read each back from the list read (`list_all()`).
2. `POST /orgs/{org_id}/deviceprofiles`, node 1 then node 2, body `plan/node<n>-profile.json` (skip a profile in `existing.reuse`: step 4.4 assigns it). Show name, line count, ports (every role P2 to P5, marking the HA link port, which exists only in Additional CLI), mgmt-0 address, hub MACs and paths, IPv6 prefixes, and each secret as "set, N characters" (the lengths the intake K1-K3 check printed) or "none", and get the yes. Then run ONE Python script per node that does all of this in one process and prints only the `write()` summary, booleans and counts:
   - `find_by_name('/orgs/{org_id}/deviceprofiles?type=gateway', <profile name>)`: complete and no profile with this name; otherwise stop, no POST (back to step 3.1).
   - Read the node's secret files: the root hash with `read_secret(path, 'root')`; the license key, the root SSH key and the HA link key with `read_secret(path, 'license')`; check them with `B.check_K1()`, `B.check_K2()`, `B.check_K3()`. Any problem: stop, no POST.
   - `body = B.fill_secrets(plan_profile, root_hash=, root_ssh_key=, license_key=, icl_psk=)` (it raises, naming only placeholders, when a value is missing or any `<...>` other than `<*_to_*>` is left; then stop, no POST). It fills all five placeholders; `fill()` of `mist_api.py` knows only the root hash and the license key.
   - Gate on `r = secret_check(body, root_hash, license_key)`: `placeholders_left` 0; with a root hash file `root_lines` 1 and `root_equal` true, without one `root_lines` 0; with a license key `license_lines` 1 and `license_equal` true, without one `license_lines` 0. With a root hash file this is `secret_check_pass(r, bool(license_key))`. Fail: stop, no POST.
   - `write('POST', path, body, secrets=<every secret value of this node>)`.
   - The raw `GET /orgs/{org_id}/deviceprofiles/{profile_id}`: without `id`, `org_id`, `created_time` and `modified_time` it equals `body` key for key and `additional_config_cmds` line for line, and `secret_check()` on it gives the same result as on `body`.
   - `redact()` of the read-back holds none of the node's secret values (print the boolean), and without the four keys it equals the plan profile (`redact()` puts back the plan's placeholder lines, the HA link key line with `<ICL-PSK>` included).
   Never write a filled body or a raw read-back to disk; save only `redact()` of the read-back.
3. Take the snapshot again: only the new objects differ. Anything else changed: stop and report.
4. Assign, one node at a time. Right before each assign, `GET /orgs/{org_id}/inventory?type=gateway&limit=1000` and `GET /sites/{site_id}/devices/{device_id}` again: the MAC belongs to that node's serial, `model` SRX400, `connected` false, `site_id` the branch site, `name` not empty, `B.check_device_record(rec, n)` empty, `deviceprofile_id` null or the profile the customer agreed to replace; otherwise stop. Then `POST /orgs/{org_id}/deviceprofiles/{profile_id}/assign` with `{"macs":["<node mac>"]}`, expect `{"success":["<node mac>"]}`. Read back `GET /sites/{site_id}/devices/{device_id}`: `deviceprofile_id` is the profile id.
5. Render check, read-only: `GET /sites/{site_id}/devices/{device_id}/config_cmd` per node, held in memory. Print counts and true/false only, plus the rendered host name line (it starts `set system host-name`):
   - `_errors` is `[]`; `set chassis high-availability local-id <n>` present; no `<...>` other than `<*_to_*>` left (`B.PLACEHOLDER_RX`).
   - Per network: `set interfaces <LAN interface> unit <unit> vlan-id <VLAN>` present (unit 0 for the untagged network). With an untagged network (T12): exactly one `native-vlan-id` line, `set interfaces <LAN interface> native-vlan-id <its VLAN>`; with none: no `native-vlan-id` line. With LACP, one `ether-options 802.3ad ae0` line per LAN member. One `set interfaces <LAN interface> unit <unit> family inet filter input TO-PEER-ISP` line per network that `plan/plan.md` steers on this node (Internet steering), and no other `filter input TO-PEER-ISP` line.
   - With a hub: the IKE gateway names, taken only from lines matching `^set security ike gateway (\S+) external-interface <WAN port>\.0$`, are exactly the plan's gateways (one per hub path, `wan_to_<hub MAC>_<hub WAN port name>`, the names in the dead-peer-detection lines); at least one line starts `set groups top routing-instances vpn_<VPN> protocols bgp group <VPN>_overlay neighbor `; `routing-instances lan instance-type` present; with an overlay network, a `policy-statement <VPN>_advertise` line present. With a hub and no overlay network (attach only) and no `routing-instances lan instance-type` in the render: the profiles' routing instance `lan` lines do not apply; stop, report it, and offer H1 = no (the pair joins the VPN later): the correction below.
   - Without a hub: no line contains `routing-instances lan `; a line starts `set groups top protocols bgp group ICD `.
   - When ge-0/0/3 is the HA link or the transit link port of a node (P4, P5): whether the render holds `deactivate interfaces ge-0/0/3 unit 0`. If it does, stop: that unit would stay inactive on the box and the HA link or transit link would not come up.
   - With a site gateway template (step 2.4): every `security-zone` name in the render is a planned network name, `wan`, `HA`, `ICD` or `vpn_<VPN>`, and every `ge-0/0/<n>` port in the render is a port of the plan.
   Any failed check: stop, no site hand-off; correct the profile with the gated PUT (`references/mist-api.md` section 4): after an answer change, `build_plan.py --answers answers.json --out plan-update --update plan` writes `plan-update/update.md` with only the changed keys of each profile and their PUT (it stops when org objects would change); show it, PUT with a yes, read back, then `plan-update` replaces `plan`; then run this step again. If `config_cmd` does not answer 200 with a `cli` list, report the status and ask the customer whether to go on with the profile read-back alone; the IKE gateway check then moves to step 7.4.
6. The customer can see the assignment in Mist at Organization > WAN > Hub Profiles > \<profile\> > Applies To Devices (view only: do not click Save, rule 10).

**Mist UI path for the profiles** (N2 = UI import). It replaces steps 4.2 and 4.4 only; step 4.1 runs first by API. First, for node 1 and then node 2, the two gates of step 4.2: the show-and-yes gate (the profile summary and the customer's yes) and the secret gate (`B.fill_secrets()`, then `secret_check()` passes on the filled body); only then write that node's filled file to `<working folder>/secrets/` with `write_private()` (mode 600 from the start), the only place a filled body may be saved, and never print it. Then steps a to e for node 1, then a to e for node 2 (a profile in `existing.reuse` is not imported: a without its `find_by_name()` part, then d and e); tell the customer to wait for you at each pause:
   - a. You: the pre-assign checks of step 4.4 for that node, and `find_by_name()` finds no gateway profile with the planned name.
   - b. The customer imports that node's file at Organization > WAN > Hub Profiles > Import Profile, typing the planned name exactly in the Name field (paper section 7 step 6), and tells you.
   - c. You find the profile by name in the gateway profile list (`list_all()`) and run the step 4.2 read-back compare in one script; a key the import added: report it and ask the customer. No assign before this compare passes.
   - d. The customer assigns it at Organization > WAN > Hub Profiles > \<profile\> > Applies To Devices (paper section 7 step 7) and tells you.
   - e. You read back the assignment (`GET /sites/{site_id}/devices/{device_id}`: `deviceprofile_id` is the profile id).

After node 2's step e, with a yes, delete both filled files. Then step 4.3: each UI import also updates the VPN the pair joins (`modified_time` changes, content unchanged), so compare that VPN by content without the four keys of `references/mist-api.md` section 2, not by `modified_time`; each node's `deviceprofile_id` also differs (the assignment): compare it with its new profile id instead. Then step 4.5.

## Step 5: Site hand-off

First re-read both inventory records and device records: `deviceprofile_id` is the node's new profile, `connected` false, `site_id` the branch site, `name` not empty, `B.check_device_record(rec, n)` empty; and both settings: `B.check_site_settings(org_setting, site_setting, answers['release'])` empty; otherwise stop. Tell the customer not to move, release or unassign either node from now on: a node moved to another site gets a new device record with no profile. Then give the customer this list, built from the answers and the plan and naming each node by its serial, and get a yes on each line:
- Both nodes on the release of B4 (`show version | no-more` on the console), factory default. A node that has run any other configuration: on its console, before shipping, with only the console cable connected, `request system zeroize ztp-option secure-enable`. The node reboots straight into ZTP: with a cable to a DHCP server and the Internet it onboards wherever it is, so keep WAN, LAN and mgmt-0 unplugged until it is at the site.
- Per ISP: DHCP on node n's WAN port (P2) with an address, a default route and DNS, no option 143, and the lease behavior of W4; each delegating ISP also answers DHCPv6 on that port with IA_NA and IA_PD and delegates the prefix of V2. The ISP modem or router accepts the new MAC (R3).
- LAN switch: per node, one LAG on that node's LAN ports (LACP active, no force-up), or the plain port of P3; the untagged network of T12 (or none) untagged and every other network's VLAN tagged; every VLAN bridged between the two nodes' links.
- Cabling, node 1 (serial <node 1 serial>) and node 2 (serial <node 2 serial>): the WAN port to the node's own ISP, the LAN ports to its own LAG or port, the HA link port to the peer's HA link port, the transit-link port to the peer's transit-link port (the ports of P2 to P5, as `plan/topology.txt` shows them).
- mgmt-0 unplugged on both nodes: ZTP tries DHCP on mgmt-0 first, and factory mgmt-0 runs a DHCP server. It goes in only at step 7.3. (With M1 = none: mgmt-0 stays unplugged; there is no out-of-band network.)
- Power on node 1 (serial <node 1 serial>) and node 2 (serial <node 2 serial>) and type nothing on them. Start `watch.py` (step 6) just before power-on. Ask the customer for the actual power-on time as free text in UTC (never offer a "just now" choice): for nodes zeroized or powered earlier, the time their WAN came up or they were powered on at the site. Record it as T0 (`watch.t0_power_on_utc`, `watch.t0_epoch` in `answers.json`; `watch.py` reads it at its next poll). If the customer does not know it, use the first Mist event of each node in `watch.log` and say so.

## Step 6: Watch

No writes and no action on the boxes. Copy `scripts/watch.py` into the working folder; just before power-on write `watch.watch_start_epoch` (now, UTC epoch) into `answers.json` and start it from the working folder:

```
nohup python3 watch.py > /dev/null 2>&1 &
```

Read `watch.log` every few minutes and report changes to the customer; `python3 watch.py --once` makes one extra poll and prints its lines (it writes nothing to `watch.log` and prints every event again). Each time you read `watch.log`, its last heartbeat line is at most about 5 minutes old; an older one means `watch.py` has stopped: start it again the same way (its first poll logs every event again: judge by the event times). `watch.py` re-reads `answers.json` every poll (T0 included), makes GET calls only and implements these rules. Per node, every 20 s, it calls `GET /sites/{site_id}/stats/devices/{device_id}` and `GET /sites/{site_id}/devices/events/search?mac=<mac>&start=<watch_start_epoch - 60>&limit=200` (following `next`) and appends to `watch.log`, through `redact()`, with the UTC time and, once T0 is recorded, the elapsed time from T0: one line per change of status, config_status, config_version, version, ip, deviceprofile_name, the interfaces' up flags and addresses, and uptime up or 0 (not the uptime value, which changes on every poll); one line per new event; the milestones; the alerts; a heartbeat every 5 minutes. A non-200 stats answer before the node's first GW_CONNECTED is logged, not an alert; a failed call is logged with the call (stats or events) and a short reason, and the watch goes on.

Event rules: sort by `timestamp`. GW_ZTP_STARTED, GW_CONNECTED and GW_DISCONNECTED can each come twice, up to 2 minutes apart: keep the first of each pair. Mist logs no event for the push itself: the push is marked by the first GW_DISCONNECTED after the first GW_CONNECTED that follows GW_ZTP_FINISHED, and the node is back after its push at the first GW_CONNECTED after that GW_DISCONNECTED. Events can arrive up to about 5 minutes late: judge every window by event timestamps, not by arrival. The milestones are recomputed every poll from the whole sorted, de-duplicated event list: when an earlier event arrives late, a milestone moves and `watch.log` says so; report the new time.

Measured in this design (push and push confirmed from `show system commit`):

| Interval | Node 1 | Node 2 |
|---|---|---|
| GW_ZTP_STARTED to GW_ZTP_FINISHED | 0:25 | 0:27 |
| GW_ZTP_FINISHED to GW_CONNECTED | 1:23 | 1:24 |
| GW_CONNECTED to the push (commit confirmed) | 3:17 | 3:15 |
| Push to GW_DISCONNECTED | 0:44 | 0:40 |
| GW_DISCONNECTED to GW_CONNECTED (off Mist) | 3:13 | 2:48 |
| Push to push confirmed | 5:38 | 4:40 |

Counted from the zeroize, which includes the zeroize reboot (paper section 5), GW_ZTP_STARTED came at 27:49 on node 1 and 18:14 on node 2, and GW_CONNECTED at 29:37 and 20:05 (node 1 booted 8 min 41 s slower). In the second run (four networks) GW_CONNECTED came 18 min after the zeroize on node 2 and 26.5 min on node 1, each node was back on Mist about 3 minutes after its push, and the push was confirmed 4 min 37 s after it was made.

One Secure ZTP retry is normal. The first call to the redirect server can time out: the node logs `SZTP failure, retrying ZTP` in `show log phc.log`, runs DHCP again (mgmt-0 first, then the WAN port) and calls again about 7 minutes later; in the second run node 1 did this and still reached GW_ZTP_STARTED 24.5 min after the zeroize. A retry needs no alert and no customer action: the windows below allow for it. With preemption off (X1 = no), a node that joins while its peer is ACTIVE joins as BACKUP, whatever its priority. In this design node 2's push landed first (about 9 minutes before node 1's) and node 2 waited in HOLD; when node 1's profile arrived, SRG1 went ACTIVE on node 1 (priority 200) and node 2 moved from HOLD to BACKUP: node 2 logged GW_HA_SRG_STATE_CHANGED (HOLD to BACKUP) and GW_HA_SRG_HEALTH_UP, and GW_BGP_NEIGHBOR_UP showed the transit-link BGP peer up. After the cold-sync reboots of step 7.2, SRG1 stayed ACTIVE on node 2, which is expected. With preemption on (X1 = yes), SRG1 returns to node 1 once node 1 is healthy (step 7.2). Whatever X1 is, the box output of step 7 decides which node is ACTIVE: a GW_HA_SRG_STATE_CHANGED event that does not match the box is reported as an observation, not as a FAIL. A few minutes off Mist after the push is normal: an ISP that holds its address (W4) answers the new Junos DHCP client once the ZTP lease expires. Do nothing inside the 10-minute commit confirmed window.

Alert the customer at once on: an event type that contains FAILED or ERROR_ADDTL_COMMAND (GW_ZTP_FAILED, GW_CONFIG_FAILED, LOCK_FAILED and the like) or starts with GW_ZTP_PRE_SCRIPT_ or GW_UPGRADE_. Absence alerts: no GW_ZTP_STARTED by T0 + 35 min; no GW_CONNECTED by T0 + 45 min; no push GW_DISCONNECTED 15 min after the first GW_CONNECTED; no GW_CONNECTED 11 min after the push GW_DISCONNECTED. Raise an absence alert only when the poll time is at least 5 minutes past the window end and the event is still absent (or came after the window end). The last alert comes after the fact, about 16 minutes after the push: an unconfirmed push has rolled back 10 minutes after it was made, so ask for `show system commit | no-more` on that node and look for a rollback entry. On an alert: no writes and no restarts. Tell the customer, and ask for read-only checks on the node's console if someone at the site can log in: `show system ztp`, `show log phc.log`, `show dhcp client binding` (paper section 2.2).

mgmt-0 stays unplugged until step 7.3 (R6). The `up` flag of `re0:mgmt-0.0` in the Mist stats belongs to the logical unit, not the cable: it showed true on both nodes with no cable in mgmt-0. It is not an alert and proves nothing about the cable; the customer's statement at step 5 does. Check 4 shows the interface zero touch used (ZtpInterface: the node's WAN port).

A node is done watching when it is back on Mist after its push: go to step 7 for that node. `watch.py` keeps running until step 8. `config_status` (NO_CHANGE, INPROGRESS, AWAITING_CONFIRM, COMMITED, FAILED) does not prove a push, and the stats can show an old `config_version` or `rebooting` for minutes. Judge by the events and by the show commands of step 7.

## Step 7: Verify

The customer runs the commands on each node's console and reports the result. The configuration holds the root hash: never ask for it in chat. Relay every command exactly as written in the code blocks, with the `<...>` values filled from the plan. The expected values come from the plan (`plan/plan.md`).

1. Push: `show system commit | no-more`: an entry by root via netconf `commit confirmed, rollback in 10mins` with `version=<config_version>`, then the confirm: the next netconf commit by root after that entry, within 10 minutes of it, whatever its log text, with no rollback entry between them; no rollback entry.
2. Cold sync: `show chassis high-availability information | no-more`: peer on `<HA link port>.0` Conn State UP, SRG1 ACTIVE on one node and BACKUP on the other, Cold Sync Status COMPLETE. A node passes its part of check 2 when its own output shows the peer Conn State UP and Cold Sync Status COMPLETE; the roles are judged on both outputs. With preemption off (X1 = no) either node can be the ACTIVE one (step 6). With preemption on (X1 = yes) SRG1 belongs on node 1: when node 2 holds it (for example after the restarts below), node 1 takes it back once its own cold sync is COMPLETE. With X1 = yes, read both nodes again 5 minutes after both show Cold Sync Status COMPLETE, then every 5 minutes: SRG1 ACTIVE on node 1 passes the role part; still ACTIVE on node 2 20 minutes after both show COMPLETE: check 2 fails; ask for `show chassis high-availability information detail | no-more` on both nodes, take the GW_HA_SRG_STATE_CHANGED events of `watch.log`, and report them with the times. Whatever X1 is, the box output decides; a Mist event that does not match it is an observation. In this design cold sync was still not COMPLETE 20 to 24 minutes after the later node's push was confirmed. Propose a restart only when it is still not COMPLETE 20 minutes after the later node's push is confirmed:
   - a. Before each restart (BACKUP, then ACTIVE), the newest `show system commit` entry on that node does not show `rollback pending` (a reboot then rolls the push back).
   - b. With a yes: `POST /sites/{site_id}/devices/{device_id}/restart`, body `{}`, for the BACKUP. Expect GW_RESTART_BY_USER, GW_CONNECTED about 6.5 min later, and a re-push of the same config_version (rollback pending until Mist confirms it; it was COMMITED about 4 minutes after the reconnect). Mist can show `rebooting` for about 10 minutes after the restart, minutes after GW_CONNECTED. `watch.py` logs the events and alerts on a FAILED one, but its milestones and absence alerts cover only the onboarding push: check 1 on that node decides whether the re-push was confirmed.
   - c. About 12 minutes after that GW_CONNECTED, check again. Still not COMPLETE: check a on the ACTIVE, then with a yes the same restart for the ACTIVE. SRG1 moves to the other node and stays (no preemption; with preemption on, it returns to node 1). In this design both reboots were needed, in both runs; cold sync was COMPLETE 5 min 30 s after the ACTIVE node's reboot. Repeat check 1 after each reboot.
3. mgmt-0: a node that passes check 1 and its part of check 2 gets its mgmt-0 plugged in. With M1 = none, mgmt-0 stays unplugged and this check is met by the customer's word that it is unplugged. Otherwise ask the customer to plug the cable in and to tell you when it is in. The proof the cable is in is the ping below, not the Mist `up` flag (step 6). The address to ping is the M2 or M3 address (static, static-gw), or with dhcp the address in `ips` of `if_stat['re0:mgmt-0.0']` (`GET /sites/{site_id}/stats/devices/{device_id}`, `watch.log` logs it) once the out-of-band DHCP server has given it. From a host on the out-of-band network, the customer pings that address, 5 of 5:

   ```
   ping -c 5 <mgmt-0 address>
   ```

   (on Windows `ping -n 5 <mgmt-0 address>`).

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
show system license | no-more
show system alarms | no-more
show system core-dumps | no-more
show system uptime | no-more
```

Each node whose ISP delegates an IPv6 prefix also:

```
show dhcpv6 client binding detail | no-more
```

With HA link encryption (X2 = yes), both nodes also (the HA link tunnel is listed only with this option; the expected output below follows the Junos MNHA documentation: an output of another form is reported as given, and checks 2 and MNHA detail decide whether the HA link works):

```
show security ike security-associations ha-link-encryption | no-more
show security ipsec security-associations ha-link-encryption | no-more
```

| Check | Expect |
|---|---|
| Version | The release of B4, for example Junos: 25.4X300-D30.3-EVO |
| ZTP | ZtpState CONFIG_COMMIT_ABORTED (the expected end state), ZtpInterface the node's WAN port, ZtpPlatformDefault Secure |
| Factory lines | No output |
| MNHA detail | CS RTO sync 1 of 1 SPUs completed, the LAN interface (ae0 or the plain LAN port) Up, Failure Events: NONE, Peer ICD Conn State UP |
| Signal routes | Signal Route Info: on the SRG1-ACTIVE node the Active Signal Route (the active signal route of `plan/plan.md`) Status INSTALLED and the Backup Signal Route NOT INSTALLED; on the BACKUP node the reverse. Any other state: FAIL; report the Signal Route Info of both nodes (with an overlay network, the local-preference 200 export to the hub follows the active signal route) |
| Virtual IP Info | One Index per network, in T order (Index n = the network at VIP n of `plan/plan.md`), its gateway/prefix on `<LAN interface>.<unit>` (unit 0 for the untagged network); Status INSTALLED on the SRG1-ACTIVE node and NOT INSTALLED on the BACKUP |
| HA history | Every line of HA Peer Conn events and SRG State Change Events is at or after the push of check 1 (`show system commit`, the same box clock); an older line means the node ran an HA configuration before this push: report it. `System booted` of `show system uptime` is before the newest push of check 1 (a node restarted at check 2 boots before its re-push); a later boot that no approved restart explains has cleared the history: report it. Since the push: only BFD conn came up lines, one UNKNOWN -> HOLD (State machine start) and one change out of HOLD (HOLD -> ACTIVE or HOLD -> BACKUP, whatever its reason); with X1 = yes, also the return of SRG1 to node 1 after node 2 held it (BACKUP -> ACTIVE on node 1, ACTIVE -> BACKUP on node 2, whatever its reason). Any other line (a BFD conn went down, another BACKUP -> ACTIVE or ACTIVE -> BACKUP, a second state machine start) not explained by a restart the customer approved: report it, ask the customer, and read the core-dumps output on that node before any PASS; still not explained, and no core file explains it: FAIL, with those lines. These outputs print in the box's own time zone: compare them as printed, and convert to UTC only to compare with `watch.log` |
| BGP | The transit-link peer (the other node's transit-link address of the plan) Established in `lan.inet.0` with a hub, in `inet.0` without; with a hub, the hub peer Established in `vpn_<VPN>.inet.0` |
| BFD | Every session Up, 1000 ms, multiplier 3: the HA link, peer forwarding, the transit-link peer and, with a hub, each overlay peer |
| IKE, IPsec | With a hub: IKEv2 SA UP on each gateway of the plan (`wan_to_<hub MAC>_<hub WAN port name>`), local `<WAN port>.0`, and one IPsec tunnel per gateway. With HA link encryption (the expected form, as above): `show security ike security-associations ha-link-encryption` shows an IKE SA UP on gateway MNHA-ICL-GW toward the peer HA link address, and `show security ipsec security-associations ha-link-encryption` one tunnel (an inbound and an outbound SA) whose ID is in that IKE SA's `IPSec Tunnel IDs` line, gateway the peer HA link address. Neither: no SA |
| WAN DHCP | `<WAN port>.0` BOUND with the ISP's lease; on each delegating node DHCPv6 BOUND, IA_NA IA_PD, the delegated prefix as Client IP Prefix |
| LAN DHCP | Not judged here: check 6 reads the bindings once the test hosts are plugged in (an empty list now is expected) |
| License | With a key in the node's profile: `Licenses installed` lists a License identifier with its Features, each permanent or date-based with an end date after today (the license certificate of this node's serial names that identifier and those features: the customer may compare them; the result does not wait for it); without one: `Licenses installed: none`. No license alarm |
| Alarms, cores | 0 alarms; no core files |

5. Mist audit: `GET /orgs/{org_id}/logs?start=<T0>&limit=50` (follow `next`; report only `log_rows()`: time, site_id, short message): the entries whose `site_id` is the branch site or whose `message` names a node MAC are only the restarts the customer approved.
6. Networks. Before any test, ask which host is on which network: the switch, port and VLAN of each, or a VLAN interface of the LAN switch acting as a DHCP client (in the second run the test hosts were the switch's VLAN interfaces). Check that each host has an address in its network before you ping from it. A host with no lease: check its access VLAN and port first; a binding of that MAC on another network shows the pair is answering DHCP and the host sits on the wrong VLAN. The minimum: one network per preferred ISP, every overlay network, one network without Internet access if the plan has one, one reach pair (T15) if the plan has one, and the IPv6 part below on every network that takes IPv6; test more networks if the customer can. Per tested network, on a host plugged into that VLAN:
   - Address: the host takes its address by DHCP; a static test address does not count on a DHCP network. Where the firewalls serve DHCP, on both nodes (with a hub):

     ```
     show dhcp server binding routing-instance lan detail | no-more
     ```

     (without a hub: `show dhcp server binding detail | no-more`): on the SRG1-ACTIVE node, which serves the lease, the test host's MAC with an address in that network's DHCP range, Incoming Client Interface `<LAN interface>.<unit>` and Client Interface Vlan Id = its VLAN; on the other node the same MAC and address (the Active Leasequery copy, whose interface and VLAN can be those of the T20 binding-sync network, for example ae0.0 and VLAN 10). A relay network: the customer's DHCP server shows the lease for the host's MAC. A network with DHCP none: the host's static address in the subnet. This is the LAN DHCP check.
   - Pings from the host, 5 of 5 each, to its gateway, and with Internet access to an Internet address; on an overlay network also to a hub-site address; on a network without Internet access, the Internet address answers 0 of 5; for a reach pair, a host of the network that may reach pings a host of the other network, and when the reach is one-way a host of the other network pings it back and gets 0 of 5:

     ```
     ping -c 5 <gateway>
     ping -c 5 <Internet address, for example 1.1.1.1>
     ping -c 5 <hub-site address>
     ```

     (on Windows `ping -n 5 <address>`).
   - Egress (the preferred ISP of T5), on one tested network per preferred ISP. Note which node holds SRG1 (check 2). While the host pings the Internet address (`ping -c 30 <Internet address>`; on Windows `ping -n 30 <Internet address>`), on the SRG1-ACTIVE node:

     ```
     show route table XNODE.inet.0 0.0.0.0/0 exact | no-more
     show firewall filter TO-PEER-ISP | no-more
     ```

     and on both nodes:

     ```
     show security flow session destination-prefix <Internet address> | no-more
     ```

     For the network whose preferred ISP is the other node's: the XNODE default is BGP via the other node's transit-link address and active, the `to-peer` counter rises between two reads of `show firewall filter TO-PEER-ISP | no-more` about 10 s apart during the pings, the ACTIVE node lists the host's session leaving on its transit-link port `<transit-link port>.0`, and the other node lists a session from the ACTIVE node's transit-link address (source NAT rule-set LAN_to_ICD) leaving on its WAN port `<WAN port>.0`. For the network whose preferred ISP is the ACTIVE node's own: the ACTIVE node lists the host's session leaving on its own WAN port. When every network prefers the same ISP, test one network: it leaves by that ISP's node.
   - IPv6 part, on every network whose IPv6 (T10) is not none: the host has a SLAAC address in that network's planned /64 (`plan/plan.md`) and pings the serving node's address (`::2` node 1, `::3` node 2, in that /64) and an IPv6 Internet address, 5 of 5 each:

     ```
     ping -6 -c 5 <node address in the /64>
     ping -6 -c 5 <IPv6 Internet address>
     ```

     (on macOS `ping6 -c 5 <address>`, on Windows `ping -6 -n 5 <address>`).
7. IPv6 prefix known after onboarding (V2 unknown), or a new prefix later (V3 accept-manual-update): the customer reports the Client IP Prefix of `show dhcpv6 client binding detail | no-more`; set `isps.<n>.delegated_prefix` and run `python3 <skill folder>/scripts/build_plan.py --answers answers.json --out plan-update --update plan`. Show `plan-update/update.md`, not `plan.md`: it lists only the changed lines and one PUT per changed profile (the objects this run created are not clashes here, and steps 3.1 and 3.3 do not run again). With a yes, the gated PUT of `references/mist-api.md` section 4 for each profile it lists: only `additional_config_cmds`, the whole new array filled with `B.fill_secrets()` in one script, then the step 4.2 read-back against `plan-update`; then `plan-update` replaces `plan`. Mist re-pushes the node (commit confirmed): `watch.py` logs its events and alerts on a FAILED one (its milestones and absence alerts cover only the onboarding push), then checks 1 and 4 and the IPv6 part of check 6.

Report PASS only when checks 1 to 6 all match. A check the customer cannot run yet (no host on that VLAN, no access to the out-of-band network) is open, not FAIL: report the results you have, name each open check and what it needs, and report PASS once the open checks are run and match. A check that does not match: report the failing check and its output. Go to step 8 once every check has a result or is named open with what it needs.

Optional, for information only (not part of PASS): if the customer saves a node's `show configuration | display set | no-more` to a local file (mode 600; it holds the root hash), diff it against `config_cmd` with a script that redacts before printing. Expected differences: the Mist agent block (groups mist-script, user mist, outbound-ssh, ephemeral db, extensions, syslog files, pki ca-profiles, scripts), `system commit synchronize` on the box, the NTP server address, notation (the render writes value lists as `[ ... ]` and `lo0.1`, `st0.0`; the box one value per line and `lo0 unit 1`, `st0 unit 0`), render `set` lines that a later render `delete` cancels (`apply-groups apbr`, `dead-peer-detection optimized`), the version line, and the render-only `deactivate interfaces ge-0/0/3 unit 0` when ge-0/0/3 is a LAN LAG member (step 4.5 checks for it when ge-0/0/3 is the HA link or the transit link). Report any other line.

## Step 8: Close out

Step 8 runs once every check of step 7 has a result or is named open with what it needs. Stop `watch.py` (`kill "$(cat watch.pid)"` in the working folder); an open check is run later from the console and the Mist reads, without `watch.py`. List the objects you created, by name (ids stay in the working folder). Remind the customer that the API token stays valid until they delete it in Mist. With a yes, delete the secret files and any filled copies in `secrets/`; otherwise leave them at mode 600. Everything else in the working folder, the plan folder included, is redacted.

## Pointers

- Paper `../../docs/SRX400-MNHA-Zero-Touch-Mist.pdf`: 3.1 checklist, 4 profile settings, 5 measured onboarding, 6 verification, 7 deployment steps, 8 reference files and placeholders.
- `../../junos/srx400-node{1,2}-zero-touch.set`: each node's configuration after onboarding with the paper's values, display set form.
- `references/intake.md`, `references/mist-api.md`, `scripts/mist_api.py`, `scripts/build_plan.py`, `scripts/watch.py`; `python3 -m unittest -v` in the skill folder runs `tests/` (the golden tests read `../../mist` and `org-objects.json` of the clone).
