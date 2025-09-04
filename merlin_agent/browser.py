from __future__ import annotations
from pathlib import Path
from typing import Optional, Dict
import re
from loguru import logger
import time
import re
from playwright.sync_api import (
    sync_playwright, Page, Browser, BrowserContext, TimeoutError as PWTimeoutError
)
from .utils import ROOT, load_json

class MerlinBrowser:
    def __init__(self, headless: bool = True, debug: bool = False):
        self.headless = headless
        self.debug = debug
        self._pw = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self.selectors: Dict[str, str] = load_json(ROOT / "config" / "selectors.json")

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        self._context = self._browser.new_context(record_video_dir=str(ROOT / "runs" / "video"))
        self._page = self._context.new_page()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._context:
                self._context.close()
        finally:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()

    @property
    def page(self) -> Page:
        assert self._page is not None
        return self._page

    def goto(self, url: str = "https://hackmerlin.io/"):
        logger.info(f"Navigating to {url}")
        self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        # Try clicking a start/play button if present
        try:
            self.page.locator(self.selectors["start_button"]).first.click(timeout=3000)
        except PWTimeoutError:
            pass

    def send_message(self, text: str):
        inp = self.page.locator(self.selectors["chat_input"]).first
        inp.click()
        try:
            inp.fill("")
        except Exception:
            pass
        inp.type(text, delay=10)
        # Click "Ask" or press Enter
        try:
            self.page.locator(self.selectors["send_button"]).first.click(timeout=1500)
        except PWTimeoutError:
            inp.press("Enter")

    def last_assistant_text(self) -> str:
        """
        Read the Merlin reply from the blockquote. If that fails, return
        whole container text as fallback.
        """
        # Wait a moment for UI to render
        container = self.page.locator(self.selectors["messages_container"]).first
        try:
            container.wait_for(state="visible", timeout=5000)
        except PWTimeoutError:
            # fallback: give UI a tiny nudge
            self.page.wait_for_timeout(500)
        try:
            # Prefer the <p> inside the blockquote
            para = self.page.locator(self.selectors["assistant_message"]).last
            return para.inner_text(timeout=3000)
        except PWTimeoutError:
            # fallback: entire blockquote text
            return container.inner_text(timeout=3000)

    def screenshot(self, path: Path):
        self.page.screenshot(path=path, full_page=True)

    def dump_dom(self, path: Path):
        html = self.page.content()
        path.write_text(html, encoding="utf-8")
        print(f"DOM dumped to {path}")
        
    def fill_password_and_submit(self, password: str) -> bool:
        """
        Fill the password into the SECRET PASSWORD field and click Submit.
        Returns True if successful.
        """
        try:
            inp = self.page.locator(self.selectors["password_input"]).first
            inp.fill(password, timeout=2000)
            btn = self.page.locator(self.selectors["submit_button"]).first
            btn.click(timeout=2000)
            return True
        except Exception as e:
            print(f"[WARN] could not submit password: {e}")
            return False

    def get_level(self) -> Optional[int]:
        """
        Robustly read the current 'Level N' from the page.
        We scan multiple heading candidates and return the first that matches /Level \d+/.
        """
        import re
        candidates = [
            "h1", "h2", "h3",
            "h1.mantine-Title-root",
            "[class*='Title-root']",
            "h1:has-text('Level')",
            "[role='heading']"
        ]
        # Try focused, specific candidates first
        tried = set()
        for sel in candidates:
            if sel in tried:
                continue
            tried.add(sel)
            try:
                loc = self.page.locator(sel)
                count = loc.count()
                # iterate all visible matches, newest first (UI may render multiple)
                for i in range(count - 1, -1, -1):
                    try:
                        txt = loc.nth(i).inner_text(timeout=500).strip()
                    except Exception:
                        continue
                    m = re.search(r"\bLevel\s+(\d+)\b", txt, flags=re.I)
                    if m:
                        return int(m.group(1))
            except Exception:
                continue

        # Last resort: read all text and search once (slower but safe)
        try:
            body_txt = self.page.locator("body").inner_text(timeout=800)
            m = re.search(r"\bLevel\s+(\d+)\b", body_txt, flags=re.I)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return None


    def wait_for_level_increment(self, prev_level: int, timeout_ms: int = 6000) -> Optional[int]:
        """
        Poll the heading until it increases beyond prev_level.
        """
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            lv = self.get_level()
            if isinstance(lv, int) and lv > prev_level:
                return lv
            self.page.wait_for_timeout(150)
        return None

    def handle_modal(self) -> str | None:
        """
        If a Mantine modal appears, scrape its body text (hint) and click Continue/X.
        Returns hint text if a modal was seen; None otherwise.
        (This does NOT imply success—success is only heading increment.)
        """
        sel = self.selectors
        try:
            modal = self.page.locator(sel["modal_root"]).first
            modal.wait_for(state="visible", timeout=1500)
        except Exception:
            return None

        hint_text = ""
        try:
            body = self.page.locator(sel["modal_body"]).first
            hint_text = body.inner_text(timeout=800)
        except Exception:
            try:
                hint_text = modal.inner_text(timeout=800)
            except Exception:
                pass

        # try Continue → Enter → Close(X)
        clicked = False
        for click_try in (
            lambda: self.page.get_by_role("button", name="Continue").click(timeout=800),
            lambda: self.page.locator(sel["modal_continue"]).first.click(timeout=800),
            lambda: (modal.focus(), self.page.keyboard.press("Enter")),
            lambda: self.page.locator(sel["modal_close"]).first.click(timeout=800),
        ):
            try:
                click_try()
                clicked = True
                break
            except Exception:
                continue

        # ensure it disappears
        try:
            self.page.locator(sel["modal_root"]).first.wait_for(state="hidden", timeout=1500)
        except Exception:
            pass

        if hint_text:
            print(f"[Modal Hint]\n{hint_text}\n")
        if clicked:
            print("[+] Modal closed.")
        return hint_text or None

    def verify_submission_by_heading(self, prev_level: int, timeout_ms: int = 7000) -> tuple[bool, Optional[int], Optional[str]]:
        """
        Strict success criterion:
        1) (optional) a modal may appear; we close it and capture its text
        2) SUCCESS ONLY IF the level heading increases beyond prev_level

        Returns: (is_success, new_level_or_None, modal_hint_or_None)
        """
        hint = self.handle_modal()  # may be None if no modal appears
        # give the UI a tick to re-render the heading
        self.page.wait_for_timeout(400)
        new_level = self.wait_for_level_increment(prev_level, timeout_ms)
        if new_level and new_level > prev_level:
            return True, new_level, hint
        return False, None, hint



