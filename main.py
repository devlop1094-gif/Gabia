import os, secrets, json
from datetime import datetime
from functools import wraps
from flask import Flask, request, redirect, session, flash, send_file, abort, get_flashed_messages, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# .env 지원 (선택)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "daon-class-2026-secret")

# CORS
CORS(app, resources={
    r"/api/*": {
        "origins": [
            "https://daonshop.cloud",
            "https://www.daonshop.cloud",
            
            "http://localhost:5000",
            "http://127.0.0.1:5000",
        ],
        "supports_credentials": True,
    }
})

db_url = os.environ.get("DATABASE_URL", "")
if db_url:
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    # Render 등에서 psycopg2 사용하도록 명시
    if db_url.startswith("postgresql://") and "+psycopg" not in db_url and "+psycopg2" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///daon.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
os.makedirs("uploads", exist_ok=True)
db = SQLAlchemy(app)

# ===== 은행 정보 =====
BANK_NAME = "카카오뱅크"
BANK_ACCOUNT = "7777-03-0806539"
BANK_HOLDER = "김시우"


# ===== 상담 봇 (규칙 기반 FAQ - API 크레딧 없음) =====
FAQ_RESPONSES = [
    {
        "keywords": ["입금", "계좌", "은행", "송금", "무통장", "결제 방법", "결제방법", "어떻게 내", "돈"],
        "reply": "무통장 입금으로 결제해 주세요.\n\n🏦 은행: 카카오뱅크\n계좌번호: 7777-03-0806539\n예금주: 김시우\n\n금액을 정확히 입금해 주시면 확인 후 '내 강의'에서 PDF를 받으실 수 있습니다."
    },
    {
        "keywords": ["가격", "얼마", "비용", "금액", "원"],
        "reply": "현재 판매 중인 강의 가격은 다음과 같습니다.\n\n• 유튜브 100만 기법 - 99,000원\n• 1달 300 기법 - 79,000원\n• 엑셀 업무 자동화 - 59,000원\n• 네이버 블로그 자동화 - 69,000원\n\n상세 페이지에서 확인하실 수 있어요!"
    },
    {
        "keywords": ["유튜브", "100만", "구독"],
        "reply": "「유튜브 100만 기법」은 유튜브 채널을 100만 구독자까지 성장시키는 실전 기법 강의입니다.\n가격: 99,000원\n\n구매 후 PDF로 바로 받아보실 수 있어요."
    },
    {
        "keywords": ["1달", "300", "한달"],
        "reply": "「1달 300 기법」은 단 한 달 만에 결과를 만드는 300가지 실전 기법 강의입니다.\n가격: 79,000원"
    },
    {
        "keywords": ["엑셀", "자동화", "업무"],
        "reply": "「엑셀 업무 자동화」는 반복되는 엑셀 업무를 자동화하는 실무 테크닉 강의입니다.\n가격: 59,000원"
    },
    {
        "keywords": ["네이버", "블로그"],
        "reply": "「네이버 블로그 자동화」는 네이버 블로그 운영을 자동화해서 트래픽과 수익을 만드는 방법 강의입니다.\n가격: 69,000원"
    },
    {
        "keywords": ["구매", "사는법", "사는 방법", "어떻게 사", "주문"],
        "reply": "구매 방법:\n1. 회원가입 / 로그인\n2. 원하는 강의 '상세보기' → '구매하기'\n3. 안내된 계좌로 입금\n4. 관리자 확인 후 '내 강의'에서 PDF 다운로드\n\n이미 구매한 강의는 다시 구매할 수 없습니다."
    },
    {
        "keywords": ["pdf", "다운로드", "다운", "파일"],
        "reply": "결제(입금)가 확인되면 '내 강의' 메뉴에서 PDF를 다운로드할 수 있습니다.\n아직 입금 대기 중이라면 조금만 기다려 주세요!"
    },
    {
        "keywords": ["로그인", "회원가입", "가입", "계정"],
        "reply": "우측 상단에서 '회원가입' 또는 '로그인'을 할 수 있습니다.\n가입 후 강의를 구매하고 '내 강의'에서 PDF를 받으세요."
    },
    {
        "keywords": ["관리자", "문의", "연락", "고객센터", "헬프"],
        "reply": "추가 문의가 필요하시면 관리자에게 직접 문의해 주세요.\n입금 확인이나 특별한 요청은 관리자 확인이 필요합니다."
    },
    {
        "keywords": ["로블록스", "roblox", "로블", "계정", "계정 구매", "계정사"],
        "reply": "로블록스 계정은 /roblox 페이지에서 구매하실 수 있습니다.\n\n🏦 은행: 카카오뱅크\n계좌번호: 7777-03-0806539\n예금주: 김시우\n\n원하는 계정을 선택 후 입금해 주시면 확인 후 계정 정보를 전달해 드립니다."
    },
    {
        "keywords": ["안녕", "하이", "헬로", "ㅎㅇ", "안녕하세요"],
        "reply": "안녕하세요! 다온 클래스 상담봇입니다 😊\n강의 안내, 가격, 입금 방법, 구매 방법, 로블록스 계정 등 궁금한 점을 편하게 물어보세요."
    },
]

