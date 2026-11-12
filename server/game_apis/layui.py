import os
import re
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LayUIAPI:
    """
    Base class for casino backends running the LayUI v1.0.7 agent platform.

    Login flow: GET /admin/login → extract CSRF token → POST /api/login
    Auth: Authorization: Bearer {token}
    Player endpoints use numeric id, looked up from /api/player/userList by account name.

    Verified on Mr All In One (agentserver.mrallinone777.com).
    Cash Frenzy, Game Room, Cash Machine, Mafia use identical platform/endpoints.

    Password rules enforced server-side:
      create: alphanumeric only, 6–12 chars
      reset:  uppercase + lowercase + special char, 6–12 chars
    Remark fields: alphanumeric only, ≤50 chars (stripped automatically).
    """

    _display = "LayUI Game"

    def __init__(self, username, password, token='', base_url=''):
        self.username = username
        self.password = password
        url = base_url.split('#')[0].rstrip('/')
        # Strip any path the user may have pasted (e.g. /admin/login, /admin)
        for suffix in ('/admin/login', '/admin'):
            if url.endswith(suffix):
                url = url[:-len(suffix)]
                break
        self.base_url = url
        self._token = token or None
        proxy_url = os.environ.get('FIXIE_URL') or os.environ.get('QUOTAGUARDSTATIC_URL')
        self._proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None

    def _session(self):
        s = requests.Session()
        s.verify = False
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
        })
        if self._proxies:
            s.proxies = self._proxies
        return s

    def _login(self, s):
        try:
            r = s.get(f'{self.base_url}/admin/login', timeout=15)
            m = re.search(r'csrf-token[^>]*content=["\']([^"\']+)["\']', r.text, re.IGNORECASE)
            if not m:
                return False, "CSRF token not found on login page"
            csrf = m.group(1)
        except Exception as e:
            return False, f"Login page fetch error: {e}"
        try:
            r = s.post(
                f'{self.base_url}/api/login',
                data={'username': self.username, 'password': self.password, 'captcha': ''},
                headers={'X-CSRF-TOKEN': csrf, 'Referer': f'{self.base_url}/admin/login'},
                timeout=15,
            )
            resp = r.json()
        except Exception as e:
            return False, f"Login POST error: {e}"
        if resp.get('status_code') == 200 and resp.get('token'):
            self._token = resp['token']
            s.headers.update({'Authorization': f'Bearer {self._token}'})
            return True, "Logged in"
        return False, resp.get('message') or f"Login failed (status={resp.get('status_code')})"

    def _authed_session(self):
        # LayUI JWT tokens expire in ~6 hours — always re-login for fresh token
        s = self._session()
        ok, msg = self._login(s)
        if not ok:
            return None, msg
        return s, None

    def _get_player_id(self, s, username):
        try:
            r = s.get(
                f'{self.base_url}/api/player/userList',
                params={'account': username, 'page': 1, 'limit': 10},
                timeout=15,
            )
            data = r.json().get('data') or []
            for p in data:
                if p.get('Account', '').lower() == username.lower():
                    return p['id'], None
            return None, f'Player "{username}" not found on {self._display}'
        except Exception as e:
            return None, str(e)

    @staticmethod
    def _clean_remark(remark):
        return re.sub(r'[^a-zA-Z0-9]', '', remark or '')[:50]

    # ── Public interface ──────────────────────────────────────────────────

    def test_connection(self):
        s = self._session()
        ok, msg = self._login(s)
        return (True, f"{self._display} connection successful") if ok else (False, msg)

    def get_balance(self, player_username, external_id=''):
        s, err = self._authed_session()
        if err:
            return None, err
        pid, err = self._get_player_id(s, player_username)
        if err:
            return None, err
        try:
            r = s.get(f'{self.base_url}/api/player/agentMoney', params={'id': pid}, timeout=15)
            d = r.json()
            if d.get('status_code') == 200:
                return float(d['data']['balance']), None
            return None, d.get('message') or "agentMoney failed"
        except Exception as e:
            return None, str(e)

    def add_credits(self, player_username, amount, note='', external_id=''):
        s, err = self._authed_session()
        if err:
            return False, err
        pid, err = self._get_player_id(s, player_username)
        if err:
            return False, err
        # agentRecharge requires the agent's current available balance
        try:
            r = s.get(f'{self.base_url}/api/player/agentMoney', params={'id': pid}, timeout=15)
            avail = r.json().get('data', {}).get('cusBlance', '0')
        except Exception as e:
            return False, f"Balance fetch error: {e}"
        try:
            r = s.post(
                f'{self.base_url}/api/player/agentRecharge',
                data={
                    'id': str(pid),
                    'available_balance': avail,
                    'opera_type': '0',
                    'bonus': '0',
                    'balance': str(int(amount)),
                    'remark': self._clean_remark(note),
                },
                timeout=15,
            )
            d = r.json()
            if d.get('status_code') == 200:
                return True, f"Added {amount} credits to {player_username}"
            return False, d.get('message') or "agentRecharge failed"
        except Exception as e:
            return False, str(e)

    def withdraw_credits(self, player_username, amount, note='', external_id=''):
        s, err = self._authed_session()
        if err:
            return False, err
        pid, err = self._get_player_id(s, player_username)
        if err:
            return False, err
        # agentWithdraw requires the player's current balance
        try:
            r = s.get(f'{self.base_url}/api/player/agentMoney', params={'id': pid}, timeout=15)
            player_bal = str(r.json().get('data', {}).get('balance', '0'))
        except Exception as e:
            return False, f"Balance fetch error: {e}"
        try:
            r = s.post(
                f'{self.base_url}/api/player/agentWithdraw',
                data={
                    'id': str(pid),
                    'customer_balance': player_bal,
                    'opera_type': '1',
                    'balance': str(int(amount)),
                    'remark': self._clean_remark(note),
                },
                timeout=15,
            )
            d = r.json()
            if d.get('status_code') == 200:
                return True, f"Withdrew {amount} credits from {player_username}"
            return False, d.get('message') or "agentWithdraw failed"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _make_pw_compliant(pw):
        # LayUI reset requires uppercase + lowercase + special char, 6–12 chars
        if not any(c.isupper() for c in pw):
            pw = pw[0].upper() + pw[1:]
        if not any(c.islower() for c in pw):
            pw = pw + 'a'
        if not any(c in '!@#$%^&*' for c in pw):
            pw = pw + '!'
        return pw[:12]

    def reset_password(self, player_username, new_password, external_id=''):
        s, err = self._authed_session()
        if err:
            return False, err
        pid, err = self._get_player_id(s, player_username)
        if err:
            return False, err
        pw = self._make_pw_compliant(new_password)
        try:
            r = s.post(
                f'{self.base_url}/api/player/reset',
                data={
                    'id': str(pid),
                    'password': pw,
                    'password_confirmation': pw,
                },
                timeout=15,
            )
            d = r.json()
            if d.get('status_code') == 200:
                return True, f"Password reset for {player_username}"
            return False, d.get('message') or "Password reset failed"
        except Exception as e:
            return False, str(e)

    def create_player(self, username, password, nickname=''):
        s, err = self._authed_session()
        if err:
            return False, err, {}
        # Server requires alphanumeric-only password, 6–12 chars for creation
        clean_pw = re.sub(r'[^a-zA-Z0-9]', '', password)[:12]
        if len(clean_pw) < 6:
            clean_pw = (clean_pw + 'Pass99')[:12]
        try:
            r = s.post(
                f'{self.base_url}/api/player/playerInsert',
                data={
                    'username': username,
                    'nickname': nickname or username,
                    'money': '0',
                    'password': clean_pw,
                    'password_confirmation': clean_pw,
                },
                timeout=15,
            )
            d = r.json()
        except Exception as e:
            return False, str(e), {}
        if d.get('status_code') == 200:
            return True, f"Player {username} created on {self._display}", {}
        msg = d.get('message', '')
        if any(w in msg.lower() for w in ('exist', 'already', 'duplicate', 'registered')):
            return True, f"Player {username} already exists on {self._display} (linked)", {}
        return False, msg or "playerInsert failed", {}
