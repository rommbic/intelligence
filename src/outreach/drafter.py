"""Uses Claude to draft personalised outreach emails in the Rommbic voice.

The prompt is deliberately opinionated about tone (from the brand guide):
straight-talking, MD-to-MD, no fluff, no corporate-sales language.

Returns (subject, body_html). Falls back to a deterministic template if Claude
is unavailable, so outreach still functions when the API key isn't configured.
"""
from __future__ import annotations

import json
import logging
import os
from html import escape
from typing import Optional

log = logging.getLogger("outreach.drafter")


SYSTEM_PROMPT = """You write outreach emails for Rommbic, the UK's leading \
retained-search recruitment firm for the construction products industry.

Voice rules (non-negotiable — from the Rommbic brand guide):
- Straight-talking, confident, slightly blunt. Professional but conversational.
- Sound like a knowledgeable industry mate, not a corporate sales team.
- Short sentences. No fluff. No jargon. No 'synergy', 'leveraging', 'passion'.
- Speak first, explain second. State the observation, then the offer.
- Signed off from Will at Rommbic.

Structure:
- 3-5 short sentences total.
- Sentence 1: reference the specific news (paraphrase — no exact article quotes).
- Sentence 2: connect that to likely hiring implications, briefly.
- Sentence 3: offer the salary & insights report; ask them to reply if useful.
- Optional short signoff.

Do NOT invent facts about the recipient or company. Only use what's in the news.
Do NOT include a footer, disclaimers, or unsubscribe language.
"""


def _fallback_email(recipient_name: str, company: str, article_title: str,
                    article_url: str) -> tuple[str, str]:
    """Deterministic fallback used when Claude is unavailable."""
    first_name = (recipient_name or "").strip().split(" ", 1)[0] or "there"
    subject = f"Saw the news on {company} — quick thought"
    text = (
        f"Hi {first_name},\n\n"
        f"Saw the news on {company} — \"{article_title}\". "
        f"Where there's momentum like this, hiring usually isn't far behind.\n\n"
        f"We publish a construction products salary & insights report with "
        f"benchmarks across the sector — happy to send it over if useful. "
        f"Just reply and I'll fire it across.\n\n"
        f"Will\n"
        f"Rommbic"
    )
    body_html = f"<p>{escape(text).replace(chr(10)+chr(10), '</p><p>').replace(chr(10), '<br>')}</p>"
    body_html += f'<p style="color:#888;font-size:11px;margin-top:14px">Ref: <a href="{escape(article_url)}">{escape(article_title)}</a></p>'
    return subject, body_html


def draft_email(recipient_name: str, recipient_title: str, company: str,
                article_title: str, article_summary: str, article_url: str,
                categories: list[str]) -> tuple[str, str]:
    """Returns (subject, body_html). Uses Claude if ANTHROPIC_API_KEY is set,
    otherwise falls back to a deterministic template."""

    if not os.getenv("ANTHROPIC_API_KEY"):
        return _fallback_email(recipient_name, company, article_title, article_url)

    try:
        import anthropic
    except ImportError:
        log.warning("anthropic library not installed; using fallback template.")
        return _fallback_email(recipient_name, company, article_title, article_url)

    first_name = (recipient_name or "").strip().split(" ", 1)[0] or "there"
    user_prompt = f"""Write a short outreach email from Will at Rommbic to a \
director at a UK construction products company, based on a news signal.

RECIPIENT: {first_name} ({recipient_title}), {company}
NEWS HEADLINE: {article_title}
NEWS SUMMARY: {article_summary}
SIGNAL TYPE: {', '.join(categories) if categories else 'general activity'}

Return STRICT JSON only, no prose:
{{
  "subject": "<short, specific, no clickbait — max 8 words>",
  "body": "<the email body in plain text, no HTML, no signature block>"
}}"""

    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        data = json.loads(raw)
        subject = str(data.get("subject", "")).strip() or f"News from {company}"
        body = str(data.get("body", "")).strip()
        if not body:
            raise ValueError("empty body from model")
        # Append fixed sign-off + reference footer (kept out of the AI's control)
        body = body.rstrip() + "\n\nWill\nRommbic"
        body_html = "<p>" + escape(body).replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
        body_html += (f'<p style="color:#888;font-size:11px;margin-top:14px">'
                      f'Ref: <a href="{escape(article_url)}">{escape(article_title)}</a></p>')
        return subject, body_html
    except Exception as exc:
        log.warning("Claude drafting failed (%s); using fallback.", exc)
        return _fallback_email(recipient_name, company, article_title, article_url)
