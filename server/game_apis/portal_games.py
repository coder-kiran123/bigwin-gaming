from .milkyway import MilkyWayAPI
from .layui import LayUIAPI
from .ultrapanda import UltraPandaAPI

# ── ASP.NET WebForms portal (Milky Way platform) ──────────────────────────
# All games below share the same ASP.NET portal as Milky Way.

def _make_portal_class(display_name, default_url):
    class _PortalAPI(MilkyWayAPI):
        _display = display_name
        def __init__(self, username, password, token='', base_url=default_url):
            super().__init__(username, password, token=token, base_url=base_url)
        def test_connection(self):
            ok, msg = super().test_connection()
            return ok, msg.replace('Milky Way', self._display) if ok else msg
        def create_player(self, u, p, n=''):
            ok, msg, ext = super().create_player(u, p, n)
            return ok, msg.replace('Milky Way', self._display), ext
    _PortalAPI.__name__ = display_name.replace(' ', '') + 'API'
    return _PortalAPI

FireKirinAPI   = _make_portal_class('Fire Kirin',   'https://firekirin.xyz:8888')
PandaMasterAPI = _make_portal_class('Panda Master', 'https://pandamaster.vip')


# ── Ultra Panda platform (Vue SPA, AES-128-ECB + MD5 sign) ───────────────
# VBlink uses the exact same API as Ultra Panda.

class VBlinkAPI(UltraPandaAPI):
    def __init__(self, username, password, token='', base_url='https://gm.vblink777.club'):
        super().__init__(username, password, token=token, base_url=base_url)
    def test_connection(self):
        ok, msg = super().test_connection()
        return ok, msg.replace('Ultra Panda', 'VBlink') if ok else msg
    def create_player(self, u, p, n=''):
        ok, msg, ext = super().create_player(u, p, n)
        return ok, msg.replace('Ultra Panda', 'VBlink'), ext


# Dragon Fury and Ultra Thunder run the same Ultra Panda software (same as Loadstar's bridge).

def _make_ultrapanda_class(display_name, default_url):
    class _UPGame(UltraPandaAPI):
        def __init__(self, username, password, token='', base_url=default_url):
            super().__init__(username, password, token=token, base_url=base_url)
        def test_connection(self):
            ok, msg = super().test_connection()
            return ok, msg.replace('Ultra Panda', display_name) if ok else msg
        def create_player(self, u, p, n=''):
            ok, msg, ext = super().create_player(u, p, n)
            return ok, msg.replace('Ultra Panda', display_name), ext
    _UPGame.__name__ = display_name.replace(' ', '') + 'API'
    return _UPGame

DragonFuryAPI   = _make_ultrapanda_class('Dragon Fury',   'https://pccnz.dragonfury.club')
UltraThunderAPI = _make_ultrapanda_class('Ultra Thunder', 'https://fmubk.ultrathunder.mobi')


# ── LayUI v1.0.7 platform ─────────────────────────────────────────────────
# Mr All In One, Cash Frenzy, Game Room, Cash Machine, Mafia all share this
# platform. Endpoints verified against agentserver.mrallinone777.com.

def _make_layui_class(display_name, default_url):
    class _LayUIGame(LayUIAPI):
        _display = display_name
        def __init__(self, username, password, token='', base_url=default_url):
            super().__init__(username, password, token=token, base_url=base_url)
    _LayUIGame.__name__ = display_name.replace(' ', '') + 'API'
    return _LayUIGame

MrAllInOneAPI  = _make_layui_class('Mr All In One', 'https://agentserver.mrallinone777.com')
CashFrenzyAPI  = _make_layui_class('Cash Frenzy',   'https://agentserver.cashfrenzy777.com')
GameRoomAPI    = _make_layui_class('Game Room',      'https://agentserver1.gameroom777.com')
CashMachineAPI = _make_layui_class('Cash Machine',   'https://agentserver.cashmachine777.com')
MafiaAPI       = _make_layui_class('Mafia',          'https://agentserver.mafia77777.com')


# ── Unknown / pending platforms ───────────────────────────────────────────

def _make_stub_class(display_name, default_url):
    class _StubAPI(MilkyWayAPI):
        _display = display_name
        def __init__(self, username, password, token='', base_url=default_url):
            super().__init__(username, password, token=token, base_url=base_url)
    _StubAPI.__name__ = display_name.replace(' ', '') + 'API'
    return _StubAPI

YoloAPI        = _make_stub_class('Yolo',         'https://agent.yolo777.game')
RiversweepsAPI = _make_stub_class('River Sweeps', 'https://river-pay.com')
