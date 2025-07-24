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

# --- GUI Application ---
class WallpaperApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("kubux wallpaper generator")
        self.className = "kubux-wallpaper-generator"

        self.image_files = []
        self.current_image_path = None
        self.max_history_items = 25 

        self.load_prompt_history()
        self.load_app_settings()

        self.base_font_size = 12 
        self.app_font = tkFont.Font(family="TkDefaultFont", size=int(self.base_font_size * self.current_font_scale))

        # Get the RGB values of 'lightgray' from Tkinter
        # winfo_rgb returns a tuple of (R, G, B) where each is 0-65535
        r_16bit, g_16bit, b_16bit = self.winfo_rgb("lightgray")
        
        # Scale down to 0-255 for PIL (divide by 256 since 65535 is roughly 255 * 256)
        r_8bit = r_16bit // 256
        g_8bit = g_16bit // 256
        b_8bit = b_16bit // 256
        
        self.pil_lightgray_rgb = (r_8bit, g_8bit, b_8bit)

        self.create_widgets()
        self.load_images() # Call load_images to set initial canvas height based on content
        
        self.geometry(self.initial_geometry)
        self.update_ui_scale(self.current_font_scale) 

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.image_display_frame.bind("<Configure>", self.on_image_display_frame_resize)
        
        # Bind mouse wheel events to the root window for global handling
        self.bind("<MouseWheel>", self._on_global_mousewheel) # Windows/macOS
        self.bind("<Button-4>", lambda event: self._on_global_mousewheel(event, delta=-1)) # Linux scroll up
        self.bind("<Button-5>", lambda event: self._on_global_mousewheel(event, delta=1))  # Linux scroll down


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
                # Ensure thumbnail scale defaults to 1.0 if not found
                self.current_thumbnail_scale = settings.get("thumbnail_scale", 1.0) 
            else:
                self.current_font_scale = 1.0
                self.initial_geometry = "1024x768"
                self.current_thumbnail_scale = 1.0 # Default to 1.0
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
        prompt_frame.grid_columnconfigure(0, weight=0) # Column for labels/buttons, fixed width
        prompt_frame.grid_columnconfigure(1, weight=1) # Column for text widget, expands
        prompt_frame.grid_columnconfigure(2, weight=0) # Column for scrollbar, fixed width
        
        prompt_frame.grid_rowconfigure(0, weight=1) # Row for Image Prompt label and top of text widget
        prompt_frame.grid_rowconfigure(1, weight=0) # Row for Load Prompt button
        prompt_frame.grid_rowconfigure(2, weight=0) # Row for Generate button

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
        self.generate_button.grid(row=2, column=0, sticky="w", padx=(0, 10), pady=(5,0)) # Added top padding


        # --- BOTTOM CONTROL FRAME (New single row for buttons and sliders) ---
        # PACK THIS FIRST WITH side="bottom" TO ENSURE IT'S AT THE VERY BOTTOM
        self.bottom_control_frame = tk.Frame(self, padx=10, pady=5)
        self.bottom_control_frame.pack(side="bottom", fill="x", anchor="sw") 

        # Buttons (packed left)
        tk.Button(self.bottom_control_frame, text="Set as Wallpaper", command=self.set_current_as_wallpaper, font=self.app_font).pack(side="left", padx=(0, 5))
        tk.Button(self.bottom_control_frame, text="Add Image", command=self.add_image_manually, font=self.app_font).pack(side="left", padx=(0, 5))
        tk.Button(self.bottom_control_frame, text="Delete Selected", command=self.delete_selected_image, font=self.app_font).pack(side="left", padx=(0, 5))

        # --- Sliders (packed right, within their own sub-frames for side-by-side labels) ---

        # Thumbnail Scale Slider (packed first to appear further left on the right side)
        thumbnail_scale_subframe = tk.Frame(self.bottom_control_frame)
        thumbnail_scale_subframe.pack(side="right", padx=(15, 0)) # Pack this sub-frame to the right

        tk.Label(thumbnail_scale_subframe, text="Thumbnail Scale:", font=self.app_font).pack(side="left", padx=(0, 5))
        self.thumbnail_scale_slider = tk.Scale(
            thumbnail_scale_subframe, # Parent is now the sub-frame
            from_=0.5, to_=3.5, resolution=0.1, 
            orient="horizontal",
            command=self._update_thumbnail_scale_callback,
            length=150, 
            showvalue=False,
            font=self.app_font 
        )
        self.thumbnail_scale_slider.set(self.current_thumbnail_scale) 
        self.thumbnail_scale_slider.pack(side="left") # Pack inside sub-frame to the left

        # UI Scale Slider (packed second to appear further right on the right side)
        ui_scale_subframe = tk.Frame(self.bottom_control_frame)
        ui_scale_subframe.pack(side="right", padx=(5, 0)) # Pack this sub-frame to the right

        tk.Label(ui_scale_subframe, text="UI Scale:", font=self.app_font).pack(side="left", padx=(0, 5))
        self.scale_slider = tk.Scale(
            ui_scale_subframe, # Parent is now the sub-frame
            from_=0.5, to_=3.5, resolution=0.1,
            orient="horizontal",
            command=self.update_ui_scale_callback,
            length=150, 
            showvalue=False,
            font=self.app_font 
        )
        self.scale_slider.set(self.current_font_scale) 
        self.scale_slider.pack(side="left") # Pack inside sub-frame to the left


        # --- Image Gallery Section (ABOVE BOTTOM CONTROL FRAME) ---
        # PACK THIS SECOND WITH side="bottom" SO IT APPEARS ABOVE THE CONTROL FRAME
        gallery_frame = tk.LabelFrame(self, text="Your Wallpaper Collection", padx=10, pady=10, font=self.app_font)
        gallery_frame.pack(side="bottom", pady=10, fill="x") 

        # Initialize gallery_canvas with MINIMAL_GALLERY_HEIGHT.
        # Its height will be updated by load_images based on content.
        self.gallery_canvas = tk.Canvas(gallery_frame, bg="lightgray", height=MINIMAL_GALLERY_HEIGHT) 
        self.gallery_canvas.pack(side="top", fill="x", expand=True) # Changed to side="top"

        gallery_scrollbar = tk.Scrollbar(gallery_frame, orient="horizontal", command=self.gallery_canvas.xview)
        gallery_scrollbar.pack(side="bottom", fill="x") # Ensures it's full length directly below canvas
        self.gallery_canvas.configure(xscrollcommand=gallery_scrollbar.set)

        self.gallery_inner_frame = tk.Frame(self.gallery_canvas, bg="lightgray")
        self.gallery_canvas.create_window((0, 0), window=self.gallery_inner_frame, anchor="nw")

        self.gallery_canvas.bind("<Enter>", self._on_gallery_enter)
        self.gallery_canvas.bind("<Leave>", self._on_gallery_leave)
        
        # Bind keyboard events to the root window (active when canvas is focused)
        self.bind("<Left>", self._on_arrow_key) 
        self.bind("<Right>", self._on_arrow_key)
        self.bind("<Up>", self._on_arrow_key) 
        self.bind("<Down>", self._on_arrow_key) 
        self.bind("<Prior>", self._on_arrow_key) 
        self.bind("<Next>", self._on_arrow_key) 
        self.bind("<Home>", self._on_arrow_key) 
        self.bind("<End>", self._on_arrow_key) 
        
        # --- Generated Image Display (MIDDLE - TAKES REMAINING SPACE) ---
        # PACK THIS LAST WITH side="top", expand=True to make it fill the remaining space
        # Set the background of the image_display_frame itself
        self.image_display_frame = tk.Frame(self, borderwidth=2, relief="groove", padx=10, pady=10, bg="lightgray")
        self.image_display_frame.pack(side="top", pady=10, fill="both", expand=True) 
        
        # Set the background of the image display label to match the desired "bar" color
        self.generated_image_label = tk.Label(self.image_display_frame, bg="lightgray") # Set default background
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

        # Update specific labels that might not be caught by generic loops or have dynamic content
        self.preview_label_text.config(font=self.app_font)
        
        # Generic update for children of key frames
        for frame in [self, self.image_display_frame, self.bottom_control_frame]:
            for child_widget in frame.winfo_children():
                # For LabelFrames and direct Labels (excluding generated_image_label)
                if isinstance(child_widget, (tk.LabelFrame, tk.Label)) and child_widget != self.generated_image_label:
                    child_widget.config(font=self.app_font)
                # For Buttons
                elif isinstance(child_widget, tk.Button):
                    child_widget.config(font=self.app_font)
                # For Text widget
                elif isinstance(child_widget, tk.Text):
                    child_widget.config(font=self.app_font)
                # For Frames containing sliders and their labels
                elif isinstance(child_widget, tk.Frame) and child_widget.winfo_children():
                    for sub_child in child_widget.winfo_children():
                        if isinstance(sub_child, (tk.Label, tk.Scale)):
                            sub_child.config(font=self.app_font)

        # Explicitly update fonts for prompt controls since they are now in grid
        # Find the label by its grid position (row 0, column 0)
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
        # load_images will re-calculate and set the canvas height based on actual thumbnail sizes
        self.load_images() 

    def on_image_display_frame_resize(self, event):
        """Called when the image display frame changes size."""
        if self.current_image_path and event.width > 0 and event.height > 0:
            self.display_image(self.current_image_path)

    def load_images(self):
        """Loads images from the IMAGE_DIR and displays them as thumbnails."""
        # Clear existing widgets
        for widget in self.gallery_inner_frame.winfo_children():
            widget.destroy() 

        # Populate image_files list
        self.image_files = []
        for filename in os.listdir(IMAGE_DIR):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                self.image_files.append(os.path.join(IMAGE_DIR, filename))

        # Sort image files by their filename (which now includes a timestamp)
        # Use reverse=True to show most recent first (larger timestamp = newer)
        self.image_files.sort(reverse=True) 

        self.thumbnails = [] 
        current_thumb_dim = int(DEFAULT_THUMBNAIL_DIM * self.current_thumbnail_scale)
        
        max_actual_thumbnail_render_height = 0 # To find the tallest thumbnail after scaling and padding

        # Create thumbnail labels if images exist
        for i, img_path in enumerate(self.image_files):
            try:
                img = Image.open(img_path)
                
                # Use img.thumbnail to scale down while maintaining aspect ratio
                # The 'current_thumb_dim' applies to the larger dimension.
                img.thumbnail((current_thumb_dim, current_thumb_dim)) 
                
                actual_thumbnail_image_height = img.height # Get the actual height AFTER thumbnailing
                
                # Calculate the total vertical space this label will occupy:
                # Image height + pady top (5) + pady bottom (5) + border top (2) + border bottom (2)
                # Adding an extra 2px buffer for robustness
                required_label_height = actual_thumbnail_image_height + 5 + 5 + 2 + 2 + 2 # Total +16 from image height
                
                max_actual_thumbnail_render_height = max(max_actual_thumbnail_render_height, required_label_height)

                photo = ImageTk.PhotoImage(img)
                self.thumbnails.append(photo)

                thumb_label = tk.Label(self.gallery_inner_frame, image=photo, cursor="hand2")
                thumb_label.image_path = img_path 
                thumb_label.bind("<Button-1>", self.on_thumbnail_click)
                thumb_label.pack(side="left", padx=5, pady=5)
            except Exception as e:
                print(f"Error loading thumbnail for {img_path}: {e}")

        # Dynamically set canvas height based on images found
        if self.image_files:
            # Set canvas height to accommodate the tallest thumbnail found (plus its padding/border/buffer)
            self.gallery_canvas.config(height=max_actual_thumbnail_render_height) 
        else:
            # Minimal height if no thumbnails
            self.gallery_canvas.config(height=MINIMAL_GALLERY_HEIGHT)

        # Update canvas scrollregion after all children are packed
        self.gallery_inner_frame.update_idletasks()
        self.gallery_canvas.config(scrollregion=self.gallery_canvas.bbox("all"))

    def _on_gallery_enter(self, event):
        """Set focus to the canvas when mouse enters, enabling keyboard scrolling."""
        self.gallery_canvas.focus_set()

    def _on_gallery_leave(self, event):
        """Remove focus from the canvas when mouse leaves."""
        self.focus_set() 

    def _on_global_mousewheel(self, event, delta=None):
        """
        Handles mouse wheel events globally and applies them to the gallery canvas
        if the mouse is currently over the gallery area.
        """
        # Get coordinates of the mouse relative to the root window
        mouse_x, mouse_y = event.x_root, event.y_root

        # Get the bounding box of the gallery_canvas relative to the screen
        canvas_x1 = self.gallery_canvas.winfo_rootx()
        canvas_y1 = self.gallery_canvas.winfo_rooty()
        canvas_x2 = canvas_x1 + self.gallery_canvas.winfo_width()
        canvas_y2 = canvas_y1 + self.gallery_canvas.winfo_height()

        # Check if the mouse is within the gallery canvas's bounds
        if (canvas_x1 <= mouse_x <= canvas_x2) and \
           (canvas_y1 <= mouse_y <= canvas_y2):
            
            if delta is not None: # For Linux (Button-4, Button-5 events)
                self.gallery_canvas.xview_scroll(delta, "units")
            elif platform.system() == "Windows":
                self.gallery_canvas.xview_scroll(int(-1*(event.delta/120)), "units")
            else: # macOS (event.delta is typically +1 or -1)
                self.gallery_canvas.xview_scroll(int(-1*event.delta), "units")
            
            return "break" # Consume the event so it doesn't propagate further

        # If not over the gallery, let the event pass (return None)

    def _on_arrow_key(self, event):
        """Scrolls the canvas horizontally using arrow keys (Left, Right, Up, Down, Page Up/Down, Home/End)."""
        # Only scroll if the gallery canvas itself has focus AND there are images to scroll
        if self.gallery_canvas.focus_get() == self.gallery_canvas and self.image_files:
            if event.keysym == "Left":
                self.gallery_canvas.xview_scroll(-1, "units")
            elif event.keysym == "Right":
                self.gallery_canvas.xview_scroll(1, "units")
            elif event.keysym == "Up": # Scroll by 5 thumbnails
                self.gallery_canvas.xview_scroll(-5, "units")
            elif event.keysym == "Down": # Scroll by 5 thumbnails
                self.gallery_canvas.xview_scroll(5, "units")
            elif event.keysym == "Prior": # Page Up - scroll by 20 thumbnails
                self.gallery_canvas.xview_scroll(-20, "units")
            elif event.keysym == "Next": # Page Down - scroll by 20 thumbnails
                self.gallery_canvas.xview_scroll(20, "units")
            elif event.keysym == "Home": # Pos1 - go to the beginning
                self.gallery_canvas.xview_moveto(0.0)
            elif event.keysym == "End": # Go to the end
                self.gallery_canvas.xview_moveto(1.0)
            return "break" # Consume the event


    def on_thumbnail_click(self, event):
        # Remove highlight from previously selected thumbnail
        for widget in self.gallery_inner_frame.winfo_children():
            if isinstance(widget, tk.Label) and hasattr(widget, 'image_path'):
                widget.config(relief="flat", borderwidth=0)
                
        selected_path = event.widget.image_path
        self.display_image(selected_path)

        # Highlight newly selected thumbnail
        event.widget.config(relief="solid", borderwidth=2, highlightbackground="blue")
        
        # Crucial fix for keyboard scrolling: After clicking a thumbnail, ensure the gallery canvas regains focus
        self.gallery_canvas.focus_set()


    def display_image(self, image_path):
        try:
            full_img = Image.open(image_path)
            img_width, img_height = full_img.size

            # Get the current dimensions of the image_display_frame
            frame_width = self.image_display_frame.winfo_width()
            frame_height = self.image_display_frame.winfo_height()

            # Add padding for the label below the image, and internal padding of the frame
            label_height = self.preview_label_text.winfo_reqheight() 
            if self.preview_label_text.winfo_height() > 1:
                label_height = self.preview_label_text.winfo_height()

            # Calculate available space within the frame for the image
            available_width = frame_width - (self.image_display_frame.cget('padx') * 2)
            available_height = frame_height - (self.image_display_frame.cget('pady') * 2) - label_height

            if available_width <= 0 or available_height <= 0:
                # Fallback dimensions if the frame hasn't fully rendered yet, or is too small
                available_width = 800
                available_height = 600

            img_aspect = img_width / img_height
            available_aspect = available_width / available_height

            new_img_width, new_img_height = available_width, available_height

            # Determine new dimensions to fit image while maintaining aspect ratio
            if img_aspect > available_aspect:
                new_img_height = int(available_width / img_aspect)
            else:
                new_img_width = int(available_height * img_aspect)

            # Ensure new dimensions are at least 1x1 to prevent errors
            new_img_width = max(1, new_img_width)
            new_img_height = max(1, new_img_height)

            # Resize the original image to fit within the calculated dimensions
            resized_img = full_img.resize((new_img_width, new_img_height), Image.LANCZOS)

            # Create a new blank image with the exact Tkinter 'lightgray' RGB color
            final_image = Image.new("RGB", (available_width, available_height), color=self.pil_lightgray_rgb)

            # Calculate paste coordinates to center the resized image on the background
            paste_x = (available_width - new_img_width) // 2
            paste_y = (available_height - new_img_height) // 2

            # Paste the resized image onto the background
            final_image.paste(resized_img, (paste_x, paste_y))

            # Convert to PhotoImage and display
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
        history_window.transient(self) # Make it a transient window relative to main window
        history_window.grab_set() # Make it modal

        frame = tk.Frame(history_window, padx=10, pady=10)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Recent Prompts:", font=self.app_font).pack(pady=(0, 5))

        # Use a Combobox for selection in the history window
        history_combobox = ttk.Combobox(
            frame,
            values=self.prompt_history,
            font=self.app_font,
            width=80 # Set a reasonable width
        )
        history_combobox.pack(fill="x", expand=True, pady=(0, 10))

        def on_select():
            selected_prompt = history_combobox.get()
            if selected_prompt:
                self.prompt_text_widget.delete("1.0", tk.END) # Clear current text
                self.prompt_text_widget.insert("1.0", selected_prompt) # Insert selected prompt
            history_window.destroy()

        select_button = tk.Button(frame, text="Load Selected", command=on_select, font=self.app_font)
        select_button.pack(pady=(5,0))

        # Automatically select the first item if history is not empty
        if self.prompt_history:
            history_combobox.set(self.prompt_history[0])


    def on_generate_button_click(self, event=None):
        # Get text from the Text widget
        prompt = self.prompt_text_widget.get("1.0", tk.END).strip()
        
        # If the event is a <Return> key press, and the prompt text ends with a newline
        # due to the key press, remove it to avoid empty lines being part of the prompt.
        # This is a common behavior with tk.Text and <Return> binding.
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
                # Use a timestamp and UUID for unique and sortable filenames
                timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S_%f') # YYYYMMDD_HHMMSS_microseconds
                # Modified naming scheme: timestamp_type_uuid.ext
                filename = f"{timestamp_str}_generated_{uuid.uuid4().hex}.png"
                save_path = os.path.join(IMAGE_DIR, filename)
                if download_image(image_url, save_path):
                    self.display_image(save_path)
                    self.load_images() 
                    self.add_prompt_to_history(prompt) 
                else:
                    pass
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
                # Use a timestamp and UUID for unique and sortable filenames
                timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                original_ext = os.path.splitext(file_path)[1]
                # Modified naming scheme: timestamp_type_uuid.ext
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
