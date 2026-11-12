import hashlib
import time
import requests

# Game Vault uses MD5 token auth: MD5(agent_id:timestamp:secret_key)
# username = agent_id
# password = secret_key

class GameVaultAPI:
    def __init__(self, username, password, token='', base_url='https://gamevault999.com'):
        self.agent_id   = username
        self.secret_key = password
        self.base_url   = base_url.rstrip('/')
        self.session    = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0',
        })

    def _make_token(self):
        ts    = int(time.time())
        raw   = f'{self.agent_id}:{ts}:{self.secret_key}'
        token = hashlib.md5(raw.encode()).hexdigest()
        return token, ts

    def _post(self, endpoint, extra=None):
        token, ts = self._make_token()
        payload = {
            'agent_id':  self.agent_id,
            'timestamp': ts,
            'token':     token,
        }
        if extra:
            payload.update(extra)
        try:
            r = self.session.post(
                f'{self.base_url}/api{endpoint}',
                json=payload,
                timeout=15,
            )
            return r.status_code, r.json() if r.headers.get('content-type','').startswith('application/json') else {}
        except Exception as e:
            return 0, {'error': str(e)}

    def test_connection(self):
        status, data = self._post('/agent/balance')
        if status == 200 and (data.get('code') == 200 or data.get('status') == 'success'):
            bal = data.get('balance', data.get('data', {}).get('balance', 'N/A'))
            return True, f'Connected. Agent balance: ${bal}'
        if status == 0:
            return False, data.get('error', 'Connection failed')
        return False, f'HTTP {status}: {data.get("msg", data.get("message", "Auth failed"))}'

    def create_player(self, player_username, player_password, nickname=''):
        status, data = self._post('/agent/create_player', {
            'username': player_username,
            'password': player_password,
            'nickname': nickname or player_username,
        })
        if status == 200 and (data.get('code') == 200 or data.get('status') == 'success'):
            return True, f'Account "{player_username}" created on Game Vault'
        msg = data.get('msg', data.get('message', f'HTTP {status}'))
        return False, msg

    def get_balance(self, player_username):
        status, data = self._post('/agent/player_balance', {'username': player_username})
        if status == 200 and data.get('code') == 200:
            bal = data.get('balance', data.get('data', {}).get('balance'))
            return float(bal) if bal is not None else None, None
        return None, data.get('msg', 'Balance check failed')

    def add_credits(self, player_username, amount):
        status, data = self._post('/agent/deposit', {
            'username': player_username,
            'amount':   amount,
        })
        if status == 200 and data.get('code') == 200:
            return True, f'Added ${amount} to {player_username}'
        return False, data.get('msg', 'Deposit failed')

    def withdraw_credits(self, player_username, amount):
        status, data = self._post('/agent/withdraw', {
            'username': player_username,
            'amount':   amount,
        })
        if status == 200 and data.get('code') == 200:
            return True, f'Withdrew ${amount} from {player_username}'
        return False, data.get('msg', 'Withdraw failed')

    def get_agent_balance(self):
        status, data = self._post('/agent/balance')
        if status == 200 and (data.get('code') == 200 or data.get('status') == 'success'):
            bal = data.get('balance', (data.get('data') or {}).get('balance', 0))
            try:
                return float(bal), None
            except (TypeError, ValueError):
                return 0.0, None
        return None, data.get('msg', data.get('message', f'HTTP {status}'))
