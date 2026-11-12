"""Outgoing email (verification and password-reset codes).

Resend (host api.resend.com): sends over HTTPS with an API key — no mailbox needed,
DNS records live on send.<domain> and resend._domainkey.<domain>.

Defaults to Gmail: smtp.gmail.com:465 with an App Password
(Google Account → Security → 2-Step Verification → App passwords).
Settings live in site_settings, set from Admin → Payment Methods → Email.
"""
import smtplib
import ssl
import requests
from email.message import EmailMessage
from email.utils import formataddr

from database import get_db

KEYS = ('email_address', 'email_app_password', 'email_name', 'email_host', 'email_port')


def get_config():
    db = get_db()
    try:
        rows = db.execute(
            'SELECT key, value FROM site_settings WHERE key IN (%s)' % ','.join('?' * len(KEYS)), KEYS
        ).fetchall()
    finally:
        db.close()
    v = {r['key']: r['value'] for r in rows}
    return {
        'address':  v.get('email_address', ''),
        'password': v.get('email_app_password', ''),
        'name':     v.get('email_name') or "BigWin Gaming",
        'host':     v.get('email_host') or 'smtp.gmail.com',
        'port':     int(v.get('email_port') or 465),
    }


def configured():
    c = get_config()
    return bool(c['address'] and c['password'])


def send(to, subject, text, cfg=None, html=None):
    """Send an email (plain text, plus an HTML version when given). Returns (ok, error)."""
    c = cfg or get_config()
    if not (c['address'] and c['password']):
        return False, 'Email is not set up'
    if c['host'] == RESEND_HOST:
        return _send_resend(c, to, subject, text, html)
    if c['host'] == BREVO_HOST:
        return _send_brevo(c, to, subject, text, html)
    msg = EmailMessage()
    msg['From'] = formataddr((c['name'], c['address']))
    msg['To'] = to
    msg['Subject'] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype='html')
    try:
        if c['port'] == 465:
            with smtplib.SMTP_SSL(c['host'], 465, context=ssl.create_default_context(), timeout=15) as s:
                s.login(c['address'], c['password'])
                s.send_message(msg)
        else:
            with smtplib.SMTP(c['host'], c['port'], timeout=15) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(c['address'], c['password'])
                s.send_message(msg)
        return True, None
    except smtplib.SMTPAuthenticationError:
        if 'gmail' in c['host']:
            return False, 'Gmail refused the login. Use an App Password (not your normal password) with 2-Step Verification on.'
        return False, f"{c['host']} refused the login. Check the email address and mailbox password."
    except smtplib.SMTPException as e:  # server answered but refused (bad recipient, sender not allowed…)
        return False, f"{c['host']} refused the email: {e}"
    except (TimeoutError, OSError) as e:
        return False, f"Could not connect to {c['host']}:{c['port']} ({e}). On Railway, sending email needs the Pro plan — redeploy after upgrading."
    except Exception as e:
        return False, str(e)


RESEND_HOST = 'api.resend.com'


def _send_resend(c, to, subject, text, html=None):
    try:
        r = requests.post('https://api.resend.com/emails', timeout=15,
                          headers={'Authorization': f"Bearer {c['password']}"},
                          json={'from': formataddr((c['name'], c['address'])), 'to': [to],
                                'subject': subject, 'text': text, **({'html': html} if html else {})})
    except Exception as e:
        return False, f'Could not reach Resend: {e}'
    if r.status_code in (200, 201) and (r.json() or {}).get('id'):
        return True, None
    try:
        d = r.json()
    except ValueError:
        d = {}
    msg = d.get('message') or d.get('error') or f'HTTP {r.status_code}'
    if r.status_code in (401, 403) and 'domain' not in str(msg).lower():
        msg = f'Resend refused the API key ({msg})'
    return False, f'Resend: {msg}'


BREVO_HOST = 'api.brevo.com'


def _send_brevo(c, to, subject, text, html=None):
    """Brevo transactional API: the password field holds the API key (xkeysib-…).
    The sender address must be verified in Brevo (Senders, or the whole domain)."""
    try:
        r = requests.post('https://api.brevo.com/v3/smtp/email', timeout=15,
                          headers={'api-key': c['password'], 'accept': 'application/json'},
                          json={'sender': {'name': c['name'], 'email': c['address']}, 'to': [{'email': to}],
                                'subject': subject, 'textContent': text, **({'htmlContent': html} if html else {})})
    except Exception as e:
        return False, f'Could not reach Brevo: {e}'
    if r.status_code in (200, 201, 202):
        return True, None
    try:
        d = r.json()
    except ValueError:
        d = {}
    msg = d.get('message') or f'HTTP {r.status_code}'
    if r.status_code == 401:
        msg = f'Brevo refused the API key ({msg}). Use an API key (xkeysib-…), not the SMTP key.'
    elif 'sender' in str(msg).lower():
        msg = f'{msg} — verify this sender address in Brevo (Senders, Domains & Dedicated IPs).'
    return False, f'Brevo: {msg}'


import os
SITE_URL  = os.environ.get('SITE_URL', 'https://bigwingaming.com').rstrip('/')   # set SITE_URL on the server
SITE_HOST = SITE_URL.split('://', 1)[-1]
LOGO_URL  = SITE_URL + '/assets/images/logo.png'