DEFAULT_REPLY = "죄송해요, 정확히 이해하지 못했어요.\n\n이런 내용을 물어보실 수 있어요:\n• 입금 / 계좌번호\n• 강의 가격\n• 구매 방법\n• PDF 다운로드\n• 특정 강의 소개\n\n다시 한 번 물어봐 주세요!"

def get_bot_reply(message: str) -> str:
    msg = (message or "").lower().strip()
    if not msg:
        return DEFAULT_REPLY
    for item in FAQ_RESPONSES:
        for kw in item["keywords"]:
            if kw in msg:
                return item["reply"]
    return DEFAULT_REPLY


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), default="")
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    def set_password(self, pw): self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    price = db.Column(db.Integer, nullable=False)
    pdf_filename = db.Column(db.String(300), default="")
    is_active = db.Column(db.Boolean, default=True)
    stock = db.Column(db.Integer, default=999)  # 재고 (로블록스 계정 등)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(64), unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"))
    amount = db.Column(db.Integer)
    status = db.Column(db.String(20), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)
    user = db.relationship("User", backref="orders")
    product = db.relationship("Product", backref="orders")

with app.app_context():
    db.create_all()

    # 기존 DB에 stock 컬럼이 없으면 추가 (Render 등 기존 테이블 대응)
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(db.engine)
        cols = [c["name"] for c in inspector.get_columns("product")]
        if "stock" not in cols:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE product ADD COLUMN stock INTEGER DEFAULT 999"))
            print("[migrate] product.stock column added")
    except Exception as e:
        print(f"[migrate] stock column check/add skipped: {e}")

    # 관리자 계정 강제 생성/업데이트 (kimsiwoo / kimsiwoo)
    admin = User.query.filter_by(username="kimsiwoo").first()
    if not admin:
        admin = User(username="kimsiwoo", email="admin@daonshop.cloud", is_admin=True)
        admin.set_password("kimsiwoo")
        db.session.add(admin)
    else:
        admin.is_admin = True
        admin.set_password("kimsiwoo")
    db.session.commit()

    if Product.query.count() == 0:
        for t,d,p in [
            ("유튜브 100만 기법","유튜브 채널을 100만 구독자까지 성장시키는 실전 기법.",99000),
            ("1달 300 기법","단 한 달 만에 결과를 만드는 300가지 실전 기법.",79000),
            ("엑셀 업무 자동화","반복되는 엑셀 업무를 자동화하는 실무 테크닉.",59000),
            ("네이버 블로그 자동화","네이버 블로그 운영을 자동화해서 트래픽과 수익을 만드는 방법.",69000),
        ]:
            db.session.add(Product(title=t, description=d, price=p, stock=999))
        db.session.commit()

    # 기존 상품 stock이 None이면 기본값 채우기
    try:
        for prod in Product.query.filter(Product.stock.is_(None)).all():
            prod.stock = 999 if "로블록스" not in (prod.title or "") else 5
        db.session.commit()
    except Exception as e:
        print(f"[migrate] stock default fill skipped: {e}")
        db.session.rollback()

    # 로블록스 계정 상품 (없으면 추가)
    roblox_products = [
        ("로블록스 계정 [프리미엄]", "프리미엄 활성화 + 로벅스 약 5만 보유 계정입니다.\n안전한 계정 이전 방식으로 전달됩니다.", 45000, 5),
        ("로블록스 계정 [고레벨]", "레벨 높고 아이템/아바타 꾸며진 계정입니다.\n로벅스 약 2~3만 포함.", 35000, 8),
        ("로블록스 계정 [로벅스 10만]", "로벅스 10만 이상 보유 계정입니다.\n프리미엄 여부는 상품 설명 참고.", 89000, 3),
        ("로블록스 계정 [입문용]", "저렴한 입문용 계정입니다.\n기본 아바타 + 소량 로벅스 포함.", 15000, 15),
    ]
    for t, d, p, s in roblox_products:
        existing = Product.query.filter_by(title=t).first()
        if not existing:
            db.session.add(Product(title=t, description=d, price=p, stock=s))
        else:
            if existing.stock is None:
                existing.stock = s
    db.session.commit()

