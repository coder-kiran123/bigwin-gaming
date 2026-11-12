import hashlib
import base64
import os
import time
import requests
import urllib.parse
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Ultra Panda — Vue SPA + REST JSON API
#
# Portal: https://ht.ultrapanda.mobi
# API base: /api/
#
# Auth flow:
#   POST /api/user/login  {username: AES_ECB(user, stime, key="123{stime}abc"),
#                          password: AES_ECB(pass, stime), stime, auth_code: ""}
#                       + {sign: MD5(sorted_vals+stime+SECRET), stime}  (interceptor adds)
#                       ← {code:200, data:{token:...}}
#   All subsequent requests:
#     Headers: x-token = url_encode(AES_ECB(token, key="xtu{ts_ms}")), x-time = ts_ms
#     Body: {token, ...params, sign, stime}
#
# Agent management API endpoints (all POST):
#   /account/getPlayerList  → {token, account: search}
#   /account/getPlayerScore → {token, account}
#   /account/savePlayer     → {token, account, pwd, score:0, name:""}
#   /account/updatePlayer   → {token, account, pwd, name, phone, remark}
#   /account/enterScore     → {token, account, score: +/-, remark, user_type:"player"}
#   /account/getPlayerInfo  → {token, account}

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    _CRYPTO_OK = True
except ImportError:
    _CRYPTO_OK = False

SIGN_SECRET = "#s3LEA3RpR6PNmbWtuBCPn!4gS2DNM44"


def _aes_ecb_encrypt(plaintext: str, key: str) -> str:
    if not _CRYPTO_OK:
        return plaintext
    key_bytes = key.encode('utf-8')
    pt_bytes = plaintext.encode('utf-8')
    cipher = AES.new(key_bytes, AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(pt_bytes, AES.block_size))
    return base64.b64encode(encrypted).decode()


def _compute_sign(payload: dict, stime: int) -> str:
    sorted_keys = sorted(payload.keys())
    n = ""
    for k in sorted_keys:
        v = payload.get(k)
        if k == "stime" or v == "" or v is None:
            continue
        n += str(v)
    sign_input = n + str(stime) + SIGN_SECRET
    return hashlib.md5(sign_input.encode('utf-8')).hexdigest()


def _signed(payload: dict) -> dict:
    stime = payload.get("stime") or int(time.time())
    sign = _compute_sign(payload, stime)
    result = {"sign": sign, "stime": stime}
    result.update(payload)
    return result


def _xtoken_headers(token: str) -> dict:
    ts_ms = int(time.time() * 1000)
    key = f"xtu{ts_ms}"
    encrypted = _aes_ecb_encrypt(token, key)
    return {
        "x-token": urllib.parse.quote(encrypted),
        "x-time": str(ts_ms),
    }


