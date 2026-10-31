# 다온 클래스

## Render 설정 방법

### 1. Build Command
```
pip install -r requirements.txt
```

### 2. Start Command (중요!)
```
gunicorn main:app
```

### 3. Environment Variables
- SECRET_KEY = 아무거나입력
- BANK_NAME = 카카오뱅크
- BANK_ACCOUNT = 7777-03-0806539
- BANK_HOLDER = 김시우

PostgreSQL 쓰면 DATABASE_URL 자동 연결됨.
안 쓰면 SQLite로 동작.
