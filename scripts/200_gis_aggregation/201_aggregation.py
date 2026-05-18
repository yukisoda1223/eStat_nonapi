# -*- coding: utf-8 -*-
"""
全国版 - 町字単位データ統合前処理
ポリゴンデータをベースに各種データを左外部結合
"""

import os
import glob
import zipfile
import pandas as pd
import geopandas as gpd
import numpy as np
from pathlib import Path
from shapely.geometry import Point
import warnings
warnings.filterwarnings('ignore')

print("="*80)
print("全国版 町字単位データ統合前処理 開始")
print("="*80)

# ===== パス設定 =====
INPUT_BASE = r"C:...\Downloads\zenkoku"
OUTPUT_DIR = r"C:...\Downloads\zenkoku\output"
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "zenkoku_all.csv")

# 都道府県コードリスト（01～47）
PREF_CODES = [str(i).zfill(2) for i in range(1, 48)]

# CRS設定
TARGET_CRS = "EPSG:6668"  # JGD2011
# 平面直角座標系は都道府県ごとに変わるため、後で設定

# 出力ディレクトリ作成
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

# ===== ZIP展開用関数 =====

def extract_zip_if_needed(zip_path):
    """ZIPファイルを同じディレクトリに展開（未展開の場合のみ）"""
    if not os.path.exists(zip_path):
        return None
    
    extract_dir = Path(zip_path).parent
    zip_name = Path(zip_path).stem
    
    # すでに展開済みか確認
    extracted_files = list(extract_dir.glob(f"{zip_name}*"))
    if len(extracted_files) > 1:  # ZIP本体以外にファイルがある
        return extract_dir
    
    print(f"  展開中: {Path(zip_path).name}")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)
    
    return extract_dir

def find_files_with_pattern(base_dir, pattern):
    """パターンマッチングでファイルを検索"""
    found = glob.glob(os.path.join(base_dir, "**", pattern), recursive=True)
    return found

# ===== ファイル探索関数 =====

def find_kokusei_files(base_dir, pref_code):
    """国勢調査CSVファイルを検索（h03_, h06_01_, h06_02_, h18_を含む）"""
    patterns = {
        'h03': f"h03_{pref_code}.csv",
        'h06_01': f"h06_01_{pref_code}.csv",
        'h06_02': f"h06_02_{pref_code}.csv",
        'h18': f"h18_{pref_code}.csv"
    }
    
    results = {}
    for key, pattern in patterns.items():
        files = find_files_with_pattern(base_dir, pattern)
        results[key] = files[0] if files else None
    
    return results

def find_estat_files(base_dir, table_name, pref_code):
    """e-StatのCSV/TXTファイルを検索（tblT001xxxCxx.csv または .txt）"""
    # まずZIPファイルを探して展開
    zip_pattern = f"{table_name}C{pref_code}.zip"
    zip_files = find_files_with_pattern(base_dir, zip_pattern)
    
    if zip_files:
        extract_zip_if_needed(zip_files[0])
    
    # CSVファイルを検索
    csv_pattern = f"{table_name}C{pref_code}.csv"
    csv_files = find_files_with_pattern(base_dir, csv_pattern)
    
    if csv_files:
        return csv_files[0]
    
    # TXTファイルを検索
    txt_pattern = f"{table_name}C{pref_code}.txt"
    txt_files = find_files_with_pattern(base_dir, txt_pattern)
    
    if txt_files:
        return txt_files[0]
    
    return None

# ===== データ処理関数（前処理コードから再利用） =====

def clean_keys(df, city_col='市区町村コード', town_col='町丁字コード'):
    """結合キーを文字列型に統一・ゼロ埋め"""
    df[city_col] = df[city_col].astype(str).str.strip().str.zfill(5)
    df[town_col] = df[town_col].astype(str).str.strip().str.zfill(9)
    return df

def standardize_chocho_code(code):
    """町丁字コードを標準化（6桁に）"""
    code_str = str(code).strip()
    if len(code_str) == 4:
        return '00' + code_str
    elif len(code_str) <= 3:
        return '00' + code_str.zfill(4)
    else:
        return code_str.zfill(6)

def create_key_code_kokusei(df):
    """国勢調査データ用のKEY_CODE作成"""
    df = df.copy()
    df['市区町村コード'] = df['市区町村コード'].astype(str).str.strip()
    df['町丁字コード'] = df['町丁字コード'].astype(str).str.strip()
    df['町丁字コード_標準'] = df['町丁字コード'].apply(standardize_chocho_code)
    df['KEY_CODE'] = df['市区町村コード'] + df['町丁字コード_標準']
    return df

