[Русский](README.md) | [English](README.en.md) | [Español](README.es.md) | [简体中文](README.zh-CN.md)

# VPN Gateway

VPN Gateway es una puerta de enlace Linux autohospedada para enrutar de forma selectiva el tráfico de una red local por VPN. Integra `dnsmasq`, `ipset`, reglas de encaminamiento, una API HTTPS y una consola web.

Los dos backends externos son mutuamente excluyentes:

- AmneziaWG mediante la interfaz `amn0`.
- XRay VLESS o Shadowsocks mediante la interfaz TUN `xray0`.

Un túnel OpenVPN opcional puede proporcionar acceso independiente a redes privadas remotas sin instalar una ruta predeterminada.

## Funciones

- Modos split, todo por VPN y todo directo.
- Categorías de dominios que alimentan el `ipset` `vpn_domains`.
- Selección entre AmneziaWG y XRay sin mezclar sus rutas.
- Configuraciones VLESS, Shadowsocks estándar, Shadowsocks de Outline y suscripciones XRay.
- Pruebas independientes de latencia y descarga que no activan la configuración examinada.
- Túnel lateral OpenVPN para rutas privadas anunciadas por el servidor.
- API FastAPI, consola web HTTPS y cliente Flutter opcional.
- Servicios y temporizadores systemd para rutas, salud, listas IP y estadísticas.

## Arquitectura

```text
Clientes LAN
    |
    +-- DNS --> dnsmasq --> direcciones añadidas a vpn_domains
    |
    +-- tráfico normal ---------------------------> router ISP
    |
    +-- destino en vpn_domains --> marca --> tabla 100
                                             |
                                             +-- amn0, o
                                             +-- xray0

Redes privadas remotas <-------------------- tun0 (OpenVPN opcional)
```

Los sockets que conectan XRay con el proveedor usan una marca de bypass y la interfaz física. Así se evita que la propia conexión del proveedor entre otra vez en `xray0`.

## Requisitos

- Debian 12, Ubuntu 24.04 o una distribución de la familia Fedora/RHEL con systemd.
- Acceso root y una dirección LAN estática.
- Compatibilidad con `iptables`, `ipset` y `dnsmasq`.
- Módulo AmneziaWG en el kernel si se usa ese backend. En un contenedor, el módulo debe instalarse y cargarse en el host.
- Al menos una configuración AmneziaWG o XRay.
- Go 1.25.12 o posterior para compilar el helper Shadowsocks de Outline.
- Flutter 3.41.9 o posterior para compilar el cliente móvil opcional.

El instalador modifica DNS, forwarding, unidades systemd y rutas. Utilice acceso por consola y prepare una copia de seguridad antes de ejecutarlo sobre una máquina existente.

## Instalación

### Paquetes de GitHub Release

Descargue `SHA256SUMS` y el artefacto adecuado desde Releases y compruebe su integridad:

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

La instalación de DEB/RPM solo copia el payload. No activa servicios ni cambia DNS o rutas; esas acciones comienzan únicamente al ejecutar `vpngateway-install`. Antes de usar RPM en producción, valide la distribución concreta con acceso por consola y revise SELinux y firewalld.

El archivo portable no requiere Git:

```bash
tar -xzf vpngateway-<VERSION>-linux.tar.gz
cd vpngateway-<VERSION>
cp config/vpngateway.conf.example config/vpngateway.conf
sudoedit config/vpngateway.conf
sudo ./install.sh
```

### Instalación desde el código fuente

```bash
git clone https://github.com/shurrman/vpngateway.git
cd vpngateway
cp config/vpngateway.conf.example config/vpngateway.conf
sudoedit config/vpngateway.conf
```

Configure como mínimo:

```bash
GATEWAY_IP=192.168.50.2
GATEWAY_HOSTNAME=gateway.lan
LAN_SUBNET=192.168.50.0/24
LAN_GATEWAY=192.168.50.1
LAN_INTERFACE=eth0
DNS_UPSTREAM="8.8.8.8 8.8.4.4"
API_ALLOWED_SUBNETS="192.168.50.0/24,127.0.0.0/8"
```

Después revise el archivo completo y ejecute:

```bash
sudo ./install.sh
```

El instalador crea `/opt/vpngateway`, instala dependencias y XRay, genera una CA local y un certificado HTTPS, configura `dnsmasq`, instala las unidades systemd e inicia la API.

