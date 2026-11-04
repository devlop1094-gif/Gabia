from fastapi import FastAPI, Request, Form
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

APP_NAME = "VeilObfuscator"
VERSION = "0.3.0"

CREDIT_RATES = {
    "KRW": 100,
    "USDT": 0.01,
}

BANK_INFO = {
    "bank": "카카오뱅크",
    "account": "7777-03-0806539",
    "holder": "김시우",
}

CRYPTO_INFO = {
    "network": "TRC20",
    "currency": "USDT",
    "address": "COMING_SOON",
}

# Admin
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin1234"  # 배포 전 꼭 변경
admin_sessions = set()

BASE_COST = {
    "basic": 5,
    "strong": 12,
    "extreme": 25,
}

OPTION_COST = {
    "rename_vars": 3,
    "encrypt_strings": 5,
    "cff": 8,
    "dead_code": 4,
    "junk_code": 3,
    "anti_tamper": 6,
    "minify": 2,
    "opaque_predicates": 5,
    "proxy_functions": 4,
    "number_encrypt": 3,
}

users_db = {}
sessions = {}
pending_payments = {}

# ======================
# Language
# ======================

LANG = {
    "ko": {
        "app_name": "VeilObfuscator",
        "welcome": "VeilObfuscator에 오신 것을 환영합니다",
        "register": "회원가입",
        "login": "로그인",
        "logout": "로그아웃",
        "username": "아이디",
        "password": "비밀번호",
        "balance": "보유 크레딧",
        "charge": "크레딧 충전",
        "obfuscate": "난독화 하기",
        "bank_transfer": "계좌이체",
        "crypto": "코인 결제",
        "select_amount": "충전 금액",
        "after_transfer": "입금 후 입금자명 또는 TxHash를 입력하고 확인을 눌러주세요",
        "depositor_name": "입금자명",
        "tx_hash": "트랜잭션 해시 (TxID)",
        "confirm_payment": "결제 확인 요청",
        "insufficient_credit": "크레딧이 부족합니다. 충전이 필요합니다.",
        "obfuscate_success": "난독화가 완료되었습니다",
        "result": "난독화 결과",
        "copy": "복사하기",
        "dashboard": "대시보드",
        "code_placeholder": "여기에 Luau / Lua 코드를 붙여넣으세요",
        "intensity": "기본 강도",
        "basic": "Basic",
        "strong": "Strong",
        "extreme": "Extreme",
        "submit": "실행",
        "payment_submitted": "결제 확인 요청이 접수되었습니다. 확인 후 크레딧이 지급됩니다.",
        "already_exists": "이미 존재하는 아이디입니다",
        "invalid_login": "아이디 또는 비밀번호가 올바르지 않습니다",
        "options": "추가 옵션",
        "opt_rename": "변수/함수 이름 섞기",
        "opt_strings": "문자열 암호화",
        "opt_cff": "Control Flow Flattening",
        "opt_dead": "Dead Code 삽입",
        "opt_junk": "Junk Code 삽입",
        "opt_tamper": "Anti-Tamper",
        "opt_minify": "공백/주석 제거",
        "opt_opaque": "Opaque Predicates",
        "opt_proxy": "Proxy Functions",
        "opt_numbers": "숫자 암호화",
    },
    "en": {
        "app_name": "VeilObfuscator",
        "welcome": "Welcome to VeilObfuscator",
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
}

def t(key: str, lang: str = "ko") -> str:
    return LANG.get(lang, LANG["ko"]).get(key, key)

# ======================
# Helpers
# ======================

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def create_token() -> str:
    return secrets.token_hex(24)

def get_current_user(request: Request):
    token = request.cookies.get("session")
    if not token or token not in sessions:
        return None
    return users_db.get(sessions[token])

def calc_credits(amount: float, method: str) -> int:
    if method == "bank":
        return max(1, int(amount / CREDIT_RATES["KRW"]))
    return max(1, int(amount / CREDIT_RATES["USDT"]))

def rand_name(length: int = 8) -> str:
    return "_" + "".join(random.choices(string.ascii_letters, k=length))


# ======================
# Obfuscation Engine (with simple VM)
# ======================

def _xor_string(s: str, key: int = 0x5A) -> str:
    encoded = "".join(chr(ord(c) ^ key) for c in s)
    encoded = encoded.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "")
    return encoded

def _make_string_decryptor(key: int = 0x5A) -> str:
    return f"local function _S(s)local r=''for i=1,#s do r=r..string.char(string.byte(s,i)~{key})end return r end"

