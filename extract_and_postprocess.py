#!/usr/bin/env python3
"""
Single-script test: extract tables from one PDF (pdfplumber + optional camelot/tabula)
and post-process (clean + merge) into one CSV.

Usage:
  pip install pdfplumber pandas
  # optional: pip install camelot-py tabula-py jpype1
  python extract_and_postprocess.py --pdf "2026-02-03 - BOLETIN No. 02 - 2DA SEMANA ENERO 2026 MERCADO.pdf"

Outputs:
  extracted_tables/pdfplumber/        (raw csvs)
  extracted_tables/camelot/           (if available)
  extracted_tables/tabula/            (if available)
  extracted_tables/pdfplumber/merged/<stem> - merged_cleaned.csv
"""

import os
import re
import sys
from pathlib import Path
import argparse

# try to reuse week-parsing helper if available
try:
    from test_parse_week_dates import parse_week_date_from_stem
except Exception:
    parse_week_date_from_stem = None

def sanitize_filename(name):
    name = str(name).strip()
    name = re.sub(r'[\\/*:?"<>|]', '_', name)
    name = ' '.join(name.split())
    if len(name) > 200:
        name = name[:200]
    return name


def ensure_dir(p):
    Path(p).mkdir(parents=True, exist_ok=True)


def extractor_pdfplumber(pdf_path, out_root):
    try:
        import pdfplumber
    except Exception as e:
        print('[skip] pdfplumber missing:', e)
        return []
    out_dir = Path(out_root) / 'pdfplumber'
    ensure_dir(out_dir)
    results = []
    with pdfplumber.open(pdf_path) as doc:
        for i, page in enumerate(doc.pages, start=1):
            try:
                tables = page.extract_tables()
            except Exception:
                tables = []
            for j, table in enumerate(tables, start=1):
                fname = f"{Path(pdf_path).stem} - pdfplumber - p{i} - t{j}.csv"
                outp = out_dir / sanitize_filename(fname)
                import csv
                with open(outp, 'w', newline='', encoding='utf-8-sig') as fh:
                    writer = csv.writer(fh)
                    for row in table:
                        writer.writerow([c if c is not None else '' for c in row])
                results.append(str(outp))
    return results


def extractor_camelot(pdf_path, out_root):
    try:
        import camelot
    except Exception as e:
        print('[skip] camelot missing or failing import:', e)
        return []
    out_dir = Path(out_root) / 'camelot'
    ensure_dir(out_dir)
    results = []
    for flavor in ('lattice', 'stream'):
        try:
            tables = camelot.read_pdf(pdf_path, pages='all', flavor=flavor)
        except Exception as e:
            print(f'[warn] camelot {flavor} read failed:', e)
            continue
        for idx, t in enumerate(tables, start=1):
            path = out_dir / f"{Path(pdf_path).stem} - camelot-{flavor}-t{idx}.csv"
            try:
                try:
                    t.df.to_csv(str(path), index=False, encoding='utf-8-sig')
                except Exception:
                    t.to_csv(str(path))
                results.append(str(path))
            except Exception as e:
                print('[warn] camelot save failed:', e)
    return results


def extractor_tabula(pdf_path, out_root):
    try:
        import tabula
    except Exception as e:
        print('[skip] tabula-py missing:', e)
        return []
    out_dir = Path(out_root) / 'tabula'
    ensure_dir(out_dir)
    results = []
    for lattice in (True, False):
        try:
            dfs = tabula.read_pdf(pdf_path, pages='all', multiple_tables=True, lattice=lattice)
        except Exception as e:
            print(f'[warn] tabula lattice={lattice} failed:', e)
            continue
        for idx, df in enumerate(dfs, start=1):
            path = out_dir / f"{Path(pdf_path).stem} - tabula-lattice{lattice}-t{idx}.csv"
            try:
                df.to_csv(path, index=False, encoding='utf-8-sig')
                results.append(str(path))
            except Exception as e:
                print('[warn] tabula save failed:', e)
    return results


