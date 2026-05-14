#!/usr/bin/env python3
"""
Bulk downloader: traverse Evotiva GetItems API and download all PDFs.

Usage:
  pip install selenium requests tqdm
  python descargar_all.py <page_url>

This script uses the same request capture approach as `evotiva_browse_api.py`.
It opens a headless Chrome to capture the GetItems request, copies cookies,
walks the folder tree, collects PDF items and downloads them to `downloads/`.
Files are named using the ItemName prefixed by YYYY-MM-DD when a timestamp
is available (same convention as the interactive tool).
"""

import sys
import time
import os
import re
import argparse
from urllib.parse import urlparse
import requests

try:
    from tqdm import tqdm
except Exception:
    tqdm = None

# reuse helpers from the interactive script
from evotiva_browse_api import (
    make_driver,
    extract_getitems_from_logs,
    find_fileactions_base,
    copy_cookies_to_session,
    call_getitems,
    resolve_file_url,
    download_file,
    sanitize_filename,
)


def ensure_dir(d):
    os.makedirs(d, exist_ok=True)


def construct_download_url(fileactions_base, itemid, req_headers):
    if not fileactions_base:
        return None
    download_url = fileactions_base.rstrip('/') + '/DownloadFile?ItemId=' + str(itemid)
    modid = req_headers.get('ModuleId') if req_headers else None
    tabid = req_headers.get('TabId') if req_headers else None
    if modid:
        download_url += '&ModuleId=' + str(modid)
    if tabid:
        download_url += '&TabId=' + str(tabid)
    return download_url


def detect_date_prefix(f, siblings):
    ts_pat = re.compile(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)')
    # 1) siblings
    for it in siblings:
        iname = str(it.get('ItemName') or '').strip()
        if ts_pat.match(iname):
            return iname[:10]
    # 2) own fields
    for v in f.values():
        if isinstance(v, str) and ts_pat.match(v.strip()):
            return v.strip()[:10]
    # 3) common timestamp keys
    for key in ('LastModifiedOnDate','LastModifiedOn','CreatedOn','CreatedOnDate','ModifiedOn'):
        val = f.get(key)
        if isinstance(val, str) and ts_pat.match(val.strip()):
            return val.strip()[:10]
    return None


def collect_all_pdfs(session, reqinfo, start_item, driver, fileactions_base):
    queue = [start_item]
    seen = set()
    pdf_tasks = []
    while queue:
        current = queue.pop(0)
        if str(current) in seen:
            continue
        seen.add(str(current))

        # refresh token from page
        try:
            token = driver.execute_script("var e=document.querySelector('input[name=\"__RequestVerificationToken\"]'); return e?e.value:null;")
            if token:
                reqinfo.setdefault('headers', {})['RequestVerificationToken'] = token
        except Exception:
            pass

        try:
            js = call_getitems(session, reqinfo, itemId=current)
            data = js.get('Data') if isinstance(js, dict) else []
        except Exception as e:
            print('[warn] GetItems failed for', current, e)
            continue

        for d in data:
            if d.get('IsFolder'):
                iid = d.get('ItemID') or d.get('ItemId')
                if iid and str(iid) not in seen:
                    queue.append(iid)
            else:
                name = str(d.get('ItemName') or '')
                if name.lower().endswith('.pdf'):
                    pdf_tasks.append({'file': d, 'siblings': data})
    return pdf_tasks


def download_all(page_url, out_dir='downloads'):
    driver = make_driver()
    try:
        print('[debug] loading page to capture API request...')
        driver.get(page_url)
        time.sleep(1.0)
        try:
            # try to open widget panel if present
            from selenium.webdriver.common.by import By
            el = driver.find_element(By.CSS_SELECTOR, '#dnn_ctr1838_View_pnlEvotivaFilesContainer')
            el.click()
            time.sleep(0.6)
        except Exception:
            pass

        logs = driver.get_log('performance')
        reqinfo = extract_getitems_from_logs(logs)
        if not reqinfo:
            print('[error] GetItems request not found in performance logs; interact with the page manually and re-run')
            return 2
        fileactions_base = find_fileactions_base(logs, reqinfo)
        print('[debug] using GetItems URL:', reqinfo.get('url'))
        print('[debug] fileactions_base =', fileactions_base)

        s = requests.Session()
        copy_cookies_to_session(driver, s)

        # determine start folder
        start = None
        try:
            from urllib.parse import parse_qs
            qs = parse_qs(urlparse(reqinfo['url']).query)
            if 'rootItemId' in qs and qs['rootItemId']:
                start = qs['rootItemId'][0]
            elif 'itemId' in qs and qs['itemId']:
                start = qs['itemId'][0]
        except Exception:
            pass
        if start is None:
            start = '0'

        print('[info] collecting list of PDFs (this may take a while)')
        tasks = collect_all_pdfs(s, reqinfo, start, driver, fileactions_base)
        print(f'[info] found {len(tasks)} PDF files')

        ensure_dir(out_dir)
        iterator = tqdm(tasks, desc='Downloading PDFs') if tqdm else tasks
        for t in iterator:
            f = t['file']
            siblings = t['siblings']
            itemid = f.get('ItemID') or f.get('ItemId')
            url = None
            if f.get('ItemUid'):
                url = resolve_file_url(s, fileactions_base, f.get('ItemUid'), reqinfo.get('headers'))
            if not url:
                url = construct_download_url(fileactions_base, itemid, reqinfo.get('headers') or {})
            if not url:
                print('[warn] no download URL for', itemid, f.get('ItemName'))
                continue

            # filename logic: date prefix + ItemName, preserve extension from URL if needed
            item_name = f.get('ItemName') or ''
            base = os.path.basename(urlparse(url).path) or ''
            name_root = item_name or base
            try:
                from pathlib import Path
                if item_name and not Path(name_root).suffix and base:
                    ext = Path(base).suffix
                    if ext:
                        name_root = name_root + ext
            except Exception:
                pass
            date_pref = detect_date_prefix(f, siblings)
            if date_pref and not str(name_root).startswith(date_pref):
                name_root = f"{date_pref} - {name_root}"
            safe = sanitize_filename(name_root)
            target = os.path.join(out_dir, safe)

            hdrs = {}
            orig_h = reqinfo.get('headers') or {}
            for k in ('RequestVerificationToken', 'ModuleId', 'Referer', 'X-Requested-With', 'User-Agent', 'TabId'):
                if orig_h.get(k):
                    hdrs[k] = orig_h.get(k)
            try:
                download_file(s, url, target, headers=hdrs)
            except Exception as e:
                print('[error] failed to download', url, e)

        print('[done] all downloads finished')
        return 0
    finally:
        driver.quit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('page_url')
    parser.add_argument('--out', default='downloads', help='output directory')
    args = parser.parse_args()
    return download_all(args.page_url, out_dir=args.out)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python descargar_all.py <page_url>')
        sys.exit(1)
    sys.exit(main())
