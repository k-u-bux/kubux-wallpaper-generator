import os
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
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


# --- Caching thumbnails ---
GLOBAL_PIL_THUMBNAIL_CACHE = {}

def get_or_make_thumbnail(img_path, thumbnail_max_size):
    try:
        mtime = os.path.getmtime(img_path)
    except FileNotFoundError:
        print(f"Error: Original image file not found for thumbnail generation: {img_path}")
        return None
    except Exception as e:
        print(f"Warning: Could not get modification time for {img_path}: {e}. Using a default value.")
        mtime = 0

    in_memory_cache_key = f"{img_path}_{thumbnail_max_size}_{mtime}"

    if in_memory_cache_key in GLOBAL_PIL_THUMBNAIL_CACHE:
        return GLOBAL_PIL_THUMBNAIL_CACHE.get(in_memory_cache_key)

    thumbnail_size_str = str(thumbnail_max_size)
    thumbnail_cache_subdir = os.path.join(THUMBNAIL_CACHE_ROOT, thumbnail_size_str)
    os.makedirs(thumbnail_cache_subdir, exist_ok=True)

    filename_hash = hashlib.sha256(in_memory_cache_key.encode('utf-8')).hexdigest()
    cached_thumbnail_path = os.path.join(thumbnail_cache_subdir, f"{filename_hash}.png")

    pil_image_thumbnail = None

    try:
        if os.path.exists(cached_thumbnail_path):
            pil_image_thumbnail = Image.open(cached_thumbnail_path)
        else:
            full_img = Image.open(img_path)
            full_img.thumbnail((thumbnail_max_size, thumbnail_max_size))
            pil_image_thumbnail = full_img
            pil_image_thumbnail.save(cached_thumbnail_path) 

        GLOBAL_PIL_THUMBNAIL_CACHE[in_memory_cache_key] = pil_image_thumbnail
        
        return pil_image_thumbnail

    except Exception as e:
        print(f"Error loading/creating thumbnail for {img_path}: {e}")
        if os.path.exists(cached_thumbnail_path):
            try:
                os.remove(cached_thumbnail_path)
                print(f"Removed corrupted thumbnail: {cached_thumbnail_path}")
            except Exception as ex:
                print(f"Could not remove corrupted thumbnail file: {ex}")
        return None
    


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
    """
    Generates a unique filename using timestamp, category, and a random part,
    preserving the original extension. Ensures filename is suitable for various file systems by sanitizing.
    """
    _, ext = os.path.splitext(original_path)
    # Using microseconds for very high uniqueness in the timestamp
    timestamp_str = datetime.now().strftime('%Y-%m-%d-%H-%M-%S-%f')

    # Generate a unique, random string.
    # We use secrets.token_urlsafe(16) which produces 16 random bytes, then URL-safe Base64 encodes them.
    # This *can* produce '/' and '+' characters, which are problematic for filenames.
    random_raw_part = secrets.token_urlsafe(18)

    # --- CRITICAL FIX: Sanitize the random part to remove/replace problematic filename characters ---
    # Replace '/' with '_' and '+' with '-' to make the string filesystem-safe.
    sanitized_random_part = random_raw_part.replace('/', '_').replace('+', '-')
    # ------------------------------------------------------------------------------------------------

    # Combine parts to form the base filename
    base_name = f"{timestamp_str}_{category}_{sanitized_random_part}"

    # Return the full unique filename with the original extension
    return f"{base_name}{ext}"

# --- GUI Application ---

# Assuming 'unique_name' is defined globally before this class
# Assuming 'IMAGE_DIR' is defined globally before this class
# Assuming 'datetime', 'os', 'tkinter', 'ttk', 'Image', 'ImageTk', 'platform', 'messagebox', 'filedialog' are imported

