import re
import uuid
import requests

# Loadstar (our own game control system) — https://www.loadstar.online
# Instead of logging into a game panel directly, a backend can be routed through
# Loadstar: this site acts as a Loadstar agent and Loadstar talks to the panel.
#
# Backend fields when attached in admin:
#   password = Loadstar API key (ls_live_…), made in Loadstar → Settings → API keys
#   base_url = Loadstar URL (default https://www.loadstar.online)
#   token    = Loadstar game id (filled in automatically on Test connection)
#   game     = our game key; Loadstar uses the same keys (firekirin, juwa, ...)
#   under    = where new players go (backends.loadstar_under): '' = Loadstar's default
#              (own game account if there is one), 'admin' = paid from the wallet,
#              or one of our own Loadstar game account ids.
#
# Player external_id = the Loadstar player id.

DEFAULT_URL = 'https://www.loadstar.online'
_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)


def is_loadstar_key(password):
    return (password or '').strip().startswith('ls_')


class LoadstarAPI:
    def __init__(self, game, username, password, token='', base_url=''):
        self.game     = game
        self.username = username
        self.api_key  = password.strip()
        url = (base_url or '').split('#')[0].rstrip('/')
        if url.endswith('/v1'):
            url = url[:-3]
        self.base_url = url or DEFAULT_URL
        token = (token or '').strip()
        self._token   = token if _UUID.match(token) else None  # Loadstar game id
        self._label   = None
        self.under    = ''

    # ── HTTP ──────────────────────────────────────────────────────────────

    def _call(self, method, path, body=None, idem_key=None, params=None):
        """Returns (http status, json). status 0 = never reached Loadstar."""
        headers = {'Authorization': f'Bearer {self.api_key}', 'Accept': 'application/json'}
        if idem_key:
            headers['Idempotency-Key'] = idem_key
        try:
            r = requests.request(method, f'{self.base_url}/v1{path}', json=body, params=params,
                                 headers=headers, timeout=60)
        except requests.exceptions.ConnectionError as e:
            return 0, {'error': {'code': 'unreachable', 'message': f'Cannot reach Loadstar: {e}'}}
        except requests.exceptions.Timeout:
            return -1, {'error': {'code': 'timeout', 'message': 'Loadstar did not answer in time'}}
        try:
            data = r.json()
        except ValueError:
            data = {'error': {'code': 'bad_response', 'message': f'HTTP {r.status_code}: {r.text[:120]}'}}
        return r.status_code, data

    @staticmethod
    def _err(data, fallback='Loadstar request failed'):
        e = (data or {}).get('error') or {}
        return e.get('message') or e.get('code') or fallback

    def _game_id(self):
        if self._token:
            return self._token, None
        status, data = self._call('GET', '/games')
        if status != 200:
            return None, self._err(data)
        games = [g for g in data.get('games', []) if g.get('game') == self.game]
        if not games:
            return None, f'Loadstar has no "{self.game}" game set up. Add it in Loadstar admin first.'
        g = next((g for g in games if not g.get('disabled')), games[0])
        self._token, self._label = g['id'], g.get('label')
        return self._token, None

    def list_games(self):
        """Every game this key can sell: ([{id, game, label, disabled, down, cents_per_credit}], error)."""
        status, data = self._call('GET', '/games')
        if status != 200:
            return None, self._err(data)
        return data.get('games', []), None

    def _find_player_id(self, player_username):
        gid, msg = self._game_id()
        if not gid:
            return None, msg
        status, data = self._call('GET', '/players', params={'game_account_id': gid, 'q': player_username, 'limit': 50})
        if status != 200:
            return None, self._err(data)
        for p in data.get('players', []):
            if p.get('username', '').lower() == player_username.lower():
                return p['id'], None
        return None, f'Player {player_username} not found in Loadstar'

    def _player_id(self, player_username, external_id=''):
        # Players made before switching to Loadstar hold the panel's id, not a Loadstar one.
        if external_id and _UUID.match(str(external_id)):
            return external_id, None
        return self._find_player_id(player_username)

    # ── Adapter interface (same as the other game_apis) ───────────────────

    def test_connection(self):
        status, data = self._call('GET', '/games')
        if status != 200:
            return False, self._err(data)
        self._token = None
        gid, msg = self._game_id()
        if not gid:
            return False, msg
        g = next(x for x in data['games'] if x['id'] == gid)
        if g.get('disabled'):
            return False, f'{g.get("label")} is turned off in Loadstar'
        if g.get('down'):
            return False, f'{g.get("label")} is not answering Loadstar right now'
        wallet, _ = self.get_agent_balance()
        price = g.get('cents_per_credit')
        parts = [f'Connected via Loadstar — {g.get("label")}']
        if price is not None:
            parts.append(f'{price}¢/credit')
        if wallet is not None:
            parts.append(f'wallet ${wallet:,.2f}')
        return True, ' · '.join(parts)

    def create_player(self, player_username, player_password, nickname=''):
        gid, msg = self._game_id()
        if not gid:
            return False, msg, ''
        body = {'game_account_id': gid, 'username': player_username, 'password': player_password}
        if nickname:
            body['nickname'] = nickname
        if self.under == 'admin':
            body['under'] = 'admin'
        elif _UUID.match(self.under or ''):
            body['agent_account_id'] = self.under
        status, data = self._call('POST', '/players', body)
        if status != 201 and ((data or {}).get('error') or {}).get('code') == 'pick_account' and not self.under:
            # "Auto" but we have several accounts on this game: use the first ready one
            # (admin can choose a specific one under "New players go under")
            accounts, _ = self.list_accounts()
            ready = [a for a in (accounts or []) if a.get('ready', True)]
            if ready:
                body.pop('under', None)
                body['agent_account_id'] = ready[0]['id']
                status, data = self._call('POST', '/players', body)
        if status == 201:
            p = data['player']
            return True, f'Player {p["username"]} created on {p.get("game_label") or self.game} via Loadstar', p['id']
        return False, self._err(data, 'Could not create player'), ''

    def list_accounts(self):
        """Our own Loadstar game accounts on this game: ([{id, name, login_name, ready}], error)."""
        gid, msg = self._game_id()
        if not gid:
            return None, msg
        status, data = self._call('GET', '/games')
        if status != 200:
            return None, self._err(data)
        g = next((x for x in data.get('games', []) if x['id'] == gid), None)
        if not g:
            return None, 'Game not found in Loadstar'
        return [{'id': a['id'], 'name': a.get('name') or a.get('login_name'), 'login_name': a.get('login_name'),
                 'ready': a.get('ready', True)} for a in g.get('my_accounts', [])], None

    def get_balance(self, player_username, external_id=''):
        # Called with the backend's own username for the backend balance: show the wallet.
        if not external_id and player_username == self.username:
            return self.get_agent_balance()
        pid, msg = self._player_id(player_username, external_id)
        if not pid:
            return None, msg
        status, data = self._call('GET', f'/players/{pid}/balance')
        if status == 200 and data.get('balance') is not None:
            return float(data['balance']), None
        return None, self._err(data, 'Balance not available')

    def get_agent_balance(self):
        status, data = self._call('GET', '/wallet')
        if status == 200 and 'balance_cents' in data:
            return data['balance_cents'] / 100, None
        return None, self._err(data, 'Wallet not available')

    def _move(self, direction, player_username, amount, order_id=None):
        credits = int(round(float(amount)))
        if credits <= 0 or abs(float(amount) - credits) > 1e-9:
            return False, 'Loadstar only moves whole credits'
        gid, msg = self._game_id()
        if not gid:
            return False, msg
        body = {'game_account_id': gid, 'player_username': player_username, 'credits': credits}
        key = str(order_id) if order_id else f'gr-{uuid.uuid4()}'
        status, data = self._call('POST', f'/credits/{direction}', body, idem_key=key)
        if status == -1:
            # Timed out: replay with the same key — Loadstar returns the first result, never moves twice.
            status, data = self._call('POST', f'/credits/{direction}', body, idem_key=key)
        op = data.get('operation') or {}
        st = op.get('status')
        if status in (200, 201) and st == 'succeeded':
            return True, op.get('message') or f'{direction} {credits} credits'
        if status == 202 or st == 'unknown':
            return False, ('The game did not confirm — check it in Loadstar (Activity) before trying again. '
                           f'Loadstar op {op.get("id", "")}')
        if status == 422 or st == 'failed':
            return False, op.get('message') or 'The game refused it'
        return False, self._err(data)

    def add_credits(self, player_username, amount, note='', external_id='', order_id=None):
        return self._move('load', player_username, amount, order_id)

    def withdraw_credits(self, player_username, amount, note='', external_id='', order_id=None):
        return self._move('redeem', player_username, amount, order_id)

    def reset_password(self, player_username, new_password, external_id=''):
        pid, msg = self._player_id(player_username, external_id)
        if not pid:
            return False, msg
        status, data = self._call('POST', f'/players/{pid}/reset-password', {'new_password': new_password})
        if status == 200:
            return True, data.get('message') or 'Password reset'
        return False, self._err(data, 'Could not reset password')
