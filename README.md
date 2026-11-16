# SRX400 MNHA Zero-Touch Onboarding with Juniper Mist

**Eric Sandoval**, Network Security Architect, HPE

Zero-touch onboarding of an SRX400 MNHA pair into Juniper Mist, on Junos OS Evolved 25.4X300-D30.3: both nodes go from their factory-default state to their own Hub Profile with nothing typed on either box. The paper, the files, and an agent skill that builds the Mist side for you.

| File | What it is |
|---|---|
| [docs/SRX400-MNHA-Zero-Touch-Mist.pdf](docs/SRX400-MNHA-Zero-Touch-Mist.pdf) | The paper: how zero touch works, what must be ready before the boxes ship, the Hub Profiles, measured onboarding, verification and deployment steps |
| [mist/srx400-node1-zero-touch.json](mist/srx400-node1-zero-touch.json), [mist/srx400-node2-zero-touch.json](mist/srx400-node2-zero-touch.json) | Mist Hub Profiles for SRX400 node 1 and node 2 (Organization > WAN > Hub Profiles > Import Profile) |
| [junos/srx400-node1-zero-touch.set](junos/srx400-node1-zero-touch.set), [junos/srx400-node2-zero-touch.set](junos/srx400-node2-zero-touch.set) | Each node's configuration after zero-touch onboarding, in `display set` form |
| [skills/srx400-zero-touch-mist/](skills/srx400-zero-touch-mist/) | Agent skill for an LLM agent: it asks for every value the build needs, builds the org objects and both Hub Profiles through the Mist API with your approval at each write, assigns them, then follows the onboarding and the checks of paper section 6 |
| [docs/Agent-Skill-Overview.pdf](docs/Agent-Skill-Overview.pdf) | One-page overview of the agent skill: what it asks, checks, builds, watches and verifies, the Mist API traps it avoids, and what is proven |

Values in angle brackets (`<...>`) are placeholders; `<*_to_*>` is a Junos wildcard and stays as is. Before use, replace the placeholders and node 1's example IPv6 /60 `2001:db8:2000::/60`, and change the hub path `HUB-wan.OrgOverlay` and the hub site prefix `10.200.0.0/16` if yours differ (paper sections 7 and 8). Prerequisite: a Mist hub on the OrgOverlay VPN (paper section 7, step 1). Without an agent, follow paper section 7, steps 1 to 16.

## Use the agent skill

1. Clone this repository.
2. In Mist, create an API token (person icon > My Account > API Token > Create Token) on an account that is admin of the org. Save it to a local file with mode 600, for example `~/mist-api-token`. The agent reads it from that file; never paste it into the chat.
3. Give your LLM agent the skill: point it at [skills/srx400-zero-touch-mist/SKILL.md](skills/srx400-zero-touch-mist/SKILL.md), or copy the folder into your agent's skills folder. The agent needs a shell with Python 3.
4. Ask it to prepare the zero-touch SRX400 pair for your site. It asks for your Mist cloud, org, site, both serials, the per-node values and the hub details, checks them against your org with read-only calls, shows the plan, and creates nothing without your yes.

The branch design itself (MNHA, per-tenant ISP steering, DHCP with Active Leasequery, the IPsec overlay) is in the companion repository [srx400-mnha-mist-branch](https://github.com/SandmanJnpr/srx400-mnha-mist-branch).

> Reference design by the author, not an official Juniper Networks or HPE position. Verify every line in your own environment before use.
