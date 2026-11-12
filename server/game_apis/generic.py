import os
import requests
import urllib3

_GAME_SSL_VERIFY = os.environ.get('GAME_SSL_VERIFY', 'false').lower() == 'true'
if not _GAME_SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Generic fallback for games without a specific API integration yet.
# Tests connection by doing a simple HTTP GET to the base URL.

class GenericAPI:
    def __init__(self, username, password, token='', base_url=''):
        self.username = username
        self.password = password
        self.token    = token
        self.base_url = base_url.rstrip('/')

    def test_connection(self):
        if not self.base_url:
            return False, 'No base URL configured'
        try:
            r = requests.get(self.base_url, timeout=10, verify=_GAME_SSL_VERIFY,
                             headers={'User-Agent': 'Mozilla/5.0'})
            if r.status_code < 500:
                return True, f'Host reachable (HTTP {r.status_code}) — credentials saved but not verified'
            return False, f'Server error: HTTP {r.status_code}'
        except requests.exceptions.ConnectionError:
            return False, f'Cannot reach {self.base_url}'
        except Exception as e:
            return False, str(e)

    def create_player(self, player_username, player_password, nickname=''):
        return False, 'API integration not implemented for this game yet. Contact support.'

    def get_balance(self, player_username):
        return None, 'Balance check not implemented for this game yet'

    def add_credits(self, player_username, amount):
        return False, 'Credit management not implemented for this game yet'

    def withdraw_credits(self, player_username, amount):
        return False, 'Credit management not implemented for this game yet'
