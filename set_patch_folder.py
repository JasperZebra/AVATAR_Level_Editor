"""
Patch Folder Management and Visual Level Selection System
Handles patch folder configuration and provides visual level selection interface
"""

import os
import json
import glob
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict, field
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QScrollArea, QWidget,
    QMessageBox, QFileDialog, QGroupBox,
    QLineEdit, QProgressDialog, QFrame, QComboBox,
    QApplication
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QThread, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QPixmap, QIcon, QPainter, QFont, QColor, QAction

# Configuration file for storing patch folder path
PATCH_CONFIG_FILE = "patch_config.json"

def _spf_log(msg):
    """Write a timestamped line to crash_log.txt from anywhere in this module."""
    try:
        import main as _m
        _m._write_crash_log(
            f"[{__import__('datetime').datetime.now().strftime('%H:%M:%S')}] {msg}\n"
        )
    except Exception:
        pass

@dataclass
class LevelInfo:
    """Data class for storing level information"""
    name: str
    worlds_path: str
    levels_path: str                                    # primary levels folder (first part)
    levels_paths: List[str] = field(default_factory=list)  # all parts (populated for multi-part levels)
    thumbnail_path: Optional[str] = None
    display_name: Optional[str] = None
    has_terrain: bool = False
    has_objects: bool = False
    file_counts: Dict[str, int] = field(default_factory=dict)

