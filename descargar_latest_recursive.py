#!/usr/bin/env python3
"""
Descend the Evotiva folder tree always choosing the most-recently-modified
item, until a PDF is found, then download that PDF.

Usage:
  python descargar_latest_recursive.py <page_url>

This reuses helpers from `evotiva_browse_api.py` just like `descargar_all.py`.
"""

import sys
import time
import os
import argparse
from datetime import datetime
from urllib.parse import urlparse
import requests

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


def parse_date_string(s):
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        # handle trailing Z
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        return datetime.fromisoformat(s)
    except Exception:
        # fallback common patterns
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(s.split('.')[0], fmt)
            except Exception:
                pass
    return None


def item_mod_time(item):
    # look for common modification/creation keys
    for key in ('LastModifiedOnDate','LastModifiedOn','ModifiedOn','CreatedOn','CreatedOnDate'):
        val = item.get(key)
        if isinstance(val, str):
            dt = parse_date_string(val)
            if dt:
                return dt
    # sometimes the ISO appears in other fields
    for v in item.values():
        if isinstance(v, str):
            dt = parse_date_string(v)
            if dt:
                return dt
    return None


def choose_top_n(items, n=1):
    """Return up to `n` items from `items` sorted by modification time desc.

    Items without parseable dates are considered older than dated items.
    """
    if not items:
        return []
    dated = []
    undated = []
    for it in items:
        dt = item_mod_time(it)
        if dt is None:
            undated.append((None, it))
        else:
            dated.append((dt, it))
    dated.sort(key=lambda x: x[0], reverse=True)
    # return items, prefer dated first, then undated in original order
    out = [it for _, it in dated]
    out.extend([it for _, it in undated])
    return out[:n]


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


def find_pdfs_in_items(items):
    """Return list of PDF items sorted by most-recent modification first."""
    pdfs = [d for d in items if not d.get('IsFolder') and str(d.get('ItemName') or '').lower().endswith('.pdf')]
    if not pdfs:
        return []
    return choose_top_n(pdfs, n=len(pdfs))


def descend_and_download(page_url, out_dir='downloads', count=1, branch=2, exclude_names=None):
    """Descend the folder tree with branching.

    At each level, inspect the folder: download any PDFs found (newest first)
    until `count` PDFs have been downloaded. If more are needed, enqueue the
    `branch` most-recent subfolders and continue (breadth-first expansion
    prioritizing recent folders).
    """
    driver = make_driver()
    try:
        print('[debug] loading page to capture GetItems request...')
        driver.get(page_url)
        time.sleep(1.0)
        try:
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

        # traversal state: breadth-first queue of folder ids (strings)
        queue = [start]
        tried = set()
        ensure_dir = lambda d: os.makedirs(d, exist_ok=True)
        ensure_dir(out_dir)

        downloaded = []
        exclude_names = set(exclude_names or [])

        # helper to download a pdf item; returns True if downloaded
        def _download_pdf_item(item):
            itemid = item.get('ItemID') or item.get('ItemId')
            url = None
            if item.get('ItemUid'):
                url = resolve_file_url(s, fileactions_base, item.get('ItemUid'), reqinfo.get('headers'))
            if not url:
                url = construct_download_url(fileactions_base, itemid, reqinfo.get('headers') or {})
            if not url:
                print('[warn] no download URL for', itemid, item.get('ItemName'))
                return False

            item_name = item.get('ItemName') or ''
            safe = sanitize_filename(item_name)
            target = os.path.join(out_dir, safe)
            hdrs = {}
            orig_h = reqinfo.get('headers') or {}
            for k in ('RequestVerificationToken', 'ModuleId', 'Referer', 'X-Requested-With', 'User-Agent', 'TabId'):
                if orig_h.get(k):
                    hdrs[k] = orig_h.get(k)
            try:
                download_file(s, url, target, headers=hdrs)
                print('[done] downloaded', target)
                downloaded.append(target)
                return True
            except Exception as e:
                print('[error] failed to download', url, e)
                return False

        # BFS-like expansion with prioritization per node
        while queue and len(downloaded) < count:
            current = queue.pop(0)
            if str(current) in tried:
                continue
            tried.add(str(current))

            # refresh token if present
            try:
                token = driver.execute_script("var e=document.querySelector('input[name=\"__RequestVerificationToken\"]'); return e?e.value:null;")
                if token:
                    reqinfo.setdefault('headers', {})['RequestVerificationToken'] = token
            except Exception:
                pass

            try:
                js = call_getitems(s, reqinfo, itemId=current)
                data = js.get('Data') if isinstance(js, dict) else []
            except Exception as e:
                print('[warn] GetItems failed for', current, e)
                continue

            if not data:
                # no items here; continue with other queued folders
                continue

            # download PDFs in this folder (newest first)
            pdf_items = find_pdfs_in_items(data)
            if pdf_items:
                for p in pdf_items:
                    if len(downloaded) >= count:
                        break
                    name = (p.get('ItemName') or '')
                    if name in exclude_names:
                        print('[info] skipping excluded PDF', name)
                        continue
                    print('[info] found PDF in folder', current, '->', name)
                    ok = _download_pdf_item(p)
                    if ok:
                        exclude_names.add(name)
                if len(downloaded) >= count:
                    break

            # enqueue top-`branch` subfolders (most-recent first)
            folders = [d for d in data if d.get('IsFolder')]
            if folders:
                top = choose_top_n(folders, n=branch)
                for ch in top:
                    next_id = ch.get('ItemID') or ch.get('ItemId')
                    if next_id and str(next_id) not in tried:
                        print('[info] queuing folder', next_id, 'name:', ch.get('ItemName'))
                        queue.append(next_id)

        if not downloaded:
            print('[info] no PDFs found in the tree starting at', start)
            return (5, downloaded)
        return (0, downloaded)

    finally:
        driver.quit()
