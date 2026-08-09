[Русский](README.md) | [English](README.en.md) | [Español](README.es.md) | [简体中文](README.zh-CN.md)

# VPN Gateway

VPN Gateway - самостоятельно разворачиваемый Linux-шлюз для выборочной маршрутизации трафика локальной сети через VPN. Он объединяет DNS-based split tunneling, policy routing, веб-консоль администратора и два взаимозаменяемых внешних VPN-backend:

- AmneziaWG через интерфейс `amn0`.
- XRay VLESS или Shadowsocks через TUN-интерфейс `xray0`.

Дополнительный OpenVPN side-tunnel может использоваться для маршрутов в удалённые приватные сети, не становясь default route. Одновременно активен только один внешний интернет-туннель; при смене backend обновляется policy routing, а OpenVPN остаётся независимым.

## Возможности

- Режимы split, весь трафик через VPN и весь трафик напрямую.
- Категории доменов, адреса которых `dnsmasq` добавляет в общий `ipset`.
- Взаимоисключаемые внешние туннели AmneziaWG и XRay.
- VLESS, стандартный Shadowsocks, Outline Shadowsocks и XRay-подписки.
- Независимые ping и download-тесты, не переключающие активный туннель.
- Опциональный OpenVPN side-tunnel для приватных маршрутов, отправленных сервером.
- HTTPS API на FastAPI и браузерная консоль управления.
- Опциональный мобильный клиент на Flutter.
- systemd-сервисы и таймеры для маршрутизации, health-check, обновления IP-списков и статистики.
- Опциональный публичный XRay VLESS+XHTTP inbound за nginx.

## Архитектура

```text
Клиенты LAN
    |
    +-- DNS --> dnsmasq --> IP доменов добавляются в ipset vpn_domains
    |
    +-- обычный трафик --------------------------> роутер провайдера
    |
    +-- назначения из vpn_domains --> fwmark --> таблица маршрутов 100
                                                   |
                                                   +-- amn0 (AmneziaWG), или
                                                   +-- xray0 (XRay TUN)

Удалённые приватные сети <----------------------- tun0 (OpenVPN)
```

Сокеты, которыми XRay подключается к провайдеру, получают отдельную bypass-mark и привязываются к физическому LAN-интерфейсу. Это не позволяет соединению с провайдером зациклиться через `xray0`.

## Требования

- Отдельная машина, VM или контейнер с Debian 12, Ubuntu 24.04 либо системой семейства Fedora/RHEL с systemd.
- Root-доступ и systemd.
- Статический LAN-адрес шлюза.
- Поддержка `iptables`, `ipset` и `dnsmasq`.
- Модуль AmneziaWG в ядре при использовании Amnezia backend. В непривилегированном контейнере модуль должен быть установлен и загружен на хосте.
- Хотя бы один конфиг AmneziaWG либо XRay VLESS/Shadowsocks.
- Go 1.25.12 или новее только для локальной сборки Outline Shadowsocks helper.
- Flutter 3.41.9 или новее только для сборки опционального мобильного клиента.

Не устанавливайте проект на удалённый production-шлюз без консольного доступа и проверенного плана отката. Установщик меняет DNS, forwarding, systemd units и сервисы маршрутизации.

## Установка

### Пакеты из GitHub Release

Скачайте `SHA256SUMS` и подходящий файл из Releases, затем проверьте checksum:

```bash
sha256sum -c SHA256SUMS
```

DEB:

```bash
sudo apt install ./vpngateway_<VERSION>_all.deb
sudo cp -n /etc/vpngateway/vpngateway.conf.example /etc/vpngateway/vpngateway.conf
sudoedit /etc/vpngateway/vpngateway.conf
sudo vpngateway-install
```

RPM:

```bash
sudo dnf install ./vpngateway-<VERSION>-1.noarch.rpm
sudo cp -n /etc/vpngateway/vpngateway.conf.example /etc/vpngateway/vpngateway.conf
sudoedit /etc/vpngateway/vpngateway.conf
sudo vpngateway-install
```

Установка DEB/RPM только размещает payload. Она не включает сервисы и не меняет DNS или маршруты: эти действия начинаются после явного запуска `vpngateway-install`. RPM-путь сначала проверяйте с консольным доступом на конкретном дистрибутиве, включая его SELinux/firewalld policy.

