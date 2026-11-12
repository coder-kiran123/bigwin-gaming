import hashlib
import os
import time
import requests
import urllib3

_GAME_SSL_VERIFY = os.environ.get('GAME_SSL_VERIFY', 'false').lower() == 'true'
if not _GAME_SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Juwa External Agent API
# Docs: multipart/form-data, success = code 0
# Auth: agent_id + timestamp + MD5(agent_id:timestamp:secret_key) in every request body
# Base URL: https://api.juwa777.com  (or custom domain provided by Juwa)

JUWA_STATUS = {
    1: 'Invalid agent ID',
    2: 'Invalid request parameters',
    3: 'Invalid token',
    4: 'Token expired',
    5: 'Access IP is not whitelisted',
    6: 'Insufficient agent balance',
    7: 'Insufficient user balance',
    8: 'Invalid user ID',
    9: 'User account frozen',
    10: 'User is in game',
    11: 'Invalid amount',
    12: 'Recharge failed, try again',
    13: 'Recharge permission denied',
    14: 'Withdrawal failed, try again',
    15: 'Withdrawal exceeds daily limit',
    16: 'Withdrawal under review',
    17: 'Withdrawal permission denied',
    18: 'Account name format error (letters, numbers, underscores only)',
    19: 'Agent has no register-user permission',
    20: 'Account name already exists',
    21: 'System failed',
    22: 'Too many registrations from this IP',
    23: 'Password must be 6–32 characters',
    400: 'Parameter error',
}


class JuwaAPI:
    def __init__(self, username, password, token='', base_url='https://api.juwa777.com'):
        self.agent_id   = str(username).strip()
        self.secret_key = str(password).strip()
        self.base_url   = (base_url or 'https://api.juwa777.com').rstrip('/')
        self.session    = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
        # Use outbound proxy when running in production (e.g. Railway + Fixie)
        # Set FIXIE_URL (or QUOTAGUARD_URL) env var to route through a fixed IP
        proxy_url = os.environ.get('FIXIE_URL') or os.environ.get('QUOTAGUARDSTATIC_URL')
        if proxy_url:
            self.session.proxies = {'http': proxy_url, 'https': proxy_url}

    def _auth_fields(self):
        ts    = int(time.time())
        raw   = f'{self.agent_id}:{ts}:{self.secret_key}'
        token = hashlib.md5(raw.encode()).hexdigest()
        return {'agent_id': self.agent_id, 'timestamp': str(ts), 'token': token}

    def _post(self, path, extra=None):
        data = self._auth_fields()
        if extra:
            data.update({k: str(v) for k, v in extra.items()})
        try:
            r = self.session.post(
                f'{self.base_url}{path}',
                data=data,          # multipart/form-data
                timeout=15,
                verify=_GAME_SSL_VERIFY,
            )
            if r.status_code == 200:
                try:
                    return r.json()
                except Exception:
                    return {'code': -1, 'msg': f'Non-JSON response: {r.text[:200]}'}
            return {'code': -1, 'msg': f'HTTP {r.status_code}'}
        except requests.exceptions.ConnectionError:
            return {'code': -1, 'msg': f'Cannot reach {self.base_url}'}
        except Exception as e:
            return {'code': -1, 'msg': str(e)}

    def _ok(self, resp):
        return resp.get('code') == 0

    def _err(self, resp):
        code = resp.get('code', -1)
        msg  = resp.get('msg') or JUWA_STATUS.get(code, f'Error code {code}')
        return msg

    # ── Test connection ───────────────────────────────────────────────────
    def test_connection(self):
        resp = self._post('/api/external/agentBalance')
        if self._ok(resp):
            bal = resp.get('data', {}).get('agent_balance', 'N/A')
            return True, f'Connected to Juwa. Agent balance: ${bal}'
        return False, self._err(resp)

    # ── Create player account ─────────────────────────────────────────────
    # Returns (success, msg, external_id)
    def create_player(self, player_username, player_password, nickname=''):
        resp = self._post('/api/external/addUser', {
            'account':   player_username,
            'login_pwd': player_password,
        })
        if self._ok(resp):
            user_id = resp.get('data', {}).get('user_id', '')
            return True, f'Juwa account "{player_username}" created (ID: {user_id})', str(user_id)
        return False, self._err(resp), ''

    # ── Get player balance ────────────────────────────────────────────────
    def get_balance(self, player_username, external_id=''):
        uid = external_id or self._get_user_id(player_username)
        if not uid:
            return None, f'Cannot find Juwa user ID for "{player_username}"'
        resp = self._post('/api/external/userBalance', {'user_id': uid})
        if self._ok(resp):
            bal = resp.get('data', {}).get('user_balance', '0')
            return float(bal), None
        return None, self._err(resp)

    # ── Add credits (recharge) ────────────────────────────────────────────
    def add_credits(self, player_username, amount, external_id='', order_id=None):
        uid = external_id or self._get_user_id(player_username)
        if not uid:
            return False, f'Cannot find Juwa user ID for "{player_username}"'
        oid  = order_id or f'pay_{int(time.time())}'
        resp = self._post('/api/external/recharge', {
            'user_id':  uid,
            'amount':   str(amount),
            'order_id': oid,
        })
        if self._ok(resp):
            new_bal = resp.get('data', {}).get('user_balance', '?')
            return True, f'Added ${amount} to {player_username}. New balance: {new_bal}'
        return False, self._err(resp)

    # ── Withdraw credits ──────────────────────────────────────────────────
    def withdraw_credits(self, player_username, amount, external_id='', order_id=None):
        uid = external_id or self._get_user_id(player_username)
        if not uid:
            return False, f'Cannot find Juwa user ID for "{player_username}"'
        oid  = order_id or f'wdw_{int(time.time())}'
        resp = self._post('/api/external/withdraw', {
            'user_id':  uid,
            'amount':   str(amount),
            'order_id': oid,
        })
        if self._ok(resp):
            new_bal = resp.get('data', {}).get('user_balance', '?')
            return True, f'Withdrew ${amount} from {player_username}. New balance: {new_bal}'
        return False, self._err(resp)

    # ── Agent balance ─────────────────────────────────────────────────────
    def get_agent_balance(self):
        resp = self._post('/api/external/agentBalance')
        if self._ok(resp):
            return float(resp.get('data', {}).get('agent_balance', 0)), None
        return None, self._err(resp)

    # ── Reset player password ─────────────────────────────────────────────
    def reset_password(self, player_username, new_password, external_id=''):
        uid = external_id or self._get_user_id(player_username)
        if not uid:
            return False, f'Cannot find Juwa user ID for "{player_username}"'
        resp = self._post('/api/external/resetPassword', {
            'user_id':   uid,
            'login_pwd': new_password,
        })
        if self._ok(resp):
            return True, 'Password reset successfully'
        return False, self._err(resp)

    # ── Force player offline ──────────────────────────────────────────────
    def force_offline(self, player_username, external_id=''):
        uid = external_id or self._get_user_id(player_username)
        if not uid:
            return False, f'Cannot find Juwa user ID for "{player_username}"'
        resp = self._post('/api/external/playerOffline', {'user_id': uid})
        if self._ok(resp):
            return True, f'{player_username} forced offline'
        return False, self._err(resp)

    # ── Lookup user_id by login name ──────────────────────────────────────
    def _get_user_id(self, account_name):
        resp = self._post('/api/external/getUserID', {'account_name': account_name})
        if self._ok(resp):
            return str(resp.get('data', {}).get('user_id', ''))
        return ''
