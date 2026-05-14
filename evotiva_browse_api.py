#!/usr/bin/env python3
"""
Interactive browser for Evotiva GetItems API.

Usage:
  pip install selenium requests
  python evotiva_browse_api.py <page_url>

Starts a headless Chrome, captures the GetItems XHR from performance logs,
then lets you navigate folders by ItemID. It will show files and folders and
can resolve a file's download URL (but will not download files).
"""

import sys, time, json, re, os, argparse
from urllib.parse import urlparse, parse_qs
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import unicodedata
import pathlib


def make_driver():
    opts = Options()
    opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    return webdriver.Chrome(options=opts)


def extract_getitems_from_logs(logs):
    pattern = re.compile(r'GetItemsServices.*GetItems', re.I)
    for entry in logs:
        try:
            msg = json.loads(entry['message'])['message']
            if msg.get('method') == 'Network.requestWillBeSent':
                req = msg.get('params', {}).get('request', {})
                url = req.get('url')
                if url and pattern.search(url):
                    return {
                        'url': url,
                        'method': req.get('method', 'GET'),
                        'headers': req.get('headers', {}),
                        'postData': req.get('postData')
                    }
        except Exception:
            continue
    return None


def find_fileactions_base(logs, reqinfo):
    pat = re.compile(r'FileActionsServices', re.I)
    for entry in logs:
        try:
            msg = json.loads(entry['message'])['message']
            if msg.get('method') == 'Network.requestWillBeSent':
                req = msg.get('params', {}).get('request', {})
                url = req.get('url')
                if url and pat.search(url):
                    m = re.search(r'(.*/FileActionsServices)', url, re.I)
                    if m:
                        return m.group(1)
        except Exception:
            continue
    try:
        return reqinfo['url'].split('/GetItemsServices')[0] + '/FileActionsServices'
    except Exception:
        return None


def copy_cookies_to_session(driver, session):
    for c in driver.get_cookies():
        session.cookies.set(c['name'], c['value'], domain=c.get('domain'))


def call_getitems(session, reqinfo, itemId=None):
    url = reqinfo['url']
    if itemId is not None:
        # Replace itemId in the query string without re-encoding commas etc.
        def replace_query_param_preserve_encoding(url, param, value):
            # naive regex replace for param=... in the query portion
            parts = url.split('?', 1)
            if len(parts) == 1:
                return url
            base, q = parts
            # replace param if exists using callable to avoid backreference ambiguity
            pattern = re.compile(r'(' + re.escape(param) + r'=)([^&]*)')
            if pattern.search(q):
                def repl(m):
                    return m.group(1) + str(value)
                nq = pattern.sub(repl, q)
            else:
                # append
                if q:
                    nq = q + '&' + param + '=' + str(value)
                else:
                    nq = param + '=' + str(value)
            return base + '?' + nq

        url = replace_query_param_preserve_encoding(url, 'itemId', itemId)
    headers = {k: v for k, v in (reqinfo.get('headers') or {}).items() if k.lower() not in ('host', 'connection', 'content-length', 'accept-encoding')}
    headers['X-Requested-With'] = headers.get('X-Requested-With', 'XMLHttpRequest')
    # ensure Referer is present (from captured headers if available)
    if 'Referer' not in headers:
        orig_headers = reqinfo.get('headers') or {}
        if orig_headers.get('Referer'):
            headers['Referer'] = orig_headers.get('Referer')
    try:
        r = session.get(url, headers=headers, timeout=30)
    except requests.exceptions.RequestException as e:
        raise
    # fallback: if 404, try POST with JSON payload
    if r.status_code == 404:
        try:
            payload = {'itemId': itemId} if itemId is not None else {}
            rpost = session.post(reqinfo['url'], json=payload, headers=headers, timeout=30)
            if rpost.status_code == 200:
                r = rpost
        except Exception:
            pass
    r.raise_for_status()
    return r.json()


