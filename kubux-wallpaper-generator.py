# Copyright 2025 [Kai-Uwe Bux]
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import hashlib
import json
import os
import math
import platform
import queue
import secrets
import threading
import subprocess
import sys
import time
from collections import OrderedDict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from math import gcd

from PySide6.QtCore import (Qt, QSize, QPoint, QTimer, Signal, QObject, QByteArray, QEvent)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton,
                              QVBoxLayout, QHBoxLayout, QGridLayout, QTextEdit,
                              QScrollArea, QSlider, QDialog, QMessageBox, QFrame,
                              QScrollBar, QSizePolicy, QListWidget, QSplitter,
                              QSpacerItem, QFileDialog, QLayout, QLineEdit)
from PySide6.QtGui import (QPixmap, QImage, QPainter, QColor, QFont, QFontMetrics,
                          QTextCursor, QIcon, QAction, QCursor, QPalette, QGuiApplication)
from watchdog.events import FileSystemEventHandler, FileClosedNoWriteEvent, FileOpenedEvent
from watchdog.observers import Observer

from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
from dotenv import load_dotenv
from together import Together
import requests

load_dotenv()

# --- configuration ---

TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
ai_features_enabled = bool(TOGETHER_API_KEY)

SUPPORTED_IMAGE_EXTENSIONS = (
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tif', '.tiff', '.webp',
    '.ico', '.icns', '.avif', '.dds', '.msp', '.pcx', '.ppm',
    '.pbm', '.pgm', '.sgi', '.tga', '.xbm', '.xpm'
)

CACHE_SIZE = 1000

HOME_DIR = os.path.expanduser('~')
CONFIG_DIR = os.path.join(HOME_DIR, ".config", "kubux-wallpaper-generator")
CACHE_DIR = os.path.join(HOME_DIR, ".cache", "kubux-thumbnail-cache")
THUMBNAIL_CACHE_ROOT = os.path.join(CACHE_DIR, "thumbnails")
DOWNLOAD_DIR = os.path.join(HOME_DIR, "Pictures", "kubux-wallpaper-generator")
IMAGE_DIR = os.path.join(CONFIG_DIR, "images")
DEFAULT_THUMBNAIL_DIM = 192
PROMPT_HISTORY_FILE = os.path.join(CONFIG_DIR, "prompt_history.json")
APP_SETTINGS_FILE = os.path.join(CONFIG_DIR, "app_settings.json")

os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(THUMBNAIL_CACHE_ROOT, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# --- logging ---

def log_action(msg):
    print(msg)

def log_error(msg):
    print(msg)

def log_debug(msg):
    print(msg)


# --- probe font ---

def get_gtk_ui_font():
    try:
        subprocess.run(["which", "gsettings"], check=True, capture_output=True)
        font_info_str = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "font-name"],
            capture_output=True, text=True, check=True
        ).stdout.strip().strip("'")
        parts = font_info_str.rsplit(' ', 1)
        font_name = "Sans"
        font_size = 10
        if len(parts) == 2 and parts[1].isdigit():
            font_name = parts[0]
            font_size = int(parts[1])
        else:
            try:
                last_space_idx = font_info_str.rfind(' ')
                if last_space_idx != -1 and font_info_str[last_space_idx+1:].isdigit():
                    font_name = font_info_str[:last_space_idx]
                    font_size = int(font_info_str[last_space_idx+1:])
            except Exception as e:
                log_error(f"Error parsing gsettings font: {e}")
        return font_name, font_size
    except subprocess.CalledProcessError:
        return "Sans", 10
    except Exception as e:
        log_error(f"Error getting GTK font: {e}")
        return "Sans", 10

def get_kde_ui_font():
    try:
        subprocess.run(["which", "kreadconfig5"], check=True, capture_output=True)
        font_string = subprocess.run(
            ["kreadconfig5", "--file", "kdeglobals", "--group", "General", "--key", "font",
             "--default", "Sans,10,-1,5,50,0,0,0,0,0"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
        parts = font_string.split(',')
        if len(parts) >= 2:
            return parts[0].strip(), int(parts[1].strip())
        return "Sans", 10
    except:
        return "Sans", 10

def get_linux_system_ui_font_info():
    desktop_session = os.environ.get("XDG_CURRENT_DESKTOP")
    if not desktop_session:
        desktop_session = os.environ.get("DESKTOP_SESSION")
    if desktop_session and ("GNOME" in desktop_session.upper() or
                            "CINNAMON" in desktop_session.upper() or
                            "XFCE" in desktop_session.upper() or
                            "MATE" in desktop_session.upper()):
        return get_gtk_ui_font()
    elif desktop_session and "KDE" in desktop_session.upper():
        return get_kde_ui_font()
    return "Sans", 10


# --- image ops ---

def resize_image(image, target_width, target_height):
    original_width, original_height = image.size
    if target_width <= 0 or target_height <= 0:
        return image.copy()
    target_aspect = target_width / target_height
    image_aspect = original_width / original_height
    if image_aspect > target_aspect:
        new_width = target_width
        new_height = int(target_width / image_aspect)
    else:
        new_height = target_height
        new_width = int(target_height * image_aspect)
    new_width = max(1, new_width)
    new_height = max(1, new_height)
    return image.resize((new_width, new_height), resample=Image.LANCZOS)

def calculate_thumbnail_dimensions(original_width, original_height, target_width, target_height):
    if target_width <= 0 or target_height <= 0:
        return original_width, original_height
    target_aspect = target_width / target_height
    image_aspect = original_width / original_height
    if image_aspect > target_aspect:
        new_width = target_width
        new_height = int(target_width / image_aspect)
    else:
        new_height = target_height
        new_width = int(target_height * image_aspect)
    return max(1, new_width), max(1, new_height)

def get_thumbnail_dimensions(img_path, max_size):
    try:
        with Image.open(img_path) as img:
            orig_w, orig_h = img.size
        return calculate_thumbnail_dimensions(orig_w, orig_h, max_size, max_size)
    except:
        return max_size, max_size

def uniq_file_id(img_path, width=-1):
    try:
        real_path = os.path.realpath(img_path)
        mtime = os.path.getmtime(real_path)
    except FileNotFoundError:
        log_error(f"File not found: {img_path}")
        return None
    except Exception as e:
        log_error(f"Could not get mtime for {img_path}: {e}")
        mtime = 0
    key = f"{real_path}_{width}_{mtime}"
    return hashlib.sha256(key.encode('utf-8')).hexdigest()

CACHE_LOCK = threading.Lock()
PIL_CACHE = OrderedDict()
QT_CACHE = OrderedDict()

def get_full_size_image(img_path):
    cache_key = uniq_file_id(img_path)
    with CACHE_LOCK:
        if cache_key in PIL_CACHE:
            PIL_CACHE.move_to_end(cache_key)
            return PIL_CACHE[cache_key]
    try:
        full_image = Image.open(img_path)
        with CACHE_LOCK:
            PIL_CACHE[cache_key] = full_image
            if len(PIL_CACHE) > CACHE_SIZE:
                PIL_CACHE.popitem(last=False)
        return full_image
    except Exception as e:
        log_error(f"Error loading image {img_path}: {e}")
        return None

def get_or_make_pil_by_key(cache_key, img_path, thumbnail_max_size):
    thumbnail_size_str = str(thumbnail_max_size)
    thumbnail_cache_subdir = os.path.join(THUMBNAIL_CACHE_ROOT, thumbnail_size_str)
    os.makedirs(thumbnail_cache_subdir, exist_ok=True)
    cached_thumbnail_path = os.path.join(thumbnail_cache_subdir, f"{cache_key}.png")
    pil_image_thumbnail = None
    if os.path.exists(cached_thumbnail_path):
        try:
            pil_image_thumbnail = Image.open(cached_thumbnail_path)
        except:
            pass
    if pil_image_thumbnail is None:
        try:
            pil_image_thumbnail = resize_image(get_full_size_image(img_path), thumbnail_max_size, thumbnail_max_size)
            tmp_path = os.path.join(os.path.dirname(cached_thumbnail_path), "tmp-" + os.path.basename(cached_thumbnail_path))
            pil_image_thumbnail.save(tmp_path)
            os.replace(tmp_path, cached_thumbnail_path)
        except Exception as e:
            log_error(f"Error creating thumbnail for {img_path}: {e}")
    return pil_image_thumbnail

def pil_to_qpixmap(pil_image):
    if pil_image is None:
        return QPixmap()
    if pil_image.mode not in ("RGB", "RGBA"):
        pil_image = pil_image.convert("RGBA")
    if pil_image.mode == "RGB":
        data = pil_image.tobytes("raw", "RGB")
        qimage = QImage(data, pil_image.width, pil_image.height, 3 * pil_image.width, QImage.Format_RGB888)
    else:
        data = pil_image.tobytes("raw", "RGBA")
        qimage = QImage(data, pil_image.width, pil_image.height, 4 * pil_image.width, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimage.copy())

def get_or_make_qt_by_key(cache_key, img_path, thumbnail_max_size):
    with CACHE_LOCK:
        if cache_key in QT_CACHE:
            QT_CACHE.move_to_end(cache_key)
            return QT_CACHE[cache_key]
    pil_image = get_or_make_pil_by_key(cache_key, img_path, thumbnail_max_size)
    qt_pixmap = pil_to_qpixmap(pil_image)
    with CACHE_LOCK:
        QT_CACHE[cache_key] = qt_pixmap
        if len(QT_CACHE) > CACHE_SIZE:
            QT_CACHE.popitem(last=False)
    return qt_pixmap


# --- async thumbnail loader ---

class ThumbnailLoader(QObject):
    thumbnail_ready = Signal(str, QPixmap)

    def __init__(self, max_workers=4):
        super().__init__()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.thumbnail_ready.connect(self._update_button, Qt.QueuedConnection)
        self.buttons = {}

    def _load_async(self, cache_key, img_path, width, button):
        self.buttons[cache_key] = button
        self.executor.submit(self._generate_thumbnail, cache_key, img_path, width)

    def _generate_thumbnail(self, cache_key, img_path, width):
        try:
            pixmap = get_or_make_qt_by_key(cache_key, img_path, width)
            self.thumbnail_ready.emit(cache_key, pixmap)
        except Exception as e:
            log_error(f"Error generating thumbnail for {img_path}: {e}")

    def _update_button(self, cache_key, pixmap):
        if cache_key in self.buttons:
            btn = self.buttons[cache_key]
            btn.set_image(pixmap)

    def load_thumbnail_for_button(self, btn, img_path, width, border):
        cache_key = uniq_file_id(img_path, width)
        btn.cache_key = cache_key
        btn.img_path = img_path
        thumb_w, thumb_h = get_thumbnail_dimensions(img_path, width)
        btn.setFixedSize(thumb_w + 2 * border, thumb_h + 2 * border)
        with CACHE_LOCK:
            if cache_key in QT_CACHE:
                QT_CACHE.move_to_end(cache_key)
                btn.set_image(QT_CACHE[cache_key])
            else:
                self._load_async(cache_key, img_path, width, btn)

    def shutdown(self):
        self.buttons.clear()
        try:
            self.thumbnail_ready.disconnect(self._update_button)
        except TypeError:
            pass
        self.executor.shutdown(wait=False)


# --- dialog ---

def fallback_show_error(title, message):
    QMessageBox.critical(None, title, message)

def custom_message_dialog(parent, title, message, font=None):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    x = parent.x() + parent.width() // 2 - 200
    y = parent.y() + parent.height() // 2 - 100
    dialog.setGeometry(x, y, 400, 300)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)
    text_widget = QTextEdit()
    text_widget.setReadOnly(True)
    text_widget.setPlainText(message)
    if font:
        text_widget.setFont(font)
    layout.addWidget(text_widget)
    button_layout = QHBoxLayout()
    button_layout.addStretch()
    ok_button = QPushButton("OK")
    ok_button.clicked.connect(dialog.accept)
    ok_button.setFixedWidth(80)
    button_layout.addWidget(ok_button)
    layout.addLayout(button_layout)
    ok_button.setFocus()
    dialog.exec()


# --- wallpaper setting ---

def set_wallpaper(image_path, error_callback=fallback_show_error):
    if platform.system() != "Linux":
        error_callback("Unsupported OS", f"Wallpaper setting not supported on {platform.system()}.")
        return False
    try:
        abs_path = os.path.abspath(image_path)
        file_uri = f"file://{abs_path}"
        desktop_env = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
        if not desktop_env and os.environ.get('DESKTOP_SESSION'):
            desktop_env = os.environ.get('DESKTOP_SESSION').lower()
        success = False
        if any(de in desktop_env for de in ['gnome', 'unity', 'pantheon', 'budgie']):
            subprocess.run(["gsettings", "set", "org.gnome.desktop.background", "picture-uri", file_uri])
            subprocess.run(["gsettings", "set", "org.gnome.desktop.background", "picture-uri-dark", file_uri])
            success = True
        elif 'kde' in desktop_env:
            script = f"""
            var allDesktops = desktops();
            for (var i=0; i < allDesktops.length; i++) {{
                d = allDesktops[i];
                d.wallpaperPlugin = "org.kde.image";
                d.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
                d.writeConfig("Image", "{abs_path}");
            }}
            """
            subprocess.run(["qdbus", "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", script])
            success = True
        elif 'xfce' in desktop_env:
            try:
                props = subprocess.check_output(['xfconf-query', '-c', 'xfce4-desktop', '-p', '/backdrop', '-l']).decode('utf-8')
                monitors = set([p.split('/')[2] for p in props.splitlines() if p.endswith('last-image')])
                for monitor in monitors:
                    monitor_props = [p for p in props.splitlines() if f'/backdrop/screen0/{monitor}/' in p and p.endswith('last-image')]
                    for prop in monitor_props:
                        subprocess.run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop, "-s", abs_path])
                success = True
            except:
                subprocess.run(["xfconf-query", "-c", "xfce4-desktop", "-p", "/backdrop/screen0/monitor0/workspace0/last-image", "-s", abs_path])
                success = True
        elif 'cinnamon' in desktop_env:
            subprocess.run(["gsettings", "set", "org.cinnamon.desktop.background", "picture-uri", file_uri])
            success = True
        elif 'mate' in desktop_env:
            subprocess.run(["gsettings", "set", "org.mate.background", "picture-filename", abs_path])
            success = True
        elif 'lxqt' in desktop_env or 'lxde' in desktop_env:
            subprocess.run(["pcmanfm-qt", f"--set-wallpaper={abs_path}"])
            subprocess.run(["pcmanfm", f"--set-wallpaper={abs_path}"])
            success = True
        elif any(de in desktop_env for de in ['i3', 'sway']):
            subprocess.run(["feh", "--bg-fill", abs_path])
            success = True
        elif not success:
            methods = [
                ["feh", "--bg-fill", abs_path],
                ["nitrogen", "--set-scaled", abs_path],
                ["gsettings", "set", "org.gnome.desktop.background", "picture-uri", file_uri]
            ]
            for method in methods:
                result = subprocess.run(method, capture_output=True)
                if result.returncode == 0:
                    success = True
                    break
        if success:
            return True
        else:
            error_callback("Desktop Environment Not Detected",
                           f"Couldn't detect your desktop environment ({desktop_env}). Try installing 'feh'.")
            return False
    except Exception as e:
        error_callback("Wallpaper Error", f"Failed to set wallpaper: {e}")
        return False


