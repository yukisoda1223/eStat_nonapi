# eStat_nonapi

e-Statのデータを**APIを使わずに**（Webの直接ダウンロード）取得し、都道府県単位で提供されるデータを集約して、**全国版のGIS（GPKG）**や**構造化CSV**として出力するためのツール群です。

- 境界線データ：ダウンロード → 都道府県別データを結合 → 全国1ファイル（GPKG）
- Excel（特殊配列）：参照箇所（セル/範囲）を指定して抽出 → 47都道府県分を実行 → 小地域境界に結合 → GPKG/CSV出力

> 注意：このリポジトリは「コード」を公開するもので、e-Statから取得したデータそのものは同梱しません。

---

## Repository structure

現在の主な構成は以下です。
scripts/
  100_download_preprocess/
    110_merge_boundaries/
      111_bulk_download_source_data.py
      112_build_national_gpkg.py
    120_excel_structuring/
      121_download_excels.ipynb
  200_gis_aggregation/
    201_aggregation.py

sample_outputs/
  tables/
    zenkoku_all_sample.csv
  gis/
    .gitkeep

---

## What each script does (high level)

### `scripts/100_download_preprocess/111_bulk_download_source_data.py`
- e-Statからソースデータ（都道府県別など）を、APIを使わずにまとめてダウンロードします。
- 取得先URLや対象（statsId等）はスクリプト内の設定に従います。

### `scripts/100_download_preprocess/112_build_national_gpkg.py`
- ダウンロード済みの境界線データ（都道府県別）を結合して、全国統一のGPKGを生成します。
- CRS/列名などの統一処理が入っている想定です。

### `scripts/100_download_preprocess/120_excel_structuring/121_download_excels.ipynb`
- Excel（特殊配列）の取得や、参照箇所の検討・動作確認用のNotebookです。
- 「どのセル/範囲を読むか」を試行しやすいように ipynb にしています。

### `scripts/200_gis_aggregation/201_aggregation.py`
- 構造化したExcel由来データを、**小地域の境界データに結合**し、GPKGやCSVを出力します。
- 47都道府県分を一括処理する想定です。

---

## Sample outputs

`sample_outputs/` は「出力形式のイメージ」を置く場所です。

- `sample_outputs/tables/zenkoku_all_sample.csv`  
  全国集計のテーブル出力例（サンプル）

- `sample_outputs/gis/`  
  GPKGはサイズが大きくなりやすいため、原則コミットしません（フォルダ維持用に `.gitkeep` を置いています）。

---

## How to run (typical order)

環境やデータセットによって前後しますが、基本の流れは次の順番です。

1. `111_bulk_download_source_data.py`（必要なソースをDL）
2. `112_build_national_gpkg.py`（境界線を全国に統合してGPKG作成）
3. `121_download_excels.ipynb`（Excel取得・参照箇所確認）
4. `201_aggregation.py`（Excel抽出→構造化→境界結合→GPKG/CSV出力）

実行例（例）：

```bash
python scripts/100_download_preprocess/111_bulk_download_source_data.py
python scripts/100_download_preprocess/112_build_national_gpkg.py
python scripts/200_gis_aggregation/201_aggregation.py
