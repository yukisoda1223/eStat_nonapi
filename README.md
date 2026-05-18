# eStat_nonapi

e-Statのデータを**APIを使わずに**（Webの直接ダウンロード）取得し、都道府県単位で提供されるデータを集約して、**全国版のGIS（GPKG）**や**構造化CSV**として出力するためのツール群です。

- 境界線データ：ダウンロード → 都道府県別データを結合 → 全国1ファイル（GPKG）
- Excel（特殊配列）：参照箇所（セル/範囲）を指定して抽出 → 47都道府県分を実行 → 小地域境界に結合 → GPKG/CSV出力

> 注意：このリポジトリは「コード」を公開するもので、e-Statから取得したデータそのものは同梱しません。

---

## Repository structure
---
現在の主な構成は以下です。
```text
eStat_nonapi/
├─ scripts/
│ ├─ 100_download_preprocess/
│ │ ├─ 110_merge_boundaries/
│ │ │ ├─ 111_bulk_download_source_data.py
│ │ │ └─ 112_build_national_gpkg.py
│ │ └─ 120_excel_structuring/
│ │   └─ 121_download_excels.ipynb
│ └─ 200_gis_aggregation/
│     └─ 201_aggregation.py
└─ sample_outputs/
├─ tables/
│ └─ zenkoku_all_sample.csv
└─ gis/
└─ .gitkeep
```


## What each script does

#### `scripts/100_download_preprocess/111_bulk_download_source_data.py`
- e-Statの統計地理情報システムから、全国47都道府県分の境界データ（小地域）を一括ダウンロードします。
- **取得元**: [統計地理情報システムデータダウンロード](https://www.e-stat.go.jp/gis/statmap-search)
- **対象データ**: 令和2年国勢調査（A002005212020）の小地域境界データ（Shape形式）
- **処理内容**:
  - 都道府県コード01～47の境界データZIPファイルを順次ダウンロード
  - 既存ファイルがある場合はスキップ（0バイトファイルは再取得）
  - レート制限のため各リクエスト間に1秒の待機時間を設定
  - ダウンロードエラー時は続行し、エラー内容を出力
- **出力先**: `C:\...\Downloads\zenkoku\ポリゴンデータ\Raw\`
- **ファイル形式**: `A002005212020_code{都道府県コード}_shape.zip`（例: `A002005212020_code01_shape.zip`）

#### `scripts/100_download_preprocess/112_build_national_gpkg.py`
- ダウンロード済みの境界線データ（都道府県別ZIP）を展開・結合して、全国統一のGPKGを生成します。
- **処理内容**:
  - 全ZIPファイルを `_extracted/` に展開
  - 各都道府県のShapefileを読み込み、CRS（座標参照系）を検証
  - CRS混在時は最初のファイルのCRSを基準に統一（自動変換）
  - 出所追跡用フィールド（`pref_code`, `source_zip`）を付与
  - 全都道府県データを1つのGPKGファイル（1レイヤ）に統合
- **出力ファイル**:
  - `zenkoku.gpkg`: 全国統合境界データ（レイヤ名: `polygons`）
  - `crs_report.csv`: 各都道府県のCRS検証レポート
  - `about_crs.txt`: 最終CRS情報の説明ファイル
- **出力先**: `C:\...\Downloads\zenkoku\ポリゴンデータ\Processed\`
- **注意事項**: CRS欠損（.prjファイル不在）のShapefileがある場合はエラーで停止

#### `scripts/100_download_preprocess/121_download_*.py`
- e-Statから町字単位の統計データを都道府県別（01～47）に一括ダウンロードするスクリプト群です。
- **共通仕様**:
  - 都道府県コードまたは統計情報IDを順次変更しながら、全国47都道府県分のデータを取得
  - レスポンスが404の場合やHTML（ログイン誘導画面等）の場合は自動スキップ
  - エラー発生時も処理を継続し、最後に取得結果サマリ（成功数/404数/エラー数）を出力
  - 既存ファイルの上書き動作（スキップ処理は未実装）
- **取得元**: 
  - e-Stat 統計データファイルダウンロード（`statInfId` パラメータ方式）
  - e-Stat 統計地理情報システム（`statsId` + `code` パラメータ方式）
- **対象データ例**:
  - `121_download_居住期間.py`: 平成18年度 居住期間データ（CSV形式、`h18_01.csv` ～ `h18_47.csv`）
  - `121_download_住宅所有.py`: 住宅の所有関係データ（ZIP形式、`tblT001085C01.zip` ～ `tblT001085C47.zip`）
  - その他、建て方、産業別就業者数、世帯構成など、複数の統計項目に対応
- **出力先**: `C:\...\Downloads\zenkoku\{データ種別}データ\Raw\`
- **カスタマイズ方法**:
  - `base`: 基準となる統計情報ID（下8桁）または開始番号
  - `STEP`: ID/コードの増分（通常は1または15）
  - `OUT_DIR`: 保存先ディレクトリ
  - URL構造やファイル命名規則は各統計項目に応じて調整
- **注意事項**: 
  - 一部スクリプトには未使用変数の参照エラーがあります（実行前に要確認）
  - 連番でないIDを使用する場合、404スキップが多発する可能性があります
  - レート制限対策（`time.sleep()`）は未実装のため、大量取得時は手動で追加推奨

#### `scripts/200_gis_aggregation/201_aggregation.py`
- 全国47都道府県分の町字単位データを統合処理します。
- **処理内容**:
  - 国勢調査データ（人口、世帯、居住期間）を都道府県別に読み込み、KEY_CODEで統合
  - e-Stat統計データ（住宅所有、建て方、産業別就業者数）を都道府県別に読み込み、KEY_CODEで統合
  - 全国ポリゴンGPKGをベースに、上記データを左外部結合
  - 空間データ（駅、鉄道、道路、地価公示）との空間演算（最近駅距離、駅数、鉄道フラグ、道路フラグ、地価等）を実行
  - 代表点座標（緯度経度）とジオメトリ（WKT形式）を付与
  - 最終的に全国統一CSVとして出力（`zenkoku_all.csv`）
- **出力形式**: UTF-8 BOM付きCSV、100列以上の統合データ
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
