"""
Euana - Single File (Render Ready)
- Register / Login
- Bank transfer / Crypto payment
- Credit system
- Server-side obfuscation + dashboard result
- Multiple obfuscation options
"""

from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import List
import secrets
import hashlib
import uuid
import re
import html as html_lib
import os
import random
import string

# ======================
# Config
# ======================

APP_NAME = "Euana"
VERSION = "1.0.0"

# Pricing: 3 credits = 1 obfuscation, ~1500 KRW for 3 credits
CREDITS_PER_OBFUSCATION = 3
KRW_PER_3_CREDITS = 1500

CRYPTO_INFO = {
    "network": "LTC",
    "currency": "LTC",
    "address": "ltc1qtu5cwhmqjjdnkjk5p8ar2quyke6g7xr2re0qpk",  # set your Litecoin address
}

# Admin
ADMIN_USERNAME = "kimsiwoo"
ADMIN_PASSWORD = "kimsiwoo"

# v1 / v2 both cost 3 credits; v2 uses stronger pipeline
BASE_COST = {
    "v1": 3,
    "v2": 3,
}

OPTION_COST = {}  # options baked into v1/v2

# ======================
# Database (PostgreSQL via DATABASE_URL)
# ======================
import json
import psycopg2
import psycopg2.extras
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

DATABASE_URL = (
    os.environ.get("DATABASE_URL")
    or os.environ.get("DB_URL")
    or os.environ.get("POSTGRES_URL")
    or os.environ.get("POSTGRESQL_URL")
)

_db_ready = False


def _normalize_db_url(url: str) -> str:
    """Render gives postgres://; psycopg2 wants postgresql:// and usually sslmode=require."""
    if not url:
        return url
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    # ensure sslmode=require (Render external + most hosted PG)
    try:
        parts = urlparse(url)
        q = parse_qs(parts.query)
        if "sslmode" not in q:
            q["sslmode"] = ["require"]
        new_query = urlencode({k: v[0] for k, v in q.items()})
        url = urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))
    except Exception:
        if "sslmode=" not in url:
            url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


class _DBConn:
    """Thin wrapper so conn.execute(...).fetchone() style works with psycopg2."""
    def __init__(self, conn):
        self._conn = conn
        self._cur = conn.cursor()

    def execute(self, sql, params=None):
        if params is not None and "?" in sql:
            sql = sql.replace("?", "%s")
        self._cur.execute(sql, params or ())
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            pass

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass


def get_db():
    """Always uses managed PostgreSQL (DATABASE_URL). Data survives web service restarts."""
    global _db_ready
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Render → Web Service → Environment → add DATABASE_URL from your PostgreSQL instance "
            "(Internal Database URL). Local file DB is NOT used — data would be lost on restart."
        )
    url = _normalize_db_url(DATABASE_URL)
    try:
        raw = psycopg2.connect(
            url,
            cursor_factory=psycopg2.extras.RealDictCursor,
            connect_timeout=15,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
        )
    except Exception as e:
        raise RuntimeError(
            f"Cannot connect to PostgreSQL. Check DATABASE_URL. Detail: {e}"
        ) from e
    conn = _DBConn(raw)
    if not _db_ready:
        try:
            _init_db_on(conn)
            _db_ready = True
        except Exception as e:
            conn.rollback()
            conn.close()
            raise RuntimeError(f"DB init failed: {e}") from e
    return conn


