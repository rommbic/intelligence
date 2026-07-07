"""Create Gmail drafts in Will's inbox using a Google Workspace service account
with domain-wide delegation.

Setup (one-time, needs Workspace admin):
  1. Google Cloud Console -> create a project, enable the Gmail API.
  2. Create a service account, download the JSON key.
  3. In Workspace Admin -> Security -> API controls -> Domain-wide delegation,
     authorise the service account's client ID with scope:
        https://www.googleapis.com/auth/gmail.compose
  4. Store the JSON key contents in the GitHub secret GOOGLE_SERVICE_ACCOUNT.
  5. Set OUTREACH_INBOX to 'will@rommbic.co.uk' (in settings or env).

Runtime: the service account impersonates the inbox user, no browser needed.
Drafts appear in Will's Drafts folder — nothing is sent automatically.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

log = logging.getLogger("outreach.gmail")

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


class GmailDrafter:
    """Creates drafts in a single specified inbox. Lazy-loads Google libraries
    so the rest of the app doesn't require them if outreach is disabled."""

    def __init__(self, inbox: str, key_json: Optional[str] = None):
        self.inbox = inbox
        self._key_json = key_json or os.getenv("GOOGLE_SERVICE_ACCOUNT", "")
        self._service = None

    def _build_service(self):
        if self._service is not None:
            return self._service
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:
            log.error("Gmail libraries not installed: %s", exc)
            return None
        if not self._key_json:
            log.error("GOOGLE_SERVICE_ACCOUNT not set; cannot create drafts.")
            return None
        try:
            info = json.loads(self._key_json)
        except json.JSONDecodeError as exc:
            log.error("GOOGLE_SERVICE_ACCOUNT is not valid JSON: %s", exc)
            return None
        try:
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=SCOPES,
            ).with_subject(self.inbox)
            self._service = build("gmail", "v1", credentials=creds,
                                  cache_discovery=False)
            return self._service
        except Exception as exc:
            log.error("Gmail auth failed: %s", exc)
            return None

    def create_draft(self, to: str, subject: str, body_html: str,
                     body_text: Optional[str] = None) -> Optional[str]:
        """Creates a draft and returns its Gmail draft ID (or None on failure).
        Failure is logged but never raised — outreach is best-effort."""
        service = self._build_service()
        if not service:
            return None
        try:
            msg = MIMEMultipart("alternative")
            msg["To"] = to
            msg["From"] = self.inbox
            msg["Subject"] = subject
            if body_text:
                msg.attach(MIMEText(body_text, "plain"))
            msg.attach(MIMEText(body_html, "html"))
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            result = service.users().drafts().create(
                userId="me", body={"message": {"raw": raw}},
            ).execute()
            draft_id = result.get("id")
            log.info("Draft created for %s (id=%s)", to, draft_id)
            return draft_id
        except Exception as exc:
            log.error("Draft creation for %s failed: %s", to, exc)
            return None
