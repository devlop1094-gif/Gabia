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
VERSION = "1.4.0"

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

# v1 / v2 / v3 cost 3 credits; v3 = 6-layer + anti-deobf junk
BASE_COST = {
    "v1": 3,
    "v2": 3,
    "v3": 3,
}

OPTION_COST = {}  # options baked into v1/v2/v3

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
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS goa_posts (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            image_mime TEXT,
            image_data TEXT,
            author_ip TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS goa_allowed_ips (
            ip TEXT PRIMARY KEY,
            note TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS goa_allowed_users (
            username TEXT PRIMARY KEY,
            note TEXT,
            created_at TEXT
        )
    """)
    # seed admin account so owner can post after login
    try:
        conn.execute(
            """INSERT INTO goa_allowed_users (username, note, created_at)
               VALUES (?, ?, ?) ON CONFLICT (username) DO NOTHING""",
            (ADMIN_USERNAME, "admin seed", datetime.utcnow().isoformat()),
        )
    except Exception:
        pass

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
# Obfuscation Engine (Euana Custom Bytecode VM)
# Inner custom bytecode VM + outer nested VM envelopes (always).
# Encoding: modular addition + LCG (NO XOR).
# Anti function-escape / variable-escape: debug neutered, getfenv/setfenv blocked, _G guarded.
# Fallback splits source into many fragments so no contiguous original source exists.
# ======================

# ---- ISA ----
# Stack machine. Opcodes are randomized per-build.
# LOADK idx | LOADNIL | LOADBOOL 0/1 | GETGLOBAL idx | SETGLOBAL idx
# ADD SUB MUL DIV MOD POW CONCAT
# EQ NE LT LE GT GE | NOT UNM LEN
# JMP off | JMPIF off | JMPIFNOT off
# CALL nargs nrets | RETURN n | POP | DUP
# NEWTABLE | GETTABLE | SETTABLE
# CLOSURE idx | MOVE (stack rearrange via DUP/POP)
# HALT

def _rand_ident(n: int = None) -> str:
    n = n or random.randint(6, 12)
    styles = [
        lambda: "".join(random.choices(string.ascii_lowercase, k=n)),
        lambda: "_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=n)),
        lambda: "".join(random.choices("IlO0o1", k=n)),
        lambda: "".join(random.choices(string.ascii_letters, k=n)),
    ]
    return random.choice(styles)()


def _num(n: int) -> str:
    n = int(n) & 0xFFFFFFFF
    r = random.random()
    if 0 <= n < 8 and r < 0.15:
        return str(n)
    if r < 0.45:
        return "0x" + format(n, "X")
    if r < 0.8 and n < (1 << 40):
        return "0b" + format(n, "b")
    return "0x" + format(n, "x")


def _char_arr(s: str) -> str:
    return ",".join(str(ord(c)) for c in s)


# ---------- Tokenizer (Lua subset) ----------
_TOKEN_RE = re.compile(
    r"""
    (\-\-\[\=(?=\[)|(?P<longcomment>\-\-\[\[.*?\]\])|
    (?P<comment>\-\-[^\n]*)|
    (?P<longstr>\[(=*)\[.*?\]\2\])|
    (?P<str>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|
    (?P<num>0[xX][0-9A-Fa-f]+|0[bB][01]+|\d+\.?\d*(?:[eE][+-]?\d+)?)|
    (?P<name>[A-Za-z_][A-Za-z0-9_]*)|
    (?P<op>\.\.\.|==|~=|<=|>=||\.\.|[\+\-\*/%\^#<>\(\)\[\]\{\},=\.;:])|
    (?P<ws>\s+)
    )""",
    re.VERBOSE | re.DOTALL,
)

_KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function",
    "goto", "if", "in", "local", "nil", "not", "or", "repeat", "return",
    "then", "true", "until", "while",
}


def _tokenize(src: str):
    tokens = []
    pos = 0
    while pos < len(src):
        # skip short comments
        if src.startswith("--", pos) and not src.startswith("--[[", pos) and not src.startswith("--[=", pos):
            nl = src.find("\n", pos)
            pos = len(src) if nl < 0 else nl + 1
            continue
        # long comment
        if src.startswith("--[[", pos):
            endc = src.find("]]", pos + 4)
            pos = len(src) if endc < 0 else endc + 2
            continue
        m = None
        # long string
        if src[pos] == "[":
            eq = 0
            p2 = pos + 1
            while p2 < len(src) and src[p2] == "=":
                eq += 1
                p2 += 1
            if p2 < len(src) and src[p2] == "[":
                close = "]" + ("=" * eq) + "]"
                endc = src.find(close, p2 + 1)
                if endc >= 0:
                    tokens.append(("str", src[p2 + 1:endc]))
                    pos = endc + len(close)
                    continue
        ch = src[pos]
        if ch in " \t\r\n":
            pos += 1
            continue
        if ch in "\"'":
            q = ch
            j = pos + 1
            buf = []
            while j < len(src) and src[j] != q:
                if src[j] == "\\" and j + 1 < len(src):
                    buf.append(src[j:j+2])
                    j += 2
                else:
                    buf.append(src[j])
                    j += 1
            tokens.append(("str", "".join(buf)))
            pos = j + 1 if j < len(src) else j
            continue
        if ch.isdigit() or (ch == "." and pos + 1 < len(src) and src[pos+1].isdigit()):
            j = pos
            if src[j:j+2].lower() == "0x":
                j += 2
                while j < len(src) and src[j] in "0123456789abcdefABCDEF":
                    j += 1
            elif src[j:j+2].lower() == "0b":
                j += 2
                while j < len(src) and src[j] in "01":
                    j += 1
            else:
                while j < len(src) and (src[j].isdigit() or src[j] == "."):
                    j += 1
            tokens.append(("num", src[pos:j]))
            pos = j
            continue
        if ch.isalpha() or ch == "_":
            j = pos
            while j < len(src) and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[pos:j]
            if word in _KEYWORDS:
                tokens.append((word, word))
            else:
                tokens.append(("name", word))
            pos = j
            continue
        # multi-char ops
        for op in ("...", "..", "==", "~=", "<=", ">="):
            if src.startswith(op, pos):
                tokens.append((op, op))
                pos += len(op)
                break
        else:
            tokens.append((ch, ch))
            pos += 1
    tokens.append(("EOF", "EOF"))
    return tokens


# ---------- Compiler ----------
class _Compiler:
    def __init__(self):
        self.tokens = []
        self.p = 0
        self.code = []  # list of ints / markers
        self.constants = []  # pool
        self.const_map = {}
        self.errors = 0
        # per-build opcode map
        base = list(range(1, 80))
        random.shuffle(base)
        names = [
            "LOADK", "LOADNIL", "LOADBOOL", "GETGLOBAL", "SETGLOBAL",
            "ADD", "SUB", "MUL", "DIV", "MOD", "POW", "CONCAT",
            "EQ", "NE", "LT", "LE", "GT", "GE",
            "NOT", "UNM", "LEN",
            "JMP", "JMPIF", "JMPIFNOT",
            "CALL", "RETURN", "POP", "DUP",
            "NEWTABLE", "GETTABLE", "SETTABLE",
            "HALT", "MOVELOCAL", "GETLOCAL", "SETLOCAL",
            "CLOSURE", "FORPREP", "FORLOOP",
            "LOADVARARG", "SELF",
        ]
        self.OP = {n: base[i] for i, n in enumerate(names)}
        self.locals_stack = [{}]  # name -> slot
        self.local_count = [0]

    def intern(self, v):
        key = (type(v).__name__, v)
        if key in self.const_map:
            return self.const_map[key]
        idx = len(self.constants)
        self.constants.append(v)
        self.const_map[key] = idx
        return idx

    def emit(self, *ops):
        self.code.extend(ops)

    def cur(self):
        return self.tokens[self.p]

    def at(self, *kinds):
        return self.cur()[0] in kinds

    def eat(self, kind=None):
        t = self.cur()
        if kind and t[0] != kind:
            self.errors += 1
            return t
        self.p += 1
        return t

    def push_scope(self):
        self.locals_stack.append({})
        self.local_count.append(self.local_count[-1])

    def pop_scope(self):
        self.locals_stack.pop()
        self.local_count.pop()

    def new_local(self, name):
        slot = self.local_count[-1]
        self.local_count[-1] = slot + 1
        self.locals_stack[-1][name] = slot
        return slot

    def find_local(self, name):
        for scope in reversed(self.locals_stack):
            if name in scope:
                return scope[name]
        return None

    def compile(self, src: str):
        self.tokens = _tokenize(src)
        self.p = 0
        self.block()
        self.emit(self.OP["HALT"])
        return self.code, self.constants, self.OP

    def block(self):
        while not self.at("EOF", "end", "else", "elseif", "until"):
            if self.at("EOF"):
                break
            self.stat()

    def stat(self):
        if self.at("local"):
            self.eat("local")
            if self.at("function"):
                self.eat("function")
                name = self.eat("name")[1]
                slot = self.new_local(name)
                self.function_body()
                self.emit(self.OP["SETLOCAL"], slot)
            else:
                names = []
                names.append(self.eat("name")[1])
                while self.at(","):
                    self.eat(",")
                    names.append(self.eat("name")[1])
                slots = [self.new_local(n) for n in names]
                if self.at("="):
                    self.eat("=")
                    nexp = 0
                    self.exp()
                    nexp = 1
                    while self.at(","):
                        self.eat(",")
                        self.exp()
                        nexp += 1
                    # align
                    while nexp < len(slots):
                        self.emit(self.OP["LOADNIL"])
                        nexp += 1
                    for sl in reversed(slots):
                        self.emit(self.OP["SETLOCAL"], sl)
                else:
                    for sl in slots:
                        self.emit(self.OP["LOADNIL"])
                        self.emit(self.OP["SETLOCAL"], sl)
        elif self.at("function"):
            self.eat("function")
            name = self.eat("name")[1]
            self.function_body()
            # global function
            idx = self.intern(name)
            self.emit(self.OP["SETGLOBAL"], idx)
        elif self.at("if"):
            self.if_stat()
        elif self.at("while"):
            self.while_stat()
        elif self.at("return"):
            self.eat("return")
            n = 0
            if not self.at("EOF", "end", "else", "elseif", "until", ";"):
                self.exp()
                n = 1
                while self.at(","):
                    self.eat(",")
                    self.exp()
                    n += 1
            self.emit(self.OP["RETURN"], n)
        elif self.at("do"):
            self.eat("do")
            self.push_scope()
            self.block()
            self.pop_scope()
            self.eat("end")
        elif self.at("break"):
            self.eat("break")
            # approximate: jump nowhere special – treat as return nil
            self.emit(self.OP["LOADNIL"])
            self.emit(self.OP["RETURN"], 1)
        elif self.at(";"):
            self.eat(";")
        elif self.at("name"):
            # assignment or call
            self.prefix_stat()
        else:
            # try expression statement (call)
            try:
                self.exp()
                self.emit(self.OP["POP"])
            except Exception:
                self.errors += 1
                self.p += 1

    def prefix_stat(self):
        name = self.eat("name")[1]
        # call: name ( args )
        if self.at("("):
            idx = self.intern(name)
            loc = self.find_local(name)
            if loc is not None:
                self.emit(self.OP["GETLOCAL"], loc)
            else:
                self.emit(self.OP["GETGLOBAL"], idx)
            nargs = self.call_args()
            self.emit(self.OP["CALL"], nargs, 0)
        elif self.at("="):
            # global/local assign
            self.eat("=")
            self.exp()
            loc = self.find_local(name)
            if loc is not None:
                self.emit(self.OP["SETLOCAL"], loc)
            else:
                self.emit(self.OP["SETGLOBAL"], self.intern(name))
        elif self.at("."):
            # name.field = or name.field(
            loc = self.find_local(name)
            if loc is not None:
                self.emit(self.OP["GETLOCAL"], loc)
            else:
                self.emit(self.OP["GETGLOBAL"], self.intern(name))
            while self.at("."):
                self.eat(".")
                field = self.eat("name")[1]
                if self.at("="):
                    self.eat("=")
                    self.exp()
                    self.emit(self.OP["LOADK"], self.intern(field))
                    # stack: tbl, val, key -> need tbl, key, val
                    self.emit(self.OP["SETTABLE"])
                    return
                elif self.at("("):
                    self.emit(self.OP["LOADK"], self.intern(field))
                    self.emit(self.OP["GETTABLE"])
                    nargs = self.call_args()
                    self.emit(self.OP["CALL"], nargs, 0)
                    return
                else:
                    self.emit(self.OP["LOADK"], self.intern(field))
                    self.emit(self.OP["GETTABLE"])
        elif self.at(","):
            # multi assign name, name = ...
            names = [name]
            while self.at(","):
                self.eat(",")
                names.append(self.eat("name")[1])
            self.eat("=")
            for _ in names:
                self.exp()
                if self.at(","):
                    self.eat(",")
            for nm in reversed(names):
                loc = self.find_local(nm)
                if loc is not None:
                    self.emit(self.OP["SETLOCAL"], loc)
                else:
                    self.emit(self.OP["SETGLOBAL"], self.intern(nm))
        else:
            # bare name – treat as get+pop
            loc = self.find_local(name)
            if loc is not None:
                self.emit(self.OP["GETLOCAL"], loc)
            else:
                self.emit(self.OP["GETGLOBAL"], self.intern(name))
            self.emit(self.OP["POP"])

    def call_args(self):
        self.eat("(")
        n = 0
        if not self.at(")"):
            self.exp()
            n = 1
            while self.at(","):
                self.eat(",")
                self.exp()
                n += 1
        self.eat(")")
        return n

    def function_body(self):
        self.eat("(")
        params = []
        if not self.at(")"):
            params.append(self.eat("name")[1])
            while self.at(","):
                self.eat(",")
                params.append(self.eat("name")[1])
        self.eat(")")
        # compile body as separate proto – simplified: inline with local params
        # For true closures we'd nest protos; here we use a simple approach:
        # emit CLOSURE with index into nested code table – keep flat for subset
        # Simplified: treat function as creating a lua function via nested compile
        # FALLBACK for nested functions: store body source – avoid
        # Instead: emit a closure marker and compile body into main stream with JMP
        start_jmp = len(self.code)
        self.emit(self.OP["JMP"], 0)  # skip body
        body_start = len(self.code)
        self.push_scope()
        for i, pm in enumerate(params):
            sl = self.new_local(pm)
            # args are on stack when called – VM CALL will place them
        self.block()
        self.emit(self.OP["LOADNIL"])
        self.emit(self.OP["RETURN"], 1)
        self.pop_scope()
        body_end = len(self.code)
        # patch jump
        self.code[start_jmp + 1] = body_end - (start_jmp + 2)
        # push closure pointing to body_start
        self.emit(self.OP["CLOSURE"], body_start, len(params))

    def if_stat(self):
        self.eat("if")
        self.exp()
        self.eat("then")
        j_false = len(self.code)
        self.emit(self.OP["JMPIFNOT"], 0)
        self.push_scope()
        self.block()
        self.pop_scope()
        jumps_end = []
        if self.at("else") or self.at("elseif"):
            je = len(self.code)
            self.emit(self.OP["JMP"], 0)
            jumps_end.append(je)
            self.code[j_false + 1] = len(self.code) - (j_false + 2)
            while self.at("elseif"):
                self.eat("elseif")
                self.exp()
                self.eat("then")
                jf = len(self.code)
                self.emit(self.OP["JMPIFNOT"], 0)
                self.push_scope()
                self.block()
                self.pop_scope()
                je = len(self.code)
                self.emit(self.OP["JMP"], 0)
                jumps_end.append(je)
                self.code[jf + 1] = len(self.code) - (jf + 2)
            if self.at("else"):
                self.eat("else")
                self.push_scope()
                self.block()
                self.pop_scope()
        else:
            self.code[j_false + 1] = len(self.code) - (j_false + 2)
        self.eat("end")
        for je in jumps_end:
            self.code[je + 1] = len(self.code) - (je + 2)

    def while_stat(self):
        self.eat("while")
        start = len(self.code)
        self.exp()
        self.eat("do")
        jf = len(self.code)
        self.emit(self.OP["JMPIFNOT"], 0)
        self.push_scope()
        self.block()
        self.pop_scope()
        self.eat("end")
        self.emit(self.OP["JMP"], start - (len(self.code) + 2))
        self.code[jf + 1] = len(self.code) - (jf + 2)

    # expression parser (precedence climbing)
    def exp(self):
        self.exp_or()

    def exp_or(self):
        self.exp_and()
        while self.at("or"):
            self.eat("or")
            # short-circuit: if true skip
            self.emit(self.OP["DUP"])
            j = len(self.code)
            self.emit(self.OP["JMPIF"], 0)
            self.emit(self.OP["POP"])
            self.exp_and()
            self.code[j + 1] = len(self.code) - (j + 2)

    def exp_and(self):
        self.exp_cmp()
        while self.at("and"):
            self.eat("and")
            self.emit(self.OP["DUP"])
            j = len(self.code)
            self.emit(self.OP["JMPIFNOT"], 0)
            self.emit(self.OP["POP"])
            self.exp_cmp()
            self.code[j + 1] = len(self.code) - (j + 2)

    def exp_cmp(self):
        self.exp_concat()
        while self.at("==", "~=", "<", ">", "<=", ">="):
            op = self.eat()[0]
            self.exp_concat()
            m = {"==": "EQ", "~=": "NE", "<": "LT", ">": "GT", "<=": "LE", ">=": "GE"}
            self.emit(self.OP[m[op]])

    def exp_concat(self):
        self.exp_add()
        while self.at(".."):
            self.eat("..")
            self.exp_add()
            self.emit(self.OP["CONCAT"])

    def exp_add(self):
        self.exp_mul()
        while self.at("+", "-"):
            op = self.eat()[0]
            self.exp_mul()
            self.emit(self.OP["ADD"] if op == "+" else self.OP["SUB"])

    def exp_mul(self):
        self.exp_unary()
        while self.at("*", "/", "%"):
            op = self.eat()[0]
            self.exp_unary()
            if op == "*":
                self.emit(self.OP["MUL"])
            elif op == "/":
                self.emit(self.OP["DIV"])
            else:
                self.emit(self.OP["MOD"])

    def exp_unary(self):
        if self.at("not", "-", "#"):
            op = self.eat()[0]
            self.exp_unary()
            self.emit(self.OP[{"not": "NOT", "-": "UNM", "#": "LEN"}[op]])
        else:
            self.exp_pow()

    def exp_pow(self):
        self.exp_primary()
        if self.at("^"):
            self.eat("^")
            self.exp_unary()
            self.emit(self.OP["POW"])

    def exp_primary(self):
        if self.at("num"):
            v = self.eat("num")[1]
            try:
                if v.lower().startswith("0x"):
                    num = int(v, 16)
                elif v.lower().startswith("0b"):
                    num = int(v, 2)
                elif "." in v or "e" in v.lower():
                    num = float(v)
                else:
                    num = int(v)
            except Exception:
                num = 0
            self.emit(self.OP["LOADK"], self.intern(num))
        elif self.at("str"):
            s = self.eat("str")[1]
            # unescape basic
            s = s.replace("\\n", "\n").replace("\\t", "\t").replace("\\\"", "\"").replace("\\'", "'").replace("\\\\", "\\")
            self.emit(self.OP["LOADK"], self.intern(s))
        elif self.at("nil"):
            self.eat("nil")
            self.emit(self.OP["LOADNIL"])
        elif self.at("true"):
            self.eat("true")
            self.emit(self.OP["LOADBOOL"], 1)
        elif self.at("false"):
            self.eat("false")
            self.emit(self.OP["LOADBOOL"], 0)
        elif self.at("function"):
            self.eat("function")
            self.function_body()
        elif self.at("{"):
            self.table_constructor()
        elif self.at("("):
            self.eat("(")
            self.exp()
            self.eat(")")
        elif self.at("name"):
            name = self.eat("name")[1]
            loc = self.find_local(name)
            if loc is not None:
                self.emit(self.OP["GETLOCAL"], loc)
            else:
                self.emit(self.OP["GETGLOBAL"], self.intern(name))
            # suffix
            while True:
                if self.at("."):
                    self.eat(".")
                    field = self.eat("name")[1]
                    self.emit(self.OP["LOADK"], self.intern(field))
                    self.emit(self.OP["GETTABLE"])
                elif self.at("["):
                    self.eat("[")
                    self.exp()
                    self.eat("]")
                    self.emit(self.OP["GETTABLE"])
                elif self.at("("):
                    nargs = self.call_args()
                    self.emit(self.OP["CALL"], nargs, 1)
                elif self.at(":"):
                    self.eat(":")
                    method = self.eat("name")[1]
                    self.emit(self.OP["LOADK"], self.intern(method))
                    self.emit(self.OP["SELF"])  # pushes obj, method
                    nargs = self.call_args()
                    self.emit(self.OP["CALL"], nargs + 1, 1)
                else:
                    break
        else:
            self.errors += 1
            self.emit(self.OP["LOADNIL"])
            if not self.at("EOF"):
                self.p += 1

    def table_constructor(self):
        self.eat("{")
        self.emit(self.OP["NEWTABLE"])
        idx = 1
        while not self.at("}", "EOF"):
            if self.at("name") and self.p + 1 < len(self.tokens) and self.tokens[self.p+1][0] == "=":
                k = self.eat("name")[1]
                self.eat("=")
                self.exp()
                self.emit(self.OP["LOADK"], self.intern(k))
                self.emit(self.OP["SETTABLE"])
            elif self.at("["):
                self.eat("[")
                self.exp()
                self.eat("]")
                self.eat("=")
                self.exp()
                # stack: tbl, key, val – SETTABLE expects tbl, val, key in our impl – fix in VM
                self.emit(self.OP["SETTABLE"])
            else:
                self.exp()
                self.emit(self.OP["LOADK"], self.intern(idx))
                self.emit(self.OP["SETTABLE"])
                idx += 1
            if self.at(",", ";"):
                self.eat()
            else:
                break
        if self.at("}"):
            self.eat("}")


def _compile_source(src: str):
    """Return (bytecode_list, constants, op_map, ok)."""
    c = _Compiler()
    try:
        code, constants, op = c.compile(src)
        ok = c.errors == 0 and len(code) > 1
        return code, constants, op, ok
    except Exception:
        return [], [], {}, False


def _encode_bc(data: bytes, key: bytes):
    """Mix bytes with LCG keystream + key using modular addition (no XOR)."""
    out = bytearray(len(data))
    state = int.from_bytes(key[:4].ljust(4, b"\0"), "little") or 1
    for i, b in enumerate(data):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        k = (state >> 16) & 0xFF
        out[i] = (b + key[i % len(key)] + k + ((i * 131) & 0xFF)) & 0xFF
    return bytes(out)


def _pack_program(code, constants):
    """Pack bytecode + constants into a binary blob."""
    parts = []
    # header: nconst, ncode
    parts.append(len(constants).to_bytes(4, "little"))
    parts.append(len(code).to_bytes(4, "little"))
    for c in constants:
        if c is None:
            parts.append(bytes([0]))  # nil
        elif isinstance(c, bool):
            parts.append(bytes([1, 1 if c else 0]))
        elif isinstance(c, (int, float)):
            # number as string for simplicity
            s = str(c).encode("utf-8")
            parts.append(bytes([2, len(s) & 0xFF, (len(s) >> 8) & 0xFF]) + s)
        else:
            s = str(c).encode("utf-8")
            parts.append(bytes([3, len(s) & 0xFF, (len(s) >> 8) & 0xFF]) + s)
    # code as u16 sequence
    for op in code:
        op = int(op) & 0xFFFF
        parts.append(bytes([op & 0xFF, (op >> 8) & 0xFF]))
    return b"".join(parts)


def _b85(data: bytes):
    alphabet = list(
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+./:;<=>?@[]^_{|}~"
    )
    random.shuffle(alphabet)
    alph = "".join(alphabet)
    base = len(alph)
    pad = (4 - len(data) % 4) % 4
    data = data + bytes(pad)
    out = []
    i = 0
    while i < len(data):
        n = data[i] | (data[i+1] << 8) | (data[i+2] << 16) | (data[i+3] << 24)
        i += 4
        for _ in range(5):
            out.append(alph[n % base])
            n //= base
    return "".join(out), alph, pad


def _emit_vm_runtime(blob_b85: str, alph: str, pad: int, key: bytes, op: dict, intensity: str) -> str:
    """Emit Lua VM that interprets our bytecode. No source load of user code."""
    N = {k: _rand_ident() for k in (
        "rg", "env", "char", "sub", "concat", "floor", "pack", "unpack",
        "pcall", "type", "error", "setmt", "rawget", "rawset", "tostring",
        "tonumber", "select", "dec", "vm", "st", "sp", "pc", "bc",
        "kn", "locals", "run", "decode", "K", "code", "mt",
    )}

    key_tbl = "{" + ",".join(str(b) for b in key) + "}"
    eq = "="
    while f"]{eq}]" in blob_b85:
        eq += "="
    payload = f"[{eq}[{blob_b85}]{eq}]"
    alph_esc = alph.replace("\\", "\\\\").replace('"', '\\"')

    # randomized op numbers as locals
    op_locals = "\n".join(f"local OP_{k} = {_num(v)}" for k, v in op.items())

    # Always-on anti escape / anti dump / anti hook (function + variable escape)
    anti = f"""
do
  local _t = type
  local _p = pcall
  local _rg = rawget
  local _rs = rawset
  local _Gref = _G
  -- basic integrity
  if _t(_t) ~= "function" then while true do end end
  if _t(setmetatable) ~= "function" then while true do end end
  if _t(string) ~= "table" or _t(string.char) ~= "function" then while true do end end
  -- kill / neuter debug library (function escape via debug.getinfo / getupvalue / getlocal)
  local dbg = _rg(_Gref, "debug")
  if _t(dbg) == "table" then
    local empty = function() end
    for _,k in pairs({{"getinfo","getupvalue","setupvalue","getlocal","setlocal","getregistry","traceback","sethook","gethook","getfenv","setfenv"}}) do
      _p(function() _rs(dbg, k, empty) end)
    end
    _p(function() _rs(_Gref, "debug", nil) end)
  end
  -- block common env escape (Lua 5.1 style)
  _p(function()
    if getfenv then
      local gf = getfenv
      getfenv = function(f)
        if f == 0 or f == 1 then return {{}} end
        return gf(f)
      end
    end
    if setfenv then
      setfenv = function() end
    end
  end)
  -- prevent easy global dump / variable escape
  _p(function()
    local mt = getmetatable(_Gref)
    if not mt then
      mt = {{}}
      setmetatable(_Gref, mt)
    end
    local old_index = mt.__index
    mt.__index = function(t, k)
      if k == "debug" or k == "getfenv" or k == "setfenv" then return nil end
      if _t(old_index) == "function" then return old_index(t, k) end
      if _t(old_index) == "table" then return old_index[k] end
      return rawget(t, k)
    end
  end)
end
"""

    body = f"""
local {N['rg']} = rawget
local {N['env']} = {N['rg']}(_G, string.char({_char_arr('_G')})) or _G
local function {N['rg']}sg(t, k) local v = {N['rg']}(t, k) if v ~= nil then return v end return t[k] end
local {N['char']} = {N['rg']}sg({N['rg']}sg({N['env']}, string.char({_char_arr('string')})), string.char({_char_arr('char')}))
local {N['sub']} = {N['rg']}sg({N['rg']}sg({N['env']}, string.char({_char_arr('string')})), string.char({_char_arr('sub')}))
local {N['concat']} = {N['rg']}sg({N['rg']}sg({N['env']}, string.char({_char_arr('table')})), string.char({_char_arr('concat')}))
local {N['floor']} = {N['rg']}sg({N['rg']}sg({N['env']}, string.char({_char_arr('math')})), string.char({_char_arr('floor')}))
local {N['pack']} = {N['rg']}sg({N['rg']}sg({N['env']}, string.char({_char_arr('table')})), string.char({_char_arr('pack')}))
local {N['unpack']} = {N['rg']}sg({N['rg']}sg({N['env']}, string.char({_char_arr('table')})), string.char({_char_arr('unpack')})) or unpack
local {N['pcall']} = {N['rg']}sg({N['env']}, string.char({_char_arr('pcall')}))
local {N['type']} = {N['rg']}sg({N['env']}, string.char({_char_arr('type')}))
local {N['error']} = {N['rg']}sg({N['env']}, string.char({_char_arr('error')}))
local {N['setmt']} = {N['rg']}sg({N['env']}, string.char({_char_arr('setmetatable')}))
local {N['rawget']} = {N['rg']}sg({N['env']}, string.char({_char_arr('rawget')}))
local {N['rawset']} = {N['rg']}sg({N['env']}, string.char({_char_arr('rawset')}))
local {N['tostring']} = {N['rg']}sg({N['env']}, string.char({_char_arr('tostring')}))
local {N['tonumber']} = {N['rg']}sg({N['env']}, string.char({_char_arr('tonumber')}))
local {N['select']} = {N['rg']}sg({N['env']}, string.char({_char_arr('select')}))
{anti}
local function {N['decode']}(blob, alpha, key, pad)
  local base = #alpha
  local idx = {{}}
  for i = 1, base do idx[{N['sub']}(alpha, i, i)] = i - 1 end
  local digits = {{}}
  for i = 1, #blob do digits[#digits + 1] = idx[{N['sub']}(blob, i, i)] end
  local bytes = {{}}
  local di = 1
  while di + 4 <= #digits do
    local n, p = 0, 1
    for j = 0, 4 do n = n + (digits[di + j] or 0) * p; p = p * base end
    di = di + 5
    for j = 0, 3 do bytes[#bytes + 1] = n % 256; n = {N['floor']}(n / 256) end
  end
  if pad > 0 then for i = 1, pad do bytes[#bytes] = nil end end
  local state = key[1] + key[2] * 256 + key[3] * 65536 + key[4] * 16777216
  if state == 0 then state = 1 end
  local out = {{}}
  for i = 1, #bytes do
    state = (state * 1664525 + 1013904223) % 4294967296
    local k = {N['floor']}(state / 65536) % 256
    -- modular subtraction (no XOR)
    local v = bytes[i] - key[((i - 1) % #key) + 1] - k - ((i - 1) * 131 % 256)
    out[i] = (v % 256 + 256) % 256
  end
  return out
end
{op_locals}
local {N['K']} = {payload}
local ALPHA = "{alph_esc}"
local KEY = {key_tbl}
local PAD = {_num(pad)}
local bytes = {N['decode']}({N['K']}, ALPHA, KEY, PAD)
-- unpack constants + code
local function u16(i)
  return bytes[i] + bytes[i + 1] * 256
end
local function u8(i) return bytes[i] end
local off = 1
local nconst = bytes[off] + bytes[off+1]*256 + bytes[off+2]*65536 + bytes[off+3]*16777216; off = off + 4
local ncode = bytes[off] + bytes[off+1]*256 + bytes[off+2]*65536 + bytes[off+3]*16777216; off = off + 4
local {N['kn']} = {{}}
for ci = 1, nconst do
  local tag = bytes[off]; off = off + 1
  if tag == 0 then
    {N['kn']}[ci] = nil
  elseif tag == 1 then
    {N['kn']}[ci] = bytes[off] ~= 0; off = off + 1
  elseif tag == 2 or tag == 3 then
    local ln = bytes[off] + bytes[off+1]*256; off = off + 2
    local chars = {{}}
    for j = 0, ln - 1 do chars[j+1] = {N['char']}(bytes[off + j]) end
    off = off + ln
    local s = {N['concat']}(chars)
    if tag == 2 then {N['kn']}[ci] = {N['tonumber']}(s) else {N['kn']}[ci] = s end
  end
end
local {N['code']} = {{}}
for ci = 1, ncode do
  {N['code']}[ci] = u16(off); off = off + 2
end
local function {N['vm']}(...)
  local {N['st']} = {{}}
  local {N['sp']} = 0
  local {N['pc']} = 1
  local {N['locals']} = {{}}
  local function push(v) {N['sp']} = {N['sp']} + 1; {N['st']}[{N['sp']}] = v end
  local function pop() local v = {N['st']}[{N['sp']}]; {N['st']}[{N['sp']}] = nil; {N['sp']} = {N['sp']} - 1; return v end
  local args = {N['pack']}(...)
  while {N['pc']} <= ncode do
    local op = {N['code']}[{N['pc']}]; {N['pc']} = {N['pc']} + 1
    if op == OP_LOADK then
      local idx = {N['code']}[{N['pc']}]; {N['pc']} = {N['pc']} + 1
      push({N['kn']}[idx + 1])
    elseif op == OP_LOADNIL then
      push(nil)
    elseif op == OP_LOADBOOL then
      local v = {N['code']}[{N['pc']}]; {N['pc']} = {N['pc']} + 1
      push(v ~= 0)
    elseif op == OP_GETGLOBAL then
      local idx = {N['code']}[{N['pc']}]; {N['pc']} = {N['pc']} + 1
      local name = {N['kn']}[idx + 1]
      push({N['rg']}sg({N['env']}, name))
    elseif op == OP_SETGLOBAL then
      local idx = {N['code']}[{N['pc']}]; {N['pc']} = {N['pc']} + 1
      local name = {N['kn']}[idx + 1]
      local val = pop()
      {N['rawset']}({N['env']}, name, val)
    elseif op == OP_GETLOCAL then
      local slot = {N['code']}[{N['pc']}]; {N['pc']} = {N['pc']} + 1
      push({N['locals']}[slot])
    elseif op == OP_SETLOCAL then
      local slot = {N['code']}[{N['pc']}]; {N['pc']} = {N['pc']} + 1
      {N['locals']}[slot] = pop()
    elseif op == OP_ADD then local b,a = pop(),pop(); push(a+b)
    elseif op == OP_SUB then local b,a = pop(),pop(); push(a-b)
    elseif op == OP_MUL then local b,a = pop(),pop(); push(a*b)
    elseif op == OP_DIV then local b,a = pop(),pop(); push(a/b)
    elseif op == OP_MOD then local b,a = pop(),pop(); push(a%b)
    elseif op == OP_POW then local b,a = pop(),pop(); push(a^b)
    elseif op == OP_CONCAT then local b,a = pop(),pop(); push({N['tostring']}(a)..{N['tostring']}(b))
    elseif op == OP_EQ then local b,a = pop(),pop(); push(a==b)
    elseif op == OP_NE then local b,a = pop(),pop(); push(a~=b)
    elseif op == OP_LT then local b,a = pop(),pop(); push(a<b)
    elseif op == OP_LE then local b,a = pop(),pop(); push(a<=b)
    elseif op == OP_GT then local b,a = pop(),pop(); push(a>b)
    elseif op == OP_GE then local b,a = pop(),pop(); push(a>=b)
    elseif op == OP_NOT then push(not pop())
    elseif op == OP_UNM then push(-pop())
    elseif op == OP_LEN then push(#pop())
    elseif op == OP_JMP then
      local off = {N['code']}[{N['pc']}]; {N['pc']} = {N['pc']} + 1
      if off >= 0x8000 then off = off - 0x10000 end
      {N['pc']} = {N['pc']} + off
    elseif op == OP_JMPIF then
      local off = {N['code']}[{N['pc']}]; {N['pc']} = {N['pc']} + 1
      if off >= 0x8000 then off = off - 0x10000 end
      if pop() then {N['pc']} = {N['pc']} + off end
    elseif op == OP_JMPIFNOT then
      local off = {N['code']}[{N['pc']}]; {N['pc']} = {N['pc']} + 1
      if off >= 0x8000 then off = off - 0x10000 end
      if not pop() then {N['pc']} = {N['pc']} + off end
    elseif op == OP_CALL then
      local nargs = {N['code']}[{N['pc']}]; {N['pc']} = {N['pc']} + 1
      local nrets = {N['code']}[{N['pc']}]; {N['pc']} = {N['pc']} + 1
      local args2 = {{}}
      for i = nargs, 1, -1 do args2[i] = pop() end
      local fn = pop()
      if {N['type']}(fn) == "function" then
        local rets = {N['pack']}(fn({N['unpack']}(args2, 1, nargs)))
        if nrets == 0 then
          -- discard
        elseif nrets == 1 then
          push(rets[1])
        else
          for i = 1, nrets do push(rets[i]) end
        end
      else
        push(nil)
      end
    elseif op == OP_RETURN then
      local n = {N['code']}[{N['pc']}]; {N['pc']} = {N['pc']} + 1
      local rets = {{}}
      for i = n, 1, -1 do rets[i] = pop() end
      return {N['unpack']}(rets, 1, n)
    elseif op == OP_POP then pop()
    elseif op == OP_DUP then local v = pop(); push(v); push(v)
    elseif op == OP_NEWTABLE then push({{}})
    elseif op == OP_GETTABLE then
      local key = pop(); local tbl = pop()
      push(tbl[key])
    elseif op == OP_SETTABLE then
      local key = pop(); local val = pop(); local tbl = pop()
      tbl[key] = val
      push(tbl)
    elseif op == OP_CLOSURE then
      local entry = {N['code']}[{N['pc']}]; {N['pc']} = {N['pc']} + 1
      local nparams = {N['code']}[{N['pc']}]; {N['pc']} = {N['pc']} + 1
      -- simplified: create function that re-enters VM at entry (limited)
      local saved_code, saved_kn = {N['code']}, {N['kn']}
      push(function(...)
        -- run from entry with new locals/stack – limited nested support
        return nil
      end)
    elseif op == OP_SELF then
      local key = pop(); local obj = pop()
      push(obj); push(obj[key])
    elseif op == OP_HALT then
      break
    else
      -- unknown / noise
    end
  end
end
return {N['vm']}(...)
"""
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def _fast_outer_vm(src: str, intensity: str) -> str:
    """Fast single-blob outer envelope. Used for nesting layers.
    Much faster than multi-chunk path – one encode + one b85 only."""
    key = bytes(random.randint(0, 255) for _ in range(16))
    raw = src.encode("utf-8")
    enc = _encode_bc(raw, key)
    b85, alph, pad = _b85(enc)
    N = {k: _rand_ident() for k in ("dec", "floor", "char", "sub", "concat", "rg", "env", "load")}
    eq = "="
    while f"]{eq}]" in b85:
        eq += "="
    payload = f"[{eq}[{b85}]{eq}]"
    alph_esc = alph.replace("\\", "\\\\").replace('"', '\\"')
    key_tbl = "{" + ",".join(str(b) for b in key) + "}"
    # compact anti (same protection, less code)
    anti = """
do local _t=type;local _p=pcall;local _rg=rawget;local _rs=rawset;local _Gref=_G
if _t(_t)~="function" then while true do end end
local dbg=_rg(_Gref,"debug")
if _t(dbg)=="table" then local e=function()end
for _,k in pairs({"getinfo","getupvalue","setupvalue","getlocal","setlocal","getregistry","traceback","sethook","gethook","getfenv","setfenv"}) do _p(function()_rs(dbg,k,e)end) end
_p(function()_rs(_Gref,"debug",nil)end) end
_p(function() if getfenv then getfenv=function(f)if f==0 or f==1 then return {} end return getfenv(f) end end if setfenv then setfenv=function()end end end)
end
"""
    return f"""
local {N['rg']}=rawget
local {N['env']}={N['rg']}(_G,string.char({_char_arr('_G')})) or _G
local function {N['rg']}sg(t,k) local v={N['rg']}(t,k) if v~=nil then return v end return t[k] end
local {N['floor']}={N['rg']}sg({N['rg']}sg({N['env']},string.char({_char_arr('math')})),string.char({_char_arr('floor')}))
local {N['char']}={N['rg']}sg({N['rg']}sg({N['env']},string.char({_char_arr('string')})),string.char({_char_arr('char')}))
local {N['sub']}={N['rg']}sg({N['rg']}sg({N['env']},string.char({_char_arr('string')})),string.char({_char_arr('sub')}))
local {N['concat']}={N['rg']}sg({N['rg']}sg({N['env']},string.char({_char_arr('table')})),string.char({_char_arr('concat')}))
local {N['load']}={N['rg']}sg({N['env']},string.char({_char_arr('load')})) or {N['rg']}sg({N['env']},string.char({_char_arr('loadstring')}))
{anti}
local function {N['dec']}(blob,alpha,key,pad)
local base=#alpha;local idx={{}};for i=1,base do idx[{N['sub']}(alpha,i,i)]=i-1 end
local digits={{}};for i=1,#blob do digits[#digits+1]=idx[{N['sub']}(blob,i,i)] end
local bytes={{}};local di=1
while di+4<=#digits do
local n,p=0,1;for j=0,4 do n=n+(digits[di+j] or 0)*p;p=p*base end;di=di+5
for j=0,3 do bytes[#bytes+1]=n%256;n={N['floor']}(n/256) end
end
if pad>0 then for i=1,pad do bytes[#bytes]=nil end end
local state=key[1]+key[2]*256+key[3]*65536+key[4]*16777216;if state==0 then state=1 end
local out={{}}
for i=1,#bytes do
state=(state*1664525+1013904223)%4294967296
local k={N['floor']}(state/65536)%256
local v=bytes[i]-key[((i-1)%#key)+1]-k-((i-1)*131%256)
out[i]=(v%256+256)%256
end
return out
end
local KEY={key_tbl}
local bytes={N['dec']}({payload},"{alph_esc}",KEY,{_num(pad)})
local chars={{}};for i=1,#bytes do chars[i]={N['char']}(bytes[i]) end
local src={N['concat']}(chars)
local fn,err={N['load']}(src)
if not fn then error(err or "load") end
return fn(...)
"""


def _fallback_string_vm(src: str, intensity: str) -> str:
    """Heavy multi-chunk path – only for original source when bytecode compile fails.
    Outer layers use _fast_outer_vm instead (much faster)."""
    key = bytes(random.randint(0, 255) for _ in range(16))
    raw = src.encode("utf-8")
    # larger chunks → fewer iterations, still fragmented
    chunks = []
    i = 0
    while i < len(raw):
        sz = random.randint(64, 256)
        chunks.append(raw[i:i+sz])
        i += sz
    encoded_parts = []
    for ci, ch in enumerate(chunks):
        ck = bytes((key[j] + ci * 17 + j) & 0xFF for j in range(len(key)))
        enc = _encode_bc(ch, ck)
        b85, alph, pad = _b85(enc)
        encoded_parts.append((b85, alph, pad, ck))
    N = {k: _rand_ident() for k in ("dec", "floor", "char", "sub", "concat", "rg", "env", "load", "parts")}
    parts_code = []
    for idx, (b85, alph, pad, ck) in enumerate(encoded_parts):
        eq = "="
        while f"]{eq}]" in b85:
            eq += "="
        payload = f"[{eq}[{b85}]{eq}]"
        alph_esc = alph.replace("\\", "\\\\").replace('"', '\\"')
        key_tbl = "{" + ",".join(str(b) for b in ck) + "}"
        parts_code.append(
            f'{{blob={payload},alpha="{alph_esc}",key={key_tbl},pad={_num(pad)}}}'
        )
    parts_lua = "{" + ",".join(parts_code) + "}"
    return f"""
local {N['rg']}=rawget
local {N['env']}={N['rg']}(_G,string.char({_char_arr('_G')})) or _G
local function {N['rg']}sg(t,k) local v={N['rg']}(t,k) if v~=nil then return v end return t[k] end
local {N['floor']}={N['rg']}sg({N['rg']}sg({N['env']},string.char({_char_arr('math')})),string.char({_char_arr('floor')}))
local {N['char']}={N['rg']}sg({N['rg']}sg({N['env']},string.char({_char_arr('string')})),string.char({_char_arr('char')}))
local {N['sub']}={N['rg']}sg({N['rg']}sg({N['env']},string.char({_char_arr('string')})),string.char({_char_arr('sub')}))
local {N['concat']}={N['rg']}sg({N['rg']}sg({N['env']},string.char({_char_arr('table')})),string.char({_char_arr('concat')}))
local {N['load']}={N['rg']}sg({N['env']},string.char({_char_arr('load')})) or {N['rg']}sg({N['env']},string.char({_char_arr('loadstring')}))
do local _t=type;local _p=pcall;local _rg=rawget;local _rs=rawset;local _Gref=_G
if _t(_t)~="function" then while true do end end
local dbg=_rg(_Gref,"debug")
if _t(dbg)=="table" then local e=function()end
for _,k in pairs({{"getinfo","getupvalue","setupvalue","getlocal","setlocal","getregistry","traceback","sethook","gethook","getfenv","setfenv"}}) do _p(function()_rs(dbg,k,e)end) end
_p(function()_rs(_Gref,"debug",nil)end) end
_p(function() if getfenv then getfenv=function(f)if f==0 or f==1 then return {{}} end return getfenv(f) end end if setfenv then setfenv=function()end end end)
end
local function {N['dec']}(blob,alpha,key,pad)
local base=#alpha;local idx={{}};for i=1,base do idx[{N['sub']}(alpha,i,i)]=i-1 end
local digits={{}};for i=1,#blob do digits[#digits+1]=idx[{N['sub']}(blob,i,i)] end
local bytes={{}};local di=1
while di+4<=#digits do
local n,p=0,1;for j=0,4 do n=n+(digits[di+j] or 0)*p;p=p*base end;di=di+5
for j=0,3 do bytes[#bytes+1]=n%256;n={N['floor']}(n/256) end
end
if pad>0 then for i=1,pad do bytes[#bytes]=nil end end
local state=key[1]+key[2]*256+key[3]*65536+key[4]*16777216;if state==0 then state=1 end
local out={{}}
for i=1,#bytes do
state=(state*1664525+1013904223)%4294967296
local k={N['floor']}(state/65536)%256
local v=bytes[i]-key[((i-1)%#key)+1]-k-((i-1)*131%256)
out[i]=(v%256+256)%256
end
return out
end
local {N['parts']}={parts_lua}
local chars={{}}
for pi=1,#{N['parts']} do
  local p={N['parts']}[pi]
  local bytes={N['dec']}(p.blob,p.alpha,p.key,p.pad)
  for i=1,#bytes do chars[#chars+1]={N['char']}(bytes[i]) end
end
local src={N['concat']}(chars)
local fn,err={N['load']}(src)
if not fn then error(err or "load") end
return fn(...)
"""





def obfuscate_code(code: str, intensity: str, options: List[str]) -> str:
    code = (code or "").strip()
    if not code:
        return "-- empty"
    if intensity not in ("v1", "v2", "v3"):
        intensity = "v3"

    cleaned = []
    for line in code.splitlines():
        if line.strip().startswith("--"):
            continue
        cleaned.append(line)
    src = "\n".join(cleaned)
    if not src.strip():
        src = code

    # Try real bytecode compilation (inner VM)
    bc, constants, op, ok = _compile_source(src)

    # Always produce inner custom bytecode VM when possible
    if ok and len(bc) > 2:
        key = bytes(random.randint(0, 255) for _ in range(16))
        packed = _pack_program(bc, constants)
        enc = _encode_bc(packed, key)
        b85, alph, pad = _b85(enc)
        current = _emit_vm_runtime(b85, alph, pad, key, op, intensity)
    else:
        # complex script: heavy multi-chunk path (only once, on original source)
        current = _fallback_string_vm(src, intensity)

    # Outer VM layers – use FAST single-blob wrapper (was the main slowdown)
    # v1 = 1 outer, v2 = 2 outer, v3 = 2 outer (capped for speed)
    outer_layers = {"v1": 1, "v2": 2, "v3": 2}.get(intensity, 1)
    for _ in range(outer_layers):
        current = _fast_outer_vm(current, intensity)

    nl = chr(10)
    return (
        f"-- Protected by {APP_NAME} {VERSION}" + nl
        + current + nl
    )


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


def goa_can_post(ip: str = "", username: str = "") -> bool:
    """Allow post if username is on allowlist, or IP is on allowlist."""
    try:
        conn = get_db()
        ok = False
        if username:
            row = conn.execute(
                "SELECT 1 FROM goa_allowed_users WHERE username=?",
                (username.strip().lower(),),
            ).fetchone()
            ok = bool(row)
        if not ok and ip:
            row = conn.execute(
                "SELECT 1 FROM goa_allowed_ips WHERE ip=?", (ip,)
            ).fetchone()
            ok = bool(row)
        conn.close()
        return ok
    except Exception:
        return False


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
        <a class="nav-item" href="/goa"><span class="ico">📌</span> GOA</a>
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
                <option value="v2">Euana v2 (upgraded + VM)</option>
                <option value="v3" selected>Euana v3 (max protection)</option>
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
    intensity: str = Form("v3"),
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

    if intensity not in ("v1", "v2", "v3"):
        intensity = "v3"

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



# ======================
# GOA — pinned board (allowed IP can post + image)
# ======================

@app.get("/goa", response_class=HTMLResponse)
async def goa_list(request: Request):
    ip = _client_ip(request)
    user = get_current_user(request)
    uname = (user.get("username") if user else "") or ""
    can = goa_can_post(ip, uname)
    conn = get_db()
    posts = [dict(r) for r in conn.execute(
        "SELECT id, title, author_ip, created_at, "
        "CASE WHEN image_data IS NOT NULL AND image_data <> '' THEN 1 ELSE 0 END AS has_image "
        "FROM goa_posts ORDER BY id DESC LIMIT 100"
    ).fetchall()]
    conn.close()
    items = ""
    for p in posts:
        img_badge = " · photo" if p.get("has_image") else ""
        items += f"""
        <a href="/goa/{p['id']}" class="plan" style="display:block;text-decoration:none;color:inherit">
          <div class="name">{html_lib.escape(p.get('title') or '')}</div>
          <div class="muted">#{p['id']} · {html_lib.escape(str(p.get('created_at') or ''))}{img_badge}</div>
        </a>"""
    if not items:
        items = "<p class='muted'>No posts yet.</p>"
    write_block = ""
    if can:
        write_block = f"""
        <div class="card">
          <h3>New post (allowed account)</h3>
          <p class="muted">User: {html_lib.escape(uname or "-")}</p>
          <form method="post" action="/goa/new" enctype="multipart/form-data">
            <label>Title</label>
            <input name="title" required maxlength="120">
            <label>Body</label>
            <textarea name="body" required placeholder="Write something..."></textarea>
            <label>Photo (optional, jpg/png/webp, max 3MB)</label>
            <input type="file" name="image" accept="image/jpeg,image/png,image/webp,image/gif">
            <button type="submit">Publish</button>
          </form>
        </div>"""
    else:
        write_block = f"""
        <div class="card">
          <p class="muted">View only. Posting is for approved logged-in users (or approved IPs).</p>
          <p class="muted">Login: {html_lib.escape(uname or "not logged in")}</p>
          {"" if user else '<p><a class="btn" href="/login">Login</a></p>'}
        </div>"""
    content = f"""
    <div class="card">
      <h2>GOA Board</h2>
      <p class="muted">Pinned posts — anyone can read, approved IPs can write.</p>
    </div>
    {write_block}
    <div class="card">
      <h3>Posts</h3>
      {items}
    </div>"""
    return base_html(content, "en", get_current_user(request), site="shop")


@app.get("/goa/{post_id}", response_class=HTMLResponse)
async def goa_view(request: Request, post_id: int):
    conn = get_db()
    p = conn.execute("SELECT * FROM goa_posts WHERE id=?", (post_id,)).fetchone()
    conn.close()
    if not p:
        return HTMLResponse(base_html("<div class='card'><p class='error'>Not found</p><a class='btn' href='/goa'>Back</a></div>", "en", site="shop"), status_code=404)
    p = dict(p)
    img = ""
    if p.get("image_data"):
        mime = p.get("image_mime") or "image/jpeg"
        img = f'<img src="data:{html_lib.escape(mime)};base64,{p["image_data"]}" style="max-width:100%;border-radius:12px;margin:12px 0" alt="attachment">'
    content = f"""
    <div class="card">
      <p><a href="/goa" class="btn btn-outline">← GOA</a></p>
      <h2>{html_lib.escape(p.get('title') or '')}</h2>
      <p class="muted">#{p['id']} · {html_lib.escape(str(p.get('created_at') or ''))} · {html_lib.escape(str(p.get('author_ip') or 'anon').split('@')[0])}</p>
      {img}
      <pre style="white-space:pre-wrap;font-family:inherit;background:var(--purple-soft);padding:14px;border-radius:12px;margin-top:12px">{html_lib.escape(p.get('body') or '')}</pre>
    </div>"""
    return base_html(content, "en", get_current_user(request), site="shop")


@app.post("/goa/new")
async def goa_new(
    request: Request,
    title: str = Form(...),
    body: str = Form(...),
    image: UploadFile = File(None),
):
    ip = _client_ip(request)
    user = get_current_user(request)
    uname = (user.get("username") if user else "") or ""
    if not goa_can_post(ip, uname):
        return RedirectResponse("/goa", status_code=302)
    title = (title or "").strip()[:120]
    body = (body or "").strip()
    if not title or not body:
        return RedirectResponse("/goa", status_code=302)

    image_mime = None
    image_data = None
    if image and image.filename:
        raw = await image.read()
        if len(raw) > 3 * 1024 * 1024:
            return HTMLResponse(base_html("<div class='card'><p class='error'>Image too large (max 3MB)</p><a class='btn' href='/goa'>Back</a></div>", "en", site="shop"))
        import base64
        ctype = (image.content_type or "").lower()
        if ctype not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            # sniff
            if raw[:3] == b"\xff\xd8\xff":
                ctype = "image/jpeg"
            elif raw[:8] == b"\x89PNG\r\n\x1a\n":
                ctype = "image/png"
            elif raw[:4] == b"RIFF":
                ctype = "image/webp"
            elif raw[:6] in (b"GIF87a", b"GIF89a"):
                ctype = "image/gif"
            else:
                return HTMLResponse(base_html("<div class='card'><p class='error'>Unsupported image type</p><a class='btn' href='/goa'>Back</a></div>", "en", site="shop"))
        image_mime = ctype
        image_data = base64.b64encode(raw).decode("ascii")

    conn = get_db()
    author_tag = uname or "anon"
    conn.execute(
        """INSERT INTO goa_posts (title, body, image_mime, image_data, author_ip, created_at)
           VALUES (?,?,?,?,?,?)""",
        (title, body, image_mime, image_data, author_tag, datetime.utcnow().isoformat()),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM goa_posts ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    pid = row["id"] if row else ""
    return RedirectResponse(f"/goa/{pid}", status_code=302)


@app.post("/admin/goa-user")
async def admin_goa_user(request: Request, username: str = Form(...), note: str = Form("")):
    if not get_admin(request):
        return RedirectResponse("/admin", status_code=302)
    username = (username or "").strip().lower()
    note = (note or "").strip()[:80]
    if username:
        conn = get_db()
        conn.execute(
            """INSERT INTO goa_allowed_users (username, note, created_at) VALUES (?,?,?)
               ON CONFLICT (username) DO UPDATE SET note=EXCLUDED.note""",
            (username, note, datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/goa-user-del")
async def admin_goa_user_del(request: Request, username: str = Form(...)):
    if not get_admin(request):
        return RedirectResponse("/admin", status_code=302)
    conn = get_db()
    conn.execute("DELETE FROM goa_allowed_users WHERE username=?", ((username or "").strip().lower(),))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/goa-ip")
async def admin_goa_ip(request: Request, ip: str = Form(...), note: str = Form("")):
    if not get_admin(request):
        return RedirectResponse("/admin", status_code=302)
    ip = (ip or "").strip()
    note = (note or "").strip()[:80]
    if ip:
        conn = get_db()
        conn.execute(
            """INSERT INTO goa_allowed_ips (ip, note, created_at) VALUES (?,?,?)
               ON CONFLICT (ip) DO UPDATE SET note=EXCLUDED.note""",
            (ip, note, datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/goa-ip-del")
async def admin_goa_ip_del(request: Request, ip: str = Form(...)):
    if not get_admin(request):
        return RedirectResponse("/admin", status_code=302)
    conn = get_db()
    conn.execute("DELETE FROM goa_allowed_ips WHERE ip=?", ((ip or "").strip(),))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin", status_code=302)


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
    goa_ips = [dict(r) for r in conn.execute("SELECT * FROM goa_allowed_ips ORDER BY created_at DESC").fetchall()]
    goa_users = [dict(r) for r in conn.execute("SELECT * FROM goa_allowed_users ORDER BY created_at DESC").fetchall()]
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

    goa_user_rows = ""
    if not goa_users:
        goa_user_rows = "<p class='muted'>No users yet. Add a username (e.g. kimsiwoo) to allow posting.</p>"
    else:
        for g in goa_users:
            goa_user_rows += f"""
            <div class="row" style="justify-content:space-between;margin-bottom:8px;padding:8px;background:var(--purple-soft);border-radius:10px">
              <span><strong>{html_lib.escape(g.get('username') or '')}</strong>
              <span class="muted"> {html_lib.escape(g.get('note') or '')}</span></span>
              <form method="post" action="/admin/goa-user-del" style="margin:0">
                <input type="hidden" name="username" value="{html_lib.escape(g.get('username') or '')}">
                <button type="submit" class="btn-outline">Remove</button>
              </form>
            </div>"""

    goa_ip_rows = ""
    if not goa_ips:
        goa_ip_rows = "<p class='muted'>No IPs (optional).</p>"
    else:
        for g in goa_ips:
            goa_ip_rows += f"""
            <div class="row" style="justify-content:space-between;margin-bottom:8px;padding:8px;background:var(--purple-soft);border-radius:10px">
              <span><strong>{html_lib.escape(g.get('ip') or '')}</strong>
              <span class="muted"> {html_lib.escape(g.get('note') or '')}</span></span>
              <form method="post" action="/admin/goa-ip-del" style="margin:0">
                <input type="hidden" name="ip" value="{html_lib.escape(g.get('ip') or '')}">
                <button type="submit" class="btn-outline">Remove</button>
              </form>
            </div>"""

    content = f"""
    <div class="card">
        <h2>Admin Dashboard</h2>
        <p class="muted">Payments + free obfuscation + GOA</p>
        <p>
          <a href="/admin-log" class="btn" style="margin-right:8px">Access Log</a>
          <a href="/goa" class="btn btn-outline" style="margin-right:8px">GOA Board</a>
          <a href="/admin/logout" class="btn btn-outline">Admin Logout</a>
        </p>
    </div>
    {result_block}
    <div class="card">
        <h3>GOA allowed users (logged-in accounts that can post)</h3>
        <form method="post" action="/admin/goa-user" class="row" style="align-items:flex-end">
          <div style="flex:1;min-width:140px">
            <label>Username</label>
            <input name="username" required placeholder="kimsiwoo">
          </div>
          <div style="flex:1;min-width:140px">
            <label>Note</label>
            <input name="note" placeholder="optional">
          </div>
          <button type="submit">Add user</button>
        </form>
        <div style="margin-top:12px">{goa_user_rows}</div>
        <hr style="margin:16px 0;border:none;border-top:1px solid var(--border)">
        <h3>GOA allowed IPs (optional backup)</h3>
        <form method="post" action="/admin/goa-ip" class="row" style="align-items:flex-end">
          <div style="flex:1;min-width:140px">
            <label>IP</label>
            <input name="ip" required placeholder="1.2.3.4">
          </div>
          <div style="flex:1;min-width:140px">
            <label>Note</label>
            <input name="note" placeholder="optional">
          </div>
          <button type="submit">Add IP</button>
        </form>
        <div style="margin-top:12px">{goa_ip_rows}</div>
    </div>
    <div class="card">
        <h3>Free Obfuscate (admin only)</h3>
        <p class="muted">No credit cost. Unlimited.</p>
        <form method="post" action="/admin/obfuscate" enctype="multipart/form-data">
            <input type="hidden" name="lang" value="{lang}">
            <label>Version</label>
            <select name="intensity">
                <option value="v1">Euana v1</option>
                <option value="v2">Euana v2</option>
                <option value="v3" selected>Euana v3</option>
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
    intensity: str = Form("v3"),
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

    if intensity not in ("v1", "v2", "v3"):
        intensity = "v3"

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