def get_user():
    uid = session.get("user_id")
    return User.query.get(uid) if uid else None

def login_required(f):
    @wraps(f)
    def deco(*a, **k):
        if not session.get("user_id"):
            flash("로그인이 필요합니다.", "error")
            return redirect("/login")
        return f(*a, **k)
    return deco

def admin_required(f):
    @wraps(f)
    def deco(*a, **k):
        u = get_user()
        if not u or not u.is_admin:
            flash("관리자만 가능합니다.", "error")
            return redirect("/")
        return f(*a, **k)
    return deco

def render(body):
    u = get_user()
    nav = ""
    if u:
        nav = f'''<a href="/my-courses" class="font-medium text-gray-700">내 강의</a>
        <a href="/my-orders" class="text-gray-600">주문내역</a>'''
        if u.is_admin:
            nav += '<a href="/admin" class="text-red-600 font-medium">관리자</a>'
        nav += '<a href="/logout" class="text-gray-500">로그아웃</a>'
    else:
        nav = '''<a href="/login" class="text-gray-600">로그인</a>
        <a href="/signup" class="bg-indigo-600 text-white px-4 py-1.5 rounded-lg">회원가입</a>'''

    flashes = ""
    for cat, msg in get_flashed_messages(with_categories=True):
        cls = "bg-red-100 text-red-700" if cat == "error" else "bg-green-100 text-green-700"
        flashes += f'<div class="mb-4 p-4 rounded-lg {cls}">{msg}</div>'

    # 실시간 AI 상담 봇 위젯 (플로팅)
    chat_widget = '''
<!-- AI 상담 봇 위젯 -->
<div id="chat-widget" class="fixed bottom-5 right-5 z-[9999]" style="pointer-events:auto;">
  <button type="button" id="chat-toggle" onclick="toggleChat()" 
          class="bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 text-white rounded-full w-14 h-14 shadow-xl flex items-center justify-center text-2xl transition cursor-pointer"
          style="pointer-events:auto; -webkit-tap-highlight-color:transparent;">
    💬
  </button>
  <div id="chat-box" class="hidden fixed bottom-20 right-5 w-[calc(100vw-2.5rem)] max-w-sm bg-white rounded-2xl shadow-2xl border border-gray-200 overflow-hidden flex flex-col z-[9999]" style="height:min(420px,70vh); pointer-events:auto;">
    <div class="bg-indigo-600 text-white px-4 py-3 flex justify-between items-center flex-shrink-0">
      <div>
        <div class="font-semibold text-sm">다온 클래스 상담봇</div>
        <div class="text-xs opacity-80">AI가 실시간으로 도와드려요</div>
      </div>
      <button type="button" onclick="toggleChat()" class="text-white/80 hover:text-white text-2xl leading-none px-1">&times;</button>
    </div>
    <div id="chat-messages" class="flex-1 overflow-y-auto p-4 space-y-3 bg-gray-50 text-sm">
      <div class="flex justify-start">
        <div class="bg-white border rounded-2xl rounded-tl-none px-3 py-2 max-w-[85%] shadow-sm">
          안녕하세요! 다온 클래스입니다 😊<br>
          강의 안내, 구매 방법, 입금 문의 등 무엇이든 물어보세요.
        </div>
      </div>
    </div>
    <div class="p-3 border-t bg-white flex-shrink-0">
      <form id="chat-form" onsubmit="sendChat(event)" class="flex gap-2">
        <input id="chat-input" type="text" placeholder="메시지를 입력하세요..." autocomplete="off"
               class="flex-1 border rounded-full px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400">
        <button type="submit" class="bg-indigo-600 text-white rounded-full px-4 py-2 text-sm hover:bg-indigo-700">전송</button>
      </form>
    </div>
  </div>
</div>

<script>
const chatHistory = [];
let chatOpen = false;

function toggleChat() {
  const box = document.getElementById("chat-box");
  if (!box) return;
  chatOpen = !chatOpen;
  if (chatOpen) {
    box.classList.remove("hidden");
    setTimeout(function(){ var el = document.getElementById("chat-input"); if(el) el.focus(); }, 50);
  } else {
    box.classList.add("hidden");
  }
}

function addMessage(role, content) {
  const container = document.getElementById("chat-messages");
  if (!container) return;
  const isUser = role === "user";
  const div = document.createElement("div");
  div.className = "flex " + (isUser ? "justify-end" : "justify-start");
  var safe = (content || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/\\n/g,"<br>");
  div.innerHTML = "<div class=\\"" + (isUser ? "bg-indigo-600 text-white rounded-2xl rounded-tr-none" : "bg-white border rounded-2xl rounded-tl-none shadow-sm") + " px-3 py-2 max-w-[85%]\\">" + safe + "</div>";
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

async function sendChat(e) {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const msg = (input && input.value || "").trim();
  if (!msg) return;
  input.value = "";
  addMessage("user", msg);
  chatHistory.push({role: "user", content: msg});

  const loadingId = "loading-" + Date.now();
  const container = document.getElementById("chat-messages");
  const loadingDiv = document.createElement("div");
  loadingDiv.id = loadingId;
  loadingDiv.className = "flex justify-start";
  loadingDiv.innerHTML = "<div class=\\"bg-white border rounded-2xl rounded-tl-none px-3 py-2 text-gray-400 text-sm\\">답변 생성 중...</div>";
  container.appendChild(loadingDiv);
  container.scrollTop = container.scrollHeight;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      credentials: "same-origin",
      body: JSON.stringify({message: msg, history: chatHistory.slice(-10)})
    });
    const data = await res.json();
    var ld = document.getElementById(loadingId);
    if (ld) ld.remove();
    if (data.reply) {
      addMessage("assistant", data.reply);
      chatHistory.push({role: "assistant", content: data.reply});
    } else {
      addMessage("assistant", data.error || "죄송합니다. 잠시 후 다시 시도해 주세요.");
    }
  } catch (err) {
    var ld2 = document.getElementById(loadingId);
    if (ld2) ld2.remove();
    addMessage("assistant", "네트워크 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.");
  }
}
</script>
'''


    return f'''<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>다온 클래스</title>
<script src="https://cdn.tailwindcss.com"></script>
</head><body class="bg-gray-50 min-h-screen">
<nav class="bg-white border-b shadow-sm">
<div class="max-w-5xl mx-auto px-4 py-3 flex justify-between items-center">
<a href="/" class="text-xl font-bold text-indigo-600">다온 클래스</a>
<div class="flex gap-4 text-sm items-center">{nav}</div>
</div></nav>
<main class="max-w-5xl mx-auto px-4 py-8">
{flashes}
{body}
</main>
<footer class="border-t mt-12 py-6 text-center text-gray-400 text-sm">© 2026 다온 클래스 · <a href="https://daonshop.cloud" class="underline">daonshop.cloud</a></footer>
{chat_widget}
</body></html>'''