def resolve_file_url(session, fileactions_base, item_uid, headers_template):
    if not fileactions_base:
        return None
    url = fileactions_base.rstrip('/') + '/GetUrl'
    headers = {k: v for k, v in (headers_template or {}).items() if k.lower() not in ('host', 'connection', 'content-length', 'accept-encoding')}
    headers['X-Requested-With'] = headers.get('X-Requested-With', 'XMLHttpRequest')
    # Ensure token header if available in template
    orig = headers_template or {}
    if not headers.get('RequestVerificationToken') and orig.get('RequestVerificationToken'):
        headers['RequestVerificationToken'] = orig.get('RequestVerificationToken')
    # Debug: show attempted request
    try:
        params = {'itemUid': item_uid}
        print('[debug] resolving GetUrl via GET', url, 'params=', params)
        print('[debug] headers used:', {k: headers.get(k) for k in ('RequestVerificationToken','ModuleId','Referer','X-Requested-With') if headers.get(k)})
        r = session.get(url, params=params, headers=headers, timeout=30)
        print(f'[debug] GetUrl GET status={r.status_code} len={len(r.content)}')
        try:
            txt = r.text
            print('[debug] body snippet:', txt[:500])
        except Exception:
            pass
        if r.status_code == 200:
            try:
                j = r.json()
                if isinstance(j, dict):
                    for k in ('Url','url','Data'):
                        v = j.get(k)
                        if isinstance(v, str) and v.startswith('http'):
                            return v
                        if isinstance(v, dict) and 'Url' in v:
                            return v['Url']
            except Exception:
                txt = r.text.strip()
                if txt.startswith('http'):
                    return txt
    except Exception as e:
        print('[debug] GetUrl GET failed:', e)
    # Try POST fallback
    try:
        print('[debug] resolving GetUrl via POST', url)
        r = session.post(url, json={'itemUid': item_uid}, headers=headers, timeout=30)
        print(f'[debug] GetUrl POST status={r.status_code} len={len(r.content) if r.content else 0}')
        try:
            print('[debug] body snippet:', r.text[:500])
        except Exception:
            pass
        if r.status_code == 200:
            try:
                j = r.json()
                if isinstance(j, dict):
                    for k in ('Url','url','Data'):
                        v = j.get(k)
                        if isinstance(v, str) and v.startswith('http'):
                            return v
                        if isinstance(v, dict) and 'Url' in v:
                            return v['Url']
            except Exception:
                txt = r.text.strip()
                if txt.startswith('http'):
                    return txt
    except Exception as e:
        print('[debug] GetUrl POST failed:', e)
    return None


def download_file(session, url, filename, headers=None):
    r = session.get(url, headers=headers or {}, stream=True, timeout=60, allow_redirects=True)
    print(f'[debug] download request status={r.status_code} Content-Type={r.headers.get("Content-Type")}')
    try:
        r.raise_for_status()
    except Exception:
        try:
            print('[debug] download response snippet:', r.text[:500])
        except Exception:
            pass
        raise
    with open(filename, 'wb') as fh:
        for chunk in r.iter_content(32768):
            if chunk:
                fh.write(chunk)
    return filename


def sanitize_filename(name):
    if not name:
        return 'download'
    # normalize and strip problematic characters
    name = unicodedata.normalize('NFKC', str(name)).strip()
    # remove path separators
    name = name.replace('/', '_').replace('\\', '_')
    # collapse spaces
    name = ' '.join(name.split())
    # limit length
    if len(name) > 200:
        name = name[:200]
    return name


def interactive_loop(session, reqinfo, fileactions_base, start_item, allow_local_fallback=False, driver=None):
    stack = [start_item]
    parent_stack = []
    current = start_item
    headers_template = reqinfo.get('headers') or {}
    while True:
        data = []
        # before each live call, try to refresh RequestVerificationToken from page
        try:
            if driver is not None:
                try:
                    token = driver.execute_script("var e=document.querySelector('input[name=\"__RequestVerificationToken\"]'); return e?e.value:null;")
                    if token:
                        reqinfo.setdefault('headers', {})['RequestVerificationToken'] = token
                except Exception:
                    pass
        except Exception:
            pass

        try:
            js = call_getitems(session, reqinfo, itemId=current)
            data = js.get('Data') if isinstance(js, dict) else []
        except Exception as e:
            print('[warn] live GetItems failed:', e)
            if allow_local_fallback:
                # attempt to fallback to local captured JSON
                if os.path.exists('getitems_result.json'):
                    try:
                        with open('getitems_result.json', 'r', encoding='utf-8') as f:
                            lj = json.load(f)
                            all_data = lj.get('Data') or []
                            # children are those with ParentFolderID == current
                            data = [d for d in all_data if str(d.get('ParentFolderID')) == str(current)]
                            print('[info] using local getitems_result.json fallback,', len(data), 'entries')
                    except Exception as e2:
                        print('[error] local fallback failed:', e2)
                else:
                    print('[error] no local fallback available (getitems_result.json missing)')
            else:
                print('[error] live-only mode: not using local fallback')
