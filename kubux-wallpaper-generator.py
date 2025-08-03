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
import secrets
import queue
import threading
import subprocess
import time
import tkinter as tk
import tkinter.font as tkFont
from collections import OrderedDict
from datetime import datetime
from tkinter import TclError
from tkinter import messagebox
from tkinter import ttk

import requests
from PIL import Image, ImageTk
from dotenv import load_dotenv
from together import Together

# Load environment variables
load_dotenv()
# --- Configuration ---
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
ai_features_enabled = bool(TOGETHER_API_KEY)


SUPPORTED_IMAGE_EXTENSIONS = (
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tif', '.tiff', '.webp',
    '.ico', '.icns', '.avif', '.dds', '.msp', '.pcx', '.ppm',
    '.pbm', '.pgm', '.sgi', '.tga', '.xbm', '.xpm'
)
    
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


# --- probe font ---

def get_gtk_ui_font():
    """
    Queries the system's default UI font and size for GTK-based desktops
    using gsettings.
    """
    try:
        # Check if gsettings is available
        subprocess.run(["which", "gsettings"], check=True, capture_output=True)

        # Get the font name string from GNOME's desktop interface settings
        font_info_str = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "font-name"],
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip().strip("'") # Remove leading/trailing whitespace and single quotes

        # Example output: 'Noto Sans 10', 'Ubuntu 11', 'Cantarell 11'
        parts = font_info_str.rsplit(' ', 1) # Split only on the last space

        font_name = "Sans" # Default fallback
        font_size = 10     # Default fallback

        if len(parts) == 2 and parts[1].isdigit():
            font_name = parts[0]
            font_size = int(parts[1])
        else:
            # Handle cases like "Font Name" 10 or unexpected formats
            # Attempt to split assuming format "Font Name Size"
            try:
                # Common scenario: "Font Name X" where X is size
                # Sometimes font names have spaces (e.g., "Noto Sans CJK JP")
                # So finding the *last* space before digits is key.
                last_space_idx = font_info_str.rfind(' ')
                if last_space_idx != -1 and font_info_str[last_space_idx+1:].isdigit():
                    font_name = font_info_str[:last_space_idx]
                    font_size = int(font_info_str[last_space_idx+1:])
                else:
                    print(f"Warning: Unexpected gsettings font format: '{font_info_str}'")
            except Exception as e:
                print(f"Error parsing gsettings font: {e}")

        return font_name, font_size

    except subprocess.CalledProcessError:
        print("gsettings command not found or failed. Are you on a GTK-based desktop with dconf/gsettings installed?")
        return "Sans", 10 # Fallback for non-GTK or missing gsettings
    except Exception as e:
        print(f"An error occurred while getting GTK font settings: {e}")
        return "Sans", 10 # General fallback

def get_kde_ui_font():
    """
    Queries the system's default UI font and size for KDE Plasma desktops
    using kreadconfig5.
    """
    try:
        # Check if kreadconfig5 is available
        subprocess.run(["which", "kreadconfig5"], check=True, capture_output=True)

        # Get the font string from the kdeglobals file
        # This typically looks like "Font Name,points,weight,slant,underline,strikeout"
        font_string = subprocess.run(
            ["kreadconfig5", "--file", "kdeglobals", "--group", "General", "--key", "font", "--default", "Sans,10,-1,5,50,0,0,0,0,0"],
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()

        parts = font_string.split(',')
        if len(parts) >= 2:
            font_name = parts[0].strip()
            # Font size is in points. kreadconfig often gives it as an int directly.
            font_size = int(parts[1].strip())
            return font_name, font_size
        else:
            print(f"Warning: Unexpected KDE font format: '{font_string}'")
            return "Sans", 10 # Fallback

    except subprocess.CalledProcessError:
        print("kreadconfig5 command not found or failed. Are you on KDE Plasma?")
        return "Sans", 10 # Fallback for non-KDE or missing kreadconfig5
    except Exception as e:
        print(f"An error occurred while getting KDE font settings: {e}")
        return "Sans", 10 # General fallback

def get_linux_system_ui_font_info():
    """
    Attempts to detect the Linux desktop environment and return its
    configured default UI font family and size.
    Returns (font_family, font_size) or (None, None) if undetectable.
    """
    # Check for common desktop environment indicators
    desktop_session = os.environ.get("XDG_CURRENT_DESKTOP")
    if not desktop_session:
        desktop_session = os.environ.get("DESKTOP_SESSION")

    print(f"Detected desktop session: {desktop_session}")

    if desktop_session and ("GNOME" in desktop_session.upper() or
                            "CINNAMON" in desktop_session.upper() or
                            "XFCE" in desktop_session.upper() or
                            "MATE" in desktop_session.upper()):
        print("Attempting to get GTK font...")
        return get_gtk_ui_font()
    elif desktop_session and "KDE" in desktop_session.upper():
        print("Attempting to get KDE font...")
        return get_kde_ui_font()
    else:
        # Fallback for other desktops or if detection fails
        print("Could not reliably detect desktop environment. Trying common defaults or gsettings as fallback.")
        # Try gsettings anyway, as it's common even outside "full" GNOME
        font_name, font_size = get_gtk_ui_font()
        if font_name != "Sans" or font_size != 10: # If gsettings returned something more specific
            return font_name, font_size
        return "Sans", 10 # Final generic fallback

def get_linux_ui_font():
    font_name, font_size = get_linux_ui_font_info()
    return tkFont.Font(family=font_name, size=font_size)
    

# --- image stuff ---

def resize_image(image, target_width, target_height):
    original_width, original_height = image.size

    if target_width <= 0 or target_height <= 0:
        return image.copy() # Return a copy of the original or a small placeholder

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

def uniq_file_id(img_path, width=-1):
    try:
        mtime = os.path.getmtime(img_path)
    except FileNotFoundError:
        print(f"Error: Original image file not found for thumbnail generation: {img_path}")
        return None
    except Exception as e:
        print(f"Warning: Could not get modification time for {img_path}: {e}. Using a default value.")
        mtime = 0
    key = f"{img_path}_{width}_{mtime}"
    return hashlib.sha256(key.encode('utf-8')).hexdigest()

PIL_CACHE = OrderedDict()

def get_full_size_image(img_path):
    cache_key = uniq_file_id(img_path)
    if cache_key in PIL_CACHE:
        PIL_CACHE.move_to_end(cache_key)
        return PIL_CACHE[cache_key]
    try:
        full_image = Image.open(img_path)
        PIL_CACHE[cache_key] = full_image
        if len( PIL_CACHE ) > 2000:
            PIL_CACHE.popitem(last=False)
            assert len( PIL_CACHE ) == 2000
        return full_image
    except Exception as e:
        print(f"Error loading of for {img_path}: {e}")
        return None
        
def get_or_make_thumbnail(img_path, thumbnail_max_size):
    cache_key = uniq_file_id(img_path, thumbnail_max_size)

    if cache_key in PIL_CACHE:
        return PIL_CACHE[cache_key]

    thumbnail_size_str = str(thumbnail_max_size)
    thumbnail_cache_subdir = os.path.join(THUMBNAIL_CACHE_ROOT, thumbnail_size_str)
    os.makedirs(thumbnail_cache_subdir, exist_ok=True)

    cached_thumbnail_path = os.path.join(thumbnail_cache_subdir, f"{cache_key}.png")

    pil_image_thumbnail = None

    # try reading from on-disk cache
    if  os.path.exists(cached_thumbnail_path):
        try:
            pil_image_thumbnail = Image.open(cached_thumbnail_path)
            PIL_CACHE[cache_key] = pil_image_thumbnail
            return pil_image_thumbnail
        except Exception as e:
            print(f"Error loading thumbnail for {img_path}: {e}")

    # if we are here, caching was not successful
    try:
        pil_image_thumbnail = resize_image( get_full_size_image(img_path), thumbnail_max_size, thumbnail_max_size )
        pil_image_thumbnail.save(cached_thumbnail_path) 
        PIL_CACHE[cache_key] = pil_image_thumbnail
    except Exception as e:
        print(f"Error loading of / creating thumbnail for {img_path}: {e}")

    return pil_image_thumbnail

def make_tk_image( pil_image ):
    if pil_image.mode not in ("RGB", "RGBA", "L", "1"):
        pil_image = pil_image.convert("RGBA")
    return ImageTk.PhotoImage(pil_image)


# --- dialogue box ---
def fallback_show_error(title, message):
    messagebox.showerror(title, message)
    
def custom_message_dialog(parent, title, message, font=("Arial", 12)):
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)  # Set to be on top of the parent window
    
    # Calculate position to center the dialog on parent
    x = parent.winfo_rootx() + parent.winfo_width() // 2 - 200
    y = parent.winfo_rooty() + parent.winfo_height() // 2 - 100
    dialog.geometry(f"400x300+{x}+{y}")
    
    # Message area
    msg_frame = ttk.Frame(dialog, padding=20)
    msg_frame.pack(fill=tk.BOTH, expand=True)
    
    # Text widget with scrollbar for the message
    text_widget = tk.Text(msg_frame, wrap=tk.WORD, font=font, 
                          highlightthickness=0, borderwidth=0)
    scrollbar = ttk.Scrollbar(msg_frame, orient="vertical", 
                              command=text_widget.yview)
    text_widget.configure(yscrollcommand=scrollbar.set)
    
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    
    # Insert the message text
    text_widget.insert(tk.END, message)
    text_widget.configure(state="disabled")  # Make read-only
    
    # OK button
    button_frame = ttk.Frame(dialog, padding=10)
    button_frame.pack(fill=tk.X)
    ok_button = ttk.Button(button_frame, text="OK", 
                          command=dialog.destroy, width=10)
    ok_button.pack(side=tk.RIGHT, padx=5)
    
    # Center dialog on screen
    dialog.update_idletasks()
    dialog.grab_set()  # Modal: user must interact with this window
    
    # Set focus and wait for window to close
    ok_button.focus_set()
    dialog.wait_window()

    
