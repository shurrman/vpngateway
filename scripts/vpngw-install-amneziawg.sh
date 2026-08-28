#!/usr/bin/env bash
set -Eeuo pipefail

TOOLS_TAG="${AWG_TOOLS_TAG:-v3.1.20260812}"
MODULE_TAG="${AWG_MODULE_TAG:-v3.1.20260827}"
TOOLS_REPO="${AWG_TOOLS_REPO:-https://github.com/amnezia-vpn/amneziawg-tools.git}"
MODULE_REPO="${AWG_MODULE_REPO:-https://github.com/amnezia-vpn/amneziawg-linux-kernel-module.git}"
BACKUP_ROOT="${AWG_BACKUP_ROOT:-/opt/vpngateway-backups}"
STATE_FILE="${AWG_STATE_FILE:-/var/lib/vpngateway/amneziawg-build.env}"

MODE="all"
RELOAD_MODULE=0
INSTALL_PACKAGES=1
BUILD_ROOT=""
BACKUP_DIR=""
MANIFEST=""
OLD_MODULE_PATH=""
NEW_MODULE_PATH=""

usage() {
    cat <<EOF
Usage: $0 [all|tools|module] [options]

Build and install pinned AmneziaWG 3.1 components from official sources.

Modes:
  all       Install userspace tools and the kernel module (default)
  tools     Install only awg and awg-quick; use this inside an LXC container
  module    Install only the kernel module; use this on the LXC host

Options:
  --reload-module  Reload amneziawg after installation. Refuses to run while
                   any AmneziaWG interface exists.
  --skip-packages  Do not install build dependencies or matching headers.
  -h, --help       Show this help.

Pinned sources:
  tools:  ${TOOLS_TAG}
  module: ${MODULE_TAG}

The script never starts or switches a VPN tunnel. A module reload is performed
only when explicitly requested and only when no AmneziaWG interface exists.
EOF
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

log() {
    printf '==> %s\n' "$*"
}

cleanup() {
    if [[ -n "$BUILD_ROOT" && -d "$BUILD_ROOT" ]]; then
        rm -rf -- "$BUILD_ROOT"
    fi
}
trap cleanup EXIT

while (($#)); do
    case "$1" in
        all|tools|module)
            MODE="$1"
            ;;
        --reload-module)
            RELOAD_MODULE=1
            ;;
        --skip-packages)
            INSTALL_PACKAGES=0
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown argument: $1"
            ;;
    esac
    shift
done

[[ $EUID -eq 0 ]] || die "run as root"

if [[ "$MODE" == "tools" && $RELOAD_MODULE -eq 1 ]]; then
    die "--reload-module is only valid for all or module mode"
fi

if [[ "$MODE" != "tools" ]] && command -v systemd-detect-virt >/dev/null 2>&1 \
    && systemd-detect-virt --container --quiet; then
    die "kernel module installation must run on the container host; use tools mode inside the container"
fi

active_awg_interfaces() {
    if command -v awg >/dev/null 2>&1; then
        awg show interfaces 2>/dev/null || true
    fi
}

if [[ $RELOAD_MODULE -eq 1 ]]; then
    ACTIVE_INTERFACES="$(active_awg_interfaces)"
    [[ -z "$ACTIVE_INTERFACES" ]] || die "refusing module reload while AmneziaWG interfaces exist: $ACTIVE_INTERFACES"
fi

KERNEL_RELEASE="$(uname -r)"
BUILD_ROOT="$(mktemp -d /tmp/vpngw-amneziawg.XXXXXX)"
BACKUP_DIR="${BACKUP_ROOT}/amneziawg-$(date +%Y%m%d-%H%M%S)"
MANIFEST="${BACKUP_DIR}/manifest.tsv"
install -d -m 700 "${BACKUP_DIR}/files"
: > "$MANIFEST"

backup_target() {
    local target="$1"
    local relative="${target#/}"

    if [[ -e "$target" || -L "$target" ]]; then
        install -d -m 700 "${BACKUP_DIR}/files/$(dirname "$relative")"
        cp -a -- "$target" "${BACKUP_DIR}/files/${relative}"
        printf 'present\t%s\t%s\n' "$relative" "$target" >> "$MANIFEST"
    else
        printf 'missing\t%s\t%s\n' "$relative" "$target" >> "$MANIFEST"
    fi
}