def remove_aggregated_rows(df):
    """大字・町名が連続している場合、最初の行（集計行）を削除"""
    if '大字・町名' not in df.columns:
        return df
    
    df = df.copy()
    df['大字・町名'] = df['大字・町名'].astype(str).str.strip()
    
    rows_to_keep = []
    for town_name, group in df.groupby('大字・町名', sort=False):
        if len(group) >= 2:
            group_filtered = group[
                (group['字・丁目名'].notna()) & 
                (group['字・丁目名'].astype(str).str.strip() != '')
            ]
            if len(group_filtered) > 0:
                rows_to_keep.append(group_filtered)
            else:
                rows_to_keep.append(group)
        else:
            rows_to_keep.append(group)
    
    if rows_to_keep:
        df_result = pd.concat(rows_to_keep, ignore_index=True)
        return df_result
    return df

def read_estat_like(path, use_cols):
    """eStat形式CSV/TXT読み込み（2行目がヘッダ、A列がKEY_CODE）"""
    if not path or not os.path.exists(path):
        # TXTファイルも探す
        if path:
            txt_path = path.replace('.csv', '.txt')
            if os.path.exists(txt_path):
                path = txt_path
            else:
                return None
        else:
            return None
    
    # CSVまたはTXTとして読み込み（エンコーディングを複数試行）
    for encoding in ['cp932', 'utf-8', 'shift-jis', 'utf-8-sig']:
        try:
            df = pd.read_csv(path, encoding=encoding, header=1, dtype=str, sep=None, engine='python')
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"    エラー: {Path(path).name} の読み込み失敗 - {str(e)}")
            return None
    else:
        print(f"    エラー: {Path(path).name} のエンコーディング判定失敗")
        return None
    
    first_col = df.columns[0]
    df = df.rename(columns={first_col: "KEY_CODE"})
    df["KEY_CODE"] = df["KEY_CODE"].astype(str).str.strip()

    missing = [c for c in use_cols if c not in df.columns]
    if missing:
        print(f"    警告: {Path(path).name} に列がありません: {missing}")
        return None

    df = df[["KEY_CODE"] + use_cols].copy()
    return df

# ===== 国勢調査データ読み込み関数 =====

def load_kokusei_h03(file_path):
    """h03_XX.csv（人口）を読み込み"""
    if not file_path:
        return None
    
    ENC = 'cp932'
    KEYS = ['市区町村コード', '町丁字コード']
    
    _raw = pd.read_csv(file_path, encoding=ENC, header=None, low_memory=False)
    df = _raw.iloc[5:, [1,2,3,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33]].copy()
    df.columns = [
        '男女', '市区町村コード', '町丁字コード', '都道府県名', '市区町村名', '大字・町名', '字・丁目名',
        '総数_人口', '0～4歳', '5～9歳', '10～14歳', '15～19歳', '20～24歳', '25～29歳', '30～34歳',
        '35～39歳', '40～44歳', '45～49歳', '50～54歳', '55～59歳', '60～64歳',
        '65～69歳', '70～74歳', '75～79歳', '80～84歳', '85～89歳', '90～94歳', '95～99歳', '100歳以上'
    ]
    
    df = df[df['男女'].astype(str).str.strip() == '総数'].copy()
    df = df.drop(columns=['男女'])
    df = df.dropna(subset=KEYS).reset_index(drop=True)
    df = remove_aggregated_rows(df)
    df = create_key_code_kokusei(df)
    
    # 数値変換
    num_cols = [c for c in df.columns if c not in KEYS + ['KEY_CODE', '町丁字コード_標準', '都道府県名', '市区町村名', '大字・町名', '字・丁目名']]
    df[num_cols] = df[num_cols].apply(pd.to_numeric, errors='coerce')
    
    # 年齢割合算出
    df['15歳未満割合'] = (df[['0～4歳','5～9歳','10～14歳']].sum(axis=1) / df['総数_人口']).round(4)
    df['15～64歳割合'] = (df[['15～19歳','20～24歳','25～29歳','30～34歳','35～39歳','40～44歳','45～49歳','50～54歳','55～59歳','60～64歳']].sum(axis=1) / df['総数_人口']).round(4)
    df['65歳以上割合'] = (df[['65～69歳','70～74歳','75～79歳','80～84歳','85～89歳','90～94歳','95～99歳','100歳以上']].sum(axis=1) / df['総数_人口']).round(4)
    
    return df

