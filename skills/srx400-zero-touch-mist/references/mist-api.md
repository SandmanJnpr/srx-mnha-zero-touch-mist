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
| `mist(method, path, body=None)` | One call; returns `(http_status, parsed JSON, or the text when the body is not JSON)`, an error body included; an empty body gives `{}`; no connection, a timeout or a dropped connection gives `(0, reason)` (after a write, status 0 means it may have landed: read back before any retry). The token is read from `mist.token_file` inside the call. A path that starts with `/api/v1` (a `next` link) has that prefix removed. Response headers go to `LAST_HEADERS` |
| `page_total()` | `X-Page-Total` of the last call, or `None` when Mist did not send it (Mist sends it only when the request carries `limit`). `None`, or larger than the rows read: the list is incomplete; stop and tell the user |
| `redact(o)` | Copy that is safe to show or save: drops `magic` (claim code); root hash, license key and every quoted `$...` string become placeholders, also inside raw JSON text (escaped quotes); values of keys ending in `psk`, `secret`, `password`, `passphrase`, `auth_key`, `community`, `community_name`, `token` or `key`, and the text after `pre-shared-key ascii-text`/`hexadecimal`, `authentication-key`, `secret` and `snmp ... community`, become `<SECRET>`. A redacted profile read-back carries the exact placeholder lines of the repository files, so it compares directly with the redacted plan |
| `profile_summary(p)` | The only fields of a device profile you print or save outside this skill's own plan and read-backs: `id`, `name`, `type`, `modified_time`, and per `port_config` entry its `name`, `usage` and `vpn_paths` keys |
| `safe_error(out, secrets=())` | An error body as safe text: every value in `secrets` masked (raw and JSON-escaped), then `redact()` on the decoded JSON, cut to 500 characters |
| `write(method, path, body, secrets=())` | One approved write. Prints only `{status, id, name}` (or `success` for the assign), never the object; returns the raw response for in-memory checks. On an error (status 0: no answer) it prints `safe_error()`; a profile create or update (`/orgs/{org_id}/deviceprofiles` or `.../deviceprofiles/{profile_id}`) without `secrets` prints only the error length. Pass the node's root hash and license key as `secrets` on every profile write |
| `read_secret(path, kind)` | Reads a root hash (`kind='root'`) or license key (`'license'`) file, stripped; raises without the value when it is not usable (intake D2, D3) |
| `fill(plan, root_hash, license_key)` | In-memory copy of a redacted plan profile with that node's secrets in place. Raises, naming only the placeholders, when any `<...>` other than `<*_to_*>` is left |
| `secret_check(profile, root_hash, license_key)`, `secret_check_pass(result, has_license)` | Booleans and counts only: placeholders left (every `<...>` other than `<*_to_*>`), root lines, root equal (a non-empty hash that starts with `$`), license lines, license equal. `secret_check_pass()` takes the result of `secret_check()`: `secret_check_pass(secret_check(body, root_hash, license_key), bool(license_key))` |

`python3 mist_api.py <path>` makes one GET and prints the status, `X-Page-Total` and the redacted
response; for `/self` only `scope`, `org_id`, `name` and `role` of each `privileges` entry and their
count; for a `/deviceprofiles` path only `profile_summary()` of each profile; for a `config_cmd` path
only its line count and `redact()` of `_errors`; for an error `safe_error()`.

Everything a command prints enters the agent's context: print only `redact()` output,
`profile_summary()`, `write()` summaries and `secret_check()` results. Never print a raw profile, a raw
`config_cmd`, a filled body or a secret file. Keep raw objects in memory; save only redacted copies.

Secrets live in one process. Read the secret files, fill, check, write, read back raw, `secret_check()`
and compare in ONE script run that prints only the `write()` summary, booleans and counts. Never pass a
filled body or a raw read-back between commands through a file; the UI path's `secrets/` files
(SKILL.md step 4) are the only filled copies on disk.

## 2. Read-back rules