def _encrypt_number(n: int) -> str:
    a = random.randint(17, 97)
    b = n + a
    return f"({b}-{a})"

def _rand_ident(n: int = 8) -> str:
    return "_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=n))

def _generate_vm(bytecode: list, intensity: str) -> str:
    """
    Simple stack-based VM wrapper.
    bytecode items: ("PUSHSTR", str), ("PUSHNUM", int), ("CALL", name), ("RET",)
    """
    pc_name = _rand_ident(5)
    stack_name = _rand_ident(5)
    code_name = _rand_ident(6)
    op_name = _rand_ident(4)

    # Encode strings in bytecode
    key = random.randint(0x20, 0x7F)
    encrypted_chunks = []
    for item in bytecode:
        if item[0] == "PUSHSTR":
            encrypted_chunks.append((_xor_string(item[1], key), "str"))
        elif item[0] == "PUSHNUM":
            encrypted_chunks.append((str(item[1]), "num"))
        else:
            encrypted_chunks.append((item[0], "op"))

    # Build data table
    data_lines = []
    for i, (val, typ) in enumerate(encrypted_chunks):
        if typ == "str":
            data_lines.append(f"[{i+1}]=_S('{val}')")
        elif typ == "num":
            data_lines.append(f"[{i+1}]={val}")
        else:
            data_lines.append(f"[{i+1}]='{val}'")

    data_tbl = ",".join(data_lines)

    vm = f"""
{_make_string_decryptor(key)}
local {code_name}={{{data_tbl}}}
local {stack_name}={{}}
local {pc_name}=1
while {pc_name}<=#{code_name} do
local {op_name}={code_name}[{pc_name}]
{pc_name}={pc_name}+1
if type({op_name})=="string" and #{op_name}>3 and string.sub({op_name},1,1)~="_" then
-- opcode
if {op_name}=="CALL" then
local fn=table.remove({stack_name})
local arg=table.remove({stack_name})
if type(fn)=="function" then fn(arg) end
elseif {op_name}=="RET" then break
end
else
table.insert({stack_name},{op_name})
end
end
"""
    return vm.strip()