class PatchFolderScanner(QThread):
    """Background thread for scanning patch folder structure"""
    
    progress_updated = pyqtSignal(int, str)  # progress percentage, status message
    scan_complete = pyqtSignal(dict)  # Dictionary of found levels
    error_occurred = pyqtSignal(str)  # Error message
    log_message = pyqtSignal(str)     # Plain log line (no progress change)

    def __init__(self, patch_folder: str, file_converter=None, game_mode: str = "avatar"):
        super().__init__()
        self.patch_folder = patch_folder
        self.file_converter = file_converter
        self.game_mode = game_mode
        self.should_stop = False

    def _log(self, msg):
        print(msg)
        self.log_message.emit(msg)
        
    def run(self):
        """Scan the patch folder for levels and their components"""
        try:
            levels_data = {}
            
            # Check for required directories - be more flexible
            worlds_dir = os.path.join(self.patch_folder, "worlds")
            levels_dir = os.path.join(self.patch_folder, "levels")
            
            # Also check for alternative naming
            if not os.path.exists(worlds_dir):
                # Try "Worlds" with capital W
                worlds_dir_alt = os.path.join(self.patch_folder, "Worlds")
                if os.path.exists(worlds_dir_alt):
                    worlds_dir = worlds_dir_alt
                    print(f"Using alternative worlds directory: {worlds_dir}")
            
            if not os.path.exists(levels_dir):
                # Try "Levels" with capital L
                levels_dir_alt = os.path.join(self.patch_folder, "Levels")
                if os.path.exists(levels_dir_alt):
                    levels_dir = levels_dir_alt
                    print(f"Using alternative levels directory: {levels_dir}")
            
            # Check if at least one directory exists
            has_worlds = os.path.exists(worlds_dir)
            has_levels = os.path.exists(levels_dir)
            
            if not has_worlds and not has_levels:
                # Try to detect if this IS a worlds or levels folder directly
                if self._check_world_data(self.patch_folder):
                    print("Detected patch folder as direct worlds folder")
                    worlds_dir = self.patch_folder
                    has_worlds = True
                    levels_dir = None
                    has_levels = False
                elif self._check_level_data(self.patch_folder):
                    print("Detected patch folder as direct levels folder")
                    levels_dir = self.patch_folder
                    has_levels = True
                    worlds_dir = None
                    has_worlds = False
                else:
                    self.error_occurred.emit(
                        f"Could not find 'worlds' or 'levels' subdirectories in:\n{self.patch_folder}\n\n"
                        f"Please ensure your patch folder contains these directories,\n"
                        f"or select the worlds/levels folder directly."
                    )
                    return
            
            print(f"Scanning with worlds_dir={worlds_dir}, levels_dir={levels_dir}")
            
            self.progress_updated.emit(10, "Scanning worlds folder...")
            
            # Get all world folders
            world_folders = {}
            if has_worlds and worlds_dir:
                self._log(f"Scanning worlds directory: {os.path.basename(worlds_dir)}")
                try:
                    items = os.listdir(worlds_dir)
                    print(f"Found {len(items)} items in worlds directory")
                    
                    for item in items:
                        if self.should_stop:
                            return
                            
                        item_path = os.path.join(worlds_dir, item)
                        if os.path.isdir(item_path):
                            # FCB conversion happens at level-load time, not during scan.
                            # Check for FCB or XML files directly to validate the folder.
                            has_world_data = self._check_world_data(item_path)
                            if has_world_data:
                                world_folders[item] = item_path
                                self._log(f"  ✓ {item}")
                            else:
                                print(f"  ✗ Not a valid world folder: {item}")
                except Exception as e:
                    print(f"Error scanning worlds: {e}")
            
            # Debug output for world folders
            print(f"\nWorld folders found:")
            for name, path in world_folders.items():
                print(f"  {name}: {path}")
            
            self.progress_updated.emit(30, f"Found {len(world_folders)} world folders")
            
            # Get all level folders
            level_folders = {}
            if has_levels and levels_dir:
                self._log(f"Scanning levels directory: {os.path.basename(levels_dir)}")
                try:
                    items = os.listdir(levels_dir)
                    print(f"Found {len(items)} items in levels directory")
                    
                    for item in items:
                        if self.should_stop:
                            return
                            
                        item_path = os.path.join(levels_dir, item)
                        if os.path.isdir(item_path):
                            # Check for worldsectors folder
                            has_level_data = self._check_level_data(item_path)
                            if has_level_data:
                                level_folders[item] = item_path
                                self._log(f"  ✓ {item}")
                            else:
                                print(f"  ✗ Not a valid level folder: {item}")
                except Exception as e:
                    print(f"Error scanning levels: {e}")
            
            # Debug output for level folders
            print(f"\nLevel folders found:")
            for name, path in level_folders.items():
                print(f"  {name}: {path}")
            
            self.progress_updated.emit(50, f"Found {len(level_folders)} level folders")
            
            # Continue even if we only have one type of folder
            print(f"Proceeding with {len(world_folders)} worlds and {len(level_folders)} levels")
            
            # Match world and level folders
            self.progress_updated.emit(60, "Matching world and level folders...")
            
            # Debug output for matching
            print(f"\nMatching results:")
            for world_name in world_folders:
                matches = self._find_matching_level(world_name, level_folders)
                print(f"  {world_name} -> {matches}")
            
            for folder_name in world_folders:
                if self.should_stop:
                    return

                # Try to find matching level folder
                matching_levels = self._find_matching_level(folder_name, level_folders)

                if matching_levels:
                    # All matched level folders are combined into a single LevelInfo entry.
                    # For multi-part levels (e.g. sp_drifting_sierra_fm_01_l1 + _l2) this
                    # means both folders are loaded together as one level.
                    # For FC2 world1/world2, all 25 grid cells are combined as one big map.
                    all_level_paths = [level_folders[lf] for lf in matching_levels]
                    primary_level_path = all_level_paths[0]

                    level_info = LevelInfo(
                        name=folder_name,
                        worlds_path=world_folders[folder_name],
                        levels_path=primary_level_path,        # kept for backward compat
                        levels_paths=all_level_paths,          # full list for multi-part loading
                    )

                    # Check for thumbnail
                    thumbnail_path = self._find_thumbnail(folder_name)
                    if thumbnail_path:
                        level_info.thumbnail_path = thumbnail_path

                    # Accumulate file counts across all level parts
                    combined_counts = {'xml_files': 0, 'fcb_files': 0, 'objects': 0, 'terrain_files': 0}
                    for lp in all_level_paths:
                        part_counts = self._count_files(world_folders[folder_name], lp)
                        for k in combined_counts:
                            combined_counts[k] += part_counts.get(k, 0)
                    level_info.file_counts = combined_counts

                    # Terrain/objects: true if any part has them
                    level_info.has_terrain = any(self._check_for_terrain(lp) for lp in all_level_paths)
                    level_info.has_objects = combined_counts.get('objects', 0) > 0

                    # Display name — note multi-part in the name so the user knows
                    base_name = self._format_display_name(folder_name)
                    if len(matching_levels) > 1:
                        level_info.display_name = f"{base_name} ({len(matching_levels)} parts)"
                    else:
                        level_info.display_name = base_name

                    levels_data[folder_name] = level_info
            
            self.progress_updated.emit(90, f"Matched {len(levels_data)} complete levels")
            
            # Also add level-only entries for unmatched level folders
            for level_name, level_path in level_folders.items():
                # Check if this level has been matched already
                already_matched = False
                for data in levels_data.values():
                    # levels_paths contains all parts; fall back to levels_path for old entries
                    all_paths = data.levels_paths if data.levels_paths else ([data.levels_path] if data.levels_path else [])
                    if level_path in all_paths:
                        already_matched = True
                        break
                
                if not already_matched:
                    # Try to find a matching world folder name (without _l suffix)
                    potential_world_name = level_name.replace('_l', '').replace('_l1', '').replace('_l2', '')
                    
                    # Create a level-only entry
                    level_info = LevelInfo(
                        name=potential_world_name,
                        worlds_path=None,  # No world data found
                        levels_path=level_path
                    )
                    
                    # Check for thumbnail
                    thumbnail_path = self._find_thumbnail(potential_world_name)
                    if thumbnail_path:
                        level_info.thumbnail_path = thumbnail_path
                    
                    # Get file counts
                    level_info.file_counts = self._count_files(None, level_path)
                    
                    # Check for terrain and objects
                    level_info.has_terrain = self._check_for_terrain(level_path)
                    level_info.has_objects = level_info.file_counts.get('objects', 0) > 0
                    
                    # Set display name
                    level_info.display_name = f"{self._format_display_name(potential_world_name)} (Objects Only)"
                    
                    levels_data[f"{potential_world_name}_objects_only"] = level_info
                    print(f"Added objects-only level: {potential_world_name}")
            
            # Also add unmatched world folders (world-only levels)
            for folder_name in world_folders:
                if folder_name not in levels_data:
                    level_info = LevelInfo(
                        name=folder_name,
                        worlds_path=world_folders[folder_name],
                        levels_path=None
                    )
                    
                    thumbnail_path = self._find_thumbnail(folder_name)
                    if thumbnail_path:
                        level_info.thumbnail_path = thumbnail_path
                    
                    level_info.display_name = f"{self._format_display_name(folder_name)} (World Only)"
                    levels_data[f"{folder_name}_world_only"] = level_info
            
            self.progress_updated.emit(100, "Scan complete!")
            
            # Log summary
            print(f"\nScan Summary:")
            print(f"  World folders found: {len(world_folders)}")
            print(f"  Level folders found: {len(level_folders)}")
            print(f"  Total entries created: {len(levels_data)}")
            
            # If we have any levels (even without worlds), that's success
            if levels_data:
                self.scan_complete.emit(levels_data)
            elif level_folders:
                # We have level folders but couldn't create entries - create basic entries
                print("Warning: Have level folders but no entries created, creating basic entries...")
                for level_name, level_path in level_folders.items():
                    level_info = LevelInfo(
                        name=level_name,
                        worlds_path=None,
                        levels_path=level_path,
                        display_name=f"{self._format_display_name(level_name)} (Level Only)"
                    )
                    levels_data[f"{level_name}_level_only"] = level_info
                self.scan_complete.emit(levels_data)
            else:
                # No data at all
                self.error_occurred.emit(
                    f"No valid level data found in the selected folder.\n\n"
                    f"Found:\n"
                    f"• {len(world_folders)} world folders\n"
                    f"• {len(level_folders)} level folders\n\n"
                    f"Please ensure your patch folder has the correct structure."
                )
            
        except Exception as e:
            self.error_occurred.emit(f"Error scanning patch folder: {str(e)}")

    def _check_world_data(self, folder_path: str) -> bool:
        """Dispatch to the correct world-data validator based on game mode."""
        if self.game_mode == "farcry2":
            return self._check_world_data_fc2(folder_path)
        return self._check_world_data_avatar(folder_path)

    def _check_world_data_avatar(self, folder_path: str) -> bool:
        """
        Avatar: The Game — world folders live under worlds/<level_name>/generated/
        and must contain at least 2 of: mapsdata, managers, omnis, sectorsdep,
        entitylibrary_full  (.fcb or .xml).
        """
        required_files = ['mapsdata', 'managers', 'omnis', 'sectorsdep', 'entitylibrary_full']
        found_files = set()

        generated_path = os.path.join(folder_path, 'generated')
        search_path = generated_path if os.path.exists(generated_path) else folder_path
        print(f"    [Avatar] Checking {os.path.basename(search_path)}...")

        try:
            if os.path.isdir(search_path):
                for file in os.listdir(search_path):
                    file_lower = file.lower()
                    for req in required_files:
                        if req in file_lower and (file_lower.endswith('.fcb') or file_lower.endswith('.xml')):
                            found_files.add(req)
                            print(f"      Found: {file}")
                            break
                if len(found_files) >= 2:
                    print(f"    ✓ {os.path.basename(folder_path)}: {len(found_files)} required files")
                    return True

            # Fallback: search subdirectories up to depth 2
            if len(found_files) < 2:
                for root, dirs, files in os.walk(folder_path):
                    depth = root[len(folder_path):].count(os.sep)
                    if depth > 2:
                        dirs.clear()
                        continue
                    for file in files:
                        file_lower = file.lower()
                        for req in required_files:
                            if req in file_lower and (file_lower.endswith('.fcb') or file_lower.endswith('.xml')):
                                found_files.add(req)
                                if len(found_files) >= 2:
                                    print(f"    ✓ {os.path.basename(folder_path)}: found in subdirectories")
                                    return True
        except Exception as e:
            print(f"    Error checking {folder_path}: {e}")
            return False

        if found_files:
            print(f"    Partial: {os.path.basename(folder_path)} has {len(found_files)}: {', '.join(found_files)}")
        return len(found_files) >= 2

    def _check_world_data_fc2(self, folder_path: str) -> bool:
        """
        Far Cry 2 — world folders (e.g. world1, world2, mp_02_s_shanty) contain
        .fcb/.xml files directly or in subdirectories.
        We consider a folder valid if it contains ANY .fcb or .xml file within
        2 levels of depth (FC2 does not use the Avatar 'generated' convention).
        """
        print(f"    [FC2] Checking {os.path.basename(folder_path)}...")
        try:
            for root, dirs, files in os.walk(folder_path):
                depth = root[len(folder_path):].count(os.sep)
                if depth > 2:
                    dirs.clear()
                    continue
                for file in files:
                    file_lower = file.lower()
                    if file_lower.endswith('.fcb') or file_lower.endswith('.xml'):
                        print(f"    ✓ {os.path.basename(folder_path)}: found {file}")
                        return True
        except Exception as e:
            print(f"    Error checking {folder_path}: {e}")
        print(f"    ✗ {os.path.basename(folder_path)}: no FCB/XML files found")
        return False
    
    def _find_matching_level(self, world_folder: str, level_folders: dict) -> list:
        """Dispatch to the correct matching logic based on game mode."""
        if self.game_mode == "farcry2":
            return self._find_matching_level_fc2(world_folder, level_folders)
        return self._find_matching_level_avatar(world_folder, level_folders)

    def _find_matching_level_avatar(self, world_folder: str, level_folders: dict) -> list:
        """
        Avatar: The Game matching rules.
        Most worlds pair with a level folder that has the same name plus a "_l",
        "_l1", "_l2" … suffix.  A small special-cases dict covers known exceptions.
        Returns a list because some worlds span multiple level folders.
        """
        matches = []

        # Pattern 1: Exact match
        if world_folder in level_folders:
            return [world_folder]

        # Pattern 2: world_name + "_l"
        if f"{world_folder}_l" in level_folders:
            matches.append(f"{world_folder}_l")

        # Pattern 3: world_name + "_l1" … "_l4"
        for i in range(1, 5):
            candidate = f"{world_folder}_l{i}"
            if candidate in level_folders and candidate not in matches:
                matches.append(candidate)

        # Pattern 4: any level that starts with world_name + "_"
        for level_name in level_folders:
            if level_name not in matches and level_name.startswith(f"{world_folder}_"):
                matches.append(level_name)

        # Known mismatches / no-suffix exceptions
        special_cases = {
            "sp_pascal_rf04":              ["sp_pascal_rf03_l"],
            "sp_pascal_rf_03":             ["sp_pascal_rf03_l"],   # underscore vs no-underscore mismatch
            "sp_vaderashallow_rf_fm_01":   ["sp_vaderashollow_rf_fm_01_l"],  # spelling mismatch (a vs o)
            "sp_jeannormand_df_01":        ["sp_jeannormand_df_01"],
            "mp_hellsgate_02":             ["mp_hellsgate_02"],
            "mp_jeannormand_of_01":        ["mp_jeannormand_of_01"],
            "mp_jeannormand_rf_02":        ["mp_jeannormand_rf_02"],
            "sp_philippe_rf_rb_01":        ["sp_philippe_rf_rb_01"],
            "z_anim_creatures":            ["z_anim_creatures"],
        }
        if world_folder in special_cases and not matches:
            for special_level in special_cases[world_folder]:
                if special_level in level_folders:
                    matches.append(special_level)

        # Last resort: substring matching
        if not matches:
            for level_name in level_folders:
                if world_folder.lower() in level_name.lower() or level_name.lower() in world_folder.lower():
                    matches.append(level_name)
                    print(f"  Partial match: {world_folder} -> {level_name}")

        return matches

    def _find_matching_level_fc2(self, world_folder: str, level_folders: dict) -> list:
        """
        Far Cry 2 matching rules.

        The two open-world maps are special:
          world1  ->  w1_a_1 … w1_e_5   (all 25 grid sectors)
          world2  ->  w2_a_1 … w2_e_5   (all 25 grid sectors)

        Every multiplayer map uses an exact name match
          e.g. mp_02_s_shanty  ->  mp_02_s_shanty

        Misc entries (ige_map, tmpla) also use exact match.
        """
        matches = []

        # Open-world maps: world1 / world2  ->  w1_* / w2_*
        world_prefix_map = {
            "world1": "w1_",
            "world2": "w2_",
        }
        if world_folder in world_prefix_map:
            prefix = world_prefix_map[world_folder]
            for level_name in sorted(level_folders):
                if level_name.startswith(prefix):
                    matches.append(level_name)
            if matches:
                print(f"  [FC2] {world_folder} -> {len(matches)} grid sectors ({matches[0]} … {matches[-1]})")
            return matches

        # Everything else: exact name match (mp_*, ige_map, tmpla, …)
        if world_folder in level_folders:
            matches.append(world_folder)
            print(f"  [FC2] Exact match: {world_folder}")
            return matches

        # Fallback: substring match (should rarely trigger)
        for level_name in level_folders:
            if world_folder.lower() in level_name.lower():
                matches.append(level_name)
                print(f"  [FC2] Partial match: {world_folder} -> {level_name}")

        return matches

    def _check_level_data(self, folder_path: str) -> bool:
        """Dispatch to the correct level-data validator based on game mode."""
        if self.game_mode == "farcry2":
            return self._check_level_data_fc2(folder_path)
        return self._check_level_data_avatar(folder_path)

    def _check_level_data_avatar(self, folder_path: str) -> bool:
        """
        Avatar: The Game — level folders must contain a 'worldsectors' subfolder
        with at least one .data.fcb or .data.xml file inside it.
        """
        for root, dirs, files in os.walk(folder_path):
            depth = root[len(folder_path):].count(os.sep)
            if depth > 3:
                dirs.clear()
                continue

            current_dir = os.path.basename(root).lower()
            if current_dir in ('worldsectors', 'worldsector'):
                data_files = [f for f in files if '.data.fcb' in f.lower() or '.data.xml' in f.lower()]
                if data_files:
                    print(f"    Found worldsectors in {os.path.basename(folder_path)} with {len(data_files)} data files")
                    return True

            for dir_name in dirs:
                if dir_name.lower() in ('worldsectors', 'worldsector'):
                    ws_path = os.path.join(root, dir_name)
                    try:
                        ws_files = os.listdir(ws_path)
                        data_files = [f for f in ws_files if '.data.fcb' in f.lower() or '.data.xml' in f.lower()]
                        if data_files:
                            print(f"    Found worldsectors in {os.path.basename(folder_path)}/{dir_name} with {len(data_files)} data files")
                            return True
                    except:
                        continue

        return False

    def _check_level_data_fc2(self, folder_path: str) -> bool:
        """
        Far Cry 2 — level folders contain .fcb/.xml files directly or inside
        subfolders (worldsectors, sdat, etc.).  We accept ANY folder that has
        at least one .fcb or .xml file within 3 levels of depth.
        The 'worldsectors' convention used by Avatar does NOT apply here.
        """
        print(f"    [FC2] Level check: {os.path.basename(folder_path)}...")
        try:
            for root, dirs, files in os.walk(folder_path):
                depth = root[len(folder_path):].count(os.sep)
                if depth > 3:
                    dirs.clear()
                    continue
                for file in files:
                    file_lower = file.lower()
                    if file_lower.endswith('.fcb') or file_lower.endswith('.xml'):
                        print(f"    ✓ {os.path.basename(folder_path)}: found {file}")
                        return True
        except Exception as e:
            print(f"    Error checking level {folder_path}: {e}")
        print(f"    ✗ {os.path.basename(folder_path)}: no FCB/XML files found")
        return False
    
    def _check_for_terrain(self, level_path: str) -> bool:
        """Check if level has terrain data (searches recursively for sdat folder)"""
        if not level_path:
            return False
        
        # Search up to 3 levels deep for sdat folder
        for root, dirs, files in os.walk(level_path):
            # Limit search depth
            depth = root[len(level_path):].count(os.sep)
            if depth > 3:
                dirs.clear()  # Don't go deeper
                continue
            
            # Check if current directory is named sdat (case-insensitive)
            current_dir = os.path.basename(root).lower()
            if current_dir == 'sdat':
                # Check for terrain files
                terrain_files = [f for f in files if '.csdat' in f.lower() or '.dat' in f.lower()]
                if terrain_files:
                    return True
            
            # Also check subdirectories
            for dir_name in dirs:
                if dir_name.lower() == 'sdat':
                    return True
        
        return False
    
    def _find_thumbnail(self, level_name: str) -> Optional[str]:
        """Find thumbnail image for the level"""
        # Look in various possible locations
        thumbnail_dirs = [
            os.path.join(self.patch_folder, "thumbnails"),
            os.path.join(self.patch_folder, "images"),
            os.path.join(self.patch_folder, "worlds", level_name),
            os.path.join(self.patch_folder, "levels", level_name)
        ]
        
        # Common thumbnail patterns
        patterns = [
            f"{level_name}.png",
            f"{level_name}_thumb.png",
            f"{level_name}_thumbnail.png",
            "thumbnail.png",
            "thumb.png",
            "preview.png"
        ]
        
        for thumb_dir in thumbnail_dirs:
            if os.path.exists(thumb_dir):
                for pattern in patterns:
                    thumb_path = os.path.join(thumb_dir, pattern)
                    if os.path.exists(thumb_path):
                        return thumb_path
        
        return None
    
    def _count_files(self, worlds_path: str, levels_path: str) -> Dict[str, int]:
        """Count various file types in the level (searches recursively)"""
        counts = {
            'xml_files': 0,
            'fcb_files': 0,
            'objects': 0,
            'terrain_files': 0
        }
        
        # Count world files recursively
        if worlds_path and os.path.exists(worlds_path):
            for root, dirs, files in os.walk(worlds_path):
                # Limit search depth
                depth = root[len(worlds_path):].count(os.sep)
                if depth > 3:
                    dirs.clear()
                    continue
                
                counts['xml_files'] += len([f for f in files if f.lower().endswith('.xml')])
                counts['fcb_files'] += len([f for f in files if f.lower().endswith('.fcb')])
        
        # Count level objects recursively
        if levels_path and os.path.exists(levels_path):
            for root, dirs, files in os.walk(levels_path):
                # Limit search depth
                depth = root[len(levels_path):].count(os.sep)
                if depth > 3:
                    dirs.clear()
                    continue
                
                # Check if in worldsectors directory
                if 'worldsectors' in root.lower() or 'worldsector' in root.lower():
                    counts['objects'] += len([f for f in files if '.data.fcb' in f.lower() or '.data.xml' in f.lower()])
                
                # Check if in sdat directory
                if 'sdat' in root.lower():
                    counts['terrain_files'] += len([f for f in files if '.csdat' in f.lower() or '.dat' in f.lower()])
        
        return counts
    
    def _format_display_name(self, folder_name: str) -> str:
        """Dispatch to the correct display-name formatter based on game mode."""
        if self.game_mode == "farcry2":
            return self._format_display_name_fc2(folder_name)
        return self._format_display_name_avatar(folder_name)

    def _format_display_name_avatar(self, folder_name: str) -> str:
        """Format folder name for display - Avatar: The Game specific formatting."""
        
        known_maps = {
            "coop_pascal_01": "Stalker's Valley",
            "menu": "Main Menu",
            "mp_ancientgrounds_03": "MP: Unil Tukru",
            "mp_bluelagoon_rb_01": "MP: Blue Lagoon",
            "mp_brokencage_rf_01": "MP: Broken Cage",
            "mp_dustbowl_rb_01": "MP: Swotulu",
            "mp_fogswamp_rb_01": "MP: Na'rìng",
            "mp_forsakencaldera_rf_01": "MP: Freyna Taron",
            "mp_gravesbog_rb_01": "MP: Grave's Bog",
            "mp_hellsgate_02": "MP: Hell's Gate",
            "mp_hometree": "MP: Hometree",
            "mp_jeannormand_of_01": "MP: Kxanìa Taw",
            "mp_jeannormand_rf_02": "MP: No'ani Tei",
            "mp_kowecave_fm_01": "MP: Mining Facility",
            "mp_kowevillage_fm_01": "MP: Vul Nawm",
            "mp_mridge_df_01": "MP: Ngay Rey",
            "mp_needlehills_rb_01": "MP: Needle Hills",
            "mp_ps3map": "MP: Asa'anga",
            "mp_vaderashollow_fm_01": "MP: Va'erä Ramunong",
            "mp_verdantpinnacle_fm_01": "MP: Iknimaya",
            "sp_bonusmap_01": "SP: Echo Chasm",
            "sp_coualthighlands_of_rf_01": "SP: The Hanging Gardens",
            "sp_drifting_sierra_fm_01": "SP: Tantalus (Ta'antasi)",
            "sp_dustbowl_hg_rb_01": "SP: Swotulu",
            "sp_gravesbog_rb_of_01": "SP: Grave's Bog",
            "sp_hellsgate_01": "SP: Hell's Gate",
            "sp_hometree": "SP: Hometree",
            "sp_jeannormand_df_01": "SP: Lost Cathedral",
            "sp_nancy_of_02": "SP: Kxanìa Taw",
            "sp_needlehills_rb_fm_01": "SP: Needle Hills",
            "sp_pascal_fm_01": "SP: Torukä Na'rìng (I)",
            "sp_pascal_rf04": "SP: Camp Navarone",
            "sp_pascal_rf_03": "SP: Torukä Na'rìng (II)",
            "sp_philippe_rf_rb_01": "SP: The FEBA",
            "sp_plainsofgoliath_of_fm_01": "SP: Plains Of Goliath (Kaoliä Tei)",
            "sp_sebastien_rb_02": "SP: Blue Lagoon",
            "sp_vaderashallow_rf_fm_01": "SP: Va'erä Ramunong",
            "z_anim_creatures": "Dev Room: Animation Creatures",
            "z_dev_orouleau": "Dev Room: Orouleau",
            "z_mpgamemodes": "MP Game Modes",
        }

        return known_maps.get(folder_name.lower(), folder_name)

    def _format_display_name_fc2(self, folder_name: str) -> str:
        """
        Far Cry 2 display-name formatting.

        Open-world sector names follow the pattern  w<map>_<row>_<col>
          e.g.  w1_a_1  ->  "World 1 — Sector A1"
                w2_e_5  ->  "World 2 — Sector E5"

        Multiplayer maps follow  mp_<num>_<size>_<name>
          e.g.  mp_02_s_shanty  ->  "MP: Shanty Town (S)"

        Misc entries are title-cased with underscores replaced by spaces.
        """
        # Open-world grid sectors: w1_a_1 … w2_e_5
        import re
        sector_match = re.match(r"^w([12])_([a-e])_([1-5])$", folder_name, re.IGNORECASE)
        if sector_match:
            world_num = sector_match.group(1)
            row = sector_match.group(2).upper()
            col = sector_match.group(3)
            return f"World {world_num} — Sector {row}{col}"

        # Multiplayer maps: mp_<num>_<size>_<name>
        mp_match = re.match(r"^mp_(\d+)_([sml])_(.+)$", folder_name, re.IGNORECASE)
        if mp_match:
            size_code = mp_match.group(2).upper()
            raw_name  = mp_match.group(3)
            # Known FC2 MP map names
            fc2_mp_names = {
                "shanty":         "Shanty Town",
                "ranch":          "Ranch",
                "dogon":          "Dogon Village",
                "colony":         "The Colony",
                "fishingvillage": "Fishing Village",
                "savanna":        "Savanna",
                "fueldepot":      "Fuel Depot",
                "woodlands":      "Woodlands",
                "mine":           "The Mine",
                "airbase":        "Airbase",
                "dunes":          "Dunes",
                "greenhouse":     "Greenhouse",
                "town":           "Town",
                "dusttown":       "Dusty Town",
                "prison":         "Prison",
            }
            pretty = fc2_mp_names.get(raw_name.lower(), raw_name.replace("_", " ").title())
            return f"MP: {pretty} ({size_code})"

        # Misc / fallback (ige_map, tmpla, world1, world2, …)
        misc_names = {
            "world1":  "World 1 (Leboa-Sako)",
            "world2":  "World 2 (Bowa-Seko)",
            "ige_map": "IGE Map",
            "tmpla":   "Template A",
        }
        return misc_names.get(folder_name.lower(), folder_name.replace("_", " ").title())
    
    def stop(self):
        """Stop the scanning thread"""
        self.should_stop = True

