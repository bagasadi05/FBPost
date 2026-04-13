import sys
import os
import json
import time
import random
import re
import datetime
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout, QHBoxLayout, QVBoxLayout, QFrame,
    QLabel, QTextEdit, QPushButton, QListWidget, QSpinBox, QProgressBar,
    QLineEdit, QComboBox,
    QMessageBox, QFileDialog, QCheckBox, QScrollArea, QSizePolicy
)
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QFont, QPalette, QColor, QCloseEvent

# â”€â”€â”€ Selenium Imports â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# â”€â”€â”€ Constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
APP_DIR = Path(__file__).resolve().parent
COOKIE_FILE = APP_DIR / "cookies.json"
GROUP_FILE  = APP_DIR / "groups.txt"
LOG_FILE = APP_DIR / "app.log"
FAILED_GROUPS_FILE = APP_DIR / "failed_groups.txt"
SCREENSHOT_DIR = APP_DIR / "screenshots"
SETTINGS_FILE = APP_DIR / "ui_settings.json"
REPORTS_DIR = APP_DIR / "reports"
GENERATED_POSTS_FILE = APP_DIR / "generated_posts.json"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
SAFE_SESSION_CAP = 20
SAFE_MIN_DELAY = 25
SAFE_MAX_DELAY = 55
SAFE_BURST_SIZE = 5
SAFE_BURST_PAUSE_MIN = 90
SAFE_BURST_PAUSE_MAX = 180
SUPPORTED_MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mpeg", ".mpg", ".m4v"
}


# â”€â”€â”€ Helper Functions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def human_delay(min_sec=1.8, max_sec=4.5):
    time.sleep(random.uniform(min_sec, max_sec))


def parse_spintax(text):
    """
    Parses {Option1|Option2|Option3} patterns randomly into text.
    """
    pattern = re.compile(r'\{([^{}]*)\}')
    while pattern.search(text):
        for match in pattern.finditer(text):
            options = match.group(1).split('|')
            choice = random.choice(options)
            text = text[:match.start()] + choice + text[match.end():]
            break
    return text

def capture_screenshot_on_error(driver, custom_name="error"):
    try:
        SCREENSHOT_DIR.mkdir(exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        # Remove invalid chars from URL snippet
        safe_name = "".join([c for c in custom_name if c.isalpha() or c.isdigit() or c=='_']) 
        filepath = SCREENSHOT_DIR / f"{safe_name}_{ts}.png"
        driver.save_screenshot(str(filepath))
        return str(filepath)
    except: return None

def sanitize_text(text):
    return ''.join(c for c in text if ord(c) <= 0xFFFF)


def load_cookies(driver):
    if not COOKIE_FILE.exists():
        return False
    try:
        cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8-sig"))
        if not isinstance(cookies, list) or not cookies:
            return False

        added = 0
        for cookie in cookies:
            try:
                if not isinstance(cookie, dict):
                    continue
                name = cookie.get("name")
                value = cookie.get("value")
                if not name or value is None:
                    continue
                driver.add_cookie({
                    "name": name,
                    "value": value,
                    "domain": cookie.get("domain", ".facebook.com"),
                    "path": cookie.get("path", "/")
                })
                added += 1
            except:
                pass
        return added > 0
    except:
        return False


def save_groups(groups):
    GROUP_FILE.write_text("\n".join(groups) + "\n", encoding="utf-8")


def load_groups():
    if not GROUP_FILE.exists():
        return []
    groups = [line.strip() for line in GROUP_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    return normalize_group_urls(groups)


def normalize_group_urls(groups):
    normalized = []
    seen = set()

    for raw_group in groups:
        if not raw_group:
            continue

        clean = raw_group.strip().split("?")[0].rstrip("/")
        if not clean.startswith("http") or "/groups/" not in clean:
            continue
        if clean in seen:
            continue

        seen.add(clean)
        normalized.append(clean)

    return normalized


def is_logged_in(driver):
    try:
        cookie_names = {cookie.get("name") for cookie in driver.get_cookies()}
        if not {"c_user", "xs"}.issubset(cookie_names):
            return False

        current_url = driver.current_url.lower()
        blocked_paths = ("login", "checkpoint", "recover", "two_step_verification")
        return not any(path in current_url for path in blocked_paths)
    except:
        return False


def load_ui_settings():
    if not SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except:
        return {}


def save_ui_settings(data):
    try:
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except:
        pass


def save_generated_posts(posts):
    try:
        GENERATED_POSTS_FILE.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")
    except:
        pass


def load_generated_posts():
    if not GENERATED_POSTS_FILE.exists():
        return []
    try:
        data = json.loads(GENERATED_POSTS_FILE.read_text(encoding="utf-8"))
        return [item.strip() for item in data if isinstance(item, str) and item.strip()]
    except:
        return []


def generate_openrouter_variations(api_key, model, source_text, count):
    api_key = (api_key or os.getenv("OPENROUTER_API_KEY", "")).strip()
    model = (model or DEFAULT_OPENROUTER_MODEL).strip()
    source_text = source_text.strip()
    if not api_key:
        raise ValueError("API key OpenRouter wajib diisi")
    if not source_text:
        raise ValueError("Isi posting wajib diisi sebelum generate variasi")
    if count <= 0:
        raise ValueError("Jumlah variasi harus lebih besar dari 0")

    prompt = (
        f"Buat {count} variasi caption dalam bahasa Indonesia berdasarkan teks berikut.\n\n"
        "Aturan:\n"
        "- Makna inti harus tetap sama\n"
        "- Tiap variasi harus berbeda susunan kalimatnya\n"
        "- Maksimal 2 kalimat per variasi\n"
        "- Gaya natural, santai, tidak kaku\n"
        "- Jangan pakai hashtag\n"
        "- Jangan pakai emoji\n"
        "- Output wajib JSON array of strings, tanpa penjelasan lain\n\n"
        f"Teks sumber:\n{source_text}"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You generate concise Indonesian marketing copy and must return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.9,
    }
    request = urlrequest.Request(
        OPENROUTER_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://local.fbpost.app",
            "X-Title": "FBPost",
        },
        method="POST",
    )

    try:
        with urlrequest.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except urlerror.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code}: {body[:200]}") from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f"Gagal menghubungi OpenRouter: {exc.reason}") from exc

    try:
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError("Respons OpenRouter tidak sesuai format yang diharapkan") from exc

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", content)
        if not match:
            raise RuntimeError("Model tidak mengembalikan JSON array yang valid")
        parsed = json.loads(match.group(0))

    posts = [item.strip() for item in parsed if isinstance(item, str) and item.strip()]
    deduped = []
    seen = set()
    for post in posts:
        if post in seen:
            continue
        seen.add(post)
        deduped.append(post)

    if not deduped:
        raise RuntimeError("Tidak ada variasi valid yang dihasilkan model")
    return deduped


def build_ai_caption_plan(api_key, model, source_text, target_count, existing_posts=None, max_rounds=6):
    if target_count <= 0:
        return []

    planned = []
    seen = set()
    for post in existing_posts or []:
        cleaned = post.strip() if isinstance(post, str) else ""
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            planned.append(cleaned)
        if len(planned) >= target_count:
            return planned[:target_count]

    rounds = 0
    while len(planned) < target_count and rounds < max_rounds:
        rounds += 1
        remaining = target_count - len(planned)
        batch_target = min(max(remaining, 10), 100)
        prompt_text = source_text
        if planned:
            recent_samples = "\n".join(f"- {item}" for item in planned[-8:])
            prompt_text = (
                f"{source_text}\n\n"
                "Hindari mengulang variasi yang mirip dengan daftar berikut:\n"
                f"{recent_samples}"
            )

        batch = generate_openrouter_variations(api_key, model, prompt_text, batch_target)
        added = 0
        for post in batch:
            if post in seen:
                continue
            seen.add(post)
            planned.append(post)
            added += 1
            if len(planned) >= target_count:
                return planned[:target_count]

        if added == 0:
            break

    if len(planned) < target_count:
        raise RuntimeError(
            f"Caption AI hanya tersedia {len(planned)} dari {target_count} grup target. Coba generate ulang atau kurangi jumlah grup."
        )
    return planned[:target_count]


def build_caption_preview(groups, captions, limit=3):
    preview_lines = []
    total = min(len(groups), len(captions), limit)
    for index in range(total):
        group_name = groups[index].rstrip("/").split("/")[-1] or groups[index]
        caption = captions[index].replace("\n", " ").strip()
        if len(caption) > 85:
            caption = caption[:85] + "..."
        preview_lines.append(f"{index + 1}. {group_name} -> {caption}")
    return "\n".join(preview_lines)


def write_run_report(mode, result_count, processed_total=0, failed_urls=None, groups=None, group_results=None):
    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{mode}_{timestamp}"
    json_path = REPORTS_DIR / f"{base_name}.json"
    txt_path = REPORTS_DIR / f"{base_name}.txt"

    failed_urls = failed_urls or []
    groups = groups or []
    group_results = group_results or []
    payload = {
        "mode": mode,
        "timestamp": timestamp,
        "processed_total": processed_total,
        "result_count": result_count,
        "failed_count": len(failed_urls),
        "failed_urls": failed_urls,
        "groups": groups,
        "group_results": group_results,
    }

    summary_lines = [
        f"Mode: {mode}",
        f"Timestamp: {timestamp}",
        f"Processed total: {processed_total}",
        f"Result count: {result_count}",
        f"Failed count: {len(failed_urls)}",
    ]
    if group_results:
        summary_lines.append("")
        summary_lines.append("Group Results:")
        for item in group_results:
            status = item.get("status", "unknown")
            url = item.get("url", "-")
            reason = item.get("reason", "")
            line = f"[{status.upper()}] {url}"
            if reason:
                line += f" | {reason}"
            summary_lines.append(line)
    if failed_urls:
        summary_lines.append("")
        summary_lines.append("Failed URLs:")
        summary_lines.extend(failed_urls)

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    txt_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return str(txt_path)