| Object | Compare |
|---|---|
| Network | The record from `GET /orgs/{org_id}/networks?limit=1000` with that name, without `id`, `org_id`, `created_time`, `modified_time`, and without `zone_id` when Mist added it as `null`: equal to the POST body |
| Service | The record from `GET /orgs/{org_id}/services?limit=1000` with that name, without the four keys: equal to the POST body |
| Hub Profile | First, on the raw `GET /orgs/{org_id}/deviceprofiles/{profile_id}` held in memory: `secret_check()` passes (no placeholder left, the root line equals that node's hash file, the license line equals its key file or is absent). Then `redact()` it and remove the four keys: no key added, none missing, none changed, `additional_config_cmds` equal, compared with the redacted plan. The redacted compare alone cannot see a fill that failed |
| Assignment | `GET /sites/{site_id}/devices/{device_id}`: `deviceprofile_id` equals the profile id |
| VPN OrgOverlay (UI path only) | Each UI Import Profile also updates the VPN: `modified_time` changes, content does not. Compare the VPN without the four keys with the snapshot copy |

The same rule decides reuse: an existing object with a planned name that equals the planned body
after the same stripping is reused read-only; an existing Hub Profile only if, in addition,
`secret_check_pass()` is true on its raw GET against this node's secret files (the redacted compare
cannot see the secrets). Any other existing object with that name is a clash: stop.

## 3. Read-only calls

| Call | Purpose | Check |
|---|---|---|
| `GET /self` | Token and cloud check; list the orgs | Read only `privileges`: entries `{scope, org_id, name, role}`; the org must have scope `org`, role `admin`. Do not depend on the other top-level keys. 401 = almost always the wrong regional API host |
| `GET /orgs/{org_id}/inventory?type=gateway&limit=1000` | Serial to `mac`, `id` (device id), `site_id`, `deviceprofile_id`, `connected`, `model`, `name`; the hub device's `mac`; the count of connected gateways | Both serials present, `model` SRX400, same `site_id`, `connected` false; `name` read and shown (empty: not a stop here, required at SKILL.md steps 4.4 and 5); `deviceprofile_id` null, or the profile the user agreed to replace. Device id has the form `00000000-0000-0000-1000-<mac>`. Never show `magic` (claim code). A serial not found: show the user how many records you read and ask before you conclude it is absent |
| `GET /sites/{site_id}` | The branch site; its `timezone` | `gatewaytemplate_id` null |
| `GET /sites/{site_id}/setting` | Gateway auto-upgrade window | `auto_upgrade` enabled: show the window; power-on and the hour after it stay outside it |
| `GET /orgs/{org_id}/vpns?limit=1000` | OrgOverlay present; hub path name; snapshot | Shape `{"name":"OrgOverlay","type":"hub_spoke","paths":{"HUB-wan":{"bfd_profile":"broadband"}},"createdBy":"user"}`. Path key = `<hub profile name>-<hub WAN port name>`; spokes use `<path>.OrgOverlay`. On the API path its `modified_time` must not change; on the UI path compare it by content (section 2) |
| `GET /orgs/{org_id}/deviceprofiles?type=gateway&limit=1000` | Profile name clash; snapshot; find the hub profile | Always with `type=gateway`: without it the list holds no gateway profiles and a clash is missed. The list holds other profiles' secrets: print and save only `profile_summary()` of each (the fields of section 1, `profile_summary()`). Hub profile: the one whose `name` + `-` + the `name` of a `port_config` entry with `usage` `wan` equals the path key; never split the path key; that entry's `name` must be `wan` |
| `GET /orgs/{org_id}/deviceprofiles/{profile_id}` | Read back a created profile; read the hub profile | See read-back rules |
| `GET /orgs/{org_id}/networks?limit=1000` | Name clash (case-insensitive), snapshot, read-back | |
| `GET /orgs/{org_id}/services?limit=1000` | Name clash for HUB-SITE-NETS, snapshot, read-back | |
| `GET /sites/{site_id}/devices/{device_id}` | Management flags; assignment read-back; snapshot | `disable_auto_config` false and `mist_configured` true, as in this design; otherwise stop (the skill writes no device records). `deviceprofile_id`. No device-level overrides: an override is any key of the node's Hub Profile file other than `name` and `type`, plus `networks`: `port_config`, `ip_configs`, `dhcpd_config`, `path_preferences`, `service_policies`, `ospf_areas`, `bgp_config`, `routing_policies`, `gateway_mgmt`, `vrf_instances`, `tunnel_configs`, `oob_ip_config`, `ntp_servers`, `dns_servers`, `ospf_config`, `extra_routes`, `extra_routes6`, `additional_config_cmds`, `router_id`, `networks`; any present on the device record: stop (SKILL.md steps 2.3, 4.4 and 5 use this list). Ignore every other key (`name`, `mac`, `serial`, `notes`, `adopted`, `model`, `type`, `hw_rev`, `bundled_mac`, `map_id`, `tag_id` and the like) |
| `GET /sites/{site_id}/devices/{device_id}/config_cmd` | Render preview after assignment; the hub's overlay import (intake C4); later, compare with the box | `{cli:[...], _errors:[]}`, checks in SKILL.md step 4.5; the line count depends on the hub and the license line and is not checked. It holds the root hash: hold it in memory, print only the checks and the lines SKILL.md names. Not 200 with a `cli` list for a node that has never connected: report the status and ask the user (SKILL.md step 4.5) |
| `GET /sites/{site_id}/stats/devices/{device_id}` | Watch every 20 s; snapshot `status`, `config_version` | `status` (connected, disconnected, rebooting), `config_status` (NO_CHANGE, INPROGRESS, AWAITING_CONFIRM, COMMITED, FAILED), `config_version`, `version`, `uptime`, `ip`, `if_stat` (re0:mgmt-0.0, ge-0/0/4.0, ae0.0, ge-0/0/2.0), `deviceprofile_name`. Values lag: log them, do not gate on them. Record the HTTP status when it is not 200 |
| `GET /sites/{site_id}/stats/devices?type=gateway` | Both nodes' stats in one call | |
| `GET /sites/{site_id}/devices/events/search?mac=<mac>&start=<epoch>&limit=200` | Event timeline per node | `{start, end, limit, total, results[], next?}`; each result has `type`, `mac`, `timestamp`; `text` only on some types (the ZTP, GW_CONNECTED, GW_DISCONNECTED and GW_RESTART_BY_USER events have none): read it with `.get('text')`. Without `start` it returns total 0. Follow `next` until it is absent |
| `GET /orgs/{org_id}/logs?start=<T0 epoch>&limit=50` | Audit: nothing else touched the nodes | `{start, end, limit, total, results[], next?}`; follow `next`. Each result has `message`, `site_id`, `timestamp`, `admin_name`. Count only entries whose `site_id` is the branch site or whose `message` names a node MAC: after onboarding, only the approved restarts, each `device[<mac>] manually restarted` |

