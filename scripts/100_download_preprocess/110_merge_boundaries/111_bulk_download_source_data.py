import time
import requests
from pathlib import Path

BASE = "https://www.e-stat.go.jp/gis/statmap-search/data"

common_params = {
    "dlserveyId": "A002005212020",
    "coordSys": "1",
    "format": "shape",
    "downloadType": "5",
    "datum": "2000",
}

headers = {
    "Referer": "https://www.e-stat.go.jp/gis/statmap-search",
    "User-Agent": "Mozilla/5.0",
}

out_dir = Path(r"C:...\Downloads\zenkoku\ポリゴンデータ\Raw")
out_dir.mkdir(parents=True, exist_ok=True)

s = requests.Session()

for i in range(1, 48):
    code = f"{i:02d}"
    params = {**common_params, "code": code}

    out = out_dir / f"A002005212020_code{code}_shape.zip"

    # 既に落としていたらスキップ（0バイトは取り直す）
    if out.exists() and out.stat().st_size > 0:
        print(f"[{code}] skip (exists): {out.name}")
        continue

    print(f"[{code}] downloading...")

    try:
        r = s.get(BASE, params=params, headers=headers, stream=True, timeout=300)
        r.raise_for_status()

        # 念のため中身がHTML（エラーページ）じゃないか軽くチェック
        ctype = (r.headers.get("content-type") or "").lower()
        if "text/html" in ctype:
            text_head = r.text[:300]
            raise RuntimeError(f"Got HTML instead of zip. head={text_head!r}")

        with out.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

        print(f"[{code}] saved: {out.name} ({out.stat().st_size} bytes)")

    except Exception as e:
        print(f"[{code}] FAILED: {e}")

    # 連続アクセスを避ける（軽いレート制限）
    time.sleep(1.0)

print("done")