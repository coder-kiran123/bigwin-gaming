import os
import re
import sqlite3

DATABASE_URL = os.environ.get('DATABASE_URL', '')
USE_PG = DATABASE_URL.startswith('postgres')

DB_PATH = os.path.join(os.path.dirname(__file__), 'casino.db')

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS backends (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game        TEXT NOT NULL,
    name        TEXT NOT NULL,
    username    TEXT NOT NULL,
    password    TEXT NOT NULL,
    token       TEXT DEFAULT '',
    base_url    TEXT DEFAULT '',
    status      TEXT DEFAULT 'unknown',
    enabled     INTEGER NOT NULL DEFAULT 1,
    balance     REAL DEFAULT 0,
    loadstar_under TEXT DEFAULT '',
    last_tested TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS players (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    email         TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    balance       REAL DEFAULT 0.0,
    fp_credits    REAL DEFAULT 1.0,
    phone         TEXT DEFAULT '',
    phone_verified INTEGER NOT NULL DEFAULT 0,
    referral_code TEXT DEFAULT '',
    status        TEXT DEFAULT 'active',
    created_at    TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS game_accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id       INTEGER NOT NULL,
    game            TEXT NOT NULL,
    game_username   TEXT NOT NULL,
    game_password   TEXT NOT NULL,
    external_id     TEXT DEFAULT '',
    balance         REAL DEFAULT 0.0,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (player_id) REFERENCES players(id)
);
CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER,
    username    TEXT,
    type        TEXT NOT NULL,
    amount      REAL DEFAULT 0.0,
    method      TEXT DEFAULT '',
    status      TEXT DEFAULT 'pending',
    notes       TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (player_id) REFERENCES players(id)
);
CREATE TABLE IF NOT EXISTS deposit_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER,
    username    TEXT,
    amount      REAL NOT NULL,
    method      TEXT NOT NULL,
    status      TEXT DEFAULT 'pending',
    notes       TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (player_id) REFERENCES players(id)
);
CREATE TABLE IF NOT EXISTS withdrawal_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER,
    username    TEXT,
    amount      REAL NOT NULL,
    method      TEXT NOT NULL,
    address     TEXT DEFAULT '',
    status      TEXT DEFAULT 'pending',
    notes       TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (player_id) REFERENCES players(id)
);
CREATE TABLE IF NOT EXISTS support_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER,
    username    TEXT NOT NULL,
    agent       TEXT NOT NULL DEFAULT 'BigWin Support',
    sender      TEXT NOT NULL,
    message     TEXT NOT NULL,
    is_read     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS roulette_prizes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    label      TEXT NOT NULL,
    color      TEXT NOT NULL DEFAULT '#6366f1',
    text_color TEXT NOT NULL DEFAULT '#fff',
    weight     INTEGER NOT NULL DEFAULT 10,
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled    INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS roulette_spins (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER,
    username    TEXT NOT NULL,
    prize_id    INTEGER,
    prize_label TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS player_bonuses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER,
    username    TEXT NOT NULL,
    type        TEXT NOT NULL,
    value       REAL NOT NULL DEFAULT 0,
    label       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    source      TEXT NOT NULL DEFAULT 'roulette',
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS marketplace_tiers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tier_label  TEXT NOT NULL,
    name        TEXT NOT NULL,
    fp_cost     INTEGER NOT NULL,
    cash_value  TEXT NOT NULL,
    badge       TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS marketplace_redemptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER,
    username    TEXT NOT NULL,
    tier_id     INTEGER,
    tier_name   TEXT NOT NULL,
    fp_spent    INTEGER NOT NULL,
    cash_value  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS referrals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id         INTEGER NOT NULL,
    referrer_username   TEXT NOT NULL,
    referred_id         INTEGER NOT NULL,
    referred_username   TEXT NOT NULL,
    fp_referrer         REAL NOT NULL DEFAULT 10,
    fp_referred         REAL NOT NULL DEFAULT 5,
    created_at          TEXT DEFAULT (datetime('now'))
);
"""

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS backends (
    id          SERIAL PRIMARY KEY,
    game        TEXT NOT NULL,
    name        TEXT NOT NULL,
    username    TEXT NOT NULL,
    password    TEXT NOT NULL,
    token       TEXT DEFAULT '',
    base_url    TEXT DEFAULT '',
    status      TEXT DEFAULT 'unknown',
    enabled     INTEGER NOT NULL DEFAULT 1,
    balance     REAL DEFAULT 0,
    loadstar_under TEXT DEFAULT '',
    last_tested TEXT DEFAULT '',
    created_at  TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
CREATE TABLE IF NOT EXISTS players (
    id            SERIAL PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    email         TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    balance       REAL DEFAULT 0.0,
    fp_credits    REAL DEFAULT 1.0,
    phone         TEXT DEFAULT '',
    phone_verified INTEGER NOT NULL DEFAULT 0,
    referral_code TEXT DEFAULT '',
    status        TEXT DEFAULT 'active',
    created_at    TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
CREATE TABLE IF NOT EXISTS game_accounts (
    id              SERIAL PRIMARY KEY,
    player_id       INTEGER NOT NULL,
    game            TEXT NOT NULL,
    game_username   TEXT NOT NULL,
    game_password   TEXT NOT NULL,
    external_id     TEXT DEFAULT '',
    balance         REAL DEFAULT 0.0,
    created_at      TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
CREATE TABLE IF NOT EXISTS transactions (
    id          SERIAL PRIMARY KEY,
    player_id   INTEGER,
    username    TEXT,
    type        TEXT NOT NULL,
    amount      REAL DEFAULT 0.0,
    method      TEXT DEFAULT '',
    status      TEXT DEFAULT 'pending',
    notes       TEXT DEFAULT '',
    created_at  TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
CREATE TABLE IF NOT EXISTS deposit_requests (
    id          SERIAL PRIMARY KEY,
    player_id   INTEGER,
    username    TEXT,
    amount      REAL NOT NULL,
    method      TEXT NOT NULL,
    status      TEXT DEFAULT 'pending',
    notes       TEXT DEFAULT '',
    created_at  TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
CREATE TABLE IF NOT EXISTS withdrawal_requests (
    id          SERIAL PRIMARY KEY,
    player_id   INTEGER,
    username    TEXT,
    amount      REAL NOT NULL,
    method      TEXT NOT NULL,
    address     TEXT DEFAULT '',
    status      TEXT DEFAULT 'pending',
    notes       TEXT DEFAULT '',
    created_at  TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
CREATE TABLE IF NOT EXISTS support_messages (
    id          SERIAL PRIMARY KEY,
    player_id   INTEGER,
    username    TEXT NOT NULL,
    agent       TEXT NOT NULL DEFAULT 'BigWin Support',
    sender      TEXT NOT NULL,
    message     TEXT NOT NULL,
    is_read     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
CREATE TABLE IF NOT EXISTS roulette_prizes (
    id         SERIAL PRIMARY KEY,
    label      TEXT NOT NULL,
    color      TEXT NOT NULL DEFAULT '#6366f1',
    text_color TEXT NOT NULL DEFAULT '#fff',
    weight     INTEGER NOT NULL DEFAULT 10,
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled    INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS roulette_spins (
    id          SERIAL PRIMARY KEY,
    player_id   INTEGER,
    username    TEXT NOT NULL,
    prize_id    INTEGER,
    prize_label TEXT NOT NULL,
    created_at  TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
CREATE TABLE IF NOT EXISTS player_bonuses (
    id          SERIAL PRIMARY KEY,
    player_id   INTEGER,
    username    TEXT NOT NULL,
    type        TEXT NOT NULL,
    value       REAL NOT NULL DEFAULT 0,
    label       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    source      TEXT NOT NULL DEFAULT 'roulette',
    created_at  TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
CREATE TABLE IF NOT EXISTS marketplace_tiers (
    id          SERIAL PRIMARY KEY,
    tier_label  TEXT NOT NULL,
    name        TEXT NOT NULL,
    fp_cost     INTEGER NOT NULL,
    cash_value  TEXT NOT NULL,
    badge       TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS marketplace_redemptions (
    id          SERIAL PRIMARY KEY,
    player_id   INTEGER,
    username    TEXT NOT NULL,
    tier_id     INTEGER,
    tier_name   TEXT NOT NULL,
    fp_spent    INTEGER NOT NULL,
    cash_value  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
CREATE TABLE IF NOT EXISTS referrals (
    id                  SERIAL PRIMARY KEY,
    referrer_id         INTEGER NOT NULL,
    referrer_username   TEXT NOT NULL,
    referred_id         INTEGER NOT NULL,
    referred_username   TEXT NOT NULL,
    fp_referrer         REAL NOT NULL DEFAULT 10,
    fp_referred         REAL NOT NULL DEFAULT 5,
    created_at          TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
"""