class FadingLabel(QLabel):
    """QLabel with fade in/out animation support"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._opacity = 1.0
        self.setAutoFillBackground(False)  # Important for transparency
        
    @pyqtProperty(float)
    def opacity(self):
        return self._opacity
    
    @opacity.setter
    def opacity(self, value):
        self._opacity = value
        self.update()  # Trigger repaint
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setOpacity(self._opacity)
        
        # Draw the pixmap with opacity
        if self.pixmap() and not self.pixmap().isNull():
            scaled_pixmap = self.pixmap()
            # Center the pixmap
            x = (self.width() - scaled_pixmap.width()) // 2
            y = (self.height() - scaled_pixmap.height()) // 2
            painter.drawPixmap(x, y, scaled_pixmap)
        else:
            # If no pixmap, draw text
            painter.setPen(QColor(136, 136, 136))  # #888
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
        
        painter.end()

class LevelButton(QPushButton):
    """Custom button widget for level selection with thumbnail carousel support"""

    level_selected = pyqtSignal(LevelInfo)

    THUMBNAILS_DIR = "thumbnails"  # central folder for all PNGs

    def __init__(self, level_info: LevelInfo, default_thumbnail: str = "thumbnails/default.png",
                 annotation=None, thumbnail_width: int = 250, thumbnail_height: int = 140):
        super().__init__()
        self.level_info = level_info
        self.default_thumbnail = default_thumbnail
        self.annotation = annotation or []
        self.thumbnail_width = thumbnail_width
        self.thumbnail_height = thumbnail_height

        # Find all thumbnails for this level
        self.thumbnail_paths = self._find_all_thumbnails()
        self.current_thumbnail_index = 0
        self.is_transitioning = False  # Flag to prevent overlapping transitions

        self.setFixedSize(self.thumbnail_width + 20, self.thumbnail_height + 110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.setup_ui()

        # *** NEW: Update model loader with game-specific paths ***
        if hasattr(self, 'canvas') and hasattr(self.canvas, 'model_loader'):
            from canvas.game_paths_config import update_model_loader_for_game
            update_model_loader_for_game(
                self.canvas.model_loader,
                self.game_path_config
            )

        # Setup thumbnail rotation if multiple found
        if len(self.thumbnail_paths) > 1:
            self.rotation_timer = QTimer(self)
            self.rotation_timer.timeout.connect(self.rotate_thumbnail)
            # Total cycle: 2s display + 1s fade out + 2s display + 1s fade in = 4s per image
            self.rotation_timer.start(4000)  # Start next transition every 4 seconds

        self.clicked.connect(lambda: self.level_selected.emit(self.level_info))

    def _find_all_thumbnails(self) -> List[str]:
        """Find all PNG thumbnails for this level (handles variants like _a, _b, _corp, _navi)"""
        thumbnails = []
        level_name = self.level_info.name
        thumbs_dir = self.THUMBNAILS_DIR

        if not os.path.exists(thumbs_dir):
            return thumbnails

        # Get all PNGs in thumbnails directory
        all_pngs = [f for f in os.listdir(thumbs_dir) if f.endswith('.png')]

        # Find all that match this level
        for png in all_pngs:
            # Check if PNG starts with level name
            if png.startswith(level_name):
                # Make sure it's actually this level and not a longer named level
                # e.g., sp_hellsgate_01 should match sp_hellsgate_01.png and sp_hellsgate_01_a.png
                # but not sp_hellsgate_01_something_else.png
                png_base = png.replace('.png', '')
                if png_base == level_name or png_base.startswith(f"{level_name}_"):
                    thumbnails.append(os.path.join(thumbs_dir, png))

        # Sort to ensure consistent order (base image first if it exists)
        thumbnails.sort()

        return thumbnails

    def rotate_thumbnail(self):
        """Rotate to next thumbnail with fade transition"""
        if len(self.thumbnail_paths) > 1 and not self.is_transitioning:
            self.is_transitioning = True

            # Fade out current image
            self.fade_out_animation = QPropertyAnimation(self.thumbnail_label, b"opacity")
            self.fade_out_animation.setDuration(800)  # 1 second fade out
            self.fade_out_animation.setStartValue(1.0)
            self.fade_out_animation.setEndValue(0.0)
            self.fade_out_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

            # When fade out completes, load next image and fade in
            self.fade_out_animation.finished.connect(self.on_fade_out_complete)
            self.fade_out_animation.start()

    def on_fade_out_complete(self):
        """Called when fade out animation completes"""
        # Move to next thumbnail
        self.current_thumbnail_index = (self.current_thumbnail_index + 1) % len(self.thumbnail_paths)

        # Load the new image
        if self.thumbnail_paths:
            pixmap = QPixmap(self.thumbnail_paths[self.current_thumbnail_index])
            if pixmap and not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    self.thumbnail_width, self.thumbnail_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.thumbnail_label.setPixmap(scaled_pixmap)

        # Fade in the new image
        self.fade_in_animation = QPropertyAnimation(self.thumbnail_label, b"opacity")
        self.fade_in_animation.setDuration(800)  # 1 second fade in
        self.fade_in_animation.setStartValue(0.0)
        self.fade_in_animation.setEndValue(1.0)
        self.fade_in_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.fade_in_animation.finished.connect(self.on_fade_in_complete)
        self.fade_in_animation.start()

    def on_fade_in_complete(self):
        """Called when fade in animation completes"""
        self.is_transitioning = False

    def update_thumbnail_display(self):
        """Update the displayed thumbnail"""
        if not self.thumbnail_paths or not hasattr(self, 'thumbnail_label'):
            return

        pixmap = QPixmap(self.thumbnail_paths[self.current_thumbnail_index])
        if pixmap and not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(
                self.thumbnail_width, self.thumbnail_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.thumbnail_label.setPixmap(scaled_pixmap)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 5, 5, 5)

        # --- Thumbnail ---
        self.thumbnail_label = FadingLabel()  # Use FadingLabel instead of QLabel
        self.thumbnail_label.setFixedSize(self.thumbnail_width, self.thumbnail_height)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("""
            QLabel {
                border: 1px solid #555;
                border-radius: 5px;
                background-color: #2b2b2b;
            }
        """)

        # Load first thumbnail or default
        pixmap = None
        if self.thumbnail_paths:
            pixmap = QPixmap(self.thumbnail_paths[0])
        elif self.default_thumbnail and os.path.exists(self.default_thumbnail):
            pixmap = QPixmap(self.default_thumbnail)

        if pixmap and not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(
                self.thumbnail_width - 10, self.thumbnail_height - 10,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.thumbnail_label.setPixmap(scaled_pixmap)
        else:
            self.thumbnail_label.setText("No Preview")
            self.thumbnail_label.setStyleSheet("""
                QLabel {
                    border: 1px solid #555;
                    border-radius: 5px;
                    background-color: #1e1e1e;
                    color: #888;
                    font-size: 18px;
                }
            """)

        layout.addWidget(self.thumbnail_label)

        # --- Level Name ---
        name_label = QLabel(self.level_info.display_name or self.level_info.name)
        name_label.setWordWrap(True)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 16px;
                font-weight: bold;
                padding: 5px;
            }
        """)
        layout.addWidget(name_label)

        # --- Info / Annotations ---
        info_text = self.annotation.copy()
        if getattr(self.level_info, 'has_terrain', False):
            info_text.append("Terrain")
        if getattr(self.level_info, 'has_objects', False):
            obj_count = self.level_info.file_counts.get('objects', 0)
            info_text.append(f"{obj_count} Objects")

        # Add thumbnail count if multiple
        if len(self.thumbnail_paths) > 1:
            info_text.append(f"{len(self.thumbnail_paths)} views")

        if info_text:
            info_label = QLabel(" | ".join(info_text))
            info_label.setWordWrap(True)
            info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            info_label.setStyleSheet("""
                QLabel {
                    color: #888;
                    font-size: 14px;
                }
            """)
            layout.addWidget(info_label)

        # --- Button Styling ---
        self.setStyleSheet("""
            QPushButton {
                background-color: #2b2b2b;
                border: 2px solid #444;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #353535;
                border: 2px solid #0d7377;
            }
            QPushButton:pressed {
                background-color: #1e1e1e;
                border: 2px solid #14ffec;
            }
        """)

    def disable_rotate(self):
        if hasattr(self, 'rotation_timer') and self.rotation_timer is not None:
            self.rotation_timer.stop()
        if hasattr(self, 'fade_out_animation') and self.fade_out_animation is not None:
            self.fade_out_animation.stop()
            self.fade_out_animation = None
        if hasattr(self, 'fade_in_animation') and self.fade_in_animation is not None:
            self.fade_in_animation.stop()
            self.fade_in_animation = None
        self.is_transitioning = False

    def on_click(self):
        print(f"[DEBUG] LevelButton clicked: {self.level_info.name}")
        self.level_selected.emit(self.level_info)

