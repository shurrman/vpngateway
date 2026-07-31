[Русский](README.md) | [English](README.en.md) | [Español](README.es.md) | [简体中文](README.zh-CN.md)

# VPN Gateway

VPN Gateway is a self-hosted Linux gateway for selective VPN routing on a local network. It combines DNS-based split tunneling, policy routing, a web administration console, and two interchangeable external VPN backends:

- AmneziaWG through an `amn0` interface.
- XRay VLESS or Shadowsocks through an `xray0` TUN interface.

An optional OpenVPN side tunnel can carry routes to private remote networks without becoming the default route. Only one external internet tunnel is active at a time; switching the backend updates policy routing while the OpenVPN side tunnel remains independent.

## Features

- Split, all-VPN, and all-direct routing modes.
- Domain categories populated into a shared `ipset` by `dnsmasq`.
- Mutually exclusive AmneziaWG and XRay external tunnels.
- VLESS, standard Shadowsocks, Outline-prefixed Shadowsocks, and XRay subscriptions.
- Independent ping and download tests that do not switch the active tunnel.
- Optional OpenVPN side tunnel for server-pushed private routes.
- FastAPI HTTPS API and a browser administration console.
- Optional Flutter administration client.
- systemd services and timers for routing, health checks, IP-list updates, and statistics.
- Optional public XRay VLESS+XHTTP inbound behind nginx.

## Architecture

```text
LAN clients
    |
    +-- DNS --> dnsmasq --> domain IPs added to vpn_domains ipset
    |
    +-- normal traffic ---------------------------> ISP router
    |
    +-- destinations in vpn_domains --> fwmark --> route table 100
                                                  |
                                                  +-- amn0 (AmneziaWG), or
                                                  +-- xray0 (XRay TUN)

Optional remote private networks <-------------- tun0 (OpenVPN)
```

XRay provider sockets use a separate bypass mark and the physical LAN interface. This prevents the provider connection from being routed back into `xray0`.

## Requirements

- A dedicated Debian 12 or Ubuntu 24.04 machine, VM, or container.
- Root access and systemd.
- A static LAN address for the gateway.
- `iptables`, `ipset`, and `dnsmasq` support.
- An AmneziaWG kernel module when using the Amnezia backend. In an unprivileged container, the module must be installed and loaded on the host.
- At least one AmneziaWG config or one XRay VLESS/Shadowsocks config.
- Go 1.25.12 or newer only when building the Outline Shadowsocks helper locally.
- Flutter 3.41.9 or newer only when building the optional mobile client.

Do not install this on a remote production gateway without console access and a rollback plan. The installer changes DNS, forwarding, systemd units, and routing services.

## Installation

Clone the repository and create a local configuration:

```bash
git clone https://github.com/shurrman/vpngateway.git
cd vpngateway
cp config/vpngateway.conf.example config/vpngateway.conf
sudoedit config/vpngateway.conf
```

At minimum, set the gateway address, LAN subnet, LAN router, and physical interface:

```bash
GATEWAY_IP=192.168.50.2
GATEWAY_HOSTNAME=gateway.lan
LAN_SUBNET=192.168.50.0/24
LAN_GATEWAY=192.168.50.1
LAN_INTERFACE=eth0
DNS_UPSTREAM="8.8.8.8 8.8.4.4"
API_ALLOWED_SUBNETS="192.168.50.0/24,127.0.0.0/8"
```

Review the complete file before installation. Then run:

```bash
sudo ./install.sh
```

The installer:

1. Installs required Debian packages.
2. Creates `/opt/vpngateway`.
3. Installs XRay and optionally builds the Outline Shadowsocks helper.
4. Generates a local CA and an HTTPS server certificate.
5. Generates `dnsmasq` configuration from `config/vpngateway.conf`.
6. Installs and enables the systemd services.
7. Starts the API and administration console.

After installation, open:

```text
https://gateway.lan/
```

Install the generated CA certificate from `https://gateway.lan/static/ca.crt` on administration devices, or terminate HTTPS with a certificate already trusted by those devices.

## Router Configuration

For devices that should use VPN Gateway automatically, configure DHCP on the LAN router with:

- Default gateway: the VPN Gateway address, for example `192.168.50.2`.
- DNS server: the same VPN Gateway address.

Keep administrative access to the original router while testing. Verify direct routing, VPN-domain routing, and DNS before changing every client.

## AmneziaWG Configuration

AmneziaWG configurations are runtime secrets and are never stored in Git. Upload an INI-style `.conf` file from the web console, or install one manually:

```bash
sudo install -d -m 700 /opt/vpngateway/config/configs
sudo install -m 600 my-provider.conf /opt/vpngateway/config/configs/provider.conf
echo provider | sudo tee /opt/vpngateway/config/configs/.active
```

