import sys
import os
import json
import time
import random
import re
import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QListWidget, QSpinBox, QProgressBar,        
    QMessageBox, QFileDialog, QCheckBox
)
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QFont, QPalette, QColor

# ─── Selenium Imports ────────────────────────────────────────────────────────
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ─── Constants ───────────────────────────────────────────────────────────────
COOKIE_FILE = "cookies.json"
GROUP_FILE  = "groups.txt"
SUPPORTED_MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mpeg", ".mpg", ".m4v"
}


# ─── Helper Functions ────────────────────────────────────────────────────────
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
        os.makedirs("screenshots", exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        # Remove invalid chars from URL snippet
        safe_name = "".join([c for c in custom_name if c.isalpha() or c.isdigit() or c=='_']) 
        filepath = f"screenshots/{safe_name}_{ts}.png"
        driver.save_screenshot(filepath)
        return filepath
    except: return None

def sanitize_text(text):
    return ''.join(c for c in text if ord(c) <= 0xFFFF)


def load_cookies(driver):
    if not os.path.exists(COOKIE_FILE):
        return False
    try:
        cookies = json.loads(Path(COOKIE_FILE).read_text(encoding="utf-8"))
        for cookie in cookies:
            try:
                driver.add_cookie({
                    "name": cookie["name"],
                    "value": cookie["value"],
                    "domain": cookie.get("domain", ".facebook.com"),
                    "path": cookie.get("path", "/")
                })
            except:
                pass
        return True
    except:
        return False


def save_groups(groups):
    Path(GROUP_FILE).write_text("\n".join(groups) + "\n", encoding="utf-8")


def load_groups():
    if not os.path.exists(GROUP_FILE):
        return []
    return [line.strip() for line in Path(GROUP_FILE).read_text(encoding="utf-8").splitlines() if line.strip()]


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


# ─── Posting Logic ───────────────────────────────────────────────────────────
def open_group_composer(driver):
    try:
        # Give JS a moment to render the page fully, especially in headless mode.
        human_delay(1.5, 3)

        # In Buy/Sell groups, the default view is "Sell". We should click "Discussion" or "Diskusi" tab first if present
        try:
            discussion_tabs = driver.find_elements(By.XPATH, "//div[@role='tablist']//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'discussion') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'diskusi')] | //div[@role='navigation']//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'discussion') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'diskusi')]")
            for tab in discussion_tabs:
                if tab.is_displayed():
                    driver.execute_script("arguments[0].click();", tab)
                    human_delay(2, 4)
                    break
        except:
            pass

        # Look for the container that contains the placeholder in different languages
        keywords = ["tulis sesuatu", "write something", "buat postingan", "kirim postingan", "create a public", "jual sesuatu", "sell something"]
        xpath = " | ".join([
            f"//div[@role='button']//span[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{kw}')]"
            for kw in keywords
        ]) + " | " + " | ".join([
            f"//span[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{kw}')]"
            for kw in keywords
        ])

        triggers = driver.find_elements(By.XPATH, xpath)
        for trigger in triggers:
            # Check visibility
            if trigger.is_displayed():
                try:
                    trigger.click()
                    return True
                except:
                    pass
                try:
                    driver.execute_script("arguments[0].click();", trigger)
                    return True
                except:
                    pass

        # Robust Fallback clicking the main placeholder container
        fallback = driver.find_elements(By.XPATH, "//div[contains(@class, 'x1i10hfl') and @role='button']//span[contains(., 'Tulis') or contains(., 'Write') or contains(., 'Buat') or contains(., 'Create') or contains(., 'Kirim')]")
        if fallback:
            for fb in fallback:
                try:
                    driver.execute_script("arguments[0].click();", fb)
                    return True
                except:
                    continue

        return False
    except Exception as e:
        print("open_group_composer error:", e)
        return False


def wait_group_editor(driver, timeout=20):
    try:
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((
                By.XPATH,
                "//div[@role='textbox'][@contenteditable='true'][@data-lexical-editor='true']"
            ))
        )
    except:
        return None


def open_media_picker(driver):
    triggers = driver.find_elements(By.XPATH,
        "//div[@role='button'][contains(., 'Foto/video') or contains(., 'Photo/video') or contains(., 'Photos/videos') or contains(., 'Foto') or contains(@aria-label, 'Foto/video') or contains(@aria-label, 'Photo/video')] | "
        "//span[contains(., 'Foto/video') or contains(., 'Photo/video') or contains(., 'Photos/videos')]"
    )
    for trigger in triggers:
        try:
            driver.execute_script("arguments[0].click();", trigger)
            return True
        except:
            continue
    return False


