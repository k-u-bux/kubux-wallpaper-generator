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
DEFAULT_THUMBNAIL_DIM = 192 # This is the maximum dimension (width or height) for the thumbnail
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

# --- Virtual Gallery Widget ---
class VirtualGallery(tk.Frame):
    def __init__(self, parent, on_image_click=None):
        super().__init__(parent)
        self.on_image_click = on_image_click
        
        self.image_files = []
        self.thumbnails_cache = {}  # Cache for loaded thumbnails
        self.thumbnail_dimensions_cache = {}  # Cache for thumbnail dimensions
        self.thumbnail_max_size = DEFAULT_THUMBNAIL_DIM
        self.current_selection = None
        
        self.scroll_position = 0
        self.visible_start = 0
        self.visible_end = 0
        
        # We'll calculate these based on actual thumbnails
        self.actual_gallery_height = MINIMAL_GALLERY_HEIGHT
        
        self.create_widgets()
        
    def create_widgets(self):
        # Canvas for drawing thumbnails
        self.canvas = tk.Canvas(self, bg="lightgray", height=self.actual_gallery_height)
        self.canvas.pack(fill="both", expand=True)
        
        # Scrollbar
        self.scrollbar = tk.Scrollbar(self, orient="horizontal", command=self.on_scrollbar)
        self.scrollbar.pack(side="bottom", fill="x")
        
        # Bind events
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())
        
        # Mouse wheel binding
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", lambda e: self.on_mousewheel(e, delta=-1))
        self.canvas.bind("<Button-5>", lambda e: self.on_mousewheel(e, delta=1))
        
        # Keyboard bindings - bind to canvas with focus
        self.canvas.bind("<Key>", self.on_keypress)
        self.canvas.bind("<Left>", lambda e: self.scroll_by_thumbnails(-1))
        self.canvas.bind("<Right>", lambda e: self.scroll_by_thumbnails(1))
        self.canvas.bind("<Up>", lambda e: self.scroll_by_thumbnails(-5))
        self.canvas.bind("<Down>", lambda e: self.scroll_by_thumbnails(5))
        self.canvas.bind("<Prior>", lambda e: self.scroll_by_thumbnails(-20))  # Page Up
        self.canvas.bind("<Next>", lambda e: self.scroll_by_thumbnails(20))   # Page Down
        self.canvas.bind("<Home>", lambda e: self.scroll_to_start())
        self.canvas.bind("<End>", lambda e: self.scroll_to_end())
        
        # Make canvas focusable
        self.canvas.config(takefocus=True)
        
    def set_thumbnail_scale(self, scale):
        """Update thumbnail scale and refresh display."""
        self.thumbnail_max_size = int(DEFAULT_THUMBNAIL_DIM * scale)
        
        # Clear caches to force regeneration
        self.thumbnails_cache.clear()
        self.thumbnail_dimensions_cache.clear()
        
        # Recalculate gallery height and refresh
        self.calculate_gallery_height()
        self.update_display()
        
    def calculate_gallery_height(self):
        """Calculate the actual height needed for the gallery based on thumbnails."""
        if not self.image_files:
            self.actual_gallery_height = MINIMAL_GALLERY_HEIGHT
            self.canvas.config(height=self.actual_gallery_height)
            return
        
        max_height = 0
        
        # Sample a few images to determine the maximum height needed
        sample_size = min(10, len(self.image_files))
        for i in range(sample_size):
            img_path = self.image_files[i]
            dims = self.get_thumbnail_dimensions(img_path)
            if dims:
                max_height = max(max_height, dims[1])
        
        # Add padding
        self.actual_gallery_height = max_height + 10  # 5px top + 5px bottom padding
        self.canvas.config(height=self.actual_gallery_height)
        
    def get_thumbnail_dimensions(self, img_path):
        """Get thumbnail dimensions from cache or calculate them."""
        cache_key = f"{img_path}_{self.thumbnail_max_size}"
        
        if cache_key not in self.thumbnail_dimensions_cache:
            try:
                img = Image.open(img_path)
                # Calculate thumbnail size while maintaining aspect ratio
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
                # Also cache dimensions
                self.thumbnail_dimensions_cache[cache_key] = (img.width, img.height)
            except Exception as e:
                print(f"Error loading thumbnail for {img_path}: {e}")
                return None
                
        return self.thumbnails_cache.get(cache_key)
        
    def load_images(self, image_paths):
        """Load new image list and refresh display."""
        self.image_files = image_paths
        self.thumbnails_cache.clear()
        self.thumbnail_dimensions_cache.clear()
        self.scroll_position = 0
        self.current_selection = None
        
        # Recalculate gallery height based on new images
        self.calculate_gallery_height()
        self.update_scrollbar()
        self.update_display()
        
    def calculate_thumbnail_x_position(self, index):
        """Calculate the x position for a thumbnail at given index."""
        x_pos = 5  # Initial padding
        
        for i in range(index):
            if i < len(self.image_files):
                dims = self.get_thumbnail_dimensions(self.image_files[i])
                if dims:
                    x_pos += dims[0] + 10  # thumbnail width + padding
                else:
                    x_pos += self.thumbnail_max_size + 10  # fallback
                    
        return x_pos
        
    def calculate_total_width(self):
        """Calculate total width of all thumbnails."""
        total_width = 10  # Start with padding
        
        for img_path in self.image_files:
            dims = self.get_thumbnail_dimensions(img_path)
            if dims:
                total_width += dims[0] + 10  # thumbnail width + spacing
            else:
                total_width += self.thumbnail_max_size + 10  # fallback
                
        return total_width
        
    def find_thumbnail_at_position(self, click_x):
        """Find which thumbnail is at the given x position."""
        adjusted_x = click_x + self.scroll_position
        current_x = 5  # Initial padding
        
        for i, img_path in enumerate(self.image_files):
            dims = self.get_thumbnail_dimensions(img_path)
            if dims:
                thumb_width = dims[0]
            else:
                thumb_width = self.thumbnail_max_size
                
            if current_x <= adjusted_x <= current_x + thumb_width:
                return i
                
            current_x += thumb_width + 10  # Move to next thumbnail
            
        return -1
        
    def on_canvas_configure(self, event):
        """Handle canvas resize."""
        self.update_scrollbar()
        self.update_display()
        
    def on_scrollbar(self, action, position, unit=None):
        """Handle scrollbar drag and click events."""
        if action == "moveto":
            # Direct positioning from scrollbar drag
            position = float(position)
            total_width = self.calculate_total_width()
            canvas_width = self.canvas.winfo_width()
            max_scroll = max(0, total_width - canvas_width)
            self.scroll_position = int(position * max_scroll)
            
        elif action == "scroll":
            # Scrollbar arrow clicks
            delta = int(position)
            if unit == "units":
                # Arrow clicks - scroll by pixels
                self.scroll_by_pixels(delta * 50)
            elif unit == "pages":
                # Between thumb and arrow clicks
                canvas_width = self.canvas.winfo_width()
                self.scroll_by_pixels(delta * canvas_width // 2)
            return  # Early return to avoid duplicate updates
            
        self.update_scrollbar()
        self.update_display()
        
    def on_keypress(self, event):
        """Handle key press events for navigation."""
        # This catches any key that wasn't handled by specific bindings
        return "break"
        
    def scroll_by_thumbnails(self, delta):
        """Scroll by delta number of thumbnails."""
        if not self.image_files:
            return
            
        if delta > 0:  # Scroll right
            # Find average thumbnail width for smoother scrolling
            avg_width = self.calculate_total_width() / len(self.image_files) if self.image_files else 100
            scroll_amount = delta * avg_width
        else:  # Scroll left
            avg_width = self.calculate_total_width() / len(self.image_files) if self.image_files else 100
            scroll_amount = delta * avg_width
            
        self.scroll_by_pixels(int(scroll_amount))
        
    def scroll_by_pixels(self, delta_pixels):
        """Scroll by delta pixels."""
        old_position = self.scroll_position
        self.scroll_position += delta_pixels
        
        # Clamp scroll position
        total_width = self.calculate_total_width()
        canvas_width = self.canvas.winfo_width()
        max_scroll = max(0, total_width - canvas_width)
        self.scroll_position = max(0, min(self.scroll_position, max_scroll))
        
        if self.scroll_position != old_position:
            self.update_scrollbar()
            self.update_display()
            
    def scroll_to_start(self):
        """Scroll to the beginning."""
        self.scroll_position = 0
        self.update_scrollbar()
        self.update_display()
        
    def scroll_to_end(self):
        """Scroll to the end."""
        total_width = self.calculate_total_width()
        canvas_width = self.canvas.winfo_width()
        max_scroll = max(0, total_width - canvas_width)
        self.scroll_position = max_scroll
        self.update_scrollbar()
        self.update_display()
        
    def on_mousewheel(self, event, delta=None):
        """Handle mouse wheel scrolling."""
        if delta is not None:  # Linux
            self.scroll_by_pixels(delta * 50)
        elif platform.system() == "Windows":
            self.scroll_by_pixels(int(-1 * (event.delta / 120)) * 50)
        else:  # macOS
            self.scroll_by_pixels(int(-1 * event.delta) * 50)
            
    def update_scrollbar(self):
        """Update scrollbar position and size."""
        if not self.image_files:
            self.scrollbar.set(0, 1)
            return
            
        canvas_width = self.canvas.winfo_width()
        total_width = self.calculate_total_width()
        
        if total_width <= canvas_width:
            self.scrollbar.set(0, 1)
        else:
            # Calculate scrollbar position
            scroll_start = self.scroll_position / total_width
            scroll_end = min(1.0, (self.scroll_position + canvas_width) / total_width)
            self.scrollbar.set(scroll_start, scroll_end)
            
    def update_display(self):
        """Update the visible thumbnails on canvas."""
        self.canvas.delete("all")
        
        if not self.image_files:
            return
            
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        # Draw visible thumbnails
        current_x = 5  # Start with padding
        
        for i, img_path in enumerate(self.image_files):
            dims = self.get_thumbnail_dimensions(img_path)
            if not dims:
                continue
                
            thumb_width, thumb_height = dims
            
            # Check if this thumbnail is visible
            thumb_left = current_x - self.scroll_position
            thumb_right = thumb_left + thumb_width
            
            if thumb_right >= 0 and thumb_left <= canvas_width:
                # Thumbnail is at least partially visible, load and draw it
                thumbnail = self.get_thumbnail(img_path)
                
                if thumbnail:
                    # Center vertically in the canvas
                    y = (canvas_height - thumb_height) // 2
                    
                    # Draw thumbnail
                    self.canvas.create_image(thumb_left, y, anchor="nw", image=thumbnail, tags=f"thumb_{i}")
                    
                    # Draw selection border if this is the current selection
                    if self.current_selection == img_path:
                        x1, y1 = thumb_left - 2, y - 2
                        x2, y2 = thumb_left + thumb_width + 2, y + thumb_height + 2
                        self.canvas.create_rectangle(x1, y1, x2, y2, outline="blue", width=2, tags=f"border_{i}")
                        
            current_x += thumb_width + 10  # Move to next position
            
            # Stop processing if we're well past the visible area
            if current_x - self.scroll_position > canvas_width + 200:
                break
                    
    def on_canvas_click(self, event):
        """Handle canvas click to select thumbnail."""
        if not self.image_files:
            return
            
        # Set focus to enable keyboard navigation
        self.canvas.focus_set()
        
        thumbnail_index = self.find_thumbnail_at_position(event.x)
        
        if 0 <= thumbnail_index < len(self.image_files):
            selected_path = self.image_files[thumbnail_index]
            self.current_selection = selected_path
            self.update_display()  # Refresh to show selection
            
            if self.on_image_click:
                self.on_image_click(selected_path)

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
        """Loads UI scale, window geometry, and thumbnail scale from a JSON file."""
        try:
            if os.path.exists(APP_SETTINGS_FILE):
                with open(APP_SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)
                self.current_font_scale = settings.get("ui_scale", 1.0)
                self.initial_geometry = settings.get("window_geometry", "1024x768")
                self.current_thumbnail_scale = settings.get("thumbnail_scale", 1.0) 
            else:
                self.current_font_scale = 1.0
                self.initial_geometry = "1024x768"
                self.current_thumbnail_scale = 1.0
        except json.JSONDecodeError as e:
            print(f"Error decoding app settings JSON: {e}. Using default settings.")
            self.current_font_scale = 1.0
            self.initial_geometry = "1024x768"
            self.current_thumbnail_scale = 1.0
        except Exception as e:
            print(f"Unexpected error loading app settings: {e}. Using default settings.")
            self.current_font_scale = 1.0
            self.initial_geometry = "1024x768"
            self.current_thumbnail_scale = 1.0

    def save_app_settings(self):
        """Saves UI scale, window geometry, and thumbnail scale to a JSON file."""
        settings = {
            "ui_scale": self.current_font_scale,
            "window_geometry": self.geometry(),
            "thumbnail_scale": self.current_thumbnail_scale 
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

        # --- Prompt Section (TOP) ---
        prompt_frame = tk.Frame(self, padx=10, pady=10)
        prompt_frame.pack(side="top", fill="x") 

        # Configure grid for prompt_frame
        prompt_frame.grid_columnconfigure(0, weight=0)
        prompt_frame.grid_columnconfigure(1, weight=1)
        prompt_frame.grid_columnconfigure(2, weight=0)
        
        prompt_frame.grid_rowconfigure(0, weight=1)
        prompt_frame.grid_rowconfigure(1, weight=0)
        prompt_frame.grid_rowconfigure(2, weight=0)

        # "Image Prompt" label
        tk.Label(prompt_frame, text="Image Prompt:", font=self.app_font).grid(row=0, column=0, sticky="nw", padx=(0, 10), pady=(0, 5)) 

        # Text widget for multi-line input
        self.prompt_text_widget = tk.Text(prompt_frame, height=3, wrap="word", font=self.app_font)
        self.prompt_text_widget.grid(row=0, column=1, rowspan=3, sticky="nsew") 
        
        # Add a scrollbar to the Text widget
        prompt_text_scrollbar = tk.Scrollbar(prompt_frame, command=self.prompt_text_widget.yview)
        prompt_text_scrollbar.grid(row=0, column=2, rowspan=3, sticky="ns")
        self.prompt_text_widget.config(yscrollcommand=prompt_text_scrollbar.set)
        
        # Bind Return key to generate image (for the Text widget)
        self.prompt_text_widget.bind("<Return>", self.on_generate_button_click)

        # "Load Prompt" button
        self.load_prompt_button = tk.Button(prompt_frame, text="Load Prompt", command=self.load_prompt_from_history, font=self.app_font)
        self.load_prompt_button.grid(row=1, column=0, sticky="w", padx=(0, 10))

        # "Generate Wallpaper" button
        self.generate_button = tk.Button(prompt_frame, text="Generate", command=self.on_generate_button_click, font=self.app_font)
        self.generate_button.grid(row=2, column=0, sticky="w", padx=(0, 10), pady=(5,0))

        # --- BOTTOM CONTROL FRAME ---
        self.bottom_control_frame = tk.Frame(self, padx=10, pady=5)
        self.bottom_control_frame.pack(side="bottom", fill="x", anchor="sw") 

        # Buttons (packed left)
        tk.Button(self.bottom_control_frame, text="Set as Wallpaper", command=self.set_current_as_wallpaper, font=self.app_font).pack(side="left", padx=(0, 5))
        tk.Button(self.bottom_control_frame, text="Add Image", command=self.add_image_manually, font=self.app_font).pack(side="left", padx=(0, 5))
        tk.Button(self.bottom_control_frame, text="Delete Selected", command=self.delete_selected_image, font=self.app_font).pack(side="left", padx=(0, 5))

        # Thumbnail Scale Slider
        thumbnail_scale_subframe = tk.Frame(self.bottom_control_frame)
        thumbnail_scale_subframe.pack(side="right", padx=(15, 0))

        tk.Label(thumbnail_scale_subframe, text="Thumbnail Scale:", font=self.app_font).pack(side="left", padx=(0, 5))
        self.thumbnail_scale_slider = tk.Scale(
            thumbnail_scale_subframe,
            from_=0.5, to_=3.5, resolution=0.1, 
            orient="horizontal",
            command=self._update_thumbnail_scale_callback,
            length=150, 
            showvalue=False,
            font=self.app_font 
        )
        self.thumbnail_scale_slider.set(self.current_thumbnail_scale) 
        self.thumbnail_scale_slider.pack(side="left")

        # UI Scale Slider
        ui_scale_subframe = tk.Frame(self.bottom_control_frame)
        ui_scale_subframe.pack(side="right", padx=(5, 0))

        tk.Label(ui_scale_subframe, text="UI Scale:", font=self.app_font).pack(side="left", padx=(0, 5))
        self.scale_slider = tk.Scale(
            ui_scale_subframe,
            from_=0.5, to_=3.5, resolution=0.1,
            orient="horizontal",
            command=self.update_ui_scale_callback,
            length=150, 
            showvalue=False,
            font=self.app_font 
        )
        self.scale_slider.set(self.current_font_scale) 
        self.scale_slider.pack(side="left")

        # --- Virtual Image Gallery Section ---
        gallery_frame = tk.LabelFrame(self, text="Your Wallpaper Collection", padx=10, pady=10, font=self.app_font)
        gallery_frame.pack(side="bottom", pady=10, fill="x") 

        # Create virtual gallery
        self.gallery = VirtualGallery(gallery_frame, on_image_click=self.on_thumbnail_click)
        self.gallery.pack(fill="both", expand=True)

        # --- Generated Image Display ---
        self.image_display_frame = tk.Frame(self, borderwidth=2, relief="groove", padx=10, pady=10, bg="lightgray")
        self.image_display_frame.pack(side="top", pady=10, fill="both", expand=True) 
        
        self.generated_image_label = tk.Label(self.image_display_frame, bg="lightgray")
        self.generated_image_label.pack(fill="both", expand=True) 
        
        self.preview_label_text = tk.Label(self.image_display_frame, text="Generated/Selected Image Preview", font=self.app_font)
        self.preview_label_text.pack(side="bottom")

    def update_ui_scale_callback(self, value):
        """Callback for the UI scale slider."""
        self.update_ui_scale(float(value))

    def update_ui_scale(self, scale_factor):
        """Adjusts the font size of various UI elements based on the scale factor."""
        self.current_font_scale = scale_factor
        new_size = int(self.base_font_size * self.current_font_scale)
        self.app_font.config(size=new_size)

        # Update all UI elements with new font
        self.preview_label_text.config(font=self.app_font)
        
        for frame in [self, self.image_display_frame, self.bottom_control_frame]:
            for child_widget in frame.winfo_children():
                if isinstance(child_widget, (tk.LabelFrame, tk.Label)) and child_widget != self.generated_image_label:
                    child_widget.config(font=self.app_font)
                elif isinstance(child_widget, tk.Button):
                    child_widget.config(font=self.app_font)
                elif isinstance(child_widget, tk.Text):
                    child_widget.config(font=self.app_font)
                elif isinstance(child_widget, tk.Frame) and child_widget.winfo_children():
                    for sub_child in child_widget.winfo_children():
                        if isinstance(sub_child, (tk.Label, tk.Scale)):
                            sub_child.config(font=self.app_font)

        # Update prompt controls
        for child in self.nametowidget(self.prompt_text_widget.winfo_parent()).grid_slaves(row=0, column=0):
            if isinstance(child, tk.Label):
                child.config(font=self.app_font)
                break
        
        self.prompt_text_widget.config(font=self.app_font)
        self.load_prompt_button.config(font=self.app_font)
        self.generate_button.config(font=self.app_font)

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
        """Loads images from the IMAGE_DIR and updates the virtual gallery."""
        self.image_files = []
        for filename in os.listdir(IMAGE_DIR):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                self.image_files.append(os.path.join(IMAGE_DIR, filename))

        # Sort by timestamp (newest first)
        self.image_files.sort(reverse=True) 
        
        # Update virtual gallery
        self.gallery.load_images(self.image_files)

    def on_thumbnail_click(self, image_path):
        """Handle thumbnail selection from virtual gallery."""
        self.display_image(image_path)

    def display_image(self, image_path):
        try:
            full_img = Image.open(image_path)
            img_width, img_height = full_img.size

            frame_width = self.image_display_frame.winfo_width()
            frame_height = self.image_display_frame.winfo_height()

            label_height = self.preview_label_text.winfo_reqheight() 
            if self.preview_label_text.winfo_height() > 1:
                label_height = self.preview_label_text.winfo_height()

            available_width = frame_width - (self.image_display_frame.cget('padx') * 2)
            available_height = frame_height - (self.image_display_frame.cget('pady') * 2) - label_height

            if available_width <= 0 or available_height <= 0:
                available_width = 800
                available_height = 600

            img_aspect = img_width / img_height
            available_aspect = available_width / available_height

            if img_aspect > available_aspect:
                new_img_height = int(available_width / img_aspect)
                new_img_width = available_width
            else:
                new_img_width = int(available_height * img_aspect)
                new_img_height = available_height

            new_img_width = max(1, new_img_width)
            new_img_height = max(1, new_img_height)

            resized_img = full_img.resize((new_img_width, new_img_height), Image.LANCZOS)
            final_image = Image.new("RGB", (available_width, available_height), color=self.pil_lightgray_rgb)

            paste_x = (available_width - new_img_width) // 2
            paste_y = (available_height - new_img_height) // 2

            final_image.paste(resized_img, (paste_x, paste_y))

            photo = ImageTk.PhotoImage(final_image)
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

        history_combobox = ttk.Combobox(
            frame,
            values=self.prompt_history,
            font=self.app_font,
            width=80
        )
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
