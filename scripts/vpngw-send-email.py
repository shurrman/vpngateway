#!/usr/bin/env python3
"""Send email notification via SMTP. Used by vpngw-health-check.sh."""

import os
import smtplib
import ssl
import sys
from email.mime.text import MIMEText
from datetime import datetime, timezone


def read_conf(path):
    conf = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                conf[k.strip()] = v.strip()
    return conf


def send_email(conf, subject, body):
    if conf.get("ENABLED", "false").lower() != "true":
        print("Notifications disabled, skipping")
        return False

    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "RECIPIENT"]
    for key in required:
        if not conf.get(key):
            print(f"Missing config: {key}")
            return False

    sender = conf.get("SMTP_FROM") or conf["SMTP_USER"]
    recipient = conf["RECIPIENT"]

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    hostname = os.environ.get("GATEWAY_HOSTNAME", "vpngateway")
    full_body = f"{body}\n\n---\nVPN Gateway ({hostname})\n{timestamp}"

    msg = MIMEText(full_body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    try:
        port = int(conf["SMTP_PORT"])
        if port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(conf["SMTP_HOST"], port, context=context, timeout=15) as server:
                server.login(conf["SMTP_USER"], conf["SMTP_PASSWORD"])
                server.send_message(msg)
        else:
            with smtplib.SMTP(conf["SMTP_HOST"], port, timeout=15) as server:
                server.starttls()
                server.login(conf["SMTP_USER"], conf["SMTP_PASSWORD"])
                server.send_message(msg)
        print(f"Email sent to {recipient}: {subject}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <conf_path> <subject> <body>")
        sys.exit(1)

    conf = read_conf(sys.argv[1])
    success = send_email(conf, sys.argv[2], sys.argv[3])
    sys.exit(0 if success else 1)