Provider files can be adapted before installation:

```bash
python3 scripts/vpngw-adapt-amneziawg.py my-provider.conf provider.conf
```

The adapted config uses `Table = off`; VPN Gateway owns policy routing and adds the required route hooks.

## XRay Client Configuration

The XRay external backend accepts:

- `vless://` share links.
- `ss://` Shadowsocks links.
- XRay JSON outbound configurations.
- Provider subscription URLs containing supported VLESS or Shadowsocks nodes.

Use the `+` control in the XRay panel to upload a standalone config or add a subscription. Subscription refresh replaces generated nodes for that subscription and removes nodes no longer returned by the provider. Standalone configs are not affected.

Ping and hard-download tests use independent temporary test paths. They do not activate the tested config or change the selected external tunnel.

## OpenVPN Side Tunnel

OpenVPN profiles are runtime secrets under `/opt/vpngateway/config/openvpn`. The wrapper rejects pushed default routes and DNS changes. It accepts only private routes advertised by the server.

```bash
sudo install -d -m 700 /opt/vpngateway/config/openvpn
sudo install -m 600 remote.ovpn /opt/vpngateway/config/openvpn/remote.ovpn
echo remote | sudo tee /opt/vpngateway/config/openvpn/.active
sudo systemctl enable --now vpngw-openvpn
```

Confirm that the server advertises only the intended private networks.

## Domain Routing

Domain categories live in `config/domains/*.lst`. Each non-comment line is a domain suffix. `dnsmasq` resolves matching names and adds their addresses to the shared `vpn_domains` ipset.

After changing categories on an installed gateway:

```bash
sudo /opt/vpngateway/scripts/vpngw-update-domains.sh
sudo dnsmasq --test
sudo systemctl restart dnsmasq
```

The web console also supports category editing and raw-file editing. DNS-over-HTTPS on client devices bypasses gateway DNS and therefore prevents DNS-based ipset population.

## Configuration Reference

Important settings in `config/vpngateway.conf`:

| Setting | Purpose |
|---|---|
| `GATEWAY_IP` | Static LAN address of VPN Gateway |
| `GATEWAY_HOSTNAME` | HTTPS hostname and certificate name |
| `LAN_SUBNET` | Local client network |
| `LAN_GATEWAY` | Direct ISP/router next hop |
| `LAN_INTERFACE` | Physical LAN interface |
| `VPN_INTERFACE` | AmneziaWG interface, normally `amn0` |
| `XRAY_TUN_INTERFACE` | XRay TUN interface, normally `xray0` |
| `XRAY_OUTBOUND_INTERFACE` | Physical interface used by XRay provider sockets |
| `DNS_UPSTREAM` | Upstream resolvers routed through the selected external tunnel |
| `DNS_LOCAL_ZONES` | Optional local-zone forwarding rules |
| `DNS_LOCAL_HOSTS` | Optional static local DNS records |
| `API_ALLOWED_SUBNETS` | Networks allowed to access the administration API |
| `FWMARK` | Mark used for selected VPN destinations |
| `XRAY_BYPASS_MARK` | Mark used to keep XRay provider sockets outside `xray0` |

## Building and Validation

Validate Python and shell sources:

```bash
python3 -m compileall -q api scripts
bash -n install.sh scripts/*.sh
```

Build and test the Outline Shadowsocks helper:

```bash
go test ./...
go run golang.org/x/vuln/cmd/govulncheck@v1.6.0 ./...
go build ./cmd/vpngw-outline-ss-local
```

Build the optional Flutter client:

```bash
cd mobile
flutter pub get
flutter analyze
flutter test
flutter build apk --release
```

The public mobile source uses the operating-system trust store. Install the gateway CA on the device before connecting to a self-signed gateway.

## Operational Checks

```bash
systemctl status vpngw-api vpngw-external-tunnel vpngw-routing dnsmasq
ip rule list
ip route show table 100
ipset list vpn_domains
curl -k https://127.0.0.1/api/v1/health
```

Do not switch or restart an active tunnel during testing unless an interruption is acceptable. Back up `/opt/vpngateway`, relevant systemd units, and routing state before upgrading an installed gateway.

## Security

- Never commit VPN profiles, private keys, subscription URLs, UUIDs, passwords, `.env` files, or generated certificates.
- Restrict the administration API with `API_ALLOWED_SUBNETS` and a host firewall.
- Keep runtime configuration directories mode `700` and secret files mode `600`.
- Review generated routes and firewall rules before using all-VPN mode.
- Treat config uploads and subscription data as credentials.

## License

VPN Gateway is distributed under the [MIT License](LICENSE).
