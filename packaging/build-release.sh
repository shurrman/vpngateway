#!/bin/bash
# Build tar.gz, DEB, and RPM release artifacts from the curated public tree.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-}"
VERSION="${VERSION#v}"
OUT_DIR="${2:-$ROOT/dist}"

api_version="$(sed -n 's/^API_VERSION = "\([^"]*\)"/\1/p' "$ROOT/api/config.py")"
if [[ -z "$VERSION" ]]; then
    VERSION="$api_version"
fi
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERROR: expected semantic version, got: $VERSION" >&2
    exit 2
fi
if [[ "$VERSION" != "$api_version" ]]; then
    echo "ERROR: release version $VERSION does not match API_VERSION $api_version" >&2
    exit 2
fi

for command in tar sha256sum dpkg-deb rpmbuild; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "ERROR: required build command not found: $command" >&2
        exit 3
    fi
done

SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "$ROOT" show -s --format=%ct HEAD 2>/dev/null || date +%s)}"
[[ "$SOURCE_DATE_EPOCH" =~ ^[0-9]+$ ]] || { echo "ERROR: invalid SOURCE_DATE_EPOCH" >&2; exit 3; }

tar_name="vpngateway-$VERSION-linux.tar.gz"
deb_name="vpngateway_${VERSION}_all.deb"
rpm_name="vpngateway-$VERSION-1.noarch.rpm"
for name in "$tar_name" "$deb_name" "$rpm_name" SHA256SUMS; do
    if [[ -e "$OUT_DIR/$name" ]]; then
        echo "ERROR: refusing to overwrite existing artifact: $OUT_DIR/$name" >&2
        exit 4
    fi
done

payload=(
    api cmd config go.mod go.sum install.sh LICENSE nginx
    README.md README.en.md README.es.md README.zh-CN.md scripts systemd
)

copy_payload() {
    local destination=$1 rel
    install -d -m 0755 "$destination"
    for rel in "${payload[@]}"; do
        [[ -e "$ROOT/$rel" ]] || { echo "ERROR: missing public payload: $rel" >&2; exit 5; }
        install -d -m 0755 "$destination/$(dirname "$rel")"
        cp -a "$ROOT/$rel" "$destination/$rel"
    done
    find "$destination" -type d -exec chmod 0755 {} +
    find "$destination" -type f -exec chmod 0644 {} +
    chmod 0755 "$destination/install.sh"
    find "$destination/scripts" -maxdepth 1 -type f \
        \( -name '*.sh' -o -name '*.py' \) -exec chmod 0755 {} +
}

normalize_times() {
    find "$1" -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} +
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
install -d -m 0755 "$OUT_DIR"

bundle="$tmp/vpngateway-$VERSION"
copy_payload "$bundle"
normalize_times "$bundle"
tar --sort=name --format=gnu --mtime="@$SOURCE_DATE_EPOCH" \
    --owner=0 --group=0 --numeric-owner \
    -C "$tmp" -czf "$OUT_DIR/$tar_name" "vpngateway-$VERSION"

pkgroot="$tmp/pkgroot"
copy_payload "$pkgroot/usr/lib/vpngateway"
install -D -m 0755 "$ROOT/packaging/vpngateway-install" "$pkgroot/usr/sbin/vpngateway-install"
install -D -m 0644 "$ROOT/config/vpngateway.conf.example" \
    "$pkgroot/etc/vpngateway/vpngateway.conf.example"
normalize_times "$pkgroot"

debroot="$tmp/debroot"
cp -a "$pkgroot" "$debroot"
install -d -m 0755 "$debroot/DEBIAN"
installed_size="$(du -sk "$pkgroot" | awk '{print $1}')"
cat > "$debroot/DEBIAN/control" <<EOF
Package: vpngateway
Version: $VERSION
Section: net
Priority: optional
Architecture: all
Installed-Size: $installed_size
Maintainer: VPN Gateway contributors
Depends: bash, ca-certificates, curl, dnsmasq, iproute2, ipset, iptables, openssl, python3, python3-pip, python3-venv, systemd, unzip
Homepage: https://github.com/shurrman/vpngateway
Description: Split-tunneling Linux VPN gateway
 Installs a versioned setup payload and an explicit installer command.
 Package installation does not enable services or alter networking.
EOF
normalize_times "$debroot"
dpkg-deb --root-owner-group --build "$debroot" "$OUT_DIR/$deb_name" >/dev/null

rpmtop="$tmp/rpmbuild"
install -d -m 0755 "$rpmtop"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
tar --sort=name --format=gnu --mtime="@$SOURCE_DATE_EPOCH" \
    --owner=0 --group=0 --numeric-owner \
    -C "$pkgroot" -czf "$rpmtop/SOURCES/vpngateway-payload.tar.gz" .
cat > "$rpmtop/SPECS/vpngateway.spec" <<EOF
Name:           vpngateway
Version:        $VERSION
Release:        1
Summary:        Split-tunneling Linux VPN gateway
License:        MIT
URL:            https://github.com/shurrman/vpngateway
BuildArch:      noarch
Source0:        vpngateway-payload.tar.gz
Requires:       bash, ca-certificates, curl, dnsmasq, iproute, ipset, iptables, openssl, python3, python3-pip, systemd, unzip

%description
Versioned setup payload for VPN Gateway. Package installation does not enable
services or alter networking; run vpngateway-install explicitly after review.

%prep
%build

%install
mkdir -p %{buildroot}
tar -xzf %{SOURCE0} -C %{buildroot}

%files
/usr/lib/vpngateway
/usr/sbin/vpngateway-install
%config(noreplace) /etc/vpngateway/vpngateway.conf.example

%post
echo "VPN Gateway payload installed. Configure /etc/vpngateway/vpngateway.conf and run vpngateway-install explicitly."
EOF
rpmbuild --define "_topdir $rpmtop" --define "_build_id_links none" \
    -bb "$rpmtop/SPECS/vpngateway.spec" >/dev/null
rpm_artifact="$(find "$rpmtop/RPMS" -type f -name '*.rpm' -print -quit)"
[[ -n "$rpm_artifact" ]] || { echo "ERROR: rpmbuild produced no package" >&2; exit 6; }
cp "$rpm_artifact" "$OUT_DIR/$rpm_name"

(
    cd "$OUT_DIR"
    sha256sum "$tar_name" "$deb_name" "$rpm_name" | sort -k2 > SHA256SUMS
)

printf 'Built release artifacts in %s\n' "$OUT_DIR"
printf '  %s\n' "$tar_name" "$deb_name" "$rpm_name" SHA256SUMS
