"""Input handler for mouse and keyboard interactions - 2D ONLY VERSION"""

import math
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMenu
from .opengl_utils import OpenGLUtils
from PyQt6.QtGui import QVector3D

class InputHandler:
    """Handles mouse and keyboard input for the canvas - 2D ONLY"""
    
    def __init__(self, canvas):
        self.canvas = canvas
        
        # Mouse state
        self.dragging = False
        self.panning = False
        self.drag_start_x = 0
        self.drag_start_y = 0
        
        # Selection box state
        self.selection_box_active = False
        self.selection_box_start_x = 0
        self.selection_box_start_y = 0
        self.selection_box_end_x = 0
        self.selection_box_end_y = 0
        
        # Modifier key states
        self.shift_is_pressed = False

        # 2D edit mode — False = View (select/rotate only), True = Edit (move enabled)
        self.edit_mode_2d = False

        # 3D edit mode — False = View (camera only), True = Edit (gizmo + selection active)
        self.edit_mode_3d = False

        # Shape point selection/drag state
        self.selected_shape_point = None   # (entity, point_index) or None
        self.dragging_shape_point = False
        self._shape_drag_anchor = None     # (world_x, world_y) updated each frame
        self._shape_drag_before = None     # snapshot dict for undo/redo

        print("InputHandler initialized - 2D ONLY")

    def handle_mouse_press(self, event):
        """Handle mouse press events - 2D ONLY"""
        print(f"Mouse press: button={event.button()}, pos=({event.position().x():.1f}, {event.position().y():.1f})")

        try:
            # Shape point handles have absolute priority — check BEFORE the gizmo so that
            # pt 0 (which sits at the entity/gizmo-center position) can be grabbed.
            if event.button() == Qt.MouseButton.LeftButton and self.edit_mode_2d:
                mouse_x = event.position().x()
                mouse_y = event.position().y()
                if self._check_shape_btn_click(mouse_x, mouse_y):
                    return
                hit_entity, hit_idx = self._find_shape_point_at(mouse_x, mouse_y)
                if hit_entity is not None:
                    if hasattr(self.canvas, 'screen_to_world'):
                        level_x, level_y = self.canvas.screen_to_world(mouse_x, mouse_y)
                    else:
                        level_x, level_y = mouse_x, mouse_y
                    if hit_entity is not self.canvas.selected_entity:
                        new_group = (self.canvas.select_entity_with_children(hit_entity)
                                     if hasattr(self.canvas, 'select_entity_with_children')
                                     else [hit_entity])
                        self.canvas.selected_entity = hit_entity
                        self.canvas.selected = new_group
                        if hasattr(self.canvas, 'gizmo_renderer'):
                            self.canvas.gizmo_renderer.update_gizmo_for_entity(hit_entity)
                        if hasattr(self.canvas, 'entitySelected'):
                            self.canvas.entitySelected.emit(hit_entity)
                    self._shape_drag_before = self._snapshot_shape_points(hit_entity)
                    self.selected_shape_point = (hit_entity, hit_idx)
                    self.dragging_shape_point = True
                    self._shape_drag_anchor = (level_x, level_y)
                    self.canvas.update()
                    return

            # CRITICAL: Check if we're clicking on a gizmo FIRST (highest priority)
            if hasattr(self.canvas, 'gizmo_renderer'):
                if self.canvas.gizmo_renderer.handle_gizmo_mouse_press(event, self.canvas):
                    print("Started gizmo interaction")
                    self.canvas.update()
                    return  # Gizmo interaction started, don't do other mouse handling

            # Handle 2D mouse press
            self.handle_mouse_press_2d(event)
            
        except Exception as e:
            print(f"Error in handle_mouse_press: {e}")
            import traceback
            traceback.print_exc()

    def handle_mouse_move(self, event):
        """Handle mouse move events - 2D ONLY"""
        try:
            # CRITICAL: Check if we're dragging a gizmo FIRST (highest priority)
            if hasattr(self.canvas, 'gizmo_renderer'):
                gizmo = self.canvas.gizmo_renderer.rotation_gizmo
                # In VIEW mode block center-drag (entity move) but allow rotation drag
                if not self.edit_mode_2d and getattr(gizmo, 'is_dragging_center', False):
                    # Cancel the center drag so the entity doesn't move
                    gizmo.is_dragging_center = False
                    return

                if self.canvas.gizmo_renderer.handle_gizmo_mouse_move(event, self.canvas):
                    # gizmo_renderer already called _update_managers_vpos_for_entity per entity.
                    # Just invalidate caches and auto-save the primary entity.
                    if hasattr(self.canvas, 'selected_entity') and self.canvas.selected_entity:
                        self.canvas.mark_entity_modified(self.canvas.selected_entity)
                        self._auto_save_entity_changes(self.canvas.selected_entity)
                    self.canvas.update()  # Update immediately for smooth gizmo interaction
                    return  # Gizmo is being dragged, don't do other mouse handling

            # Handle 2D mouse move
            self.handle_mouse_move_2d(event)
            
        except Exception as e:
            print(f"Error in handle_mouse_move: {e}")

    def handle_mouse_release(self, event):
        """Handle mouse release events - 2D ONLY"""
        print(f"Mouse release: button={event.button()}")

        try:
            # CRITICAL: Check if we're releasing a gizmo FIRST (highest priority)
            if hasattr(self.canvas, 'gizmo_renderer'):
                if self.canvas.gizmo_renderer.handle_gizmo_mouse_release(event, self.canvas):
                    print("Ended gizmo interaction")
                    # Sync 3D gizmo after 2D gizmo center-square move
                    if hasattr(self.canvas, 'gizmo_3d') and self.canvas.selected_entity:
                        self.canvas.gizmo_3d.sync_position()
                    # Write managers.xml if vPos was updated during this drag
                    if hasattr(self.canvas, '_flush_managers_xml'):
                        self.canvas._flush_managers_xml()
                    self.canvas.update()
                    return  # Gizmo interaction ended, don't do other mouse handling

            # Handle 2D mouse release
            self.handle_mouse_release_2d(event)

        except Exception as e:
            print(f"Error in handle_mouse_release: {e}")

    def handle_mouse_press_2d(self, event):
        """Handle mouse press in 2D mode with gizmo integration"""
        if event.button() == Qt.MouseButton.LeftButton:
            # CRITICAL: Check if we're clicking on a gizmo FIRST (before anything else)
            if hasattr(self.canvas, 'gizmo_renderer'):
                if self.canvas.gizmo_renderer.handle_gizmo_mouse_press(event, self.canvas):
                    # IMPORTANT: Set up group rotation for ALL selected entities
                    if hasattr(self.canvas, 'selected') and self.canvas.selected:
                        # Set up group rotation if more than one entity
                        if len(self.canvas.selected) > 1:
                            self.canvas.gizmo_renderer.rotation_gizmo._rotation_group = self.canvas.selected
                            self.canvas.gizmo_renderer.rotation_gizmo._rotation_center = self.canvas.calculate_group_center(self.canvas.selected)
                            print(f"🔄 Starting group rotation for {len(self.canvas.selected)} entities")
                        else:
                            # Single entity - clear group rotation
                            self.canvas.gizmo_renderer.rotation_gizmo._rotation_group = None
                            self.canvas.gizmo_renderer.rotation_gizmo._rotation_center = None
                            print("Started single entity rotation")
                    self.canvas.update()
                    return  # Gizmo interaction started, don't do other mouse handling
            
            # Get editor/canvas coordinates
            mouse_x = event.position().x()
            mouse_y = event.position().y()

            # Convert to level/world coordinates
            if hasattr(self.canvas, 'screen_to_world'):
                level_x, level_y = self.canvas.screen_to_world(mouse_x, mouse_y)
            else:
                level_x, level_y = mouse_x, mouse_y

            print(f"Mouse click at level coords: ({level_x:.1f}, {level_y:.1f})")

            # Shape point handle hit-test (edit mode only, selected entity only)
            if self.edit_mode_2d and self.canvas.selected_entity:
                hit_idx = self._get_shape_point_at(mouse_x, mouse_y, self.canvas.selected_entity)
                if hit_idx is not None:
                    self._shape_drag_before = self._snapshot_shape_points(self.canvas.selected_entity)
                    self.selected_shape_point = (self.canvas.selected_entity, hit_idx)
                    self.dragging_shape_point = True
                    self._shape_drag_anchor = (level_x, level_y)
                    self.canvas.update()
                    return

            # Check if an entity was clicked
            entity = self.get_entity_at_position(mouse_x, mouse_y)

            ctrl_held = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)

            if entity:
                # Resolve entity + its linked children as a group
                if hasattr(self.canvas, 'select_entity_with_children'):
                    new_group = self.canvas.select_entity_with_children(entity)
                else:
                    new_group = [entity]

                if ctrl_held:
                    # --- CTRL+click: add to / remove from existing selection ---
                    existing = list(self.canvas.selected) if hasattr(self.canvas, 'selected') and self.canvas.selected else []
                    existing_ids = {id(e) for e in existing}

                    if id(entity) in existing_ids:
                        # Entity already selected — remove the whole group
                        remove_ids = {id(e) for e in new_group}
                        existing = [e for e in existing if id(e) not in remove_ids]
                    else:
                        # Entity not yet selected — append the group (no duplicates)
                        for e in new_group:
                            if id(e) not in existing_ids:
                                existing.append(e)
                                existing_ids.add(id(e))

                    self.canvas.selected = existing
                    self.canvas.selected_entity = existing[0] if existing else None

                    # No drag on CTRL+click — just a selection toggle
                    self.dragging = False
                    self._drag_before_positions = None
                    print(f"CTRL+click: selection now {len(existing)} entities")
                else:
                    # --- Normal click: replace selection ---
                    self.canvas.selected_entity = entity
                    self.canvas.selected = new_group

                    # Only allow dragging (moving) in Edit mode
                    if self.edit_mode_2d:
                        self.dragging = True
                        from .undo_redo import UndoRedoManager
                        self._drag_before_positions = UndoRedoManager.snapshot_positions(new_group)
                    else:
                        self._drag_before_positions = None
                    print(f"Selected entity: {getattr(entity, 'name', 'unknown')} ({len(new_group)} total)")

                # Update gizmo to centre of current selection
                current_selection = self.canvas.selected
                if hasattr(self.canvas, 'gizmo_renderer'):
                    if len(current_selection) > 1:
                        center = self.canvas.calculate_group_center(current_selection)
                        virtual_entity = type('VirtualEntity', (), {
                            'x': center[0],
                            'y': center[1],
                            'z': center[2],
                            'name': f'Group ({len(current_selection)} entities)'
                        })()
                        self.canvas.gizmo_renderer.update_gizmo_for_entity(virtual_entity)
                    elif current_selection:
                        self.canvas.gizmo_renderer.update_gizmo_for_entity(current_selection[0])
                    else:
                        self.canvas.gizmo_renderer.hide_gizmo()

                # Emit selection signal (use primary entity)
                if hasattr(self.canvas, 'entitySelected') and self.canvas.selected_entity:
                    self.canvas.entitySelected.emit(self.canvas.selected_entity)

            else:
                # Start selection box on empty space
                self.selection_box_active = True
                self.selection_box_start_x = mouse_x
                self.selection_box_start_y = mouse_y
                self.selection_box_end_x = mouse_x
                self.selection_box_end_y = mouse_y
                print("Started selection box")

                # DON'T clear selection when STARTING a selection box
                # Selection will be cleared/updated when the box completes in _complete_selection_box
                # This allows the selection box to work properly
                                
            self.drag_start_x = mouse_x
            self.drag_start_y = mouse_y
            self.canvas.update()

        elif event.button() == Qt.MouseButton.MiddleButton:
            # Middle-click starts panning
            self.panning = True
            self.drag_start_x = event.position().x()
            self.drag_start_y = event.position().y()
            self.canvas.setCursor(Qt.CursorShape.ClosedHandCursor)

    def handle_mouse_move_2d(self, event):
        """Handle mouse move in 2D mode with entity dragging and gizmo updates"""
        current_x = event.position().x()
        current_y = event.position().y()
        
        if self.selection_box_active:
            # Update selection box end position
            self.selection_box_end_x = current_x
            self.selection_box_end_y = current_y
            self.canvas.update()
            
        elif self.dragging_shape_point and self.selected_shape_point:
            world_x, world_y = OpenGLUtils.screen_to_world(current_x, current_y, self.canvas)
            ax, ay = self._shape_drag_anchor
            dx = world_x - ax
            dy = world_y - ay
            self._shape_drag_anchor = (world_x, world_y)

            entity, pt_idx = self.selected_shape_point
            if pt_idx == 0:
                # First point: move entity + all shape points together
                self._shift_shape_points(entity, dx, dy)
                entity.x += dx
                entity.y += dy
                self.canvas.mark_entity_modified(entity)
                self._update_entity_xml(entity)
                # Keep the gizmo centred on the entity's new position
                if hasattr(self.canvas, 'gizmo_renderer'):
                    self.canvas.gizmo_renderer.update_gizmo_for_entity(entity)
                if hasattr(self.canvas, '_update_managers_vpos_for_entity'):
                    self.canvas._update_managers_vpos_for_entity(entity)
                if hasattr(self.canvas, 'invalidate_position_cache'):
                    self.canvas.invalidate_position_cache()
            else:
                # Other points: move just that point
                self._move_shape_point(entity, pt_idx, dx, dy)
            self.canvas.update()

        elif self.dragging and hasattr(self.canvas, 'selected_entity') and self.canvas.selected_entity:
            # Move entity/entities
            world_x, world_y = OpenGLUtils.screen_to_world(current_x, current_y, self.canvas)
            
            # Get all selected entities (single or multiple)
            entities_to_move = self.canvas.selected if hasattr(self.canvas, 'selected') and self.canvas.selected else [self.canvas.selected_entity]
            
            # Calculate delta from the primary selected entity
            old_x, old_y = self.canvas.selected_entity.x, self.canvas.selected_entity.y
            delta_x = world_x - old_x
            delta_y = world_y - old_y
            
            # Move all selected entities by the same delta
            _snap = (getattr(self.canvas, 'terrain_snap_enabled', False)
                     and getattr(self.canvas, 'mode', 0) == 1)
            _height_fn = self.canvas.get_terrain_height_at if (_snap and hasattr(self.canvas, 'get_terrain_height_at')) else None
            for entity in entities_to_move:
                entity.x += delta_x
                entity.y += delta_y
                if _height_fn is not None:
                    entity.z = _height_fn(entity.x, entity.y)
                self._shift_shape_points(entity, delta_x, delta_y)

                # CRITICAL: Invalidate caches when entity position changes
                self.canvas.mark_entity_modified(entity)

                # Update XML
                self._update_entity_xml(entity)

                # Sync managers.xml vPos for this entity if it is referenced there
                if hasattr(self.canvas, '_update_managers_vpos_for_entity'):
                    self.canvas._update_managers_vpos_for_entity(entity)
            
            # CRITICAL: Update gizmo position when entities move
            if hasattr(self.canvas, 'gizmo_renderer'):
                if len(entities_to_move) > 1:
                    # Multiple entities - update gizmo to new group center
                    center = self.canvas.calculate_group_center(entities_to_move)
                    from PyQt6.QtCore import QObject
                    virtual_entity = type('VirtualEntity', (), {
                        'x': center[0],
                        'y': center[1],
                        'z': center[2],
                        'name': f'Group ({len(entities_to_move)} entities)'
                    })()
                    self.canvas.gizmo_renderer.update_gizmo_for_entity(virtual_entity)
                else:
                    # Single entity - update normally
                    self.canvas.gizmo_renderer.update_gizmo_for_entity(self.canvas.selected_entity)
            
            # Invalidate 2D position cache so culling uses the updated coordinates
            if hasattr(self.canvas, 'invalidate_position_cache'):
                self.canvas.invalidate_position_cache()

            # Auto-save (just once for the primary entity)
            self._auto_save_entity_changes(self.canvas.selected_entity)

            # Live-update stats panel and entity browser directly (signal alone is unreliable during drag)
            e = self.canvas.selected_entity
            if e is not None:
                _main = self.canvas
                while _main.parent():
                    _main = _main.parent()
                if hasattr(_main, 'on_entity_position_updated'):
                    _main.on_entity_position_updated(e, (e.x, e.y, e.z))


            self.canvas.update()
            
        elif self.panning:
            # Handle panning
            dx = current_x - self.drag_start_x
            dy = current_y - self.drag_start_y

            self.canvas.camera_controller.offset_x += dx
            # Y is flipped in world_to_screen (screen_y = height - (world_y*scale + offset_y))
            # so dragging down (dy > 0) must subtract from offset_y to move the view down.
            self.canvas.camera_controller.offset_y -= dy
            self.canvas.offset_x = self.canvas.camera_controller.offset_x
            self.canvas.offset_y = self.canvas.camera_controller.offset_y

            self.drag_start_x = current_x
            self.drag_start_y = current_y
            self.canvas.update()
        else:
            # Update cursor and status for hover
            self._update_cursor_2d(current_x, current_y)
            self._update_status_bar_2d(current_x, current_y)

    def handle_mouse_release_2d(self, event):
        """Handle mouse release in 2D mode"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.selection_box_active:
                # Complete selection box and select entities within it
                self._complete_selection_box()
                self.selection_box_active = False
                print("Ended selection box")
                
            if self.dragging:
                print("Ended entity dragging")
                # Sync 3D gizmo to final drag position
                if hasattr(self.canvas, 'gizmo_3d') and self.canvas.selected_entity:
                    self.canvas.gizmo_3d.sync_position()
                # Ensure 2D position cache reflects the final drag position
                if hasattr(self.canvas, 'invalidate_position_cache'):
                    self.canvas.invalidate_position_cache()
                # Push MoveCommand for undo/redo
                before = getattr(self, '_drag_before_positions', None)
                if before and hasattr(self.canvas, 'undo_redo'):
                    from .undo_redo import UndoRedoManager, MoveCommand
                    entities = [item[0] for item in before]
                    after = UndoRedoManager.snapshot_positions(entities)
                    self.canvas.undo_redo.push(MoveCommand(before, after))
                self._drag_before_positions = None
                # Write managers.xml if vPos was updated during this drag
                if hasattr(self.canvas, '_flush_managers_xml'):
                    self.canvas._flush_managers_xml()
                # In unified mode, refresh the By Sector tree if any entity crossed a sector boundary
                if getattr(self.canvas, 'unified_mode', False):
                    moved_sectors = False
                    for entity in (self.canvas.selected if self.canvas.selected else
                                   ([self.canvas.selected_entity] if self.canvas.selected_entity else [])):
                        cur_sid = int(entity.y // 64) * 16 + int(entity.x // 64)
                        if cur_sid != getattr(entity, 'source_sector_id', cur_sid):
                            moved_sectors = True
                            break
                    if moved_sectors:
                        main_win = self.canvas
                        while main_win.parent():
                            main_win = main_win.parent()
                        if hasattr(main_win, 'update_entity_tree'):
                            main_win.update_entity_tree()

                # Mark final + source sectors dirty once (skipped per-frame during drag)
                if getattr(self.canvas, 'unified_mode', False):
                    for entity in (self.canvas.selected if self.canvas.selected else
                                   ([self.canvas.selected_entity] if self.canvas.selected_entity else [])):
                        self.canvas.mark_sector_dirty(entity)

            if self.panning:
                print("Ended left-button panning")

            if self.dragging_shape_point and self.selected_shape_point:
                entity, pt_idx = self.selected_shape_point
                # Sync hidPos/hidPos_precise then flush to disk.
                # For pt0: entity.x/y already accumulated during drag; _update_entity_xml
                #          writes them to the field plus any fallback format.
                # For pt1+: entity.x/y unchanged; still call so the save path is uniform.
                self._update_entity_xml(entity)
                self.canvas.mark_entity_modified(entity)
                self._auto_save_entity_changes(entity)
                before = self._shape_drag_before
                if before is not None and hasattr(self.canvas, 'undo_redo'):
                    from .undo_redo import ShapePointCommand
                    after_snap = self._snapshot_shape_points(entity)
                    self.canvas.undo_redo.push(ShapePointCommand(before, after_snap))
                self._shape_drag_before = None

            self.dragging = False
            self.dragging_shape_point = False
            self._shape_drag_anchor = None
            self.panning = False
            self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
            
        elif event.button() == Qt.MouseButton.MiddleButton:
            if self.panning:
                print("Ended middle-button panning")
            self.panning = False
            self.canvas.setCursor(Qt.CursorShape.ArrowCursor)

        elif event.button() == Qt.MouseButton.RightButton:
            # Show context menu
            if hasattr(self.canvas, 'showContextMenu'):
                self.canvas.showContextMenu(event)
            elif hasattr(self.canvas.parent(), 'show_enhanced_context_menu'):
                self.canvas.parent().show_enhanced_context_menu(event)

    def _complete_selection_box(self):
        """Select all entities within the selection box"""
        if not hasattr(self.canvas, 'entities') or not self.canvas.entities:
            return
        
        # Get box bounds in screen coordinates
        min_x = min(self.selection_box_start_x, self.selection_box_end_x)
        max_x = max(self.selection_box_start_x, self.selection_box_end_x)
        min_y = min(self.selection_box_start_y, self.selection_box_end_y)
        max_y = max(self.selection_box_start_y, self.selection_box_end_y)
        
        # Find entities within box
        selected_entities = []
        for entity in self.canvas.entities:
            # Skip entities not on current map (bypass in unified mode)
            if (not getattr(self.canvas, 'unified_mode', False) and
                    hasattr(self.canvas, 'current_map') and self.canvas.current_map is not None and
                    getattr(entity, 'map_name', None) != self.canvas.current_map.name):
                continue
                
            if not hasattr(entity, 'x') or not hasattr(entity, 'y'):
                continue
            
            # Convert entity position to screen coordinates
            screen_x, screen_y = OpenGLUtils.world_to_screen(entity.x, entity.y, self.canvas)
            
            # Check if entity is within selection box
            if min_x <= screen_x <= max_x and min_y <= screen_y <= max_y:
                selected_entities.append(entity)
        
        if selected_entities:
            # Expand selection to include children and related entities
            # Use dictionary to avoid duplicates (entities aren't hashable)
            expanded_selection = {}
            for entity in selected_entities:
                if hasattr(self.canvas, 'select_entity_with_children'):
                    related_entities = self.canvas.select_entity_with_children(entity)
                    for related in related_entities:
                        entity_id = id(related)
                        if entity_id not in expanded_selection:
                            expanded_selection[entity_id] = related
                else:
                    entity_id = id(entity)
                    if entity_id not in expanded_selection:
                        expanded_selection[entity_id] = entity
            
            # Convert back to list
            final_selection = list(expanded_selection.values())
            
            self.canvas.selected = final_selection
            
            if len(final_selection) == 1:
                # Single entity selected
                self.canvas.selected_entity = final_selection[0]
                # Update gizmo for single selection
                if hasattr(self.canvas, 'gizmo_renderer'):
                    self.canvas.gizmo_renderer.update_gizmo_for_entity(final_selection[0])
                    print(f"📍 Gizmo positioned at single entity: {final_selection[0].name}")
                # Emit selection signal
                if hasattr(self.canvas, 'entitySelected'):
                    self.canvas.entitySelected.emit(final_selection[0])
            else:
                # Multiple entities selected
                self.canvas.selected_entity = final_selection[0]  # Primary entity is first one
                
                # Show gizmo at the CENTER of all selected entities
                if hasattr(self.canvas, 'gizmo_renderer'):
                    # Calculate center manually here with proper validation
                    valid_entities = [e for e in final_selection if hasattr(e, 'x') and hasattr(e, 'y') and hasattr(e, 'z')]
                    
                    if valid_entities:
                        center_x = sum(e.x for e in valid_entities) / len(valid_entities)
                        center_y = sum(e.y for e in valid_entities) / len(valid_entities)
                        center_z = sum(e.z for e in valid_entities) / len(valid_entities)
                        
                        print(f"📍 Calculating group center from {len(valid_entities)} valid entities")
                        print(f"   Center: ({center_x:.1f}, {center_y:.1f}, {center_z:.1f})")
                        
                        # Create a virtual entity at the group center for gizmo positioning
                        virtual_entity = type('VirtualEntity', (), {
                            'x': center_x,
                            'y': center_y,
                            'z': center_z,
                            'name': f'Group ({len(final_selection)} entities)'
                        })()
                        
                        # Update gizmo position
                        self.canvas.gizmo_renderer.update_gizmo_for_entity(virtual_entity)
                        
                        # Explicitly ensure gizmo is visible
                        if hasattr(self.canvas.gizmo_renderer, 'rotation_gizmo'):
                            self.canvas.gizmo_renderer.rotation_gizmo.hidden = False
                        
                        print(f"✅ Gizmo shown at group center for {len(final_selection)} entities")
                    else:
                        print(f"⚠️ No valid entities with x,y,z coordinates in selection")
                
                # Emit signal for primary entity so editor/preview update
                if hasattr(self.canvas, 'entitySelected'):
                    self.canvas.entitySelected.emit(final_selection[0])
                print(f"📍 Multi-selection: emitted entitySelected for primary entity, {len(final_selection)} total selected")
            
            print(f"Selected {len(final_selection)} entities with selection box (including {len(final_selection) - len(selected_entities)} related)")
        else:
            # Empty selection box - clear selection
            if not (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier):
                self.canvas.selected_entity = None
                self.canvas.selected = []
                self.canvas._managers_vpos_links = {}

                # Hide gizmo when clearing selection
                if hasattr(self.canvas, 'gizmo_renderer'):
                    print("Empty selection box: Hiding gizmo")
                    self.canvas.gizmo_renderer.hide_gizmo()
                
                # Emit cleared selection signal
                if hasattr(self.canvas, 'entitySelected'):
                    self.canvas.entitySelected.emit(None)
        
        self.canvas.update()

    def get_selection_box(self):
        """Get current selection box coordinates for rendering"""
        if self.selection_box_active:
            return (self.selection_box_start_x, self.selection_box_start_y,
                    self.selection_box_end_x, self.selection_box_end_y)
        return None

    def _find_shape_point_at(self, screen_x, screen_y):
        """Check selected entity first, then all entities; return (entity, pt_idx) or (None, None)."""
        er = getattr(self.canvas, 'entity_renderer', None)
        if er is None:
            return None, None
        sel = self.canvas.selected_entity
        if sel:
            idx = self._get_shape_point_at(screen_x, screen_y, sel)
            if idx is not None:
                return sel, idx
        for e in (getattr(self.canvas, 'entities', None) or []):
            if e is sel:
                continue
            if not er.has_shape_points(e):
                continue
            idx = self._get_shape_point_at(screen_x, screen_y, e)
            if idx is not None:
                return e, idx
        return None, None

    def _get_shape_point_at(self, screen_x, screen_y, entity):
        """Return index of the closest hidShapePoint handle within RADIUS of (screen_x, screen_y), or None."""
        er = getattr(self.canvas, 'entity_renderer', None)
        if er is None:
            return None
        points = er.get_shape_points(entity)
        RADIUS = 14
        best_idx = None
        best_dist = float('inf')
        print(f"[shapept] click=({screen_x:.1f},{screen_y:.1f}) checking {len(points)} pts, RADIUS={RADIUS}")
        for i, (px, py, pz) in enumerate(points):
            sx, sy = self.canvas.world_to_screen(px, py)
            dist = ((sx - screen_x) ** 2 + (sy - screen_y) ** 2) ** 0.5
            print(f"  pt{i}: world=({px:.2f},{py:.2f}) screen=({sx:.1f},{sy:.1f}) dist={dist:.1f}")
            if dist <= RADIUS and dist < best_dist:
                best_idx = i
                best_dist = dist
        print(f"  → hit={best_idx} dist={best_dist:.1f}")
        return best_idx

    def _snapshot_shape_points(self, entity):
        """Return a snapshot dict for ShapePointCommand undo/redo."""
        points = []
        if hasattr(entity, 'xml_element') and entity.xml_element is not None:
            field = entity.xml_element.find("field[@name='hidShapePoints']")
            if field is not None:
                for pt in field.findall('Point'):
                    try:
                        parts = pt.text.strip().split(',')
                        if len(parts) == 3:
                            points.append((float(parts[0]), float(parts[1]), float(parts[2])))
                    except (ValueError, AttributeError):
                        pass
        return {'entity': entity, 'points': points, 'ex': entity.x, 'ey': entity.y, 'ez': entity.z}

    def _shift_shape_points(self, entity, dx, dy):
        """Shift ALL hidShapePoints by (dx, dy) world units in-place in the XML."""
        if not hasattr(entity, 'xml_element') or entity.xml_element is None:
            return
        field = entity.xml_element.find("field[@name='hidShapePoints']")
        if field is None:
            return
        for pt in field.findall('Point'):
            try:
                parts = pt.text.strip().split(',')
                if len(parts) == 3:
                    pt.text = f"{float(parts[0]) + dx},{float(parts[1]) + dy},{parts[2]}"
            except (ValueError, AttributeError):
                pass
        er = getattr(self.canvas, 'entity_renderer', None)
        if er:
            er.invalidate_entity_cache(entity)

    def _move_shape_point(self, entity, pt_idx, dx, dy):
        """Move a single hidShapePoint by (dx, dy) world units."""
        if not hasattr(entity, 'xml_element') or entity.xml_element is None:
            return
        field = entity.xml_element.find("field[@name='hidShapePoints']")
        if field is None:
            return
        pts = field.findall('Point')
        if pt_idx >= len(pts):
            return
        try:
            parts = pts[pt_idx].text.strip().split(',')
            if len(parts) == 3:
                pts[pt_idx].text = f"{float(parts[0]) + dx},{float(parts[1]) + dy},{parts[2]}"
        except (ValueError, AttributeError):
            pass
        er = getattr(self.canvas, 'entity_renderer', None)
        if er:
            er.invalidate_entity_cache(entity)

    def _check_shape_btn_click(self, screen_x, screen_y):
        """Return True and act if (screen_x, screen_y) lands on a +/- shape point button."""
        entity = getattr(self.canvas, '_shape_btn_entity', None)
        if entity is None:
            return False

        def in_rect(rect):
            if rect is None:
                return False
            rx, ry, rw, rh = rect
            return rx <= screen_x <= rx + rw and ry <= screen_y <= ry + rh

        if in_rect(getattr(self.canvas, '_shape_add_btn_rect', None)):
            self._add_shape_point(entity)
            return True
        if in_rect(getattr(self.canvas, '_shape_remove_btn_rect', None)):
            self._remove_last_shape_point(entity)
            return True
        return False

    def _add_shape_point(self, entity):
        """Append a new hidShapePoint 5 world-units left and down from the last point."""
        import xml.etree.ElementTree as ET
        if not hasattr(entity, 'xml_element') or entity.xml_element is None:
            return
        field = entity.xml_element.find("field[@name='hidShapePoints']")
        if field is None:
            return
        pts = field.findall('Point')
        if not pts:
            return
        last_pt = pts[-1]
        try:
            parts = last_pt.text.strip().split(',')
            if len(parts) != 3:
                return
            lx, ly, lz = float(parts[0]), float(parts[1]), parts[2].strip()
        except (ValueError, AttributeError):
            return

        closing_tail = last_pt.tail
        point_tail = pts[-2].tail if len(pts) >= 2 else field.text
        last_pt.tail = point_tail

        new_pt = ET.Element('Point')
        new_pt.text = f"{lx - 5},{ly - 5},{lz}"
        new_pt.tail = closing_tail
        field.append(new_pt)

        er = getattr(self.canvas, 'entity_renderer', None)
        if er:
            er.invalidate_entity_cache(entity)
        self._auto_save_entity_changes(entity)
        self.canvas.update()

    def _remove_last_shape_point(self, entity):
        """Remove the last hidShapePoint (never removes pt0)."""
        if not hasattr(entity, 'xml_element') or entity.xml_element is None:
            return
        field = entity.xml_element.find("field[@name='hidShapePoints']")
        if field is None:
            return
        pts = field.findall('Point')
        if len(pts) <= 1:
            return
        last_pt = pts[-1]
        second_last = pts[-2]
        second_last.tail = last_pt.tail
        field.remove(last_pt)

        # Clear drag state if it was pointing at the removed index
        if (self.selected_shape_point and
                self.selected_shape_point[0] is entity and
                self.selected_shape_point[1] >= len(pts) - 1):
            self.selected_shape_point = None
            self.dragging_shape_point = False
            self._shape_drag_anchor = None

        er = getattr(self.canvas, 'entity_renderer', None)
        if er:
            er.invalidate_entity_cache(entity)
        self._auto_save_entity_changes(entity)
        self.canvas.update()

    def toggle_edit_mode_2d(self):
        """Toggle between View mode (select/rotate only) and Edit mode (move enabled)."""
        self.edit_mode_2d = not self.edit_mode_2d
        mode_name = "EDIT" if self.edit_mode_2d else "VIEW"
        print(f"2D mode: {mode_name}")
        if self.edit_mode_2d:
            self.canvas.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
        self.canvas.update()

    def toggle_edit_mode_3d(self):
        """Toggle between 3D View mode (camera only) and 3D Edit mode (gizmo + selection active)."""
        self.edit_mode_3d = not self.edit_mode_3d
        mode_name = "EDIT" if self.edit_mode_3d else "VIEW"
        print(f"3D mode: {mode_name}")
        self.canvas.update()

    def _update_cursor_2d(self, screen_x, screen_y):
        """Update cursor based on 2D hover state - includes gizmo detection"""
        # Check for gizmo hover first (highest priority)
        if (hasattr(self.canvas, 'selected_entity') and self.canvas.selected_entity and 
            hasattr(self.canvas, 'gizmo_renderer') and 
            self.canvas.gizmo_renderer.rotation_gizmo.is_point_on_circle(screen_x, screen_y, self.canvas)):
            self.canvas.setCursor(Qt.CursorShape.PointingHandCursor)
            return
        
        # Check for entity hover
        hovered_entity = self.get_entity_at_position(screen_x, screen_y)
        if hovered_entity:
            self.canvas.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.canvas.setCursor(Qt.CursorShape.ArrowCursor)

    def handle_wheel(self, event):
        """Handle wheel events - 2D ONLY"""
        print(f"Wheel event: delta={event.angleDelta().y()}")
        
        # Always use 2D zoom
        self.canvas.camera_controller.handle_wheel_zoom_2d(event, self.canvas)
    
    def handle_key_press(self, event):
        """Handle key press events - 2D ONLY with SHIFT speed boost"""
        # Set modifier flags
        if event.key() == Qt.Key.Key_Shift:
            self.shift_is_pressed = True
            if hasattr(self.canvas, 'camera_controller'):
                self.canvas.camera_controller.set_shift_modifier(True)

        # Movement keys — use scan code so any keyboard layout works
        from canvas.opengl_utils import movement_action
        action = movement_action(event)
        if action:
            self.canvas.camera_controller.set_movement_flag(action, True)

    def handle_key_release(self, event):
        """Handle key release events - 2D ONLY with SHIFT speed boost"""
        # Reset modifier flags
        if event.key() == Qt.Key.Key_Shift:
            self.shift_is_pressed = False
            if hasattr(self.canvas, 'camera_controller'):
                self.canvas.camera_controller.set_shift_modifier(False)

        # Movement keys — use scan code so any keyboard layout works
        from canvas.opengl_utils import movement_action
        action = movement_action(event)
        if action:
            self.canvas.camera_controller.set_movement_flag(action, False)
    
    def get_entity_at_position(self, screen_x, screen_y, radius=8):
        """Get entity at the given screen position in 2D mode"""
        entities = getattr(self.canvas, 'entities', [])
        if not entities:
            return None
            
        for entity in entities:
            if (not getattr(self.canvas, 'unified_mode', False) and
                    hasattr(self.canvas, 'current_map') and self.canvas.current_map is not None and
                    getattr(entity, 'map_name', None) != self.canvas.current_map.name):
                continue
                
            if not hasattr(entity, 'x') or not hasattr(entity, 'y'):
                continue
                
            x, y = OpenGLUtils.world_to_screen(entity.x, entity.y, self.canvas)
            
            entity_size = 6 if entity in getattr(self.canvas, 'selected', []) else 4
            square_size = entity_size * 2
            half_size = square_size // 2
            
            if (x - half_size <= screen_x <= x + half_size and 
                y - half_size <= screen_y <= y + half_size):
                return entity
        return None

    def center_view_here(self, event):
        """Center view at click location"""
        width = self.canvas.width()
        height = self.canvas.height()
        
        # 2D centering
        self.canvas.camera_controller.offset_x += width / 2 - event.position().x()
        self.canvas.camera_controller.offset_y += height / 2 - event.position().y()
        
        self.canvas.update()
        print(f"Centered view at click position")
    
    def zoom_to_selected_entities(self):
        """Zoom view to show all selected entities"""
        selected = getattr(self.canvas, 'selected', [])
        if not selected:
            return
        
        if len(selected) == 1:
            entity = selected[0]
            self.canvas.camera_controller.zoom_to_entity_2d(entity, self.canvas)
        else:
            # Multiple entities - zoom to fit all
            self._zoom_to_multiple_entities(selected)
    
    def toggle_grid(self):
        """Toggle grid display"""
        self.canvas.show_grid = not getattr(self.canvas, 'show_grid', True)
        print(f"Grid toggled: {self.canvas.show_grid}")
        self.canvas.update()
    
    def toggle_entities(self):
        """Toggle entity display"""
        self.canvas.show_entities = not getattr(self.canvas, 'show_entities', True)
        print(f"Entities toggled: {self.canvas.show_entities}")
        self.canvas.update()
            
    def _update_status_bar_2d(self, screen_x, screen_y):
        """Update status bar with 2D cursor info"""
        try:
            if hasattr(self.canvas.parent(), 'statusBar') and self.canvas.parent().statusBar():
                world_x, world_y = OpenGLUtils.screen_to_world(screen_x, screen_y, self.canvas)
                
                cursor_info = f"Cursor: X: {world_x:.2f}, Y: {world_y:.2f}"
                
                # Add sector information if available
                if hasattr(self.canvas, 'grid_config') and self.canvas.grid_config:
                    sector_x = int(world_x / 64)  # Assuming 64-unit sectors
                    sector_y = int(world_y / 64)
                    cursor_info += f" | Sector: ({sector_x}, {sector_y})"
                
                self.canvas.parent().statusBar().showMessage(cursor_info)
        except Exception as e:
            pass  # Ignore status bar errors

    def _zoom_to_multiple_entities(self, entities):
        """Zoom to fit multiple entities"""
        if not entities:
            return
        
        # Calculate bounding box
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        
        for entity in entities:
            if hasattr(entity, 'x') and hasattr(entity, 'y'):
                min_x = min(min_x, entity.x)
                min_y = min(min_y, entity.y)
                max_x = max(max_x, entity.x)
                max_y = max(max_y, entity.y)
        
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        
        # 2D zoom calculation
        width = max_x - min_x
        height = max_y - min_y
        padding = 1.5
        
        scale_x = self.canvas.width() / (width * padding) if width > 0 else 1.0
        scale_y = self.canvas.height() / (height * padding) if height > 0 else 1.0
        
        target_scale = min(scale_x, scale_y)
        target_scale = max(0.1, min(10.0, target_scale))
        
        self.canvas.scale_factor = target_scale
        self.canvas.camera_controller.offset_x = (self.canvas.width() / 2) - (center_x * self.canvas.scale_factor)
        self.canvas.camera_controller.offset_y = (self.canvas.height() / 2) - (center_y * self.canvas.scale_factor)
        
        self.canvas.update()
        print(f"Zoomed to {len(entities)} entities")
    
    def _auto_save_entity_changes(self, entity):
        """Auto-save entity changes"""
        if hasattr(self.canvas, '_auto_save_entity_changes'):
            self.canvas._auto_save_entity_changes(entity)
    
    def _update_entity_xml(self, entity):
        """Update entity XML"""
        if hasattr(self.canvas, 'update_entity_xml'):
            self.canvas.update_entity_xml(entity)