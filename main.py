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

# Single domain – shop + obfuscation are different paths (no subdomain)
# SHOP_PATH = /shop   OBF_PATH = /obfuscate

# Pricing: $2 = 3 credits (1 obfuscation costs 3 credits)
CREDITS_PER_OBFUSCATION = 3
USD_PER_3_CREDITS = 2.0

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
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            created_at TEXT
        )
    """)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT DEFAULT ''")
    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS access_logs (
            id SERIAL PRIMARY KEY,
            created_at TEXT,
            ip TEXT,
            path TEXT,
            method TEXT,
            username TEXT,
            email TEXT,
            user_agent TEXT,
            device TEXT,
            referer TEXT
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
        CREATE TABLE IF NOT EXISTS discord_links (
            discord_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
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
# - setmetatable dispatch
# - mixed hex/binary literals
# - CF state machine
# - returns loaded chunk result (fixes nil/null)
# ======================

def _rand_ident(n: int = 8) -> str:
    if random.random() < 0.35:
        return "".join(random.choices(string.ascii_letters, k=n))
    return "_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _num(n: int, mask32: bool = False) -> str:
    n = int(n)
    if mask32:
        n = n & 0xFFFFFFFF
    if n < 0:
        n = n & 0xFFFFFFFF
    r = random.random()
    if 0 <= n < 16 and r < 0.3:
        return str(n)
    if r < 0.4:
        return hex(n)
    if r < 0.7 and 0 <= n < (1 << 48):
        return "0b" + format(n, "b")
    return "0x" + format(n, "X")


def _pack_bytes(data: bytes, seed: int) -> list:
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
        f"(function()local a={_num(a)}return(a+a)==(a*{_num(2)})end)()",
        f"(function()local a={_num(a)}return not(a*a<{_num(0)})end)()",
    ]
    return random.choice(forms)


def _junk_block() -> str:
    a, b = _rand_ident(4), _rand_ident(4)
    n1, n2 = random.randint(1, 99), random.randint(1, 99)
    return (
        f"do local {a}={_num(n1)};local {b}={_num(n2)};"
        f"if {a}*{a}<{_num(0)} then {b}={b}+{_num(1)} end end"
    )


def _emit_vm(src: str, intensity: str) -> str:
    """
    Emit:
      return setmetatable({...}, {__index=...}):ENTRY()
    The loaded original chunk's return values are propagated (no silent nil).
    """
    raw = src.encode("utf-8")
    seed = random.randint(0x10000, 0x7FFFFFFF)
    packed = _pack_bytes(raw, seed)
    chunks = _split_table(packed)

    id_bxor = _rand_ident(4)
    id_dec = _rand_ident(4)
    id_main = _rand_ident(4)
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
    id_st = _rand_ident(3)
    id_ret = _rand_ident(3)
    id_loader = _rand_ident(4)

    bc_parts = ",".join(_emit_number_table(c) for c in chunks)

    st_init, st_decode, st_build, st_load, st_run, st_done = (
        _num(1), _num(2), _num(3), _num(4), _num(5), _num(6)
    )
    junk1 = _junk_block()
    junk2 = _junk_block()
    ot = _opaque_true()

    # Portable byte XOR (x^y^z) without bit32
    bxor_fn = f"""local function {id_bxor}(x,y,z)
x=math.floor(x)%{_num(256)};y=math.floor(y)%{_num(256)};z=math.floor(z)%{_num(256)}
local r,p={_num(0)},{_num(1)}
for _=1,{_num(8)} do
local bx,by,bz=x%{_num(2)},y%{_num(2)},z%{_num(2)}
r=r+((bx+by+bz)%{_num(2)})*p
x=math.floor(x/{_num(2)});y=math.floor(y/{_num(2)});z=math.floor(z/{_num(2)});p=p*{_num(2)}
end
return r
end"""

    dec_fn = f"""local function {id_dec}(word,key,pos,out,olen)
