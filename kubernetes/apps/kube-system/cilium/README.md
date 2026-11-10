# Cilium

## UniFi BGP

The UDM Pro side of the BGP peering is an FRR config kept at the repo root and
hand-uploaded to the router; nothing in the repo applies it.

- [`bgp.conf`](../../../../bgp.conf) — IPv4 peering, and the file loaded on the UDM.
  It matches [`app/networks.yaml`](./app/networks.yaml): router `192.168.1.1`
  (ASN 64513) peering with the three nodes (ASN 64514).
- [`bgp-v6.conf`](../../../../bgp-v6.conf) — a variant that adds an IPv6 peer group.
  It has not been applied to the UDM. Cilium's side is IPv4 only (one IPv4 peer, an
  IPv4 address family and an IPv4 LoadBalancer pool in `app/networks.yaml`), so there
  is nothing for that peer group to receive.

Edit those files, not this one. This README used to carry its own copy of the config,
which drifted from them.
