"""Notification settings and health status endpoints."""

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from config import CONFIG_DIR
from models.common import ok, error
from services.script_runner import run_command

router = APIRouter(prefix="/notifications", tags=["notifications"])

CONF_FILE = CONFIG_DIR / "notifications.conf"
STATE_FILE = Path("/tmp/vpngw-health-state")
SEND_EMAIL = Path("/opt/vpngateway/scripts/vpngw-send-email.py")
PYTHON = Path("/opt/vpngateway/api/venv/bin/python3")


class NotificationConfig(BaseModel):
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    recipient: str = ""
    enabled: bool = False


def _read_conf() -> dict:
    conf = {}
    if CONF_FILE.exists():
        for line in CONF_FILE.read_text().split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                conf[k.strip()] = v.strip()
    return conf


def _write_conf(conf: dict):
    lines = ["# VPN Gateway email notification settings"]
    for k, v in conf.items():
        lines.append(f"{k}={v}")
    CONF_FILE.write_text("\n".join(lines) + "\n")


@router.get("/config")
async def get_config():
    conf = _read_conf()
    # Mask password
    password = conf.get("SMTP_PASSWORD", "")
    masked = ("*" * len(password)) if password else ""
    return ok({
        "smtp_host": conf.get("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(conf.get("SMTP_PORT", "587")),
        "smtp_user": conf.get("SMTP_USER", ""),
        "smtp_password_set": bool(password),
        "smtp_password_masked": masked,
        "smtp_from": conf.get("SMTP_FROM", ""),
        "recipient": conf.get("RECIPIENT", ""),
        "enabled": conf.get("ENABLED", "false").lower() == "true",
    })


@router.put("/config")
async def update_config(req: NotificationConfig):
    # If password is empty, keep existing
    existing = _read_conf()
    password = req.smtp_password
    if not password and existing.get("SMTP_PASSWORD"):
        password = existing["SMTP_PASSWORD"]

    conf = {
        "SMTP_HOST": req.smtp_host,
        "SMTP_PORT": str(req.smtp_port),
        "SMTP_USER": req.smtp_user,
        "SMTP_PASSWORD": password,
        "SMTP_FROM": req.smtp_from or req.smtp_user,
        "RECIPIENT": req.recipient,
        "ENABLED": "true" if req.enabled else "false",
    }
    _write_conf(conf)
    return ok({"saved": True})


@router.post("/test")
async def test_notification():
    if not CONF_FILE.exists():
        return error("Notification config not found")

    result = await run_command(
        str(PYTHON), str(SEND_EMAIL), str(CONF_FILE),
        "[VPN Gateway] Test Notification",
        "This is a test email from VPN Gateway health monitoring.",
    )
    if result.success:
        return ok({"sent": True}, log=result.output)
    else:
        return error(f"Failed to send: {result.output}")


@router.get("/status")
async def health_status():
    state = "unknown"
    if STATE_FILE.exists():
        state = STATE_FILE.read_text().strip()

    return ok({
        "state": state,
        "state_file": str(STATE_FILE),
    })