def _layout(preheader, title, intro, code, after, footer_note):
    """Branded HTML email: table layout + inline styles so it renders in Gmail, Outlook and Apple Mail."""
    from html import escape as e
    digits = ''.join(f'<span style="display:inline-block;width:40px;margin:0 3px;padding:12px 0;background:#0d1527;'
                     f'border:1px solid #2a3a66;border-radius:10px;color:#f0c040;font-size:28px;font-weight:800;'
                     f'font-family:Menlo,Consolas,monospace">{d}</span>' for d in code)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light"><meta name="supported-color-schemes" content="dark light"><title>{e(title)}</title></head>
<body style="margin:0;padding:0;background:#070b16;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{e(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#070b16" style="background:#070b16;">
<tr><td align="center" style="padding:32px 12px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:480px;">
    <tr><td align="center" style="padding-bottom:18px;">
      <a href="{SITE_URL}" style="text-decoration:none;">
        <img src="{LOGO_URL}" width="72" height="72" alt="BigWin Gaming" style="display:block;border:0;width:72px;height:72px;">
      </a>
      <div style="margin-top:10px;font-family:Georgia,'Times New Roman',serif;font-size:22px;font-weight:bold;letter-spacing:4px;color:#f0c040;">BIGWIN GAMING</div>
    </td></tr>
    <tr><td bgcolor="#111a30" style="background:#111a30;border:1px solid #1e2d4a;border-radius:18px;padding:30px 26px;font-family:Helvetica,Arial,sans-serif;">
      <h1 style="margin:0 0 10px;font-size:21px;line-height:1.3;color:#ffffff;font-weight:700;">{e(title)}</h1>
      <p style="margin:0 0 22px;font-size:15px;line-height:1.6;color:#cbd5e1;">{intro}</p>
      <div style="text-align:center;margin:0 0 8px;white-space:nowrap;">{digits}</div>
      <p style="margin:0 0 22px;text-align:center;font-size:13px;color:#94a3b8;">This code expires in <strong style="color:#e2e8f0;">10 minutes</strong>.</p>
      <p style="margin:0 0 18px;font-size:14px;line-height:1.6;color:#cbd5e1;">{after}</p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="background:#1a1408;border:1px solid #5c4610;border-radius:12px;padding:12px 14px;font-size:13px;line-height:1.5;color:#f6d77a;">
          🔒 <strong>Never share this code.</strong> BigWin Gaming staff will never ask you for it — not by chat, text or phone.
        </td></tr></table>
    </td></tr>
    <tr><td align="center" style="padding:22px 10px 0;font-family:Helvetica,Arial,sans-serif;font-size:12px;line-height:1.6;color:#64748b;">
      {footer_note}<br>
      <a href="{SITE_URL}" style="color:#c9a227;text-decoration:none;">{SITE_HOST}</a> &nbsp;·&nbsp;
      <a href="{SITE_URL}/support.html" style="color:#c9a227;text-decoration:none;">Support</a> &nbsp;·&nbsp;
      <a href="{SITE_URL}/privacy" style="color:#c9a227;text-decoration:none;">Privacy</a><br>
      © 2026 BigWin Gaming. 18+ only. Please play responsibly.
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""


def code_email(code, purpose, username=''):
    """(subject, plain text, html) for a 6-digit code email."""
    from html import escape as e
    hi = f'Hi {username},' if username else 'Hi,'
    if purpose == 'reset':
        subject = f'{code} is your BigWin Gaming password reset code'
        intro = f'{e(hi)}<br>We got a request to reset the password for your BigWin Gaming account. Enter this code to choose a new password:'
        after = "Didn't ask to reset your password? You can ignore this email — your password stays the same and your account is safe."
        text = (f"{hi}\n\nWe got a request to reset the password for your BigWin Gaming account.\n\n"
                f"Your password reset code: {code}\n\nThis code expires in 10 minutes.\n\n"
                "Didn't ask for this? Ignore this email — your password stays the same.\n\n"
                f"Never share this code. BigWin Gaming staff will never ask you for it.\n\n— BigWin Gaming\n{SITE_HOST}")
        title, pre, note = 'Reset your password', f'Your password reset code is {code}', 'You received this because a password reset was requested for your account.'
    else:
        subject = f'{code} is your BigWin Gaming verification code'
        intro = f'{e(hi)}<br>Thanks for joining BigWin Gaming! Enter this code to verify your email address:'
        after = "Verifying your email keeps your account safe and lets you reset your password if you ever forget it. Didn't request this? Just ignore this email."
        text = (f"{hi}\n\nThanks for joining BigWin Gaming! Enter this code to verify your email address.\n\n"
                f"Your verification code: {code}\n\nThis code expires in 10 minutes.\n\n"
                "Didn't request this? Just ignore this email.\n\n"
                f"Never share this code. BigWin Gaming staff will never ask you for it.\n\n— BigWin Gaming\n{SITE_HOST}")
        title, pre, note = 'Verify your email', f'Your verification code is {code}', 'You received this because this email was added to a BigWin Gaming account.'
    return subject, text, _layout(pre, title, intro, code, e(after), note)


def test_email():
    """(subject, text, html) for the admin 'Send test' button."""
    text = 'This test email confirms your site can send verification and password-reset codes.'
    return ('BigWin Gaming email is working ✅', text,
            _layout('Your BigWin Gaming email settings work', 'Email is working ✅',
                    'Your site can now send <strong>verification</strong> and <strong>password reset</strong> codes. '
                    'Here is what players will see:', '123456', 'This is only a test — no action needed.',
                    'Sent from your BigWin Gaming admin settings.'))
