"""写真の保存。

.env に BLOB_READ_WRITE_TOKEN があれば Vercel Blob に、
なければローカルの static/uploads/ に保存する。

どちらの場合も「画像を表示するためのURL」を文字列で返す。
"""

import io
import os
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

BLOB_TOKEN = os.getenv("BLOB_READ_WRITE_TOKEN")
BLOB_API = "https://blob.vercel-storage.com"
BLOB_API_VERSION = "10"

LOCAL_DIR = Path(__file__).parent / "static" / "uploads"
LOCAL_DIR.mkdir(parents=True, exist_ok=True)

# 長辺をこのピクセル数まで縮小してから保存する（無料枠の節約と表示速度のため）
MAX_SIDE = 1600
JPEG_QUALITY = 85


def _to_jpeg(raw: bytes) -> bytes:
    """アップロードされた画像を、縮小したJPEGに変換する。"""
    image = Image.open(io.BytesIO(raw))

    # スマホ写真の回転情報を反映させる
    try:
        from PIL import ImageOps

        image = ImageOps.exif_transpose(image)
    except Exception:
        pass

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue()


def _put_to_blob(filename: str, data: bytes) -> str:
    """Vercel Blob にアップロードして、公開URLを返す。"""
    response = requests.put(
        f"{BLOB_API}/{filename}",
        headers={
            "access": "public",
            "authorization": f"Bearer {BLOB_TOKEN}",
            "x-api-version": BLOB_API_VERSION,
            "x-content-type": "image/jpeg",
            "x-add-random-suffix": "1",
        },
        data=data,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["url"]


def save_photo(raw: bytes) -> str | None:
    """写真を保存してURLを返す。失敗したら None。"""
    if not raw:
        return None

    try:
        data = _to_jpeg(raw)
    except Exception as e:
        print(f"[storage] 画像を変換できませんでした: {e}")
        return None

    filename = f"{uuid.uuid4().hex}.jpg"

    if BLOB_TOKEN:
        try:
            return _put_to_blob(filename, data)
        except Exception as e:
            # アップロードに失敗しても、記録そのものは残せるようにする
            print(f"[storage] Vercel Blobへの保存に失敗しました: {e}")
            return None

    (LOCAL_DIR / filename).write_bytes(data)
    return f"/static/uploads/{filename}"
