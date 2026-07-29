#!/usr/bin/env python3
"""Capture the manual's UI screenshots with headless Chromium.

Playwright's own chromium download is blocked on this Mac (Microsoft CDN
returns 400 + the installer hangs), so we drive a Homebrew-installed
Chromium instead -- its build comes from Google's CDN, which works here.
Selenium Manager auto-resolves the matching chromedriver.

Setup (once):
    brew install --cask chromium
    xattr -dr com.apple.quarantine /Applications/Chromium.app

Then, with the app running (frontend :5173, backend :8000):
    webui/backend/.venv/bin/python webui/frontend/scripts/capture_shots.py

Writes docs/figures/shot_{dashboard,optimize,ore,vincoli,orario}.png,
which the manual already embeds via \\grokfig{shot_*}.
"""
from __future__ import annotations

import pathlib
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

BASE = "http://localhost:5173"
CHROMIUM = "/Applications/Chromium.app/Contents/MacOS/Chromium"
OUT = pathlib.Path(__file__).resolve().parents[3] / "docs" / "figures"

# (stem, path, optional button text to click before shooting)
SHOTS = [
    ("shot_dashboard", "/", None),
    ("shot_optimize", "/optimize", None),
    ("shot_ore", "/ore", None),
    ("shot_vincoli", "/constraints", None),
    ("shot_orario", "/schedule", "Per classe"),
]


def _maybe_click(driver, text: str) -> None:
    """Best-effort click of a button/element whose visible text matches."""
    for by, sel in [
        (By.XPATH, f"//button[contains(normalize-space(.), {text!r})]"),
        (By.XPATH, f"//*[@role='button'][contains(normalize-space(.), {text!r})]"),
    ]:
        try:
            els = [e for e in driver.find_elements(by, sel) if e.is_displayed()]
            if els:
                els[0].click()
                return
        except Exception:
            pass


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    opts = Options()
    opts.binary_location = CHROMIUM
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--hide-scrollbars")
    opts.add_argument("--force-device-scale-factor=1")
    opts.add_argument("--window-size=1360,950")
    driver = webdriver.Chrome(options=opts)
    try:
        for stem, path, click_text in SHOTS:
            driver.get(BASE + path)
            time.sleep(3.5)                 # SPA + TanStack queries settle
            if click_text:
                _maybe_click(driver, click_text)
                time.sleep(2.0)
            dest = OUT / f"{stem}.png"
            driver.save_screenshot(str(dest))
            print(f"  captured {dest.name}  ({dest.stat().st_size} B)")
    finally:
        driver.quit()
    print(f"done -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
