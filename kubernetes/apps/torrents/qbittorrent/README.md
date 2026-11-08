# Unifi Firewall Configuration

**Setup VPN Interface with Policy-Based Routing:**

1.  _Set up WireGuard as the VPN client on my Unifi gateway._

2.  _Create a Policy-Based Route:_

    • Interface = VPN Tunnel

    • Killswitch = enabled

    • Source = vLAN Network

    • Destination = Any

**Custom Firewall and NAT Rules:**

3.  _Firewall Rule:_

    • Go to Policy Engine → Zones → Create Policy

    • Source Zone = External

           •   Any/IP/MAC/Region = Any

           •   Port = Any

    • Action = Allow (tick Auto Allow Return Traffic)

           •   Check the “Auto Allow Return Traffic” box

    • Destination Zone = DMZ

           •   Any/Network/IP = IP (Specific - Set this to the internal IP in the VPN vLAN/Zone)

           •   Port = Specific (Set this to the port you want to forward to)

    • Save the rule.

4.  NAT Rule (Destination NAT):

    • Go to Policy Engine → Policy Table → click “Create New Policy”

    • Type = Dest. NAT

           •   Interface/VPN Tunnel = VPN Tunnel

           •   Translated IP Address = Internal IP in the VPN vLAN/Zone

           •   Protocol = TCP/UDP (or either or)

    • Source = Any

           •   Port = Any

    • Destination = IP Set this to the internal IP address from the VPN tunnel (VPN IP Address Found in VPN/VPN Client/Tunnel IP 10.X.X.X).

           •   Port = Specific (Set this to the port you want to forward to)
