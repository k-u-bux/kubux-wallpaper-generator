# vibe coded with Gemini 2.5 Flash (2025-07-23)
# =============================================

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
from datetime import datetime # Import datetime
import math

# Load environment variables
load_dotenv()
# --- Configuration ---
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
if not TOGETHER_API_KEY:
    messagebox.showerror("API Key Error", "TOGETHER_API_KEY not found in .env file or environment variables.")
    exit()

# Use os.path.expanduser('~') for cross-platform home directory retrieval
HOME_DIR = os.path.expanduser('~')
CONFIG_DIR = os.path.join(HOME_DIR, ".config", "kubux-wallpaper-generator") # More robust for path joining
IMAGE_DIR = os.path.join(CONFIG_DIR, "images")
DEFAULT_THUMBNAIL_DIM = 192 # Changed back to 192 as requested
PROMPT_HISTORY_FILE = os.path.join(CONFIG_DIR, "prompt_history.json")
APP_SETTINGS_FILE = os.path.join(CONFIG_DIR, "app_settings.json")    
MINIMAL_GALLERY_HEIGHT = 20 # Height of the gallery when no thumbnails are present (just a small strip)

# Ensure configuration and image directories exist
os.makedirs(IMAGE_DIR, exist_ok=True) # This will create CONFIG_DIR if it doesn't exist, then IMAGE_DIR

# Ensure image directory exists
os.makedirs(IMAGE_DIR, exist_ok=True)

# --- Wallpaper Setting Functions (Platform-Specific) ---
def set_wallpaper(image_path):
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes
            SPI_SETDESKWALLPAPER = 20
            SPIF_UPDATEINIFILE = 0x01
            SPIF_SENDWININICHANGE = 0x02
            ctypes.windll.user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, image_path, SPIF_UPDATEINIFILE | SPIF_SENDWININICHANGE)
            return True
        elif system == "Darwin": # macOS
            # macOS requires AppleScript
            script = f'tell application "Finder" to set desktop picture to POSIX file "{image_path}"'
            os.system(f"osascript -e '{script}'")
            return True
        elif system == "Linux":
            # For GNOME desktop environments (most common)
            os.system(f"gsettings set org.gnome.desktop.background picture-uri file://{image_path}")
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
        image_url = response.data[0].url
        return image_url
    except Exception as e:
        messagebox.showerror("API Error", f"Error generating image: {e}")
        return None

def download_image(url, save_path):
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status() 
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        messagebox.showerror("Download Error", f"Failed to download image: {e}")
        return False

