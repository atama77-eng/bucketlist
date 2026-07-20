"""データベース接続。

ローカルでは SQLite（app.db というファイル）を使う。
Supabase に切り替えるときは .env の DATABASE_URL を書き換えるだけでよい。
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlmodel import Session, SQLModel, create_engine

load_dotenv()

# どこから起動しても同じ app.db を見るように、絶対パスにしておく
DEFAULT_SQLITE = f"sqlite:///{Path(__file__).parent / 'app.db'}"
DATABASE_URL = os.getenv("DATABASE_URL") or DEFAULT_SQLITE

# Neon や Supabase の接続文字列は postgres:// で始まることがあるが、
# SQLAlchemy は postgresql:// を求めるので自動で直す
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL.startswith("sqlite"):
    # SQLite のときだけ必要なおまじない
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # Neon はアクセスがないとDBが眠る。切れた接続を掴まないよう pool_pre_ping を付ける
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)


def init_db() -> None:
    """テーブルがなければ作る。アプリ起動時に1回呼ぶ。"""
    import models  # noqa: F401  テーブル定義を読み込ませるために必要

    SQLModel.metadata.create_all(engine)


def get_session():
    """1リクエストにつき1つのDBセッションを使い回す。"""
    with Session(engine) as session:
        yield session
