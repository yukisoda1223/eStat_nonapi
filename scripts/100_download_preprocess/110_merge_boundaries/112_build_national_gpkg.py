import re
import zipfile
from pathlib import Path
from datetime import datetime

import pandas as pd
import geopandas as gpd


RAW_DIR = Path(r"...\Downloads\zenkoku\ポリゴンデータ\Raw")
OUT_DIR = RAW_DIR.parent / "Processed"

# 生成物
EXTRACT_DIR = OUT_DIR / "_extracted"         # 作業用：ここに全部展開
GPKG_PATH = OUT_DIR / "zenkoku.gpkg"
CRS_REPORT_PATH = OUT_DIR / "crs_report.csv"
README_PATH = OUT_DIR / "about_crs.txt"

# GPKGレイヤ名（1レイヤ結合）
LAYER_NAME = "polygons"


def guess_pref_code_from_name(name: str) -> str | None:
    """
    zipファイル名から都道府県コード(01-47)を推定。
    例: A002005212020_code02_shape.zip -> "02"
    """
    m = re.search(r"(?:^|[_-])code(\d{2})(?:[_-]|\.|$)", name)
    if m:
        return m.group(1)
    # もし別命名ならここに追加ルールを書く
    return None


def ensure_empty_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def unzip_all(raw_dir: Path, extract_dir: Path) -> list[Path]:
    """
    raw_dir配下のzipをすべて extract_dir/ZIP名/ に展開
    戻り値：展開先フォルダのリスト
    """
    ensure_empty_dir(extract_dir)
    zip_paths = sorted(raw_dir.glob("*.zip"))
    if not zip_paths:
        raise FileNotFoundError(f"No zip files found in: {raw_dir}")

    extracted_folders = []
    for z in zip_paths:
        dest = extract_dir / z.stem
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(z, "r") as zipf:
            zipf.extractall(dest)
        extracted_folders.append(dest)

    return extracted_folders


def find_shp_files(folder: Path) -> list[Path]:
    # ZIPによってはサブフォルダがあるのでrglob
    return sorted(folder.rglob("*.shp"))


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1) 解凍
    extracted = unzip_all(RAW_DIR, EXTRACT_DIR)

    rows = []
    gdfs = []

    # 2) 読み込み＆CRS記録
    for folder in extracted:
        zip_name = folder.name  # zip stem
        pref_code = guess_pref_code_from_name(zip_name)

        shp_files = find_shp_files(folder)
        if not shp_files:
            rows.append({
                "zip_stem": zip_name,
                "pref_code": pref_code,
                "shp_path": "",
                "status": "NO_SHP_FOUND",
                "crs_epsg": "",
                "crs_wkt": "",
                "note": "",
            })
            continue

        # 原則：最初のshpを使う（複数ある場合はレポートに残す）
        # もしZIP内に複数shpがあるのが普通なら、ここを「全shpを対象」に変更できます。
        shp = shp_files[0]

        try:
            gdf = gpd.read_file(shp)

            # CRS情報（epsgが取れない場合もある）
            crs_obj = gdf.crs
            epsg = crs_obj.to_epsg() if crs_obj is not None else None
            wkt = crs_obj.to_wkt() if crs_obj is not None else None

            rows.append({
                "zip_stem": zip_name,
                "pref_code": pref_code,
                "shp_path": str(shp),
                "status": "OK",
                "crs_epsg": epsg if epsg is not None else "",
                "crs_wkt": wkt if wkt is not None else "",
                "note": "multiple_shp_in_zip" if len(shp_files) > 1 else "",
                "feature_count": len(gdf),
                "geometry_type_sample": str(gdf.geometry.geom_type.mode().iloc[0]) if len(gdf) else "",
            })

            # 出所追跡用フィールド追加
            gdf["pref_code"] = pref_code if pref_code is not None else ""
            gdf["source_zip"] = f"{zip_name}.zip"

            gdfs.append(gdf)

        except Exception as e:
            rows.append({
                "zip_stem": zip_name,
                "pref_code": pref_code,
                "shp_path": str(shp),
                "status": "READ_FAILED",
                "crs_epsg": "",
                "crs_wkt": "",
                "note": repr(e),
            })

    # 3) CRSレポート出力（結合前）
    report = pd.DataFrame(rows)
    report.to_csv(CRS_REPORT_PATH, index=False, encoding="utf-8-sig")

    ok = report[report["status"] == "OK"].copy()
    if ok.empty:
        raise RuntimeError(f"No readable shapefiles. See report: {CRS_REPORT_PATH}")

    # 4) CRS方針：基本は「全て同じならそのまま」。混在/欠損はレポート＆処理上は可能な範囲で合わせる
    #    geopandas の concat はCRSが同一でないと危険なので、
    #    - 最初に「基準CRS」を決める（最初のOKのCRS）
    #    - CRS欠損はそのままだと変換できないので注意喚起（ここでは欠損があれば結合前に停止する設計）
    base_crs = gdfs[0].crs

    # CRS欠損チェック
    missing_crs = [i for i, gdf in enumerate(gdfs) if gdf.crs is None]
    if missing_crs:
        raise RuntimeError(
            "Some inputs have missing CRS (no .prj or unreadable). "
            f"Cannot safely merge. See: {CRS_REPORT_PATH}"
        )

    # CRS混在チェック＆必要なら変換
    # 「たぶん全部一緒」を前提にしつつ、違っていたら基準に変換して結合します。
    normalized = []
    for gdf in gdfs:
        if gdf.crs != base_crs:
            normalized.append(gdf.to_crs(base_crs))
        else:
            normalized.append(gdf)

    merged = pd.concat(normalized, ignore_index=True)
    merged = gpd.GeoDataFrame(merged, geometry="geometry", crs=base_crs)

    # 5) GPKG出力（同名があれば上書きしたいので削除）
    if GPKG_PATH.exists():
        GPKG_PATH.unlink()

    merged.to_file(GPKG_PATH, layer=LAYER_NAME, driver="GPKG")

    # 6) CRS説明ファイル（最終CRSを明示）
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    final_epsg = merged.crs.to_epsg() if merged.crs is not None else None
    final_wkt = merged.crs.to_wkt() if merged.crs is not None else None

    README_PATH.write_text(
        "\n".join([
            f"Generated: {now}",
            f"Input raw dir: {RAW_DIR}",
            f"Extract dir: {EXTRACT_DIR}",
            f"Output gpkg: {GPKG_PATH}",
            f"GPKG layer: {LAYER_NAME}",
            "",
            "CRS handling:",
            "- Detected CRS for each input shapefile is recorded in crs_report.csv",
            "- Merge output CRS is set to the CRS of the first readable shapefile.",
            "- If any input CRS differed, it was reprojected to the output CRS before merging.",
            "",
            f"Final CRS EPSG: {final_epsg if final_epsg is not None else 'unknown'}",
            "Final CRS WKT (may be long):",
            final_wkt if final_wkt else "unknown",
            "",
        ]),
        encoding="utf-8"
    )

    print("DONE")
    print("Output folder:", OUT_DIR)
    print("GPKG:", GPKG_PATH)
    print("CRS report:", CRS_REPORT_PATH)
    print("CRS note:", README_PATH)


if __name__ == "__main__":
    main()