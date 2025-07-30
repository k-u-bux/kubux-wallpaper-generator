import os
import time
import queue
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
from tkinter import TclError
from PIL import Image, ImageTk
from together import Together
from dotenv import load_dotenv
import platform
import uuid
import threading
import tkinter.font as tkFont
import json
import requests
import base64
import secrets
from datetime import datetime
import hashlib
import shutil
from collections import OrderedDict

BG_COLOR="#d9d9d9" # matches the bg of tk frames

# Load environment variables
load_dotenv()
# --- Configuration ---
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
if not TOGETHER_API_KEY:
    messagebox.showerror("API Key Error", "TOGETHER_API_KEY not found in .env file or environment variables.")
    exit()

HOME_DIR = os.path.expanduser('~')
CONFIG_DIR = os.path.join(HOME_DIR, ".config", "kubux-wallpaper-generator")
CACHE_DIR = os.path.join(HOME_DIR, ".cache", "kubux-wallpaper-generator")
THUMBNAIL_CACHE_ROOT = os.path.join(CACHE_DIR, "thumbnails")
DOWNLOAD_DIR = os.path.join(HOME_DIR, "Pictures", "kubux-wallpaper-generator")
IMAGE_DIR = os.path.join(CONFIG_DIR, "images")
DEFAULT_THUMBNAIL_DIM = 192
PROMPT_HISTORY_FILE = os.path.join(CONFIG_DIR, "prompt_history.json")
APP_SETTINGS_FILE = os.path.join(CONFIG_DIR, "app_settings.json")    

os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(THUMBNAIL_CACHE_ROOT, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

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
        PIL_CACHE[cache_key] = full_image;
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


# --- Wallpaper Setting Functions (Platform-Specific) ---
def set_wallpaper(image_path):
    system = platform.system()
    try:
        abs_path = os.path.abspath(image_path)
        if system == "Windows":
            import ctypes
            SPI_SETDESKWALLPAPER = 20
            ctypes.windll.user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, abs_path, 3)
            return True
        elif system == "Darwin":
            script = f'tell application "Finder" to set desktop picture to POSIX file "{abs_path}"'
            os.system(f"osascript -e '{script}'")
            return True
        elif system == "Linux":
            os.system(f"gsettings set org.gnome.desktop.background picture-uri file://{abs_path}")
            return True
        else:
            messagebox.showwarning("Unsupported OS", f"Wallpaper setting not supported on {system}.")
            return False
    except Exception as e:
        messagebox.showerror("Wallpaper Error", f"Failed to set wallpaper: {e}")
        return False


# --- Together.ai Image Generation ---
client = Together(api_key=TOGETHER_API_KEY)

def generate_image(prompt, model="black-forest-labs/FLUX.1-pro", width=1184, height=736, steps=28):
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
        messagebox.showerror("API Error", f"Error generating image: {e}")
        return None

def download_image(url, file_name):
    try:
        save_path = os.path.join(DOWNLOAD_DIR,file_name)
        link_path = os.path.join(IMAGE_DIR,file_name)
        response = requests.get(url, stream=True)
        response.raise_for_status() 
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
        os.symlink(save_path, link_path)
        return link_path
    except Exception as e:
        messagebox.showerror("Download Error", f"Failed to download image: {e}")
        return None

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
    return file_list;


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

    SUPPORTED_IMAGE_EXTENSIONS = (
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tif', '.tiff', '.webp',
        '.ico', '.icns', '.avif', '.dds', '.msp', '.pcx', '.ppm',
        '.pbm', '.pgm', '.sgi', '.tga', '.xbm', '.xpm'
    )

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

