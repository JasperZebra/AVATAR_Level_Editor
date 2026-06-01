# all_in_one_copy_paste.py
# Enhanced copy/paste system that works like export/import for all entity types

import json
import xml.etree.ElementTree as ET
import copy
import os
import time
import random
import struct
import types
from PyQt6.QtWidgets import QApplication, QMessageBox, QMenu
from PyQt6.QtCore import QMimeData
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from data_models import Entity

class EntityClipboard:
    """Handles copy/paste operations for entities using export/import methodology"""
    
    def __init__(self):
        self.clipboard_data = None
        
    def copy_entities(self, entities):
        """Copy entities INCLUDING Structure children AND seated NPCs - WITH SAFETY CHECKS"""
        if not entities:
            return False
        
        print(f"\n{'='*70}")
        print(f"COPY WITH RELATIONSHIPS - STARTING")
        print(f"{'='*70}")
        
        # CRITICAL: Store original states BEFORE any operations
        original_states = {}
        for entity in entities:
            original_states[id(entity)] = {  # Use Python object id as key
                'entity_obj': entity,
                'x': entity.x,
                'y': entity.y,
                'z': entity.z,
                'id': entity.id,
                'name': entity.name,
                'xml_string': ET.tostring(entity.xml_element, encoding='unicode') if hasattr(entity, 'xml_element') and entity.xml_element else None
            }
            print(f"📌 Saved original: {entity.name} at ({entity.x:.1f}, {entity.y:.1f}, {entity.z:.1f}), ID={entity.id}")
        
        try:
            # Build a dictionary of all entities by ID for quick lookup
            entities_dict = {}
            if hasattr(self, 'editor') and hasattr(self.editor, 'entities'):
                for entity in self.editor.entities:
                    entities_dict[entity.id] = entity
            
            # Collect all entities including relationships
            all_entities_to_copy = []
            already_included = set()
            relationship_map = {
                'structure_children': {},  # parent_id -> [child_ids]
                'seated_npcs': {},         # vehicle_id -> [npc_ids]
                'all_relationships': {}    # entity_id -> {'children': [], 'seated': [], 'linked': []}
            }
            
            print(f"\n=== COLLECTING ENTITIES WITH ALL RELATIONSHIPS ===")
            
            for entity in entities:
                if entity.id not in already_included:
                    all_entities_to_copy.append(entity)
                    already_included.add(entity.id)
                    print(f"✅ Added: {entity.name}")
                    
                    # Track relationships for this entity
                    entity_relationships = {
                        'children': [],
                        'seated': [],
                        'linked': []
                    }
                    
                    # Check if this entity has an XML element
                    if hasattr(entity, 'xml_element') and entity.xml_element is not None:
                        
                        # 1. Check for Structure children
                        entity_class_field = entity.xml_element.find(".//field[@name='text_hidEntityClass']")
                        if entity_class_field is not None:
                            entity_class = entity_class_field.get('value-String', '')
                            
                            if 'Prefab' in entity_class or 'Structure' in entity.name:
                                print(f"  🏗️ Structure/Prefab detected, checking for children...")
                                
                                children_obj = entity.xml_element.find(".//object[@name='Children']")
                                if children_obj is not None:
                                    child_objects = children_obj.findall("object[@name='Child']")
                                    child_ids = []
                                    
                                    for child_obj in child_objects:
                                        id_field = child_obj.find("field[@name='ID']")
                                        name_field = child_obj.find("field[@name='Name']")
                                        
                                        if id_field is not None:
                                            child_id = id_field.get('value-Hash64')
                                            child_name = name_field.get('value-String') if name_field is not None else 'unknown'
                                            child_ids.append(child_id)
                                            
                                            # Find actual child entity
                                            if child_id in entities_dict:
                                                child_entity = entities_dict[child_id]
                                                if child_entity.id not in already_included:
                                                    all_entities_to_copy.append(child_entity)
                                                    already_included.add(child_entity.id)
                                                    entity_relationships['children'].append(child_id)
                                                    print(f"    ✅ Added child: {child_name} (ID: {child_id})")
                                            elif child_name:
                                                # Fallback: find by name
                                                for ent_id, ent in entities_dict.items():
                                                    if ent.name == child_name and ent.id not in already_included:
                                                        all_entities_to_copy.append(ent)
                                                        already_included.add(ent.id)
                                                        child_ids.append(ent.id)
                                                        entity_relationships['children'].append(ent.id)
                                                        print(f"    ✅ Added child by name: {child_name}")
                                                        break
                                    
                                    if child_ids:
                                        relationship_map['structure_children'][entity.id] = child_ids
                                        print(f"  📦 Structure has {len(child_ids)} children")
                        
                        # 2. Check for seated NPCs (CFCXAIComponent → AIObject) via value-Hash64
                        ai_component = entity.xml_element.find(".//object[@name='CFCXAIComponent']")
                        if ai_component is not None:
                            ai_object = ai_component.find(".//object[@name='AIObject']")
                            if ai_object is not None:
                                print(f"  🚗 Vehicle detected, checking for seated NPCs...")

                                seated_ids = []
                                # Find all fields in AIObject that reference entities
                                for field in ai_object.findall("field"):
                                    entity_id_ref = field.get('value-Hash64')
                                    if entity_id_ref and entity_id_ref in entities_dict:
                                        seated_entity = entities_dict[entity_id_ref]
                                        # Make sure it's not self-reference
                                        if seated_entity.id != entity.id:
                                            if seated_entity.id not in already_included:
                                                all_entities_to_copy.append(seated_entity)
                                                already_included.add(seated_entity.id)
                                                seated_ids.append(seated_entity.id)
                                                entity_relationships['seated'].append(seated_entity.id)
                                                print(f"    🪑 Added seated NPC: {seated_entity.name} (ID: {seated_entity.id})")

                                if seated_ids:
                                    relationship_map['seated_npcs'][entity.id] = seated_ids
                                    print(f"  🚗 Vehicle has {len(seated_ids)} seated NPCs")

                        # 3. Check all ent* fields with value-Id64 or bare BinHex (entUser, entInitialUser, etc.)
                        import struct as _struct
                        user_ids = []
                        for field in entity.xml_element.iter('field'):
                            fname = field.get('name', '')
                            if not fname.startswith('ent'):
                                continue
                            ref_id = field.get('value-Id64')
                            if not ref_id:
                                # Bare BinHex fallback (no value-Id64 attribute)
                                binhex = (field.text or '').strip().upper()
                                if len(binhex) == 16 and binhex != 'FFFFFFFFFFFFFFFF':
                                    try:
                                        ref_id = str(_struct.unpack('<Q', bytes.fromhex(binhex))[0])
                                    except Exception:
                                        pass
                            if ref_id and ref_id in entities_dict and ref_id != entity.id:
                                ref_entity = entities_dict[ref_id]
                                if ref_entity.id not in already_included:
                                    all_entities_to_copy.append(ref_entity)
                                    already_included.add(ref_entity.id)
                                    user_ids.append(ref_entity.id)
                                    entity_relationships['seated'].append(ref_entity.id)
                                    print(f"    👤 Added user/pilot ({fname}): {ref_entity.name} (ID: {ref_id})")
                        if user_ids:
                            if entity.id not in relationship_map['seated_npcs']:
                                relationship_map['seated_npcs'][entity.id] = []
                            relationship_map['seated_npcs'][entity.id].extend(user_ids)
                            print(f"  🎮 Entity has {len(user_ids)} user/pilot references")
                    
                    # Store all relationships for this entity
                    if entity_relationships['children'] or entity_relationships['seated'] or entity_relationships['linked']:
                        relationship_map['all_relationships'][entity.id] = entity_relationships
            
            print(f"\n📊 COLLECTION SUMMARY:")
            print(f"   Original selection: {len(entities)} entities")
            print(f"   Total collected: {len(all_entities_to_copy)} entities")
            print(f"   Additional entities: {len(all_entities_to_copy) - len(entities)}")
            print(f"   Structures with children: {len(relationship_map['structure_children'])}")
            print(f"   Vehicles with seated NPCs: {len(relationship_map['seated_npcs'])}")
            
            # Serialize all entities
            serialized_entities = []
            
            for entity in all_entities_to_copy:
                if hasattr(entity, 'xml_element') and entity.xml_element is not None:
                    # CRITICAL: Deep copy the XML element to avoid modifying original
                    xml_copy = copy.deepcopy(entity.xml_element)
                    
                    # Remove export-specific attributes
                    export_attrs = ['type', 'exported_name', 'exported_id', 'export_version', 'exported_position']
                    for attr in export_attrs:
                        if attr in xml_copy.attrib:
                            del xml_copy.attrib[attr]
                    
                    xml_string = ET.tostring(xml_copy, encoding='unicode')
                    
                    entity_data = {
                        'id': entity.id,
                        'name': entity.name,
                        'x': entity.x,
                        'y': entity.y,
                        'z': entity.z,
                        'xml': xml_string,
                        'source_file': getattr(entity, 'source_file', 'unknown'),
                        'source_file_path': getattr(entity, 'source_file_path', None),
                        'map_name': getattr(entity, 'map_name', None),
                        'entity_type': getattr(entity, 'entity_type', None),
                        'source_sector_id': getattr(entity, 'source_sector_id', -1),
                        'source_layer': getattr(entity, 'source_layer', 'main'),
                        'has_xml_element': True,
                        'is_structure_parent': entity.id in relationship_map['structure_children'],
                        'is_vehicle_with_npc': entity.id in relationship_map['seated_npcs']
                    }
                else:
                    entity_data = {
                        'id': entity.id,
                        'name': entity.name,
                        'x': entity.x,
                        'y': entity.y,
                        'z': entity.z,
                        'xml': None,
                        'source_file': getattr(entity, 'source_file', 'unknown'),
                        'source_file_path': getattr(entity, 'source_file_path', None),
                        'map_name': getattr(entity, 'map_name', None),
                        'entity_type': getattr(entity, 'entity_type', None),
                        'source_sector_id': getattr(entity, 'source_sector_id', -1),
                        'source_layer': getattr(entity, 'source_layer', 'main'),
                        'has_xml_element': False,
                        'is_structure_parent': False,
                        'is_vehicle_with_npc': False
                    }
                
                serialized_entities.append(entity_data)
            
            clipboard_data = {
                'type': 'avatar_entities_fcb',
                'version': '2.2',  # Bumped version for relationship support
                'format': 'FCBConverter',
                'count': len(serialized_entities),
                'original_selection_count': len(entities),
                'includes_relationships': len(all_entities_to_copy) > len(entities),
                'structure_child_map': relationship_map['structure_children'],
                'seated_npc_map': relationship_map['seated_npcs'],
                'all_relationships': relationship_map['all_relationships'],
                'copy_date': time.strftime('%Y-%m-%d %H:%M:%S'),
                'entities': serialized_entities
            }
            
            json_string = json.dumps(clipboard_data, indent=2)
            
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtCore import QMimeData
            
            clipboard = QApplication.clipboard()
            mime_data = QMimeData()
            mime_data.setText(json_string)
            mime_data.setData("application/x-avatar-entities-fcb", json_string.encode())
            clipboard.setMimeData(mime_data)
            
            self.clipboard_data = clipboard_data
            
            print(f"✅ Successfully copied {len(entities)} entities ({len(all_entities_to_copy)} total with relationships)")
            
            # VERIFY: Check if originals were modified during copy
            print(f"\n{'='*70}")
            print(f"VERIFYING ORIGINALS AFTER COPY")
            print(f"{'='*70}")
            
            corrupted = False
            for obj_id, original_state in original_states.items():
                entity = original_state['entity_obj']
                
                if (entity.x != original_state['x'] or 
                    entity.y != original_state['y'] or
                    entity.z != original_state['z'] or
                    entity.id != original_state['id'] or
                    entity.name != original_state['name']):
                    
                    print(f"🚨 BUG DETECTED: Original entity was MODIFIED during copy!")
                    print(f"  Entity: {original_state['name']}")
                    print(f"  Position: ({original_state['x']:.1f}, {original_state['y']:.1f}, {original_state['z']:.1f}) → ({entity.x:.1f}, {entity.y:.1f}, {entity.z:.1f})")
                    print(f"  ID: {original_state['id']} → {entity.id}")
                    print(f"  Name: {original_state['name']} → {entity.name}")
                    corrupted = True
                else:
                    print(f"✅ {entity.name} unchanged")
            
            if corrupted:
                print(f"\n⚠️ WARNING: Original entities were corrupted during copy!")
                print(f"   This is a BUG that needs to be fixed!")
            else:
                print(f"\n✅ All original entities remain unchanged - copy is safe!")
            
            return True
            
        except Exception as e:
            print(f"❌ Error copying entities: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
            
    def paste_entities(self, target_position=None, id_generator=None, name_generator=None):
        """Paste entities with ALL relationships (Structure children + seated NPCs) - FIXED offset with safety checks"""
        try:
            from PyQt6.QtWidgets import QApplication
            
            clipboard = QApplication.clipboard()
            mime_data = clipboard.mimeData()
            
            clipboard_data = None
            
            if mime_data.hasFormat("application/x-avatar-entities-fcb"):
                json_string = mime_data.data("application/x-avatar-entities-fcb").data().decode()
                clipboard_data = json.loads(json_string)
            elif mime_data.hasText():
                try:
                    json_string = mime_data.text()
                    clipboard_data = json.loads(json_string)
                    if not (clipboard_data.get('type') in ['avatar_entities', 'avatar_entities_fcb'] and 'entities' in clipboard_data):
                        clipboard_data = None
                except json.JSONDecodeError:
                    clipboard_data = None
            
            if clipboard_data is None:
                clipboard_data = self.clipboard_data
                
            if clipboard_data is None:
                print("No entity data found in clipboard")
                return []
            
            entities_data = clipboard_data.get('entities', [])
            if not entities_data:
                print("No entities found in clipboard data")
                return []
            
            print(f"\n=== PASTING {len(entities_data)} ENTITIES WITH RELATIONSHIPS ===")
            
            # Calculate offset - ONLY from first entity, apply uniformly to ALL
            offset_x = offset_y = offset_z = 0
            
            if target_position and entities_data:
                first_entity = entities_data[0]
                offset_x = target_position[0] - first_entity['x']
                offset_y = target_position[1] - first_entity['y']
                if len(target_position) >= 3:
                    offset_z = target_position[2] - first_entity['z']
                else:
                    offset_z = 0
                print(f"Applying uniform offset to ALL entities: ({offset_x:.1f}, {offset_y:.1f}, {offset_z:.1f})")
            
            existing_ids = self._get_all_existing_entity_ids()
            existing_names = self._get_all_existing_entity_names()
            
            # Track ID mapping for updating relationships
            id_mapping = {}  # old_id -> new_id
            
            new_entities = []
            
            # Get relationship maps
            structure_child_map = clipboard_data.get('structure_child_map', {})
            seated_npc_map = clipboard_data.get('seated_npc_map', {})
            
            # Identify all child/seated IDs
            all_child_ids = set()
            for parent_id, child_ids in structure_child_map.items():
                all_child_ids.update(child_ids)
            
            all_seated_ids = set()
            for vehicle_id, npc_ids in seated_npc_map.items():
                all_seated_ids.update(npc_ids)
            
            print(f"\n📊 Relationship Summary:")
            print(f"   Total entities: {len(entities_data)}")
            print(f"   Structure children: {len(all_child_ids)}")
            print(f"   Seated NPCs: {len(all_seated_ids)}")
            
            # First pass: Create all entities with new IDs and UNIFORM offset
            for i, entity_data in enumerate(entities_data):
                try:
                    print(f"\n📦 Processing entity {i+1}/{len(entities_data)}: {entity_data['name']}")
                    
                    if entity_data.get('has_xml_element', True) and entity_data.get('xml'):
                        xml_element = ET.fromstring(entity_data['xml'])
                        
                        # Generate new unique entity ID
                        old_id = entity_data['id']
                        new_id = self._generate_unique_entity_id(existing_ids, id_generator)
                        existing_ids.add(new_id)
                        
                        # Store ID mapping
                        id_mapping[old_id] = new_id
                        
                        # Generate unique name
                        new_name = self._generate_unique_entity_name(entity_data['name'], existing_names, name_generator)
                        existing_names.add(new_name)
                        
                        print(f"  ID mapping: {old_id} → {new_id}")
                        print(f"  Name: {entity_data['name']} → {new_name}")
                        
                        # Update entity ID and name
                        self._update_entity_id_in_xml(xml_element, new_id)
                        self._update_entity_name_in_xml(xml_element, new_name)
                        
                        # Apply SAME offset to ALL entities
                        new_x = entity_data['x'] + offset_x
                        new_y = entity_data['y'] + offset_y
                        new_z = entity_data['z'] + offset_z
                        
                        # Log entity type
                        is_parent = old_id in structure_child_map
                        is_child = old_id in all_child_ids
                        is_vehicle = old_id in seated_npc_map
                        is_seated = old_id in all_seated_ids
                        
                        if is_parent:
                            print(f"  🏗️ Structure parent: applying offset")
                        elif is_child:
                            print(f"  📦 Structure child: applying offset")
                        elif is_vehicle:
                            print(f"  🚗 Vehicle: applying offset")
                        elif is_seated:
                            print(f"  🪑 Seated NPC: applying offset")
                        else:
                            print(f"  📍 Standalone entity: applying offset")
                        
                        print(f"  Position: ({entity_data['x']:.1f}, {entity_data['y']:.1f}, {entity_data['z']:.1f}) → ({new_x:.1f}, {new_y:.1f}, {new_z:.1f})")
                        
                        self._update_entity_position_in_xml(xml_element, new_x, new_y, new_z)
                        
                        # Create entity
                        from data_models import Entity
                        entity = Entity(
                            id=str(new_id),
                            name=new_name,
                            x=new_x,
                            y=new_y,
                            z=new_z,
                            xml_element=xml_element
                        )
                        
                    else:
                        # Fallback for entities without XML
                        print(f"  Entity has no XML element, creating basic entity")
                        
                        old_id = entity_data['id']
                        new_id = self._generate_unique_entity_id(existing_ids, id_generator)
                        existing_ids.add(new_id)
                        id_mapping[old_id] = new_id
                        
                        new_name = self._generate_unique_entity_name(entity_data['name'], existing_names, name_generator)
                        existing_names.add(new_name)
                        
                        new_x = entity_data['x'] + offset_x
                        new_y = entity_data['y'] + offset_y
                        new_z = entity_data['z'] + offset_z
                        
                        from data_models import Entity
                        entity = Entity(
                            id=str(new_id),
                            name=new_name,
                            x=new_x,
                            y=new_y,
                            z=new_z
                        )
                    
                    entity.source_file = entity_data.get('source_file', 'worldsectors')
                    entity.source_file_path = entity_data.get('source_file_path', None)
                    entity.map_name = entity_data.get('map_name', None)
                    entity.entity_type = entity_data.get('entity_type', None)
                    entity.source_sector_id = entity_data.get('source_sector_id', -1)
                    entity.source_layer = entity_data.get('source_layer', 'main')
                    
                    new_entities.append(entity)
                    print(f"  ✅ Created entity: {entity.name}")
                    
                except Exception as e:
                    print(f"  ❌ Error processing entity {i+1}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            # Second pass: Update Structure parent-child references
            print(f"\n🔗 Updating Structure parent-child references...")
            for parent_old_id, child_old_ids in structure_child_map.items():
                if parent_old_id not in id_mapping:
                    print(f"  ⚠️ Parent ID {parent_old_id} not found in ID mapping")
                    continue
                
                parent_new_id = id_mapping[parent_old_id]
                
                # Find the parent entity
                parent_entity = None
                for entity in new_entities:
                    if int(entity.id) == parent_new_id:
                        parent_entity = entity
                        break
                
                if parent_entity is None or not hasattr(parent_entity, 'xml_element') or parent_entity.xml_element is None:
                    print(f"  ⚠️ Parent entity not found or has no XML")
                    continue
                
                print(f"  🔧 Updating Structure: {parent_entity.name}")
                
                # Find Children object
                children_obj = parent_entity.xml_element.find(".//object[@name='Children']")
                if children_obj is None:
                    print(f"    ⚠️ No Children object found")
                    continue
                
                # Update each child reference
                child_objects = children_obj.findall("object[@name='Child']")
                updated_count = 0
                
                for child_obj in child_objects:
                    id_field = child_obj.find("field[@name='ID']")
                    name_field = child_obj.find("field[@name='Name']")
                    
                    if id_field is not None:
                        old_child_id = id_field.get('value-Hash64')
                        child_name = name_field.get('value-String', 'unknown') if name_field is not None else 'unknown'
                        
                        if old_child_id in id_mapping:
                            new_child_id = id_mapping[old_child_id]
                            
                            # Update child ID
                            id_field.set('value-Hash64', str(new_child_id))
                            binary_hex = self._int64_to_binhex(new_child_id)
                            id_field.text = binary_hex
                            
                            # Update child name
                            if name_field is not None:
                                for entity in new_entities:
                                    if int(entity.id) == new_child_id:
                                        name_field.set('value-String', entity.name)
                                        name_binary_hex = self._string_to_binhex(entity.name)
                                        name_field.text = name_binary_hex
                                        print(f"    ✅ Updated child: {child_name} → {entity.name} (ID: {old_child_id} → {new_child_id})")
                                        updated_count += 1
                                        break
                        else:
                            print(f"    ⚠️ Child ID {old_child_id} not found in ID mapping")
                
                print(f"    ✅ Updated {updated_count} child references in {parent_entity.name}")
            
            # Third pass: Update seated NPC references (NEW!)
            print(f"\n🚗 Updating seated NPC references...")
            for vehicle_old_id, npc_old_ids in seated_npc_map.items():
                if vehicle_old_id not in id_mapping:
                    print(f"  ⚠️ Vehicle ID {vehicle_old_id} not found in ID mapping")
                    continue
                
                vehicle_new_id = id_mapping[vehicle_old_id]
                
                # Find the vehicle entity
                vehicle_entity = None
                for entity in new_entities:
                    if int(entity.id) == vehicle_new_id:
                        vehicle_entity = entity
                        break
                
                if vehicle_entity is None or not hasattr(vehicle_entity, 'xml_element') or vehicle_entity.xml_element is None:
                    print(f"  ⚠️ Vehicle entity not found or has no XML")
                    continue
                
                print(f"  🔧 Updating vehicle: {vehicle_entity.name}")
                
                # Find CFCXAIComponent → AIObject
                ai_component = vehicle_entity.xml_element.find(".//object[@name='CFCXAIComponent']")
                if ai_component is None:
                    print(f"    ⚠️ No CFCXAIComponent found")
                    continue
                
                ai_object = ai_component.find(".//object[@name='AIObject']")
                if ai_object is None:
                    print(f"    ⚠️ No AIObject found")
                    continue
                
                # Update seated NPC references
                updated_count = 0
                for npc_old_id in npc_old_ids:
                    if npc_old_id in id_mapping:
                        npc_new_id = id_mapping[npc_old_id]
                        
                        # Find the NPC entity to get its name
                        npc_entity = None
                        for entity in new_entities:
                            if int(entity.id) == npc_new_id:
                                npc_entity = entity
                                break
                        
                        # Update the field that references this NPC
                        for field in ai_object.findall("field"):
                            field_value = field.get('value-Hash64')
                            if field_value == npc_old_id:
                                field.set('value-Hash64', str(npc_new_id))
                                binary_hex = self._int64_to_binhex(npc_new_id)
                                field.text = binary_hex
                                
                                npc_name = npc_entity.name if npc_entity else "Unknown"
                                print(f"    🪑 Updated seated NPC: {npc_name} (ID: {npc_old_id} → {npc_new_id})")
                                updated_count += 1
                                break
                    else:
                        print(f"    ⚠️ NPC ID {npc_old_id} not found in ID mapping")
                
                print(f"    ✅ Updated {updated_count} seated NPC references in {vehicle_entity.name}")
            
            # Fourth pass: update all ent* entity reference fields (value-Id64 and bare BinHex)
            print(f"\n🔗 Updating entity reference fields (entUser, entInitialUser, etc.)...")
            import struct as _struct
            for new_entity in new_entities:
                if not hasattr(new_entity, 'xml_element') or new_entity.xml_element is None:
                    continue
                updated = []
                for field in new_entity.xml_element.iter('field'):
                    fname = field.get('name', '')
                    if not fname.startswith('ent'):
                        continue

                    # Case 1: has value-Id64 attribute
                    ref_id = field.get('value-Id64')
                    if ref_id and ref_id in id_mapping:
                        new_ref_id = id_mapping[ref_id]
                        field.set('value-Id64', str(new_ref_id))
                        field.text = _struct.pack('<Q', new_ref_id & 0xFFFFFFFFFFFFFFFF).hex().upper()
                        updated.append(f"{fname}: {ref_id}→{new_ref_id}")
                        continue

                    # Case 2: bare BinHex (no value-Id64 attribute)
                    if ref_id is None:
                        binhex = (field.text or '').strip().upper()
                        if len(binhex) == 16 and binhex != 'FFFFFFFFFFFFFFFF':
                            try:
                                old_int = _struct.unpack('<Q', bytes.fromhex(binhex))[0]
                                old_id_str = str(old_int)
                                if old_id_str in id_mapping:
                                    new_ref_id = id_mapping[old_id_str]
                                    field.text = _struct.pack('<Q', new_ref_id).hex().upper()
                                    updated.append(f"{fname} (bare): {old_id_str}→{new_ref_id}")
                            except Exception:
                                pass

                if updated:
                    print(f"  ✅ {new_entity.name}: {', '.join(updated)}")

            print(f"\n✅ Successfully pasted {len(new_entities)} entities with all relationships preserved")
            return new_entities
            
        except Exception as e:
            print(f"❌ Error pasting entities: {str(e)}")
            import traceback
            traceback.print_exc()
            return []
                    
    def _update_entity_position_in_xml(self, xml_element, new_x, new_y, new_z):
        """Update entity position in XML using the same method as import system"""
        try:
            # Check if this is FCBConverter format (has field elements)
            pos_field = xml_element.find(".//field[@name='hidPos']")
            if pos_field is not None:
                # FCBConverter format
                pos_field.set('value-Vector3', f"{new_x:.0f},{new_y:.0f},{new_z:.0f}")
                # Update binary hex data
                binary_hex = self._coordinates_to_binhex(new_x, new_y, new_z)
                pos_field.text = binary_hex
                print(f"    Updated hidPos (FCB format): ({new_x:.1f}, {new_y:.1f}, {new_z:.1f})")
            else:
                # Dunia Tools format (has value elements)
                pos_elem = xml_element.find(".//value[@name='hidPos']")
                if pos_elem is not None:
                    x_elem = pos_elem.find("./x")
                    y_elem = pos_elem.find("./y")
                    z_elem = pos_elem.find("./z")
                    
                    if x_elem is not None:
                        x_elem.text = f"{new_x:.0f}"
                    if y_elem is not None:
                        y_elem.text = f"{new_y:.0f}"
                    if z_elem is not None:
                        z_elem.text = f"{new_z:.0f}"
                    print(f"    Updated hidPos (Dunia format): ({new_x:.1f}, {new_y:.1f}, {new_z:.1f})")
                else:
                    print(f"    Warning: hidPos field not found in entity XML")
            
            # Also update hidPos_precise if it exists
            pos_precise_field = xml_element.find(".//field[@name='hidPos_precise']")
            if pos_precise_field is not None:
                # FCBConverter format
                pos_precise_field.set('value-Vector3', f"{new_x:.0f},{new_y:.0f},{new_z:.0f}")
                # Update binary hex data
                binary_hex = self._coordinates_to_binhex(new_x, new_y, new_z)
                pos_precise_field.text = binary_hex
                print(f"    Updated hidPos_precise (FCB format): ({new_x:.1f}, {new_y:.1f}, {new_z:.1f})")
            else:
                # Dunia Tools format
                pos_precise_elem = xml_element.find(".//value[@name='hidPos_precise']")
                if pos_precise_elem is not None:
                    x_elem = pos_precise_elem.find("./x")
                    y_elem = pos_precise_elem.find("./y")
                    z_elem = pos_precise_elem.find("./z")
                    
                    if x_elem is not None:
                        x_elem.text = f"{new_x:.0f}"
                    if y_elem is not None:
                        y_elem.text = f"{new_y:.0f}"
                    if z_elem is not None:
                        z_elem.text = f"{new_z:.0f}"
                    print(f"    Updated hidPos_precise (Dunia format): ({new_x:.1f}, {new_y:.1f}, {new_z:.1f})")
            
        except Exception as e:
            print(f"    Error updating entity position: {e}")

    def _coordinates_to_binhex(self, x, y, z):
        """Convert coordinates to BinHex format (same as import system)"""
        try:
            import struct
            binary_data = struct.pack('<fff', float(x), float(y), float(z))
            hex_string = binary_data.hex().upper()
            return hex_string
        except Exception as e:
            print(f"Error converting coordinates to BinHex: {e}")
            return "000000000000000000000000"  # Return zeros on error
    
    def _update_entity_id_in_xml(self, xml_element, new_id):
        """Update entity ID in XML using the same method as import system"""
        try:
            # Check if this is FCBConverter format (has field elements)
            id_field = xml_element.find(".//field[@name='disEntityId']")
            if id_field is not None:
                # FCBConverter format
                id_field.set('value-Id64', str(new_id))
                # Update binary hex data
                binary_hex = self._int64_to_binhex(new_id)
                id_field.text = binary_hex
                print(f"    Updated disEntityId (FCB format): {new_id}")
            else:
                # Dunia Tools format (has value elements)
                id_elem = xml_element.find(".//value[@name='disEntityId']")
                if id_elem is not None:
                    id_elem.text = str(new_id)
                    print(f"    Updated disEntityId (Dunia format): {new_id}")
                else:
                    print(f"    Warning: disEntityId field not found in entity XML")
        except Exception as e:
            print(f"    Error updating entity ID: {e}")

    def _update_entity_name_in_xml(self, xml_element, new_name):
        """Update entity name in XML using the same method as import system"""
        try:
            # Check if this is FCBConverter format (has field elements)
            name_field = xml_element.find(".//field[@name='hidName']")
            if name_field is not None:
                # FCBConverter format
                name_field.set('value-String', new_name)
                # Update binary hex data
                binary_hex = self._string_to_binhex(new_name)
                name_field.text = binary_hex
                print(f"    Updated hidName (FCB format): {new_name}")
            else:
                # Dunia Tools format (has value elements)
                name_elem = xml_element.find(".//value[@name='hidName']")
                if name_elem is not None:
                    name_elem.text = new_name
                    print(f"    Updated hidName (Dunia format): {new_name}")
                else:
                    print(f"    Warning: hidName field not found in entity XML")
        except Exception as e:
            print(f"    Error updating entity name: {e}")

    def _int64_to_binhex(self, value):
        """Convert 64-bit integer to BinHex format"""
        try:
            import struct
            binary_data = struct.pack('<Q', int(value))
            return binary_data.hex().upper()
        except:
            return "0000000000000000"


    def _string_to_binhex(self, text):
        """Convert string to BinHex format"""
        try:
            # Encode string as UTF-8 and add null terminator
            binary_data = text.encode('utf-8') + b'\x00'
            hex_string = binary_data.hex().upper()
            return hex_string
        except Exception as e:
            print(f"Error converting string '{text}' to BinHex: {e}")
            return "00"
    
    def _get_all_existing_entity_ids(self):
        """Get all existing entity IDs to ensure uniqueness"""
        existing_ids = set()
        # This method needs access to the editor's data
        # It will be called with proper context from the bound methods
        return existing_ids

    def _get_all_existing_entity_names(self):
        """Get all existing entity names to ensure uniqueness"""
        existing_names = set()
        # This method needs access to the editor's data
        # It will be called with proper context from the bound methods
        return existing_names

    def _generate_unique_entity_id(self, existing_ids, id_generator=None):
        """Generate a unique entity ID"""
        # Try the provided generator first
        if id_generator:
            for _ in range(100):
                try:
                    new_id = int(id_generator())
                    if new_id not in existing_ids:
                        return new_id
                except:
                    continue
        
        # Fallback: generate based on timestamp and random component
        base_id = int(time.time() * 1000000)
        
        for attempt in range(1000):
            new_id = base_id + random.randint(1000, 999999) + attempt
            
            # Ensure it's in valid range for 64-bit signed integer
            if new_id > 9223372036854775807:
                new_id = random.randint(1000000000000000000, 9000000000000000000)
            
            if new_id not in existing_ids:
                return new_id
        
        # Last resort: simple incremental
        max_id = max(existing_ids) if existing_ids else 1000000000000000000
        return max_id + 1

    def _generate_unique_entity_name(self, original_name, existing_names, name_generator=None):
        """Generate a unique entity name"""
        if name_generator:
            try:
                new_name = name_generator(original_name)
                if new_name not in existing_names:
                    return new_name
            except Exception as e:
                print(f"Name generator error: {e}")
        
        # Default naming strategy: append _Copy_N
        base_name = original_name
        
        # Remove existing _Copy_N suffix if present
        import re
        match = re.match(r'^(.+)_Copy_(\d+)$', original_name)
        if match:
            base_name = match.group(1)
        
        # Try _Copy first
        copy_name = f"{base_name}_Copy"
        if copy_name not in existing_names:
            return copy_name
        
        # Try _Copy_N
        for i in range(1, 1000):
            candidate_name = f"{base_name}_Copy_{i}"
            if candidate_name not in existing_names:
                return candidate_name
        
        # Last resort: add timestamp
        timestamp = int(time.time()) % 100000
        return f"{base_name}_Copy_{timestamp}"
    
    def has_clipboard_data(self):
        """Check if clipboard contains entity data"""
        try:
            clipboard = QApplication.clipboard()
            mime_data = clipboard.mimeData()
            
            if mime_data.hasFormat("application/x-avatar-entities-fcb"):
                return True
            
            if mime_data.hasText():
                try:
                    json_string = mime_data.text()
                    clipboard_data = json.loads(json_string)
                    return clipboard_data.get('type') in ['avatar_entities', 'avatar_entities_fcb']
                except json.JSONDecodeError:
                    pass
            
            return self.clipboard_data is not None
            
        except Exception:
            return False
    
    def get_clipboard_info(self):
        """Get information about clipboard contents"""
        try:
            clipboard = QApplication.clipboard()
            mime_data = clipboard.mimeData()
            
            clipboard_data = None
            
            if mime_data.hasFormat("application/x-avatar-entities-fcb"):
                json_string = mime_data.data("application/x-avatar-entities-fcb").data().decode()
                clipboard_data = json.loads(json_string)
            elif mime_data.hasText():
                try:
                    json_string = mime_data.text()
                    clipboard_data = json.loads(json_string)
                    if clipboard_data.get('type') not in ['avatar_entities', 'avatar_entities_fcb']:
                        clipboard_data = None
                except json.JSONDecodeError:
                    clipboard_data = None
            
            if clipboard_data is None:
                clipboard_data = self.clipboard_data
            
            if clipboard_data is None:
                return None
            
            return {
                'count': clipboard_data.get('count', 0),
                'version': clipboard_data.get('version', 'unknown'),
                'copy_date': clipboard_data.get('copy_date', 'unknown'),
                'entities': [entity['name'] for entity in clipboard_data.get('entities', [])]
            }
            
        except Exception:
            return None


def setup_complete_smart_system(editor):
    """Setup copy/paste system using export/import methodology with Structure children support"""
    print("Setting up enhanced copy/paste system with Structure children support...")
    
    # Initialize clipboard system
    editor.entity_clipboard = EntityClipboard()
    editor.entity_clipboard.editor = editor  # ⭐ CRITICAL: Bind editor reference for entity lookup
    editor.next_entity_id = 3000000000000000000
    editor._remove_entity_from_worldsector_fixed = types.MethodType(_remove_entity_from_worldsector_fixed, editor)
    editor.test_entity_deletion = types.MethodType(test_entity_deletion, editor)
    
    def generate_new_entity_id(self):
        existing_ids = self.get_all_existing_entity_ids()

        while True:
            # Generate a random 63-bit positive integer (fits in signed 64-bit)
            new_id = random.randint(10**18, 9 * 10**18)

            if new_id not in existing_ids:
                return str(new_id)
            
    def generate_unique_entity_name(self, original_name):
        """Generate a unique entity name with smart naming"""
        import re
        
        # Pattern to match existing copy naming
        copy_pattern = r'^(.+?)(?:_Copy(?:_\d+)?)?$'
        match = re.match(copy_pattern, original_name)
        base_name = match.group(1) if match else original_name
        
        # Add timestamp for uniqueness
        timestamp = int(time.time()) % 10000
        return f"{base_name}_Copy_{timestamp}"
    
    def get_all_existing_entity_ids(self):
        """Get all existing entity IDs from editor data"""
        existing_ids = set()
        
        # Check main entities list
        if hasattr(self, 'entities'):
            for entity in self.entities:
                try:
                    entity_id = int(entity.id)
                    existing_ids.add(entity_id)
                except (ValueError, AttributeError):
                    pass
        
        # Check worldsector XML trees for entity IDs
        if hasattr(self, 'worldsectors_trees'):
            for file_path, tree in self.worldsectors_trees.items():
                try:
                    root = tree.getroot()
                    for id_field in root.findall(".//field[@name='disEntityId']"):
                        id_value = id_field.get('value-Id64')
                        if id_value:
                            try:
                                entity_id = int(id_value)
                                existing_ids.add(entity_id)
                            except ValueError:
                                pass
                except Exception as e:
                    print(f"Error scanning {file_path} for entity IDs: {e}")
        
        return existing_ids
    
    def get_all_existing_entity_names(self):
        """Get all existing entity names from editor data"""
        existing_names = set()
        
        # Check main entities list
        if hasattr(self, 'entities'):
            for entity in self.entities:
                if hasattr(entity, 'name') and entity.name:
                    existing_names.add(entity.name)
        
        # Check worldsector XML trees for entity names
        if hasattr(self, 'worldsectors_trees'):
            for file_path, tree in self.worldsectors_trees.items():
                try:
                    root = tree.getroot()
                    for name_field in root.findall(".//field[@name='hidName']"):
                        name_value = name_field.get('value-String')
                        if name_value:
                            existing_names.add(name_value)
                except Exception as e:
                    print(f"Error scanning {file_path} for entity names: {e}")
        
        return existing_names
    
    def copy_selected_entities(self):
        if not hasattr(self, 'canvas') or not hasattr(self.canvas, 'selected'):
            return False
            
        selected_entities = getattr(self.canvas, 'selected', [])
        if not selected_entities:
            self.status_bar.showMessage("No entities selected to copy")
            return False
        
        success = self.entity_clipboard.copy_entities(selected_entities)
        if success:
            self.status_bar.showMessage(f"Copied {len(selected_entities)} entities to clipboard")
        else:
            self.status_bar.showMessage("Failed to copy entities")
        
        return success
    
    def _add_entity_to_main_level_file(self, entity):
        """Insert a pasted entity into the correct MissionLayer of its original main-level file.

        Layer resolution order:
          1. entity.source_layer (set at load time from MissionLayer text_PathId)
          2. text_hidMissionLayerPath inside the entity's xml_element
          3. First MissionLayer in the file
          4. Root element (last resort — no MissionLayer present)
        """
        _TREE_MAP = {
            'mapsdata':   ('xml_tree',       'xml_tree_modified'),
            'omnis':      ('omnis_tree',      'omnis_tree_modified'),
            'managers':   ('managers_tree',   'managers_tree_modified'),
            'sectorsdep': ('sectordep_tree',  'sectordep_tree_modified'),
        }
        src = getattr(entity, 'source_file', '')
        mapping = _TREE_MAP.get(src)
        if not mapping:
            return False

        tree_attr, flag_attr = mapping
        tree = getattr(self, tree_attr, None)
        if tree is None:
            print(f"  ⚠️ {tree_attr} not loaded — cannot paste entity into {src}")
            return False

        root = tree.getroot()

        # Determine the target layer name
        layer_name = getattr(entity, 'source_layer', None) or ''
        if not layer_name and entity.xml_element is not None:
            ml_field = entity.xml_element.find(".//field[@name='text_hidMissionLayerPath']")
            if ml_field is not None:
                layer_name = ml_field.get('value-String', '').strip()

        # Find the matching MissionLayer element
        entity_container = None
        if layer_name:
            for ml_elem in root.findall("./object[@name='MissionLayer']"):
                pf = ml_elem.find("./field[@name='text_PathId']")
                if pf is not None and pf.get('value-String', '') == layer_name:
                    entity_container = ml_elem
                    break
            if entity_container is None:
                print(f"  ⚠️ MissionLayer '{layer_name}' not found in {src}, falling back to first")

        # Fallback: first MissionLayer
        if entity_container is None:
            entity_container = root.find("./object[@name='MissionLayer']")

        # Last resort: root
        if entity_container is None:
            entity_container = root

        layer_label = layer_name or entity_container.get('name', 'root')
        entity_container.append(copy.deepcopy(entity.xml_element))
        setattr(self, flag_attr, True)
        print(f"  ✅ Added to {src} / MissionLayer '{layer_label}'")
        return True

    def paste_entities(self, target_position=None, at_cursor=False):
        """Paste entities using import methodology with automatic +20 X/Y offset or cursor position - WITH SAFETY CHECKS"""
        
        print(f"\n{'='*70}")
        print(f"PASTE SAFETY CHECK - STARTING")
        print(f"{'='*70}")
        
        # CRITICAL: Store all original entity states BEFORE paste
        original_states = {}
        for entity in self.entities:
            original_states[id(entity)] = {  # Use Python object id as key
                'entity_obj': entity,
                'x': entity.x,
                'y': entity.y,
                'z': entity.z,
                'id': entity.id,
                'name': entity.name
            }
        
        print(f"📌 Saved {len(original_states)} original entity states")
        
        # Calculate target position if pasting at cursor
        if at_cursor and hasattr(self, 'canvas') and hasattr(self.canvas, 'last_mouse_world_pos'):
            target_position = self.canvas.last_mouse_world_pos
        
        # Bind the helper methods to the clipboard so it can access editor data
        self.entity_clipboard._get_all_existing_entity_ids = lambda: self.get_all_existing_entity_ids()
        self.entity_clipboard._get_all_existing_entity_names = lambda: self.get_all_existing_entity_names()
        
        # If no target position specified, apply automatic +20 X/Y offset
        if target_position is None:
            # Get clipboard data to calculate offset from first entity
            clipboard_data = None
            try:
                from PyQt6.QtWidgets import QApplication
                clipboard = QApplication.clipboard()
                mime_data = clipboard.mimeData()
                
                if mime_data.hasFormat("application/x-avatar-entities-fcb"):
                    json_string = mime_data.data("application/x-avatar-entities-fcb").data().decode()
                    clipboard_data = json.loads(json_string)
                elif mime_data.hasText():
                    try:
                        json_string = mime_data.text()
                        clipboard_data = json.loads(json_string)
                        if not (clipboard_data.get('type') in ['avatar_entities', 'avatar_entities_fcb'] and 'entities' in clipboard_data):
                            clipboard_data = None
                    except json.JSONDecodeError:
                        clipboard_data = None
                
                if clipboard_data is None:
                    clipboard_data = self.entity_clipboard.clipboard_data
                
                # Calculate automatic offset position
                if clipboard_data and clipboard_data.get('entities'):
                    first_entity = clipboard_data['entities'][0]
                    target_position = (
                        first_entity['x'] + 20,  # +20 on X axis
                        first_entity['y'] + 20,  # +20 on Y axis  
                        first_entity['z']        # Keep Z the same
                    )
                    print(f"Auto-offsetting paste by +20 X/Y: {target_position}")
            except Exception as e:
                print(f"Error calculating auto-offset: {e}")
                target_position = None
        
        # Use import-style pasting
        new_entities = self.entity_clipboard.paste_entities(
            target_position=target_position,
            id_generator=self.generate_new_entity_id,
            name_generator=self.generate_unique_entity_name
        )
        
        if not new_entities:
            self.status_bar.showMessage("No entities to paste")
            
            # Still verify originals even on failure
            print(f"\n{'='*70}")
            print(f"VERIFYING ORIGINALS AFTER FAILED PASTE")
            print(f"{'='*70}")
            
            corrupted = False
            for obj_id, original_state in original_states.items():
                entity = original_state['entity_obj']
                if (entity.x != original_state['x'] or entity.y != original_state['y'] or 
                    entity.z != original_state['z'] or entity.id != original_state['id'] or 
                    entity.name != original_state['name']):
                    print(f"🚨 BUG: Original {original_state['name']} was modified!")
                    corrupted = True
            
            if not corrupted:
                print(f"✅ All originals safe after failed paste")
            
            return []
        
        print(f"\n=== ADDING PASTED ENTITIES TO EDITOR ===")
        
        # Process each entity using import-style approach
        successfully_added = []
        for i, entity in enumerate(new_entities):
            print(f"\nProcessing entity {i+1}: {entity.name}")
            print(f"  Entity ID: {entity.id}")
            print(f"  Position: ({entity.x}, {entity.y}, {entity.z})")
            print(f"  Has XML element: {hasattr(entity, 'xml_element') and entity.xml_element is not None}")
            
            # Add to main entities list
            self.entities.append(entity)
            
            # Add to XML — route by source_file: main-level files stay in their file,
            # worldsector entities go to the position-matched sector.
            if hasattr(entity, 'xml_element') and entity.xml_element is not None:
                src = getattr(entity, 'source_file', '')
                if src in ('mapsdata', 'omnis', 'managers', 'sectorsdep'):
                    print(f"  Routing to main-level file: {src}")
                    success = self._add_entity_to_main_level_file(entity)
                    if not success:
                        print(f"  ⚠️ Failed to add to {src}, entity still in memory list")
                    successfully_added.append(entity)
                else:
                    # Find target worldsector file using position-based lookup in unified mode
                    target_sector_file, target_sector_id = self._find_best_worldsector_for_entity(entity)

                    if target_sector_file:
                        print(f"  Adding to worldsector: {os.path.basename(target_sector_file)}")

                        # Use the same method as import system
                        success = self._add_entity_xml_to_sector(entity.xml_element, target_sector_file)
                        if success:
                            entity.source_file_path = target_sector_file
                            entity.source_file = "worldsectors"
                            entity.source_sector_id = target_sector_id
                            # Keep source_layer from copy data (already set during paste)
                            # Mark the sector dirty so unified save picks it up
                            if target_sector_id >= 0 and hasattr(self, 'canvas'):
                                self.canvas.dirty_sectors.add(target_sector_id)
                            successfully_added.append(entity)
                            print(f"  ✅ Successfully added to worldsector (sector_id={target_sector_id})")
                        else:
                            print(f"  ⚠️ Failed to add to worldsector, but entity added to main list")
                            successfully_added.append(entity)
                    else:
                        print(f"  ⚠️ No suitable worldsector found, adding to main list only")
                        successfully_added.append(entity)
            else:
                print(f"  Entity has no XML element, adding to main list only")
                successfully_added.append(entity)
        
        # Assign 3D models to the new entities so they appear immediately in 3D mode
        if hasattr(self, 'canvas') and hasattr(self.canvas, 'model_loader') and new_entities:
            try:
                self.canvas.model_loader.assign_models_to_entities(
                    new_entities,
                    game_mode=getattr(self, 'game_mode', 'avatar')
                )
            except Exception as _me:
                print(f"Warning: could not assign models to pasted entities: {_me}")

        # Update UI (center_view=False: paste doesn't reset camera)
        self.canvas.set_entities(self.entities, center_view=False)
        if hasattr(self, 'update_entity_tree'):
            self.update_entity_tree()

        # Select the pasted entities
        self.canvas.selected = new_entities
        self.canvas.selected_entity = new_entities[0] if new_entities else None
        self.selected_entity = self.canvas.selected_entity

        self.canvas.update()
        if hasattr(self, 'update_ui_for_selected_entity'):
            self.update_ui_for_selected_entity(self.selected_entity)
        
        self.status_bar.showMessage(f"Pasted {len(successfully_added)} entities")
        print(f"=== PASTE COMPLETE: {len(successfully_added)} entities ===\n")
        
        # VERIFY: Check if originals were modified during paste
        print(f"\n{'='*70}")
        print(f"VERIFYING ORIGINALS AFTER PASTE")
        print(f"{'='*70}")
        
        corrupted = False
        for obj_id, original_state in original_states.items():
            entity = original_state['entity_obj']
            
            # Check if this entity is still in the original list (not a new one)
            if entity not in new_entities:
                if (entity.x != original_state['x'] or 
                    entity.y != original_state['y'] or
                    entity.z != original_state['z'] or
                    entity.id != original_state['id'] or
                    entity.name != original_state['name']):
                    
                    print(f"🚨 BUG DETECTED: Original entity was MODIFIED during paste!")
                    print(f"  Entity: {original_state['name']}")
                    print(f"  Position: ({original_state['x']:.1f}, {original_state['y']:.1f}, {original_state['z']:.1f}) → ({entity.x:.1f}, {entity.y:.1f}, {entity.z:.1f})")
                    print(f"  ID: {original_state['id']} → {entity.id}")
                    print(f"  Name: {original_state['name']} → {entity.name}")
                    corrupted = True
                else:
                    print(f"✅ Original {entity.name} unchanged")
        
        if corrupted:
            print(f"\n🚨 CRITICAL BUG: Original entities were corrupted during paste!")
            print(f"   The paste operation modified entities it shouldn't have touched!")
        else:
            print(f"\n✅ SUCCESS: All original entities remain unchanged - paste is safe!")
        
        return new_entities

    def _find_best_worldsector_for_entity(self, entity):
        """Find the best worldsector file for an entity.

        In unified mode uses position-based lookup with the same formula as save
        routing: gx = floor(x / 64), gy = floor(y / 64), sector_id = gy*16+gx.
        Falls back to the first available file when no sector matches.

        Returns (xml_path, sector_id) tuple, or (None, -1) if no files are loaded.
        """
        x, y = entity.x, entity.y
        print(f"🎯 Finding target worldsector for {entity.name} at ({x}, {y})")

        if not hasattr(self, 'worldsectors_trees'):
            self.worldsectors_trees = {}

        available_files = list(self.worldsectors_trees.keys()) if self.worldsectors_trees else []
        print(f"🗂️ Available worldsector files: {len(available_files)}")

        if not available_files:
            print("❌ No worldsector files loaded")
            return (None, -1)

        # Build known_sectors map (sector_id → (gx, gy, xml_path)) — mirrors save routing
        known_sectors = {}
        for xml_path, tree in self.worldsectors_trees.items():
            if not xml_path.endswith('.converted.xml'):
                continue
            root = tree.getroot()
            gx = gy = 0
            xf = root.find("./field[@name='X']")
            if xf is not None:
                try:
                    gx = int(xf.get('value-Int32', 0))
                except (ValueError, TypeError):
                    pass
            yf = root.find("./field[@name='Y']")
            if yf is not None:
                try:
                    gy = int(yf.get('value-Int32', 0))
                except (ValueError, TypeError):
                    pass
            known_sectors[gy * 16 + gx] = (gx, gy, xml_path)

        # Position-based lookup (unified mode primary path)
        if known_sectors:
            target_gx = int(x // 64)
            target_gy = int(y // 64)
            target_id = target_gy * 16 + target_gx
            if target_id in known_sectors:
                _, _, xml_path = known_sectors[target_id]
                print(f"📁 Position-based match: sector ({target_gx},{target_gy}) → {os.path.basename(xml_path)}")
                return (xml_path, target_id)
            print(f"⚠️ No sector at grid ({target_gx},{target_gy}), falling back to first file")

        # Fallback: first available file
        fallback_file = available_files[0]
        fallback_id = -1
        for sid, (_, _, xml_path) in known_sectors.items():
            if xml_path == fallback_file:
                fallback_id = sid
                break
        print(f"📁 Using fallback worldsector file: {os.path.basename(fallback_file)}")
        return (fallback_file, fallback_id)

    def _add_entity_xml_to_sector(self, entity_xml, sector_file_path):
        """Add entity XML to MissionLayer - prefers 'outside_entity', falls back to 'main'"""
        try:
            # Load the target file if not already loaded
            if not hasattr(self, 'worldsectors_trees'):
                self.worldsectors_trees = {}
            
            if sector_file_path not in self.worldsectors_trees:
                if os.path.exists(sector_file_path):
                    tree = ET.parse(sector_file_path)
                    self.worldsectors_trees[sector_file_path] = tree
                else:
                    print(f"Sector file does not exist: {sector_file_path}")
                    return False
            
            tree = self.worldsectors_trees[sector_file_path]
            root = tree.getroot()
            
            # Find ALL MissionLayers
            mission_layers = root.findall(".//object[@name='MissionLayer']")
            if not mission_layers:
                print(f"No MissionLayer found in {sector_file_path}")
                return False
            
            print(f"Found {len(mission_layers)} MissionLayer(s) in file")
            
            # Search for MissionLayers - try "outside_entity" first, then "main"
            target_mission_layer = None
            target_path_id = None
            
            for preferred_id in ["outside_entity", "main"]:
                for mission_layer in mission_layers:
                    # Check text_PathId field (FCBConverter format)
                    path_id_field = mission_layer.find("field[@name='text_PathId']")
                    if path_id_field is not None:
                        path_id_value = path_id_field.get('value-String', '')
                        if path_id_value == preferred_id:
                            target_mission_layer = mission_layer
                            target_path_id = preferred_id
                            print(f"✅ Found target MissionLayer: {preferred_id}")
                            break
                    
                    # Also check Dunia Tools format (value element)
                    path_id_elem = mission_layer.find("value[@name='text_PathId']")
                    if path_id_elem is not None:
                        path_id_value = path_id_elem.text or ''
                        if path_id_value == preferred_id:
                            target_mission_layer = mission_layer
                            target_path_id = preferred_id
                            print(f"✅ Found target MissionLayer: {preferred_id}")
                            break
                
                # If we found a layer, stop searching
                if target_mission_layer is not None:
                    break
            
            if target_mission_layer is None:
                print(f"❌ No MissionLayer with PathId='outside_entity' or 'main' found in {sector_file_path}")
                print(f"Available MissionLayers:")
                for ml in mission_layers:
                    path_field = ml.find("field[@name='text_PathId']")
                    if path_field is not None:
                        print(f"  - {path_field.get('value-String', 'unknown')}")
                    else:
                        path_elem = ml.find("value[@name='text_PathId']")
                        if path_elem is not None:
                            print(f"  - {path_elem.text or 'unknown'}")
                return False
            
            # Count existing entities BEFORE adding
            existing_entities = target_mission_layer.findall("object[@name='Entity']")
            print(f"MissionLayer '{target_path_id}' currently has {len(existing_entities)} entities")
            
            # CRITICAL FIX: Create truly independent copy
            print(f"🔧 Creating independent copy of entity XML...")
            xml_string = ET.tostring(entity_xml, encoding='unicode')
            entity_copy = ET.fromstring(xml_string)
            
            # IMPORTANT: Insert the entity at the END of the MissionLayer's children
            # Find the last Entity index to insert after all other entities
            last_entity_index = -1
            for i, child in enumerate(target_mission_layer):
                if child.tag == 'object' and child.get('name') == 'Entity':
                    last_entity_index = i
            
            if last_entity_index >= 0:
                # Insert after the last entity
                insert_position = last_entity_index + 1
                print(f"🔧 Inserting entity at position {insert_position} (after last entity)")
                target_mission_layer.insert(insert_position, entity_copy)
            else:
                # No entities yet, append at end
                print(f"🔧 Appending entity (first entity in layer)")
                target_mission_layer.append(entity_copy)
            
            # Verify the entity was added correctly
            new_entities = target_mission_layer.findall("object[@name='Entity']")
            print(f"MissionLayer '{target_path_id}' now has {len(new_entities)} entities")
            
            if len(new_entities) <= len(existing_entities):
                print(f"❌ Entity was not added correctly!")
                print(f"Expected: {len(existing_entities) + 1}, Got: {len(new_entities)}")
                
                # Debug: Check what's in the MissionLayer
                print(f"🔍 Debug - MissionLayer children:")
                for i, child in enumerate(target_mission_layer):
                    print(f"  {i}: {child.tag}, name={child.get('name', 'N/A')}")
                
                return False
            
            print(f"✅ Successfully added entity to '{target_path_id}' MissionLayer")
            
            # CRITICAL: Use indent() to properly format the XML before saving
            print(f"🔧 Formatting XML with proper indentation...")
            try:
                # Python 3.9+ has indent() built-in
                ET.indent(tree, space="  ")
            except AttributeError:
                # Fallback for older Python versions
                self._indent_xml(root)
            
            # Save the file immediately
            print(f"💾 Writing to file: {sector_file_path}")
            tree.write(sector_file_path, encoding='utf-8', xml_declaration=True)
            print(f"💾 Saved {os.path.basename(sector_file_path)}")
            
            # Mark as modified
            if not hasattr(self, 'worldsectors_modified'):
                self.worldsectors_modified = {}
            self.worldsectors_modified[sector_file_path] = True
            
            return True
            
        except Exception as e:
            print(f"❌ Error adding entity to sector: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _indent_xml(self, elem, level=0):
        """Fallback XML indentation for Python < 3.9"""
        i = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + "  "
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
            for child in elem:
                self._indent_xml(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

    def duplicate_selected_entities(self):
        """Duplicate selected entities with +20 X/Y offset and unique names (includes Structure children) - WITH SAFETY CHECKS"""
        if not hasattr(self, 'canvas') or not hasattr(self.canvas, 'selected'):
            return False
            
        selected_entities = getattr(self.canvas, 'selected', [])
        if not selected_entities:
            self.status_bar.showMessage("No entities selected to duplicate")
            return False
        
        print(f"\n{'='*70}")
        print(f"DUPLICATE SAFETY CHECK - STARTING")
        print(f"{'='*70}")
        print(f"Duplicating {len(selected_entities)} selected entities...")
        
        # CRITICAL: Store all original entity states BEFORE duplication
        original_states = {}
        for entity in self.entities:
            original_states[id(entity)] = {  # Use Python object id as key
                'entity_obj': entity,
                'x': entity.x,
                'y': entity.y,
                'z': entity.z,
                'id': entity.id,
                'name': entity.name
            }
        
        print(f"📌 Saved {len(original_states)} original entity states before duplication")
        
        # Also specifically track the selected entities
        selected_states = {}
        for entity in selected_entities:
            selected_states[id(entity)] = {
                'entity_obj': entity,
                'x': entity.x,
                'y': entity.y,
                'z': entity.z,
                'id': entity.id,
                'name': entity.name
            }
            print(f"📌 Selected: {entity.name} at ({entity.x:.1f}, {entity.y:.1f}, {entity.z:.1f}), ID={entity.id}")
        
        try:
            # Copy to clipboard (this automatically includes Structure children)
            print(f"\n=== STEP 1: COPYING TO CLIPBOARD ===")
            success = self.entity_clipboard.copy_entities(selected_entities)
            if not success:
                self.status_bar.showMessage("Failed to copy entities for duplication")
                print(f"❌ Copy failed")
                return False
            
            # VERIFY: Check if originals were modified during copy
            print(f"\n{'='*70}")
            print(f"VERIFYING ORIGINALS AFTER COPY (Step 1)")
            print(f"{'='*70}")
            
            corrupted_in_copy = False
            for obj_id, original_state in selected_states.items():
                entity = original_state['entity_obj']
                if (entity.x != original_state['x'] or entity.y != original_state['y'] or 
                    entity.z != original_state['z'] or entity.id != original_state['id'] or 
                    entity.name != original_state['name']):
                    print(f"🚨 BUG: Selected entity {original_state['name']} was modified during copy!")
                    print(f"   Position: ({original_state['x']:.1f}, {original_state['y']:.1f}) → ({entity.x:.1f}, {entity.y:.1f})")
                    print(f"   ID: {original_state['id']} → {entity.id}")
                    print(f"   Name: {original_state['name']} → {entity.name}")
                    corrupted_in_copy = True
                else:
                    print(f"✅ {entity.name} unchanged after copy")
            
            if corrupted_in_copy:
                print(f"\n🚨 CRITICAL BUG: Copy operation corrupted originals!")
                self.status_bar.showMessage("Error: Copy corrupted original entities")
                return False
            else:
                print(f"\n✅ All selected entities safe after copy")
            
            # Get info about what was actually copied (includes children)
            clipboard_info = self.entity_clipboard.get_clipboard_info()
            if clipboard_info:
                total_count = clipboard_info.get('count', len(selected_entities))
                print(f"\n📋 Clipboard contains {total_count} entities (including Structure children)")
            
            # Calculate offset position (+20 X/Y from first selected entity)
            offset_position = None
            if selected_entities:
                first_entity = selected_entities[0]
                offset_position = (
                    first_entity.x + 20,  # +20 on X axis
                    first_entity.y + 20,  # +20 on Y axis
                    first_entity.z        # Keep Z the same
                )
                print(f"\n=== STEP 2: PASTING WITH OFFSET ===")
                print(f"Duplicating with +20 X/Y offset: ({offset_position[0]:.1f}, {offset_position[1]:.1f}, {offset_position[2]:.1f})")
            
            # Paste with offset (this will paste all entities including children)
            new_entities = self.paste_entities(target_position=offset_position)
            
            if not new_entities:
                self.status_bar.showMessage("Failed to duplicate entities")
                print(f"❌ Paste failed")
                
                # Still verify originals
                print(f"\n{'='*70}")
                print(f"VERIFYING ORIGINALS AFTER FAILED PASTE")
                print(f"{'='*70}")
                
                corrupted = False
                for obj_id, original_state in selected_states.items():
                    entity = original_state['entity_obj']
                    if (entity.x != original_state['x'] or entity.y != original_state['y'] or 
                        entity.z != original_state['z'] or entity.id != original_state['id'] or 
                        entity.name != original_state['name']):
                        print(f"🚨 BUG: {original_state['name']} was modified!")
                        corrupted = True
                
                if not corrupted:
                    print(f"✅ All originals safe after failed paste")
                
                return False
            
            # VERIFY: Check if originals were modified during paste
            print(f"\n{'='*70}")
            print(f"VERIFYING ORIGINALS AFTER PASTE (Step 2)")
            print(f"{'='*70}")
            
            corrupted_in_paste = False
            for obj_id, original_state in selected_states.items():
                entity = original_state['entity_obj']
                
                # Make sure this isn't one of the new entities
                if entity not in new_entities:
                    if (entity.x != original_state['x'] or entity.y != original_state['y'] or 
                        entity.z != original_state['z'] or entity.id != original_state['id'] or 
                        entity.name != original_state['name']):
                        print(f"🚨 BUG: Original selected entity {original_state['name']} was modified during paste!")
                        print(f"   Position: ({original_state['x']:.1f}, {original_state['y']:.1f}) → ({entity.x:.1f}, {entity.y:.1f})")
                        print(f"   ID: {original_state['id']} → {entity.id}")
                        print(f"   Name: {original_state['name']} → {entity.name}")
                        corrupted_in_paste = True
                    else:
                        print(f"✅ Original {entity.name} unchanged after paste")
            
            # Also check if ANY entity in the scene was modified
            print(f"\n--- Checking ALL entities in scene ---")
            any_corrupted = False
            for obj_id, original_state in original_states.items():
                entity = original_state['entity_obj']
                
                # Skip new entities
                if entity not in new_entities:
                    if (entity.x != original_state['x'] or entity.y != original_state['y'] or 
                        entity.z != original_state['z'] or entity.id != original_state['id'] or 
                        entity.name != original_state['name']):
                        
                        # Only report if it's not in the selected list (we already reported those)
                        if id(entity) not in selected_states:
                            print(f"🚨 BUG: Unrelated entity {original_state['name']} was modified!")
                            print(f"   This entity was NOT selected but was still modified!")
                            print(f"   Position: ({original_state['x']:.1f}, {original_state['y']:.1f}) → ({entity.x:.1f}, {entity.y:.1f})")
                            any_corrupted = True
            
            if corrupted_in_paste or any_corrupted:
                print(f"\n🚨 CRITICAL BUG: Duplication modified original entities!")
                self.status_bar.showMessage("Warning: Duplication may have corrupted originals")
            else:
                print(f"\n✅ SUCCESS: All original entities remain unchanged!")
            
            # Count results
            original_count = len(selected_entities)
            total_count = len(new_entities)
            
            # Display summary
            print(f"\n{'='*70}")
            print(f"DUPLICATION COMPLETE")
            print(f"{'='*70}")
            print(f"Original selection: {original_count} entities")
            print(f"Total duplicated: {total_count} entities (including children)")
            print(f"New entities created:")
            for entity in new_entities:
                print(f"  - {entity.name} at ({entity.x:.1f}, {entity.y:.1f}, {entity.z:.1f}), ID={entity.id}")
            
            if total_count > original_count:
                message = f"Duplicated {original_count} entities + {total_count - original_count} children = {total_count} total"
            else:
                message = f"Duplicated {total_count} entities"
            
            self.status_bar.showMessage(message)
            print(f"✅ {message}")
            return True
            
        except Exception as e:
            print(f"\n❌ Exception during duplication: {str(e)}")
            import traceback
            traceback.print_exc()
            
            # Still verify originals on exception
            print(f"\n{'='*70}")
            print(f"VERIFYING ORIGINALS AFTER EXCEPTION")
            print(f"{'='*70}")
            
            for obj_id, original_state in selected_states.items():
                entity = original_state['entity_obj']
                if (entity.x != original_state['x'] or entity.y != original_state['y'] or 
                    entity.z != original_state['z'] or entity.id != original_state['id'] or 
                    entity.name != original_state['name']):
                    print(f"🚨 {original_state['name']} was modified!")
            
            self.status_bar.showMessage(f"Error during duplication: {str(e)}")
            return False
            
    def delete_selected_entities(self):
        """Delete selected entities from both memory and XML (includes Structure children AND main XML files)"""
        if not hasattr(self, 'canvas') or not hasattr(self.canvas, 'selected'):
            return False
            
        selected_entities = getattr(self.canvas, 'selected', [])
        if not selected_entities:
            self.status_bar.showMessage("No entities selected to delete")
            return False
        
        print(f"\n🗑️ COLLECTING ENTITIES FOR DELETION...")
        
        # Build a dictionary of all entities by ID for quick lookup
        entities_dict = {}
        if hasattr(self, 'entities'):
            for entity in self.entities:
                entities_dict[entity.id] = entity
        
        # Collect all entities to delete including Structure children
        all_entities_to_delete = []
        already_included = set()
        
        for entity in selected_entities:
            if entity.id not in already_included:
                all_entities_to_delete.append(entity)
                already_included.add(entity.id)
                print(f"  ✓ Marked for deletion: {entity.name}")
                
                # Check if this is a Structure/Prefab entity
                if hasattr(entity, 'xml_element') and entity.xml_element is not None:
                    entity_class_field = entity.xml_element.find(".//field[@name='text_hidEntityClass']")
                    if entity_class_field is not None:
                        entity_class = entity_class_field.get('value-String', '')
                        
                        if 'Prefab' in entity_class or 'Structure' in entity.name:
                            print(f"    → This is a Structure/Prefab, checking for children...")
                            
                            # Find children to delete
                            children_obj = entity.xml_element.find(".//object[@name='Children']")
                            if children_obj is not None:
                                child_objects = children_obj.findall("object[@name='Child']")
                                
                                for child_obj in child_objects:
                                    id_field = child_obj.find("field[@name='ID']")
                                    name_field = child_obj.find("field[@name='Name']")
                                    
                                    if id_field is not None:
                                        child_id = id_field.get('value-Hash64')
                                        child_name = name_field.get('value-String') if name_field is not None else 'unknown'
                                        
                                        # Find the actual child entity
                                        if child_id in entities_dict:
                                            child_entity = entities_dict[child_id]
                                            if child_entity.id not in already_included:
                                                all_entities_to_delete.append(child_entity)
                                                already_included.add(child_entity.id)
                                                print(f"      ✓ Marked child for deletion: {child_name}")
                                        elif child_name:
                                            # Try to find by name as fallback
                                            for ent_id, ent in entities_dict.items():
                                                if ent.name == child_name and ent.id not in already_included:
                                                    all_entities_to_delete.append(ent)
                                                    already_included.add(ent.id)
                                                    print(f"      ✓ Marked child for deletion by name: {child_name}")
                                                    break
                                
                                if len(all_entities_to_delete) > len(selected_entities):
                                    child_count = len(all_entities_to_delete) - len(selected_entities)
                                    print(f"    → Structure has {child_count} children that will be deleted")
        
        original_count = len(selected_entities)
        total_count = len(all_entities_to_delete)
        
        print(f"\n📊 Total entities to delete: {total_count} (selected: {original_count}, children: {total_count - original_count})")
        
        # Show confirmation dialog with child count
        if total_count > original_count:
            message = (f"Are you sure you want to delete {original_count} entities?\n\n"
                    f"This includes {total_count - original_count} Structure children for a total of {total_count} entities.\n\n"
                    f"This will remove them from both the display and the XML files.")
        else:
            message = (f"Are you sure you want to delete {total_count} entities?\n\n"
                    f"This will remove them from both the display and the XML files.")
        
        reply = QMessageBox.question(
            self,
            "Delete Entities",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return False
        
        print(f"\n🗑️ DELETING {total_count} entities...")
        
        deleted_count = 0
        
        # Remove entities from ALL XML sources
        for entity in all_entities_to_delete:
            print(f"\n🗑️ Processing deletion of: {entity.name}")
            
            # Determine source and remove from appropriate XML tree
            source_file = getattr(entity, 'source_file', None)
            source_file_path = getattr(entity, 'source_file_path', None)
            
            removed_from_xml = False
            
            # 1. Try to remove from landmark XML — checked BEFORE worldsectors because
            #    landmark files live inside the worldsectors folder, so a full-path
            #    'worldsector' substring check would also match landmark paths.
            if source_file == 'landmark' or (source_file_path and 'landmark' in os.path.basename(source_file_path or '').lower()):
                lm_trees = getattr(self, 'landmark_trees', {})
                # Normalise paths for Windows case/separator variance before looking up
                lm_tree_key = None
                if lm_trees and source_file_path:
                    norm_sfp = os.path.normcase(os.path.normpath(source_file_path))
                    for k in lm_trees:
                        if os.path.normcase(os.path.normpath(k)) == norm_sfp:
                            lm_tree_key = k
                            break
                if lm_tree_key is not None:
                    print(f"  Removing from landmark XML: {os.path.basename(lm_tree_key)}")
                    try:
                        success = self._remove_entity_from_landmark_tree(entity, lm_tree_key)
                        if success:
                            print(f"  ✅ Successfully removed from landmark XML")
                            removed_from_xml = True
                        else:
                            print(f"  ⚠️ Failed to remove from landmark XML (entity not found in tree)")
                    except Exception as e:
                        print(f"  ❌ Error removing from landmark XML: {e}")
                else:
                    if not lm_trees:
                        print(f"  ⚠️ landmark_trees is empty — landmark file was not loaded into memory")
                    elif not source_file_path:
                        print(f"  ⚠️ entity has no source_file_path — cannot find landmark tree")
                    else:
                        print(f"  ⚠️ landmark path not found in landmark_trees: {source_file_path}")
                        print(f"       Available keys: {[os.path.basename(k) for k in lm_trees]}")

            # 2. Try to remove from worldsector XML
            elif source_file == 'worldsectors' or (source_file_path and 'worldsector' in source_file_path.lower()):
                if hasattr(self, 'worldsectors_trees') and source_file_path in self.worldsectors_trees:
                    print(f"  Removing from worldsector XML: {os.path.basename(source_file_path)}")
                    try:
                        success = self._remove_entity_from_worldsector_fixed(entity)
                        if success:
                            print(f"  ✅ Successfully removed from worldsector XML")
                            removed_from_xml = True
                            # Mark the sector dirty so FCB conversion runs on save
                            src_sid = getattr(entity, 'source_sector_id', -1)
                            if src_sid >= 0 and hasattr(self, 'canvas'):
                                self.canvas.dirty_sectors.add(src_sid)
                        else:
                            print(f"  ⚠️ Failed to remove from worldsector XML")
                    except Exception as e:
                        print(f"  ❌ Error removing from worldsector XML: {e}")

            # 3. Try to remove from main mapsdata XML
            elif source_file == 'mapsdata' or source_file is None:
                if hasattr(self, 'xml_tree') and self.xml_tree is not None:
                    print(f"  Removing from mapsdata XML")
                    try:
                        success = self._remove_entity_from_main_xml(entity, self.xml_tree)
                        if success:
                            print(f"  ✅ Successfully removed from mapsdata XML")
                            self.xml_tree_modified = True
                            removed_from_xml = True
                        else:
                            print(f"  ⚠️ Failed to remove from mapsdata XML")
                    except Exception as e:
                        print(f"  ❌ Error removing from mapsdata XML: {e}")
            
            # 3. Try to remove from omnis XML
            elif source_file == 'omnis':
                if hasattr(self, 'omnis_tree') and self.omnis_tree is not None:
                    print(f"  Removing from omnis XML")
                    try:
                        success = self._remove_entity_from_main_xml(entity, self.omnis_tree)
                        if success:
                            print(f"  ✅ Successfully removed from omnis XML")
                            self.omnis_tree_modified = True
                            removed_from_xml = True
                        else:
                            print(f"  ⚠️ Failed to remove from omnis XML")
                    except Exception as e:
                        print(f"  ❌ Error removing from omnis XML: {e}")
            
            # 4. Try to remove from managers XML
            elif source_file == 'managers':
                if hasattr(self, 'managers_tree') and self.managers_tree is not None:
                    print(f"  Removing from managers XML")
                    try:
                        success = self._remove_entity_from_main_xml(entity, self.managers_tree)
                        if success:
                            print(f"  ✅ Successfully removed from managers XML")
                            self.managers_tree_modified = True
                            removed_from_xml = True
                        else:
                            print(f"  ⚠️ Failed to remove from managers XML")
                    except Exception as e:
                        print(f"  ❌ Error removing from managers XML: {e}")
            
            # 5. Try to remove from sectorsdep XML
            elif source_file == 'sectorsdep' or source_file == 'sectorsdep':
                if hasattr(self, 'sectordep_tree') and self.sectordep_tree is not None:
                    print(f"  Removing from sectordep XML")
                    try:
                        success = self._remove_entity_from_main_xml(entity, self.sectordep_tree)
                        if success:
                            print(f"  ✅ Successfully removed from sectordep XML")
                            self.sectordep_tree_modified = True
                            removed_from_xml = True
                        else:
                            print(f"  ⚠️ Failed to remove from sectordep XML")
                    except Exception as e:
                        print(f"  ❌ Error removing from sectordep XML: {e}")
            
            # Log if entity wasn't removed from any XML
            if not removed_from_xml:
                print(f"  ⚠️ Entity was not removed from any XML file (source: {source_file})")
            
            # Remove from main entities list (memory)
            if entity in self.entities:
                self.entities.remove(entity)
                deleted_count += 1
                print(f"  ✅ Removed from main entities list")
            else:
                print(f"  ⚠️ Entity not found in main entities list")
        
        # Clear selection
        self.canvas.selected = []
        self.canvas.selected_entity = None
        self.selected_entity = None

        # Update UI — don't recentre the camera after a delete
        self.canvas.set_entities(self.entities, center_view=False)
        if hasattr(self, 'update_entity_tree'):
            self.update_entity_tree()

        self.canvas.update()

        # Show detailed status message
        if deleted_count > original_count:
            message = f"Deleted {original_count} entities + {deleted_count - original_count} children = {deleted_count} total"
        else:
            message = f"Deleted {deleted_count} entities from display and XML"
        
        self.status_bar.showMessage(message)
        print(f"🗑️ DELETION COMPLETE: {deleted_count} entities removed")
        return True

    def _remove_entity_from_main_xml(self, entity, tree):
        """Remove entity from main XML tree (mapsdata, omnis, managers, sectordep)"""
        try:
            root = tree.getroot()
            
            # Search for the entity by name in the XML tree
            entities_found = []
            
            # Try FCBConverter format first (field elements)
            for entity_elem in root.findall(".//object[@name='Entity']"):
                name_field = entity_elem.find(".//field[@name='hidName']")
                if name_field is not None:
                    stored_name = name_field.get('value-String')
                    if stored_name == entity.name:
                        entities_found.append(entity_elem)
            
            # If not found, try Dunia Tools format (value elements)
            if not entities_found:
                for entity_elem in root.findall(".//object[@type='Entity']"):
                    name_elem = entity_elem.find(".//value[@name='hidName']")
                    if name_elem is not None and name_elem.text == entity.name:
                        entities_found.append(entity_elem)
            
            if not entities_found:
                print(f"    Entity '{entity.name}' not found in XML tree")
                return False
            
            if len(entities_found) > 1:
                print(f"    Warning: Found {len(entities_found)} entities with name '{entity.name}', removing first match")
            
            # Remove the entity element from its parent
            entity_elem = entities_found[0]
            parent = entity_elem.getparent() if hasattr(entity_elem, 'getparent') else None
            
            if parent is None:
                # Find parent the hard way
                for possible_parent in root.iter():
                    if entity_elem in list(possible_parent):
                        parent = possible_parent
                        break
            
            if parent is not None:
                parent.remove(entity_elem)
                print(f"    Removed entity from parent element")
                return True
            else:
                print(f"    Could not find parent element to remove entity from")
                return False
                
        except Exception as e:
            print(f"    Error removing entity from main XML: {e}")
            import traceback
            traceback.print_exc()
            return False

    def select_all_entities(self):
        """Select all visible entities"""
        if not hasattr(self, 'canvas'):
            return False
        
        visible_entities = []
        for entity in self.entities:
            if (not getattr(self.canvas, 'unified_mode', False) and
                    hasattr(self, 'current_map') and self.current_map is not None and
                    hasattr(entity, 'map_name') and entity.map_name != self.current_map.name):
                continue
            visible_entities.append(entity)
        
        if not visible_entities:
            self.status_bar.showMessage("No entities to select")
            return False
        
        self.canvas.selected = visible_entities
        self.canvas.selected_entity = visible_entities[0] if visible_entities else None
        self.selected_entity = self.canvas.selected_entity
        
        if hasattr(self, 'update_ui_for_selected_entity'):
            self.update_ui_for_selected_entity(self.selected_entity)
        
        self.canvas.update()
        self.status_bar.showMessage(f"Selected {len(visible_entities)} entities")
        return True
    
    def show_clipboard_info(self):
        """Show clipboard information"""
        info = self.entity_clipboard.get_clipboard_info()
        if info is None:
            self.status_bar.showMessage("No entity data in clipboard")
            return
        
        entity_names = info['entities'][:5]
        if len(info['entities']) > 5:
            entity_names.append(f"... and {len(info['entities']) - 5} more")
        
        QMessageBox.information(
            self,
            "Clipboard Contents",
            f"Entity count: {info['count']}\n"
            f"Version: {info['version']}\n"
            f"Copied: {info.get('copy_date', 'unknown')}\n\n"
            f"Entities:\n" + "\n".join([f"• {name}" for name in entity_names])
        )
    
    # Bind methods to editor
    editor.generate_new_entity_id = types.MethodType(generate_new_entity_id, editor)
    editor.generate_unique_entity_name = types.MethodType(generate_unique_entity_name, editor)
    editor._remove_entity_from_main_xml = types.MethodType(_remove_entity_from_main_xml, editor)
    editor.get_all_existing_entity_ids = types.MethodType(get_all_existing_entity_ids, editor)
    editor.get_all_existing_entity_names = types.MethodType(get_all_existing_entity_names, editor)
    editor.copy_selected_entities = types.MethodType(copy_selected_entities, editor)
    editor.paste_entities = types.MethodType(paste_entities, editor)
    editor.duplicate_selected_entities = types.MethodType(duplicate_selected_entities, editor)
    editor.delete_selected_entities = types.MethodType(delete_selected_entities, editor)
    editor.select_all_entities = types.MethodType(select_all_entities, editor)
    editor.show_clipboard_info = types.MethodType(show_clipboard_info, editor)
    editor._find_best_worldsector_for_entity = types.MethodType(_find_best_worldsector_for_entity, editor)
    editor._add_entity_xml_to_sector = types.MethodType(_add_entity_xml_to_sector, editor)
    editor._add_entity_to_main_level_file = types.MethodType(_add_entity_to_main_level_file, editor)
    editor._indent_xml = types.MethodType(_indent_xml, editor)
    
    # Setup UI
    setup_ui_integration(editor)
    setup_keyboard_shortcuts(editor)
    
    print("✅ Enhanced copy/paste system setup complete with Structure children support!")

def _remove_entity_from_worldsector_fixed(self, entity):
    """Remove entity from its worldsector XML file - FIXED for FCBConverter format and multiple MissionLayers"""
    try:
        source_file = entity.source_file_path
        print(f"\n🔧 Removing {entity.name} from {os.path.basename(source_file)}")
        
        # Auto-load source file if not already loaded
        if not hasattr(self, 'worldsectors_trees'):
            self.worldsectors_trees = {}
        
        if source_file not in self.worldsectors_trees:
            if os.path.exists(source_file):
                try:
                    tree = ET.parse(source_file)
                    self.worldsectors_trees[source_file] = tree
                    print(f"🔧 Auto-loaded source file: {os.path.basename(source_file)}")
                except Exception as e:
                    print(f"❌ Error loading source file {source_file}: {e}")
                    return False
            else:
                print(f"❌ Source file does not exist: {source_file}")
                return False
        
        tree = self.worldsectors_trees[source_file]
        root = tree.getroot()
        
        # Find ALL MissionLayers - there can be multiple in worldsector files
        mission_layers = root.findall(".//object[@name='MissionLayer']")
        if not mission_layers:
            print(f"❌ No MissionLayer found in {source_file}")
            return False
        
        print(f"📋 Found {len(mission_layers)} MissionLayer(s) in file")
        
        entity_to_remove = None
        source_mission_layer = None
        
        # Search through ALL MissionLayers
        for layer_idx, mission_layer in enumerate(mission_layers):
            print(f"\n🔍 Checking MissionLayer {layer_idx + 1}/{len(mission_layers)}")
            print(f"📋 This MissionLayer has {len(mission_layer)} children")
            
            # Look for entities directly under this MissionLayer
            entities_in_layer = mission_layer.findall("object[@name='Entity']")
            print(f"🔍 Found {len(entities_in_layer)} Entity objects in this MissionLayer")
            
            # Search through entities in FCBConverter format
            for i, entity_elem in enumerate(entities_in_layer):
                print(f"🔍 Checking entity {i+1}/{len(entities_in_layer)}")
                
                # Look for hidName field (FCBConverter format)
                name_field = entity_elem.find("field[@name='hidName']")
                if name_field is not None:
                    stored_name = name_field.get('value-String')
                    print(f"   Name in XML: '{stored_name}'")
                    print(f"   Looking for: '{entity.name}'")
                    
                    if stored_name == entity.name:
                        print(f"✅ FOUND MATCH: {entity.name} in MissionLayer {layer_idx + 1}")
                        entity_to_remove = entity_elem
                        source_mission_layer = mission_layer
                        break
                    else:
                        print(f"❌ No match")
                else:
                    print(f"   No hidName field found")
            
            # If found, break out of layer loop
            if entity_to_remove is not None:
                break
            
            # If not found in FCBConverter format in this layer, try Dunia Tools format as fallback
            print(f"🔍 Trying Dunia Tools format in MissionLayer {layer_idx + 1}...")
            for entity_elem in entities_in_layer:
                name_elem = entity_elem.find("./value[@name='hidName']")
                if name_elem is not None and name_elem.text == entity.name:
                    print(f"✅ Found {entity.name} in Dunia Tools format in MissionLayer {layer_idx + 1}")
                    entity_to_remove = entity_elem
                    source_mission_layer = mission_layer
                    break
            
            # If found, break out of layer loop
            if entity_to_remove is not None:
                break
        
        if entity_to_remove is None:
            print(f"❌ Entity {entity.name} not found in any MissionLayer")
            return False
        
        # Remove the entity from the correct MissionLayer
        print(f"🗑️ Removing entity from MissionLayer")
        source_mission_layer.remove(entity_to_remove)
        
        # Verify removal
        all_entities_after = []
        for ml in mission_layers:
            all_entities_after.extend(ml.findall("object[@name='Entity']"))
        print(f"✅ Entity removed. All MissionLayers now have {len(all_entities_after)} total entities")
        
        # Save immediately
        try:
            ET.indent(tree, space="  ")
        except AttributeError:
            pass  # Python < 3.9
        tree.write(source_file, encoding='utf-8', xml_declaration=True)
        print(f"💾 Saved {os.path.basename(source_file)}")

        # Mark file as modified
        if not hasattr(self, 'worldsectors_modified'):
            self.worldsectors_modified = {}
        self.worldsectors_modified[source_file] = True

        return True

    except Exception as e:
        print(f"❌ Error removing entity: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_entity_deletion(self, entity_name):
    """Test method to debug entity deletion"""
    print(f"\n🧪 TESTING DELETION for {entity_name}")
    
    # Find the entity
    target_entity = None
    for entity in self.entities:
        if entity.name == entity_name:
            target_entity = entity
            break
    
    if not target_entity:
        print(f"❌ Entity {entity_name} not found in entities list")
        return False
    
    print(f"✅ Found entity in entities list")
    print(f"   Position: ({target_entity.x}, {target_entity.y}, {target_entity.z})")
    print(f"   Source file: {getattr(target_entity, 'source_file_path', 'None')}")
    
    # Check if entity exists in XML
    if hasattr(target_entity, 'source_file_path') and target_entity.source_file_path:
        source_file = target_entity.source_file_path
        
        if hasattr(self, 'worldsectors_trees') and source_file in self.worldsectors_trees:
            tree = self.worldsectors_trees[source_file]
            root = tree.getroot()
            
            # Count entities before deletion
            all_entities_before = root.findall(".//object[@name='Entity']")
            print(f"📊 Total entities in XML before deletion: {len(all_entities_before)}")
            
            # Find our specific entity
            found_in_xml = False
            for mission_layer in root.findall(".//object[@name='MissionLayer']"):
                for entity_elem in mission_layer.findall("object[@name='Entity']"):
                    name_field = entity_elem.find("field[@name='hidName']")
                    if name_field is not None:
                        stored_name = name_field.get('value-String')
                        if stored_name == entity_name:
                            found_in_xml = True
                            print(f"✅ Found entity in XML file")
                            break
                if found_in_xml:
                    break
            
            if not found_in_xml:
                print(f"❌ Entity not found in XML file")
                return False
        else:
            print(f"❌ Worldsector tree not loaded for {source_file}")
            return False
    else:
        print(f"⚠️ Entity has no source_file_path")
        return False
    
    # Perform the deletion test
    print(f"\n🗑️ Performing deletion...")
    success = self._remove_entity_from_worldsector_fixed(target_entity)
    
    if success:
        # Verify deletion
        all_entities_after = root.findall(".//object[@name='Entity']")
        print(f"📊 Total entities in XML after deletion: {len(all_entities_after)}")
        print(f"📊 Entities removed: {len(all_entities_before) - len(all_entities_after)}")
        
        # Check if our entity is still there
        still_found = False
        for mission_layer in root.findall(".//object[@name='MissionLayer']"):
            for entity_elem in mission_layer.findall("object[@name='Entity']"):
                name_field = entity_elem.find("field[@name='hidName']")
                if name_field is not None:
                    stored_name = name_field.get('value-String')
                    if stored_name == entity_name:
                        still_found = True
                        break
            if still_found:
                break
        
        if still_found:
            print(f"❌ Entity still found in XML after deletion!")
            return False
        else:
            print(f"✅ Entity successfully removed from XML")
            return True
    else:
        print(f"❌ Deletion failed")
        return False


def setup_ui_integration(editor):
    """Setup UI integration with enhanced features"""
    # Create Edit menu if it doesn't exist
    # if not hasattr(editor, 'edit_menu'):
    #     editor.edit_menu = editor.menuBar().addMenu("Misc")
    
    # # Add actions
    # editor.edit_menu.addSeparator()
    
    # copy_action = QAction("Copy Entities", editor)
    # copy_action.setShortcut(QKeySequence.StandardKey.Copy)
    # copy_action.triggered.connect(editor.copy_selected_entities)
    # editor.edit_menu.addAction(copy_action)
    
    # paste_action = QAction("Paste Entities", editor)
    # paste_action.setShortcut(QKeySequence.StandardKey.Paste)
    # paste_action.triggered.connect(lambda: editor.paste_entities(at_cursor=True))
    # editor.edit_menu.addAction(paste_action)
    
    # duplicate_action = QAction("Duplicate Entities", editor)
    # duplicate_action.setShortcut("Ctrl+D")
    # duplicate_action.triggered.connect(editor.duplicate_selected_entities)
    # editor.edit_menu.addAction(duplicate_action)
    
    # editor.edit_menu.addSeparator()
    
    # select_all_action = QAction("Select All Entities", editor)
    # select_all_action.setShortcut(QKeySequence.StandardKey.SelectAll)
    # select_all_action.triggered.connect(editor.select_all_entities)
    # editor.edit_menu.addAction(select_all_action)
    
    # clipboard_info_action = QAction("Show Clipboard Info", editor)
    # clipboard_info_action.triggered.connect(editor.show_clipboard_info)
    # editor.edit_menu.addAction(clipboard_info_action)
    
    # Setup context menu
    setup_context_menu(editor)


def setup_context_menu(self):
    """Setup enhanced context menu with all copy/paste features"""
    if not hasattr(self, 'canvas'):
        return
    if hasattr(self.canvas, 'showContextMenu'):
        self.canvas._original_showContextMenu = self.canvas.showContextMenu
    
    def enhanced_showContextMenu(event):
        from PyQt6.QtWidgets import QMenu
        
        menu = QMenu(self.canvas)
        
        selected_entities = getattr(self.canvas, 'selected', [])
        has_selection = len(selected_entities) > 0
        has_clipboard = hasattr(self, 'entity_clipboard') and self.entity_clipboard.has_clipboard_data()
        
        if has_selection:
            menu.addAction(f"Selected: {len(selected_entities)} entities").setEnabled(False)
            menu.addSeparator()
            
            copy_action = menu.addAction("Copy Entities")
            copy_action.triggered.connect(self.copy_selected_entities)
            
            duplicate_action = menu.addAction("Duplicate Entities")
            duplicate_action.triggered.connect(self.duplicate_selected_entities)
            
            # CRITICAL FIX: Make sure delete is properly connected
            delete_action = menu.addAction("Delete Entities")
            delete_action.triggered.connect(self.delete_selected_entities)
            
            menu.addSeparator()
        
        if has_clipboard:
            clipboard_info = self.entity_clipboard.get_clipboard_info()
            if clipboard_info:
                paste_label = f"Paste {clipboard_info['count']} Entities"
                
                paste_action = menu.addAction(paste_label)
                paste_action.triggered.connect(lambda: self.paste_entities(at_cursor=True))
                
                paste_original_action = menu.addAction("Paste at Original Position")
                paste_original_action.triggered.connect(lambda: self.paste_entities(at_cursor=False))
                
                menu.addSeparator()
                
                clipboard_info_action = menu.addAction("Show Clipboard Info")
                clipboard_info_action.triggered.connect(self.show_clipboard_info)
                
                menu.addSeparator()
        
        # Selection actions
        if not has_selection:
            select_all_action = menu.addAction("Select All Entities")
            select_all_action.triggered.connect(self.select_all_entities)
            menu.addSeparator()
        
        # View actions
        world_x, world_y = self.canvas.screen_to_world(event.position().x(), event.position().y())
        
        center_action = menu.addAction("Center View Here")
        center_action.triggered.connect(lambda: center_view_at(self, world_x, world_y))
        
        # Add zoom actions if available
        if hasattr(self.canvas, 'zoom_in'):
            menu.addSeparator()
            zoom_in_action = menu.addAction("Zoom In")
            zoom_in_action.triggered.connect(self.canvas.zoom_in)
            
            zoom_out_action = menu.addAction("Zoom Out")
            zoom_out_action.triggered.connect(self.canvas.zoom_out)
            
            reset_view_action = menu.addAction("Reset View")
            reset_view_action.triggered.connect(self.reset_view)
        
        menu.exec(event.globalPosition().toPoint())
    
    self.canvas.showContextMenu = enhanced_showContextMenu

def center_view_at(editor, world_x, world_y):
    """Center view at coordinates"""
    if editor.canvas.mode == 0:  # 2D mode
        editor.canvas.offset_x = (editor.canvas.width() / 2) - (world_x * editor.canvas.scale_factor)
        editor.canvas.offset_y = (editor.canvas.height() / 2) - (world_y * editor.canvas.scale_factor)
    else:  # 3D mode
        editor.canvas.offset_x = -world_x
        editor.canvas.offset_z = world_y
    
    editor.canvas.update()


def setup_keyboard_shortcuts(self):
    """Setup comprehensive keyboard shortcuts"""
    from PyQt6.QtGui import QShortcut, QKeySequence
    
    # Copy (Ctrl+C)
    copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self)
    copy_shortcut.activated.connect(self.copy_selected_entities)
    
    # Paste (Ctrl+V)  
    paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self)
    paste_shortcut.activated.connect(lambda: self.paste_entities(at_cursor=True))
    
    # Duplicate (Ctrl+D)
    duplicate_shortcut = QShortcut(QKeySequence("Ctrl+D"), self)
    duplicate_shortcut.activated.connect(self.duplicate_selected_entities)
    
    # CRITICAL FIX: Delete (Delete key) - make sure this is connected
    delete_shortcut = QShortcut(QKeySequence.StandardKey.Delete, self)
    delete_shortcut.activated.connect(self.delete_selected_entities)
    
    # Select All (Ctrl+A)
    select_all_shortcut = QShortcut(QKeySequence.StandardKey.SelectAll, self)
    select_all_shortcut.activated.connect(self.select_all_entities)
    
    # Show clipboard info (Ctrl+I)
    clipboard_info_shortcut = QShortcut(QKeySequence("Ctrl+I"), self)
    clipboard_info_shortcut.activated.connect(self.show_clipboard_info)
    
    print("✅ Keyboard shortcuts setup complete including delete key")