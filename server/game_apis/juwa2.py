import os
import random
import re
import time
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import ddddocr as _ddddocr
    _OCR = _ddddocr.DdddOcr(show_ad=False)
    _OCR_OK = True
except ImportError:
    _OCR_OK = False

# Juwa 2.0 — Vue SPA, PHP/Laravel backend
#
# Portal: https://agent.juwa2.com
# Login flow:
#   1. Generate random 8-digit checkCode
#   2. GET /api/agent/captcha?t={checkCode}  → PNG captcha image
#   3. Solve captcha with ddddocr (retry up to 5x on wrong code)
#   4. POST /api/agent/agentLogin {agent_name, agent_pwd, agent_code:solved,
#                                  google_code:"", t:checkCode,
#                                  browser_type:"chrome", device_type:"desktop",
#                                  __visitorId: FINGERPRINT}
#      ← {code:200, data:{token:"...", agent_id:N, expires_time:"..."}}
#   Authorization: Bearer {token}
#
# Player endpoints (all POST /api/user/...):
#   userList        {page, limit, account}  → data.list[].{user_id,login_name,balance}
#   addUser         {account, nickname, login_pwd, check_pwd, captcha:null, t:""}
#   rechargeRedeem  {user_id, type:1, account, balance, amount, remark, bonusStatus:0}
#   rechargeRedeem  {user_id, type:2, account, balance, amount, remark}
#   resetUserPwd    {uid, login_pwd, check_pwd}
#
# Agent balance: POST /api/agent/balance {} → data.t

_FINGERPRINT = "3927fbca2b4c0e862a73c04cc7ddb64d"