# --- helpers ---

def unique_name(original_path, category):
    _, ext = os.path.splitext(original_path)
    timestamp_str = datetime.now().strftime('%Y-%m-%d-%H-%M-%S-%f')
    random_raw_part = secrets.token_urlsafe(18)
    sanitized_random_part = random_raw_part.replace('/', '_').replace('+', '-')
    return f"{timestamp_str}_{category}_{sanitized_random_part}{ext}"

def is_image_file_name(file_name):
    return file_name.lower().endswith(SUPPORTED_IMAGE_EXTENSIONS)

def is_image_file(file_path):
    return os.path.isfile(file_path) and is_image_file_name(os.path.basename(file_path))

def list_image_files(directory_path):
    if not os.path.isdir(directory_path):
        return []
    full_paths = [os.path.join(directory_path, f) for f in os.listdir(directory_path)]
    result = [p for p in full_paths if is_image_file(p)]
    result.sort()
    result.reverse()
    return result

def get_parent_directory(path):
    return os.path.dirname(path)

def list_subdirectories(parent_directory_path):
    if not os.path.isdir(parent_directory_path):
        return []
    subdirs = []
    for item_name in os.listdir(parent_directory_path):
        item_path = os.path.join(parent_directory_path, item_name)
        if os.path.isdir(item_path):
            subdirs.append(item_path)
    subdirs.sort()
    return subdirs

def list_relevant_files(dir_path):
    file_list = list_image_files(dir_path)
    file_list.extend(list_image_files(get_parent_directory(dir_path)))
    for subdir in list_subdirectories(dir_path):
        file_list.extend(list_image_files(subdir))
    return file_list


# --- watch directory ---

watch_for_changes = True

class DirectoryEventHandler(QObject, FileSystemEventHandler):
    directory_changed = Signal()

    def __init__(self, directory, on_change_callback):
        QObject.__init__(self)
        FileSystemEventHandler.__init__(self)
        self.directory = directory
        self.directory_changed.connect(on_change_callback)

    def on_any_event(self, event):
        if isinstance(event, (FileOpenedEvent, FileClosedNoWriteEvent)):
            return
        if watch_for_changes:
            self.directory_changed.emit()


class DirectoryWatcher():
    def __init__(self, on_change_callback):
        self._on_change_callback = on_change_callback
        self.observer = None

    def start_watching(self, directory):
        self.event_handler = DirectoryEventHandler(directory, self._on_change_callback)
        self.observer = Observer()
        self.observer.daemon = True
        self.observer.schedule(self.event_handler, directory, recursive=False)
        self.observer.start()

    def stop_watching(self):
        if self.observer is not None:
            self.observer.stop()
            self.observer.join()
            self.observer = None

    def change_dir(self, directory):
        self.stop_watching()
        self.start_watching(directory)


# --- predictive preloading of thumbnails ---

class BackgroundWorker:
    def background(self):
        while self.keep_running:
            old_size = self.current_size
            old_directory = self.current_dir
            to_do_list = list_relevant_files(old_directory)
            for path_name in to_do_list:
                if not self.keep_running:
                    return
                self.barrier()
                if self.keep_running and (old_size == self.current_size) and (old_directory == self.current_dir):
                    self.path_name_queue.put(path_name)
                else:
                    break
            while self.keep_running and (old_size == self.current_size) and (old_directory == self.current_dir):
                time.sleep(2)

    def __init__(self, path, width):
        self.keep_running = True
        self.current_size = width
        self.current_dir = path
        self.path_name_queue = queue.Queue()
        self.worker = threading.Thread(target=self.background)
        self.block = threading.Event()
        self.worker.daemon = True
        self.worker.start()
        self.pause()

    def pause(self):
        self.block.clear()

    def resume(self):
        self.block.set()

    def barrier(self):
        self.block.wait()

    def run(self, dir_path, size):
        self.pause()
        self.current_size = size
        self.current_dir = dir_path
        self.resume()

    def stop(self):
        self.keep_running = False
        self.resume()


# --- Together.ai generation ---

def good_dimensions(delta=0.05):
    app = QApplication.instance()
    if app is None:
        return 1664, 960  # sensible default
    screen = app.primaryScreen()
    screen_width = screen.size().width()
    screen_height = screen.size().height()
    ratio = screen_width / screen_height
    best_h = 20
    best_w = best_h * math.ceil(ratio)
    for w in range(8, 46):
        for h in range(8, 46):
            r = w / h
            if not r < ratio:
                if not ratio + delta < r:
                    best_w = w
                    best_h = h
    return best_w * 32, best_h * 32