# --- Grid Gallery Widget (auto-columns based on width) ---
class GridGallery(tk.Frame):
    def __init__(self, parent, on_image_click=None):
        super().__init__(parent)
        self.on_image_click = on_image_click
        
        self.image_files = []
        self.thumbnails_cache = {}
        self.thumbnail_dimensions_cache = {}
        self.thumbnail_max_size = DEFAULT_THUMBNAIL_DIM
        self.current_selection = None
        
        # Performance improvements: f) Debouncing for thumbnail scale changes
        self._scale_update_after_id = None
        
        self.create_widgets()
        
    def create_widgets(self):
        # Canvas and scrollbar for the grid
        self.canvas = tk.Canvas(self, bg="lightgray")
        self.canvas.pack(side="left", fill="both", expand=True)
        
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollbar.pack(side="right", fill="y")
        
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # Frame inside canvas for the grid
        self.grid_frame = tk.Frame(self.canvas, bg="lightgray")
        self.canvas_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        
        # Bind events
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())
        
        # Performance improvements: e) Mouse wheel binding - Fixed: bind to gallery frame AND canvas
        self.bind_mousewheel_recursively(self)
        
        # Keyboard bindings - Fixed: b) All navigation keys working with proper speeds
        self.canvas.bind("<Up>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Down>", lambda e: self.canvas.yview_scroll(1, "units"))
        self.canvas.bind("<Left>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Right>", lambda e: self.canvas.yview_scroll(1, "units"))
        self.canvas.bind("<Prior>", lambda e: self.canvas.yview_scroll(-5, "units"))  # Page Up - faster
        self.canvas.bind("<Next>", lambda e: self.canvas.yview_scroll(5, "units"))   # Page Down - faster
        self.canvas.bind("<Home>", lambda e: self.canvas.yview_moveto(0))
        self.canvas.bind("<End>", lambda e: self.canvas.yview_moveto(1))
        
        self.canvas.config(takefocus=True)
        
    def bind_mousewheel_recursively(self, widget):
        """Performance improvements: e) Bind mousewheel events to widget and all its children."""
        widget.bind("<MouseWheel>", self.on_mousewheel)
        widget.bind("<Button-4>", lambda e: self.on_mousewheel(e, delta=-1))
        widget.bind("<Button-5>", lambda e: self.on_mousewheel(e, delta=1))
        
        # Bind to all children as well
        for child in widget.winfo_children():
            self.bind_mousewheel_recursively(child)
        
    def calculate_columns(self):
        """Calculate number of columns based on available width and thumbnail size."""
        available_width = self.canvas.winfo_width()
        if available_width <= 1:
            return 1
        
        # Account for padding and scrollbar
        effective_width = available_width - 20  # scrollbar + padding
        thumb_width_with_padding = self.thumbnail_max_size + 4  # 2px padding each side
        
        columns = max(1, effective_width // thumb_width_with_padding)
        return columns
        
    def set_thumbnail_scale(self, scale):
        """Performance improvements: g) Update thumbnail scale with debouncing to avoid jagged experience."""
        # Cancel any pending update
        if self._scale_update_after_id:
            self.after_cancel(self._scale_update_after_id)
            
        # Schedule the actual update with a small delay
        self._scale_update_after_id = self.after(150, lambda: self._do_scale_update(scale))
        
    def _do_scale_update(self, scale):
        """Actually perform the scale update."""
        self._scale_update_after_id = None
        self.thumbnail_max_size = int(DEFAULT_THUMBNAIL_DIM * scale)
        self.thumbnails_cache.clear()
        self.thumbnail_dimensions_cache.clear()
        self.refresh_display()
        
    def get_thumbnail_dimensions(self, img_path):
        """Get thumbnail dimensions from cache or calculate them."""
        cache_key = f"{img_path}_{self.thumbnail_max_size}"
        
        if cache_key not in self.thumbnail_dimensions_cache:
            try:
                img = Image.open(img_path)
                img.thumbnail((self.thumbnail_max_size, self.thumbnail_max_size))
                self.thumbnail_dimensions_cache[cache_key] = (img.width, img.height)
            except Exception as e:
                print(f"Error calculating thumbnail dimensions for {img_path}: {e}")
                return None
                
        return self.thumbnail_dimensions_cache.get(cache_key)
        
    def get_thumbnail(self, img_path):
        """Get thumbnail from cache or create it."""
        cache_key = f"{img_path}_{self.thumbnail_max_size}"
        
        if cache_key not in self.thumbnails_cache:
            try:
                img = Image.open(img_path)
                img.thumbnail((self.thumbnail_max_size, self.thumbnail_max_size))
                photo = ImageTk.PhotoImage(img)
                self.thumbnails_cache[cache_key] = photo
                self.thumbnail_dimensions_cache[cache_key] = (img.width, img.height)
            except Exception as e:
                print(f"Error loading thumbnail for {img_path}: {e}")
                return None
                
        return self.thumbnails_cache.get(cache_key)
        
    def load_images(self, image_paths):
        """Load new image list and refresh display."""
        self.image_files = image_paths
        self.current_selection = None
        self.refresh_display()
        
    def refresh_display(self):
        """Clear and rebuild the grid display."""
        # Clear existing widgets
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
            
        if not self.image_files:
            return
            
        # Calculate columns based on current width
        columns = self.calculate_columns()
        
        # Calculate grid layout
        for i, img_path in enumerate(self.image_files):
            row = i // columns
            col = i % columns
            
            thumbnail = self.get_thumbnail(img_path)
            if thumbnail:
                # Create button with thumbnail
                btn = tk.Button(
                    self.grid_frame,
                    image=thumbnail,
                    command=lambda path=img_path: self.on_thumbnail_click(path),
                    cursor="hand2",
                    relief="flat",
                    borderwidth=0
                )
                btn.image = thumbnail  # Keep reference
                btn.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")
                
                # Highlight if selected
                if self.current_selection == img_path:
                    btn.config(relief="solid", borderwidth=2, highlightbackground="blue")
                    
        # Configure grid weights for centering
        for col in range(columns):
            self.grid_frame.grid_columnconfigure(col, weight=1)
            
        # Update canvas scroll region
        self.grid_frame.update_idletasks()
        self.canvas.config(scrollregion=self.canvas.bbox("all"))
        
        # Performance improvements: e) Re-bind mousewheel to newly created buttons
        self.bind_mousewheel_recursively(self.grid_frame)
        
    def on_canvas_configure(self, event):
        """Handle canvas resize."""
        # Update the grid frame width to match canvas
        canvas_width = event.width
        self.canvas.itemconfig(self.canvas_window, width=canvas_width)
        # Refresh display to recalculate columns
        self.refresh_display()
        
    def on_mousewheel(self, event, delta=None):
        """Handle mouse wheel scrolling."""
        if delta is not None:  # Linux
            self.canvas.yview_scroll(delta, "units")
        elif platform.system() == "Windows":
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        else:  # macOS
            self.canvas.yview_scroll(int(-1 * event.delta), "units")
            
    def on_thumbnail_click(self, image_path):
        """Performance improvements: f) Handle thumbnail click - optimized to avoid full redraw."""
        old_selection = self.current_selection
        self.current_selection = image_path
        
        # Performance improvements: f) Only update selection highlights, not full redraw
        if old_selection != self.current_selection:
            self.update_selection_only(old_selection, self.current_selection)
        
        if self.on_image_click:
            self.on_image_click(image_path)
            
    def update_selection_only(self, old_selection, new_selection):
        """Performance improvements: f) Update only selection borders without full redraw."""
        # Update button appearances without full refresh
        for widget in self.grid_frame.winfo_children():
            if isinstance(widget, tk.Button) and hasattr(widget, 'cget'):
                # Try to get the command and extract the path
                try:
                    # This is a bit hacky but avoids storing path references
                    cmd_str = str(widget['command'])
                    
                    # Reset old selection
                    if old_selection and old_selection in cmd_str:
                        widget.config(relief="flat", borderwidth=0)
                    
                    # Highlight new selection
                    if new_selection and new_selection in cmd_str:
                        widget.config(relief="solid", borderwidth=2, highlightbackground="blue")
                        
                except (tk.TclError, KeyError):
                    # If we can't determine the path, fall back to full refresh
                    self.refresh_display()
                    return

# --- GUI Application ---
class WallpaperApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("kubux wallpaper generator")
        
        # Set application ID for GNOME
        try:
            self.tk.call('wm', 'class', self._w, 'io.github.kubux.wallpaper-generator')
        except:
            pass

        self.image_files = []
        self.current_image_path = None
        self.max_history_items = 25 

        self.load_prompt_history()
        self.load_app_settings()

        self.base_font_size = 12 
        self.app_font = tkFont.Font(family="TkDefaultFont", size=int(self.base_font_size * self.current_font_scale))

        # Get the RGB values of 'lightgray' from Tkinter
        r_16bit, g_16bit, b_16bit = self.winfo_rgb("lightgray")
        r_8bit = r_16bit // 256
        g_8bit = g_16bit // 256
        b_8bit = b_16bit // 256
        self.pil_lightgray_rgb = (r_8bit, g_8bit, b_8bit)

        self.create_widgets()
        self.load_images()
        
        self.geometry(self.initial_geometry)
        self.update_ui_scale(self.current_font_scale) 

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.image_display_frame.bind("<Configure>", self.on_image_display_frame_resize)

    def load_prompt_history(self):
        """Loads prompt history from a JSON file."""
        try:
            if os.path.exists(PROMPT_HISTORY_FILE):
                with open(PROMPT_HISTORY_FILE, 'r') as f:
                    self.prompt_history = json.load(f)
                if not isinstance(self.prompt_history, list) or \
                   not all(isinstance(item, str) for item in self.prompt_history):
                    print(f"Warning: Prompt history file '{PROMPT_HISTORY_FILE}' corrupted. Resetting.")
                    self.prompt_history = []
            else:
                self.prompt_history = [] 
        except json.JSONDecodeError as e:
            print(f"Error decoding prompt history JSON: {e}. Resetting history.")
            self.prompt_history = []
        except Exception as e:
            print(f"Unexpected error loading prompt history: {e}. Resetting history.")
            self.prompt_history = []

    def save_prompt_history(self):
        """Saves prompt history to a JSON file."""
        try:
            with open(PROMPT_HISTORY_FILE, 'w') as f:
                json.dump(self.prompt_history, f, indent=4) 
        except Exception as e:
            print(f"Error saving prompt history: {e}")

    def load_app_settings(self):
        """Loads UI scale, window geometry, thumbnail scale, and paned window position from a JSON file."""
        try:
            if os.path.exists(APP_SETTINGS_FILE):
                with open(APP_SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)
                self.current_font_scale = settings.get("ui_scale", 1.0)
                self.initial_geometry = settings.get("window_geometry", "1200x800")  # Larger default
                self.current_thumbnail_scale = settings.get("thumbnail_scale", 1.0)
                # d) Add paned window position saving/loading
                self.paned_position = settings.get("paned_position", 500)  # Default pane position
            else:
                self.current_font_scale = 1.0
                self.initial_geometry = "1200x800"
                self.current_thumbnail_scale = 1.0
                self.paned_position = 500
        except json.JSONDecodeError as e:
            print(f"Error decoding app settings JSON: {e}. Using default settings.")
            self.current_font_scale = 1.0
            self.initial_geometry = "1200x800"
            self.current_thumbnail_scale = 1.0
            self.paned_position = 500
        except Exception as e:
            print(f"Unexpected error loading app settings: {e}. Using default settings.")
            self.current_font_scale = 1.0
            self.initial_geometry = "1200x800"
            self.current_thumbnail_scale = 1.0
            self.paned_position = 500

    def save_app_settings(self):
        """Saves UI scale, window geometry, thumbnail scale, and paned window position to a JSON file."""
        settings = {
            "ui_scale": self.current_font_scale,
            "window_geometry": self.geometry(),
            "thumbnail_scale": self.current_thumbnail_scale,
            # d) Save paned window position
            "paned_position": self.paned_window.sash_coord(0)[0]  # Get horizontal position
        }
        try:
            with open(APP_SETTINGS_FILE, 'w') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            print(f"Error saving app settings: {e}")

    def on_closing(self):
        """Handles application shutdown, saving history and settings, then destroying the window."""
        self.save_prompt_history()
        self.save_app_settings() 
        self.destroy() 

    def create_widgets(self):
        self.style = ttk.Style()
        self.style.configure('.', font=self.app_font) 

        # Main container
        main_container = tk.Frame(self)
        main_container.pack(fill="both", expand=True, padx=5, pady=5)
        
        # d) Top area with paned window for resizable divider - make it resizable vertically too!
        self.paned_window = tk.PanedWindow(main_container, orient="horizontal", sashrelief="raised", sashwidth=4)
        self.paned_window.pack(fill="both", expand=True, pady=(0, 5))
        
        # --- LEFT PANE: PREVIEW AND PROMPT STACKED ---
        left_pane = tk.Frame(self.paned_window)
        self.paned_window.add(left_pane, minsize=400)
        
        # d) Add vertical paned window for resizable prompt/preview separation
        self.vertical_paned = tk.PanedWindow(left_pane, orient="vertical", sashrelief="raised", sashwidth=4)
        self.vertical_paned.pack(fill="both", expand=True)
        
        # Preview area (top)
        self.image_display_frame = tk.LabelFrame(self.vertical_paned, text="Preview", font=self.app_font, bg="lightgray")
        self.vertical_paned.add(self.image_display_frame, minsize=200)
        
        self.generated_image_label = tk.Label(self.image_display_frame, bg="lightgray")
        self.generated_image_label.pack(fill="both", expand=True, padx=5, pady=5)

        # Prompt area (bottom of left pane)
        prompt_frame = tk.LabelFrame(self.vertical_paned, text="Generate New Wallpaper", font=self.app_font)
        self.vertical_paned.add(prompt_frame, minsize=100)
        
        # d) Increase default height for larger prompts
        self.prompt_text_widget = tk.Text(prompt_frame, height=6, wrap="word", font=self.app_font)
        self.prompt_text_widget.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Bind Return key
        self.prompt_text_widget.bind("<Return>", self.on_generate_button_click)

        # --- RIGHT PANE: THUMBNAILS ---
        thumbnail_frame = tk.LabelFrame(self.paned_window, text="Your Wallpaper Collection", font=self.app_font)
        self.paned_window.add(thumbnail_frame, minsize=250)
        
        # Create grid gallery
        self.gallery = GridGallery(thumbnail_frame, on_image_click=self.on_thumbnail_click)
        self.gallery.pack(fill="both", expand=True, padx=5, pady=5)

        # a) --- BOTTOM ROW: THREE BLOCKS WITH EXTENSIBLE GAPS ---
        controls_frame = tk.Frame(main_container)
        controls_frame.pack(fill="x", pady=(5, 0))
        
        # Configure grid with 3 blocks and extensible gaps
        controls_frame.grid_columnconfigure(0, weight=0)  # Left block - fixed
        controls_frame.grid_columnconfigure(1, weight=1)  # Left gap - extensible
        controls_frame.grid_columnconfigure(2, weight=0)  # Center block - fixed (sliders)
        controls_frame.grid_columnconfigure(3, weight=1)  # Right gap - extensible
        controls_frame.grid_columnconfigure(4, weight=0)  # Right block - fixed
        
        # a) LEFT BLOCK: Generation functions
        left_block = tk.Frame(controls_frame)
        left_block.grid(row=0, column=0, sticky="w")
        
        tk.Button(left_block, text="Generate", command=self.on_generate_button_click, font=self.app_font).pack(side="left", padx=(0, 5))
        self.generate_button = left_block.winfo_children()[-1]  # Keep reference for status updates
        
        tk.Button(left_block, text="Load Prompt", command=self.load_prompt_from_history, font=self.app_font).pack(side="left")
        
        # a) CENTER BLOCK: Sliders
        center_block = tk.Frame(controls_frame)
        center_block.grid(row=0, column=2, sticky="")
        
        ui_scale_subframe = tk.Frame(center_block)
        ui_scale_subframe.pack(side="left", padx=(0, 20))
        
        tk.Label(ui_scale_subframe, text="UI Size:", font=self.app_font).pack(side="left", padx=(0, 5))
        self.scale_slider = tk.Scale(ui_scale_subframe, from_=0.5, to_=2.5, resolution=0.1, orient="horizontal", 
                                   command=self.update_ui_scale_callback, showvalue=False, font=self.app_font, length=100)
        self.scale_slider.set(self.current_font_scale)
        self.scale_slider.pack(side="left")
        
        thumb_scale_subframe = tk.Frame(center_block)
        thumb_scale_subframe.pack(side="left")
        
        tk.Label(thumb_scale_subframe, text="Thumb Size:", font=self.app_font).pack(side="left", padx=(0, 5))
        self.thumbnail_scale_slider = tk.Scale(thumb_scale_subframe, from_=0.5, to_=2.5, resolution=0.1, orient="horizontal",
                                             command=self._update_thumbnail_scale_callback, showvalue=False, font=self.app_font, length=100)
        self.thumbnail_scale_slider.set(self.current_thumbnail_scale)
        self.thumbnail_scale_slider.pack(side="left")
        
        # a) RIGHT BLOCK: Wallpaper selection functions
        right_block = tk.Frame(controls_frame)
        right_block.grid(row=0, column=4, sticky="e")
        
        tk.Button(right_block, text="Add Image", command=self.add_image_manually, font=self.app_font).pack(side="left", padx=(0, 5))
        tk.Button(right_block, text="Delete", command=self.delete_selected_image, font=self.app_font).pack(side="left", padx=(0, 5))
        tk.Button(right_block, text="Set Wallpaper", command=self.set_current_as_wallpaper, font=self.app_font).pack(side="left")
        
        # d) Set initial paned window positions after a brief delay
        self.after(100, self.set_initial_pane_positions)

    def set_initial_pane_positions(self):
        """d) Set the initial pane positions from saved settings."""
        try:
            # Set horizontal pane position
            self.paned_window.sash_place(0, self.paned_position, 0)
            # Set vertical pane position (2/3 for preview, 1/3 for prompt)
            total_height = self.vertical_paned.winfo_height()
            if total_height > 100:  # Only if the pane is properly sized
                prompt_height = total_height // 3
                self.vertical_paned.sash_place(0, 0, total_height - prompt_height)
        except (tk.TclError, IndexError):
            # If setting position fails, that's okay
            pass

    def update_ui_scale_callback(self, value):
        """Callback for the UI scale slider."""
        self.update_ui_scale(float(value))

    def update_ui_scale(self, scale_factor):
        """Adjusts the font size of various UI elements based on the scale factor."""
        self.current_font_scale = scale_factor
        new_size = int(self.base_font_size * self.current_font_scale)
        self.app_font.config(size=new_size)

        # Update all widgets with font
        def update_widget_fonts(widget):
            if hasattr(widget, 'config'):
                try:
                    if isinstance(widget, (tk.Label, tk.Button, tk.LabelFrame, tk.Text, tk.Scale)):
                        widget.config(font=self.app_font)
                except:
                    pass
            
            for child in widget.winfo_children():
                update_widget_fonts(child)
        
        update_widget_fonts(self)
        
        if self.current_image_path:
            self.display_image(self.current_image_path)

    def _update_thumbnail_scale_callback(self, value):
        """Callback for the thumbnail scale slider."""
        self.current_thumbnail_scale = float(value)
        self.gallery.set_thumbnail_scale(self.current_thumbnail_scale)

    def on_image_display_frame_resize(self, event):
        """Called when the image display frame changes size."""
        if self.current_image_path and event.width > 0 and event.height > 0:
            self.display_image(self.current_image_path)

    def load_images(self):
        """Loads images from the IMAGE_DIR and updates the gallery."""
        self.image_files = []
        for filename in os.listdir(IMAGE_DIR):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                self.image_files.append(os.path.join(IMAGE_DIR, filename))

        # Sort by timestamp (newest first)
        self.image_files.sort(reverse=True) 
        
        # Update gallery
        self.gallery.load_images(self.image_files)

    def on_thumbnail_click(self, image_path):
        """Handle thumbnail selection from gallery."""
        self.display_image(image_path)

    def display_image(self, image_path):
        try:
            full_img = Image.open(image_path)
            img_width, img_height = full_img.size

            frame_width = self.generated_image_label.winfo_width()
            frame_height = self.generated_image_label.winfo_height()

            if frame_width <= 1 or frame_height <= 1:
                # Frame not ready yet
                self.after(100, lambda: self.display_image(image_path))
                return

            # Calculate size to fit in the label
            img_aspect = img_width / img_height
            frame_aspect = frame_width / frame_height

            if img_aspect > frame_aspect:
                new_width = frame_width - 10  # Some padding
                new_height = int(new_width / img_aspect)
            else:
                new_height = frame_height - 10  # Some padding
                new_width = int(new_height * img_aspect)

            new_width = max(1, new_width)
            new_height = max(1, new_height)

            # Resize and display
            resized_img = full_img.resize((new_width, new_height), Image.LANCZOS)
            photo = ImageTk.PhotoImage(resized_img)
            
            self.generated_image_label.config(image=photo)
            self.generated_image_label.image = photo 
            self.current_image_path = image_path
            
        except Exception as e:
            messagebox.showerror("Image Display Error", f"Could not display image: {e}")
            self.current_image_path = None

    def add_prompt_to_history(self, prompt):
        """Adds a prompt to history and saves it to file."""
        if prompt in self.prompt_history:
            self.prompt_history.remove(prompt) 
        self.prompt_history.insert(0, prompt) 

        if len(self.prompt_history) > self.max_history_items:
            self.prompt_history = self.prompt_history[:self.max_history_items]

        self.save_prompt_history() 

    def load_prompt_from_history(self):
        """Opens a new window to select a prompt from history."""
        history_window = tk.Toplevel(self)
        history_window.title("Select Prompt from History")
        history_window.transient(self)
        history_window.grab_set()

        frame = tk.Frame(history_window, padx=10, pady=10)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Recent Prompts:", font=self.app_font).pack(pady=(0, 5))

        history_combobox = ttk.Combobox(frame, values=self.prompt_history, font=self.app_font, width=80)
        history_combobox.pack(fill="x", expand=True, pady=(0, 10))

        def on_select():
            selected_prompt = history_combobox.get()
            if selected_prompt:
                self.prompt_text_widget.delete("1.0", tk.END)
                self.prompt_text_widget.insert("1.0", selected_prompt)
            history_window.destroy()

        select_button = tk.Button(frame, text="Load Selected", command=on_select, font=self.app_font)
        select_button.pack(pady=(5,0))

        if self.prompt_history:
            history_combobox.set(self.prompt_history[0])

    def on_generate_button_click(self, event=None):
        prompt = self.prompt_text_widget.get("1.0", tk.END).strip()
        
        if event and event.keysym == "Return" and prompt.endswith("\n"):
            prompt = prompt[:-1].strip()

        if not prompt:
            messagebox.showwarning("Input Error", "Please enter a prompt.")
            return

        self.generate_button.config(text="Generating...", state="disabled")
        self.update_idletasks() 

        def run_generation():
            image_url = generate_image(prompt)
            if image_url:
                timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                filename = f"{timestamp_str}_generated_{uuid.uuid4().hex}.png"
                save_path = os.path.join(IMAGE_DIR, filename)
                if download_image(image_url, save_path):
                    self.display_image(save_path)
                    self.load_images() 
                    self.add_prompt_to_history(prompt) 
            self.generate_button.config(text="Generate", state="normal")

        thread = threading.Thread(target=run_generation)
        thread.start()

    def add_image_manually(self):
        file_path = filedialog.askopenfilename(
            title="Select an image file",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif *.bmp")]
        )
        if file_path:
            try:
                timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                original_ext = os.path.splitext(file_path)[1]
                filename = f"{timestamp_str}_manual_{uuid.uuid4().hex}{original_ext}"
                destination_path = os.path.join(IMAGE_DIR, filename)
                import shutil
                shutil.copy(file_path, destination_path)
                self.load_images()
                self.display_image(destination_path)
            except Exception as e:
                messagebox.showerror("File Error", f"Failed to add image: {e}")

    def delete_selected_image(self):
        if not self.current_image_path or not os.path.exists(self.current_image_path):
            messagebox.showwarning("Deletion Error", "No image selected or file does not exist.")
            return

        if messagebox.askyesno("Confirm Deletion", f"Are you sure you want to delete '{os.path.basename(self.current_image_path)}'?"):
            try:
                os.remove(self.current_image_path)
                self.generated_image_label.config(image=None) 
                self.generated_image_label.image = None
                self.current_image_path = None
                self.load_images() 
            except Exception as e:
                messagebox.showerror("Deletion Error", f"Failed to delete image: {e}")

    def set_current_as_wallpaper(self):
        if not self.current_image_path or not os.path.exists(self.current_image_path):
            messagebox.showwarning("Wallpaper Error", "No image selected to set as wallpaper.")
            return

        if not set_wallpaper(os.path.abspath(self.current_image_path)):
            messagebox.showerror("Wallpaper Error", "Failed to set wallpaper.")

if __name__ == "__main__":
    app = WallpaperApp()
    app.tk.call('wm', 'iconname', app._w, 'kubux-wallpaper-generator')
    app.mainloop()
