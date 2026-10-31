import os, secrets
from datetime import datetime
from functools import wraps
from flask import Flask, request, redirect, session, flash, send_file, abort, get_flashed_messages
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "daon-class-2026-secret"

db_url = os.environ.get("DATABASE_URL", "")
if db_url:
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///daon.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
os.makedirs("uploads", exist_ok=True)
db = SQLAlchemy(app)

BANK_NAME = "카카오뱅크"
BANK_ACCOUNT = "7777-03-0806539"
BANK_HOLDER = "김시우"

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
            db.session.add(Product(title=t, description=d, price=p))
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
<footer class="border-t mt-12 py-6 text-center text-gray-400 text-sm">© 2026 다온 클래스</footer>
</body></html>'''


@app.route("/")
def index():
    products = Product.query.filter_by(is_active=True).all()
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


@app.route("/product/<int:pid>")
def product_detail(pid):
    p = Product.query.get_or_404(pid)
    u = get_user()
    btn = f'<a href="/order/{p.id}" class="inline-block bg-indigo-600 text-white px-8 py-3 rounded-lg">구매하기</a>' if u else '<a href="/login" class="inline-block bg-indigo-600 text-white px-8 py-3 rounded-lg">로그인 후 구매하기</a>'
    return render(f'''<div class="bg-white rounded-xl border p-8">
    <h1 class="text-3xl font-bold mb-4">{p.title}</h1>
    <p class="text-2xl text-indigo-600 font-bold mb-6">{p.price:,}원</p>
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
    if Order.query.filter_by(user_id=u.id, product_id=p.id, status="paid").first():
        flash("이미 구매한 강의입니다.","success")
        return redirect("/my-courses")
    order = Order.query.filter_by(user_id=u.id, product_id=p.id, status="pending").first()
    if not order:
        order = Order(order_id=f"DAON-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}",
                      user_id=u.id, product_id=p.id, amount=p.price)
        db.session.add(order); db.session.commit()
    return render(f'''<div class="max-w-lg mx-auto bg-white rounded-xl border p-8">
    <div class="text-center mb-6"><div class="text-5xl mb-3">🏦</div><h1 class="text-2xl font-bold">입금 안내</h1></div>
    <div class="bg-indigo-50 rounded-lg p-5 mb-6 space-y-3">
    <div class="flex justify-between"><span class="text-gray-600">강의</span><span class="font-medium">{p.title}</span></div>
    <div class="flex justify-between"><span class="text-gray-600">입금 금액</span><span class="font-bold text-indigo-600 text-lg">{order.amount:,}원</span></div>
    <hr>
    <div class="flex justify-between"><span class="text-gray-600">은행</span><span class="font-medium">{BANK_NAME}</span></div>
    <div class="flex justify-between"><span class="text-gray-600">계좌번호</span><span class="font-mono font-bold text-lg">{BANK_ACCOUNT}</span></div>
    <div class="flex justify-between"><span class="text-gray-600">예금주</span><span class="font-medium">{BANK_HOLDER}</span></div>
    </div>
    <div class="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-sm text-yellow-800 mb-6">
    금액을 정확히 입금해 주세요. 확인 후 <strong>내 강의</strong>에서 PDF를 받을 수 있습니다.
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
        btn = f'<a href="/download/{o.id}" class="bg-indigo-600 text-white px-5 py-2.5 rounded-lg text-sm">PDF 다운로드</a>' if o.product.pdf_filename else '<span class="text-sm text-gray-400">PDF 준비 중</span>'
        rows += f'''<div class="bg-white rounded-xl border p-5 flex justify-between items-center">
        <div><h3 class="font-semibold text-lg">{o.product.title}</h3></div>{btn}</div>'''
    if not rows: rows = '<p class="text-gray-500">아직 구매한 강의가 없습니다. <a href="/" class="text-indigo-600">강의 보러가기</a></p>'
    return render(f'<h1 class="text-2xl font-bold mb-6">내 강의</h1><div class="space-y-4">{rows}</div>')


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
        prod_rows += f'''<div class="bg-white rounded-xl border p-4 flex justify-between items-center">
        <span>{p.title} - {p.price:,}원 {pdf}</span>
        <div class="flex gap-3">
        <a href="/admin/product/{p.id}" class="text-indigo-600 text-sm">수정</a>
        <a href="/admin/product/delete/{p.id}" class="text-red-600 text-sm" onclick="return confirm('정말 삭제하시겠습니까?')">삭제</a>
        </div></div>'''
    return render(f'''<h1 class="text-2xl font-bold mb-6">관리자</h1>
    <h2 class="font-semibold mb-3">주문 관리</h2>
    <div class="space-y-3 mb-10">{order_rows or '<p class="text-gray-500">주문이 없습니다.</p>'}</div>
    <h2 class="font-semibold mb-3">상품 관리</h2>
    <a href="/admin/product/new" class="inline-block mb-4 bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm">+ 상품 추가</a>
    <div class="space-y-3">{prod_rows}</div>''')


@app.route("/admin/pay/<int:oid>")
@admin_required
def admin_pay(oid):
    order = Order.query.get_or_404(oid)
    if order.status == "pending":
        order.status = "paid"; order.paid_at = datetime.utcnow()
        db.session.commit(); flash("결제완료 처리했습니다.","success")
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
    return render(f'''<div class="max-w-lg mx-auto bg-white rounded-xl border p-8">
    <h1 class="text-2xl font-bold mb-6">{'상품 수정' if product else '상품 추가'}</h1>
    <form method="post" enctype="multipart/form-data" class="space-y-4">
    <input name="title" value="{tv}" placeholder="제목" required class="w-full border rounded-lg px-4 py-2">
    <textarea name="description" rows="5" placeholder="설명" class="w-full border rounded-lg px-4 py-2">{dv}</textarea>
    <input name="price" type="number" value="{pv}" placeholder="가격" required class="w-full border rounded-lg px-4 py-2">
    <input name="pdf" type="file" accept=".pdf" class="w-full">
    <button class="w-full bg-indigo-600 text-white py-3 rounded-lg">저장</button>
    </form></div>''')


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
