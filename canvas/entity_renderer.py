"""Entity rendering for 2D mode - 2D ONLY VERSION"""

import math
from time import time
from PyQt6.QtCore import Qt, QPoint, QPointF, QRectF
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QVector3D, QPolygon, QPolygonF, QPixmap
from .opengl_utils import OpenGLUtils
import os

class EntityRenderer:
    """Handles rendering of entities in 2D mode - 2D ONLY"""
    
    def __init__(self):
        # Enhanced entity type colors - matching simplified_map_editor.py
        self.type_colors = {
            # Vehicles
            "Vehicle": QColor(52, 152, 255),      # Blue - Vehicles
            
            # Characters and NPCs  
            "NPC": QColor(46, 255, 113),          # Green - NPCs/Characters
            "Character": QColor(46, 255, 113),    # Green - NPCs/Characters
            
            # Weapons and combat
            "Weapon": QColor(255, 76, 60),        # Red - Weapons/Explosives
            "Explosive": QColor(255, 76, 60),     # Red - Weapons/Explosives
            
            # Mission and gameplay
            "Spawn": QColor(255, 156, 18),        # Orange - Spawn Locations
            "Mission": QColor(185, 89, 255),      # Purple - Mission Objects
            "Objective": QColor(185, 89, 255),    # Purple - Mission Objects
            "Checkpoint": QColor(255, 156, 18),   # Orange - Spawn Locations
            
            # Interactive objects
            "Trigger": QColor(255, 230, 15),      # Yellow - Triggers/Zones
            "Zone": QColor(255, 230, 15),         # Yellow - Triggers/Zones
            "Area": QColor(255, 230, 15),         # Yellow - Triggers/Zones
            "Region": QColor(255, 230, 15),       # Yellow - Triggers/Zones
            
            # Environment and props
            "Prop": QColor(170, 180, 190),        # Gray - Props/Static Objects
            "StaticObject": QColor(170, 180, 190), # Gray - Props/Static Objects
            "Building": QColor(170, 180, 190),    # Gray - Props/Static Objects
            "Structure": QColor(170, 180, 190),   # Gray - Props/Static Objects
            "Container": QColor(170, 180, 190),   # Gray - Props/Static Objects
            
            # Lighting and effects
            "Light": QColor(255, 255, 160),       # Light Yellow - Lights
            "Lamp": QColor(255, 255, 160),        # Light Yellow - Lights
            "Spotlight": QColor(255, 255, 160),   # Light Yellow - Lights
            "Effect": QColor(0, 255, 200),        # Teal - Effects/Particles
            "Particle": QColor(0, 255, 200),      # Teal - Effects/Particles
            "VFX": QColor(0, 255, 200),           # Teal - Effects/Particles
            
            # Navigation and waypoints
            "Waypoint": QColor(185, 89, 255),     # Purple - Mission Objects
            "Path": QColor(185, 89, 255),         # Purple - Mission Objects
            "Node": QColor(185, 89, 255),         # Purple - Mission Objects
            "Navpoint": QColor(185, 89, 255),     # Purple - Mission Objects
            
            # Audio
            "Sound": QColor(0, 255, 200),         # Teal - Effects/Particles
            "Audio": QColor(0, 255, 200),         # Teal - Effects/Particles
            "Music": QColor(0, 255, 200),         # Teal - Effects/Particles
            "Ambience": QColor(0, 255, 200),      # Teal - Effects/Particles
            
            # Camera and cinematics
            "Camera": QColor(185, 89, 255),       # Purple - Mission Objects
            "View": QColor(185, 89, 255),         # Purple - Mission Objects
            "Cinematic": QColor(185, 89, 255),    # Purple - Mission Objects
            
            # Special data sources
            "WorldSectors": QColor(255, 100, 100), # Red - WorldSectors Objects
            "Landmarks": QColor(255, 100, 100),    # Red - WorldSectors Objects
            
            # Nature and terrain
            "Tree": QColor(170, 180, 190),        # Gray - Props/Static Objects
            "Plant": QColor(170, 180, 190),       # Gray - Props/Static Objects
            "Rock": QColor(170, 180, 190),        # Gray - Props/Static Objects
            "Water": QColor(170, 180, 190),       # Gray - Props/Static Objects
            
            # Animals / Pandoran wildlife
            "Animal": QColor(255, 200, 100),       # Amber - Pandoran creatures

            # Default
            "Unknown": QColor(130, 130, 130)      # Dark Gray - Unknown Type
        }

        # Prefix-based classification from the first dot-segment of hidName.
        # Keys are lowercase; values are entity-type strings from type_colors.
        self._HIDNAME_PREFIX_TYPES = {
            "vehicle":                          "Vehicle",
            "enemy_archetypes":                 "NPC",
            "animals":                          "Animal",
            "weapons":                          "Weapon",
            "oa_explosives":                    "Weapon",
            "turrets":                          "Weapon",
            "props":                            "Prop",
            "object_archetypes":                "Prop",
            "breakable":                        "Prop",
            "avatar_vegetation_gatheringobject":"Prop",
            "avatar_vegetation_rf":             "Prop",
            "avatar_vegetation_fm":             "Prop",
            "plants":                           "Prop",
            "tables":                           "Prop",
            "domino":                           "Prop",
            "curves":                           "Prop",
            "weaponproperties":                 "Prop",
            "player":                           "NPC",
            "multiplayer":                      "NPC",
            "ghostpatrols":                     "NPC",
            "interactive":                      "Trigger",
            "stp_archetypes":                   "Spawn",
            "avatar_scriptedevents":            "Mission",
            "cameras":                          "Mission",
            "metagame":                         "Mission",
            "stimemitters":                     "Effect",
            "postfxs":                          "Effect",
            "beautifiers":                      "Effect",
            "realtree":                         "Prop",
        }
        
        # Legacy fallback patterns — checked only when hidName prefix is unrecognized.
        # ORDERING MATTERS: Animal before NPC so Pandoran wildlife isn't misclassified.
        self.type_patterns = {
            # Vehicles — check before NPC to catch "samson", "scorpion", etc. first
            "Vehicle": ["vehicle", "car", "truck", "boat", "ship", "plane", "buggy", "atv",
                        "quad", "dove", "ampsuit", "samson", "scorpion", "valkyrie", "dragon",
                        "helicopter"],

            # Pandoran wildlife — check before NPC so "viperwolf", "banshee" etc. are Animal,
            # not accidentally caught by "avatar" or "navi" in NPC patterns.
            "Animal": ["viperwolf", "direhorse", "hammerhead", "hexapede", "thanator",
                       "leonopteryx", "stingbat", "sturmbeest", "hellfirewasp", "banshee"],

            # Characters and NPCs
            "NPC": ["npc", "character", "ai_", "enemy", "friend", "ally", "neutral",
                    "avatar", "navi", "marine", "soldier", "civilian"],
            "Character": ["char_", "avatar_", "npc_"],

            # Weapons and combat
            "Weapon": ["weapon", "gun", "rifle", "pistol", "sword", "bow", "arrow", "spear",
                       "shotgun", "flamethrower", "bomb", "explosive", "grenade", "missile",
                       "rocket"],
            "Explosive": ["mine", "tnt"],

            # Mission and gameplay
            "Spawn": ["spawn", "start", "respawn", "SpawnPoint_"],
            "Mission": ["mission", "objective", "goal", "target"],
            "Objective": ["objective", "goal", "target"],
            "Checkpoint": ["checkpoint", "savepoint", "check_"],

            # Interactive objects
            "Trigger": ["trigger"],
            "Zone": ["zone"],
            "Area": ["area"],
            "Region": ["region"],

            # Environment and props
            "Prop": ["prop_", "object_", "static_"],
            "StaticObject": ["so.", "static_object", "staticobject"],
            "Building": ["building", "house", "structure_build"],
            "Structure": ["structure", "construct", "fence", "fence_"],
            "Container": ["container", "box", "crate", "barrel"],
            
            # Lighting and effects
            "Light": ["light"],
            "Lamp": ["lamp"],
            "Spotlight": ["spotlight", "spot_light"],
            "Effect": ["fx_", "effect"],
            "Particle": ["particle", "particles"],
            "VFX": ["vfx_", "visual_effect"],
            
            # Navigation and waypoints
            "Waypoint": ["waypoint", "wp_"],
            "Path": ["path", "route"],
            "Node": ["node", "nav_node"],
            "Navpoint": ["navpoint", "navigation_point"],
            
            # Audio
            "Sound": ["sound"],
            "Audio": ["audio"],
            "Music": ["music"],
            "Ambience": ["ambience", "ambient"],
            
            # Camera and cinematics
            "Camera": ["camera"],
            "View": ["view"],
            "Cinematic": ["cinematic", "cutscene"],
            
            # Nature and terrain
            "Tree": ["tree", "palm", "oak", "pine", "Mossy_Tree"],
            "Plant": ["plant", "bush", "grass", "flower"],
            "Rock": ["rock", "stone", "boulder"],
            "Water": ["water", "river", "lake", "ocean"],
        }
        
        # Vehicle icon mapping - maps icon keys to PNG filenames
        self.HIDNAME_TO_ICON = {
            "vehicle.air.paraglider": "paraglider.png",
            "vehicle.avatar.ampsuit": "ampsuit.png",
            "vehicle.avatar.atv": "atv.png",
            "vehicle.avatar.banshee": "banshee.png",
            "vehicle.avatar.boat_drivable": "boat.png",
            "vehicle.avatar.buggy_drivable": "buggy.png",
            "vehicle.avatar.bulldozer": "bulldozer.png",
            "vehicle.avatar.dove_drivable": "dove.png",
            "vehicle.avatar.dragon": "dragon.png",
            "vehicle.avatar.leonopteryx": "leonopteryx.png",
            "vehicle.avatar.samson_pilotable": "samson.png",
            "vehicle.avatar.scorpion_pilotable": "scorpion.png",
            "vehicle.avatar.valkyrie": "valkyrie.png",
            "vehicle.avatar.wheelloader_drivable": "wheelloader.png",
            "vehicle.corp_lights.buggy_light": "buggy_light.png",
            "vehicle.corp_lights.dove_light": "dove_light.png",
            "vehicle.corp_lights.dragon_light": "dragon_light.png",
            "vehicle.land.bigtruck": "bigtruck.png",
            "vehicle.land.buggy": "buggy.png",
            "vehicle.land.datsun": "datsun.png",
            "vehicle.land.jeepliberty": "jeepliberty.png",
            "vehicle.land.jeepwrangler": "jeepwrangler.png",
            "vehicle.land.rover": "rover.png",
            "vehicle.sea.fishingboat": "fishingboat.png",
            "vehicle.sea.gunboat": "gunboat.png",
            "vehicle.sea.hydroboat": "hydroboat.png",
            "vehicle.sea.pirogue": "pirogue.png",
            "vehicle.sea.swampboat": "swampboat.png",
            "vehicle.test.avatararmedvehicle": "test_vehicle.png",
            "vehicle.test.avatarboat": "test_boat.png",
            "vehicle.test.testboat": "test_boat.png",
            "vehicle.wreck.carburned01_bk": "wreck_car.png",
            "vehicle.wreck.carwrecked01_bk": "wreck_car.png",
        }
        
        # Icon cache - stores loaded QPixmaps
        self.icon_cache = {}
        self.icons_directory = None
        
        # Icon display settings
        self.icon_size = 32  # Default icon size in pixels
        self.show_vehicle_icons = True

        # Vehicle-specific icon sizes (in pixels)
        self.VEHICLE_ICON_SIZES = {
            # Large vehicles
            "vehicle.avatar.samson_pilotable": 80,
            "vehicle.avatar.dragon": 48,
            "vehicle.avatar.valkyrie": 48,
            "vehicle.avatar.leonopteryx": 56,
            "vehicle.avatar.bulldozer": 44,
            "vehicle.avatar.wheelloader_drivable": 44,
            "vehicle.land.bigtruck": 44,
            
            # Medium vehicles
            "vehicle.avatar.scorpion_pilotable": 40,
            "vehicle.avatar.ampsuit": 40,
            "vehicle.avatar.buggy_drivable": 36,
            "vehicle.avatar.dove_drivable": 36,
            "vehicle.avatar.atv": 34,
            "vehicle.land.buggy": 36,
            "vehicle.land.rover": 36,
            "vehicle.land.jeepliberty": 36,
            "vehicle.land.jeepwrangler": 36,
            "vehicle.land.datsun": 34,
            
            # Small vehicles/creatures
            "vehicle.avatar.banshee": 38,
            "vehicle.avatar.boat_drivable": 36,
            "vehicle.sea.fishingboat": 38,
            "vehicle.sea.gunboat": 40,
            "vehicle.sea.hydroboat": 34,
            "vehicle.sea.pirogue": 32,
            "vehicle.sea.swampboat": 36,
            
            # Very small
            "vehicle.air.paraglider": 28,
            
            # Light variants
            "vehicle.corp_lights.buggy_light": 36,
            "vehicle.corp_lights.dove_light": 36,
            "vehicle.corp_lights.dragon_light": 48,
            
            # Wrecks
            "vehicle.wreck.carburned01_bk": 34,
            "vehicle.wreck.carwrecked01_bk": 34,
            
            # Test vehicles
            "vehicle.test.avatararmedvehicle": 40,
            "vehicle.test.avatarboat": 36,
            "vehicle.test.testboat": 36,
        }
                
        # Performance tracking
        self._last_2d_log_time = 0
        self._frame_count = 0

        # Entity cache system
        self.entity_cache = {}
        self.cache_version = 0
        
        # PERFORMANCE OPTIMIZATION: Batch rendering data
        self._batch_circles = []
        self._batch_size = 500
        
        print("EntityRenderer initialized - 2D ONLY")

    def set_icons_directory(self, directory_path):
        """Set the directory containing vehicle icon PNGs"""
        if os.path.isdir(directory_path):
            self.icons_directory = directory_path
            print(f"Vehicle icons directory set: {directory_path}")
            # Don't pre-load - we'll load on-demand for selected entities
            print("Icons will be loaded on-demand when entities are selected")
        else:
            print(f"Invalid icons directory: {directory_path}")

    def _preload_icons(self):
        """DEPRECATED - No longer pre-loading all icons"""
        pass 

    def get_entity_icon(self, entity):
        """Get icon pixmap for an entity, returns None if no icon available"""
        if not self.show_vehicle_icons:
            print("DEBUG: show_vehicle_icons is False")
            return None
        
        if not self.icons_directory:
            print("DEBUG: icons_directory not set")
            return None
        
        # DEBUG: Print entity attributes
        entity_name = getattr(entity, 'name', 'unknown')
        print(f"\n=== ICON DEBUG for {entity_name} ===")
        print(f"Entity attributes: {[attr for attr in dir(entity) if not attr.startswith('_')][:20]}")
        
        # Try to get vehicle identifier from multiple sources
        icon_key = None
        
        # Method 1: Check tplCreatureType (most reliable for vehicles)
        tpl_creature_type = getattr(entity, 'tplCreatureType', None)
        print(f"tplCreatureType: {tpl_creature_type}")
        if tpl_creature_type:
            icon_key = self._match_vehicle_pattern(tpl_creature_type)
            print(f"Pattern matched tplCreatureType to: {icon_key}")
        
        # Method 2: Check hidName if no match yet
        if not icon_key:
            hidname = getattr(entity, 'hidName', None)
            print(f"hidName: {hidname}")
            if hidname:
                icon_key = self._match_vehicle_pattern(hidname)
                print(f"Pattern matched hidName to: {icon_key}")
        
        # Method 3: Check name attribute
        if not icon_key:
            name = getattr(entity, 'name', None)
            print(f"name: {name}")
            if name:
                icon_key = self._match_vehicle_pattern(name)
                print(f"Pattern matched name to: {icon_key}")
        
        # If we found a key, check cache or load it
        if icon_key:
            print(f"Final icon_key: {icon_key}")
            
            # Check if already in cache
            if icon_key in self.icon_cache:
                print(f"✓ Found in cache")
                return self.icon_cache[icon_key]
            
            # Not in cache - load it now
            if icon_key in self.HIDNAME_TO_ICON:
                filename = self.HIDNAME_TO_ICON[icon_key]
                icon_path = os.path.join(self.icons_directory, filename)
                print(f"Attempting to load: {icon_path}")
                
                if os.path.exists(icon_path):
                    pixmap = QPixmap(icon_path)
                    if not pixmap.isNull():
                        # Cache it for next time
                        self.icon_cache[icon_key] = pixmap
                        print(f"✓ Loaded icon: {filename}")
                        return pixmap
                    else:
                        print(f"✗ Failed to load icon (null pixmap): {icon_path}")
                else:
                    print(f"✗ Icon file not found: {icon_path}")
            else:
                print(f"✗ icon_key '{icon_key}' not in HIDNAME_TO_ICON mapping")
        else:
            print(f"✗ No icon_key found for this entity")
        
        print("=== END ICON DEBUG ===\n")
        return None

    def _match_vehicle_pattern(self, vehicle_string):
        """Match vehicle string to vehicle icon key by pattern matching"""
        if not vehicle_string:
            return None
        
        vehicle_lower = vehicle_string.lower()
        
        # Direct exact match (case-insensitive)
        if vehicle_lower in self.HIDNAME_TO_ICON:
            return vehicle_lower
        
        # Remove common suffixes and try again
        clean_string = vehicle_lower
        for suffix in ['.scripted', '.static', '.drivable', '.pilotable', '_drivable', '_pilotable', 
                       '.multi', '.controlled', '.npcversion', '.rogue', '.fortnavarone']:
            clean_string = clean_string.replace(suffix, '')
        
        if clean_string in self.HIDNAME_TO_ICON:
            return clean_string
        
        # Pattern matching for specific vehicles
        vehicle_patterns = {
            # Avatar vehicles
            'samson': 'vehicle.avatar.samson_pilotable',
            'scorpion': 'vehicle.avatar.scorpion_pilotable',
            'valkyrie': 'vehicle.avatar.valkyrie',
            'dragon': 'vehicle.avatar.dragon',
            'ampsuit': 'vehicle.avatar.ampsuit',
            'banshee': 'vehicle.avatar.banshee',
            'leonopteryx': 'vehicle.avatar.leonopteryx',
            'dove': 'vehicle.avatar.dove_drivable',
            'atv': 'vehicle.avatar.atv',
            'bulldozer': 'vehicle.avatar.bulldozer',
            'wheelloader': 'vehicle.avatar.wheelloader_drivable',
            
            # Far Cry 2 vehicles
            'paraglider': 'vehicle.air.paraglider',
            'bigtruck': 'vehicle.land.bigtruck',
            'datsun': 'vehicle.land.datsun',
            'jeepliberty': 'vehicle.land.jeepliberty',
            'jeepwrangler': 'vehicle.land.jeepwrangler',
            'rover': 'vehicle.land.rover',
            'fishingboat': 'vehicle.sea.fishingboat',
            'gunboat': 'vehicle.sea.gunboat',
            'hydroboat': 'vehicle.sea.hydroboat',
            'pirogue': 'vehicle.sea.pirogue',
            'swampboat': 'vehicle.sea.swampboat',
        }
        
        # Check for vehicle patterns in the string
        for pattern, icon_key in vehicle_patterns.items():
            if pattern in vehicle_lower:
                # Special handling for buggy vs buggy_light
                if pattern == 'buggy':
                    if 'light' in vehicle_lower:
                        return 'vehicle.corp_lights.buggy_light'
                    # Check if it's avatar buggy or fc2 buggy
                    if 'avatar' in vehicle_lower or 'corp' in vehicle_lower:
                        return 'vehicle.avatar.buggy_drivable'
                    else:
                        return 'vehicle.land.buggy'
                
                # Special handling for boat variants
                if pattern == 'boat' and 'avatar.boat' in vehicle_lower:
                    return 'vehicle.avatar.boat_drivable'
                
                return icon_key
        
        # Special cases for light variants
        if 'dove' in vehicle_lower and 'light' in vehicle_lower:
            return 'vehicle.corp_lights.dove_light'
        if 'dragon' in vehicle_lower and 'light' in vehicle_lower:
            return 'vehicle.corp_lights.dragon_light'
        
        # Check for wrecks
        if 'wreck' in vehicle_lower or 'burned' in vehicle_lower:
            return 'vehicle.wreck.carburned01_bk'
        
        return None

    def _get_candidate_names(self, entity_obj, entity_name):
        """Return names to check for prefix classification.

        Checks hidName (entity.name) first, then tplCreatureType from the XML
        element if it differs — so both FC2 and Avatar entities are handled.
        """
        candidates = [entity_name] if entity_name else []
        if entity_obj is not None:
            xml_el = getattr(entity_obj, 'xml_element', None)
            if xml_el is not None:
                ct_field = xml_el.find("./field[@name='tplCreatureType']")
                if ct_field is not None:
                    ct = ct_field.get('value-String') or ct_field.get('strVal') or ''
                    ct = ct.strip()
                    if ct and ct not in candidates:
                        candidates.append(ct)
            # Also check properties dict (ObjectEntity)
            props = getattr(entity_obj, 'properties', None)
            if props:
                ct = props.get('creature_type', '')
                if ct and ct not in candidates:
                    candidates.append(ct)
        return candidates

    def determine_entity_type(self, entity):
        """Enhanced entity type determination - CACHED"""
        # Check cache first
        entity_id = id(entity)
        if entity_id in self.entity_cache:
            cached_data = self.entity_cache[entity_id]
            if 'entity_type' in cached_data:
                return cached_data['entity_type']
        
        # Handle both entity objects and entity names
        if isinstance(entity, str):
            entity_name = entity
            entity_obj = None
        else:
            entity_name = getattr(entity, 'name', 'unknown')
            entity_obj = entity
        
        entity_name_lower = entity_name.lower()
        
        # Check if entity has object_type attribute
        if entity_obj and hasattr(entity_obj, 'object_type') and entity_obj.object_type:
            obj_type = entity_obj.object_type
            if obj_type in self.type_colors:
                return obj_type
        
        # Check for special data sources first
        if entity_obj:
            source_file_type = getattr(entity_obj, 'source_file_type', None)
            if source_file_type == "worldsector":
                return "WorldSectors"
            elif source_file_type == "landmark":
                return "Landmarks"

        # Prefix-based classification: use the first dot-segment of hidName.
        # Also check tplCreatureType from the XML element if available.
        for candidate_name in self._get_candidate_names(entity_obj, entity_name):
            prefix = candidate_name.split('.')[0].lower()
            result = self._HIDNAME_PREFIX_TYPES.get(prefix)
            if result:
                return result

        # Fallback: legacy substring pattern matching
        for entity_type, patterns in self.type_patterns.items():
            for pattern in patterns:
                if pattern in entity_name_lower:
                    return entity_type
        
        # Fallback to basic pattern matching
        if any(keyword in entity_name_lower for keyword in ["fence", "wall", "barrier"]):
            return "Structure"
        
        if any(keyword in entity_name_lower for keyword in ["pickup", "item", "collectible"]):
            return "Mission"
        
        return "Unknown"

    def get_entity_size_by_type(self, entity):
        """Enhanced size multipliers for more entity types - CACHED"""
        # Check cache first
        entity_id = id(entity)
        if entity_id in self.entity_cache:
            cached_data = self.entity_cache[entity_id]
            if 'size_multiplier' in cached_data:
                return cached_data['size_multiplier']
        
        if hasattr(entity, 'object_type') and entity.object_type:
            entity_type = entity.object_type
        else:
            entity_type = self.determine_entity_type(entity)
        
        size_multipliers = {
            # Large objects
            "Vehicle": 0.1,
            "Building": 0.1,
            "Structure": 0.1,
            
            # Medium objects
            "NPC": 0.1,
            "Character": 0.1,
            "StaticObject": 0.1,
            "Container": 0.1,
            "Tree": 0.1,
            
            # Small objects
            "Weapon": 0.1,
            "Prop": 0.1,
            "Light": 0.1,
            "Lamp": 0.1,
            "Sound": 0.1,
            "Audio": 0.1,
            
            # Tiny objects
            "Waypoint": 0.1,
            "Node": 0.1,
            "Effect": 0.1,
            "Particle": 0.1,
            
            # Mission objects
            "Mission": 0.1,
            "Objective": 0.1,
            "Spawn": 0.1,
            "Checkpoint": 0.1,
            
            # Interactive areas
            "Trigger": 0.1,
            "Zone": 0.1,
            "Area": 0.1,
            "Region": 0.1,
            
            # Special
            "WorldSectors": 0.1,
            "Landmarks": 0.1,
            
            # Default
            "Unknown": 0.1
        }
        
        return size_multipliers.get(entity_type, 0.1)
    
    def get_or_cache_entity_data(self, entity):
        """Get comprehensive cached entity data - OPTIMIZED"""
        entity_id = id(entity)
        
        # Check if entity has current cache
        if (entity_id in self.entity_cache and 
            self.entity_cache[entity_id].get('cache_version') == self.cache_version):
            return self.entity_cache[entity_id]
        
        # Compute all entity data once
        entity_type = self.determine_entity_type(entity)
        size_multiplier = self.get_entity_size_by_type(entity)
        is_fence = self.is_fence_object(entity)
        is_primitive = self.is_primitive_object(entity)
        is_trigger = self.is_trigger_entity(entity)
        has_shape = self.has_shape_points(entity)

        entity_data = {
            'cache_version': self.cache_version,
            'entity_type': entity_type,
            'size_multiplier': size_multiplier,
            'is_fence': is_fence,
            'is_primitive': is_primitive,
            'is_trigger': is_trigger,
            'has_shape_points': has_shape,
            'name': getattr(entity, 'name', 'unknown'),
            'normal_color': self.type_colors.get(entity_type, self.type_colors["Unknown"]),
            'selected_color': QColor(0, 0, 255),  # Blue selection color
            'rotation': 0.0,
            'rotation_cache_time': 0
        }
        
        # Cache it
        self.entity_cache[entity_id] = entity_data
        return entity_data

    def render_entities_2d(self, painter, canvas, entities):
        """2D rendering — GPU-style: vectorised cull + style-batched draw.

        Mirrors the 3D renderer's approach:
        - Entities arrive pre-culled (world-space AABB + budget cap in _get_visible_entities)
        - World→screen is inlined arithmetic, not a Python function call per entity
        - Entities are grouped by (color, outline_width) so setPen/setBrush fire once per
          group instead of once per entity
        - Fast path for rotation==0: plain drawRect(QRectF), no save/translate/rotate/restore
        """
        if not entities:
            return

        self._frame_count += 1
        current_time = time()
        should_log = current_time - self._last_2d_log_time > 5.0
        if should_log:
            print(f"Rendering {len(entities)} entities in 2D mode (GPU-style batch)")
            self._last_2d_log_time = current_time

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        SQUARE_SIZE = 6
        SELECTED_SIZE = 8

        selected_set = set(id(e) for e in getattr(canvas, 'selected', []))
        has_gizmo = (hasattr(canvas, 'gizmo_renderer') and
                     canvas.gizmo_renderer.rotation_gizmo is not None)

        # Inline world→screen constants — eliminates per-entity Python function-call overhead
        scale = canvas.scale_factor
        ox    = canvas.offset_x
        oy    = canvas.offset_y
        h     = canvas.height()

        from PyQt6.QtCore import QRectF

        # style_key -> {'color': QColor, 'out_w': int,
        #               'rects': [QRectF],            <- rotation == 0 fast path
        #               'rotated': [(sx,sy,size,rot)]} <- rotation != 0 slow path
        style_groups   = {}
        fence_list     = []
        primitive_list = []
        trigger_list   = []
        shape_list     = []
        label_list     = []

        for entity in entities:
            try:
                # Inlined world→screen (2 muls + 2 adds per entity, no function call)
                sx = int(round(entity.x * scale + ox))
                sy = int(round(h - (entity.y * scale + oy)))

                entity_data = self.get_or_cache_entity_data(entity)
                is_selected = id(entity) in selected_set

                if is_selected:
                    color = entity_data['selected_color']
                    size  = SELECTED_SIZE
                    out_w = 2
                else:
                    color = entity_data['normal_color']
                    size  = SQUARE_SIZE
                    out_w = 1

                rotation = 0.0
                if has_gizmo:
                    rotation = canvas.gizmo_renderer.rotation_gizmo.extract_entity_rotation(entity)

                key = (color.rgb(), out_w)
                if key not in style_groups:
                    style_groups[key] = {'color': color, 'out_w': out_w,
                                         'rects': [], 'rotated': []}

                if rotation == 0.0:
                    # Fast path: one drawRect call, no painter state save/restore
                    style_groups[key]['rects'].append(
                        QRectF(sx - size, sy - size, size * 2, size * 2)
                    )
                else:
                    style_groups[key]['rotated'].append((sx, sy, size, rotation))

                if entity_data['is_fence']:
                    fence_list.append((entity, sx, sy))
                if entity_data.get('is_primitive', False):
                    primitive_list.append((entity, sx, sy, is_selected))
                if entity_data.get('is_trigger', False) and getattr(canvas, 'show_trigger_zones', True):
                    trigger_list.append((entity, sx, sy, is_selected))
                if entity_data.get('has_shape_points', False):
                    shape_list.append((entity, is_selected))
                if is_selected:
                    label_list.append((entity, sx, sy, size))

            except Exception as e:
                if should_log:
                    print(f"Error processing entity: {e}")
                continue

        # --- Draw all style groups: one setPen/setBrush per group ---
        for group in style_groups.values():
            painter.setPen(QPen(Qt.GlobalColor.black, group['out_w']))
            painter.setBrush(QBrush(group['color']))
            # Fast path: no save/restore per entity
            for rect in group['rects']:
                painter.drawRect(rect)
            # Slow path: rotating entities only
            for sx, sy, size, rotation in group['rotated']:
                painter.save()
                painter.translate(sx, sy)
                painter.rotate(rotation)
                painter.drawRect(QRectF(-size, -size, size * 2, size * 2))
                painter.restore()

        # --- Fences, primitives, labels drawn after all squares ---
        for entity, x, y in fence_list:
            self.draw_fence_indicator_optimized(painter, entity, x, y, canvas)
        for entity, x, y, is_sel in primitive_list:
            self.draw_primitive_indicator_2d(painter, entity, x, y, canvas, is_sel)
        for entity, x, y, is_sel in trigger_list:
            self.draw_trigger_indicator_2d(painter, entity, x, y, canvas, is_sel)
        edit_mode = getattr(getattr(canvas, 'input_handler', None), 'edit_mode_2d', False)
        canvas._shape_add_btn_rect = None
        canvas._shape_remove_btn_rect = None
        canvas._shape_btn_entity = None
        for entity, is_sel in shape_list:
            self.draw_shape_outline_2d(painter, entity, canvas, is_sel, edit_mode)
        for entity, x, y, size in label_list:
            self._draw_entity_label_2d_optimized(painter, entity, x, y, size, False)

        if should_log:
            print(f"Drew {len(entities)} entities | {len(style_groups)} style groups")

    def draw_batch_squares_rotated(self, painter, squares_data):
        """Draw multiple rotated squares efficiently"""
        if not squares_data:
            return
        
        for square in squares_data:
            x = square['x']
            y = square['y']
            size = square['size']
            rotation = square.get('rotation', 0.0)
            color = square['color']
            outline_width = square['outline_width']
            
            # Set pen and brush
            painter.setPen(QPen(Qt.GlobalColor.black, outline_width))
            painter.setBrush(QBrush(color))
            
            # Save painter state
            painter.save()
            
            # Move to entity position and rotate
            painter.translate(x, y)
            painter.rotate(rotation)
            
            # Draw square centered at origin (after translation)
            from PyQt6.QtCore import QRectF
            rect = QRectF(-size, -size, size * 2, size * 2)
            painter.drawRect(rect)
            
            # Restore painter state
            painter.restore()

    def draw_batch_icons(self, painter, icons_data):
        """Draw multiple vehicle icons efficiently with rotation"""
        if not icons_data:
            return  # Removed debug print - this is normal when nothing is selected
        
        for icon_info in icons_data:
            x = icon_info['x']
            y = icon_info['y']
            pixmap = icon_info['pixmap']
            size = icon_info['size']
            rotation = icon_info.get('rotation', 0.0)
            is_selected = icon_info['is_selected']
            is_highlighted = icon_info['is_highlighted']
            
            # Save painter state
            painter.save()
            
            # Move to the entity position
            painter.translate(x, y)
            
            # Rotate around the center
            painter.rotate(rotation)
            
            # Scale pixmap to desired size
            scaled_pixmap = pixmap.scaled(
                size, size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            
            # Calculate position (center the icon)
            half_size = size // 2
            draw_x = -half_size
            draw_y = -half_size
                        
            # Draw the icon
            painter.drawPixmap(draw_x, draw_y, scaled_pixmap)
            
            # Restore painter state
            painter.restore()

    def draw_square(self, painter, x, y, size):
        """Draw a square centered at (x, y) with side length = size * 2"""
        from PyQt6.QtCore import QRectF

        half = size
        rect = QRectF(x - half, y - half, size * 2, size * 2)
        painter.drawRect(rect)

    def draw_batch_circles(self, painter, circles_data):
        """Draw multiple SQUARES efficiently using the same batching system."""
        if not circles_data:
            return
        
        circles_by_style = {}
        
        for circle in circles_data:
            style_key = (
                circle['color'].rgb(),
                circle['outline_width']
            )
            
            if style_key not in circles_by_style:
                circles_by_style[style_key] = []
            
            circles_by_style[style_key].append(circle)
        
        for (color_rgb, outline_width), circle_group in circles_by_style.items():
            color = QColor()
            color.setRgb(color_rgb)
            
            painter.setPen(QPen(Qt.GlobalColor.black, outline_width))
            painter.setBrush(QBrush(color))
            
            for circle in circle_group:
                radius = circle['size']
                self.draw_square(painter, circle['x'], circle['y'], radius)

    def draw_fence_indicator_optimized(self, painter, entity, screen_x, screen_y, canvas):
        """Draw fence line with static-size endpoint circles"""
        if not self.is_fence_object(entity):
            return False

        # Get Z rotation from hidAngles
        rotation = 0.0
        hid_angles = getattr(entity, 'hidAngles', None)
        if hid_angles:
            rotation = hid_angles[2]  # Z-axis rotation

        # Adjust to match game orientation
        rotation += 90

        # Cache for performance
        entity_data = self.get_or_cache_entity_data(entity)
        entity_data['rotation'] = rotation

        # Fence line calculation
        fence_width_world = 24
        half_width_screen = (fence_width_world * canvas.scale_factor) / 2
        angle_rad = math.radians(rotation)
        dx = half_width_screen * math.cos(angle_rad)
        dy = half_width_screen * math.sin(angle_rad)

        start_x = int(screen_x - dx)
        start_y = int(screen_y - dy)
        end_x = int(screen_x + dx)
        end_y = int(screen_y + dy)

        # Draw the main fence line
        painter.setPen(QPen(QColor(255, 0, 0), 3))
        painter.drawLine(start_x, start_y, end_x, end_y)

        # Draw static-size endpoint circles (same size as squares)
        painter.setBrush(QBrush(QColor(255, 0, 0)))
        painter.setPen(QPen(Qt.GlobalColor.black, 1))
        radius = 8  # static pixel radius
        painter.drawEllipse(start_x - radius, start_y - radius, radius * 2, radius * 2)
        painter.drawEllipse(end_x - radius, end_y - radius, radius * 2, radius * 2)

        return True

    def draw_primitive_indicator_2d(self, painter, entity, screen_x, screen_y, canvas, is_selected=False):
        """Draw 2D box representation of primitive blocking volume"""
        if not self.is_primitive_object(entity):
            return False
        
        # Get shape data
        shape_data = self.get_primitive_shape_data(entity)
        shape_type = shape_data['shape_type']
        vector_scale = shape_data['scale']
        hid_scale = shape_data['hidScale']
        
        # Get rotation from hidAngles
        rotation = 0.0
        hid_angles = getattr(entity, 'hidAngles', None)
        if hid_angles:
            rotation = hid_angles[2]  # Z-axis rotation
        
        # Convert scale to screen space
        # For 2D top-down view, we use X and Y scale
        # X = left/right (width), Y = forward/back (height in 2D view), Z = up/down (not shown in top-down)
        # The wireframe shapes are defined from -1 to 1 (size 2), so when we apply
        # vector_scale * hid_scale, we get the full world size
        # Example: vector_scale=[2,3,4] * hid_scale=1.0 * base_size=2 = [4,6,8] world units
        width_world = vector_scale[0] * hid_scale * 2   # X scale (left/right)
        height_world = vector_scale[1] * hid_scale * 2  # Y scale (forward/back in top-down)
        
        width_screen = width_world * canvas.scale_factor
        height_screen = height_world * canvas.scale_factor
        
        # Debug: log first few primitives
        if not hasattr(self, '_2d_primitive_log_count'):
            self._2d_primitive_log_count = 0
        
        if self._2d_primitive_log_count < 3:
            entity_name = getattr(entity, 'name', 'unknown')
            print(f"2D Primitive '{entity_name}': vectorScale={vector_scale}, hidScale={hid_scale}")
            print(f"  Using X={vector_scale[0]}, Y={vector_scale[1]} (Z={vector_scale[2]} not shown in top-down)")
            print(f"  width_world={width_world:.2f}, height_world={height_world:.2f}")
            print(f"  scale_factor={canvas.scale_factor:.4f}")
            print(f"  width_screen={width_screen:.2f}, height_screen={height_screen:.2f}")
            self._2d_primitive_log_count += 1
        
        # Draw based on shape type
        painter.save()
        painter.translate(screen_x, screen_y)
        painter.rotate(rotation)
        
        # Color coding: blue when selected, cyan/teal when not selected
        if is_selected:
            color = QColor(0, 100, 255, 30)  # Blue with transparency when selected
            outline_color = QColor(0, 0, 255, 255)  # Bright blue outline when selected
            pen_width = 2  # Thicker outline when selected
        else:
            color = QColor(0, 255, 255, 25)  # Cyan with transparency when not selected
            outline_color = QColor(0, 200, 200, 255)  # Darker cyan for outline
            pen_width = 1
        
        painter.setPen(QPen(outline_color, pen_width, Qt.PenStyle.DashLine))
        painter.setBrush(QBrush(color))
        
        half_w = width_screen / 2
        half_h = height_screen / 2
        
        if shape_type == 0:  # Cube
            # Draw rectangle
            painter.drawRect(int(-half_w), int(-half_h), int(width_screen), int(height_screen))
        
        elif shape_type == 1:  # Sphere
            # Draw circle (use average of width/height for radius)
            radius = (width_screen + height_screen) / 4
            painter.drawEllipse(int(-radius), int(-radius), int(radius * 2), int(radius * 2))
        
        elif shape_type == 2:  # Cylinder
            # Draw ellipse (width for diameter, height for depth)
            painter.drawEllipse(int(-half_w), int(-half_h), int(width_screen), int(height_screen))
        
        painter.restore()
        return True

    def _draw_entity_label_2d_optimized(self, painter, entity, x, y, size, is_highlighted):
        """Optimized 2D label drawing"""
        entity_name = getattr(entity, 'name', 'Unknown')
        
        # Simplified label for performance
        if len(entity_name) > 50:
            entity_name = entity_name[:50] + "..."
        
        painter.setFont(QFont("Arial", 8))  # Smaller font for performance
        
        if is_highlighted:
            painter.setPen(QPen(QColor(0, 0, 0), 1))
            painter.setBrush(QBrush(QColor(255, 255, 0, 200)))
        else:
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(QBrush(QColor(0, 0, 0, 150)))
        
        # Simple text positioning
        text_x = x + size + 5
        text_y = y
        
        # Draw simple background
        metrics = painter.fontMetrics()
        text_width = metrics.boundingRect(entity_name).width()
        painter.fillRect(text_x - 2, text_y - metrics.ascent() - 2, 
                        text_width + 4, metrics.height() + 4, 
                        QColor(0, 0, 0, 150))
        
        # Draw text
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.drawText(text_x, text_y, entity_name)

    def is_fence_object(self, entity):
        """Check if entity is a fence object - CACHED"""
        entity_id = id(entity)
        if entity_id in self.entity_cache:
            cached_data = self.entity_cache[entity_id]
            if 'is_fence' in cached_data:
                return cached_data['is_fence']
        
        entity_name = getattr(entity, 'name', '')
        is_fence = "SO.corp_fence_security_" in entity_name
        
        # Cache the result
        if entity_id not in self.entity_cache:
            self.entity_cache[entity_id] = {}
        self.entity_cache[entity_id]['is_fence'] = is_fence
        
        return is_fence
    
    def is_primitive_object(self, entity):
        """Check if entity is a Primitive object (invisible blocking volume) - CACHED"""
        entity_id = id(entity)
        if entity_id in self.entity_cache:
            cached_data = self.entity_cache[entity_id]
            if 'is_primitive' in cached_data:
                return cached_data['is_primitive']
        
        entity_name = getattr(entity, 'name', '')
        is_primitive = "Primitive" in entity_name
        
        # Cache the result
        if entity_id not in self.entity_cache:
            self.entity_cache[entity_id] = {}
        self.entity_cache[entity_id]['is_primitive'] = is_primitive
        
        return is_primitive
    
    def get_primitive_shape_data(self, entity):
        """Extract primitive shape information from entity components - CACHED"""
        entity_id = id(entity)
        if entity_id in self.entity_cache:
            cached_data = self.entity_cache[entity_id]
            if 'primitive_shape' in cached_data:
                return cached_data['primitive_shape']
        
        shape_data = {
            'shape_type': 0,  # Default to Cube (0)
            'scale': [1.0, 1.0, 1.0],  # Default vectorScale
            'hidScale': 1.0  # Default hidScale (uniform scale)
        }
        
        entity_name = getattr(entity, 'name', 'unknown')
        debug = False  # Set to True to see detailed extraction logging
        
        # Extract from XML element if available
        if hasattr(entity, 'xml_element') and entity.xml_element is not None:
            if debug:
                print(f"\n=== Extracting primitive data for {entity_name} ===")
            
            # Extract hidScale (uniform scale like 3D models use)
            scale_field = entity.xml_element.find(".//field[@name='hidScale']")
            if scale_field is not None:
                binhex = scale_field.text
                if binhex and len(binhex) >= 8:  # Need at least 8 hex chars (4 bytes)
                    try:
                        import struct
                        # Convert hex string to bytes
                        scale_bytes = bytes.fromhex(binhex[:8])
                        # Unpack as little-endian 32-bit float
                        hidScale = struct.unpack('<f', scale_bytes)[0]
                        # Sanity check: scale should be positive and reasonable
                        if hidScale > 0 and hidScale <= 100:
                            shape_data['hidScale'] = hidScale
                            if debug:
                                print(f"  hidScale: {hidScale}")
                    except (ValueError, struct.error) as e:
                        if debug:
                            print(f"  Error parsing hidScale: {e}")
            
            # Find CSimplePrimitiveComponent in XML
            primitive_component = entity.xml_element.find(".//object[@name='CSimplePrimitiveComponent']")
            if primitive_component is not None:
                if debug:
                    print(f"  Found CSimplePrimitiveComponent")
                
                # Get shape type (selShape)
                shape_field = primitive_component.find(".//field[@name='selShape']")
                if shape_field is not None:
                    shape_enum = shape_field.get('value-Enum')
                    if shape_enum is not None:
                        try:
                            shape_data['shape_type'] = int(shape_enum)
                            if debug:
                                print(f"  selShape: {shape_data['shape_type']}")
                        except (ValueError, TypeError) as e:
                            if debug:
                                print(f"  Error parsing selShape: {e}")
                
                # Get vectorScale from XML
                vector_scale_field = primitive_component.find(".//field[@name='vectorScale']")
                if vector_scale_field is not None:
                    if debug:
                        print(f"  Found vectorScale field")
                    
                    # Try to get from value-Vector3 attribute first
                    vector3_str = vector_scale_field.get('value-Vector3')
                    if vector3_str:
                        try:
                            # Parse "X,Y,Z" format
                            parts = vector3_str.split(',')
                            if len(parts) >= 3:
                                shape_data['scale'] = [float(parts[0]), float(parts[1]), float(parts[2])]
                                if debug:
                                    print(f"  vectorScale (from attribute): {shape_data['scale']}")
                        except (ValueError, AttributeError) as e:
                            if debug:
                                print(f"  Error parsing value-Vector3: {e}")
                    
                    # If that didn't work, try parsing BinHex
                    if shape_data['scale'] == [1.0, 1.0, 1.0]:
                        binhex = vector_scale_field.text
                        if binhex and len(binhex) >= 24:  # Need 24 hex chars (3 floats * 4 bytes * 2 hex/byte)
                            try:
                                import struct
                                # Extract 3 floats from hex string
                                x_bytes = bytes.fromhex(binhex[0:8])
                                y_bytes = bytes.fromhex(binhex[8:16])
                                z_bytes = bytes.fromhex(binhex[16:24])
                                
                                x = struct.unpack('<f', x_bytes)[0]
                                y = struct.unpack('<f', y_bytes)[0]
                                z = struct.unpack('<f', z_bytes)[0]
                                
                                # Sanity check
                                if all(0 < val <= 100 for val in [x, y, z]):
                                    shape_data['scale'] = [x, y, z]
                                    if debug:
                                        print(f"  vectorScale (from BinHex): {shape_data['scale']}")
                            except (ValueError, struct.error) as e:
                                if debug:
                                    print(f"  Error parsing BinHex: {e}")
                else:
                    if debug:
                        print(f"  vectorScale field not found!")
            else:
                if debug:
                    print(f"  CSimplePrimitiveComponent not found!")
        else:
            if debug:
                print(f"  No xml_element attribute on entity!")
        
        # Fallback: Try to extract from components attribute (legacy support)
        if shape_data['scale'] == [1.0, 1.0, 1.0] and hasattr(entity, 'components'):
            if debug:
                print(f"  Trying fallback: components attribute")
            for component in entity.components:
                # Look for CSimplePrimitiveComponent
                component_name = getattr(component, 'name', '')
                if 'CSimplePrimitiveComponent' in component_name or 'SimplePrimitive' in component_name:
                    # Get shape type (selShape)
                    if hasattr(component, 'selShape'):
                        shape_data['shape_type'] = component.selShape
                        if debug:
                            print(f"  selShape (from component): {shape_data['shape_type']}")
                    
                    # Get scale (vectorScale)
                    if hasattr(component, 'vectorScale'):
                        scale = component.vectorScale
                        if isinstance(scale, (list, tuple)) and len(scale) >= 3:
                            shape_data['scale'] = [float(scale[0]), float(scale[1]), float(scale[2])]
                            if debug:
                                print(f"  vectorScale (from component): {shape_data['scale']}")
                    
                    break
        
        # Cache the result
        if entity_id not in self.entity_cache:
            self.entity_cache[entity_id] = {}
        self.entity_cache[entity_id]['primitive_shape'] = shape_data
        
        # Log first few primitives to verify extraction
        if not hasattr(self, '_primitive_log_count'):
            self._primitive_log_count = 0
        
        if self._primitive_log_count < 5:  # Log first 5 primitives
            print(f"Primitive '{entity_name}': type={shape_data['shape_type']}, "
                  f"vectorScale={shape_data['scale']}, hidScale={shape_data['hidScale']}")
            self._primitive_log_count += 1
        
        return shape_data
    
    def get_shape_points(self, entity):
        """Parse hidShapePoints <Point> children into [[x,y,z], ...]. Cached."""
        entity_id = id(entity)
        if entity_id in self.entity_cache and 'shape_points' in self.entity_cache[entity_id]:
            return self.entity_cache[entity_id]['shape_points']
        points = []
        if hasattr(entity, 'xml_element') and entity.xml_element is not None:
            field = entity.xml_element.find("field[@name='hidShapePoints']")
            if field is not None:
                for pt in field.findall('Point'):
                    try:
                        parts = pt.text.strip().split(',')
                        if len(parts) == 3:
                            points.append([float(parts[0]), float(parts[1]), float(parts[2])])
                    except (ValueError, AttributeError):
                        pass
        if entity_id not in self.entity_cache:
            self.entity_cache[entity_id] = {}
        self.entity_cache[entity_id]['shape_points'] = points
        return points

    def has_shape_points(self, entity):
        return len(self.get_shape_points(entity)) > 0

    def draw_shape_outline_2d(self, painter, entity, canvas, is_selected, edit_mode):
        """Draw hidShapePoints polygon. View mode: dashed outline. Edit mode: + draggable handles."""
        points = self.get_shape_points(entity)
        if not points:
            return

        screen_pts = [QPointF(*canvas.world_to_screen(px, py)) for px, py, pz in points]
        if len(screen_pts) < 2:
            return

        if is_selected:
            outline_color = QColor(0, 220, 80, 255)
            fill_color    = QColor(0, 200, 80, 30)
            pen_width = 2
        else:
            outline_color = QColor(0, 180, 60, 180)
            fill_color    = QColor(0, 160, 60, 12)
            pen_width = 1

        painter.setPen(QPen(outline_color, pen_width, Qt.PenStyle.DashLine))
        painter.setBrush(QBrush(fill_color))
        painter.drawPolygon(QPolygonF(screen_pts))

        # Draw point handles — larger in edit mode (interactive), small dots in view mode
        ih = getattr(canvas, 'input_handler', None)
        sel_pt = getattr(ih, 'selected_shape_point', None)
        sel_entity = sel_pt[0] if sel_pt else None
        sel_idx    = sel_pt[1] if sel_pt else None

        painter.setPen(QPen(QColor(255, 255, 255, 200), 1))
        for i, sp in enumerate(screen_pts):
            sx, sy = sp.x(), sp.y()
            is_sel_pt = (sel_entity is entity and sel_idx == i)
            if edit_mode:
                r = 8 if i == 0 else 6
                if i == 0:
                    color = QColor(255, 120, 0, 240) if is_sel_pt else QColor(255, 200, 0, 220)
                else:
                    color = QColor(255, 60, 60, 240) if is_sel_pt else QColor(0, 220, 80, 200)
            else:
                r = 4 if i == 0 else 3
                color = QColor(255, 200, 0, 180) if i == 0 else QColor(0, 200, 80, 160)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QRectF(sx - r, sy - r, r * 2, r * 2))

        # +/- buttons at the last point (edit mode + selected entity only)
        if edit_mode and is_selected and len(screen_pts) >= 1:
            lsx, lsy = screen_pts[-1].x(), screen_pts[-1].y()
            btn_w, btn_h = 16, 16
            gap = 3
            add_x = lsx + 14
            add_y = lsy - btn_h / 2
            rem_x = add_x + btn_w + gap
            rem_y = add_y

            canvas._shape_add_btn_rect = (add_x, add_y, btn_w, btn_h)
            canvas._shape_btn_entity = entity
            if len(screen_pts) >= 2:
                canvas._shape_remove_btn_rect = (rem_x, rem_y, btn_w, btn_h)

            font = painter.font()
            font.setBold(True)
            painter.setFont(font)

            painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
            painter.setBrush(QBrush(QColor(0, 150, 70, 210)))
            painter.drawRoundedRect(QRectF(add_x, add_y, btn_w, btn_h), 3, 3)
            painter.setPen(QPen(QColor(255, 255, 255, 255), 1))
            painter.drawText(QRectF(add_x, add_y, btn_w, btn_h), Qt.AlignmentFlag.AlignCenter, "+")

            if len(screen_pts) >= 2:
                painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
                painter.setBrush(QBrush(QColor(170, 35, 35, 210)))
                painter.drawRoundedRect(QRectF(rem_x, rem_y, btn_w, btn_h), 3, 3)
                painter.setPen(QPen(QColor(255, 255, 255, 255), 1))
                painter.drawText(QRectF(rem_x, rem_y, btn_w, btn_h), Qt.AlignmentFlag.AlignCenter, "−")

            font.setBold(False)
            painter.setFont(font)

    def is_trigger_entity(self, entity):
        """Check if entity has a CProximityTriggerComponent - CACHED"""
        entity_id = id(entity)
        if entity_id in self.entity_cache and 'is_trigger' in self.entity_cache[entity_id]:
            return self.entity_cache[entity_id]['is_trigger']
        is_trigger = False
        if hasattr(entity, 'xml_element') and entity.xml_element is not None:
            is_trigger = entity.xml_element.find(".//object[@name='CProximityTriggerComponent']") is not None
        if entity_id not in self.entity_cache:
            self.entity_cache[entity_id] = {}
        self.entity_cache[entity_id]['is_trigger'] = is_trigger
        return is_trigger

    def get_trigger_size(self, entity):
        """Extract vectorSize and hidScale from CProximityTriggerComponent - CACHED.
        Returns {'size': [x,y,z], 'hidScale': float} matching get_primitive_shape_data layout."""
        entity_id = id(entity)
        if entity_id in self.entity_cache and 'trigger_size' in self.entity_cache[entity_id]:
            return self.entity_cache[entity_id]['trigger_size']

        data = {'size': [5.0, 5.0, 5.0], 'hidScale': 1.0}

        if hasattr(entity, 'xml_element') and entity.xml_element is not None:
            xml = entity.xml_element

            # Read hidScale from entity root (same as get_primitive_shape_data)
            scale_field = xml.find(".//field[@name='hidScale']")
            if scale_field is not None:
                binhex = scale_field.text
                if binhex and len(binhex) >= 8:
                    try:
                        import struct
                        hid = struct.unpack('<f', bytes.fromhex(binhex[:8]))[0]
                        if 0 < hid <= 100:
                            data['hidScale'] = hid
                    except (ValueError, struct.error):
                        pass

            # Read vectorSize from CProximityTriggerComponent
            comp = xml.find(".//object[@name='CProximityTriggerComponent']")
            if comp is not None:
                size_field = comp.find("field[@name='vectorSize']")
                if size_field is not None:
                    vec3 = size_field.get('value-Vector3')
                    if vec3:
                        try:
                            parts = vec3.split(',')
                            if len(parts) >= 3:
                                data['size'] = [float(parts[0]), float(parts[1]), float(parts[2])]
                        except (ValueError, AttributeError):
                            pass
                    else:
                        binhex = size_field.text
                        if binhex and len(binhex) >= 24:
                            try:
                                import struct
                                x = struct.unpack('<f', bytes.fromhex(binhex[0:8]))[0]
                                y = struct.unpack('<f', bytes.fromhex(binhex[8:16]))[0]
                                z = struct.unpack('<f', bytes.fromhex(binhex[16:24]))[0]
                                if all(0 < v < 100000 for v in [x, y, z]):
                                    data['size'] = [x, y, z]
                            except (ValueError, struct.error):
                                pass

        if entity_id not in self.entity_cache:
            self.entity_cache[entity_id] = {}
        self.entity_cache[entity_id]['trigger_size'] = data
        return data

    def get_trigger_color(self, entity):
        """Return (r,g,b) float tuple for a trigger entity's wireframe color.
        Red   = kill triggers or COmniMapTickedEntity
        Grey  = domino/omni entities (COmniEntity, DominoOmniEntity_)
        Yellow = everything else (default proximity trigger)
        """
        name = getattr(entity, 'name', '') or ''
        entity_class = ''
        if hasattr(entity, 'xml_element') and entity.xml_element is not None:
            cls_field = entity.xml_element.find("field[@name='text_hidEntityClass']")
            if cls_field is not None:
                entity_class = cls_field.get('value-String', '') or ''

        name_upper = name.upper()
        cls_upper  = entity_class.upper()

        if 'KILL' in name_upper or 'COMNIMAPTICKED' in cls_upper:
            return (1.0, 0.15, 0.15)   # red
        if 'DOMINOOMNI' in name_upper or cls_upper in ('COMNIENTITY', 'COMNIMAPENTITY'):
            return (0.55, 0.55, 0.55)  # grey
        return (1.0, 1.0, 0.0)         # yellow (default)

    def draw_trigger_indicator_2d(self, painter, entity, screen_x, screen_y, canvas, is_selected=False):
        """Draw 2D yellow wireframe box for trigger volume"""
        data = self.get_trigger_size(entity)
        size = data['size']
        hid_scale = data['hidScale']
        # vectorSize are half-extents; wireframe is -1..1 so multiply by 2 for full world size
        # Same formula as draw_primitive_indicator_2d
        width_screen  = size[0] * hid_scale * 2 * canvas.scale_factor
        height_screen = size[1] * hid_scale * 2 * canvas.scale_factor
        half_w = width_screen / 2
        half_h = height_screen / 2

        rotation = 0.0
        hid_angles = getattr(entity, 'hidAngles', None)
        if hid_angles and len(hid_angles) >= 3:
            rotation = hid_angles[2]

        r, g, b = self.get_trigger_color(entity)
        ri, gi, bi = int(r * 255), int(g * 255), int(b * 255)

        if is_selected:
            fill_color    = QColor(ri, gi, bi, 40)
            outline_color = QColor(ri, gi, bi, 255)
            pen_width = 2
        else:
            fill_color    = QColor(ri, gi, bi, 20)
            outline_color = QColor(int(r * 200), int(g * 200), int(b * 200), 200)
            pen_width = 1

        painter.save()
        painter.translate(screen_x, screen_y)
        if rotation != 0.0:
            painter.rotate(rotation)
        painter.setPen(QPen(outline_color, pen_width, Qt.PenStyle.DashLine))
        painter.setBrush(QBrush(fill_color))
        painter.drawRect(int(-half_w), int(-half_h), int(width_screen), int(height_screen))
        painter.restore()
        return True

    def invalidate_entity_cache(self, entity):
        """Invalidate cache for specific entity"""
        entity_id = id(entity)
        if entity_id in self.entity_cache:
            del self.entity_cache[entity_id]

    def invalidate_all_caches(self):
        """Invalidate all entity caches by bumping version"""
        self.cache_version += 1
        print(f"Cache version bumped to {self.cache_version}")

    def invalidate_all_entity_caches(self):
        """Invalidate cached data for ALL entities"""
        self.entity_cache.clear()
        self.cache_version += 1