# ==================== 메인 페이지 라우트 ====================

@app.route("/")
def index():
    # 강의 상품만 표시 (로블록스 계정 제외)
    products = Product.query.filter_by(is_active=True).filter(~Product.title.like("%로블록스%")).all()
    cards = ""
    for p in products:
        cards += f'''<div class="bg-white rounded-xl border p-6">
        <h2 class="text-xl font-semibold mb-2">{p.title}</h2>
        <p class="text-gray-600 text-sm mb-4">{(p.description or "")[:80]}...</p>
        <div class="flex justify-between items-center">
        <span class="text-indigo-600 font-bold text-lg">{p.price:,}원</span>
        <a href="/product/{p.id}" class="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm">상세보기</a>
        </div></div>'''
    if not cards:
        cards = '<p class="text-gray-500">등록된 강의가 없습니다.</p>'
    return render(f'<h1 class="text-3xl font-bold mb-8">강의 목록</h1><div class="grid md:grid-cols-2 gap-6">{cards}</div>')


@app.route("/roblox")
def roblox_index():
    """로블록스 계정 구매 페이지"""
    products = Product.query.filter_by(is_active=True).filter(Product.title.like("%로블록스%")).all()
    cards = ""
    for p in products:
        stock = p.stock if p.stock is not None else 0
        if stock <= 0:
            stock_badge = '<span class="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full">품절</span>'
            btn = '<span class="bg-gray-300 text-gray-500 px-4 py-2 rounded-lg text-sm cursor-not-allowed">품절</span>'
        else:
            stock_badge = f'<span class="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">재고 {stock}개</span>'
            btn = f'<a href="/product/{p.id}" class="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-indigo-700">상세보기</a>'
        cards += f'''<div class="bg-white rounded-xl border p-6 hover:shadow-md transition">
        <div class="flex items-center gap-2 mb-2">
            <span class="text-2xl">🎮</span>
            <h2 class="text-xl font-semibold">{p.title}</h2>
            {stock_badge}
        </div>
        <p class="text-gray-600 text-sm mb-4 whitespace-pre-line">{(p.description or "")[:120]}{"..." if len(p.description or "") > 120 else ""}</p>
        <div class="flex justify-between items-center">
        <span class="text-indigo-600 font-bold text-lg">{p.price:,}원</span>
        {btn}
        </div></div>'''
    if not cards:
        cards = '<p class="text-gray-500">현재 판매 중인 로블록스 계정이 없습니다.</p>'
    body = f'''
    <div class="mb-8">
        <h1 class="text-3xl font-bold mb-2">🎮 로블록스 계정 구매</h1>
        <p class="text-gray-600">안전하고 빠른 계정 이전 · 입금 확인 후 즉시 전달</p>
    </div>
    <div class="bg-indigo-50 border border-indigo-100 rounded-xl p-4 mb-8 text-sm text-indigo-800">
        <strong>구매 안내</strong><br>
        1. 원하는 계정을 선택하고 구매하기<br>
        2. 카카오뱅크 <strong>7777-03-0806539</strong> (예금주: 김시우) 로 입금<br>
        3. 관리자 확인(결제완료 처리) 후 계정 정보 전달
    </div>
    <div class="grid md:grid-cols-2 gap-6">{cards}</div>
    '''
    return render(body)