class _Cursor:
    """Unified cursor: works like sqlite3 cursor, lastrowid always populated."""
    def __init__(self, cur, is_pg=False, is_insert=False):
        self._cur = cur
        self._is_pg = is_pg
        self.rowcount = cur.rowcount
        self.lastrowid = None
        if is_pg and is_insert:
            try:
                row = cur.fetchone()
                if row:
                    self.lastrowid = row.get('id') or row.get(list(row.keys())[0])
            except Exception:
                pass
        elif not is_pg:
            self.lastrowid = cur.lastrowid

    def fetchone(self):
        row = self._cur.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(r) for r in (self._cur.fetchall() or [])]


class DB:
    """Unified DB connection for SQLite and PostgreSQL."""

    def __init__(self):
        if USE_PG:
            import psycopg2, psycopg2.extras
            self._conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
            self._is_pg = True
        else:
            self._conn = sqlite3.connect(DB_PATH)
            self._conn.row_factory = sqlite3.Row
            self._is_pg = False

    _has_id_cache = {}   # Postgres table → has an "id" column (looked up once per table per process)

    def _has_id(self, table):
        if table not in DB._has_id_cache:
            cur = self._conn.cursor()
            cur.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
                        "AND table_name = %s AND column_name = 'id'", (table,))
            DB._has_id_cache[table] = cur.fetchone() is not None
        return DB._has_id_cache[table]

    def execute(self, sql, params=()):
        sql_run = sql.replace('?', '%s') if self._is_pg else sql
        is_insert = sql_run.strip().upper().startswith('INSERT')
        if self._is_pg and is_insert and 'RETURNING' not in sql_run.upper():
            # lastrowid needs RETURNING id — but only tables with an id column have one
            # (email_codes, phone_otps, site_settings, payment_methods… don't, and failed every insert)
            m = re.match(r'\s*INSERT\s+INTO\s+"?(\w+)"?', sql_run, re.I)
            if m and self._has_id(m.group(1).lower()):
                sql_run = sql_run.rstrip().rstrip(';') + ' RETURNING id'
            else:
                is_insert = False   # nothing to fetch for lastrowid
        cur = self._conn.cursor()
        cur.execute(sql_run, params)
        return _Cursor(cur, self._is_pg, is_insert=is_insert)

    def executescript(self, sql):
        if self._is_pg:
            cur = self._conn.cursor()
            for stmt in sql.split(';'):
                s = stmt.strip()
                if s:
                    try:
                        cur.execute(s)
                    except Exception:
                        self._conn.rollback()
            self._conn.commit()
        else:
            self._conn.executescript(sql)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_db():
    return DB()