def load_kokusei_h06_01(file_path):
    """h06_01_XX.csv（世帯数）を読み込み"""
    if not file_path:
        return None
    
    ENC = 'cp932'
    KEYS = ['市区町村コード', '町丁字コード']
    
    _raw = pd.read_csv(file_path, encoding=ENC, header=None, low_memory=False)
    df = _raw.iloc[4:, [1,2,3,12,13,14,15,16,17,18,19]].copy()
    df.columns = [
        '世帯員の年齢による世帯の種類', '市区町村コード', '町丁字コード',
        '総数_世帯1', '親族のみの世帯_世帯1', '核家族世帯_世帯1',
        'うち夫婦のみの世帯_世帯1', 'うち夫婦と子供から成る世帯_世帯1',
        '核家族以外の世帯_世帯1', '非親族を含む世帯_世帯1', '単独世帯_世帯1'
    ]
    
    df = df[df['世帯員の年齢による世帯の種類'].astype(str).str.strip() == '総数'].copy()
    df = df.drop(columns=['世帯員の年齢による世帯の種類'])
    df = df.dropna(subset=KEYS).reset_index(drop=True)
    
    # 名称列を追加
    _raw_full = pd.read_csv(file_path, encoding=ENC, header=None, low_memory=False)
    df_names = _raw_full.iloc[4:, [1,2,8,9,10,11]].copy()
    df_names.columns = ['市区町村コード', '町丁字コード', '都道府県名', '市区町村名', '大字・町名', '字・丁目名']
    df_names = df_names.dropna(subset=KEYS).reset_index(drop=True)
    
    df = pd.concat([df.reset_index(drop=True), df_names[['都道府県名', '市区町村名', '大字・町名', '字・丁目名']].reset_index(drop=True)], axis=1)
    df = remove_aggregated_rows(df)
    df = create_key_code_kokusei(df)
    
    return df

def load_kokusei_h06_02(file_path):
    """h06_02_XX.csv（世帯別人数）を読み込み"""
    if not file_path:
        return None
    
    ENC = 'cp932'
    KEYS = ['市区町村コード', '町丁字コード']
    
    _raw = pd.read_csv(file_path, encoding=ENC, header=None, low_memory=False)
    df = _raw.iloc[4:, [1,2,11,12,13,14,15,16,17,18]].copy()
    df.columns = [
        '市区町村コード', '町丁字コード',
        '総数_世帯2', '親族のみの世帯_世帯2', '核家族世帯_世帯2',
        'うち夫婦のみの世帯_世帯2', 'うち夫婦と子供から成る世帯_世帯2',
        '核家族以外の世帯_世帯2', '非親族を含む世帯_世帯2', '単独世帯_世帯2'
    ]
    df = df.dropna(subset=KEYS).reset_index(drop=True)
    
    # 名称列を追加
    _raw_full = pd.read_csv(file_path, encoding=ENC, header=None, low_memory=False)
    df_names = _raw_full.iloc[4:, [1,2,7,8,9,10]].copy()
    df_names.columns = ['市区町村コード', '町丁字コード', '都道府県名', '市区町村名', '大字・町名', '字・丁目名']
    df_names = df_names.dropna(subset=KEYS).reset_index(drop=True)
    
    df = pd.concat([df.reset_index(drop=True), df_names[['都道府県名', '市区町村名', '大字・町名', '字・丁目名']].reset_index(drop=True)], axis=1)
    df = remove_aggregated_rows(df)
    df = create_key_code_kokusei(df)
    
    return df

def load_kokusei_h18(file_path):
    """h18_XX.csv（居住期間）を読み込み"""
    if not file_path:
        return None
    
    ENC = 'cp932'
    KEYS = ['市区町村コード', '町丁字コード']
    
    _raw = pd.read_csv(file_path, encoding=ENC, header=None, low_memory=False)
    df = _raw.iloc[4:, [1,2,3,12,13,14,15,16,17,18]].copy()
    df.columns = [
        '男女', '市区町村コード', '町丁字コード',
        '総数_居住', '出生時から', '1年未満', '1年以上5年未満',
        '5年以上10年未満', '10年以上20年未満', '20年以上'
    ]
    
    df = df[df['男女'].astype(str).str.strip() == '総数'].copy()
    df = df.drop(columns=['男女'])
    df = df.dropna(subset=KEYS).reset_index(drop=True)
    
    # 名称列を追加
    _raw_full = pd.read_csv(file_path, encoding=ENC, header=None, low_memory=False)
    df_names = _raw_full.iloc[4:, [1,2,3,8,9,10,11]].copy()
    df_names.columns = ['男女', '市区町村コード', '町丁字コード', '都道府県名', '市区町村名', '大字・町名', '字・丁目名']
    df_names = df_names[df_names['男女'].astype(str).str.strip() == '総数'].copy()
    df_names = df_names.drop(columns=['男女'])
    df_names = df_names.dropna(subset=KEYS).reset_index(drop=True)
    
    df = pd.concat([df.reset_index(drop=True), df_names[['都道府県名', '市区町村名', '大字・町名', '字・丁目名']].reset_index(drop=True)], axis=1)
    df = remove_aggregated_rows(df)
    df = create_key_code_kokusei(df)
    
    return df

