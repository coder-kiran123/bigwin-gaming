import os
import random
import string
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Vegas Sweeps — Vue SPA + REST JSON API
#
# Portal: https://agent.lasvegassweeps.com
# API base: /api/
#
# Auth flow:
#   GET  /api/agent/captcha?t={rand}  → image/png CAPTCHA (ddddocr)
#   POST /api/agent/agentLogin        → {agent_name, agent_pwd, agent_code, t}
#                                     ← {code:200, data:{token, agent_id, ...}}
#   Bearer token in Authorization header for all subsequent requests
#
# User ops:
#   POST /api/user/userList      → {search, page, limit}
#   POST /api/user/addUser       → {account, login_pwd, check_pwd, nickname, t}
#   POST /api/user/userRechargeRedeem → {user_id, type:1/2, account, balance, amount, remark}
#   POST /api/user/resetUserPwd  → {uid, login_pwd, check_pwd}
#   POST /api/user/balance       → {user_id}

_ocr = None

def _get_ocr():
    global _ocr
    if _ocr is None:
        try:
            import ddddocr
            _ocr = ddddocr.DdddOcr(show_ad=False)
        except ImportError:
            pass
    return _ocr


class VegasSweepsAPI:
    API_BASE = '/api/'
    CAPTCHA_URL = 'agent/captcha'
    LOGIN_URL   = 'agent/agentLogin'

    def __init__(self, username, password, token='', base_url='https://agent.lasvegassweeps.com'):
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip('/')
        self._token = None
        self._agent_id = None
        proxy_url = os.environ.get('FIXIE_URL') or os.environ.get('QUOTAGUARDSTATIC_URL')
        self._proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None

    def _session(self):
        s = requests.Session()
        s.verify = False
        s.headers.update({'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'})
        if self._proxies:
            s.proxies = self._proxies
        return s

    def _api(self, path):
        return self.base_url + self.API_BASE + path

    def _solve_captcha(self, session, t_val, cap_type=''):
        url = self._api(self.CAPTCHA_URL) + f'?t={t_val}'
        if cap_type:
            url += f'&type={cap_type}'
        try:
            r = session.get(url, timeout=15)
            ocr = _get_ocr()
            if not ocr:
                return None, 'ddddocr not available'
            code = ocr.classification(r.content)
            return code, None
        except Exception as e:
            return None, str(e)

    def _login(self):
        s = self._session()
        for attempt in range(4):
            t_val = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
            code, err = self._solve_captcha(s, t_val)
            if err:
                return False, err, None
            payload = {
                'agent_name': self.username,
                'agent_pwd':  self.password,
                'agent_code': code,
                't':          t_val,
            }
            try:
                r = s.post(self._api(self.LOGIN_URL), json=payload, timeout=15)
                resp = r.json()
            except Exception as e:
                return False, str(e), None
            if resp.get('code') == 200:
                self._token    = resp['data']['token']
                self._agent_id = resp['data']['agent_id']
                return True, 'Logged in', s
            msg = resp.get('msg', 'Login failed')
            # Wrong CAPTCHA → retry; wrong credentials → fail fast
            if 'captcha' in msg.lower() or 'verification' in msg.lower() or 'code' in msg.lower():
                continue
            return False, msg, None
        return False, 'CAPTCHA failed after 4 attempts', None

    def _authed_session(self):
        ok, msg, s = self._login()
        if not ok:
            return None, msg
        s.headers.update({'Authorization': f'Bearer {self._token}'})
        return s, None

    def _post(self, s, path, payload):
        try:
            r = s.post(self._api(path), json={**payload, 'locale': 'en', 'timezone': 'cst'}, timeout=15)
            return r.json(), None
        except Exception as e:
            return None, str(e)

    def _find_player(self, s, username):
        resp, err = self._post(s, 'user/userList', {'search': username, 'page': 1, 'limit': 10})
        if err:
            return None, err
        if resp.get('code') != 200:
            return None, resp.get('msg', 'userList failed')
        users = resp.get('data', {}).get('list', [])
        for u in users:
            if u.get('login_name', '').lower() == username.lower():
                return u, None
        return None, f'Player "{username}" not found'

    # ── Public interface ──────────────────────────────────────────────────

    def test_connection(self):
        ok, msg, _ = self._login()
        if ok:
            return True, 'Vegas Sweeps connection successful'
        return False, msg

    def get_balance(self, player_username):
        s, err = self._authed_session()
        if err:
            return None, err
        user, err = self._find_player(s, player_username)
        if err:
            return None, err
        resp, err = self._post(s, 'user/balance', {'user_id': user['user_id']})
        if err:
            return None, err
        if resp.get('code') != 200:
            return None, resp.get('msg', 'balance failed')
        return float(resp['data']['t']), None

    def add_credits(self, player_username, amount, note=''):
        s, err = self._authed_session()
        if err:
            return False, err
        user, err = self._find_player(s, player_username)
        if err:
            return False, err
        payload = {
            'user_id': user['user_id'],
            'type':    1,
            'account': user['login_name'],
            'balance': str(user.get('balance', 0)),
            'amount':  str(amount),
            'remark':  note,
        }
        resp, err = self._post(s, 'user/userRechargeRedeem', payload)
        if err:
            return False, err
        if resp.get('code') == 200 and resp.get('data', {}).get('code', 0) not in (29, 30, 31):
            return True, f'Added {amount} credits to {player_username}'
        msg = resp.get('msg') or resp.get('data', {}).get('msg', 'Recharge failed')
        return False, msg

    def withdraw_credits(self, player_username, amount, note=''):
        s, err = self._authed_session()
        if err:
            return False, err
        user, err = self._find_player(s, player_username)
        if err:
            return False, err
        payload = {
            'user_id': user['user_id'],
            'type':    2,
            'account': user['login_name'],
            'balance': str(user.get('balance', 0)),
            'amount':  str(amount),
            'remark':  note,
        }
        resp, err = self._post(s, 'user/userRechargeRedeem', payload)
        if err:
            return False, err
        if resp.get('code') == 200 and resp.get('data', {}).get('code', 0) not in (29, 30, 31):
            return True, f'Withdrew {amount} credits from {player_username}'
        msg = resp.get('msg') or resp.get('data', {}).get('msg', 'Redeem failed')
        return False, msg

    def reset_password(self, player_username, new_password, external_id=''):
        s, err = self._authed_session()
        if err:
            return False, err
        user, err = self._find_player(s, player_username)
        if err:
            return False, err
        payload = {
            'uid':       user['user_id'],
            'login_pwd': new_password,
            'check_pwd': new_password,
        }
        resp, err = self._post(s, 'user/resetUserPwd', payload)
        if err:
            return False, err
        if resp.get('code') == 200:
            return True, f'Password reset for {player_username}'
        return False, resp.get('msg', 'Password reset failed')

    def create_player(self, username, password, nickname=''):
        s, err = self._authed_session()
        if err:
            return False, err, {}
        # Do NOT send 't' — the server treats its presence as a CAPTCHA trigger.
        # Without 't', creation succeeds without CAPTCHA. If the server ever requires
        # it (inner code=43), generate a token, solve CAPTCHA, and retry.
        payload = {
            'account':   username,
            'nickname':  nickname or username,
            'login_pwd': password,
            'check_pwd': password,
        }
        for attempt in range(3):
            resp, err = self._post(s, 'user/addUser', payload)
            if err:
                return False, err, {}
            if resp.get('code') == 200:
                inner_code = resp.get('data', {}).get('code', 0) if isinstance(resp.get('data'), dict) else 0
                if inner_code == 43:
                    t_val = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
                    cap_code, cap_err = self._solve_captcha(s, t_val, cap_type='user_create')
                    if cap_err:
                        return False, cap_err, {}
                    payload['captcha'] = cap_code
                    payload['t'] = t_val
                    continue
                if inner_code == 0:
                    return True, f'Player {username} created on Vegas Sweeps', ''
                return False, resp.get('msg', 'Create player failed'), {}
            # "login name have used" — account already exists on the platform
            # (can happen if a previous create succeeded on their side but failed to save locally)
            msg = resp.get('msg', '')
            if 'login name' in msg.lower() or 'have used' in msg.lower() or 'already' in msg.lower():
                return True, f'Player {username} already exists on Vegas Sweeps (linked)', ''
            return False, msg or 'Create player failed', {}
        return False, 'CAPTCHA failed after retries', {}