write_rollback() {
    cat > "${BACKUP_DIR}/rollback.sh" <<'ROLLBACK'
#!/usr/bin/env bash
set -Eeuo pipefail

BACKUP_DIR="$(cd "$(dirname "$0")" && pwd)"
MANIFEST="${BACKUP_DIR}/manifest.tsv"

if [[ -f "${BACKUP_DIR}/module.changed" ]]; then
    if command -v awg >/dev/null 2>&1; then
        active="$(awg show interfaces 2>/dev/null || true)"
        if [[ -n "$active" ]]; then
            printf 'Refusing rollback while AmneziaWG interfaces exist: %s\n' "$active" >&2
            exit 1
        fi
    fi
    modprobe -r amneziawg 2>/dev/null || true
fi

while IFS=$'\t' read -r state relative target; do
    [[ -n "$target" ]] || continue
    if [[ "$state" == "present" ]]; then
        install -d "$(dirname "$target")"
        cp -a -- "${BACKUP_DIR}/files/${relative}" "$target"
    else
        rm -f -- "$target"
    fi
done < "$MANIFEST"

if [[ -f "${BACKUP_DIR}/module.changed" ]]; then
    depmod -a
    if [[ -f "${BACKUP_DIR}/module.previously-loaded" ]]; then
        modprobe amneziawg
    fi
fi

printf 'Rollback completed from %s\n' "$BACKUP_DIR"
ROLLBACK
    chmod 700 "${BACKUP_DIR}/rollback.sh"
}

write_rollback

install_build_dependencies() {
    [[ $INSTALL_PACKAGES -eq 1 ]] || return 0

    local need_tools=0
    local need_module=0
    [[ "$MODE" != "module" ]] && need_tools=1
    [[ "$MODE" != "tools" ]] && need_module=1

    if command -v apt-get >/dev/null 2>&1; then
        local packages=(build-essential git pkg-config)
        [[ $need_tools -eq 1 ]] && packages+=(libmnl-dev)
        apt-get update
        if [[ $need_module -eq 1 && ! -d "/lib/modules/${KERNEL_RELEASE}/build" ]]; then
            if apt-cache show "proxmox-headers-${KERNEL_RELEASE}" >/dev/null 2>&1; then
                packages+=("proxmox-headers-${KERNEL_RELEASE}")
            elif apt-cache show "pve-headers-${KERNEL_RELEASE}" >/dev/null 2>&1; then
                packages+=("pve-headers-${KERNEL_RELEASE}")
            elif apt-cache show "linux-headers-${KERNEL_RELEASE}" >/dev/null 2>&1; then
                packages+=("linux-headers-${KERNEL_RELEASE}")
            else
                die "matching headers for ${KERNEL_RELEASE} are unavailable; install them without upgrading the running kernel"
            fi
        fi
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${packages[@]}"
    elif command -v dnf >/dev/null 2>&1; then
        local packages=(gcc make git pkgconf-pkg-config)
        [[ $need_tools -eq 1 ]] && packages+=(libmnl-devel)
        [[ $need_module -eq 1 && ! -d "/lib/modules/${KERNEL_RELEASE}/build" ]] && packages+=("kernel-devel-${KERNEL_RELEASE}")
        dnf install -y "${packages[@]}"
    elif command -v yum >/dev/null 2>&1; then
        local packages=(gcc make git pkgconfig)
        [[ $need_tools -eq 1 ]] && packages+=(libmnl-devel)
        [[ $need_module -eq 1 && ! -d "/lib/modules/${KERNEL_RELEASE}/build" ]] && packages+=("kernel-devel-${KERNEL_RELEASE}")
        yum install -y "${packages[@]}"
    else
        die "unsupported package manager; install build tools, git, libmnl headers, and matching kernel headers, then use --skip-packages"
    fi

    if [[ $need_module -eq 1 ]]; then
        [[ -d "/lib/modules/${KERNEL_RELEASE}/build" ]] || die "matching kernel headers are still unavailable for ${KERNEL_RELEASE}"
    fi
}