def obfuscate_code(code: str, intensity: str, options: List[str]) -> str:
    result = code
    opts = set(options or [])
    header = [
        f"-- Obfuscated by {APP_NAME} v{VERSION}",
        f"-- intensity: {intensity} | options: {', '.join(sorted(opts)) if opts else 'none'}",
        f"-- {datetime.utcnow().isoformat()}Z",
        "",
    ]

    if intensity == "strong":
        opts.update(["rename_vars", "encrypt_strings", "junk_code"])
    elif intensity == "extreme":
        opts.update(["rename_vars", "encrypt_strings", "cff", "dead_code", "junk_code", "number_encrypt", "opaque_predicates"])

    if "minify" in opts:
        lines = []
        for line in result.splitlines():
            s = line.strip()
            if s.startswith("--") or not s:
                continue
            lines.append(s)
        result = " ".join(lines)

    if "rename_vars" in opts:
        mapping = {}
        def ren(m):
            name = m.group(1)
            if name not in mapping:
                mapping[name] = _rand_ident(7)
            return "local " + mapping[name]
        result = re.sub(r"\blocal\s+([a-zA-Z_][a-zA-Z0-9_]*)", ren, result)

    if "encrypt_strings" in opts:
        key = 0x5A
        decryptor = _make_string_decryptor(key)
        def str_enc(m):
            content = m.group(2)
            if len(content) < 1:
                return m.group(0)
            return f"_S('{_xor_string(content, key)}')"
        result = re.sub(r"(['\"])(.*?)\1", str_enc, result)
        result = decryptor + chr(10) + result

    if "number_encrypt" in opts:
        def num_enc(m):
            n = int(m.group(0))
            return _encrypt_number(n) if n > 9 else m.group(0)
        result = re.sub(r"\b\d{2,}\b", num_enc, result)

    if "dead_code" in opts:
        dead_snippets = ["if false then local _d=1 end", "do local _x=nil end", "if 1>2 then return end"]
        lines = result.splitlines() or [result]
        for _ in range(min(5, max(2, len(lines)//3))):
            lines.insert(random.randint(0, len(lines)), random.choice(dead_snippets))
        result = chr(10).join(lines)

    if "junk_code" in opts:
        junk_snippets = [f"local {_rand_ident()}=math.random()", f"local {_rand_ident()}=os.clock()", f"local {_rand_ident()}={{}}"]
        lines = result.splitlines() or [result]
        for _ in range(min(4, max(2, len(lines)//4))):
            lines.insert(random.randint(0, len(lines)), random.choice(junk_snippets))
        result = chr(10).join(lines)

    if "opaque_predicates" in opts:
        result = result.replace("if ", "if (function() return true end)() and ", 1)

    if "proxy_functions" in opts:
        p = _rand_ident(6)
        result = f"local {p}=function(f,...)return f(...)end" + chr(10) + result

    if "anti_tamper" in opts:
        result = "local _t0=os.clock()" + chr(10) + "if debug and debug.getinfo then local _=debug.getinfo(1) end" + chr(10) + result

    if "cff" in opts:
        result = "local _st=0" + chr(10) + "while true do" + chr(10) + "if _st==0 then" + chr(10) + result + chr(10) + "_st=1" + chr(10) + "elseif _st==1 then break end" + chr(10) + "end"

    if intensity == "extreme" and ("cff" in opts or "encrypt_strings" in opts):
        key = random.randint(0x30, 0x6F)
        payload = _xor_string(result, key)
        result = (
            _make_string_decryptor(key) + chr(10)
            + f"local _bc=_S('{payload}')" + chr(10)
            + "local _fn,err=loadstring(_bc)" + chr(10)
            + "if _fn then _fn() else error(err) end"
        )

    return chr(10).join(header) + result


def calc_cost(intensity: str, options: List[str]) -> int:
    cost = BASE_COST.get(intensity, 12)
    for opt in options:
        cost += OPTION_COST.get(opt, 0)
    return cost

# ======================
# App
# ======================

app = FastAPI(title=APP_NAME, version=VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def base_html(content: str, lang: str = "ko", user=None):
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
    <a href="/?lang=ko">한국어</a>
    <a href="/?lang=en">English</a>
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
async def home(request: Request, lang: str = "ko"):
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
async def register_page(lang: str = "ko"):
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
async def register(username: str = Form(...), password: str = Form(...), lang: str = Form("ko")):
    username = username.strip().lower()
    if username in users_db:
        content = f"""<div class="card"><p class="error">{t('already_exists', lang)}</p>
        <a class="btn" href="/register?lang={lang}">{t('register', lang)}</a></div>"""
        return HTMLResponse(base_html(content, lang))
    users_db[username] = {
        "username": username,
        "password": hash_password(password),
        "credits": 40,
        "lang": lang,
        "results": {},
        "created_at": datetime.utcnow().isoformat(),
    }
    token = create_token()
    sessions[token] = username
    resp = RedirectResponse(f"/dashboard?lang={lang}", status_code=302)
    resp.set_cookie("session", token, httponly=True, max_age=60*60*24*30)
    return resp

@app.get("/login", response_class=HTMLResponse)
async def login_page(lang: str = "ko"):
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
async def login(username: str = Form(...), password: str = Form(...), lang: str = Form("ko")):
    username = username.strip().lower()
    user = users_db.get(username)
    if not user or user["password"] != hash_password(password):
        content = f"""<div class="card"><p class="error">{t('invalid_login', lang)}</p>
        <a class="btn" href="/login?lang={lang}">{t('login', lang)}</a></div>"""
        return HTMLResponse(base_html(content, lang))
    token = create_token()
    sessions[token] = username
    resp = RedirectResponse(f"/dashboard?lang={lang}", status_code=302)
    resp.set_cookie("session", token, httponly=True, max_age=60*60*24*30)
    return resp

@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session")
    if token in sessions:
        del sessions[token]
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie("session")
    return resp

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, lang: str = "ko", result_id: str = None, error: str = None):
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
        <h3>{t('obfuscate', lang)}</h3>
        <form method="post" action="/obfuscate">
            <input type="hidden" name="lang" value="{lang}">
            <label>{t('intensity', lang)}</label>
            <select name="intensity">
                <option value="basic">{t('basic', lang)} (5+)</option>
                <option value="strong" selected>{t('strong', lang)} (12+)</option>
                <option value="extreme">{t('extreme', lang)} (25+)</option>
            </select>

            <label>{t('options', lang)}</label>
            <div class="opts">
                <label><input type="checkbox" name="options" value="rename_vars" checked> {t('opt_rename', lang)} (+3)</label>
                <label><input type="checkbox" name="options" value="encrypt_strings" checked> {t('opt_strings', lang)} (+5)</label>
                <label><input type="checkbox" name="options" value="cff"> {t('opt_cff', lang)} (+8)</label>
                <label><input type="checkbox" name="options" value="dead_code"> {t('opt_dead', lang)} (+4)</label>
                <label><input type="checkbox" name="options" value="junk_code"> {t('opt_junk', lang)} (+3)</label>
                <label><input type="checkbox" name="options" value="anti_tamper"> {t('opt_tamper', lang)} (+6)</label>
                <label><input type="checkbox" name="options" value="minify"> {t('opt_minify', lang)} (+2)</label>
                <label><input type="checkbox" name="options" value="opaque_predicates"> {t('opt_opaque', lang)} (+5)</label>
                <label><input type="checkbox" name="options" value="proxy_functions"> {t('opt_proxy', lang)} (+4)</label>
                <label><input type="checkbox" name="options" value="number_encrypt"> {t('opt_numbers', lang)} (+3)</label>
            </div>

            <label>Code</label>
            <textarea name="code" required placeholder="{t('code_placeholder', lang)}"></textarea>
            <button type="submit">{t('submit', lang)}</button>
        </form>
    </div>
    <div class="card">
        <h3>{t('charge', lang)}</h3>
        <form method="post" action="/charge">
            <input type="hidden" name="lang" value="{lang}">
            <label>Method</label>
            <select name="method">
                <option value="bank">{t('bank_transfer', lang)} (카카오뱅크)</option>
                <option value="crypto">{t('crypto', lang)} (USDT)</option>
            </select>
            <label>{t('select_amount', lang)}</label>
            <input type="number" name="amount" value="10000" min="1000" step="1000">
            <button type="submit">{t('charge', lang)}</button>
        </form>
    </div>"""
    return base_html(content, lang, user)

@app.post("/obfuscate")
async def do_obfuscate(request: Request, code: str = Form(...), intensity: str = Form("strong"), lang: str = Form("ko")):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(f"/login?lang={lang}", status_code=302)

    form = await request.form()
    options = form.getlist("options")

    cost = calc_cost(intensity, options)
    if user["credits"] < cost:
        return RedirectResponse(
            f"/dashboard?lang={lang}&error={t('insufficient_credit', lang)} (need {cost})",
            status_code=302
        )

    user["credits"] -= cost
    result = obfuscate_code(code, intensity, options)

    result_id = str(uuid.uuid4())[:8]
    if "results" not in user:
        user["results"] = {}
    user["results"][result_id] = result

    return RedirectResponse(f"/dashboard?lang={lang}&result_id={result_id}", status_code=302)

@app.post("/charge")
async def create_charge(request: Request, amount: float = Form(...), method: str = Form(...), lang: str = Form("ko")):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(f"/login?lang={lang}", status_code=302)

    payment_id = str(uuid.uuid4())[:8]
    credits = calc_credits(amount, method)
    pending_payments[payment_id] = {
        "payment_id": payment_id,
        "username": user["username"],
        "method": method,
        "amount": amount,
        "credits": credits,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
    }

    if method == "bank":
        body = f"""
        <div class="card">
            <h3>{t('bank_transfer', lang)}</h3>
            <p><strong>{BANK_INFO['bank']}</strong></p>
            <p style="font-size:1.4rem;letter-spacing:1px">{BANK_INFO['account']}</p>
            <p>예금주: {BANK_INFO['holder']}</p>
            <p class="muted">금액: {amount:,.0f}원 → {credits} 크레딧</p>
            <p class="muted">Payment ID: <code>{payment_id}</code></p>
            <hr style="border-color:#334155;margin:20px 0">
            <p>{t('after_transfer', lang)}</p>
            <form method="post" action="/confirm-payment">
                <input type="hidden" name="lang" value="{lang}">
                <input type="hidden" name="payment_id" value="{payment_id}">
                <label>{t('depositor_name', lang)}</label>
                <input name="depositor_name" required placeholder="입금자명">
                <button type="submit">{t('confirm_payment', lang)}</button>
            </form>
            <p style="margin-top:16px"><a href="/dashboard?lang={lang}" class="btn btn-outline">← Dashboard</a></p>
        </div>"""
    else:
        body = f"""
        <div class="card">
            <h3>{t('crypto', lang)}</h3>
            <p>{CRYPTO_INFO['currency']} ({CRYPTO_INFO['network']})</p>
            <p style="font-size:1.1rem;word-break:break-all">{CRYPTO_INFO['address']}</p>
            <p class="muted">Amount: {amount} {CRYPTO_INFO['currency']} → {credits} credits</p>
            <p class="muted">Payment ID: <code>{payment_id}</code></p>
            <hr style="border-color:#334155;margin:20px 0">
            <p>{t('after_transfer', lang)}</p>
            <form method="post" action="/confirm-payment">
                <input type="hidden" name="lang" value="{lang}">
                <input type="hidden" name="payment_id" value="{payment_id}">
                <label>{t('tx_hash', lang)}</label>
                <input name="tx_hash" required placeholder="Transaction Hash">
                <button type="submit">{t('confirm_payment', lang)}</button>
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
    lang: str = Form("ko")
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(f"/login?lang={lang}", status_code=302)

    payment = pending_payments.get(payment_id)
    if not payment or payment["username"] != user["username"]:
        return RedirectResponse(f"/dashboard?lang={lang}&error=Payment not found", status_code=302)

    if payment["status"] == "pending":
        payment["status"] = "pending"  # stays pending until admin approves
        payment["depositor_name"] = depositor_name
        payment["tx_hash"] = tx_hash
        payment["submitted_at"] = datetime.utcnow().isoformat()
        # credits added only after /admin approve

    msg = {
        "ko": "입금 확인 요청이 접수되었습니다. 관리자 승인 후 크레딧이 지급됩니다.",
        "en": "Payment proof submitted. Credits will be added after admin approval."
    }.get(lang, "Submitted. Waiting for admin approval.")

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
    if token and token in admin_sessions:
        return True
    return False


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, lang: str = "ko"):
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
    pending = [p for p in pending_payments.values() if p.get("status") == "pending"]
    completed = [p for p in pending_payments.values() if p.get("status") == "completed"]
    completed = sorted(completed, key=lambda x: x.get("created_at", ""), reverse=True)[:20]

    rows = ""
    if not pending:
        rows = "<p class='muted'>대기 중인 결제가 없습니다.</p>"
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
                    <button type="submit">승인 (크레딧 지급)</button>
                </form>
                <form method="post" action="/admin/reject" style="display:inline;margin-left:8px">
                    <input type="hidden" name="payment_id" value="{p['payment_id']}">
                    <input type="hidden" name="lang" value="{lang}">
                    <button type="submit" class="btn-outline" style="background:#7f1d1d;border-color:#7f1d1d">거절</button>
                </form>
            </div>"""

    done_rows = ""
    for p in completed:
        done_rows += f"<p class='muted'>{p['payment_id']} · {p['username']} · {p['credits']}cr · {p.get('created_at','')}</p>"

    content = f"""
    <div class="card">
        <h2>Admin Dashboard</h2>
        <p class="muted">대기 결제 승인 / 거절</p>
        <p><a href="/admin/logout" class="btn btn-outline">Admin Logout</a></p>
    </div>
    <div class="card">
        <h3>Pending ({len(pending)})</h3>
        {rows}
    </div>
    <div class="card">
        <h3>Recent Completed</h3>
        {done_rows or "<p class='muted'>없음</p>"}
    </div>"""
    return base_html(content, lang)


@app.post("/admin/login")
async def admin_login(username: str = Form(...), password: str = Form(...), lang: str = Form("ko")):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        token = create_token()
        admin_sessions.add(token)
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
    if token in admin_sessions:
        admin_sessions.discard(token)
    resp = RedirectResponse("/admin", status_code=302)
    resp.delete_cookie("admin_session")
    return resp


@app.post("/admin/approve")
async def admin_approve(request: Request, payment_id: str = Form(...), lang: str = Form("ko")):
    if not get_admin(request):
        return RedirectResponse("/admin", status_code=302)

    payment = pending_payments.get(payment_id)
    if not payment:
        return RedirectResponse(f"/admin?lang={lang}", status_code=302)

    if payment["status"] == "pending":
        payment["status"] = "completed"
        payment["approved_at"] = datetime.utcnow().isoformat()
        payment["approved_by"] = "admin"
        username = payment["username"]
        if username in users_db:
            users_db[username]["credits"] += payment["credits"]

    return RedirectResponse(f"/admin?lang={lang}", status_code=302)


@app.post("/admin/reject")
async def admin_reject(request: Request, payment_id: str = Form(...), lang: str = Form("ko")):
    if not get_admin(request):
        return RedirectResponse("/admin", status_code=302)

    payment = pending_payments.get(payment_id)
    if payment and payment["status"] == "pending":
        payment["status"] = "rejected"
        payment["rejected_at"] = datetime.utcnow().isoformat()

    return RedirectResponse(f"/admin?lang={lang}", status_code=302)



# ======================
# Run (Render compatible)
# ======================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"{APP_NAME} v{VERSION}")
    print(f"Bank: {BANK_INFO['bank']} {BANK_INFO['account']} ({BANK_INFO['holder']})")
    print(f"Listening on port {port}")
    print(f"Admin: /admin  (user={kimsiwoo} / pass={kimsiwoo})")
    uvicorn.run(app, host="0.0.0.0", port=port)