class Juwa2API:
    _display = "Juwa 2.0"

    def __init__(self, username, password, token='', base_url='https://agent.juwa2.com'):
        self.username = username
        self.password = password
        self.base_url = base_url.split('#')[0].rstrip('/')
        self._token = token or None
        self._agent_id = None
        self._token_expires = 0.0  # unix timestamp
        proxy_url = os.environ.get('FIXIE_URL') or os.environ.get('QUOTAGUARDSTATIC_URL')
        self._proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None

    def _session(self):
        s = requests.Session()
        s.verify = False
        s.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        })
        if self._proxies:
            s.proxies.update(self._proxies)
        return s

    def _json_headers(self):
        return {
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'Origin': self.base_url,
            'Referer': f'{self.base_url}/login',
        }

    def _login(self, s, max_captcha_tries=5):
        if not _OCR_OK:
            return False, "ddddocr not installed — run: pip install ddddocr"
        for attempt in range(max_captcha_tries):
            check_code = random.randint(10_000_000, 99_999_999)
            try:
                r = s.get(
                    f'{self.base_url}/api/agent/captcha',
                    params={'t': check_code},
                    timeout=12,
                )
                raw = r.content
                if not raw or not raw.startswith(b'\x89PNG'):
                    return False, f"Captcha endpoint returned non-image (HTTP {r.status_code}): {r.text[:80]}"
                from PIL import Image
                import io as _io
                img = Image.open(_io.BytesIO(raw)).convert('RGB')
                buf = _io.BytesIO()
                img.save(buf, format='PNG')
                cap_code = _OCR.classification(buf.getvalue())
            except Exception as e:
                return False, f"Captcha fetch error: {e}"
            try:
                r2 = s.post(
                    f'{self.base_url}/api/agent/agentLogin',
                    json={
                        'agent_name': self.username,
                        'agent_pwd': self.password,
                        'agent_code': cap_code,
                        'google_code': '',
                        't': check_code,
                        'browser_type': 'chrome',
                        'device_type': 'desktop',
                        '__visitorId': _FINGERPRINT,
                    },
                    headers=self._json_headers(),
                    timeout=15,
                )
                resp = r2.json()
            except Exception as e:
                return False, f"Login request error: {e}"

            if resp.get('code') == 200:
                d = resp['data']
                self._token = d['token']
                self._agent_id = d.get('agent_id')
                # Parse expiry: "2026-06-13 18:45:32"
                try:
                    import datetime
                    exp = datetime.datetime.strptime(
                        d.get('expires_time', ''), '%Y-%m-%d %H:%M:%S'
                    )
                    self._token_expires = exp.timestamp() - 300  # refresh 5 min early
                except Exception:
                    self._token_expires = time.time() + 5.5 * 3600
                s.headers.update({'Authorization': f'Bearer {self._token}'})
                return True, 'Logged in'

            msg = resp.get('msg', '')
            if 'incorrect' in msg.lower() or 'verification' in msg.lower():
                time.sleep(0.4)
                continue  # captcha wrong, retry with new one
            return False, msg or f"Login failed (code={resp.get('code')})"
        return False, 'Login failed: captcha could not be solved after retries'

    def _authed_session(self):
        s = self._session()
        s.headers.update(self._json_headers())
        if self._token and time.time() < self._token_expires:
            s.headers.update({'Authorization': f'Bearer {self._token}'})
            return s, None
        ok, msg = self._login(s)
        if not ok:
            return None, msg
        return s, None

    def _find_player(self, s, player_username):
        try:
            r = s.post(
                f'{self.base_url}/api/user/userList',
                json={'page': 1, 'limit': 20, 'account': player_username},
                timeout=15,
            )
            data = r.json()
        except Exception as e:
            return None, str(e)
        lst = (data.get('data') or {}).get('list') or []
        for p in lst:
            if (p.get('login_name') or '').lower() == player_username.lower():
                return p, None
        return None, f'Player "{player_username}" not found on {self._display}'

    # ── Public interface ──────────────────────────────────────────────────

    def test_connection(self):
        s = self._session()
        ok, msg = self._login(s)
        return (True, f'{self._display} connection successful') if ok else (False, msg)

    def get_balance(self, player_username, external_id=''):
        s, err = self._authed_session()
        if err:
            return None, err
        player, err = self._find_player(s, player_username)
        if err:
            return None, err
        try:
            return float(player.get('balance') or 0), None
        except Exception:
            return 0.0, None

    def add_credits(self, player_username, amount, note='', external_id=''):
        s, err = self._authed_session()
        if err:
            return False, err
        player, err = self._find_player(s, player_username)
        if err:
            return False, err
        try:
            r = s.post(
                f'{self.base_url}/api/user/rechargeRedeem',
                json={
                    'user_id': player['user_id'],
                    'type': 1,
                    'account': player['login_name'],
                    'balance': player.get('balance', 0) or 0,
                    'amount': int(amount),
                    'remark': (note or '')[:50],
                    'bonusStatus': 0,
                },
                timeout=15,
            )
            d = r.json()
        except Exception as e:
            return False, str(e)
        if d.get('code') == 200:
            return True, f'Added {amount} credits to {player_username}'
        return False, d.get('msg') or d.get('message') or 'rechargeRedeem failed'

    def withdraw_credits(self, player_username, amount, note='', external_id=''):
        s, err = self._authed_session()
        if err:
            return False, err
        player, err = self._find_player(s, player_username)
        if err:
            return False, err
        try:
            r = s.post(
                f'{self.base_url}/api/user/rechargeRedeem',
                json={
                    'user_id': player['user_id'],
                    'type': 2,
                    'account': player['login_name'],
                    'balance': player.get('balance', 0) or 0,
                    'amount': int(amount),
                    'remark': (note or '')[:50],
                },
                timeout=15,
            )
            d = r.json()
        except Exception as e:
            return False, str(e)
        if d.get('code') == 200:
            return True, f'Withdrew {amount} credits from {player_username}'
        return False, d.get('msg') or d.get('message') or 'rechargeRedeem (redeem) failed'

    def reset_password(self, player_username, new_password, external_id=''):
        s, err = self._authed_session()
        if err:
            return False, err
        player, err = self._find_player(s, player_username)
        if err:
            return False, err
        try:
            r = s.post(
                f'{self.base_url}/api/user/resetUserPwd',
                json={
                    'uid': player['user_id'],
                    'login_pwd': new_password,
                    'check_pwd': new_password,
                },
                timeout=15,
            )
            d = r.json()
        except Exception as e:
            return False, str(e)
        if d.get('code') == 200:
            return True, f'Password reset for {player_username}'
        return False, d.get('msg') or d.get('message') or 'resetUserPwd failed'

    def create_player(self, username, password, nickname=''):
        s, err = self._authed_session()
        if err:
            return False, err, {}
        try:
            r = s.post(
                f'{self.base_url}/api/user/addUser',
                json={
                    'account': username,
                    'nickname': nickname or username,
                    'login_pwd': password,
                    'check_pwd': password,
                    'captcha': None,
                    't': '',
                },
                timeout=15,
            )
            d = r.json()
        except Exception as e:
            return False, str(e), {}
        if d.get('code') == 200:
            inner = d.get('data') or {}
            if inner.get('code') == 0 or inner.get('retcode') == 0:
                return True, f'Player {username} created on {self._display}', {}
        msg = (d.get('data') or {}).get('msg') or d.get('msg') or ''
        if any(w in msg.lower() for w in ('exist', 'already', 'duplicate', 'registered')):
            return True, f'Player {username} already exists on {self._display} (linked)', {}
        return False, msg or 'addUser failed', {}

    def get_agent_balance(self):
        s, err = self._authed_session()
        if err:
            return None, err
        try:
            r = s.post(f'{self.base_url}/api/agent/balance', json={}, timeout=15)
            d = r.json()
        except Exception as e:
            return None, str(e)
        if d.get('code') == 200:
            bal = (d.get('data') or {}).get('t', 0)
            try:
                return float(bal), None
            except (TypeError, ValueError):
                return 0.0, None
        return None, d.get('msg', 'Agent balance fetch failed')