key=(key*{_num(1664525)}+{_num(1013904223)})%{_num(4294967296)}
word=math.floor(word)
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

    # CRITICAL: return the chunk's return value(s)
    main_fn = f"""local function {id_main}(...)
local {id_bc}={{{bc_parts}}}
local {id_buf}={{}}
local {id_key}={_num(seed)}
local {id_len}={_num(len(raw))}
local {id_j}={_num(0)}
local {id_st}={st_init}
local {id_run},{id_fn},{id_err},{id_ret}
local {id_loader}=load or loadstring
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
local t={{}}
for {id_i}=1,{id_len} do t[{id_i}]=string.char({id_buf}[{id_i}]) end
{id_run}=table.concat(t)
{id_st}={st_load}
elseif {id_st}=={st_load} then
{id_fn},{id_err}={id_loader}({id_run})
if not {id_fn} then error({id_err} or "load failed") end
{id_st}={st_run}
elseif {id_st}=={st_run} then
if {ot} then
{id_ret}={id_fn}(...)
else
{id_ret}={id_fn}(...)
end
{id_st}={st_done}
else
{id_st}={st_done}
end
end
return {id_ret}
end"""

    k_main = random.randint(0x40, 0xFF)
    k_boot = random.randint(0x100, 0x3FF)
    handler_main = _num(k_main)
    handler_boot = _num(k_boot)
    entry = random.choice(["B", "R", "X", "K", "Z", "Q"])

    vm = f"""return setmetatable({{
[{handler_main}]=function(self,...)
{bxor_fn}
{dec_fn}
{main_fn}
return {id_main}(...)
end,
[{handler_boot}]=function(self,...)
return self[{handler_main}](self,...)
end,
}},{{
__index=function(t,k)
if k=="{entry}" then return t[{handler_boot}] end
end
}}):{entry}(...)"""

    if intensity == "v2":
        vm = " ".join(vm.split())
    else:
        vm = "\n".join(ln.rstrip() for ln in vm.splitlines() if ln.strip())
    return vm


def _emit_chunk_layer(src: str) -> str:
    """Extra layer: split source into XOR'd char-code chunks, rebuild + load."""
    data = src.encode("utf-8")
    key = random.randint(1, 255)
    cs = random.randint(24, 40)
    chunks = []
    for i in range(0, len(data), cs):
        part = data[i:i + cs]
        enc = [(b ^ ((key + i + j) & 0xFF)) for j, b in enumerate(part)]
        chunks.append(enc)

    id_k = _rand_ident(3)
    id_b = _rand_ident(4)
    id_o = _rand_ident(3)
    id_i = _rand_ident(2)
    id_j = _rand_ident(2)
    id_t = _rand_ident(2)
    id_s = _rand_ident(3)
    id_f = _rand_ident(3)
    id_e = _rand_ident(3)
    id_r = _rand_ident(3)

    tbl_parts = []
    for ch in chunks:
        tbl_parts.append("{" + ",".join(_num(x) for x in ch) + "}")
    tbl = "{" + ",".join(tbl_parts) + "}"

    ot = _opaque_true()
    junk = _junk_block()

    code = f"""return (function(...)
local {id_k}={_num(key)}
local {id_b}={tbl}
local {id_o}={{}}
local {id_i}=0
for {id_t}=1,#{id_b} do
local {id_s}={id_b}[{id_t}]
for {id_j}=1,#{id_s} do
local c={id_s}[{id_j}]
{id_i}={id_i}+1
{id_o}[{id_i}]=string.char(c~(({id_k}+({id_i}-1))%256))
end
end
{junk}
local {id_r}=table.concat({id_o})
local {id_f},{id_e}=(load or loadstring)({id_r})
if not {id_f} then error({id_e} or "layer") end
if {ot} then return {id_f}(...) end
return {id_f}(...)
end)(...)"""
    return " ".join(code.split())


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

    # Multi-layer (fresh keys each pass). Avoid exponential size blow-up.
    # v1: chunk → VM → VM
    # v2: chunk → VM → chunk → VM → VM (outer minified)
    body = src
    if intensity == "v1":
        # 3 layers: chunk + VM + VM
        body = _emit_chunk_layer(body)
        body = _emit_vm(body, "v1")
        body = _emit_vm(body, "v1")
    else:
        # 4 layers: chunk + VM + chunk + outer VM (minified)
        body = _emit_chunk_layer(body)
        body = _emit_vm(body, "v1")
        body = _emit_chunk_layer(body)
        body = _emit_vm(body, "v2")

    header = (
        f"-- Protected using {APP_NAME} Obfuscator {VERSION}\n"
        f"-- {datetime.utcnow().strftime('%Y-%m-%d')} | {intensity} | multi-layer\n"
    )
    return header + body