def generate_image(prompt, model, width=None, height=None, error_callback=fallback_show_error):
    if width is None or height is None:
        width, height = good_dimensions()
    client = Together(api_key=TOGETHER_API_KEY)
    log_action(f"Generating: prompt={prompt}, model={model}, size={width}x{height}")
    try:
        response = client.images.generate(prompt=prompt, model=model, width=width, height=height)
        return response.data[0].url
    except Exception as e:
        error_callback("API Error", f"Failed to generate image: {e}")
        return None

def download_image(url, file_name, prompt, error_callback=fallback_show_error):
    key = prompt
    prompt_dir = hashlib.sha256(key.encode('utf-8')).hexdigest()
    save_path = os.path.join(DOWNLOAD_DIR, prompt_dir, file_name)
    tmp_save_path = save_path + "-tmp"
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        dir_name = os.path.dirname(save_path)
        os.makedirs(dir_name, exist_ok=True)
        prompt_file = os.path.join(dir_name, "prompt.txt")
        try:
            with open(prompt_file, 'w') as f:
                f.write(prompt)
        except IOError as e:
            log_error(f"Error writing prompt: {e}")
        with open(tmp_save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_save_path, save_path)
    except Exception as e:
        try:
            os.remove(tmp_save_path)
            os.remove(save_path)
        except:
            pass
        error_callback("Download Error", f"Failed to download image: {e}")
        return None

    try:
        link_path = os.path.join(DOWNLOAD_DIR, file_name)
        if os.path.lexists(link_path):
            os.remove(link_path)
        os.symlink(save_path, link_path)
    except Exception as e:
        error_callback("File system error", f"Failed to link image: {e}")

    try:
        link_path = os.path.join(IMAGE_DIR, file_name)
        if os.path.lexists(link_path):
            os.remove(link_path)
        os.symlink(save_path, link_path)
        return link_path
    except Exception as e:
        error_callback("File system error", f"Failed to link image: {e}")
        return None


# --- widgets ---

def get_font(widget):
    while widget.parent() is not None:
        widget = widget.parent()
    if hasattr(widget, 'main_font'):
        return widget.main_font
    return QFont("Sans", 10)


class ThumbnailButton(QPushButton):
    def __init__(self, parent=None, item_border_width=6):
        super().__init__(parent)
        self.img_path = None
        self.item_border_width = item_border_width
        self.cache_key = None
        self.qt_image = None
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet(f"padding: 0px; margin: 0px; border: {self.item_border_width}px solid transparent;")

    def set_image(self, pixmap):
        self.qt_image = pixmap
        self.setIcon(QIcon(pixmap))
        icon_size = QSize(self.width() - 2 * self.item_border_width,
                          self.height() - 2 * self.item_border_width)
        self.setIconSize(icon_size)


class DirectoryThumbnailGrid:
    def __init__(self, parent_widget, directory_path="",
                 static_button_config_callback=None, dynamic_button_config_callback=None):
        self._parent_widget = parent_widget
        self._directory_path = directory_path
        self._static_button_config_callback = static_button_config_callback
        self._dynamic_button_config_callback = dynamic_button_config_callback
        self._widget_cache = OrderedDict()
        self._cache_size = 1000
        self._active_widgets = {}
        self._files = []
        self.thumbnail_loader = ThumbnailLoader()

    def set_directory_path(self, path):
        self._directory_path = path
        return self.update_file_list()

    def _recreate_thumbnail_loader(self):
        if hasattr(self, 'thumbnail_loader'):
            self.thumbnail_loader.shutdown()
        self.thumbnail_loader = ThumbnailLoader()

    def get_button(self, img_path, width, border_width):
        cache_key = uniq_file_id(img_path, width)
        btn = self._widget_cache.get(cache_key, None)
        if btn is None:
            btn = ThumbnailButton(self._parent_widget, border_width)
            self.thumbnail_loader.load_thumbnail_for_button(btn, img_path, width, border_width)
            self._widget_cache[cache_key] = btn
            if self._static_button_config_callback:
                self._static_button_config_callback(btn, img_path)
        else:
            self._widget_cache.move_to_end(cache_key)
        while len(self._widget_cache) > self._cache_size:
            self._widget_cache.popitem(last=False)
        return btn

    def refresh_buttons(self):
        if self._dynamic_button_config_callback:
            for img_path, btn in self._active_widgets.items():
                self._dynamic_button_config_callback(btn, img_path)

    def update_file_list(self):
        old_files = self._files
        self._files = list_image_files(self._directory_path)
        return self._files != old_files


ITEM_BORDER_WIDTH = 3
SPACING = 3
PADDING = 6

