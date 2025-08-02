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

import platform
import subprocess
import os
import tkinter.font as tkFont # Assuming you're using Tkinter

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
    
# To test this code standalone (outside your app)
if __name__ == "__main__":
    if platform.system() == "Linux":
        font_name, font_size = get_linux_system_ui_font_info()
        print(f"\nFinal detected Linux UI Font: Family='{font_name}', Size={font_size}")
    else:
        print("This script is for Linux only.")