`<mac>` is 12 lowercase hex digits with no separators, as the inventory shows it.

## 4. Writes (each one needs the user's yes)

| Call | Body | Expect |
|---|---|---|
| `POST /orgs/{org_id}/networks` | One `org-objects.json` body (steps 1 to 7: MGMT, CORP, GUEST, MEDIA, SECURITY, IOT, ICD), one call each, in order | 200 and the stored object with `id`. Read-back = body plus `zone_id: null` |
| `POST /orgs/{org_id}/services` | `{"name":"HUB-SITE-NETS","type":"custom","addresses":["<hub site prefixes>"],"specs":[{"protocol":"any","port_range":"0"}]}` | 200 and the object with `id`. Read-back = body |
| `POST /orgs/{org_id}/deviceprofiles` | The whole profile file (it carries `name` and `"type":"gateway"`, no `id`), placeholders filled, secrets filled in memory only; `secret_check_pass()` true on the body before the call; `write(..., secrets=(root_hash, license_key))`; fill, POST and read-back in one script run (section 1) | 200 and the object with `id`. Read-back per section 2. Created unassigned |
| `POST /orgs/{org_id}/deviceprofiles/{profile_id}/assign` | `{"macs":["<node mac>"]}` | `{"success":["<node mac>"]}`. On a connected device this logs GW_CONFIG_CHANGED_BY_USER and Mist pushes 34 to 38 s later; in the drop-ship order the node is not yet powered on |
| `POST /sites/{site_id}/devices/{device_id}/restart` | `{}` | `{}`. GW_RESTART_BY_USER at once; node back on Mist 6 min 35 s to 6 min 40 s later; Mist re-pushes the same `config_version`; audit entry `device[<mac>] manually restarted` |