def _init_db_on(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            credits INTEGER NOT NULL DEFAULT 0,
            results TEXT DEFAULT '{}',
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_sessions (
            token TEXT PRIMARY KEY,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            payment_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            method TEXT,
            amount INTEGER,
            credits INTEGER,
            krw_value DOUBLE PRECISION,
            status TEXT DEFAULT 'pending',
            depositor_name TEXT,
            tx_hash TEXT,
            created_at TEXT,
            submitted_at TEXT,
            approved_at TEXT,
            rejected_at TEXT,
            approved_by TEXT
        )
    """)
    conn.commit()


def init_db():
    conn = get_db()
    conn.close()


# Try early init (non-fatal if DB not ready yet at import)
if DATABASE_URL:
    try:
        init_db()
        print("[DB] connected and tables ready")
    except Exception as e:
        print(f"[DB] init at startup failed (will retry on first request): {e}")

# ======================
# Language
# ======================

LANG = {
    "app_name": "Euana",
    "welcome": "Welcome to Euana",
    "register": "Sign Up",
    "login": "Login",
    "logout": "Logout",
    "username": "Username",
    "password": "Password",
    "balance": "Credit Balance",
    "charge": "Charge Credits",
    "obfuscate": "Obfuscate",
    "bank_transfer": "Bank Transfer",
    "crypto": "Crypto Payment",
    "select_amount": "Amount",
    "after_transfer": "After payment, enter depositor name or TxHash and confirm",
    "depositor_name": "Depositor Name",
    "tx_hash": "Transaction Hash (TxID)",
    "confirm_payment": "Submit Payment Proof",
    "insufficient_credit": "Insufficient credits. Please charge.",
    "obfuscate_success": "Obfuscation completed",
    "result": "Obfuscation Result",
    "copy": "Copy",
    "dashboard": "Dashboard",
    "code_placeholder": "Paste your Luau / Lua code here",
    "intensity": "Base Intensity",
    "basic": "Basic",
    "strong": "Strong",
    "extreme": "Extreme",
    "submit": "Run",
    "payment_submitted": "Payment proof submitted. Credits will be added after verification.",
    "already_exists": "Username already exists",
    "invalid_login": "Invalid username or password",
    "options": "Extra Options",
    "opt_rename": "Rename Variables / Functions",
    "opt_strings": "Encrypt Strings",
    "opt_cff": "Control Flow Flattening",
    "opt_dead": "Insert Dead Code",
    "opt_junk": "Insert Junk Code",
    "opt_tamper": "Anti-Tamper",
    "opt_minify": "Minify (remove comments/whitespace)",
    "opt_opaque": "Opaque Predicates",
    "opt_proxy": "Proxy Functions",
    "opt_numbers": "Encrypt Numbers",
}

def t(key: str, lang: str = "en") -> str:
    return LANG.get(key, key)

# ======================
# Helpers
# ======================

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def create_token() -> str:
    return secrets.token_hex(24)

def get_current_user(request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    conn = get_db()
    row = conn.execute("SELECT username FROM sessions WHERE token=?", (token,)).fetchone()
    if not row:
        conn.close()
        return None
    user_row = conn.execute("SELECT * FROM users WHERE username=?", (row["username"],)).fetchone()
    conn.close()
    if not user_row:
        return None
    user = dict(user_row)
    try:
        user["results"] = json.loads(user.get("results") or "{}")
    except Exception:
        user["results"] = {}
    return user

def save_user(user: dict):
    conn = get_db()
    conn.execute(
        "UPDATE users SET credits=?, results=? WHERE username=?",
        (user["credits"], json.dumps(user.get("results", {})), user["username"])
    )
    conn.commit()
    conn.close()

def calc_credits(amount: float, method: str = "ltc") -> int:
    # amount is credits to buy
    return max(3, int(amount))

def rand_name(length: int = 8) -> str:
    return "_" + "".join(random.choices(string.ascii_letters, k=length))


# ======================
# Obfuscation Engine (AntiLua-style VM)
# - setmetatable dispatch table
# - mixed hex/binary literals
# - control-flow state machine
# - multi-layer packing (no plain XOR string)
# - no recoverable source in output
# ======================

def _rand_ident(n: int = 8) -> str:
    # mix letter styles like commercial obfuscators
    if random.random() < 0.35:
        return "".join(random.choices(string.ascii_letters, k=n))
    return "_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _num(n: int, mask32: bool = False) -> str:
    """Emit integer in random base style (dec / hex / bin)."""
    n = int(n)
    if mask32:
        n = n & 0xFFFFFFFF
    if n < 0:
        n = n & 0xFFFFFFFF
    r = random.random()
    if 0 <= n < 16 and r < 0.35:
        return str(n)
    if r < 0.4:
        return hex(n)
    if r < 0.75 and n < (1 << 64):
        return "0b" + format(n, "b")
    return "0x" + format(n, "X")


def _pack_bytes(data: bytes, seed: int) -> list:
    """Pack bytes -> list of 32-bit ints with LCG keystream + position mix."""
    out = []
    state = seed & 0xFFFFFFFF
    i = 0
    while i < len(data):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        chunk = 0
        for b in range(4):
            if i + b < len(data):
                kb = (state >> (8 * b)) & 0xFF
                chunk |= ((data[i + b] ^ kb ^ ((i + b) & 0xFF)) & 0xFF) << (8 * b)
        out.append(chunk & 0xFFFFFFFF)
        i += 4
    return out


def _split_table(nums: list, size: int = None) -> list:
    size = size or random.randint(6, 14)
    return [nums[i:i + size] for i in range(0, len(nums), size)]


def _emit_number_table(nums: list) -> str:
    return "{" + ",".join(_num(x, mask32=True) for x in nums) + "}"


def _opaque_true() -> str:
    a = random.randint(2, 17)
    forms = [
        f"(function()local a={_num(a)}return a*a>={_num(0)}end)()",
        f"(function()local a={_num(a)}return(a+a)==(a*2)end)()",
        f"(function()local a={_num(a)}return not(a*a<0)end)()",
    ]
    return random.choice(forms)


def _opaque_false() -> str:
    a = random.randint(2, 17)
    return f"(function()local a={_num(a)}return a*a<{_num(0)}end)()"


def _junk_block() -> str:
    a, b = _rand_ident(4), _rand_ident(4)
    n1, n2 = random.randint(1, 99), random.randint(1, 99)
    return (
        f"do local {a}={_num(n1)};local {b}={_num(n2)};"
        f"if {a}*{a}<{_num(0)} then {b}={b}+{_num(1)} end end"
    )


def _emit_vm(src: str, intensity: str) -> str:
    """
    AntiLua-inspired wrapper:
    return setmetatable({ [handlers] }, { }):ENTRY()
    Handlers decode packed bytecode via state-machine CF, rebuild source, load+run.
    """
    raw = src.encode("utf-8")
    seed = random.randint(0x10000, 0x7FFFFFFF)
    packed = _pack_bytes(raw, seed)
    chunks = _split_table(packed)

    # names
    id_env = _rand_ident(3)
    id_entry = _rand_ident(2)  # method name on metatable
    id_bc = _rand_ident(4)
    id_buf = _rand_ident(4)
    id_key = _rand_ident(3)
    id_len = _rand_ident(3)
    id_i = _rand_ident(2)
    id_j = _rand_ident(2)
    id_t = _rand_ident(2)
    id_pc = _rand_ident(3)
    id_op = _rand_ident(3)
    id_run = _rand_ident(4)
    id_fn = _rand_ident(3)
    id_err = _rand_ident(3)
    id_st = _rand_ident(3)  # state for CF flatten
    id_acc = _rand_ident(3)
    id_bxor = _rand_ident(4)
    id_dec = _rand_ident(4)
    id_main = _rand_ident(4)

    # bytecode nested tables
    bc_parts = ",".join(_emit_number_table(c) for c in chunks)

    # state-machine states
    S_INIT, S_DECODE, S_BUILD, S_LOAD, S_RUN, S_DONE = 1, 2, 3, 4, 5, 6
    # shuffle display values
    states = [S_INIT, S_DECODE, S_BUILD, S_LOAD, S_RUN, S_DONE]
    random.shuffle(states)
    # map logical -> actual
    # keep sequential for correctness but express as opaque nums
    st_init = _num(1)
    st_decode = _num(2)
    st_build = _num(3)
    st_load = _num(4)
    st_run = _num(5)
    st_done = _num(6)

    junk1 = _junk_block()
    junk2 = _junk_block()
    ot = _opaque_true()

    # portable 3-way XOR for bytes (no bit32 required)
    bxor_fn = f"""local function {id_bxor}(x,y,z)
x=x%{_num(256)};y=y%{_num(256)};z=z%{_num(256)}
local r,p={_num(0)},{_num(1)}
for _=1,8 do
local bx,by,bz=x%{_num(2)},y%{_num(2)},z%{_num(2)}
r=r+((bx+by+bz)%{_num(2)})*p
x=math.floor(x/{_num(2)});y=math.floor(y/{_num(2)});z=math.floor(z/{_num(2)});p=p*{_num(2)}
end
return r
end"""

    # decoder for one u32 word into up to 4 bytes
    dec_fn = f"""local function {id_dec}(word,key,pos,out,olen)
key=(key*{_num(1664525)}+{_num(1013904223)})%{_num(4294967296)}
for a=0,3 do
if pos<olen then
local div={_num(1)}
for _=1,a do div=div*{_num(256)} end
local kb=math.floor(key/div)%{_num(256)}
local b=math.floor(word/div)%{_num(256)}
pos=pos+{_num(1)}
out[pos]={id_bxor}(b,kb,(pos-{_num(1)})%{_num(256)})
end
end
return key,pos
end"""

    # main body with CF flattening
    main_fn = f"""local function {id_main}()
local {id_bc}={{{bc_parts}}}
local {id_buf}={{}}
local {id_key}={_num(seed)}
local {id_len}={_num(len(raw))}
local {id_j}={_num(0)}
local {id_st}={st_init}
local {id_run},{id_fn},{id_err}
{junk1}
while {id_st}~={st_done} do
if {id_st}=={st_init} then
{junk2}
{id_st}={st_decode}
elseif {id_st}=={st_decode} then
local {id_i}={_num(1)}
while {id_i}<=#{id_bc} do
local {id_t}={id_bc}[{id_i}]
{id_i}={id_i}+{_num(1)}
if type({id_t})=="table" then
local {id_pc}={_num(1)}
while {id_pc}<=#{id_t} do
local {id_op}={id_t}[{id_pc}]
{id_pc}={id_pc}+{_num(1)}
{id_key},{id_j}={id_dec}({id_op},{id_key},{id_j},{id_buf},{id_len})
end
end
end
{id_st}={st_build}
elseif {id_st}=={st_build} then
{id_run}=""
for {id_i}=1,{id_len} do
{id_run}={id_run}..string.char({id_buf}[{id_i}])
end
{id_st}={st_load}
elseif {id_st}=={st_load} then
{id_fn},{id_err}=(load or loadstring)({id_run})
if not {id_fn} then error({id_err} or "load") end
{id_st}={st_run}
elseif {id_st}=={st_run} then
if {ot} then {id_fn}() end
{id_st}={st_done}
else
{id_st}={st_done}
end
end
end"""

    # setmetatable dispatch style (AntiLua-like surface)
    # handlers table with numeric keys in hex/bin
    k_main = random.randint(0x40, 0xFF)
    k_boot = random.randint(0x100, 0x3FF)

    handler_main = _num(k_main)
    handler_boot = _num(k_boot)

    # entry method name random short
    entry = random.choice(["B", "R", "X", "K", "Z", "Q"])

    vm = f"""return setmetatable({{
[{handler_main}]=function({id_env})
{bxor_fn}
{dec_fn}
{main_fn}
return {id_main}()
end,
[{handler_boot}]=function(self,...)
return self[{handler_main}](self,...)
end,
}},{{
__index=function(t,k)
if k=="{entry}" then return t[{handler_boot}] end
end
}}):{entry}(...)"""

    # single line minify for v2 outer; keep slightly readable structure for debug of engine
    if intensity == "v2":
        # compress whitespace
        vm = " ".join(vm.split())
        # but restore some newlines after certain keywords for Luau parser safety - actually one line is fine in Lua
    else:
        lines = [ln.rstrip() for ln in vm.splitlines() if ln.strip()]
        vm = "\n".join(lines)

    return vm


def obfuscate_code(code: str, intensity: str, options: List[str]) -> str:
    code = (code or "").strip()
    if not code:
        return "-- empty"

    if intensity not in ("v1", "v2"):
        intensity = "v2"

    cleaned = []
    for line in code.splitlines():
        s = line.strip()
        if s.startswith("--"):
            continue
        cleaned.append(line)
    src = "\n".join(cleaned)
    if not src.strip():
        src = code

    # v1: single VM layer (AntiLua-style surface)
    # v2: double layer + heavier junk / minified
    body = _emit_vm(src, intensity)
    if intensity == "v2":
        body = _emit_vm(body, "v2")

    header = (
        f"-- Protected using {APP_NAME} Obfuscator {VERSION}\n"
        f"-- {datetime.utcnow().strftime('%Y-%m-%d')} | {intensity}\n"
    )
    return header + body



def calc_cost(intensity: str, options: List[str] = None) -> int:
    return BASE_COST.get(intensity, CREDITS_PER_OBFUSCATION)

# ======================
# App
# ======================

app = FastAPI(title=APP_NAME, version=VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def base_html(content: str, lang: str = "en", user=None):
    balance = user["credits"] if user else 0
    username = user["username"] if user else ""
    nav_user = ""
    if user:
        nav_user = f"""
        <span class="muted" style="margin-left:16px">{username} · {balance} credits</span>
        <a href="/logout" class="btn btn-outline" style="margin-left:12px">{t('logout', lang)}</a>
        """
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{APP_NAME}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}}
.container{{max-width:980px;margin:0 auto;padding:24px}}
header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px;flex-wrap:wrap;gap:12px}}
h1{{font-size:1.55rem;color:#a5b4fc}}
.card{{background:#1e293b;border-radius:12px;padding:22px;margin-bottom:18px;border:1px solid #334155}}
input,select,textarea{{width:100%;padding:11px;margin:7px 0 14px;border-radius:8px;border:1px solid #475569;background:#0f172a;color:#e2e8f0;font-size:14px}}
textarea{{height:210px;font-family:monospace;resize:vertical}}
button,.btn{{display:inline-block;padding:11px 18px;border-radius:8px;border:none;background:#6366f1;color:white;font-weight:600;cursor:pointer;text-decoration:none;font-size:14px}}
button:hover,.btn:hover{{background:#4f46e5}}
.btn-outline{{background:transparent;border:1px solid #6366f1}}
.row{{display:flex;gap:12px;flex-wrap:wrap;align-items:center}}
.muted{{color:#94a3b8;font-size:13px}}
pre.result{{background:#020617;padding:16px;border-radius:8px;overflow-x:auto;white-space:pre-wrap;word-break:break-all;font-size:12.5px;border:1px solid #1e293b;max-height:430px;overflow-y:auto}}
.success{{color:#4ade80}}
.error{{color:#f87171}}
label{{font-size:13px;color:#94a3b8}}
.nav a{{margin-left:12px;color:#a5b4fc;text-decoration:none;font-size:14px}}
.opts{{display:grid;grid-template-columns:1fr 1fr;gap:8px 16px;margin:10px 0 16px}}
.opts label{{display:flex;align-items:center;gap:8px;color:#e2e8f0;font-size:13px;cursor:pointer}}
.opts input{{width:auto;margin:0}}
@media(max-width:600px){{.opts{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="container">
<header>
  <h1>{APP_NAME}</h1>
  <div class="nav">
    {nav_user}
  </div>
</header>
{content}
</div>
</body>
</html>"""

# ======================
# Routes
# ======================

@app.get("/db-check")
async def db_check():
    info = {
        "database_url_set": bool(DATABASE_URL),
        "database_url_prefix": (DATABASE_URL[:32] + "...") if DATABASE_URL else None,
        "persistent": True,
        "note": "PostgreSQL keeps users/credits/payments across web service restarts",
    }
    try:
        conn = get_db()
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        info["ok"] = True
        info["users"] = int(row["c"]) if row else 0
        # write+read probe so we know commits work
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _health (k TEXT PRIMARY KEY, v TEXT)"
        )
        conn.execute(
            "INSERT INTO _health (k, v) VALUES (%s, %s) ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v",
            ("ping", datetime.utcnow().isoformat()),
        )
        conn.commit()
        ping = conn.execute("SELECT v FROM _health WHERE k=%s", ("ping",)).fetchone()
        info["write_ok"] = bool(ping)
        conn.close()
    except Exception as e:
        info["ok"] = False
        info["error"] = str(e)
    return JSONResponse(info)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, lang: str = "en"):
    user = get_current_user(request)
    if user:
        return RedirectResponse(f"/dashboard?lang={lang}", status_code=302)
    content = f"""
    <div class="card">
        <h2>{t('welcome', lang)}</h2>
        <p class="muted" style="margin:12px 0 24px">Luau / Lua Obfuscator + Credit System</p>
        <div class="row">
            <a class="btn" href="/register?lang={lang}">{t('register', lang)}</a>
            <a class="btn btn-outline" href="/login?lang={lang}">{t('login', lang)}</a>
        </div>
    </div>"""
    return base_html(content, lang)