class ImagePickerDialog(tk.Toplevel):
    def __init__(self, master, thumbnail_max_size, image_dir_path):
        super().__init__(master)
        self.title("Add Images to Collection")
        self.transient(master)
        self.grab_set()

        self.master_app = master
        self.thumbnail_max_size = thumbnail_max_size
        self.image_dir_path = image_dir_path

        self.current_directory = ""
        if hasattr(self.master_app, 'app_settings'):
            saved_dir = self.master_app.app_settings.get('image_picker_last_directory')
            if saved_dir and os.path.isdir(saved_dir):
                self.current_directory = saved_dir
            else:
                self.current_directory = os.path.expanduser(os.path.join('~', 'Pictures'))
                if not os.path.isdir(self.current_directory):
                    self.current_directory = os.path.expanduser('~')
        else:
            self.current_directory = os.path.expanduser(os.path.join('~', 'Pictures'))
            if not os.path.isdir(self.current_directory):
                self.current_directory = os.path.expanduser('~')

        self.selected_files = {}
        self.image_widgets = {}

        self.create_widgets()
        self._load_geometry()
        self._browse_directory(self.current_directory)

        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        self.after(100, self.focus_set)

    def create_widgets(self):
        # Thumbnail Display Area (Canvas and Scrollbar)
        self.canvas_frame = ttk.Frame(self)
        self.canvas_frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.gallery_canvas = tk.Canvas(self.canvas_frame, bg="lightgrey")
        self.gallery_scrollbar = ttk.Scrollbar(self.canvas_frame, orient="vertical", command=self.gallery_canvas.yview)
        self.gallery_canvas.config(yscrollcommand=self.gallery_scrollbar.set)
        
        self.gallery_scrollbar.pack(side="right", fill="y")
        self.gallery_canvas.pack(side="left", fill="both", expand=True)
        
        self.gallery_grid_frame = tk.Frame(self.gallery_canvas, bg="lightgrey")
        self.gallery_canvas.create_window((0, 0), window=self.gallery_grid_frame, anchor="nw")

        self.gallery_canvas.bind("<Configure>", self._on_canvas_configure)
        self.gallery_grid_frame.bind("<Configure>", lambda e: self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all")))
        
        self._bind_mousewheel(self.gallery_canvas)
        self._bind_mousewheel(self.gallery_grid_frame)

        self.bind("<Up>", lambda e: self.gallery_canvas.yview_scroll(-1, "units"))
        self.bind("<Down>", lambda e: self.gallery_canvas.yview_scroll(1, "units"))
        self.bind("<Prior>", lambda e: self.gallery_canvas.yview_scroll(-1, "pages"))
        self.bind("<Next>", lambda e: self.gallery_canvas.yview_scroll(1, "pages"))

        # Control Frame (at the bottom)
        control_frame = ttk.Frame(self)
        control_frame.pack(fill="x", padx=5, pady=5)

        # Breadcrumb Frame
        self.breadcrumb_frame = ttk.Frame(control_frame)
        self.breadcrumb_frame.pack(side="left", fill="x", expand=True, padx=5)

        # Right side: Add and Cancel buttons (packed in reverse order for correct visual sequence)
        ttk.Button(control_frame, text="Cancel", command=self._on_closing).pack(side="right")
        ttk.Button(control_frame, text="Add Selected", command=self._on_add_selected).pack(side="right", padx=2)

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
        self.destroy()

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
        self._update_breadcrumbs() # Call new method to update breadcrumbs
        self._refresh_thumbnail_grid()

    def _update_breadcrumbs(self):
        for widget in self.breadcrumb_frame.winfo_children():
            widget.destroy()

        path_parts = []
        current_path = self.current_directory
        while current_path and current_path != os.path.dirname(current_path):
            path_parts.insert(0, os.path.basename(current_path) or current_path) # Handle root path basename being empty
            current_path = os.path.dirname(current_path)
        if not path_parts: # For very root paths like '/' or 'C:\'
            path_parts = [self.current_directory] if self.current_directory else ['/']

        accumulated_path = ""
        for i, part in enumerate(path_parts):
            if i == 0:
                # For Windows, handle drive letters correctly
                if platform.system() == "Windows" and self.current_directory and self.current_directory[1:3] == ':\\':
                    accumulated_path = self.current_directory[:3]
                else:
                    accumulated_path = os.path.sep if part == '' else os.path.join(os.path.sep, part) # Handle root '/'
            else:
                accumulated_path = os.path.join(accumulated_path, part)
            
            # Use os.path.normpath to clean up redundant separators if any
            display_path = os.path.normpath(accumulated_path)
            # Special handling for root paths to display correctly, e.g. "C:\" or "/"
            if platform.system() == "Windows" and len(display_path) == 2 and display_path[1] == ':':
                 display_path += os.path.sep # Add backslash for drive letters C: -> C:\
            elif display_path == '': # For Linux root /
                display_path = os.path.sep

            btn_text = part if part != '' else os.path.sep # Display '/' for root part
            
            if i < len(path_parts) - 1: # Not the last segment
                btn = ttk.Button(self.breadcrumb_frame, text=btn_text, command=lambda p=display_path: self._browse_directory(p))
                btn.pack(side="left")
                ttk.Label(self.breadcrumb_frame, text=" > ").pack(side="left")
            else: # Last segment (current directory)
                current_dir_btn = ttk.Menubutton(self.breadcrumb_frame, 
                                                 text=btn_text, 
                                                 direction="above" )
                current_dir_btn.pack(side="left")
                current_dir_menu = tk.Menu(current_dir_btn, tearoff=0, font=self.master_app.app_font)
                current_dir_btn.config(menu=current_dir_menu)

                subdirs = sorted([d for d in os.listdir(self.current_directory) if os.path.isdir(os.path.join(self.current_directory, d))])
                if subdirs:
                    for subdir in subdirs:
                        subdir_path = os.path.join(self.current_directory, subdir)
                        current_dir_menu.add_command(label=subdir, command=lambda p=subdir_path: self._browse_directory(p))
                else:
                    current_dir_menu.add_command(label="(No subdirectories)", state="disabled")


    def _refresh_thumbnail_grid(self):
        for widget in self.gallery_grid_frame.winfo_children():
            widget.destroy()
        self.image_widgets.clear()

        files_in_dir = [os.path.join(self.current_directory, f) for f in os.listdir(self.current_directory)]
        image_files = sorted([f for f in files_in_dir if f.lower().endswith(('.png', '.jpg', '.jpeg')) and os.path.isfile(f)])
        thumbnail_cols = self._calculate_columns()
        if thumbnail_cols == 0: thumbnail_cols = 1 # Ensure at least one column

        # Add directory entries first
        current_grid_idx = 0
        for img_path in image_files:
            row, col = divmod(current_grid_idx, thumbnail_cols)
            
            thumbnail = ImageTk.PhotoImage(get_or_make_thumbnail(img_path, self.thumbnail_max_size))
            if thumbnail:
                btn = tk.Button(self.gallery_grid_frame, image=thumbnail, 
                                command=lambda p=img_path, current_btn=None: self._toggle_selection(p, self.image_widgets[p] if p in self.image_widgets else current_btn),
                                cursor="hand2", relief="flat", borderwidth=0, 
                                highlightthickness=3, highlightbackground="lightgrey")
                btn.image = thumbnail
                btn.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")
                self.image_widgets[img_path] = btn

                self._bind_mousewheel(btn)

                if img_path in self.selected_files:
                    self._highlight_selection(btn, True)
            self.gallery_grid_frame.grid_columnconfigure(col, weight=1)
            current_grid_idx += 1

        self.gallery_grid_frame.update_idletasks()
        self.gallery_canvas.config(scrollregion=self.gallery_canvas.bbox("all"))

    def _get_thumbnail(self, img_path):
        """Generates a thumbnail for the given image path."""
        try:
            full_img = Image.open(img_path)
            full_img.thumbnail((self.thumbnail_max_size, self.thumbnail_max_size))
            tk_thumbnail = ImageTk.PhotoImage(full_img)
            return tk_thumbnail
        except Exception as e:
            print(f"Error creating thumbnail for {img_path}: {e}")
            return None

    def _toggle_selection(self, img_path, button_widget):
        """Toggles the selection state of an image."""
        if img_path in self.selected_files:
            del self.selected_files[img_path]
            self._highlight_selection(button_widget, False)
        else:
            self.selected_files[img_path] = True
            self._highlight_selection(button_widget, True)

    def _highlight_selection(self, button_widget, is_selected):
        """Applies or removes the selection highlight."""
        if is_selected:
            button_widget.config(relief="flat", borderwidth=0, highlightthickness=3, highlightbackground="blue")
        else:
            button_widget.config(relief="flat", borderwidth=0, highlightthickness=3, highlightbackground="lightgrey")

    def _on_add_selected(self):
        """Callback for 'Add Selected' button, saves geometry and adds files."""
        self._save_geometry()
        self.master_app.add_multiple_images_as_symlinks(list(self.selected_files.keys()))
        self.destroy()

    def get_selected_paths(self):
        """Returns the list of currently selected image file paths."""
        return list(self.selected_files.keys())

    def _on_canvas_configure(self, event):
        """Handles canvas resizing to adjust grid layout."""
        self.gallery_canvas.itemconfig(self.gallery_canvas.find_all()[0], width=event.width)
        
        new_columns = self._calculate_columns()
        if new_columns != self.gallery_grid_frame.grid_size()[0] and (self.image_widgets or os.listdir(self.current_directory)):
             self._refresh_thumbnail_grid()

    def _calculate_columns(self):
        """Calculates how many columns of thumbnails can fit in the canvas."""
        available_width = self.gallery_canvas.winfo_width()
        if available_width <= 1: return 1
        thumb_width_with_padding = self.thumbnail_max_size + 4
        return max(1, (available_width - 20) // thumb_width_with_padding)

    def _bind_mousewheel(self, widget):
        """Binds mousewheel events for scrolling within the ImagePickerDialog's canvas."""
        def on_mousewheel_local(event):
            if platform.system() == "Windows": 
                self.gallery_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            elif event.num == 4:
                self.gallery_canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.gallery_canvas.yview_scroll(1, "units")
        
        widget.bind("<MouseWheel>", on_mousewheel_local, add="+")
        widget.bind("<Button-4>", lambda e: on_mousewheel_local(e), add="+")
        widget.bind("<Button-5>", lambda e: on_mousewheel_local(e), add="+")


class WallpaperApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("kubux wallpaper generator")

        try:
            self.tk.call('wm', 'class', self._w, 'io.github.kubux.wallpaper-generator')
        except tk.TclError: pass
        
        self.current_image_path = None
        self.max_history_items = 25
        self.gallery_image_files = []
        self.gallery_thumbnails_cache = {}
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
        """Loads application settings from a JSON file, assigning the full dictionary to self.app_settings."""
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
        """Saves application settings to a JSON file, preserving existing keys."""
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
        self.gallery_grid_frame = tk.Frame(self.gallery_canvas)
        self.gallery_canvas.create_window((0, 0), window=self.gallery_grid_frame, anchor="nw")
        
        self._gallery_bind_mousewheel(self)
        
        self.gallery_canvas.bind("<Key>", self._gallery_on_key_press)
        self.gallery_canvas.bind("<Enter>", lambda e: self.gallery_canvas.focus_set())
        self.gallery_canvas.bind("<Leave>", lambda e: self.focus_set())

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
            full_img = Image.open(image_path)
            fw, fh = self.generated_image_label.winfo_width(), self.generated_image_label.winfo_height()
            if fw <= 1 or fh <= 1: return
            
            img_aspect = full_img.width / full_img.height
            frame_aspect = fw / fh
            
            if img_aspect > frame_aspect:
                nw = fw - 10
                nh = int(nw / img_aspect)
            else:
                nh = fh - 10
                nw = int(nh * img_aspect)
                
            resized_img = full_img.resize((max(1, nw), max(1, nh)), Image.LANCZOS)
            photo = ImageTk.PhotoImage(resized_img)
            self.generated_image_label.config(image=photo)
            self.generated_image_label.image = photo 
            self.current_image_path = image_path
        except Exception as e:
            messagebox.showerror("Image Display Error", f"Could not display image: {e}")
            self.current_image_path = None
    
    # --- Gallery Methods ---
    def load_images(self):
        try:
            self.gallery_image_files = sorted([os.path.join(IMAGE_DIR, f) for f in os.listdir(IMAGE_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg'))], reverse=True)
        except OSError:
            self.gallery_image_files = []
        self._gallery_refresh_display()

    def _gallery_refresh_display(self):
        for widget in self.gallery_grid_frame.winfo_children():
            widget.destroy()
        try:
            old_num_columns = self.gallery_grid_frame.grid_size()[0]
            for i in range(old_num_columns):
                self.gallery_grid_frame.grid_columnconfigure(i, weight=0)
        except IndexError: pass
        if not self.gallery_image_files:
            self.gallery_grid_frame.update_idletasks()
            self.gallery_canvas.config(scrollregion=self.gallery_canvas.bbox("all"))
            return
        thumbnail_cols = self._gallery_calculate_columns()
        self.gallery_grid_frame.grid_columnconfigure(0, weight=1)
        self.gallery_grid_frame.grid_columnconfigure(thumbnail_cols + 1, weight=1)
        for i, img_path in enumerate(self.gallery_image_files):
            row, col = divmod(i, thumbnail_cols)
            thumbnail = ImageTk.PhotoImage(get_or_make_thumbnail(img_path, self.gallery_thumbnail_max_size))
            if thumbnail:
                btn = tk.Button(self.gallery_grid_frame, image=thumbnail, command=lambda p=img_path: self._gallery_on_thumbnail_click(p),
                                cursor="hand2", relief="flat", borderwidth=0)
                btn.image = thumbnail
                btn.grid(row=row, column=col + 1, padx=2, pady=2)
                if self.gallery_current_selection == img_path:
                    btn.config(relief="solid", borderwidth=2, highlightbackground="blue")
        self.gallery_grid_frame.update_idletasks()
        self.gallery_canvas.config(scrollregion=self.gallery_canvas.bbox("all"))

    def _gallery_update_thumbnail_scale_callback(self, value):
        if self._gallery_scale_update_after_id: self.after_cancel(self._gallery_scale_update_after_id)
        self._gallery_scale_update_after_id = self.after(400, lambda: self._gallery_do_scale_update(float(value)))

    def _gallery_do_scale_update(self, scale):
        self.current_thumbnail_scale = scale
        self.gallery_thumbnail_max_size = int(DEFAULT_THUMBNAIL_DIM * scale)
        self.gallery_thumbnails_cache.clear()
        self._gallery_refresh_display()

    def _gallery_on_canvas_configure(self, event):
        if not self._initial_load_done and event.width > 1:
            self.load_images()
            self._initial_load_done = True
            
        if self._gallery_resize_job: 
            self.after_cancel(self._gallery_resize_job)
        self._gallery_resize_job = self.after(400, lambda e=event: self._do_gallery_resize_refresh(e))

    def _do_gallery_resize_refresh(self, event):
        self.gallery_canvas.itemconfig(self.gallery_canvas.find_all()[0], width=event.width)
        try: current_columns = self.gallery_grid_frame.grid_size()[0] - 2
        except IndexError: current_columns = 0
        new_columns = self._gallery_calculate_columns()
        if new_columns != current_columns and new_columns > 0: self._gallery_refresh_display()

    def _gallery_calculate_columns(self):
        available_width = self.gallery_canvas.winfo_width()
        if available_width <= 1: return 1
        thumb_width_with_padding = self.gallery_thumbnail_max_size + 4 
        return max(1, (available_width - 20) // thumb_width_with_padding)

    def _gallery_on_thumbnail_click(self, image_path):
        old_selection = self.gallery_current_selection
        self.gallery_current_selection = image_path
        if old_selection != self.gallery_current_selection: self._gallery_update_selection_highlight(old_selection, image_path)
        self.display_image(image_path)

    def _gallery_update_selection_highlight(self, old_path, new_path):
        for widget in self.gallery_grid_frame.winfo_children():
            if isinstance(widget, tk.Button):
                try: cmd_str = str(widget['command'])
                except (tk.TclError, KeyError): self._gallery_refresh_display(); return
                if old_path and old_path in cmd_str: widget.config(relief="flat", borderwidth=0)
                if new_path and new_path in cmd_str: widget.config(relief="solid", borderwidth=2, highlightbackground="blue")

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
           """
           Adds multiple images to IMAGE_DIR as symlinks, ensuring unique names.
           This method is called by the ImagePickerDialog after selection.
           """
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
        dialog = ImagePickerDialog(self, self.gallery_thumbnail_max_size, IMAGE_DIR)
        self.wait_window(dialog)

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
