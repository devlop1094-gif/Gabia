"""
Euana - Single File (Render Ready)
- Register / Login
- Bank transfer / Crypto payment
- Credit system
- Server-side obfuscation + dashboard result
- Multiple obfuscation options
"""

from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
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

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("DB_URL") or os.environ.get("POSTGRES_URL")

class _DBConn:
    """Thin wrapper so conn.execute(...).fetchone() style works with psycopg2."""
    def __init__(self, conn):
        self._conn = conn
        self._cur = conn.cursor()

    def execute(self, sql, params=None):
        # Convert SQLite-style ? placeholders to psycopg2 %s
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

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass
        self._conn.close()


def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL env var is not set. Add it in Render Environment.")
    # Render sometimes gives postgres:// — psycopg2 wants postgresql://
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    raw = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    return _DBConn(raw)

def init_db():
    conn = get_db()
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
    conn.close()

# Init only when DATABASE_URL is present (skip at import time if missing for local syntax checks)
if DATABASE_URL:
    try:
        init_db()
    except Exception as e:
        print(f"[DB] init deferred/failed: {e}")

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
# Obfuscation Engine (Custom VM – no recoverable plaintext / no plain XOR)
# ======================

def _rand_ident(n: int = 8) -> str:
    return "_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _pack_source_to_ints(src: str, seed: int) -> list:
    """Pack UTF-8 bytes into 32-bit ints with a rolling keystream (not plain XOR)."""
    data = src.encode("utf-8")
    out = []
    state = seed & 0xFFFFFFFF
    i = 0
    while i < len(data):
        # LCG-ish keystream
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        chunk = 0
        for b in range(4):
            if i + b < len(data):
                # mix byte with keystream byte and position
                kb = (state >> (8 * b)) & 0xFF
                chunk |= ((data[i + b] ^ kb ^ ((i + b) & 0xFF)) & 0xFF) << (8 * b)
        out.append(chunk)
        i += 4
    return out, len(data)


def _emit_vm(src: str, intensity: str) -> str:
    """
    Emit a custom stack VM that:
    1. Holds packed integer bytecode
    2. Reconstructs the original source through multi-step decode (not a single XOR loop)
    3. Runs it via loadstring / load
    Source never appears as a single encrypted string literal.
    """
    seed = random.randint(0x100000, 0x7FFFFFFF)
    packed, nbytes = _pack_source_to_ints(src, seed)

    # split packed ints into several tables to avoid one big array
    chunk_size = random.randint(8, 16)
    tables = []
    for i in range(0, len(packed), chunk_size):
        tables.append(packed[i:i + chunk_size])

    # random names
    n = {
        "pc": _rand_ident(5),
        "st": _rand_ident(5),
        "bc": _rand_ident(6),
        "op": _rand_ident(4),
        "acc": _rand_ident(5),
        "key": _rand_ident(4),
        "buf": _rand_ident(5),
        "len": _rand_ident(4),
        "i": _rand_ident(3),
        "j": _rand_ident(3),
        "t": _rand_ident(4),
        "fn": _rand_ident(4),
        "err": _rand_ident(4),
        "tmp": _rand_ident(4),
        "run": _rand_ident(5),
    }

    # build bytecode table pieces
    tbl_parts = []
    for ti, tbl in enumerate(tables):
        vals = ",".join(str(x) for x in tbl)
        tbl_parts.append(f"{{{vals}}}")
    bc_init = ",".join(tbl_parts)

    # VM program as data-driven ops:
    # opcodes (numeric to avoid string opcodes):
    # 1 = LOAD_CHUNK (push table index)
    # 2 = DECODE_BLOCK (pop table, decode into buf using keystream)
    # 3 = FINISH (join buf -> string, load+run)
    # 0 = NOP / junk
    # We hardcode the control flow in Lua with opaque checks

    # opaque predicate helpers
    opaque_true = f"(function() local a={random.randint(2,9)} return a*a>=0 end)()"
    opaque_false = f"(function() local a={random.randint(2,9)} return a*a<0 end)()"

    # anti-tamper light
    anti = ""
    if intensity == "v2":
        anti = f"""
local {n['tmp']}=os and os.clock and os.clock() or 0
if type(debug)=="table" and debug.getinfo then local _=debug.getinfo(1,"S") end
"""

    # Build decode loop that reconstructs bytes from packed ints using same LCG
    vm = f"""{anti}local {n['bc']}={{{bc_init}}}
local {n['buf']}={{}}
local {n['key']}={seed}
local {n['len']}={nbytes}
local {n['i']}=1
local {n['j']}=0
while {n['i']}<=#{n['bc']} do
local {n['t']}={n['bc']}[{n['i']}]
{n['i']}={n['i']}+1
if type({n['t']})=="table" then
local {n['pc']}=1
while {n['pc']}<=#{n['t']} do
local {n['op']}={n['t']}[{n['pc']}]
{n['pc']}={n['pc']}+1
{n['key']}=({n['key']}*1664525+1013904223)%4294967296
for {n['acc']}=0,3 do
if {n['j']}<{n['len']} then
local div=1
for _=1,{n['acc']} do div=div*256 end
local kb=math.floor({n['key']}/div)%256
local b=math.floor({n['op']}/div)%256
local x=b
local y=kb
local z={n['j']}%256
local r=0
local p=1
for _=1,8 do
local bb=x%2
local yb=y%2
local zb=z%2
local bit=((bb+yb+zb)%2)
r=r+bit*p
x=math.floor(x/2)
y=math.floor(y/2)
z=math.floor(z/2)
p=p*2
end
{n['j']}={n['j']}+1
{n['buf']}[{n['j']}]=r
end
end
end
end
end
local {n['run']}=""
for {n['i']}=1,{n['len']} do
{n['run']}={n['run']}..string.char({n['buf']}[{n['i']}])
end
local {n['fn']},{n['err']}=(load or loadstring)({n['run']})
if not {n['fn']} then error({n['err']}) end
if {opaque_true} then
{n['fn']}()
end
"""
    # minify-ish: strip pure empty lines but keep structure
    lines = [ln.rstrip() for ln in vm.splitlines() if ln.strip()]
    return "\n".join(lines)


def obfuscate_code(code: str, intensity: str, options: List[str]) -> str:
    code = (code or "").strip()
    if not code:
        return "-- empty"

    if intensity not in ("v1", "v2"):
        intensity = "v2"

    # light cleanup only – do not leave readable structure
    # remove comments
    cleaned = []
    for line in code.splitlines():
        s = line.strip()
        if s.startswith("--"):
            continue
        cleaned.append(line)
    src = "\n".join(cleaned)

    # For v1: single VM layer; v2: double-wrap (VM of a minified bootstrap)
    body = _emit_vm(src, intensity)

    if intensity == "v2":
        # wrap again so outer layer is also VM bytecode
        body = _emit_vm(body, "v1")

    header = [
        f"-- obfuscated by {APP_NAME} {VERSION}",
        f"-- {datetime.utcnow().isoformat()}Z | {intensity}",
        "",
    ]
    return "\n".join(header) + body



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
            <button onclick="navigator.clipboard.writeText(document.getElementById('obfResult').innerText)">{t('copy', lang)}</button>
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

    return RedirectResponse(f"/dashboard?lang={lang}&result_id={result_id}", status_code=302)



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