# --- Together.ai Image Generation ---

def best_dimensions():
    root = tk.Tk()
    root.withdraw()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    ratio = screen_width / screen_height
    root.destroy()
    best_h = 20;
    best_w = best_h * math.ceil(ratio)
    for w in range(8,46):
        for h in range(8,46):
            r = w / h
            if not r < ratio:
                if not ( best_w / best_h ) < r:
                    best_w = w
                    best_h = h
    return best_w * 32, best_h * 32
                
def good_dimensions(delta=0.05):
    root = tk.Tk()
    root.withdraw()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    ratio = screen_width / screen_height
    root.destroy()
    best_h = 20;
    best_w = best_h * math.ceil(ratio)
    for w in range(8,46):
        for h in range(8,46):
            r = w / h
            if not r < ratio:
                if not ratio + delta < r:
                    best_w = w
                    best_h = h
    return best_w * 32, best_h * 32
                
ai_width, ai_height = good_dimensions()

# print(f"width = {ai_width}, height = {ai_height}")

def generate_image(prompt, model,
#                   width=1184, height=736, steps=28,
#                   width=1248, height=704, # almost 16 : 9
#                   width=1920, height=1080, # almost 16 : 9
                   width=ai_width, height=ai_height,
                   steps=28,
                   error_callback=fallback_show_error):
    client = Together(api_key=TOGETHER_API_KEY)
    try:
        response = client.images.generate(
            prompt=prompt,
            model=model,
            width=width,
            height=height,
            steps=steps
        )
        return response.data[0].url
    except Exception as e:
        message = f"Failed to download image: {e}"
        error_callback("API Error", message)
        return None