@app.get("/register", response_class=HTMLResponse)
async def register_page(lang: str = "en"):
    content = f"""
    <div class="card">
        <h2>{t('register', lang)}</h2>
        <form method="post" action="/register">
            <input type="hidden" name="lang" value="{lang}">
            <label>{t('username', lang)}</label>
            <input name="username" required minlength="3" maxlength="32" pattern="[a-zA-Z0-9_]+">
            <label>{t('password', lang)}</label>
            <input type="password" name="password" required minlength="4">
            <button type="submit">{t('register', lang)}</button>
        </form>
        <p class="muted" style="margin-top:16px"><a href="/login?lang={lang}" style="color:#a5b4fc">{t('login', lang)}</a></p>
    </div>"""
    return base_html(content, lang)

@app.post("/register")
async def register(username: str = Form(...), password: str = Form(...), lang: str = Form("en")):
    username = username.strip().lower()
    try:
        conn = get_db()
        exists = conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
        if exists:
            conn.close()
            content = f"""<div class="card"><p class="error">{t('already_exists', lang)}</p>
            <a class="btn" href="/register?lang={lang}">{t('register', lang)}</a></div>"""
            return HTMLResponse(base_html(content, lang))
        created = datetime.utcnow().isoformat()
        conn.execute(
            "INSERT INTO users (username, password, credits, results, created_at) VALUES (?,?,?,?,?)",
            (username, hash_password(password), 0, "{}", created)
        )
        token = create_token()
        conn.execute("INSERT INTO sessions (token, username, created_at) VALUES (?,?,?)", (token, username, created))
        conn.commit()
        conn.close()
    except Exception as e:
        content = f"""<div class="card"><p class="error">DB error: {html_lib.escape(str(e))}</p>
        <a class="btn" href="/register?lang={lang}">{t('register', lang)}</a></div>"""
        return HTMLResponse(base_html(content, lang))
    resp = RedirectResponse(f"/dashboard?lang={lang}", status_code=302)
    resp.set_cookie("session", token, httponly=True, max_age=60*60*24*30)
    return resp