def rows_to_list(rows):
    return [dict(r) for r in rows] if rows else []


def init_db():
    db = get_db()
    schema = SCHEMA_PG if USE_PG else SCHEMA_SQLITE

    if USE_PG:
        cur = db._conn.cursor()
        for stmt in schema.split(';'):
            s = stmt.strip()
            if s:
                try:
                    cur.execute(s)
                    db._conn.commit()
                except Exception:
                    db._conn.rollback()
        # Migrations
        for migration in [
            "ALTER TABLE game_accounts ADD COLUMN IF NOT EXISTS external_id TEXT DEFAULT ''",
            "ALTER TABLE backends ADD COLUMN IF NOT EXISTS enabled INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE backends ADD COLUMN IF NOT EXISTS loadstar_under TEXT DEFAULT ''",
            """CREATE TABLE IF NOT EXISTS telegram_support_links (
                id SERIAL PRIMARY KEY, chat_id TEXT NOT NULL, message_id BIGINT NOT NULL,
                player_id INTEGER, username TEXT NOT NULL, agent TEXT NOT NULL,
                created_at TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))""",
            "CREATE INDEX IF NOT EXISTS tg_links_msg ON telegram_support_links (chat_id, message_id)",
            """CREATE TABLE IF NOT EXISTS phone_otps (
                username TEXT PRIMARY KEY, phone TEXT NOT NULL, code_hash TEXT NOT NULL,
                expires INTEGER NOT NULL, tries INTEGER NOT NULL DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS email_codes (
                key TEXT PRIMARY KEY, username TEXT NOT NULL, purpose TEXT NOT NULL, email TEXT NOT NULL,
                code_hash TEXT NOT NULL, expires INTEGER NOT NULL, tries INTEGER NOT NULL DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS support_messages (
                id SERIAL PRIMARY KEY, player_id INTEGER, username TEXT NOT NULL,
                agent TEXT NOT NULL DEFAULT 'BigWin Support', sender TEXT NOT NULL,
                message TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))""",
            """CREATE TABLE IF NOT EXISTS roulette_prizes (
                id SERIAL PRIMARY KEY, label TEXT NOT NULL,
                color TEXT NOT NULL DEFAULT '#6366f1', text_color TEXT NOT NULL DEFAULT '#fff',
                weight INTEGER NOT NULL DEFAULT 10, sort_order INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS roulette_spins (
                id SERIAL PRIMARY KEY, player_id INTEGER, username TEXT NOT NULL,
                prize_id INTEGER, prize_label TEXT NOT NULL,
                created_at TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))""",
            """CREATE TABLE IF NOT EXISTS player_bonuses (
                id SERIAL PRIMARY KEY, player_id INTEGER, username TEXT NOT NULL,
                type TEXT NOT NULL, value REAL NOT NULL DEFAULT 0, label TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', source TEXT NOT NULL DEFAULT 'roulette',
                created_at TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))""",
            """CREATE TABLE IF NOT EXISTS marketplace_tiers (
                id SERIAL PRIMARY KEY, tier_label TEXT NOT NULL, name TEXT NOT NULL,
                fp_cost INTEGER NOT NULL, cash_value TEXT NOT NULL,
                badge TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS marketplace_redemptions (
                id SERIAL PRIMARY KEY, player_id INTEGER, username TEXT NOT NULL,
                tier_id INTEGER, tier_name TEXT NOT NULL, fp_spent INTEGER NOT NULL,
                cash_value TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))""",
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS phone TEXT DEFAULT ''",
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS phone_verified INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS email_verified INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS referral_code TEXT DEFAULT ''",
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS first_name TEXT DEFAULT ''",
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS last_name TEXT DEFAULT ''",
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS referred_by_name TEXT DEFAULT ''",
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS google_uid TEXT DEFAULT ''",
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS avatar TEXT DEFAULT ''",
            """CREATE TABLE IF NOT EXISTS link_requests (
                id SERIAL PRIMARY KEY, player_id INTEGER NOT NULL, username TEXT NOT NULL,
                game TEXT NOT NULL, game_username TEXT NOT NULL, status TEXT DEFAULT 'pending',
                handled_by TEXT DEFAULT '', note TEXT DEFAULT '', handled_at TEXT DEFAULT '',
                created_at TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))""",
            """CREATE TABLE IF NOT EXISTS load_requests (
                id SERIAL PRIMARY KEY, player_id INTEGER, username TEXT NOT NULL,
                game TEXT NOT NULL, game_username TEXT DEFAULT '', amount REAL NOT NULL,
                method TEXT DEFAULT '', screenshot TEXT DEFAULT '', status TEXT DEFAULT 'pending',
                agent TEXT DEFAULT '', handled_by TEXT DEFAULT '', note TEXT DEFAULT '', handled_at TEXT DEFAULT '',
                created_at TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))""",
            "ALTER TABLE deposit_requests ADD COLUMN IF NOT EXISTS payment_url TEXT DEFAULT ''",
            "ALTER TABLE deposit_requests ADD COLUMN IF NOT EXISTS keyhub_token TEXT DEFAULT ''",
            "ALTER TABLE deposit_requests ADD COLUMN IF NOT EXISTS screenshot TEXT DEFAULT ''",
            "ALTER TABLE deposit_requests ADD COLUMN IF NOT EXISTS load_game TEXT DEFAULT ''",
            "ALTER TABLE deposit_requests ADD COLUMN IF NOT EXISTS load_amount REAL DEFAULT 0",
            "ALTER TABLE deposit_requests ADD COLUMN IF NOT EXISTS load_status TEXT DEFAULT ''",
            "ALTER TABLE withdrawal_requests ADD COLUMN IF NOT EXISTS payout_url TEXT DEFAULT ''",
            "ALTER TABLE withdrawal_requests ADD COLUMN IF NOT EXISTS keyhub_token TEXT DEFAULT ''",
            """CREATE TABLE IF NOT EXISTS referrals (
                id SERIAL PRIMARY KEY, referrer_id INTEGER NOT NULL,
                referrer_username TEXT NOT NULL, referred_id INTEGER NOT NULL,
                referred_username TEXT NOT NULL,
                fp_referrer REAL NOT NULL DEFAULT 10, fp_referred REAL NOT NULL DEFAULT 5,
                created_at TEXT DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))""",
            """CREATE TABLE IF NOT EXISTS site_settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')""",
            """CREATE TABLE IF NOT EXISTS payment_methods (
                key TEXT PRIMARY KEY, name TEXT NOT NULL, icon TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1, address TEXT NOT NULL DEFAULT '',
                qr_image TEXT NOT NULL DEFAULT '', payment_link TEXT NOT NULL DEFAULT '',
                instructions TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS support_agents (
                id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                icon TEXT NOT NULL DEFAULT '🎧', color TEXT NOT NULL DEFAULT '#6366f1',
                password_hash TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0)""",
            "ALTER TABLE support_agents ADD COLUMN last_heartbeat DOUBLE PRECISION DEFAULT NULL",
            "ALTER TABLE withdrawal_requests ADD COLUMN tip_amount DOUBLE PRECISION NOT NULL DEFAULT 0",
        ]:
            try:
                cur.execute(migration)
                db._conn.commit()
            except Exception:
                db._conn.rollback()
        _seed_prizes(db)
        _seed_tiers(db)
        _seed_payment_methods(db)
        _seed_support_agents(db)
        _widen_money_columns(db)
        print("[DB] PostgreSQL initialized")
    else:
        db._conn.executescript(schema)
        for migration in [
            "ALTER TABLE game_accounts ADD COLUMN external_id TEXT DEFAULT ''",
            "ALTER TABLE backends ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE backends ADD COLUMN loadstar_under TEXT DEFAULT ''",
            """CREATE TABLE IF NOT EXISTS telegram_support_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, message_id INTEGER NOT NULL,
                player_id INTEGER, username TEXT NOT NULL, agent TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')))""",
            "CREATE INDEX IF NOT EXISTS tg_links_msg ON telegram_support_links (chat_id, message_id)",
            """CREATE TABLE IF NOT EXISTS phone_otps (
                username TEXT PRIMARY KEY, phone TEXT NOT NULL, code_hash TEXT NOT NULL,
                expires INTEGER NOT NULL, tries INTEGER NOT NULL DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS email_codes (
                key TEXT PRIMARY KEY, username TEXT NOT NULL, purpose TEXT NOT NULL, email TEXT NOT NULL,
                code_hash TEXT NOT NULL, expires INTEGER NOT NULL, tries INTEGER NOT NULL DEFAULT 0)""",
            "ALTER TABLE players ADD COLUMN phone TEXT DEFAULT ''",
            "ALTER TABLE players ADD COLUMN phone_verified INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE players ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE players ADD COLUMN referral_code TEXT DEFAULT ''",
            "ALTER TABLE players ADD COLUMN first_name TEXT DEFAULT ''",
            "ALTER TABLE players ADD COLUMN last_name TEXT DEFAULT ''",
            "ALTER TABLE players ADD COLUMN referred_by_name TEXT DEFAULT ''",
            "ALTER TABLE players ADD COLUMN google_uid TEXT DEFAULT ''",
            "ALTER TABLE players ADD COLUMN avatar TEXT DEFAULT ''",
            """CREATE TABLE IF NOT EXISTS link_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL, username TEXT NOT NULL,
                game TEXT NOT NULL, game_username TEXT NOT NULL, status TEXT DEFAULT 'pending',
                handled_by TEXT DEFAULT '', note TEXT DEFAULT '', handled_at TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')))""",
            """CREATE TABLE IF NOT EXISTS load_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER, username TEXT NOT NULL,
                game TEXT NOT NULL, game_username TEXT DEFAULT '', amount REAL NOT NULL,
                method TEXT DEFAULT '', screenshot TEXT DEFAULT '', status TEXT DEFAULT 'pending',
                agent TEXT DEFAULT '', handled_by TEXT DEFAULT '', note TEXT DEFAULT '', handled_at TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')))""",
            "ALTER TABLE deposit_requests ADD COLUMN payment_url TEXT DEFAULT ''",
            "ALTER TABLE deposit_requests ADD COLUMN keyhub_token TEXT DEFAULT ''",
            "ALTER TABLE deposit_requests ADD COLUMN screenshot TEXT DEFAULT ''",
            "ALTER TABLE deposit_requests ADD COLUMN load_game TEXT DEFAULT ''",
            "ALTER TABLE deposit_requests ADD COLUMN load_amount REAL DEFAULT 0",
            "ALTER TABLE deposit_requests ADD COLUMN load_status TEXT DEFAULT ''",
            "ALTER TABLE withdrawal_requests ADD COLUMN payout_url TEXT DEFAULT ''",
            "ALTER TABLE withdrawal_requests ADD COLUMN keyhub_token TEXT DEFAULT ''",
            "CREATE TABLE IF NOT EXISTS site_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')",
            """CREATE TABLE IF NOT EXISTS payment_methods (
                key TEXT PRIMARY KEY, name TEXT NOT NULL, icon TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1, address TEXT NOT NULL DEFAULT '',
                qr_image TEXT NOT NULL DEFAULT '', payment_link TEXT NOT NULL DEFAULT '',
                instructions TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS support_agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL, icon TEXT NOT NULL DEFAULT '🎧',
                color TEXT NOT NULL DEFAULT '#6366f1',
                password_hash TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0)""",
            "ALTER TABLE support_agents ADD COLUMN last_heartbeat REAL DEFAULT NULL",
            "ALTER TABLE withdrawal_requests ADD COLUMN tip_amount REAL NOT NULL DEFAULT 0",
        ]:
            try:
                db._conn.execute(migration)
                db._conn.commit()
            except Exception:
                pass
        try:
            db._conn.execute("UPDATE backends SET base_url='' WHERE game='ultrapanda' AND base_url LIKE '%ultrapanda.me%'")
            db._conn.execute("UPDATE backends SET base_url=SUBSTR(base_url, 1, INSTR(base_url,'#')-1) WHERE INSTR(base_url,'#')>0")
            db._conn.commit()
        except Exception:
            pass
        _seed_prizes(db)
        _seed_tiers(db)
        _seed_payment_methods(db)
        _seed_support_agents(db)
        print(f"[DB] SQLite initialized: {DB_PATH}")

    db.close()