def calc_cost(intensity: str, options: List[str] = None) -> int:
    return BASE_COST.get(intensity, CREDITS_PER_OBFUSCATION)

# ======================
# App
# ======================

app = FastAPI(title=APP_NAME, version=VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _client_ip(request: Request) -> str:
    xf = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip") or ""
    if xf:
        return xf.split(",")[0].strip()
    if request.client:
        return request.client.host or ""
    return ""


def _device_from_ua(ua: str) -> str:
    ua_l = (ua or "").lower()
    if any(x in ua_l for x in ("iphone", "android", "mobile", "ipad")):
        if "ipad" in ua_l:
            return "Tablet"
        return "Phone"
    if any(x in ua_l for x in ("windows", "macintosh", "linux", "cros")):
        return "PC"
    return "Unknown"


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    response = await call_next(request)
    try:
        path = request.url.path or "/"
        # skip static-ish / noisy
        if path.startswith("/db-check") or path.endswith(".ico"):
            return response
        ua = request.headers.get("user-agent") or ""
        username = ""
        email = ""
        phone = ""
        try:
            user = get_current_user(request)
            if user:
                username = user.get("username") or ""
                email = user.get("email") or ""
                phone = user.get("phone") or ""
        except Exception:
            pass
        conn = get_db()
        conn.execute(
            """INSERT INTO access_logs
               (created_at, ip, path, method, username, email, user_agent, device, referer)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                datetime.utcnow().isoformat(),
                _client_ip(request),
                path[:300],
                request.method,
                username,
                (email + ((" / " + phone) if phone else ""))[:200],
                ua[:500],
                _device_from_ua(ua),
                (request.headers.get("referer") or "")[:300],
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[access_log] {e}")
    return response


def get_site(request: Request) -> str:
    """Return 'shop' or 'api' from URL path (single domain, no subdomain)."""
    p = request.url.path or "/"
    if p.startswith("/obfuscate") or p.startswith("/download"):
        return "api"
    return "shop"

def site_title(site: str) -> str:
    if site == "api":
        return APP_NAME
    return "DaonShop"

def set_session_cookie(resp, token: str):
    resp.set_cookie("session", token, httponly=True, max_age=60*60*24*30, samesite="lax")
    return resp

def base_html(content: str, lang: str = "en", user=None, site: str = "shop"):
    balance = user["credits"] if user else 0
    username = user["username"] if user else ""
    title = site_title(site)
    brand = "DaonShop" if site == "shop" else APP_NAME
    # sidebar nav
    if site == "shop":
        nav_items = """
        <a class="nav-item" href="/shop"><span class="ico">▦</span> Dashboard</a>
        <a class="nav-item" href="/shop#purchase"><span class="ico">🛒</span> Purchase</a>
        <a class="nav-item" href="/obfuscate"><span class="ico">◎</span> Obfuscation</a>
        """
    else:
        nav_items = """
        <a class="nav-item" href="/obfuscate"><span class="ico">◎</span> Obfuscation</a>
        <a class="nav-item" href="/shop"><span class="ico">🛒</span> Purchase</a>
        <a class="nav-item" href="/shop"><span class="ico">▦</span> Dashboard</a>
        """
    user_block = ""
    if user:
        user_block = f"""
        <a class="nav-item" href="#"><span class="ico">☺</span> {username}</a>
        <div class="credits-pill">{balance} credits</div>
        <a class="nav-item logout" href="/logout"><span class="ico">→</span> Logout</a>
        """
    else:
        user_block = f"""
        <a class="nav-item" href="/login"><span class="ico">☺</span> Login</a>
        <a class="nav-item" href="/register"><span class="ico">+</span> Sign Up</a>
        """

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  --bg:#f4f2fb;
  --card:#ffffff;
  --purple:#7c3aed;
  --purple2:#8b5cf6;
  --purple-soft:#ede9fe;
  --text:#1e1b4b;
  --muted:#6b7280;
  --border:#e9e5f5;
  --shadow:0 8px 24px rgba(124,58,237,.08);
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
.layout{{display:flex;min-height:100vh}}
.sidebar{{width:240px;background:var(--card);border-right:1px solid var(--border);padding:20px 14px;position:sticky;top:0;height:100vh}}
.brand{{display:flex;align-items:center;gap:10px;font-weight:800;font-size:1.25rem;color:var(--purple);padding:8px 10px 22px}}
.brand .logo{{width:32px;height:32px;border-radius:50%;border:2px dashed var(--purple);display:flex;align-items:center;justify-content:center;font-size:14px}}
.nav-item{{display:flex;align-items:center;gap:10px;padding:12px 14px;border-radius:12px;color:var(--text);text-decoration:none;font-weight:600;font-size:14px;margin-bottom:4px}}
.nav-item:hover,.nav-item.active{{background:var(--purple-soft);color:var(--purple)}}
.nav-item.logout{{color:#dc2626}}
.nav-item .ico{{width:20px;text-align:center;opacity:.85}}
.credits-pill{{margin:12px 10px;background:var(--purple-soft);color:var(--purple);font-weight:700;font-size:13px;padding:8px 12px;border-radius:999px;text-align:center}}
.main{{flex:1;padding:28px 28px 48px;max-width:960px}}
h1,h2,h3{{color:var(--text)}}
h2{{font-size:1.4rem;margin-bottom:8px}}
h3{{font-size:1.1rem;margin-bottom:10px}}
.muted{{color:var(--muted);font-size:13px}}
.card{{background:var(--card);border-radius:18px;padding:22px;margin-bottom:18px;border:1px solid var(--border);box-shadow:var(--shadow)}}
.plan{{background:var(--purple-soft);border-radius:16px;padding:18px;margin-bottom:12px;display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px}}
.plan .name{{font-weight:700;font-size:1.05rem}}
.plan .price{{font-weight:700;color:var(--purple);font-size:1.05rem}}
.plan .actions{{display:flex;gap:8px;flex-wrap:wrap}}
input,select,textarea{{width:100%;padding:12px 14px;margin:8px 0 14px;border-radius:12px;border:1px solid var(--border);background:#faf9fc;color:var(--text);font-size:14px}}
textarea{{height:200px;font-family:ui-monospace,monospace;resize:vertical}}
button,.btn{{display:inline-block;padding:11px 18px;border-radius:12px;border:none;background:var(--purple);color:#fff;font-weight:700;cursor:pointer;text-decoration:none;font-size:13px;letter-spacing:.02em}}
button:hover,.btn:hover{{background:var(--purple2)}}
.btn-outline{{background:#fff;color:var(--purple);border:1.5px solid var(--purple)}}
.btn-soft{{background:var(--purple-soft);color:var(--purple)}}
.row{{display:flex;gap:12px;flex-wrap:wrap;align-items:center}}
pre.result{{background:#0f172a;color:#e2e8f0;padding:16px;border-radius:12px;overflow:auto;white-space:pre-wrap;word-break:break-all;font-size:12px;max-height:420px}}
.success{{color:#059669}}
.error{{color:#dc2626}}
label{{font-size:13px;color:var(--muted);font-weight:600}}
.topbar{{display:none;align-items:center;justify-content:space-between;padding:12px 16px;background:var(--card);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:20}}
.topbar .menu-btn,.sidebar .close-btn{{background:var(--purple-soft);color:var(--purple);border:none;border-radius:10px;width:40px;height:40px;font-size:18px;cursor:pointer;font-weight:700}}
.sidebar .brand-row{{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}}
.sidebar .close-btn{{display:none}}
@media(max-width:800px){{
  .topbar{{display:flex}}
  .layout{{flex-direction:column}}
  .sidebar{{
    width:min(300px,86vw);height:100vh;position:fixed;top:0;left:0;z-index:40;
    border-right:1px solid var(--border);transform:translateX(-105%);transition:transform .2s ease;
    box-shadow:var(--shadow);
  }}
  .sidebar.open{{transform:translateX(0)}}
  .sidebar .close-btn{{display:inline-flex;align-items:center;justify-content:center}}
  .sidebar-backdrop{{display:none;position:fixed;inset:0;background:rgba(15,23,42,.35);z-index:30}}
  .sidebar-backdrop.show{{display:block}}
  .main{{padding:18px}}
}}
</style>
</head>
<body>
<div class="topbar">
  <button type="button" class="menu-btn" onclick="openNav()" aria-label="Open menu">☰</button>
  <div style="font-weight:800;color:var(--purple)">{brand}</div>
  <div style="width:40px"></div>
</div>
<div class="sidebar-backdrop" id="navBackdrop" onclick="closeNav()"></div>
<div class="layout">
  <aside class="sidebar" id="sidebar">
    <div class="brand-row">
      <div class="brand" style="padding:0;margin:0"><div class="logo">🔒</div>{brand}</div>
      <button type="button" class="close-btn" onclick="closeNav()" aria-label="Close menu">✕</button>
    </div>
    {nav_items}
    {user_block}
  </aside>
  <main class="main">
    {content}
  </main>
</div>
<script>
function openNav(){{
  document.getElementById('sidebar').classList.add('open');
  document.getElementById('navBackdrop').classList.add('show');
}}
function closeNav(){{
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('navBackdrop').classList.remove('show');
}}
</script>
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
    site = get_site(request)
    user = get_current_user(request)
    if user:
        return RedirectResponse(f"/shop?lang={lang}", status_code=302)
    if site == "api":
        content = f"""
        <div class="card">
            <h2>Euana</h2>
            <p class="muted" style="margin:12px 0 24px">Luau / Lua obfuscation dashboard. Buy credits on the shop, then obfuscate your scripts here.</p>
            <div class="row">
                <a class="btn" href="/login?lang={lang}">{t('login', lang)}</a>
                <a class="btn btn-outline" href="/register?lang={lang}">{t('register', lang)}</a>
                <a class="btn btn-outline" href="/shop">Buy credits (Shop)</a>
            </div>
        </div>"""
    else:
        content = f"""
        <div class="card">
            <h2>DaonShop</h2>
            <p class="muted" style="margin:12px 0 24px">Credit shop for Euana. $2 = 3 credits. Pay with Litecoin, then go to Obfuscation.</p>
            <div class="row">
                <a class="btn" href="/login?lang={lang}">{t('login', lang)}</a>
                <a class="btn btn-outline" href="/register?lang={lang}">{t('register', lang)}</a>
                <a class="btn btn-outline" href="/obfuscate">Open Euana</a>
            </div>
        </div>"""
    return base_html(content, lang, site=site)

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, lang: str = "en"):
    site = get_site(request)
    content = f"""
    <div class="card">
        <h2>{t('register', lang)}</h2>
        <form method="post" action="/register">
            <input type="hidden" name="lang" value="{lang}">
            <label>{t('username', lang)}</label>
            <input name="username" required minlength="3" maxlength="32" pattern="[a-zA-Z0-9_]+">
            <label>{t('password', lang)}</label>
            <input type="password" name="password" required minlength="4">
            <label>Email (optional)</label>
            <input type="email" name="email" placeholder="you@email.com">
            <label>Phone (optional)</label>
            <input name="phone" placeholder="+82...">
            <button type="submit">{t('register', lang)}</button>
        </form>
        <p class="muted" style="margin-top:16px"><a href="/login?lang={lang}" style="color:#a5b4fc">{t('login', lang)}</a></p>
    </div>"""
    return base_html(content, lang, site=site)

@app.post("/register")
async def register(username: str = Form(...), password: str = Form(...), email: str = Form(""), phone: str = Form(""), lang: str = Form("en")):
    username = username.strip().lower()
    email = (email or "").strip().lower()
    phone = (phone or "").strip()
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
            "INSERT INTO users (username, password, credits, results, email, phone, created_at) VALUES (?,?,?,?,?,?,?)",
            (username, hash_password(password), 0, "{}", email, phone, created)
        )
        token = create_token()
        conn.execute("INSERT INTO sessions (token, username, created_at) VALUES (?,?,?)", (token, username, created))
        conn.commit()
        conn.close()
    except Exception as e:
        content = f"""<div class="card"><p class="error">DB error: {html_lib.escape(str(e))}</p>
        <a class="btn" href="/register?lang={lang}">{t('register', lang)}</a></div>"""
        return HTMLResponse(base_html(content, lang))
    resp = RedirectResponse(f"/shop?lang={lang}", status_code=302)
    set_session_cookie(resp, token)
    return resp

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, lang: str = "en"):
    site = get_site(request)
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
    return base_html(content, lang, site=site)

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
    resp = RedirectResponse(f"/shop?lang={lang}", status_code=302)
    set_session_cookie(resp, token)
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

@app.get("/shop", response_class=HTMLResponse)
@app.get("/obfuscate", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, lang: str = "en", result_id: str = None, error: str = None):
    p = request.url.path or ""
    site = "api" if p.startswith("/obfuscate") else "shop"
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

    balance_card = f"""
    <div class="card">
        <h2>{"Euana Dashboard" if site == "api" else "Shop Dashboard"}</h2>
        <p style="font-size:1.25rem;margin:10px 0">{t('balance', lang)}: <strong>{user['credits']}</strong></p>
    </div>
    """

    if site == "api":
        content = balance_card + result_block + f"""
    <div class="card">
        <h3>Obfuscate</h3>
        <p class="muted">3 credits = 1 run. Paste code or upload a .lua / .txt file. Buy credits at the shop if needed.</p>
        <p class="muted" style="margin-bottom:12px"><a href="/shop" style="color:#a5b4fc">→ Buy credits on DaonShop</a></p>
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
"""
    else:
        content = balance_card + f"""
    <div class="card" id="purchase">
        <h2>Purchase Plans</h2>
        <p class="muted" style="margin-bottom:16px">$2 = 3 credits · 3 credits = 1 obfuscation · Pay with Litecoin</p>

        <div class="plan">
            <div>
                <div class="name">☺ Starter Pack</div>
                <div class="muted">3 credits · 1 obfuscation</div>
            </div>
            <div class="price">$2</div>
            <div class="actions">
                <form method="post" action="/charge" style="display:inline">
                    <input type="hidden" name="lang" value="{lang}">
                    <input type="hidden" name="method" value="crypto">
                    <input type="hidden" name="credits_buy" value="3">
                    <button type="submit">BUY NOW</button>
                </form>
            </div>
        </div>

        <div class="plan">
            <div>
                <div class="name">★ Basic</div>
                <div class="muted">15 credits · 5 obfuscations</div>
            </div>
            <div class="price">$10</div>
            <div class="actions">
                <form method="post" action="/charge" style="display:inline">
                    <input type="hidden" name="lang" value="{lang}">
                    <input type="hidden" name="method" value="crypto">
                    <input type="hidden" name="credits_buy" value="15">
                    <button type="submit">BUY NOW</button>
                </form>
            </div>
        </div>

        <div class="plan">
            <div>
                <div class="name">🏆 Premium</div>
                <div class="muted">45 credits · 15 obfuscations</div>
            </div>
            <div class="price">$30</div>
            <div class="actions">
                <form method="post" action="/charge" style="display:inline">
                    <input type="hidden" name="lang" value="{lang}">
                    <input type="hidden" name="method" value="crypto">
                    <input type="hidden" name="credits_buy" value="45">
                    <button type="submit">BUY NOW</button>
                </form>
            </div>
        </div>

        <div class="plan">
            <div>
                <div class="name">📦 Custom amount</div>
                <div class="muted">Multiples of 3 credits · $2 per 3 credits</div>
            </div>
            <form method="post" action="/charge" class="actions" style="align-items:center">
                <input type="hidden" name="lang" value="{lang}">
                <input type="hidden" name="method" value="crypto">
                <input type="number" name="credits_buy" value="3" min="3" step="3" style="width:120px;margin:0">
                <button type="submit">BUY NOW</button>
            </form>
        </div>
    </div>
    <div class="card">
        <h3>Euana</h3>
        <p class="muted" style="margin-bottom:12px">Use credits on the Obfuscation page to obfuscate Luau / Lua scripts.</p>
        <a class="btn" href="/obfuscate">Open Obfuscation</a>
    </div>
"""
    return base_html(content, lang, user, site=site)




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
            f"/obfuscate?lang={lang}&error=Please paste code or upload a file",
            status_code=302
        )

    if intensity not in ("v1", "v2"):
        intensity = "v2"

    cost = CREDITS_PER_OBFUSCATION
    if user["credits"] < cost:
        return RedirectResponse(
            f"/obfuscate?lang={lang}&error=Insufficient credits (need {cost})",
            status_code=302
        )

    user["credits"] -= cost
    result = obfuscate_code(code, intensity, [])

    result_id = str(uuid.uuid4())[:8]
    if "results" not in user:
        user["results"] = {}
    user["results"][result_id] = result
    save_user(user)

    return RedirectResponse(f"/obfuscate?lang={lang}&result_id={result_id}", status_code=302)


@app.get("/download/{result_id}")
async def download_result(request: Request, result_id: str):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    results = user.get("results") or {}
    content = results.get(result_id)
    if not content:
        return RedirectResponse("/obfuscate?error=Result+not+found", status_code=302)
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
    # USD reference: $2 per 3 credits
    usd_value = (credits_buy / 3) * USD_PER_3_CREDITS
    created = datetime.utcnow().isoformat()

    conn = get_db()
    conn.execute(
        """INSERT INTO payments
           (payment_id, username, method, amount, credits, krw_value, status, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (payment_id, user["username"], "ltc", credits_buy, credits_buy, usd_value, "pending", created)
    )
    conn.commit()
    conn.close()

    body = f"""
    <div class="card">
        <h3>Litecoin payment</h3>
        <p><strong>{CRYPTO_INFO['currency']}</strong> ({CRYPTO_INFO['network']})</p>
        <p style="font-size:1.1rem;word-break:break-all">{CRYPTO_INFO['address']}</p>
        <p class="muted">Credits: <strong>{credits_buy}</strong> · <strong>${usd_value:,.2f}</strong> USD</p>
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
        <p style="margin-top:16px"><a href="/shop?lang={lang}" class="btn btn-outline">← Shop</a></p>
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
        return RedirectResponse(f"/shop?lang={lang}&error=Payment not found", status_code=302)

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
        <a class="btn" href="/shop?lang={lang}">Shop</a>
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

    result_id = request.query_params.get("result_id")
    error = request.query_params.get("error")
    result_block = ""
    if error:
        result_block = f"""<div class="card"><p class="error">{html_lib.escape(error)}</p></div>"""
    elif result_id:
        # admin results stored in memory-like table via payments? use a simple admin_results in users table under username __admin__
        conn2 = get_db()
        row = conn2.execute("SELECT results FROM users WHERE username=?", ("__admin__",)).fetchone()
        conn2.close()
        results = {}
        if row:
            try:
                results = json.loads(row["results"] or "{}")
            except Exception:
                results = {}
        if result_id in results:
            safe = html_lib.escape(results[result_id])
            result_block = f"""
            <div class="card">
                <h3 class="success">Admin obfuscation done (free)</h3>
                <pre class="result" id="obfResult">{safe}</pre>
                <div class="row" style="margin-top:12px">
                    <button type="button" onclick="navigator.clipboard.writeText(document.getElementById('obfResult').innerText)">Copy</button>
                    <a class="btn" href="/admin/download/{result_id}" style="margin-left:8px">Download .lua</a>
                </div>
            </div>"""

    content = f"""
    <div class="card">
        <h2>Admin Dashboard</h2>
        <p class="muted">Payments + free obfuscation</p>
        <p><a href="/admin-log" class="btn" style="margin-right:8px">Access Log</a><a href="/admin/logout" class="btn btn-outline">Admin Logout</a></p>
    </div>
    {result_block}
    <div class="card">
        <h3>Free Obfuscate (admin only)</h3>
        <p class="muted">No credit cost. Unlimited.</p>
        <form method="post" action="/admin/obfuscate" enctype="multipart/form-data">
            <input type="hidden" name="lang" value="{lang}">
            <label>Version</label>
            <select name="intensity">
                <option value="v1">Euana v1</option>
                <option value="v2" selected>Euana v2</option>
            </select>
            <label>Code</label>
            <textarea name="code" placeholder="Paste Luau / Lua code"></textarea>
            <label>Or upload file</label>
            <input type="file" name="file" accept=".lua,.luau,.txt,.text">
            <button type="submit">Obfuscate (free)</button>
        </form>
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



@app.get("/admin-log", response_class=HTMLResponse)
async def admin_log(request: Request, lang: str = "en"):
    if not get_admin(request):
        return RedirectResponse("/admin", status_code=302)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM access_logs ORDER BY id DESC LIMIT 300"
    ).fetchall()
    conn.close()
    table = ""
    for r in rows:
        r = dict(r)
        table += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid var(--border);font-size:12px">{html_lib.escape(str(r.get('created_at') or ''))}</td>
          <td style="padding:8px;border-bottom:1px solid var(--border);font-size:12px">{html_lib.escape(str(r.get('ip') or ''))}</td>
          <td style="padding:8px;border-bottom:1px solid var(--border);font-size:12px">{html_lib.escape(str(r.get('device') or ''))}</td>
          <td style="padding:8px;border-bottom:1px solid var(--border);font-size:12px">{html_lib.escape(str(r.get('username') or '-'))}</td>
          <td style="padding:8px;border-bottom:1px solid var(--border);font-size:12px">{html_lib.escape(str(r.get('email') or '-'))}</td>
          <td style="padding:8px;border-bottom:1px solid var(--border);font-size:12px">{html_lib.escape(str(r.get('path') or ''))}</td>
          <td style="padding:8px;border-bottom:1px solid var(--border);font-size:11px;max-width:180px;overflow:hidden;text-overflow:ellipsis" title="{html_lib.escape(str(r.get('user_agent') or ''))}">{html_lib.escape((str(r.get('user_agent') or ''))[:60])}</td>
        </tr>"""
    if not table:
        table = "<tr><td colspan='7' class='muted' style='padding:12px'>No logs yet.</td></tr>"
    content = f"""
    <div class="card">
        <h2>Access Log</h2>
        <p class="muted">Recent visitors — IP, device, account, email, path</p>
        <p style="margin:10px 0"><a class="btn btn-outline" href="/admin">← Admin</a>
        <a class="btn btn-outline" href="/admin-log" style="margin-left:8px">Refresh</a></p>
        <div style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;margin-top:12px">
          <thead>
            <tr style="text-align:left;font-size:12px;color:var(--muted)">
              <th style="padding:8px">Time (UTC)</th>
              <th style="padding:8px">IP</th>
              <th style="padding:8px">Device</th>
              <th style="padding:8px">User</th>
              <th style="padding:8px">Email / Phone</th>
              <th style="padding:8px">Path</th>
              <th style="padding:8px">User-Agent</th>
            </tr>
          </thead>
          <tbody>{table}</tbody>
        </table>
        </div>
    </div>"""
    return base_html(content, lang, site="shop")


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



@app.post("/admin/obfuscate")
async def admin_obfuscate(
    request: Request,
    code: str = Form(""),
    intensity: str = Form("v2"),
    lang: str = Form("en"),
    file: UploadFile = File(None),
):
    if not get_admin(request):
        return RedirectResponse("/admin", status_code=302)

    if file and file.filename:
        raw = await file.read()
        try:
            code = raw.decode("utf-8")
        except Exception:
            code = raw.decode("latin-1", errors="ignore")

    code = (code or "").strip()
    if len(code) < 5:
        return RedirectResponse(f"/admin?lang={lang}&error=Paste+code+or+upload+file", status_code=302)

    if intensity not in ("v1", "v2"):
        intensity = "v2"

    result = obfuscate_code(code, intensity, [])
    result_id = str(uuid.uuid4())[:8]

    # store under synthetic __admin__ user
    conn = get_db()
    row = conn.execute("SELECT results FROM users WHERE username=?", ("__admin__",)).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO users (username, password, credits, results, created_at) VALUES (?,?,?,?,?)",
            ("__admin__", hash_password(secrets.token_hex(16)), 0, "{}", datetime.utcnow().isoformat()),
        )
        results = {}
    else:
        try:
            results = json.loads(row["results"] or "{}")
        except Exception:
            results = {}
    results[result_id] = result
    # keep last 30 only
    if len(results) > 30:
        for k in list(results.keys())[:-30]:
            del results[k]
    conn.execute(
        "UPDATE users SET results=? WHERE username=?",
        (json.dumps(results), "__admin__"),
    )
    conn.commit()
    conn.close()

    return RedirectResponse(f"/admin?lang={lang}&result_id={result_id}", status_code=302)


@app.get("/admin/download/{result_id}")
async def admin_download(request: Request, result_id: str):
    if not get_admin(request):
        return RedirectResponse("/admin", status_code=302)
    conn = get_db()
    row = conn.execute("SELECT results FROM users WHERE username=?", ("__admin__",)).fetchone()
    conn.close()
    results = {}
    if row:
        try:
            results = json.loads(row["results"] or "{}")
        except Exception:
            results = {}
    content = results.get(result_id)
    if not content:
        return RedirectResponse("/admin?error=Result+not+found", status_code=302)
    filename = f"admin_obfuscated_{result_id}.lua"
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
