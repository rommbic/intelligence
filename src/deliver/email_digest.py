"""Builds the daily HTML digest and sends it to all consultants.

Transport (auto-selected):
  * Resend  — if RESEND_API_KEY is set (recommended for reliable delivery)
  * SMTP    — if SMTP_HOST/SMTP_USER/SMTP_PASS are set (use your M365 / Workspace)
If neither is configured the digest is written to data/last_email.html and the
run still succeeds (so the dashboard never depends on email being set up).
"""
from __future__ import annotations

import logging
import os
import smtplib
from datetime import timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

import requests

from ..config import DATA_DIR
from ..util import Item, now_utc

log = logging.getLogger("deliver.email")

_BADGE = {  # score band -> brand colour
    "high": "#e87511", "med": "#2e4a54", "low": "#6b7780",
}


def _band(score: int) -> str:
    return "high" if score >= 8 else "med" if score >= 6 else "low"


def build_html(items: list[Item], settings: dict) -> str:
    date = now_utc().astimezone(timezone.utc).strftime("%A %d %B %Y")
    dash = settings.get("dashboard_url", "#")
    min_score = settings.get("email", {}).get("min_score_to_email", 5)
    shown = [it for it in items if it.score >= min_score]

    rows = []
    for it in shown:
        cats = ", ".join(it.categories) or "—"
        company = f'<span style="color:#e87511;font-weight:700">{escape(it.company)}</span> · ' if it.company else ""
        why = f'<div style="color:#2e4a54;font-size:13px;margin-top:3px;font-style:italic">{escape(it.rationale)}</div>' if it.rationale else ""
        roles = f'<div style="color:#6b7780;font-size:11px;margin-top:3px;text-transform:uppercase;letter-spacing:.5px">Roles: {escape(it.likely_roles)}</div>' if it.likely_roles else ""
        rows.append(f"""
        <tr>
          <td style="padding:14px 0;border-bottom:1px solid #ece6da;vertical-align:top">
            <span style="display:inline-block;min-width:34px;text-align:center;background:{_BADGE[_band(it.score)]};
                         color:#fff;font-weight:700;border-radius:4px;padding:3px 7px;font-size:14px">{it.score}</span>
          </td>
          <td style="padding:14px 0 14px 12px;border-bottom:1px solid #ece6da">
            <a href="{escape(it.link)}" style="color:#161614;font-weight:600;text-decoration:none;font-size:15px">{escape(it.title)}</a>
            <div style="color:#6b7780;font-size:11px;margin-top:4px;text-transform:uppercase;letter-spacing:.5px">{company}{escape(cats)}{' · ' + escape(it.source) if it.source else ''}</div>
            {why}{roles}
          </td>
        </tr>""")

    body = "".join(rows) or '<tr><td style="padding:24px 0;color:#6b7780">No qualifying signals today.</td></tr>'
    font = "'IBM Plex Sans', Arial, Helvetica, sans-serif"
    return f"""<!doctype html><html><body style="margin:0;background:#fdfbf8;font-family:{font}">
      <div style="max-width:680px;margin:0 auto;padding:26px 22px">
        <div style="background:#161614;border-bottom:3px solid #e87511;border-radius:10px 10px 0 0;padding:18px 20px">
          <div style="font-size:11px;letter-spacing:3px;color:rgba(253,251,248,.5);text-transform:uppercase;font-weight:700">Construction Products Recruitment Intelligence</div>
          <div style="font-size:23px;font-weight:800;letter-spacing:-.5px;color:#fdfbf8;margin-top:4px">ROMMBIC <span style="font-size:13px;font-weight:700;letter-spacing:2px;color:#fdfbf8">&nbsp;|&nbsp; INTELLIGENCE PORTAL</span></div>
          <div style="font-size:12px;color:rgba(253,251,248,.55);text-transform:uppercase;letter-spacing:1px;margin-top:6px">{date} · {len(shown)} signals</div>
        </div>
        <table style="width:100%;border-collapse:collapse;margin-top:6px">{body}</table>
        <div style="margin-top:22px;text-align:center">
          <a href="{escape(dash)}" style="background:#161614;color:#fdfbf8;text-decoration:none;
             padding:11px 20px;border-radius:7px;font-size:13px;font-weight:700;letter-spacing:.5px">OPEN THE PORTAL →</a>
        </div>
        <div style="font-size:13px;color:#161614;text-align:center;margin-top:20px;font-weight:800;letter-spacing:.3px">
          Serious searching<span style="color:#e87511">.</span> No time wasted<span style="color:#e87511">.</span></div>
        <div style="font-size:11px;color:#9a958c;text-align:center;margin-top:8px">
          Automated brief for Rommbic consultants · scores indicate hiring-intent strength (1–10).
        </div>
      </div></body></html>"""


def _send_resend(html: str, subject: str, settings: dict, recipients: list[str]) -> bool:
    key = os.getenv("RESEND_API_KEY")
    if not key:
        return False
    em = settings["email"]
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "from": f'{em["from_name"]} <{em["from_address"]}>',
            "to": recipients, "subject": subject, "html": html,
        }, timeout=20,
    )
    if r.status_code >= 300:
        log.error("Resend error %s: %s", r.status_code, r.text)
        return False
    log.info("Digest sent via Resend to %d recipients", len(recipients))
    return True


def _send_smtp(html: str, subject: str, settings: dict, recipients: list[str]) -> bool:
    host, user, pwd = os.getenv("SMTP_HOST"), os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    if not (host and user and pwd):
        return False
    em = settings["email"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f'{em["from_name"]} <{em["from_address"]}>'
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText("Open in an HTML-capable client.", "plain"))
    msg.attach(MIMEText(html, "html"))
    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(user, pwd)
        s.sendmail(em["from_address"], recipients, msg.as_string())
    log.info("Digest sent via SMTP to %d recipients", len(recipients))
    return True


def send(items: list[Item], settings: dict) -> None:
    em = settings.get("email", {})
    recipients = em.get("recipients", [])
    html = build_html(items, settings)
    (DATA_DIR / "last_email.html").write_text(html, encoding="utf-8")

    if not recipients:
        log.warning("No recipients configured; digest written to data/last_email.html only.")
        return
    subject = f'{em.get("subject_prefix", "Rommbic Daily Intel")} — ' \
              f'{now_utc().astimezone(timezone.utc).strftime("%d %b %Y")}'
    if _send_resend(html, subject, settings, recipients):
        return
    if _send_smtp(html, subject, settings, recipients):
        return
    log.warning("No email transport configured; digest saved to data/last_email.html.")