class DirectoryThumbnailGrid(tk.Frame):
    def __init__(self, master=None, directory_path="", item_fixed_width=192, 
                 button_config_callback=None, **kwargs):
        super().__init__(master, **kwargs)
        
        self._directory_path = directory_path
        self._item_fixed_width = item_fixed_width
        self._button_config_callback = button_config_callback 
        self._known_widgets = OrderedDict() # This is a dict: hash_str -> (tk.Button, ImageTk.PhotoImage)
        self._active_widgets = {} # This is a dict: img_path -> (tk.Button, ImageTk.PhotoImage)
        self._last_known_width = -1
        self._cache_size = 2000

        self.bind("<Configure>", self._on_resize)

    def set_size_and_path(self, width, path=IMAGE_DIR):
        self._directory_path = path;
        self._item_fixed_width = width;
        self.regrid();

    def get_button(self, img_path, width):
        cache_key = uniq_file_id(img_path, width)
        target_btn, tk_image = self._known_widgets.get(cache_key, (None, None)) 
        
        if target_btn is None:
            target_btn = tk.Button(self)
            tk_image_ref = self._configure_thumbnail_button_internal(target_btn, img_path)
            assert not tk_image_ref is None
            self._known_widgets[cache_key] = (target_btn, tk_image_ref)
        else:
            assert not tk_image is None
            self._known_widgets.move_to_end(cache_key)
            
        return (target_btn, tk_image)
            
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
            target_btn, tk_image = self.get_button(img_path, self._item_fixed_width)
            self._active_widgets[img_path] = (target_btn, tk_image)
            
        self._perform_grid_layout() 

    def _on_resize(self, event=None):
        self.update_idletasks()
        current_width = self.winfo_width() 

        if event is not None and event.width > 0:
            current_width = event.width
            
        if current_width <= 0 or current_width == self._last_known_width:
            return

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
            self._perform_grid_layout() 

    def _calculate_columns(self, frame_width):
        if frame_width <= 0: return 1
        item_total_occupancy_width = self._item_fixed_width + (2 * 2) 
        buffer_for_gutters_and_edges = 10 
        available_width_for_items = frame_width - buffer_for_gutters_and_edges
        if available_width_for_items <= 0: return 1
        calculated_cols = max(1, available_width_for_items // item_total_occupancy_width)
        return min(calculated_cols, 10)

    def _perform_grid_layout(self):
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
        
        self.update_idletasks()

        while len( self._known_widgets ) > self._cache_size:
            self._known_widgets.popitem(last=False)
        
    def _configure_thumbnail_button_internal(self, btn, img_path):
        thumbnail_pil = get_or_make_thumbnail(img_path, self._item_fixed_width)
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
        for btn, _ in self._known_widgets.values(): 
            if btn is not None and btn.winfo_exists():
                btn.image = None
                btn.destroy() 
        self._known_widgets.clear()
        super().destroy()


class LongMenu(tk.Toplevel):
    def __init__(self, master, default_option, other_options, font=None, x_pos=None, y_pos=None):
        super().__init__(master)
        self.overrideredirect(True) # Remove window decorations (title bar, borders)
        self.transient(master)      # Tie to master window
        # self.grab_set()             # Make it modal, redirect all input here

        self.result = default_option
        self.options = other_options

        self.app_font = font if font else ("TkDefaultFont", 12, "normal")

        self.listbox_frame = ttk.Frame(self)
        self.listbox_frame.pack(padx=10, pady=10, fill="both", expand=True)

        self.listbox = tk.Listbox(
            self.listbox_frame,
            selectmode=tk.SINGLE,
            font=self.app_font,
            height=15
        )
        self.listbox.pack(side="left", fill="both", expand=True)

        self.scrollbar = ttk.Scrollbar(self.listbox_frame, orient="vertical", command=self.listbox.yview)
        self.scrollbar.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=self.scrollbar.set)

        # Populate the listbox
        for option_name in other_options:
            self.listbox.insert(tk.END, option_name)

        # --- Bindings ---
        self.listbox.bind("<<ListboxSelect>>", self._on_listbox_select)
        self.listbox.bind("<Double-Button-1>", self._on_double_click) # Double-click to select and close
        self.bind("<Return>", self._on_return_key) # Enter key to select and close
        self.bind("<Escape>", self._on_cancel) # Close on Escape key
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

        self.listbox.focus_set() # Set focus to the listbox for immediate keyboard navigation
        self.wait_window(self) # Make the dialog modal until it's destroyed

    def _on_listbox_select(self, event):
        self._on_ok()

    def _on_double_click(self, event):
        self._on_ok()

    def _on_return_key(self, event):
        self._on_ok()

    def _on_ok(self):
        selected_indices = self.listbox.curselection()
        if selected_indices:
            # Store the selected directory name, not the full path yet
            self.result = self.options[selected_indices[0]]
        self.destroy()

    def _on_cancel(self, event=None):
        self.result = None
        self.destroy()

    def _on_focus_out(self, event):
        # If the widget losing focus is not a child of this menu (e.g., clicking outside)
        # then close the menu.
        if self.winfo_exists() and not self.focus_get() in self.winfo_children():
            self._on_cancel()

        