class LevelSelectorDialog(QDialog):
    """Dialog for visual level selection"""
    level_selected = pyqtSignal(dict)  # Emits level_info dict for loading
    patch_folder_change_requested = pyqtSignal()  # Emits when user wants to change patch folder

    def __init__(self, levels_data: Dict[str, LevelInfo], parent=None, game_mode="avatar", patch_manager=None):
        super().__init__(parent)
        self.levels_data = levels_data
        self.game_mode = game_mode
        self.selected_level = None
        self.patch_manager = patch_manager

        self.setWindowTitle("Select Level")
        self.setModal(True)
        self.resize(1300, 850)

        print(f"[DEBUG] LevelSelectorDialog initialized with {len(self.levels_data)} levels")

        self.setup_ui()

    def setup_ui(self):
        """Setup the complete user interface"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # Determine theme colors based on parent's theme
        is_dark = False
        if self.parent() and hasattr(self.parent(), 'force_dark_theme'):
            is_dark = self.parent().force_dark_theme
        
        # Define theme colors
        if is_dark:
            colors = {
                'bg': '#2b2b2b',
                'bg_alt': '#1e1e1e',
                'button': '#404040',
                'button_hover': '#4a4a4a',
                'button_pressed': '#353535',
                'input': '#353535',
                'border': '#555555',
                'text': '#ffffff',
                'text_secondary': '#888888',
                'accent': '#0d7377',
            }
        else:
            colors = {
                'bg': '#f0f0f0',
                'bg_alt': '#ffffff',
                'button': '#e0e0e0',
                'button_hover': '#d0d0d0',
                'button_pressed': '#c0c0c0',
                'input': '#ffffff',
                'border': '#b0b0b0',
                'text': '#000000',
                'text_secondary': '#666666',
                'accent': '#0078d7',
            }

        # Header with patch folder info
        header_layout = QVBoxLayout()
        header_label = QLabel("Select a Level to Load")
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_label.setStyleSheet(f"""
            QLabel {{
                font-size: 16px; 
                font-weight: bold; 
                padding: 10px;
                color: {colors['text']};
            }}
        """)
        header_layout.addWidget(header_label)
        
        # Patch folder info and buttons
        patch_info_layout = QHBoxLayout()
        patch_info_layout.addStretch()
        
        # Patch folder label
        if self.patch_manager:
            patch_folder = self.patch_manager.get_patch_folder()
            if patch_folder:
                # Truncate long paths for display
                display_path = patch_folder
                if len(display_path) > 60:
                    display_path = "..." + display_path[-57:]
                folder_label = QLabel(f"Patch: {display_path}")
                folder_label.setStyleSheet(f"color: {colors['text_secondary']}; font-size: 11px;")
                folder_label.setToolTip(patch_folder)  # Show full path on hover
                patch_info_layout.addWidget(folder_label)
        
        # Resource folder label (NEW)
        if self.parent() and hasattr(self.parent(), 'resource_folder'):
            resource_folder = self.parent().resource_folder
            if resource_folder:
                display_resource = resource_folder
                if len(display_resource) > 60:
                    display_resource = "..." + display_resource[-57:]
                resource_label = QLabel(f"Resources: {display_resource}")
                resource_label.setStyleSheet(f"color: {colors['text_secondary']}; font-size: 11px;")
                resource_label.setToolTip(resource_folder)
                patch_info_layout.addWidget(resource_label)
            else:
                no_resource_label = QLabel("Resources: Not Set")
                no_resource_label.setStyleSheet(f"color: #ff6b6b; font-size: 11px;")
                no_resource_label.setToolTip("3D models will not be loaded without a resource folder")
                patch_info_layout.addWidget(no_resource_label)
        
        patch_info_layout.addSpacing(10)
        
        # Change Patch Folder button
        change_folder_btn = QPushButton("Change Patch Folder...")
        change_folder_btn.setMaximumWidth(180)
        change_folder_btn.clicked.connect(self.on_change_patch_folder)
        change_folder_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors['button']};
                border: 1px solid {colors['border']};
                border-radius: 4px;
                padding: 5px 10px;
                color: {colors['text']};
            }}
            QPushButton:hover {{
                background-color: {colors['button_hover']};
                border: 1px solid {colors['accent']};
            }}
            QPushButton:pressed {{
                background-color: {colors['button_pressed']};
            }}
        """)
        patch_info_layout.addWidget(change_folder_btn)
        
        # Change Resource Folder button (NEW)
        change_resource_btn = QPushButton("Set Resource Folder...")
        change_resource_btn.setMaximumWidth(180)
        change_resource_btn.clicked.connect(self.on_change_resource_folder)
        change_resource_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors['button']};
                border: 1px solid {colors['border']};
                border-radius: 4px;
                padding: 5px 10px;
                color: {colors['text']};
            }}
            QPushButton:hover {{
                background-color: {colors['button_hover']};
                border: 1px solid {colors['accent']};
            }}
            QPushButton:pressed {{
                background-color: {colors['button_pressed']};
            }}
        """)
        patch_info_layout.addWidget(change_resource_btn)
        
        patch_info_layout.addStretch()
        header_layout.addLayout(patch_info_layout)
        
        layout.addLayout(header_layout)

        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet(f"background-color: {colors['border']};")
        layout.addWidget(separator)

        # Filter and search controls
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)
        
        # Filter dropdown
        filter_label = QLabel("Filter:")
        filter_label.setStyleSheet(f"color: {colors['text']}; font-weight: bold;")
        filter_layout.addWidget(filter_label)
        
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            "All Levels", 
            "Complete Levels", 
            "World Only", 
            "Has Terrain", 
            "Has Objects"
        ])
        self.filter_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {colors['input']};
                border: 1px solid {colors['border']};
                border-radius: 4px;
                padding: 5px;
                color: {colors['text']};
                min-width: 150px;
            }}
            QComboBox:hover {{
                border: 1px solid {colors['accent']};
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {colors['text']};
                margin-right: 5px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {colors['input']};
                border: 1px solid {colors['border']};
                selection-background-color: {colors['accent']};
                color: {colors['text']};
            }}
        """)
        self.filter_combo.currentTextChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.filter_combo)

        filter_layout.addSpacing(20)

        # Search box
        search_label = QLabel("Search:")
        search_label.setStyleSheet(f"color: {colors['text']}; font-weight: bold;")
        filter_layout.addWidget(search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search levels...")
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {colors['input']};
                border: 1px solid {colors['border']};
                border-radius: 4px;
                padding: 5px;
                color: {colors['text']};
            }}
            QLineEdit:focus {{
                border: 1px solid {colors['accent']};
            }}
        """)
        self.search_input.textChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.search_input, 1)  # Stretch factor of 1

        layout.addLayout(filter_layout)

        # Level count label
        self.count_label = QLabel()
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count_label.setStyleSheet(f"color: {colors['text_secondary']}; font-size: 11px; padding: 5px;")
        layout.addWidget(self.count_label)

        # Scroll area for level buttons
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {colors['border']};
                background-color: {colors['bg_alt']};
            }}
            QScrollBar:vertical {{
                background-color: {colors['button']};
                width: 12px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background-color: {colors['border']};
                border-radius: 6px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {colors['accent']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        
        container = QWidget()
        self.grid_layout = QGridLayout(container)
        self.grid_layout.setSpacing(15)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
        scroll_area.setWidget(container)
        layout.addWidget(scroll_area, 1)  # Stretch factor of 1

        # Bottom buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_button = QPushButton("Cancel")
        cancel_button.setMinimumWidth(100)
        cancel_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors['button']};
                border: 1px solid {colors['border']};
                border-radius: 4px;
                padding: 8px 16px;
                color: {colors['text']};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors['button_hover']};
                border: 1px solid {colors['accent']};
            }}
            QPushButton:pressed {{
                background-color: {colors['button_pressed']};
            }}
        """)
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)

        # Populate levels
        self.populate_levels()
    
    def on_change_resource_folder(self):
        """Handle resource folder change request with XBG to GLTF conversion"""
        print("[DEBUG] Change resource folder requested")
        
        if not self.parent():
            QMessageBox.warning(
                self,
                "Error",
                "Cannot set resource folder: Parent window not available."
            )
            return
        
        # Import the function
        from set_patch_folder import set_resource_folder
        
        # Call set_resource_folder to let user select folder
        if not set_resource_folder(self.parent()):
            print("[DEBUG] Resource folder selection cancelled")
            return
        
        print("[DEBUG] Resource folder changed successfully")
        
        # Get the new resource folder path
        resource_folder = self.parent().resource_folder
        
        if not resource_folder or not os.path.exists(resource_folder):
            print("[DEBUG] No valid resource folder set")
            return
        
        # Check if canvas has model_loader
        if not hasattr(self.parent(), 'canvas') or not hasattr(self.parent().canvas, 'model_loader'):
            print("[DEBUG] Canvas does not have model_loader")
            QMessageBox.warning(
                self,
                "Model Loader Not Available",
                "3D model loader is not initialized.\n\n"
                "The resource folder has been saved but models cannot be scanned yet."
            )
            return
        
        canvas = self.parent().canvas
        model_loader = canvas.model_loader
        
        print("[DEBUG] Setting up 3D models from resource folder...")
        
        # Create progress dialog
        from simplified_map_editor import EnhancedProgressDialog
        
        progress_dialog = EnhancedProgressDialog(
            "Setting Up 3D Models",
            self,
            game_mode=self.game_mode
        )
        progress_dialog.append_log(f"Resource folder: {os.path.basename(resource_folder)}")

        scan_cancelled = [False]
        def on_resource_scan_cancelled():
            scan_cancelled[0] = True
        progress_dialog.cancelled.connect(on_resource_scan_cancelled)

        progress_dialog.show()
        QApplication.processEvents()

        try:
            # Step 1: Set models directory (graphics folder)
            models_path = os.path.join(resource_folder, "graphics")
            
            if not os.path.exists(models_path):
                progress_dialog.mark_complete()
                progress_dialog.close()
                QMessageBox.warning(
                    self,
                    "Graphics Folder Not Found",
                    f"The selected resource folder does not contain a 'graphics' subdirectory.\n\n"
                    f"Selected: {resource_folder}\n\n"
                    f"Please select your unpacked game data folder (e.g., Data_Win32)."
                )
                return
            
            progress_dialog.append_log(f"Found graphics folder: {models_path}")
            progress_dialog.set_progress(10)
            QApplication.processEvents()
            
            # Step 2: Set materials directory for textures
            materials_path = os.path.join(resource_folder, "graphics", "_materials")
            if not os.path.exists(materials_path):
                materials_path = os.path.join(resource_folder, "graphics", "materials")
            
            if os.path.exists(materials_path):
                model_loader.set_materials_directory(materials_path)
                progress_dialog.append_log(f"✓ Materials folder: {os.path.basename(materials_path)}")
            else:
                progress_dialog.append_log("⚠ Materials folder not found - models will render without textures")
            
            progress_dialog.set_progress(20)
            QApplication.processEvents()
            
            # Step 3: Check for XBG files
            progress_dialog.set_status("Checking for XBG model files...")
            progress_dialog.append_log("Scanning for XBG files...")
            QApplication.processEvents()
            
            xbg_files = []
            for _i, (_walk_root, _dirs, _walk_files) in enumerate(os.walk(models_path)):
                for file in _walk_files:
                    if file.lower().endswith('.xbg'):
                        xbg_files.append(os.path.join(_walk_root, file))
                if _i % 20 == 0:
                    QApplication.processEvents()
                    if scan_cancelled[0]:
                        progress_dialog.mark_complete()
                        progress_dialog.close()
                        return

            progress_dialog.append_log(f"Found {len(xbg_files)} XBG files")
            progress_dialog.set_progress(30)
            QApplication.processEvents()
            if scan_cancelled[0]:
                progress_dialog.mark_complete()
                progress_dialog.close()
                return
            
            # Steps 4 & 5 (removed): the editor now reads .xbg models DIRECTLY at
            # load time (no GLTF conversion). The old "Convert XBG Models?"
            # prompt + batch conversion are gone — there is nothing to convert.
            converted_count = 0
            progress_dialog.append_log(
                f"✓ {len(xbg_files)} XBG models — loaded directly, no conversion needed")

            progress_dialog.set_progress(70)
            QApplication.processEvents()
            if scan_cancelled[0]:
                progress_dialog.mark_complete()
                progress_dialog.close()
                return

            # Step 6: Index the models directory. This sets models_directory so
            # the direct loader can resolve .xbg paths (it walks the folder per
            # lookup; the index is just a diagnostic count).
            progress_dialog.set_status("Indexing models...")
            progress_dialog.append_log("Scanning the resource folder (may take a moment on large folders)...")
            QApplication.processEvents()
            if scan_cancelled[0]:
                progress_dialog.mark_complete()
                progress_dialog.close()
                return

            success = model_loader.set_models_directory(models_path, scan_recursive=True)

            if success:
                model_count = len(model_loader._models_index)
                progress_dialog.append_log(f"✓ Indexed {model_count} XBG models")
                progress_dialog.set_progress(100)
                progress_dialog.mark_complete()
                QApplication.processEvents()
                progress_dialog.close()

                QMessageBox.information(
                    self,
                    "Resource Folder Updated",
                    f"Resource folder has been set up successfully!\n\n"
                    f"✓ {len(xbg_files)} XBG models found — loaded directly from the game files\n"
                    f"  (no GLTF conversion, no cache)\n\n"
                    f"Models will load when you select a level."
                )
            else:
                progress_dialog.mark_complete()
                progress_dialog.close()
                QMessageBox.warning(
                    self,
                    "Indexing Failed",
                    f"Failed to index models directory.\n\n{models_path}"
                )
        
        except Exception as e:
            progress_dialog.mark_complete()
            progress_dialog.close()
            QMessageBox.critical(
                self,
                "Setup Error",
                f"Error setting up resource folder:\n\n{str(e)}"
            )
            print(f"Error setting up resource folder: {e}")
            import traceback
            traceback.print_exc()

    def refresh_resource_folder_display(self):
        """Refresh only the resource folder display without rebuilding entire UI"""
        # Find the patch info layout and update the resource folder label
        if self.parent() and hasattr(self.parent(), 'resource_folder'):
            resource_folder = self.parent().resource_folder
            
            # For now, just show a simple message - full UI refresh requires dialog recreation
            # The user will see the updated path when they reopen the dialog
            print(f"[DEBUG] Resource folder updated: {resource_folder}")
        else:
            print("[DEBUG] Could not refresh resource folder display")
    
    def on_change_patch_folder(self):
        """Handle patch folder change request"""
        print("[DEBUG] Change patch folder requested")
        if self.patch_manager:
            print("[DEBUG] Calling set_patch_folder...")
            # Call set_patch_folder directly - this opens the folder browser
            if self.patch_manager.set_patch_folder():
                # Folder changed successfully, close and signal to rescan
                print("[DEBUG] Patch folder changed successfully, closing dialog")
                self.patch_folder_change_requested.emit()
                self.accept()  # Close with success
            else:
                print("[DEBUG] Patch folder selection cancelled, keeping dialog open")
                # If set_patch_folder returns False (cancelled), do nothing - keep dialog open
        else:
            print("[DEBUG ERROR] patch_manager is None!")
            QMessageBox.information(
                self,
                "Change Patch Folder",
                "Patch folder manager not available."
            )

    def populate_levels(self, filter_text="", filter_type="All Levels"):
        """Populate the grid with level buttons"""
        # Clear existing buttons
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Get default thumbnail based on game mode
        default_thumb = "avatar_default_level.png" if self.game_mode != "farcry2" else "fc2_default_level.png"

        # Filter levels
        filtered_levels = []
        for name, level_info in self.levels_data.items():
            has_world = bool(level_info.worlds_path)
            has_level = bool(level_info.levels_path)

            # Apply text filter
            if filter_text:
                filter_lower = filter_text.lower()
                name_match = filter_lower in name.lower()
                display_match = level_info.display_name and filter_lower in level_info.display_name.lower()
                if not (name_match or display_match):
                    continue

            # Apply type filter
            if filter_type == "Complete Levels" and not (has_world and has_level):
                continue
            elif filter_type == "World Only" and not has_world:
                continue
            elif filter_type == "Has Terrain" and not level_info.has_terrain:
                continue
            elif filter_type == "Has Objects" and not level_info.has_objects:
                continue

            # Determine annotation for display
            annotation = []
            if has_world and not has_level:
                annotation.append("World Only")
            elif has_level and not has_world:
                annotation.append("Level Only")
            elif has_world and has_level:
                annotation.append("World + Level")

            filtered_levels.append((name, level_info, annotation))

        # Sort levels alphabetically by display name
        filtered_levels.sort(key=lambda x: x[1].display_name or x[0])

        # Update count label
        total_levels = len(self.levels_data)
        filtered_count = len(filtered_levels)
        if filtered_count == total_levels:
            self.count_label.setText(f"Showing {total_levels} level{'s' if total_levels != 1 else ''}")
        else:
            self.count_label.setText(f"Showing {filtered_count} of {total_levels} level{'s' if total_levels != 1 else ''}")

        # Add buttons to grid
        row, col = 0, 0
        max_cols = 4
        
        if not filtered_levels:
            # Show "no results" message
            no_results = QLabel("No levels match your search criteria")
            no_results.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_results.setStyleSheet("""
                QLabel {
                    color: #888;
                    font-size: 14px;
                    padding: 40px;
                }
            """)
            self.grid_layout.addWidget(no_results, 0, 0, 1, max_cols)
        else:
            print("[DEBUG] Setting up level buttons")
            self.level_buttons = {}
            for name, level_info, annotation in filtered_levels:
                button = LevelButton(level_info, default_thumb, annotation)
                self.level_buttons[name] = button
                button.level_selected.connect(self.on_level_selected)
                self.grid_layout.addWidget(button, row, col)
                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1

            # Add empty space filler at the end
            spacer = QWidget()
            spacer.setSizePolicy(
                spacer.sizePolicy().horizontalPolicy(),
                spacer.sizePolicy().verticalPolicy()
            )
            self.grid_layout.addWidget(spacer, row + 1, 0, 1, max_cols)

    def apply_filter(self):
        """Apply current filter and search criteria"""
        filter_text = self.search_input.text()
        filter_type = self.filter_combo.currentText()
        self.populate_levels(filter_text, filter_type)

    def closeEvent(self, event):
        """Stop all LevelButton rotation timers before closing."""
        if hasattr(self, 'level_buttons'):
            for btn in self.level_buttons.values():
                btn.disable_rotate()
        super().closeEvent(event)

    def on_level_selected(self, level_info: LevelInfo):
        """Handle level selection"""
        print(f"[DEBUG] Level selected: {level_info.name}")
        _wp = getattr(level_info, 'worlds_path', None)
        _lp = getattr(level_info, 'levels_path', None)
        level_dict = {
            'name': level_info.name,
            'worlds_path': _wp,
            'levels_path': _lp,
            'levels_paths': getattr(level_info, 'levels_paths', None) or ([_lp] if _lp else []),
            'base_folder': os.path.dirname(_wp or _lp)
        }
        self.selected_level = level_dict
        self.level_selected.emit(level_dict)
        print(f"[DEBUG] LevelSelectorDialog accepted with: {self.selected_level}")
        print(f"[DEBUG] stopping all rotations")
        for name, btn in self.level_buttons.items():
            print(f"[DEBUG] disabling rotation for buton {name}")
            btn.disable_rotate()
        self.accept()

    def on_change_patch_folder(self):
        """Handle patch folder change request"""
        _spf_log("on_change_patch_folder called")
        print("[DEBUG] Change patch folder requested")
        if self.patch_manager:
            print("[DEBUG] Calling set_patch_folder...")
            # Call set_patch_folder directly - this opens the folder browser
            if self.patch_manager.set_patch_folder():
                # Folder changed successfully, close and signal to rescan.
                # Stop rotation timers first — accept() skips closeEvent.
                _spf_log(f"set_patch_folder returned True → new folder: {self.patch_manager.patch_folder}")
                print("[DEBUG] Patch folder changed successfully, stopping timers and closing dialog")
                if hasattr(self, 'level_buttons'):
                    for btn in self.level_buttons.values():
                        btn.disable_rotate()
                _spf_log("timers/animations stopped, emitting patch_folder_change_requested")
                self.patch_folder_change_requested.emit()
                _spf_log("signal emitted, calling self.accept()")
                self.accept()  # Close with success (exactly once)
                _spf_log("self.accept() returned")
            else:
                _spf_log("set_patch_folder returned False (cancelled)")
                print("[DEBUG] Patch folder selection cancelled, keeping dialog open")
                # If set_patch_folder returns False (cancelled), do nothing - keep dialog open
        else:
            print("[DEBUG ERROR] patch_manager is None!")
            QMessageBox.information(
                self,
                "Change Patch Folder",
                "Patch folder manager not available."
            )