A created profile that needs a correction before power-on: take the raw
`GET /orgs/{org_id}/deviceprofiles/{profile_id}` held in memory (never a saved or redacted copy: those
carry placeholders and would wipe the secrets), change only the planned value, show the change
redacted, and with a yes `PUT /orgs/{org_id}/deviceprofiles/{profile_id}` with only the changed
top-level key and its whole value (for `additional_config_cmds`, the whole array, never `[]` or `null`).
When the body carries `additional_config_cmds`, `secret_check_pass()` is true on it before the PUT.
The raw GET, the change, the PUT (with `secrets=`) and the read-back run in one script, as for the
POST: never save the raw object or the PUT body to disk. Then read back per section 2.

## 5. Calls this skill never makes

- `PUT /sites/{site_id}/devices/{device_id}` with `{"deviceprofile_id": ...}`: it returns 200 and bumps `modified_time` but does not change the profile. Any device-record write (a `notes` PUT, a `disable_auto_config` toggle) made Mist re-push a connected gateway.
- Any DELETE, and any write to an object the skill did not create, unless the user asks for it.
- Writes to the hub, its profile or the VPN OrgOverlay: they are prerequisites the user owns.

## 6. Traps

| Trap | Avoid |
|---|---|
| Wrong regional API host: 401 with a valid token | Derive the host from the portal host; `GET /self` first |
| In this design, creating the org networks, the application and the two unassigned profiles made Mist re-render and push (commit confirmed) the assigned, connected gateways about 45 to 55 s later; the only change on them was the NTP server address | Treat any org-object create as a push to every gateway in the org. Tell the user, with the count of connected gateways, before the first org-object POST; a check seconds after the POST misses it, so look again after 2 minutes |
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
| A node that connects with no profile gets a different first push (site gateway template or the Mist default render). Moving a device to another site (unassign, then assign) gives it a new device record with `deviceprofile_id` null | Assign both profiles before power-on; site `gatewaytemplate_id` null; re-read both inventory records right before power-on; the user does not move, release or unassign the nodes after the assign |
| These profiles assigned over a pair running another MNHA configuration failed with GW_CONFIG_FAILED (`Configuration does not support multiple IPv4 addresses per virtual-ip entry without grid-id`); Mist does not delete chassis high-availability lines | Nodes start factory default on 25.4X300-D30.3 (`request system zeroize ztp-option secure-enable`); stop if a node is already connected with another configuration |
| Factory mgmt-0 has a static address and a DHCP server, and ZTP tries DHCP on mgmt-0 first | mgmt-0 unplugged until the node passes the push and cold sync checks |
| After the push the ISP DHCP server answers the new Junos DHCP client only once the ZTP lease expires; the node is off Mist about 3 minutes | Keep the three ge-0/0/2 DHCP client lines and a 10-minute ISP lease; do nothing inside the 10-minute commit confirmed window |
| Cold sync stuck at `CS RTO sync 0 of 1` after the first pushes; a BACKUP reboot alone did not clear it | Ask before each restart; BACKUP first; then the ACTIVE; never restart a node whose newest commit shows `rollback pending` (the reboot rolls the push back) |
| Secrets in profile bodies leak into files, logs and read-back dumps | Fill them in memory at write time; `redact()` before saving or showing; a license key is bound to one serial: each node gets only its own key, no line for a node without one |
| Saving a profile in the Mist UI editor adds default keys, so it no longer equals the file | Create and maintain the profiles by API; compare the read-back with the plan |
| Hub path or MAC mismatch: the spoke `vpn_paths` key and `path_preferences` use `<path>.OrgOverlay`; the DPD lines must name the Mist-generated IKE gateway | Read the path from `GET /orgs/{org_id}/vpns?limit=1000`; take `<hub-MAC>` from the hub device's inventory `mac`; after the assign check `config_cmd` (step 4.5) |
| A hub overlay import filter that does not accept the IOT subnet drops the IOT routes at the hub | The user confirms the hub import accepts 10.10.60.0/24 |
| The host name renders from the Mist device name | The user names both nodes in Mist before power-on; the skill only reads the name and shows the rendered `set system host-name` line |
| A device record with `disable_auto_config` true gets no push from Mist (in this design a true-to-false change forced a push) | Require `disable_auto_config` false and `mist_configured` true before the assign and at the hand-off |
| A list read can be paged in a large org: a serial, the hub record or a clash can be missed | Add `limit=1000` to every list read (Mist sends `X-Page-Total` only then); show the row count; stop when `page_total()` is None or larger |
| Other gateway profiles in the org carry their own secrets (PSKs, keys, hashes) | Print and save only `profile_summary()` of profiles this skill did not create |
