from .milkyway    import MilkyWayAPI
from .orionstars  import OrionStarsAPI
from .gamevault   import GameVaultAPI
from .juwa        import JuwaAPI
from .juwa2       import Juwa2API
from .vegassweeps import VegasSweepsAPI
from .ultrapanda  import UltraPandaAPI
from .portal_games import (
    FireKirinAPI, VBlinkAPI, PandaMasterAPI,
    GameRoomAPI, CashFrenzyAPI, CashMachineAPI, MafiaAPI,
    MrAllInOneAPI, YoloAPI, RiversweepsAPI,
    DragonFuryAPI, UltraThunderAPI,
)
from .generic import GenericAPI
from .loadstar import LoadstarAPI, is_loadstar_key

# Map game key → (API class, default portal URL)
GAME_MAP = {
    # ── Dedicated APIs ───────────────────────────────────────────────────
    'juwa':        (Juwa2API,       'https://ht.juwa777.com'),
    'juwa2':       (Juwa2API,       'https://agent.juwa2.com'),
    'gamevault':   (Juwa2API,       'https://agent.gamevault999.com'),
    'vegassweeps': (Juwa2API,       'https://agent.lasvegassweeps.com'),
    'ultrapanda':  (UltraPandaAPI,  'https://ht.ultrapanda.mobi'),
    'dragonfury':  (DragonFuryAPI,  'https://pccnz.dragonfury.club'),
    'ultrathunder': (UltraThunderAPI, 'https://fmubk.ultrathunder.mobi'),

    # ── ASP.NET portal platform ─────────────────────────────────────────
    'milkyway':    (MilkyWayAPI,    'https://milkywayapp.xyz:8781'),
    'orionstars':  (OrionStarsAPI,  'https://orionstars.vip:8781'),
    'firekirin':   (FireKirinAPI,   'https://firekirin.xyz:8888'),
    'vblink':      (VBlinkAPI,      'https://gm.vblink777.club'),
    'pandamaster': (PandaMasterAPI, 'https://pandamaster.vip'),
    'gameroom':    (GameRoomAPI,    'https://agentserver1.gameroom777.com'),
    'cashfrenzy':  (CashFrenzyAPI,  'https://agentserver.cashfrenzy777.com'),
    'cashmachine': (CashMachineAPI, 'https://agentserver.cashmachine777.com'),
    'mafia':       (MafiaAPI,       'https://agentserver.mafia77777.com'),
    'mrallinone':  (MrAllInOneAPI,  'https://agentserver.mrallinone777.com'),
    'yolo':        (YoloAPI,        'https://agent.yolo777.game'),
    'riversweeps': (RiversweepsAPI, 'https://river-pay.com'),
}

def get_api(game, username, password, token='', base_url=''):
    # A Loadstar API key as the password routes this game through Loadstar.
    if is_loadstar_key(password):
        return LoadstarAPI(game, username, password, token=token, base_url=base_url)
    entry = GAME_MAP.get(game)
    if not entry:
        return None
    cls, default_url = entry
    url = base_url or default_url
    return cls(username=username, password=password, token=token, base_url=url)