_DEFAULT_PRIZES = [
    ('1 WZ Free Play',   '#ef4444', '#fff', 22, 0),
    ('2 WZ Free Play',   '#f97316', '#fff', 18, 1),
    ('3 WZ Free Play',   '#22c55e', '#fff', 14, 2),
    ('5 WZ Free Play',   '#06b6d4', '#fff', 10, 3),
    ('5% Deposit',    '#8b5cf6', '#fff',  8, 4),
    ('10% Deposit',   '#ec4899', '#fff',  7, 5),
    ('Free Spins',    '#84cc16', '#111',  6, 6),
    ('VIP Points',    '#f59e0b', '#111',  5, 7),
    ('Mystery Bonus', '#6366f1', '#fff',  4, 8),
    ('25 WZ Free Play',  '#eab308', '#111',  1, 9),
    ('Deposit Bonus', '#14b8a6', '#fff',  5, 10),
]

def _widen_money_columns(db):
    """Postgres REAL is single precision ($19.99 was stored as 19.9899998). Switch every REAL column to
    full precision, rounding what is there to the cent. Runs once: afterwards there are no REAL columns."""
    try:
        cur = db._conn.cursor()
        cur.execute("SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND data_type = 'real'")
        cols = [(r['table_name'], r['column_name']) for r in cur.fetchall()]
    except Exception:
        db._conn.rollback()
        return
    for table, col in cols:
        try:
            cur = db._conn.cursor()
            cur.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{col}" TYPE DOUBLE PRECISION '
                        f'USING round("{col}"::double precision::numeric, 2)::double precision')   # via float8: exact
            db._conn.commit()
            print(f"[DB] {table}.{col}: REAL → DOUBLE PRECISION (rounded to the cent)")
        except Exception as e:
            db._conn.rollback()   # e.g. the other worker is doing it at the same moment
            print(f"[DB] {table}.{col}: not widened ({e})")