@app.route("/product/<int:pid>")
def product_detail(pid):
    p = Product.query.get_or_404(pid)
    u = get_user()
    stock = p.stock if p.stock is not None else 0
    is_roblox = "로블록스" in (p.title or "")
    back_link = ""
    if is_roblox:
        back_link = '<a href="/roblox" class="text-sm text-indigo-600 mb-4 inline-block">← 로블록스 계정 목록으로</a>'
    stock_html = ""
    if is_roblox:
        if stock <= 0:
            stock_html = '<p class="text-red-600 font-medium mb-4">현재 품절입니다.</p>'
        else:
            stock_html = f'<p class="text-green-600 text-sm mb-4">재고: {stock}개</p>'
    if stock <= 0 and is_roblox:
        btn = '<span class="inline-block bg-gray-300 text-gray-500 px-8 py-3 rounded-lg cursor-not-allowed">품절</span>'
    elif u:
        btn = f'<a href="/order/{p.id}" class="inline-block bg-indigo-600 text-white px-8 py-3 rounded-lg">구매하기</a>'
    else:
        btn = '<a href="/login" class="inline-block bg-indigo-600 text-white px-8 py-3 rounded-lg">로그인 후 구매하기</a>'
    return render(f'''{back_link}
    <div class="bg-white rounded-xl border p-8">
    <h1 class="text-3xl font-bold mb-4">{p.title}</h1>
    <p class="text-2xl text-indigo-600 font-bold mb-2">{p.price:,}원</p>
    {stock_html}
    <div class="text-gray-700 whitespace-pre-line mb-8">{p.description or ""}</div>
    {btn}</div>''')


@app.route("/signup", methods=["GET","POST"])
def signup():
    if get_user(): return redirect("/")
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        email = request.form.get("email","").strip()
        if not username or not password:
            flash("아이디와 비밀번호를 입력하세요.","error")
        elif User.query.filter_by(username=username).first():
            flash("이미 존재하는 아이디입니다.","error")
        else:
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user); db.session.commit()
            session["user_id"] = user.id
            flash("회원가입 완료!","success")
            return redirect("/")
    return render('''<div class="max-w-md mx-auto bg-white rounded-xl border p-8">
    <h1 class="text-2xl font-bold mb-6 text-center">회원가입</h1>
    <form method="post" class="space-y-4">
    <input name="username" placeholder="아이디" required class="w-full border rounded-lg px-4 py-2">
    <input name="email" type="email" placeholder="이메일 (선택)" class="w-full border rounded-lg px-4 py-2">
    <input name="password" type="password" placeholder="비밀번호" required class="w-full border rounded-lg px-4 py-2">
    <button class="w-full bg-indigo-600 text-white py-3 rounded-lg">가입하기</button>
    </form>
    <p class="text-center mt-4 text-sm">이미 계정이 있으신가요? <a href="/login" class="text-indigo-600">로그인</a></p>
    </div>''')


