import re
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
        return _English(LoadstarAPI(game, username, password, token=token, base_url=base_url))
    entry = GAME_MAP.get(game)
    if not entry:
        return None
    cls, default_url = entry
    url = base_url or default_url
    return _English(cls(username=username, password=password, token=token, base_url=url))


# ── Chinese panel messages → English (Ultra Thunder, Dragon Fury, Ultra Panda… answer in Chinese) ──
# Longer phrases first so "充值失败" wins over "失败".
_ZH = [
    ('服务器维护中', 'server under maintenance — try again later'), ('系统维护中', 'system under maintenance — try again later'),
    ('维护中', 'under maintenance'),
    ('充值失败', 'Recharge failed'), ('上分失败', 'Recharge failed'), ('下分失败', 'Withdraw failed'), ('提现失败', 'Withdraw failed'),
    ('兑换失败', 'Redeem failed'), ('登录失败', 'Login failed'), ('创建失败', 'Create failed'), ('修改失败', 'Update failed'),
    ('代理余额不足', 'your agent balance on this panel is too low'), ('余额不足', 'balance too low'),
    ('分数不足', 'not enough score'), ('积分不足', 'not enough score'), ('库存不足', 'not enough stock'),
    ('玩家不存在', 'player not found'), ('用户不存在', 'user not found'), ('账号不存在', 'account not found'),
    ('会员不存在', 'player not found'),
    ('账号已存在', 'username already exists'), ('用户名已存在', 'username already exists'), ('玩家已存在', 'player already exists'),
    ('账号或密码错误', 'wrong username or password'), ('用户名或密码错误', 'wrong username or password'), ('密码错误', 'wrong password'),
    ('验证码错误', 'wrong captcha code'), ('验证码', 'captcha'),
    ('权限不足', 'no permission'), ('没有权限', 'no permission'), ('无权限', 'no permission'),
    ('账号被冻结', 'account frozen'), ('账号已冻结', 'account frozen'), ('账号已禁用', 'account disabled'), ('已被禁用', 'disabled'),
    ('玩家在线', 'player is online — log them out of the game first'), ('正在游戏中', 'player is in a game — try after they exit'),
    ('登录已过期', 'session expired'), ('令牌失效', 'session expired'), ('token失效', 'session expired'), ('请重新登录', 'please log in again'),
    ('操作过于频繁', 'too many requests — wait a moment'), ('操作频繁', 'too many requests — wait a moment'),
    ('请求过于频繁', 'too many requests — wait a moment'),
    ('参数错误', 'invalid request'), ('签名错误', 'signature error'), ('系统繁忙', 'system busy'), ('系统错误', 'system error'),
    ('网络错误', 'network error'), ('请求超时', 'request timed out'), ('请稍后再试', 'please try again later'),
    ('金额错误', 'invalid amount'), ('金额必须大于0', 'amount must be more than 0'),
    ('IP不在白名单', 'this server IP is not on the panel allowlist'), ('IP限制', 'IP not allowed'), ('白名单', 'allowlist'),
    ('操作成功', 'success'), ('成功', 'success'), ('失败', 'failed'),
]
_CJK = re.compile(r'[㐀-鿿]')


def to_english(msg):
    """'充值失败：服务器维护中' → 'Recharge failed: server under maintenance — try again later (充值失败：服务器维护中)'."""
    if not isinstance(msg, str) or not _CJK.search(msg):
        return msg
    out = msg
    for zh, en in _ZH:
        out = out.replace(zh, en)
    out = out.replace('：', ': ').replace('，', ', ').replace('。', '. ').replace('！', '!').replace('（', ' (').replace('）', ')')
    out = re.sub(r'\s+', ' ', out).strip()
    if _CJK.search(out):          # words we don't know — say where it came from instead of repeating it
        return f'Game panel says: {msg}' if not re.search(r'[A-Za-z]', out) else f'{out} (panel: {msg})'
    return f'{out} ({msg})'


class _English:
    """Wraps a game API so every text it returns (errors, messages) is translated to English."""
    def __init__(self, api):
        object.__setattr__(self, '_api', api)

    def __setattr__(self, name, value):
        # settings like api.under (Loadstar) must reach the real API object
        setattr(self._api, name, value)

    def __getattr__(self, name):
        attr = getattr(self._api, name)
        if not callable(attr):
            return attr

        def call(*a, **k):
            res = attr(*a, **k)
            if isinstance(res, tuple):
                return tuple(to_english(x) for x in res)
            return to_english(res)
        return call
