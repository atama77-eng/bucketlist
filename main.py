"""アプリ本体。画面と処理の対応をここに書く。

http://127.0.0.1:8000 で動かす。
"""

import random
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

import db as db_module
import generator
from db import DATABASE_URL, get_session, init_db
from generator import generate_plan, generate_questions, suggest_next_steps
from models import Achievement, Answer, Tip, Todo, Wish
from storage import BLOB_TOKEN, save_photo

BASE_DIR = Path(__file__).parent

init_db()  # テーブルがなければ作る

app = FastAPI()

# staticフォルダが無い環境で落ちないようにしておく
STATIC_DIR = BASE_DIR / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")


# ---------------------------------------------------------------
# 一覧画面
# ---------------------------------------------------------------

@app.get("/")
def index(request: Request, session: Session = Depends(get_session)):
    wishes = session.exec(select(Wish).order_by(Wish.created_at.desc())).all()

    cards = []
    for wish in wishes:
        todos = session.exec(select(Todo).where(Todo.wish_id == wish.id)).all()
        total = len(todos)
        done = sum(1 for t in todos if t.done)
        cards.append(
            {
                "wish": wish,
                "total": total,
                "done": done,
                "percent": int(done / total * 100) if total else 0,
            }
        )

    return templates.TemplateResponse(request, "index.html", {"cards": cards})


# ---------------------------------------------------------------
# 新規作成 → 質問 → 計画生成
# ---------------------------------------------------------------

@app.get("/new")
def new_form(request: Request):
    return templates.TemplateResponse(request, "new.html", {})


@app.post("/new")
def new_create(title: str = Form(...), session: Session = Depends(get_session)):
    wish = Wish(title=title.strip())
    session.add(wish)
    session.commit()
    session.refresh(wish)

    # 質問を作って保存しておく（答えは空のまま）
    for q in generate_questions(wish.title):
        session.add(Answer(wish_id=wish.id, question=q, answer=""))
    session.commit()

    return RedirectResponse(f"/wish/{wish.id}/questions", status_code=303)


@app.get("/wish/{wish_id}/questions")
def questions_form(
    wish_id: int, request: Request, session: Session = Depends(get_session)
):
    wish = session.get(Wish, wish_id)
    answers = session.exec(select(Answer).where(Answer.wish_id == wish_id)).all()
    return templates.TemplateResponse(
        request, "questions.html", {"wish": wish, "answers": answers}
    )


@app.post("/wish/{wish_id}/questions")
async def questions_submit(
    wish_id: int, request: Request, session: Session = Depends(get_session)
):
    form = await request.form()
    wish = session.get(Wish, wish_id)
    answers = session.exec(select(Answer).where(Answer.wish_id == wish_id)).all()

    for a in answers:
        a.answer = str(form.get(f"answer_{a.id}", "")).strip()
        session.add(a)
    session.commit()

    # ToDo と Tips を作る
    qa = [(a.question, a.answer) for a in answers]
    todos, tips = generate_plan(wish.title, qa)

    for i, text in enumerate(todos):
        session.add(Todo(wish_id=wish.id, text=text, order_no=i))
    for tip in tips:
        session.add(Tip(wish_id=wish.id, kind=tip["kind"], content=tip["content"]))

    wish.status = "active"
    session.add(wish)
    session.commit()

    return RedirectResponse(f"/wish/{wish.id}", status_code=303)


# ---------------------------------------------------------------
# 詳細画面
# ---------------------------------------------------------------

@app.get("/wish/{wish_id}")
def detail(wish_id: int, request: Request, session: Session = Depends(get_session)):
    wish = session.get(Wish, wish_id)
    todos = session.exec(
        select(Todo).where(Todo.wish_id == wish_id).order_by(Todo.order_no)
    ).all()
    tips = session.exec(select(Tip).where(Tip.wish_id == wish_id)).all()
    achievement = session.exec(
        select(Achievement).where(Achievement.wish_id == wish_id)
    ).first()

    # 開くたびに1つだけ表示する
    tip = random.choice(tips) if tips else None

    all_done = bool(todos) and all(t.done for t in todos)
    has_notes = any(t.note for t in todos)

    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "wish": wish,
            "todos": todos,
            "tip": tip,
            "all_done": all_done,
            "achievement": achievement,
            "has_notes": has_notes,
        },
    )


# ---------------------------------------------------------------
# メモ（ToDoを進めてわかったこと）
# ---------------------------------------------------------------

@app.get("/todo/{todo_id}/note")
def note_form(todo_id: int, request: Request, session: Session = Depends(get_session)):
    todo = session.get(Todo, todo_id)
    wish = session.get(Wish, todo.wish_id)
    return templates.TemplateResponse(
        request, "note.html", {"todo": todo, "wish": wish}
    )