class BreadCrumNavigator(ttk.Frame):
    def __init__(self, master, on_navigate_callback=None, font=None,
                 long_press_threshold_ms=400, drag_threshold_pixels=5,
                 max_menu_items=25):
        
        super().__init__(master)
        self.on_navigate_callback = on_navigate_callback
        self.current_path = "" 

        self.LONG_PRESS_THRESHOLD_MS = long_press_threshold_ms
        self.DRAG_THRESHOLD_PIXELS = drag_threshold_pixels
        self.max_menu_items = max_menu_items

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

        self.current_path = os.path.normpath(path)
        self._update_breadcrumbs()

    def _update_breadcrumbs(self):
        for widget in self.winfo_children():
            widget.destroy()

        btn_list = []
        current_display_path = self.current_path
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
            btn_list.insert( 0, btn );        
            
        for i, btn in enumerate( btn_list ):
            ttk.Label(self, text=" / ").pack(side="left")
            if i + 1 == len( btn_list ):
                 btn.bind("<ButtonPress-1>", self._on_button_press_menu)
            btn.pack(side="left")            
            
    def _trigger_navigate(self, path):
        if self.on_navigate_callback:
            self.on_navigate_callback(path)

    def _on_button_press_menu(self, event):
        self._show_subdirectory_menu( event.widget )
            
    def _on_button_press(self, event):
        self._press_start_time = time.time()
        self._press_x, self._press_y = event.x_root, event.y_root
        self._active_button = event.widget
        self._long_press_timer_id = self.after(self.LONG_PRESS_THRESHOLD_MS, 
                                                lambda: self._on_long_press_timeout(self._active_button))

    def _on_button_release(self, event):
        if self._long_press_timer_id:
            self.after_cancel(self._long_press_timer_id)
            self._long_press_timer_id = None

        if self._active_button:
            dist = (abs(event.x_root - self._press_x)**2 + abs(event.y_root - self._press_y)**2)**0.5
            if dist < self.DRAG_THRESHOLD_PIXELS:
                if (time.time() - self._press_start_time) * 1000 < self.LONG_PRESS_THRESHOLD_MS:
                    path = self._active_button.path
                    if path and self.on_navigate_callback:
                        self.on_navigate_callback(path)
            self._active_button = None

    def _on_button_motion(self, event):
        if self._active_button and self._long_press_timer_id:
            dist = (abs(event.x_root - self._press_x)**2 + abs(event.y_root - self._press_y)**2)**0.5
            if dist > self.DRAG_THRESHOLD_PIXELS:
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
            full_path = os.path.join( path, entry );
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
    def cache_widget(self):
        try:
            path_name = path_name_queue.get_nowait()
            self.gallery_grid.get_button(path_name, self.thumbnail_max_size)
            # print(f"created button for {path_name} at size {self.thumbnail_max_size}")
        except queue.Empty:
            pass
        self.after(50, self.cache_widget)
        
    def __init__(self, master, thumbnail_max_size, image_dir_path):
        super().__init__(master)
        self.withdraw()

        self.master_app = master
        self.thumbnail_max_size = thumbnail_max_size
        self.current_directory = image_dir_path

        self.selected_files = {}

        self.create_widgets()

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        self.after(0, self.cache_widget)

    def hide(self):
        self.grab_release()
        self.withdraw()

    def repaint(self):
        self.gallery_grid.set_size_and_path(self.thumbnail_max_size, self.current_directory)
        self.update_idletasks()

    def show(self, width):
        self.thumbnail_max_size = width
        self.deiconify()
        self._load_geometry()
        self.title("Add Images to Collection")
        self.transient(self.master)
        self.grab_set()
        self._browse_directory(self.current_directory)
        self.gallery_canvas.yview_moveto(0.0)
        self.after(100, self.focus_set)
 
    def create_widgets(self):
        # Thumbnail Display Area (Canvas and Scrollbar)
        self.canvas_frame = ttk.Frame(self)
        self.canvas_frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.gallery_canvas = tk.Canvas(self.canvas_frame, bg=BG_COLOR)
        self.gallery_scrollbar = ttk.Scrollbar(self.canvas_frame, orient="vertical", command=self.gallery_canvas.yview)
        self.gallery_canvas.config(yscrollcommand=self.gallery_scrollbar.set)
        
        self.gallery_scrollbar.pack(side="right", fill="y")
        self.gallery_canvas.pack(side="left", fill="both", expand=True)
        
        self.gallery_grid = DirectoryThumbnailGrid(
            self.gallery_canvas, 
            directory_path=self.current_directory,
            item_fixed_width=self.thumbnail_max_size,
            button_config_callback=self._configure_picker_button,
            bg=BG_COLOR
        )
        self.gallery_canvas.create_window((0, 0), window=self.gallery_grid, anchor="nw")

        self.gallery_canvas.bind("<Configure>", self._on_canvas_configure)
        self.gallery_grid.bind("<Configure>", lambda e: self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all")))
        
        self._bind_mousewheel(self)

        self.bind("<Up>", lambda e: self.gallery_canvas.yview_scroll(-1, "units"))
        self.bind("<Down>", lambda e: self.gallery_canvas.yview_scroll(1, "units"))
        self.bind("<Prior>", lambda e: self.gallery_canvas.yview_scroll(-1, "pages"))
        self.bind("<Next>", lambda e: self.gallery_canvas.yview_scroll(1, "pages"))

        # Control Frame (at the bottom)
        control_frame = ttk.Frame(self)
        control_frame.pack(fill="x", padx=5, pady=5)

        # Breadcrumb Frame
        self.breadcrumb_nav = BreadCrumNavigator(
            control_frame, # Parent is the control_frame
            on_navigate_callback=self._browse_directory, # This callback will update the grid and breadcrumbs
            font=self.master_app.app_font, # Use the app's font
        )
        self.breadcrumb_nav.pack(side="left", fill="x", expand=True, padx=5)

        # Right side: Add and Cancel buttons (packed in reverse order for correct visual sequence)
        ttk.Button(control_frame, text="Cancel", command=self._on_closing).pack(side="right", padx=(24,2))
        ttk.Button(control_frame, text="Add Selected", command=self._on_add_selected).pack(side="right", padx=24)

    def _configure_picker_button(self, btn, img_path, tk_thumbnail):
        """Callback to configure image picker buttons."""
        btn.config(
            cursor="hand2", 
            relief="flat", 
            borderwidth=0,
            highlightthickness=3,
            bg=BG_COLOR,
            command=lambda p=img_path: self._toggle_selection(p, btn)
        )
        
        if img_path in self.selected_files:
            btn.config(highlightbackground="blue")
        else:
            btn.config(highlightbackground=BG_COLOR)

    def _center_toplevel_window(self, toplevel_window):
        toplevel_window.update_idletasks()
        master_x = self.master_app.winfo_x()
        master_y = self.master_app.winfo_y()
        master_w = self.master_app.winfo_width()
        master_h = self.master_app.winfo_height()

        popup_w = toplevel_window.winfo_width()
        popup_h = toplevel_window.winfo_height()

        x_pos = master_x + (master_w // 2) - (popup_w // 2)
        y_pos = master_y + (master_h // 2) - (popup_h // 2)

        toplevel_window.geometry(f"+{x_pos}+{y_pos}")

    def _on_closing(self):
        """Handler for window close, saves geometry then destroys."""
        self._save_geometry()
        self.hide()

    def _save_geometry(self):
        """Saves the current dialog geometry AND current directory to app settings."""
        if hasattr(self.master_app, 'app_settings'):
            self.update_idletasks()
            geometry = self.geometry()
            self.master_app.app_settings['image_picker_dialog_geometry'] = geometry
            self.master_app.app_settings['image_picker_last_directory'] = self.current_directory
            self.master_app.save_app_settings()

    def _load_geometry(self):
        """Loads and applies saved dialog geometry from app settings."""
        if hasattr(self.master_app, 'app_settings'):
            geometry_str = self.master_app.app_settings.get('image_picker_dialog_geometry')
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
            messagebox.showerror("Error", f"Invalid directory: {path}", parent=self)
            return
        
        self.current_directory = path
        try: # Added try-except for background_worker in case it's not global or initialized yet
            background_worker.current_dir = path
        except NameError:
            print("Warning: background_worker not found. Cannot update its current_dir.")
            
        self.breadcrumb_nav.set_path(path)
        self.gallery_grid.set_size_and_path(self.thumbnail_max_size, self.current_directory)
        self.repaint()

    def _toggle_selection(self, img_path, button_widget):
        if img_path in self.selected_files:
            del self.selected_files[img_path]
            button_widget.config(highlightbackground=BG_COLOR)
        else:
            self.selected_files[img_path] = True
            button_widget.config(highlightbackground="blue")

    def _on_add_selected(self):
        """Callback for 'Add Selected' button, saves geometry and adds files."""
        self._save_geometry()
        self.master_app.add_multiple_images_as_symlinks(list(self.selected_files.keys()))
        self.hide()

    def get_selected_paths(self):
        """Returns the list of currently selected image file paths."""
        return list(self.selected_files.keys())

    def _on_canvas_configure(self, event):
        """Handles canvas resizing to adjust grid layout."""
        self.gallery_canvas.itemconfig(self.gallery_canvas.find_all()[0], width=event.width)
        self.gallery_grid._on_resize()

    def _bind_mousewheel(self, widget):
        widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
        widget.bind("<Button-4>", lambda e: self._on_mousewheel(e), add="+")
        widget.bind("<Button-5>", lambda e: self._on_mousewheel(e), add="+")

    def _on_mousewheel(self, event):
        if platform.system() == "Windows": self.gallery_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        elif event.num == 4: self.gallery_canvas.yview_scroll(-1, "units")
        elif event.num == 5: self.gallery_canvas.yview_scroll(1, "units")

        
class WallpaperApp(tk.Tk):
    def __init__(self):
        super().__init__(className="kubux-wallpaper-generator")
        self.title("kubux wallpaper generator")
        self.current_image_path = None
        self.max_history_items = 125
        self.gallery_current_selection = None
        self.gallery_thumbnail_max_size = DEFAULT_THUMBNAIL_DIM
        self._gallery_scale_update_after_id = None
        self._gallery_resize_job = None
        self._ui_scale_job = None
        self._initial_load_done = False

        self.load_prompt_history()
        self.load_app_settings()
        self.gallery_thumbnail_max_size = int(DEFAULT_THUMBNAIL_DIM * self.current_thumbnail_scale)
        self.base_font_size = 12
        self.app_font = tkFont.Font(family="TkDefaultFont", size=int(self.base_font_size * self.current_font_scale))
        self.geometry(self.initial_geometry)
        
        self.create_widgets()
        
        self.update_idletasks()
        self.set_initial_pane_positions()
        
        self.gallery_canvas.bind("<Configure>", self._gallery_on_canvas_configure)
        self.image_display_frame.bind("<Configure>", self.on_image_display_frame_resize)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.update_idletasks()
        self.dialog = None

    def image_dir(self):
        if hasattr(self, 'app_settings'):
            saved_dir = self.app_settings.get('image_picker_last_directory')
            if saved_dir and os.path.isdir(saved_dir):
                return  saved_dir

        default_dir = os.path.expanduser(os.path.join('~', 'Pictures'))
        if not os.path.isdir(default_dir):
            default_dir = os.path.expanduser('~')
        # print(f"image_dir = {default_dir}")
        return default_dir
        
    def load_prompt_history(self):
        try:
            if os.path.exists(PROMPT_HISTORY_FILE):
                with open(PROMPT_HISTORY_FILE, 'r') as f:
                    self.prompt_history = json.load(f)
            else: self.prompt_history = [] 
        except (json.JSONDecodeError, Exception): self.prompt_history = []

    def save_prompt_history(self):
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

    def save_app_settings(self):
        try:
            if not hasattr(self, 'app_settings'):
                self.app_settings = {}

            self.app_settings["ui_scale"] = self.current_font_scale
            self.app_settings["window_geometry"] = self.geometry()
            self.app_settings["thumbnail_scale"] = self.current_thumbnail_scale
            
            if hasattr(self, 'paned_window') and self.paned_window.winfo_exists():
                self.app_settings["horizontal_paned_position"] = self.paned_window.sashpos(0)
            if hasattr(self, 'vertical_paned') and self.vertical_paned.winfo_exists():
                self.app_settings["vertical_paned_position"] = self.vertical_paned.sashpos(0)

            with open(APP_SETTINGS_FILE, 'w') as f:
                json.dump(self.app_settings, f, indent=4)
        except Exception as e:
            print(f"Error saving app settings: {e}")

    def on_closing(self):
        background_worker.stop()
        self.save_prompt_history()
        self.save_app_settings() 
        self.destroy() 

    def create_widgets(self):
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

        self.image_display_frame = ttk.LabelFrame(self.vertical_paned, text="Preview")
        self.vertical_paned.add(self.image_display_frame, weight=1)

        self.generated_image_label = ttk.Label(self.image_display_frame, anchor="center")
        self.generated_image_label.pack(fill="both", expand=True, padx=5, pady=5)

        prompt_frame_outer = ttk.LabelFrame(self.vertical_paned, text="Generate New Wallpaper")
        self.vertical_paned.add(prompt_frame_outer, weight=0)

        prompt_frame_inner = tk.Frame(prompt_frame_outer)
        prompt_frame_inner.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.prompt_text_widget = tk.Text(prompt_frame_inner, height=6, wrap="word", relief="sunken", borderwidth=2, font=self.app_font)
        self.prompt_text_widget.pack(fill="both", expand=True)
        self.prompt_text_widget.bind("<Return>", lambda event: self.on_generate_button_click())

        self.gallery_canvas = tk.Canvas(thumbnail_frame_outer)
        self.gallery_scrollbar = ttk.Scrollbar(thumbnail_frame_outer, orient="vertical", command=self.gallery_canvas.yview)
        self.gallery_canvas.config(yscrollcommand=self.gallery_scrollbar.set)
        self.gallery_scrollbar.pack(side="right", fill="y")
        self.gallery_canvas.pack(side="left", fill="both", expand=True)
        
        self.gallery_grid = DirectoryThumbnailGrid(
            self.gallery_canvas, 
            directory_path=IMAGE_DIR,
            item_fixed_width=self.gallery_thumbnail_max_size,
            button_config_callback=self._gallery_configure_button,
            bg=BG_COLOR
        )
        self.gallery_canvas.create_window((0, 0), window=self.gallery_grid, anchor="nw")
        
        self._gallery_bind_mousewheel(self)

        self.gallery_canvas.bind("<Key>", self._gallery_on_key_press)
        self.gallery_canvas.bind("<Enter>", lambda e: self.gallery_canvas.focus_set())
        self.gallery_canvas.bind("<Leave>", lambda e: self.focus_set())

        self.gallery_grid.bind("<Configure>", lambda e: self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all")))

        generate_btn_frame = tk.Frame(controls_frame)
        generate_btn_frame.grid(row=0, column=0, sticky="w")
        self.generate_button = ttk.Button(generate_btn_frame, text="Generate", command=self.on_generate_button_click)
        self.generate_button.pack(side="left", padx=(2,24))
        self.history_button = ttk.Button(generate_btn_frame, text="History", command=self._show_prompt_history)
        self.history_button.pack(side="left")

        sliders_frame = tk.Frame(controls_frame)
        sliders_frame.grid(row=0, column=2)
        ttk.Label(sliders_frame, text="UI Size:").pack(side="left")

        self.scale_slider = tk.Scale(
            sliders_frame, from_=0.5, to=2.5, orient="horizontal", 
            resolution=0.1, showvalue=0
        )
        self.scale_slider.set(self.current_font_scale)
        self.scale_slider.config(command=self.update_ui_scale)
        self.scale_slider.pack(side="left")
        
        ttk.Label(sliders_frame, text="Thumb Size:", padding="20 0 0 0").pack(side="left")
        
        self.thumbnail_scale_slider = tk.Scale(
            sliders_frame, from_=0.5, to=2.5, orient="horizontal",
            resolution=0.1, showvalue=0
        )
        self.thumbnail_scale_slider.set(self.current_thumbnail_scale)
        self.thumbnail_scale_slider.config(command=self._gallery_update_thumbnail_scale_callback)
        self.thumbnail_scale_slider.pack(side="left")

        action_btn_frame = tk.Frame(controls_frame)
        action_btn_frame.grid(row=0, column=4, sticky="e")
        ttk.Button(action_btn_frame, text="Delete", command=self.delete_selected_image).pack(side="left", padx=24)
        ttk.Button(action_btn_frame, text="Add", command=self.manually_add_images).pack(side="left", padx=24)
        ttk.Button(action_btn_frame, text="Set Wallpaper", command=self.set_current_as_wallpaper).pack(side="left", padx=(24,2))

        users_images = self.image_dir()
        self.dialog = ImagePickerDialog(self, self.gallery_thumbnail_max_size, users_images)
        background_worker.run(users_images, self.gallery_thumbnail_max_size)
        background_worker.pause()
        self.after(3000, background_worker.resume)
 
    def _gallery_configure_button(self, btn, img_path, tk_thumbnail):
        """Callback to configure gallery buttons."""
        btn.config(
            cursor="hand2", 
            relief="flat", 
            borderwidth=0,
            bg=BG_COLOR,
            command=lambda p=img_path: self._gallery_on_thumbnail_click(p)
        )

    def set_initial_pane_positions(self):
        try:
            self.paned_window.sashpos(0, self.horizontal_paned_position)
            self.vertical_paned.sashpos(0, self.vertical_paned_position)
        except (tk.TclError, IndexError): 
            pass

    def update_ui_scale(self, value):
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
        if self.current_image_path: self.display_image(self.current_image_path)
    
    def on_image_display_frame_resize(self, event):
        if self.current_image_path and event.width > 1 and event.height > 1:
            self.display_image(self.current_image_path)

    def display_image(self, image_path):
        try:
            full_img = get_full_size_image(image_path)
            fw, fh = self.generated_image_label.winfo_width(), self.generated_image_label.winfo_height()
            if fw <= 1 or fh <= 1: return
            resized_img = resize_image( full_img, fw, fh )
            photo = make_tk_image(resized_img)
            self.generated_image_label.config(image=photo)
            self.generated_image_label.image = photo 
            self.current_image_path = image_path
        except Exception as e:
            messagebox.showerror("Image Display Error", f"Could not display image: {e}")
            self.current_image_path = None
    
    # --- Gallery Methods ---
    def load_images(self):
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
        self.gallery_grid.set_size_and_path(self.gallery_thumbnail_max_size)
        self.update_idletasks()
        self._adjust_gallery_scroll_position(old_scroll_fraction)
        background_worker.current_size = self.gallery_thumbnail_max_size
        background_worker.resume()

    def _gallery_on_canvas_configure(self, event):
        if not self._initial_load_done and event.width > 1:
            self.load_images()
            self._initial_load_done = True
            
        if self._gallery_resize_job: 
            self.after_cancel(self._gallery_resize_job)
        self._gallery_resize_job = self.after(400, lambda e=event: self._do_gallery_resize_refresh(e))

    def _do_gallery_resize_refresh(self, event):
        self.gallery_canvas.itemconfig(self.gallery_canvas.find_all()[0], width=event.width)
        background_worker.pause()
        self.gallery_grid._on_resize()
        background_worker.resume()
        
    def _gallery_on_thumbnail_click(self, image_path):
        old_selection = self.gallery_current_selection
        self.gallery_current_selection = image_path
        self.display_image(image_path)
    
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
    def add_prompt_to_history(self, prompt):
        if prompt in self.prompt_history: self.prompt_history.remove(prompt) 
        self.prompt_history.insert(0, prompt)
        self.prompt_history = self.prompt_history[:self.max_history_items]
        self.save_prompt_history()
    
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
            messagebox.showinfo("Prompt History", "No saved prompts found.", parent=self)
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

    def on_generate_button_click(self):
        prompt = self.prompt_text_widget.get("1.0", tk.END).strip()
        if not prompt: return messagebox.showwarning("Input Error", "Please enter a prompt.")
        self.add_prompt_to_history(prompt)
        self.generate_button.config(text="Generating...", state="disabled")
        threading.Thread(target=self._run_generation_task, args=(prompt,), daemon=True).start()

    def _run_generation_task(self, prompt):
        image_url = generate_image(prompt)
        if image_url:
            file_name = unique_name("dummy.png","generated")
            save_path = download_image(image_url, file_name)
            if save_path:
                self.after(0, self.load_images_and_select, save_path)
        self.after(0, self.generate_button.config, {'text':"Generate", 'state':"normal"})

    def load_images_and_select(self, path_to_select):
        self.load_images()
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
        
        self.load_images()

    def manually_add_images(self):
        if self.dialog is None:
            self.dialog = ImagePickerDialog(self, self.gallery_thumbnail_max_size, self.image_dir())
        self.dialog.show(self.gallery_thumbnail_max_size)

    def delete_selected_image(self):
        path_to_delete = self.gallery_current_selection
        if path_to_delete and os.path.exists(path_to_delete):
            try:
                os.remove(path_to_delete)
                self.generated_image_label.config(image=None)
                self.generated_image_label.image = None
                self.current_image_path = None
                self.gallery_current_selection = None
                self.load_images()
            except Exception as e: messagebox.showerror("Deletion Error", f"Failed to delete {e}")

    def set_current_as_wallpaper(self):
        if not self.current_image_path: return messagebox.showwarning("Wallpaper Error", "No image selected.")
        set_wallpaper(self.current_image_path)


if __name__ == "__main__":
    app = WallpaperApp()
    app.mainloop()