@app.route("/login", methods=["GET","POST"])
def login():
    if get_user(): return redirect("/")
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session["user_id"] = user.id
            flash(f"{user.username}님 환영합니다!","success")
            return redirect("/")
        flash("아이디 또는 비밀번호가 틀렸습니다.","error")
    return render('''<div class="max-w-md mx-auto bg-white rounded-xl border p-8">
    <h1 class="text-2xl font-bold mb-6 text-center">로그인</h1>
    <form method="post" class="space-y-4">
    <input name="username" placeholder="아이디" required class="w-full border rounded-lg px-4 py-2">
    <input name="password" type="password" placeholder="비밀번호" required class="w-full border rounded-lg px-4 py-2">
    <button class="w-full bg-indigo-600 text-white py-3 rounded-lg">로그인</button>
    </form>
    <p class="text-center mt-4 text-sm">계정이 없으신가요? <a href="/signup" class="text-indigo-600">회원가입</a></p>
    </div>''')


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("로그아웃되었습니다.","success")
    return redirect("/")


@app.route("/order/<int:pid>")
@login_required
def create_order(pid):
    p = Product.query.get_or_404(pid)
    u = get_user()
    stock = p.stock if p.stock is not None else 0
    is_roblox = "로블록스" in (p.title or "")
    if is_roblox and stock <= 0:
        flash("현재 품절된 상품입니다.", "error")
        return redirect("/roblox")
    if Order.query.filter_by(user_id=u.id, product_id=p.id, status="paid").first():
        flash("이미 구매한 상품입니다.","success")
        return redirect("/my-courses")
    order = Order.query.filter_by(user_id=u.id, product_id=p.id, status="pending").first()
    if not order:
        order = Order(order_id=f"DAON-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}",
                      user_id=u.id, product_id=p.id, amount=p.price)
        db.session.add(order); db.session.commit()
    item_label = "상품" if is_roblox else "강의"
    after_msg = "확인 후 계정 정보를 전달해 드립니다." if is_roblox else "확인 후 <strong>내 강의</strong>에서 PDF를 받을 수 있습니다."
    return render(f'''<div class="max-w-lg mx-auto bg-white rounded-xl border p-8">
    <div class="text-center mb-6"><div class="text-5xl mb-3">🏦</div><h1 class="text-2xl font-bold">입금 안내</h1></div>
    <div class="bg-indigo-50 rounded-lg p-5 mb-6 space-y-3">
    <div class="flex justify-between"><span class="text-gray-600">{item_label}</span><span class="font-medium">{p.title}</span></div>
    <div class="flex justify-between"><span class="text-gray-600">입금 금액</span><span class="font-bold text-indigo-600 text-lg">{order.amount:,}원</span></div>
    <hr>
    <div class="flex justify-between"><span class="text-gray-600">은행</span><span class="font-medium">{BANK_NAME}</span></div>
    <div class="flex justify-between"><span class="text-gray-600">계좌번호</span><span class="font-mono font-bold text-lg">{BANK_ACCOUNT}</span></div>
    <div class="flex justify-between"><span class="text-gray-600">예금주</span><span class="font-medium">{BANK_HOLDER}</span></div>
    </div>
    <div class="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-sm text-yellow-800 mb-6">
    금액을 정확히 입금해 주세요. {after_msg}
    </div>
    <div class="text-center"><a href="/my-orders" class="text-indigo-600">주문 내역 보기</a>
    <p class="text-xs text-gray-400 mt-2">주문번호: {order.order_id}</p></div></div>''')