def normalize_media_paths(paths):
    normalized = []
    seen = set()

    for raw_path in paths:
        if not raw_path:
            continue

        path = Path(raw_path).expanduser().resolve()
        suffix = path.suffix.lower()

        if not path.is_file() or suffix not in SUPPORTED_MEDIA_EXTENSIONS:
            continue

        path_str = str(path)
        if path_str in seen:
            continue

        seen.add(path_str)
        normalized.append(path_str)

    return normalized


# â”€â”€â”€ Posting Logic â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def wait_post_dialog(driver, timeout=10):
    dialog_xpath = (
        "//div[@role='dialog' and .//div[@role='textbox' and @contenteditable='true']]"
    )
    try:
        return WebDriverWait(driver, timeout).until(
            EC.visibility_of_element_located((By.XPATH, dialog_xpath))
        )
    except:
        return None


def open_group_composer(driver):
    try:
        human_delay(1.5, 3)

        try:
            discussion_tabs = driver.find_elements(By.XPATH, "//div[@role='tablist']//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'discussion') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'diskusi')] | //div[@role='navigation']//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'discussion') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'diskusi')]")
            for tab in discussion_tabs:
                if tab.is_displayed():
                    driver.execute_script("arguments[0].click();", tab)
                    human_delay(2, 4)
                    break
        except:
            pass

        keywords = [
            "tulis sesuatu", "write something", "buat postingan", "buat pos",
            "create post", "create public post", "kirim postingan",
            "what's on your mind", "jual sesuatu", "sell something"
        ]
        lowered = "translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"
        keyword_text_xpath = " or ".join([f"contains({lowered}, '{kw}')" for kw in keywords])
        keyword_aria_xpath = " or ".join([
            "contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
            f"'{kw}')"
            for kw in keywords
        ])
        trigger_xpath = " | ".join([
            (
                "//div[@role='button'"
                " and not(ancestor::div[@role='dialog'])"
                " and not(ancestor::div[@role='article'])"
                f" and ({keyword_text_xpath})]"
            ),
            (
                "//div[@role='button'"
                " and not(ancestor::div[@role='dialog'])"
                " and not(ancestor::div[@role='article'])"
                f" and ({keyword_aria_xpath})]"
            )
        ])

        triggers = driver.find_elements(By.XPATH, trigger_xpath)
        for trigger in triggers:
                try:
                    if not trigger.is_displayed():
                        continue
                    driver.execute_script("arguments[0].click();", trigger)
                    dialog = wait_post_dialog(driver, timeout=6)
                    if dialog is not None:
                        return dialog
                except:
                    continue

        return None
    except Exception as e:
        print("open_group_composer error:", e)
        return None


def wait_group_editor(driver, container=None, timeout=20):
    search_root = container or driver
    try:
        return WebDriverWait(driver, timeout).until(
            lambda d: next(iter([
                el for el in search_root.find_elements(
                    By.XPATH,
                    ".//div[@role='textbox' and @contenteditable='true' and @data-lexical-editor='true']"
                    " | .//div[@role='textbox' and @contenteditable='true']"
                )
                if el.is_displayed()
            ]), None)
        )
    except:
        return None


def open_media_picker(driver, container):
    triggers = container.find_elements(By.XPATH,
        ".//div[@role='button'][contains(., 'Foto/video') or contains(., 'Photo/video') or contains(., 'Photos/videos') or contains(., 'Foto') or contains(@aria-label, 'Foto/video') or contains(@aria-label, 'Photo/video')] | "
        ".//span[contains(., 'Foto/video') or contains(., 'Photo/video') or contains(., 'Photos/videos')]"
    )
    for trigger in triggers:
        try:
            driver.execute_script("arguments[0].click();", trigger)
            return True
        except:
            continue
    return False


def wait_media_input(driver, container=None, timeout=20):
    search_root = container or driver
    try:
        return WebDriverWait(driver, timeout).until(
            lambda d: next(iter(search_root.find_elements(
                By.XPATH,
                ".//input[@type='file' and (contains(@accept, 'image') or contains(@accept, 'video') or not(@accept))]"
            )), None)
        )
    except:
        return None


def upload_media_files(driver, media_paths, container=None, timeout=45):
    if not media_paths:
        return True, None

    media_input = wait_media_input(driver, container=container, timeout=4)
    if not media_input and not container:
        return False, "Composer post tidak valid untuk upload media"
    if not media_input and not open_media_picker(driver, container):
        return False, "Tombol upload media tidak ditemukan"

    if not media_input:
        media_input = wait_media_input(driver, container=container, timeout=timeout)
    if not media_input:
        return False, "Input file upload tidak muncul"

    try:
        media_input.send_keys("\n".join(media_paths))
    except Exception as exc:
        return False, f"Gagal memilih file: {str(exc)[:120]}"

    # Wait for the files to process (avoiding strict DOM check on file input element)
    time.sleep((len(media_paths) * 2) + 2)
    return True, None


def input_text_strict(driver, element, text):
    clean = sanitize_text(text)
    try:
        WebDriverWait(driver, 8).until(lambda d: element.is_displayed())
        driver.execute_script("""
            arguments[0].scrollIntoView({block: 'center'});
            arguments[0].focus();
        """, element)
        human_delay(0.5, 1.2)

        try:
            ActionChains(driver).move_to_element(element).click().send_keys(clean).perform()
            human_delay(0.8, 1.5)
        except Exception:
            # If ActionChains fails (e.g. element not interactable), fallback to click and send
            element.click()
            element.send_keys(clean)
            human_delay(0.8, 1.5)

        current_text = driver.execute_script(
            "return (arguments[0].innerText || arguments[0].textContent || '').trim();",
            element
        )

        if not current_text:
            driver.execute_script("""
                const dataTransfer = new DataTransfer();
                dataTransfer.setData('text/plain', arguments[1]);
                const event = new ClipboardEvent('paste', {
                    clipboardData: dataTransfer,
                    bubbles: true,
                    cancelable: true
                });
                arguments[0].dispatchEvent(event);
            """, element, clean)
            
            human_delay(0.5, 1.0)

            current_text = driver.execute_script(
                "return (arguments[0].innerText || arguments[0].textContent || '').trim();",
                element
            )
            if not current_text:
                driver.execute_script("""
                    const target = arguments[0];
                    const value = arguments[1];
                    target.focus();
                    target.innerHTML = '';
                    const selection = window.getSelection();
                    const range = document.createRange();
                    range.selectNodeContents(target);
                    range.collapse(false);
                    selection.removeAllRanges();
                    selection.addRange(range);
                    document.execCommand('insertText', false, value);
                    target.dispatchEvent(new InputEvent('beforeinput', {bubbles: true, inputType: 'insertText', data: value}));
                    target.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
                """, element, clean)

        final_text = driver.execute_script(
            "return (arguments[0].innerText || arguments[0].textContent || '').trim();",
            element
        )
        return bool(final_text)
    except Exception as e:
        print("input error:", e)
        return False


def wait_post_button(driver, container=None, timeout=20):
    search_root = container or driver
    try:
        return WebDriverWait(driver, timeout).until(
            lambda d: next(iter([
                btn for btn in search_root.find_elements(
                    By.XPATH,
                    ".//div[@role='button' and (contains(@aria-label, 'Post') or contains(@aria-label, 'Posting') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'post'))]"
                )
                if btn.is_displayed() and btn.is_enabled()
            ]), None)
        )
    except:
        return None

def check_pending_post(driver):
    """
    Checks if a post goes to 'Pending Admin Approval' or similar status.
    """
    try:
        time.sleep(2)
        pending_msg = driver.find_elements(By.XPATH, "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'persetujuan admin') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'pending approval')]")
        if pending_msg:
            return True
        return False
    except:
        return False