Переносимый архив не требует Git:

```bash
tar -xzf vpngateway-<VERSION>-linux.tar.gz
cd vpngateway-<VERSION>
cp config/vpngateway.conf.example config/vpngateway.conf
sudoedit config/vpngateway.conf
sudo ./install.sh
```

### Установка из исходников

Клонируйте репозиторий и создайте локальную конфигурацию:

```bash
git clone https://github.com/shurrman/vpngateway.git
cd vpngateway
cp config/vpngateway.conf.example config/vpngateway.conf
sudoedit config/vpngateway.conf
```

Как минимум задайте адрес шлюза, LAN-подсеть, LAN-роутер и физический интерфейс:

```bash
GATEWAY_IP=192.168.50.2
GATEWAY_HOSTNAME=gateway.lan
LAN_SUBNET=192.168.50.0/24
LAN_GATEWAY=192.168.50.1
LAN_INTERFACE=eth0
DNS_UPSTREAM="8.8.8.8 8.8.4.4"
API_ALLOWED_SUBNETS="192.168.50.0/24,127.0.0.0/8"
```

Перед установкой проверьте весь файл, затем выполните:

```bash
sudo ./install.sh
```

Установщик:

1. Устанавливает необходимые пакеты через `apt-get`, `dnf` или `yum`.
2. Создаёт `/opt/vpngateway`.
3. Устанавливает XRay и при необходимости собирает Outline Shadowsocks helper.
4. Генерирует локальный CA и HTTPS-сертификат сервера.
5. Создаёт конфигурацию `dnsmasq` из `config/vpngateway.conf`.
6. Устанавливает и включает systemd-сервисы.
7. Запускает API и консоль администратора.

После установки откройте:

```text
https://gateway.lan/
```

Установите сгенерированный CA из `https://gateway.lan/static/ca.crt` на устройства администратора либо используйте для HTTPS сертификат, которому эти устройства уже доверяют.

## Настройка роутера

Для устройств, которые должны автоматически использовать VPN Gateway, задайте в DHCP на LAN-роутере:

- Default gateway: адрес VPN Gateway, например `192.168.50.2`.
- DNS server: тот же адрес VPN Gateway.

Во время проверки сохраняйте административный доступ к исходному роутеру. Проверьте прямую маршрутизацию, маршрутизацию VPN-доменов и DNS до перевода всех клиентов.

## Конфигурация AmneziaWG

Конфиги AmneziaWG являются runtime-секретами и никогда не хранятся в Git. Загрузите INI-файл `.conf` через веб-консоль либо установите его вручную:

```bash
sudo install -d -m 700 /opt/vpngateway/config/configs
sudo install -m 600 my-provider.conf /opt/vpngateway/config/configs/provider.conf
echo provider | sudo tee /opt/vpngateway/config/configs/.active
```

Перед установкой провайдерский файл можно адаптировать:

```bash
python3 scripts/vpngw-adapt-amneziawg.py my-provider.conf provider.conf
```

Адаптированный конфиг использует `Table = off`; policy routing и необходимые route hooks создаёт VPN Gateway.

## Конфигурация XRay Client

Внешний XRay backend принимает:

- Share-ссылки `vless://`.
- Shadowsocks-ссылки `ss://`.
- XRay JSON outbound-конфигурации.
- URL подписок провайдера, содержащих поддерживаемые VLESS или Shadowsocks nodes.

Используйте кнопку `+` в панели XRay, чтобы загрузить standalone-конфиг или добавить подписку. Обновление подписки заменяет созданные из неё nodes и удаляет отсутствующие в новом ответе провайдера. Standalone-конфиги при этом не изменяются.

Ping и hard download tests используют независимые временные пути. Они не активируют проверяемый конфиг и не меняют выбранный внешний туннель.

## OpenVPN Side Tunnel

OpenVPN-профили являются runtime-секретами и хранятся в `/opt/vpngateway/config/openvpn`. Wrapper запрещает полученные от сервера default routes и изменения DNS, принимая только маршруты к приватным сетям.