@app.route("/my-orders")
@login_required
def my_orders():
    orders = Order.query.filter_by(user_id=session["user_id"]).order_by(Order.created_at.desc()).all()
    rows = ""
    for o in orders:
        st = "결제 완료" if o.status=="paid" else "입금 대기"
        cls = "bg-green-100 text-green-700" if o.status=="paid" else "bg-yellow-100 text-yellow-700"
        rows += f'''<div class="bg-white rounded-xl border p-5 flex justify-between items-center">
        <div><h3 class="font-semibold">{o.product.title}</h3>
        <p class="text-sm text-gray-500">{o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else ""} · {o.amount:,}원</p></div>
        <span class="px-3 py-1 rounded-full text-sm {cls}">{st}</span></div>'''
    if not rows: rows = '<p class="text-gray-500">주문 내역이 없습니다.</p>'
    return render(f'<h1 class="text-2xl font-bold mb-6">내 주문 내역</h1><div class="space-y-4">{rows}</div>')


@app.route("/my-courses")
@login_required
def my_courses():
    orders = Order.query.filter_by(user_id=session["user_id"], status="paid").all()
    rows = ""
    for o in orders:
        is_roblox = "로블록스" in (o.product.title or "")
        if o.product.pdf_filename:
            btn = f'<a href="/download/{o.id}" class="bg-indigo-600 text-white px-5 py-2.5 rounded-lg text-sm">PDF 다운로드</a>'
        elif is_roblox:
            btn = '<span class="text-sm text-green-600 font-medium">계정 전달 예정 / 관리자 확인 완료</span>'
        else:
            btn = '<span class="text-sm text-gray-400">PDF 준비 중</span>'
        rows += f'''<div class="bg-white rounded-xl border p-5 flex justify-between items-center">
        <div><h3 class="font-semibold text-lg">{o.product.title}</h3></div>{btn}</div>'''
    if not rows: rows = '<p class="text-gray-500">아직 구매한 상품이 없습니다. <a href="/" class="text-indigo-600">강의 보러가기</a> · <a href="/roblox" class="text-indigo-600">로블록스 계정</a></p>'
    return render(f'<h1 class="text-2xl font-bold mb-6">내 강의 / 구매 상품</h1><div class="space-y-4">{rows}</div>')


@app.route("/download/<int:oid>")
@login_required
def download(oid):
    order = Order.query.get_or_404(oid)
    if order.user_id != session["user_id"] or order.status != "paid": abort(403)
    if not order.product.pdf_filename:
        flash("PDF가 아직 없습니다.","error"); return redirect("/my-courses")
    path = os.path.join("uploads", order.product.pdf_filename)
    if not os.path.exists(path):
        flash("파일을 찾을 수 없습니다.","error"); return redirect("/my-courses")
    return send_file(path, as_attachment=True)


@app.route("/admin")
@admin_required
def admin():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    products = Product.query.all()
    order_rows = ""
    for o in orders:
        st = "결제완료" if o.status=="paid" else "입금대기"
        cls = "text-green-600" if o.status=="paid" else "text-yellow-600"
        btn = f'<a href="/admin/pay/{o.id}" class="bg-green-600 text-white px-3 py-1 rounded text-sm">결제완료 처리</a>' if o.status=="pending" else ""
        order_rows += f'''<div class="bg-white rounded-xl border p-4 flex justify-between items-center">
        <div>{o.user.username} - {o.product.title} ({o.amount:,}원)</div>
        <div class="flex gap-2 items-center"><span class="text-sm {cls}">{st}</span>{btn}</div></div>'''
    prod_rows = ""
    for p in products:
        pdf = '<span class="text-green-600 text-xs">PDF</span>' if p.pdf_filename else ""
        stock = p.stock if p.stock is not None else 0
        stock_cls = "text-red-600" if stock <= 0 else "text-gray-600"
        prod_rows += f'''<div class="bg-white rounded-xl border p-4 flex justify-between items-center">
        <span>{p.title} - {p.price:,}원 {pdf} <span class="text-xs {stock_cls}">(재고 {stock})</span></span>
        <div class="flex gap-3">
        <a href="/admin/product/{p.id}" class="text-indigo-600 text-sm">수정</a>
        <a href="/admin/product/delete/{p.id}" class="text-red-600 text-sm" onclick="return confirm('정말 삭제하시겠습니까?')">삭제</a>
        </div></div>'''
    return render(f'''<h1 class="text-2xl font-bold mb-6">관리자</h1>
    <h2 class="font-semibold mb-3">주문 관리 (구매 승인)</h2>
    <div class="space-y-3 mb-10">{order_rows or '<p class="text-gray-500">주문이 없습니다.</p>'}</div>
    <h2 class="font-semibold mb-3">상품 관리 (재고 수정 가능)</h2>
    <a href="/admin/product/new" class="inline-block mb-4 bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm">+ 상품 추가</a>
    <div class="space-y-3">{prod_rows}</div>''')