def clean_and_merge_pdfplumber(stem, extracted_root):
    import pandas as pd
    base = Path(extracted_root) / 'pdfplumber'
    if not base.exists():
        print('[info] no pdfplumber outputs to process')
        return None
    files = [p for p in base.glob('*.csv') if stem.lower() in p.name.lower() and 'cleaned' not in p.name.lower()]
    files.sort()
    tables = []
    def is_mostly_non_numeric(row):
        nonempty = [c for c in row if c is not None and str(c).strip()!='']
        if not nonempty:
            return False
        non_numeric = 0
        for v in nonempty:
            s = str(v).strip()
            if re.match(r'^[-+]?\d+[\.,]?\d*$', s.replace(',', '')):
                continue
            non_numeric += 1
        return non_numeric >= max(1, int(0.6*len(nonempty)))

    for p in files:
        try:
            df = pd.read_csv(p, header=None, dtype=str)
        except Exception as e:
            print('read failed', p, e); continue
        # remove everything before the header row (e.g. the row that contains 'N°' and 'PRODUCTO'/'U/M')
        header_idx = None
        try:
            max_scan = min(30, len(df))
            for i in range(max_scan):
                try:
                    vals = [str(x).upper() for x in df.iloc[i].tolist()]
                except Exception:
                    continue
                joined = ' '.join(vals)
                if ('PRODUCTO' in joined and ('U/M' in joined or 'U/M' in ' '.join(vals))) or 'N°' in joined or 'N' == vals[0]:
                    header_idx = i
                    break
            if header_idx is not None:
                df = df.iloc[header_idx:].reset_index(drop=True)
            else:
                # fallback: drop first 3 rows if header not found
                df = df.iloc[3:].reset_index(drop=True)
        except Exception:
            pass
        # robust string trimming without relying on DataFrame.applymap (compat issues)
        for col in df.columns:
            try:
                if df[col].dtype == object or df[col].dtype == 'string':
                    df[col] = df[col].astype(str).str.strip()
                else:
                    # convert non-object types to string and strip if needed
                    df[col] = df[col].apply(lambda x: str(x).strip() if pd.notna(x) else x)
            except Exception:
                try:
                    df[col] = df[col].astype(str).apply(lambda x: x.strip())
                except Exception:
                    pass
        df = df.dropna(how='all').dropna(axis=1, how='all').reset_index(drop=True)
        header_row = None
        for idx in range(min(3, len(df))):
            if is_mostly_non_numeric(df.iloc[idx].tolist()):
                header_row = idx; break
        if header_row is not None and header_row != 0:
            new_header = df.iloc[header_row].astype(str).tolist()
            df = df.drop(index=range(0, header_row+1))
            df.columns = new_header
            df = df.reset_index(drop=True)
        elif header_row == 0:
            df.columns = df.iloc[0].astype(str).tolist()
            df = df.drop(index=0).reset_index(drop=True)
        df = df.dropna(axis=1, how='all')
        tables.append(df)
    if not tables:
        print('[info] no cleaned tables produced')
        return None
    # align columns
    # First ensure each table has unique column labels (pandas can't reindex with duplicate labels)
    def make_unique_columns(cols):
        seen = {}
        out = []
        for c in cols:
            key = c if c is not None else ''
            if key in seen:
                seen[key] += 1
                new = f"{key}.{seen[key]}"
            else:
                seen[key] = 0
                new = key
            out.append(new)
        return out

    norm_tables = []
    for df in tables:
        cols = list(df.columns)
        if len(cols) != len(set(cols)):
            # duplicate labels present; make unique
            new_cols = make_unique_columns(cols)
            try:
                df = df.copy()
                df.columns = new_cols
            except Exception:
                # fallback: rename with numeric indices
                df = df.copy()
                df.columns = [f'col{i}' for i in range(len(new_cols))]
        norm_tables.append(df)

    all_cols = []
    for df in norm_tables:
        for c in df.columns:
            if c not in all_cols:
                all_cols.append(c)
    reindexed = [df.reindex(columns=all_cols) for df in norm_tables]
    merged = pd.concat(reindexed, ignore_index=True, sort=False)

    # CUSTOM CLEANING per user request:
    # - keep only the 2nd and 3rd columns (if present)
    # - find the first column that contains a '%' value and also keep that column and the column before it
    # - drop all other columns
    # - then drop rows where the second kept column is empty
    cols = list(merged.columns)
    keep = []
    # second and third columns (0-based indices 1 and 2)
    if len(cols) >= 2:
        keep.append(cols[1])
    if len(cols) >= 3:
        keep.append(cols[2])

    percent_col = None
    percent_idx = None
    for idx, col in enumerate(cols):
        try:
            # treat values as strings and look for '%'
            if merged[col].astype(str).str.contains('%', na=False).any():
                percent_col = col
                percent_idx = idx
                break
        except Exception:
            continue
    if percent_col is not None:
        if percent_col not in keep:
            keep.append(percent_col)
        if percent_idx is not None and percent_idx - 1 >= 0:
            prev_col = cols[percent_idx - 1]
            if prev_col not in keep:
                keep.append(prev_col)

    # preserve original order of columns as in `cols`
    keep_ordered = [c for c in cols if c in keep]
    if not keep_ordered:
        # fallback: keep all
        keep_ordered = cols
    merged = merged.reindex(columns=keep_ordered)

    # remove the last column entirely (user requested)
    try:
        if merged.shape[1] > 0:
            merged = merged.iloc[:, :-1]
    except Exception:
        pass

    # remove rows where the first column is empty/blank
    try:
        if merged.shape[1] >= 1:
            first_col = merged.columns[0]
            mask_first = merged[first_col].astype(str).str.strip().replace({'nan': ''}) != ''
            merged = merged[mask_first]
    except Exception:
        pass
    # Ensure first three columns have expected headers and drop rows where 'Producto' is empty
    try:
        cols_now = list(merged.columns)
        if len(cols_now) >= 1:
            rename_map = {}
            if len(cols_now) >= 1:
                rename_map[cols_now[0]] = 'Producto'
            if len(cols_now) >= 2:
                rename_map[cols_now[1]] = 'Unidad'
            if len(cols_now) >= 3:
                rename_map[cols_now[2]] = 'Precio'
            if rename_map:
                merged = merged.rename(columns=rename_map)
        # drop rows where Producto is empty/blank
        if 'Producto' in merged.columns:
            mask_prod = merged['Producto'].astype(str).str.strip().replace({'nan': ''}) != ''
            merged = merged[mask_prod]
    except Exception:
        pass

    # drop rows where the second kept column is empty (use positional access to avoid KeyError)
    try:
        if merged.shape[1] >= 2:
            # use iloc to avoid issues if column labels changed
            second_series = merged.iloc[:, 1].astype(str).str.strip().replace({'nan': ''})
            mask_nonempty = second_series != ''
            merged = merged[mask_nonempty]
    except Exception:
        pass

    # insert a `fecha` column extracted from the PDF filename (stem)
    try:
        date_val = None
        # prefer parsing week-style stems (e.g. '1RA SEMANA MAYO 2025')
        try:
            if parse_week_date_from_stem:
                parsed = parse_week_date_from_stem(stem)
                if parsed:
                    date_val = parsed
        except Exception:
            date_val = None

        # fallback: extract ISO date like YYYY-MM-DD from the stem
        if not date_val:
            m = re.search(r"\d{4}-\d{2}-\d{2}", stem)
            date_val = m.group(0) if m else stem

        try:
            merged.insert(0, 'fecha', date_val)
        except Exception:
            merged['fecha'] = date_val
    except Exception:
        pass

    out_dir = base / 'merged'
    ensure_dir(out_dir)
    out_path = out_dir / (f"{stem} - merged_cleaned.csv")
    merged.to_csv(out_path, index=False, encoding='utf-8-sig')
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pdf', required=True)
    parser.add_argument('--out', default='extracted_tables')
    args = parser.parse_args()
    pdf = Path(args.pdf)
    if not pdf.exists():
        print('PDF not found:', pdf); return 1
    stem = pdf.stem
    print('[info] extracting with pdfplumber...')
    res_pp = extractor_pdfplumber(str(pdf), args.out)
    print(f'[info] pdfplumber -> {len(res_pp)} tables')
    print('[info] skipping camelot/tabula — using pdfplumber only')
    res_c = []
    res_t = []

    print('[info] post-processing pdfplumber outputs (clean + merge)')
    merged = clean_and_merge_pdfplumber(stem, args.out)
    if merged:
        print('[done] merged file written to', merged)
    else:
        print('[warn] no merged output produced')
    print('\nSummary:')
    print(' pdfplumber:', len(res_pp))
    print(' camelot   :', len(res_c))
    print(' tabula    :', len(res_t))
    return 0


if __name__ == '__main__':
    sys.exit(main())