@app.get("/login", response_class=HTMLResponse)
async def login_page(lang: str = "en"):
    content = f"""
    <div class="card">
        <h2>{t('login', lang)}</h2>
        <form method="post" action="/login">
            <input type="hidden" name="lang" value="{lang}">
            <label>{t('username', lang)}</label>
            <input name="username" required>
            <label>{t('password', lang)}</label>
            <input type="password" name="password" required>
            <button type="submit">{t('login', lang)}</button>
        </form>
        <p class="muted" style="margin-top:16px"><a href="/register?lang={lang}" style="color:#a5b4fc">{t('register', lang)}</a></p>
    </div>"""
    return base_html(content, lang)

@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...), lang: str = Form("en")):
    username = username.strip().lower()
    try:
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not user or user["password"] != hash_password(password):
            conn.close()
            content = f"""<div class="card"><p class="error">{t('invalid_login', lang)}</p>
            <a class="btn" href="/login?lang={lang}">{t('login', lang)}</a></div>"""
            return HTMLResponse(base_html(content, lang))
        token = create_token()
        conn.execute("INSERT INTO sessions (token, username, created_at) VALUES (?,?,?)", (token, username, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        content = f"""<div class="card"><p class="error">DB error: {html_lib.escape(str(e))}</p>
        <a class="btn" href="/login?lang={lang}">{t('login', lang)}</a></div>"""
        return HTMLResponse(base_html(content, lang))
    resp = RedirectResponse(f"/dashboard?lang={lang}", status_code=302)
    resp.set_cookie("session", token, httponly=True, max_age=60*60*24*30)
    return resp

@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session")
    if token:
        conn = get_db()
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie("session")
    return resp

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, lang: str = "en", result_id: str = None, error: str = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(f"/login?lang={lang}", status_code=302)

    result_block = ""
    if error:
        result_block = f"""<div class="card"><p class="error">{html_lib.escape(error)}</p></div>"""
    elif result_id and result_id in user.get("results", {}):
        safe = html_lib.escape(user["results"][result_id])
        result_block = f"""
        <div class="card">
            <h3 class="success">{t('obfuscate_success', lang)}</h3>
            <p class="muted">{t('result', lang)}</p>
            <pre class="result" id="obfResult">{safe}</pre>
            <div class="row" style="margin-top:12px">
                <button type="button" onclick="navigator.clipboard.writeText(document.getElementById('obfResult').innerText)">{t('copy', lang)}</button>
                <a class="btn" href="/download/{result_id}" style="margin-left:8px">Download .lua</a>
            </div>
        </div>"""

    content = f"""
    <div class="card">
        <h2>{t('dashboard', lang)}</h2>
        <p style="font-size:1.25rem;margin:10px 0">{t('balance', lang)}: <strong>{user['credits']}</strong></p>
    </div>
    {result_block}
        <div class="card">
        <h3>Obfuscate</h3>
        <p class="muted">3 credits = 1 run (~1500 KRW per 3 credits). Paste code or upload a .lua / .txt file.</p>
        <form method="post" action="/obfuscate" enctype="multipart/form-data">
            <input type="hidden" name="lang" value="{lang}">
            <label>Version</label>
            <select name="intensity">
                <option value="v1">Euana v1 (standard)</option>
                <option value="v2" selected>Euana v2 (upgraded + VM)</option>
            </select>
            <label>Code</label>
            <textarea name="code" placeholder="Paste Luau / Lua code here (optional if you upload a file)"></textarea>
            <label>Or upload file</label>
            <input type="file" name="file" accept=".lua,.luau,.txt,.text">
            <button type="submit">Obfuscate (3 credits)</button>
        </form>
    </div>
    <div class="card">
        <h3>Buy credits (Litecoin only)</h3>
        <p class="muted">Pay with LTC only. 3 credits ≈ 1500 KRW. Submit txid after payment for admin approval.</p>
        <form method="post" action="/charge">
            <input type="hidden" name="lang" value="{lang}">
            <input type="hidden" name="method" value="crypto">
            <label>Credits (multiples of 3)</label>
            <input type="number" name="credits_buy" value="3" min="3" step="3">
            <button type="submit">Get LTC address</button>
        </form>
    </div>
"""
    return base_html(content, lang, user)


@app.post("/obfuscate")
async def do_obfuscate(
    request: Request,
    code: str = Form(""),
    intensity: str = Form("v2"),
    lang: str = Form("en"),
    file: UploadFile = File(None),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(f"/login?lang={lang}", status_code=302)

    # File upload takes priority
    if file and file.filename:
        raw = await file.read()
        try:
            code = raw.decode("utf-8")
        except Exception:
            code = raw.decode("latin-1", errors="ignore")

    code = (code or "").strip()
    if len(code) < 5:
        return RedirectResponse(
            f"/dashboard?lang={lang}&error=Please paste code or upload a file",
            status_code=302
        )

    if intensity not in ("v1", "v2"):
        intensity = "v2"

    cost = CREDITS_PER_OBFUSCATION
    if user["credits"] < cost:
        return RedirectResponse(
            f"/dashboard?lang={lang}&error=Insufficient credits (need {cost})",
            status_code=302
        )

    user["credits"] -= cost
    result = obfuscate_code(code, intensity, [])

    result_id = str(uuid.uuid4())[:8]
    if "results" not in user:
        user["results"] = {}
    user["results"][result_id] = result
    save_user(user)

    

@app.get("/download/{result_id}")
async def download_result(request: Request, result_id: str):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    results = user.get("results") or {}
    content = results.get(result_id)
    if not content:
        return RedirectResponse("/dashboard?error=Result+not+found", status_code=302)
    filename = f"obfuscated_{result_id}.lua"
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/charge")
async def create_charge(
    request: Request,
    credits_buy: int = Form(3),
    method: str = Form("crypto"),
    lang: str = Form("en"),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(f"/login?lang={lang}", status_code=302)

    # Only Litecoin
    method = "crypto"
    credits_buy = max(3, int(credits_buy))
    if credits_buy % 3 != 0:
        credits_buy = credits_buy + (3 - credits_buy % 3)

    payment_id = str(uuid.uuid4())[:8]
    # Reference KRW value for display only
    krw_value = (credits_buy / 3) * KRW_PER_3_CREDITS
    created = datetime.utcnow().isoformat()

    conn = get_db()
    conn.execute(
        """INSERT INTO payments
           (payment_id, username, method, amount, credits, krw_value, status, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (payment_id, user["username"], "ltc", credits_buy, credits_buy, krw_value, "pending", created)
    )
    conn.commit()
    conn.close()

    body = f"""
    <div class="card">
        <h3>Litecoin payment</h3>
        <p><strong>{CRYPTO_INFO['currency']}</strong> ({CRYPTO_INFO['network']})</p>
        <p style="font-size:1.1rem;word-break:break-all">{CRYPTO_INFO['address']}</p>
        <p class="muted">Credits: <strong>{credits_buy}</strong> (ref. ~{krw_value:,.0f} KRW)</p>
        <p class="muted">Payment ID: <code>{payment_id}</code></p>
        <hr style="border-color:#334155;margin:20px 0">
        <p>After sending LTC, paste the transaction ID below. Admin will approve and grant credits.</p>
        <form method="post" action="/confirm-payment">
            <input type="hidden" name="lang" value="{lang}">
            <input type="hidden" name="payment_id" value="{payment_id}">
            <label>Transaction ID (txid)</label>
            <input name="tx_hash" required placeholder="LTC transaction id">
            <button type="submit">Submit txid</button>
        </form>
        <p style="margin-top:16px"><a href="/dashboard?lang={lang}" class="btn btn-outline">← Dashboard</a></p>
    </div>"""
    return HTMLResponse(base_html(body, lang, user))


@app.post("/confirm-payment")
async def confirm_payment(
    request: Request,
    payment_id: str = Form(...),
    depositor_name: str = Form(None),
    tx_hash: str = Form(None),
    lang: str = Form("en")
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(f"/login?lang={lang}", status_code=302)

    conn = get_db()
    row = conn.execute("SELECT * FROM payments WHERE payment_id=?", (payment_id,)).fetchone()
    if not row or row["username"] != user["username"]:
        conn.close()
        return RedirectResponse(f"/dashboard?lang={lang}&error=Payment not found", status_code=302)

    payment = dict(row)
    if payment["status"] == "pending":
        conn.execute(
            "UPDATE payments SET depositor_name=?, tx_hash=?, submitted_at=? WHERE payment_id=?",
            (depositor_name, tx_hash, datetime.utcnow().isoformat(), payment_id)
        )
        conn.commit()
    conn.close()

    msg = "Payment proof submitted. Credits will be added after admin approval."

    content = f"""
    <div class="card">
        <h3 class="success">{msg}</h3>
        <p>Payment ID: <code>{payment_id}</code></p>
        <p>{t('balance', lang)}: {user['credits']} (pending +{payment['credits']})</p>
        <a class="btn" href="/dashboard?lang={lang}">Dashboard</a>
    </div>"""
    return HTMLResponse(base_html(content, lang, user))



# ======================
# Admin
# ======================

def get_admin(request: Request):
    token = request.cookies.get("admin_session")
    if not token:
        return False
    conn = get_db()
    row = conn.execute("SELECT 1 FROM admin_sessions WHERE token=?", (token,)).fetchone()
    conn.close()
    return bool(row)


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, lang: str = "en"):
    if not get_admin(request):
        content = f"""
        <div class="card">
            <h2>Admin Login</h2>
            <form method="post" action="/admin/login">
                <input type="hidden" name="lang" value="{lang}">
                <label>Username</label>
                <input name="username" required>
                <label>Password</label>
                <input type="password" name="password" required>
                <button type="submit">Login</button>
            </form>
        </div>"""
        return base_html(content, lang)

    # list pending + recent
    conn = get_db()
    pending = [dict(r) for r in conn.execute("SELECT * FROM payments WHERE status='pending' ORDER BY created_at DESC").fetchall()]
    completed = [dict(r) for r in conn.execute("SELECT * FROM payments WHERE status='completed' ORDER BY created_at DESC LIMIT 20").fetchall()]
    conn.close()

    rows = ""
    if not pending:
        rows = "<p class='muted'>No pending payments.</p>"
    else:
        for p in pending:
            dep = p.get("depositor_name") or p.get("tx_hash") or "-"
            rows += f"""
            <div style="border:1px solid #334155;border-radius:8px;padding:12px;margin-bottom:10px">
                <p><strong>ID:</strong> {p['payment_id']} | <strong>User:</strong> {p['username']}</p>
                <p><strong>Method:</strong> {p['method']} | <strong>Amount:</strong> {p['amount']} → <strong>{p['credits']} credits</strong></p>
                <p><strong>Depositor / Tx:</strong> {dep}</p>
                <p class="muted">{p.get('created_at','')}</p>
                <form method="post" action="/admin/approve" style="display:inline">
                    <input type="hidden" name="payment_id" value="{p['payment_id']}">
                    <input type="hidden" name="lang" value="{lang}">
                    <button type="submit">Approve (grant credits)</button>
                </form>
                <form method="post" action="/admin/reject" style="display:inline;margin-left:8px">
                    <input type="hidden" name="payment_id" value="{p['payment_id']}">
                    <input type="hidden" name="lang" value="{lang}">
                    <button type="submit" class="btn-outline" style="background:#7f1d1d;border-color:#7f1d1d">Reject</button>
                </form>
            </div>"""

    done_rows = ""
    for p in completed:
        done_rows += f"<p class='muted'>{p['payment_id']} · {p['username']} · {p['credits']}cr · {p.get('created_at','')}</p>"

    content = f"""
    <div class="card">
        <h2>Admin Dashboard</h2>
        <p class="muted">Approve or reject pending payments</p>
        <p><a href="/admin/logout" class="btn btn-outline">Admin Logout</a></p>
    </div>
    <div class="card">
        <h3>Pending ({len(pending)})</h3>
        {rows}
    </div>
    <div class="card">
        <h3>Recent Completed</h3>
        {done_rows or "<p class='muted'>None</p>"}
    </div>"""
    return base_html(content, lang)


@app.post("/admin/login")
async def admin_login(username: str = Form(...), password: str = Form(...), lang: str = Form("en")):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        token = create_token()
        conn = get_db()
        conn.execute("INSERT INTO admin_sessions (token, created_at) VALUES (?,?)", (token, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
        resp = RedirectResponse(f"/admin?lang={lang}", status_code=302)
        resp.set_cookie("admin_session", token, httponly=True, max_age=60*60*12)
        return resp
    content = f"""
    <div class="card">
        <p class="error">Invalid admin credentials</p>
        <a class="btn" href="/admin?lang={lang}">Back</a>
    </div>"""
    return HTMLResponse(base_html(content, lang))


@app.get("/admin/logout")
async def admin_logout(request: Request):
    token = request.cookies.get("admin_session")
    if token:
        conn = get_db()
        conn.execute("DELETE FROM admin_sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()
    resp = RedirectResponse("/admin", status_code=302)
    resp.delete_cookie("admin_session")
    return resp


@app.post("/admin/approve")
async def admin_approve(request: Request, payment_id: str = Form(...), lang: str = Form("en")):
    if not get_admin(request):
        return RedirectResponse("/admin", status_code=302)

    conn = get_db()
    payment = conn.execute("SELECT * FROM payments WHERE payment_id=?", (payment_id,)).fetchone()
    if not payment:
        conn.close()
        return RedirectResponse(f"/admin?lang={lang}", status_code=302)

    if payment["status"] == "pending":
        conn.execute(
            "UPDATE payments SET status=?, approved_at=?, approved_by=? WHERE payment_id=?",
            ("completed", datetime.utcnow().isoformat(), "admin", payment_id)
        )
        conn.execute(
            "UPDATE users SET credits = credits + ? WHERE username=?",
            (payment["credits"], payment["username"])
        )
        conn.commit()
    conn.close()

    return RedirectResponse(f"/admin?lang={lang}", status_code=302)


@app.post("/admin/reject")
async def admin_reject(request: Request, payment_id: str = Form(...), lang: str = Form("en")):
    if not get_admin(request):
        return RedirectResponse("/admin", status_code=302)

    conn = get_db()
    payment = conn.execute("SELECT * FROM payments WHERE payment_id=?", (payment_id,)).fetchone()
    if payment and payment["status"] == "pending":
        conn.execute(
            "UPDATE payments SET status=?, rejected_at=? WHERE payment_id=?",
            ("rejected", datetime.utcnow().isoformat(), payment_id)
        )
        conn.commit()
    conn.close()

    return RedirectResponse(f"/admin?lang={lang}", status_code=302)



# ======================
# Run (Render compatible)
# ======================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"{APP_NAME} Obfuscator v{VERSION}")
    print(f"Listening on port {port}")
    print(f"Admin: /admin  (user={ADMIN_USERNAME} / pass={ADMIN_PASSWORD})")
    print(f"DB: PostgreSQL (DATABASE_URL set={bool(DATABASE_URL)})")
    uvicorn.run(app, host="0.0.0.0", port=port)