@app.route("/admin/pay/<int:oid>")
@admin_required
def admin_pay(oid):
    order = Order.query.get_or_404(oid)
    if order.status == "pending":
        order.status = "paid"
        order.paid_at = datetime.utcnow()
        # 재고 차감 (로블록스 계정 등)
        product = order.product
        if product and product.stock is not None and product.stock > 0:
            product.stock -= 1
        db.session.commit()
        flash("결제완료 처리했습니다. (재고 반영됨)", "success")
    return redirect("/admin")


@app.route("/admin/product/delete/<int:pid>")
@admin_required
def admin_product_delete(pid):
    product = Product.query.get_or_404(pid)
    if product.pdf_filename:
        pdf_path = os.path.join("uploads", product.pdf_filename)
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except:
                pass
    db.session.delete(product)
    db.session.commit()
    flash("상품이 삭제되었습니다.", "success")
    return redirect("/admin")


@app.route("/admin/product/new", methods=["GET","POST"])
@app.route("/admin/product/<int:pid>", methods=["GET","POST"])
@admin_required
def admin_product(pid=None):
    product = Product.query.get(pid) if pid else None
    if request.method == "POST":
        if not product:
            product = Product(); db.session.add(product)
        product.title = request.form.get("title","").strip()
        product.description = request.form.get("description","")
        product.price = int(request.form.get("price") or 0)
        try:
            product.stock = int(request.form.get("stock") or 0)
        except ValueError:
            product.stock = 0
        product.is_active = True
        f = request.files.get("pdf")
        if f and f.filename:
            fn = secure_filename(f"{secrets.token_hex(4)}_{f.filename}")
            f.save(os.path.join("uploads", fn))
            product.pdf_filename = fn
        db.session.commit(); flash("저장되었습니다.","success")
        return redirect("/admin")
    tv = product.title if product else ""
    dv = product.description if product else ""
    pv = product.price if product else ""
    sv = product.stock if product and product.stock is not None else 10
    return render(f'''<div class="max-w-lg mx-auto bg-white rounded-xl border p-8">
    <h1 class="text-2xl font-bold mb-6">{'상품 수정' if product else '상품 추가'}</h1>
    <form method="post" enctype="multipart/form-data" class="space-y-4">
    <input name="title" value="{tv}" placeholder="제목" required class="w-full border rounded-lg px-4 py-2">
    <textarea name="description" rows="5" placeholder="설명" class="w-full border rounded-lg px-4 py-2">{dv}</textarea>
    <input name="price" type="number" value="{pv}" placeholder="가격" required class="w-full border rounded-lg px-4 py-2">
    <input name="stock" type="number" value="{sv}" placeholder="재고 수량" min="0" class="w-full border rounded-lg px-4 py-2">
    <p class="text-xs text-gray-500 -mt-2">로블록스 계정 등은 재고를 정확히 입력하세요. 결제완료 처리 시 1개씩 차감됩니다.</p>
    <input name="pdf" type="file" accept=".pdf" class="w-full">
    <button class="w-full bg-indigo-600 text-white py-3 rounded-lg">저장</button>
    </form></div>''')


# ==================== API 엔드포인트 ====================

@app.route("/api/health")
def api_health():
    return jsonify({
        "status": "ok",
        "service": "daon-class-api",
        "domain": "daonshop.cloud",
        "chat_enabled": True,
        "time": datetime.utcnow().isoformat() + "Z"
    })


@app.route("/api/products")
def api_products():
    products = Product.query.filter_by(is_active=True).all()
    return jsonify([{
        "id": p.id,
        "title": p.title,
        "description": p.description,
        "price": p.price,
        "has_pdf": bool(p.pdf_filename)
    } for p in products])


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """규칙 기반 상담 봇 (API 크레딧 없음)"""
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "메시지를 입력해 주세요."}), 400
    reply = get_bot_reply(message)
    return jsonify({"reply": reply, "model": "faq-bot"})


@app.route("/api/info")
def api_info():
    return jsonify({
        "name": "다온 클래스",
        "domain": "daonshop.cloud",
        "api_domain": null,
        "bank": {
            "name": BANK_NAME,
            "account": BANK_ACCOUNT,
            "holder": BANK_HOLDER,
        },
        "features": ["강의 판매", "무통장 입금", "PDF 다운로드", "AI 실시간 상담 봇"],
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
