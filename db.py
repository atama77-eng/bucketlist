"""データベース接続。

ローカルでは SQLite（app.db というファイル）を使う。
Neon に切り替えるときは .env の DATABASE_URL を書き換えるだけでよい。
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlmodel import Session, SQLModel, create_engine

load_dotenv()

# Vercel上で動いているかどうか（Vercelが自動で入れる環境変数で判定）
IS_VERCEL = bool(os.getenv("VERCEL"))

# どこから起動しても同じ app.db を見るように、絶対パスにしておく
DEFAULT_SQLITE = f"sqlite:///{Path(__file__).parent / 'app.db'}"
DATABASE_URL = os.getenv("DATABASE_URL") or DEFAULT_SQLITE

if IS_VERCEL and DATABASE_URL.startswith("sqlite"):
    # Vercelはファイルを書き込めないので、SQLiteのままだと起動時に落ちる。
    # 環境変数 DATABASE_URL の設定漏れが原因。とりあえず起動はさせる。
    print("[db] 警告: DATABASE_URL が設定されていません。Neonの接続文字列を登録してください。")
    print("[db] 一時領域のDBで起動します（データは保存されません）")
    DATABASE_URL = "sqlite:////tmp/app.db"

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
    _add_missing_columns()


# 後から models.py に増やした項目を、既存のテーブルにも足すための処理。
# create_all はテーブルを作りはするが、既存テーブルに列は追加してくれないため。
# 形式: (テーブル名, 列名, SQLでの型と初期値)
_LATER_COLUMNS = [
    ("todo", "note", "VARCHAR DEFAULT ''"),
]


def _add_missing_columns() -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    for table, column, definition in _LATER_COLUMNS:
        if table not in tables:
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        if column in existing:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
            print(f"[db] {table} テーブルに {column} 列を追加しました")
        except Exception as e:
            print(f"[db] {table}.{column} を追加できませんでした: {e}")


def get_session():
    """1リクエストにつき1つのDBセッションを使い回す。"""
    with Session(engine) as session:
        yield session