_OLD_PRIZE_LABELS = {'$1 Freeplay': '1 WZ Free Play', '$2 Freeplay': '2 WZ Free Play', '$3 Freeplay': '3 WZ Free Play',
                     '$5 Freeplay': '5 WZ Free Play', '$25 Freeplay': '25 WZ Free Play'}

def _seed_prizes(db):
    # Free Play is points (WZ), not dollars: rename the old default wheel labels once
    try:
        for old_label, new_label in _OLD_PRIZE_LABELS.items():
            db.execute('UPDATE roulette_prizes SET label=? WHERE label=?', (new_label, old_label))
        db.commit()
    except Exception:
        try:
            db._conn.rollback()
        except Exception:
            pass
    try:
        existing = db.execute('SELECT COUNT(*) as n FROM roulette_prizes').fetchone()
        if existing and existing.get('n', 0) == 0:
            for (label, color, text_color, weight, sort_order) in _DEFAULT_PRIZES:
                db.execute(
                    'INSERT INTO roulette_prizes (label, color, text_color, weight, sort_order) VALUES (?,?,?,?,?)',
                    (label, color, text_color, weight, sort_order)
                )
            db.commit()
    except Exception:
        pass


_DEFAULT_TIERS = [
    ('STARTER · TIER 1', 'Quick Cash',    100,   '$20',    '',      0),
    ('STARTER · TIER 2', 'Mini Vault',    250,   '$50',    '',      1),
    ('MID · TIER 3',     'Lucky Stack',   500,   '$100',   '',      2),
    ('MID · TIER 4',     'Gold Vault',    1000,  '$200',   '',      3),
    ('HIGH · TIER 5',    'Royal Vault',   2500,  '$500',   '',      4),
    ('HIGH · TIER 6',    'Elite Cashout', 5000,  '$1,000', '',      5),
    ('WHALE · TIER 7',   'Whale Vault',   10000, '$2,000', 'whale', 6),
]

