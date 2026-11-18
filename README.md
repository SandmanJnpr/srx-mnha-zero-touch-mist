# SRX400 MNHA Zero-Touch Onboarding with Juniper Mist

**Eric Sandoval**, Network Security Architect, HPE

Zero-touch onboarding of an SRX400 MNHA pair into Juniper Mist, on Junos OS Evolved 25.4X300-D30.3: both nodes go from their factory-default state to their own Hub Profile with nothing typed on either box. The paper and the files.

| File | What it is |
|---|---|
| [docs/SRX400-MNHA-Zero-Touch-Mist.pdf](docs/SRX400-MNHA-Zero-Touch-Mist.pdf) | The paper: how zero touch works, what must be ready before the boxes ship, the Hub Profiles, measured onboarding, verification and deployment steps |
| [mist/srx400-node1-zero-touch.json](mist/srx400-node1-zero-touch.json), [mist/srx400-node2-zero-touch.json](mist/srx400-node2-zero-touch.json) | Mist Hub Profiles for SRX400 node 1 and node 2 (Organization > WAN > Hub Profiles > Import Profile) |
| [mist/org-objects.json](mist/org-objects.json) | The seven org networks and the application HUB-SITE-NETS, as Mist API request bodies in create order (paper section 7, steps 2 and 3) |
| [junos/srx400-node1-zero-touch.set](junos/srx400-node1-zero-touch.set), [junos/srx400-node2-zero-touch.set](junos/srx400-node2-zero-touch.set) | Each node's configuration after zero-touch onboarding, in `display set` form |
| [docs/QR-vs-SZTP.pdf](docs/QR-vs-SZTP.pdf) | One-page comparison: the QR code (the claim) and SZTP (the secure bootstrap) are two different jobs in the same onboarding flow |

Values in angle brackets (`<...>`) are placeholders; `<*_to_*>` is a Junos wildcard and stays as is. Before use, replace the placeholders and node 1's example IPv6 /60 `2001:db8:2000::/60`, and change the hub path `HUB-wan.OrgOverlay` and the hub site prefix `10.200.0.0/16` if yours differ (paper sections 7 and 8). Prerequisite: a Mist hub on the OrgOverlay VPN (paper section 7, step 1). Then follow paper section 7, steps 1 to 16.

The branch design itself (MNHA, per-tenant ISP steering, DHCP with Active Leasequery, the IPsec overlay) is in the companion repository [srx400-mnha-mist-branch](https://github.com/SandmanJnpr/srx400-mnha-mist-branch).

> Reference design by the author, not an official Juniper Networks or HPE position. Verify every line in your own environment before use.