@app.post("/todo/{todo_id}/note")
def note_save(
    todo_id: int, note: str = Form(""), session: Session = Depends(get_session)
):
    todo = session.get(Todo, todo_id)
    todo.note = note.strip()
    session.add(todo)
    session.commit()
    return RedirectResponse(f"/wish/{todo.wish_id}", status_code=303)


@app.get("/wish/{wish_id}/suggest")
def suggest(wish_id: int, request: Request, session: Session = Depends(get_session)):
    """メモを読ませて、次の一歩を提案してもらう。"""
    wish = session.get(Wish, wish_id)
    todos = session.exec(
        select(Todo).where(Todo.wish_id == wish_id).order_by(Todo.order_no)
    ).all()
    answers = session.exec(select(Answer).where(Answer.wish_id == wish_id)).all()

    suggestions, error = suggest_next_steps(
        wish.title,
        [(a.question, a.answer) for a in answers],
        [{"text": t.text, "done": t.done, "note": t.note} for t in todos],
    )

    return templates.TemplateResponse(
        request,
        "suggest.html",
        {"wish": wish, "suggestions": suggestions, "error": error},
    )


@app.post("/wish/{wish_id}/suggest")
async def suggest_add(
    wish_id: int, request: Request, session: Session = Depends(get_session)
):
    """選ばれた提案をToDoリストの末尾に追加する。"""
    form = await request.form()
    chosen = form.getlist("chosen")

    last = session.exec(
        select(Todo).where(Todo.wish_id == wish_id).order_by(Todo.order_no.desc())
    ).first()
    next_no = (last.order_no + 1) if last else 0

    for i, text in enumerate(chosen):
        session.add(Todo(wish_id=wish_id, text=str(text), order_no=next_no + i))
    session.commit()

    return RedirectResponse(f"/wish/{wish_id}", status_code=303)


@app.get("/status")
def status(request: Request):
    """設定がきちんと反映されているかを確認する画面。"""
    import os

    api = generator.check_api()

    # 接続先は表示するが、ユーザー名とパスワードは伏せる
    if DATABASE_URL.startswith("sqlite"):
        db_kind = "SQLite（ファイル）"
        db_where = DATABASE_URL.replace("sqlite:///", "")
    else:
        db_kind = "Postgres（Neonなど）"
        db_where = DATABASE_URL.split("@")[-1].split("?")[0]

    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "api": api,
            "is_vercel": bool(os.getenv("VERCEL")),
            "db_kind": db_kind,
            "db_where": db_where,
            "db_ok": not DATABASE_URL.startswith("sqlite"),
            "db_error": db_module.INIT_ERROR,
            "blob": bool(BLOB_TOKEN),
            "last_error": generator.LAST_ERROR,
        },
    )


@app.get("/wish/{wish_id}/log")
def log(wish_id: int, request: Request, session: Session = Depends(get_session)):
    """ToDoと、そこで得たメモを順番に並べた記録画面。"""
    wish = session.get(Wish, wish_id)
    todos = session.exec(
        select(Todo).where(Todo.wish_id == wish_id).order_by(Todo.order_no)
    ).all()
    achievement = session.exec(
        select(Achievement).where(Achievement.wish_id == wish_id)
    ).first()

    return templates.TemplateResponse(
        request,
        "log.html",
        {"wish": wish, "todos": todos, "achievement": achievement},
    )


@app.post("/todo/{todo_id}/toggle")
def toggle_todo(todo_id: int, session: Session = Depends(get_session)):
    todo = session.get(Todo, todo_id)
    todo.done = not todo.done
    session.add(todo)
    session.commit()
    return RedirectResponse(f"/wish/{todo.wish_id}", status_code=303)


@app.post("/wish/{wish_id}/delete")
def delete_wish(wish_id: int, session: Session = Depends(get_session)):
    for model in (Todo, Tip, Answer, Achievement):
        for row in session.exec(select(model).where(model.wish_id == wish_id)).all():
            session.delete(row)
    wish = session.get(Wish, wish_id)
    if wish:
        session.delete(wish)
    session.commit()
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------
# 達成記録
# ---------------------------------------------------------------

@app.get("/wish/{wish_id}/achieve")
def achieve_form(wish_id: int, request: Request, session: Session = Depends(get_session)):
    wish = session.get(Wish, wish_id)
    return templates.TemplateResponse(request, "achieve.html", {"wish": wish})


@app.post("/wish/{wish_id}/achieve")
async def achieve_submit(
    wish_id: int,
    note: str = Form(""),
    photo: UploadFile = File(None),
    session: Session = Depends(get_session),
):
    photo_path = None
    if photo is not None and photo.filename:
        # 保存先（ローカル or Vercel Blob）は storage.py が判断する
        photo_path = save_photo(await photo.read())

    session.add(Achievement(wish_id=wish_id, photo_path=photo_path, note=note.strip()))

    wish = session.get(Wish, wish_id)
    wish.status = "done"
    session.add(wish)
    session.commit()

    return RedirectResponse(f"/wish/{wish_id}", status_code=303)