# ===== メイン処理: 都道府県ごとの処理 =====

def process_prefecture(pref_code):
    """都道府県ごとのデータ処理"""
    print(f"\n{'='*80}")
    print(f"都道府県コード {pref_code} の処理開始")
    print(f"{'='*80}")
    
    try:
        # ===== 国勢調査データ読み込み =====
        print(f"\n[{pref_code}] 国勢調査データ読み込み")
        
        kokusei_base = os.path.join(INPUT_BASE, "人口データ", "Raw")
        kokusei_files = find_kokusei_files(kokusei_base, pref_code)
        
        # 人口データがない場合はスキップ
        if not kokusei_files.get('h03'):
            print(f"  警告: h03_{pref_code}.csv が見つかりません - スキップ")
            return None
        
        df3 = load_kokusei_h03(kokusei_files['h03'])
        if df3 is None:
            print(f"  エラー: h03_{pref_code}.csv の読み込み失敗")
            return None
        print(f"  h03 (人口): {len(df3)}行")
        
        # 世帯データ
        kokusei_base_setai1 = os.path.join(INPUT_BASE, "世帯1データ", "Raw")
        kokusei_files_setai1 = find_kokusei_files(kokusei_base_setai1, pref_code)
        df6_1 = load_kokusei_h06_01(kokusei_files_setai1.get('h06_01'))
        print(f"  h06_01 (世帯1): {len(df6_1) if df6_1 is not None else 0}行")
        
        kokusei_base_setai2 = os.path.join(INPUT_BASE, "世帯2データ", "Raw")
        kokusei_files_setai2 = find_kokusei_files(kokusei_base_setai2, pref_code)
        df6_2 = load_kokusei_h06_02(kokusei_files_setai2.get('h06_02'))
        print(f"  h06_02 (世帯2): {len(df6_2) if df6_2 is not None else 0}行")
        
        # 居住期間データ
        kokusei_base_kyoju = os.path.join(INPUT_BASE, "居住期間データ", "Raw")
        kokusei_files_kyoju = find_kokusei_files(kokusei_base_kyoju, pref_code)
        df18 = load_kokusei_h18(kokusei_files_kyoju.get('h18'))
        print(f"  h18 (居住期間): {len(df18) if df18 is not None else 0}行")
        
        # 国勢調査データを統合
        print(f"\n[{pref_code}] 国勢調査データ統合中...")
        merged_kokusei = df3.copy()
        
        if df6_1 is not None:
            merged_kokusei = merged_kokusei.merge(
                df6_1.drop(columns=['市区町村コード', '町丁字コード', '町丁字コード_標準', '都道府県名', '市区町村名', '大字・町名', '字・丁目名'], errors='ignore'),
                on='KEY_CODE', how='left'
            )
        
        if df6_2 is not None:
            merged_kokusei = merged_kokusei.merge(
                df6_2.drop(columns=['市区町村コード', '町丁字コード', '町丁字コード_標準', '都道府県名', '市区町村名', '大字・町名', '字・丁目名'], errors='ignore'),
                on='KEY_CODE', how='left'
            )
        
        if df18 is not None:
            merged_kokusei = merged_kokusei.merge(
                df18.drop(columns=['市区町村コード', '町丁字コード', '町丁字コード_標準', '都道府県名', '市区町村名', '大字・町名', '字・丁目名'], errors='ignore'),
                on='KEY_CODE', how='left'
            )
        
        print(f"  国勢調査統合後: {len(merged_kokusei)}行")
        
        # ===== e-Statデータ読み込み =====
        print(f"\n[{pref_code}] e-Statデータ読み込み")
        
        estat_085_path = find_estat_files(os.path.join(INPUT_BASE, "住宅所有データ", "Raw"), "tblT001085", pref_code)
        estat_086_path = find_estat_files(os.path.join(INPUT_BASE, "住宅の建て方世帯数データ", "Raw"), "tblT001086", pref_code)
        estat_103_path = find_estat_files(os.path.join(INPUT_BASE, "産業別就業者数データ", "Raw"), "tblT001103", pref_code)
        
        cols_085 = ["住宅に住む一般世帯", "持ち家", "民営借家"]
        cols_086 = ["一戸建", "長屋建", "共同住宅"]
        cols_103 = [
            "Ａ農業、林業", "うち農業", "Ｂ漁業", "Ｃ鉱業、採石業、砂利採取業",
            "Ｄ建設業", "Ｅ製造業", "Ｆ電気・ガス・熱供給・水道業", "Ｇ情報通信業",
            "Ｈ運輸業、郵便業", "Ｉ卸売業、小売業", "Ｊ金融業、保険業",
            "Ｋ不動産業、物品賃貸業", "Ｌ学術研究、専門・技術サービス業",
            "Ｍ宿泊業、飲食サービス業", "Ｎ生活関連サービス業、娯楽業",
            "Ｏ教育、学習支援業", "Ｐ医療、福祉", "Ｑ複合サービス事業",
            "Ｒサービス業（他に分類されないもの）", "Ｓ公務（他に分類されるものを除く）",
            "Ｔ分類不能の産業", "総数（従業上の地位「不詳」を含む）",
            "雇用者（役員を含む）", "自営業主（家庭内職者を含む）", "家族従業者"
        ]
        
        df_085 = read_estat_like(estat_085_path, cols_085)
        df_086 = read_estat_like(estat_086_path, cols_086)
        df_103 = read_estat_like(estat_103_path, cols_103)
        
        print(f"  住宅所有: {len(df_085) if df_085 is not None else 0}行")
        print(f"  住宅建て方: {len(df_086) if df_086 is not None else 0}行")
        print(f"  産業別就業者: {len(df_103) if df_103 is not None else 0}行")
        
        # e-Stat統合
        merged_estat = pd.DataFrame({'KEY_CODE': merged_kokusei['KEY_CODE'].unique()})
        
        if df_085 is not None:
            merged_estat = merged_estat.merge(df_085, on='KEY_CODE', how='left')
        if df_086 is not None:
            merged_estat = merged_estat.merge(df_086, on='KEY_CODE', how='left')
        if df_103 is not None:
            merged_estat = merged_estat.merge(df_103, on='KEY_CODE', how='left')
        
        print(f"  e-Stat統合後: {len(merged_estat)}行")
        
        # ===== 最終統合 =====
        print(f"\n[{pref_code}] 全データ統合")
        
        df_final = merged_kokusei.merge(merged_estat, on='KEY_CODE', how='left')
        
        print(f"  最終行数: {len(df_final)}")
        print(f"  最終列数: {len(df_final.columns)}")
        
        return df_final
        
    except Exception as e:
        print(f"\n  エラー: 都道府県コード {pref_code} の処理に失敗")
        print(f"  詳細: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

# ===== 全国ポリゴンデータ読み込み =====

print("\n[全国] ポリゴンベースデータ読み込み")
POLYGON_GPKG = os.path.join(INPUT_BASE, "ポリゴンデータ", "Processed", "zenkoku.gpkg")

if not os.path.exists(POLYGON_GPKG):
    raise FileNotFoundError(f"ポリゴンデータが見つかりません: {POLYGON_GPKG}")

gdf_base = gpd.read_file(POLYGON_GPKG)
print(f"  元CRS: {gdf_base.crs}")
print(f"  行数: {len(gdf_base)}")

# CRS確認
if gdf_base.crs != TARGET_CRS:
    print(f"  CRS変換: {gdf_base.crs} → {TARGET_CRS}")
    gdf_base = gdf_base.to_crs(TARGET_CRS)

# KEY_CODE確認
if 'KEY_CODE' not in gdf_base.columns:
    raise ValueError("ポリゴンデータにKEY_CODE列がありません")

gdf_base['KEY_CODE'] = gdf_base['KEY_CODE'].astype(str).str.strip()
print(f"  ユニークKEY_CODE数: {gdf_base['KEY_CODE'].nunique()}")

# 重複チェック
if gdf_base['KEY_CODE'].duplicated().sum() > 0:
    print(f"  警告: 重複KEY_CODE: {gdf_base['KEY_CODE'].duplicated().sum()}件")
    print("  ポリゴン統合中...")
    
    agg_dict = {}
    for col in gdf_base.columns:
        if col in ['geometry', 'KEY_CODE']:
            continue
        elif pd.api.types.is_numeric_dtype(gdf_base[col]):
            agg_dict[col] = 'sum'
        else:
            agg_dict[col] = 'first'
    
    gdf_base = gdf_base.dissolve(by='KEY_CODE', aggfunc=agg_dict).reset_index()
    print(f"  統合後: {len(gdf_base)}行")

# ===== 全都道府県処理 =====

print("\n[全国] 都道府県ごとの処理開始")

all_data = []
success_count = 0
fail_count = 0

for pref_code in PREF_CODES:
    df_pref = process_prefecture(pref_code)
    
    if df_pref is not None:
        all_data.append(df_pref)
        success_count += 1
    else:
        fail_count += 1

print(f"\n{'='*80}")
print(f"都道府県処理完了: 成功 {success_count}件, 失敗 {fail_count}件")
print(f"{'='*80}")

# ===== 全国データ統合 =====

if not all_data:
    raise RuntimeError("処理できた都道府県データがありません")

print("\n[全国] 全国データ統合中...")
df_all_kokusei = pd.concat(all_data, ignore_index=True)
print(f"  統合後: {len(df_all_kokusei)}行, {len(df_all_kokusei.columns)}列")

# ===== ポリゴンデータと結合 =====

print("\n[全国] ポリゴンデータと結合")
print(f"  ポリゴン: {len(gdf_base)}行")
print(f"  国勢調査+e-Stat: {len(df_all_kokusei)}行")

# ジオメトリを退避
geom_col = gdf_base[['KEY_CODE', 'geometry']].copy()
df_base = gdf_base.drop(columns=['geometry'])

# データ結合
df_merged = df_base.merge(df_all_kokusei, on='KEY_CODE', how='left')
print(f"  結合後: {len(df_merged)}行")

# ジオメトリを戻す
df_merged = df_merged.merge(geom_col, on='KEY_CODE', how='left')
gdf_result = gpd.GeoDataFrame(df_merged, geometry='geometry', crs=TARGET_CRS)

# 結合状況確認
matched = gdf_result['総数_人口'].notna().sum()
print(f"  データマッチ: {matched}行 / {len(gdf_result)}行 ({matched/len(gdf_result)*100:.1f}%)")

# ===== 空間データ処理 =====

print("\n[全国] 空間データ処理")

# 全国共通データ読み込み
CHIKA_SHP = os.path.join(INPUT_BASE, "地価公示データ", "L01-20.shp")
RAIL_SHP = os.path.join(INPUT_BASE, "駅鉄道データ", "N02-19_RailroadSection.shp")
STATION_SHP = os.path.join(INPUT_BASE, "駅鉄道データ", "N02-19_Station.shp")
ROAD_SHP = os.path.join(INPUT_BASE, "道路データ", "N01-07L-2K_Road.shp")

# 駅データ
print("  駅データ読み込み...")
gdf_station = gpd.read_file(STATION_SHP, encoding='cp932')
if gdf_station.crs != TARGET_CRS:
    gdf_station = gdf_station.to_crs(TARGET_CRS)
print(f"    駅数: {len(gdf_station)}")

# 鉄道データ
print("  鉄道データ読み込み...")
gdf_rail = gpd.read_file(RAIL_SHP, encoding='cp932')
if gdf_rail.crs != TARGET_CRS:
    gdf_rail = gdf_rail.to_crs(TARGET_CRS)
print(f"    鉄道路線数: {len(gdf_rail)}")

# 道路データ
print("  道路データ読み込み...")
gdf_road = gpd.read_file(ROAD_SHP, encoding='cp932')
if gdf_road.crs is None:
    gdf_road = gdf_road.set_crs("EPSG:4612")
if gdf_road.crs != TARGET_CRS:
    gdf_road = gdf_road.to_crs(TARGET_CRS)
print(f"    道路数: {len(gdf_road)}")

# 地価データ
print("  地価データ読み込み...")
gdf_chika = gpd.read_file(CHIKA_SHP, encoding='cp932')
if gdf_chika.crs is None:
    gdf_chika = gdf_chika.set_crs("EPSG:4612")
if gdf_chika.crs != TARGET_CRS:
    gdf_chika = gdf_chika.to_crs(TARGET_CRS)
print(f"    地価ポイント数: {len(gdf_chika)}")

# 平面直角座標系への変換（距離計算用）
# ★ 全国版では精度を犠牲にして一律EPSG:6677（平面直角7系）を使用
# より正確には都道府県ごとに適切な平面直角座標系を選ぶべき
PROJECTED_CRS = "EPSG:6677"

print(f"\n  投影座標系変換: {PROJECTED_CRS}")
gdf_poly_proj = gdf_result.to_crs(PROJECTED_CRS)
gdf_station_proj = gdf_station.to_crs(PROJECTED_CRS)
gdf_rail_proj = gdf_rail.to_crs(PROJECTED_CRS)
gdf_road_proj = gdf_road.to_crs(PROJECTED_CRS)
gdf_chika_proj = gdf_chika.to_crs(PROJECTED_CRS)

# 道路種別フィルタ
if 'N01_001' in gdf_road_proj.columns:
    gdf_highway_proj = gdf_road_proj[gdf_road_proj['N01_001'].astype(str) == '1'].copy()
    gdf_major_proj = gdf_road_proj[gdf_road_proj['N01_001'].astype(str).isin(['2', '3'])].copy()
else:
    gdf_highway_proj = gpd.GeoDataFrame(geometry=[], crs=PROJECTED_CRS)
    gdf_major_proj = gpd.GeoDataFrame(geometry=[], crs=PROJECTED_CRS)

print(f"    高速道路: {len(gdf_highway_proj)}件")
print(f"    主要道路: {len(gdf_major_proj)}件")

# 駅・鉄道・道路・地価の空間計算
print("\n  空間計算実行中...")
spatial_data = []

total_rows = len(gdf_poly_proj)
for idx, row in gdf_poly_proj.iterrows():
    poly_geom = row.geometry
    rep_point = poly_geom.representative_point()
    
    # 駅数
    stations_within = gdf_station_proj[gdf_station_proj.within(poly_geom)]
    station_count = len(stations_within)
    
    # 最近駅距離
    distances_station = gdf_station_proj.geometry.distance(rep_point).sort_values()
    nearest_station = distances_station.iloc[0] if len(distances_station) > 0 else np.nan
    second_station = distances_station.iloc[1] if len(distances_station) > 1 else np.nan
    
    # 鉄道フラグ
    rail_flag = 1 if gdf_rail_proj.intersects(poly_geom).any() else 0
    
    # 道路フラグ
    highway_flag = 1 if len(gdf_highway_proj) > 0 and gdf_highway_proj.intersects(poly_geom).any() else 0
    major_flag = 1 if len(gdf_major_proj) > 0 and gdf_major_proj.intersects(poly_geom).any() else 0
    
    # 最近地価距離
    distances_chika = gdf_chika_proj.geometry.distance(rep_point)
    if len(distances_chika) > 0:
        nearest_chika_idx = distances_chika.idxmin()
        nearest_chika_dist = distances_chika.min()
        nearest_chika_row = gdf_chika_proj.loc[nearest_chika_idx]
        chika_val = nearest_chika_row.get('L01_006', np.nan)
        chika_rate = nearest_chika_row.get('L01_007', np.nan)
    else:
        nearest_chika_dist = np.nan
        chika_val = np.nan
        chika_rate = np.nan
    
    # 面積
    area = poly_geom.area
    
    spatial_data.append({
        'KEY_CODE': row['KEY_CODE'],
        '駅数': station_count,
        '最近駅距離': nearest_station,
        '2nd最近駅距離': second_station,
        '鉄道フラグ': rail_flag,
        '高速道路フラグ': highway_flag,
        '主要道路フラグ': major_flag,
        '公示地価': chika_val,
        '対年変動率': chika_rate,
        '最近地価距離': nearest_chika_dist,
        '面積': area
    })
    
    if (idx + 1) % 1000 == 0:
        print(f"    {idx + 1}/{total_rows} 処理済 ({(idx+1)/total_rows*100:.1f}%)")

print(f"    {total_rows}/{total_rows} 処理済 (100.0%)")

df_spatial = pd.DataFrame(spatial_data)

# ===== 代表点計算 =====

print("\n  代表点計算...")
gdf_result['rep_point'] = gdf_result.geometry.representative_point()
gdf_result['代表点_lon'] = gdf_result['rep_point'].x
gdf_result['代表点_lat'] = gdf_result['rep_point'].y
gdf_result['ジオメトリ'] = gdf_result.geometry.to_wkt()

# ===== 最終データ統合 =====

print("\n[全国] 最終データ統合")

df_final = pd.DataFrame(gdf_result.drop(columns=['geometry', 'rep_point']))
df_final = df_final.merge(df_spatial, on='KEY_CODE', how='left')

print(f"  最終行数: {len(df_final)}")
print(f"  最終列数: {len(df_final.columns)}")

# ===== CSV出力 =====

print("\n[全国] CSV出力")

# カラム順序整理（PREF_NAMEをCITY_NAMEの左に配置）
desired_order = [
    'KEY_CODE', 'S_AREA', 'PREF_NAME', 'CITY_NAME', 'S_NAME',
    '市区町村コード', '町丁字コード', '都道府県名', '市区町村名', '大字・町名', '字・丁目名',
    '総数_人口', '0～4歳', '5～9歳', '10～14歳', '15～19歳', '20～24歳', '25～29歳', '30～34歳',
    '35～39歳', '40～44歳', '45～49歳', '50～54歳', '55～59歳', '60～64歳',
    '65～69歳', '70～74歳', '75～79歳', '80～84歳', '85～89歳', '90～94歳', '95～99歳', '100歳以上',
    '15歳未満割合', '15～64歳割合', '65歳以上割合',
    '総数_世帯1', '親族のみの世帯_世帯1', '核家族世帯_世帯1',
    'うち夫婦のみの世帯_世帯1', 'うち夫婦と子供から成る世帯_世帯1',
    '核家族以外の世帯_世帯1', '非親族を含む世帯_世帯1', '単独世帯_世帯1',
    '総数_世帯2', '親族のみの世帯_世帯2', '核家族世帯_世帯2',
    'うち夫婦のみの世帯_世帯2', 'うち夫婦と子供から成る世帯_世帯2',
    '核家族以外の世帯_世帯2', '非親族を含む世帯_世帯2', '単独世帯_世帯2',
    '総数_居住', '出生時から', '1年未満', '1年以上5年未満',
    '5年以上10年未満', '10年以上20年未満', '20年以上',
    '住宅に住む一般世帯', '持ち家', '民営借家',
    '一戸建', '長屋建', '共同住宅',
    'Ａ農業、林業', 'うち農業', 'Ｂ漁業', 'Ｃ鉱業、採石業、砂利採取業',
    'Ｄ建設業', 'Ｅ製造業', 'Ｆ電気・ガス・熱供給・水道業', 'Ｇ情報通信業',
    'Ｈ運輸業、郵便業', 'Ｉ卸売業、小売業', 'Ｊ金融業、保険業',
    'Ｋ不動産業、物品賃貸業', 'Ｌ学術研究、専門・技術サービス業',
    'Ｍ宿泊業、飲食サービス業', 'Ｎ生活関連サービス業、娯楽業',
    'Ｏ教育、学習支援業', 'Ｐ医療、福祉', 'Ｑ複合サービス事業',
    'Ｒサービス業（他に分類されないもの）', 'Ｓ公務（他に分類されるものを除く）',
    'Ｔ分類不能の産業', '総数（従業上の地位「不詳」を含む）',
    '雇用者（役員を含む）', '自営業主（家庭内職者を含む）', '家族従業者',
    '駅数', '最近駅距離', '2nd最近駅距離', '鉄道フラグ',
    '高速道路フラグ', '主要道路フラグ',
    '面積', '公示地価', '対年変動率', '最近地価距離',
    '代表点_lon', '代表点_lat', 'ジオメトリ'
]

final_columns = [c for c in desired_order if c in df_final.columns]
remaining_columns = [c for c in df_final.columns if c not in final_columns]

if remaining_columns:
    print(f"  追加カラム: {remaining_columns}")
    final_columns.extend(remaining_columns)

df_output = df_final[final_columns].copy()

# CSV出力
df_output.to_csv(OUTPUT_CSV, index=False, encoding='utf_8_sig')  # BOM付きUTF-8
print(f"  ✓ 保存完了: {OUTPUT_CSV}")

# ===== 完了サマリー =====

print("\n" + "="*80)
print("全国版処理完了サマリー")
print("="*80)
print(f"最終行数: {len(df_output):,}")
print(f"最終列数: {len(df_output.columns)}")
print(f"出力ファイル: {OUTPUT_CSV}")
print(f"\n都道府県処理: 成功 {success_count}件, 失敗 {fail_count}件")
print(f"\n主要統計:")
print(f"  - 人口データ有: {df_output['総数_人口'].notna().sum():,}件 ({df_output['総数_人口'].notna().sum()/len(df_output)*100:.1f}%)")
print(f"  - 駅数データ有: {df_output['駅数'].notna().sum():,}件 ({df_output['駅数'].notna().sum()/len(df_output)*100:.1f}%)")
print(f"  - 地価データ有: {df_output['公示地価'].notna().sum():,}件 ({df_output['公示地価'].notna().sum()/len(df_output)*100:.1f}%)")
print("="*80)