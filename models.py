"""データベースのテーブル定義。

SQLModel を使うと、ここに書いたクラスがそのまま DB のテーブルになる。
SQLite でも Postgres(Supabase) でも同じコードが動く。
"""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Wish(SQLModel, table=True):
    """やりたいこと本体。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    # draft = 質問に答える前 / active = 実行中 / done = 達成済み
    status: str = "draft"
    created_at: datetime = Field(default_factory=datetime.now)


class Answer(SQLModel, table=True):
    """作成時の質問と、その答え。ToDo生成の材料になる。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    wish_id: int = Field(foreign_key="wish.id", index=True)
    question: str
    answer: str


class Todo(SQLModel, table=True):
    """やりたいことを実現するための小さな一歩。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    wish_id: int = Field(foreign_key="wish.id", index=True)
    text: str
    order_no: int = 0
    done: bool = False
    # 進めてわかったこと・調べた結果を書き残す欄
    note: str = ""


class Tip(SQLModel, table=True):
    """モチベーション／知識のストック。開くたびに1つだけ表示する。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    wish_id: int = Field(foreign_key="wish.id", index=True)
    kind: str = "motivation"  # motivation または knowledge
    content: str


class Achievement(SQLModel, table=True):
    """達成の記録。写真と感想。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    wish_id: int = Field(foreign_key="wish.id", index=True)
    photo_path: Optional[str] = None
    note: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
