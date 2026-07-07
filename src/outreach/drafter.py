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


SYSTEM_PROMPT = """You write outreach emails for Rommbic, the UK's leading retained-search recruitment firm for the construction products industry.

Voice rules (non-negotiable, from the Rommbic brand guide):
- Informal. Sound like a text from a mate who happens to work in recruitment.
- Straight-talking, confident, slightly blunt. Zero corporate-sales language.
- No 'synergy', 'leveraging', 'passion', 'exciting news', 'noticed that'.
- No hedge words: 'just', 'might', 'perhaps', 'thought I'd'.
- Signed off from Will.

PUNCTUATION - HARD RULE:
Only use standard hyphens (-). Never use em dashes (--, —) or en dashes (–).
If you want a pause, use a comma or start a new sentence. This is strict.

Structure - TWO SENTENCES ONLY:
1. One sentence about the news, ending with a note that hiring usually follows.
2. One short, sharp sentence offering the salary and insights report, reply-to-get.

Example of the RIGHT shape (adapt the news bit; keep the offer sentence tight):
"Saw the news about [company] [thing that happened] - hiring's usually not far behind.
Want a copy of our construction products salary and insights report? Just reply and I'll send it."

Do NOT invent facts. Do NOT include a subject line in the body. Do NOT add a sign-off - one is appended automatically.
"""


def _fallback_email(recipient_name: str, company: str, article_title: str,
                    article_url: str) -> tuple[str, str]:
    """Deterministic fallback used when Claude is unavailable."""
    first_name = (recipient_name or "").strip().split(" ", 1)[0] or "there"
    subject = f"Saw the news on {company}"
    text = (
        f"Hi {first_name},\n\n"
        f"Saw the news about {company} - hiring's usually not far behind.\n\n"
        f"Want a copy of our construction products salary and insights report? "
        f"Just reply and I'll send it.\n\n"
        f"Will"
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
  "subject": "<short, specific, no clickbait, max 8 words>",
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
        # Safety net: normalise any smart/em/en dashes to plain hyphens, so the
        # recipient never sees fancy dashes even if the model slips.
        for bad, good in (("\u2014", "-"), ("\u2013", "-"),
                          ("\u2015", "-"), ("--", "-")):
            subject = subject.replace(bad, good)
            body = body.replace(bad, good)
        # Append fixed sign-off. Just "Will" - concise, informal.
        body = body.rstrip() + "\n\nWill"
        body_html = "<p>" + escape(body).replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
        body_html += (f'<p style="color:#888;font-size:11px;margin-top:14px">'
                      f'Ref: <a href="{escape(article_url)}">{escape(article_title)}</a></p>')
        return subject, body_html
    except Exception as exc:
        log.warning("Claude drafting failed (%s); using fallback.", exc)
        return _fallback_email(recipient_name, company, article_title, article_url)