def wait_media_input(driver, timeout=20):
    try:
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((
                By.XPATH,
                "//input[@type='file' and (contains(@accept, 'image') or contains(@accept, 'video') or not(@accept))]"
            ))
        )
    except:
        return None


def upload_media_files(driver, media_paths, timeout=45):
    if not media_paths:
        return True, None

    media_input = wait_media_input(driver, timeout=4)
    if not media_input and not open_media_picker(driver):
        return False, "Tombol upload media tidak ditemukan"

    if not media_input:
        media_input = wait_media_input(driver, timeout=timeout)
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
        # FB lexical editors can be finicky. Wait for it to be interactable.
        WebDriverWait(driver, 5).until(EC.element_to_be_clickable(element))
        
        driver.execute_script("arguments[0].focus();", element)
        human_delay(0.5, 1.2)

        try:
            ActionChains(driver).move_to_element(element).click().send_keys(clean).perform()
            human_delay(0.8, 1.5)
        except Exception:
            # If ActionChains fails (e.g. element not interactable), fallback to click and send
            element.click()
            element.send_keys(clean)
            human_delay(0.8, 1.5)

        # FB might intercept normal send_keys. If still empty, use a DataTransfer event or direct input
        if not element.text.strip():
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
            
            # Absolute fallback if it's still missing
            if not driver.execute_script("return arguments[0].innerText;", element).strip():
                driver.execute_script("""
                    arguments[0].innerText = arguments[1];
                    arguments[0].dispatchEvent(new Event('input', {bubbles: true}));
                """, element, clean)
        
        return True
    except Exception as e:
        print("input error:", e)
        return False


def wait_post_button(driver, timeout=20):
    try:
        return WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//div[@role='button'][contains(@aria-label, 'Post') or contains(@aria-label, 'Posting') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'post')]"
            ))
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

