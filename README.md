# SRX400 MNHA Zero-Touch Onboarding with Juniper Mist

**Eric Sandoval**, Network Security Architect, HPE

Zero-touch onboarding of an SRX400 MNHA pair into Juniper Mist, on Junos OS Evolved 25.4X300-D30.3: both nodes go from their factory-default state to their own Hub Profile with nothing typed on either box. The paper, the reference files, and an agent skill that asks about your proposed topology and builds the Mist side for you.

## Proven on SRX400 hardware

Both runs used an SRX400 pair on Junos OS Evolved 25.4X300-D30.3, and nothing was typed on either box:
- **The reference design of the paper:** both nodes went from factory default to their Hub Profiles and passed the verification of paper section 6. The reference files below are that design; with the paper's answers the agent skill builds exactly those objects.
- **The agent skill end to end:** an LLM agent with only this skill and a Mist API token took a second topology (four networks, the HA link and transit link ports swapped) from the intake questions to step 7 of the skill: both nodes onboarded, MNHA formed with cold sync COMPLETE, and every network reached its gateway and the Internet by its preferred ISP.

For other answers the skill builds from the same reference lines, names each part beyond the reference design in its plan before your yes, and verifies the pair after onboarding.

| File | What it is |
|---|---|
| [docs/SRX400-MNHA-Zero-Touch-Mist.pdf](docs/SRX400-MNHA-Zero-Touch-Mist.pdf) | The paper: how zero touch works, what must be ready before the boxes ship, the Hub Profiles, measured onboarding, verification and deployment steps |
| [mist/srx400-node1-zero-touch.json](mist/srx400-node1-zero-touch.json), [mist/srx400-node2-zero-touch.json](mist/srx400-node2-zero-touch.json) | Reference design output: the Mist Hub Profiles for SRX400 node 1 and node 2 with the paper's values, as the agent skill's generator writes them (Organization > WAN > Hub Profiles > Import Profile) |
| [mist/org-objects.json](mist/org-objects.json) | Reference design output: the seven org networks and the application HUB-SITE-NETS, as Mist API request bodies in create order (paper section 7, steps 2 and 3) |
| [junos/srx400-node1-zero-touch.set](junos/srx400-node1-zero-touch.set), [junos/srx400-node2-zero-touch.set](junos/srx400-node2-zero-touch.set) | Each node's configuration after zero-touch onboarding with the paper's values, in `display set` form |
| [skills/srx400-zero-touch-mist/](skills/srx400-zero-touch-mist/) | Agent skill for an LLM agent: it asks about your proposed topology and configuration, builds the org objects and one Hub Profile per SRX400 node from your answers through the Mist API with your approval at each write, assigns them to your serials, then follows the zero-touch onboarding and the checks of paper section 6 (what is proven on hardware: above) |
| [docs/QR-vs-SZTP.pdf](docs/QR-vs-SZTP.pdf) | One-page comparison: the QR code (the claim) and SZTP (the secure bootstrap) are two different jobs in the same onboarding flow |

The reference files carry the paper's design: six networks, the hub overlay on the OrgOverlay VPN, and IPv6 from ISP 1. Values in angle brackets (`<...>`) are placeholders; `<*_to_*>` is a Junos wildcard and stays as is. Without an agent, follow paper section 7, steps 1 to 16: replace the placeholders and node 1's example IPv6 /60 `2001:db8:2000::/60`, and change the hub path `HUB-wan.OrgOverlay` and the hub site prefix `10.200.0.0/16` if yours differ (paper sections 7 and 8); that path needs a Mist hub on the OrgOverlay VPN (paper section 7, step 1). With the agent skill, your answers take the place of the reference values.

## Use the agent skill

Prerequisites:
- An LLM agent with a shell (macOS or Linux) and Python 3.9 or later; the skill uses the standard library only.
- A Mist API token of an account that is admin of the org, or admin of its MSP (person icon > My Account > API Token > Create Token), saved in a local file with mode 600, for example `~/mist-api-token`. The agent reads it from that file; never paste it into the chat.
- Both SRX400 serials in the org inventory and assigned to the branch site, each with its name set in Mist; both nodes on Junos OS Evolved 25.4X300-D30.3 (a later 25.4X300 release also builds; an older one is refused) and in their factory-default state.
- Each node has its own ISP that hands it an address by DHCP on an untagged Ethernet port (an ISP router in front is fine); a static address, PPPoE, a tagged VLAN, a shared hand-off without a lease per node, or two WANs on one node is refused. After the first push the ISP either gives a new address at once or holds its address for 13 minutes or less (10 minutes is the proven value).
- A LAN switch with one LAG (LACP active, no force-up) or one plain port per firewall, every network VLAN on both firewalls' links; the HA link and transit link cabled straight between the firewalls; mgmt-0 unplugged until the agent asks for it.
- Mist free to push to that site: no push freeze or push window, the default 10-minute commit confirm timer, and SRX firmware auto-upgrade on first onboarding off (or pinned to the installed release), no device-level settings on the two device records; the agent checks these read-only.
- A Mist hub on a hub-and-spoke VPN in the same org, only if you want the branch networks to reach a hub site over the overlay.

Steps:
1. Clone this repository.
2. Give your LLM agent the skill: point it at [skills/srx400-zero-touch-mist/SKILL.md](skills/srx400-zero-touch-mist/SKILL.md) in the clone (the skill's tests and its pointers to the paper and the reference files read `../../`). If you copy the skill folder into your agent's skills folder, keep the clone: the agent asks for its path (intake N3) and reads the paper and the reference files from there. The agent keeps its working files (answers, plan, logs) in a folder of its own outside the clone.
3. Ask it to prepare the zero-touch SRX400 pair for your site. It asks about your proposed topology and configuration: the ports of each firewall, your ISPs and how they hand over the Internet, your networks (VLANs, subnets, gateways, DHCP, preferred ISP, Internet access, IPv6), the hub and overlay, DNS and NTP, management, and the internal addressing. It needs no drawing: it derives the rest, checks your answers against your org with read-only calls, and shows you the resulting topology and plan.
4. Once you confirm the plan, it creates the org objects and the two Hub Profiles, each write only after your yes, and assigns them to your serials (or, if you choose to import the profiles yourself at Organization > WAN > Hub Profiles > Import Profile, it checks each import and assignment). It then gives you the site hand-off list (cabling, LAN switch VLANs and LAGs, ISP DHCP), watches both nodes call home and take their configuration, and verifies them.

The branch design itself (MNHA, per-tenant ISP steering, DHCP with Active Leasequery, the IPsec overlay) is in the companion repository [srx400-mnha-mist-branch](https://github.com/SandmanJnpr/srx400-mnha-mist-branch).

> Reference design by the author, not an official Juniper Networks or HPE position. Verify every line in your own environment before use.
