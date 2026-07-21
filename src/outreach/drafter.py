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
- Informal. Sound like a note from a mate who happens to work in recruitment.
- Straight-talking, confident, slightly blunt. Zero corporate-sales language.
- No 'synergy', 'leveraging', 'passion', 'exciting news', 'noticed that'.
- No hedge words like 'perhaps', 'thought I'd'.
- Signed off from Matt (appended automatically).

PUNCTUATION - HARD RULE:
Only use standard hyphens (-). Never em dashes (--, —) or en dashes (–).
If you want a pause, use a comma or start a new sentence.

Structure - TWO SENTENCES:

Sentence 1: Reference the SPECIFIC news event. Name what actually happened, not just "the news". If it's an acquisition, name it. If it's a new depot, say depot. If it's a leadership change, say who did what. Show you actually read it. This sentence carries all the personalisation.

Sentence 2: Say that Rommbic works solely with construction products businesses, and if they're hiring off the back of this, drop you a line. Conditional, not pushy. Do NOT mention a salary report, a benchmarks doc, or anything downloadable. This is not a lead magnet, it is an offer to help if the timing fits.

Example of the RIGHT shape (news is invented for illustration):
"Saw British Steel is getting nationalised - big shift for the UK industry and probably a lot changing at the top.
We work solely with construction products businesses on senior hires - if you're building the team out around this, drop me a line."

Do NOT invent facts. Do NOT include a subject line in the body. Do NOT include a link or footer. Do NOT add a sign-off - one is appended automatically.
"""


def _fallback_email(recipient_name: str, company: str, article_title: str,
                    article_url: str) -> tuple[str, str]:
    """Deterministic fallback used when Claude is unavailable."""
    first_name = (recipient_name or "").strip().split(" ", 1)[0] or "there"
    subject = f"Saw the news on {company}"
    text = (
        f"Hi {first_name},\n\n"
        f"Saw the news about {company} - could mean quite a bit of change at the top.\n\n"
        f"We work solely with construction products businesses on senior hires - "
        f"if you're building the team out around this, drop me a line.\n\n"
        f"Matt"
    )
    body_html = f"<p>{escape(text).replace(chr(10)+chr(10), '</p><p>').replace(chr(10), '<br>')}</p>"
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
    # Google News summaries arrive with HTML in them; strip so Claude gets clean prose.
    import re
    clean_summary = re.sub(r"<[^>]+>", " ", article_summary or "")
    clean_summary = re.sub(r"\s+", " ", clean_summary).strip()

    user_prompt = f"""Write a short outreach email from Matt at Rommbic to a director at a UK construction products company, based on a news signal.

RECIPIENT: {first_name} ({recipient_title}), {company}
NEWS HEADLINE: {article_title}
NEWS SUMMARY: {clean_summary}
SIGNAL TYPE: {', '.join(categories) if categories else 'general activity'}

The first sentence MUST reference the SPECIFIC event in the headline (e.g. "the nationalisation news", "the new depot in Leeds", "the MD appointment"), not just "the news". Show you actually read it.

Return STRICT JSON only, no prose:
{{
  "subject": "<short, specific, max 8 words>",
  "body": "<the email body in plain text, no HTML, no signature block, no link>"
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
        # Append fixed sign-off. Just "Matt" - concise, informal.
        body = body.rstrip() + "\n\nMatt"
        body_html = "<p>" + escape(body).replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
        return subject, body_html
    except Exception as exc:
        log.warning("Claude drafting failed (%s); using fallback.", exc)
        return _fallback_email(recipient_name, company, article_title, article_url)