# ─── Bot Worker Thread ───────────────────────────────────────────────────────
class BotWorker(QThread):
    log           = Signal(str, str)     # msg, category
    progress      = Signal(int)
    status        = Signal(str)
    finished      = Signal(int)          # success count
    groups_ready  = Signal(list)

    def __init__(self, mode, text="", delay_min=8, delay_max=18, max_groups=70, groups=None, media_paths=None, headless=True):
        super().__init__()
        self.mode       = mode
        self.text       = text
        self.delay_min  = delay_min
        self.delay_max  = delay_max
        self.max_groups = max_groups
        self.groups     = groups or []
        self.media_paths = media_paths or []
        self.headless   = headless
        self._stop_flag = False

    def request_stop(self):
        self._stop_flag = True

    def emit_log(self, message, category="info", log_to_file=True):
        self.log.emit(message, category)
        if log_to_file:
            try:
                import datetime
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open("app.log", "a", encoding="utf-8") as f:
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
        success_count = 0
        failed_urls = []

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
            self.emit_log("Login berhasil via cookies", "success")

            if self.mode == "fetch":
                groups = self._fetch_groups(driver)
                save_groups(groups)
                self.groups_ready.emit(groups)
                return

            # ── Posting mode ───────────────────────────────────────────────── 
            total = len(self.groups)
            if total == 0:
                self.emit_log("Tidak ada grup untuk diproses", "error")
                return

            self.status.emit(f"Memproses {total} grup...")

            for i, url in enumerate(self.groups, 1):
                if self._stop_flag:
                    self.emit_log("Proses dihentikan oleh pengguna", "warning") 
                    break

                short_url = url.split("/")[-1] or url
                self.emit_log(f"[{i}/{total}] → {short_url}", "info")

                try:
                    driver.get(url)
                    human_delay(5.5, 9.5)

                    if not open_group_composer(driver):
                        self.emit_log("   Gagal membuka composer", "error")
                        capture_screenshot_on_error(driver, f"err_composer_{short_url}")
                        failed_urls.append(url)
                        continue

                    editor = wait_group_editor(driver, timeout=12)
                    if self.text:
                        if not editor:
                            self.emit_log("   Editor tidak ditemukan", "error") 
                            capture_screenshot_on_error(driver, f"err_editor_{short_url}")
                            failed_urls.append(url)
                            continue

                        # Parse Spintax before inserting text
                        spintaxed_text = parse_spintax(self.text)

                        if not input_text_strict(driver, editor, spintaxed_text):    
                            self.emit_log("   Gagal memasukkan teks", "error")  
                            capture_screenshot_on_error(driver, f"err_text_{short_url}")
                            failed_urls.append(url)
                            continue

                    if self.media_paths:
                        self.emit_log(f"   Mengunggah {len(self.media_paths)} media...", "info")
                        uploaded, reason = upload_media_files(driver, self.media_paths)
                        if not uploaded:
                            self.emit_log(f"   Upload media gagal: {reason}", "error")
                            capture_screenshot_on_error(driver, f"err_media_{short_url}")
                            failed_urls.append(url)
                            continue

                        # Beri waktu Facebook memproses preview, khususnya untuk video.
                        if any(Path(path).suffix.lower() in {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.mpeg', '.mpg', '.m4v'} for path in self.media_paths):   
                            human_delay(12, 18)
                        else:
                            human_delay(4, 7)

                    btn = wait_post_button(driver)
                    if not btn:
                        self.emit_log("   Tombol Post tidak muncul/aktif", "error")
                        capture_screenshot_on_error(driver, f"err_btn_post_{short_url}")
                        failed_urls.append(url)
                        continue

                    driver.execute_script("arguments[0].click();", btn)
                    human_delay(4, 8)

                    if check_pending_post(driver):
                        self.emit_log("   [PENDING] Postingan menunggu persetujuan Admin", "warning")
                    else:
                        self.emit_log("   Berhasil diposting ✓", "success")
                        success_count += 1

                except Exception as e:
                    self.emit_log(f"   Error: {str(e)[:140]}...", "error")      
                    capture_screenshot_on_error(driver, f"err_exception_{short_url}")
                    failed_urls.append(url)

                prog = int((i / total) * 100)
                self.progress.emit(prog)

                delay = random.uniform(self.delay_min, self.delay_max)
                self.status.emit(f"Menunggu {delay:.1f} detik...")
                time.sleep(delay)

            # Write failed groups fallback sum at the end
            if failed_urls:
                try:
                    with open("failed_groups.txt", "w", encoding="utf-8") as f:
                        f.write("\n".join(failed_urls))
                    self.emit_log(f"Menyimpan {len(failed_urls)} grup yang gagal ke failed_groups.txt", "info")
                except: pass

            self.finished.emit(success_count)

        except Exception as e:
            self.emit_log(f"Critical error: {str(e)}", "error")
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass

    def _fetch_groups(self, driver):
        driver.get("https://www.facebook.com/groups/joins/")
        human_delay(6, 10)

        groups = set()
        last_count = 0

        while len(groups) < self.max_groups:
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
                self.emit_log(f"↻ Ditemukan {count_now} grup unik...", "info")  

                if count_now == last_count:
                    self.emit_log("Tidak ada grup baru setelah scroll → selesai", "info")
                    break

                last_count = count_now

                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                human_delay(4, 8)

            except Exception as e:
                self.emit_log(f"Error saat fetch: {str(e)[:120]}", "warning")   

        return list(groups)[:self.max_groups]


# ─── Main Window ─────────────────────────────────────────────────────────────
class FacebookPosterUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Auto Post Group Beta Version           IG : @ncots_id           Tele : @jlimboo")
        self.resize(1020, 800)
        self.setMinimumSize(880, 660)

        self.worker = None
        self.media_paths = []
        self._init_ui()
        self._apply_dark_theme()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        grid = QGridLayout(central)
        grid.setContentsMargins(22, 22, 22, 22)
        grid.setSpacing(14)

        # Title
        title = QLabel("Auto Post Mode Santai :v")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Segoe UI Variable", 17, QFont.Bold))
        grid.addWidget(title, 0, 0, 1, 3)
        
        self.chk_headless = QCheckBox("Mode Tersembunyi (Headless)")
        self.chk_headless.setChecked(True)
        self.chk_headless.setFont(QFont("Segoe UI Variable", 10))
        grid.addWidget(self.chk_headless, 0, 3, 1, 2, alignment=Qt.AlignRight)

        # Text area
        lbl_text = QLabel("Isi Posting")
        lbl_text.setFont(QFont("Segoe UI Variable", 11))
        grid.addWidget(lbl_text, 1, 0, alignment=Qt.AlignRight | Qt.AlignTop)

        self.post_edit = QTextEdit()
        self.post_edit.setPlaceholderText("Tulis konten yang ingin disebar ke semua grup...")
        self.post_edit.setMinimumHeight(140)
        self.post_edit.setFont(QFont("Segoe UI Variable", 11))
        grid.addWidget(self.post_edit, 1, 1, 1, 4)

        # Media
        lbl_media = QLabel("Media")
        lbl_media.setFont(QFont("Segoe UI Variable", 11))
        grid.addWidget(lbl_media, 2, 0, alignment=Qt.AlignRight | Qt.AlignTop)

        media_box = QHBoxLayout()
        self.lbl_media_summary = QLabel("Belum ada foto / video dipilih")
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

        grid.addLayout(media_box, 2, 1, 1, 4)

        # Delay
        lbl_delay = QLabel("Delay")
        lbl_delay.setFont(QFont("Segoe UI Variable", 11))
        grid.addWidget(lbl_delay, 3, 0, alignment=Qt.AlignRight)

        delay_box = QHBoxLayout()
        self.spin_min = QSpinBox()
        self.spin_min.setRange(4, 120)
        self.spin_min.setValue(8)
        self.spin_min.setSuffix(" s")
        self.spin_min.setFixedWidth(95)
        delay_box.addWidget(self.spin_min)

        delay_box.addWidget(QLabel(" – "))

        self.spin_max = QSpinBox()
        self.spin_max.setRange(6, 300)
        self.spin_max.setValue(18)
        self.spin_max.setSuffix(" s")
        self.spin_max.setFixedWidth(95)
        delay_box.addWidget(self.spin_max)

        delay_box.addStretch()
        grid.addLayout(delay_box, 3, 1, 1, 4)

        # Buttons row 1
        btn_row1 = QHBoxLayout()
        self.btn_fetch = QPushButton("Ambil Daftar Grup")
        self.btn_fetch.setFixedHeight(48)
        self.btn_fetch.clicked.connect(self._start_fetch_groups)
        btn_row1.addWidget(self.btn_fetch)

        self.btn_load = QPushButton("Load groups.txt")
        self.btn_load.setFixedHeight(48)
        self.btn_load.clicked.connect(self._load_groups_file)
        btn_row1.addWidget(self.btn_load)

        grid.addLayout(btn_row1, 4, 0, 1, 5)

        # Group list
        lbl_groups = QLabel("Daftar Grup")
        lbl_groups.setFont(QFont("Segoe UI Variable", 11))
        grid.addWidget(lbl_groups, 5, 0, alignment=Qt.AlignRight | Qt.AlignTop)

        self.group_list = QListWidget()
        self.group_list.setAlternatingRowColors(True)
        self.group_list.setFont(QFont("Segoe UI Variable", 10))
        self.group_list.setStyleSheet("QListWidget::item { padding: 7px 10px; }")
        grid.addWidget(self.group_list, 5, 1, 1, 4)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFixedHeight(24)
        grid.addWidget(self.progress, 6, 0, 1, 5)

        self.lbl_status = QLabel("Ready")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setFont(QFont("Segoe UI Variable", 10))
        grid.addWidget(self.lbl_status, 7, 0, 1, 5)

        # Post + Stop
        post_row = QHBoxLayout()
        self.btn_post = QPushButton("POST MASSAL 🚀")
        self.btn_post.setFixedHeight(56)
        self.btn_post.setFont(QFont("Segoe UI Variable", 13, QFont.Bold))
        self.btn_post.clicked.connect(self._start_posting)
        post_row.addWidget(self.btn_post)

        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setFixedHeight(56)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_worker)
        post_row.addWidget(self.btn_stop)

        grid.addLayout(post_row, 8, 0, 1, 5)

        # Log
        lbl_log = QLabel("Log")
        lbl_log.setFont(QFont("Segoe UI Variable", 11))
        grid.addWidget(lbl_log, 9, 0, alignment=Qt.AlignRight | Qt.AlignTop)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(190)
        self.log_view.setFont(QFont("Consolas", 10))
        grid.addWidget(self.log_view, 9, 1, 1, 4)

        grid.setColumnStretch(1, 1)
        grid.setRowStretch(9, 1)

    def _apply_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window,          QColor(24, 24, 28))
        palette.setColor(QPalette.WindowText,      QColor(225, 225, 235))
        palette.setColor(QPalette.Base,            QColor(32, 32, 38))
        palette.setColor(QPalette.AlternateBase,   QColor(38, 38, 46))
        palette.setColor(QPalette.Text,            QColor(225, 225, 235))
        palette.setColor(QPalette.Button,          QColor(40, 40, 48))
        palette.setColor(QPalette.ButtonText,      QColor(225, 225, 235))
        palette.setColor(QPalette.Highlight,       QColor(70, 130, 255))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        QApplication.setPalette(palette)

        self.setStyleSheet("""
            QMainWindow {
                background: #18181c;
            }
            QLabel {
                color: #d0d0e0;
            }
            QTextEdit, QListWidget {
                background: #22222a;
                color: #e8e8f0;
                border: 1px solid #383844;
                border-radius: 9px;
                padding: 9px;
                selection-background-color: #4a6aff;
            }
            QPushButton {
                background: #34344a;
                color: #e0e0ff;
                border: 1px solid #4a4a60;
                border-radius: 9px;
                padding: 10px 20px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #44445c;
            }
            QPushButton:pressed {
                background: #28283c;
            }
            #btn_post {
                background: #0066ff;
                border: none;
                color: white;
            }
            #btn_post:hover {
                background: #0055dd;
            }
            #btn_stop {
                background: #e63946;
                border: none;
                color: white;
            }
            #btn_stop:hover {
                background: #d32f2f;
            }
            QProgressBar {
                background: #22222a;
                border: 1px solid #383844;
                border-radius: 9px;
                text-align: center;
                color: #d0d0e0;
            }
            QProgressBar::chunk {
                background: #0066ff;
                border-radius: 8px;
            }
            QSpinBox {
                background: #22222a;
                color: #e8e8f0;
                border: 1px solid #383844;
                border-radius: 7px;
                padding: 5px;
            }
        """)

        self.btn_post.setObjectName("btn_post")
        self.btn_stop.setObjectName("btn_stop")

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

    def _start_fetch_groups(self):
        self.btn_fetch.setEnabled(False)
        self.btn_load.setEnabled(False)
        self.log("Memulai pengambilan daftar grup...", "info")

        self.worker = BotWorker(mode="fetch", max_groups=80, headless=self.chk_headless.isChecked())
        self._connect_signals()
        self.worker.start()

    def _load_groups_file(self):
        groups = load_groups()
        if not groups:
            self.log("groups.txt kosong atau tidak ada", "warning")
            return
        self.group_list.clear()
        for g in groups:
            self.group_list.addItem(g)
        self.log(f"Memuat {len(groups)} grup dari file", "success")

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

    def _start_posting(self):
        groups = [self.group_list.item(i).text() for i in range(self.group_list.count())]
        text = self.post_edit.toPlainText().strip()
        media_paths = list(self.media_paths)

        if not groups:
            QMessageBox.warning(self, "Peringatan", "Belum ada grup yang dipilih!")
            return
        if not text and not media_paths:
            QMessageBox.warning(self, "Peringatan", "Isi postingan atau pilih minimal satu media!")
            return

        min_d = self.spin_min.value()
        max_d = self.spin_max.value()
        if min_d >= max_d:
            QMessageBox.warning(self, "Error", "Delay minimum harus lebih kecil dari maximum!")
            return

        total = len(groups)
        media_note = f"\nMedia: {len(media_paths)} file" if media_paths else ""
        reply = QMessageBox.question(
            self, "Konfirmasi",
            f"Posting ke <b>{total}</b> grup?\n"
            f"Delay: {min_d} – {max_d} detik{media_note}\nLanjutkan?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.progress.setValue(0)
        self.btn_post.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_fetch.setEnabled(False)
        self.btn_load.setEnabled(False)

        self.worker = BotWorker(
            mode="post",
            text=text,
            delay_min=min_d,
            delay_max=max_d,
            groups=groups,
            media_paths=media_paths,
            headless=self.chk_headless.isChecked()
        )
        self._connect_signals()
        self.worker.start()

    def _connect_signals(self):
        self.worker.log.connect(self.log)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.status.connect(self.lbl_status.setText)
        self.worker.groups_ready.connect(self._on_groups_ready)
        self.worker.finished.connect(self._on_finished)

    def _on_groups_ready(self, groups):
        self.group_list.clear()
        for url in groups:
            self.group_list.addItem(url)
        self.log(f"Berhasil mengumpulkan {len(groups)} grup", "success")
        self.btn_fetch.setEnabled(True)
        self.btn_load.setEnabled(True)

    def _on_finished(self, success_count):
        total = self.group_list.count()
        self.btn_post.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_fetch.setEnabled(True)
        self.btn_load.setEnabled(True)
        self.lbl_status.setText("Selesai")
        self.progress.setValue(100)

        msg = f"Proses selesai\nBerhasil: {success_count} / {total}\nGagal: {total - success_count}"
        self.log(msg, "success" if success_count > total//2 else "warning")

        QMessageBox.information(self, "Selesai", msg)

    def _stop_worker(self):
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self.log("Permintaan penghentian dikirim...", "warning")
            self.btn_stop.setEnabled(False)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = FacebookPosterUI()
    window.show()
    sys.exit(app.exec())