def _seed_tiers(db):
    try:
        existing = db.execute('SELECT COUNT(*) as n FROM marketplace_tiers').fetchone()
        if existing and existing.get('n', 0) == 0:
            for (tier_label, name, fp_cost, cash_value, badge, sort_order) in _DEFAULT_TIERS:
                db.execute(
                    'INSERT INTO marketplace_tiers (tier_label, name, fp_cost, cash_value, badge, sort_order) VALUES (?,?,?,?,?,?)',
                    (tier_label, name, fp_cost, cash_value, badge, sort_order)
                )
            db.commit()
    except Exception:
        pass


_DEFAULT_PAYMENT_METHODS = [
    ('cashapp', 'Cash App',  '💵', 1, '', '', '', '', 0),
    ('bitcoin', 'Bitcoin',   '₿',  1, '', '', '', '', 1),
    ('zelle',   'Zelle',     '🏦', 1, '', '', '', '', 2),
    ('usdt',    'USDT',      '💠', 1, '', '', '', '', 3),
]

def _seed_payment_methods(db):
    try:
        existing = db.execute('SELECT COUNT(*) as n FROM payment_methods').fetchone()
        if existing and existing.get('n', 0) == 0:
            for (key, name, icon, enabled, address, qr_image, payment_link, instructions, sort_order) in _DEFAULT_PAYMENT_METHODS:
                db.execute(
                    'INSERT INTO payment_methods (key,name,icon,enabled,address,qr_image,payment_link,instructions,sort_order) VALUES (?,?,?,?,?,?,?,?,?)',
                    (key, name, icon, enabled, address, qr_image, payment_link, instructions, sort_order)
                )
            db.commit()
    except Exception:
        pass


