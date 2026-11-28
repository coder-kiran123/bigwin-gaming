import hashlib
import hmac
import json
import os
import re
import secrets as _secrets
import bcrypt as _bcrypt
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, jsonify, make_response, redirect, request, send_from_directory
from werkzeug.utils import safe_join
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
# Load settings from the project's .env file (local dev). On a host, set real environment variables instead.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
except ImportError:
    pass

from database import init_db, get_db
from game_apis import get_api, GAME_MAP
from game_apis.loadstar import is_loadstar_key

import requests as _http

BASE_DIR = os.path.dirname(os.path.abspath(__file__))          # server/
WEB_DIR  = os.path.dirname(BASE_DIR)                            # project root: the website files

# ── Game-balance in-memory cache (reduces proxy calls) ───────────────────────
# Key: (player_id, game)  Value: (balance, fetched_at_unix)
_BAL_CACHE: dict = {}
_BAL_CACHE_TTL = 180   # seconds — balance stays fresh for 3 minutes

# ── Admin auth ───────────────────────────────────────────────────────────
import time as _time
ADMIN_PASSWORD   = os.environ.get('ADMIN_PASSWORD', '')   # required — admin login is off until set
# Signing secret: SECRET_KEY, or a random one kept in the database (set by _load_secret() at startup).
# Never a value written in the code — the code was publicly downloadable.
_ADMIN_SECRET    = os.environ.get('SECRET_KEY', '')

def _make_admin_token():
    ts  = str(int(_time.time()))
    sig = hmac.new(_ADMIN_SECRET.encode(), (ADMIN_PASSWORD + ts).encode(), hashlib.sha256).hexdigest()[:40]
    return f"{ts}.{sig}"

def _verify_admin_token(token):
    if not token:
        return False
    try:
        ts, sig = token.split('.', 1)
        if int(_time.time()) - int(ts) > 86400 * 7:   # 7-day expiry
            return False
        expected = hmac.new(_ADMIN_SECRET.encode(), (ADMIN_PASSWORD + ts).encode(), hashlib.sha256).hexdigest()[:40]
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False

# ── Auth decorators ──────────────────────────────────────────────────────

def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Admin-Token', '')
        if not _verify_admin_token(token):
            return jsonify({'success': False, 'msg': 'Admin authentication required'}), 401
        return f(*args, **kwargs)
    return decorated

def _make_player_token(pid):
    ts  = str(int(_time.time()))
    sig = hmac.new(_ADMIN_SECRET.encode(), f'{pid}:{ts}'.encode(), hashlib.sha256).hexdigest()[:40]
    return f'{pid}:{ts}:{sig}'

def _verify_player_token(token, pid):
    try:
        parts = token.split(':')
        if len(parts) != 3:
            return False
        t_pid, ts, sig = parts
        if int(t_pid) != int(pid):
            return False
        if _time.time() - int(ts) > 86400 * 30:   # 30-day expiry
            return False
        expected = hmac.new(_ADMIN_SECRET.encode(), f'{pid}:{ts}'.encode(), hashlib.sha256).hexdigest()[:40]
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False

def require_player(f):
    """Verify the caller is the player whose pid is in the URL."""
    @wraps(f)
    def decorated(*args, **kwargs):
        pid   = kwargs.get('pid')
        token = request.headers.get('X-Player-Token', '')
        if not token or not _verify_player_token(token, pid):
            return jsonify({'success': False, 'msg': 'Player authentication required'}), 401
        return f(*args, **kwargs)
    return decorated

# ── KeyHub payment gateway ────────────────────────────────────────────────
KEYHUB_BASE     = 'https://www.keyhubsolutions.com'

def _get_keyhub_key():
    """Read KeyHub API key: DB value takes priority over env var so admin can update without Railway."""
    try:
        db  = get_db()
        row = db.execute("SELECT value FROM site_settings WHERE key='keyhub_api_key'").fetchone()
        db.close()
        if row and row['value']:
            return row['value']
    except Exception:
        pass
    return os.environ.get('KEYHUB_API_KEY', '')

KEYHUB_API_KEY  = os.environ.get('KEYHUB_API_KEY', '')  # legacy — use _get_keyhub_key() for live value
_DEP_SIG_SECRET = os.environ.get('SECRET_KEY', '')
_KEYHUB_METHOD_MAP = {
    'cashapp':    'ecashapp',
    'card':       'card',
    'apple_pay':  'applepay',
    'google_pay': 'googlepay',
    'bitcoin':    'BTC',
    'btc':        'BTC',
    'eth':        'ETH',
    'usdt':       'USDT_TRC20',
}

def _dep_sig(dep_id):
    """HMAC signature for deposit return URL — verifies the redirect came from KeyHub."""
    return hmac.new(
        _DEP_SIG_SECRET.encode(), str(dep_id).encode(), hashlib.sha256
    ).hexdigest()[:24]

def _keyhub_collect(amount, customer_name='', method='cashapp', redirect_url=''):
    api_key = _get_keyhub_key()
    if not api_key:
        return None, 'KeyHub not configured — add API key in Admin → Payment Methods'
    km = _KEYHUB_METHOD_MAP.get(str(method).lower(), 'ecashapp')
    # KeyHub takes one `method`; payment_methods kept for older KeyHub builds.
    payload = {'amount': round(float(amount), 2), 'currency': 'USD', 'method': km, 'payment_methods': km}
    if customer_name:
        payload['customer_name'] = customer_name
    if redirect_url:
        # try common redirect param names; KeyHub will ignore unknown ones
        payload['redirect_url'] = redirect_url
        payload['return_url']   = redirect_url
        payload['success_url']  = redirect_url
    try:
        r = _http.post(
            f'{KEYHUB_BASE}/api/v1/collect',
            json=payload,
            headers={'X-API-Key': api_key, 'Authorization': f'Bearer {api_key}'},
            timeout=15,
        )
        d = r.json()
        if r.status_code == 201:
            return d, None
        return None, d.get('error', f'KeyHub HTTP {r.status_code}')
    except Exception as e:
        return None, str(e)


# KeyHub checkouts only take these amounts with Cash App / Apple Pay / Google Pay.
KEYHUB_PAY_AMOUNTS = (9.99, 14.99, 17.99, 19.99, 24.99, 29.99, 30.99, 39.99, 49.99, 59.99,
                      99.99, 124.99, 129.99, 149.99, 199.99)
KEYHUB_PAY_METHODS = [('cashapp', 'Cash App'), ('apple_pay', 'Apple Pay'), ('google_pay', 'Google Pay')]

def _keyhub_status(reference):
    """Ask KeyHub whether a checkout was paid. Never trust a redirect or the browser.
    Returns ('paid' | 'open' | 'failed' | 'unknown', paid_amount or None, error)."""
    api_key = _get_keyhub_key()
    if not api_key or not reference:
        return 'unknown', None, 'KeyHub not configured or no payment reference'
    try:
        r = _http.get(f'{KEYHUB_BASE}/api/v1/payment-status', params={'reference': reference},
                      headers={'X-API-Key': api_key, 'Authorization': f'Bearer {api_key}'}, timeout=15)
        d = r.json()
    except Exception as e:
        return 'unknown', None, str(e)
    if r.status_code != 200:
        return 'unknown', None, d.get('error', f'KeyHub HTTP {r.status_code}')
    st = d.get('status')
    amt = d.get('amount')
    if st == 'completed':
        return 'paid', float(amt) if amt is not None else None, None
    if st in ('failed', 'expired'):
        return 'failed', None, None
    return 'open', None, None


def _keyhub_payout(amount, recipient_name):
    api_key = _get_keyhub_key()
    if not api_key:
        return None, 'KeyHub not configured — add API key in Admin → Payment Methods'
    try:
        r = _http.post(
            f'{KEYHUB_BASE}/api/v1/payout',
            json={'amount': float(amount), 'recipient_name': recipient_name},
            headers={'X-API-Key': api_key},
            timeout=15,
        )
        d = r.json()
        if r.status_code == 201:
            return d, None
        return None, d.get('error', f'KeyHub HTTP {r.status_code}')
    except Exception as e:
        return None, str(e)

app = Flask(__name__)
# Railway's proxy sits in front of the app: take the player's real IP / https from its headers.
# Without this every player shared the proxy's IP, so rate limits (e.g. 20 signups/hour) were site-wide.
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
_ALLOWED_ORIGIN = os.environ.get('ALLOWED_ORIGIN', '*')
CORS(app, origins=_ALLOWED_ORIGIN, supports_credentials=False)
limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri='memory://')


@app.errorhandler(429)
def _too_many(e):
    # JSON like every other API answer, so pages can show it (an HTML page made signup fall into "demo mode")
    return jsonify({'success': False, 'msg': 'Too many attempts. Please wait a minute and try again.'}), 429

# ── Cache helpers ─────────────────────────────────────────────────────────
def _cache(response, seconds):
    response.headers['Cache-Control'] = f'public, max-age={seconds}'
    return response

def _no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response

_ASSET_REF = re.compile(r'''(\b(?:src|href)=["'])([^"':?#]+\.(?:js|css))(?:\?[^"']*)?(["'])''')


def _versioned_html(directory, filename):
    """Page HTML with ?v=<last change> on every local .js/.css, so phones fetch a file again as soon
    as it changes instead of reusing a cached copy (a stale dashboard.js stayed for days)."""
    path = safe_join(directory, filename)
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as f:
        html = f.read()

    def add_version(m):
        ref = m.group(2)
        asset = os.path.join(WEB_DIR, ref.lstrip('/')) if ref.startswith('/') else os.path.join(os.path.dirname(path), ref)
        try:
            v = int(os.path.getmtime(asset))
        except OSError:
            return m.group(0)
        return f'{m.group(1)}{ref}?v={v}{m.group(3)}'
    return _ASSET_REF.sub(add_version, html)


def _serve(directory, filename, cache_seconds=0):
    if filename.endswith('.html'):
        html = _versioned_html(directory, filename)
        if html is not None:
            return _no_cache(make_response(html, 200, {'Content-Type': 'text/html; charset=utf-8'}))
    resp = make_response(send_from_directory(directory, filename))
    return _cache(resp, cache_seconds) if cache_seconds else _no_cache(resp)