Abra la consola en:

```text
https://gateway.lan/
```

Instale en los dispositivos administrativos la CA disponible en `https://gateway.lan/static/ca.crt`, o use un certificado HTTPS de confianza pública.

## Configuración del router

Para los clientes que deban usar la puerta de enlace automáticamente, configure DHCP con:

- Puerta de enlace predeterminada: `192.168.50.2`.
- Servidor DNS: `192.168.50.2`.

Mantenga acceso al router original durante las pruebas. Compruebe DNS, tráfico directo y tráfico de dominios VPN antes de migrar todos los dispositivos.

## AmneziaWG

Las configuraciones `.conf` contienen secretos y nunca se guardan en Git. Se pueden cargar desde la consola web o instalar manualmente:

```bash
sudo install -d -m 700 /opt/vpngateway/config/configs
sudo install -m 600 proveedor.conf /opt/vpngateway/config/configs/proveedor.conf
echo proveedor | sudo tee /opt/vpngateway/config/configs/.active
```

Para adaptar un archivo del proveedor:

```bash
python3 scripts/vpngw-adapt-amneziawg.py proveedor.conf adaptado.conf
```

La configuración adaptada usa `Table = off`; VPN Gateway administra las rutas y los hooks.

## Cliente XRay

El backend XRay acepta enlaces `vless://`, enlaces `ss://`, configuraciones JSON y suscripciones con nodos VLESS o Shadowsocks. Use el botón `+` del panel XRay para añadir una configuración o suscripción.

Al actualizar una suscripción se sustituyen únicamente sus nodos generados y se eliminan los que ya no aparecen. Las configuraciones independientes no se modifican. Las pruebas de ping y descarga emplean rutas temporales independientes y no cambian el túnel activo.

## Túnel OpenVPN opcional

```bash
sudo install -d -m 700 /opt/vpngateway/config/openvpn
sudo install -m 600 remoto.ovpn /opt/vpngateway/config/openvpn/remoto.ovpn
echo remoto | sudo tee /opt/vpngateway/config/openvpn/.active
sudo systemctl enable --now vpngw-openvpn
```

El wrapper rechaza rutas predeterminadas y DNS enviados por el servidor. Verifique que el servidor anuncie únicamente las redes privadas previstas.

## Dominios

Las categorías están en `config/domains/*.lst`. Cada línea no comentada es un sufijo de dominio. Después de editarlas en una instalación:

```bash
sudo /opt/vpngateway/scripts/vpngw-update-domains.sh
sudo dnsmasq --test
sudo systemctl restart dnsmasq
```

DNS-over-HTTPS en los clientes evita el DNS de la puerta de enlace e impide que `dnsmasq` rellene el ipset dinámicamente.

## Compilación y comprobación

```bash
python3 -m compileall -q api scripts
bash -n install.sh scripts/*.sh
go test ./...
go run golang.org/x/vuln/cmd/govulncheck@v1.6.0 ./...
go build ./cmd/vpngw-outline-ss-local
```

Cliente Flutter opcional:

```bash
cd mobile
flutter pub get
flutter analyze
flutter test
flutter build apk --release
```

La aplicación pública utiliza el almacén de confianza del sistema operativo. Instale la CA de la puerta de enlace en el dispositivo si utiliza un certificado autofirmado.

## Verificación operativa

```bash
systemctl status vpngw-api vpngw-external-tunnel vpngw-routing dnsmasq
ip rule list
ip route show table 100
ipset list vpn_domains
curl -k https://127.0.0.1/api/v1/health
```

No reinicie ni cambie un túnel activo durante una prueba si no puede aceptar una interrupción. Antes de actualizar, haga copia de `/opt/vpngateway`, de las unidades systemd afectadas y del estado de encaminamiento.

## Seguridad

- No guarde en Git perfiles VPN, claves, URLs de suscripción, UUID, contraseñas, `.env` ni certificados generados.
- Limite la API con `API_ALLOWED_SUBNETS` y un firewall.
- Use modo `700` para directorios de configuración y `600` para secretos.
- Revise las rutas y reglas de firewall antes de activar el modo todo por VPN.

## Licencia

VPN Gateway se distribuye bajo la [Licencia MIT](LICENSE).