_DEFAULT_SUPPORT_AGENTS = [
    ("BigWin Support", '♛', '#7c3aed', 0),
    ('Nicky',           '👩', '#db2777', 1),
    ('Brody',           '👨', '#2563eb', 2),
]

_OLD_SUPPORT_NAMES = ("Leo's Playhouse Support", 'Fortune Support')

def _rename_support_agent(db):
    """Rebrand: move the old protected agent and its chats to the new name, once."""
    new = _DEFAULT_SUPPORT_AGENTS[0][0]
    for old in _OLD_SUPPORT_NAMES:
        try:
            if not db.execute('SELECT id FROM support_agents WHERE name=?', (new,)).fetchone():
                db.execute('UPDATE support_agents SET name=? WHERE name=?', (new, old))
            else:
                db.execute('UPDATE support_agents SET active=0 WHERE name=?', (old,))
            db.execute('UPDATE support_messages SET agent=? WHERE agent=?', (new, old))
            try:
                db.execute('UPDATE telegram_support_links SET agent=? WHERE agent=?', (new, old))
            except Exception:
                pass
            db.commit()
        except Exception:
            try:
                db._conn.rollback()
            except Exception:
                pass


def _seed_support_agents(db):
    _rename_support_agent(db)
    try:
        # Always ensure BigWin Support exists — it's the protected default agent
        existing = db.execute('SELECT id FROM support_agents WHERE name=?', ("BigWin Support",)).fetchone()
        if not existing:
            db.execute(
                'INSERT INTO support_agents (name,icon,color,active,sort_order) VALUES (?,?,?,1,?)',
                ("BigWin Support", '♛', '#7c3aed', 0)
            )
            db.commit()
        else:
            # Make sure it's always active
            db.execute("UPDATE support_agents SET active=1 WHERE name=?", ("BigWin Support",))
            db.commit()

        # Seed extra default agents only if table was empty before (first-run only)
        total = db.execute('SELECT COUNT(*) as n FROM support_agents').fetchone()
        if total and total.get('n', 0) <= 1:
            for (name, icon, color, sort_order) in _DEFAULT_SUPPORT_AGENTS[1:]:
                try:
                    db.execute(
                        'INSERT INTO support_agents (name,icon,color,active,sort_order) VALUES (?,?,?,1,?)',
                        (name, icon, color, sort_order)
                    )
                except Exception:
                    pass
            db.commit()
    except Exception:
        pass
