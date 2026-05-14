#!/usr/bin/env python3
"""
Download the most-recent PDF (descending into most-recent folders) and run
the pdfplumber extraction + postprocessing. Save all outputs under a folder
named with today's date.

Usage:
  python descargar_procesar_latest.py <page_url>

Outputs:
  <YYYY-MM-DD>/downloads/            (downloaded PDF)
  <YYYY-MM-DD>/extracted_tables/     (extraction + merged CSV)
"""

import sys
import argparse
from pathlib import Path
from datetime import date
import shutil
import io
import ftplib
import pandas as pd
import logging

# reuse orchestrator and extractors
from descargar_latest_recursive import descend_and_download
from extract_and_postprocess import extractor_pdfplumber, clean_and_merge_pdfplumber


PAGE_URL = "https://www.mific.gob.ni/Inicio/Comercio/Comercio-Interior/Boletines/Bolet%C3%ADn-Al-Consumidor"
OUT_ROOT = '.'


def main():
    today = date.today().isoformat()
    base = Path(OUT_ROOT) / today
    downloads_dir = base / 'downloads'
    extracted_root = base / 'extracted_tables'

    downloads_dir.mkdir(parents=True, exist_ok=True)
    extracted_root.mkdir(parents=True, exist_ok=True)

    # configure logging: file + console (overwrite each run) in script folder
    log_path = Path(__file__).with_name('log.txt')
    try:
        if log_path.exists():
            log_path.unlink()
    except Exception:
        pass
    logger = logging.getLogger('mific-auto')
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(log_path, mode='w', encoding='utf-8')
    ch = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter('[%(levelname)s] %(message)s')
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.handlers = [fh, ch]

    logger.info('downloading latest PDFs into %s', downloads_dir)
    # descend_and_download will create the files inside downloads_dir; request DOWNLOAD_COUNT most recent
    DOWNLOAD_COUNT = 2

    # start from empty downloads dir to avoid re-using old files
    for p in downloads_dir.iterdir():
        try:
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p)
        except Exception:
            pass

    all_downloaded = []
    exclude_names = set()
    remaining = DOWNLOAD_COUNT
    # try repeatedly until we have enough or no more found
    while remaining > 0:
        rc, found = descend_and_download(PAGE_URL, out_dir=str(downloads_dir), count=remaining, exclude_names=list(exclude_names))
        if rc != 0 and not found:
            print('[warn] downloader returned', rc, 'and found', found)
            break
        for f in found:
            all_downloaded.append(f)
            exclude_names.add(Path(f).name)
        remaining = DOWNLOAD_COUNT - len(all_downloaded)
        if not found:
            break

    if not all_downloaded:
        # fallback: pick any PDFs in the downloads dir
        pdfs = sorted(downloads_dir.rglob('*.pdf'), key=lambda p: p.stat().st_mtime)
        if not pdfs:
            print('[error] no PDF found in', downloads_dir)
            return 2
        selected = pdfs[-DOWNLOAD_COUNT:]
        logger.info('selected PDFs for processing (fallback): %s', selected)
    else:
        selected = [Path(p) for p in all_downloaded]
        logger.info('selected PDFs for processing: %s', selected)

    merged_files = []
    for pdf in selected:
        logger.info('extracting tables with pdfplumber for %s', pdf)
        res = extractor_pdfplumber(str(pdf), str(extracted_root))
        logger.info('pdfplumber -> %s tables for %s', len(res), pdf.name)

        logger.info('running post-processing (clean + merge) for %s', pdf)
        merged = clean_and_merge_pdfplumber(pdf.stem, str(extracted_root))
        if merged:
            try:
                out_target = base / Path(merged).name
                shutil.copy2(merged, out_target)
                logger.info('merged CSV copied to %s', out_target)
            except Exception:
                logger.info('merged CSV at %s', merged)
            merged_files.append(str(merged))
        else:
            logger.warning('no merged output produced for %s', pdf)

    # combine merged files into one dataframe if we have any
    combined_new_df = None
    new_max = None
    if merged_files:
        dfs = []
        for m in merged_files:
            try:
                df = pd.read_csv(m, parse_dates=['fecha'], encoding='utf-8-sig')
                dfs.append(df)
            except Exception as e:
                logger.warning('failed reading merged file %s: %s', m, e)
        if dfs:
            try:
                combined_new_df = pd.concat(dfs, ignore_index=True, sort=False)
                new_max = pd.to_datetime(combined_new_df['fecha'], errors='coerce').max()
                logger.info('combined new data max fecha = %s', new_max)
            except Exception as e:
                logger.error('failed combining merged files: %s', e)
                combined_new_df = None

    # FTP sync: compare with precios_mific.csv on FTP and append if newer
    FTP_HOST = 'nicadatos.lat'
    FTP_USER = 'ccomerical2@nicadatos.lat'
    FTP_PASS = 'ccomercial422'
    FTP_DIR = '/public_html/data_precios'
    REMOTE_FILE = 'precios_mific.csv'

    def ftp_download(host, user, passwd, remote_dir, filename):
        try:
            with ftplib.FTP(host) as ftp:
                ftp.login(user=user, passwd=passwd)
                ftp.cwd(remote_dir)
                bio = io.BytesIO()
                ftp.retrbinary(f'RETR {filename}', bio.write)
                bio.seek(0)
                return bio.read()
        except Exception as e:
            print('[warn] FTP download failed for %s/%s: %s' % (remote_dir, filename, e))
            return None

    def ftp_upload(host, user, passwd, remote_dir, filename, data_bytes):
        try:
            with ftplib.FTP(host) as ftp:
                ftp.login(user=user, passwd=passwd)
                ftp.cwd(remote_dir)
                bio = io.BytesIO(data_bytes)
                ftp.storbinary(f'STOR {filename}', bio)
            return True
        except Exception as e:
            print('[error] FTP upload failed for %s/%s: %s' % (remote_dir, filename, e))
            return False

    try:
        logger.info('Attempting to download remote precios file from FTP: %s/%s', FTP_DIR, REMOTE_FILE)
        remote_bytes = ftp_download(FTP_HOST, FTP_USER, FTP_PASS, FTP_DIR, REMOTE_FILE)
        if remote_bytes:
            try:
                from io import BytesIO
                remote_df = pd.read_csv(BytesIO(remote_bytes), parse_dates=['fecha'], encoding='utf-8-sig')
                remote_max = pd.to_datetime(remote_df['fecha'], errors='coerce').max()
                logger.info('Remote precios_mific.csv max fecha = %s', remote_max)
            except Exception as e:
                logger.warning('Failed to parse remote CSV: %s', e)
                remote_df = None
                remote_max = None
        else:
            remote_df = None
            remote_max = None

        # Determine which new dates (if any) are not present in remote data and append only those rows
        if combined_new_df is not None:
            try:
                new_dates = set(pd.to_datetime(combined_new_df['fecha'], errors='coerce').dt.date.dropna())
            except Exception:
                new_dates = set()
            try:
                remote_dates = set(pd.to_datetime(remote_df['fecha'], errors='coerce').dt.date.dropna()) if remote_df is not None else set()
            except Exception:
                remote_dates = set()

            missing_dates = sorted(list(new_dates - remote_dates))
            if not new_dates:
                logger.info('No fecha values found in new data — skipping upload')
            elif not missing_dates:
                logger.info('All new fechas already exist in remote file — skipping upload')
            else:
                logger.info('New fechas to append: %s', missing_dates)
                # filter rows from combined_new_df whose date is in missing_dates
                try:
                    mask = pd.to_datetime(combined_new_df['fecha'], errors='coerce').dt.date.isin(missing_dates)
                    to_add = combined_new_df[mask]
                except Exception as e:
                    logger.warning('Failed to filter new rows by fecha: %s', e)
                    to_add = combined_new_df

                if remote_df is not None:
                    try:
                        combined = pd.concat([remote_df, to_add], ignore_index=True, sort=False)
                    except Exception:
                        combined = to_add
                else:
                    combined = to_add

                out_b = io.BytesIO()
                combined.to_csv(out_b, index=False, encoding='utf-8-sig')
                out_b.seek(0)
                ok = ftp_upload(FTP_HOST, FTP_USER, FTP_PASS, FTP_DIR, REMOTE_FILE, out_b.read())
                if ok:
                    logger.info('Remote precios_mific.csv updated successfully on FTP')
                else:
                    logger.error('Failed to update remote precios_mific.csv')
    except Exception as e:
        logger.exception('FTP sync step failed: %s', e)

    logger.info('summary: outputs saved under %s', base)
    return 0


if __name__ == '__main__':
    sys.exit(main())
