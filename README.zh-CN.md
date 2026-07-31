[Русский](README.md) | [English](README.en.md) | [Español](README.es.md) | [简体中文](README.zh-CN.md)

# VPN Gateway

VPN Gateway 是一个自托管的 Linux 局域网 VPN 网关。它通过 `dnsmasq`、`ipset` 和策略路由，让指定域名经过 VPN，其余流量继续使用普通互联网出口，并提供 HTTPS 管理界面和 API。

外部互联网隧道支持两个互斥后端：

- 通过 `amn0` 接口使用 AmneziaWG。
- 通过 `xray0` TUN 接口使用 XRay VLESS 或 Shadowsocks。

还可以启用独立的 OpenVPN 侧隧道，仅访问远端私有网络，不接受远端服务器推送的默认路由。

## 功能

- 分流、全部走 VPN、全部直连三种路由模式。
- 按域名分类并动态填充 `vpn_domains` ipset。
- AmneziaWG 与 XRay 外部隧道互斥切换。
- 支持 VLESS、标准 Shadowsocks、Outline 前缀 Shadowsocks 和 XRay 订阅。
- 独立的延迟及下载测试，不会激活被测试配置，也不会切换当前隧道。
- 可选 OpenVPN 侧隧道，用于服务器推送的私有网段。
- FastAPI HTTPS API、浏览器管理界面和可选 Flutter 客户端。
- 使用 systemd 管理路由、健康检查、IP 列表更新和统计任务。

## 架构

```text
局域网客户端
    |
    +-- DNS --> dnsmasq --> 将解析结果加入 vpn_domains
    |
    +-- 普通流量 -------------------------------> ISP 路由器
    |
    +-- vpn_domains 目标 --> fwmark --> 路由表 100
                                           |
                                           +-- amn0，或
                                           +-- xray0

远端私有网络 <----------------------------- tun0（可选 OpenVPN）
```

XRay 到服务提供商的连接使用独立 bypass mark，并绑定物理网卡，从而避免提供商连接再次进入 `xray0` 形成路由环路。

## 系统要求

- Debian 12 或 Ubuntu 24.04，使用 systemd。
- root 权限和固定局域网地址。
- 内核支持 `iptables`、`ipset` 和 `dnsmasq`。
- 使用 AmneziaWG 时需要对应内核模块。在容器环境中，应在宿主机安装并加载该模块。
- 至少一个 AmneziaWG 或 XRay 配置。
- 编译 Outline Shadowsocks helper 时需要 Go 1.25.12 或更高版本。
- 编译可选移动客户端时需要 Flutter 3.41.9 或更高版本。

安装程序会修改 DNS、IP 转发、systemd 服务和路由。对现有远程服务器安装前，应确保拥有控制台访问和可执行的回滚方案。

## 安装

```bash
git clone https://github.com/shurrman/vpngateway.git
cd vpngateway
cp config/vpngateway.conf.example config/vpngateway.conf
sudoedit config/vpngateway.conf
```

至少需要设置以下参数：

```bash
GATEWAY_IP=192.168.50.2
GATEWAY_HOSTNAME=gateway.lan
LAN_SUBNET=192.168.50.0/24
LAN_GATEWAY=192.168.50.1
LAN_INTERFACE=eth0
DNS_UPSTREAM="8.8.8.8 8.8.4.4"
API_ALLOWED_SUBNETS="192.168.50.0/24,127.0.0.0/8"
```

检查完整配置后运行：

```bash
sudo ./install.sh
```

安装程序会创建 `/opt/vpngateway`，安装依赖和 XRay，生成本地 CA 与 HTTPS 证书，生成 `dnsmasq` 配置，安装 systemd 单元并启动 API。

安装完成后访问：

```text
https://gateway.lan/
```

请在管理设备上安装 `https://gateway.lan/static/ca.crt` 提供的 CA，或者为管理界面配置受设备信任的 HTTPS 证书。

## 路由器配置

若希望局域网设备自动使用 VPN Gateway，请在 DHCP 中设置：

- 默认网关：VPN Gateway 地址，例如 `192.168.50.2`。
- DNS 服务器：同一个 VPN Gateway 地址。

测试期间请保留对原路由器的管理访问。先验证 DNS、直连流量和 VPN 域名流量，再迁移全部客户端。

## AmneziaWG 配置

`.conf` 文件包含密钥，绝不能提交到 Git。可以通过网页界面上传，也可以手动安装：

```bash
sudo install -d -m 700 /opt/vpngateway/config/configs
sudo install -m 600 provider.conf /opt/vpngateway/config/configs/provider.conf
echo provider | sudo tee /opt/vpngateway/config/configs/.active
```

可先转换提供商配置：

```bash
python3 scripts/vpngw-adapt-amneziawg.py provider.conf adapted.conf
```

转换后的配置使用 `Table = off`，策略路由和 hooks 由 VPN Gateway 管理。

## XRay 客户端配置

XRay 后端支持 `vless://` 链接、`ss://` 链接、XRay JSON 配置，以及包含 VLESS 或 Shadowsocks 节点的订阅。使用 XRay 面板中的 `+` 添加独立配置或订阅。

订阅更新时，只会替换该订阅生成的节点，并删除提供商已经移除的节点；独立配置不会受影响。延迟和下载测试使用独立临时路径，不会改变当前活动隧道。

## 可选 OpenVPN 侧隧道

```bash
sudo install -d -m 700 /opt/vpngateway/config/openvpn
sudo install -m 600 remote.ovpn /opt/vpngateway/config/openvpn/remote.ovpn
echo remote | sudo tee /opt/vpngateway/config/openvpn/.active
sudo systemctl enable --now vpngw-openvpn
```

OpenVPN wrapper 会拒绝服务器推送的默认路由和 DNS，只接受目标私有网段。请确认服务器仅发布预期路由。

## 域名分流

域名分类文件位于 `config/domains/*.lst`。每个非注释行代表一个域名后缀。修改已安装网关上的分类后运行：

```bash
sudo /opt/vpngateway/scripts/vpngw-update-domains.sh
sudo dnsmasq --test
sudo systemctl restart dnsmasq
```

客户端启用 DNS-over-HTTPS 后会绕过网关 DNS，因此 `dnsmasq` 无法根据域名动态填充 ipset。

## 构建与检查

```bash
python3 -m compileall -q api scripts
bash -n install.sh scripts/*.sh
go test ./...
go run golang.org/x/vuln/cmd/govulncheck@v1.6.0 ./...
go build ./cmd/vpngw-outline-ss-local
```

构建可选 Flutter 客户端：

```bash
cd mobile
flutter pub get
flutter analyze
flutter test
flutter build apk --release
```

公开版本的移动客户端使用操作系统信任库。若网关使用自签名证书，请先在设备上安装网关 CA。

## 运行检查

```bash
systemctl status vpngw-api vpngw-external-tunnel vpngw-routing dnsmasq
ip rule list
ip route show table 100
ipset list vpn_domains
curl -k https://127.0.0.1/api/v1/health
```

如果不能接受连接中断，请勿在测试时切换或重启活动隧道。升级前应备份 `/opt/vpngateway`、相关 systemd 单元和当前路由状态。

## 安全建议

- 不要提交 VPN 配置、私钥、订阅 URL、UUID、密码、`.env` 或生成的证书。
- 使用 `API_ALLOWED_SUBNETS` 和主机防火墙限制管理 API。
- 配置目录使用 `700` 权限，秘密文件使用 `600` 权限。
- 启用全部走 VPN 模式前检查生成的路由和防火墙规则。

## 许可证

VPN Gateway 使用 [MIT 许可证](LICENSE)发布。