_STATIC_EXT = {'.js', '.css', '.webp', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico', '.woff', '.woff2'}

# ── Serve frontend files (HTML/CSS/JS/images) ────────────────────────────
# Biggest legitimate body is a ~3 MB screenshot as base64; refuse anything far larger
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
_IMG_DATA_URI = re.compile(r'^data:image/(png|jpe?g|webp|gif);base64,')


@app.route('/')
def root():
    return _serve(WEB_DIR, 'index.html')

@app.route('/login')
@app.route('/signup')
@app.route('/register')
def auth_page():
    return _serve(WEB_DIR, 'auth.html')

@app.route('/admin')
@app.route('/admin/')
def admin_root():
    return _serve(os.path.join(WEB_DIR, 'admin'), 'index.html')

@app.route('/support-portal')
@app.route('/how-to-play')
@app.route('/guide')
def guide_page():
    return _serve(WEB_DIR, 'guide.html')


@app.route('/privacy')
def privacy_page():
    return _serve(WEB_DIR, 'privacy.html')


@app.route('/terms')
def terms_page():
    return _serve(WEB_DIR, 'terms.html')


@app.route('/support-portal.html')
def support_portal():
    return _serve(WEB_DIR, 'support-portal.html')

@app.route('/api/admin/ping')
def admin_ping():
    return jsonify({'status': 'ok', 'ts': int(_time.time()), 'pw_set': bool(os.environ.get('ADMIN_PASSWORD'))})

@app.route('/api/admin/login', methods=['POST'])
@limiter.limit('5 per minute; 20 per hour')
def admin_login():
    data = request.get_json() or {}
    pw   = data.get('password', '').strip()
    if not ADMIN_PASSWORD:
        return err('Admin login is disabled: set the ADMIN_PASSWORD environment variable on the server.', 503)
    if not hmac.compare_digest(pw, ADMIN_PASSWORD):
        return jsonify({'success': False, 'msg': 'Invalid password'}), 401
    return jsonify({'success': True, 'token': _make_admin_token()})

@app.route('/api/admin/verify', methods=['POST'])
def admin_verify():
    token = (request.get_json() or {}).get('token', '')
    if _verify_admin_token(token):
        return jsonify({'success': True})
    return jsonify({'success': False, 'msg': 'Session expired'}), 401

@app.route('/admin/<path:filename>')
def admin_static(filename):
    # Admin files never cached — they update frequently
    return _serve(os.path.join(WEB_DIR, 'admin'), filename, 0)

# Only these are served from the app folder — never .py source, databases, Procfile, dotfiles…
_PUBLIC_EXT = _STATIC_EXT | {'.html', '.json', '.txt', '.xml', '.webmanifest', '.pdf', '.mp4', '.webm', '.mp3'}
_PRIVATE_NAMES = {'requirements.txt', 'runtime.txt', 'procfile'}


@app.route('/<path:filename>')
def static_files(filename):
    parts = filename.replace('\\', '/').split('/')
    ext = os.path.splitext(filename)[1].lower()
    if (ext not in _PUBLIC_EXT or any(p.startswith('.') or p in ('server', 'game_apis', '__pycache__') for p in parts)
            or parts[-1].lower() in _PRIVATE_NAMES):
        return err('Not found', 404)
    # Images/fonts may be kept a week; .js/.css are re-checked every time (a 304 when unchanged)
    # so a deploy reaches phones right away instead of up to 7 days later.
    secs = 86400 * 7 if ext in _STATIC_EXT - {'.js', '.css'} else 0
    return _serve(WEB_DIR, filename, secs)

# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────

def hash_password(pw):
    return _bcrypt.hashpw(pw.encode(), _bcrypt.gensalt()).decode()

def check_password(pw, stored_hash):
    """Verify password against bcrypt hash. Falls back to SHA256 for legacy accounts."""
    if stored_hash.startswith('$2'):
        return _bcrypt.checkpw(pw.encode(), stored_hash.encode())
    # Legacy SHA256 hash — accept on first login; caller should re-hash and save
    return hashlib.sha256(pw.encode()).hexdigest() == stored_hash

def _upgrade_password_hash(db, player_id, pw):
    """Re-hash a legacy SHA256 password to bcrypt on successful login."""
    db.execute('UPDATE players SET password_hash=? WHERE id=?', (hash_password(pw), player_id))
    db.commit()

def row_to_dict(row):
    return dict(row) if row else None

def rows_to_list(rows):
    return [dict(r) for r in rows]


def ok(data=None, msg='OK'):
    return jsonify({'success': True, 'msg': msg, 'data': data}), 200

def err(msg, code=400):
    return jsonify({'success': False, 'msg': msg}), code


# ─────────────────────────────────────────
#  BACKEND ATTACHMENTS
# ─────────────────────────────────────────

@app.route('/api/debug/juwa', methods=['GET'])
@require_admin
def debug_juwa():
    import requests, random, os
    proxy_url = os.environ.get('FIXIE_URL') or os.environ.get('QUOTAGUARDSTATIC_URL')
    proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None
    out = {'proxy_url': proxy_url or 'NOT SET', 'steps': []}

    # Step 1: check outbound IP
    try:
        r = requests.get('http://httpbin.org/ip', proxies=proxies, timeout=8)
        out['steps'].append({'step': 'outbound_ip', 'ok': True, 'ip': r.json().get('origin')})
    except Exception as e:
        out['steps'].append({'step': 'outbound_ip', 'ok': False, 'error': str(e)})

    # Step 2: captcha fetch
    try:
        check_code = random.randint(10_000_000, 99_999_999)
        r = requests.get('https://ht.juwa777.com/api/agent/captcha',
                         params={'t': check_code}, proxies=proxies, verify=False, timeout=10)  # juwa uses self-signed cert
        is_png = r.content[:4] == b'\x89PNG'
        out['steps'].append({'step': 'captcha', 'ok': is_png, 'status': r.status_code,
                              'content_type': r.headers.get('Content-Type'), 'is_png': is_png})
    except Exception as e:
        out['steps'].append({'step': 'captcha', 'ok': False, 'error': str(e)})

    # Step 3: ddddocr
    try:
        import ddddocr
        ocr = ddddocr.DdddOcr(show_ad=False)
        out['steps'].append({'step': 'ddddocr', 'ok': True})
    except Exception as e:
        out['steps'].append({'step': 'ddddocr', 'ok': False, 'error': str(e)})
        return ok(out)

    # Step 4: full login attempt
    try:
        from PIL import Image
        import io as _io
        check_code = random.randint(10_000_000, 99_999_999)
        r = requests.get('https://ht.juwa777.com/api/agent/captcha',
                         params={'t': check_code}, proxies=proxies, verify=False, timeout=10)  # juwa uses self-signed cert
        img = Image.open(_io.BytesIO(r.content)).convert('RGB')
        buf = _io.BytesIO(); img.save(buf, format='PNG')
        cap_code = ocr.classification(buf.getvalue())
        out['steps'].append({'step': 'captcha_solved', 'ok': True, 'code': cap_code})

        _j_user = os.environ.get('DEBUG_JUWA_USER', '')
        _j_pass = os.environ.get('DEBUG_JUWA_PASS', '')
        r2 = requests.post('https://ht.juwa777.com/api/agent/agentLogin',
            json={'agent_name': _j_user, 'agent_pwd': _j_pass,
                  'agent_code': cap_code, 'google_code': '', 't': check_code,
                  'browser_type': 'chrome', 'device_type': 'desktop',
                  '__visitorId': '3927fbca2b4c0e862a73c04cc7ddb64d'},
            proxies=proxies, verify=False, timeout=15)  # juwa uses self-signed cert
        resp = r2.json()
        out['steps'].append({'step': 'login', 'ok': resp.get('code') == 200,
                              'code': resp.get('code'), 'msg': resp.get('msg')})
    except Exception as e:
        out['steps'].append({'step': 'login', 'ok': False, 'error': str(e)})

    # Step 5: test via Juwa2API class (same as attach flow)
    try:
        api = get_api('juwa', os.environ.get('DEBUG_JUWA_USER', ''), os.environ.get('DEBUG_JUWA_PASS', ''))
        s2 = api._session()
        ok_conn, msg_conn = api._login(s2)
        out['steps'].append({
            'step': 'api_class_test', 'ok': ok_conn, 'msg': msg_conn,
            'proxies_set': bool(api._proxies), 'proxy_val': str(api._proxies)
        })
    except Exception as e:
        out['steps'].append({'step': 'api_class_test', 'ok': False, 'error': str(e)})

    return ok(out)


@app.route('/api/debug/attach-test', methods=['GET'])
@require_admin
def debug_attach_test():
    game     = request.args.get('game', 'juwa')
    username = request.args.get('u', '')
    password = request.args.get('p', '')
    base_url = request.args.get('url', '')
    api = get_api(game, username, password, '', base_url)
    if not api:
        return ok({'error': f'Unknown game: {game}'})
    ok_conn, msg_conn = api.test_connection()
    return ok({
        'game': game, 'base_url': api.base_url,
        'proxies': str(api._proxies),
        'ok': ok_conn, 'msg': msg_conn
    })


@app.route('/api/backends', methods=['GET'])
@require_admin
def get_backends():
    db = get_db()
    rows = db.execute('SELECT * FROM backends ORDER BY created_at DESC').fetchall()
    db.close()
    result = rows_to_list(rows)
    # mask passwords in response
    for b in result:
        b['is_loadstar'] = is_loadstar_key(b['password'])
        b['password'] = '••••••'
    return ok(result)


@app.route('/api/backends/attach-loadstar', methods=['POST'])
@require_admin
def attach_loadstar_all():
    """Attach every Loadstar game this site supports in one go."""
    data     = request.json or {}
    api_key  = data.get('api_key', '').strip()
    base_url = data.get('base_url', '').strip()
    username = data.get('username', '').strip() or 'loadstar'
    if not is_loadstar_key(api_key):
        return err('That is not a Loadstar API key (it starts with ls_live_)')

    games, msg = get_api('', username, api_key, '', base_url).list_games()
    if games is None:
        return err(msg)

    db  = get_db()
    now = datetime.utcnow().isoformat()
    added, skipped, unsupported = [], [], []
    seen = set()
    # Prefer an enabled entry when Loadstar has the same game twice
    for g in sorted(games, key=lambda g: bool(g.get('disabled'))):
        key, label = g.get('game'), g.get('label') or g.get('game')
        if key in seen:
            continue
        seen.add(key)
        if key not in GAME_MAP:
            unsupported.append(label)
            continue
        if db.execute('SELECT id FROM backends WHERE game = ?', (key,)).fetchone():
            skipped.append(label)
            continue
        status = 'failed' if g.get('disabled') or g.get('down') else 'connected'
        db.execute(
            '''INSERT INTO backends (game, name, username, password, token, base_url, status, last_tested)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (key, f'{label} (Loadstar)', username, api_key, g['id'], base_url, status, now)
        )
        added.append({'game': key, 'label': label, 'status': status})
    db.commit()
    db.close()

    parts = [f'Attached {len(added)} game(s)']
    if skipped:
        parts.append(f'skipped {len(skipped)} already attached ({", ".join(skipped)})')
    if unsupported:
        parts.append(f'{len(unsupported)} not on this site ({", ".join(unsupported)})')
    return ok({'added': added, 'skipped': skipped, 'unsupported': unsupported}, ' · '.join(parts))


def _loadstar_backend(bid):
    db  = get_db()
    row = db.execute('SELECT * FROM backends WHERE id = ?', (bid,)).fetchone()
    db.close()
    if not row:
        return None, err('Backend not found', 404)
    b = dict(row)
    if not is_loadstar_key(b['password']):
        return None, err('This backend is not connected through Loadstar')
    return b, None


@app.route('/api/backends/<int:bid>/loadstar-accounts', methods=['GET'])
@require_admin
def loadstar_accounts(bid):
    b, e = _loadstar_backend(bid)
    if e:
        return e
    api = get_api(b['game'], b['username'], b['password'], b['token'], b['base_url'])
    accounts, msg = api.list_accounts()
    if accounts is None:
        return err(msg)
    return ok({'under': b.get('loadstar_under') or '', 'accounts': accounts})


@app.route('/api/backends/<int:bid>/loadstar-under', methods=['POST'])
@require_admin
def set_loadstar_under(bid):
    b, e = _loadstar_backend(bid)
    if e:
        return e
    under = ((request.json or {}).get('under') or '').strip()
    if under not in ('', 'admin'):
        api = get_api(b['game'], b['username'], b['password'], b['token'], b['base_url'])
        accounts, msg = api.list_accounts()
        if accounts is None:
            return err(msg)
        if not any(a['id'] == under for a in accounts):
            return err('That game account is not yours in Loadstar')
    db = get_db()
    db.execute('UPDATE backends SET loadstar_under=? WHERE id=?', (under, bid))
    db.commit()
    db.close()
    return ok({'under': under}, 'Saved')


@app.route('/api/backends/attach', methods=['POST'])
@require_admin
def attach_backend():
    data     = request.json or {}
    game     = data.get('game', '').strip()
    name     = data.get('name', '').strip()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    token    = data.get('token', '').strip()
    base_url = data.get('base_url', '').strip()
    do_test  = data.get('test_connection', True)

    if not game:     return err('Game is required')
    if not name:     return err('Attachment name is required')
    if not username: return err('Backend username is required')
    if not password: return err('Backend password is required')

    status = 'unknown'
    msg    = 'Attached without testing'

    if do_test:
        api = get_api(game, username, password, token, base_url)
        if not api:
            return err(f'Unknown game: {game}')
        connected, msg = api.test_connection()
        status = 'connected' if connected else 'failed'
        token = getattr(api, '_token', None) or token

    db = get_db()
    try:
        cursor = db.execute(
            '''INSERT INTO backends (game, name, username, password, token, base_url, status, last_tested)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (game, name, username, password, token or '', base_url, status, datetime.utcnow().isoformat())
        )
        backend_id = cursor.lastrowid
        db.commit()
    finally:
        db.close()

    return ok({'id': backend_id, 'status': status, 'message': msg}, msg)


@app.route('/api/backends/<int:bid>', methods=['DELETE'])
@require_admin
def delete_backend(bid):
    db = get_db()
    db.execute('DELETE FROM backends WHERE id = ?', (bid,))
    db.commit()
    db.close()
    return ok(msg='Backend removed')


@app.route('/api/backends/<int:bid>/toggle', methods=['POST'])
@require_admin
def toggle_backend(bid):
    db  = get_db()
    row = db.execute('SELECT enabled FROM backends WHERE id = ?', (bid,)).fetchone()
    if not row:
        db.close()
        return err('Backend not found', 404)
    new_val = 0 if row['enabled'] else 1
    db.execute('UPDATE backends SET enabled = ? WHERE id = ?', (new_val, bid))
    db.commit()
    db.close()
    return ok({'enabled': bool(new_val)}, 'Game turned on — players can see and use it' if new_val else
              'Game turned off — hidden from players; existing players can only cash out')


@app.route('/api/backends/<int:bid>/test', methods=['POST'])
@require_admin
def test_backend(bid):
    db   = get_db()
    row  = db.execute('SELECT * FROM backends WHERE id = ?', (bid,)).fetchone()
    if not row:
        db.close()
        return err('Backend not found', 404)

    b = dict(row)
    api = get_api(b['game'], b['username'], b['password'], b['token'], b['base_url'])
    if not api:
        db.close()
        return err(f'No API module for game: {b["game"]}')

    connected, msg = api.test_connection()
    status = 'connected' if connected else 'failed'
    new_token = getattr(api, '_token', None) or b['token']
    db.execute(
        'UPDATE backends SET status=?, last_tested=?, token=? WHERE id=?',
        (status, datetime.utcnow().isoformat(), new_token or '', bid)
    )
    db.commit()
    db.close()
    return ok({'status': status, 'message': msg})


@app.route('/api/backends/<int:bid>/balance', methods=['GET'])
@require_admin
def backend_balance(bid):
    db  = get_db()
    row = db.execute('SELECT * FROM backends WHERE id = ?', (bid,)).fetchone()
    if not row:
        db.close()
        return err('Backend not found', 404)

    b   = dict(row)
    api = get_api(b['game'], b['username'], b['password'], b['token'], b['base_url'])
    if not api:
        db.close()
        return err(f'No API module for: {b["game"]}')

    bal, error = api.get_balance(b['username'])
    if bal is not None:
        db.execute('UPDATE backends SET balance=? WHERE id=?', (bal, bid))
        db.commit()
    db.close()

    if error:
        return err(error)
    return ok({'balance': bal})


# ─────────────────────────────────────────
#  PLAYER AUTH
# ─────────────────────────────────────────

def _gen_referral_code(db):
    import string as _str
    chars = _str.ascii_uppercase + _str.digits
    for _ in range(20):
        code = ''.join(_secrets.choice(chars) for _ in range(8))
        if not db.execute('SELECT id FROM players WHERE referral_code=?', (code,)).fetchone():
            return code
    return ''.join(_secrets.choice(chars) for _ in range(10))


@app.route('/api/auth/register', methods=['POST'])
@limiter.limit('5 per minute; 20 per hour')
def register():
    data          = request.json or {}
    email         = data.get('email', '').strip().lower()
    username      = data.get('username', '').strip() or email   # BigWin signs players up by email
    password      = data.get('password', '').strip()
    first_name    = data.get('first_name', '').strip()[:60]
    last_name     = data.get('last_name', '').strip()[:60]
    referred_by   = data.get('referred_by', '').strip()[:80]   # free text: the member's name, username or code
    referral_code = (data.get('referral_code', '') or referred_by).strip().upper().lstrip('#')

    if not username: return err('Email is required')
    if not password: return err('Password is required')
    if len(password) < 6: return err('Password must be at least 6 characters')

    if email and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return err('Enter a valid email address')

    db = get_db()
    existing = db.execute('SELECT id FROM players WHERE LOWER(username)=LOWER(?)', (username,)).fetchone()
    if existing:
        db.close()
        return err('That username is taken — pick another one.')
    if email and db.execute('SELECT id FROM players WHERE LOWER(email)=LOWER(?)', (email,)).fetchone():
        db.close()
        return err('That email already has an account — sign in, or use "Forgot password".')

    # Find referrer if code provided
    referrer = None
    if referral_code:
        # Exact code first; then without a shown prefix (#WZ…, or #LP / #FP from before the rebrand)
        for cand in [referral_code] + [referral_code[2:] for pre in ('BW', 'WZ', 'LP', 'FP') if referral_code.startswith(pre)]:
            referrer = db.execute(
                'SELECT id, username, fp_credits FROM players WHERE referral_code=?', (cand,)
            ).fetchone()
            if referrer:
                break
    # BigWin: "Referred by" is usually a member's name/username/email rather than a code
    if not referrer and referred_by:
        referrer = db.execute(
            'SELECT id, username, fp_credits FROM players WHERE LOWER(username)=LOWER(?) OR LOWER(email)=LOWER(?)',
            (referred_by, referred_by)
        ).fetchone()

    my_code   = _gen_referral_code(db)
    fp_start  = 1.0 + (5.0 if referrer else 0.0)  # 1 signup + 5 referral bonus

    pw_hash = hash_password(password)
    try:
        cursor = db.execute(
            'INSERT INTO players (username, email, password_hash, fp_credits, referral_code, first_name, last_name, referred_by_name) VALUES (?,?,?,?,?,?,?,?)',
            (username, email or None, pw_hash, fp_start, my_code, first_name, last_name, referred_by)
        )
        player_id = cursor.lastrowid

        db.execute(
            'INSERT INTO transactions (player_id, username, type, amount, status, notes) VALUES (?,?,?,?,?,?)',
            (player_id, username, 'signup_bonus', 1.0, 'approved', '1 BW free play bonus')
        )

        if referrer:
            # Give referrer 10 FP
            db.execute('UPDATE players SET fp_credits = fp_credits + 10 WHERE id=?', (referrer['id'],))
            db.execute(
                'INSERT INTO referrals (referrer_id, referrer_username, referred_id, referred_username) VALUES (?,?,?,?)',
                (referrer['id'], referrer['username'], player_id, username)
            )
            db.execute(
                'INSERT INTO transactions (player_id, username, type, amount, status, notes) VALUES (?,?,?,?,?,?)',
                (player_id, username, 'referral_bonus', 5.0, 'approved', f'Referred by {referrer["username"]}')
            )
            db.execute(
                'INSERT INTO transactions (player_id, username, type, amount, status, notes) VALUES (?,?,?,?,?,?)',
                (referrer['id'], referrer['username'], 'referral_bonus', 10.0, 'approved', f'Referred {username}')
            )

        db.commit()
    except Exception as e:
        db.close()
        print(f'[register] {username}: {e}')
        if re.search(r'unique|duplicate', str(e), re.I):
            return err('That username or email already has an account.')
        return err('Could not create your account right now. Please try again.')

    db.close()
    return ok({
        'id':          player_id,
        'player_id':   player_id,
        'username':    username,
        'email':       email,
        'first_name':  first_name,
        'last_name':   last_name,
        'fp_credits':  fp_start,
        'balance':     0,
        'referral_code': my_code,
        'referred_by': referrer['username'] if referrer else None,
        'token':       _make_player_token(player_id),
    }, 'Account created')


@app.route('/api/auth/refresh-token', methods=['POST'])
def refresh_player_token():
    """Issue a fresh player token to an existing session (no password needed).
    Security: player_id must match username in DB — same trust as localStorage access."""
    # Used to hand a token to anyone who knew a player id + username (no password): account takeover.
    # Old sessions now sign in again.
    return err('Please sign in again.', 401)


@app.route('/api/auth/login', methods=['POST'])
@limiter.limit('10 per minute; 50 per hour')
def login():
    data     = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return err('Username and password required')

    db  = get_db()
    # Sign in with username or email (BigWin uses email)
    row = db.execute('SELECT * FROM players WHERE LOWER(username)=LOWER(?) OR LOWER(email)=LOWER(?) ORDER BY id LIMIT 1',
                     (username, username)).fetchone()

    if not row or not check_password(password, row['password_hash']):
        db.close()
        return err('Invalid username or password', 401)

    if row['status'] == 'inactive':
        db.close()
        return err('Account is disabled. Contact support.', 403)

    # Upgrade legacy SHA256 hash to bcrypt on first successful login
    if not row['password_hash'].startswith('$2'):
        _upgrade_password_hash(db, row['id'], password)

    player = dict(row)
    player.pop('password_hash', None)
    player['token'] = _make_player_token(row['id'])
    db.close()
    return ok(player, 'Login successful')


def _find_referrer(db, text):
    """Match 'Referred by' text against a referral code, username or email."""
    text = (text or '').strip()
    if not text:
        return None
    code = text.upper().lstrip('#')
    for cand in [code] + [code[2:] for pre in ('BW', 'WZ', 'LP', 'FP') if code.startswith(pre)]:
        row = db.execute('SELECT id, username FROM players WHERE referral_code=?', (cand,)).fetchone()
        if row:
            return row
    return db.execute('SELECT id, username FROM players WHERE LOWER(username)=LOWER(?) OR LOWER(email)=LOWER(?)',
                      (text, text)).fetchone()


@app.route('/api/auth/google', methods=['POST'])
@limiter.limit('10 per minute; 50 per hour')
def google_auth():
    """Sign in / sign up with Google via Firebase Authentication.
    Body: { id_token, referred_by? }. The ID token is verified with Google's public keys — the browser
    is never trusted for who the user is. New players must give a 'Referred by' (members-only)."""
    project_id = os.environ.get('FIREBASE_PROJECT_ID', '').strip()
    if not project_id:
        return err('Google sign-in is not set up on the server (FIREBASE_PROJECT_ID is missing).', 503)
    data        = request.json or {}
    token       = data.get('id_token', '')
    referred_by = data.get('referred_by', '').strip()[:80]
    if not token:
        return err('Missing Google token')
    try:
        from google.oauth2 import id_token as _gid
        from google.auth.transport import requests as _greq
        claims = _gid.verify_firebase_token(token, _greq.Request(), audience=project_id)
    except Exception as e:
        print(f'[google_auth] token rejected: {e}')
        return err('Google sign-in could not be verified. Please try again.', 401)

    uid   = claims.get('user_id') or claims.get('sub') or ''
    email = (claims.get('email') or '').strip().lower()
    if not uid or not email or not claims.get('email_verified', False):
        return err('Your Google account has no verified email address.', 400)
    first_name, _, last_name = (claims.get('name') or '').strip().partition(' ')

    db  = get_db()
    row = db.execute('SELECT * FROM players WHERE google_uid=? OR LOWER(email)=LOWER(?) ORDER BY id LIMIT 1',
                     (uid, email)).fetchone()
    if row:
        if row['status'] == 'inactive':
            db.close()
            return err('Account is disabled. Contact support.', 403)
        if not row['google_uid']:
            db.execute('UPDATE players SET google_uid=?, email_verified=1 WHERE id=?', (uid, row['id']))
            db.commit()
        player = dict(row)
        player.pop('password_hash', None)
        player['token'] = _make_player_token(row['id'])
        db.close()
        return ok(player, 'Login successful')

    # New player
    if not referred_by:
        db.close()
        return jsonify({'success': False, 'code': 'need_referral',
                        'msg': 'No BigWin account for this Google account yet. Create one: enter who referred you, then Sign up with Google.'}), 404
    referrer = _find_referrer(db, referred_by)
    fp_start = 1.0 + (5.0 if referrer else 0.0)
    my_code  = _gen_referral_code(db)
    try:
        cur = db.execute(
            '''INSERT INTO players (username, email, password_hash, fp_credits, referral_code,
                                    first_name, last_name, referred_by_name, google_uid, email_verified)
               VALUES (?,?,?,?,?,?,?,?,?,1)''',
            (email, email, hash_password(_secrets.token_urlsafe(32)), fp_start, my_code,
             first_name[:60], last_name[:60], referred_by, uid))
        pid = cur.lastrowid
        db.execute('INSERT INTO transactions (player_id, username, type, amount, status, notes) VALUES (?,?,?,?,?,?)',
                   (pid, email, 'signup_bonus', 1.0, 'approved', '1 BW free play bonus'))
        if referrer:
            db.execute('UPDATE players SET fp_credits = fp_credits + 10 WHERE id=?', (referrer['id'],))
            db.execute('INSERT INTO referrals (referrer_id, referrer_username, referred_id, referred_username) VALUES (?,?,?,?)',
                       (referrer['id'], referrer['username'], pid, email))
        db.commit()
    except Exception as e:
        db.close()
        print(f'[google_auth] create {email}: {e}')
        return err('Could not create your account right now. Please try again.')
    row = db.execute('SELECT * FROM players WHERE id=?', (pid,)).fetchone()
    db.close()
    player = dict(row)
    player.pop('password_hash', None)
    player['token'] = _make_player_token(pid)
    return ok(player, 'Account created')


@app.route('/api/players/<int:pid>/change-password', methods=['POST'])
@require_player
def change_password(pid):
    data         = request.get_json() or {}
    current_pw   = data.get('current_password', '').strip()
    new_pw       = data.get('new_password', '').strip()
    if not current_pw or not new_pw:
        return err('current_password and new_password are required')
    if len(new_pw) < 6:
        return err('New password must be at least 6 characters')
    db  = get_db()
    row = db.execute('SELECT password_hash FROM players WHERE id=?', (pid,)).fetchone()
    if not row:
        db.close()
        return err('Player not found', 404)
    if not check_password(current_pw, row['password_hash']):
        db.close()
        return err('Current password is incorrect', 401)
    db.execute('UPDATE players SET password_hash=? WHERE id=?', (hash_password(new_pw), pid))
    db.commit()
    db.close()
    return ok({}, 'Password changed successfully')


# ── Email codes (forgot password + email verification) ──
import mailer as _mailer
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _email_code_start(db, username, purpose, email):
    """Make a code, store its hash (works on every gunicorn worker), email it. Returns (ok, error)."""
    import time
    code = str(_secrets.randbelow(900000) + 100000)
    key  = f'{purpose}:{username}'
    db.execute('DELETE FROM email_codes WHERE key=?', (key,))
    db.execute('INSERT INTO email_codes (key, username, purpose, email, code_hash, expires, tries) VALUES (?,?,?,?,?,?,0)',
               (key, username, purpose, email, _otp_hash(key, code), int(time.time()) + 600))
    db.commit()
    subject, body, html = _mailer.code_email(code, purpose, username)
    return _mailer.send(email, subject, body, html=html)


def _email_code_check(db, username, purpose, code):
    """Returns (email, None) when the code is right — and uses it up — else (None, error)."""
    import time
    key = f'{purpose}:{username}'
    row = db.execute('SELECT * FROM email_codes WHERE key=?', (key,)).fetchone()
    if not row:
        return None, 'No code requested. Please request a new code.'
    if time.time() > row['expires'] or row['tries'] >= _OTP_MAX_TRIES:
        db.execute('DELETE FROM email_codes WHERE key=?', (key,))
        db.commit()
        return None, 'Code expired. Please request a new one.'
    code = re.sub(r'\D', '', str(code or ''))
    if not hmac.compare_digest(row['code_hash'], _otp_hash(key, code)):
        db.execute('UPDATE email_codes SET tries = tries + 1 WHERE key=?', (key,))
        db.commit()
        left = _OTP_MAX_TRIES - row['tries'] - 1
        return None, (f'Invalid code. {left} tries left.' if left > 0 else 'Invalid code. Please request a new one.')
    used = db.execute('DELETE FROM email_codes WHERE key=? AND code_hash=?', (key, row['code_hash']))
    db.commit()
    if used.rowcount == 0:
        return None, 'Code already used.'
    return row['email'], None


@app.route('/api/players/reset-password/send', methods=['POST'])
@limiter.limit('3 per minute; 10 per hour')
def reset_password_send():
    """Forgot password, step 1: email a code to the address on the account."""
    username = ((request.get_json() or {}).get('username') or '').strip()
    if not username:
        return err('Enter your username')
    if not _mailer.configured():
        return err('Password reset by email is not available right now — please contact support.')
    db  = get_db()
    row = db.execute('SELECT id, email FROM players WHERE username=?', (username,)).fetchone()
    if not row or not row['email']:
        db.close()
        return err('No email on file for that username — please contact support.')
    sent, e = _email_code_start(db, username, 'reset', row['email'])
    db.close()
    if not sent:
        print(f'[email] reset code to {username} failed: {e}')
        return err('Could not send the email right now. Please try again or contact support.')
    return ok({'email': _mask_email(row['email'])}, f'Code sent to {_mask_email(row["email"])}')


@app.route('/api/players/reset-password', methods=['POST'])
@limiter.limit('10 per minute; 30 per hour')
def reset_password_by_email():
    """Forgot password, step 2: the emailed code proves the player owns the account."""
    data     = request.get_json() or {}
    username = (data.get('username') or '').strip()
    code     = (data.get('code') or '').strip()
    new_pw   = (data.get('new_password') or '').strip()
    if not username or not new_pw:
        return err('username and new_password are required')
    if not code:
        return err('Enter the code we emailed you')
    if len(new_pw) < 6:
        return err('New password must be at least 6 characters')
    db = get_db()
    email, e = _email_code_check(db, username, 'reset', code)
    if not email:
        db.close()
        return err(e)
    # Reading the code proves they own this inbox, so the email counts as verified too
    db.execute('UPDATE players SET password_hash=?, email_verified=1 WHERE username=? AND LOWER(email)=LOWER(?)',
               (hash_password(new_pw), username, email))
    db.commit()
    db.close()
    return ok({}, 'Password reset successfully')


@app.route('/api/verify/email/send', methods=['POST'])
@limiter.limit('3 per minute; 10 per hour')
def verify_email_send():
    data     = request.json or {}
    username = (data.get('username') or '').strip()
    db  = get_db()
    row = db.execute('SELECT id, email, email_verified FROM players WHERE username=?', (username,)).fetchone()
    if not row:
        db.close()
        return err('Player not found', 404)
    if not _verify_player_token(request.headers.get('X-Player-Token', ''), row['id']):
        db.close()
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401
    email = (data.get('email') or row['email'] or '').strip().lower()
    if not _EMAIL_RE.match(email):
        db.close()
        return err('Enter a valid email address')
    if row['email_verified'] and (row['email'] or '').lower() == email:
        db.close()
        return err('Email already verified')
    if db.execute('SELECT id FROM players WHERE LOWER(email)=? AND id<>?', (email, row['id'])).fetchone():
        db.close()
        return err('That email is already used by another account.')
    if not _mailer.configured():
        db.close()
        return err('Email verification is not available right now.')
    sent, e = _email_code_start(db, username, 'verify', email)
    db.close()
    if not sent:
        print(f'[email] verify code to {username} failed: {e}')
        return err('Could not send the email right now. Please try again.')
    return ok({'email': email}, f'Code sent to {email}')


@app.route('/api/verify/email/confirm', methods=['POST'])
@limiter.limit('10 per minute')
def verify_email_confirm():
    data     = request.json or {}
    username = (data.get('username') or '').strip()
    db  = get_db()
    row = db.execute('SELECT id FROM players WHERE username=?', (username,)).fetchone()
    if not row:
        db.close()
        return err('Player not found', 404)
    if not _verify_player_token(request.headers.get('X-Player-Token', ''), row['id']):
        db.close()
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401
    email, e = _email_code_check(db, username, 'verify', data.get('code'))
    if not email:
        db.close()
        return err(e)
    if db.execute('SELECT id FROM players WHERE LOWER(email)=? AND id<>?', (email.lower(), row['id'])).fetchone():
        db.close()
        return err('That email is already used by another account.')
    db.execute('UPDATE players SET email=?, email_verified=1 WHERE id=?', (email, row['id']))
    db.commit()
    db.close()
    return ok({'email': email}, 'Email verified!')


@app.route('/api/admin/email-config', methods=['GET', 'POST'])
@require_admin
def admin_email_config():
    if request.method == 'GET':
        c = _mailer.get_config()
        return ok({'configured': bool(c['address'] and c['password']), 'address': c['address'], 'name': c['name'],
                   'host': c['host'], 'port': c['port']})
    data    = request.json or {}
    address = (data.get('address') or '').strip()
    pw      = re.sub(r'\s', '', data.get('app_password') or '')   # Google shows it as "abcd efgh ijkl mnop"
    name    = (data.get('name') or '').strip() or "BigWin Gaming"
    host    = (data.get('host') or 'smtp.gmail.com').strip().lower()
    try:
        port = int(data.get('port') or 465)
    except (TypeError, ValueError):
        port = 0
    if host in (_mailer.RESEND_HOST, _mailer.BREVO_HOST):
        port = 443
    elif port not in (465, 587, 2525) or not re.match(r'^[a-z0-9.-]+\.[a-z]{2,}$', host):
        return err('Mail server must look like mail.example.com and the port must be 465 or 587')
    cur     = _mailer.get_config()
    pw      = pw or (cur['password'] if address == cur['address'] else '')
    if not _EMAIL_RE.match(address) or not pw:
        return err('Email address and password are required')
    cfg = dict(cur, address=address, password=pw, name=name, host=host, port=port)
    test_to = (data.get('test_to') or '').strip() or address
    if not _EMAIL_RE.match(test_to):
        return err('"Send test to" must be an email address')
    t_subject, t_text, t_html = _mailer.test_email()
    sent, e = _mailer.send(test_to, t_subject, t_text, cfg, html=t_html)
    if not sent:
        return err(f'Not saved — {e}')
    db = get_db()
    _upsert_setting(db, 'email_address', address)
    _upsert_setting(db, 'email_app_password', pw)
    _upsert_setting(db, 'email_name', name)
    _upsert_setting(db, 'email_host', host)
    _upsert_setting(db, 'email_port', str(port))
    db.close()
    return ok(msg=f'Saved — a test email was sent to {test_to}')


@app.route('/api/admin/email-disconnect', methods=['POST'])
@require_admin
def admin_email_disconnect():
    db = get_db()
    for k in _mailer.KEYS:
        db.execute('DELETE FROM site_settings WHERE key=?', (k,))
    db.commit()
    db.close()
    return ok(msg='Email turned off')


@app.route('/api/players/<int:pid>/admin-reset-password', methods=['POST'])
@require_admin
def admin_reset_password(pid):
    data   = request.get_json() or {}
    new_pw = data.get('new_password', '').strip()
    if not new_pw:
        return err('new_password is required')
    if len(new_pw) < 6:
        return err('Password must be at least 6 characters')
    db = get_db()
    if not db.execute('SELECT id FROM players WHERE id=?', (pid,)).fetchone():
        db.close()
        return err('Player not found', 404)
    db.execute('UPDATE players SET password_hash=? WHERE id=?', (hash_password(new_pw), pid))
    db.commit()
    db.close()
    return ok({}, 'Password reset by admin')


# ─────────────────────────────────────────
#  PLAYERS (admin)
# ─────────────────────────────────────────

# ─────────────────────────────────────────
#  REFERRAL
# ─────────────────────────────────────────

@app.route('/api/referral/info', methods=['GET'])
def referral_info():
    admin_token  = request.headers.get('X-Admin-Token', '')
    player_token = request.headers.get('X-Player-Token', '')
    username = request.args.get('username', '').strip()
    if not username:
        return err('username required')
    db     = get_db()
    player = db.execute('SELECT id, referral_code FROM players WHERE username=?', (username,)).fetchone()
    if not player:
        db.close()
        return err('Player not found', 404)
    if not _verify_admin_token(admin_token) and not _verify_player_token(player_token, player['id']):
        db.close()
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401

    pid  = player['id']
    code = player['referral_code'] or ''

    # Generate code if missing (existing accounts)
    if not code:
        code = _gen_referral_code(db)
        db.execute('UPDATE players SET referral_code=? WHERE id=?', (code, pid))
        db.commit()

    rows = db.execute(
        'SELECT * FROM referrals WHERE referrer_id=? ORDER BY created_at DESC', (pid,)
    ).fetchall()
    total_fp   = sum(r['fp_referrer'] for r in rows)
    db.close()

    base = request.host_url.rstrip('/')
    return ok({
        'referral_code': code,
        'invite_link':   f'{base}/auth.html?ref={code}',
        'total_referrals': len(rows),
        'fp_earned':     total_fp,
        'cash_earned':   0,
        'referrals':     [dict(r) for r in rows],
    })


@app.route('/api/referral/list', methods=['GET'])
@require_admin
def referral_list_admin():
    db   = get_db()
    rows = db.execute('SELECT * FROM referrals ORDER BY id DESC LIMIT 200').fetchall()
    db.close()
    return ok([dict(r) for r in rows])


@app.route('/api/players/me', methods=['GET'])
def get_player_me():
    admin_token  = request.headers.get('X-Admin-Token', '')
    player_token = request.headers.get('X-Player-Token', '')
    username = request.args.get('username', '').strip()
    if not username:
        return err('username required')
    db  = get_db()
    row = db.execute('SELECT id,username,email,first_name,last_name,balance,fp_credits,phone_verified,email_verified,referral_code,status FROM players WHERE username=?', (username,)).fetchone()
    db.close()
    if not row:
        return err('Player not found', 404)
    if not _verify_admin_token(admin_token) and not _verify_player_token(player_token, row['id']):
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401
    return ok(dict(row))


@app.route('/api/players', methods=['GET'])
@require_admin
def get_players():
    db   = get_db()
    rows = db.execute('SELECT id,username,email,balance,fp_credits,status,created_at FROM players ORDER BY created_at DESC').fetchall()
    db.close()
    return ok(rows_to_list(rows))


@app.route('/api/players/create', methods=['POST'])
@require_admin
def admin_create_player():
    """Admin: create a new player account."""
    data     = request.json or {}
    username = (data.get('username') or '').strip()
    email    = (data.get('email') or '').strip() or None
    password = (data.get('password') or '').strip()
    balance  = float(data.get('balance', 0) or 0)
    if not username: return err('Username is required')
    if not password: return err('Password is required')
    if len(password) < 6: return err('Password must be at least 6 characters')
    pw_hash  = hash_password(password)
    ref_code = _secrets.token_hex(4).upper()
    db = get_db()
    try:
        db.execute(
            'INSERT INTO players (username, email, password_hash, balance, referral_code) VALUES (?,?,?,?,?)',
            (username, email, pw_hash, balance, ref_code)
        )
        db.commit()
        pid = db.execute('SELECT id FROM players WHERE username=?', (username,)).fetchone()['id']
        db.close()
        return ok({'id': pid, 'username': username}, 'Player created')
    except Exception as e:
        db.close()
        if 'UNIQUE' in str(e) or 'unique' in str(e):
            return err('Username or email already exists')
        return err(str(e))

@app.route('/api/players/<int:pid>/toggle-status', methods=['POST'])
@require_admin
def admin_toggle_player_status(pid):
    """Admin: enable or disable a player account."""
    db  = get_db()
    row = db.execute('SELECT status FROM players WHERE id=?', (pid,)).fetchone()
    if not row:
        db.close()
        return err('Player not found', 404)
    new_status = 'inactive' if row['status'] == 'active' else 'active'
    db.execute('UPDATE players SET status=? WHERE id=?', (new_status, pid))
    db.commit()
    db.close()
    return ok({'status': new_status}, f'Player {"enabled" if new_status == "active" else "disabled"}')

@app.route('/api/players/<int:pid>/credit', methods=['POST'])
@require_admin
def admin_credit_player(pid):
    """Admin: directly add wallet balance to any player."""
    data   = request.json or {}
    amount = float(data.get('amount', 0))
    note   = data.get('note', 'Manual credit by admin').strip() or 'Manual credit by admin'
    if amount <= 0:
        return err('Amount must be greater than 0')
    db  = get_db()
    row = db.execute('SELECT id, username FROM players WHERE id=?', (pid,)).fetchone()
    if not row:
        db.close()
        return err('Player not found', 404)
    db.execute('UPDATE players SET balance = balance + ? WHERE id=?', (amount, pid))
    db.execute(
        'INSERT INTO transactions (player_id, username, type, amount, status, notes) VALUES (?,?,?,?,?,?)',
        (pid, row['username'], 'admin_credit', amount, 'approved', note)
    )
    db.commit()
    new_bal = db.execute('SELECT balance FROM players WHERE id=?', (pid,)).fetchone()['balance']
    db.close()
    return ok({'new_balance': new_bal}, f'${amount:.2f} credited to {row["username"]}')


@app.route('/api/players/<int:pid>/redeem', methods=['POST'])
@require_admin
def admin_redeem_player(pid):
    """Admin: deduct wallet balance from a player (redeem/adjustment)."""
    data   = request.json or {}
    amount = float(data.get('amount', 0))
    note   = data.get('note', 'Balance redeemed by admin').strip() or 'Balance redeemed by admin'
    if amount <= 0:
        return err('Amount must be greater than 0')
    db  = get_db()
    row = db.execute('SELECT id, username, balance FROM players WHERE id=?', (pid,)).fetchone()
    if not row:
        db.close()
        return err('Player not found', 404)
    if float(row['balance']) < amount:
        db.close()
        return err(f'Insufficient balance — player only has ${float(row["balance"]):.2f}')
    db.execute('UPDATE players SET balance = balance - ? WHERE id=?', (amount, pid))
    db.execute(
        'INSERT INTO transactions (player_id, username, type, amount, status, notes) VALUES (?,?,?,?,?,?)',
        (pid, row['username'], 'withdrawal', amount, 'approved', note)
    )
    db.commit()
    new_bal = db.execute('SELECT balance FROM players WHERE id=?', (pid,)).fetchone()['balance']
    db.close()
    return ok({'new_balance': new_bal}, f'${amount:.2f} redeemed from {row["username"]}')

@app.route('/api/players/<int:pid>', methods=['GET'])
def get_player(pid):
    admin_token  = request.headers.get('X-Admin-Token', '')
    player_token = request.headers.get('X-Player-Token', '')
    if not _verify_admin_token(admin_token) and not _verify_player_token(player_token, pid):
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401
    db  = get_db()
    row = db.execute('SELECT id,username,email,balance,fp_credits,phone_verified,email_verified,referral_code,status,created_at FROM players WHERE id=?', (pid,)).fetchone()
    if not row:
        db.close()
        return err('Player not found', 404)
    player = dict(row)

    games = db.execute('SELECT * FROM game_accounts WHERE player_id=?', (pid,)).fetchall()
    player['game_accounts'] = rows_to_list(games)

    txns = db.execute('SELECT * FROM transactions WHERE player_id=? ORDER BY created_at DESC LIMIT 20', (pid,)).fetchall()
    player['transactions'] = rows_to_list(txns)
    db.close()
    return ok(player)


# ─────────────────────────────────────────
#  GAME ACCOUNTS (create player accounts on game APIs)
# ─────────────────────────────────────────

@app.route('/api/games/status', methods=['GET'])
def games_status():
    """Public: which games players can use. 'active' = new accounts and loads allowed;
    'paused' = turned off in admin, existing players can only cash out."""
    db   = get_db()
    rows = db.execute("SELECT game, MAX(enabled) AS on_ FROM backends WHERE status='connected' GROUP BY game").fetchall()
    db.close()
    active = sorted(r['game'] for r in rows if r['on_'])
    paused = sorted(r['game'] for r in rows if not r['on_'])
    return ok({'active': active, 'paused': paused})


def _game_login(username, game, salt=''):
    """Game login for a player: 7–16 letters/numbers, which every panel accepts
    (Ultra Panda, VBlink, Dragon Fury and Ultra Thunder refuse anything else).
    'crazyeebuddha1470@gmail.com' + ultrathunder → 'crazyeebuddha1ult'."""
    base   = re.sub(r'[^a-zA-Z0-9]', '', (username or '').split('@')[0]) or 'player'
    suffix = re.sub(r'[^a-z0-9]', '', (game or '').lower())[:3]
    name   = base[:16 - len(suffix) - len(salt)] + suffix + salt
    while len(name) < 7:
        name += str(_secrets.randbelow(10))
    return name


@app.route('/api/players/<int:pid>/create-game-account', methods=['POST'])
def create_game_account(pid):
    admin_token  = request.headers.get('X-Admin-Token', '')
    player_token = request.headers.get('X-Player-Token', '')
    if not _verify_admin_token(admin_token) and not _verify_player_token(player_token, pid):
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401
    data = request.json or {}
    game = data.get('game', '').strip()

    if not game:
        return err('Game is required')

    # Get the attached backend for this game
    db  = get_db()
    brow = db.execute(
        "SELECT * FROM backends WHERE game=? AND status='connected' ORDER BY enabled DESC, created_at DESC LIMIT 1",
        (game,)
    ).fetchone()

    if not brow:
        db.close()
        return err(f'No connected backend for {game}. Attach and test a backend first.')
    if not brow['enabled'] and not _verify_admin_token(admin_token):
        db.close()
        return err('This game is turned off right now. Please pick another game.')

    prow = db.execute('SELECT * FROM players WHERE id=?', (pid,)).fetchone()
    if not prow:
        db.close()
        return err('Player not found', 404)

    b      = dict(brow)
    player = dict(prow)

    # Check if already has this game
    existing = db.execute(
        'SELECT id FROM game_accounts WHERE player_id=? AND game=?', (pid, game)
    ).fetchone()
    if existing:
        db.close()
        return err(f'Player already has a {game} account')

    # Generate game credentials (alphanumeric only — many providers reject special chars)
    import string, re
    _chars = string.ascii_letters + string.digits
    _rand  = ''.join(_secrets.choice(_chars) for _ in range(6))
    game_user = _game_login(player['username'], game)
    game_pass = data.get('password', f'BW{pid:04d}{_rand}')

    api = get_api(b['game'], b['username'], b['password'], b['token'], b['base_url'])
    if not api:
        db.close()
        return err(f'No API module for {game}')
    if hasattr(api, 'under'):
        api.under = b.get('loadstar_under') or ''

    try:
        result = api.create_player(game_user, game_pass)
        # Someone else already has that login on the panel: try once more with a few random digits
        if not result[0] and re.search(r'exist|taken|duplicate|registered|in use', str(result[1]), re.I):
            game_user = _game_login(player['username'], game, salt=f'{_secrets.randbelow(900) + 100}')
            result = api.create_player(game_user, game_pass)
    except Exception as ex:
        db.close()
        return err(f'API error: {ex}')

    if len(result) == 3:
        success, msg, external_id = result
    else:
        success, msg = result
        external_id = ''

    if success:
        db.execute(
            'INSERT INTO game_accounts (player_id, game, game_username, game_password, external_id) VALUES (?,?,?,?,?)',
            (pid, game, game_user, game_pass, str(external_id))
        )
        db.execute(
            'INSERT INTO transactions (player_id, username, type, amount, status, notes) VALUES (?,?,?,?,?,?)',
            (pid, player['username'], 'game_account_created', 0, 'approved', f'{game} account: {game_user}')
        )
        db.commit()
        db.close()
        return ok({'game': game, 'username': game_user, 'password': game_pass, 'external_id': str(external_id)}, msg)
    else:
        db.close()
        return err(msg)


@app.route('/api/players/<int:pid>/reset-game-password', methods=['POST'])
@require_player
def reset_game_password(pid):
    data     = request.json or {}
    game     = data.get('game', '').strip()
    new_pass = data.get('new_password', '').strip()

    if not game or not new_pass:
        return err('game and new_password are required')
    if len(new_pass) < 6 or len(new_pass) > 32:
        return err('Password must be 6–32 characters')

    db    = get_db()
    garow = db.execute(
        'SELECT * FROM game_accounts WHERE player_id=? AND game=?', (pid, game)
    ).fetchone()
    if not garow:
        db.close()
        return err(f'No {game} account found for this player')

    brow = db.execute(
        "SELECT * FROM backends WHERE game=? AND status='connected' ORDER BY enabled DESC, created_at DESC LIMIT 1", (game,)
    ).fetchone()
    if not brow:
        db.close()
        return err(f'No connected backend for {game}')

    ga  = dict(garow)
    b   = dict(brow)
    api = get_api(b['game'], b['username'], b['password'], b['token'], b['base_url'])

    success, msg = api.reset_password(ga['game_username'], new_pass, external_id=ga.get('external_id', ''))

    if success:
        db.execute('UPDATE game_accounts SET game_password=? WHERE id=?', (new_pass, ga['id']))
        db.commit()

    db.close()
    return ok({}, msg) if success else err(msg)


@app.route('/api/players/<int:pid>/game-balance', methods=['GET'])
def get_player_game_balance(pid):
    admin_token  = request.headers.get('X-Admin-Token', '')
    player_token = request.headers.get('X-Player-Token', '')
    if not _verify_admin_token(admin_token) and not _verify_player_token(player_token, pid):
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401
    game  = request.args.get('game', '').strip()
    force = request.args.get('force', '').lower() in ('1', 'true')
    if not game:
        return err('game param required')

    # Return cached balance if fresh (avoid hitting the proxy on every click)
    cache_key = (pid, game)
    if not force:
        cached = _BAL_CACHE.get(cache_key)
        if cached and (_time.time() - cached[1]) < _BAL_CACHE_TTL:
            return ok({'balance': cached[0], 'game': game, 'cached': True})

    db   = get_db()
    garow = db.execute(
        'SELECT * FROM game_accounts WHERE player_id=? AND game=?', (pid, game)
    ).fetchone()
    if not garow:
        db.close()
        return err(f'No {game} account found for this player')

    brow = db.execute(
        "SELECT * FROM backends WHERE game=? AND status='connected' ORDER BY enabled DESC, created_at DESC LIMIT 1", (game,)
    ).fetchone()
    if not brow:
        db.close()
        return err(f'No connected backend for {game}')

    ga  = dict(garow)
    b   = dict(brow)
    api = get_api(b['game'], b['username'], b['password'], b['token'], b['base_url'])
    bal, error = api.get_balance(ga['game_username'], external_id=ga.get('external_id', ''))

    if bal is not None:
        _BAL_CACHE[cache_key] = (bal, _time.time())
        db.execute('UPDATE game_accounts SET balance=? WHERE id=?', (bal, ga['id']))
        db.commit()

    db.close()
    if error:
        return err(error)
    return ok({'balance': bal, 'game': game, 'username': ga['game_username']})


@app.route('/api/players/<int:pid>/game-accounts', methods=['GET'])
def get_player_game_accounts(pid):
    # The player themself, admin or a support agent — not anyone who knows a player id
    if not (_verify_player_token(request.headers.get('X-Player-Token', ''), pid)
            or _verify_admin_token(request.headers.get('X-Admin-Token', '')) or get_support_agent()):
        return jsonify({'success': False, 'msg': 'Please sign in again.'}), 401
    db   = get_db()
    rows = db.execute('SELECT * FROM game_accounts WHERE player_id=? ORDER BY created_at DESC', (pid,)).fetchall()
    db.close()
    result = rows_to_list(rows)
    for r in result:
        r['game_password'] = '••••••'   # always masked — real pw is in local cache only
    return ok(result)


@app.route('/api/players/<int:pid>/game-login', methods=['GET'])
@require_player
def player_game_login(pid):
    """The signed-in player's own login for one game (for Copy & Play and showing the password)."""
    game = request.args.get('game', '').strip()
    db = get_db()
    row = db.execute('SELECT game_username, game_password FROM game_accounts WHERE player_id=? AND game=?',
                     (pid, game)).fetchone()
    db.close()
    if not row:
        return err('No account on that game', 404)
    resp = make_response(ok({'username': row['game_username'], 'password': row['game_password'] or ''}))
    resp.headers['Cache-Control'] = 'no-store'
    return resp


def _load_to_game(db, pid, game, amount):
    """Move `amount` from the player's wallet into their own account on `game`.
    Returns (ok, msg, new_balance, code); code is 'insufficient' when the wallet is short."""
    brow = db.execute(
        "SELECT * FROM backends WHERE game=? AND status='connected' ORDER BY enabled DESC, created_at DESC LIMIT 1", (game,)
    ).fetchone()
    if not brow:
        return False, 'Game backend not connected — contact support.', None, 'no_backend'
    if not brow['enabled']:
        return False, 'This game is paused — you can still cash out your credits, but not add new ones.', None, 'paused'
    # Always the player's own game login, never one sent by the browser
    ga = db.execute('SELECT game_username, external_id FROM game_accounts WHERE player_id=? AND game=?',
                    (pid, game)).fetchone()
    if not ga:
        return False, f'You have no {game} account yet — create one first.', None, 'no_account'

    # Atomic balance deduction: only deducts if balance is sufficient
    cursor = db.execute(
        'UPDATE players SET balance = balance - ? WHERE id=? AND balance >= ?',
        (amount, pid, amount)
    )
    if cursor.rowcount == 0:
        prow = db.execute('SELECT balance FROM players WHERE id=?', (pid,)).fetchone()
        if not prow:
            return False, 'Player not found', None, 'no_player'
        return (False, f'Insufficient balance. You have ${float(prow["balance"]):.2f}, need ${amount:.2f}.',
                float(prow['balance']), 'insufficient')
    db.commit()

    prow = db.execute('SELECT username FROM players WHERE id=?', (pid,)).fetchone()
    b    = dict(brow)
    api  = get_api(b['game'], b['username'], b['password'], b['token'], b['base_url'])
    try:
        success, msg = api.add_credits(ga['game_username'], amount, external_id=ga['external_id'] or '')
    except Exception as ex:
        success, msg = False, f'API error: {ex}'

    if success:
        _BAL_CACHE.pop((pid, game), None)
        db.execute(
            'INSERT INTO transactions (player_id, username, type, amount, status, notes) VALUES (?,?,?,?,?,?)',
            (pid, prow['username'], 'add_credits', amount, 'approved', f'{game} +${amount:.2f} to {ga["game_username"]}')
        )
        db.commit()
        new_bal = db.execute('SELECT balance FROM players WHERE id=?', (pid,)).fetchone()['balance']
        return True, f'${amount:.2f} loaded to your {game} account!', new_bal, 'ok'
    # Refund on game API failure
    db.execute('UPDATE players SET balance = balance + ? WHERE id=?', (amount, pid))
    db.commit()
    new_bal = db.execute('SELECT balance FROM players WHERE id=?', (pid,)).fetchone()['balance']
    return False, f'Could not load credits: {msg}. Your balance was not charged.', new_bal, 'game_error'


def _pay_options(shortfall):
    """KeyHub amounts that cover `shortfall`, smallest first (empty when KeyHub is off or it's too big)."""
    if not _get_keyhub_key():
        return []
    return [a for a in KEYHUB_PAY_AMOUNTS if a + 0.005 >= shortfall]


@app.route('/api/players/<int:pid>/load-credits', methods=['POST'])
@require_player
def player_load_credits(pid):
    """Player-facing: deduct wallet balance and add game credits atomically.
    When the wallet is short, the reply says how much is missing and which payments can cover it."""
    data   = request.json or {}
    game   = data.get('game', '').strip()
    amount = round(float(data.get('amount', 0) or 0), 2)
    if not game or amount <= 0:
        return err('game and amount are required')

    db = get_db()
    ok_, msg, new_bal, code = _load_to_game(db, pid, game, amount)
    db.close()
    if ok_:
        return ok({'new_balance': new_bal}, msg)
    if code == 'insufficient':
        shortfall = round(amount - new_bal, 2)
        return jsonify({'success': False, 'msg': msg, 'data': {
            'insufficient': True, 'balance': new_bal, 'shortfall': shortfall,
            'pay_amounts': _pay_options(shortfall),
            'pay_methods': [{'key': k, 'name': n} for k, n in KEYHUB_PAY_METHODS],
        }}), 400
    return err(msg)


@app.route('/api/players/<int:pid>/pay-and-load', methods=['POST'])
@require_player
def pay_and_load(pid):
    """Wallet is short: make a KeyHub checkout. Once KeyHub confirms it, the payment goes to the
    wallet and `amount` loads into the game (see /api/deposits/<id>/confirm)."""
    data       = request.json or {}
    game       = data.get('game', '').strip()
    amount     = round(float(data.get('amount', 0) or 0), 2)
    pay_amount = round(float(data.get('pay_amount', 0) or 0), 2)
    method     = data.get('method', 'cashapp')
    if not game or amount <= 0:
        return err('game and amount are required')
    if pay_amount not in KEYHUB_PAY_AMOUNTS:
        return err('Pick one of the listed payment amounts')
    if method not in dict(KEYHUB_PAY_METHODS):
        return err('Pick Cash App, Apple Pay or Google Pay')

    db   = get_db()
    prow = db.execute('SELECT username, balance FROM players WHERE id=?', (pid,)).fetchone()
    if not prow:
        db.close()
        return err('Player not found', 404)
    brow = db.execute("SELECT enabled FROM backends WHERE game=? AND status='connected' ORDER BY enabled DESC LIMIT 1",
                      (game,)).fetchone()
    if not brow or not brow['enabled']:
        db.close()
        return err('This game is not available right now.')
    if not db.execute('SELECT id FROM game_accounts WHERE player_id=? AND game=?', (pid, game)).fetchone():
        db.close()
        return err(f'You have no {game} account yet — create one first.')
    if float(prow['balance']) + pay_amount + 0.005 < amount:
        db.close()
        return err(f'${pay_amount:.2f} plus your ${float(prow["balance"]):.2f} wallet is not enough for ${amount:.2f}.')

    cur = db.execute(
        "INSERT INTO deposit_requests (player_id, username, amount, method, load_game, load_amount, load_status) "
        "VALUES (?,?,?,?,?,?,?)",
        (pid, prow['username'], pay_amount, method, game, amount, 'waiting')
    )
    dep_id = cur.lastrowid
    db.commit()

    kh_data, kh_err = _keyhub_collect(pay_amount, prow['username'], method)
    if not kh_data or not kh_data.get('payment_url'):
        db.execute("UPDATE deposit_requests SET status='rejected', load_status='', notes=? WHERE id=?",
                   (f'KeyHub: {kh_err}'[:300], dep_id))
        db.commit()
        db.close()
        return err(f'Could not create the payment: {kh_err or "no payment link"}')
    reference = kh_data.get('reference') or kh_data.get('token') or ''
    db.execute('UPDATE deposit_requests SET payment_url=?, keyhub_token=? WHERE id=?',
               (kh_data['payment_url'], reference, dep_id))
    db.commit()
    db.close()
    return ok({'request_id': dep_id, 'payment_url': kh_data['payment_url'], 'pay_amount': pay_amount,
               'load_amount': amount}, 'Payment page ready')


@app.route('/api/players/<int:pid>/avatar', methods=['GET', 'POST'])
@require_player
def player_avatar(pid):
    """The player's profile photo (a small data-URI image; the app shrinks it before upload)."""
    db = get_db()
    try:
        if request.method == 'GET':
            row = db.execute('SELECT avatar FROM players WHERE id=?', (pid,)).fetchone()
            return ok({'avatar': (row['avatar'] if row else '') or ''})
        img = str((request.json or {}).get('avatar') or '').strip()
        if img and (not _IMG_DATA_URI.match(img[:64]) or len(img) > 400_000):
            return err('Upload a PNG, JPG or WebP image.')
        db.execute('UPDATE players SET avatar=? WHERE id=?', (img, pid))
        db.commit()
        return ok({'avatar': img}, 'Profile photo updated' if img else 'Profile photo removed')
    finally:
        db.close()


@app.route('/api/players/<int:pid>/wallet', methods=['GET'])
@require_player
def player_wallet(pid):
    """Payments page: wallet balance, recent history and deposits still waiting for approval."""
    db = get_db()
    try:
        prow = db.execute('SELECT balance, fp_credits FROM players WHERE id=?', (pid,)).fetchone()
        if not prow:
            return err('Player not found', 404)
        txns = db.execute(
            'SELECT id, type, amount, method, status, notes, created_at FROM transactions '
            'WHERE player_id=? ORDER BY id DESC LIMIT 40', (pid,)).fetchall()
        deps = db.execute(
            "SELECT id, amount, method, payment_url, created_at, "
            "CASE WHEN screenshot IS NOT NULL AND screenshot<>'' THEN 1 ELSE 0 END AS has_screenshot "
            "FROM deposit_requests WHERE player_id=? AND status='pending' ORDER BY id DESC LIMIT 10", (pid,)).fetchall()
        return ok({'balance': round(float(prow['balance'] or 0), 2),
                   'bonus_credits': round(float(prow['fp_credits'] or 0), 2),
                   'transactions': rows_to_list(txns), 'pending_deposits': rows_to_list(deps)})
    finally:
        db.close()


@app.route('/api/players/<int:pid>/pending-loads', methods=['GET'])
@require_player
def pending_loads(pid):
    """Pay-to-load payments that are still waiting, so the games page can keep checking them."""
    db   = get_db()
    rows = db.execute(
        "SELECT id, amount, load_game, load_amount, payment_url, created_at FROM deposit_requests "
        "WHERE player_id=? AND status='pending' AND load_game<>'' ORDER BY id DESC LIMIT 5", (pid,)
    ).fetchall()
    db.close()
    return ok(rows_to_list(rows))


@app.route('/api/players/<int:pid>/add-credits', methods=['POST'])
@require_admin
def add_credits(pid):
    data          = request.json or {}
    game          = data.get('game', '').strip()
    amount        = float(data.get('amount', 0))
    game_username = data.get('game_username', '').strip()
    if not game or amount <= 0:
        return err('game and amount are required')

    db   = get_db()
    brow = db.execute(
        "SELECT * FROM backends WHERE game=? AND status='connected' ORDER BY enabled DESC, created_at DESC LIMIT 1", (game,)
    ).fetchone()
    if not brow:
        db.close()
        return err(f'No connected backend for {game}')

    b       = dict(brow)
    api     = get_api(b['game'], b['username'], b['password'], b['token'], b['base_url'])
    # fetch external_id (Juwa user_id) from game_accounts if stored
    garow   = db.execute(
        'SELECT external_id FROM game_accounts WHERE player_id=? AND game=?', (pid, game)
    ).fetchone()
    ext_id  = garow['external_id'] if garow else ''
    success, msg = api.add_credits(game_username, amount, external_id=ext_id)
    if success:
        prow  = db.execute('SELECT username FROM players WHERE id=?', (pid,)).fetchone()
        uname = prow['username'] if prow else str(pid)
        db.execute(
            'INSERT INTO transactions (player_id, username, type, amount, status, notes) VALUES (?,?,?,?,?,?)',
            (pid, uname, 'add_credits', amount, 'approved', f'{game} +${amount} to {game_username}')
        )
        db.commit()
    db.close()
    return ok({}, msg) if success else err(msg)


@app.route('/api/players/<int:pid>/withdraw-credits', methods=['POST'])
@require_admin
def withdraw_credits(pid):
    """Admin-only: withdraw credits without crediting wallet."""
    data          = request.json or {}
    game          = data.get('game', '').strip()
    amount        = float(data.get('amount', 0))
    game_username = data.get('game_username', '').strip()
    if not game or amount <= 0:
        return err('game and amount are required')

    db   = get_db()
    brow = db.execute(
        "SELECT * FROM backends WHERE game=? AND status='connected' ORDER BY enabled DESC, created_at DESC LIMIT 1", (game,)
    ).fetchone()
    if not brow:
        db.close()
        return err(f'No connected backend for {game}')

    b       = dict(brow)
    api     = get_api(b['game'], b['username'], b['password'], b['token'], b['base_url'])
    garow   = db.execute(
        'SELECT external_id FROM game_accounts WHERE player_id=? AND game=?', (pid, game)
    ).fetchone()
    ext_id  = garow['external_id'] if garow else ''
    success, msg = api.withdraw_credits(game_username, amount, external_id=ext_id)
    if success:
        prow  = db.execute('SELECT username FROM players WHERE id=?', (pid,)).fetchone()
        uname = prow['username'] if prow else str(pid)
        db.execute(
            'INSERT INTO transactions (player_id, username, type, amount, status, notes) VALUES (?,?,?,?,?,?)',
            (pid, uname, 'withdraw_credits', amount, 'approved', f'{game} -${amount} from {game_username}')
        )
        db.commit()
    db.close()
    return ok({}, msg) if success else err(msg)


@app.route('/api/players/<int:pid>/game-to-wallet', methods=['POST'])
@require_player
def game_to_wallet(pid):
    """Player-facing: withdraw game credits and credit wallet balance."""
    data          = request.json or {}
    game          = data.get('game', '').strip()
    amount        = float(data.get('amount', 0))
    if not game or amount <= 0:
        return err('game and amount are required')

    db = get_db()
    prow = db.execute('SELECT username FROM players WHERE id=?', (pid,)).fetchone()
    if not prow:
        db.close()
        return err('Player not found', 404)

    brow = db.execute(
        "SELECT * FROM backends WHERE game=? AND status='connected' ORDER BY enabled DESC, created_at DESC LIMIT 1", (game,)
    ).fetchone()
    if not brow:
        db.close()
        return err('Game backend not connected — contact support.')

    b      = dict(brow)
    # Only the player's own game login — never one sent by the browser
    garow  = db.execute('SELECT game_username, external_id FROM game_accounts WHERE player_id=? AND game=?', (pid, game)).fetchone()
    if not garow:
        db.close()
        return err(f'You have no {game} account.')
    game_username = garow['game_username']
    ext_id = garow['external_id'] or ''

    # Call game API to remove credits
    api = get_api(b['game'], b['username'], b['password'], b['token'], b['base_url'])
    success, msg = api.withdraw_credits(game_username, amount, external_id=ext_id)

    if success:
        _BAL_CACHE.pop((pid, game), None)
        # Credit wallet balance
        db.execute('UPDATE players SET balance = balance + ? WHERE id=?', (amount, pid))
        db.execute(
            'INSERT INTO transactions (player_id, username, type, amount, status, notes) VALUES (?,?,?,?,?,?)',
            (pid, prow['username'], 'withdraw_credits', amount, 'approved',
             f'Winnings from {game} — ${amount:.2f} added to wallet')
        )
        db.commit()
        new_bal = db.execute('SELECT balance FROM players WHERE id=?', (pid,)).fetchone()['balance']
        db.close()
        return ok({'new_balance': new_bal}, f'${amount:.2f} from {game} added to your wallet!')
    else:
        db.close()
        return err(f'Could not withdraw from game: {msg}')


# ─────────────────────────────────────────
#  DEPOSITS & WITHDRAWALS
# ─────────────────────────────────────────

def _credit_deposit(db, d, note):
    """Mark a pending deposit approved and add it to the wallet, once.
    Returns (credited, bonus_msg). False when it was already handled."""
    cur = db.execute("UPDATE deposit_requests SET status='approved' WHERE id=? AND status='pending'", (d['id'],))
    if cur.rowcount == 0:
        return False, ''
    if d['player_id']:
        db.execute('UPDATE players SET balance = balance + ? WHERE id=?', (d['amount'], d['player_id']))
        db.execute(
            'INSERT INTO transactions (player_id, username, type, amount, status, method, notes) VALUES (?,?,?,?,?,?,?)',
            (d['player_id'], d['username'], 'deposit', d['amount'], 'approved', d['method'], f'{note} req #{d["id"]}')
        )
    bonus_msg = ''
    bonus = db.execute(
        "SELECT * FROM player_bonuses WHERE username=? AND type='deposit_pct' AND status='pending' ORDER BY id ASC LIMIT 1",
        (d['username'],)
    ).fetchone()
    if bonus:
        bonus_amount = round(d['amount'] * bonus['value'] / 100, 2)
        if d['player_id']:
            db.execute('UPDATE players SET fp_credits = fp_credits + ? WHERE id=?', (bonus_amount, d['player_id']))
        else:
            db.execute('UPDATE players SET fp_credits = fp_credits + ? WHERE username=?', (bonus_amount, d['username']))
        db.execute("UPDATE player_bonuses SET status='applied' WHERE id=?", (bonus['id'],))
        db.execute(
            'INSERT INTO transactions (player_id, username, type, amount, status, method, notes) VALUES (?,?,?,?,?,?,?)',
            (d['player_id'], d['username'], 'bonus', bonus_amount, 'approved', 'roulette',
             f"{bonus['value']:.0f}% deposit bonus req #{d['id']}")
        )
        bonus_msg = f' + ${bonus_amount:.2f} bonus ({bonus["value"]:.0f}% deposit bonus applied)'
    db.commit()
    return True, bonus_msg


def _finish_game_load(db, d):
    """After a pay-to-load deposit is credited, move the load amount into the game."""
    if not d.get('load_game') or not d['player_id']:
        return None
    # Claim the load atomically so two confirmations can never load it twice
    claim = db.execute("UPDATE deposit_requests SET load_status='loading' WHERE id=? AND load_status='waiting'", (d['id'],))
    db.commit()
    if claim.rowcount == 0:
        return None
    ok_, msg, _bal, _code = _load_to_game(db, d['player_id'], d['load_game'], float(d['load_amount'] or 0))
    db.execute('UPDATE deposit_requests SET load_status=?, notes=? WHERE id=?',
               ('loaded' if ok_ else 'load_failed', msg[:300], d['id']))
    db.commit()
    return ok_, msg


@app.route('/api/deposits', methods=['GET'])
@require_admin
def get_deposits():
    db   = get_db()
    rows = db.execute('SELECT * FROM deposit_requests ORDER BY created_at DESC').fetchall()
    db.close()
    return ok(rows_to_list(rows))


@app.route('/api/deposits', methods=['POST'])
def create_deposit():
    admin_token  = request.headers.get('X-Admin-Token', '')
    player_token = request.headers.get('X-Player-Token', '')
    data     = request.json or {}
    pid      = data.get('player_id')
    method   = str(data.get('method', 'cashapp') or 'cashapp')[:40]
    try:
        amount = round(float(data.get('amount', 0) or 0), 2)
    except (TypeError, ValueError):
        amount = 0

    if not _verify_admin_token(admin_token) and not _verify_player_token(player_token, pid):
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401

    if amount <= 0:
        return err('Invalid amount')
    if amount > 10000:
        return err('Maximum deposit per request is $10,000.00')

    db = get_db()
    # Never trust a username from the browser — it decides whose bonus and chat this deposit touches
    prow = db.execute('SELECT username FROM players WHERE id=?', (pid,)).fetchone()
    if not prow:
        db.close()
        return err('Player not found', 404)
    username = prow['username']
    if not _get_keyhub_key() and not db.execute(
            'SELECT 1 FROM payment_methods WHERE key=? AND enabled=1', (method,)).fetchone():
        db.close()
        return err('Pick one of the listed payment methods.')

    # Insert first to get dep_id for the signed return URL
    cursor = db.execute(
        'INSERT INTO deposit_requests (player_id, username, amount, method) VALUES (?,?,?,?)',
        (pid, username, float(amount), method)
    )
    dep_id = cursor.lastrowid
    db.commit()

    # Build signed return URL so KeyHub can redirect back after payment
    base_url    = request.host_url.rstrip('/')
    sig         = _dep_sig(dep_id)
    return_url  = f'{base_url}/api/payments/return?dep_id={dep_id}&sig={sig}'

    # Call KeyHub collect
    kh_data, kh_err = _keyhub_collect(float(amount), username, method, redirect_url=return_url)
    payment_url  = kh_data.get('payment_url', '') if kh_data else ''
    keyhub_token = kh_data.get('token', '')        if kh_data else ''

    # Store payment URL and token
    db.execute(
        'UPDATE deposit_requests SET payment_url=?, keyhub_token=? WHERE id=?',
        (payment_url, keyhub_token, dep_id)
    )
    db.commit()
    db.close()

    return ok({
        'request_id':  dep_id,
        'payment_url': payment_url,
        'keyhub_ok':   bool(payment_url),
        'keyhub_err':  kh_err,
    }, 'Deposit request created')


@app.route('/api/deposits/<int:rid>/screenshot', methods=['POST'])
def deposit_screenshot(rid):
    """Player uploads payment receipt screenshot for a deposit request."""
    data       = request.json or {}
    screenshot = (data.get('screenshot') or '').strip()   # base64 data-URI
    if not screenshot:
        return err('No screenshot provided')
    if not _IMG_DATA_URI.match(screenshot[:64]) or len(screenshot) > 4_000_000:
        return err('Upload a PNG, JPG or WebP image under 3 MB.')

    db  = get_db()
    row = db.execute('SELECT * FROM deposit_requests WHERE id=?', (rid,)).fetchone()
    if not row:
        db.close()
        return err('Deposit not found', 404)

    d = dict(row)

    admin_token  = request.headers.get('X-Admin-Token', '')
    player_token = request.headers.get('X-Player-Token', '')
    if not _verify_admin_token(admin_token) and not _verify_player_token(player_token, d['player_id']):
        db.close()
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401
    if d['status'] != 'pending':
        db.close()
        return err('This deposit is already ' + d['status'] + '.')
    db.execute('UPDATE deposit_requests SET screenshot=? WHERE id=?', (screenshot, rid))

    # Auto-create support ticket so admin is notified
    agent_name = _get_available_agent(db)
    ticket_msg = (
        f"[DEPOSIT #{rid}] Payment receipt submitted\n"
        f"Amount: ${d['amount']:.2f} via {d['method']}\n"
        f"[screenshot attached]"
    )
    db.execute(
        'INSERT INTO support_messages (player_id, username, agent, sender, message) VALUES (?,?,?,?,?)',
        (d['player_id'], d['username'], agent_name, 'player', ticket_msg)
    )
    # Store screenshot as a follow-up image message so it renders in chat
    db.execute(
        'INSERT INTO support_messages (player_id, username, agent, sender, message) VALUES (?,?,?,?,?)',
        (d['player_id'], d['username'], agent_name, 'player', screenshot)
    )
    db.commit()
    db.close()
    return ok(msg='Screenshot received — support ticket created')


@app.route('/api/deposits/<int:rid>/approve', methods=['POST'])
@require_admin
def approve_deposit(rid):
    db  = get_db()
    row = db.execute('SELECT * FROM deposit_requests WHERE id=?', (rid,)).fetchone()
    if not row:
        db.close()
        return err('Request not found', 404)

    d = dict(row)
    credited, bonus_msg = _credit_deposit(db, d, 'Deposit')
    if not credited:
        db.close()
        return err(f'Deposit is already {d["status"]}')
    load = _finish_game_load(db, d)
    db.close()
    load_msg = '' if load is None else (f' · loaded into {d["load_game"]}' if load[0] else f' · game load failed: {load[1]}')
    return ok(msg=f'Deposit of ${d["amount"]} approved{bonus_msg}{load_msg}')


@app.route('/api/deposits/<int:rid>/confirm', methods=['POST'])
def confirm_deposit_keyhub(rid):
    """Player-triggered auto-approval after completing payment on KeyHub."""
    admin_token  = request.headers.get('X-Admin-Token', '')
    player_token = request.headers.get('X-Player-Token', '')
    data = request.json or {}
    pid  = data.get('player_id')

    db  = get_db()
    row = db.execute('SELECT * FROM deposit_requests WHERE id=?', (rid,)).fetchone()
    if not row:
        db.close()
        return err('Request not found', 404)

    d = dict(row)

    # Enforce ownership: must be the deposit's owner or an admin
    if not _verify_admin_token(admin_token) and not _verify_player_token(player_token, d['player_id']):
        db.close()
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401

    if not d.get('payment_url'):
        db.close()
        return err('Deposit was not processed through KeyHub')

    if d['status'] != 'pending':
        player = db.execute('SELECT balance FROM players WHERE id=?', (d['player_id'],)).fetchone()
        db.close()
        return ok({'balance': player['balance'] if player else 0, 'already': True, 'status': d['status'],
                   'load_status': d.get('load_status') or '', 'load_msg': d.get('notes') or ''},
                  f'Deposit already {d["status"]}')

    # Only KeyHub can say it was paid
    pay_status, paid_amt, kh_err = _keyhub_status(d.get('keyhub_token'))
    if pay_status != 'paid':
        db.close()
        msgs = {'open': 'Payment not received yet', 'failed': 'Payment failed or expired',
                'unknown': f'Could not check payment: {kh_err}'}
        return ok({'paid': False, 'status': pay_status}, msgs[pay_status])
    if paid_amt is not None and paid_amt + 0.005 < float(d['amount']):
        db.close()
        return err(f'KeyHub shows ${paid_amt:.2f} paid, less than ${d["amount"]:.2f}. Contact support.')

    credited, bonus_msg = _credit_deposit(db, d, 'KeyHub verified')
    if not credited:  # another check got here first
        player = db.execute('SELECT balance FROM players WHERE id=?', (d['player_id'],)).fetchone()
        db.close()
        return ok({'balance': player['balance'] if player else 0, 'already': True}, 'Deposit already handled')
    load = _finish_game_load(db, d)
    player = db.execute('SELECT balance FROM players WHERE id=?', (d['player_id'],)).fetchone()
    new_balance = player['balance'] if player else 0
    db.close()
    data = {'paid': True, 'balance': new_balance, 'amount': d['amount'], 'bonus_msg': bonus_msg}
    if load is not None:
        data.update({'load_ok': load[0], 'load_msg': load[1]})
        if load[0]:
            return ok(data, f'Paid! ${float(d["load_amount"]):.2f} loaded into your game.')
        return ok(data, f'Paid — ${d["amount"]:.2f} is in your wallet, but the game load failed: {load[1]}')
    return ok(data, f'${d["amount"]:.2f} deposited{bonus_msg}! Balance updated.')


@app.route('/api/payments/return', methods=['GET'])
def payment_return():
    """KeyHub redirects here after a successful payment. Auto-approves the deposit."""
    dep_id = request.args.get('dep_id', '')
    sig    = request.args.get('sig', '')

    def _fail(reason):
        return redirect(f'/wallet.html?dep_err={reason}')

    if not dep_id or not sig:
        return _fail('missing')

    # Verify HMAC signature
    if sig != _dep_sig(dep_id):
        return _fail('invalid_sig')

    db  = get_db()
    row = db.execute('SELECT * FROM deposit_requests WHERE id=?', (dep_id,)).fetchone()
    if not row:
        db.close()
        return _fail('not_found')

    d = dict(row)

    if d['status'] != 'pending':
        db.close()
        return redirect(f'/wallet.html?deposited=already&amt={d["amount"]}')

    # The signed link only proves the URL is ours, not that anyone paid — ask KeyHub.
    pay_status, paid_amt, _ = _keyhub_status(d.get('keyhub_token'))
    if pay_status != 'paid' or (paid_amt is not None and paid_amt + 0.005 < float(d['amount'])):
        db.close()
        return _fail('not_paid')

    if _credit_deposit(db, d, 'KeyHub verified (return)')[0]:
        _finish_game_load(db, d)
    db.close()
    return redirect(f'/wallet.html?deposited=true&amt={d["amount"]}')


@app.route('/api/deposits/<int:rid>/reject', methods=['POST'])
@require_admin
def reject_deposit(rid):
    db = get_db()
    db.execute("UPDATE deposit_requests SET status='rejected' WHERE id=?", (rid,))
    db.commit()
    db.close()
    return ok(msg='Deposit request rejected')


@app.route('/api/withdrawals', methods=['GET'])
@require_admin
def get_withdrawals():
    db   = get_db()
    rows = db.execute('SELECT * FROM withdrawal_requests ORDER BY created_at DESC').fetchall()
    db.close()
    return ok(rows_to_list(rows))


@app.route('/api/withdrawals', methods=['POST'])
def create_withdrawal():
    data    = request.json or {}
    pid     = data.get('player_id')
    try:
        amount     = round(float(data.get('amount', 0) or 0), 2)
        tip_amount = round(float(data.get('tip_amount', 0) or 0), 2)
    except (TypeError, ValueError):
        return err('Invalid amount')
    if tip_amount < 0:
        return err('Invalid tip')
    # Require either admin token or player's own token
    admin_token  = request.headers.get('X-Admin-Token', '')
    player_token = request.headers.get('X-Player-Token', '')
    if not _verify_admin_token(admin_token) and not _verify_player_token(player_token, pid):
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401
    method  = str(data.get('method', '') or '')[:40]
    address = str(data.get('address', '') or '').strip()[:200]

    if amount <= 0:    return err('Invalid amount')
    if not method:     method = 'cashapp'
    # address is required only when KeyHub is NOT handling the payout
    if not address and not _get_keyhub_key():
        return err('Payment address required')

    db    = get_db()
    try:
        rules = _get_cashout_rules(db)
    except Exception:
        rules = _CASHOUT_DEFAULTS.copy()

    # ── Rule: minimum cashout ──
    if amount < rules['min_cashout']:
        db.close()
        return err(f'Minimum cashout is ${rules["min_cashout"]:.2f}')

    # ── Rule: maximum cashout ──
    if amount > rules['max_cashout']:
        db.close()
        return err(f'Maximum cashout per request is ${rules["max_cashout"]:.2f}')

    # ── Rule: daily limit ──
    today = datetime.utcnow().strftime('%Y-%m-%d')
    daily_row = db.execute(
        "SELECT COALESCE(SUM(amount),0) AS total FROM withdrawal_requests "
        "WHERE player_id=? AND status IN ('pending','approved') AND created_at >= ?",
        (pid, today)
    ).fetchone()
    daily_used = float(daily_row['total']) if daily_row else 0.0
    if daily_used + amount > rules['daily_limit']:
        remaining = max(0, rules['daily_limit'] - daily_used)
        db.close()
        return err(f'Daily cashout limit of ${rules["daily_limit"]:.2f} reached. '
                   f'You can still withdraw ${remaining:.2f} today.')

    # ── Rule: wagering requirement ──
    wager_mult = float(rules['wagering_multiplier'])
    if wager_mult > 1:
        dep_row = db.execute(
            "SELECT COALESCE(SUM(amount),0) AS total FROM transactions "
            "WHERE player_id=? AND type='deposit' AND status='approved'",
            (pid,)
        ).fetchone()
        total_deposited = float(dep_row['total']) if dep_row else 0.0

        wager_row = db.execute(
            "SELECT COALESCE(SUM(amount),0) AS total FROM transactions "
            "WHERE player_id=? AND type IN ('add_credits','load_credits')",
            (pid,)
        ).fetchone()
        total_wagered = float(wager_row['total']) if wager_row else 0.0

        required = total_deposited * wager_mult
        if total_wagered < required:
            still_needed = required - total_wagered
            db.close()
            return err(f'Wagering requirement not met. You need to play ${still_needed:.2f} '
                       f'more before cashing out (${wager_mult:.0f}× requirement).')

    tip_agent  = (data.get('tip_agent') or '').strip()[:60]

    # ── Balance check + deduction in ONE statement, so two requests at once can't both spend it ──
    total_deduct = round(amount + tip_amount, 2)
    prow = db.execute('SELECT username FROM players WHERE id=?', (pid,)).fetchone()
    if not prow:
        db.close()
        return err('Player not found', 404)
    username_str = prow['username']
    took = db.execute('UPDATE players SET balance = balance - ? WHERE id=? AND balance >= ?',
                      (total_deduct, pid, total_deduct - 0.001))
    if took.rowcount == 0:
        db.close()
        return err('Insufficient balance')

    cursor = db.execute(
        'INSERT INTO withdrawal_requests (player_id, username, amount, method, address, tip_amount) VALUES (?,?,?,?,?,?)',
        (pid, username_str, amount, method, address, tip_amount)
    )
    rid = cursor.lastrowid

    # Record tip as a negative transaction so it shows in history
    if tip_amount > 0 and tip_agent:
        db.execute(
            'INSERT INTO transactions (player_id, username, type, amount, status, notes) VALUES (?,?,?,?,?,?)',
            (pid, username_str, 'tip', tip_amount, 'approved', f'Tip to {tip_agent}')
        )

    # Always insert a pending withdrawal transaction so the player can see it
    txn_cur = db.execute(
        'INSERT INTO transactions (player_id, username, type, amount, status, notes) VALUES (?,?,?,?,?,?)',
        (pid, username_str, 'withdrawal', amount, 'pending', f'Cashout #{rid} via {method}')
    )
    txn_id = txn_cur.lastrowid

    db.commit()

    # ── Auto-process: try KeyHub payout immediately ──
    payout_url   = ''
    auto_status  = 'pending'

    kh_key = _get_keyhub_key()
    if kh_key:
        kh_data, kh_err = _keyhub_payout(amount, username_str)
        if kh_data:
            payout_url  = kh_data.get('payout_url', '')
            auto_status = 'approved'
            db.execute(
                "UPDATE withdrawal_requests SET status='approved', payout_url=? WHERE id=?",
                (payout_url, rid)
            )
            db.execute(
                "UPDATE transactions SET status='approved', notes=? WHERE id=?",
                (f'KeyHub auto-payout — claim URL: {payout_url}', txn_id)
            )
            db.commit()
        else:
            # KeyHub configured but failed — leave pending, notify via support
            _auto_support_msg(db, pid, username_str, rid, amount, method, address,
                              f'KeyHub error: {kh_err}')
            db.commit()
    else:
        # No KeyHub — create a support message so admin can process manually
        _auto_support_msg(db, pid, username_str, rid, amount, method, address, '')
        db.commit()

    db.close()
    return ok({'request_id': rid, 'payout_url': payout_url, 'auto_status': auto_status},
              'Withdrawal processed automatically' if payout_url else 'Withdrawal request submitted — support notified')


def _get_available_agent(db):
    """Return an online agent name (heartbeat < 120s), or fallback to first active agent."""
    rows = db.execute(
        'SELECT name, last_heartbeat FROM support_agents WHERE active=1 ORDER BY sort_order, id'
    ).fetchall()
    now = _time.time()
    for row in rows:
        hb = row['last_heartbeat']
        if hb and (now - hb) < 120:
            return row['name']
    return rows[0]['name'] if rows else "BigWin Support"


def _auto_support_msg(db, pid, username, rid, amount, method, address, extra):
    """Insert a system support message so admin sees this withdrawal in the inbox."""
    lines = [
        f'💸 Cashout Request #{rid}',
        f'Amount: ${float(amount):.2f}',
        f'Method: {method}',
    ]
    if address:
        lines.append(f'Send to: {address}')
    if extra:
        lines.append(extra)
    lines.append('Please process and confirm.')
    msg = '\n'.join(lines)
    try:
        agent_name = _get_available_agent(db)
        db.execute(
            'INSERT INTO support_messages (player_id, username, agent, sender, message) VALUES (?,?,?,?,?)',
            (pid, username, agent_name, 'player', msg)
        )
    except Exception:
        pass


@app.route('/api/withdrawals/<int:rid>/reject', methods=['POST'])
@require_admin
def reject_withdrawal(rid):
    db  = get_db()
    row = db.execute('SELECT * FROM withdrawal_requests WHERE id=?', (rid,)).fetchone()
    if not row:
        db.close()
        return err('Request not found', 404)
    d = dict(row)
    if d.get('status') == 'rejected':
        db.close()
        return err('Already rejected')
    db.execute("UPDATE withdrawal_requests SET status='rejected' WHERE id=?", (rid,))
    # Refund full amount including tip
    tip_amt     = float(d.get('tip_amount') or 0)
    total_back  = float(d['amount']) + tip_amt
    if d['player_id']:
        db.execute('UPDATE players SET balance = balance + ? WHERE id=?', (total_back, d['player_id']))
        db.execute(
            'INSERT INTO transactions (player_id, username, type, amount, status, notes) VALUES (?,?,?,?,?,?)',
            (d['player_id'], d.get('username',''), 'refund', total_back, 'approved',
             f'Cashout #{rid} declined — ${total_back:.2f} refunded')
        )
    # Mark the pending withdrawal transaction as rejected
    db.execute(
        "UPDATE transactions SET status='rejected' WHERE player_id=? AND type='withdrawal' "
        "AND status='pending' AND notes LIKE ?",
        (d['player_id'], f'Cashout #{rid}%')
    )
    db.commit()
    db.close()
    return ok(msg=f'Withdrawal rejected — ${total_back:.2f} refunded to player')


@app.route('/api/withdrawals/<int:rid>/approve', methods=['POST'])
@require_admin
def approve_withdrawal(rid):
    db  = get_db()
    row = db.execute('SELECT * FROM withdrawal_requests WHERE id=?', (rid,)).fetchone()
    if not row:
        db.close()
        return err('Request not found', 404)
    d = dict(row)

    if d['status'] != 'pending':
        db.close()
        return err(f'Withdrawal already {d["status"]}')

    payout_url = ''

    if KEYHUB_API_KEY:
        # Route through KeyHub — auto-approve only if KeyHub succeeds
        kh_data, kh_err = _keyhub_payout(d['amount'], d['username'])
        if not kh_data:
            db.close()
            return err(f'KeyHub payout failed: {kh_err}')
        payout_url = kh_data.get('payout_url', '')
        status = 'sent'  # KeyHub charged immediately; money is on the way
        notes  = f'KeyHub payout — claim URL: {payout_url}'
    else:
        # No KeyHub key — manual approval
        status = 'approved'
        notes  = 'Manual payout by admin'

    db.execute(
        "UPDATE withdrawal_requests SET status=?, payout_url=? WHERE id=?",
        (status, payout_url, rid)
    )
    db.execute(
        'INSERT INTO transactions (player_id, username, type, amount, status, method, notes) VALUES (?,?,?,?,?,?,?)',
        (d['player_id'], d['username'], 'withdrawal', d['amount'], status, d['method'], notes)
    )
    db.commit()
    db.close()
    return ok(
        {'payout_url': payout_url, 'status': status},
        msg=f'Withdrawal of ${d["amount"]:.2f} {status} — ' +
            ('payout link created for player' if payout_url else 'manual processing')
    )


# ─────────────────────────────────────────
#  TRANSACTIONS
# ─────────────────────────────────────────

@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    admin_token  = request.headers.get('X-Admin-Token', '')
    player_token = request.headers.get('X-Player-Token', '')
    player_id = request.args.get('player_id')
    is_admin = _verify_admin_token(admin_token)
    if not is_admin and not _verify_player_token(player_token, player_id):
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401
    # Non-admins must specify their own player_id; they cannot dump all transactions
    if not is_admin and not player_id:
        return jsonify({'success': False, 'msg': 'player_id required'}), 400
    limit     = int(request.args.get('limit', 50))
    db        = get_db()
    # Exclude internal system events that are not meaningful to the player
    hidden_types = ('game_account_created', 'system')
    placeholders = ','.join('?' * len(hidden_types))
    if player_id:
        rows = db.execute(
            f'SELECT * FROM transactions WHERE player_id=? AND type NOT IN ({placeholders}) ORDER BY created_at DESC LIMIT ?',
            (player_id, *hidden_types, limit)
        ).fetchall()
    else:
        rows = db.execute(
            f'SELECT * FROM transactions WHERE type NOT IN ({placeholders}) ORDER BY created_at DESC LIMIT ?',
            (*hidden_types, limit)
        ).fetchall()
    db.close()
    return ok(rows_to_list(rows))


# ─────────────────────────────────────────
#  DASHBOARD STATS
# ─────────────────────────────────────────

@app.route('/api/server-ip', methods=['GET'])
@require_admin
def get_server_ip():
    try:
        import urllib.request
        ip = urllib.request.urlopen('https://api.ipify.org', timeout=5).read().decode().strip()
        return ok({'ip': ip})
    except Exception as e:
        return ok({'ip': 'unavailable', 'error': str(e)})

@app.route('/api/stats', methods=['GET'])
@require_admin
def get_stats():
    db = get_db()
    total_players = db.execute('SELECT COUNT(*) as c FROM players').fetchone()['c']
    total_games   = db.execute('SELECT COUNT(*) as c FROM game_accounts').fetchone()['c']
    pending_dep   = db.execute("SELECT COUNT(*) as c FROM deposit_requests WHERE status='pending'").fetchone()['c']
    pending_wd    = db.execute("SELECT COUNT(*) as c FROM withdrawal_requests WHERE status='pending'").fetchone()['c']
    total_balance = db.execute('SELECT COALESCE(SUM(balance),0) as s FROM players').fetchone()['s']
    total_fp      = db.execute('SELECT COALESCE(SUM(fp_credits),0) as s FROM players').fetchone()['s']
    dep_today     = db.execute(
        "SELECT COALESCE(SUM(amount),0) as s FROM deposit_requests WHERE status='approved' AND date(created_at)=date('now')"
    ).fetchone()['s']
    wd_today      = db.execute(
        "SELECT COALESCE(SUM(amount),0) as s FROM withdrawal_requests WHERE status='approved' AND date(created_at)=date('now')"
    ).fetchone()['s']
    # Week = last 7 days, month = since the 1st (cutoffs computed here so SQL works on SQLite and PostgreSQL)
    _now        = datetime.utcnow()
    week_start  = (_now - timedelta(days=6)).strftime('%Y-%m-%d')
    month_start = _now.strftime('%Y-%m-01')
    def _sum(table, since):
        return db.execute(f"SELECT COALESCE(SUM(amount),0) as s FROM {table} WHERE status='approved' AND created_at >= ?",
                          (since,)).fetchone()['s']
    dep_week, dep_month = _sum('deposit_requests', week_start), _sum('deposit_requests', month_start)
    wd_week,  wd_month  = _sum('withdrawal_requests', week_start), _sum('withdrawal_requests', month_start)
    backends_ok   = db.execute("SELECT COUNT(*) as c FROM backends WHERE status='connected'").fetchone()['c']
    backends_all  = db.execute('SELECT COUNT(*) as c FROM backends').fetchone()['c']
    db.close()

    return ok({
        'total_players':  total_players,
        'total_games':    total_games,
        'pending_deposits':    pending_dep,
        'pending_withdrawals': pending_wd,
        'total_balance':  round(total_balance, 2),
        'total_fp':       round(total_fp, 2),
        'deposits_today': round(dep_today, 2),
        'withdrawals_today': round(wd_today, 2),
        'deposits_week':  round(dep_week, 2),
        'deposits_month': round(dep_month, 2),
        'withdrawals_week':  round(wd_week, 2),
        'withdrawals_month': round(wd_month, 2),
        'backends_connected': backends_ok,
        'backends_total': backends_all,
    })


# ─────────────────────────────────────────
#  PROVIDER BALANCES
# ─────────────────────────────────────────

@app.route('/api/providers/balances', methods=['GET'])
@require_admin
def get_provider_balances():
    db   = get_db()
    rows = db.execute("SELECT * FROM backends WHERE status='connected' ORDER BY game").fetchall()
    result = []
    for row in rows:
        b   = dict(row)
        api = get_api(b['game'], b['username'], b['password'], b['token'], b['base_url'])
        has_agent_bal = api and hasattr(api, 'get_agent_balance')
        live_bal = b.get('balance') if has_agent_bal else None
        if has_agent_bal:
            bal, err_msg = api.get_agent_balance()
            if bal is not None:
                live_bal = bal
                db.execute('UPDATE backends SET balance=? WHERE id=?', (bal, b['id']))
        result.append({
            'id':          b['id'],
            'game':        b['game'],
            'name':        b['name'],
            'status':      b['status'],
            'balance':     live_bal,
            'last_tested': b['last_tested'],
        })
    db.commit()
    db.close()
    return ok(result)


@app.route('/api/providers/refresh-all', methods=['POST'])
@require_admin
def refresh_all_providers():
    db   = get_db()
    rows = db.execute('SELECT * FROM backends').fetchall()
    results = []
    for row in rows:
        b   = dict(row)
        api = get_api(b['game'], b['username'], b['password'], b['token'], b['base_url'])
        if api:
            connected, msg = api.test_connection()
            status = 'connected' if connected else 'failed'
            db.execute(
                'UPDATE backends SET status=?, last_tested=? WHERE id=?',
                (status, datetime.utcnow().isoformat(), b['id'])
            )
            results.append({'id': b['id'], 'game': b['game'], 'status': status, 'msg': msg})
    db.commit()
    db.close()
    return ok(results, f'Refreshed {len(results)} backends')


# ─────────────────────────────────────────
#  WORKER ROUTES (support agents — masked PII)
# ─────────────────────────────────────────

def _mask_email(email):
    if not email or '@' not in email: return '—'
    local, domain = email.split('@', 1)
    d_parts = domain.split('.', 1)
    return f'{local[0]}***@{d_parts[0][0]}***.{d_parts[1] if len(d_parts)>1 else "com"}'

def _mask_phone(phone):
    if not phone: return '—'
    digits = ''.join(c for c in phone if c.isdigit())
    return f'***-***-{digits[-4:]}' if len(digits) >= 4 else '****'

def _require_worker():
    """Returns agent_name or aborts with 401."""
    agent = get_support_agent()
    if not agent:
        return None, jsonify({'success': False, 'msg': 'Support token required'}), 401
    return agent, None, None

@app.route('/api/worker/deposits', methods=['GET'])
def worker_get_deposits():
    agent, resp, code = _require_worker()
    if resp: return resp, code
    db   = get_db()
    rows = db.execute(
        "SELECT d.id, d.username, d.amount, d.method, d.status, d.created_at, "
        "p.email, p.phone "
        "FROM deposit_requests d LEFT JOIN players p ON p.id=d.player_id "
        "WHERE d.status='pending' ORDER BY d.created_at DESC LIMIT 100"
    ).fetchall()
    db.close()
    result = []
    for r in rows:
        result.append({
            'id': r['id'], 'username': r['username'],
            'amount': r['amount'], 'method': r['method'],
            'status': r['status'], 'created_at': r['created_at'],
            'contact': _mask_email(r['email']) if r['email'] else _mask_phone(r['phone']),
        })
    return ok(result)

@app.route('/api/worker/withdrawals', methods=['GET'])
def worker_get_withdrawals():
    agent, resp, code = _require_worker()
    if resp: return resp, code
    db   = get_db()
    rows = db.execute(
        "SELECT w.id, w.username, w.amount, w.method, w.address, w.status, w.created_at, "
        "p.email, p.phone "
        "FROM withdrawal_requests w LEFT JOIN players p ON p.id=w.player_id "
        "WHERE w.status='pending' ORDER BY w.created_at DESC LIMIT 100"
    ).fetchall()
    db.close()
    result = []
    for r in rows:
        result.append({
            'id': r['id'], 'username': r['username'],
            'amount': r['amount'], 'method': r['method'],
            'address': r['address'] or '—',
            'status': r['status'], 'created_at': r['created_at'],
            'contact': _mask_email(r['email']) if r['email'] else _mask_phone(r['phone']),
        })
    return ok(result)

@app.route('/api/worker/deposits/<int:rid>/approve', methods=['POST'])
def worker_approve_deposit(rid):
    agent, resp, code = _require_worker()
    if resp: return resp, code
    return approve_deposit.__wrapped__(rid)

@app.route('/api/worker/deposits/<int:rid>/reject', methods=['POST'])
def worker_reject_deposit(rid):
    agent, resp, code = _require_worker()
    if resp: return resp, code
    return reject_deposit.__wrapped__(rid)

@app.route('/api/worker/withdrawals/<int:rid>/approve', methods=['POST'])
def worker_approve_withdrawal(rid):
    agent, resp, code = _require_worker()
    if resp: return resp, code
    return approve_withdrawal.__wrapped__(rid)

@app.route('/api/worker/withdrawals/<int:rid>/reject', methods=['POST'])
def worker_reject_withdrawal(rid):
    agent, resp, code = _require_worker()
    if resp: return resp, code
    return reject_withdrawal.__wrapped__(rid)

@app.route('/api/worker/players', methods=['GET'])
def worker_get_players():
    agent, resp, code = _require_worker()
    if resp: return resp, code
    q  = (request.args.get('q') or '').strip()
    db = get_db()
    if q:
        rows = db.execute(
            "SELECT id,username,balance,fp_credits,status,created_at,email,phone "
            "FROM players WHERE username LIKE ? ORDER BY created_at DESC LIMIT 100",
            (f'%{q}%',)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id,username,balance,fp_credits,status,created_at,email,phone "
            "FROM players ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    db.close()
    result = []
    for r in rows:
        result.append({
            'id': r['id'], 'username': r['username'],
            'balance': r['balance'], 'fp_credits': r['fp_credits'],
            'status': r['status'], 'created_at': r['created_at'],
            'contact': _mask_email(r['email']) if r['email'] else _mask_phone(r['phone']),
        })
    return ok(result)

@app.route('/api/worker/players/<int:pid>', methods=['GET'])
def worker_get_player(pid):
    agent, resp, code = _require_worker()
    if resp: return resp, code
    db  = get_db()
    row = db.execute(
        "SELECT id,username,balance,fp_credits,status,created_at,email,phone "
        "FROM players WHERE id=?", (pid,)
    ).fetchone()
    if not row:
        db.close()
        return err('Player not found', 404)
    games = db.execute('SELECT id,game,game_username,balance,created_at FROM game_accounts WHERE player_id=?', (pid,)).fetchall()
    txns  = db.execute(
        "SELECT type,amount,status,notes,created_at FROM transactions WHERE player_id=? ORDER BY created_at DESC LIMIT 30",
        (pid,)
    ).fetchall()
    db.close()
    return ok({
        'id': row['id'], 'username': row['username'],
        'balance': row['balance'], 'fp_credits': row['fp_credits'],
        'status': row['status'], 'created_at': row['created_at'],
        'contact': _mask_email(row['email']) if row['email'] else _mask_phone(row['phone']),
        'game_accounts': rows_to_list(games),
        'transactions':  rows_to_list(txns),
    })

@app.route('/api/worker/players/<int:pid>/toggle-status', methods=['POST'])
def worker_toggle_player_status(pid):
    agent, resp, code = _require_worker()
    if resp: return resp, code
    return admin_toggle_player_status(pid)

@app.route('/api/worker/players/<int:pid>/reset-password', methods=['POST'])
def worker_reset_password(pid):
    agent, resp, code = _require_worker()
    if resp: return resp, code
    # Same admin switch as the panel's Players page
    if not _can_manage_players():
        return _deny('Only the admin can reset passwords right now.')
    return admin_reset_password(pid)

@app.route('/api/worker/conversations', methods=['GET'])
def worker_all_conversations():
    """All conversations across all agents — visible to any support worker."""
    agent, resp, code = _require_worker()
    if resp: return resp, code
    db   = get_db()
    rows = db.execute('''
        SELECT s.username, s.agent,
               MAX(s.created_at) as last_time,
               SUM(CASE WHEN s.sender='player' AND s.is_read=0 THEN 1 ELSE 0 END) as unread,
               (SELECT message FROM support_messages
                WHERE username=s.username AND agent=s.agent
                ORDER BY id DESC LIMIT 1) as last_message,
               (SELECT sender FROM support_messages
                WHERE username=s.username AND agent=s.agent
                ORDER BY id DESC LIMIT 1) as last_sender
        FROM support_messages s
        WHERE s.sender != 'system'
        GROUP BY s.username, s.agent
        ORDER BY unread DESC, last_time DESC
    ''').fetchall()
    db.close()
    return ok([dict(r) for r in rows])

@app.route('/api/worker/tickets', methods=['GET'])
def worker_tickets():
    """System-generated support tickets (e.g. manual withdrawal requests)."""
    agent, resp, code = _require_worker()
    if resp: return resp, code
    db   = get_db()
    rows = db.execute('''
        SELECT s.id, s.username, s.agent, s.message, s.is_read, s.created_at
        FROM support_messages s
        WHERE s.sender = 'player'
          AND s.message LIKE '%Manual Withdrawal%'
        ORDER BY s.created_at DESC LIMIT 200
    ''').fetchall()
    # Also grab any auto-generated system messages
    rows2 = db.execute('''
        SELECT s.id, s.username, s.agent, s.message, s.is_read, s.created_at
        FROM support_messages s
        WHERE s.sender = 'system'
        ORDER BY s.created_at DESC LIMIT 200
    ''').fetchall()
    db.close()
    seen = set()
    tickets = []
    for r in list(rows) + list(rows2):
        key = r['id']
        if key not in seen:
            seen.add(key)
            tickets.append(dict(r))
    tickets.sort(key=lambda x: x['created_at'], reverse=True)
    return ok(tickets)

@app.route('/api/worker/tickets/<int:tid>/close', methods=['POST'])
def worker_close_ticket(tid):
    agent, resp, code = _require_worker()
    if resp: return resp, code
    db = get_db()
    db.execute('UPDATE support_messages SET is_read=1 WHERE id=?', (tid,))
    db.commit()
    db.close()
    return ok({}, 'Ticket closed')

@app.route('/api/worker/players/create', methods=['POST'])
def worker_create_player():
    agent, resp, code = _require_worker()
    if resp: return resp, code
    return admin_create_player()

@app.route('/api/worker/players/<int:pid>/wallet-load', methods=['POST'])
def worker_wallet_load(pid):
    agent, resp, code = _require_worker()
    if resp: return resp, code
    return admin_credit_player(pid)

@app.route('/api/worker/players/<int:pid>/wallet-redeem', methods=['POST'])
def worker_wallet_redeem(pid):
    agent, resp, code = _require_worker()
    if resp: return resp, code
    return admin_redeem_player(pid)

@app.route('/api/worker/players/<int:pid>/game-balance', methods=['GET'])
def worker_game_balance(pid):
    agent, resp, code = _require_worker()
    if resp: return resp, code
    return get_player_game_balance(pid)

@app.route('/api/worker/players/<int:pid>/game-load', methods=['POST'])
def worker_game_load(pid):
    agent, resp, code = _require_worker()
    if resp: return resp, code
    return add_credits(pid)

@app.route('/api/worker/players/<int:pid>/game-redeem', methods=['POST'])
def worker_game_redeem(pid):
    agent, resp, code = _require_worker()
    if resp: return resp, code
    return withdraw_credits(pid)

# ─────────────────────────────────────────
#  SUPPORT AGENTS
# ─────────────────────────────────────────

def _hash_support_pw(pw):
    return _bcrypt.hashpw(pw.encode(), _bcrypt.gensalt()).decode()

def _check_support_pw(pw, stored):
    if stored.startswith('$2'):
        return _bcrypt.checkpw(pw.encode(), stored.encode())
    return hashlib.sha256(pw.encode()).hexdigest() == stored

def _make_support_token(agent_name):
    ts  = str(int(_time.time()))
    sig = hmac.new(_ADMIN_SECRET.encode(), (agent_name + ts).encode(), hashlib.sha256).hexdigest()[:40]
    import base64 as _b64
    raw = f'{agent_name}|{ts}|{sig}'
    return _b64.b64encode(raw.encode()).decode()

def _verify_support_token(token):
    try:
        import base64 as _b64
        raw   = _b64.b64decode(token.encode()).decode()
        parts = raw.split('|')
        if len(parts) != 3: return None
        agent_name, ts, sig = parts
        if int(_time.time()) - int(ts) > 86400 * 30: return None  # 30-day TTL
        expected = hmac.new(_ADMIN_SECRET.encode(), (agent_name + ts).encode(), hashlib.sha256).hexdigest()[:40]
        if not hmac.compare_digest(sig, expected): return None
        return agent_name
    except Exception:
        return None

def get_support_agent():
    """Return agent_name if request carries a valid support token, else None."""
    token = request.headers.get('X-Support-Token', '').strip()
    if not token: return None
    return _verify_support_token(token)

@app.route('/api/support/agents', methods=['GET'])
def list_support_agents():
    """Public: active agents for player-facing support/tip step, with online status."""
    db   = get_db()
    rows = db.execute(
        'SELECT id, name, icon, color, last_heartbeat FROM support_agents WHERE active=1 ORDER BY sort_order, id'
    ).fetchall()
    db.close()
    now = _time.time()
    agents = []
    for row in rows:
        hb = row['last_heartbeat']
        d  = dict(row)
        d['is_online'] = bool(hb and (now - hb) < 120)
        del d['last_heartbeat']
        agents.append(d)
    return ok(agents)

@app.route('/api/worker/heartbeat', methods=['POST'])
def worker_heartbeat():
    """Support agent pings this every 30s while logged in — marks them as online."""
    agent, resp, code = _require_worker()
    if resp: return resp, code
    db = get_db()
    db.execute('UPDATE support_agents SET last_heartbeat=? WHERE name=?', (_time.time(), agent['name']))
    db.commit()
    db.close()
    return ok({'ts': _time.time()})


@app.route('/api/support/agent-login', methods=['POST'])
def support_agent_login():
    data     = request.json or {}
    name     = (data.get('name') or '').strip()
    password = (data.get('password') or '').strip()
    if not name or not password:
        return err('Name and password required')
    db  = get_db()
    row = db.execute(
        'SELECT * FROM support_agents WHERE name=? AND active=1', (name,)
    ).fetchone()
    db.close()
    if not row:
        return err('Agent not found or inactive')
    if not row['password_hash']:
        return err('No password set for this agent — ask the admin to set one')
    if not _check_support_pw(password, row['password_hash']):
        return err('Incorrect password')
    token = _make_support_token(name)
    return ok({'token': token, 'name': name, 'icon': row['icon'], 'color': row['color']}, 'Logged in')

@app.route('/api/admin/support-agents', methods=['GET'])
@require_admin
def admin_list_support_agents():
    db   = get_db()
    rows = db.execute('SELECT id, name, icon, color, active, sort_order FROM support_agents ORDER BY sort_order, id').fetchall()
    db.close()
    return ok(rows_to_list(rows))

@app.route('/api/admin/support-agents', methods=['POST'])
@require_admin
def admin_create_support_agent():
    data     = request.json or {}
    name     = (data.get('name') or '').strip()
    icon     = (data.get('icon') or '🎧').strip()
    color    = (data.get('color') or '#6366f1').strip()
    password = (data.get('password') or '').strip()
    if not name: return err('Name is required')
    if not password or len(password) < 4: return err('Password must be at least 4 characters')
    pw_hash = _hash_support_pw(password)
    db = get_db()
    try:
        db.execute(
            'INSERT INTO support_agents (name, icon, color, password_hash, active) VALUES (?,?,?,?,1)',
            (name, icon, color, pw_hash)
        )
        db.commit()
        db.close()
        return ok({}, f'Agent "{name}" created')
    except Exception as e:
        db.close()
        if 'UNIQUE' in str(e) or 'unique' in str(e):
            return err('An agent with that name already exists')
        return err(str(e))

PROTECTED_AGENT = "BigWin Support"

@app.route('/api/admin/support-agents/<int:aid>', methods=['POST'])
@require_admin
def admin_update_support_agent(aid):
    data     = request.json or {}
    name     = (data.get('name') or '').strip()
    icon     = (data.get('icon') or '').strip()
    color    = (data.get('color') or '').strip()
    password = (data.get('password') or '').strip()
    active   = 1 if data.get('active', True) else 0
    if not name: return err('Name is required')
    db  = get_db()
    row = db.execute('SELECT id, name FROM support_agents WHERE id=?', (aid,)).fetchone()
    if not row:
        db.close()
        return err('Agent not found')
    # Prevent renaming or deactivating the protected default agent
    if row['name'] == PROTECTED_AGENT:
        name   = PROTECTED_AGENT
        active = 1
    if password:
        if len(password) < 4:
            db.close()
            return err('Password must be at least 4 characters')
        db.execute('UPDATE support_agents SET name=?,icon=?,color=?,active=?,password_hash=? WHERE id=?',
                   (name, icon, color, active, _hash_support_pw(password), aid))
    else:
        db.execute('UPDATE support_agents SET name=?,icon=?,color=?,active=? WHERE id=?',
                   (name, icon, color, active, aid))
    db.commit()
    db.close()
    return ok({}, 'Agent updated')

@app.route('/api/admin/support-agents/<int:aid>', methods=['DELETE'])
@require_admin
def admin_delete_support_agent(aid):
    db  = get_db()
    row = db.execute('SELECT name FROM support_agents WHERE id=?', (aid,)).fetchone()
    if row and row['name'] == PROTECTED_AGENT:
        db.close()
        return err(f'"{PROTECTED_AGENT}" is the default agent and cannot be removed')
    db.execute('DELETE FROM support_agents WHERE id=?', (aid,))
    db.commit()
    db.close()
    return ok({}, 'Agent deleted')

# ─────────────────────────────────────────
#  SUPPORT CHAT
# ─────────────────────────────────────────

_VISITOR_RE = re.compile(r'^visitor_[a-z0-9]{3,12}$')


def _support_access(username):
    """Who may read/write this support conversation: 'staff', 'player', 'visitor' or None.
    Staff = admin or a logged-in support agent. A registered player only with their own login
    token. Unregistered visitors only under their random visitor_xxxxx name."""
    if _verify_admin_token(request.headers.get('X-Admin-Token', '')) or get_support_agent():
        return 'staff', None
    db  = get_db()
    row = db.execute('SELECT id FROM players WHERE username=?', (username,)).fetchone()
    db.close()
    if row:
        ok_ = _verify_player_token(request.headers.get('X-Player-Token', ''), row['id'])
        return ('player', row['id']) if ok_ else (None, None)
    return ('visitor', None) if _VISITOR_RE.match(username or '') else (None, None)


@app.route('/api/support/messages', methods=['GET'])
def get_support_messages():
    username = request.args.get('username', '').strip()
    agent    = request.args.get('agent', "BigWin Support").strip()
    since_id = request.args.get('since_id', 0, type=int)
    preview  = request.args.get('preview', '').lower() in ('1', 'true')
    if not username:
        return err('username required')
    if not _support_access(username)[0]:
        return jsonify({'success': False, 'msg': 'Please sign in again.'}), 401
    db   = get_db()
    rows = db.execute(
        'SELECT * FROM support_messages WHERE username=? AND agent=? AND id>? ORDER BY id ASC',
        (username, agent, since_id)
    ).fetchall()
    if not preview:
        # only mark as read when the player actually opens the chat (not badge-count checks)
        db.execute('UPDATE support_messages SET is_read=1 WHERE username=? AND agent=? AND sender=?',
                   (username, agent, 'agent'))
        db.commit()
    db.close()
    return ok([dict(r) for r in rows])


@app.route('/api/support/messages', methods=['POST'])
def send_support_message():
    data     = request.json or {}
    username = data.get('username', '').strip()
    message  = data.get('message', '').strip()
    sender   = data.get('sender', 'player')
    agent    = data.get('agent', "BigWin Support")
    if not username or not message:
        return err('username and message required')
    if sender not in ('player', 'agent'):
        return err('Invalid sender')
    who, player_id = _support_access(username)
    # Only staff can write as support; players only into their own chat (no impersonation / phishing)
    if not who or (sender == 'agent' and who != 'staff'):
        return jsonify({'success': False, 'msg': 'Please sign in again.'}), 401
    if len(message) > 3_000_000:
        return err('Message too large')
    db  = get_db()
    cur = db.execute(
        'INSERT INTO support_messages (player_id, username, agent, sender, message) VALUES (?,?,?,?,?)',
        (player_id, username, agent, sender, message)
    )
    msg_id = cur.lastrowid
    db.commit()
    db.close()
    return ok({'id': msg_id}, 'Message sent')


_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]{2,}$')


@app.route('/api/support/contact', methods=['POST'])
@limiter.limit('3 per minute; 10 per hour')
def support_contact():
    """Public Support-page form → a ticket in the admin support inbox (thread 'contact:<email>').
    Kept out of players' own chats so nobody can post into someone else's conversation."""
    data    = request.json or {}
    name    = str(data.get('name') or '').strip()[:80]
    email   = str(data.get('email') or '').strip().lower()[:120]
    message = str(data.get('message') or '').strip()
    if not name:
        return err('Enter your name.')
    if not _EMAIL_RE.match(email):
        return err('Enter a valid email address.')
    if len(message) < 10:
        return err('Message must be at least 10 characters.')
    if len(message) > 3000:
        return err('Message is too long (3000 characters max).')
    text = (f'📩 Contact form — reply by email\nName: {name}\nEmail: {email}\n\n{message}')
    db = get_db()
    try:
        db.execute('INSERT INTO support_messages (player_id, username, agent, sender, message) VALUES (?,?,?,?,?)',
                   (None, f'contact:{email}', SUPPORT_DEFAULT_AGENT, 'player', text))
        db.commit()
    finally:
        db.close()
    return ok(msg="Thanks! We'll reply to your email soon.")


@app.route('/api/support/conversations', methods=['GET'])
def get_support_conversations():
    # Admin or a logged-in support agent (they answer chats from the admin panel)
    if not _verify_admin_token(request.headers.get('X-Admin-Token', '')) and not get_support_agent():
        return jsonify({'success': False, 'msg': 'Staff only'}), 401
    db   = get_db()
    rows = db.execute('''
        SELECT s.username, s.agent,
               MAX(s.created_at) as last_time,
               COUNT(*) as total,
               SUM(CASE WHEN s.sender='player' AND s.is_read=0 THEN 1 ELSE 0 END) as unread,
               (SELECT message FROM support_messages
                WHERE username=s.username AND agent=s.agent
                ORDER BY id DESC LIMIT 1) as last_message,
               (SELECT sender FROM support_messages
                WHERE username=s.username AND agent=s.agent
                ORDER BY id DESC LIMIT 1) as last_sender
        FROM support_messages s
        GROUP BY s.username, s.agent
        ORDER BY last_time DESC
    ''').fetchall()
    db.close()
    return ok([dict(r) for r in rows])


@app.route('/api/support/conversations/<username>', methods=['GET'])
def get_conversation(username):
    if _support_access(username)[0] != 'staff':
        return jsonify({'success': False, 'msg': 'Staff only'}), 401
    agent = request.args.get('agent', "BigWin Support")
    db    = get_db()
    rows  = db.execute(
        'SELECT * FROM support_messages WHERE username=? AND agent=? ORDER BY id ASC',
        (username, agent)
    ).fetchall()
    db.execute('UPDATE support_messages SET is_read=1 WHERE username=? AND agent=? AND sender=?',
               (username, agent, 'player'))
    db.commit()
    db.close()
    return ok([dict(r) for r in rows])


# ─────────────────────────────────────────
#  ROULETTE
# ─────────────────────────────────────────
import random as _random

@app.route('/api/roulette/prizes', methods=['GET'])
def roulette_prizes():
    db   = get_db()
    rows = db.execute(
        'SELECT * FROM roulette_prizes WHERE enabled=1 ORDER BY sort_order ASC, id ASC'
    ).fetchall()
    db.close()
    return ok([dict(r) for r in rows])


@app.route('/api/roulette/prizes', methods=['POST'])
@require_admin
def roulette_save_prizes():
    prizes = request.json or []
    if not isinstance(prizes, list):
        return err('Expected list of prizes')
    db = get_db()
    db.execute('DELETE FROM roulette_prizes', ())
    for i, p in enumerate(prizes):
        db.execute(
            'INSERT INTO roulette_prizes (label, color, text_color, weight, sort_order, enabled) VALUES (?,?,?,?,?,?)',
            (p.get('label','Prize'), p.get('color','#6366f1'), p.get('text_color','#fff'),
             int(p.get('weight', 10)), i, 1 if p.get('enabled', True) else 0)
        )
    db.commit()
    db.close()
    return ok(None, 'Prizes saved')


def _parse_prize(label):
    """Returns (type, value) for a prize label string."""
    ll = label.lower()
    m = (re.search(r'\$(\d+(?:\.\d+)?)\s*free\s*play', ll)          # old labels: "$5 Freeplay"
         or re.search(r'(\d+(?:\.\d+)?)\s*wz\b', ll))                   # "5 WZ Free Play"
    if m:
        return 'freeplay', float(m.group(1))
    m = re.search(r'(\d+(?:\.\d+)?)\s*%\s*deposit', ll)
    if m:
        return 'deposit_pct', float(m.group(1))
    if 'deposit bonus' in ll:
        return 'deposit_pct', 10.0
    if 'free spin' in ll:
        return 'free_spins', 0.0
    if 'vip' in ll:
        return 'vip_points', 0.0
    if 'mystery' in ll:
        return 'mystery', 0.0
    return 'other', 0.0


@app.route('/api/roulette/spin', methods=['POST'])
def roulette_spin():
    data      = request.json or {}
    username  = data.get('username', '').strip()
    player_id = data.get('player_id')
    admin_token  = request.headers.get('X-Admin-Token', '')
    player_token = request.headers.get('X-Player-Token', '')
    if not _verify_admin_token(admin_token) and not _verify_player_token(player_token, player_id):
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401
    if not username:
        return err('username required')

    db = get_db()

    # Check already spun in last 24 hours (timezone-safe rolling window)
    cutoff = (datetime.utcnow() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    today = db.execute(
        "SELECT id FROM roulette_spins WHERE username=? AND created_at >= ? ORDER BY id DESC LIMIT 1",
        (username, cutoff)
    ).fetchone()
    if today:
        db.close()
        return err('Already spun today. Come back tomorrow!', 429)

    prizes = db.execute(
        'SELECT * FROM roulette_prizes WHERE enabled=1 ORDER BY sort_order ASC, id ASC'
    ).fetchall()
    if not prizes:
        db.close()
        return err('No prizes configured')

    weights = [p['weight'] for p in prizes]
    total   = sum(weights)
    r       = _random.uniform(0, total)
    cumul   = 0
    winner_idx = 0
    for i, w in enumerate(weights):
        cumul += w
        if r <= cumul:
            winner_idx = i
            break

    winner = prizes[winner_idx]
    prize_label = winner['label']

    db.execute(
        'INSERT INTO roulette_spins (player_id, username, prize_id, prize_label) VALUES (?,?,?,?)',
        (player_id, username, winner['id'], prize_label)
    )

    prize_type, prize_value = _parse_prize(prize_label)
    reward_msg = ''

    if prize_type == 'freeplay' and prize_value > 0:
        # Credit freeplay immediately
        if player_id:
            db.execute('UPDATE players SET fp_credits = fp_credits + ? WHERE id=?', (prize_value, player_id))
        else:
            db.execute('UPDATE players SET fp_credits = fp_credits + ? WHERE username=?', (prize_value, username))
        db.execute(
            'INSERT INTO player_bonuses (player_id, username, type, value, label, status) VALUES (?,?,?,?,?,?)',
            (player_id, username, 'freeplay', prize_value, prize_label, 'applied')
        )
        reward_msg = f'{prize_value:.0f} WZ Free Play added to your account!'

    elif prize_type == 'deposit_pct' and prize_value > 0:
        # Store pending deposit bonus — applied on next deposit approval
        db.execute(
            'INSERT INTO player_bonuses (player_id, username, type, value, label, status) VALUES (?,?,?,?,?,?)',
            (player_id, username, 'deposit_pct', prize_value, prize_label, 'pending')
        )
        reward_msg = f'{prize_value:.0f}% deposit bonus unlocked! It will be added when your next deposit is approved.'

    else:
        db.execute(
            'INSERT INTO player_bonuses (player_id, username, type, value, label, status) VALUES (?,?,?,?,?,?)',
            (player_id, username, prize_type, prize_value, prize_label, 'pending')
        )
        reward_msg = f'{prize_label} recorded! Our team will apply it shortly.'

    db.commit()
    db.close()

    return ok({
        'prize_index': winner_idx,
        'prize': dict(winner),
        'reward_msg': reward_msg,
        'prize_type': prize_type,
        'prize_value': prize_value,
    })


@app.route('/api/roulette/spins', methods=['GET'])
@require_admin
def roulette_spins():
    db   = get_db()
    rows = db.execute(
        'SELECT * FROM roulette_spins ORDER BY id DESC LIMIT 200'
    ).fetchall()
    db.close()
    return ok([dict(r) for r in rows])


@app.route('/api/roulette/reset', methods=['POST'])
@require_admin
def roulette_reset():
    """Admin: delete all spins for a player so they can spin again."""
    data     = request.json or {}
    username = data.get('username', '').strip()
    if not username:
        return err('username required')
    db = get_db()
    db.execute('DELETE FROM roulette_spins WHERE username=?', (username,))
    db.commit()
    db.close()
    return ok({'reset': True})


@app.route('/api/roulette/check', methods=['GET'])
def roulette_check():
    username = request.args.get('username', '').strip()
    if not username:
        return ok({'can_spin': True})
    db     = get_db()
    cutoff = (datetime.utcnow() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    today  = db.execute(
        "SELECT prize_label, created_at FROM roulette_spins WHERE username=? AND created_at >= ? ORDER BY id DESC LIMIT 1",
        (username, cutoff)
    ).fetchone()
    db.close()
    if today:
        return ok({'can_spin': False, 'last_prize': today['prize_label'], 'spun_at': today['created_at']})
    return ok({'can_spin': True})


# ─────────────────────────────────────────
#  PHONE VERIFICATION
# ─────────────────────────────────────────
import random as _rnd_phone

# Codes live in the database (table phone_otps): gunicorn runs several workers,
# so a code kept in one worker's memory was "not found" when Verify hit another.
_OTP_MAX_TRIES = 5


def _normalize_phone(raw):
    """'(555) 123-4567' → '+15551234567'. US/Canada numbers get +1; others must start with +."""
    raw = (raw or '').strip()
    digits = re.sub(r'\D', '', raw)
    if raw.startswith('+'):
        return '+' + digits if 8 <= len(digits) <= 15 else None
    if len(digits) == 10:
        return '+1' + digits
    if len(digits) == 11 and digits.startswith('1'):
        return '+' + digits
    return None


def _otp_hash(username, code):
    return hmac.new(_ADMIN_SECRET.encode(), f'{username}:{code}'.encode(), hashlib.sha256).hexdigest()

@app.route('/api/verify/phone/send', methods=['POST'])
@limiter.limit('3 per minute; 10 per hour')
def verify_phone_send():
    import time
    admin_token  = request.headers.get('X-Admin-Token', '')
    player_token = request.headers.get('X-Player-Token', '')
    data     = request.json or {}
    username = data.get('username', '').strip()
    if not username or not data.get('phone'):
        return err('username and phone required')
    phone = _normalize_phone(data.get('phone'))
    if not phone:
        return err('Enter a valid phone number, e.g. (555) 123-4567 or +44 7700 900123')

    db = get_db()
    player = db.execute('SELECT id, phone_verified, phone FROM players WHERE username=?', (username,)).fetchone()
    if not player:
        db.close()
        return err('Player not found', 404)
    if not _verify_admin_token(admin_token) and not _verify_player_token(player_token, player['id']):
        db.close()
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401
    if player.get('phone_verified'):
        db.close()
        return err('Phone already verified')
    if db.execute('SELECT id FROM players WHERE phone=? AND phone_verified=1 AND id<>?', (phone, player['id'])).fetchone():
        db.close()
        return err('This phone number is already verified on another account.')

    sms_provider, sms_cfg = _get_sms_config()
    if sms_provider == 'twilio_verify':
        try:
            r = _http.post(f'https://verify.twilio.com/v2/Services/{sms_cfg["service"]}/Verifications',
                           data={'To': phone, 'Channel': 'sms'}, auth=(sms_cfg['sid'], sms_cfg['token']), timeout=15)
            d = r.json()
        except Exception as e:
            db.close()
            return err(f'SMS failed: {e}')
        if r.status_code not in (200, 201):
            db.close()
            return err(f'SMS failed: {d.get("message", r.status_code)}')
        db.execute('DELETE FROM phone_otps WHERE username=?', (username,))
        db.execute('INSERT INTO phone_otps (username, phone, code_hash, expires, tries) VALUES (?,?,?,?,0)',
                   (username, phone, 'twilio_verify', int(time.time()) + 600))
        db.commit()
        db.close()
        return ok({'sms_sent': True, 'phone': phone}, f'Code sent to {phone}')

    code = str(_secrets.randbelow(900000) + 100000)
    db.execute('DELETE FROM phone_otps WHERE username=?', (username,))
    db.execute('INSERT INTO phone_otps (username, phone, code_hash, expires, tries) VALUES (?,?,?,?,0)',
               (username, phone, _otp_hash(username, code), int(time.time()) + 600))
    db.commit()

    sms_text = f"Your BigWin Gaming verification code is: {code}"

    if sms_provider == 'telnyx':
        import urllib.request, json as _json
        try:
            payload = _json.dumps({'from': sms_cfg['from'], 'to': phone, 'text': sms_text}).encode()
            req = urllib.request.Request(
                'https://api.telnyx.com/v2/messages', data=payload,
                headers={'Content-Type': 'application/json',
                         'Authorization': f'Bearer {sms_cfg["key"]}'},
                method='POST'
            )
            urllib.request.urlopen(req, timeout=10)
            db.close()
            return ok({'sms_sent': True, 'phone': phone}, f'Code sent to {phone}')
        except Exception as e:
            db.close()
            return err(f'SMS failed: {e}')
    elif sms_provider == 'twilio':
        try:
            from twilio.rest import Client
            tw = Client(sms_cfg['sid'], sms_cfg['token'])
            tw.messages.create(body=sms_text, from_=sms_cfg['from'], to=phone)
            db.close()
            return ok({'sms_sent': True, 'phone': phone}, f'Code sent to {phone}')
        except Exception as e:
            db.close()
            return err(f'SMS failed: {e}')
    else:
        if os.environ.get('SMS_DEMO') != '1':
            # No SMS provider: never show the code on screen — that let anyone claim +5 WZ with made-up numbers
            db.execute('DELETE FROM phone_otps WHERE username=?', (username,))
            db.commit()
            db.close()
            return err('Phone verification isn\'t available yet. Please check back soon.')
        db.close()
        return ok({'sms_sent': False, 'demo_code': code, 'phone': phone}, 'Demo mode — no SMS sent')


@app.route('/api/verify/phone/confirm', methods=['POST'])
def verify_phone_confirm():
    import time
    admin_token  = request.headers.get('X-Admin-Token', '')
    player_token = request.headers.get('X-Player-Token', '')
    data     = request.json or {}
    username = data.get('username', '').strip()
    code     = re.sub(r'\D', '', str(data.get('code', '')))
    if not username or not code:
        return err('username and code required')

    db = get_db()
    player = db.execute('SELECT id, phone_verified FROM players WHERE username=?', (username,)).fetchone()
    if not player:
        db.close()
        return err('Player not found', 404)
    if not _verify_admin_token(admin_token) and not _verify_player_token(player_token, player['id']):
        db.close()
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401
    if player.get('phone_verified'):
        db.close()
        return err('Phone already verified')

    otp = db.execute('SELECT * FROM phone_otps WHERE username=?', (username,)).fetchone()
    if not otp:
        db.close()
        return err('No pending verification. Please request a new code.')
    if time.time() > otp['expires'] or otp['tries'] >= _OTP_MAX_TRIES:
        db.execute('DELETE FROM phone_otps WHERE username=?', (username,))
        db.commit()
        db.close()
        return err('Code expired. Please request a new one.')
    if otp['code_hash'] == 'twilio_verify':
        _p, vcfg = _get_sms_config()
        try:
            r = _http.post(f'https://verify.twilio.com/v2/Services/{vcfg["service"]}/VerificationCheck',
                           data={'To': otp['phone'], 'Code': code}, auth=(vcfg['sid'], vcfg['token']), timeout=15)
            code_ok = r.status_code == 200 and r.json().get('status') == 'approved'
        except Exception:
            db.close()
            return err('Could not check the code right now. Please try again.')
    else:
        code_ok = hmac.compare_digest(otp['code_hash'], _otp_hash(username, code))
    if not code_ok:
        db.execute('UPDATE phone_otps SET tries = tries + 1 WHERE username=?', (username,))
        db.commit()
        left = _OTP_MAX_TRIES - otp['tries'] - 1
        db.close()
        return err(f'Invalid code. {left} tries left.' if left > 0 else 'Invalid code. Please request a new one.')

    # Verify the number the code was actually sent to — never one sent with the code
    phone = otp['phone']
    claimed = db.execute("DELETE FROM phone_otps WHERE username=? AND code_hash=?", (username, otp['code_hash']))
    db.commit()
    if claimed.rowcount == 0:  # a parallel request used it first
        db.close()
        return err('Code already used.')
    if db.execute('SELECT id FROM players WHERE phone=? AND phone_verified=1 AND id<>?', (phone, player['id'])).fetchone():
        db.close()
        return err('This phone number is already verified on another account.')

    db.execute('UPDATE players SET phone=?, phone_verified=1, fp_credits=fp_credits+5 WHERE username=? AND phone_verified=0',
               (phone, username))
    db.execute(
        'INSERT INTO transactions (player_id, username, type, amount, status, notes) VALUES (?,?,?,?,?,?)',
        (player['id'], username, 'phone_verify_bonus', 5.0, 'approved', '+5 WZ for phone verification')
    )
    db.commit()
    db.close()
    return ok({'fp_added': 5}, 'Phone verified! +5 WZ Free Play added.')


@app.route('/api/players/bonuses', methods=['GET'])
def player_bonuses():
    admin_token  = request.headers.get('X-Admin-Token', '')
    player_token = request.headers.get('X-Player-Token', '')
    username = request.args.get('username', '').strip()
    if not username:
        return err('username required')
    db   = get_db()
    _p   = db.execute('SELECT id FROM players WHERE username=?', (username,)).fetchone()
    _pid = _p['id'] if _p else None
    if not _verify_admin_token(admin_token) and not _verify_player_token(player_token, _pid):
        db.close()
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401
    rows = db.execute(
        "SELECT * FROM player_bonuses WHERE username=? ORDER BY id DESC",
        (username,)
    ).fetchall()
    db.close()
    return ok([dict(r) for r in rows])


# ─────────────────────────────────────────
#  MARKETPLACE
# ─────────────────────────────────────────

@app.route('/api/marketplace/tiers', methods=['GET'])
def marketplace_tiers():
    db   = get_db()
    rows = db.execute(
        'SELECT * FROM marketplace_tiers WHERE enabled=1 ORDER BY sort_order ASC, id ASC'
    ).fetchall()
    db.close()
    return ok([dict(r) for r in rows])


@app.route('/api/marketplace/tiers', methods=['POST'])
@require_admin
def marketplace_save_tiers():
    tiers = request.json or []
    if not isinstance(tiers, list):
        return err('Expected list of tiers')
    db = get_db()
    db.execute('DELETE FROM marketplace_tiers', ())
    for i, t in enumerate(tiers):
        db.execute(
            'INSERT INTO marketplace_tiers (tier_label, name, fp_cost, cash_value, badge, sort_order, enabled) VALUES (?,?,?,?,?,?,?)',
            (t.get('tier_label','TIER'), t.get('name','Tier'), int(t.get('fp_cost',100)),
             t.get('cash_value','$0'), t.get('badge',''), i,
             1 if t.get('enabled', True) else 0)
        )
    db.commit()
    db.close()
    return ok(None, 'Tiers saved')


@app.route('/api/marketplace/redeem', methods=['POST'])
def marketplace_redeem():
    data      = request.json or {}
    username  = data.get('username', '').strip()
    player_id = data.get('player_id')
    admin_token  = request.headers.get('X-Admin-Token', '')
    player_token = request.headers.get('X-Player-Token', '')
    if not _verify_admin_token(admin_token) and not _verify_player_token(player_token, player_id):
        return jsonify({'success': False, 'msg': 'Authentication required'}), 401
    tier_id   = data.get('tier_id')
    if not username or not tier_id:
        return err('username and tier_id required')

    db   = get_db()
    tier = db.execute('SELECT * FROM marketplace_tiers WHERE id=? AND enabled=1', (tier_id,)).fetchone()
    if not tier:
        db.close()
        return err('Tier not found')

    # Check player FP balance
    player = None
    if player_id:
        player = db.execute('SELECT * FROM players WHERE id=?', (player_id,)).fetchone()
    if not player:
        player = db.execute('SELECT * FROM players WHERE username=?', (username,)).fetchone()

    if not player:
        db.close()
        return err('Player not found')

    fp_cost = tier['fp_cost']
    if player['fp_credits'] < fp_cost:
        db.close()
        return err(f'Not enough WZ. You have {player["fp_credits"]:.0f} WZ, need {fp_cost} WZ.')

    # Deduct FP
    db.execute('UPDATE players SET fp_credits = fp_credits - ? WHERE id=?', (fp_cost, player['id']))

    # Create redemption record
    cur = db.execute(
        'INSERT INTO marketplace_redemptions (player_id, username, tier_id, tier_name, fp_spent, cash_value) VALUES (?,?,?,?,?,?)',
        (player['id'], username, tier_id, tier['name'], fp_cost, tier['cash_value'])
    )
    redemption_id = cur.lastrowid

    db.execute(
        'INSERT INTO transactions (player_id, username, type, amount, status, method, notes) VALUES (?,?,?,?,?,?,?)',
        (player['id'], username, 'marketplace_redeem', fp_cost, 'pending', 'marketplace',
         f'{tier["name"]} — {tier["cash_value"]} (redemption #{redemption_id})')
    )
    db.commit()
    db.close()
    return ok({
        'redemption_id': redemption_id,
        'tier_name': tier['name'],
        'cash_value': tier['cash_value'],
        'fp_spent': fp_cost,
    }, f'Redemption submitted! {tier["cash_value"]} will be sent within 24 hours.')


@app.route('/api/marketplace/redemptions', methods=['GET'])
@require_admin
def marketplace_redemptions():
    db   = get_db()
    rows = db.execute(
        'SELECT * FROM marketplace_redemptions ORDER BY id DESC LIMIT 200'
    ).fetchall()
    db.close()
    return ok([dict(r) for r in rows])


@app.route('/api/marketplace/redemptions/<int:rid>/approve', methods=['POST'])
@require_admin
def marketplace_approve(rid):
    data  = request.json or {}
    notes = data.get('notes', '')
    db    = get_db()
    row   = db.execute('SELECT * FROM marketplace_redemptions WHERE id=?', (rid,)).fetchone()
    if not row:
        db.close()
        return err('Redemption not found', 404)

    # Parse "$1,000" → 1000.0
    try:
        cash_amount = float(row['cash_value'].replace('$', '').replace(',', '').strip())
    except Exception:
        cash_amount = 0.0

    db.execute("UPDATE marketplace_redemptions SET status='paid', notes=? WHERE id=?", (notes, rid))

    if row['player_id'] and cash_amount > 0:
        db.execute('UPDATE players SET balance = balance + ? WHERE id=?', (cash_amount, row['player_id']))
        db.execute(
            'INSERT INTO transactions (player_id, username, type, amount, status, method, notes) VALUES (?,?,?,?,?,?,?)',
            (row['player_id'], row['username'], 'marketplace_payout', cash_amount, 'approved',
             'marketplace', f'{row["tier_name"]} redemption #{rid}')
        )

    db.commit()
    db.close()
    return ok(msg=f'Redemption #{rid} paid — ${cash_amount:.2f} added to {row["username"]} balance')


@app.route('/api/marketplace/redemptions/<int:rid>/reject', methods=['POST'])
@require_admin
def marketplace_reject(rid):
    data  = request.json or {}
    notes = data.get('notes', '')
    db    = get_db()
    row   = db.execute('SELECT * FROM marketplace_redemptions WHERE id=?', (rid,)).fetchone()
    if not row:
        db.close()
        return err('Redemption not found', 404)
    # Refund FP
    db.execute("UPDATE marketplace_redemptions SET status='rejected', notes=? WHERE id=?", (notes, rid))
    if row['player_id']:
        db.execute('UPDATE players SET fp_credits = fp_credits + ? WHERE id=?', (row['fp_spent'], row['player_id']))
    db.commit()
    db.close()
    return ok(msg=f'Redemption #{rid} rejected and {row["fp_spent"]} FP refunded')


@app.route('/api/stats/finance', methods=['GET'])
@require_admin
def stats_finance():
    db = get_db()
    total_dep   = db.execute("SELECT COALESCE(SUM(amount),0) as s FROM deposit_requests WHERE status='approved'").fetchone()['s']
    total_wd    = db.execute("SELECT COALESCE(SUM(amount),0) as s FROM withdrawal_requests WHERE status='approved'").fetchone()['s']
    pending_dep = db.execute("SELECT COALESCE(SUM(amount),0) as s FROM deposit_requests WHERE status='pending'").fetchone()['s']
    pending_wd  = db.execute("SELECT COALESCE(SUM(amount),0) as s FROM withdrawal_requests WHERE status='pending'").fetchone()['s']
    by_method   = db.execute("SELECT method, SUM(amount) as total, COUNT(*) as cnt FROM deposit_requests WHERE status='approved' GROUP BY method").fetchall()
    recent      = db.execute("SELECT username, type, amount, status, created_at FROM transactions ORDER BY created_at DESC LIMIT 10").fetchall()
    db.close()
    return ok({
        'total_deposited':  round(total_dep, 2),
        'total_withdrawn':  round(total_wd, 2),
        'net':              round(total_dep - total_wd, 2),
        'pending_deposits': round(pending_dep, 2),
        'pending_withdrawals': round(pending_wd, 2),
        'by_method': [dict(r) for r in by_method],
        'recent':    [dict(r) for r in recent],
    })


@app.route('/api/stats/players', methods=['GET'])
@require_admin
def stats_players():
    db = get_db()
    total    = db.execute('SELECT COUNT(*) as c FROM players').fetchone()['c']
    active   = db.execute("SELECT COUNT(*) as c FROM players WHERE status='active'").fetchone()['c']
    with_bal = db.execute('SELECT COUNT(*) as c FROM players WHERE balance > 0').fetchone()['c']
    top      = db.execute('SELECT username, balance, fp_credits, created_at FROM players ORDER BY balance DESC LIMIT 10').fetchall()
    recent   = db.execute('SELECT username, balance, status, created_at FROM players ORDER BY created_at DESC LIMIT 10').fetchall()
    games_ct = db.execute('SELECT game, COUNT(*) as cnt FROM game_accounts GROUP BY game ORDER BY cnt DESC').fetchall()
    db.close()
    return ok({
        'total': total, 'active': active, 'with_balance': with_bal,
        'top_players':    [dict(r) for r in top],
        'recent_players': [dict(r) for r in recent],
        'by_game':        [dict(r) for r in games_ct],
    })


@app.route('/api/stats/payments', methods=['GET'])
@require_admin
def stats_payments():
    db = get_db()
    dep_by_method = db.execute("SELECT method, COUNT(*) as cnt, COALESCE(SUM(amount),0) as total FROM deposit_requests GROUP BY method").fetchall()
    wd_by_method  = db.execute("SELECT method, COUNT(*) as cnt, COALESCE(SUM(amount),0) as total FROM withdrawal_requests GROUP BY method").fetchall()
    dep_status    = db.execute("SELECT status, COUNT(*) as cnt FROM deposit_requests GROUP BY status").fetchall()
    wd_status     = db.execute("SELECT status, COUNT(*) as cnt FROM withdrawal_requests GROUP BY status").fetchall()
    db.close()
    return ok({
        'deposits_by_method':    [dict(r) for r in dep_by_method],
        'withdrawals_by_method': [dict(r) for r in wd_by_method],
        'deposit_status':        [dict(r) for r in dep_status],
        'withdrawal_status':     [dict(r) for r in wd_status],
    })


@app.route('/api/game-records', methods=['GET'])
@require_admin
def game_records():
    db   = get_db()
    game = request.args.get('game', '')
    sql  = 'SELECT ga.*, p.username as player FROM game_accounts ga JOIN players p ON p.id=ga.player_id'
    if game:
        rows = db.execute(sql + ' WHERE ga.game=? ORDER BY ga.created_at DESC', (game,)).fetchall()
    else:
        rows = db.execute(sql + ' ORDER BY ga.created_at DESC LIMIT 100').fetchall()
    db.close()
    return ok([dict(r) for r in rows])


@app.route('/api/stats/games', methods=['GET'])
@require_admin
def stats_games():
    db   = get_db()
    rows = db.execute("""
        SELECT b.game, b.name, b.status, b.enabled, b.balance as agent_balance,
               COUNT(ga.id) as player_count,
               COALESCE(SUM(ga.balance),0) as players_balance
        FROM backends b
        LEFT JOIN game_accounts ga ON ga.game = b.game
        GROUP BY b.id ORDER BY player_count DESC
    """).fetchall()
    db.close()
    return ok([dict(r) for r in rows])


_CASHOUT_DEFAULTS = {
    'min_cashout':          10,
    'max_cashout':          500,
    'daily_limit':          1000,
    'wagering_multiplier':  1,
}

def _get_cashout_rules(db):
    import json as _json
    try:
        row = db.execute("SELECT value FROM site_settings WHERE key='cashout_rules'").fetchone()
        if row:
            return {**_CASHOUT_DEFAULTS, **_json.loads(row['value'])}
    except Exception:
        pass
    return _CASHOUT_DEFAULTS.copy()

@app.route('/api/cashout-rules', methods=['GET'])
def get_cashout_rules():
    import json as _json
    db  = get_db()
    try:
        row   = db.execute("SELECT value FROM site_settings WHERE key='cashout_rules'").fetchone()
        rules = _json.loads(row['value']) if row else _CASHOUT_DEFAULTS.copy()
    except Exception:
        rules = _CASHOUT_DEFAULTS.copy()
    db.close()
    return jsonify({'success': True, 'data': rules})

@app.route('/api/cashout-rules', methods=['POST'])
@require_admin
def save_cashout_rules():
    import json as _json
    data = request.get_json() or {}
    rules = {
        'min_cashout':         float(data.get('min_cashout',         _CASHOUT_DEFAULTS['min_cashout'])),
        'max_cashout':         float(data.get('max_cashout',         _CASHOUT_DEFAULTS['max_cashout'])),
        'daily_limit':         float(data.get('daily_limit',         _CASHOUT_DEFAULTS['daily_limit'])),
        'wagering_multiplier': float(data.get('wagering_multiplier', _CASHOUT_DEFAULTS['wagering_multiplier'])),
    }
    db  = get_db()
    val = _json.dumps(rules)
    try:
        # Bypass the DB wrapper to avoid its auto-appended "RETURNING id"
        # which fails because site_settings has no id column.
        if db._is_pg:
            cur = db._conn.cursor()
            cur.execute(
                "INSERT INTO site_settings(key,value) VALUES(%s,%s) "
                "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                ('cashout_rules', val)
            )
        else:
            db._conn.execute(
                "INSERT INTO site_settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ('cashout_rules', val)
            )
        db.commit()
    except Exception as e:
        db.close()
        return jsonify({'success': False, 'msg': str(e)}), 500
    db.close()
    return jsonify({'success': True, 'data': rules})

@app.route('/api/admin/keyhub-config', methods=['GET', 'POST'])
@require_admin
def admin_keyhub_config():
    if request.method == 'GET':
        key = _get_keyhub_key()
        preview = (key[:8] + '•••' + key[-4:]) if len(key) > 12 else ('•' * len(key) if key else '')
        return jsonify({'success': True, 'data': {'configured': bool(key), 'key_preview': preview}})
    # POST — save new key
    import json as _json
    data = request.get_json() or {}
    new_key = data.get('api_key', '').strip()
    if not new_key:
        return jsonify({'success': False, 'msg': 'API key is required'}), 400
    db = get_db()
    try:
        if db._is_pg:
            cur = db._conn.cursor()
            cur.execute(
                "INSERT INTO site_settings(key,value) VALUES(%s,%s) "
                "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                ('keyhub_api_key', new_key)
            )
        else:
            db._conn.execute(
                "INSERT INTO site_settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ('keyhub_api_key', new_key)
            )
        db.commit()
    except Exception as e:
        db.close()
        return jsonify({'success': False, 'msg': str(e)}), 500
    db.close()
    return jsonify({'success': True, 'msg': 'KeyHub API key saved'})

@app.route('/api/admin/keyhub-disconnect', methods=['POST'])
@require_admin
def admin_keyhub_disconnect():
    db = get_db()
    try:
        if db._is_pg:
            cur = db._conn.cursor()
            cur.execute("DELETE FROM site_settings WHERE key='keyhub_api_key'")
        else:
            db._conn.execute("DELETE FROM site_settings WHERE key='keyhub_api_key'")
        db.commit()
    except Exception as e:
        db.close()
        return jsonify({'success': False, 'msg': str(e)}), 500
    db.close()
    return jsonify({'success': True, 'msg': 'KeyHub disconnected'})

@app.route('/api/admin/keyhub-test', methods=['GET'])
@require_admin
def admin_keyhub_test():
    import requests as _req
    key = _get_keyhub_key()
    if not key:
        return jsonify({'success': False, 'msg': 'No API key configured — save one first'})
    try:
        r = _http.get(
            f'{KEYHUB_BASE}/api/v1/ping',
            headers={'X-API-Key': key},
            timeout=8,
        )
        if r.status_code in (200, 204):
            return jsonify({'success': True})
        # Some gateways return 401 for bad key, 200 for good
        return jsonify({'success': False, 'msg': f'KeyHub returned HTTP {r.status_code} — check your API key'})
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Could not reach KeyHub: {e}'})

@app.route('/api/payment-status', methods=['GET'])
def payment_status():
    """Public: tells the frontend whether KeyHub payout is active."""
    return ok({'keyhub_payout': bool(_get_keyhub_key())})


def _get_sms_config():
    """Return (provider, config_dict) from DB or env vars. provider is 'telnyx'|'twilio'|None."""
    db = get_db()
    vals = {}
    try:
        rows = db.execute(
            "SELECT key, value FROM site_settings WHERE key IN "
            "('sms_provider','telnyx_api_key','telnyx_from','twilio_sid','twilio_token','twilio_from','twilio_verify_sid')"
        ).fetchall()
        for r in rows:
            vals[r['key']] = r['value']
    except Exception: pass
    db.close()

    provider = vals.get('sms_provider') or ''

    # Twilio Verify: Twilio makes, sends and checks the code — no US 10DLC registration needed
    if provider == 'twilio_verify':
        sid, token, svc = vals.get('twilio_sid'), vals.get('twilio_token'), vals.get('twilio_verify_sid')
        if sid and token and svc:
            return 'twilio_verify', {'sid': sid, 'token': token, 'service': svc, 'from': 'Twilio Verify'}

    if provider == 'twilio' or (not provider and os.environ.get('TWILIO_ACCOUNT_SID')):
        sid   = vals.get('twilio_sid')   or os.environ.get('TWILIO_ACCOUNT_SID', '')
        token = vals.get('twilio_token') or os.environ.get('TWILIO_AUTH_TOKEN', '')
        frm   = vals.get('twilio_from')  or os.environ.get('TWILIO_FROM', '')
        if sid and token and frm:
            return 'twilio', {'sid': sid, 'token': token, 'from': frm}

    if provider == 'telnyx' or (not provider and os.environ.get('TELNYX_API_KEY')):
        key = vals.get('telnyx_api_key') or os.environ.get('TELNYX_API_KEY', '')
        frm = vals.get('telnyx_from')    or os.environ.get('TELNYX_FROM', '')
        if key and frm:
            return 'telnyx', {'key': key, 'from': frm}

    return None, {}


@app.route('/api/admin/sms-config', methods=['GET', 'POST'])
@require_admin
def admin_sms_config():
    if request.method == 'GET':
        provider, cfg = _get_sms_config()
        if provider:
            return ok({'configured': True, 'provider': 'Twilio Verify' if provider == 'twilio_verify' else provider.capitalize(),
                       'from_preview': cfg.get('from', '')})
        return ok({'configured': False})

    data     = request.json or {}
    provider = (data.get('provider') or '').strip().lower()
    db = get_db()

    if provider == 'twilio_verify':
        sid   = (data.get('twilio_sid')   or '').strip()
        token = (data.get('twilio_token') or '').strip()
        svc   = (data.get('verify_sid')   or '').strip()
        if not sid.startswith('AC') or not token or not svc.startswith('VA'):
            db.close()
            return err('Account SID (AC…), Auth Token and Verify Service SID (VA…) are required')
        try:  # check the keys before saving
            r = _http.get(f'https://verify.twilio.com/v2/Services/{svc}', auth=(sid, token), timeout=10)
        except Exception as e:
            db.close()
            return err(f'Could not reach Twilio: {e}')
        if r.status_code != 200:
            db.close()
            return err(f'Twilio refused these keys: {(r.json() if r.content else {}).get("message", r.status_code)}')
        _upsert_setting(db, 'sms_provider',      'twilio_verify')
        _upsert_setting(db, 'twilio_sid',        sid)
        _upsert_setting(db, 'twilio_token',      token)
        _upsert_setting(db, 'twilio_verify_sid', svc)
        db.close()
        return ok(msg=f'Twilio Verify activated ({r.json().get("friendly_name", svc)})')
    if provider == 'twilio':
        sid   = (data.get('twilio_sid')   or '').strip()
        token = (data.get('twilio_token') or '').strip()
        frm   = (data.get('twilio_from')  or '').strip()
        if not sid or not token or not frm:
            return err('twilio_sid, twilio_token and twilio_from required')
        _upsert_setting(db, 'sms_provider',  'twilio')
        _upsert_setting(db, 'twilio_sid',    sid)
        _upsert_setting(db, 'twilio_token',  token)
        _upsert_setting(db, 'twilio_from',   frm)
    elif provider == 'telnyx':
        key = (data.get('telnyx_api_key') or '').strip()
        frm = (data.get('telnyx_from')    or '').strip()
        if not key or not frm:
            return err('telnyx_api_key and telnyx_from required')
        _upsert_setting(db, 'sms_provider',   'telnyx')
        _upsert_setting(db, 'telnyx_api_key', key)
        _upsert_setting(db, 'telnyx_from',    frm)
    else:
        db.close()
        return err('provider must be twilio_verify, twilio or telnyx')

    db.commit(); db.close()
    return ok(msg=f'SMS config saved — {provider.capitalize()} activated')


@app.route('/api/admin/sms-disconnect', methods=['POST'])
@require_admin
def admin_sms_disconnect():
    db = get_db()
    try:
        for k in ('sms_provider','telnyx_api_key','telnyx_from','twilio_sid','twilio_token','twilio_from','twilio_verify_sid'):
            db.execute("DELETE FROM site_settings WHERE key=?", (k,))
        db.commit()
    except Exception: pass
    db.close()
    return ok(msg='SMS config removed')

@app.route('/api/payment-methods', methods=['GET'])
def payment_methods():
    """Player-facing: returns only enabled methods (no admin fields)."""
    db   = get_db()
    rows = db.execute(
        "SELECT key,name,icon,address,qr_image,payment_link,instructions FROM payment_methods WHERE enabled=1 ORDER BY sort_order"
    ).fetchall()
    db.close()
    return ok(rows_to_list(rows))

@app.route('/api/admin/payment-methods', methods=['GET'])
@require_admin
def admin_get_payment_methods():
    """Admin: returns all methods including disabled ones."""
    db   = get_db()
    rows = db.execute('SELECT * FROM payment_methods ORDER BY sort_order').fetchall()
    db.close()
    return ok(rows_to_list(rows))

@app.route('/api/admin/payment-methods/<key>', methods=['POST'])
@require_admin
def admin_update_payment_method(key):
    """Admin: create or update a payment method."""
    data  = request.json or {}
    name         = (data.get('name') or '').strip()
    icon         = (data.get('icon') or '').strip()
    enabled      = 1 if data.get('enabled', True) else 0
    address      = (data.get('address') or '').strip()
    qr_image     = (data.get('qr_image') or '').strip()
    payment_link = (data.get('payment_link') or '').strip()
    instructions = (data.get('instructions') or '').strip()
    sort_order   = int(data.get('sort_order', 0) or 0)
    if not name: return err('Name is required')
    db = get_db()
    existing = db.execute('SELECT key FROM payment_methods WHERE key=?', (key,)).fetchone()
    if existing:
        db.execute(
            'UPDATE payment_methods SET name=?,icon=?,enabled=?,address=?,qr_image=?,payment_link=?,instructions=?,sort_order=? WHERE key=?',
            (name, icon, enabled, address, qr_image, payment_link, instructions, sort_order, key)
        )
    else:
        db.execute(
            'INSERT INTO payment_methods (key,name,icon,enabled,address,qr_image,payment_link,instructions,sort_order) VALUES (?,?,?,?,?,?,?,?,?)',
            (key, name, icon, enabled, address, qr_image, payment_link, instructions, sort_order)
        )
    db.commit()
    db.close()
    return ok({'key': key}, 'Payment method saved')


def _upsert_setting(db, key, value):
    """Insert or update a site_settings row without relying on RETURNING."""
    if db._is_pg:
        cur = db._conn.cursor()
        cur.execute(
            "INSERT INTO site_settings(key,value) VALUES(%s,%s) "
            "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
            (key, value)
        )
        db._conn.commit()
    else:
        db._conn.execute(
            "INSERT INTO site_settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value)
        )
        db._conn.commit()


# ── Facebook / Telegram "message us" links (Admin → Payment Methods → Contact Links) ──
_SOCIAL_KEYS = {'facebook': 'social_facebook', 'telegram': 'social_telegram'}
_SOCIAL_NAME = re.compile(r'^[A-Za-z0-9._-]{2,64}$')


def _social_username(kind, value):
    """'BigWin', '@BigWin' or a facebook.com / m.me / t.me link -> 'BigWin'. '' = clear. None = invalid."""
    v = (value or '').strip()
    if not v:
        return ''
    if '://' in v or v.lower().startswith(('www.', 'facebook.', 'fb.', 'm.me', 't.me', 'telegram.')):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(v if '://' in v else 'https://' + v)
        host = (u.hostname or '').lower()
        hosts = ('facebook.com', 'fb.com', 'm.me') if kind == 'facebook' else ('t.me', 'telegram.me')
        if not any(host == h or host.endswith('.' + h) for h in hosts):
            return None
        seg = [s for s in u.path.split('/') if s]
        if seg and seg[0] == 'profile.php':
            v = (parse_qs(u.query).get('id') or [''])[0]
        else:
            v = seg[0] if seg else ''
    v = v.lstrip('@')
    return v if _SOCIAL_NAME.match(v) else None


def _social_links():
    db = get_db()
    try:
        out = {}
        for kind, key in _SOCIAL_KEYS.items():
            row = db.execute('SELECT value FROM site_settings WHERE key=?', (key,)).fetchone()
            out[kind] = (row['value'] if row else '') or ''
        return out
    finally:
        db.close()


@app.route('/api/site/social', methods=['GET'])
def get_social_links():
    """Public: Facebook page + Telegram usernames for the 'Message us' buttons."""
    return ok(_social_links())


@app.route('/api/admin/social-links', methods=['GET', 'POST'])
@require_admin
def admin_social_links():
    if request.method == 'GET':
        return ok(_social_links())
    data  = request.json or {}
    clean = {}
    for kind in _SOCIAL_KEYS:
        name = _social_username(kind, data.get(kind, ''))
        if name is None:
            label = 'Facebook page' if kind == 'facebook' else 'Telegram username'
            return err(f'That {label} doesn\'t look right — paste the username or the full link.')
        clean[kind] = name
    db = get_db()
    try:
        for kind, key in _SOCIAL_KEYS.items():
            _upsert_setting(db, key, clean[kind])
    finally:
        db.close()
    return ok(clean, 'Saved — the buttons are live on the website.')


@app.route('/api/deposit-settings', methods=['GET'])
def get_deposit_settings():
    """Public: returns deposit screenshot requirement so wallet.html can enforce it."""
    db  = get_db()
    row = db.execute("SELECT value FROM site_settings WHERE key='deposit_screenshot_required'").fetchone()
    db.close()
    required = (row['value'] == '1') if row else False
    return ok({'screenshot_required': required})


@app.route('/api/admin/deposit-settings', methods=['POST'])
@require_admin
def save_deposit_settings():
    """Admin: toggle whether screenshot is required for manual deposits."""
    data     = request.json or {}
    required = 1 if data.get('screenshot_required') else 0
    db = get_db()
    _upsert_setting(db, 'deposit_screenshot_required', str(required))
    db.close()
    return ok(msg='Deposit settings saved')



# ─────────────────────────────────────────
#  TELEGRAM ADMIN NOTIFICATIONS
# ─────────────────────────────────────────
import threading as _threading
import telegram_notify as _tg
from telegram_notify import esc as _e

_GAME_NAMES = {
    'juwa': 'Juwa', 'juwa2': 'Juwa 2.0', 'gamevault': 'Game Vault', 'milkyway': 'Milky Way',
    'orionstars': 'Orion Stars', 'ultrapanda': 'Ultra Panda', 'firekirin': 'Fire Kirin',
    'gameroom': 'Gameroom', 'cashfrenzy': 'Cash Frenzy', 'cashmachine': 'Cash Machine', 'mafia': 'Mafia',
    'mrallinone': 'Mr. All In One', 'vblink': 'VBlink', 'pandamaster': 'Panda Master', 'yolo': 'Yolo',
    'vegassweeps': 'Vegas Sweeps', 'riversweeps': 'Riversweeps', 'dragonfury': 'Dragon Fury',
    'ultrathunder': 'Ultra Thunder',
}
_gname = lambda k: _GAME_NAMES.get(k or '', k or '?')
_money = lambda v: f'${float(v or 0):,.2f}'
_METHOD_NAMES = {'cashapp': 'Cash App', 'apple_pay': 'Apple Pay', 'google_pay': 'Google Pay', 'card': 'Card'}
_meth = lambda m: _METHOD_NAMES.get(m or '', m or '?')


def _tg_row(sql, args):
    db = get_db()
    try:
        row = db.execute(sql, args).fetchone()
        return dict(row) if row else {}
    finally:
        db.close()


def _tg_player(pid):
    return _tg_row('SELECT username, balance FROM players WHERE id=?', (pid,)) if pid else {}


def _tg_build(c):
    """(category, text) for one finished request, or None. `c` is a snapshot of the request."""
    ep, ok_, msg, req, data, va = c['endpoint'], c['ok'], c['msg'], c['req'], c['data'], c['view_args']
    by = f"worker <b>{_e(c['worker'])}</b>" if c['worker'] else 'admin'
    pid = va.get('pid') or req.get('player_id')
    p = _tg_player(pid)
    who = f"<b>{_e(p.get('username') or req.get('username') or f'player #{pid}')}</b>"
    wallet = f"\nWallet now: {_money(p.get('balance'))}" if p else ''
    game = _gname(req.get('game'))

    if ep == 'register':
        return ('players', f"🙋 New player {_e(req.get('username'))}") if ok_ else None

    if ep == 'reset_password_by_email' and ok_:
        return 'players', f"🔑 <b>{_e(req.get('username'))}</b> reset their password with an email code"

    if ep == 'verify_email_confirm' and ok_:
        return 'players', f"📧 <b>{_e(req.get('username'))}</b> verified email {_e(_mask_email((data or {}).get('email')))}"

    if ep == 'verify_phone_confirm' and ok_:
        pp = _tg_row('SELECT phone FROM players WHERE username=?', (req.get('username'),))
        ph = pp.get('phone') or ''
        return 'players', f"📱 <b>{_e(req.get('username'))}</b> verified phone ···{_e(ph[-4:])} (+5 WZ)"

    if ep == 'create_game_account':
        if ok_:
            return 'games', f"🎮 {who} got a {game} account: <code>{_e((data or {}).get('username'))}</code>"
        return 'problems', f"⚠️ {game} account for {who} failed\n{_e(msg)}"

    if ep == 'player_load_credits':
        if ok_:
            return 'games', f"⬆️ {who} loaded {_money(req.get('amount'))} into {game}{wallet}"
        if (data or {}).get('insufficient'):
            return None  # normal: the pay & load sheet opens next
        return 'problems', f"⚠️ {who} could not load {_money(req.get('amount'))} into {game}\n{_e(msg)}"

    if ep == 'pay_and_load':
        if ok_:
            return 'money', (f"💳 {who} is paying {_money(req.get('pay_amount'))} ({_e(_meth(req.get('method')))}) "
                             f"to load {_money(req.get('amount'))} into {game} — waiting for KeyHub")
        return 'problems', f"⚠️ {who} could not start a payment for {game}\n{_e(msg)}"

    if ep in ('confirm_deposit_keyhub', 'payment_return'):
        rid = va.get('rid') or c['args'].get('dep_id')
        d = _tg_row('SELECT * FROM deposit_requests WHERE id=?', (rid,))
        if not d:
            return None
        if ep == 'confirm_deposit_keyhub':
            if not ok_:
                return 'problems', f"⚠️ Payment check for deposit #{rid} ({_e(d['username'])}): {_e(msg)}"
            if not (data or {}).get('paid'):
                return None  # still waiting, or already handled
        elif 'deposited=true' not in c['location']:
            return None
        p = _tg_player(d['player_id'])
        head = f"✅ Payment received: {_money(d['amount'])} from <b>{_e(d['username'])}</b> ({_e(_meth(d['method']))}, KeyHub verified)"
        if d.get('load_game'):
            if d.get('load_status') == 'loaded':
                return 'money', f"{head}\n⬆️ Loaded {_money(d['load_amount'])} into {_gname(d['load_game'])}\nWallet now: {_money(p.get('balance'))}"
            return 'problems', (f"⚠️ PAID but NOT loaded — {_money(d['amount'])} from <b>{_e(d['username'])}</b> is in their wallet.\n"
                                f"{_gname(d['load_game'])} load of {_money(d['load_amount'])} failed: {_e(d.get('notes'))}")
        return 'money', f"{head}\nWallet now: {_money(p.get('balance'))}"

    if ep == 'create_deposit' and ok_:
        how = 'KeyHub link' if (data or {}).get('payment_url') else 'manual payment'
        return 'money', f"📥 Deposit request #{(data or {}).get('request_id')}: {_money(req.get('amount'))} via {_e(_meth(req.get('method')))} from {who} ({how})"

    if ep == 'deposit_screenshot' and ok_:
        d = _tg_row('SELECT username, amount FROM deposit_requests WHERE id=?', (va.get('rid'),))
        return 'money', f"🧾 Receipt uploaded for deposit #{va.get('rid')}: {_money(d.get('amount'))} from <b>{_e(d.get('username'))}</b> — please check"

    if ep in ('approve_deposit', 'worker_approve_deposit', 'reject_deposit', 'worker_reject_deposit'):
        if not ok_:
            return None
        d = _tg_row('SELECT username, amount FROM deposit_requests WHERE id=?', (va.get('rid'),))
        icon = '✅' if 'approve' in ep else '❌'
        return 'money', f"{icon} Deposit #{va.get('rid')} ({_money(d.get('amount'))}, <b>{_e(d.get('username'))}</b>) by {by}\n{_e(msg)}"

    if ep == 'create_withdrawal' and ok_:
        return 'money', (f"📤 Cashout request: {_money(req.get('amount'))} via {_e(req.get('method'))} for {who}"
                         + (f" (+{_money(req.get('tip_amount'))} tip)" if float(req.get('tip_amount') or 0) else '')
                         + f"\nTo: <code>{_e(req.get('address'))}</code>")

    if ep in ('approve_withdrawal', 'worker_approve_withdrawal', 'reject_withdrawal', 'worker_reject_withdrawal'):
        d = _tg_row('SELECT username, amount FROM withdrawal_requests WHERE id=?', (va.get('rid'),))
        if not ok_:
            return 'problems', f"⚠️ Cashout #{va.get('rid')} ({_money(d.get('amount'))}, <b>{_e(d.get('username'))}</b>) failed: {_e(msg)}"
        icon = '✅' if 'approve' in ep else '❌'
        return 'money', f"{icon} Cashout #{va.get('rid')} ({_money(d.get('amount'))}, <b>{_e(d.get('username'))}</b>) by {by}\n{_e(msg)}"

    if ep == 'game_to_wallet':
        if ok_:
            return 'games', f"⬇️ {who} cashed out {_money(req.get('amount'))} from {game} to wallet{wallet}"
        return 'problems', f"⚠️ {who} could not cash out {_money(req.get('amount'))} from {game}\n{_e(msg)}"

    if ep in ('add_credits', 'worker_game_load', 'withdraw_credits', 'worker_game_redeem'):
        verb = 'loaded' if ep in ('add_credits', 'worker_game_load') else 'redeemed'
        if ok_:
            return 'games', f"🛠 {by.capitalize()} {verb} {_money(req.get('amount'))} on {game} for {who}"
        return 'problems', f"⚠️ {by.capitalize()} could not {verb[:-1] if verb.endswith('ed') else verb} {_money(req.get('amount'))} on {game} for {who}\n{_e(msg)}"

    if ep in ('admin_credit_player', 'worker_wallet_load', 'admin_redeem_player', 'worker_wallet_redeem') and ok_:
        sign = '+' if ep in ('admin_credit_player', 'worker_wallet_load') else '−'
        return 'money', f"🛠 Wallet {sign}{_money(req.get('amount'))} for {who} by {by}\n{_e(req.get('note') or '')}{wallet}"

    if ep in ('marketplace_approve', 'marketplace_reject') and ok_:
        return 'money', f"🛒 {_e(msg)} (by {by})"

    if ep == 'send_support_message' and ok_ and req.get('sender', 'player') == 'player':
        text = str(req.get('message') or '')
        if text.startswith('data:image'):
            text = '[image — open the support page to see it]'
        return 'support', (f"💬 <b>{_e(req.get('username'))}</b> → {_e(req.get('agent') or SUPPORT_DEFAULT_AGENT)}\n"
                           f"{_e(text[:3000])}\n\n<i>Reply to this message to answer.</i>"), {
            'username': req.get('username'), 'agent': req.get('agent') or SUPPORT_DEFAULT_AGENT,
            'player_id': req.get('player_id')}

    if ep == 'support_contact' and ok_:
        return 'support', (f"📩 <b>Contact form</b> from {_e(req.get('name'))} &lt;{_e(req.get('email'))}&gt;\n"
                           f"{_e(str(req.get('message') or '')[:3000])}\n\n<i>Reply to them by email.</i>")

    if ep == 'toggle_backend' and ok_:
        b = _tg_row('SELECT game, name FROM backends WHERE id=?', (va.get('bid'),))
        on = (data or {}).get('enabled')
        return 'admin', f"{'▶️' if on else '⏸'} {_gname(b.get('game'))} turned {'ON' if on else 'OFF'} ({_e(b.get('name'))})"

    if ep in ('attach_backend', 'attach_loadstar_all') and ok_:
        return 'admin', f"🔌 Backend attached: {_e(req.get('name') or 'Loadstar games')}\n{_e(msg)}"

    if ep == 'delete_backend' and ok_:
        return 'admin', f"🗑 Backend #{va.get('bid')} removed"

    if ep == 'set_loadstar_under' and ok_:
        b = _tg_row('SELECT game FROM backends WHERE id=?', (va.get('bid'),))
        u = (data or {}).get('under') or 'auto'
        return 'admin', f"🌟 {_gname(b.get('game'))}: new players now go under <code>{_e(u)}</code>"

    return None


_TG_ENDPOINTS = {
    'register', 'create_game_account', 'player_load_credits', 'pay_and_load', 'confirm_deposit_keyhub',
    'payment_return', 'create_deposit', 'deposit_screenshot', 'approve_deposit', 'worker_approve_deposit',
    'reject_deposit', 'worker_reject_deposit', 'create_withdrawal', 'approve_withdrawal',
    'worker_approve_withdrawal', 'reject_withdrawal', 'worker_reject_withdrawal', 'game_to_wallet',
    'add_credits', 'worker_game_load', 'withdraw_credits', 'worker_game_redeem', 'admin_credit_player',
    'worker_wallet_load', 'admin_redeem_player', 'worker_wallet_redeem', 'marketplace_approve',
    'marketplace_reject', 'toggle_backend', 'attach_backend', 'attach_loadstar_all', 'delete_backend',
    'set_loadstar_under', 'send_support_message', 'support_contact', 'verify_phone_confirm', 'reset_password_by_email',
    'verify_email_confirm',
}
SUPPORT_DEFAULT_AGENT = "BigWin Support"


def _tg_remember(sent, link):
    """Store which Telegram message belongs to which support conversation."""
    db = get_db()
    try:
        for chat_id, message_id in sent:
            db.execute('INSERT INTO telegram_support_links (chat_id, message_id, player_id, username, agent) '
                       'VALUES (?,?,?,?,?)', (chat_id, message_id, link.get('player_id'), link['username'], link['agent']))
        db.commit()
    finally:
        db.close()


@app.after_request
def _tg_after_request(response):
    try:
        if request.endpoint not in _TG_ENDPOINTS or response.status_code == 401:
            return response
        body = response.get_json(silent=True) if response.is_json else None
        c = {
            'endpoint': request.endpoint, 'view_args': dict(request.view_args or {}),
            'args': request.args.to_dict(), 'req': request.get_json(silent=True) or {},
            'ok': bool(body and body.get('success')), 'msg': (body or {}).get('msg', ''),
            'data': (body or {}).get('data'), 'location': response.headers.get('Location', ''),
            'worker': get_support_agent() if request.endpoint.startswith('worker_') else None,
        }

        def run():
            try:
                out = _tg_build(c)
                if out:
                    cfg = _tg.get_config()
                    if cfg['token'] and cfg['chats'] and out[0] in cfg['events']:
                        sent, _ = _tg.send_tracked(out[1], cfg['token'], cfg['chats'])
                        if len(out) > 2 and sent:
                            _tg_remember(sent, out[2])
            except Exception as ex:
                print(f'[telegram] {ex}')
        _threading.Thread(target=run, daemon=True).start()
    except Exception as ex:
        print(f'[telegram] {ex}')
    return response


@app.route('/api/admin/telegram-config', methods=['GET', 'POST'])
@require_admin
def admin_telegram_config():
    if request.method == 'GET':
        cfg = _tg.get_config()
        tok = cfg['token']
        return ok({'configured': bool(tok and cfg['chats']),
                   'token_preview': (tok[:6] + '…' + tok[-4:]) if tok else '',
                   'chat_id': ','.join(cfg['chats']), 'events': cfg['events'],
                   'categories': [{'key': k, 'label': v} for k, v in _tg.CATEGORIES.items()]})
    data   = request.json or {}
    token  = (data.get('bot_token') or '').strip()
    chats  = (data.get('chat_id') or '').strip()
    events = [e for e in (data.get('events') or []) if e in _tg.CATEGORIES]
    cfg    = _tg.get_config()
    token  = token or cfg['token']
    if not token or not chats:
        return err('Bot token and chat ID are required')
    secret = _secrets.token_urlsafe(32)
    db = get_db()
    _upsert_setting(db, 'telegram_bot_token', token)
    _upsert_setting(db, 'telegram_chat_id', chats)
    _upsert_setting(db, 'telegram_events', json.dumps(events))
    _upsert_setting(db, 'telegram_webhook_secret', secret)
    db.close()
    sent, e = _tg.send_now("✅ <b>BigWin Gaming</b> notifications are on.", token, [c.strip() for c in chats.split(',') if c.strip()])
    if not sent:
        return err(f'Saved, but Telegram refused the test message: {e}')
    # Replies from Telegram come back here. Telegram only calls https addresses.
    hook_ok, hook_err = _tg.set_webhook(token, f'https://{request.host}/api/telegram/webhook', secret)
    if not hook_ok:
        return ok(msg=f'Saved and test sent — but replying from Telegram is off: {hook_err}')
    return ok(msg='Saved — a test message was sent. You can now reply to support messages in Telegram.')


# ─────────────────────────────────────────
#  LOAD REQUESTS (manual loads: player pays → support loads the game by hand → taps Loaded)
# ─────────────────────────────────────────
_GAME_KEY = re.compile(r'^[a-z0-9_-]{2,40}$')
_LR_PUBLIC = 'id, game, game_username, amount, method, status, note, created_at, handled_at'


def _lr_tg_text(r, method_name=''):
    return (f"🎮 <b>Load request #{r['id']}</b>\n"
            f"Player: <b>{_e(r['username'])}</b>\n"
            f"Game: <b>{_e(_gname(r['game']))}</b>"
            + (f" — Game ID <code>{_e(r['game_username'])}</code>" if r.get('game_username') else ' — no Game ID yet') + "\n"
            f"Amount: <b>{_money(r['amount'])}</b> via {_e(method_name or r['method'])}"
            + ("\n📎 Receipt attached in Live Support" if r.get('screenshot') else ''))


def _lr_buttons(rid):
    return {'inline_keyboard': [[{'text': '✅ Loaded', 'callback_data': f'lr:{rid}:loaded'},
                                 {'text': '❌ Reject', 'callback_data': f'lr:{rid}:reject'}]]}


def _lr_notify(r, method_name):
    """Telegram alert with Loaded / Reject buttons (background; never slows the player down)."""
    def run():
        try:
            cfg = _tg.get_config()
            if not (cfg['token'] and cfg['chats'] and 'money' in cfg['events']):
                return
            for chat in cfg['chats']:
                try:
                    m = _tg.api(cfg['token'], 'sendMessage', {
                        'chat_id': chat, 'text': _lr_tg_text(r, method_name), 'parse_mode': 'HTML',
                        'reply_markup': _lr_buttons(r['id'])})
                    # Replying to the alert in Telegram also answers the player in their chat
                    _tg_remember([(str(chat), m['message_id'])],
                                 {'username': r['username'], 'agent': r['agent'], 'player_id': r['player_id']})
                except Exception as ex:
                    print(f'[telegram] load request: {ex}')
        except Exception as ex:
            print(f'[telegram] {ex}')
    _threading.Thread(target=run, daemon=True).start()


def _lr_finish(rid, action, by, note='', from_status='pending'):
    """Mark a pending load request loaded/rejected exactly once and tell the player in their chat.
    Returns (ok, message, row). `from_status`='loading' finishes an auto-load that claimed the request."""
    status = 'loaded' if action == 'loaded' else 'rejected'
    db = get_db()
    try:
        cur = db.execute("UPDATE load_requests SET status=?, handled_by=?, note=?, handled_at=? "
                         "WHERE id=? AND status=?",
                         (status, by[:60], note[:300], datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), rid,
                          from_status))
        row = db.execute('SELECT * FROM load_requests WHERE id=?', (rid,)).fetchone()
        if not row:
            return False, 'Load request not found', None
        r = dict(row)
        if cur.rowcount == 0:
            db.commit()
            return False, f"Already {r['status']} by {r['handled_by'] or 'someone'}", r
        game = _gname(r['game'])
        if status == 'loaded':
            text = (f"✅ Loaded! {_money(r['amount'])} is now in your {game} account"
                    + (f" ({r['game_username']})" if r['game_username'] else '') + ". Good luck! 🍀")
            db.execute('INSERT INTO transactions (player_id, username, type, amount, status, method, notes) '
                       'VALUES (?,?,?,?,?,?,?)',
                       (r['player_id'], r['username'], 'manual_load', r['amount'], 'approved', r['method'],
                        f"{game} load #{rid} by {by}"[:300]))
        else:
            text = (f"❌ We couldn't complete your {_money(r['amount'])} {game} load."
                    + (f" {note}" if note else " We couldn't confirm the payment.")
                    + " Reply here if you need help.")
        db.execute('INSERT INTO support_messages (player_id, username, agent, sender, message) VALUES (?,?,?,?,?)',
                   (r['player_id'], r['username'], r['agent'] or SUPPORT_DEFAULT_AGENT, 'agent', text))
        db.commit()
        return True, ('Marked loaded — the player was told in chat' if status == 'loaded'
                      else 'Rejected — the player was told in chat'), r
    finally:
        db.close()


@app.route('/api/players/<int:pid>/load-requests', methods=['GET', 'POST'])
@require_player
@limiter.limit('10 per minute; 60 per hour', methods=['POST'])
def player_load_requests(pid):
    db = get_db()
    try:
        if request.method == 'GET':
            rows = db.execute(f'SELECT {_LR_PUBLIC} FROM load_requests WHERE player_id=? ORDER BY id DESC LIMIT 30',
                              (pid,)).fetchall()
            return ok(rows_to_list(rows))

        data = request.json or {}
        game = str(data.get('game') or '').strip().lower()
        method = str(data.get('method') or '').strip()[:40]
        shot = str(data.get('screenshot') or '').strip()
        try:
            amount = round(float(data.get('amount') or 0), 2)
        except (TypeError, ValueError):
            amount = 0
        if not _GAME_KEY.match(game):
            return err('Please choose a game.')
        if amount < 5:
            return err('Minimum load is $5.00')
        if amount > 5000:
            return err('Maximum load per request is $5,000.00')
        mrow = db.execute('SELECT name FROM payment_methods WHERE key=? AND enabled=1', (method,)).fetchone()
        if not mrow:
            return err('Please choose one of the listed payment methods.')
        if shot and (not _IMG_DATA_URI.match(shot[:64]) or len(shot) > 4_000_000):
            return err('Upload a PNG, JPG or WebP image under 3 MB.')
        if db.execute("SELECT COUNT(*) AS n FROM load_requests WHERE player_id=? AND status='pending'",
                      (pid,)).fetchone()['n'] >= 5:
            return err('You already have 5 loads waiting. Please wait for support to finish them.')

        prow = db.execute('SELECT username FROM players WHERE id=?', (pid,)).fetchone()
        if not prow:
            return err('Player not found', 404)
        garow = db.execute('SELECT game_username FROM game_accounts WHERE player_id=? AND game=?', (pid, game)).fetchone()
        agent = _get_available_agent(db)
        cur = db.execute(
            'INSERT INTO load_requests (player_id, username, game, game_username, amount, method, screenshot, agent) '
            'VALUES (?,?,?,?,?,?,?,?)',
            (pid, prow['username'], game, garow['game_username'] if garow else '', amount, method, shot, agent))
        rid = cur.lastrowid
        r = dict(db.execute('SELECT * FROM load_requests WHERE id=?', (rid,)).fetchone())
        # Shows up in the player's chat and in the admin Live Support inbox
        db.execute('INSERT INTO support_messages (player_id, username, agent, sender, message) VALUES (?,?,?,?,?)',
                   (pid, r['username'], agent, 'player',
                    f"🎮 Load request #{rid}\nGame: {_gname(game)}"
                    + (f" ({r['game_username']})" if r['game_username'] else '')
                    + f"\nAmount: {_money(amount)}\nPaid with: {mrow['name']}"))
        if shot:
            db.execute('INSERT INTO support_messages (player_id, username, agent, sender, message) VALUES (?,?,?,?,?)',
                       (pid, r['username'], agent, 'player', shot))
        db.commit()
        _lr_notify(r, mrow['name'])
        return ok({k: r[k] for k in ('id', 'game', 'amount', 'method', 'status', 'created_at')},
                  "Sent! We'll load your game and message you in Chats.")
    finally:
        db.close()


def _staff_name():
    """'Admin' or the support agent's name; None when the caller is neither."""
    if _verify_admin_token(request.headers.get('X-Admin-Token', '')):
        return 'Admin'
    return get_support_agent()


@app.route('/api/staff/load-requests', methods=['GET'])
def staff_load_requests():
    if not _staff_name():
        return jsonify({'success': False, 'msg': 'Staff only'}), 401
    status = request.args.get('status', 'pending')
    db = get_db()
    try:
        if status == 'all':
            rows = db.execute('SELECT * FROM load_requests ORDER BY id DESC LIMIT 100').fetchall()
        else:
            rows = db.execute("SELECT * FROM load_requests WHERE status='pending' ORDER BY id ASC LIMIT 100").fetchall()
        pending = db.execute("SELECT COUNT(*) AS n FROM load_requests WHERE status='pending'").fetchone()['n']
        names = {m['key']: m['name'] for m in db.execute('SELECT key, name FROM payment_methods').fetchall()}
        auto_on = _auto_load_on(db)
        ready = _auto_ready_games(db) if auto_on else set()
        out = rows_to_list(rows)
        for r in out:
            r['game_name'] = _gname(r['game'])
            r['method_name'] = names.get(r['method'], r['method'])
            # ⚡ possible: switched on, game connected, and the player has a Game ID on it
            ga = None
            if r['status'] == 'pending' and r['game'] in ready:
                ga = db.execute('SELECT game_username FROM game_accounts WHERE player_id=? AND game=?',
                                (r['player_id'], r['game'])).fetchone()
                if ga and not r['game_username']:
                    r['game_username'] = ga['game_username']
            r['auto_ok'] = bool(ga)
    finally:
        db.close()
    return ok({'requests': out, 'pending': pending, 'auto_enabled': auto_on})


# ── Auto-load: support taps ⚡ and the server adds the credits on the game panel itself ──
def _auto_load_on(db):
    row = db.execute("SELECT value FROM site_settings WHERE key='auto_load_enabled'").fetchone()
    return bool(row and row['value'] == '1')


def _auto_ready_games(db):
    """Games with a connected, switched-on backend (auto-load possible)."""
    return {r['game'] for r in db.execute(
        "SELECT DISTINCT game FROM backends WHERE status='connected' AND enabled=1").fetchall()}


@app.route('/api/admin/auto-load', methods=['GET', 'POST'])
@require_admin
def admin_auto_load():
    db = get_db()
    try:
        if request.method == 'POST':
            on = bool((request.json or {}).get('enabled'))
            _upsert_setting(db, 'auto_load_enabled', '1' if on else '0')
        return ok({'enabled': _auto_load_on(db), 'games': sorted(_gname(g) for g in _auto_ready_games(db))},
                  'Auto-load turned ' + ('ON' if _auto_load_on(db) else 'OFF') if request.method == 'POST' else 'OK')
    finally:
        db.close()


@app.route('/api/staff/load-requests/<int:rid>/auto', methods=['POST'])
def staff_auto_load(rid):
    """Add the credits through the game's backend (no player wallet involved — they paid outside),
    then finish the request like a manual 'Loaded'."""
    by = _staff_name()
    if not by:
        return jsonify({'success': False, 'msg': 'Staff only'}), 401
    db = get_db()
    try:
        if not _auto_load_on(db):
            return err('Auto-load is turned off by the admin.')
        # Claim it first so a manual tap or a second ⚡ can't load it twice
        claim = db.execute("UPDATE load_requests SET status='loading' WHERE id=? AND status='pending'", (rid,))
        db.commit()
        row = db.execute('SELECT * FROM load_requests WHERE id=?', (rid,)).fetchone()
        if not row:
            return err('Load request not found', 404)
        r = dict(row)
        if claim.rowcount == 0:
            return err(f"Already {r['status']}" + (f" by {r['handled_by']}" if r['handled_by'] else ''))

        def release(msg):
            db.execute("UPDATE load_requests SET status='pending' WHERE id=? AND status='loading'", (rid,))
            db.commit()
            return err(msg)

        brow = db.execute("SELECT * FROM backends WHERE game=? AND status='connected' AND enabled=1 "
                          "ORDER BY created_at DESC LIMIT 1", (r['game'],)).fetchone()
        if not brow:
            return release(f"{_gname(r['game'])} has no connected backend — load it by hand.")
        ga = db.execute('SELECT game_username, external_id FROM game_accounts WHERE player_id=? AND game=?',
                        (r['player_id'], r['game'])).fetchone()
        if not ga:
            return release('This player has no Game ID for this game yet — create one or load by hand.')
        b = dict(brow)
        try:
            api = get_api(b['game'], b['username'], b['password'], b['token'], b['base_url'])
            success, msg = api.add_credits(ga['game_username'], float(r['amount']), external_id=ga['external_id'] or '')
        except Exception as ex:
            success, msg = False, f'API error: {ex}'
        if not success:
            return release(f'Panel refused the load: {msg}')
        _BAL_CACHE.pop((r['player_id'], r['game']), None)
    finally:
        db.close()
    done, msg, _r = _lr_finish(rid, 'loaded', f'{by} (auto)', from_status='loading')
    return ok(msg='⚡ Loaded automatically — the player was told in chat') if done else err(msg)


# ─────────────────────────────────────────
#  GAME ID LINKS (connect a player's existing panel account to their website account)
#  Panels can't check a game password for us, so a player can only *ask*; staff confirm.
# ─────────────────────────────────────────
_GAME_USER = re.compile(r'^[A-Za-z0-9_.@-]{3,40}$')


def _setting_on(db, key, default=True):
    row = db.execute('SELECT value FROM site_settings WHERE key=?', (key,)).fetchone()
    return (row['value'] == '1') if row and row['value'] in ('0', '1') else default


def _link_settings(db):
    return {'requests_enabled': _setting_on(db, 'link_requests_enabled', True),
            'agents_can_link': _setting_on(db, 'link_agents_enabled', True)}


def _can_link():
    """'Admin', or the agent's name when admin lets agents link; else None."""
    if _verify_admin_token(request.headers.get('X-Admin-Token', '')):
        return 'Admin'
    agent = get_support_agent()
    if not agent:
        return None
    db = get_db()
    try:
        return agent if _link_settings(db)['agents_can_link'] else None
    finally:
        db.close()


def _panel_lookup(db, game, game_username):
    """Ask the game's panel whether this username exists. Returns (checked, exists, balance, message)."""
    brow = db.execute("SELECT * FROM backends WHERE game=? AND status='connected' ORDER BY enabled DESC, created_at DESC LIMIT 1",
                      (game,)).fetchone()
    if not brow:
        return False, None, None, f'{_gname(game)} is not connected under Backends — check the username in the panel yourself.'
    b = dict(brow)
    try:
        api = get_api(b['game'], b['username'], b['password'], b['token'], b['base_url'])
        bal, e = api.get_balance(game_username)
    except Exception as ex:
        bal, e = None, f'API error: {ex}'
    if bal is not None:
        return True, True, bal, f'Found on {_gname(game)} — balance ${float(bal):.2f}'
    return True, False, None, f'Not found on {_gname(game)}: {e}'


def _do_link(db, pid, game, game_username):
    """Create the game_accounts row. Returns error text or ''."""
    if db.execute('SELECT 1 FROM game_accounts WHERE player_id=? AND game=?', (pid, game)).fetchone():
        return f'This player already has a {_gname(game)} Game ID.'
    taken = db.execute('SELECT player_id FROM game_accounts WHERE game=? AND LOWER(game_username)=LOWER(?)',
                       (game, game_username)).fetchone()
    if taken:
        return f'{game_username} is already linked to another website account (player #{taken["player_id"]}).'
    db.execute("INSERT INTO game_accounts (player_id, game, game_username, game_password) VALUES (?,?,?,'')",
               (pid, game, game_username))
    return ''


@app.route('/api/link-settings', methods=['GET'])
def public_link_settings():
    db = get_db()
    try:
        return ok({'requests_enabled': _link_settings(db)['requests_enabled']})
    finally:
        db.close()


@app.route('/api/admin/link-settings', methods=['GET', 'POST'])
@require_admin
def admin_link_settings():
    db = get_db()
    try:
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            for field, key in (('requests_enabled', 'link_requests_enabled'), ('agents_can_link', 'link_agents_enabled')):
                if field in data:
                    _upsert_setting(db, key, '1' if data[field] else '0')
        return ok(_link_settings(db), 'Saved' if request.method == 'POST' else 'OK')
    finally:
        db.close()


@app.route('/api/players/<int:pid>/link-requests', methods=['GET', 'POST'])
@require_player
@limiter.limit('5 per minute; 20 per hour', methods=['POST'])
def player_link_requests(pid):
    db = get_db()
    try:
        if request.method == 'GET':
            rows = db.execute('SELECT id, game, game_username, status, note, created_at FROM link_requests '
                              'WHERE player_id=? ORDER BY id DESC LIMIT 20', (pid,)).fetchall()
            return ok(rows_to_list(rows))
        if not _link_settings(db)['requests_enabled']:
            return err('Linking old accounts is turned off right now — message support in Chats.')
        data = request.get_json(silent=True) or {}
        game = str(data.get('game') or '').strip().lower()
        gu   = str(data.get('game_username') or '').strip()
        if not _GAME_KEY.match(game):
            return err('Please choose a game.')
        if not _GAME_USER.match(gu):
            return err('Enter your game username (letters and numbers, 3–40 characters).')
        if db.execute('SELECT 1 FROM game_accounts WHERE player_id=? AND game=?', (pid, game)).fetchone():
            return err(f'You already have a {_gname(game)} Game ID.')
        if db.execute("SELECT 1 FROM link_requests WHERE player_id=? AND game=? AND status='pending'", (pid, game)).fetchone():
            return err(f'You already asked to link a {_gname(game)} account — support will check it soon.')
        prow = db.execute('SELECT username FROM players WHERE id=?', (pid,)).fetchone()
        cur = db.execute('INSERT INTO link_requests (player_id, username, game, game_username) VALUES (?,?,?,?)',
                         (pid, prow['username'], game, gu))
        rid = cur.lastrowid
        agent = _get_available_agent(db)
        db.execute('INSERT INTO support_messages (player_id, username, agent, sender, message) VALUES (?,?,?,?,?)',
                   (pid, prow['username'], agent, 'player',
                    f'🔗 Link request #{rid}\nGame: {_gname(game)}\nMy username there: {gu}'))
        db.commit()
        _tg.notify('support', f"🔗 <b>Link request #{rid}</b>\nPlayer: <b>{_e(prow['username'])}</b>\n"
                              f"{_e(_gname(game))} username: <code>{_e(gu)}</code>\n<i>Check it in admin → Game ID Links.</i>")
        return ok({'id': rid}, "Sent! Support will check it and link it — you'll get a message in Chats.")
    finally:
        db.close()


@app.route('/api/staff/link-requests', methods=['GET'])
def staff_link_requests():
    if not _staff_name():
        return jsonify({'success': False, 'msg': 'Staff only'}), 401
    status = request.args.get('status', 'pending')
    db = get_db()
    try:
        if status == 'all':
            rows = db.execute('SELECT * FROM link_requests ORDER BY id DESC LIMIT 100').fetchall()
        else:
            rows = db.execute("SELECT * FROM link_requests WHERE status='pending' ORDER BY id ASC LIMIT 100").fetchall()
        pending = db.execute("SELECT COUNT(*) AS n FROM link_requests WHERE status='pending'").fetchone()['n']
        out = rows_to_list(rows)
        for r in out:
            r['game_name'] = _gname(r['game'])
        return ok({'requests': out, 'pending': pending, 'settings': _link_settings(db),
                   'can_link': bool(_can_link()),
                   'games': [{'key': k, 'name': v} for k, v in sorted(_GAME_NAMES.items(), key=lambda kv: kv[1])]})
    finally:
        db.close()


@app.route('/api/staff/link-check', methods=['POST'])
def staff_link_check():
    """Look a username up on the game's panel (before approving or linking)."""
    if not _staff_name():
        return jsonify({'success': False, 'msg': 'Staff only'}), 401
    data = request.get_json(silent=True) or {}
    game = str(data.get('game') or '').strip().lower()
    gu   = str(data.get('game_username') or '').strip()
    if not _GAME_KEY.match(game) or not _GAME_USER.match(gu):
        return err('Pick a game and enter a valid username.')
    db = get_db()
    try:
        checked, exists, bal, msg = _panel_lookup(db, game, gu)
    finally:
        db.close()
    return ok({'checked': checked, 'exists': exists, 'balance': bal}, msg)


@app.route('/api/staff/link-requests/<int:rid>/<action>', methods=['POST'])
def staff_finish_link(rid, action):
    by = _can_link()
    if not by:
        return _deny('Only the admin can link accounts right now.')
    if action not in ('approve', 'reject'):
        return err('Unknown action', 404)
    note = str((request.get_json(silent=True) or {}).get('note') or '').strip()[:300]
    db = get_db()
    try:
        row = db.execute("SELECT * FROM link_requests WHERE id=?", (rid,)).fetchone()
        if not row:
            return err('Link request not found', 404)
        r = dict(row)
        if r['status'] != 'pending':
            return err(f"Already {r['status']} by {r['handled_by'] or 'someone'}")
        game = _gname(r['game'])
        if action == 'approve':
            checked, exists, _bal, msg = _panel_lookup(db, r['game'], r['game_username'])
            if checked and not exists:
                return err(msg + ' — fix the username or reject the request.')
        # Claim it first so two staff can't both handle it
        cur = db.execute("UPDATE link_requests SET status=?, handled_by=?, note=?, handled_at=? WHERE id=? AND status='pending'",
                         ('approved' if action == 'approve' else 'rejected', by, note,
                          datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), rid))
        db.commit()
        if cur.rowcount == 0:
            return err('Someone else just handled this request.')
        if action == 'approve':
            problem = _do_link(db, r['player_id'], r['game'], r['game_username'])
            if problem:
                db.execute("UPDATE link_requests SET status='pending', handled_by='', handled_at='' WHERE id=?", (rid,))
                db.commit()
                return err(problem)
            text = f"✅ Your {game} account {r['game_username']} is now linked. You can load and cash out from the Payments tab."
        else:
            text = (f"❌ We couldn't link {game} account {r['game_username']}."
                    + (f' {note}' if note else ' Please check the username or message us here.'))
        db.execute('INSERT INTO support_messages (player_id, username, agent, sender, message) VALUES (?,?,?,?,?)',
                   (r['player_id'], r['username'], _get_available_agent(db), 'agent', text))
        db.commit()
        return ok(msg=('Linked — the player was told in chat' if action == 'approve' else 'Rejected — the player was told in chat'))
    finally:
        db.close()


@app.route('/api/staff/link-direct', methods=['POST'])
def staff_link_direct():
    """Staff link an existing panel username to a website account without a request."""
    by = _can_link()
    if not by:
        return _deny('Only the admin can link accounts right now.')
    data = request.get_json(silent=True) or {}
    who  = str(data.get('player') or '').strip()
    game = str(data.get('game') or '').strip().lower()
    gu   = str(data.get('game_username') or '').strip()
    if not who or not _GAME_KEY.match(game) or not _GAME_USER.match(gu):
        return err('Enter the website account, pick a game and enter the game username.')
    db = get_db()
    try:
        prow = db.execute('SELECT id, username FROM players WHERE LOWER(username)=LOWER(?) OR LOWER(email)=LOWER(?)',
                          (who, who)).fetchone()
        if not prow:
            return err(f'No website account "{who}" — use their email or username.')
        checked, exists, _bal, msg = _panel_lookup(db, game, gu)
        if checked and not exists:
            return err(msg)
        problem = _do_link(db, prow['id'], game, gu)
        if problem:
            return err(problem)
        # Close any waiting request for this game: approved if it was this username, otherwise superseded
        now_s = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        db.execute("UPDATE link_requests SET status='approved', handled_by=?, handled_at=? "
                   "WHERE player_id=? AND game=? AND status='pending' AND LOWER(game_username)=LOWER(?)",
                   (by, now_s, prow['id'], game, gu))
        db.execute("UPDATE link_requests SET status='rejected', handled_by=?, handled_at=?, note=? "
                   "WHERE player_id=? AND game=? AND status='pending'",
                   (by, now_s, f'Linked {gu} instead', prow['id'], game))
        db.execute('INSERT INTO support_messages (player_id, username, agent, sender, message) VALUES (?,?,?,?,?)',
                   (prow['id'], prow['username'], _get_available_agent(db), 'agent',
                    f"✅ Your {_gname(game)} account {gu} is now linked to this website account."))
        db.commit()
        return ok(msg=f"Linked {gu} ({_gname(game)}) to {prow['username']}" + ('' if checked else ' — not checked on a panel'))
    finally:
        db.close()


# ─────────────────────────────────────────
#  PLAYER ACCOUNTS FOR STAFF (create account / reset password)
#  Admin always; support agents only while the admin allows it.
# ─────────────────────────────────────────
def _deny(msg):
    """Signed-in staff without permission get 403 (the panel keeps them logged in); strangers get 401."""
    return jsonify({'success': False, 'msg': msg}), (403 if _staff_name() else 401)


def _can_manage_players():
    if _verify_admin_token(request.headers.get('X-Admin-Token', '')):
        return 'Admin'
    agent = get_support_agent()
    if not agent:
        return None
    db = get_db()
    try:
        return agent if _setting_on(db, 'agents_manage_players', True) else None
    finally:
        db.close()


def _staff_note(text):
    """Telegram note to the admin when an agent touches player accounts."""
    try:
        _tg.notify('admin', text)
    except Exception:
        pass


def _temp_password():
    alphabet = 'abcdefghjkmnpqrstuvwxyz23456789'   # no look-alikes (l/1, o/0)
    return ''.join(_secrets.choice(alphabet) for _ in range(8))


@app.route('/api/staff/permissions', methods=['GET'])
def staff_permissions():
    """What the signed-in staff member may do (the admin panel shows/hides pages with this)."""
    if not _staff_name():
        return jsonify({'success': False, 'msg': 'Staff only'}), 401
    return ok({'manage_players': bool(_can_manage_players()), 'link_accounts': bool(_can_link())})


@app.route('/api/admin/agent-permissions', methods=['GET', 'POST'])
@require_admin
def admin_agent_permissions():
    db = get_db()
    try:
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            if 'manage_players' in data:
                _upsert_setting(db, 'agents_manage_players', '1' if data['manage_players'] else '0')
        return ok({'manage_players': _setting_on(db, 'agents_manage_players', True)})
    finally:
        db.close()


@app.route('/api/staff/players', methods=['GET', 'POST'])
def staff_players():
    by = _can_manage_players()
    if not by:
        return _deny('Only the admin can manage player accounts right now.')
    db = get_db()
    try:
        if request.method == 'GET':
            q = request.args.get('q', '').strip().lower()[:80]
            if q:
                like = f'%{q}%'
                rows = db.execute(
                    "SELECT id, username, email, first_name, last_name, status, created_at FROM players "
                    "WHERE LOWER(username) LIKE ? OR LOWER(COALESCE(email,'')) LIKE ? "
                    "OR LOWER(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) LIKE ? "
                    "ORDER BY id DESC LIMIT 50", (like, like, like)).fetchall()
            else:
                rows = db.execute("SELECT id, username, email, first_name, last_name, status, created_at FROM players "
                                  "ORDER BY id DESC LIMIT 50").fetchall()
            out = rows_to_list(rows)
            for p in out:
                p['games'] = [g['game'] for g in db.execute('SELECT game FROM game_accounts WHERE player_id=?',
                                                             (p['id'],)).fetchall()]
            return ok(out)

        # Create a website account (same rules as signing up on the site)
        data  = request.get_json(silent=True) or {}
        email = str(data.get('email') or '').strip().lower()
        first = str(data.get('first_name') or '').strip()[:60]
        last  = str(data.get('last_name') or '').strip()[:60]
        pw    = str(data.get('password') or '').strip() or _temp_password()
        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            return err('Enter a valid email address.')
        if len(pw) < 6:
            return err('Password must be at least 6 characters.')
        if db.execute('SELECT 1 FROM players WHERE LOWER(username)=LOWER(?) OR LOWER(email)=LOWER(?)',
                      (email, email)).fetchone():
            return err('That email already has an account — use Reset password instead.')
        cur = db.execute(
            'INSERT INTO players (username, email, password_hash, fp_credits, referral_code, first_name, last_name, '
            'referred_by_name) VALUES (?,?,?,?,?,?,?,?)',
            (email, email, hash_password(pw), 0, _gen_referral_code(db), first, last, f'Created by {by}'))
        db.commit()
        pid = cur.lastrowid
    finally:
        db.close()
    if by != 'Admin':
        _staff_note(f'👤 {_e(by)} created website account <b>{_e(email)}</b>')
    return ok({'id': pid, 'username': email, 'password': pw},
              f'Account created — give the player their email and password: {pw}')


@app.route('/api/staff/players/<int:pid>/reset-password', methods=['POST'])
def staff_reset_player_password(pid):
    by = _can_manage_players()
    if not by:
        return _deny('Only the admin can reset passwords right now.')
    pw = str((request.get_json(silent=True) or {}).get('new_password') or '').strip() or _temp_password()
    if len(pw) < 6:
        return err('Password must be at least 6 characters.')
    db = get_db()
    try:
        row = db.execute('SELECT username FROM players WHERE id=?', (pid,)).fetchone()
        if not row:
            return err('Player not found', 404)
        db.execute('UPDATE players SET password_hash=? WHERE id=?', (hash_password(pw), pid))
        db.commit()
    finally:
        db.close()
    if by != 'Admin':
        _staff_note(f'🔑 {_e(by)} reset the password for <b>{_e(row["username"])}</b>')
    return ok({'password': pw}, f'New password for {row["username"]}: {pw}')


@app.route('/api/staff/dashboard', methods=['GET'])
@require_admin
def staff_dashboard():
    """Admin dashboard: today's loads, waiting work, players and the last 7 days (UTC days)."""
    now   = datetime.utcnow()
    today = now.strftime('%Y-%m-%d')
    week  = (now - timedelta(days=6)).strftime('%Y-%m-%d')
    db = get_db()
    try:
        one = lambda sql, args=(): db.execute(sql, args).fetchone()
        waiting = one("SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS s FROM load_requests WHERE status='pending'")
        loaded  = one("SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS s FROM load_requests "
                      "WHERE status='loaded' AND handled_at >= ?", (today,))
        rejected = one("SELECT COUNT(*) AS n FROM load_requests WHERE status='rejected' AND handled_at >= ?", (today,))
        cashouts = one("SELECT COUNT(*) AS n FROM support_messages WHERE sender='player' AND created_at >= ? "
                       "AND message LIKE ?", (today, '💸 Cashout request%'))
        unread  = one("SELECT COUNT(DISTINCT username) AS n FROM support_messages WHERE sender='player' AND is_read=0")
        players = one("SELECT COUNT(*) AS n FROM players")
        new_pl  = one("SELECT COUNT(*) AS n FROM players WHERE created_at >= ?", (today,))
        days = {r['d']: (r['n'], float(r['s'])) for r in db.execute(
            "SELECT SUBSTR(handled_at,1,10) AS d, COUNT(*) AS n, SUM(amount) AS s FROM load_requests "
            "WHERE status='loaded' AND handled_at >= ? GROUP BY SUBSTR(handled_at,1,10)", (week,)).fetchall()}
        top = db.execute("SELECT game, COUNT(*) AS n, SUM(amount) AS s FROM load_requests "
                         "WHERE status='loaded' AND handled_at >= ? GROUP BY game ORDER BY s DESC LIMIT 5",
                         (week,)).fetchall()
        recent = db.execute(f'SELECT {_LR_PUBLIC}, username, handled_by FROM load_requests ORDER BY id DESC LIMIT 8').fetchall()
    finally:
        db.close()
    series = []
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).strftime('%Y-%m-%d')
        n, s = days.get(d, (0, 0.0))
        series.append({'day': d, 'count': n, 'amount': round(s, 2)})
    rec = rows_to_list(recent)
    for r in rec:
        r['game_name'] = _gname(r['game'])
    return ok({
        'waiting': {'count': waiting['n'], 'amount': round(float(waiting['s']), 2)},
        'loaded_today': {'count': loaded['n'], 'amount': round(float(loaded['s']), 2)},
        'rejected_today': rejected['n'], 'cashouts_today': cashouts['n'], 'unread_chats': unread['n'],
        'players': {'total': players['n'], 'today': new_pl['n']},
        'week': series,
        'top_games': [{'game': _gname(r['game']), 'count': r['n'], 'amount': round(float(r['s']), 2)} for r in top],
        'recent': rec,
    })