def num_columns(frame_width, item_width, item_border_width, lr_padding, spacing):
    if frame_width <= 0:
        return 1
    item_total = item_width + 2 * item_border_width + spacing
    available = frame_width - 2 * lr_padding
    if available <= 0:
        return 1
    return max(1, available // item_total)

def interleaved_range(start, middle, end):
    result = [middle]
    max_dist = max(middle - start, (end - 1) - middle)
    for offset in range(1, max_dist + 1):
        low = middle - offset
        high = middle + offset
        if low >= start:
            result.append(low)
        if high < end:
            result.append(high)
    return result


class ThumbnailArea(QScrollArea):
    def __init__(self, master=None, directory_path="", item_width=None, item_border_width=None,
                 static_button_config_callback=None, dynamic_button_config_callback=None, **kwargs):
        super().__init__(master)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._viewport_widget = QWidget()
        self.setViewport(self._viewport_widget)
        self._item_width = item_width
        self._item_border_width = item_border_width
        self._spacing = SPACING
        self.grid = DirectoryThumbnailGrid(
            self._viewport_widget,
            directory_path=directory_path,
            static_button_config_callback=static_button_config_callback,
            dynamic_button_config_callback=dynamic_button_config_callback
        )
        self.refresh_job = None
        self._center_idx = None
        self._rows = 0
        self._row_heights = []
        self._row_y_positions = []
        self._cols = 1
        self._buffer_rows = 6
        self._scroll_position = 0
        self.set_size_and_path(item_width, directory_path)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setMouseTracking(True)
        self.viewport().installEventFilter(self)

    def scrollbar_pos(self):
        return self.verticalScrollBar().value()

    def _vp_height(self):
        return self.viewport().height()

    def _vp_width(self):
        return self.viewport().width()

    def set_size_and_path(self, width, path):
        self._item_width = width
        self.grid.set_directory_path(path)
        self._recalculate_grid()
        self.move_scrollbar(self._scroll_pos_from_index(self._center_idx))
        self._render_viewport()

    def _calculate_columns(self, viewport_width):
        return num_columns(viewport_width, self._item_width, self._item_border_width, PADDING, self._spacing)

    def _calculate_row_heights(self, cols):
        self._row_heights = []
        self._row_y_positions = [PADDING]
        total_files = len(self.grid._files)
        self._rows = (total_files + cols - 1) // cols
        for row_idx in range(self._rows):
            start_idx = row_idx * cols
            end_idx = min(start_idx + cols, total_files)
            max_thumb_height = 0
            for file_idx in range(start_idx, end_idx):
                img_path = self.grid._files[file_idx]
                thumb_w, thumb_h = get_thumbnail_dimensions(img_path, self._item_width)
                button_h = thumb_h + 2 * self._item_border_width
                max_thumb_height = max(max_thumb_height, button_h)
            self._row_heights.append(max_thumb_height)
            next_y = self._row_y_positions[-1] + max_thumb_height + self._spacing
            self._row_y_positions.append(next_y)
        return self._row_y_positions[-1] - self._spacing + PADDING if self._row_heights else 2 * PADDING

    def _find_visible_rows(self, scroll_pos, viewport_height):
        if not self._row_heights or not self._row_y_positions:
            return 0, 0, 0
        visible_start_row = 0
        for i in range(len(self._row_heights)):
            if self._row_y_positions[i] <= scroll_pos:
                visible_start_row = i
        scroll_bottom = scroll_pos + viewport_height
        visible_end_row = visible_start_row
        for i in range(visible_start_row, len(self._row_heights)):
            if self._row_y_positions[i] <= scroll_bottom:
                visible_end_row = i
        visible_middle_row = visible_start_row + ((visible_end_row - visible_start_row) // 2)
        visible_start_row = max(0, visible_start_row - self._buffer_rows)
        visible_end_row = max(0, min(self._rows - 1, visible_end_row + self._buffer_rows))
        return visible_start_row, visible_middle_row, visible_end_row

    def _layout_visible_rows(self, cols, scroll_offset):
        for btn in self.grid._active_widgets.values():
            if btn is not None:
                btn.hide()
        self.grid._active_widgets = {}
        visible_start_row, visible_middle_row, visible_end_row = self._find_visible_rows(scroll_offset, self._vp_height())
        start_idx = visible_start_row * cols
        end_idx = min((1 + visible_end_row) * cols, len(self.grid._files))
        col_width = self._item_width + 2 * self._item_border_width
        total_item_width = cols * col_width
        total_base_spacing = (cols - 1) * self._spacing
        total_base_padding = 2 * PADDING
        used_width = total_item_width + total_base_spacing + total_base_padding
        extra_space = self._vp_width() - used_width
        num_gaps = cols + 1
        gap_extra = extra_space / num_gaps if num_gaps > 0 else 0
        effective_padding = PADDING + gap_extra
        effective_spacing = self._spacing + gap_extra
        for idx in interleaved_range(start_idx, visible_middle_row * cols, end_idx):
            if idx >= len(self.grid._files):
                break
            img_path = self.grid._files[idx]
            btn = self.grid.get_button(img_path, self._item_width, self._item_border_width)
            if self.grid._dynamic_button_config_callback:
                self.grid._dynamic_button_config_callback(btn, img_path)
            self.grid._active_widgets[img_path] = btn
            row = idx // cols
            col = idx % cols
            button_width = btn.width()
            x_centering_offset = (col_width - button_width) / 2
            x = effective_padding + col * (col_width + effective_spacing) + x_centering_offset
            row_height = self._row_heights[row]
            button_height = btn.height()
            y_centering_offset = (row_height - button_height) / 2
            y = self._row_y_positions[row] - scroll_offset + y_centering_offset
            btn.setGeometry(int(x), int(y), btn.width(), btn.height())
            btn.show()

    def _index_from_scroll_pos(self, scroll_pos):
        if not self._row_heights or not self.grid._files:
            return None
        center_y = scroll_pos + self._vp_height() / 2
        center_row = 0
        for i in range(len(self._row_heights)):
            if self._row_y_positions[i] < center_y:
                center_row = i
        file_idx = center_row * self._cols
        if file_idx >= len(self.grid._files):
            file_idx = len(self.grid._files) - 1
        return file_idx

    def _scroll_pos_from_index(self, file_idx):
        if file_idx is None or not self._row_heights:
            return 0
        max_scroll = self.verticalScrollBar().maximum()
        row = file_idx // self._cols
        if row >= len(self._row_y_positions):
            return max_scroll
        row_y = self._row_y_positions[row]
        row_height = self._row_heights[row] if row < len(self._row_heights) else 0
        target_scroll = row_y + row_height / 2 - self._vp_height() / 2
        return max(0, min(target_scroll, max_scroll))

    def move_scrollbar(self, value):
        self._scroll_position = value
        scrollbar = self.verticalScrollBar()
        blocked = scrollbar.blockSignals(True)
        try:
            scrollbar.setValue(int(value))
            max_scroll = max(0, self._height - self._vp_height())
            scrollbar.setRange(0, int(max_scroll))
            scrollbar.setPageStep(self._vp_height())
            scrollbar.setSingleStep(self._vp_height() // 10)
        finally:
            scrollbar.blockSignals(blocked)

    def _recalculate_grid(self):
        self._cols = self._calculate_columns(self._vp_width())
        self._height = self._calculate_row_heights(self._cols)
        self._rows = len(self._row_heights)

    def _render_viewport(self):
        for btn in self.grid._active_widgets.values():
            if btn is not None:
                btn.hide()
        self.grid._active_widgets = {}
        self._cols = self._calculate_columns(self._vp_width())
        if not self.grid._files:
            self._rows = 0
            self._row_heights = []
            self._row_y_positions = []
            self.verticalScrollBar().setRange(0, 0)
            return
        self._layout_visible_rows(self._cols, self._scroll_position)

    def _on_scroll_debounce_helper(self):
        self._render_viewport()
        self._center_idx = self._index_from_scroll_pos(self._scroll_position)

    def _on_scroll(self, value):
        self._scroll_position = value
        if self.refresh_job:
            self.refresh_job.stop()
        self.refresh_job = QTimer()
        self.refresh_job.setSingleShot(True)
        self.refresh_job.timeout.connect(self._on_scroll_debounce_helper)
        self.refresh_job.start(50)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recalculate_grid()
        self.move_scrollbar(self._scroll_pos_from_index(self._center_idx))
        self._render_viewport()

    def keyPressEvent(self, event):
        key = event.key()
        sb = self.verticalScrollBar()
        if key == Qt.Key_Up:
            sb.setValue(sb.value() - sb.singleStep())
        elif key == Qt.Key_Down:
            sb.setValue(sb.value() + sb.singleStep())
        elif key == Qt.Key_Left:
            sb.setValue(sb.value() - 5 * sb.singleStep())
        elif key == Qt.Key_Right:
            sb.setValue(sb.value() + 5 * sb.singleStep())
        elif key == Qt.Key_PageUp:
            sb.setValue(sb.value() - sb.pageStep())
        elif key == Qt.Key_PageDown:
            sb.setValue(sb.value() + sb.pageStep())
        elif key == Qt.Key_Home:
            sb.setValue(sb.minimum())
        elif key == Qt.Key_End:
            sb.setValue(sb.maximum())
        else:
            super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if obj is self.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            self.setFocus()
        return super().eventFilter(obj, event)

    def get_button(self, img_path, width, pre_cache=True):
        return self.grid.get_button(img_path, width, self._item_border_width)

    def redraw(self):
        self._recalculate_grid()
        self._render_viewport()

    def refresh(self):
        self._render_viewport()

    def regrid(self):
        self.grid.update_file_list()
        self.redraw()

    def shutdown(self):
        if hasattr(self.grid, 'thumbnail_loader'):
            self.grid.thumbnail_loader.shutdown()



# --- image viewer ---

class ImageViewer(QMainWindow):
    def __init__(self, master, image_path, start_fullscreen=False):
        super().__init__(master)
        self.master = master
        self.image_path = image_path
        self.file_name = os.path.basename(image_path)
        self.is_fullscreen = start_fullscreen
        self.original_image = get_full_size_image(self.image_path)
        self.display_image = None

        self.setWindowTitle(self.file_name)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        w, h = self.original_image.size
        x, y = w, h
        while x < 1000 and y < 600:
            x *= 1.1
            y *= 1.1
        while 1300 < x or 900 < y:
            x /= 1.1
            y /= 1.1

        canvas_width = int(x)
        canvas_height = int(y)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setStyleSheet("background-color: black;")

        self.canvas = QLabel()
        self.canvas.setAlignment(Qt.AlignCenter)
        self.canvas.setStyleSheet("background-color: black;")
        self.scroll_area.setWidget(self.canvas)

        main_layout.addWidget(self.scroll_area, 1)

        self.zoom_factor = x / w
        self.fit_to_window = True
        self.pan_start_x = 0
        self.pan_start_y = 0
        self.panning = False

        self.resize(canvas_width, canvas_height)
        self._update_image()

        self.scroll_area.setMouseTracking(True)
        self.canvas.setMouseTracking(True)
        self.canvas.mousePressEvent = self._on_mouse_down
        self.canvas.mouseMoveEvent = self._on_mouse_drag
        self.canvas.mouseReleaseEvent = self._on_mouse_up
        self.canvas.wheelEvent = self._on_mouse_wheel

        if start_fullscreen:
            self.showFullScreen()
        else:
            self.show()
        self.activateWindow()
        self.canvas.setFocus()

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            self.showFullScreen()
        else:
            self.showNormal()
        QTimer.singleShot(100, self._update_image)

    def _update_image(self):
        if not self.original_image:
            return
        canvas_width = self.scroll_area.viewport().width()
        canvas_height = self.scroll_area.viewport().height()
        if canvas_width <= 1:
            canvas_width = 800
        if canvas_height <= 1:
            canvas_height = 600
        orig_width, orig_height = self.original_image.size
        if self.fit_to_window:
            scale = min(canvas_width / orig_width, canvas_height / orig_height)
            self.zoom_factor = scale
            new_width = int(orig_width * scale)
            new_height = int(orig_height * scale)
        else:
            new_width = int(orig_width * self.zoom_factor)
            new_height = int(orig_height * self.zoom_factor)
        self.display_image = self.original_image.resize((new_width, new_height), Image.LANCZOS)
        pixmap = pil_to_qpixmap(self.display_image)
        self.canvas.setPixmap(pixmap)
        self.canvas.resize(pixmap.size())

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Plus or key == Qt.Key_Equal:
            self._zoom_in()
        elif key == Qt.Key_Minus or key == Qt.Key_Underscore:
            self._zoom_out()
        elif key == Qt.Key_0:
            self.fit_to_window = True
            self._update_image()
        elif key == Qt.Key_F11 or key == Qt.Key_F:
            self.toggle_fullscreen()
        elif key == Qt.Key_Escape:
            self._close()
        else:
            super().keyPressEvent(event)

    def _on_mouse_down(self, event):
        if event.button() == Qt.LeftButton:
            self.panning = True
            self.pan_start_x = event.globalX()
            self.pan_start_y = event.globalY()
            self.canvas.setCursor(Qt.ClosedHandCursor)

    def _on_mouse_drag(self, event):
        if not self.panning:
            return
        dx = self.pan_start_x - event.globalX()
        dy = self.pan_start_y - event.globalY()
        h_bar = self.scroll_area.horizontalScrollBar()
        v_bar = self.scroll_area.verticalScrollBar()
        h_bar.setValue(h_bar.value() + dx)
        v_bar.setValue(v_bar.value() + dy)
        self.pan_start_x = event.globalX()
        self.pan_start_y = event.globalY()

    def _on_mouse_up(self, event):
        if event.button() == Qt.LeftButton:
            self.panning = False
            self.canvas.setCursor(Qt.ArrowCursor)

    def _on_mouse_wheel(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self._zoom_in(event.position().x(), event.position().y())
        else:
            self._zoom_out(event.position().x(), event.position().y())

    def resizeEvent(self, event):
        if self.fit_to_window:
            self._update_image()
        super().resizeEvent(event)

    def _zoom_in(self, x=None, y=None):
        self.fit_to_window = False
        self.zoom_factor *= 1.25
        if x is not None and y is not None:
            x_fraction = x / self.display_image.width
            y_fraction = y / self.display_image.height
        self._update_image()
        if x is not None and y is not None:
            h_bar = self.scroll_area.horizontalScrollBar()
            v_bar = self.scroll_area.verticalScrollBar()
            new_x = x_fraction * self.display_image.width
            new_y = y_fraction * self.display_image.height
            cw = self.scroll_area.viewport().width()
            ch = self.scroll_area.viewport().height()
            h_bar.setValue(int(max(0, new_x - cw / 2)))
            v_bar.setValue(int(max(0, new_y - ch / 2)))

    def _zoom_out(self, x=None, y=None):
        self.fit_to_window = False
        self.zoom_factor /= 1.25
        if self.zoom_factor < 0.1:
            self.fit_to_window = True
            self._update_image()
            return
        if x is not None and y is not None:
            x_fraction = x / self.display_image.width
            y_fraction = y / self.display_image.height
        self._update_image()
        if x is not None and y is not None:
            h_bar = self.scroll_area.horizontalScrollBar()
            v_bar = self.scroll_area.verticalScrollBar()
            new_x = x_fraction * self.display_image.width
            new_y = y_fraction * self.display_image.height
            cw = self.scroll_area.viewport().width()
            ch = self.scroll_area.viewport().height()
            h_bar.setValue(int(max(0, new_x - cw / 2)))
            v_bar.setValue(int(max(0, new_y - ch / 2)))

    def _close(self):
        if self.is_fullscreen:
            self.toggle_fullscreen()
        self.close()

    def closeEvent(self, event):
        event.accept()


# --- long menu ---

class LongMenu(QDialog):
    def __init__(self, master, default_option, other_options, font=None, x_pos=None, y_pos=None,
                 pos="bottom", n_lines=20):
        super().__init__(master, Qt.Popup | Qt.FramelessWindowHint)
        self.result = default_option
        self._options = other_options
        self._main_font = font if font else get_font(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        max_length = max((len(line) for line in self._options), default=10) + 5

        self._listbox = QListWidget()
        self._listbox.setFont(self._main_font)
        fm = QFontMetrics(self._main_font)
        char_width = fm.averageCharWidth()
        self._listbox.setMinimumWidth(char_width * max_length)
        self._listbox.setMinimumHeight(20 + fm.height() * min(n_lines, len(self._options)))

        for option_name in other_options:
            self._listbox.addItem(option_name)
        if self._options:
            self._listbox.setCurrentRow(0)

        layout.addWidget(self._listbox)

        self._listbox.itemClicked.connect(self._exit_ok)
        self._listbox.itemDoubleClicked.connect(self._exit_ok)

        self.adjustSize()

        if x_pos is None or y_pos is None:
            master_pos = master.mapToGlobal(QPoint(0, 0))
            x_pos = master_pos.x()
            y_pos = master_pos.y() + master.height()

        if pos == "top":
            y_pos = y_pos - self.height()
        elif pos == "center":
            y_pos = y_pos - int(0.5 * self.height())
        if y_pos < 0:
            y_pos = 0

        screen = QApplication.primaryScreen().availableGeometry()
        if x_pos + self.width() > screen.width():
            x_pos = screen.width() - self.width() - 5
        if y_pos + self.height() > screen.height():
            y_pos = screen.height() - self.height() - 5

        self.move(int(x_pos), int(y_pos))
        self._listbox.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            self._exit_ok()
        elif event.key() == Qt.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(event)

    def _exit_ok(self, item=None):
        current_item = self._listbox.currentItem()
        if current_item:
            self.result = current_item.text()
        else:
            row = self._listbox.currentRow()
            if row >= 0 and row < len(self._options):
                self.result = self._options[row]
        self.accept()

    def _cancel(self):
        self.result = None
        self.reject()


# --- breadcrumb navigator ---

class BreadCrumNavigator(QWidget):
    def __init__(self, master, on_navigate_callback=None, font=None,
                 long_press_threshold_ms=400, drag_threshold_pixels=5):
        super().__init__(master)
        self._on_navigate_callback = on_navigate_callback
        self._current_path = ""
        self._LONG_PRESS_THRESHOLD_MS = long_press_threshold_ms
        self._DRAG_THRESHOLD_PIXELS = drag_threshold_pixels
        self._long_press_timer = None
        self._press_start_time = 0
        self._press_x = 0
        self._press_y = 0
        self._active_button = None
        self._elide_max_width = 180  # max pixel width for any segment button
        self._segment_data = []  # list of (full_path, original_name)

        if font is None:
            self.font = get_font(self)
        else:
            self.font = font

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setMinimumHeight(QFontMetrics(self.font).height() + 12)

    def set_path(self, path):
        if not os.path.isdir(path):
            return
        self._current_path = os.path.normpath(path)
        self._segment_data = []
        p = self._current_path
        while len(p) > 1:
            parent = os.path.dirname(p)
            name = os.path.basename(p)
            if name == '':
                name = os.path.sep
            self._segment_data.insert(0, (p, name))
            p = parent
        self._segment_data.insert(0, (p, "//"))
        self._reflow()

    def resizeEvent(self, event):
        self._reflow()
        super().resizeEvent(event)

    def _reflow(self):
        if not self._segment_data:
            return
        avail_width = self.width()
        fm = QFontMetrics(self.font)
        if avail_width <= 0:
            return

        btn_pad = 10  # approx QPushButton text + padding
        sep_width = fm.horizontalAdvance("/")

        # Step 1: measure total width of all original (un-elided) segment names
        def total_width_of(names):
            total = 0
            for i, n in enumerate(names):
                total += fm.horizontalAdvance(n) + btn_pad
                if i > 0:
                    total += sep_width
            return total

        full_names = [name for path, name in self._segment_data]
        total_needed = total_width_of(full_names)

        # Step 2: if everything fits with no truncation — no elision, no dropping
        if total_needed <= avail_width:
            self._rebuild_buttons(list(self._segment_data), [], False)
            return

        # Step 3: overflow — iteratively shrink the widest segment just enough to fit
        budgets = {i: None for i in range(len(self._segment_data))}

        def total_width_of_budgeted():
            total = 0
            for i, (_, name) in enumerate(self._segment_data):
                b = budgets[i]
                if b is not None:
                    w = b
                else:
                    w = fm.horizontalAdvance(name)
                total += w + btn_pad
                if i > 0:
                    total += sep_width
            return total

        while total_width_of_budgeted() > avail_width:
            current_extents = []
            for i, (_, name) in enumerate(self._segment_data):
                b = budgets[i]
                if b is not None:
                    w = b
                else:
                    w = fm.horizontalAdvance(name)
                current_extents.append((w, i))
            current_extents.sort(reverse=True)
            widest_idx = current_extents[0][1]
            widest_current = current_extents[0][0]

            if widest_current <= 20:
                break

            new_budget = max(20, widest_current - 10)
            budgets[widest_idx] = new_budget

        elided = []
        for i, (path, name) in enumerate(self._segment_data):
            b = budgets[i]
            if b is not None:
                display = fm.elidedText(name, Qt.ElideMiddle, b)
            else:
                display = name
            elided.append((path, display))

        # Step 4: drop parents from left until it fits (keep at least last 1)
        def total_width_of_displays(displays):
            total = 0
            for i, d in enumerate(displays):
                total += fm.horizontalAdvance(d) + btn_pad
                if i > 0:
                    total += sep_width
            return total

        dropped = []
        remaining = list(elided)
        while len(remaining) > 1 and total_width_of_displays([d for _, d in remaining]) > avail_width:
            dropped.append(remaining.pop(0))

        show_dots = len(dropped) > 0
        self._rebuild_buttons(remaining, dropped, show_dots)

    def _rebuild_buttons(self, segments, dropped, show_dots):
        # Clear layout
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # "…" button for dropped ancestors
        if show_dots and dropped:
            dots_btn = QPushButton("…")
            dots_btn.setFlat(True)
            dots_btn.setFont(self.font)
            dots_btn.setStyleSheet("padding: 0px; margin: 0px;")
            # path = path of deepest dropped ancestor's parent (so menu shows them)
            dots_btn.path = self._segment_data[0][0]  # root path
            dots_btn._dropped = dropped
            dots_btn.setToolTip("Dropped parent directories")
            dots_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            dots_btn.pressed.connect(lambda: self._on_dots_press(dots_btn))
            self._layout.addWidget(dots_btn)
            dots_btn.show()

        for i, (path, display) in enumerate(segments):
            if i > 0 or show_dots:
                sep = QLabel("/")
                sep.setFont(self.font)
                sep.setContentsMargins(0, 0, 0, 0)
                sep.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                self._layout.addWidget(sep)
                sep.show()

            btn = QPushButton(display)
            btn.setFlat(True)
            btn.setFont(self.font)
            btn.setStyleSheet("padding: 0px; margin: 0px;")
            btn.path = path
            btn.setToolTip(path)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.pressed.connect(lambda b=btn: self._on_button_press(b))
            btn.released.connect(lambda b=btn: self._on_button_release(b))
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda pos, b=btn: self._on_button_press_menu(b))

            if i == 0 and not show_dots:
                # Root ("//") button: single press shows subdirectory menu directly
                btn.pressed.disconnect()
                btn.pressed.connect(lambda b=btn: self._on_button_press_menu(b))

            self._layout.addWidget(btn)
            btn.show()

        self._layout.addStretch(1)

    def _on_dots_press(self, btn):
        """Show menu of dropped ancestors when '…' is pressed."""
        dropped_names = [os.path.basename(p) or os.path.sep for p, _ in btn._dropped]
        btn_pos = btn.mapToGlobal(QPoint(0, btn.height()))
        menu = LongMenu(
            btn,
            default_option=None,
            other_options=dropped_names,
            font=self.font,
            x_pos=btn_pos.x(),
            y_pos=btn_pos.y(),
            n_lines=15
        )
        menu.exec()
        selected_name = menu.result
        if selected_name:
            # Find the path for the selected name
            for path, name in btn._dropped:
                if os.path.basename(path) == selected_name or \
                   (selected_name == os.path.sep and path == self._segment_data[0][0]):
                    self._trigger_navigate(path)
                    return
            # Fallback: navigate to root
            self._trigger_navigate(self._segment_data[0][0])

    def _trigger_navigate(self, path):
        if self._on_navigate_callback:
            self._on_navigate_callback(path)

    def _on_button_press_menu(self, button):
        self._show_subdirectory_menu(button)

    def _on_button_press(self, button):
        self._press_start_time = time.time()
        self._press_x = QCursor.pos().x()
        self._press_y = QCursor.pos().y()
        self._active_button = button
        self._long_press_timer = QTimer()
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.timeout.connect(lambda: self._on_long_press_timeout(button))
        self._long_press_timer.start(self._LONG_PRESS_THRESHOLD_MS)

    def _on_button_release(self, button):
        if self._long_press_timer and self._long_press_timer.isActive():
            self._long_press_timer.stop()
        if self._active_button:
            current_pos = QCursor.pos()
            dist = math.sqrt((current_pos.x() - self._press_x)**2 + (current_pos.y() - self._press_y)**2)
            if dist < self._DRAG_THRESHOLD_PIXELS:
                if (time.time() - self._press_start_time) * 1000 < self._LONG_PRESS_THRESHOLD_MS:
                    path = self._active_button.path
                    if path and self._on_navigate_callback:
                        self._on_navigate_callback(path)
            self._active_button = None

    def _on_long_press_timeout(self, button):
        if self._active_button is button:
            self._show_subdirectory_menu(button)
            self._long_press_timer = None

    def _show_subdirectory_menu(self, button):
        path = button.path
        selected_path = path

        all_entries = os.listdir(path)
        subdirs = []
        hidden_subdirs = []
        for entry in all_entries:
            full_path = os.path.join(path, entry)
            if os.path.isdir(full_path):
                if entry.startswith('.'):
                    hidden_subdirs.append(entry)
                else:
                    subdirs.append(entry)
        subdirs.sort()
        hidden_subdirs.sort()
        sorted_subdirs = subdirs + hidden_subdirs

        if sorted_subdirs:
            button_pos = button.mapToGlobal(QPoint(0, button.height()))
            menu_x = button_pos.x()
            menu_y = button_pos.y()
            selector_dialog = LongMenu(
                button,
                None,
                sorted_subdirs,
                font=self.font,
                x_pos=menu_x,
                y_pos=menu_y,
                n_lines=15
            )
            selector_dialog.exec()
            selected_name = selector_dialog.result
            if selected_name:
                selected_path = os.path.join(path, selected_name)

        self._trigger_navigate(selected_path)


# --- image picker dialog ---

class ImagePickerDialog(QDialog):
    def __init__(self, master, thumbnail_max_size, image_dir):
        super().__init__(master)
        self.master = master
        self._thumbnail_max_size = thumbnail_max_size
        self._current_image_dir = image_dir
        self.selected_files = []
        self._initialized = False
        self.setWindowTitle("Add Images to Collection")
        self.resize(800, 600)
        self._save_settings()
        self._create_widgets()
        self.background_worker = BackgroundWorker(self._current_image_dir, self._thumbnail_max_size)
        self._start_cache_timer()
        self.watcher = DirectoryWatcher(self._on_directory_changed)
        self.watcher.start_watching(self._current_image_dir)

    def showEvent(self, event):
        if not self._initialized:
            self._initialized = True
            self._restore_geometry()
            self.breadcrumb_nav.set_path(self._current_image_dir)
        super().showEvent(event)

    def _on_directory_changed(self):
        self._gallery_grid.regrid()

    def _save_settings(self):
        if hasattr(self.master, 'app_settings'):
            self.master.app_settings['image_picker_dialog_geometry'] = self.saveGeometry().toBase64().data().decode()
            self.master.app_settings['image_picker_last_directory'] = self._current_image_dir
            self.master.save_app_settings()

    def _restore_geometry(self):
        geometry_str = None
        if hasattr(self.master, 'app_settings'):
            geometry_str = self.master.app_settings.get('image_picker_dialog_geometry')
        restored = False
        if geometry_str:
            try:
                restored = self.restoreGeometry(QByteArray.fromBase64(geometry_str.encode()))
            except Exception:
                restored = False
        if restored:
            screen = QApplication.primaryScreen().availableGeometry()
            if not screen.intersects(self.frameGeometry()):
                restored = False
        if not restored:
            self.resize(800, 600)
            x = self.master.x() + (self.master.width() - self.width()) // 2
            y = self.master.y() + (self.master.height() - self.height()) // 2
            self.move(x, y)

    def _start_cache_timer(self):
        self._cache_timer = QTimer(self)
        self._cache_timer.timeout.connect(self._cache_widget)
        self._cache_timer.start(50)

    def _cache_widget(self):
        try:
            path_name = self.background_worker.path_name_queue.get_nowait()
            get_or_make_pil_by_key(uniq_file_id(path_name, self._thumbnail_max_size), path_name, self._thumbnail_max_size)
        except queue.Empty:
            pass

    def _create_widgets(self):
        layout = QVBoxLayout(self)

        # Top bar: breadcrumb navigation
        top_frame = QWidget()
        top_layout = QHBoxLayout(top_frame)
        top_layout.setContentsMargins(0, 0, 0, 0)

        self.breadcrumb_nav = BreadCrumNavigator(
            top_frame,
            on_navigate_callback=self._browse_directory,
            font=self.master.main_font
        )
        top_layout.addWidget(self.breadcrumb_nav, 1)

        layout.addWidget(top_frame)

        # Gallery
        self._gallery_grid = ThumbnailArea(
            self,
            directory_path=self._current_image_dir,
            item_width=self._thumbnail_max_size,
            item_border_width=ITEM_BORDER_WIDTH,
            dynamic_button_config_callback=self._configure_picker_button
        )
        layout.addWidget(self._gallery_grid, 1)

        # Bottom bar: action buttons
        bottom_frame = QWidget()
        bottom_layout = QHBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        clone_btn = QPushButton("Clone")
        clone_btn.setFont(self.master.main_font)
        clone_btn.clicked.connect(self._on_clone)
        bottom_layout.addWidget(clone_btn)

        sel_all_btn = QPushButton("Sel. All")
        sel_all_btn.setFont(self.master.main_font)
        sel_all_btn.clicked.connect(self._on_select_all)
        bottom_layout.addWidget(sel_all_btn)

        desel_btn = QPushButton("Des.")
        desel_btn.setFont(self.master.main_font)
        desel_btn.clicked.connect(self._on_deselect)
        bottom_layout.addWidget(desel_btn)

        add_btn = QPushButton("Add Selected")
        add_btn.setFont(self.master.main_font)
        add_btn.clicked.connect(self._on_add_selected)
        bottom_layout.addWidget(add_btn)

        close_btn = QPushButton("Close")
        close_btn.setFont(self.master.main_font)
        close_btn.clicked.connect(self._on_close)
        bottom_layout.addWidget(close_btn)

        layout.addWidget(bottom_frame)

    def _configure_picker_button(self, btn, img_path):
        border_color = "blue" if img_path in self.selected_files else "transparent"
        btn.setStyleSheet(f"padding: 0px; margin: 0px; border: {ITEM_BORDER_WIDTH}px solid {border_color};")
        if not getattr(btn, '_picker_signals_connected', False):
            btn._picker_signals_connected = True
            btn.clicked.connect(lambda checked, p=img_path: self._toggle_selection(p))
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda pos, p=img_path: self._show_full_screen(p))

    def _toggle_selection(self, img_path):
        if img_path in self.selected_files:
            self.selected_files.remove(img_path)
        else:
            self.selected_files.append(img_path)
        self.refresh_selection()

    def _show_full_screen(self, img_path):
        try:
            ImageViewer(self, img_path, start_fullscreen=True)
        except Exception as e:
            custom_message_dialog(self, "Error", f"Could not open image: {e}", font=self.master.main_font)

    def _browse_directory(self, path):
        if not os.path.isdir(path):
            return
        self._current_image_dir = path
        self.watcher.change_dir(path)
        self.background_worker.run(path, self._thumbnail_max_size)
        self.breadcrumb_nav.set_path(path)
        self._gallery_grid.set_size_and_path(self._thumbnail_max_size, self._current_image_dir)

    def _on_clone(self):
        self.master._manually_add_images(self._current_image_dir)

    def _on_select_all(self):
        all_files = list_image_files(self._current_image_dir)
        for f in all_files:
            if f not in self.selected_files:
                self.selected_files.append(f)
        self.refresh_selection()

    def _on_deselect(self):
        self.selected_files = []
        self.refresh_selection()

    def refresh_selection(self):
        self._gallery_grid.redraw()

    def _on_add_selected(self):
        self.master.add_multiple_images_as_symlinks(self.selected_files)
        self.selected_files = []
        self._gallery_grid.redraw()

    def _on_close(self):
        self._save_settings()
        self.background_worker.stop()
        self.watcher.stop_watching()
        self._cache_timer.stop()
        self._gallery_grid.shutdown()
        self.accept()

    def closeEvent(self, event):
        self._on_close()
        event.accept()


# --- main app ---

class WallpaperApp(QMainWindow):
    generation_finished = Signal()
    image_ready = Signal(str)
    error_occurred = Signal(str, str)

    def _preview_resize_debounce(self):
        if self.current_image_path:
            self._display_image(self.current_image_path)

    def eventFilter(self, obj, event):
        if obj is self._preview_frame and event.type() == QEvent.Type.Resize and self.current_image_path:
            w = event.size().width()
            h = event.size().height()
            if w > 1 and h > 1:
                if self._preview_resize_timer:
                    self._preview_resize_timer.stop()
                self._preview_resize_timer = QTimer()
                self._preview_resize_timer.setSingleShot(True)
                self._preview_resize_timer.timeout.connect(self._preview_resize_debounce)
                self._preview_resize_timer.start(100)
        return super().eventFilter(obj, event)

    def __init__(self):
        super().__init__()
        self.generation_finished.connect(self._reset_generate_button)
        self.image_ready.connect(self._load_images_and_select)
        self.error_occurred.connect(lambda t, m: custom_message_dialog(self, t, m, font=self.main_font))
        self.setWindowTitle("kubux wallpaper generator")
        self.setMinimumSize(0, 0)
        self.current_image_path = None
        self._preview_resize_timer = None
        self.max_history_items = 125
        self.gallery_current_selection = None
        self.gallery_thumbnail_max_size = DEFAULT_THUMBNAIL_DIM
        self._open_pickers = 0
        self._open_picker_dialogs = []
        self._initial_load_done = False
        self._load_prompt_history()
        self.load_app_settings()
        self.gallery_thumbnail_max_size = int(DEFAULT_THUMBNAIL_DIM * self.current_thumbnail_scale)
        font_name, font_size = get_linux_system_ui_font_info()
        self.base_font_size = font_size
        self.main_font = QFont(font_name, int(self.base_font_size * self.current_font_scale))
        if self.initial_geometry:
            self.restoreGeometry(QByteArray.fromBase64(self.initial_geometry.encode()))
        else:
            self.resize(1200, 800)
        self._create_widgets()
        self.show()

    def _load_prompt_history(self):
        try:
            if os.path.exists(PROMPT_HISTORY_FILE):
                with open(PROMPT_HISTORY_FILE, 'r') as f:
                    self.prompt_history = json.load(f)
            else:
                self.prompt_history = []
        except:
            self.prompt_history = []

    def _save_prompt_history(self):
        try:
            with open(PROMPT_HISTORY_FILE, 'w') as f:
                json.dump(self.prompt_history, f, indent=4)
        except Exception as e:
            log_error(f"Error saving prompt history: {e}")

    def load_app_settings(self):
        try:
            if os.path.exists(APP_SETTINGS_FILE):
                with open(APP_SETTINGS_FILE, 'r') as f:
                    self.app_settings = json.load(f)
            else:
                self.app_settings = {}
        except:
            self.app_settings = {}
        self.current_font_scale = self.app_settings.get("ui_scale", 1.0)
        self.initial_geometry = self.app_settings.get("window_geometry", None)
        self.current_thumbnail_scale = self.app_settings.get("thumbnail_scale", 1.0)
        self.horizontal_paned_position = self.app_settings.get("horizontal_paned_position", 600)
        self.vertical_paned_position = self.app_settings.get("vertical_paned_position", 400)
        self.model_string = self.app_settings.get("model_string", "black-forest-labs/FLUX.1.1-pro")
        self.image_dir = self.app_settings.get("image_dir", IMAGE_DIR)
        self.gallery_scroll_index = self.app_settings.get("gallery_grid_scroll_index", None)

    def save_app_settings(self):
        try:
            if not hasattr(self, 'app_settings'):
                self.app_settings = {}
            self.app_settings["ui_scale"] = self.current_font_scale
            self.app_settings["window_geometry"] = self.saveGeometry().toBase64().data().decode()
            self.app_settings["thumbnail_scale"] = self.current_thumbnail_scale
            self.app_settings["model_string"] = self.model_string
            self.app_settings["image_dir"] = self.image_dir
            self.app_settings["image_picker_last_directory"] = self._image_dir()
            if hasattr(self, 'gallery_grid'):
                self.app_settings["gallery_grid_scroll_index"] = self.gallery_grid._center_idx
            if hasattr(self, 'horizontal_splitter'):
                sizes = self.horizontal_splitter.sizes()
                if len(sizes) >= 2:
                    self.app_settings["horizontal_paned_position"] = sizes[0]
            if hasattr(self, 'vertical_splitter'):
                sizes = self.vertical_splitter.sizes()
                if len(sizes) >= 2:
                    self.app_settings["vertical_paned_position"] = sizes[0]
            with open(APP_SETTINGS_FILE, 'w') as f:
                json.dump(self.app_settings, f, indent=4)
        except Exception as e:
            log_error(f"Error saving app settings: {e}")

    def _preview_is_gone(self):
        if not hasattr(self, 'horizontal_splitter') or not hasattr(self, 'vertical_splitter'):
            return False
        h_sizes = self.horizontal_splitter.sizes()
        v_sizes = self.vertical_splitter.sizes()
        return (len(h_sizes) > 0 and h_sizes[0] <= 5) or (len(v_sizes) > 0 and v_sizes[0] <= 5)

    def _toggle_commands_frame(self):
        if self._preview_is_gone():
            self.gen_commands_frame.hide()
            self.sel_commands_frame.show()
            self.setWindowTitle("kubux wallpaper picker")
        else:
            self.sel_commands_frame.hide()
            self.gen_commands_frame.show()
            self.setWindowTitle("kubux wallpaper generator")

    def _create_widgets(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 0)
        main_layout.setSpacing(5)

        # Main content area — goes ABOVE the command bar (added first = top)
        self.horizontal_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.horizontal_splitter, 1)

        left_pane = QWidget()
        left_pane.setMinimumSize(0, 0)
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.vertical_splitter = QSplitter(Qt.Vertical)
        left_layout.addWidget(self.vertical_splitter)

        # Preview frame (top of left pane)
        self._preview_frame = QFrame()
        self._preview_frame.installEventFilter(self)
        preview_layout = QVBoxLayout(self._preview_frame)
        preview_layout.setContentsMargins(5, 5, 5, 5)
        preview_label = QLabel("Preview")
        preview_label.setFont(self.main_font)
        preview_layout.addWidget(preview_label)
        self.preview_image_label = QLabel()
        self.preview_image_label.setAlignment(Qt.AlignCenter)
        self.preview_image_label.setMinimumSize(0, 0)
        self.preview_image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        preview_layout.addWidget(self.preview_image_label, 1)
        self.vertical_splitter.addWidget(self._preview_frame)

        # Prompt frame (bottom of left pane)
        if ai_features_enabled:
            prompt_frame = QFrame()
            prompt_layout = QVBoxLayout(prompt_frame)
            prompt_layout.setContentsMargins(5, 5, 5, 5)
            prompt_label = QLabel("Generate New Wallpaper")
            prompt_label.setFont(self.main_font)
            prompt_layout.addWidget(prompt_label)
            self.prompt_text = QTextEdit()
            self.prompt_text.setFont(self.main_font)
            self.prompt_text.setMinimumSize(0, 0)
            prompt_layout.addWidget(self.prompt_text, 1)
            self.vertical_splitter.addWidget(prompt_frame)

        self.horizontal_splitter.addWidget(left_pane)

        # Thumbnail gallery (right pane)
        gallery_frame = QFrame()
        gallery_frame.setMinimumSize(0, 0)
        gallery_layout = QVBoxLayout(gallery_frame)
        gallery_layout.setContentsMargins(5, 5, 5, 5)
        gallery_label = QLabel("Your Wallpaper Collection")
        gallery_label.setFont(self.main_font)
        gallery_layout.addWidget(gallery_label)
        self.gallery_grid = ThumbnailArea(
            gallery_frame,
            directory_path=IMAGE_DIR,
            item_width=self.gallery_thumbnail_max_size,
            item_border_width=ITEM_BORDER_WIDTH,
            dynamic_button_config_callback=self._gallery_configure_button
        )
        gallery_layout.addWidget(self.gallery_grid, 1)
        self.horizontal_splitter.addWidget(gallery_frame)
        self.horizontal_splitter.setStretchFactor(0, 1)
        QTimer.singleShot(0, self.gallery_grid.setFocus)
        self.horizontal_splitter.setStretchFactor(1, 0)

        # Bottom command frames — added AFTER the splitter so they're at the bottom
        self.bottom_frame = QWidget()
        bottom_layout = QVBoxLayout(self.bottom_frame)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        self.gen_commands_frame = QWidget()
        gen_layout = QHBoxLayout(self.gen_commands_frame)
        gen_layout.setContentsMargins(0, 0, 0, 0)

        self.generate_button = QPushButton("Generate")
        self.generate_button.setFont(self.main_font)
        self.generate_button.clicked.connect(self._on_generate_button_click)
        gen_layout.addWidget(self.generate_button)

        self.history_button = QPushButton("History")
        self.history_button.setFont(self.main_font)
        self.history_button.clicked.connect(self._show_prompt_history)
        gen_layout.addWidget(self.history_button)

        if not ai_features_enabled:
            self.generate_button.setEnabled(False)
            self.history_button.setEnabled(False)
            self.enable_ai_button = QPushButton("Enable AI Generation")
            self.enable_ai_button.setFont(self.main_font)
            self.enable_ai_button.clicked.connect(self.show_api_setup_instructions)
            gen_layout.addWidget(self.enable_ai_button)

        ui_label = QLabel("UI:")
        ui_label.setFont(self.main_font)
        gen_layout.addWidget(ui_label)
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(50, 250)
        self.scale_slider.setValue(int(self.current_font_scale * 100))
        self.scale_slider.valueChanged.connect(self._update_ui_scale)
        self.scale_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        gen_layout.addWidget(self.scale_slider)

        thumb_label = QLabel("Thumbs:")
        thumb_label.setFont(self.main_font)
        gen_layout.addWidget(thumb_label)
        self.thumbnail_scale_slider = QSlider(Qt.Horizontal)
        self.thumbnail_scale_slider.setRange(50, 250)
        self.thumbnail_scale_slider.setValue(int(self.current_thumbnail_scale * 100))
        self.thumbnail_scale_slider.valueChanged.connect(self._gallery_update_thumbnail_scale_callback)
        self.thumbnail_scale_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        gen_layout.addWidget(self.thumbnail_scale_slider)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setFont(self.main_font)
        self.delete_button.clicked.connect(self._delete_selected_image)
        gen_layout.addWidget(self.delete_button)

        self.add_button = QPushButton("Add")
        self.add_button.setFont(self.main_font)
        self.add_button.clicked.connect(lambda checked: self._manually_add_images())
        gen_layout.addWidget(self.add_button)

        self.set_wallpaper_button = QPushButton("Set Wallpaper")
        self.set_wallpaper_button.setFont(self.main_font)
        self.set_wallpaper_button.clicked.connect(self._set_current_as_wallpaper)
        gen_layout.addWidget(self.set_wallpaper_button)

        bottom_layout.addWidget(self.gen_commands_frame)

        self.sel_commands_frame = QWidget()
        sel_layout = QHBoxLayout(self.sel_commands_frame)
        sel_layout.setContentsMargins(0, 0, 0, 0)
        sel_ui_label = QLabel("UI:")
        sel_ui_label.setFont(self.main_font)
        sel_layout.addWidget(sel_ui_label)
        self.sel_scale_slider = QSlider(Qt.Horizontal)
        self.sel_scale_slider.setRange(50, 250)
        self.sel_scale_slider.setValue(int(self.current_font_scale * 100))
        self.sel_scale_slider.valueChanged.connect(self._update_ui_scale)
        self.sel_scale_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        sel_layout.addWidget(self.sel_scale_slider)
        sel_thumb_label = QLabel("Thumbs:")
        sel_thumb_label.setFont(self.main_font)
        sel_layout.addWidget(sel_thumb_label)
        self.sel_thumbnail_scale_slider = QSlider(Qt.Horizontal)
        self.sel_thumbnail_scale_slider.setRange(50, 250)
        self.sel_thumbnail_scale_slider.setValue(int(self.current_thumbnail_scale * 100))
        self.sel_thumbnail_scale_slider.valueChanged.connect(self._gallery_update_thumbnail_scale_callback)
        self.sel_thumbnail_scale_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        sel_layout.addWidget(self.sel_thumbnail_scale_slider)
        sel_add_btn = QPushButton("Add")
        sel_add_btn.setFont(self.main_font)
        sel_add_btn.clicked.connect(lambda checked: self._manually_add_images())
        sel_layout.addWidget(sel_add_btn)
        self.sel_commands_frame.hide()
        bottom_layout.addWidget(self.sel_commands_frame)

        main_layout.addWidget(self.bottom_frame)

        # Set initial splitter positions
        self.horizontal_splitter.setSizes([self.horizontal_paned_position, 400])
        self.vertical_splitter.setSizes([self.vertical_paned_position, 150])

        self.horizontal_splitter.splitterMoved.connect(self._toggle_commands_frame)
        self.vertical_splitter.splitterMoved.connect(self._toggle_commands_frame)

        self._toggle_commands_frame()

        self._gallery_watcher = DirectoryWatcher(self._on_image_dir_changed)
        self._gallery_watcher.start_watching(IMAGE_DIR)

        QTimer.singleShot(0, self._restore_gallery_scroll)

    def _restore_gallery_scroll(self):
        if self.gallery_scroll_index is None:
            return
        self.gallery_grid._center_idx = self.gallery_scroll_index
        self.gallery_grid.move_scrollbar(self.gallery_grid._scroll_pos_from_index(self.gallery_scroll_index))
        self.gallery_grid._render_viewport()

    def _on_image_dir_changed(self):
        self._load_images()

    def _gallery_configure_button(self, btn, img_path):
        if not getattr(btn, '_gallery_signals_connected', False):
            btn._gallery_signals_connected = True
            btn.clicked.connect(lambda checked, p=img_path: self._gallery_on_thumbnail_click(p))
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda pos, p=img_path: self._gallery_on_thumbnail_click_right(p))

    def show_api_setup_instructions(self):
        instructions = """
        To enable AI image generation:
        1. Create a Together.ai account at https://together.ai
        2. Generate an API key from your account settings
        3. Create a .env file in your home directory with:
        TOGETHER_API_KEY=your_api_key_here
        Then restart the application.
        """
        custom_message_dialog(self, "Enable AI Image Generation", instructions, font=self.main_font)

    def _update_ui_scale(self, value):
        scale = value / 100.0
        self.current_font_scale = scale
        self.scale_slider.setValue(value)
        self.sel_scale_slider.setValue(value)
        new_size = int(self.base_font_size * scale)
        self.main_font.setPointSize(new_size)
        self._update_all_fonts()

    def _update_all_fonts(self):
        def update_widget_fonts(widget, font):
            if hasattr(widget, 'setFont'):
                try:
                    widget.setFont(font)
                except:
                    pass
            for child in widget.findChildren(QWidget):
                if hasattr(child, 'setFont'):
                    try:
                        child.setFont(font)
                    except:
                        pass
        update_widget_fonts(self, self.main_font)

    def _display_image(self, image_path):
        try:
            full_img = get_full_size_image(image_path)
            if full_img is None:
                import time
                time.sleep(0.15)
                full_img = get_full_size_image(image_path)
            if full_img is None:
                return
            fw = self.preview_image_label.width()
            fh = self.preview_image_label.height()
            if fw <= 1 or fh <= 1:
                return
            resized_img = resize_image(full_img, fw, fh)
            pixmap = pil_to_qpixmap(resized_img)
            self.preview_image_label.setPixmap(pixmap)
            self.current_image_path = image_path
        except Exception as e:
            log_error(f"Error displaying image: {e}")
            self.current_image_path = None

    def broadcast_contents_change(self):
        if hasattr(self, 'gallery_grid'):
            self.gallery_grid.regrid()

    def _load_images(self):
        self.gallery_grid.regrid()

    def _gallery_update_thumbnail_scale_callback(self, value):
        scale = value / 100.0
        self.thumbnail_scale_slider.setValue(value)
        self.sel_thumbnail_scale_slider.setValue(value)
        self.current_thumbnail_scale = scale
        self.gallery_thumbnail_max_size = int(DEFAULT_THUMBNAIL_DIM * scale)
        self.gallery_grid.set_size_and_path(self.gallery_thumbnail_max_size, IMAGE_DIR)

    def _gallery_on_thumbnail_click(self, image_path):
        self.gallery_current_selection = image_path
        self.current_image_path = image_path
        self._display_image(image_path)
        if self._preview_is_gone():
            self._set_current_as_wallpaper()

    def _gallery_on_thumbnail_click_right(self, image_path):
        self._delete_image(image_path)

    def _add_prompt_to_history(self, prompt):
        if prompt in self.prompt_history:
            self.prompt_history.remove(prompt)
        self.prompt_history.insert(0, prompt)
        self.prompt_history = self.prompt_history[:self.max_history_items]
        self._save_prompt_history()

    def _show_prompt_history(self):
        if not self.prompt_history:
            custom_message_dialog(self, "Prompt History", "No saved prompts found.", font=self.main_font)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Prompt History")
        dialog.resize(600, 400)
        layout = QVBoxLayout(dialog)
        listbox = QListWidget()
        listbox.setFont(self.main_font)
        for prompt in self.prompt_history:
            listbox.addItem(prompt)
        listbox.itemDoubleClicked.connect(lambda item: self._select_prompt_from_history(listbox, dialog))
        layout.addWidget(listbox, 1)
        btn_layout = QHBoxLayout()
        select_btn = QPushButton("Select")
        select_btn.setFont(self.main_font)
        select_btn.clicked.connect(lambda: self._select_prompt_from_history(listbox, dialog))
        btn_layout.addWidget(select_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(self.main_font)
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        dialog.exec()

    def _select_prompt_from_history(self, listbox, dialog):
        items = listbox.selectedItems()
        if items:
            self.prompt_text.setPlainText(items[0].text())
            dialog.accept()

    def _on_generate_button_click(self):
        prompt = self.prompt_text.toPlainText().strip()
        if not prompt:
            custom_message_dialog(self, "Input Error", "Please enter a prompt.", font=self.main_font)
            return
        self._add_prompt_to_history(prompt)
        self.generate_button.setText("Generating...")
        self.generate_button.setEnabled(False)
        # Compute dimensions on main thread — QScreen not safe from worker threads
        width, height = good_dimensions()
        threading.Thread(target=self._run_generation_task, args=(prompt, width, height), daemon=True).start()

    def _run_generation_task(self, prompt, width, height):
        def error_dialog(title, message):
            self.error_occurred.emit(title, message)
        image_url = generate_image(prompt, model=self.model_string, width=width, height=height, error_callback=error_dialog)
        if image_url:
            file_name = unique_name("dummy.png", "generated")
            save_path = download_image(image_url, file_name, prompt, error_callback=error_dialog)
            if save_path:
                self.image_ready.emit(save_path)
        self.generation_finished.emit()

    def _reset_generate_button(self):
        self.generate_button.setText("Generate")
        self.generate_button.setEnabled(True)

    def _load_images_and_select(self, path_to_select):
        self._load_images()
        self.gallery_grid.move_scrollbar(self.gallery_grid.verticalScrollBar().maximum())
        self._gallery_on_thumbnail_click(path_to_select)

    def add_multiple_images_as_symlinks(self, original_paths):
        if not original_paths:
            return
        for file_path in original_paths:
            try:
                if not os.path.exists(file_path):
                    continue
                file_name = unique_name(file_path, "manual")
                dest = os.path.join(IMAGE_DIR, file_name)
                is_already_linked = False
                for existing_linked_file in os.listdir(IMAGE_DIR):
                    full_existing_link_path = os.path.join(IMAGE_DIR, existing_linked_file)
                    if os.path.islink(full_existing_link_path) and os.path.realpath(full_existing_link_path) == os.path.realpath(file_path):
                        is_already_linked = True
                        break
                if is_already_linked:
                    continue
                if os.path.lexists(dest):
                    os.remove(dest)
                os.symlink(file_path, dest)
            except Exception as e:
                log_error(f"Failed to add image: {e}")
        self._load_images()

    def _manually_add_images(self, directory=None):
        if directory is None:
            directory = self._image_dir()
        dialog = ImagePickerDialog(self, self.gallery_thumbnail_max_size, directory)
        dialog.setParent(None)
        dialog.setWindowFlags(Qt.Window)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.finished.connect(self._picker_finished)
        if self._open_pickers == 0:
            self.setEnabled(False)
        self._open_pickers += 1
        self._open_picker_dialogs.append(dialog)
        dialog.show()

    def _picker_finished(self):
        dialog = self.sender()
        if dialog in self._open_picker_dialogs:
            self._open_picker_dialogs.remove(dialog)
        self._open_pickers -= 1
        if self._open_pickers == 0:
            self.setEnabled(True)

    def _image_dir(self):
        if hasattr(self, 'app_settings'):
            saved_dir = self.app_settings.get('image_picker_last_directory')
            if saved_dir and os.path.isdir(saved_dir):
                return saved_dir
        default_dir = os.path.expanduser(os.path.join('~', 'Pictures'))
        if not os.path.isdir(default_dir):
            default_dir = os.path.expanduser('~')
        return default_dir

    def _delete_image(self, path_to_delete):
        if path_to_delete and os.path.exists(path_to_delete):
            try:
                os.remove(path_to_delete)
                self.preview_image_label.clear()
                self.current_image_path = None
                self.gallery_current_selection = None
                self._load_images()
            except Exception as e:
                custom_message_dialog(self, "Deletion Error", f"Failed to delete: {e}", font=self.main_font)

    def _delete_selected_image(self):
        self._delete_image(self.gallery_current_selection)

    def _set_current_as_wallpaper(self):
        if not self.current_image_path:
            custom_message_dialog(self, "Wallpaper Error", "No image selected.", font=self.main_font)
            return
        set_wallpaper(self.current_image_path)

    def closeEvent(self, event):
        for d in list(self._open_picker_dialogs):
            d.close()
        self._save_prompt_history()
        self.save_app_settings()
        if hasattr(self, '_gallery_watcher'):
            self._gallery_watcher.stop_watching()
        if hasattr(self, 'gallery_grid'):
            self.gallery_grid.shutdown()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("kubux-wallpaper-generator")
    app.setDesktopFileName("kubux-wallpaper-generator")
    window = WallpaperApp()
    sys.exit(app.exec())