class PatchFolderManager:
    """Main manager class for patch folder operations"""
    
    def __init__(self, parent=None, game_mode: str = "avatar"):
        self.parent = parent
        self.game_mode = game_mode
        self.patch_folder: Optional[str] = None
        self.levels_data: dict = {}
        self.scanner_thread: Optional[PatchFolderScanner] = None

        # Load saved patch folder configuration for this game
        self.load_config()
    
    def load_config(self):
        """Load saved patch folder configuration for the current game mode."""
        if not os.path.exists(PATCH_CONFIG_FILE):
            return
        try:
            with open(PATCH_CONFIG_FILE, 'r') as f:
                config = json.load(f)

            # Per-game key e.g. "avatar_patch_folder" / "fc2_patch_folder"
            key = f"{self.game_mode}_patch_folder"
            folder = config.get(key)

            # Migrate old single-key format on first load
            if folder is None:
                folder = config.get('patch_folder')
                if folder:
                    print(f"Migrating legacy 'patch_folder' key to '{key}'")
                    self.patch_folder = folder
                    self.save_config()   # rewrite with per-game key
                    return

            if folder and os.path.exists(folder):
                self.patch_folder = folder
                print(f"Loaded patch folder from config [{self.game_mode}]: {self.patch_folder}")
            else:
                print(f"Saved patch folder not found [{self.game_mode}]: {folder}")
        except Exception as e:
            print(f"Error loading patch config: {e}")
    
    def save_config(self):
        """Save patch folder for the current game mode, preserving other games' entries."""
        try:
            # Load existing config so we don't overwrite the other game's entry
            config = {}
            if os.path.exists(PATCH_CONFIG_FILE):
                with open(PATCH_CONFIG_FILE, 'r') as f:
                    config = json.load(f)

            # Remove legacy key if present (one-time migration)
            config.pop('patch_folder', None)

            key = f"{self.game_mode}_patch_folder"
            config[key] = self.patch_folder

            with open(PATCH_CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
            print(f"Saved patch folder to config [{self.game_mode}]: {self.patch_folder}")
        except Exception as e:
            print(f"Error saving patch config: {e}")
    
    def set_patch_folder(self):
        """Let user select and set the patch folder"""
        folder = QFileDialog.getExistingDirectory(
            self.parent,
            "Select Patch Folder (containing 'worlds' and 'levels' subdirectories)",
            self.patch_folder or ""
        )
        
        if not folder:
            return False
        
        # Validate folder structure
        worlds_dir = os.path.join(folder, "worlds")
        levels_dir = os.path.join(folder, "levels")
        
        if not os.path.exists(worlds_dir) and not os.path.exists(levels_dir):
            reply = QMessageBox.warning(
                self.parent,
                "Invalid Patch Folder",
                f"The selected folder doesn't contain 'worlds' or 'levels' subdirectories.\n\n"
                f"Selected: {folder}\n\n"
                "Please select a valid patch folder or create the required structure.",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return False
        
        self.patch_folder = folder
        self.save_config()
        # Do NOT call scan_patch_folder() here — select_level() will scan
        # after this returns, and calling both creates two progress dialogs.
        return True
    
    def scan_patch_folder(self, show_progress=True):
        """
        Scan the patch folder for available levels with EnhancedProgressDialog.
        Populates self.levels_data and emits signals for completion or error.
        """
        if not self.patch_folder or not os.path.exists(self.patch_folder):
            QMessageBox.warning(
                self.parent,
                "Patch Folder Not Found",
                f"The configured patch folder is invalid or missing:\n{self.patch_folder}"
            )
            self.patch_folder = None
            self.levels_data = {}
            return False

        # Stop existing thread if running
        if self.scanner_thread and self.scanner_thread.isRunning():
            self.scanner_thread.stop()
            self.scanner_thread.wait(2000)

        # Get game mode from parent if available
        game_mode = "avatar"
        if self.parent and hasattr(self.parent, 'game_mode'):
            game_mode = self.parent.game_mode

        # Create EnhancedProgressDialog instead of QProgressDialog
        from simplified_map_editor import EnhancedProgressDialog  # Import at the top of file
        
        progress_dialog = None
        if show_progress:
            progress_dialog = EnhancedProgressDialog(
                "Scanning Patch Folder", 
                self.parent, 
                game_mode=game_mode
            )
            progress_dialog.append_log(f"Scanning folder: {os.path.basename(self.patch_folder)}")
            progress_dialog.show()
            QApplication.processEvents()

        # Get file_converter from parent if available
        file_converter = None
        if self.parent and hasattr(self.parent, 'file_converter'):
            file_converter = self.parent.file_converter

        self.scanner_thread = PatchFolderScanner(self.patch_folder, file_converter, game_mode)

        def on_complete(levels_data):
            self.levels_data = levels_data or {}
            if progress_dialog:
                progress_dialog.set_progress(100)
                progress_dialog.mark_complete()
                progress_dialog.stop_icon()
                progress_dialog.close()
            print(f"Scan complete: Found {len(self.levels_data)} levels")
            if self.parent:
                QMessageBox.information(
                    self.parent,
                    "Scan Complete",
                    f"Found {len(self.levels_data)} levels in patch folder."
                )

        def on_error(msg):
            self.levels_data = {}
            if progress_dialog:
                progress_dialog.append_log(f"ERROR: {msg}")
                progress_dialog.mark_complete()
                progress_dialog.stop_icon()
                progress_dialog.close()
            print(f"Scan error: {msg}")
            if self.parent:
                QMessageBox.critical(self.parent, "Scan Error", msg)

        def on_progress(percent, message):
            if progress_dialog:
                progress_dialog.set_progress(percent)
                progress_dialog.set_status(message)
                progress_dialog.append_log(message)
                QApplication.processEvents()

        self.scanner_thread.scan_complete.connect(on_complete)
        self.scanner_thread.error_occurred.connect(on_error)
        self.scanner_thread.progress_updated.connect(on_progress)
        if progress_dialog:
            self.scanner_thread.log_message.connect(progress_dialog.append_log)

        if progress_dialog:
            progress_dialog.cancelled.connect(self.scanner_thread.stop)

        self.scanner_thread.finished.connect(self.on_scan_thread_finished)
        self.scanner_thread.start()
        return True
    
    def on_scan_thread_finished(self):
        """Clean up when scan thread finishes"""
        if self.scanner_thread:
            self.scanner_thread.deleteLater()
            self.scanner_thread = None
        print("Scanner thread finished")
    
    def on_scan_complete(self, levels_data: dict, progress_dialog=None):
        """Handle scan completion"""
        self.levels_data = levels_data
        if progress_dialog:
            progress_dialog.close()
        print(f"Scan complete: Found {len(levels_data)} levels")
        if self.parent:
            QMessageBox.information(
                self.parent,
                "Scan Complete",
                f"Found {len(levels_data)} levels in patch folder."
            )
    
    def on_scan_error(self, error_msg: str, progress_dialog=None):
        """Handle scan error"""
        if progress_dialog:
            progress_dialog.close()
        print(f"Scan error: {error_msg}")
        if self.parent:
            QMessageBox.critical(self.parent, "Scan Error", error_msg)
    
    def match_worlds_to_levels(self):
        """
        Match world folders to their corresponding level folders.
        If a world has no matching level, create a 'world-only' entry.
        """
        self.levels_data = {}  # Reset levels data

        for world_name, world_path in self.worlds.items():
            matched_levels = []

            # Try to find levels that match this world
            for level_name, level_path in self.levels.items():
                if level_name.startswith(world_name):
                    matched_levels.append(level_name)

            # If no levels, create a 'world-only' entry
            if not matched_levels:
                matched_levels.append(f"{world_name}_world_only")

            # Save in levels_data
            self.levels_data[world_name] = matched_levels
    
    def get_level_info(self, level_name: str) -> Optional[dict]:
        """Get info for a specific level"""
        if level_name in self.levels_data:
            level_info = self.levels_data[level_name]
            return dict(
                name=level_info.name,
                worlds_path=level_info.worlds_path,
                levels_path=level_info.levels_path,
                levels_paths=level_info.levels_paths or ([level_info.levels_path] if level_info.levels_path else []),
                base_folder=os.path.dirname(level_info.worlds_path)
            )
        return None
    
    def get_patch_folder(self) -> Optional[str]:
        return self.patch_folder
    
    def is_configured(self) -> bool:
        return self.patch_folder is not None and os.path.exists(self.patch_folder)
    
    def cleanup(self):
        """Clean up resources"""
        if self.scanner_thread and self.scanner_thread.isRunning():
            self.scanner_thread.stop()
            if not self.scanner_thread.wait(2000):
                print("Warning: scanner thread did not stop, terminating...")
                self.scanner_thread.terminate()
                self.scanner_thread.wait(1000)
        if self.scanner_thread:
            self.scanner_thread.deleteLater()
            self.scanner_thread = None
        print("PatchFolderManager cleanup complete")

def set_resource_folder(main_window):
    """
    Let user select their unpacked game data folder for 3D models.
    This should be the root Data_Win32 folder containing graphics/, worlds/, etc.
    Saved per-game to patch_config.json as avatar_resource_folder / farcry2_resource_folder.
    """
    current_folder = getattr(main_window, 'resource_folder', None)

    folder = QFileDialog.getExistingDirectory(
        main_window,
        "Select Unpacked Game Data Folder (e.g., Data_Win32 containing graphics/)",
        current_folder or ""
    )

    if not folder:
        return False

    # Validate folder structure
    graphics_dir = os.path.join(folder, "graphics")

    if not os.path.exists(graphics_dir):
        reply = QMessageBox.warning(
            main_window,
            "Invalid Resource Folder",
            f"The selected folder doesn't contain a 'graphics' subdirectory.\n\n"
            f"Selected: {folder}\n\n"
            "Please select your unpacked game data folder (e.g., Data_Win32).",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return False

    main_window.resource_folder = folder

    # Save to patch_config.json under a game-specific key
    try:
        game_mode = getattr(main_window, 'game_mode', 'avatar')
        key = f"{game_mode}_resource_folder"

        config = {}
        if os.path.exists(PATCH_CONFIG_FILE):
            with open(PATCH_CONFIG_FILE, 'r') as f:
                config = json.load(f)

        config[key] = folder

        with open(PATCH_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)

        print(f"Saved resource folder to config [{game_mode}]: {folder}")
    except Exception as e:
        print(f"Error saving resource folder config: {e}")

    QMessageBox.information(
        main_window,
        "Resource Folder Set",
        f"Resource folder has been set to:\n{folder}\n\n"
        "3D models will now be loaded from this folder when you load a level."
    )

    return True


def load_resource_folder_config(main_window):
    """
    Load the game-specific resource folder from patch_config.json on startup.
    Key format: avatar_resource_folder / farcry2_resource_folder.
    Falls back to the legacy editor_config.json 'resource_folder' key and migrates
    it into patch_config.json on first run so no data is lost.
    """
    try:
        game_mode = getattr(main_window, 'game_mode', 'avatar')
        key = f"{game_mode}_resource_folder"
        resource_folder = None

        config = {}
        if os.path.exists(PATCH_CONFIG_FILE):
            with open(PATCH_CONFIG_FILE, 'r') as f:
                config = json.load(f)
            resource_folder = config.get(key)

        # One-time migration: pull old value from editor_config.json if not yet in patch_config
        if resource_folder is None:
            try:
                with open("editor_config.json", 'r') as f:
                    old_config = json.load(f)
                legacy = old_config.get('resource_folder')
                if legacy:
                    print(f"Migrating resource_folder from editor_config.json [{game_mode}]")
                    resource_folder = legacy
                    config[key] = legacy
                    with open(PATCH_CONFIG_FILE, 'w') as f:
                        json.dump(config, f, indent=2)
            except Exception:
                pass

        if resource_folder and os.path.exists(resource_folder):
            main_window.resource_folder = resource_folder
            print(f"Loaded resource folder from config [{game_mode}]: {resource_folder}")
        else:
            if resource_folder:
                print(f"Saved resource folder not found [{game_mode}]: {resource_folder}")
            main_window.resource_folder = None
    except Exception as e:
        print(f"Error loading resource folder config: {e}")
        main_window.resource_folder = None

def integrate_patch_manager(main_window):
    """
    Updated integration with resource folder support.
    """
    print("\n[DEBUG] integrate_patch_manager() CALLED")

    # Create PatchFolderManager instance
    print("[DEBUG] Creating PatchFolderManager instance...")
    main_window.patch_manager = PatchFolderManager(main_window, game_mode=main_window.game_mode)
    patch_manager = main_window.patch_manager
    
    # Initialize resource_folder to None (will be set by user or loaded from config)
    if not hasattr(main_window, 'resource_folder'):
        main_window.resource_folder = None
    
    # Load resource folder from config
    load_resource_folder_config(main_window)
    
    # *** SET WORLDS_FOLDER FROM PATCH_MANAGER ***
    if patch_manager.is_configured():
        worlds_dir = os.path.join(patch_manager.patch_folder, "worlds")
        if os.path.exists(worlds_dir):
            main_window.worlds_folder = worlds_dir
            print(f"✅ Set worlds_folder from patch config: {main_window.worlds_folder}")
        else:
            # Try alternative naming (capital W)
            worlds_dir_alt = os.path.join(patch_manager.patch_folder, "Worlds")
            if os.path.exists(worlds_dir_alt):
                main_window.worlds_folder = worlds_dir_alt
                print(f"✅ Set worlds_folder (alt case): {main_window.worlds_folder}")
            else:
                print(f"⚠️ Could not find worlds subdirectory in patch folder: {patch_manager.patch_folder}")
    else:
        print("⚠️ Patch folder not configured, worlds_folder not set")

    # -------------------------------------------------------------------------
    # EXISTING select_level METHOD - NO CHANGES NEEDED
    # -------------------------------------------------------------------------
    _log_to_crash_file = _spf_log  # reuse module-level logger inside this closure

    def new_select_level():
        # PREVENT RE-ENTRY - Critical to avoid infinite loops
        if hasattr(main_window, '_selecting_level') and main_window._selecting_level:
            print("⚠️ Already selecting level, ignoring duplicate call")
            _log_to_crash_file("select_level re-entry blocked")
            return

        main_window._selecting_level = True

        try:
            _log_to_crash_file("=== select_level START ===")
            print("\n=== STARTING LEVEL SELECTION (ENHANCED) ===")

            # PARTIAL RESET - Don't trigger game selector
            if hasattr(main_window, 'reset_editor_state_no_game_change'):
                main_window.reset_editor_state_no_game_change()
            else:
                # Fallback: manual partial reset
                print("⚠️ Using fallback partial reset")
                main_window.entities = []
                main_window.objects = []
                main_window.selected_entity = None
                if hasattr(main_window, 'canvas'):
                    main_window.canvas.entities = []
                    main_window.canvas.selected = []
                    main_window.canvas.selected_entity = None

            if not patch_manager.is_configured():
                print("[DEBUG] Patch folder not configured, prompting user...")
                reply = QMessageBox.question(
                    main_window,
                    "Patch Folder Not Set",
                    "No patch folder is configured. Would you like to set one now?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    if not patch_manager.set_patch_folder():
                        print("[DEBUG] User cancelled folder selection")
                        return
                    else:
                        # Update worlds_folder after setting patch folder
                        update_worlds_folder(patch_manager, main_window)
                else:
                    print("[DEBUG] User declined to set patch folder")
                    return

            # Scan patch folder if levels_data is empty
            if not patch_manager.levels_data:
                _log_to_crash_file(f"SCAN START: {patch_manager.patch_folder}")
                print("[DEBUG] No levels_data, scanning patch folder...")

                # Stop and fully disconnect any previous scanner thread first
                if patch_manager.scanner_thread is not None:
                    old_thread = patch_manager.scanner_thread
                    if old_thread.isRunning():
                        print("[DEBUG] Stopping previous scanner thread...")
                        old_thread.stop()
                        old_thread.wait(3000)
                    try:
                        old_thread.scan_complete.disconnect()
                        old_thread.error_occurred.disconnect()
                        old_thread.progress_updated.disconnect()
                        old_thread.log_message.disconnect()
                    except Exception:
                        pass
                    patch_manager.scanner_thread = None

                # Import EnhancedProgressDialog
                _log_to_crash_file("importing EnhancedProgressDialog")
                from simplified_map_editor import EnhancedProgressDialog

                # Create enhanced progress dialog
                _log_to_crash_file("creating EnhancedProgressDialog")
                progress_dialog = EnhancedProgressDialog(
                    "Scanning Patch Folder",
                    main_window,
                    game_mode=main_window.game_mode
                )
                progress_dialog.append_log(f"Scanning: {os.path.basename(patch_manager.patch_folder)}")
                progress_dialog.show()
                QApplication.processEvents()

                # Get file_converter from main_window
                file_converter = main_window.file_converter if hasattr(main_window, 'file_converter') else None

                _log_to_crash_file("creating PatchFolderScanner thread")
                scanner_thread = PatchFolderScanner(patch_manager.patch_folder, file_converter, main_window.game_mode)
                patch_manager.scanner_thread = scanner_thread

                scan_completed = [False]

                def on_complete(levels_data):
                    if not progress_dialog or progress_dialog.was_cancelled:
                        return
                    patch_manager.levels_data = levels_data or {}
                    progress_dialog.set_progress(100)
                    progress_dialog.append_log(f"✓ Scan complete: {len(patch_manager.levels_data)} levels found")
                    progress_dialog.mark_complete()
                    progress_dialog.stop_icon()
                    progress_dialog.close()
                    scan_completed[0] = True
                    _log_to_crash_file(f"SCAN COMPLETE: {len(patch_manager.levels_data)} levels")
                    print(f"[DEBUG] Scan complete: Found {len(patch_manager.levels_data)} levels")

                def on_error(msg):
                    if not progress_dialog:
                        return
                    patch_manager.levels_data = {}
                    progress_dialog.append_log(f"✗ Error: {msg}")
                    progress_dialog.mark_complete()
                    progress_dialog.stop_icon()
                    progress_dialog.close()
                    scan_completed[0] = True
                    _log_to_crash_file(f"SCAN ERROR: {msg}")
                    print(f"[DEBUG] Scan error: {msg}")
                    QMessageBox.critical(main_window, "Scan Error", msg)

                def on_progress(percent, message):
                    if not progress_dialog or progress_dialog.was_cancelled:
                        return
                    progress_dialog.set_progress(percent)
                    progress_dialog.set_status(message)
                    progress_dialog.append_log(message)

                def on_scan_cancelled():
                    patch_manager.levels_data = {}
                    scan_completed[0] = True
                    _log_to_crash_file("SCAN CANCELLED by user")

                scanner_thread.scan_complete.connect(on_complete)
                scanner_thread.error_occurred.connect(on_error)
                scanner_thread.progress_updated.connect(on_progress)
                scanner_thread.log_message.connect(progress_dialog.append_log)
                progress_dialog.cancelled.connect(scanner_thread.stop)
                progress_dialog.cancelled.connect(on_scan_cancelled)
                _log_to_crash_file("scanner thread starting")
                scanner_thread.start()

                # Wait for scan to complete using a small sleep to avoid
                # hammering processEvents which can cause re-entrant issues
                import time
                while not scan_completed[0]:
                    QApplication.processEvents()
                    time.sleep(0.02)

                _log_to_crash_file("scan wait loop done")
                print("[DEBUG] Scan finished.")
            else:
                _log_to_crash_file(f"SCAN SKIPPED (levels_data already has {len(patch_manager.levels_data)} entries)")

            # Check again after scan
            if not patch_manager.levels_data:
                print("[DEBUG ERROR] No levels found after scan")
                QMessageBox.warning(
                    main_window,
                    "No Levels Found",
                    "Patch scan returned 0 usable levels."
                )
                return

            # Now show the level selector dialog with the scanned data
            _log_to_crash_file(f"creating LevelSelectorDialog with {len(patch_manager.levels_data)} levels")
            print("[DEBUG] Showing level selector dialog...")
            print(f"[DEBUG] Creating dialog with {len(patch_manager.levels_data)} levels")

            dialog = LevelSelectorDialog(
                patch_manager.levels_data,
                main_window,
                main_window.game_mode,
                patch_manager
            )
            _log_to_crash_file("LevelSelectorDialog created OK")
            print(f"[DEBUG] Dialog created with patch_manager: {dialog.patch_manager is not None}")

            def on_level_selected(lvl):
                print(f"[DEBUG] Level selected signal received: {lvl}")

            # Snapshot folder at dialog-open time so on_patch_folder_change can
            # tell whether the user actually changed it or just re-selected it.
            folder_at_open = patch_manager.patch_folder

            # Flag set inside the modal loop so we can act AFTER exec() returns
            patch_folder_was_changed = [False]

            def on_patch_folder_change():
                """
                Signal handler — called while dialog.exec() is still on the stack.
                We must NOT open a new dialog or call select_level() here directly
                because that would nest a second modal event loop inside the first,
                which crashes Qt silently.  Instead we just mark the flag; the
                LevelSelectorDialog.on_change_patch_folder caller will call
                self.accept() exactly once after this signal handler returns.
                """
                folder_changed = (patch_manager.patch_folder != folder_at_open)
                _log_to_crash_file(f"on_patch_folder_change: folder_changed={folder_changed} old={folder_at_open} new={patch_manager.patch_folder}")
                print(f"[DEBUG] Patch folder change signal received. Actually changed: {folder_changed}")

                # Stop any running scanner thread before we do anything else
                if patch_manager.scanner_thread and patch_manager.scanner_thread.isRunning():
                    print("[DEBUG] Stopping scanner thread before patch folder change")
                    patch_manager.scanner_thread.stop()
                    patch_manager.scanner_thread.wait(3000)

                update_worlds_folder(patch_manager, main_window)

                # Only force a rescan if the folder actually changed.
                # For the same folder, keep existing levels_data so the second
                # select_level call skips the scan and just reopens the dialog.
                if folder_changed:
                    patch_manager.levels_data = {}

                # Mark that we need to reopen AFTER exec() returns.
                # Do NOT call dialog.accept() here — the caller already does so,
                # and a double-accept corrupts Qt's nested event loop in frozen exes.
                patch_folder_was_changed[0] = True

            dialog.level_selected.connect(on_level_selected)
            dialog.patch_folder_change_requested.connect(on_patch_folder_change)

            _log_to_crash_file("entering dialog.exec()")
            result = dialog.exec()
            _log_to_crash_file(f"dialog.exec() returned: {result}")
            print(f"[DEBUG] Level selector exec result: {result}")

            # If the user changed the patch folder (or re-selected it), reopen
            # the selector after exec() has fully unwound.
            if patch_folder_was_changed[0]:
                print("[DEBUG] Patch folder dialog reopening after exec() returned")
                main_window.status_bar.showMessage("Reopening level selector...", 2000)
                # Release the lock before re-entering select_level
                main_window._selecting_level = False
                QTimer.singleShot(100, lambda: main_window.select_level())
                return

            if result == QDialog.DialogCode.Accepted and hasattr(dialog, 'selected_level') and dialog.selected_level:
                level_dict = dialog.selected_level
                print("[DEBUG] level_dict returned:")
                for k, v in level_dict.items():
                    print(f"    {k} = {v}")

                wp = level_dict.get("worlds_path")
                lp = level_dict.get("levels_path")

                # Validate paths - be more lenient
                worlds_valid = main_window.validate_worlds_folder(wp) if wp else True
                levels_valid = main_window.validate_levels_folder(lp) if lp else True

                print(f"[DEBUG] Validation results: worlds_valid={worlds_valid}, levels_valid={levels_valid}")

                # Only proceed if we have at least one valid path
                if (wp and worlds_valid) or (lp and levels_valid):
                    _log_to_crash_file(f"Loading level: {level_dict.get('name')}")
                    print("[DEBUG] Calling load_complete_level() with selected level")
                    main_window.load_complete_level(level_dict)
                else:
                    print("[DEBUG ERROR] Neither worlds nor levels paths are valid")
                    QMessageBox.warning(
                        main_window,
                        "Invalid Level",
                        "The selected level has no valid world or level data."
                    )
            else:
                print("[DEBUG] User cancelled level selection")
                _log_to_crash_file("select_level: user cancelled or no level selected")

        except Exception as _exc:
            import traceback as _tb
            _msg = _tb.format_exc()
            _log_to_crash_file(f"EXCEPTION in select_level:\n{_msg}")
            try:
                from PyQt6.QtWidgets import QMessageBox as _QMB
                _QMB.critical(
                    main_window,
                    "Level Selector Error",
                    f"An error occurred in the level selector.\n\n"
                    f"Details saved to crash_log.txt\n\n{type(_exc).__name__}: {_exc}"
                )
            except Exception:
                pass
            raise  # re-raise so sys.excepthook also fires

        finally:
            # Always release the lock
            main_window._selecting_level = False
            _log_to_crash_file("=== select_level END ===")

    # REPLACE the original select_level method
    main_window.select_level = new_select_level
    print("[DEBUG] ✓ Patched select_level method (replaced original)")
    
    # Also update the action if it exists
    if hasattr(main_window, 'select_level_action'):
        try:
            main_window.select_level_action.triggered.disconnect()
        except:
            pass
        main_window.select_level_action.triggered.connect(main_window.select_level)
        print("[DEBUG] ✓ Reconnected select_level_action")


def update_worlds_folder(patch_manager, main_window):
    """Helper function to update worlds_folder when patch folder changes"""
    if patch_manager.is_configured():
        worlds_dir = os.path.join(patch_manager.patch_folder, "worlds")
        if os.path.exists(worlds_dir):
            main_window.worlds_folder = worlds_dir
            print(f"✅ Updated worlds_folder: {main_window.worlds_folder}")
        else:
            # Try alternative naming (capital W)
            worlds_dir_alt = os.path.join(patch_manager.patch_folder, "Worlds")
            if os.path.exists(worlds_dir_alt):
                main_window.worlds_folder = worlds_dir_alt
                print(f"✅ Updated worlds_folder (alt case): {main_window.worlds_folder}")
            else:
                print(f"⚠️ Could not find worlds subdirectory in patch folder: {patch_manager.patch_folder}")
                main_window.worlds_folder = None
    else:
        print("⚠️ Patch folder not configured, worlds_folder cleared")
        main_window.worlds_folder = None


def on_patch_folder_changed(patch_manager, main_window):
    """Handler for when user manually sets patch folder from menu"""
    if patch_manager.set_patch_folder():
        update_worlds_folder(patch_manager, main_window)
        QMessageBox.information(
            main_window,
            "Patch Folder Updated",
            f"Patch folder has been set to:\n{patch_manager.patch_folder}\n\n"
            f"Worlds folder: {main_window.worlds_folder if hasattr(main_window, 'worlds_folder') else 'Not found'}"
        )