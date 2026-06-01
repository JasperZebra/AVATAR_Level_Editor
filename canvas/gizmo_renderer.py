"""Gizmo renderer for rotation tools and entity manipulation - 2D ONLY"""

import math
import time
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QVector3D
from .opengl_utils import OpenGLUtils

class RotationGizmo:
    """Rotation gizmo for rotating entities around their Z-axis - 2D ONLY"""
    
    def __init__(self):
        self.position = QVector3D(0, 0, 0)
        self.hidden = True
        self.radius = 30
        self.thickness = 3
        self.is_dragging = False
        self.is_dragging_center = False  # ADD THIS LINE
        self.drag_start_angle = 0
        self.initial_rotation = 0
        self.current_rotation = 0
        self.drag_start_pos = (0, 0)
        
        # Performance tracking
        self._last_rotation_log_time = 0
    
    def move_to_entity(self, entity):
        """Move gizmo to entity position"""
        if entity:
            self.position = QVector3D(entity.x, entity.y, entity.z)  # Store entity coordinates
            self.hidden = False
            self.current_rotation = self.extract_entity_rotation(entity)
            self.initial_rotation = self.current_rotation
            print(f"🎯 Moved rotation gizmo to {getattr(entity, 'name', 'entity')} at ({entity.x}, {entity.y}) rotation {self.current_rotation:.1f}°")
        else:
            self.hidden = True

    def extract_entity_rotation(self, entity):
        """Extract Z rotation from entity's XML data with comprehensive caching"""
        entity_id = id(entity)
        current_time = time.time()
        
        # PRIORITY 1: Check entity renderer cache first (most reliable)
        if hasattr(self, 'canvas') and hasattr(self.canvas, 'entity_renderer'):
            entity_data = self.canvas.entity_renderer.entity_cache.get(entity_id)
            if (entity_data and 
                current_time - entity_data.get('rotation_cache_time', 0) < 5.0):
                return entity_data['rotation']
        
        # PRIORITY 2: Check local gizmo cache
        if hasattr(entity, '_gizmo_cached_rotation') and hasattr(entity, '_gizmo_rotation_cache_time'):
            if current_time - entity._gizmo_rotation_cache_time < 5.0:
                return entity._gizmo_cached_rotation
        
        # CALCULATION NEEDED: No valid cache found
        if not hasattr(entity, 'xml_element') or entity.xml_element is None:
            # Cache the "no rotation" result in both places
            self._cache_rotation_result(entity, 0.0, current_time)
            return 0.0
        
        rotation_z = 0.0
        entity_name = getattr(entity, 'name', 'entity')
        
        # Reduce logging frequency to every 5 seconds
        should_log = current_time - getattr(self, '_last_rotation_log_time', 0) > 5.0
        
        try:
            # Method 1: FCBConverter format (field elements)
            angles_field = entity.xml_element.find("./field[@name='hidAngles']")
            if angles_field is not None:
                angles_value = angles_field.get('value-Vector3')
                if angles_value:
                    try:
                        parts = angles_value.split(',')
                        if len(parts) >= 3:
                            game_rotation = float(parts[2].strip())
                            # Convert from game coordinates to editor coordinates
                            rotation_z = (360 - game_rotation) % 360
                            
                            if should_log and rotation_z != 0:
                                print(f"🔄 FCB rotation for {entity_name}: game={game_rotation:.1f}° -> editor={rotation_z:.1f}°")
                                self._last_rotation_log_time = current_time
                            
                            # Cache result in both places
                            self._cache_rotation_result(entity, rotation_z, current_time)
                            return rotation_z
                    except (ValueError, IndexError):
                        pass
            
            # Method 2: Dunia Tools format (value elements)
            angles_elem = entity.xml_element.find("./value[@name='hidAngles']")
            if angles_elem is not None:
                z_elem = angles_elem.find("./z")
                if z_elem is not None and z_elem.text:
                    try:
                        game_rotation = float(z_elem.text.strip())
                        # Convert from game coordinates to editor coordinates
                        rotation_z = (360 - game_rotation) % 360
                        
                        if should_log and rotation_z != 0:
                            print(f"🔄 Dunia rotation for {entity_name}: game={game_rotation:.1f}° -> editor={rotation_z:.1f}°")
                            self._last_rotation_log_time = current_time
                        
                        # Cache result in both places
                        self._cache_rotation_result(entity, rotation_z, current_time)
                        return rotation_z
                    except ValueError:
                        pass
            
            # Method 3: Check for rotation field directly
            rotation_field = entity.xml_element.find("./field[@name='rotation']")
            if rotation_field is not None:
                rotation_value = rotation_field.get('value') or rotation_field.text
                if rotation_value:
                    try:
                        rotation_z = float(rotation_value)
                        
                        if should_log and rotation_z != 0:
                            print(f"🔄 Direct rotation for {entity_name}: {rotation_z:.1f}°")
                            self._last_rotation_log_time = current_time
                        
                        # Cache result in both places
                        self._cache_rotation_result(entity, rotation_z, current_time)
                        return rotation_z
                    except ValueError:
                        pass
                        
        except Exception:
            pass
        
        # No rotation found - cache the zero result
        if should_log:
            print(f"⚠️ No rotation found for {entity_name}, using 0°")
            self._last_rotation_log_time = current_time
        
        # Cache the "no rotation found" result in both places
        self._cache_rotation_result(entity, 0.0, current_time)
        return 0.0

    def _cache_rotation_result(self, entity, rotation_z, current_time):
        """Cache rotation result in both local and entity renderer caches"""
        entity_id = id(entity)
        
        # Cache in local gizmo cache
        entity._gizmo_cached_rotation = rotation_z
        entity._gizmo_rotation_cache_time = current_time
        
        # Cache in entity renderer cache if available
        if hasattr(self, 'canvas') and hasattr(self.canvas, 'entity_renderer'):
            # Get or create entity data
            entity_data = self.canvas.entity_renderer.get_or_cache_entity_data(entity)
            entity_data['rotation'] = rotation_z
            entity_data['rotation_cache_time'] = current_time

    def get_cached_rotation(self, entity, canvas):
        """Get cached rotation with minimal recalculation - used by EntityRenderer"""
        entity_id = id(entity)
        current_time = time()
        
        # Get entity data from cache
        entity_data = self.get_or_cache_entity_data(entity)
        
        # Check if rotation cache is still valid (5 second cache)
        if (current_time - entity_data.get('rotation_cache_time', 0) < 5.0):
            return entity_data['rotation']
        
        # Only recalculate if cache expired - delegate to gizmo renderer
        if hasattr(canvas, 'gizmo_renderer') and canvas.gizmo_renderer.rotation_gizmo:
            rotation = canvas.gizmo_renderer.rotation_gizmo.extract_entity_rotation(entity)
            return rotation
        
        return 0.0
    
    def update_entity_rotation(self, entity, new_rotation):
        """Update entity rotation in XML and invalidate cache"""
        if not hasattr(entity, 'xml_element') or entity.xml_element is None:
            print(f"⚠️ Cannot update rotation for {getattr(entity, 'name', 'entity')}: No XML element")
            return False
        
        try:
            # Convert editor rotation to game rotation
            game_rotation = (360 - new_rotation) % 360
            entity_name = getattr(entity, 'name', 'entity')
            
            # Only log updates occasionally
            current_time = time.time()
            should_log = current_time - getattr(self, '_last_update_log_time', 0) > 1.0
            
            if should_log:
                print(f"🔄 Updating {entity_name}: editor={new_rotation:.1f}° -> game={game_rotation:.1f}°")
                self._last_update_log_time = current_time
            
            # Method 1: FCBConverter format
            angles_field = entity.xml_element.find("./field[@name='hidAngles']")
            if angles_field is not None:
                angles_value = angles_field.get('value-Vector3')
                if angles_value:
                    try:
                        parts = angles_value.split(',')
                        if len(parts) >= 3:
                            # Update Z rotation while preserving X and Y
                            parts[2] = f"{game_rotation:.1f}"
                            new_angles_value = ','.join(parts)
                            angles_field.set('value-Vector3', new_angles_value)
                            
                            # Update binary hex data if present
                            binary_hex = self._angles_to_binhex(float(parts[0]), float(parts[1]), game_rotation)
                            angles_field.text = binary_hex
                            
                            # Invalidate cache
                            self._invalidate_rotation_cache(entity)
                            
                            # Find canvas through direct object inspection
                            try:
                                canvas = None
                                if hasattr(self, 'canvas'):
                                    canvas = self.canvas
                                else:
                                    # Try to find the canvas from the current frame
                                    import inspect
                                    for frame_info in inspect.stack():
                                        frame_locals = frame_info.frame.f_locals
                                        if 'canvas' in frame_locals and hasattr(frame_locals['canvas'], 'mark_entity_modified'):
                                            canvas = frame_locals['canvas']
                                            break
                                        if 'self' in frame_locals and hasattr(frame_locals['self'], 'canvas'):
                                            canvas = frame_locals['self'].canvas
                                            break
                                
                                if canvas and hasattr(canvas, 'mark_entity_modified'):
                                    canvas.mark_entity_modified(entity)
                                
                            except Exception as canvas_error:
                                print(f"⚠️ Could not invalidate canvas cache: {canvas_error}")
                            
                            if should_log:
                                print(f"✅ Updated FCB rotation: {new_angles_value}")
                            return True
                    except (ValueError, IndexError):
                        pass
            
            # Method 2: Dunia Tools format (around line 188)
            angles_elem = entity.xml_element.find("./value[@name='hidAngles']")
            if angles_elem is not None:
                z_elem = angles_elem.find("./z")
                if z_elem is not None:
                    # Format with decimals if value has decimals, otherwise as integer
                    z_elem.text = f"{game_rotation:.2f}" if game_rotation % 1 != 0 else str(int(game_rotation))
                    
                    # Invalidate cache
                    self._invalidate_rotation_cache(entity)
                    
                    if should_log:
                        print(f"✅ Updated Dunia rotation: {game_rotation:.1f}°")
                    return True
                
            # Method 3: Direct rotation field
            rotation_field = entity.xml_element.find("./field[@name='rotation']")
            if rotation_field is not None:
                rotation_field.set('value', f"{new_rotation:.1f}")
                if rotation_field.text is not None:
                    rotation_field.text = f"{new_rotation:.1f}"
                
                # Invalidate cache
                self._invalidate_rotation_cache(entity)
                
                if should_log:
                    print(f"✅ Updated direct rotation: {new_rotation:.1f}°")
                return True
            
            if should_log:
                print(f"⚠️ No rotation field found to update for {entity_name}")
            return False
            
        except Exception as e:
            print(f"⚠️ Exception updating rotation for {getattr(entity, 'name', 'entity')}: {e}")
            return False
    
    def _invalidate_rotation_cache(self, entity):
        """Invalidate cached rotation data for an entity"""
        cache_attrs = ['_gizmo_cached_rotation', '_gizmo_rotation_cache_time', 
                      '_cached_rotation', '_rotation_cache_time']
        for attr in cache_attrs:
            if hasattr(entity, attr):
                delattr(entity, attr)
    
    def _angles_to_binhex(self, x, y, z):
        """Convert angles to BinHex format for FCBConverter"""
        import struct
        
        # Pack as three 32-bit little-endian floats
        binary_data = struct.pack('<fff', float(x), float(y), float(z))
        
        # Convert to hex string (uppercase)
        hex_string = binary_data.hex().upper()
        
        return hex_string
    
    def render_2d(self, painter, canvas):
        """Render rotation gizmo in 2D mode with center square for moving"""
        if self.hidden:
            return
        
        # Use entity coordinates for 2D positioning
        screen_x, screen_y = OpenGLUtils.world_to_screen(self.position.x(), self.position.y(), canvas)
        
        # Check if gizmo is visible
        if (screen_x < -50 or screen_x > canvas.width() + 50 or
            screen_y < -50 or screen_y > canvas.height() + 50):
            return
        
        # Draw hollow blue circle (rotation handle)
        if self.is_dragging:
            painter.setPen(QPen(QColor(255, 255, 0), self.thickness + 1))  # Yellow when dragging
        else:
            painter.setPen(QPen(QColor(0, 120, 255), self.thickness))  # Blue normally
        
        painter.setBrush(QBrush(QColor(0, 0, 0, 0)))  # Transparent fill
        
        painter.drawEllipse(
            int(screen_x - self.radius), 
            int(screen_y - self.radius),
            self.radius * 2, 
            self.radius * 2
        )
        
        # Draw rotation indicator line
        angle_rad = math.radians(self.current_rotation - 90)  # -90 to start from top
        indicator_x = screen_x + (self.radius - 5) * math.cos(angle_rad)
        indicator_y = screen_y + (self.radius - 5) * math.sin(angle_rad)
        
        painter.setPen(QPen(QColor(255, 255, 0), 3))
        painter.drawLine(
            int(screen_x), int(screen_y),
            int(indicator_x), int(indicator_y)
        )
        
        # Draw CENTER SQUARE (move handle)
        square_size = 12  # Size of the center square
        square_half = square_size // 2
        
        # Different colors based on state
        if hasattr(self, 'is_dragging_center') and self.is_dragging_center:
            square_color = QColor(255, 255, 0)  # Yellow when dragging
            square_border = QColor(255, 255, 255)  # White border
        else:
            square_color = QColor(0, 200, 255)  # Cyan/bright blue
            square_border = QColor(255, 255, 255)  # White border
        
        painter.setPen(QPen(square_border, 2))
        painter.setBrush(QBrush(square_color))
        painter.drawRect(
            int(screen_x - square_half),
            int(screen_y - square_half),
            square_size,
            square_size
        )
        
        # Draw angle text with better positioning to avoid overlap
        game_rotation = (360 - self.current_rotation) % 360
        painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
        
        # Position text below the gizmo to avoid entity label overlap
        text_x = int(screen_x - 30)
        text_y = int(screen_y + self.radius + 20)
        
        # Create compact single-line text
        rotation_text = f"Rot: {self.current_rotation:.1f}° (Game: {game_rotation:.1f}°)"
        
        # Measure text for background
        metrics = painter.fontMetrics()
        text_rect = metrics.boundingRect(rotation_text)
        text_width = text_rect.width()
        text_height = text_rect.height()
        
        # Keep text on screen
        canvas_width = canvas.width()
        canvas_height = canvas.height()
        
        if text_x + text_width > canvas_width - 10:
            text_x = canvas_width - text_width - 10
        if text_x < 10:
            text_x = 10
        if text_y + text_height > canvas_height - 10:
            text_y = int(screen_y - self.radius - 10)  # Above gizmo instead
        
        # Draw background for text
        bg_padding = 3
        bg_x = text_x - bg_padding
        bg_y = text_y - metrics.ascent() - bg_padding
        bg_width = text_width + bg_padding * 2
        bg_height = text_height + bg_padding * 2
        
        # Semi-transparent background
        painter.fillRect(bg_x, bg_y, bg_width, bg_height, QColor(0, 0, 0, 180))
        painter.setPen(QPen(QColor(255, 255, 255, 150), 1))
        painter.drawRect(bg_x, bg_y, bg_width, bg_height)
        
        # Draw text
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.drawText(text_x, text_y, rotation_text)

    def is_point_on_circle(self, screen_x, screen_y, canvas):
        """Check if a screen point is on the rotation circle"""
        if self.hidden:
            return False
        
        # Use entity coordinates for 2D mode
        gizmo_screen_x, gizmo_screen_y = OpenGLUtils.world_to_screen(self.position.x(), self.position.y(), canvas)
        
        dx = screen_x - gizmo_screen_x
        dy = screen_y - gizmo_screen_y
        distance = math.sqrt(dx * dx + dy * dy)
        
        tolerance = self.thickness + 8  # More generous tolerance
        return abs(distance - self.radius) <= tolerance

    def is_point_on_center_square(self, screen_x, screen_y, canvas):
        """Check if a screen point is on the center square (move handle)"""
        if self.hidden:
            return False
        
        # Use entity coordinates for 2D mode
        gizmo_screen_x, gizmo_screen_y = OpenGLUtils.world_to_screen(self.position.x(), self.position.y(), canvas)
        
        square_size = 12
        square_half = square_size // 2
        
        # Check if point is within the square bounds
        return (gizmo_screen_x - square_half <= screen_x <= gizmo_screen_x + square_half and
                gizmo_screen_y - square_half <= screen_y <= gizmo_screen_y + square_half)

    def start_rotation(self, screen_x, screen_y, canvas):
        """Start rotation interaction - FIXED to setup group rotation"""
        # Check if clicking on center square first (move handle)
        # In VIEW mode the center square is disabled — only rotation is allowed.
        ih = getattr(canvas, 'input_handler', None)
        edit_mode = getattr(ih, 'edit_mode_2d', True)  # default True = allow if no handler
        if self.is_point_on_center_square(screen_x, screen_y, canvas):
            if not edit_mode:
                print("Center square drag blocked — switch to Edit mode to move entities")
                return False
            self.is_dragging_center = True
            self.drag_start_pos = (screen_x, screen_y)
            # Save positions for undo
            entities = getattr(canvas, 'selected', None) or []
            if not entities and hasattr(canvas, 'selected_entity') and canvas.selected_entity:
                entities = [canvas.selected_entity]
            from .undo_redo import UndoRedoManager
            self._undo_center_before = UndoRedoManager.snapshot_positions(entities)
            print(f"Started center square drag (move mode)")
            return True

        # Check if clicking on rotation circle
        if not self.is_point_on_circle(screen_x, screen_y, canvas):
            return False

        self.is_dragging = True
        self.is_dragging_center = False
        self.drag_start_pos = (screen_x, screen_y)

        # FIXED: Setup group rotation if multiple entities are selected
        if hasattr(canvas, 'selected') and canvas.selected and len(canvas.selected) > 1:
            # GROUP ROTATION: Set up rotation group
            self._rotation_group = canvas.selected
            self._rotation_center = canvas.calculate_group_center(canvas.selected)
            self._last_group_rotation = self.current_rotation
            print(f"🔄 Starting GROUP rotation for {len(canvas.selected)} entities around center {self._rotation_center}")
        else:
            # SINGLE ENTITY ROTATION: Clear group rotation state
            self._rotation_group = None
            self._rotation_center = None
            if hasattr(self, '_last_group_rotation'):
                delattr(self, '_last_group_rotation')
            print(f"🔄 Starting SINGLE rotation")

        # Save rotation+position state for undo
        entities = getattr(canvas, 'selected', None) or []
        if not entities and hasattr(canvas, 'selected_entity') and canvas.selected_entity:
            entities = [canvas.selected_entity]
        from .undo_redo import UndoRedoManager
        self._undo_rotate_before = UndoRedoManager.snapshot_rotations(entities, canvas)

        # Calculate initial angle from gizmo center
        gizmo_screen_x, gizmo_screen_y = OpenGLUtils.world_to_screen(self.position.x(), self.position.y(), canvas)
        dx = screen_x - gizmo_screen_x
        dy = screen_y - gizmo_screen_y
        self.drag_start_angle = math.degrees(math.atan2(dy, dx))

        self.initial_rotation = self.current_rotation
        print(f"Started rotation: initial={self.initial_rotation:.1f}°, start_angle={self.drag_start_angle:.1f}°")
        return True

    def update_rotation(self, screen_x, screen_y, canvas, entity):
        """Update rotation during drag - SUPPORTS GROUP ROTATION AND CENTER DRAG (MOVE)"""
        if not self.is_dragging and not self.is_dragging_center:
            return
        
        # Handle center square dragging (MOVE mode)
        if self.is_dragging_center:
            # Calculate movement delta
            delta_x = screen_x - self.drag_start_pos[0]
            delta_y = screen_y - self.drag_start_pos[1]
            
            # Convert screen delta to world delta
            world_start = OpenGLUtils.screen_to_world(self.drag_start_pos[0], self.drag_start_pos[1], canvas)
            world_current = OpenGLUtils.screen_to_world(screen_x, screen_y, canvas)
            
            world_delta_x = world_current[0] - world_start[0]
            world_delta_y = world_current[1] - world_start[1]
            
            # Get all selected entities
            entities_to_move = getattr(canvas, 'selected', [])
            if not entities_to_move and hasattr(canvas, 'selected_entity') and canvas.selected_entity:
                entities_to_move = [canvas.selected_entity]
            
            if entities_to_move:
                # Move all selected entities
                for ent in entities_to_move:
                    if hasattr(ent, 'x') and hasattr(ent, 'y'):
                        ent.x += world_delta_x
                        ent.y += world_delta_y

                        # Shift hidShapePoints so the shape polygon follows the entity
                        if hasattr(canvas, 'input_handler'):
                            canvas.input_handler._shift_shape_points(ent, world_delta_x, world_delta_y)

                        # Update XML
                        if hasattr(canvas, 'update_entity_xml'):
                            canvas.update_entity_xml(ent)

                        # Mark as modified
                        if hasattr(canvas, 'mark_entity_modified'):
                            canvas.mark_entity_modified(ent)

                        # Sync managers.xml vPos for this entity
                        if hasattr(canvas, '_update_managers_vpos_for_entity'):
                            canvas._update_managers_vpos_for_entity(ent)
                
                # Move the gizmo position as well
                self.position.setX(self.position.x() + world_delta_x)
                self.position.setY(self.position.y() + world_delta_y)

                # Update drag start position for next delta calculation
                self.drag_start_pos = (screen_x, screen_y)

                # Live-update stats panel and entity browser
                primary = canvas.selected_entity if hasattr(canvas, 'selected_entity') else None
                if primary is not None:
                    _main = canvas
                    while _main.parent():
                        _main = _main.parent()
                    if hasattr(_main, 'on_entity_position_updated'):
                        _main.on_entity_position_updated(primary, (primary.x, primary.y, primary.z))

                # Log occasionally
                current_time = time.time()
                if current_time - getattr(self, '_last_move_log_time', 0) > 0.5:
                    print(f"📦 Moving {len(entities_to_move)} entities by ({world_delta_x:.1f}, {world_delta_y:.1f})")
                    self._last_move_log_time = current_time
            
            return
        
        # Handle rotation (existing code)
        # Check if we're rotating a group
        is_group_rotation = (hasattr(self, '_rotation_group') and 
                            self._rotation_group and
                            len(self._rotation_group) > 1)
        
        try:
            # Calculate current angle from gizmo center
            gizmo_screen_x, gizmo_screen_y = OpenGLUtils.world_to_screen(
                self.position.x(), self.position.y(), canvas)
            dx = screen_x - gizmo_screen_x
            dy = screen_y - gizmo_screen_y
            current_angle = math.degrees(math.atan2(dy, dx))
            
            # Calculate rotation delta from drag start
            angle_delta = current_angle - self.drag_start_angle
            
            # Update current rotation display
            new_rotation = (self.initial_rotation + angle_delta) % 360
            
            if is_group_rotation:
                # GROUP ROTATION: Rotate all entities around common center
                rotation_group = self._rotation_group
                rotation_center = self._rotation_center
                
                # Calculate incremental rotation since last update
                if not hasattr(self, '_last_group_rotation'):
                    self._last_group_rotation = self.initial_rotation
                
                incremental_rotation = new_rotation - self._last_group_rotation
                
                # Normalize the incremental rotation to avoid wrap-around issues
                if incremental_rotation > 180:
                    incremental_rotation -= 360
                elif incremental_rotation < -180:
                    incremental_rotation += 360
                
                # Only apply if rotation changed significantly (avoid floating point spam)
                if abs(incremental_rotation) > 0.1:
                    # FIXED: Invert rotation direction for group rotation to match single entity behavior
                    # Negate the incremental rotation so clockwise mouse movement = clockwise rotation
                    canvas.rotate_group_around_center(
                        rotation_group, 
                        -incremental_rotation,  # FIXED: Negated to reverse direction
                        rotation_center
                    )
                    
                    # CRITICAL: Invalidate entity renderer cache for all rotated entities
                    if hasattr(canvas, 'entity_renderer'):
                        for ent in rotation_group:
                            canvas.entity_renderer.invalidate_entity_cache(ent)
                    
                    # Update tracking
                    self._last_group_rotation = new_rotation
                    self.current_rotation = new_rotation
                    
                    # Log occasionally
                    current_time = time.time()
                    if current_time - getattr(self, '_last_drag_log_time', 0) > 0.5:
                        print(f"🔄 Group rotation: {new_rotation:.1f}° (delta: {-incremental_rotation:+.1f}°, {len(rotation_group)} entities)")
                        self._last_drag_log_time = current_time
            else:
                # SINGLE ENTITY ROTATION: Apply absolute rotation
                self.current_rotation = new_rotation
                
                if self.update_entity_rotation(entity, self.current_rotation):
                    # CRITICAL: Invalidate entity renderer cache
                    if hasattr(canvas, 'entity_renderer'):
                        canvas.entity_renderer.invalidate_entity_cache(entity)
                    
                    current_time = time.time()
                    if current_time - getattr(self, '_last_drag_log_time', 0) > 0.5:
                        print(f"🔄 Single rotation: {self.current_rotation:.1f}°")
                        self._last_drag_log_time = current_time
            
        except Exception as e:
            print(f"Error updating rotation: {e}")
            import traceback
            traceback.print_exc()

    def end_rotation(self, canvas=None):
        """End rotation interaction - CLEAN UP GROUP ROTATION STATE"""
        if self.is_dragging:
            print(f"✅ Rotation completed: {self.current_rotation:.1f}°")
            self.is_dragging = False
            
            # Clean up group rotation state
            if hasattr(self, '_rotation_group'):
                delattr(self, '_rotation_group')
            if hasattr(self, '_rotation_center'):
                delattr(self, '_rotation_center')
            if hasattr(self, '_last_applied_rotation'):
                delattr(self, '_last_applied_rotation')
            if hasattr(self, '_last_group_rotation'):
                delattr(self, '_last_group_rotation')
            
            # Force cache invalidation
            if hasattr(self, '_last_rotated_entity'):
                entity = self._last_rotated_entity
                if hasattr(entity, '_cached_style_2d'):
                    delattr(entity, '_cached_style_2d')
                delattr(self, '_last_rotated_entity')
        elif self.is_dragging_center:
            print(f"✅ Move completed")
            self.is_dragging_center = False
            # Rebuild By Sector tree if entity crossed a sector boundary
            if canvas is not None and getattr(canvas, 'unified_mode', False):
                entity = canvas.selected_entity if hasattr(canvas, 'selected_entity') else None
                if entity is not None:
                    cur_sid = int(entity.y // 64) * 16 + int(entity.x // 64)
                    if cur_sid != getattr(entity, 'source_sector_id', cur_sid):
                        _main = canvas
                        while _main.parent():
                            _main = _main.parent()
                        if hasattr(_main, 'update_entity_tree'):
                            _main.update_entity_tree()
        else:
            self.is_dragging = False
            self.is_dragging_center = False

class GizmoRenderer:
    """Handles rendering of gizmos and manipulation tools - 2D ONLY"""
    
    def __init__(self):
        self.rotation_gizmo = RotationGizmo()
        print("GizmoRenderer initialized (2D only)")
    
    def render_rotation_gizmo_2d(self, painter, canvas):
        """Render rotation gizmo in 2D mode - handles both single and multi-selection"""
        # Show gizmo if: 1) entity is selected, OR 2) multiple entities are selected
        should_show = False
        
        if hasattr(canvas, 'selected_entity') and canvas.selected_entity:
            should_show = True
        elif hasattr(canvas, 'selected') and canvas.selected and len(canvas.selected) > 0:
            should_show = True
        
        if should_show and not self.rotation_gizmo.hidden:
            self.rotation_gizmo.render_2d(painter, canvas)

    def handle_gizmo_mouse_press(self, event, canvas):
        """Handle mouse press for gizmo interactions"""
        if (hasattr(canvas, 'selected_entity') and canvas.selected_entity and 
            self.rotation_gizmo.start_rotation(event.position().x(), event.position().y(), canvas)):
            print("Started gizmo rotation interaction")
            return True
        return False

    def handle_gizmo_mouse_move(self, event, canvas):
        """Handle mouse move for gizmo interactions - FIXED to include center drag"""
        # FIXED: Check BOTH is_dragging (rotation) AND is_dragging_center (move)
        if ((self.rotation_gizmo.is_dragging or self.rotation_gizmo.is_dragging_center) and 
            hasattr(canvas, 'selected_entity') and canvas.selected_entity):
            self.rotation_gizmo.update_rotation(
                event.position().x(), event.position().y(), canvas, canvas.selected_entity
            )
            return True
        return False

    def handle_gizmo_mouse_release(self, event, canvas):
        """Handle mouse release for gizmo interactions - FIXED to include center drag"""
        # FIXED: Check BOTH is_dragging (rotation) AND is_dragging_center (move)
        was_rotating = self.rotation_gizmo.is_dragging
        was_moving_center = self.rotation_gizmo.is_dragging_center
        if was_rotating or was_moving_center:
            self.rotation_gizmo.end_rotation(canvas)
            print("Ended gizmo interaction")
            # Push undo command
            if hasattr(canvas, 'undo_redo'):
                from .undo_redo import UndoRedoManager, MoveCommand, RotateCommand
                if was_rotating:
                    before = getattr(self.rotation_gizmo, '_undo_rotate_before', None)
                    if before:
                        entities = [item[0] for item in before]
                        after = UndoRedoManager.snapshot_rotations(entities, canvas)
                        canvas.undo_redo.push(RotateCommand(before, after))
                        self.rotation_gizmo._undo_rotate_before = None
                elif was_moving_center:
                    before = getattr(self.rotation_gizmo, '_undo_center_before', None)
                    if before:
                        entities = [item[0] for item in before]
                        after = UndoRedoManager.snapshot_positions(entities)
                        canvas.undo_redo.push(MoveCommand(before, after))
                        self.rotation_gizmo._undo_center_before = None
            return True
        return False

    def is_gizmo_active(self):
        """Check if any gizmo is currently being interacted with - FIXED"""
        # FIXED: Check BOTH is_dragging (rotation) AND is_dragging_center (move)
        return self.rotation_gizmo.is_dragging or self.rotation_gizmo.is_dragging_center
    
    def update_gizmo_for_entity(self, entity):
        """Update gizmo position when entity is selected"""
        print(f"🎯 update_gizmo_for_entity called with: {getattr(entity, 'name', 'unknown')}")
        print(f"   Entity coords: ({getattr(entity, 'x', 'N/A')}, {getattr(entity, 'y', 'N/A')}, {getattr(entity, 'z', 'N/A')})")
        self.rotation_gizmo.move_to_entity(entity)
        print(f"   Gizmo hidden after move: {self.rotation_gizmo.hidden}")
        print(f"   Gizmo position: ({self.rotation_gizmo.position.x()}, {self.rotation_gizmo.position.y()}, {self.rotation_gizmo.position.z()})")

    def hide_gizmo(self):
        """Hide all gizmos"""
        self.rotation_gizmo.hidden = True
    