class UltraPandaAPI:
    API_BASE = "https://ht.ultrapanda.mobi/api"

    def __init__(self, username, password, token='', base_url='https://ht.ultrapanda.mobi'):
        self.username = username
        self.password = password
        # Strip hash fragment and trailing slashes from whatever URL was stored
        self.base_url = base_url.split('#')[0].rstrip('/')
        self._token = token or None  # reuse cached token if provided
        proxy_url = os.environ.get('FIXIE_URL') or os.environ.get('QUOTAGUARDSTATIC_URL')
        self._proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None

    def _api(self, path):
        return self.base_url + "/api/" + path.lstrip('/')

    def _session(self):
        s = requests.Session()
        s.verify = False
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": self.base_url,
            "Referer": self.base_url + "/",
            "x-fingerprint": "9b39f485a86166310f1746d039067d54",
        })
        if self._proxies:
            s.proxies = self._proxies
        return s

    def _login(self, s):
        stime = int(time.time())
        payload = {
            "username": _aes_ecb_encrypt(self.username, f"123{stime}abc"),
            "password": _aes_ecb_encrypt(self.password, f"123{stime}abc"),
            "stime": stime,
            "auth_code": "",
        }
        try:
            r = s.post(self._api("user/login"), json=_signed(payload), timeout=20)
            if not r.text.strip():
                return False, f"Empty response (HTTP {r.status_code})"
            if r.text.strip()[0] != '{':
                return False, f"Non-JSON response (HTTP {r.status_code}): {r.text[:120]}"
            resp = r.json()
        except Exception as e:
            return False, str(e)
        if resp.get("code") == 20000:
            self._login_resp = resp  # some panels put the login's own score here
            self._token = resp.get("token") or (resp.get("data") or {}).get("token")
            if self._token:
                return True, "Logged in"
        return False, resp.get("msg") or f"Login failed (code={resp.get('code')})"

    def _authed_session(self, force_relogin=False):
        s = self._session()
        if self._token and not force_relogin:
            s.headers.update(_xtoken_headers(self._token))
            return s, None
        ok, msg = self._login(s)
        if not ok:
            return None, msg
        s.headers.update(_xtoken_headers(self._token))
        return s, None

    def _post(self, s, path, payload, _retry=True):
        full_payload = {"token": self._token}
        full_payload.update(payload)
        try:
            r = s.post(self._api(path), json=_signed(full_payload), timeout=20)
            if not r.text.strip():
                return None, f"Empty response (HTTP {r.status_code})"
            if r.text.strip()[0] != '{':
                return None, f"Non-JSON response (HTTP {r.status_code}): {r.text[:120]}"
            resp = r.json()
            # Token expired — re-login once and retry
            if _retry and resp.get("code") in (401, 403, 1001, 1003) or (
                resp.get("code") != 20000 and "权限" in (resp.get("msg") or resp.get("message") or "")
            ):
                s2, err = self._authed_session(force_relogin=True)
                if not err:
                    return self._post(s2, path, payload, _retry=False)
            return resp, None
        except Exception as e:
            return None, str(e)

    def _find_player(self, s, account):
        resp, err = self._post(s, "account/getPlayerList", {"account": account})
        if err:
            return None, err
        if resp.get("code") != 20000:
            return None, resp.get("msg") or resp.get("message") or "getPlayerList failed"
        items = (resp.get("data") or {}).get("list") or []
        for p in items:
            if p.get("account", "").lower() == account.lower():
                return p, None
        return None, f'Player "{account}" not found'

    @staticmethod
    def _find_num(obj, keys=("LimitNum", "limitNum", "curScore", "score", "Score", "balance", "money")):
        # First number under one of the balance keys, anywhere in a JSON reply.
        if isinstance(obj, dict):
            for k in keys:
                if k in obj and obj[k] not in (None, ''):
                    try:
                        return float(obj[k])
                    except (TypeError, ValueError):
                        pass
            for v in obj.values():
                n = UltraPandaAPI._find_num(v, keys)
                if n is not None:
                    return n
        elif isinstance(obj, list):
            for v in obj:
                n = UltraPandaAPI._find_num(v, keys)
                if n is not None:
                    return n
        return None

    # ── Public interface ──────────────────────────────────────────────────

    def get_agent_balance(self):
        # Ported from Loadstar's bridge. Ultra Panda answers account/getScore with no fields;
        # Dragon Fury and Ultra Thunder need our account named, and answer with curScore.
        # Last resort: the score in the login reply.
        s, err = self._authed_session(force_relogin=True)
        if err:
            return None, err
        errors, unlimited = [], False
        for payload in ({}, {"account": self.username}):
            resp, err = self._post(s, "account/getScore", payload)
            if err:
                errors.append(err)
                continue
            if resp.get("code") != 20000:
                errors.append(resp.get("msg") or resp.get("message") or "getScore failed")
                continue
            bal = resp.get("LimitNum")
            if bal is None:
                bal = resp.get("curScore")
            if bal is None and isinstance(resp.get("data"), dict):
                bal = resp["data"].get("LimitNum", resp["data"].get("curScore"))
            if bal is None:
                bal = self._find_num(resp)
            try:
                return float(bal), None
            except (TypeError, ValueError):
                unlimited = True  # answered, but this login has no credit limit
                break
        bal = self._find_num({k: v for k, v in (getattr(self, '_login_resp', None) or {}).items() if k != 'token'})
        if bal is not None:
            return bal, None
        if unlimited:
            return None, 'No credit limit on this login'
        return None, errors[-1] if errors else 'Balance not found'


    def test_connection(self):
        s = self._session()
        ok, msg = self._login(s)
        if ok:
            return True, "Ultra Panda connection successful"
        return False, msg

    def get_balance(self, player_username, external_id=''):
        s, err = self._authed_session()
        if err:
            return None, err
        resp, err = self._post(s, "account/getPlayerScore", {"account": player_username})
        if err:
            return None, err
        if resp.get("code") != 20000:
            return None, resp.get("msg") or resp.get("message") or "getPlayerScore failed"
        score = resp.get("curScore") or (resp.get("data") or {}).get("score") or 0
        return float(score), None

    def add_credits(self, player_username, amount, note='', external_id=''):
        s, err = self._authed_session()
        if err:
            return False, err
        resp, err = self._post(s, "account/enterScore", {
            "account": player_username,
            "score": str(amount),
            "remark": note or "",
            "user_type": "player",
        })
        if err:
            return False, err
        if resp.get("code") == 20000:
            return True, f"Added {amount} credits to {player_username}"
        return False, resp.get("msg") or resp.get("message") or "enterScore failed"

    def withdraw_credits(self, player_username, amount, note='', external_id=''):
        s, err = self._authed_session()
        if err:
            return False, err
        resp, err = self._post(s, "account/enterScore", {
            "account": player_username,
            "score": str(-abs(amount)),
            "remark": note or "",
            "user_type": "player",
        })
        if err:
            return False, err
        if resp.get("code") == 20000:
            return True, f"Withdrew {amount} credits from {player_username}"
        return False, resp.get("msg") or resp.get("message") or "enterScore (withdraw) failed"

    def reset_password(self, player_username, new_password, external_id=''):
        s, err = self._authed_session()
        if err:
            return False, err
        resp, err = self._post(s, "account/updatePlayer", {
            "account": player_username,
            "pwd": new_password,
            "name": player_username,
            "phone": "",
            "remark": "",
        })
        if err:
            return False, err
        if resp.get("code") == 20000:
            return True, f"Password reset for {player_username}"
        code = resp.get("code")
        msg = resp.get("msg") or resp.get("message") or f"updatePlayer failed (code={code})"
        return False, msg

    def create_player(self, username, password, nickname=''):
        s, err = self._authed_session()
        if err:
            return False, err, {}
        resp, err = self._post(s, "account/savePlayer", {
            "account": username,
            "pwd": password,
            "score": "0",
            "name": nickname or username,
        })
        if err:
            return False, err, {}
        if resp.get("code") == 20000:
            return True, f"Player {username} created on Ultra Panda", ""
        msg = resp.get("msg", "")
        if "exist" in msg.lower() or "already" in msg.lower() or "duplicate" in msg.lower():
            return True, f"Player {username} already exists on Ultra Panda (linked)", ""
        return False, msg or "savePlayer failed", {}
