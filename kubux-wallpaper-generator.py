# vibe coded with Gemini 2.5 Flash (2025-07-23)
# =============================================
# Golden Version: [v1.0-golden] - Final with FOUC (Flash of Unstyled Content) Fix

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
from datetime import datetime

# Load environment variables
load_dotenv()
# --- Configuration ---
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
if not TOGETHER_API_KEY:
    messagebox.showerror("API Key Error", "TOGETHER_API_KEY not found in .env file or environment variables.")
    exit()

HOME_DIR = os.path.expanduser('~')
CONFIG_DIR = os.path.join(HOME_DIR, ".config", "kubux-wallpaper-generator")
IMAGE_DIR = os.path.join(CONFIG_DIR, "images")
DEFAULT_THUMBNAIL_DIM = 192
PROMPT_HISTORY_FILE = os.path.join(CONFIG_DIR, "prompt_history.json")
APP_SETTINGS_FILE = os.path.join(CONFIG_DIR, "app_settings.json")    

os.makedirs(IMAGE_DIR, exist_ok=True)

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
        elif system == "Darwin": # macOS
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

def download_image(url, save_path):
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status() 
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
        return True
    except Exception as e:
        messagebox.showerror("Download Error", f"Failed to download image: {e}")
        return False

# --- GUI Application ---
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
        self._initial_load_done = False # --- FIX: Flag for initial load

        self.load_prompt_history()
        self.load_app_settings()
        self.gallery_thumbnail_max_size = int(DEFAULT_THUMBNAIL_DIM * self.current_thumbnail_scale)
        self.base_font_size = 12
        self.app_font = tkFont.Font(family="TkDefaultFont", size=int(self.base_font_size * self.current_font_scale))
        self.geometry(self.initial_geometry)
        
        self.create_widgets()
        
        self.update_idletasks()
        self.set_initial_pane_positions()
        
        # --- FIX: Initial load is now handled by the <Configure> event ---
        # self.after(1, self.load_images) # REMOVED

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
        try:
            if os.path.exists(APP_SETTINGS_FILE):
                with open(APP_SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)
                self.current_font_scale = settings.get("ui_scale", 1.0)
                self.initial_geometry = settings.get("window_geometry", "1200x800")
                self.current_thumbnail_scale = settings.get("thumbnail_scale", 1.0)
                self.horizontal_paned_position = settings.get("horizontal_paned_position", 600)
                self.vertical_paned_position = settings.get("vertical_paned_position", 400)
            else: raise FileNotFoundError
        except (json.JSONDecodeError, FileNotFoundError, Exception):
            self.current_font_scale = 1.0
            self.initial_geometry = "1200x800"
            self.current_thumbnail_scale = 1.0
            self.horizontal_paned_position = 600
            self.vertical_paned_position = 400

    def save_app_settings(self):
        try:
            settings = {
                "ui_scale": self.current_font_scale,
                "window_geometry": self.geometry(),
                "thumbnail_scale": self.current_thumbnail_scale,
                "horizontal_paned_position": self.paned_window.sashpos(0),
                "vertical_paned_position": self.vertical_paned.sashpos(0)
            }
            with open(APP_SETTINGS_FILE, 'w') as f:
                json.dump(settings, f, indent=4)
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
        self.generate_button.pack(side="left", padx=(0,2))
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
        ttk.Button(action_btn_frame, text="Add", command=self.add_image_manually).pack(side="left", padx=2)
        ttk.Button(action_btn_frame, text="Delete", command=self.delete_selected_image).pack(side="left", padx=2)
        ttk.Button(action_btn_frame, text="Set Wallpaper", command=self.set_current_as_wallpaper).pack(side="left", padx=2)

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
            thumbnail = self._gallery_get_thumbnail(img_path)
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

    def _gallery_get_thumbnail(self, img_path):
        cache_key = f"{img_path}_{self.gallery_thumbnail_max_size}"
        if cache_key not in self.gallery_thumbnails_cache:
            try:
                img = Image.open(img_path)
                img.thumbnail((self.gallery_thumbnail_max_size, self.gallery_thumbnail_max_size))
                self.gallery_thumbnails_cache[cache_key] = ImageTk.PhotoImage(img)
            except Exception as e:
                print(f"Error loading thumbnail for {img_path}: {e}")
                return None
        return self.gallery_thumbnails_cache.get(cache_key)

    # --- FIX: Modified <Configure> handler ---
    def _gallery_on_canvas_configure(self, event):
        # On the very first configure event that has a real width, load images.
        if not self._initial_load_done and event.width > 1:
            self.load_images()
            self._initial_load_done = True
            
        # Continue with the existing debounced resize logic for subsequent resizes.
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
        self.generate_button.config(text="Generating...", state="disabled")
        threading.Thread(target=self._run_generation_task, args=(prompt,), daemon=True).start()

    def _run_generation_task(self, prompt):
        image_url = generate_image(prompt)
        if image_url:
            filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:6]}.png"
            save_path = os.path.join(IMAGE_DIR, filename)
            if download_image(image_url, save_path):
                self.add_prompt_to_history(prompt)
                self.after(0, self.load_images_and_select, save_path)
        self.after(0, self.generate_button.config, {'text':"Generate", 'state':"normal"})

    def load_images_and_select(self, path_to_select):
        self.load_images()
        self._gallery_on_thumbnail_click(path_to_select)

    def add_image_manually(self):
        file_path = filedialog.askopenfilename(filetypes=[("Image files", "*.png *.jpg *.jpeg")])
        if not file_path: return
        try:
            ext = os.path.splitext(file_path)[1]
            filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_manual{ext}"
            dest = os.path.join(IMAGE_DIR, filename)
            import shutil
            shutil.copy(file_path, dest)
            self.load_images_and_select(dest)
        except Exception as e: messagebox.showerror("File Error", f"Failed to add image: {e}")

    def delete_selected_image(self):
        path_to_delete = self.gallery_current_selection
        if not path_to_delete or not os.path.exists(path_to_delete):
            return messagebox.showwarning("Deletion Error", "No image selected.")
        if messagebox.askyesno("Confirm Deletion", f"Delete '{os.path.basename(path_to_delete)}'?"):
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
