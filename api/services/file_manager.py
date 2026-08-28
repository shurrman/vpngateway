"""Read/write config files with parsing and atomic writes."""

import ipaddress
import re
from pathlib import Path

from config import CONFIG_DIR, DOMAINS_DIR, DOMAINS_FILE
from models.domains import DomainGroup
from models.networks import NetworkFile


# Domain name validation
DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$"
)


def validate_domain(domain: str) -> bool:
    return bool(DOMAIN_RE.match(domain)) and len(domain) <= 253


def validate_cidr(cidr: str) -> bool:
    try:
        ipaddress.ip_network(cidr, strict=False)
        return True
    except ValueError:
        return False


def _atomic_write(path: Path, content: str):
    """Write content to file atomically via temp file + rename."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content)
    tmp.rename(path)


# --- Domains ---
#
# Categories: each file in CONFIG_DIR/domains/ is a category. Stem of
# the filename is the category id used by the API and UI:
#
#   config/domains/main.lst         id = "main"  (the catch-all)
#   config/domains/aws.lst          id = "aws"
#   config/domains/cloudflare.lst   id = "cloudflare"
#   config/domains/<X>.lst          id = "<X>"
#
# All categories populate the same vpn_domains ipset (split is purely
# organisational — see CHANGELOG entry 47). The directory layout was
# adopted in v3.0.5 to avoid the older `domains-<X>.lst` naming
# clashing with `*-networks.lst` (CIDR lists).

# Category ids map directly to config/domains/<id>.lst. Keep this as a
# conservative filename whitelist: no slashes, dots, whitespace, or shell
# metacharacters. Case is intentionally preserved because gateway-local
# runtime categories such as HOME.lst are valid and editable through the API.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _category_path(category_id: str) -> Path | None:
    """Map a category id to the on-disk .lst path. Returns None for an
    invalid id (caller should report the error)."""
    if not NAME_RE.match(category_id):
        return None
    return DOMAINS_DIR / f"{category_id}.lst"


def _path_to_category_id(path: Path) -> str:
    return path.stem


def _domain_list_paths() -> list[Path]:
    """List real domain category files, ignoring hidden macOS sidecars."""
    if not DOMAINS_DIR.is_dir():
        return []
    return sorted(
        path for path in DOMAINS_DIR.glob("*.lst")
        if not path.name.startswith(".")
    )


def _parse_groups(raw: str) -> list[DomainGroup]:
    """Split a single .lst file into groups by leading `# Comment` lines."""
    groups: list[DomainGroup] = []
    current_group = "Ungrouped"
    current_domains: list[str] = []

    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            comment = stripped.lstrip("# ").strip()
            if comment and current_domains:
                groups.append(DomainGroup(name=current_group, domains=current_domains))
                current_domains = []
            if comment:
                current_group = comment
        elif stripped:
            current_domains.append(stripped)

    if current_domains:
        groups.append(DomainGroup(name=current_group, domains=current_domains))

    return groups


def read_domain_categories() -> list[dict]:
    """Read every config/domains/*.lst as a category.

    Returns a list of dicts ready for JSON, each containing:
        id, filename, total, groups, raw
    Order: "main" first if it exists, then the rest alphabetically.
    """
    categories: list[dict] = []

    paths = _domain_list_paths()
    # Float "main" to the top so the UI shows the catch-all category
    # first regardless of where it lands alphabetically.
    paths.sort(key=lambda p: (p.stem != "main", p.stem))

    for path in paths:
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        groups = _parse_groups(raw)
        categories.append({
            "id": _path_to_category_id(path),
            "filename": path.name,
            "total": sum(len(g.domains) for g in groups),
            "groups": [g.model_dump() for g in groups],
            "raw": raw,
        })

    return categories


# Backward-compat shim — older callers expect (groups_for_main, raw_for_main).
# Most things should move to read_domain_categories().
def read_domains() -> tuple[list[DomainGroup], str]:
    try:
        raw = DOMAINS_FILE.read_text()
    except FileNotFoundError:
        return [], ""
    return _parse_groups(raw), raw


def add_domains(domains: list[str], group: str | None = None,
                category: str = "main") -> str:
    """Append domains to the named category file. Returns "" on success
    or an error message."""
    path = _category_path(category)
    if path is None:
        return f"invalid category id: {category!r}"

    invalid = [d for d in domains if not validate_domain(d)]
    if invalid:
        return f"Invalid domains: {', '.join(invalid)}"

    if not path.exists():
        # Auto-create new categories on first write so users can add a
        # domain to e.g. "github" before the file exists.
        if category == "main":
            return "config/domains/main.lst missing — gateway is misconfigured"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {category} domains\n")

    content = path.read_text()
    existing = {
        line.strip()
        for line in content.split("\n")
        if line.strip() and not line.strip().startswith("#")
    }
    new_domains = [d for d in domains if d not in existing]
    if not new_domains:
        return "All domains already exist"

    addition = "\n"
    if group:
        addition += f"\n# {group}\n"
    addition += "\n".join(new_domains) + "\n"

    _atomic_write(path, content.rstrip("\n") + addition)
    return ""


def delete_domains(domains: list[str], category: str | None = None) -> str:
    """Delete domains from one category, or from every category if
    category is None (removes the first match — useful when the UI
    doesn't know which file the domain lives in)."""
    to_remove = set(domains)
    if not to_remove:
        return ""

    if category is not None:
        path = _category_path(category)
        if path is None:
            return f"invalid category id: {category!r}"
        if not path.exists():
            return f"category {category!r} not found"
        paths = [path]
    else:
        paths = _domain_list_paths()

    removed = set()
    for p in paths:
        try:
            content = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = content.split("\n")
        new_lines = []
        changed = False
        for line in lines:
            s = line.strip()
            if s in to_remove and s not in removed:
                removed.add(s)
                changed = True
                continue  # drop this line
            new_lines.append(line)
        if changed:
            # Normalise to a trailing newline. Without it, vpngw-update-
            # domains.sh's `while read` would drop the last line on the
            # next regen — see CHANGELOG entry 66.
            new_text = "\n".join(new_lines)
            if not new_text.endswith("\n"):
                new_text += "\n"
            _atomic_write(p, new_text)

    return ""


def replace_domains_raw(raw: str, category: str = "main") -> str:
    """Replace the entire content of one category."""
    path = _category_path(category)
    if path is None:
        return f"invalid category id: {category!r}"

    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            if not validate_domain(stripped):
                return f"Invalid domain: {stripped}"
    # Force a trailing newline. The Raw editor in the Web UI doesn't
    # always include one (and humans pasting content via SSH rarely do).
    # Without it the last domain silently disappears on the next regen.
    if not raw.endswith("\n"):
        raw += "\n"
    _atomic_write(path, raw)
    return ""


# --- Networks ---

def list_network_files() -> list[NetworkFile]:
    """List all *-networks.lst files."""
    files = []
    for path in sorted(CONFIG_DIR.glob("*-networks.lst")):
        if path.name.startswith("._"):
            continue
        name = path.stem.replace("-networks", "")
        entries, description = _parse_network_file(path)
        files.append(NetworkFile(
            name=name,
            filename=path.name,
            description=description,
            entry_count=len(entries),
            entries=entries,
        ))
    return files


def get_network_file(name: str) -> NetworkFile | None:
    if name.startswith("._"):
        return None
    path = CONFIG_DIR / f"{name}-networks.lst"
    if not path.exists():
        return None
    entries, description = _parse_network_file(path)
    return NetworkFile(
        name=name,
        filename=path.name,
        description=description,
        entry_count=len(entries),
        entries=entries,
    )


def _parse_network_file(path: Path) -> tuple[list[str], str]:
    content = path.read_text(encoding="utf-8", errors="replace")
    entries = []
    description = ""
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            if not description:
                description = stripped.lstrip("# ").strip()
        elif stripped:
            entries.append(stripped)
    return entries, description


def add_cidrs_to_network(name: str, cidrs: list[str]) -> str:
    invalid = [c for c in cidrs if not validate_cidr(c)]
    if invalid:
        return f"Invalid CIDRs: {', '.join(invalid)}"

    path = CONFIG_DIR / f"{name}-networks.lst"
    if not path.exists():
        return f"Network file {name}-networks.lst not found"

    content = path.read_text(encoding="utf-8", errors="replace")
    existing = {line.strip() for line in content.split("\n") if line.strip() and not line.strip().startswith("#")}
    new_cidrs = [c for c in cidrs if c not in existing]
    if not new_cidrs:
        return "All CIDRs already exist"

    _atomic_write(path, content.rstrip("\n") + "\n" + "\n".join(new_cidrs) + "\n")
    return ""


def delete_cidrs_from_network(name: str, cidrs: list[str]) -> str:
    path = CONFIG_DIR / f"{name}-networks.lst"
    if not path.exists():
        return f"Network file {name}-networks.lst not found"

    to_remove = set(cidrs)
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.split("\n")
    new_lines = [line for line in lines if line.strip() not in to_remove]
    _atomic_write(path, "\n".join(new_lines))
    return ""


def create_network_file(name: str, description: str, cidrs: list[str]) -> str:
    invalid = [c for c in cidrs if not validate_cidr(c)]
    if invalid:
        return f"Invalid CIDRs: {', '.join(invalid)}"

    path = CONFIG_DIR / f"{name}-networks.lst"
    if path.exists():
        return f"Network file {name}-networks.lst already exists"

    content = f"# {description}\n" if description else ""
    content += "\n".join(cidrs) + "\n"
    _atomic_write(path, content)
    return ""


def delete_network_file(name: str) -> str:
    path = CONFIG_DIR / f"{name}-networks.lst"
    if not path.exists():
        return f"Network file {name}-networks.lst not found"
    path.unlink()
    return ""
