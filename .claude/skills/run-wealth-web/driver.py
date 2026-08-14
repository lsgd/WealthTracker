#!/usr/bin/env python3
"""Drive the Wealth Tracker web app: log in through the real UI and screenshot
the dashboard. Exits 0 only if the dashboard actually rendered.

Uses the Python Playwright already installed in the project venv (it is a
backend dependency for the Morgan Stanley integration). If the venv's
Playwright expects a browser build that is not in the local cache, falls back
to the newest cached chromium-headless-shell instead of downloading anything.

Usage (from repo root, venv active):
    python .claude/skills/run-wealth-web/driver.py \
        --url http://localhost:5173 --shot /tmp/wealth-dashboard.png
"""
import argparse
import glob
import os
import re
import sys

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


def launch(p):
    try:
        return p.chromium.launch()
    except PlaywrightError:
        # Browser-build mismatch (e.g. Playwright wants chromium_headless_shell-1234,
        # cache only has -1223). Any recent build drives this app fine.
        candidates = sorted(glob.glob(os.path.expanduser(
            '~/Library/Caches/ms-playwright/'
            'chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell'
        )))
        if not candidates:
            raise
        return p.chromium.launch(executable_path=candidates[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://localhost:5173',
                    help='Frontend base URL (check vite output: falls back to 5174+ if busy)')
    ap.add_argument('--user', default='demo1')
    ap.add_argument('--password', default='demo12345')
    ap.add_argument('--shot', default='/tmp/wealth-dashboard.png')
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.goto(args.url, wait_until='networkidle')
        page.fill('input[type="text"]', args.user)
        page.fill('input[type="password"]', args.password)
        page.click('button[type="submit"]')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(2500)  # charts animate in

        ok = page.get_by_text(re.compile('total wealth', re.I)).count() > 0
        page.screenshot(path=args.shot, full_page=True)
        print('url:', page.url)
        print('screenshot:', args.shot)
        print('dashboard:', 'OK' if ok else 'NOT RENDERED (inspect the screenshot)')
        browser.close()
        sys.exit(0 if ok else 1)


main()
