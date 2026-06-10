# theme_settings.py
"""
Theme Settings Manager for Level Editor
Handles saving and loading user theme preferences
"""

import json
import os


class ThemeSettings:
    """Manages theme preferences with JSON persistence"""
    
    def __init__(self, config_file="editor_config.json"):
        self.config_file = config_file
        self.settings = self._load_settings()
    
    def _load_settings(self):
        """Load settings from JSON file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    settings = json.load(f)
                    print(f"✓ Loaded theme settings from {self.config_file}")
                    return settings
        except Exception as e:
            print(f"⚠ Could not load settings: {e}")
        
        # Return default settings
        return {
            'force_dark_theme': False,
            'show_welcome': True
        }
    
    def _save_settings(self):
        """Save settings to JSON file.

        Merge-writes: re-reads the file and overlays this class's keys on top,
        so keys written by other components (e.g. the canvas's 'render_tier')
        are never clobbered by this class's startup snapshot."""
        try:
            on_disk = {}
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, 'r') as f:
                        on_disk = json.load(f) or {}
                except Exception:
                    on_disk = {}
            on_disk.update(self.settings)
            self.settings = on_disk
            with open(self.config_file, 'w') as f:
                json.dump(self.settings, f, indent=4)
            print(f"✓ Saved theme settings to {self.config_file}")
            return True
        except Exception as e:
            print(f"⚠ Could not save settings: {e}")
            return False
    
    def get_dark_theme(self):
        """Get dark theme preference"""
        return self.settings.get('force_dark_theme', False)
    
    def set_dark_theme(self, enabled):
        """Set dark theme preference and save"""
        self.settings['force_dark_theme'] = enabled
        self._save_settings()
        print(f"{'🌙' if enabled else '☀️'} Theme set to {'Dark' if enabled else 'Light'} mode")
    
    def get_show_welcome(self):
        """Get show welcome screen preference"""
        return self.settings.get('show_welcome', True)
    
    def set_show_welcome(self, enabled):
        """Set show welcome screen preference and save"""
        self.settings['show_welcome'] = enabled
        self._save_settings()
    