# â”€â”€â”€ Bot Worker Thread â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class BotWorker(QThread):
    log           = Signal(str, str)     # msg, category
    progress      = Signal(int)
    status        = Signal(str)
    completed     = Signal(str, int, int)     # mode, result count, processed total
    groups_ready  = Signal(list)
    report_ready  = Signal(str)

    def __init__(
        self,
        mode,
        text="",
        delay_min=8,
        delay_max=18,
        max_groups=None,
        groups=None,
        media_paths=None,
        content_variants=None,
        headless=True,
        stop_on_pending=False,
        burst_pause_every=0,
        burst_pause_min=0,
        burst_pause_max=0,
    ):
        super().__init__()
        self.mode       = mode
        self.text       = text
        self.delay_min  = delay_min
        self.delay_max  = delay_max
        self.max_groups = max_groups
        self.groups     = groups or []
        self.media_paths = media_paths or []
        self.content_variants = content_variants or []
        self.headless   = headless
        self.stop_on_pending = stop_on_pending
        self.burst_pause_every = burst_pause_every
        self.burst_pause_min = burst_pause_min
        self.burst_pause_max = burst_pause_max
        self._stop_flag = False

    def request_stop(self):
        self._stop_flag = True

    def sleep_with_stop(self, seconds, step=0.25):
        elapsed = 0.0
        while elapsed < seconds:
            if self._stop_flag:
                return False
            chunk = min(step, seconds - elapsed)
            time.sleep(chunk)
            elapsed += chunk
        return True

    def emit_log(self, message, category="info", log_to_file=True):
        self.log.emit(message, category)
        if log_to_file:
            try:
                import datetime
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with LOG_FILE.open("a", encoding="utf-8") as f:
                    f.write(f"[{ts}] [{category.upper()}] {message}\n")
            except:
                pass

    def run(self):
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-notifications")
        options.add_argument("--window-size=1280,900")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        driver = None
        result_count = 0
        processed_total = 0
        failed_urls = []
        group_results = []
        report_path = ""

        try:
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            driver.get("https://www.facebook.com/")
            human_delay(4, 7.5)

            if not load_cookies(driver):
                self.emit_log("cookies.json tidak ditemukan atau rusak", "error")
                return

            driver.refresh()
            human_delay(5, 9)
            if not is_logged_in(driver):
                self.emit_log("Cookie termuat, tetapi sesi Facebook tidak valid atau sudah expired", "error")
                return

            self.emit_log("Login berhasil via cookies", "success")

            if self.mode == "test_cookie":
                result_count = 1
                self.status.emit("Cookie valid")
                return

            if self.mode == "fetch":
                groups = self._fetch_groups(driver)
                save_groups(groups)
                self.groups_ready.emit(groups)
                result_count = len(groups)
                group_results = [{"url": group, "status": "fetched"} for group in groups]
                report_path = write_run_report(
                    "fetch",
                    result_count,
                    processed_total=result_count,
                    groups=groups,
                    group_results=group_results,
                )
                return

            # â”€â”€ Posting mode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ 
            total = len(self.groups)
            if total == 0:
                self.emit_log("Tidak ada grup untuk diproses", "error")
                return

            self.status.emit(f"Memproses {total} grup...")

            for i, url in enumerate(self.groups, 1):
                if self._stop_flag:
                    self.emit_log("Proses dihentikan oleh pengguna", "warning") 
                    group_results.append({"url": url, "status": "stopped", "reason": "Dihentikan pengguna"})
                    break

                short_url = url.split("/")[-1] or url
                current_result = {"url": url, "status": "failed", "reason": ""}
                self.emit_log(f"[{i}/{total}] â†’ {short_url}", "info")
                processed_total = i

                try:
                    driver.get(url)
                    human_delay(5.5, 9.5)

                    composer_dialog = open_group_composer(driver)
                    if not composer_dialog:
                        self.emit_log("   Gagal membuka composer", "error")
                        capture_screenshot_on_error(driver, f"err_composer_{short_url}")
                        failed_urls.append(url)
                        current_result["reason"] = "Gagal membuka composer"
                        group_results.append(current_result)
                        continue

                    editor = wait_group_editor(driver, container=composer_dialog, timeout=12)
                    text_to_post = ""
                    if self.content_variants and i <= len(self.content_variants):
                        text_to_post = self.content_variants[i - 1]
                    elif self.text:
                        text_to_post = parse_spintax(self.text)
                    if text_to_post:
                        current_result["text"] = text_to_post

                    if text_to_post:
                        if not editor:
                            self.emit_log("   Editor tidak ditemukan", "error") 
                            capture_screenshot_on_error(driver, f"err_editor_{short_url}")
                            failed_urls.append(url)
                            current_result["reason"] = "Editor tidak ditemukan"
                            group_results.append(current_result)
                            continue

                        if not input_text_strict(driver, editor, text_to_post):    
                            self.emit_log("   Gagal memasukkan teks", "error")  
                            capture_screenshot_on_error(driver, f"err_text_{short_url}")
                            failed_urls.append(url)
                            current_result["reason"] = "Gagal memasukkan teks"
                            group_results.append(current_result)
                            continue

                    if self.media_paths:
                        self.emit_log(f"   Mengunggah {len(self.media_paths)} media...", "info")
                        uploaded, reason = upload_media_files(driver, self.media_paths, container=composer_dialog)
                        if not uploaded:
                            self.emit_log(f"   Upload media gagal: {reason}", "error")
                            capture_screenshot_on_error(driver, f"err_media_{short_url}")
                            failed_urls.append(url)
                            current_result["reason"] = f"Upload media gagal: {reason}"
                            group_results.append(current_result)
                            continue

                        # Beri waktu Facebook memproses preview, khususnya untuk video.
                        if any(Path(path).suffix.lower() in {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.mpeg', '.mpg', '.m4v'} for path in self.media_paths):   
                            human_delay(12, 18)
                        else:
                            human_delay(4, 7)

                    # Tutup overlay "Tambahkan ke postingan Anda" jika terbuka (muncul sebagai portal DOM terpisah)
                    try:
                        overlay_open = False
                        titles = driver.find_elements(By.XPATH, "//div[@role='dialog']//*[not(*) and (contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'tambahkan ke postingan') or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'add to your post'))]")
                        for t in titles:
                            if t.is_displayed():
                                overlay_open = True
                                dialog_node = t.find_element(By.XPATH, "./ancestor::div[@role='dialog'][1]")
                                # Tombol "back" (panah kiri) hampir dipastikan adalah elemen role=button pertama di struktur modal ini
                                all_btn = dialog_node.find_elements(By.XPATH, ".//div[@role='button']")
                                if all_btn:
                                    driver.execute_script("arguments[0].click();", all_btn[0])
                                    import time
                                    time.sleep(1.5)
                                break
                    except Exception:
                        pass

                    btn = wait_post_button(driver, container=composer_dialog)
                    if not btn:
                        self.emit_log("   Tombol Post tidak muncul/aktif", "error")
                        capture_screenshot_on_error(driver, f"err_btn_post_{short_url}")
                        failed_urls.append(url)
                        current_result["reason"] = "Tombol Post tidak muncul/aktif"
                        group_results.append(current_result)
                        continue

                    driver.execute_script("arguments[0].click();", btn)
                    
                    dialog_closed = False
                    for _ in range(15):
                        try:
                            if not composer_dialog.is_displayed():
                                dialog_closed = True
                                break
                        except Exception:
                            dialog_closed = True
                            break
                        import time
                        time.sleep(2)
                        
                    if not dialog_closed:
                        self.emit_log("   Tombol post diklik tapi form tidak tertutup (kemungkinan terblokir/error)", "error")
                        capture_screenshot_on_error(driver, f"err_dialog_stuck_{short_url}")
                        failed_urls.append(url)
                        current_result["reason"] = "Form posting tidak tertutup"
                        group_results.append(current_result)
                        continue
                        
                    human_delay(2, 4)

                    if check_pending_post(driver):
                        self.emit_log("   [PENDING] Postingan menunggu persetujuan Admin", "warning")
                        current_result["status"] = "pending"
                        current_result["reason"] = "Menunggu persetujuan admin"
                        if self.stop_on_pending:
                            group_results.append(current_result)
                            self.emit_log("Safety mode aktif: proses dihentikan karena post masuk pending admin", "warning")
                            break
                    else:
                        self.emit_log("   Berhasil diposting âœ“", "success")
                        current_result["status"] = "success"
                        result_count += 1
                    group_results.append(current_result)

                except Exception as e:
                    self.emit_log(f"   Error: {str(e)[:140]}...", "error")      
                    capture_screenshot_on_error(driver, f"err_exception_{short_url}")
                    failed_urls.append(url)
                    current_result["reason"] = str(e)[:140]
                    group_results.append(current_result)

                prog = int((i / total) * 100)
                self.progress.emit(prog)

                delay = random.uniform(self.delay_min, self.delay_max)
                self.status.emit(f"Menunggu {delay:.1f} detik...")
                if not self.sleep_with_stop(delay):
                    self.emit_log("Proses dihentikan saat masa jeda", "warning")
                    break

                if self.burst_pause_every > 0 and i < total and i % self.burst_pause_every == 0:
                    cooloff = random.uniform(self.burst_pause_min, self.burst_pause_max)
                    self.emit_log(
                        f"Safety cooloff aktif setelah {i} grup. Jeda tambahan {cooloff:.1f} detik",
                        "warning"
                    )
                    self.status.emit(f"Safety cooloff {cooloff:.1f} detik...")
                    if not self.sleep_with_stop(cooloff):
                        self.emit_log("Proses dihentikan saat safety cooloff", "warning")
                        break

            # Write failed groups fallback sum at the end
            if failed_urls:
                try:
                    with FAILED_GROUPS_FILE.open("w", encoding="utf-8") as f:
                        f.write("\n".join(failed_urls))
                    self.emit_log(f"Menyimpan {len(failed_urls)} grup yang gagal ke {FAILED_GROUPS_FILE.name}", "info")
                except: pass

            report_path = write_run_report(
                "post",
                result_count,
                processed_total=total,
                failed_urls=failed_urls,
                groups=self.groups,
                group_results=group_results,
            )

        except Exception as e:
            self.emit_log(f"Critical error: {str(e)}", "error")
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            if report_path:
                self.report_ready.emit(report_path)
            if self.mode == "fetch":
                processed_total = result_count
            elif self.mode == "test_cookie":
                processed_total = result_count
            elif processed_total == 0 and self.groups:
                processed_total = len(group_results) or len(self.groups)
            self.completed.emit(self.mode, result_count, processed_total)

    def _fetch_groups(self, driver):
        driver.get("https://www.facebook.com/groups/joins/")
        human_delay(6, 10)

        groups = set()
        last_count = 0

        while self.max_groups is None or len(groups) < self.max_groups:
            if self._stop_flag:
                break

            try:
                links = driver.find_elements(By.XPATH, "//a[contains(@href, '/groups/')]")

                for link in links:
                    href = link.get_attribute("href")
                    if not href:
                        continue

                    clean = href.split("?")[0].rstrip("/")

                    if (
                        "/groups/" in clean
                        and clean.count("/") >= 4
                        and not clean.endswith(("/feed", "/discover", "/joins", "/groups", "/members", "/about", "/pending"))
                        and clean.split("/groups/")[-1].strip()
                    ):
                        groups.add(clean)

                count_now = len(groups)
                self.emit_log(f"â†» Ditemukan {count_now} grup unik...", "info")  

                if count_now == last_count:
                    self.emit_log("Tidak ada grup baru setelah scroll â†’ selesai", "info")
                    break

                last_count = count_now

                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                human_delay(4, 8)

            except Exception as e:
                self.emit_log(f"Error saat fetch: {str(e)[:120]}", "warning")   

        group_list = sorted(groups)
        if self.max_groups is None:
            return group_list
        return group_list[:self.max_groups]


# â”€â”€â”€ Main Window â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class FacebookPosterUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Auto Post Group Beta Version           IG : @ncots_id           Tele : @jlimboo")
        self.resize(1020, 800)
        self.setMinimumSize(880, 660)

        self.worker = None
        self.media_paths = []
        self.generated_posts = load_generated_posts()
        self._settings = load_ui_settings()
        self._smart_pipeline_active = False
        self._smart_pipeline_requires_fetch = False
        self._silent_cookie_test = False
        self._init_ui_modern()
        self._apply_dark_theme()
        self._restore_ui_settings()
        self._run_startup_automation()

    def _unused_legacy_init_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        grid = QGridLayout(central)
        grid.setContentsMargins(28, 24, 28, 24)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)

        # Title
        title = QLabel("Facebook Group Publisher")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Segoe UI Variable", 20, QFont.Bold))
        grid.addWidget(title, 0, 0, 1, 3)

        subtitle = QLabel("Kelola daftar grup, atur limit posting, dan pantau proses dari satu dashboard.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setFont(QFont("Segoe UI Variable", 10))
        grid.addWidget(subtitle, 1, 0, 1, 3)

        self.chk_headless = QCheckBox("Mode Tersembunyi (Headless)")
        self.chk_headless.setChecked(True)
        self.chk_headless.setFont(QFont("Segoe UI Variable", 10))
        grid.addWidget(self.chk_headless, 0, 3, 2, 2, alignment=Qt.AlignRight | Qt.AlignVCenter)

        # Text area
        lbl_text = QLabel("Isi Posting")
        lbl_text.setObjectName("sectionLabel")
        lbl_text.setFont(QFont("Segoe UI Variable", 11))
        grid.addWidget(lbl_text, 2, 0, alignment=Qt.AlignRight | Qt.AlignTop)

        self.post_edit = QTextEdit()
        self.post_edit.setPlaceholderText("Tulis konten yang ingin disebar ke semua grup...")
        self.post_edit.setMinimumHeight(140)
        self.post_edit.setFont(QFont("Segoe UI Variable", 11))
        self.post_edit.setObjectName("editor")
        grid.addWidget(self.post_edit, 2, 1, 1, 4)

        # Media
        lbl_media = QLabel("Media")
        lbl_media.setObjectName("sectionLabel")
        lbl_media.setFont(QFont("Segoe UI Variable", 11))
        grid.addWidget(lbl_media, 3, 0, alignment=Qt.AlignRight | Qt.AlignTop)

        media_box = QHBoxLayout()
        media_box.setSpacing(10)
        self.lbl_media_summary = QLabel("Belum ada foto / video dipilih")
        self.lbl_media_summary.setObjectName("helperText")
        self.lbl_media_summary.setWordWrap(True)
        self.lbl_media_summary.setMinimumHeight(38)
        media_box.addWidget(self.lbl_media_summary, 1)

        self.btn_pick_media = QPushButton("Pilih Foto / Video")
        self.btn_pick_media.setFixedHeight(42)
        self.btn_pick_media.clicked.connect(self._pick_media_files)
        media_box.addWidget(self.btn_pick_media)

        self.btn_clear_media = QPushButton("Hapus Media")
        self.btn_clear_media.setFixedHeight(42)
        self.btn_clear_media.clicked.connect(self._clear_media_files)
        media_box.addWidget(self.btn_clear_media)

        grid.addLayout(media_box, 3, 1, 1, 4)

        # Delay
        lbl_delay = QLabel("Delay")
        lbl_delay.setObjectName("sectionLabel")
        lbl_delay.setFont(QFont("Segoe UI Variable", 11))
        grid.addWidget(lbl_delay, 4, 0, alignment=Qt.AlignRight)

        delay_box = QHBoxLayout()
        delay_box.setSpacing(10)
        self.spin_min = QSpinBox()
        self.spin_min.setRange(4, 120)
        self.spin_min.setValue(8)
        self.spin_min.setSuffix(" s")
        self.spin_min.setFixedWidth(95)
        delay_box.addWidget(self.spin_min)

        delay_box.addWidget(QLabel(" â€“ "))

        self.spin_max = QSpinBox()
        self.spin_max.setRange(6, 300)
        self.spin_max.setValue(18)
        self.spin_max.setSuffix(" s")
        self.spin_max.setFixedWidth(95)
        delay_box.addWidget(self.spin_max)

        delay_box.addStretch()
        grid.addLayout(delay_box, 4, 1, 1, 4)

        # Post limit
        lbl_post_limit = QLabel("Maks. Post")
        lbl_post_limit.setObjectName("sectionLabel")
        lbl_post_limit.setFont(QFont("Segoe UI Variable", 11))
        grid.addWidget(lbl_post_limit, 5, 0, alignment=Qt.AlignRight)

        post_limit_box = QHBoxLayout()
        post_limit_box.setSpacing(10)
        self.spin_post_limit = QSpinBox()
        self.spin_post_limit.setRange(0, 100000)
        self.spin_post_limit.setValue(0)
        self.spin_post_limit.setSpecialValueText("Semua grup")
        self.spin_post_limit.setFixedWidth(140)
        self.spin_post_limit.valueChanged.connect(lambda _: self._update_group_summary(self.group_list.count()))
        post_limit_box.addWidget(self.spin_post_limit)
        helper = QLabel("0 = semua grup yang ada di daftar")
        helper.setObjectName("helperText")
        post_limit_box.addWidget(helper)
        post_limit_box.addStretch()
        grid.addLayout(post_limit_box, 5, 1, 1, 4)

        # Buttons row 1
        btn_row1 = QHBoxLayout()
        btn_row1.setSpacing(10)
        self.btn_fetch = QPushButton("Ambil Daftar Grup")
        self.btn_fetch.setFixedHeight(48)
        self.btn_fetch.clicked.connect(self._start_fetch_groups)
        btn_row1.addWidget(self.btn_fetch)

        self.btn_load = QPushButton("Load groups.txt")
        self.btn_load.setFixedHeight(48)
        self.btn_load.clicked.connect(self._load_groups_file)
        btn_row1.addWidget(self.btn_load)

        grid.addLayout(btn_row1, 6, 0, 1, 5)

        # Group list
        lbl_groups = QLabel("Daftar Grup")
        lbl_groups.setObjectName("sectionLabel")
        lbl_groups.setFont(QFont("Segoe UI Variable", 11))
        grid.addWidget(lbl_groups, 7, 0, alignment=Qt.AlignRight | Qt.AlignTop)

        self.lbl_group_summary = QLabel("Belum ada grup dimuat")
        self.lbl_group_summary.setObjectName("helperText")
        self.lbl_group_summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.lbl_group_summary, 7, 4, alignment=Qt.AlignRight | Qt.AlignVCenter)

        self.group_list = QListWidget()
        self.group_list.setAlternatingRowColors(True)
        self.group_list.setFont(QFont("Segoe UI Variable", 10))
        self.group_list.setStyleSheet("QListWidget::item { padding: 7px 10px; }")
        self.group_list.setObjectName("groupList")
        grid.addWidget(self.group_list, 7, 1, 1, 3)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFixedHeight(24)
        grid.addWidget(self.progress, 8, 0, 1, 5)

        self.lbl_status = QLabel("Ready")
        self.lbl_status.setObjectName("statusLabel")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setFont(QFont("Segoe UI Variable", 10))
        grid.addWidget(self.lbl_status, 9, 0, 1, 5)

        # Post + Stop
        post_row = QHBoxLayout()
        post_row.setSpacing(10)
        self.btn_post = QPushButton("POST MASSAL ðŸš€")
        self.btn_post.setFixedHeight(56)
        self.btn_post.setFont(QFont("Segoe UI Variable", 13, QFont.Bold))
        self.btn_post.clicked.connect(self._start_posting)
        post_row.addWidget(self.btn_post)

        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setFixedHeight(56)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_worker)
        post_row.addWidget(self.btn_stop)

        grid.addLayout(post_row, 10, 0, 1, 5)

        # Log
        lbl_log = QLabel("Log")
        lbl_log.setObjectName("sectionLabel")
        lbl_log.setFont(QFont("Segoe UI Variable", 11))
        grid.addWidget(lbl_log, 11, 0, alignment=Qt.AlignRight | Qt.AlignTop)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(190)
        self.log_view.setFont(QFont("Consolas", 10))
        self.log_view.setObjectName("logView")
        grid.addWidget(self.log_view, 11, 1, 1, 4)

        grid.setColumnStretch(1, 1)
        grid.setRowStretch(11, 1)

    def _init_ui_modern(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        root = QGridLayout(central)
        root.setContentsMargins(28, 24, 28, 24)
        root.setHorizontalSpacing(18)
        root.setVerticalSpacing(16)

        title = QLabel("Facebook Group Publisher")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Segoe UI Variable", 20, QFont.Bold))
        root.addWidget(title, 0, 0, 1, 2)

        subtitle = QLabel("Kelola daftar grup, atur limit posting, dan pantau proses dari satu dashboard.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setFont(QFont("Segoe UI Variable", 10))
        root.addWidget(subtitle, 1, 0, 1, 2)

        self.chk_headless = QCheckBox("Mode Tersembunyi (Headless)")
        self.chk_headless.setChecked(True)
        self.chk_headless.setFont(QFont("Segoe UI Variable", 10))
        root.addWidget(self.chk_headless, 0, 1, 2, 1, alignment=Qt.AlignRight | Qt.AlignVCenter)

        left_scroll = QScrollArea()
        left_scroll.setObjectName("leftScroll")
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        left_panel = QFrame()
        left_panel.setObjectName("panel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(14)
        left_scroll.setWidget(left_panel)

        right_panel = QFrame()
        right_panel.setObjectName("panel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(14)

        root.addWidget(left_scroll, 2, 0)
        root.addWidget(right_panel, 2, 1)
        root.setColumnStretch(0, 6)
        root.setColumnStretch(1, 5)
        root.setRowStretch(2, 1)

        lbl_text = QLabel("Isi Posting")
        lbl_text.setObjectName("sectionLabel")
        lbl_text.setFont(QFont("Segoe UI Variable", 11))
        left_layout.addWidget(lbl_text)

        self.post_edit = QTextEdit()
        self.post_edit.setPlaceholderText("Tulis konten yang ingin disebar ke semua grup...")
        self.post_edit.setMinimumHeight(190)
        self.post_edit.setFont(QFont("Segoe UI Variable", 11))
        self.post_edit.setObjectName("editor")
        left_layout.addWidget(self.post_edit)

        lbl_media = QLabel("Media")
        lbl_media.setObjectName("sectionLabel")
        lbl_media.setFont(QFont("Segoe UI Variable", 11))
        left_layout.addWidget(lbl_media)

        media_box = QHBoxLayout()
        media_box.setSpacing(10)
        self.lbl_media_summary = QLabel("Belum ada foto / video dipilih")
        self.lbl_media_summary.setObjectName("helperText")
        self.lbl_media_summary.setWordWrap(True)
        self.lbl_media_summary.setMinimumHeight(38)
        media_box.addWidget(self.lbl_media_summary, 1)

        self.btn_pick_media = QPushButton("Pilih Foto / Video")
        self.btn_pick_media.setFixedHeight(42)
        self.btn_pick_media.clicked.connect(self._pick_media_files)
        media_box.addWidget(self.btn_pick_media)

        self.btn_clear_media = QPushButton("Hapus Media")
        self.btn_clear_media.setFixedHeight(42)
        self.btn_clear_media.clicked.connect(self._clear_media_files)
        media_box.addWidget(self.btn_clear_media)
        left_layout.addLayout(media_box)

        settings_frame = QFrame()
        settings_frame.setObjectName("subPanel")
        settings_layout = QVBoxLayout(settings_frame)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setSpacing(12)

        settings_title = QLabel("Pengaturan Posting")
        settings_title.setObjectName("sectionLabel")
        settings_title.setFont(QFont("Segoe UI Variable", 11))
        settings_layout.addWidget(settings_title)

        delay_label = QLabel("Delay Antar Grup")
        delay_label.setObjectName("helperText")
        settings_layout.addWidget(delay_label)

        delay_box = QHBoxLayout()
        delay_box.setSpacing(10)
        self.spin_min = QSpinBox()
        self.spin_min.setRange(4, 120)
        self.spin_min.setValue(8)
        self.spin_min.setSuffix(" s")
        self.spin_min.setFixedWidth(110)
        delay_box.addWidget(self.spin_min)

        delay_sep = QLabel("sampai")
        delay_sep.setObjectName("helperText")
        delay_box.addWidget(delay_sep)

        self.spin_max = QSpinBox()
        self.spin_max.setRange(6, 300)
        self.spin_max.setValue(18)
        self.spin_max.setSuffix(" s")
        self.spin_max.setFixedWidth(110)
        delay_box.addWidget(self.spin_max)
        delay_box.addStretch()
        settings_layout.addLayout(delay_box)

        limit_label = QLabel("Maksimal Grup untuk Dipost")
        limit_label.setObjectName("helperText")
        settings_layout.addWidget(limit_label)

        self.spin_post_limit = QSpinBox()
        self.spin_post_limit.setRange(0, 100000)
        self.spin_post_limit.setValue(0)
        self.spin_post_limit.setSpecialValueText("Semua grup")
        self.spin_post_limit.setFixedWidth(180)
        settings_layout.addWidget(self.spin_post_limit)

        helper = QLabel("Nilai 0 berarti semua grup pada daftar akan diproses.")
        helper.setObjectName("helperText")
        helper.setWordWrap(True)
        settings_layout.addWidget(helper)

        mode_label = QLabel("Mode Konten")
        mode_label.setObjectName("helperText")
        settings_layout.addWidget(mode_label)

        self.combo_content_mode = QComboBox()
        self.combo_content_mode.addItems(["Spintax / Manual", "AI Batch OpenRouter"])
        self.combo_content_mode.currentIndexChanged.connect(self._update_content_mode_ui)
        settings_layout.addWidget(self.combo_content_mode)

        automation_label = QLabel("Otomasi User")
        automation_label.setObjectName("helperText")
        settings_layout.addWidget(automation_label)

        self.chk_auto_load_groups = QCheckBox("Auto-load groups.txt")
        self.chk_auto_load_groups.setChecked(True)
        settings_layout.addWidget(self.chk_auto_load_groups)

        self.chk_auto_fallback = QCheckBox("Auto fallback ke manual jika AI gagal")
        self.chk_auto_fallback.setChecked(True)
        settings_layout.addWidget(self.chk_auto_fallback)

        self.chk_skip_confirm = QCheckBox("Lewati dialog konfirmasi sebelum posting")
        self.chk_skip_confirm.setChecked(False)
        settings_layout.addWidget(self.chk_skip_confirm)

        safety_label = QLabel("Guardrail Aman")
        safety_label.setObjectName("helperText")
        settings_layout.addWidget(safety_label)

        self.chk_safe_mode = QCheckBox("Mode aman konservatif")
        self.chk_safe_mode.setChecked(True)
        settings_layout.addWidget(self.chk_safe_mode)

        self.chk_stop_on_pending = QCheckBox("Berhenti jika post masuk pending admin")
        self.chk_stop_on_pending.setChecked(True)
        settings_layout.addWidget(self.chk_stop_on_pending)

        safe_cap_row = QHBoxLayout()
        safe_cap_row.setSpacing(10)
        safe_cap_label = QLabel("Batas sesi aman")
        safe_cap_label.setObjectName("helperText")
        safe_cap_row.addWidget(safe_cap_label)

        self.spin_safe_session_cap = QSpinBox()
        self.spin_safe_session_cap.setRange(5, 100)
        self.spin_safe_session_cap.setValue(SAFE_SESSION_CAP)
        self.spin_safe_session_cap.setSuffix(" grup")
        self.spin_safe_session_cap.setFixedWidth(130)
        safe_cap_row.addWidget(self.spin_safe_session_cap)
        safe_cap_row.addStretch()
        settings_layout.addLayout(safe_cap_row)
        left_layout.addWidget(settings_frame)

        self.btn_toggle_ai = QPushButton("Pengaturan AI")
        self.btn_toggle_ai.setObjectName("secondaryButton")
        self.btn_toggle_ai.setCheckable(True)
        self.btn_toggle_ai.setChecked(False)
        self.btn_toggle_ai.clicked.connect(self._toggle_ai_panel)
        left_layout.addWidget(self.btn_toggle_ai)

        self.ai_frame = QFrame()
        self.ai_frame.setObjectName("subPanel")
        self.ai_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        ai_layout = QVBoxLayout(self.ai_frame)
        ai_layout.setContentsMargins(16, 16, 16, 16)
        ai_layout.setSpacing(12)

        ai_hint = QLabel("Kontrol AI dipakai untuk generate batch caption sebelum proses posting dimulai.")
        ai_hint.setObjectName("helperText")
        ai_hint.setWordWrap(True)
        ai_layout.addWidget(ai_hint)

        api_label = QLabel("OpenRouter API Key")
        api_label.setObjectName("helperText")
        ai_layout.addWidget(api_label)

        self.input_openrouter_key = QLineEdit()
        self.input_openrouter_key.setPlaceholderText("sk-or-v1-...")
        self.input_openrouter_key.setEchoMode(QLineEdit.Password)
        ai_layout.addWidget(self.input_openrouter_key)

        model_label = QLabel("Model")
        model_label.setObjectName("helperText")
        ai_layout.addWidget(model_label)

        self.input_openrouter_model = QLineEdit()
        self.input_openrouter_model.setPlaceholderText(DEFAULT_OPENROUTER_MODEL)
        self.input_openrouter_model.setText(DEFAULT_OPENROUTER_MODEL)
        ai_layout.addWidget(self.input_openrouter_model)

        variant_label = QLabel("Jumlah Variasi")
        variant_label.setObjectName("helperText")
        ai_layout.addWidget(variant_label)

        variant_row = QHBoxLayout()
        variant_row.setSpacing(10)
        self.spin_variant_count = QSpinBox()
        self.spin_variant_count.setRange(1, 500)
        self.spin_variant_count.setValue(30)
        self.spin_variant_count.setFixedWidth(120)
        variant_row.addWidget(self.spin_variant_count)

        self.btn_generate_ai = QPushButton("Generate Variasi")
        self.btn_generate_ai.setFixedHeight(40)
        self.btn_generate_ai.clicked.connect(self._generate_ai_variations)
        variant_row.addWidget(self.btn_generate_ai)
        variant_row.addStretch()
        ai_layout.addLayout(variant_row)

        self.lbl_generated_summary = QLabel("Variasi AI belum dibuat")
        self.lbl_generated_summary.setObjectName("helperText")
        self.lbl_generated_summary.setWordWrap(True)
        ai_layout.addWidget(self.lbl_generated_summary)
        left_layout.addWidget(self.ai_frame)

        action_grid = QGridLayout()
        action_grid.setHorizontalSpacing(10)
        action_grid.setVerticalSpacing(10)
        action_grid.setColumnStretch(0, 1)
        action_grid.setColumnStretch(1, 1)
        self.btn_smart_start = QPushButton("Smart Start")
        self.btn_smart_start.setFixedHeight(48)
        self.btn_smart_start.clicked.connect(self._start_smart_run)
        action_grid.addWidget(self.btn_smart_start, 0, 0, 1, 2)

        self.btn_test_cookie = QPushButton("Tes Cookie")
        self.btn_test_cookie.setFixedHeight(48)
        self.btn_test_cookie.clicked.connect(self._start_cookie_test)
        action_grid.addWidget(self.btn_test_cookie, 1, 0)

        self.btn_fetch = QPushButton("Ambil Daftar Grup")
        self.btn_fetch.setFixedHeight(48)
        self.btn_fetch.clicked.connect(self._start_fetch_groups)
        action_grid.addWidget(self.btn_fetch, 1, 1)

        self.btn_load = QPushButton("Load groups.txt")
        self.btn_load.setFixedHeight(48)
        self.btn_load.clicked.connect(self._load_groups_file)
        action_grid.addWidget(self.btn_load, 2, 0, 1, 2)
        left_layout.addLayout(action_grid)

        post_row = QHBoxLayout()
        post_row.setSpacing(10)
        self.btn_post = QPushButton("Mulai Posting")
        self.btn_post.setFixedHeight(56)
        self.btn_post.setFont(QFont("Segoe UI Variable", 13, QFont.Bold))
        self.btn_post.clicked.connect(self._start_posting)
        post_row.addWidget(self.btn_post)

        self.btn_stop = QPushButton("Hentikan")
        self.btn_stop.setFixedHeight(56)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_worker)
        post_row.addWidget(self.btn_stop)
        left_layout.addLayout(post_row)
        left_layout.addStretch()

        groups_header = QHBoxLayout()
        groups_header.setSpacing(10)
        lbl_groups = QLabel("Daftar Grup")
        lbl_groups.setObjectName("sectionLabel")
        lbl_groups.setFont(QFont("Segoe UI Variable", 11))
        groups_header.addWidget(lbl_groups)
        groups_header.addStretch()

        self.lbl_group_summary = QLabel("Belum ada grup dimuat")
        self.lbl_group_summary.setObjectName("helperText")
        self.lbl_group_summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        groups_header.addWidget(self.lbl_group_summary)
        right_layout.addLayout(groups_header)

        self.group_list = QListWidget()
        self.group_list.setAlternatingRowColors(True)
        self.group_list.setFont(QFont("Segoe UI Variable", 10))
        self.group_list.setStyleSheet("QListWidget::item { padding: 7px 10px; }")
        self.group_list.setObjectName("groupList")
        right_layout.addWidget(self.group_list, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFixedHeight(24)
        right_layout.addWidget(self.progress)

        self.lbl_status = QLabel("Ready")
        self.lbl_status.setObjectName("statusLabel")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setFont(QFont("Segoe UI Variable", 10))
        right_layout.addWidget(self.lbl_status)

        lbl_log = QLabel("Log Aktivitas")
        lbl_log.setObjectName("sectionLabel")
        lbl_log.setFont(QFont("Segoe UI Variable", 11))
        right_layout.addWidget(lbl_log)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(220)
        self.log_view.setFont(QFont("Consolas", 10))
        self.log_view.setObjectName("logView")
        right_layout.addWidget(self.log_view, 1)

        self.spin_post_limit.valueChanged.connect(lambda _: self._update_group_summary(self.group_list.count()))
        self._update_content_mode_ui(self.combo_content_mode.currentIndex())

    def _toggle_ai_panel(self):
        self.ai_frame.setVisible(self.btn_toggle_ai.isChecked())

    def _update_content_mode_ui(self, index):
        is_ai_mode = index == 1
        self.btn_toggle_ai.setChecked(is_ai_mode)
        self.btn_toggle_ai.setText("Sembunyikan Pengaturan AI" if is_ai_mode else "Tampilkan Pengaturan AI")
        self.ai_frame.setVisible(is_ai_mode)
        self.btn_generate_ai.setEnabled(is_ai_mode)
        self.input_openrouter_key.setEnabled(is_ai_mode)
        self.input_openrouter_model.setEnabled(is_ai_mode)
        self.spin_variant_count.setEnabled(is_ai_mode)
        if is_ai_mode:
            self.lbl_generated_summary.setText(
                self.lbl_generated_summary.text() if getattr(self, "generated_posts", None) else "Variasi AI belum dibuat"
            )
        else:
            self.lbl_generated_summary.setText("Mode manual aktif. Panel AI disembunyikan untuk merapikan tampilan.")

    def _apply_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window,          QColor(14, 19, 27))
        palette.setColor(QPalette.WindowText,      QColor(229, 235, 241))
        palette.setColor(QPalette.Base,            QColor(20, 27, 36))
        palette.setColor(QPalette.AlternateBase,   QColor(27, 35, 46))
        palette.setColor(QPalette.Text,            QColor(229, 235, 241))
        palette.setColor(QPalette.Button,          QColor(29, 39, 52))
        palette.setColor(QPalette.ButtonText,      QColor(229, 235, 241))
        palette.setColor(QPalette.Highlight,       QColor(49, 130, 206))
        palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        QApplication.setPalette(palette)

        self.setStyleSheet("""
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0e131b, stop:0.45 #111827, stop:1 #16202a);
            }
            QWidget#central {
                background: transparent;
            }
            QScrollArea#leftScroll {
                background: transparent;
                border: none;
            }
            QScrollArea#leftScroll > QWidget > QWidget {
                background: transparent;
            }
            QFrame#panel {
                background: rgba(14, 22, 31, 0.78);
                border: 1px solid #243243;
                border-radius: 16px;
            }
            QFrame#subPanel {
                background: rgba(21, 30, 42, 0.92);
                border: 1px solid #2a3a4d;
                border-radius: 14px;
            }
            QLabel {
                color: #d8e1ea;
            }
            QLabel#pageTitle {
                color: #f5f7fb;
                letter-spacing: 0.4px;
            }
            QLabel#pageSubtitle {
                color: #93a4b8;
                padding-bottom: 6px;
            }
            QLabel#sectionLabel {
                color: #9fb2c8;
                font-weight: 600;
                padding-top: 6px;
            }
            QLabel#helperText {
                color: #7f93a8;
            }
            QLabel#statusLabel {
                background: rgba(22, 32, 42, 0.9);
                color: #dbe7f3;
                border: 1px solid #233142;
                border-radius: 10px;
                padding: 10px 14px;
            }
            QTextEdit, QListWidget {
                background: rgba(19, 26, 35, 0.96);
                color: #edf2f7;
                border: 1px solid #2b3a4d;
                border-radius: 12px;
                padding: 10px;
                selection-background-color: #3d7eff;
            }
            QTextEdit:focus, QListWidget:focus, QSpinBox:focus {
                border: 1px solid #4e9df5;
            }
            QPushButton {
                background: rgba(28, 39, 52, 0.95);
                color: #e7edf5;
                border: 1px solid #314257;
                border-radius: 11px;
                padding: 10px 18px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(37, 51, 68, 0.98);
                border-color: #45627f;
            }
            QPushButton:pressed {
                background: #1b2633;
            }
            QPushButton:disabled {
                background: rgba(31, 39, 48, 0.7);
                color: #7d8b99;
                border-color: #27323f;
            }
            QPushButton#secondaryButton {
                text-align: left;
                padding: 10px 14px;
                color: #9fb2c8;
            }
            QPushButton#secondaryButton:checked {
                background: rgba(24, 37, 52, 0.98);
                border-color: #4a6787;
                color: #edf2f7;
            }
            #btn_post {
                background: #0f7ae5;
                border: 1px solid #2893ff;
                color: white;
            }
            #btn_post:hover {
                background: #1388ff;
            }
            #btn_stop {
                background: #c44536;
                border: 1px solid #df5a4b;
                color: white;
            }
            #btn_stop:hover {
                background: #d54d3e;
            }
            QProgressBar {
                background: rgba(19, 26, 35, 0.96);
                border: 1px solid #2b3a4d;
                border-radius: 10px;
                text-align: center;
                color: #d9e4ee;
                padding: 2px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #177ddc, stop:1 #4db6ff);
                border-radius: 8px;
            }
            QSpinBox, QCheckBox {
                color: #dbe5ef;
            }
            QSpinBox, QLineEdit, QComboBox {
                background: rgba(19, 26, 35, 0.96);
                color: #edf2f7;
                border: 1px solid #2b3a4d;
                border-radius: 10px;
                padding: 6px 8px;
                min-height: 22px;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QCheckBox::indicator:unchecked {
                border: 1px solid #3b4f66;
                border-radius: 5px;
                background: #15202b;
            }
            QCheckBox::indicator:checked {
                border: 1px solid #3b8cff;
                border-radius: 5px;
                background: #1f6feb;
            }
        """)

        self.btn_post.setObjectName("btn_post")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_toggle_ai.setObjectName("secondaryButton")

    def log(self, message, category="info"):
        colors = {
            "success": "#34d399",
            "error":   "#f87171",
            "warning": "#fbbf24",
            "info":    "#60a5fa"
        }
        col = colors.get(category, "#cbd5e1")
        ts = time.strftime("%H:%M:%S")
        self.log_view.append(f'<span style="color:#6b7280">[{ts}]</span> <span style="color:{col}">{message}</span>')
        self.log_view.ensureCursorVisible()

    def _restore_ui_settings(self):
        settings = self._settings
        if not settings:
            return

        self.chk_headless.setChecked(bool(settings.get("headless", True)))
        self.spin_min.setValue(int(settings.get("delay_min", 8)))
        self.spin_max.setValue(int(settings.get("delay_max", 18)))
        self.spin_post_limit.setValue(int(settings.get("post_limit", 0)))
        self.spin_variant_count.setValue(int(settings.get("variant_count", 30)))
        self.input_openrouter_key.setText(str(settings.get("openrouter_api_key", "")))
        self.input_openrouter_model.setText(str(settings.get("openrouter_model", DEFAULT_OPENROUTER_MODEL)))
        self.combo_content_mode.setCurrentIndex(int(settings.get("content_mode", 0)))
        self.chk_auto_load_groups.setChecked(bool(settings.get("auto_load_groups", True)))
        self.chk_auto_fallback.setChecked(bool(settings.get("auto_fallback_manual", True)))
        self.chk_skip_confirm.setChecked(bool(settings.get("skip_post_confirm", False)))
        self.chk_safe_mode.setChecked(bool(settings.get("safe_mode", True)))
        self.chk_stop_on_pending.setChecked(bool(settings.get("stop_on_pending", True)))
        self.spin_safe_session_cap.setValue(int(settings.get("safe_session_cap", SAFE_SESSION_CAP)))

        draft_text = settings.get("draft_text", "")
        if isinstance(draft_text, str):
            self.post_edit.setPlainText(draft_text)
        self._refresh_generated_summary()

    def _persist_ui_settings(self):
        save_ui_settings({
            "headless": self.chk_headless.isChecked(),
            "delay_min": self.spin_min.value(),
            "delay_max": self.spin_max.value(),
            "post_limit": self.spin_post_limit.value(),
            "variant_count": self.spin_variant_count.value(),
            "openrouter_api_key": self.input_openrouter_key.text().strip(),
            "openrouter_model": self.input_openrouter_model.text().strip(),
            "content_mode": self.combo_content_mode.currentIndex(),
            "auto_load_groups": self.chk_auto_load_groups.isChecked(),
            "auto_fallback_manual": self.chk_auto_fallback.isChecked(),
            "skip_post_confirm": self.chk_skip_confirm.isChecked(),
            "safe_mode": self.chk_safe_mode.isChecked(),
            "stop_on_pending": self.chk_stop_on_pending.isChecked(),
            "safe_session_cap": self.spin_safe_session_cap.value(),
            "draft_text": self.post_edit.toPlainText(),
        })

    def _refresh_generated_summary(self):
        total = len(self.generated_posts)
        if total <= 0:
            self.lbl_generated_summary.setText("Variasi AI belum dibuat")
            return

        preview = self.generated_posts[0][:90]
        suffix = "..." if len(self.generated_posts[0]) > 90 else ""
        self.lbl_generated_summary.setText(f"{total} variasi siap dipakai. Contoh: {preview}{suffix}")

    def _resolve_post_target_count(self):
        total_groups = self.group_list.count()
        if total_groups <= 0:
            return 0
        post_limit = self.spin_post_limit.value()
        return total_groups if post_limit == 0 else min(total_groups, post_limit)

    def _generate_ai_variations(self):
        self._persist_ui_settings()
        source_text = self.post_edit.toPlainText().strip()
        api_key = self.input_openrouter_key.text().strip()
        model = self.input_openrouter_model.text().strip()
        count = self.spin_variant_count.value()
        target_count = self._resolve_post_target_count()
        if target_count > 0:
            count = target_count

        try:
            self.lbl_status.setText("Menghasilkan variasi AI...")
            self.btn_generate_ai.setEnabled(False)
            self.log(f"Menyiapkan {count} caption AI untuk distribusi per grup...", "info")
            posts = build_ai_caption_plan(api_key, model, source_text, count)
        except Exception as exc:
            self.log(f"Generate AI gagal: {str(exc)}", "error")
            QMessageBox.warning(self, "Generate Gagal", str(exc))
            return
        finally:
            self.btn_generate_ai.setEnabled(True)

        self.generated_posts = posts
        save_generated_posts(posts)
        self._refresh_generated_summary()
        self.lbl_status.setText(f"Caption AI siap ({len(posts)})")
        self.log(f"Berhasil menyiapkan {len(posts)} caption AI, satu untuk tiap grup target", "success")

    def _run_startup_automation(self):
        if self.chk_auto_load_groups.isChecked():
            self._load_groups_file(silent=True, log_missing=False)

    def _load_groups_into_list(self, groups, log_message=True):
        self.group_list.clear()
        for group in groups:
            self.group_list.addItem(group)
        self._update_group_summary(len(groups))
        if log_message:
            self.log(f"Memuat {len(groups)} grup dari file", "success")
        return True

    def _start_fetch_groups(self):
        self._persist_ui_settings()
        self.btn_smart_start.setEnabled(False)
        self.btn_test_cookie.setEnabled(False)
        self.btn_fetch.setEnabled(False)
        self.btn_load.setEnabled(False)
        self.progress.setValue(0)
        self.lbl_status.setText("Mengambil daftar grup...")
        self.log("Memulai pengambilan daftar grup...", "info")

        self.worker = BotWorker(mode="fetch", max_groups=None, headless=self.chk_headless.isChecked())
        self._connect_signals()
        self.worker.start()

    def _start_cookie_test(self, silent=False):
        self._persist_ui_settings()
        self._silent_cookie_test = silent
        self.btn_smart_start.setEnabled(False)
        self.btn_test_cookie.setEnabled(False)
        self.btn_fetch.setEnabled(False)
        self.btn_load.setEnabled(False)
        self.btn_post.setEnabled(False)
        self.progress.setValue(0)
        self.lbl_status.setText("Memeriksa validitas cookie...")
        self.log("Memulai pengecekan cookie...", "info")

        self.worker = BotWorker(mode="test_cookie", headless=self.chk_headless.isChecked())
        self._connect_signals()
        self.worker.start()

    def _start_smart_run(self):
        if self.worker and self.worker.isRunning():
            return

        self._persist_ui_settings()
        if self.group_list.count() == 0 and self.chk_auto_load_groups.isChecked():
            loaded = self._load_groups_file(silent=True, log_missing=False)
            if loaded:
                self.log("Daftar grup dimuat otomatis untuk Smart Start.", "info")

        self._smart_pipeline_active = True
        self._smart_pipeline_requires_fetch = self.group_list.count() == 0
        self.log("Smart Start dimulai: tes cookie, siapkan grup, lalu posting otomatis.", "info")
        self._start_cookie_test(silent=True)

    def _load_groups_file(self, silent=False, log_missing=True):
        groups = normalize_group_urls(load_groups())
        if not groups:
            if log_missing:
                self.log("groups.txt kosong atau tidak ada", "warning")
            if not silent:
                QMessageBox.warning(self, "groups.txt", "groups.txt kosong atau tidak ada.")
            return False
        return self._load_groups_into_list(groups, log_message=not silent)

    def _pick_media_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Pilih foto / video untuk dipost",
            str(Path.cwd()),
            "Media Files (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.mp4 *.mov *.avi *.mkv *.webm *.mpeg *.mpg *.m4v)"
        )
        if not paths:
            return

        picked = normalize_media_paths(paths)
        if not picked:
            QMessageBox.warning(self, "Media Tidak Valid", "Tidak ada file foto / video yang valid dipilih.")
            return

        self.media_paths = picked
        self._refresh_media_summary()
        self.log(f"Memilih {len(self.media_paths)} file media", "success")

    def _clear_media_files(self):
        self.media_paths = []
        self._refresh_media_summary()
        self.log("Daftar media dibersihkan", "info")

    def _refresh_media_summary(self):
        if not self.media_paths:
            self.lbl_media_summary.setText("Belum ada foto / video dipilih")
            return

        names = [Path(path).name for path in self.media_paths[:3]]
        summary = ", ".join(names)
        extra = len(self.media_paths) - len(names)
        if extra > 0:
            summary += f" +{extra} file lagi"

        self.lbl_media_summary.setText(f"{len(self.media_paths)} file dipilih: {summary}")

    def _cancel_smart_pipeline(self):
        self._smart_pipeline_active = False
        self._smart_pipeline_requires_fetch = False

    def _start_posting(self):
        self._persist_ui_settings()
        if self.group_list.count() == 0 and self.chk_auto_load_groups.isChecked():
            loaded = self._load_groups_file(silent=True, log_missing=False)
            if loaded:
                self.log("Daftar grup dimuat otomatis sebelum posting.", "info")

        all_groups = [self.group_list.item(i).text() for i in range(self.group_list.count())]
        text = self.post_edit.toPlainText().strip()
        media_paths = list(self.media_paths)
        content_mode = self.combo_content_mode.currentIndex()
        content_variants = []
        api_key = self.input_openrouter_key.text().strip()
        model = self.input_openrouter_model.text().strip()

        if not all_groups:
            self._cancel_smart_pipeline()
            QMessageBox.warning(self, "Peringatan", "Belum ada grup yang dipilih!")
            return
        if content_mode == 0 and not text and not media_paths:
            self._cancel_smart_pipeline()
            QMessageBox.warning(self, "Peringatan", "Isi postingan atau pilih minimal satu media!")
            return

        min_d = self.spin_min.value()
        max_d = self.spin_max.value()
        if min_d >= max_d:
            self._cancel_smart_pipeline()
            QMessageBox.warning(self, "Error", "Delay minimum harus lebih kecil dari maximum!")
            return

        post_limit = self.spin_post_limit.value()
        groups = all_groups if post_limit == 0 else all_groups[:post_limit]
        total = len(groups)
        if total <= 0:
            self._cancel_smart_pipeline()
            QMessageBox.warning(self, "Peringatan", "Tidak ada grup yang masuk ke target posting.")
            return

        safe_mode = self.chk_safe_mode.isChecked()
        stop_on_pending = self.chk_stop_on_pending.isChecked()
        burst_pause_every = 0
        burst_pause_min = 0
        burst_pause_max = 0
        safety_note = ""

        if safe_mode:
            safe_cap = self.spin_safe_session_cap.value()
            if total > safe_cap:
                groups = groups[:safe_cap]
                total = len(groups)
                self.log(f"Mode aman membatasi sesi ke {total} grup.", "warning")

            adjusted_min = max(min_d, SAFE_MIN_DELAY)
            adjusted_max = max(max_d, SAFE_MAX_DELAY, adjusted_min + 5)
            if adjusted_min != min_d or adjusted_max != max_d:
                self.log(
                    f"Mode aman menyesuaikan delay ke {adjusted_min}-{adjusted_max} detik.",
                    "warning"
                )
            min_d = adjusted_min
            max_d = adjusted_max
            burst_pause_every = SAFE_BURST_SIZE
            burst_pause_min = SAFE_BURST_PAUSE_MIN
            burst_pause_max = SAFE_BURST_PAUSE_MAX
            safety_note = (
                f"\nSafety mode: aktif | Sesi maks {total} grup | Cooloff tiap {SAFE_BURST_SIZE} grup"
            )

        if content_mode == 1:
            if not text:
                self._cancel_smart_pipeline()
                QMessageBox.warning(self, "Peringatan", "Isi posting dasar wajib diisi untuk generate caption AI.")
                return
            try:
                self.lbl_status.setText("Menyiapkan caption AI per grup...")
                self.log(f"Menyiapkan {total} caption AI untuk {total} grup target...", "info")
                content_variants = build_ai_caption_plan(api_key, model, text, total, existing_posts=self.generated_posts)
            except Exception as exc:
                self.lbl_status.setText("Generate caption AI gagal")
                self.log(f"Persiapan caption AI gagal: {str(exc)}", "error")
                if not self.chk_auto_fallback.isChecked():
                    fallback_reply = QMessageBox.question(
                        self,
                        "Generate Gagal",
                        f"{str(exc)}\n\nGunakan mode manual / spintax sebagai fallback untuk melanjutkan posting?",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if fallback_reply != QMessageBox.Yes:
                        self._cancel_smart_pipeline()
                        return
                content_mode = 0
                self.combo_content_mode.setCurrentIndex(0)
                self.log("Fallback ke mode manual / spintax untuk melanjutkan posting.", "warning")

            if content_variants:
                self.generated_posts = list(content_variants)
                save_generated_posts(self.generated_posts)
                self._refresh_generated_summary()

        media_note = f"\nMedia: {len(media_paths)} file" if media_paths else ""
        limit_note = "\nBatas post: semua grup" if post_limit == 0 else f"\nBatas post: {total} grup"
        mode_note = "\nMode konten: AI Batch OpenRouter" if content_mode == 1 else "\nMode konten: Spintax / Manual"
        ai_note = f"\nCaption AI siap: {len(content_variants)}" if content_mode == 1 else ""
        preview_note = ""
        if content_mode == 1 and content_variants:
            preview_text = build_caption_preview(groups, content_variants)
            if preview_text:
                preview_note = f"\n\nPreview mapping:\n{preview_text}"
        if not self.chk_skip_confirm.isChecked():
            reply = QMessageBox.question(
                self, "Konfirmasi",
                f"Posting ke <b>{total}</b> grup?\n"
                f"Delay: {min_d} - {max_d} detik{media_note}{limit_note}{mode_note}{ai_note}{safety_note}{preview_note}\nLanjutkan?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                self._cancel_smart_pipeline()
                return
        else:
            self.log(f"Konfirmasi dilewati. Job langsung dimulai untuk {total} grup.", "info")

        self.progress.setValue(0)
        self.btn_post.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_test_cookie.setEnabled(False)
        self.btn_fetch.setEnabled(False)
        self.btn_load.setEnabled(False)

        self.worker = BotWorker(
            mode="post",
            text=text,
            delay_min=min_d,
            delay_max=max_d,
            groups=groups,
            media_paths=media_paths,
            content_variants=content_variants,
            headless=self.chk_headless.isChecked(),
            stop_on_pending=stop_on_pending,
            burst_pause_every=burst_pause_every,
            burst_pause_min=burst_pause_min,
            burst_pause_max=burst_pause_max,
        )
        self._connect_signals()
        self.worker.start()

    def _connect_signals(self):
        self.worker.log.connect(self.log)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.status.connect(self.lbl_status.setText)
        self.worker.groups_ready.connect(self._on_groups_ready)
        self.worker.report_ready.connect(self._on_report_ready)
        self.worker.completed.connect(self._on_worker_completed)
        self.worker.finished.connect(self._cleanup_worker)

    def _update_group_summary(self, total):
        if total <= 0:
            self.lbl_group_summary.setText("Belum ada grup dimuat")
            return

        post_limit = self.spin_post_limit.value()
        active_total = total if post_limit == 0 else min(total, post_limit)
        self.lbl_group_summary.setText(f"Total {total} grup | Akan dipost {active_total}")

    def _on_groups_ready(self, groups):
        self.group_list.clear()
        for url in groups:
            self.group_list.addItem(url)
        self._update_group_summary(len(groups))
        if groups:
            self.log(f"Berhasil mengumpulkan {len(groups)} grup", "success")
        else:
            self.log("Tidak ada grup yang berhasil dikumpulkan", "warning")

    def _on_report_ready(self, report_path):
        self.log(f"Report tersimpan: {Path(report_path).name}", "info")

    def _on_worker_completed(self, mode, result_count, processed_total):
        was_smart_pipeline = self._smart_pipeline_active
        self.btn_post.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_smart_start.setEnabled(True)
        self.btn_test_cookie.setEnabled(True)
        self.btn_fetch.setEnabled(True)
        self.btn_load.setEnabled(True)

        if mode == "test_cookie":
            self.progress.setValue(100 if result_count else 0)
            self.lbl_status.setText("Cookie valid" if result_count else "Cookie tidak valid")
            if result_count and was_smart_pipeline:
                if self._smart_pipeline_requires_fetch:
                    self.log("Cookie valid. Smart Start lanjut ambil daftar grup...", "info")
                    self._start_fetch_groups()
                else:
                    self.log("Cookie valid. Smart Start lanjut ke posting...", "info")
                    self._start_posting()
                return
            if result_count and not self._silent_cookie_test:
                QMessageBox.information(self, "Tes Cookie", "Cookie valid dan sesi Facebook bisa digunakan.")
            if not result_count:
                self._smart_pipeline_active = False
            self._silent_cookie_test = False
            return

        if mode == "fetch":
            self.progress.setValue(100 if result_count > 0 else 0)
            self.lbl_status.setText("Selesai ambil grup")
            if was_smart_pipeline:
                if result_count > 0:
                    self.log("Daftar grup siap. Smart Start lanjut ke posting...", "info")
                    self._smart_pipeline_requires_fetch = False
                    self._start_posting()
                else:
                    self.log("Smart Start berhenti karena tidak ada grup yang berhasil diambil.", "warning")
                    self._smart_pipeline_active = False
            return

        total = processed_total
        self.lbl_status.setText("Selesai")
        self.progress.setValue(100)

        failed_total = max(total - result_count, 0)
        msg = f"Proses selesai\nBerhasil: {result_count} / {total}\nGagal: {failed_total}"
        self.log(msg, "success" if result_count > total // 2 else "warning")

        self._smart_pipeline_active = False
        self._silent_cookie_test = False
        QMessageBox.information(self, "Selesai", msg)

    def _stop_worker(self):
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self.log("Permintaan penghentian dikirim...", "warning")
            self.btn_stop.setEnabled(False)

    def _cleanup_worker(self):
        worker = self.sender()
        if worker is not None:
            worker.deleteLater()
        if worker is self.worker:
            self.worker = None

    def closeEvent(self, event: QCloseEvent):
        self._persist_ui_settings()
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self.worker.wait(5000)
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = FacebookPosterUI()
    window.show()
    sys.exit(app.exec())
