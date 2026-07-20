"""質問・ToDo・Tips を作る部分。

ここがこのアプリの「頭脳」。
.env に ANTHROPIC_API_KEY があれば Claude API を使い、
なければ固定テンプレートで動く（ステップ1はこちらでOK）。

APIが失敗しても必ずテンプレートに落ちるので、アプリが止まることはない。
"""

import json
import os

from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")


# ---------------------------------------------------------------
# テンプレート版（APIキーがないときのフォールバック）
# ---------------------------------------------------------------

def _fallback_questions(title: str) -> list[str]:
    return [
        f"「{title}」は、いつまでに実現したいですか？",
        "今、それに向けてどのくらい進んでいますか？（何もしていない場合はそう書いてください）",
        "なぜそれをやりたいのですか？実現したときの自分を想像して書いてみてください。",
    ]


def _fallback_plan(title: str, qa: list[tuple[str, str]]) -> tuple[list[str], list[dict]]:
    todos = [
        f"「{title}」について調べる（本・記事・動画を3つ見る）",
        "必要なお金をざっくり見積もる",
        "必要な時間と期間を書き出す",
        "すでに実現した人を1人見つけて、その人のやり方を読む",
        "今週できる一番小さな一歩を決める",
        "その一歩を実行する",
        "振り返って、次の一歩を決める",
    ]
    tips = [
        {"kind": "motivation", "content": "「いつかやる」は永遠に来ません。今日カレンダーに1行だけ予定を入れてください。"},
        {"kind": "motivation", "content": "完璧な準備を待つと一生始まりません。7割の状態で始めたほうが早く終わります。"},
        {"kind": "motivation", "content": "うまくいかない日があっても、やめなければ失敗にはなりません。"},
        {"kind": "knowledge", "content": "大きな目標は、1回15分でできる作業まで分解すると急に進みはじめます。"},
        {"kind": "knowledge", "content": "同じことをやった人の体験談を読むと、想定していなかった落とし穴が見つかります。"},
        {"kind": "knowledge", "content": "進捗を人に話すと、実行率が上がることが知られています。誰か1人に宣言してみてください。"},
    ]
    return todos, tips


# ---------------------------------------------------------------
# Claude API 版
# ---------------------------------------------------------------

def _call_claude(prompt: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=API_KEY)
    message = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _extract_json(text: str) -> dict:
    """返答からJSON部分だけを取り出す。```json ``` で囲まれていても対応する。"""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("JSONが見つかりません")
    return json.loads(text[start : end + 1])


# ---------------------------------------------------------------
# 外から呼ぶのはこの2つだけ
# ---------------------------------------------------------------

def generate_questions(title: str) -> list[str]:
    """やりたいことを受けて、3つの質問を返す。"""
    if not API_KEY:
        return _fallback_questions(title)

    prompt = f"""あなたは人生の目標達成を支援するコーチです。

ユーザーが「死ぬまでにやりたいこと」として次を挙げました:
「{title}」

これを実行可能な計画に落とし込むために、ユーザーに聞くべき質問をちょうど3つ考えてください。

条件:
- 1問目は期限や時期に関するもの
- 2問目は現在の状況・スキル・進捗に関するもの
- 3問目は動機や、実現したときの気持ちを引き出すもの
- 「{title}」の内容に具体的に踏み込んだ質問にすること（一般論にしない）
- 各質問は80文字以内

次のJSON形式だけを出力してください:
{{"questions": ["質問1", "質問2", "質問3"]}}"""

    try:
        data = _extract_json(_call_claude(prompt))
        questions = [str(q) for q in data["questions"]][:3]
        if len(questions) == 3:
            return questions
    except Exception as e:  # ネットワーク断・JSON崩れなど何が起きても止めない
        print(f"[generator] 質問生成に失敗したためテンプレートを使います: {e}")
    return _fallback_questions(title)


def generate_plan(title: str, qa: list[tuple[str, str]]) -> tuple[list[str], list[dict]]:
    """質問への答えを踏まえて、ToDoリストとTipsのストックを返す。"""
    if not API_KEY:
        return _fallback_plan(title, qa)

    qa_text = "\n".join(f"Q: {q}\nA: {a}" for q, a in qa)
    prompt = f"""あなたは人生の目標達成を支援するコーチです。

ユーザーの「死ぬまでにやりたいこと」:
「{title}」

ヒアリング結果:
{qa_text}

これをもとに、次の2つを作ってください。

1. ToDoリスト（5〜8個）
   - 上から順に実行すれば実現に近づく順番にする
   - 1つ1つが「今日か今週、実際に手をつけられる」粒度にする
   - 「頑張る」「意識する」のような曖昧なものは禁止。行動を書く
   - ユーザーの回答内容（期限・現状・動機）を反映させる

2. Tips（6〜8個）
   - kind が "motivation" のもの: やる気が落ちたときに効く一言
   - kind が "knowledge" のもの: 「{title}」に固有の、知っていると得をする具体的な知識やコツ
   - 一般論ではなく「{title}」ならではの内容にすること
   - 各120文字以内

次のJSON形式だけを出力してください:
{{"todos": ["...", "..."],
  "tips": [{{"kind": "motivation", "content": "..."}}, {{"kind": "knowledge", "content": "..."}}]}}"""

    try:
        data = _extract_json(_call_claude(prompt))
        todos = [str(t) for t in data["todos"]]
        tips = [
            {"kind": t.get("kind", "motivation"), "content": str(t["content"])}
            for t in data["tips"]
        ]
        if todos and tips:
            return todos, tips
    except Exception as e:
        print(f"[generator] 計画生成に失敗したためテンプレートを使います: {e}")
    return _fallback_plan(title, qa)