```bash
sudo install -d -m 700 /opt/vpngateway/config/openvpn
sudo install -m 600 remote.ovpn /opt/vpngateway/config/openvpn/remote.ovpn
echo remote | sudo tee /opt/vpngateway/config/openvpn/.active
sudo systemctl enable --now vpngw-openvpn
```

Убедитесь, что сервер рекламирует только необходимые приватные сети.

## Маршрутизация доменов

Категории доменов находятся в `config/domains/*.lst`. Каждая строка без комментария задаёт доменный суффикс. `dnsmasq` разрешает соответствующие имена и добавляет полученные адреса в общий ipset `vpn_domains`.

После изменения категорий на установленном шлюзе:

```bash
sudo /opt/vpngateway/scripts/vpngw-update-domains.sh
sudo dnsmasq --test
sudo systemctl restart dnsmasq
```

Веб-консоль также поддерживает редактирование категорий и raw-файлов. DNS-over-HTTPS на клиентских устройствах обходит DNS шлюза и поэтому мешает наполнению ipset по доменным именам.

## Основные параметры

Важные настройки в `config/vpngateway.conf`:

| Параметр | Назначение |
|---|---|
| `GATEWAY_IP` | Статический LAN-адрес VPN Gateway |
| `GATEWAY_HOSTNAME` | HTTPS hostname и имя в сертификате |
| `LAN_SUBNET` | Локальная клиентская сеть |
| `LAN_GATEWAY` | Прямой next hop к ISP/роутеру |
| `LAN_INTERFACE` | Физический LAN-интерфейс |
| `VPN_INTERFACE` | AmneziaWG-интерфейс, обычно `amn0` |
| `XRAY_TUN_INTERFACE` | XRay TUN-интерфейс, обычно `xray0` |
| `XRAY_OUTBOUND_INTERFACE` | Физический интерфейс для provider sockets XRay |
| `DNS_UPSTREAM` | Upstream DNS, маршрутизируемые через выбранный внешний туннель |
| `DNS_LOCAL_ZONES` | Опциональные правила пересылки локальных DNS-зон |
| `DNS_LOCAL_HOSTS` | Опциональные статические локальные DNS-записи |
| `API_ALLOWED_SUBNETS` | Сети, которым разрешён доступ к API администратора |
| `FWMARK` | Метка для выбранных VPN-направлений |
| `XRAY_BYPASS_MARK` | Метка, удерживающая provider sockets вне `xray0` |

## Сборка и проверка

Проверка Python и shell-файлов:

```bash
python3 -m compileall -q api scripts
bash -n install.sh scripts/*.sh
```

Сборка и тест Outline Shadowsocks helper:

```bash
go test ./...
go run golang.org/x/vuln/cmd/govulncheck@v1.6.0 ./...
go build ./cmd/vpngw-outline-ss-local
```

Сборка опционального Flutter-клиента:

```bash
cd mobile
flutter pub get
flutter analyze
flutter test
flutter build apk --release
```

Публичная версия мобильного клиента использует системное хранилище доверенных сертификатов. Перед подключением к шлюзу с self-signed сертификатом установите CA шлюза на устройство.

## Эксплуатационные проверки

```bash
systemctl status vpngw-api vpngw-external-tunnel vpngw-routing dnsmasq
ip rule list
ip route show table 100
ipset list vpn_domains
curl -k https://127.0.0.1/api/v1/health
```

Не переключайте и не перезапускайте активный туннель во время проверки, если обрыв соединения недопустим. Перед обновлением установленного шлюза сделайте backup `/opt/vpngateway`, затрагиваемых systemd units и текущего routing state.

## Безопасность

- Никогда не коммитьте VPN-профили, private keys, URL подписок, UUID, пароли, `.env` и сгенерированные сертификаты.
- Ограничьте API администратора через `API_ALLOWED_SUBNETS` и firewall хоста.
- Используйте mode `700` для runtime-каталогов конфигурации и `600` для секретных файлов.
- Проверяйте созданные маршруты и firewall rules перед включением all-VPN режима.
- Считайте загруженные конфиги и данные подписок учётными данными.

## Лицензия

VPN Gateway распространяется по [лицензии MIT](LICENSE).