def download_image(url, file_name, prompt, error_callback=fallback_show_error):
    key = f"{prompt}"
    prompt_dir = hashlib.sha256(key.encode('utf-8')).hexdigest()
    save_path = os.path.join(DOWNLOAD_DIR,prompt_dir,file_name)
    tmp_save_path = save_path + "-tmp"
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status() 
        dir_name = os.path.dirname(save_path)
        os.makedirs(dir_name, exist_ok=True)
        prompt_file = os.path.join( dir_name, "prompt.txt")
        try:
            with open(prompt_file, 'w') as file:
                file.write(prompt)
        except IOError as e:
            print(f"Error writing prompt {prompt} to file: {e}")
        with open(tmp_save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
        os.replace(tmp_save_path, save_path)
    except Exception as e:
        try:
            os.remove(tmp_save_path)
            os.remove(save_path)
        except Exception: pass
        message = f"Failed to download image: {e}"
        error_callback("Download Error", message)
        return None
    try:
        link_path=os.path.join(IMAGE_DIR, file_name)
        os.symlink(save_path, link_path)
        return link_path
    except Exception as e:
        os.remove(link_path)
        message = f"Failed to link image: {e}"
        error_callback("File system error,", message)
        return None
    

# --- Wallpaper Setting Functions (Platform-Specific) ---

def set_wallpaper(image_path, error_callback=fallback_show_error):
    """
    Set the wallpaper on Linux systems with support for multiple desktop environments.
    
    Args:
        image_path: Path to the image file
        
    Returns:
        bool: True if wallpaper was successfully set, False otherwise
    """
    if platform.system() != "Linux":
        error_callback("Unsupported OS", f"Wallpaper setting not supported on {platform.system()}.")
        return False
        
    try:
        abs_path = os.path.abspath(image_path)
        file_uri = f"file://{abs_path}"
        
        # Detect desktop environment
        desktop_env = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
        if not desktop_env and os.environ.get('DESKTOP_SESSION'):
            desktop_env = os.environ.get('DESKTOP_SESSION').lower()
            
        success = False
        
        # GNOME, Unity, Pantheon, Budgie
        if any(de in desktop_env for de in ['gnome', 'unity', 'pantheon', 'budgie']):
            # Try GNOME 3 approach first (newer versions)
            os.system(f"gsettings set org.gnome.desktop.background picture-uri '{file_uri}'")
            # For GNOME 40+ with dark mode support
            os.system(f"gsettings set org.gnome.desktop.background picture-uri-dark '{file_uri}'")
            success = True
            
        # KDE Plasma
        elif 'kde' in desktop_env:
            # For KDE Plasma 5
            script = f"""
            var allDesktops = desktops();
            for (var i=0; i < allDesktops.length; i++) {{
                d = allDesktops[i];
                d.wallpaperPlugin = "org.kde.image";
                d.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
                d.writeConfig("Image", "{abs_path}");
            }}
            """
            os.system(f"qdbus org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript '{script}'")
            success = True
            
        # XFCE
        elif 'xfce' in desktop_env:
            # Get the current monitor
            try:
                import subprocess
                props = subprocess.check_output(['xfconf-query', '-c', 'xfce4-desktop', '-p', '/backdrop', '-l']).decode('utf-8')
                monitors = set([p.split('/')[2] for p in props.splitlines() if p.endswith('last-image')])
                
                for monitor in monitors:
                    # Find all properties for this monitor
                    monitor_props = [p for p in props.splitlines() if f'/backdrop/screen0/{monitor}/' in p and p.endswith('last-image')]
                    for prop in monitor_props:
                        os.system(f"xfconf-query -c xfce4-desktop -p {prop} -s {abs_path}")
                success = True
            except:
                # Fallback for older XFCE
                os.system(f"xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitor0/workspace0/last-image -s {abs_path}")
                success = True
                
        # Cinnamon
        elif 'cinnamon' in desktop_env:
            os.system(f"gsettings set org.cinnamon.desktop.background picture-uri '{file_uri}'")
            success = True
            
        # MATE
        elif 'mate' in desktop_env:
            os.system(f"gsettings set org.mate.background picture-filename '{abs_path}'")
            success = True
            
        # LXQt, LXDE
        elif 'lxqt' in desktop_env or 'lxde' in desktop_env:
            # For PCManFM-Qt
            os.system(f"pcmanfm-qt --set-wallpaper={abs_path}")
            # For PCManFM
            os.system(f"pcmanfm --set-wallpaper={abs_path}")
            success = True
            
        # i3wm, sway and other tiling window managers often use feh
        elif any(de in desktop_env for de in ['i3', 'sway']):
            os.system(f"feh --bg-fill '{abs_path}'")
            success = True
            
        # Fallback method using feh (works for many minimal window managers)
        elif not success:
            # Try generic methods
            methods = [
                f"feh --bg-fill '{abs_path}'",
                f"nitrogen --set-scaled '{abs_path}'",
                f"gsettings set org.gnome.desktop.background picture-uri '{file_uri}'"
            ]
            
            for method in methods:
                exit_code = os.system(method)
                if exit_code == 0:
                    success = True
                    break
                    
        if success:
            return True
        else:
            error_callback("Desktop Environment Not Detected", 
                           f"Couldn't detect your desktop environment ({desktop_env}). Try installing 'feh' package and retry.")
            return False
            
    except Exception as e:
        error_callback("Wallpaper Error", f"Failed to set wallpaper: {e}")
        return False
    

def unique_name(original_path, category):
    _, ext = os.path.splitext(original_path)
    timestamp_str = datetime.now().strftime('%Y-%m-%d-%H-%M-%S-%f')
    random_raw_part = secrets.token_urlsafe(18)
    sanitized_random_part = random_raw_part.replace('/', '_').replace('+', '-')
    base_name = f"{timestamp_str}_{category}_{sanitized_random_part}"
    return f"{base_name}{ext}"

def get_parent_directory(path):
    return os.path.dirname(path)

def list_subdirectories(parent_directory_path):
    if not os.path.isdir(parent_directory_path):
        return []

    subdirectories = []
    for item_name in os.listdir(parent_directory_path):
        item_path = os.path.join(parent_directory_path, item_name)
        if os.path.isdir(item_path):
            subdirectories.append(item_path)
    
    subdirectories.sort() # Optional: keep the list sorted
    return subdirectories

def list_relevant_files(dir_path):
    file_list = list_image_files(dir_path)
    file_list.extend( list_image_files( get_parent_directory( dir_path ) ) )
    for subdir in list_subdirectories( dir_path ):
        file_list.extend( list_image_files( subdir ) )
    return file_list


path_name_queue = queue.Queue()

class BackgroundWorker:
    def background(self):
        while self.keep_running:
            old_size = self.current_size
            old_directory = self.current_dir
            to_do_list = list_relevant_files( old_directory )
            for path_name in to_do_list:
                if not self.keep_running:
                    return
                self.barrier()
                if self.keep_running and ( old_size == self.current_size ) and ( old_directory == self.current_dir ):
                    # print(f"background: {path_name}")
                    get_or_make_thumbnail(path_name, old_size)
                    path_name_queue.put(path_name)
                else:
                    break
            while self.keep_running and ( old_size == self.current_size ) and ( old_directory == self.current_dir ):
                time.sleep(2)

    def __init__(self):
        self.keep_running = True
        self.current_size = 0
        self.current_dir = ""
        self.worker = threading.Thread( target=self.background )
        self.block = threading.Event()

    def pause(self):
        self.block.clear()

    def resume(self):
        self.block.set()

    def barrier(self):
        self.block.wait()

    def run(self, dir_path, size):
        self.current_size = size
        self.current_dir = dir_path
        self.worker.start()

    def stop(self):
        self.keep_running = False
        self.resume()
        
background_worker = BackgroundWorker()


def list_image_files(directory_path):
    if not os.path.isdir(directory_path):
        return []

    image_files = []

    for filename in os.listdir(directory_path):
        f_path = os.path.join(directory_path, filename)
        # Check if it's a file and its lowercase extension is in our supported list
        if os.path.isfile(f_path) and filename.lower().endswith(SUPPORTED_IMAGE_EXTENSIONS):
            image_files.append(f_path)

    image_files.sort()
    return image_files

def settle_geometry(widget):
    while widget.master:
        widget = widget.master
    widget.update_idletasks()


# --- widgets ---

class FullscreenImageViewer(tk.Toplevel):
    """
    A widget for displaying an image with zooming and panning capabilities.
    """
    
    def __init__(self, master, image_path, title=None, start_fullscreen=False):
        """
        Initialize the image viewer.
        
        Args:
            master: The parent widget
            image_path: Path to the image file to display
            title: Optional title for the window (defaults to filename)
            start_fullscreen: Whether to start in fullscreen mode
        """
        super().__init__(master)
        
        self.image_path = image_path
        self.original_image = None
        self.display_image = None
        self.photo_image = None
        self.is_fullscreen = False
        
        # Set window properties
        self.title(title or os.path.basename(image_path))
        self.minsize(400, 300)
        
        # Make it transient with parent, but allow window manager integration
        self.transient(master)
        self.resizable(True, True)
        
        # Ensure proper window manager integration
        self.wm_attributes("-type", "normal")
        self.wm_attributes('-fullscreen', start_fullscreen)
        self.protocol("WM_DELETE_WINDOW", self._close)
        
        # Create a frame to hold the canvas and scrollbars
        self.frame = ttk.Frame(self)
        self.frame.pack(fill=tk.BOTH, expand=True)
        
        # Create horizontal and vertical scrollbars
        self.h_scrollbar = ttk.Scrollbar(self.frame, orient=tk.HORIZONTAL)
        self.v_scrollbar = ttk.Scrollbar(self.frame, orient=tk.VERTICAL)
        
        # Create canvas for the image
        self.canvas = tk.Canvas(
            self.frame, 
            xscrollcommand=self.h_scrollbar.set,
            yscrollcommand=self.v_scrollbar.set,
            bg="black"
        )
        
        # Configure scrollbars
        self.h_scrollbar.config(command=self.canvas.xview)
        self.v_scrollbar.config(command=self.canvas.yview)
        
        # Grid layout for canvas and scrollbars
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.h_scrollbar.grid(row=1, column=0, sticky="ew")
        self.v_scrollbar.grid(row=0, column=1, sticky="ns")
        
        # Configure frame grid weights
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)
        
        # Image display state
        self.zoom_factor = 1.0
        self.fit_to_window = True  # Start in "fit to window" mode
        
        # Pan control variables
        self.pan_start_x = 0
        self.pan_start_y = 0
        self.panning = False
        
        # Bind events
        self._bind_events()
        
        # Load the image
        self._load_image()
        
        # Center window on parent 
        if not start_fullscreen:
            self.geometry("800x600")
            self._center_on_parent()
        
        # Set fullscreen if requested (after window has been mapped)
        if start_fullscreen:
            self.update_idletasks()  # Make sure window is realized first
            self.toggle_fullscreen()
        
        # Set focus to receive key events
        self.canvas.focus_set()
    
    def toggle_fullscreen(self):
        """Toggle fullscreen mode."""
        self.is_fullscreen = not self.is_fullscreen
        self.attributes('-fullscreen', self.is_fullscreen)
        self.update_idletasks()
        self._update_image()
    
    def _load_image(self):
        """Load the image from file and display it."""
        try:
            self.original_image = Image.open(self.image_path)
            self._update_image()
        except Exception as e:
            print(f"Error loading image {self.image_path}: {e}")
            self.destroy()

    def _update_image(self):
        """Update the displayed image based on current zoom and size."""
        if not self.original_image:
            return
                
        # Get current canvas size
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        # Use default size if canvas size not available yet
        if canvas_width <= 1:
            canvas_width = 800
        if canvas_height <= 1:
            canvas_height = 600
                
        # Get original image dimensions
        orig_width, orig_height = self.original_image.size
        
        # Calculate dimensions based on fit mode or zoom
        if self.fit_to_window:
            # Calculate scale to fit the window
            scale_width = canvas_width / orig_width
            scale_height = canvas_height / orig_height
            scale = min(scale_width, scale_height)
            self.zoom_factor = scale
            
            # Apply the scale
            new_width = int(orig_width * scale)
            new_height = int(orig_height * scale)
        else:
            # Apply the current zoom factor
            new_width = int(orig_width * self.zoom_factor)
            new_height = int(orig_height * self.zoom_factor)
        
        # Resize image
        self.display_image = self.original_image.resize(
            (new_width, new_height), 
            Image.LANCZOS
        )
        self.photo_image = ImageTk.PhotoImage(self.display_image)
        
        # Calculate the offset to center the image
        x_offset = max(0, (canvas_width - new_width) // 2)
        y_offset = max(0, (canvas_height - new_height) // 2)
        
        # Update canvas with new image
        self.canvas.delete("all")
        self.image_id = self.canvas.create_image(
            x_offset, y_offset, 
            anchor=tk.NW, 
            image=self.photo_image
        )
        
        # Set the scroll region - determine if scrolling is needed
        if new_width > canvas_width or new_height > canvas_height:
            # Image is larger than canvas, set scroll region to image size
            self.canvas.config(scrollregion=(0, 0, new_width, new_height))
            
            # When image is larger than canvas, we don't need the offset
            # We'll reposition the image at the origin for proper scrolling
            self.canvas.coords(self.image_id, 0, 0)
        else:
            # Image fits within canvas, include the offset in the scroll region
            self.canvas.config(scrollregion=(0, 0, 
                                            max(canvas_width, x_offset + new_width), 
                                            max(canvas_height, y_offset + new_height)))
        
        # Update scrollbars visibility based on image vs canvas size
        self._update_scrollbars()
        
        # If in fit mode or image is smaller than canvas, center the view
        if self.fit_to_window or (new_width <= canvas_width and new_height <= canvas_height):
            # Reset scroll position to start
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)

    def _update_scrollbars(self):
        """Show or hide scrollbars based on the image size compared to canvas."""
        # Get image and canvas dimensions
        img_width = self.display_image.width
        img_height = self.display_image.height
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        # Show/hide horizontal scrollbar
        if img_width <= canvas_width:
            self.h_scrollbar.grid_remove()
            self.canvas.xview_moveto(0)  # Reset horizontal scroll position
        else:
            self.h_scrollbar.grid()
            
        # Show/hide vertical scrollbar
        if img_height <= canvas_height:
            self.v_scrollbar.grid_remove()
            self.canvas.yview_moveto(0)  # Reset vertical scroll position
        else:
            self.v_scrollbar.grid()
                            
    def _center_on_parent(self):
        """Center this window on its parent."""
        self.update_idletasks()
        parent = self.master
        
        # Get parent and self dimensions
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        
        self_width = self.winfo_width()
        self_height = self.winfo_height()
        
        # Calculate position
        x = parent_x + (parent_width - self_width) // 2
        y = parent_y + (parent_height - self_height) // 2
        
        # Set position
        self.geometry(f"+{x}+{y}")
    
    def _bind_events(self):
        """Bind all event handlers."""
        # Keyboard events
        self.bind("<Key>", self._on_key)
        self.bind("<F11>", lambda e: self.toggle_fullscreen())
        self.bind("<Escape>", self._on_escape)
        
        # Mouse events
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        
        # Mouse wheel events
        if platform.system() == "Windows":
            self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        else:
            self.canvas.bind("<Button-4>", self._on_mouse_wheel)
            self.canvas.bind("<Button-5>", self._on_mouse_wheel)
            
        # Window events
        self.bind("<Configure>", self._on_configure)
    
    def _on_escape(self, event):
        self._close()
    
    def _close(self):
        if self.is_fullscreen:
            self.toggle_fullscreen()
        self.grab_release()
        self.destroy()
        
    def _on_key(self, event):
        """Handle keyboard events."""
        key = event.char
        
        if key == '+' or key == '=':  # Zoom in
            self._zoom_in()
        elif key == '-' or key == '_':  # Zoom out
            self._zoom_out()
        elif key == '0':  # Reset zoom
            self.fit_to_window = True
            self._update_image()
    
    def _on_mouse_down(self, event):
        """Handle mouse button press."""
        self.panning = True
        self.pan_start_x = event.x
        self.pan_start_y = event.y
        self.canvas.config(cursor="fleur")  # Change cursor to indicate panning
        
    def _on_mouse_drag(self, event):
        """Handle mouse drag for panning."""
        if not self.panning:
            return
            
        # Calculate the distance moved
        dx = self.pan_start_x - event.x
        dy = self.pan_start_y - event.y
        
        # Move the canvas view
        self.canvas.xview_scroll(dx, "units")
        self.canvas.yview_scroll(dy, "units")
        
        # Update the starting position
        self.pan_start_x = event.x
        self.pan_start_y = event.y
    
    def _on_mouse_up(self, event):
        """Handle mouse button release."""
        self.panning = False
        self.canvas.config(cursor="")  # Reset cursor
    
    def _on_mouse_wheel(self, event):
        """Handle mouse wheel events for zooming."""
        if platform.system() == "Windows":
            delta = event.delta
            if delta > 0:
                self._zoom_in(event.x, event.y)
            else:
                self._zoom_out(event.x, event.y)
        else:
            # For Linux/Unix/Mac
            if event.num == 4:  # Scroll up
                self._zoom_in(event.x, event.y)
            elif event.num == 5:  # Scroll down
                self._zoom_out(event.x, event.y)
                
    def _on_configure(self, event):
        """Handle window resize events."""
        # Only process events for the main window, not child widgets
        if event.widget == self and self.fit_to_window:
            # Delay update to avoid excessive redraws during resize
            self.after_cancel(getattr(self, '_resize_job', 'break'))
            self._resize_job = self.after(100, self._update_image)
    
    def _zoom_in(self, x=None, y=None):
        """Zoom in on the image."""
        self.fit_to_window = False
        self.zoom_factor *= 1.25
        
        # Save current view fractions before zooming
        if x is not None and y is not None:
            # Calculate the fractions to maintain zoom point
            x_fraction = self.canvas.canvasx(x) / (self.display_image.width)
            y_fraction = self.canvas.canvasy(y) / (self.display_image.height)
            
        # Update the image with new zoom
        self._update_image()
        
        # After zoom, scroll to maintain focus point
        if x is not None and y is not None:
            # Calculate new position in the zoomed image
            new_x = x_fraction * self.display_image.width
            new_y = y_fraction * self.display_image.height
            
            # Calculate canvas center
            canvas_width = self.canvas.winfo_width()
            canvas_height = self.canvas.winfo_height()
            
            # Calculate scroll fractions
            x_view_fraction = (new_x - canvas_width / 2) / self.display_image.width
            y_view_fraction = (new_y - canvas_height / 2) / self.display_image.height
            
            # Apply the scroll
            self.canvas.xview_moveto(max(0, min(1, x_view_fraction)))
            self.canvas.yview_moveto(max(0, min(1, y_view_fraction)))
    
    def _zoom_out(self, x=None, y=None):
        """Zoom out from the image."""
        self.fit_to_window = False
        self.zoom_factor /= 1.25
        
        # Minimum zoom factor - if we go below this, switch to fit mode
        min_zoom = 0.1
        if self.zoom_factor < min_zoom:
            self.fit_to_window = True
            self._update_image()
            return
            
        # Same logic as zoom in for maintaining focus point
        if x is not None and y is not None:
            x_fraction = self.canvas.canvasx(x) / (self.display_image.width)
            y_fraction = self.canvas.canvasy(y) / (self.display_image.height)
            
        self._update_image()
        
        if x is not None and y is not None:
            new_x = x_fraction * self.display_image.width
            new_y = y_fraction * self.display_image.height
            
            canvas_width = self.canvas.winfo_width()
            canvas_height = self.canvas.winfo_height()
            
            x_view_fraction = (new_x - canvas_width / 2) / self.display_image.width
            y_view_fraction = (new_y - canvas_height / 2) / self.display_image.height
            
            self.canvas.xview_moveto(max(0, min(1, x_view_fraction)))
            self.canvas.yview_moveto(max(0, min(1, y_view_fraction)))

    
class DirectoryThumbnailGrid(tk.Frame):
    def __init__(self, master=None, directory_path="", item_width=None, item_border_width=None,
                 button_config_callback=None, **kwargs):
        super().__init__(master, **kwargs)

        self._item_border_width = item_border_width
        self._directory_path = directory_path
        self._item_width = item_width
        self._button_config_callback = button_config_callback 
        self._widget_cache = OrderedDict() # This is a dict: hash_str -> (tk.Button, ImageTk.PhotoImage)
        self._cache_size = 2000
        self._active_widgets = {} # This is a dict: img_path -> (tk.Button, ImageTk.PhotoImage)
        self._last_known_width = -1
        self.pack_propagate(True)
        self.grid_propagate(True)    
        self.bind("<Configure>", self._on_resize)

    def get_width_and_height(self):
        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        return width, height
        
    def set_size_and_path(self, width, path=IMAGE_DIR):
        self._directory_path = path
        self._item_width = width
        return self.regrid()

    def _get_button(self, img_path, width):
        cache_key = uniq_file_id(img_path, width)
        target_btn, tk_image = self._widget_cache.get(cache_key, (None, None))
        
        if target_btn is None:
            target_btn = tk.Button(self)
            tk_image_ref = self._configure_button(target_btn, img_path)
            assert not tk_image_ref is None
            self._widget_cache[cache_key] = (target_btn, tk_image_ref)
        else:
            assert not tk_image is None
            self._button_config_callback(target_btn, img_path, tk_image)
            self._widget_cache.move_to_end(cache_key)
            
        return target_btn, tk_image
            
    def regrid(self):
        new_image_paths_from_disk = list_image_files(self._directory_path)
        # Note: Since the helper returns sorted (oldest first), we need to reverse it
        # to match the existing behavior of showing newest first
        new_image_paths_from_disk.reverse()

        for btn, _ in self._active_widgets.values():
            assert btn is not None
            assert btn.winfo_exists()
            btn.grid_forget()

        self._active_widgets = {}

        # Create/reuse and configure buttons for the new set of image paths
        for img_path in new_image_paths_from_disk:
            target_btn, tk_image = self._get_button(img_path, self._item_width)
            self._active_widgets[img_path] = (target_btn, tk_image)
            
        return self._layout_the_grid()

    def _on_resize(self, event=None):
        self.update_idletasks()
        current_width = self.winfo_width() 
        current_height = self.winfo_height()

        if event is not None and event.width > 0:
            current_width = event.width
            
        if current_width <= 0 or current_width == self._last_known_width:
            return current_width, current_height

        # print(f"current_width = {current_width}, last known width = {self._last_known_width}")
            
        self._last_known_width = current_width

        desired_content_cols_for_width = self._calculate_columns(current_width)
        if desired_content_cols_for_width == 0:
            desired_content_cols_for_width = 1 

        actual_tk_total_cols = 0
        try:
            actual_tk_total_cols = self.grid_size()[0]
        except TclError:
            pass 

        actual_tk_content_cols = 0
        if actual_tk_total_cols >= 2: 
            actual_tk_content_cols = actual_tk_total_cols - 2
        elif actual_tk_total_cols > 0:
            actual_tk_content_cols = actual_tk_total_cols

        if desired_content_cols_for_width != actual_tk_content_cols:
            return self._layout_the_grid()
        
        return self.get_width_and_height()

    def _calculate_columns(self, frame_width):
        if frame_width <= 0: return 1
        item_total_occupancy_width = self._item_width + (2 * self._item_border_width)
        buffer_for_gutters_and_edges = 10 
        available_width_for_items = frame_width - buffer_for_gutters_and_edges
        if available_width_for_items <= 0: return 1
        calculated_cols = max(1, available_width_for_items // item_total_occupancy_width)
        return calculated_cols

    def _layout_the_grid(self):
        desired_content_cols_for_this_pass = self._calculate_columns(self.master.winfo_width())
        if desired_content_cols_for_this_pass == 0:
            desired_content_cols_for_this_pass = 1 

        current_configured_cols = 0
        try:
            current_configured_cols = self.grid_size()[0]
        except TclError:
            pass
        for i in range(current_configured_cols):
            self.grid_columnconfigure(i, weight=0)
            
        self.grid_columnconfigure(0, weight=1)  
        self.grid_columnconfigure(desired_content_cols_for_this_pass + 1, weight=1) 

        # Widget Placement Loop
        for i, img_path in enumerate(self._active_widgets.keys()):
            widget, _ = self._active_widgets.get(img_path) 
            
            if widget is None or not widget.winfo_exists():
                print(f"Warning: Attempted to layout a non-existent widget for path '{img_path}'. Skipping.")
                continue
            row, col_idx = divmod(i, desired_content_cols_for_this_pass)
            grid_column = col_idx + 1 
            widget.grid(row=row, column=grid_column, padx=2, pady=2) 
        
        while len(self._widget_cache) > self._cache_size:
            self._widget_cache.popitem(last=False)

        return self.get_width_and_height()
    
    def _configure_button(self, btn, img_path):
        thumbnail_pil = get_or_make_thumbnail(img_path, self._item_width)
        tk_thumbnail = None
        if thumbnail_pil:
            try:
                tk_thumbnail = make_tk_image(thumbnail_pil)
            except Exception as e:
                print(f"Error converting PIL image to ImageTk.PhotoImage for {img_path}: {e}")
        
        if tk_thumbnail is not None:
            btn.config(image=tk_thumbnail)
        elif tk_thumbnail is None: 
            btn.config(image=None)
            
        if self._button_config_callback:
            self._button_config_callback(btn, img_path, tk_thumbnail)
        else:
            btn.config(relief="flat", borderwidth=0, cursor="arrow", command=None)
            
        return tk_thumbnail

    def destroy(self):
        for btn, _ in self._active_widgets.values(): 
            if btn is not None and btn.winfo_exists():
                btn.image = None
                btn.destroy() 
        self._active_widgets.clear()
        for btn, _ in self._widget_cache.values():
            if btn is not None and btn.winfo_exists():
                btn.image = None
                btn.destroy() 
        self._widget_cache.clear()
        super().destroy()


class LongMenu(tk.Toplevel):
    def __init__(self, master, default_option, other_options, font=None, x_pos=None, y_pos=None):
        super().__init__(master)
        self.overrideredirect(True) # Remove window decorations (title bar, borders)
        self.transient(master)      # Tie to master window
        # self.grab_set()             # Make it modal, redirect all input here

        self.result = default_option
        self._options = other_options

        self._app_font = font if font else ("TkDefaultFont", 12, "normal")

        self._listbox_frame = ttk.Frame(self)
        self._listbox_frame.pack(padx=10, pady=10, fill="both", expand=True)

        self._listbox = tk.Listbox(
            self._listbox_frame,
            selectmode=tk.SINGLE,
            font=self._app_font,
            height=15
        )
        self._listbox.pack(side="left", fill="both", expand=True)

        self._scrollbar = ttk.Scrollbar(self._listbox_frame, orient="vertical", command=self._listbox.yview)
        self._scrollbar.pack(side="right", fill="y")
        self._listbox.config(yscrollcommand=self._scrollbar.set)

        # Populate the _listbox
        for option_name in other_options:
            self._listbox.insert(tk.END, option_name)

        # --- Bindings ---
        self._listbox.bind("<<ListboxSelect>>", self._on_listbox_select)
        self._listbox.bind("<Double-Button-1>", self._on_double_click) # Double-click to select and close
        self.bind("<Return>", self._on_return_key) # Enter key to select and close
        self.bind("<Escape>", self._cancel) # Close on Escape key
        self.bind("<FocusOut>", self._on_focus_out)
        
        # --- Positioning and Focus ---
        self.update_idletasks()
        self.grab_set() 

        if x_pos is None or y_pos is None:
            master_x = master.winfo_x()
            master_y = master.winfo_y()
            master_h = master.winfo_height()
            x_pos = master_x
            y_pos = master_y + master_h

        screen_width = self.winfo_screenwidth()
        popup_w = self.winfo_width()
        if x_pos + popup_w > screen_width:
            x_pos = screen_width - popup_w - 5 # 5 pixels margin
            
        # Adjust if menu would go off-screen downwards (or upwards if preferred)
        screen_height = self.winfo_screenheight()
        popup_h = self.winfo_height()
        if y_pos + popup_h > screen_height:
            y_pos = screen_height - popup_h - 5 # 5 pixels margin
            
        self.geometry(f"+{int(x_pos)}+{int(y_pos)}")        # Center the window relative to its master

        self._listbox.focus_set() # Set focus to the _listbox for immediate keyboard navigation
        self.wait_window(self) # Make the dialog modal until it's destroyed

    def _on_listbox_select(self, event):
        self._exit_ok()

    def _on_double_click(self, event):
        self._exit_ok()

    def _on_return_key(self, event):
        self._exit_ok()

    def _exit_ok(self):
        selected_indices = self._listbox.curselection()
        if selected_indices:
            # Store the selected directory name, not the full path yet
            self.result = self._options[selected_indices[0]]
        self.destroy()

    def _cancel(self, event=None):
        self.result = None
        self.destroy()

    def _on_focus_out(self, event):
        # If the widget losing focus is not a child of this menu (e.g., clicking outside)
        # then close the menu.
        if self.winfo_exists() and not self.focus_get() in self.winfo_children():
            self._cancel()

        
class BreadCrumNavigator(ttk.Frame):
    def __init__(self, master, on_navigate_callback=None, font=None,
                 long_press_threshold_ms=400, drag_threshold_pixels=5):
        
        super().__init__(master)
        self._on_navigate_callback = on_navigate_callback
        self._current_path = ""

        self._LONG_PRESS_THRESHOLD_MS = long_press_threshold_ms
        self._DRAG_THRESHOLD_PIXELS = drag_threshold_pixels

        self._long_press_timer_id = None
        self._press_start_time = 0
        self._press_x = 0
        self._press_y = 0
        self._active_button = None 

        if isinstance(font, tkFont.Font):
            self.btn_font = (
                font.actual('family'),
                font.actual('size'),
                font.actual('weight') 
            )
        elif isinstance(font, (tuple, str)):
            self.btn_font = font
        else:
            self.btn_font = ("TkDefaultFont", 10, "normal") 

    def set_path(self, path):
        if not os.path.isdir(path):
            print(f"Warning: Path '{path}' is not a directory. Cannot set breadcrumbs.")
            return

        self._current_path = os.path.normpath(path)
        self._update_breadcrumbs()

    def _update_breadcrumbs(self):
        for widget in self.winfo_children():
            widget.destroy()

        btn_list = []
        current_display_path = self._current_path
        while len(current_display_path) > 1: 
            path = current_display_path
            current_display_path = os.path.dirname(path)
            btn_text = os.path.basename(path)
            if btn_text == '': 
                btn_text = os.path.sep
            btn = tk.Button(self, text=btn_text, font=self.btn_font)
            btn.path = path
            btn.bind("<ButtonPress-1>", self._on_button_press)
            btn.bind("<ButtonRelease-1>", self._on_button_release)
            btn.bind("<Motion>", self._on_button_motion)
            btn_list.insert( 0, btn )

        btn_text="//"
        btn = tk.Button(self, text=btn_text, font=self.btn_font)
        btn.path = current_display_path
        btn.bind("<ButtonPress-1>", self._on_button_press)
        btn.bind("<ButtonRelease-1>", self._on_button_release)
        btn.bind("<Motion>", self._on_button_motion)
        btn_list.insert( 0, btn )

        for i, btn in enumerate( btn_list ):
            if i > 0:
                ttk.Label(self, text=" / ").pack(side="left")
            if i + 1 == len( btn_list ):
                 btn.bind("<ButtonPress-1>", self._on_button_press_menu)
            btn.pack(side="left")            
            
    def _trigger_navigate(self, path):
        if self._on_navigate_callback:
            self._on_navigate_callback(path)

    def _on_button_press_menu(self, event):
        self._show_subdirectory_menu( event.widget )
            
    def _on_button_press(self, event):
        self._press_start_time = time.time()
        self._press_x, self._press_y = event.x_root, event.y_root
        self._active_button = event.widget
        self._long_press_timer_id = self.after(self._LONG_PRESS_THRESHOLD_MS,
                                               lambda: self._on_long_press_timeout(self._active_button))

    def _on_button_release(self, event):
        if self._long_press_timer_id:
            self.after_cancel(self._long_press_timer_id)
            self._long_press_timer_id = None

        if self._active_button:
            dist = (abs(event.x_root - self._press_x)**2 + abs(event.y_root - self._press_y)**2)**0.5
            if dist < self._DRAG_THRESHOLD_PIXELS:
                if (time.time() - self._press_start_time) * 1000 < self._LONG_PRESS_THRESHOLD_MS:
                    path = self._active_button.path
                    if path and self._on_navigate_callback:
                        self._on_navigate_callback(path)
            self._active_button = None

    def _on_button_motion(self, event):
        if self._active_button and self._long_press_timer_id:
            dist = (abs(event.x_root - self._press_x)**2 + abs(event.y_root - self._press_y)**2)**0.5
            if dist > self._DRAG_THRESHOLD_PIXELS:
                self.after_cancel(self._long_press_timer_id)
                self._long_press_timer_id = None
                self._active_button = None

    def _on_long_press_timeout(self, button):
        if self._active_button is button:
            self._show_subdirectory_menu(button)
            self._long_press_timer_id = None

    def _show_subdirectory_menu(self, button):
        path = button.path
        selected_path = path

        all_entries = os.listdir(path)
        subdirs = []
        hidden_subdirs = []
        for entry in all_entries:
            full_path = os.path.join( path, entry )
            if os.path.isdir( full_path ):
                if entry.startswith('.'):
                    hidden_subdirs.append(entry)
                else:
                    subdirs.append(entry)
        subdirs.sort()
        hidden_subdirs.sort()
        sorted_subdirs = subdirs + hidden_subdirs
        
        if sorted_subdirs:
            button_x = button.winfo_rootx()
            button_y = button.winfo_rooty()
            button_height = button.winfo_height()
            menu_x = button_x
            menu_y = button_y + button_height
            selector_dialog = LongMenu(
                button,
                None,
                sorted_subdirs,
                font=self.btn_font,
                x_pos=menu_x,
                y_pos=menu_y
            )
            selected_name = selector_dialog.result
            if selected_name:
                selected_path = os.path.join(path, selected_name)
                
        self._trigger_navigate(selected_path)

        
class ImagePickerDialog(tk.Toplevel):
    def _cache_widget(self):
        try:
            path_name = path_name_queue.get_nowait()
            self._gallery_grid._get_button(path_name, self._thumbnail_max_size)
            # print(f"created button for {path_name} at size {self._thumbnail_max_size}")
        except queue.Empty:
            pass
        self.after(50, self._cache_widget)
        
    def __init__(self, master, thumbnail_max_size, image_dir):
        super().__init__(master)
        self.withdraw()

        self._master = master
        self._thumbnail_max_size = thumbnail_max_size
        self._current_image_dir = image_dir
        self.selected_files = []

        self._create_widgets()

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        self.after(0, self._cache_widget)

    def hide(self):
        self.grab_release()
        self.withdraw()

    def _repaint(self):
        self._gallery_grid.set_size_and_path(self._thumbnail_max_size, self._current_image_dir)
        self.update_idletasks()

    def show(self, width):
        self._thumbnail_max_size = width
        self.selected_files = []
        self.deiconify()
        self._load_geometry()
        self.title("Add Images to Collection")
        self.transient(self._master)
        self.grab_set()
        self._browse_directory(self._current_image_dir)
        self._gallery_canvas.yview_moveto(0.0)
        self.after(100, self.focus_set)
 
    def _create_widgets(self):
        # Thumbnail Display Area (Canvas and Scrollbar)
        self._canvas_frame = ttk.Frame(self)
        self._canvas_frame.pack(fill="both", expand=True, padx=5, pady=5)

        self._gallery_canvas = tk.Canvas(self._canvas_frame, bg=self.cget("background"))
        self._gallery_scrollbar = ttk.Scrollbar(self._canvas_frame, orient="vertical", command=self._gallery_canvas.yview)
        self._gallery_canvas.config(yscrollcommand=self._gallery_scrollbar.set)
        
        self._gallery_scrollbar.pack(side="right", fill="y")
        self._gallery_canvas.pack(side="left", fill="both", expand=True)
        
        self._gallery_grid = DirectoryThumbnailGrid(
            self._gallery_canvas,
            directory_path=self._current_image_dir,
            item_width=self._thumbnail_max_size,
            item_border_width=6,
            button_config_callback=self._configure_picker_button,
            bg=self.cget("background")
        )
        self._gallery_canvas.create_window((0, 0), window=self._gallery_grid, anchor="nw")

        self._gallery_canvas.bind("<Configure>", self._on_canvas_configure)
        self._gallery_grid.bind("<Configure>", lambda e: self._gallery_canvas.configure(scrollregion=self._gallery_canvas.bbox("all")))
        
        self._bind_mousewheel(self)

        self.bind("<Up>", lambda e: self._gallery_canvas.yview_scroll(-1, "units"))
        self.bind("<Down>", lambda e: self._gallery_canvas.yview_scroll(1, "units"))
        self.bind("<Prior>", lambda e: self._gallery_canvas.yview_scroll(-1, "pages"))
        self.bind("<Next>", lambda e: self._gallery_canvas.yview_scroll(1, "pages"))

        # Control Frame (at the bottom)
        self._control_frame = ttk.Frame(self)
        self._control_frame.pack(fill="x", padx=5, pady=5)

        # Breadcrumb Frame
        self.breadcrumb_nav = BreadCrumNavigator(
            self._control_frame, # Parent is the _control_frame
            on_navigate_callback=self._browse_directory, # This callback will update the grid and breadcrumbs
            font=self._master.app_font, # Use the app's font
        )
        self.breadcrumb_nav.pack(side="left", fill="x", expand=True, padx=5)

        # Right side: Add and Cancel buttons (packed in reverse order for correct visual sequence)
        ttk.Button(self._control_frame, text="Cancel", command=self._on_closing).pack(side="right", padx=(24, 2))
        ttk.Button(self._control_frame, text="Add Selected", command=self._on_add_selected).pack(side="right", padx=24)

    def _adjust_gallery_scroll_position(self, old_scroll_fraction):
        bbox = self._gallery_canvas.bbox("all")

        if not bbox:
            self._gallery_canvas.yview_moveto(0.0)
            return
    
        total_content_height = bbox[3] - bbox[1] # y2 - y1
        visible_canvas_height = self._gallery_canvas.winfo_height()
        if total_content_height <= visible_canvas_height:
            self._gallery_canvas.yview_moveto(0.0)
            return

        old_abs_scroll_pos = old_scroll_fraction * total_content_height
        max_scroll_abs_pos = total_content_height - visible_canvas_height
        if max_scroll_abs_pos < 0: # Should not happen if previous check passed, but for safety
            max_scroll_abs_pos = 0

        new_abs_scroll_pos = min(old_abs_scroll_pos, max_scroll_abs_pos)
        new_scroll_fraction = new_abs_scroll_pos / total_content_height

        self._gallery_canvas.yview_moveto(new_scroll_fraction)
        
    def _show_full_screen(self, img_path):
        """Open the image in the fullscreen viewer when right-clicked."""
        try:
            # raise ValueError("thrown for testing")
            viewer = FullscreenImageViewer(self, img_path, title=img_path, start_fullscreen=True)
            viewer.grab_set()  # Make the viewer modal
        except Exception as e:
            custom_message_dialog(parent=self, title="Error", message=f"Could not open image: {e}", font=self._master.app_font)
        
    def _configure_picker_button(self, btn, img_path, tk_thumbnail):
         btn.config(
            cursor="hand2", 
            relief="flat", 
            borderwidth=0,
            highlightthickness=3,
            bg=self.cget("background"),
            command=lambda dummy=None: self._toggle_selection(img_path, btn)
         )
         btn.bind("<Button-3>", lambda dummy: self._show_full_screen(img_path))
        
         if img_path in self.selected_files:
             btn.config(highlightbackground="blue")
         else:
             btn.config(highlightbackground=self.cget("background"))

    def _center_toplevel_window(self, toplevel_window):
        toplevel_window.update_idletasks()
        master_x = self._master.winfo_x()
        master_y = self._master.winfo_y()
        master_w = self._master.winfo_width()
        master_h = self._master.winfo_height()

        popup_w = toplevel_window.winfo_width()
        popup_h = toplevel_window.winfo_height()

        x_pos = master_x + (master_w // 2) - (popup_w // 2)
        y_pos = master_y + (master_h // 2) - (popup_h // 2)

        toplevel_window.geometry(f"+{x_pos}+{y_pos}")

    def _on_closing(self):
        self._save_geometry()
        self.hide()

    def _save_geometry(self):
        if hasattr(self._master, 'app_settings'):
            self.update_idletasks()
            geometry = self.geometry()
            self._master.app_settings['image_picker_dialog_geometry'] = geometry
            self._master.app_settings['image_picker_last_directory'] = self._current_image_dir
            self._master.save_app_settings()

    def _load_geometry(self):
        if hasattr(self._master, 'app_settings'):
            geometry_str = self._master.app_settings.get('image_picker_dialog_geometry')
            if geometry_str:
                try:
                    self.geometry(geometry_str)
                    self.update_idletasks() 
                    x, y, w, h = self.winfo_x(), self.winfo_y(), self.winfo_width(), self.winfo_height()
                    screen_width = self.winfo_screenwidth()
                    screen_height = self.winfo_screenheight()

                    if x < -w/2 or x > screen_width - w/2 or y < -h/2 or y > screen_height - h/2:
                        self._center_toplevel_window(self)
                except Exception as e:
                    print(f"Error loading image picker dialog geometry: {e}. Centering window.")
                    self._center_toplevel_window(self)
            else:
                self._center_toplevel_window(self)
        else:
            self._center_toplevel_window(self)

    def _browse_directory(self, path):
        if not os.path.isdir(path):
            custom_message_dialog(parent=self, title="Error", message=f"Invalid directory: {path}", font=self._master.app_font)
            return
        
        self._current_image_dir = path
        try: # Added try-except for background_worker in case it's not global or initialized yet
            background_worker.current_dir = path
        except NameError:
            print("Warning: background_worker not found. Cannot update its current_dir.")
            
        self.breadcrumb_nav.set_path(path)
        self._gallery_grid.set_size_and_path(self._thumbnail_max_size, self._current_image_dir)
        self._repaint()

    def _toggle_selection(self, img_path, button_widget):
        if img_path in self.selected_files:
            self.selected_files.remove(img_path)
            button_widget.config(highlightbackground=self.cget("background"))
        else:
            self.selected_files.append(img_path)
            button_widget.config(highlightbackground="blue")

    def _on_add_selected(self):
        self._save_geometry()
        self._master.add_multiple_images_as_symlinks(self.selected_files)
        self.hide()

    def _on_canvas_configure(self, event):
        self._gallery_canvas.itemconfig(self._gallery_canvas.find_all()[0], width=event.width)
        old_scroll_fraction = self._gallery_canvas.yview()[0]
        width, height = self._gallery_grid._on_resize()
        # print(f"widht = {width}, height = {height}")
        self._gallery_canvas.configure(scrollregion=(0, 0, width, height))
        self._adjust_gallery_scroll_position(old_scroll_fraction)

    def _bind_mousewheel(self, widget):
        widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
        widget.bind("<Button-4>", lambda e: self._on_mousewheel(e), add="+")
        widget.bind("<Button-5>", lambda e: self._on_mousewheel(e), add="+")

    def _on_mousewheel(self, event):
        if platform.system() == "Windows": self._gallery_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        elif event.num == 4: self._gallery_canvas.yview_scroll(-1, "units")
        elif event.num == 5: self._gallery_canvas.yview_scroll(1, "units")

        
class WallpaperApp(tk.Tk):
    def __init__(self):
        super().__init__(className="kubux-wallpaper-generator")
        self.title("kubux wallpaper generator")
        self.configure(background=self.cget("background"))
        self.current_image_path = None
        self.max_history_items = 125
        self.gallery_current_selection = None
        self.gallery_thumbnail_max_size = DEFAULT_THUMBNAIL_DIM
        self._gallery_scale_update_after_id = None
        self._gallery_resize_job = None
        self._ui_scale_job = None
        self._initial_load_done = False

        self._load_prompt_history()
        self.load_app_settings()
        self.gallery_thumbnail_max_size = int(DEFAULT_THUMBNAIL_DIM * self.current_thumbnail_scale)
        font_name, font_size = get_linux_system_ui_font_info()
        self.base_font_size = font_size
        self.app_font = tkFont.Font(family=font_name, size=int(self.base_font_size * self.current_font_scale))
        self.geometry(self.initial_geometry)
        
        self._create_widgets()
        
        self.update_idletasks()
        self._set_initial_pane_positions()
        
        self.gallery_canvas.bind("<Configure>", self._gallery_on_canvas_configure)
        self.display_frame.bind("<Configure>", self._on_display_frame_resize)
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        self.update_idletasks()
        self.dialog = None

    def _image_dir(self):
        if hasattr(self, 'app_settings'):
            saved_dir = self.app_settings.get('image_picker_last_directory')
            if saved_dir and os.path.isdir(saved_dir):
                return  saved_dir

        default_dir = os.path.expanduser(os.path.join('~', 'Pictures'))
        if not os.path.isdir(default_dir):
            default_dir = os.path.expanduser('~')
        return default_dir
        
    def _load_prompt_history(self):
        try:
            if os.path.exists(PROMPT_HISTORY_FILE):
                with open(PROMPT_HISTORY_FILE, 'r') as f:
                    self.prompt_history = json.load(f)
            else: self.prompt_history = [] 
        except (json.JSONDecodeError, Exception): self.prompt_history = []

    def _save_prompt_history(self):
        try:
            with open(PROMPT_HISTORY_FILE, 'w') as f:
                json.dump(self.prompt_history, f, indent=4) 
        except Exception as e: print(f"Error saving prompt history: {e}")

    def load_app_settings(self):
        try:
            if os.path.exists(APP_SETTINGS_FILE):
                with open(APP_SETTINGS_FILE, 'r') as f:
                    self.app_settings = json.load(f)
            else:
                self.app_settings = {}
        except (json.JSONDecodeError, Exception) as e:
            print(f"Error loading app settings, initializing defaults: {e}")
            self.app_settings = {}
        
        self.current_font_scale = self.app_settings.get("ui_scale", 1.0)
        self.initial_geometry = self.app_settings.get("window_geometry", "1200x800")
        self.current_thumbnail_scale = self.app_settings.get("thumbnail_scale", 1.0)
        self.horizontal_paned_position = self.app_settings.get("horizontal_paned_position", 600)
        self.vertical_paned_position = self.app_settings.get("vertical_paned_position", 400)
        self.model_string = self.app_settings.get("model_string", "black-forest-labs/FLUX.1-pro")

    def save_app_settings(self):
        try:
            if not hasattr(self, 'app_settings'):
                self.app_settings = {}

            self.app_settings["ui_scale"] = self.current_font_scale
            self.app_settings["window_geometry"] = self.geometry()
            self.app_settings["thumbnail_scale"] = self.current_thumbnail_scale
            self.app_settings["model_string"] = self.model_string
            
            if hasattr(self, 'paned_window') and self.paned_window.winfo_exists():
                self.app_settings["horizontal_paned_position"] = self.paned_window.sashpos(0)
            if hasattr(self, 'vertical_paned') and self.vertical_paned.winfo_exists():
                self.app_settings["vertical_paned_position"] = self.vertical_paned.sashpos(0)

            with open(APP_SETTINGS_FILE, 'w') as f:
                json.dump(self.app_settings, f, indent=4)
        except Exception as e:
            print(f"Error saving app settings: {e}")

    def _preview_is_gone(self):
        return self.paned_window.sashpos(0) == 0 or self.vertical_paned.sashpos(0) == 0
            
    def _on_closing(self):
        background_worker.stop()
        self._save_prompt_history()
        self.save_app_settings()
        self.destroy() 

    def _create_widgets(self):
        self.style = ttk.Style()
        self.style.configure('.', font=self.app_font)

        controls_frame = tk.Frame(self)
        controls_frame.pack(side="bottom", fill="x", pady=(5, 5), padx=5)
        controls_frame.grid_columnconfigure((1, 3), weight=1)

        main_container = tk.Frame(self)
        main_container.pack(side="top", fill="both", expand=True, padx=5, pady=(5, 0))

        self.paned_window = ttk.PanedWindow(main_container, orient="horizontal")
        self.paned_window.pack(fill="both", expand=True)
        
        left_pane = ttk.Frame(self.paned_window)
        self.paned_window.add(left_pane, weight=1)

        thumbnail_frame_outer = ttk.LabelFrame(self.paned_window, text="Your Wallpaper Collection")
        self.paned_window.add(thumbnail_frame_outer, weight=0)

        self.vertical_paned = ttk.PanedWindow(left_pane, orient="vertical")
        self.vertical_paned.pack(fill="both", expand=True)

        self.display_frame = ttk.LabelFrame(self.vertical_paned, text="Preview")
        self.vertical_paned.add(self.display_frame, weight=1)

        self.generated_image_label = ttk.Label(self.display_frame, anchor="center")
        self.generated_image_label.pack(fill="both", expand=True, padx=5, pady=5)

        prompt_frame_outer = ttk.LabelFrame(self.vertical_paned, text="Generate New Wallpaper")
        if ai_features_enabled:
            self.vertical_paned.add(prompt_frame_outer, weight=0)

        prompt_frame_inner = tk.Frame(prompt_frame_outer)
        prompt_frame_inner.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.prompt_text_widget = tk.Text(prompt_frame_inner, height=6, wrap="word", relief="sunken", borderwidth=2, font=self.app_font)
        self.prompt_text_widget.pack(fill="both", expand=True)
        self.prompt_text_widget.bind("<Return>", lambda event: self._on_generate_button_click())

        self.gallery_canvas = tk.Canvas(thumbnail_frame_outer)
        self.gallery_scrollbar = ttk.Scrollbar(thumbnail_frame_outer, orient="vertical", command=self.gallery_canvas.yview)
        self.gallery_canvas.config(yscrollcommand=self.gallery_scrollbar.set)
        self.gallery_scrollbar.pack(side="right", fill="y")
        self.gallery_canvas.pack(side="left", fill="both", expand=True)
        
        self.gallery_grid = DirectoryThumbnailGrid(
            self.gallery_canvas, 
            directory_path=IMAGE_DIR,
            item_width=self.gallery_thumbnail_max_size,
            item_border_width=2,
            button_config_callback=self._gallery_configure_button,
            bg=self.cget("background")
        )
        self.gallery_canvas.create_window((0, 0), window=self.gallery_grid, anchor="nw")
        
        self._gallery_bind_mousewheel(self)

        self.gallery_canvas.bind("<Key>", self._gallery_on_key_press)
        self.gallery_canvas.bind("<Enter>", lambda e: self.gallery_canvas.focus_set())
        self.gallery_canvas.bind("<Leave>", lambda e: self.focus_set())

        self.gallery_grid.bind("<Configure>", lambda e: self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all")))

        generate_btn_frame = tk.Frame(controls_frame)
        generate_btn_frame.grid(row=0, column=0, sticky="w")
        self.generate_button = ttk.Button(generate_btn_frame, text="Generate", command=self._on_generate_button_click)
        self.generate_button.pack(side="left", padx=(2,8))
        self.history_button = ttk.Button(generate_btn_frame, text="History", command=self._show_prompt_history)
        self.history_button.pack(side="left")

        if not ai_features_enabled:
            # Disable AI-dependent UI elements
            self.generate_button.configure(state="disabled")
            self.history_button.configure(state="disabled")
            
            # Add an informational button in their place
            self.enable_ai_button = ttk.Button(
                generate_btn_frame, 
                text="Enable AI Generation",
                command=self.show_api_setup_instructions
            )
            self.enable_ai_button.pack(side="left", padx=(8,0))

        sliders_frame = tk.Frame(controls_frame)
        sliders_frame.grid(row=0, column=2)
        ttk.Label(sliders_frame, text="UI:").pack(side="left")

        self.scale_slider = tk.Scale(
            sliders_frame, from_=0.5, to=2.5, orient="horizontal", 
            resolution=0.1, showvalue=False
        )
        self.scale_slider.set(self.current_font_scale)
        self.scale_slider.config(command=self._update_ui_scale)
        self.scale_slider.pack(side="left")
        
        ttk.Label(sliders_frame, text="Thumbs:", padding="20 0 0 0").pack(side="left")
        
        self.thumbnail_scale_slider = tk.Scale(
            sliders_frame, from_=0.5, to=2.5, orient="horizontal",
            resolution=0.1, showvalue=False
        )
        self.thumbnail_scale_slider.set(self.current_thumbnail_scale)
        self.thumbnail_scale_slider.config(command=self._gallery_update_thumbnail_scale_callback)
        self.thumbnail_scale_slider.pack(side="left")

        action_btn_frame = tk.Frame(controls_frame)
        action_btn_frame.grid(row=0, column=4, sticky="e")
        ttk.Button(action_btn_frame, text="Delete", command=self._delete_selected_image).pack(side="left", padx=(8,0))
        ttk.Button(action_btn_frame, text="Add", command=self._manually_add_images).pack(side="left", padx=(8,0))
        ttk.Button(action_btn_frame, text="Set Wallpaper", command=self._set_current_as_wallpaper).pack(side="left", padx=(8, 2))

        users_images = self._image_dir()
        self.dialog = ImagePickerDialog(self, self.gallery_thumbnail_max_size, users_images)
        background_worker.run(users_images, self.gallery_thumbnail_max_size)
        background_worker.pause()
        self.after(3000, background_worker.resume)
 
    def _gallery_configure_button(self, btn, img_path, tk_thumbnail):
        btn.config(
            cursor="hand2", 
            relief="flat", 
            borderwidth=0,
            bg=self.cget("background"),
            command=lambda dummy=None: self._gallery_on_thumbnail_click(img_path)
        )
        btn.bind("<Button-3>", lambda dummy: self._gallery_on_thumbnail_click_right(img_path))

    def show_api_setup_instructions(self):
        instructions = """
        To enable AI image generation:
        
        1. Create a Together.ai account at https://together.ai
        2. Generate an API key from your account settings
        3. Create a .env file in your home directory with:
        TOGETHER_API_KEY=your_api_key_here
        
        Then restart the application to access all features.
        """
        custom_message_dialog(self, "Enable AI Image Generation", 
                              instructions, font=self.app_font)    
            
    def _set_initial_pane_positions(self):
        try:
            self.paned_window.sashpos(0, self.horizontal_paned_position)
            self.vertical_paned.sashpos(0, self.vertical_paned_position)
        except (tk.TclError, IndexError): 
            pass

    def _update_ui_scale(self, value):
        if self._ui_scale_job: self.after_cancel(self._ui_scale_job)
        self._ui_scale_job = self.after(400, lambda: self._do_update_ui_scale(float(value)))

    def _do_update_ui_scale(self, scale_factor):
        self.current_font_scale = scale_factor
        new_size = int(self.base_font_size * scale_factor)
        self.app_font.config(size=new_size)
        def update_widget_fonts(widget, font):
            try:
                if 'font' in widget.config(): widget.config(font=font)
            except tk.TclError: pass
            for child in widget.winfo_children(): update_widget_fonts(child, font)
        update_widget_fonts(self, self.app_font)
        if self.current_image_path: self._display_image(self.current_image_path)
    
    def _on_display_frame_resize(self, event):
        if self.current_image_path and event.width > 1 and event.height > 1:
            self._display_image(self.current_image_path)

    def _display_image(self, image_path):
        try:
            # raise ValueError("simulated for testing")
            full_img = get_full_size_image(image_path)
            fw, fh = self.generated_image_label.winfo_width(), self.generated_image_label.winfo_height()
            if fw <= 1 or fh <= 1: return
            resized_img = resize_image( full_img, fw, fh )
            photo = make_tk_image(resized_img)
            self.generated_image_label.config(image=photo)
            self.generated_image_label.image = photo 
            self.current_image_path = image_path
        except Exception as e:
            custom_message_dialog(parent=self, title="Image Display Error", message=f"Could not display image: {e}", font=self.app_font)
            self.current_image_path = None
    
    # --- Gallery Methods ---
    def _load_images(self):
        background_worker.pause()
        self.gallery_grid.regrid()
        background_worker.resume()

    def _gallery_update_thumbnail_scale_callback(self, value):
        if self._gallery_scale_update_after_id: self.after_cancel(self._gallery_scale_update_after_id)
        self._gallery_scale_update_after_id = self.after(300, lambda: self._gallery_do_scale_update(float(value)))

    def _adjust_gallery_scroll_position(self, old_scroll_fraction):
        bbox = self.gallery_canvas.bbox("all")

        if not bbox:
            self.gallery_canvas.yview_moveto(0.0)
            return
    
        total_content_height = bbox[3] - bbox[1] # y2 - y1
        visible_canvas_height = self.gallery_canvas.winfo_height()
        if total_content_height <= visible_canvas_height:
            self.gallery_canvas.yview_moveto(0.0)
            return

        old_abs_scroll_pos = old_scroll_fraction * total_content_height
        max_scroll_abs_pos = total_content_height - visible_canvas_height
        if max_scroll_abs_pos < 0: # Should not happen if previous check passed, but for safety
            max_scroll_abs_pos = 0

        new_abs_scroll_pos = min(old_abs_scroll_pos, max_scroll_abs_pos)
        new_scroll_fraction = new_abs_scroll_pos / total_content_height

        self.gallery_canvas.yview_moveto(new_scroll_fraction)

    def _gallery_do_scale_update(self, scale):
        self.current_thumbnail_scale = scale
        self.gallery_thumbnail_max_size = int(DEFAULT_THUMBNAIL_DIM * scale)
        background_worker.pause()
        old_scroll_fraction = self.gallery_canvas.yview()[0]
        width, height = self.gallery_grid.set_size_and_path(self.gallery_thumbnail_max_size)
        # print(f"widht = {width}, height = {height}")
        self.gallery_canvas.configure(scrollregion=(0, 0, width, height))
        self._adjust_gallery_scroll_position(old_scroll_fraction)
        background_worker.current_size = self.gallery_thumbnail_max_size
        background_worker.resume()

    def _gallery_on_canvas_configure(self, event):
        if not self._initial_load_done and event.width > 1:
            self._load_images()
            self._initial_load_done = True
            
        if self._gallery_resize_job: 
            self.after_cancel(self._gallery_resize_job)
        self._gallery_resize_job = self.after(400, lambda e=event: self._do_gallery_resize_refresh(e))

    def _do_gallery_resize_refresh(self, event):
        self.gallery_canvas.itemconfig(self.gallery_canvas.find_all()[0], width=event.width)
        background_worker.pause()
        old_scroll_fraction = self.gallery_canvas.yview()[0]
        width, height = self.gallery_grid._on_resize()
        # print(f"widht = {width}, height = {height}")
        self.gallery_canvas.configure(scrollregion=(0, 0, width, height))
        self._adjust_gallery_scroll_position(old_scroll_fraction)
        self.update_idletasks()
        background_worker.resume()
        
    def _gallery_on_thumbnail_click(self, image_path):
        old_selection = self.gallery_current_selection
        self.gallery_current_selection = image_path
        self._display_image(image_path)
        if self._preview_is_gone():
            self._set_current_as_wallpaper()
    
    def _gallery_on_thumbnail_click_right(self, image_path):
        self._delete_image(image_path)
    
    def _gallery_bind_mousewheel(self, widget):
        widget.bind("<MouseWheel>", self._gallery_on_mousewheel, add="+")
        widget.bind("<Button-4>", lambda e: self._gallery_on_mousewheel(e), add="+")
        widget.bind("<Button-5>", lambda e: self._gallery_on_mousewheel(e), add="+")

    def _gallery_on_mousewheel(self, event):
        if platform.system() == "Windows": self.gallery_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        elif event.num == 4: self.gallery_canvas.yview_scroll(-1, "units")
        elif event.num == 5: self.gallery_canvas.yview_scroll(1, "units")
        
    def _gallery_on_key_press(self, event):
        key = event.keysym
        if key == 'Up': self.gallery_canvas.yview_scroll(-1, "units")
        elif key == 'Down': self.gallery_canvas.yview_scroll(1, "units")
        elif key == 'Left': self.gallery_canvas.yview_scroll(-5, "units")
        elif key == 'Right': self.gallery_canvas.yview_scroll(5, "units")
        elif key == 'Prior': self.gallery_canvas.yview_scroll(-1, "pages")
        elif key == 'Next': self.gallery_canvas.yview_scroll(1, "pages")
        elif key == 'Home': self.gallery_canvas.yview_moveto(0.0)
        elif key == 'End': self.gallery_canvas.yview_moveto(1.0)
        else: return
        return 'break'

    # --- Core App Actions ---
    def _add_prompt_to_history(self, prompt):
        if prompt in self.prompt_history: self.prompt_history.remove(prompt) 
        self.prompt_history.insert(0, prompt)
        self.prompt_history = self.prompt_history[:self.max_history_items]
        self._save_prompt_history()
    
    def _center_toplevel_window(self, toplevel_window):
        toplevel_window.update_idletasks() 
        main_win_x = self.winfo_x()
        main_win_y = self.winfo_y()
        main_win_w = self.winfo_width()
        main_win_h = self.winfo_height()
        popup_w = toplevel_window.winfo_width()
        popup_h = toplevel_window.winfo_height()
        x_pos = main_win_x + (main_win_w // 2) - (popup_w // 2)
        y_pos = main_win_y + (main_win_h // 2) - (popup_h // 2)
        toplevel_window.geometry(f"+{x_pos}+{y_pos}")

    def _show_prompt_history(self):
        if not self.prompt_history:
            custom_message_dialog(parent=self, title="Prompt History", message="No saved prompts found.", font=self.app_font)
            return

        history_window = tk.Toplevel(self)
        history_window.title("Prompt History")
        history_window.transient(self)
        history_window.grab_set()

        listbox_frame = tk.Frame(history_window, padx=5, pady=5)
        listbox_frame.pack(fill="both", expand=True)

        listbox = tk.Listbox(listbox_frame, font=self.app_font, height=15, width=100)
        scrollbar = ttk.Scrollbar(listbox_frame, orient="vertical", command=listbox.yview)
        listbox.config(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        listbox.pack(side="left", fill="both", expand=True)

        for prompt in self.prompt_history: listbox.insert(tk.END, prompt)

        def _on_prompt_selected(event=None):
            selection_indices = listbox.curselection()
            if not selection_indices: return
            selected_prompt = listbox.get(selection_indices[0])
            self.prompt_text_widget.delete("1.0", tk.END)
            self.prompt_text_widget.insert("1.0", selected_prompt)
            history_window.destroy()

        listbox.bind("<Double-1>", _on_prompt_selected)

        button_frame = ttk.Frame(history_window)
        button_frame.pack(fill="x", padx=5, pady=(0, 5))
        ttk.Button(button_frame, text="Select", command=_on_prompt_selected).pack(side="right")
        ttk.Button(button_frame, text="Cancel", command=history_window.destroy).pack(side="right", padx=5)

        self._center_toplevel_window(history_window)

    def _on_generate_button_click(self):
        prompt = self.prompt_text_widget.get("1.0", tk.END).strip()
        if not prompt: return custom_message_dialog(parent=self, title="Input Error", message="Please enter a prompt.",font=self.app_font)
        self._add_prompt_to_history(prompt)
        self.generate_button.config(text="Generating...", state="disabled")
        threading.Thread(target=self._run_generation_task, args=(prompt,), daemon=True).start()

    def _run_generation_task(self, prompt):
        image_url = generate_image(prompt, model=self.model_string,
                                   error_callback=lambda t, m : custom_message_dialog(parent=self,
                                                                                      title=t,
                                                                                      message=m,
                                                                                      font=self.app_font))
        if image_url:
            file_name = unique_name("dummy.png","generated")
            save_path = download_image(image_url, file_name, prompt,
                                       error_callback=lambda t, m : custom_message_dialog(parent=self,
                                                                                          title=t,
                                                                                          message=m,
                                                                                          font=self.app_font))
            if save_path:
                self.after(0, self._load_images_and_select, save_path)
        self.after(0, self.generate_button.config, {'text':"Generate", 'state':"normal"})

    def _load_images_and_select(self, path_to_select):
        self._load_images()
        self._gallery_on_thumbnail_click(path_to_select)

    def add_multiple_images_as_symlinks(self, original_paths):
        if not original_paths:
            print("DEBUG: No files selected for symlinking. Returning.")
            return
    
        for i, file_path in enumerate(original_paths):
            try:
                if not os.path.exists(file_path):
                    print(f"WARNING: Original file not found, skipping: {file_path}")
                    continue
    
                file_name = unique_name(file_path, "manual")
                dest = os.path.join(IMAGE_DIR, file_name)
    
                is_already_linked = False
                for existing_linked_file in os.listdir(IMAGE_DIR):
                    full_existing_link_path = os.path.join(IMAGE_DIR, existing_linked_file)
                    if os.path.islink(full_existing_link_path) and os.path.realpath(full_existing_link_path) == os.path.realpath(file_path):
                        print(f"DEBUG: DUPLICATE DETECTED: {file_path} is already linked as {existing_linked_file}. Skipping.")
                        is_already_linked = True
                        break
                
                if is_already_linked:
                    continue
    
                os.symlink(file_path, dest)
    
            except Exception as e:
                print(f"ERROR: Failed to add image '{os.path.basename(file_path)}' due to symlink error: {type(e).__name__}: {e}")
        
        self._load_images()

    def _manually_add_images(self):
        if self.dialog is None:
            self.dialog = ImagePickerDialog(self, self.gallery_thumbnail_max_size, self._image_dir())
        self.dialog.show(self.gallery_thumbnail_max_size)

    def _delete_image(self, path_to_delete):
        if path_to_delete and os.path.exists(path_to_delete):
            try:
                # raise ValueError("thrown for testing purposes")
                os.remove(path_to_delete)
                self.generated_image_label.config(image=None)
                self.generated_image_label.image = None
                self.current_image_path = None
                self.gallery_current_selection = None
                self._load_images()
            except Exception as e:
                custom_message_dialog(parent=self, title="Deletion Error", message=f"Failed to delete {e}", font=self.app_font)

    def _delete_selected_image(self):
        self._delete_image(self.gallery_current_selection)

    def _set_current_as_wallpaper(self):
        if not self.current_image_path:
            return custom_message_dialog(parent=self, title="Wallpaper Error", message="No image selected.", font=self.app_font)
        set_wallpaper(self.current_image_path)


if __name__ == "__main__":
    app = WallpaperApp()
    app.mainloop()
