"""Admin notifications on Telegram.

Settings live in site_settings (set from Admin → Payment Methods → Telegram):
  telegram_bot_token   bot token from @BotFather
  telegram_chat_id     one or more chat ids, comma separated (a person, group or channel)
  telegram_events      JSON list of enabled categories (missing = all on)

Messages are sent from a background thread: a slow or broken Telegram never
slows down or breaks a player's request.
"""
import html
import json
import threading
import requests

from database import get_db

CATEGORIES = {
    'money':    '💰 Money — deposits, payments, cashouts, wallet changes',
    'games':    '🎮 Games — loads, cash-outs to wallet, new game accounts',
    'players':  '🙋 Players — new signups',
    'problems': '⚠️ Problems — failed loads, paid-but-not-loaded, refused payments',
    'admin':    '🛠 Admin changes — games on/off, backends attached or removed',
    'support':  '💬 Support — player messages (reply to them in Telegram to answer)',
}


def _setting(db, key):
    row = db.execute('SELECT value FROM site_settings WHERE key=?', (key,)).fetchone()
    return (row['value'] if row else '') or ''


def get_config():
    db = get_db()
    try:
        token = _setting(db, 'telegram_bot_token')
        chats = _setting(db, 'telegram_chat_id')
        raw   = _setting(db, 'telegram_events')
    finally:
        db.close()
    try:
        events = json.loads(raw) if raw else list(CATEGORIES)
    except ValueError:
        events = list(CATEGORIES)
    return {'token': token, 'chats': [c.strip() for c in chats.split(',') if c.strip()], 'events': events}


def api(token, method, payload):
    r = requests.post(f'https://api.telegram.org/bot{token}/{method}', json=payload, timeout=10)
    d = r.json()
    if not d.get('ok'):
        raise RuntimeError(d.get('description') or f'HTTP {r.status_code}')
    return d.get('result')


def send_tracked(text, token, chats, reply_to=None):
    """Send to every chat. Returns ([(chat_id, message_id)], last_error)."""
    sent, last_err = [], None
    for chat in chats:
        try:
            payload = {'chat_id': chat, 'text': text[:4000], 'parse_mode': 'HTML', 'disable_web_page_preview': True}
            if reply_to:
                payload['reply_parameters'] = {'message_id': reply_to, 'allow_sending_without_reply': True}
            m = api(token, 'sendMessage', payload)
            sent.append((str(chat), m['message_id']))
        except Exception as e:
            last_err = str(e)
    return sent, last_err


def send_now(text, token=None, chats=None):
    """Send right away. Returns (ok, error) — used by the admin 'Send test' button."""
    if token is None or chats is None:
        cfg = get_config()
        token, chats = cfg['token'], cfg['chats']
    if not token or not chats:
        return False, 'Telegram is not set up'
    _sent, last_err = send_tracked(text, token, chats)
    return last_err is None, last_err


def set_webhook(token, url, secret):
    """Point the bot at our webhook so replies to support messages reach the site."""
    try:
        api(token, 'setWebhook', {'url': url, 'secret_token': secret, 'allowed_updates': ['message', 'callback_query'],
                                  'drop_pending_updates': True})
        return True, None
    except Exception as e:
        return False, str(e)


def notify(category, text):
    """Fire-and-forget: send `text` if Telegram is set up and `category` is switched on."""
    def run():
        try:
            cfg = get_config()
            if cfg['token'] and cfg['chats'] and category in cfg['events']:
                send_now(text, cfg['token'], cfg['chats'])
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def esc(v):
    return html.escape(str(v if v is not None else ''))
