# Kubux Wallpaper Generator

![Kubux Wallpaper Generator](screenshot.png)

A desktop application for managing your wallpaper collection with AI image generation capabilities.

## Features

- **AI-Powered Wallpaper Generation**: Create unique wallpapers using text prompts through Together.ai's FLUX.1-pro model
- **Wallpaper Collection Management**: Browse, preview, and organize your wallpaper collection
- **Multi-Desktop Environment Support**: Set wallpapers on most Linux desktop environments
- **Advanced Image Viewing**: Zoom, pan, and examine images in detail
- **Simple Import Tool**: Add images from your existing collection with an intuitive file browser
- **Customizable UI**: Adjust interface scaling and thumbnail sizes to your preference
- **Prompt History**: Reuse your successful generation prompts

## Installation

### From Source (Nix)

Kubux Wallpaper Generator includes a `flake.nix` for easy installation on NixOS and other systems with Nix package manager:

```bash
# Clone the repository
git clone https://github.com/yourusername/kubux-wallpaper-generator
cd kubux-wallpaper-generator

# Build and install using Nix flakes
nix profile install .
```

Alternatively, you can run or install by pointing nix directly to the project url.


### From Source (Manual, untested)

If you're not using NixOS, you can install the dependencies manually:

```bash
# Install dependencies
pip install pillow requests python-dotenv together

# Run the application
python kubux-wallpaper-generator.py
```

## Setting up AI Image Generation

1. Create an account at [Together.ai](https://together.ai)
2. Generate an API key from your account settings
3. Create a `.env` file in your home directory  with:
```
TOGETHER_API_KEY=your_api_key_here
```
4. Restart the application to enable AI features

## Usage

### Managing Your Wallpaper Collection

- **Browse Gallery**: Scroll through your wallpaper collection in the right panel
- **Preview Images**: Click any thumbnail to preview it in full size
- **Set Wallpaper**: Select an image and click "Set Wallpaper" to apply it to your desktop
- **Delete Images**: Remove unwanted images by selecting them and clicking "Delete". Alternatively, a right click on a thumbnail will immediately remove it.  Note: the curated wallpaper collection is maintained as a directory of symlinks to the actual image files. Removing an image from the wallpaper collection will not destroy the image file but it will just remove the symlink to it.
- **Add Images**: Import existing images from your computer by clicking "Add". Note: this will move or copy files, it will create a symlink to the image file.

### Adding Images to Your Wallpaper Collection
- **Select Images**: Left-click on thumbnails to select or unselect them.
- **Examine Images**: Right-click on thumbnails to open the image viewer with zoom capabilities
- **Navigation**: There is a bread crum navigation bar to move around in the file system.
- **Go Back to the Main App**: Click "Add Selected" or "Cancel" to return to the main window.

### Generating AI Wallpapers

1. Enter a descriptive prompt in the text area
2. Click "Generate" and wait for the AI to create your wallpaper
3. The new wallpaper will be automatically added to your collection
4. Access your previous prompts by clicking "History"

### Customizing the Interface

- **Adjust UI Size**: Use the "UI Size" slider to scale the entire interface
- **Adjust Thumbnail Size**: Use the "Thumb Size" slider to change thumbnail dimensions

### Keyboard Shortcuts

**In the main window:**
- Arrow keys: Navigate through thumbnails
- Page Up/Down: Scroll gallery faster

**In the image viewer:**
- `+`: Zoom in
- `-`: Zoom out
- `0`: Reset to fit window
- F11: Toggle fullscreen
- Mouse drag: Pan when zoomed in
- Mouse wheel: Zoom in/out
- Esc: Close viewer

## Configuration

The application stores configuration files and cached data in standard XDG directories:

- **Config**: `~/.config/kubux-wallpaper-generator/`
- **Cache**: `~/.cache/kubux-wallpaper-generator/`
- **Downloads**: `~/Pictures/kubux-wallpaper-generator/`

## Development

A development environment is included in the flake.nix:

```bash
# Enter development shell with all dependencies
nix develop

# Run the application from the development environment
python kubux-wallpaper-generator.py
```

## License

Kubux Wallpaper Generator is licensed under the [Apache License 2.0](LICENSE).

### Why Apache 2.0?

- **Patent Protection**: Includes an express patent license to users
- **Attribution**: Requires appropriate attribution
- **Contribution Clarity**: Clear handling of contributions
- **Commercial Use**: Permissive for businesses and commercial use
- **Warranty Disclaimer**: Clear protections for developers


## Acknowledgments

- Together.ai for providing the image generation API
- The Python community for the libraries used in this project
- NixOS for the reproducible build and development system
- AI tools for generating code and documentation
- scancode-toolkit for keeping AI somewhat in check