@app.route('/api/staff/load-requests/<int:rid>/<action>', methods=['POST'])
def staff_finish_load(rid, action):
    by = _staff_name()
    if not by:
        return jsonify({'success': False, 'msg': 'Staff only'}), 401
    if action not in ('loaded', 'reject'):
        return err('Unknown action', 404)
    note = str((request.get_json(silent=True) or {}).get('note') or '').strip()
    done, msg, _r = _lr_finish(rid, action, by, note)
    return ok(msg=msg) if done else err(msg)


@app.route('/api/telegram/webhook', methods=['POST'])
def telegram_webhook():
    """Telegram → us. A reply to a support message becomes an agent reply in that player's chat."""
    db = get_db()
    try:
        row = db.execute("SELECT value FROM site_settings WHERE key='telegram_webhook_secret'").fetchone()
    finally:
        db.close()
    secret = (row['value'] if row else '') or ''
    if not secret or not hmac.compare_digest(request.headers.get('X-Telegram-Bot-Api-Secret-Token', ''), secret):
        return jsonify({'ok': False}), 403

    cfg = _tg.get_config()
    update = request.get_json(silent=True) or {}

    # ✅ Loaded / ❌ Reject buttons on a load-request alert
    cq = update.get('callback_query')
    if cq:
        cmsg = cq.get('message') or {}
        cchat = str((cmsg.get('chat') or {}).get('id', ''))
        parts = str(cq.get('data') or '').split(':')
        reply = 'Not allowed'
        if cchat in cfg['chats'] and len(parts) == 3 and parts[0] == 'lr' and parts[1].isdigit():
            by = (cq.get('from') or {}).get('first_name') or 'Telegram'
            done, reply, r = _lr_finish(int(parts[1]), parts[2], f'{by} (Telegram)')
            if r:
                verdict = ('✅ <b>Loaded</b>' if r['status'] == 'loaded' else '❌ <b>Rejected</b>') + \
                          f" by {_e(r['handled_by'])}"
                try:
                    _tg.api(cfg['token'], 'editMessageText', {
                        'chat_id': cchat, 'message_id': cmsg.get('message_id'), 'parse_mode': 'HTML',
                        'text': _lr_tg_text(r) + '\n\n' + verdict})
                except Exception as ex:
                    print(f'[telegram] edit: {ex}')
        try:
            _tg.api(cfg['token'], 'answerCallbackQuery', {'callback_query_id': cq.get('id'), 'text': reply[:190]})
        except Exception:
            pass
        return jsonify({'ok': True})

    msg = update.get('message') or {}
    chat_id = str((msg.get('chat') or {}).get('id', ''))
    if not msg or chat_id not in cfg['chats']:
        return jsonify({'ok': True})  # ignore strangers

    def answer(text):
        _threading.Thread(target=_tg.send_tracked, args=(text, cfg['token'], [chat_id]),
                          kwargs={'reply_to': msg.get('message_id')}, daemon=True).start()

    reply_to = (msg.get('reply_to_message') or {}).get('message_id')
    text = (msg.get('text') or '').strip()
    if not reply_to:
        if text.startswith('/start') or text.startswith('/help'):
            answer('👋 Player support messages show up here. <b>Reply</b> to one to answer that player.')
        return jsonify({'ok': True})

    db = get_db()
    try:
        link = db.execute('SELECT * FROM telegram_support_links WHERE chat_id=? AND message_id=?',
                          (chat_id, reply_to)).fetchone()
        if not link:
            answer('ℹ️ That message isn\'t a player support message — reply to one that starts with 💬.')
            return jsonify({'ok': True})
        if not text:
            answer('ℹ️ Only text replies can be sent to players.')
            return jsonify({'ok': True})
        db.execute('INSERT INTO support_messages (player_id, username, agent, sender, message) VALUES (?,?,?,?,?)',
                   (link['player_id'], link['username'], link['agent'], 'agent', text[:4000]))
        db.execute('UPDATE support_messages SET is_read=1 WHERE username=? AND agent=? AND sender=?',
                   (link['username'], link['agent'], 'player'))
        db.commit()
    finally:
        db.close()
    who = (msg.get('from') or {}).get('first_name') or 'you'
    answer(f"✅ Sent to <b>{_e(link['username'])}</b> (as {_e(link['agent'])}, by {_e(who)})")
    return jsonify({'ok': True})


