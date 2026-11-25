# Mist API calls for the SRX400 zero-touch drop ship

Every call this skill makes, with its body, what to check, and the traps. Base URL:
`https://api.<cloud>.mist.com/api/v1` (from the portal host `manage.<cloud>.mist.com`; the global
cloud is `api.mist.com`). Headers `Authorization: Token <token>` and `Content-Type: application/json`
on every call. Paths below are relative to the base URL.

## 1. Client: `scripts/mist_api.py`

Copy `scripts/mist_api.py` (Python 3 standard library only) into the working folder, next to
`answers.json`, and run every script from that folder with plain `python3 <script>`, so the folder is
on `sys.path`. With `python3 -I` (isolated mode leaves the script's folder off `sys.path`), run
`sys.path.insert(0, '<working folder>')` before `import mist_api`. Its functions:

| Function | Use |
|---|---|
| `mist(method, path, body=None)` | One call; returns `(http_status, parsed JSON, or the text when the body is not JSON)`, an error body included; an empty body gives `{}`; no connection, a timeout or a dropped connection gives `(0, reason)` (after a write, status 0 means it may have landed: read back before any retry). The token is read from `mist.token_file` inside the call. Nothing is sent, `(0, reason)` without the value, when `mist.api_host` is not a Mist API host or not the API host of `mist.portal_host`, or when the token file does not hold one token line of letters and digits; a redirect is never followed (the 3xx comes back as it is). A path that starts with `/api/v1` (a `next` link) has that prefix removed. Response headers go to `LAST_HEADERS` |
| `mask_token(text)` | `text` with the API token and any `Token <value>` masked (`watch.py` masks every line with it) |
| `page_total()` | `X-Page-Total` of the last call, or `None` when Mist did not send it (Mist sends it only when the request carries `limit`). Read every list with `list_all()` |
| `list_all(path, limit=1000)` | Every row of a list read (SKILL.md rule 12): `path` with its filters (`type=gateway`), without `limit` and `page`; it reads `limit=1000&page=1`, then `page=2`, `page=3`, ... with the same limit until the unique ids read equal `X-Page-Total`. Returns `(status, rows, total, complete)`; `complete` false (no `X-Page-Total`, a page that does not answer 200 with a list, or a page with no new row before the total): the list is incomplete; stop and tell the user |
| `find_by_name(path, name)` | `(complete, rows)`: the rows of `list_all(path)` whose `name` equals `name`, ignoring case. The name-clash check right before each create of SKILL.md step 4; `complete` false: stop |
| `redact(o)` | Copy that is safe to show or save: drops `magic` (claim code); `config_diff`, `commit_log`, `before` and `after` (event diffs, audit copies) become their length; root hash, license key and every `$n$...` string (quoted or not) become placeholders; the value after `pre-shared-key ascii-text`/`hexadecimal`, `authentication-key` (also `... type md5 value`), `secret`, `password`, `plain-text-password-value`, `authentication-password`, `privacy-password`, `md5 <n> key`, a quoted `key "..."`, a quoted `ssh-<type> "..."` and `community` becomes `<SECRET>`, in set and hierarchical form, also inside raw JSON text (escaped quotes, escapes inside the value, an unterminated quote to the end); the text rules run on dict keys too; under a key whose name ends in `psk`, `secret`, `password`, `passwd`, `passphrase`, `pass`, `pw`, `auth_key`, `community`, `comm`, `token`, `key`, `keys` or `hash` every scalar, every scalar of a list and a direct `value` child become `<SECRET>`. On a profile read-back the root password, root SSH key, license and HA link key lines come back as the placeholder lines of the plan profiles (`set system root-authentication <ROOT-SSH-KEY-TYPE> "<ROOT-SSH-KEY>"` for a key of any type; the `MNHA-ICL-IKE-POL pre-shared-key` line with `"<ICL-PSK>"`); any other pre-shared key becomes `"<SECRET>"` |
| `event_rows(events)`, `log_rows(logs)` | The only fields of device events (`type`, `timestamp`, `mac`, a short redacted `text`) and of org audit log entries (`timestamp`, `site_id`, a short redacted `message`) that are printed or reported |
| `device_summary(rec)`, `setting_summary(st)` | A device record: identity, `disable_auto_config`, `mist_configured` and the names of its device-level settings; an org or site setting: only the fields `build_plan.check_site_settings()` judges, `root_password` as set or not |
| `write_private(path, data)` | Writes a new file with mode 600 from the start (refuses an existing file): the UI path's filled files |
| `profile_summary(p)` | The only fields of a device profile you print or save outside this skill's own plan and read-backs: `id`, `name`, `type`, `modified_time`, and per `port_config` entry its `name`, `usage` and `vpn_paths` keys |
| `safe_error(out, secrets=())` | An error body as safe text: every value in `secrets` masked (raw and JSON-escaped), then `redact()` on the decoded JSON, cut to 500 characters |
| `write(method, path, body, secrets=())` | One approved write. Prints only `{status, id, name}` (or `success` for the assign), never the object; returns the raw response for in-memory checks. On an error (status 0: no answer) it prints `safe_error()`; a profile create or update (`/orgs/{org_id}/deviceprofiles` or `.../deviceprofiles/{profile_id}`) without `secrets` prints only the error length. Pass the node's root hash and license key as `secrets` on every profile write |
| `read_secret(path, kind)` | Reads a root hash (`kind='root'`) or license key (`'license'`) file, stripped; raises without the value when group or others can read the file (chmod 600) or the value is not usable. A root SSH key or HA link key file is read with `'license'` (the one-line rule) and checked with `build_plan.check_K1(value, 'ssh-key')` or `check_K3(value)` (intake K1 to K3) |
| `fill(plan, root_hash, license_key)` | In-memory copy of a redacted plan profile with that node's root hash and license key in place. Raises, naming only the placeholders, when any `<...>` other than `<*_to_*>` is left. A plan profile can also carry `<ROOT-SSH-KEY-TYPE>`, `<ROOT-SSH-KEY>` and `<ICL-PSK>`: fill every profile with `build_plan.fill_secrets(profile, root_hash=, root_ssh_key=, license_key=, icl_psk=)`, which fills all five and raises the same way (SKILL.md step 4.2) |
| `self_privileges(out)` | The `GET /self` entries reduced to `scope`, `org_id`, `msp_id`, `name`, `role` (what `python3 mist_api.py /self` prints; SKILL.md step 2.2) |
| `secret_check(profile, root_hash, license_key)`, `secret_check_pass(result, has_license)` | Booleans and counts only: placeholders left (every `<...>` other than `<*_to_*>`), root lines, root equal (a non-empty hash that starts with `$`), license lines, license equal. `secret_check_pass()` takes the result of `secret_check()`: `secret_check_pass(secret_check(body, root_hash, license_key), bool(license_key))` |

`python3 mist_api.py <path>` makes one GET and prints the status and `X-Page-Total` (a list path: every page
through `list_all()`, with the row count, the total and `complete`), then only what this skill reads
(`cli_view()`): for `/self` the `scope`, `org_id`, `msp_id`, `name` and `role` of each `privileges` entry (and
`orggroup_ids` when set) and their count; `GET /orgs/{org_id}`: id, name, `msp_id`, `orggroup_ids`; a site: id,
name, timezone, gatewaytemplate_id; a setting: `setting_summary()`; the inventory: serial, mac, id, site_id, model,
name, type, connected, deviceprofile_id per record; a device record: `device_summary()`; stats: status, config and
version fields, `if_stat` up and ips; events and logs: `event_rows()`, `log_rows()`; a gateway template: its name and
the keys of `port_config` and `ip_configs`; a `/deviceprofiles` path: `profile_summary()` of each profile; a
`config_cmd` path: its line count and `redact()` of `_errors`; networks, services, VPNs and MSP org lists: `redact()`;
any other path: only its key names; an error: `safe_error()`.

Everything a command prints enters the agent's context: print only what `python3 mist_api.py <path>` prints,
`profile_summary()`, `event_rows()`, `log_rows()`, `write()` summaries and `secret_check()` results. Never print a raw profile, a raw
`config_cmd`, a filled body or a secret file. Keep raw objects in memory; save only redacted copies.

Secrets live in one process. Read the secret files, fill (`build_plan.fill_secrets()`), check, write, read back raw, `secret_check()`
and compare in ONE script run that prints only the `write()` summary, booleans and counts. Never pass a
filled body or a raw read-back between commands through a file; the UI path's `secrets/` files
(SKILL.md step 4) are the only filled copies on disk.

## 2. Read-back rules

| Object | Compare |
|---|---|
| Network | The record from `GET /orgs/{org_id}/networks?limit=1000` (every page, `list_all()`) with that name, without `id`, `org_id`, `created_time`, `modified_time`, and without `zone_id` when Mist added it as `null`: equal to the POST body |
| Service | The record from `GET /orgs/{org_id}/services?limit=1000` (every page, `list_all()`) with that name, without the four keys: equal to the POST body |
| Hub Profile | On the raw `GET /orgs/{org_id}/deviceprofiles/{profile_id}` held in memory, without the four keys: equal to the filled body that was sent, key for key and `additional_config_cmds` line for line, and `secret_check()` gives the same result as on that body (no placeholder left, the root line equals that node's hash file or is absent with an SSH key only, the license line equals its key file or is absent). This covers the root SSH key and the HA link key too, which `secret_check()` does not see. Save only `redact()` of it |
| Assignment | `GET /sites/{site_id}/devices/{device_id}`: `deviceprofile_id` equals the profile id |
| VPN the pair joins (UI path only) | Each UI Import Profile also updates the VPN: `modified_time` changes, content does not. Compare the VPN without the four keys with the snapshot copy |

The same rule decides reuse: an existing object with a planned name that equals the planned body
after the same stripping is reused read-only; an existing Hub Profile only if, in addition,
its raw GET equals the planned body filled with this node's secret files (the Hub Profile rule above).
Any other existing object with that name is a clash: a customer network name goes back to intake T1,
a profile name to N1; for ICD or HUB-SITE-NETS, stop.

## 3. Read-only calls

Every list read below (a path with `limit=1000`) goes through `list_all()`: `&page=2`, `&page=3`, ... with
the same limit until the unique ids read equal `X-Page-Total` (SKILL.md rule 12).

| Call | Purpose | Check |
|---|---|---|
| `GET /self` | Token and cloud check; list the orgs | Read only `privileges`: entries `{scope, org_id, msp_id, name, role}` (an `msp` entry carries `msp_id`, no `org_id`; an `orggroup` entry its org group ids); the org needs an `org` entry with role `admin`, an `msp` entry with role `admin` for the MSP the org belongs to, or an `orggroup` entry with role `admin` for one of the org's groups (`build_plan.check_A3_privileges(privileges, org_id, org=<GET /orgs/{org_id}>)`); `site` or `sitegroup` access only: stop. Do not depend on the other top-level keys. 401 = almost always the wrong regional API host |
| `GET /msps/{msp_id}/orgs?limit=1000` | Per `msp` entry of `GET /self` (its `msp_id`): the orgs to pick from (intake A3) | Read only; a list to pick from, not the proof (Mist documents no paging for it: show the rows read) |
| `GET /orgs/{org_id}` | The chosen org: its `msp_id` and `orggroup_ids` prove MSP or org-group access (intake A3) | 200 needed; held in memory for `check_A3_privileges(..., org=)` |
| `GET /orgs/{org_id}/inventory?type=gateway&limit=1000` | Serial to `mac`, `id` (device id), `site_id`, `deviceprofile_id`, `connected`, `model`, `name`; the hub device's `mac`; the count of connected gateways | Both serials present, `model` SRX400, same `site_id`, `connected` false; `name` read and shown (empty: not a stop here, required at SKILL.md steps 4.4 and 5); `deviceprofile_id` null, or the profile the user agreed to replace. Device id has the form `00000000-0000-0000-1000-<mac>`. Never show `magic` (claim code). A serial not found: show the user how many records you read and ask before you conclude it is absent |
| `GET /sites/{site_id}` | The branch site; its `timezone` | `gatewaytemplate_id`: null, or a template the render check of SKILL.md step 4.5 covers (an assigned Hub Profile is meant to take its place; `plan.md` lists it under "Beyond the reference design") |
| `GET /orgs/{org_id}/gatewaytemplates/{gatewaytemplate_id}` | The site's gateway template, when set | Hold it in memory; print only its `name`, the keys of `port_config` and the keys of `ip_configs` (it can hold secrets) |
| `GET /orgs/{org_id}/setting`, `GET /sites/{site_id}/setting` | SRX settings that change the zero-touch push (intake B1) | Held in memory; `build_plan.check_site_settings(org_setting, site_setting, release)` judges `juniper_srx.auto_upgrade` (SRX firmware upgrade on first onboarding: off, or `custom_versions` SRX400 = the B4 release), `config_push_policy` (`no_push`, `push_window`), `gateway_mgmt` (`config_revert_timer` 10 or absent, `protect_re`, `root_password`, `disable_oob`); a site value takes the place of the org value. Run it in group 3 (B4 not answered: a pinned auto-upgrade is a B4 problem until then), again after B4 with the B4 release, before the writes (SKILL.md step 3.3) and at the hand-off (step 5). The site `auto_upgrade` key is the AP firmware window and is not judged. Settings can hold secrets (`vars`, `gateway_mgmt.root_password`): print only `setting_summary()` |
| `GET /orgs/{org_id}/vpns?limit=1000` | The hub-and-spoke VPN and its paths (intake H2, H3); snapshot | Shape, for the paper's VPN, `{"name":"OrgOverlay","type":"hub_spoke","paths":{"HUB-wan":{"bfd_profile":"broadband"}},"createdBy":"user"}`. Path key = `<hub profile name>-<hub WAN port name>`; spokes use `<path>.<VPN>`. On the API path its `modified_time` must not change; on the UI path compare it by content (section 2) |
| `GET /orgs/{org_id}/deviceprofiles?type=gateway&limit=1000` | Profile name clash; snapshot; find the hub profile | Always with `type=gateway`: without it the list holds no gateway profiles and a clash is missed. The list holds other profiles' secrets: print and save only `profile_summary()` of each (the fields of section 1, `profile_summary()`). Hub profile: the one whose `name` + `-` + the `name` of a `port_config` entry with `usage` `wan` equals the path key; never split the path key; that entry's `name` is the hub WAN port name |
| `GET /orgs/{org_id}/deviceprofiles/{profile_id}` | Read back a created profile; read the hub profile | See read-back rules |
| `GET /orgs/{org_id}/networks?limit=1000` | Name clash (case-insensitive), snapshot, read-back | |
| `GET /orgs/{org_id}/services?limit=1000` | Name clash for HUB-SITE-NETS, snapshot, read-back | |
| `GET /sites/{site_id}/devices/{device_id}` | Management flags; assignment read-back; snapshot | `build_plan.check_device_record(rec, n)` (SKILL.md steps 2.3, 4.4 and 5): `disable_auto_config` absent or false (a never-connected gateway record can lack the key) and `mist_configured` true; and no device-level setting: an allow-list, so every key other than the identity and placement keys (`id`, `name`, `mac`, `serial`, `notes`, `model`, `type`, `hw_rev`, `map_id`, `tag_id`, `tag_uuid`, `evpn_scope`, `evpntopo_id`, `st_ip_base`, `adopted`, `bundled_mac`, `managed`, `mist_configured`, `disable_auto_config`, `deviceprofile_id`, `site_id`, `org_id`, `created_time`, `modified_time`, `x`, `y`, `height`, `orientation`, `locked`, `image1_url` to `image3_url`) that holds a value (for example `port_config`, `mnha_config`, `vrf_config`, `vars`, `dns_suffix`, `port_mirroring`, `idp_profiles`, `additional_config_cmds`) is one Mist renders on top of the Hub Profile; any problem is a precondition (the skill writes no device records). `deviceprofile_id`. Print only `device_summary()` |
| `GET /sites/{site_id}/devices/{device_id}/config_cmd` | Render preview after assignment; the hub's overlay import lines, advertise policy and AS (intake H5, H6, I2); later, compare with the box | `{cli:[...], _errors:[]}`, checks in SKILL.md step 4.5; the render line count depends on the answers and is not checked. It holds the root hash: hold it in memory, print only the checks and the lines SKILL.md names. Not 200 with a `cli` list for a node that has never connected: report the status and ask the user (SKILL.md step 4.5) |
| `GET /sites/{site_id}/stats/devices/{device_id}` | Watch every 20 s; snapshot `status`, `config_version` | `status` (connected, disconnected, rebooting), `config_status` (NO_CHANGE, INPROGRESS, AWAITING_CONFIRM, COMMITED, FAILED), `config_version`, `version`, `uptime`, `ip`, `if_stat` (keyed by interface, with the paper's ports re0:mgmt-0.0, ge-0/0/4.0, ae0.0, ge-0/0/2.0; each entry has `up` and `ips`: the mgmt-0 address of SKILL.md step 7.3, also one from out-of-band DHCP), `deviceprofile_name`. Values lag: log them, do not gate on them. Record the HTTP status when it is not 200 |
| `GET /sites/{site_id}/stats/devices?type=gateway` | Both nodes' stats in one call | |
| `GET /sites/{site_id}/devices/events/search?mac=<mac>&start=<epoch>&limit=200` | Event timeline per node (the branch site); for another connected gateway of the org (SKILL.md step 4), `{site_id}` is that gateway's own `site_id` from its inventory record | `{start, end, limit, total, results[], next?}`; each result has `type`, `mac`, `timestamp`; `text` only on some types (the ZTP, GW_CONNECTED, GW_DISCONNECTED and GW_RESTART_BY_USER events have none): read it with `.get('text')`. GW_CONFIGURED events of connected gateways carry `config_diff` and `commit_log` (their configuration): report only `event_rows()`. Without `start` it returns total 0. Follow `next` until it is absent |
| `GET /orgs/{org_id}/logs?start=<T0 epoch>&limit=50` | Audit: nothing else touched the nodes | `{start, end, limit, total, results[], next?}`; follow `next`. Each result has `message`, `site_id`, `timestamp`, `admin_name` and can carry whole `before`/`after` objects: report only `log_rows()`. Count only entries whose `site_id` is the branch site or whose `message` names a node MAC: after onboarding, only the approved restarts, each `device[<mac>] manually restarted` |

`<mac>` is 12 lowercase hex digits with no separators, as the inventory shows it.

## 4. Writes (each one needs the user's yes)

| Call | Body | Expect |
|---|---|---|
| `POST /orgs/{org_id}/networks` | One network body of the plan folder's `org-objects.json` (the customer's networks in T order, then ICD), one call each, in step order, skipping `existing.reuse`; right before each, `find_by_name()` finds no network with that name | 200 and the stored object with `id`. Read-back = body plus `zone_id: null` |
| `POST /orgs/{org_id}/services` | The HUB-SITE-NETS body of the plan folder's `org-objects.json` (only with a hub and an overlay network): `{"name":"HUB-SITE-NETS","type":"custom","addresses":["<hub site prefixes>"],"specs":[{"protocol":"any","port_range":"0"}]}` | 200 and the object with `id`. Read-back = body |
| `POST /orgs/{org_id}/deviceprofiles` | The whole plan profile `node<n>-profile.json` (it carries `name` and `"type":"gateway"`, no `id`), secrets filled in memory only with `build_plan.fill_secrets()`; the secret gate of SKILL.md step 4.2 passes on the body before the call; `write(..., secrets=<every secret value of that node>)`; fill, POST and read-back in one script run (section 1) | 200 and the object with `id`. Read-back per section 2. Created unassigned |
| `POST /orgs/{org_id}/deviceprofiles/{profile_id}/assign` | `{"macs":["<node mac>"]}` | `{"success":["<node mac>"]}`. On a connected device this logs GW_CONFIG_CHANGED_BY_USER and Mist pushes 34 to 38 s later; in the drop-ship order the node is not yet powered on |
| `POST /sites/{site_id}/devices/{device_id}/restart` | `{}` | `{}`. GW_RESTART_BY_USER at once; node back on Mist 6 min 35 s to 6 min 40 s later; Mist re-pushes the same `config_version`; audit entry `device[<mac>] manually restarted` |

A created profile that needs a correction before power-on: take the raw
`GET /orgs/{org_id}/deviceprofiles/{profile_id}` held in memory (never a saved or redacted copy: those
carry placeholders and would wipe the secrets), change only the planned value, show the change
redacted (after an answer change, `build_plan.py --update <plan folder> --out <new folder>` writes `update.md`:
the changed top-level keys of each profile and one PUT per changed profile), and with a yes
`PUT /orgs/{org_id}/deviceprofiles/{profile_id}` with only the changed top-level keys and their whole values (for
`additional_config_cmds`, the whole array, never `[]` or `null`).
When the body carries `additional_config_cmds`, fill it with `build_plan.fill_secrets()` and the secret gate of SKILL.md step 4.2 passes on it before the PUT (the IPv6 update of SKILL.md step 7.7 is such a PUT).
The raw GET, the change, the PUT (with `secrets=`) and the read-back run in one script, as for the
POST: never save the raw object or the PUT body to disk. Then read back per section 2.

## 5. Calls this skill never makes

- `PUT /sites/{site_id}/devices/{device_id}` with `{"deviceprofile_id": ...}`: it returns 200 and bumps `modified_time` but does not change the profile. Any device-record write (a `notes` PUT, a `disable_auto_config` toggle) made Mist re-push a connected gateway.
- Any DELETE, and any write to an object the skill did not create, unless the user asks for it.
- Writes to the hub, its profile or the VPN: they are prerequisites the user owns.

## 6. Traps

| Trap | Avoid |
|---|---|
| Wrong regional API host: 401 with a valid token | Derive the host from the portal host; `GET /self` first |
| In this design, each create of an org network, the application or an unassigned profile made Mist re-render and push (commit confirmed) the connected gateways of the org about 45 to 55 s later; the only change on them was the NTP server address | Treat every create as a push to every connected gateway, repeated across the writes. Before the first org-object POST tell the user which gateways are connected and suggest a change window (SKILL.md step 3.5). A check seconds after a POST misses the push: 2 minutes after the last network write and again after the profile writes, read each connected gateway's events since the first write in that gateway's own site (`GET /sites/{gw_site_id}/devices/events/search?mac=<gw mac>&start=<epoch>&limit=200`, `{gw_site_id}` = the `site_id` of its inventory record, not the branch site), report them and stop on an event type that contains FAILED (SKILL.md step 4) |
| The API accepts names the Mist UI refuses (over 32 characters, or characters other than letters, digits, `_` and `-`) | Validate every name locally before the POST |
| The API accepts a profile that references networks or applications that do not exist; the UI then refuses it | Create the org objects first, check every referenced name exists, then POST the profiles |
| PUT merges top-level keys and replaces nested objects; `additional_config_cmds: []` renders no Additional CLI (MNHA gone); a `null` override falls back to platform-default ports | Create with POST only; correct with a PUT of the changed key's whole value; never `[]` or `null`; read back after every write |
| A redacted copy used as a write body puts the literal placeholders on the box | Build every write body from the raw object in memory; `secret_check()` before the write and on the raw read-back |
| Additional CLI takes `set` and `delete` only; one `insert` line fails the whole push with no reason given | Reject any other line |
| `deviceprofiles` without `type=gateway` misses gateway profiles | Always add `type=gateway` |
| `events/search` without `start` returns total 0 | Always pass `start` (60 s before `watch.py` started, just before power-on); follow `next` |
| Events arrive up to about 5 minutes late and out of order; GW_ZTP_STARTED (3 to 5 s apart), GW_CONNECTED (1 min 46 s to 1 min 48 s apart) and GW_DISCONNECTED (8 to 15 s apart) each came twice per node | Sort by `timestamp`; keep the first of each pair; judge alert windows by event timestamps, not arrival time (SKILL.md step 6) |
| `config_status` is not a push gate: COMMITED can show once and not for a later push, INPROGRESS can stick, FAILED can flip on retry | Confirm a push on the box: `show system commit` |
| After a reboot from Mist the status stays `rebooting` about 10 minutes after the restart, minutes after GW_CONNECTED; right after ZTP the stats can show the old `config_version` | Judge by GW_CONNECTED events and show commands |
| A node that connects with no profile gets a different first push (site gateway template or the Mist default render). Moving a device to another site (unassign, then assign) gives it a new device record with `deviceprofile_id` null | Assign both profiles before power-on; with a site gateway template, the render check of SKILL.md step 4.5; re-read both inventory records right before power-on; the user does not move, release or unassign the nodes after the assign |
| These profiles assigned over a pair running another MNHA configuration failed with GW_CONFIG_FAILED (`Configuration does not support multiple IPv4 addresses per virtual-ip entry without grid-id`); Mist does not delete chassis high-availability lines | Nodes start factory default on 25.4X300-D30.3 (`request system zeroize ztp-option secure-enable`); stop if a node is already connected with another configuration |
| Factory mgmt-0 has a static address and a DHCP server, and ZTP tries DHCP on mgmt-0 first | mgmt-0 unplugged until the node passes the push and cold sync checks |
| After the push the ISP DHCP server answers the new Junos DHCP client only once the ZTP lease expires; the node is off Mist about 3 minutes | Keep the three WAN DHCP client lines the plan carries and an ISP that holds its address for 13 minutes at most or gives a new one at once (intake W4; 10 minutes in this design); do nothing inside the 10-minute commit confirmed window |
| Cold sync stuck at `CS RTO sync 0 of 1` after the first pushes; a BACKUP reboot alone did not clear it | Ask before each restart; BACKUP first; then the ACTIVE; never restart a node whose newest commit shows `rollback pending` (the reboot rolls the push back) |
| Secrets in profile bodies leak into files, logs and read-back dumps | Fill them in memory at write time; `redact()` before saving or showing; a license key is bound to one serial: each node gets only its own key, no line for a node without one |
| Saving a profile in the Mist UI editor adds default keys, so it no longer equals the file | Create and maintain the profiles by API; compare the read-back with the plan |
| Hub path or MAC mismatch: the spoke `vpn_paths` key and `path_preferences` use `<path>.<VPN>`; the DPD lines must name the Mist-generated IKE gateway `wan_to_<hub MAC>_<hub WAN port name>` | Read the paths from `GET /orgs/{org_id}/vpns?limit=1000`; take each hub MAC from the hub device's inventory `mac`; after the assign check `config_cmd` (SKILL.md step 4.5) |
| A hub overlay import filter that does not accept the overlay networks' subnets drops their routes at the hub | The user confirms the hub import accepts them (intake H6) |
| The host name renders from the Mist device name | The user names both nodes in Mist before power-on; the skill only reads the name and shows the rendered `set system host-name` line |
| A device record with `disable_auto_config` true gets no push from Mist (in this design a true-to-false change forced a push); a never-connected gateway record can lack the key | Require `disable_auto_config` absent or false and `mist_configured` true before the assign and at the hand-off (`check_device_record()`) |
| SRX firmware auto-upgrade on first onboarding (`juniper_srx.auto_upgrade`, org or site setting) upgrades the gateway when it first connects | `check_site_settings()` at SKILL.md step 2.4: off, or pinned to the B4 release for SRX400 |
| `urllib` forwards the Authorization header on a redirect to any host | The client follows no redirect and sends only to the portal's API host |
| A list read can be paged in a large org (more than 1000 networks, gateways or profiles): a serial, the hub record or a clash can be missed | Read every list with `list_all()`: `limit=1000` (Mist sends `X-Page-Total` only then), then `&page=2`, `&page=3`, ... until the unique ids read equal `X-Page-Total`; show the row count and the total; stop only when `list_all()` reports the list incomplete |
| Other gateway profiles in the org carry their own secrets (PSKs, keys, hashes) | Print and save only `profile_summary()` of profiles this skill did not create |
