from __future__ import annotations
from pathlib import Path
from typing import Optional, Dict
import re
from loguru import logger
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

    def get_level(self) -> Optional[int]:
        """
        Extracts 'Level N' from the heading (h1.mantine-Title-root).
        """
        try:
            heading = self.page.locator(self.selectors["level_heading"]).first.inner_text(timeout=2000)
            m = re.search(r"Level\s+(\d+)", heading, flags=re.I)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return None

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

    def handle_modal(self) -> str | None:
        """
        If a Mantine modal appears, grab its body text (hint) and press Continue.
        Returns the modal text if found.
        """
        sel = self.selectors
        try:
            modal = self.page.locator(sel["modal_root"]).first
            # Wait briefly for modal to show up after submit
            modal.wait_for(state="visible", timeout=4000)
        except Exception:
            return None

        # Read hint text
        hint_text = ""
        try:
            body = self.page.locator(sel["modal_body"]).first
            hint_text = body.inner_text(timeout=1500)
        except Exception:
            try:
                hint_text = modal.inner_text(timeout=1500)
            except Exception:
                pass

        # Try role-based click first (most robust with portals/overlays)
        clicked = False
        try:
            self.page.get_by_role("button", name="Continue").click(timeout=1500)
            clicked = True
        except Exception:
            # CSS fallback
            try:
                self.page.locator(sel["modal_continue"]).first.click(timeout=1500)
                clicked = True
            except Exception:
                # Fallback: press Enter while dialog focused
                try:
                    modal.focus()
                    self.page.keyboard.press("Enter")
                    clicked = True
                except Exception:
                    # Last resort: close button (X)
                    try:
                        self.page.locator(sel["modal_close"]).first.click(timeout=1500)
                        clicked = True
                    except Exception:
                        pass

        # Ensure it actually went away
        try:
            self.page.locator(sel["modal_root"]).first.wait_for(state="hidden", timeout=3000)
        except Exception:
            # If still visible, try one more force-click on Continue (overlay can intercept)
            try:
                self.page.get_by_role("button", name="Continue").click(timeout=1000, force=True)
                self.page.locator(sel["modal_root"]).first.wait_for(state="hidden", timeout=2000)
                clicked = True
            except Exception:
                pass

        if hint_text:
            print(f"[Modal Hint]\n{hint_text}\n")
        if clicked:
            print("[+] Modal dismissed (Continue).")
            
        self.page.wait_for_timeout(250)
        return hint_text or None