@app.route('/api/admin/telegram-test', methods=['POST'])
@require_admin
def admin_telegram_test():
    sent, e = _tg.send_now("🔔 Test notification from <b>BigWin Gaming</b> admin.")
    return ok(msg='Test message sent') if sent else err(f'Telegram error: {e}')


@app.route('/api/admin/telegram-disconnect', methods=['POST'])
@require_admin
def admin_telegram_disconnect():
    db = get_db()
    cfg = _tg.get_config()
    if cfg['token']:
        try:
            _tg.api(cfg['token'], 'deleteWebhook', {})
        except Exception:
            pass
    for k in ('telegram_bot_token', 'telegram_chat_id', 'telegram_events', 'telegram_webhook_secret'):
        db.execute('DELETE FROM site_settings WHERE key=?', (k,))
    db.commit()
    db.close()
    return ok(msg='Telegram notifications turned off')


init_db()


def _load_secret():
    """SECRET_KEY if set; otherwise one random secret, created once and shared by all workers via the DB."""
    global _ADMIN_SECRET, _DEP_SIG_SECRET
    if os.environ.get('SECRET_KEY'):
        return
    db = get_db()
    try:
        row = db.execute("SELECT value FROM site_settings WHERE key='signing_secret'").fetchone()
        if not row or not row['value']:
            try:
                db.execute("INSERT INTO site_settings (key, value) VALUES ('signing_secret', ?)", (_secrets.token_hex(32),))
                db.commit()
            except Exception:
                db._conn.rollback()   # another worker made it first
            row = db.execute("SELECT value FROM site_settings WHERE key='signing_secret'").fetchone()
        _ADMIN_SECRET = _DEP_SIG_SECRET = row['value']
    finally:
        db.close()


_load_secret()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    print(f'\n🎰 BigWin Gaming server running on http://localhost:{port}\n')
    app.run(host='0.0.0.0', port=port, debug=False)