install_tools() {
    local source_dir="${BUILD_ROOT}/amneziawg-tools"

    backup_target /usr/bin/awg
    backup_target /usr/bin/awg-quick
    backup_target /usr/share/man/man8/awg.8
    backup_target /usr/share/man/man8/awg-quick.8

    log "building AmneziaWG tools ${TOOLS_TAG}"
    git clone --quiet --depth 1 --branch "$TOOLS_TAG" "$TOOLS_REPO" "$source_dir"
    TOOLS_COMMIT="$(git -C "$source_dir" rev-parse HEAD)"
    make -C "${source_dir}/src"
    make -C "${source_dir}/src" install
    command -v awg >/dev/null 2>&1 || die "awg was not installed"
    command -v awg-quick >/dev/null 2>&1 || die "awg-quick was not installed"
    awg --version
}

install_module() {
    local source_dir="${BUILD_ROOT}/amneziawg-module"
    local installed_module_path="/lib/modules/${KERNEL_RELEASE}/updates/amneziawg.ko"

    if modinfo amneziawg >/dev/null 2>&1; then
        OLD_MODULE_PATH="$(modinfo -n amneziawg)"
        backup_target "$OLD_MODULE_PATH"
    fi
    if [[ "$installed_module_path" != "$OLD_MODULE_PATH" ]]; then
        backup_target "$installed_module_path"
    fi
    if lsmod | awk '{print $1}' | grep -qx amneziawg; then
        touch "${BACKUP_DIR}/module.previously-loaded"
    fi
    touch "${BACKUP_DIR}/module.changed"

    log "building AmneziaWG kernel module ${MODULE_TAG} for ${KERNEL_RELEASE}"
    git clone --quiet --depth 1 --branch "$MODULE_TAG" "$MODULE_REPO" "$source_dir"
    MODULE_COMMIT="$(git -C "$source_dir" rev-parse HEAD)"
    make -C "${source_dir}/src"
    make -C "${source_dir}/src" install
    depmod -a

    [[ -f "$installed_module_path" ]] || die "expected installed module is missing: ${installed_module_path}"
    NEW_MODULE_PATH="$(modinfo -n amneziawg 2>/dev/null || true)"
    [[ -n "$NEW_MODULE_PATH" ]] || die "amneziawg module was not installed for ${KERNEL_RELEASE}"
    if [[ "$NEW_MODULE_PATH" != "$installed_module_path" ]] \
        && ! cmp -s "$installed_module_path" "$NEW_MODULE_PATH"; then
        case "$NEW_MODULE_PATH" in
            *.ko)
                log "replacing stale higher-priority module at ${NEW_MODULE_PATH}"
                install -m 0644 "$installed_module_path" "$NEW_MODULE_PATH"
                depmod -a
                ;;
            *)
                die "stale compressed module has priority at ${NEW_MODULE_PATH}; remove its owning package safely before reload"
                ;;
        esac
    fi
    NEW_MODULE_PATH="$(modinfo -n amneziawg)"
    cmp -s "$installed_module_path" "$NEW_MODULE_PATH" \
        || die "selected module ${NEW_MODULE_PATH} does not match the pinned build"

    if [[ $RELOAD_MODULE -eq 1 ]]; then
        ACTIVE_INTERFACES="$(active_awg_interfaces)"
        [[ -z "$ACTIVE_INTERFACES" ]] || die "refusing module reload while AmneziaWG interfaces exist: $ACTIVE_INTERFACES"
        modprobe -r amneziawg 2>/dev/null || true
        modprobe amneziawg
        log "loaded AmneziaWG module from $(modinfo -n amneziawg)"
    else
        log "installed the module on disk without unloading or reloading the running module"
    fi
}

install_build_dependencies

TOOLS_COMMIT=""
MODULE_COMMIT=""
case "$MODE" in
    all)
        install_tools
        install_module
        ;;
    tools)
        install_tools
        ;;
    module)
        install_module
        ;;
esac

backup_target "$STATE_FILE"
install -d -m 755 "$(dirname "$STATE_FILE")"
cat > "$STATE_FILE" <<EOF
AWG_TOOLS_TAG=${TOOLS_TAG}
AWG_TOOLS_COMMIT=${TOOLS_COMMIT}
AWG_MODULE_TAG=${MODULE_TAG}
AWG_MODULE_COMMIT=${MODULE_COMMIT}
AWG_KERNEL_RELEASE=${KERNEL_RELEASE}
AWG_INSTALLED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
chmod 600 "$STATE_FILE"

log "installation completed; rollback: ${BACKUP_DIR}/rollback.sh"
