import os
import re
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Milky Way / Orion Stars — ASP.NET WebForms portal (v3.x)
#
# Login flow:
#   GET /  → get ViewState + session cookie
#   GET /Tools/VerifyImagePage.aspx  → solve numeric CAPTCHA with ddddocr
#   POST / → credentials + captcha → redirects to Store.aspx on success
#
# Credit flow (per-player):
#   GET  AccountsList.aspx  → ViewState for search
#   POST AccountsList.aspx  → txtSearch=username → parse updateSelect('uid,gid')
#   POST AccountsList.aspx  → tourl=0/1/2 + uid + gid → get dialog page URL
#   GET  GrantTreasure.aspx / ChangeTreasure.aspx / ResetPassWord.aspx → ViewState
#   POST same page          → submit amount / password

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


class MilkyWayAPI:
    LOGIN_URL    = '/'
    CAPTCHA_URL  = '/Tools/VerifyImagePage.aspx'
    LIST_URL     = '/Module/AccountManager/AccountsList.aspx'

    def __init__(self, username, password, token='', base_url='https://milkywayapp.xyz:8781'):
        self.username      = username.strip()
        self.password      = password.strip()
        self.base_url      = base_url.rstrip('/')
        self._session      = None
        self._logged_in    = False
        self._manual_sid   = token.strip() if token else ''

        proxy_url = os.environ.get('FIXIE_URL') or os.environ.get('QUOTAGUARDSTATIC_URL')
        self._proxy = {'http': proxy_url, 'https': proxy_url} if proxy_url else None

    # ── Session helpers ───────────────────────────────────────────────────

    def _new_session(self):
        s = requests.Session()
        s.verify = False
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        if self._proxy:
            s.proxies = self._proxy
        return s

    def _extract(self, name, html):
        for pat in [
            rf'id="{re.escape(name)}"[^>]*value="([^"]*)"',
            rf'name="{re.escape(name)}"[^>]*value="([^"]*)"',
        ]:
            m = re.search(pat, html)
            if m:
                return m.group(1)
        return ''

    def _hidden_fields(self, html):
        return {
            '__EVENTTARGET':        '',
            '__EVENTARGUMENT':      '',
            '__VIEWSTATE':          self._extract('__VIEWSTATE', html),
            '__VIEWSTATEGENERATOR': self._extract('__VIEWSTATEGENERATOR', html),
            '__EVENTVALIDATION':    self._extract('__EVENTVALIDATION', html),
        }

    def _solve_captcha(self, session):
        ocr = _get_ocr()
        if not ocr:
            raise RuntimeError('ddddocr not installed — run: pip install ddddocr')
        r = session.get(self.base_url + self.CAPTCHA_URL, timeout=10)
        return ocr.classification(r.content)

    def _login(self):
        s = self._new_session()

        if self._manual_sid:
            s.cookies.set('ASP.NET_SessionId', self._manual_sid)
            self._session   = s
            self._logged_in = True
            return True, 'Using provided session ID'

        if not self.username or not self.password:
            return False, 'No username/password provided for Milky Way'

        _bad_creds = {'errorNamePassowrd', 'errorBindIP', 'errorBlockIPErr', 'errorNullity', 'errorUserRole'}
        _errs = {
            'errorNamePassowrd': 'Wrong username or password',
            'errorVerifyCode':   'CAPTCHA wrong',
            'verifycode':        'CAPTCHA wrong',
            'errorBindIP':       'Account bound to a specific IP; cannot login from here',
            'errorBlockIPErr':   'IP temporarily blocked',
            'errorNullity':      'Account banned',
            'errorUserRole':     'Account does not have admin role',
        }

        last_err = 'Unknown error'
        for attempt in range(4):   # retry up to 4x on bad CAPTCHA
            try:
                r = s.get(self.base_url + self.LOGIN_URL, timeout=15, allow_redirects=True)
                if 'txtLoginName' not in r.text:
                    return False, f'Login page unavailable (HTTP {r.status_code})'

                code = self._solve_captcha(s)

                fields = self._hidden_fields(r.text)
                fields.update({
                    '__LASTFOCUS':   '',
                    'ddlRole':       '0',
                    'txtLoginName':  self.username,
                    'txtLoginPass':  self.password,
                    'txtVerifyCode': code,
                    'btnLogin':      'Login in',
                })
                r2 = s.post(
                    self.base_url + self.LOGIN_URL, data=fields,
                    headers={'Referer': self.base_url + self.LOGIN_URL}, timeout=15,
                )

                if 'errtype=' in r2.url or 'errtype=' in r2.text:
                    m = re.search(r'errtype=(\w+)', r2.url + r2.text)
                    err_key = m.group(1) if m else 'errorNamePassowrd'
                    last_err = _errs.get(err_key, f'Login failed: {err_key}')
                    # Only retry for CAPTCHA errors
                    if err_key not in ('errorVerifyCode', 'verifycode'):
                        return False, last_err
                    continue  # retry with new CAPTCHA

                if 'Store.aspx' in r2.url or ('txtLoginName' not in r2.text and r2.status_code == 200):
                    self._session   = s
                    self._logged_in = True
                    return True, 'Logged in to Milky Way'

                last_err = f'Unexpected login response (HTTP {r2.status_code})'

            except Exception as e:
                last_err = str(e)

        return False, last_err

    def _ensure_session(self):
        if self._logged_in and self._session:
            return True, ''
        return self._login()

    def _get(self, path, referer=None):
        ok, msg = self._ensure_session()
        if not ok:
            return None, msg
        ref = referer or (self.base_url + '/Store.aspx')
        r = self._session.get(self.base_url + path, headers={'Referer': ref}, timeout=15)
        if self._session_expired(r):
            self._logged_in = False
            ok2, msg2 = self._login()
            if not ok2:
                return None, f'Re-login failed: {msg2}'
            r = self._session.get(self.base_url + path, headers={'Referer': ref}, timeout=15)
        return r, None

    def _post(self, path, data, referer=None, content_type=None):
        ok, msg = self._ensure_session()
        if not ok:
            return None, msg
        ref = referer or (self.base_url + path)
        h = {'Referer': ref}
        if content_type:
            h['Content-Type'] = content_type
        r = self._session.post(self.base_url + path, data=data, headers=h, timeout=15)
        if self._session_expired(r):
            self._logged_in = False
            ok2, msg2 = self._login()
            if not ok2:
                return None, f'Re-login failed: {msg2}'
            r = self._session.post(self.base_url + path, data=data, headers=h, timeout=15)
        return r, None

    def _session_expired(self, r):
        return 'txtLoginName' in r.text or 'errtype=overtime' in r.url

    def _alerts(self, html):
        msgs  = re.findall(r'testAlter\("([^"]+)"\)', html)
        msgs += re.findall(r"alert\('([^']+)'\)", html)
        msgs += re.findall(r'myAlert\([^,]+,\s*["\']([^"\']+)["\']', html)
        msgs += re.findall(r'showAlter\("([^"]+)"\)', html)
        return msgs

    # ── Player lookup ─────────────────────────────────────────────────────

    def _find_player(self, username):
        """Search AccountsList and return (uid, gid, balance) or raise."""
        r, err = self._get(self.LIST_URL)
        if err:
            return None, None, None, err

        # POST search
        fields = self._hidden_fields(r.text)
        fields.update({'__EVENTTARGET': 'ctl16', 'txtSearch': username, 'ShowHideAccount': '1'})
        r2, err = self._post(self.LIST_URL, fields, referer=self.base_url + '/Store.aspx')
        if err:
            return None, None, None, err

        # Parse updateSelect('uid,gid') from result row
        m = re.search(r"updateSelect\(\s*['\"](\d+),(\d+)['\"]", r2.text)
        if not m:
            return None, None, None, f'Player "{username}" not found'

        uid, gid = m.group(1), m.group(2)

        # Parse balance from the table row
        bal = 0.0
        bal_m = re.search(
            rf'{re.escape(username)}\s*</td>.*?<td[^>]*>\s*([\d.]+)\s*</td>',
            r2.text, re.DOTALL
        )
        if bal_m:
            try:
                bal = float(bal_m.group(1))
            except ValueError:
                pass

        return uid, gid, bal, None

    def _dialog_url(self, uid, gid, tourl_idx):
        """Get the dialog page URL for recharge(0), redeem(1), or reset-password(2)."""
        r, err = self._post(
            self.LIST_URL,
            data={'tourl': str(tourl_idx), 'getpassuid': uid, 'getpassgid': gid},
            referer=self.base_url + '/Store.aspx',
            content_type='application/x-www-form-urlencoded',
        )
        if err:
            return None, err
        url = r.text.split('|')[0].strip()
        if not url or 'aspx' not in url.lower():
            return None, 'Could not get dialog URL — player may not be selected'
        return '/' + url.lstrip('/'), None

    # ── Public API ────────────────────────────────────────────────────────

    def test_connection(self):
        ok, msg = self._login()
        if not ok:
            return False, msg
        r, err = self._get(self.LIST_URL)
        if err:
            return False, err
        if 'txtSearch' in r.text:
            return True, f'Connected to Milky Way ({self.base_url})'
        return False, 'Logged in but account list page not loading'

    def create_player(self, player_username, player_password, nickname=''):
        create_path = '/Module/AccountManager/AccountsList.aspx'
        # Dialog index 6 = Create Player
        r, err = self._post(
            self.LIST_URL,
            data={'tourl': '6', 'getpassuid': '', 'getpassgid': '', 'param': '1'},
            referer=self.base_url + '/Store.aspx',
            content_type='application/x-www-form-urlencoded',
        )
        if err:
            return False, err, ''

        dialog_url = r.text.split('|')[0].strip()
        if not dialog_url or 'aspx' not in dialog_url.lower():
            return False, 'Could not load create-player dialog', ''

        cp_path = '/' + dialog_url.lstrip('/')
        rp, err = self._get(cp_path, referer=self.base_url + self.LIST_URL)
        if err:
            return False, err, ''

        nick = nickname or (player_username + '1' if len(player_username) < 6 else player_username)

        # Extract the actual postback target from the page (e.g. 'ctl07')
        btn_m = re.search(r"__doPostBack\('([^']+)',''\)", rp.text)
        event_target = btn_m.group(1) if btn_m else 'ctl07'

        fields = self._hidden_fields(rp.text)
        fields.update({
            '__EVENTTARGET': event_target,
            'txtAccount':    player_username,
            'txtNickName':   nick,
            'txtLogonPass':  player_password,
            'txtLogonPass2': player_password,
        })
        r2, err = self._post(cp_path, fields, referer=self.base_url + cp_path)
        if err:
            return False, err, ''

        msgs = self._alerts(r2.text)
        if any('success' in m.lower() or 'added' in m.lower() for m in msgs):
            return True, f'Account "{player_username}" created on Milky Way', ''
        elif any('exist' in m.lower() or 'already' in m.lower() for m in msgs):
            return False, f'Username "{player_username}" already exists', ''
        elif msgs:
            return False, '; '.join(msgs), ''
        # Fallback: check if page reloaded cleanly
        if 'txtAccount' not in r2.text:
            return True, f'Account "{player_username}" created on Milky Way', ''
        return False, 'No confirmation — check portal manually', ''

    def get_balance(self, player_username, external_id=''):
        uid, gid, bal, err = self._find_player(player_username)
        if err:
            return None, err
        return bal, None

    def get_agent_balance(self):
        r, err = self._get(self.LIST_URL)
        if err:
            return None, err
        # AccountsList injects: updateBalance("Balance:123.45")
        m = re.search(r'updateBalance\(["\']Balance:([\d.]+)["\']', r.text)
        if m:
            return float(m.group(1)), None
        # Fallback: look for balance display in page
        m2 = re.search(r'Balance.*?:\s*([\d.]+)', r.text)
        if m2:
            return float(m2.group(1)), None
        return None, 'Agent balance not found on AccountsList page'

    def add_credits(self, player_username, amount, external_id='', order_id=None):
        uid, gid, _, err = self._find_player(player_username)
        if err:
            return False, err

        url, err = self._dialog_url(uid, gid, 0)   # 0 = Recharge
        if err:
            return False, err

        rp, err = self._get(url, referer=self.base_url + self.LIST_URL)
        if err:
            return False, err

        fields = self._hidden_fields(rp.text)
        fields.update({
            '__EVENTTARGET': 'Button1',
            'textGameID':    gid,
            'textAccounts':  player_username,
            'txtAddGold':    str(int(amount)),
        })
        r2, err = self._post(url, fields, referer=self.base_url + url)
        if err:
            return False, err

        msgs = self._alerts(r2.text)
        if any('success' in m.lower() for m in msgs):
            return True, f'Added ${amount} to {player_username}'
        elif msgs:
            return False, '; '.join(msgs)
        # If page changed (no more form), treat as success
        if 'txtAddGold' not in r2.text:
            return True, f'Added ${amount} to {player_username}'
        return False, 'Recharge submitted but no confirmation received'

    def withdraw_credits(self, player_username, amount, external_id='', order_id=None):
        uid, gid, bal, err = self._find_player(player_username)
        if err:
            return False, err
        if bal is not None and float(amount) > bal:
            return False, f'Insufficient balance: player has ${bal:.2f}, requested ${amount}'

        url, err = self._dialog_url(uid, gid, 1)   # 1 = Redeem
        if err:
            return False, err

        rp, err = self._get(url, referer=self.base_url + self.LIST_URL)
        if err:
            return False, err

        fields = self._hidden_fields(rp.text)
        fields.update({
            '__EVENTTARGET': 'Button1',
            'textGameID':    gid,
            'textAccounts':  player_username,
            'txtAddGold':    str(int(amount)),
        })
        r2, err = self._post(url, fields, referer=self.base_url + url)
        if err:
            return False, err

        msgs = self._alerts(r2.text)
        if any('success' in m.lower() for m in msgs):
            return True, f'Withdrew ${amount} from {player_username}'
        elif msgs:
            return False, '; '.join(msgs)
        if 'txtAddGold' not in r2.text:
            return True, f'Withdrew ${amount} from {player_username}'
        return False, 'Redeem submitted but no confirmation received'

    def reset_password(self, player_username, new_password, external_id=''):
        uid, gid, _, err = self._find_player(player_username)
        if err:
            return False, err

        url, err = self._dialog_url(uid, gid, 2)   # 2 = Reset Password
        if err:
            return False, err

        rp, err = self._get(url, referer=self.base_url + self.LIST_URL)
        if err:
            return False, err

        fields = self._hidden_fields(rp.text)
        fields.update({
            '__EVENTTARGET':    'Button1',
            'textGameID':       gid,
            'textAccounts':     player_username,
            'txtConfirmPass':   new_password,
            'txtSureConfirmPass': new_password,
        })
        r2, err = self._post(url, fields, referer=self.base_url + url)
        if err:
            return False, err

        msgs = self._alerts(r2.text)
        if any('success' in m.lower() for m in msgs):
            return True, f'Password reset for {player_username}'
        elif msgs:
            return False, '; '.join(msgs)
        if 'txtConfirmPass' not in r2.text:
            return True, f'Password reset for {player_username}'
        return False, 'Reset submitted but no confirmation received'

    def ping(self):
        """Keep session alive — call every 20 min."""
        if not self._session:
            return False
        try:
            r = self._session.get(self.base_url + '/', timeout=10, allow_redirects=True)
            return 'txtLoginName' not in r.text
        except Exception:
            return False
