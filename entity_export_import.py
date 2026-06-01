# entity_export_import.py - Entity Export/Import System for Level Editor

import os
import json
import xml.etree.ElementTree as ET
import shutil
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QLineEdit, QFileDialog, QMessageBox, 
                             QComboBox, QTextEdit, QGroupBox, QCheckBox,
                             QListWidget, QListWidgetItem, QSplitter,
                             QProgressDialog, QApplication, QWidget,
                             QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QIcon, QColor
from data_models import Entity
from ui_style_utils import apply_checkbox_style
import time


class XMLHelper:
    """Helper class for XML manipulation shared between export and import"""
    
    @staticmethod
    def update_entity_position(xml_element, x, y, z):
        """Update position fields in entity XML - works for both formats"""
        try:
            # FCBConverter format (has field elements)
            pos_field = xml_element.find(".//field[@name='hidPos']")
            if pos_field is not None:
                pos_field.set('value-Vector3', f"{x},{y},{z}")
                binary_hex = XMLHelper.coordinates_to_binhex(x, y, z)
                pos_field.text = binary_hex

                # Also update hidPos_precise
                pos_precise = xml_element.find(".//field[@name='hidPos_precise']")
                if pos_precise is not None:
                    pos_precise.set('value-Vector3', f"{x},{y},{z}")
                    pos_precise.text = binary_hex
                return True
            
            # Dunia Tools format (has value elements)
            pos_elem = xml_element.find(".//value[@name='hidPos']")
            if pos_elem is not None:
                for axis, value in [('x', x), ('y', y), ('z', z)]:
                    axis_elem = pos_elem.find(f"./{axis}")
                    if axis_elem is not None:
                        axis_elem.text = str(int(value))
                
                # Also update hidPos_precise
                pos_precise = xml_element.find(".//value[@name='hidPos_precise']")
                if pos_precise is not None:
                    for axis, value in [('x', x), ('y', y), ('z', z)]:
                        axis_elem = pos_precise.find(f"./{axis}")
                        if axis_elem is not None:
                            axis_elem.text = str(int(value))
                return True
                
            return False
        except Exception as e:
            print(f"Error updating position: {e}")
            return False
    
    @staticmethod
    def coordinates_to_binhex(x, y, z):
        """Convert coordinates to BinHex format (IEEE 754 32-bit floats)"""
        import struct
        try:
            binary_data = struct.pack('<fff', float(x), float(y), float(z))
            return binary_data.hex().upper()
        except Exception as e:
            print(f"Error converting to BinHex: {e}")
            return "000000000000000000000000"
    
    @staticmethod
    def int64_to_binhex(value):
        """Convert 64-bit integer to BinHex format"""
        import struct
        try:
            binary_data = struct.pack('<Q', int(value))
            return binary_data.hex().upper()
        except:
            return "0000000000000000"
    
    @staticmethod
    def update_entity_id(xml_element, new_id):
        """Update entity ID in XML"""
        try:
            # FCBConverter format
            id_field = xml_element.find(".//field[@name='disEntityId']")
            if id_field is not None:
                id_field.set('value-Id64', str(new_id))
                binary_hex = XMLHelper.int64_to_binhex(new_id)
                id_field.text = binary_hex
                return True
            
            # Dunia Tools format
            id_elem = xml_element.find(".//value[@name='disEntityId']")
            if id_elem is not None:
                id_elem.text = str(new_id)
                return True
                
            return False
        except Exception as e:
            print(f"Error updating entity ID: {e}")
            return False
    
    @staticmethod
    def extract_position_from_xml(xml_element):
        """Extract position from XML element"""
        try:
            # FCBConverter format
            pos_field = xml_element.find(".//field[@name='hidPos']")
            if pos_field is not None:
                pos_vector = pos_field.get('value-Vector3', '0,0,0')
                x, y, z = map(float, pos_vector.split(','))
                return x, y, z
            
            # Dunia Tools format
            pos_elem = xml_element.find(".//value[@name='hidPos']")
            if pos_elem is not None:
                x = float(pos_elem.find('./x').text or 0)
                y = float(pos_elem.find('./y').text or 0)
                z = float(pos_elem.find('./z').text or 0)
                return x, y, z
        except:
            pass
        
        return 0.0, 0.0, 0.0
    
    @staticmethod
    def extract_entity_name(xml_element):
        """Extract entity name from XML"""
        try:
            # FCBConverter format
            name_field = xml_element.find(".//field[@name='hidName']")
            if name_field is not None:
                return name_field.get('value-String', 'Unknown')
            
            # Dunia Tools format
            name_elem = xml_element.find(".//value[@name='hidName']")
            if name_elem is not None:
                return name_elem.text or 'Unknown'
        except:
            pass
        
        return 'Unknown'
    
    @staticmethod
    def extract_entity_id(xml_element):
        """Extract entity ID from XML"""
        try:
            # FCBConverter format
            id_field = xml_element.find(".//field[@name='disEntityId']")
            if id_field is not None:
                return id_field.get('value-Id64', 'Unknown')
            
            # Dunia Tools format
            id_elem = xml_element.find(".//value[@name='disEntityId']")
            if id_elem is not None:
                return id_elem.text or 'Unknown'
        except:
            pass
        
        return 'Unknown'


class EntityExportDialog(QDialog):
    """Dialog for exporting selected entities to XML files"""
    
    def __init__(self, parent, selected_entities):
        super().__init__(parent)
        self.parent_editor = parent
        self.selected_entities = selected_entities
        self.objects_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "objects")
        
        self.setWindowTitle("Export Entities")
        self.setModal(True)
        self.resize(500, 400)
        
        self.setup_ui()
        self.load_existing_collections()
        
    def setup_ui(self):
        """Setup the export dialog UI"""
        layout = QVBoxLayout(self)
        
        # Title
        title_label = QLabel("Export Entities to Collection")
        title_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)
        
        # Entity count info
        info_label = QLabel(f"Selected {len(self.selected_entities)} entities for export")
        layout.addWidget(info_label)
        
        # Collection name
        name_group = QGroupBox("Collection Settings")
        name_layout = QVBoxLayout(name_group)
        
        name_layout.addWidget(QLabel("Collection Name:"))
        self.collection_name_edit = QLineEdit()
        self.collection_name_edit.setPlaceholderText("Enter a name for this collection...")
        name_layout.addWidget(self.collection_name_edit)
        
        # Existing collections dropdown
        name_layout.addWidget(QLabel("Or select existing collection:"))
        self.existing_combo = QComboBox()
        self.existing_combo.addItem("-- Create New Collection --")
        self.existing_combo.currentTextChanged.connect(self.on_existing_selected)
        name_layout.addWidget(self.existing_combo)
        
        layout.addWidget(name_group)
        
        # Export options
        options_group = QGroupBox("Export Options")
        options_layout = QVBoxLayout(options_group)
        
        self.preserve_positions_check = QCheckBox("Preserve entity positions")
        self.preserve_positions_check.setChecked(True)
        self.preserve_positions_check.setToolTip("Save the current positions of entities")
        apply_checkbox_style(self.preserve_positions_check)
        options_layout.addWidget(self.preserve_positions_check)

        self.include_metadata_check = QCheckBox("Include metadata (source files, map info)")
        self.include_metadata_check.setChecked(True)
        apply_checkbox_style(self.include_metadata_check)
        options_layout.addWidget(self.include_metadata_check)
        
        layout.addWidget(options_group)
        
        # Preview
        preview_group = QGroupBox("Entities to Export")
        preview_layout = QVBoxLayout(preview_group)
        
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumHeight(150)
        
        # Show entity names
        entity_names = "\n".join([f"• {e.name}" for e in self.selected_entities[:10]])
        if len(self.selected_entities) > 10:
            entity_names += f"\n... and {len(self.selected_entities) - 10} more"
        self.preview_text.setPlainText(entity_names)
        
        preview_layout.addWidget(self.preview_text)
        layout.addWidget(preview_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        export_button = QPushButton("Export Collection")
        export_button.clicked.connect(self.export_entities)
        button_layout.addWidget(export_button)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        
        # Status label
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

    def load_existing_collections(self):
        """Load existing entity collections"""
        if not hasattr(self, 'existing_combo'):
            return
            
        if os.path.exists(self.objects_folder):
            for item in os.listdir(self.objects_folder):
                item_path = os.path.join(self.objects_folder, item)
                if os.path.isdir(item_path):
                    # Check if it contains entity XML files
                    has_entities = any(f.endswith('.xml') for f in os.listdir(item_path))
                    if has_entities:
                        self.existing_combo.addItem(item)
    
    def on_existing_selected(self, collection_name):
        """Handle selection of existing collection"""
        if collection_name != "-- Create New Collection --":
            self.collection_name_edit.setText(collection_name)
        else:
            self.collection_name_edit.clear()
    
    def export_entities(self):
        """Export the selected entities to XML files - INCLUDING CHILDREN AND SEATED NPCs AS SEPARATE FILES"""
        collection_name = self.collection_name_edit.text().strip()
        
        if not collection_name:
            QMessageBox.warning(self, "No Collection Name", 
                            "Please enter a collection name.")
            return
        
        # Validate collection name
        if not self.is_valid_folder_name(collection_name):
            QMessageBox.warning(self, "Invalid Name", 
                            "Collection name contains invalid characters.\n"
                            "Please use only letters, numbers, spaces, and basic punctuation.")
            return
        
        try:
            # Create objects folder if it doesn't exist
            if not os.path.exists(self.objects_folder):
                os.makedirs(self.objects_folder)
            
            # Create collection folder
            collection_folder = os.path.join(self.objects_folder, collection_name)
            if not os.path.exists(collection_folder):
                os.makedirs(collection_folder)
            
            print(f"\n{'='*70}")
            print(f"EXPORT WITH CHILDREN AND SEATED NPCs - STARTING")
            print(f"{'='*70}")
            print(f"Original selection: {len(self.selected_entities)} entities")
            
            # ✨ ENHANCED: Collect entities and identify ALL relationships
            all_entities_to_export, structure_child_map, seated_npc_map, initial_user_map = self.collect_entities_with_children(
                self.selected_entities
            )

            print(f"📊 Total entities found: {len(all_entities_to_export)}")
            print(f"   Top-level entities: {len(self.selected_entities)}")
            print(f"   Children + Seated NPCs + Initial Users: {len(all_entities_to_export) - len(self.selected_entities)}")
            print(f"   Structures found: {len(structure_child_map)}")
            print(f"   Vehicles found: {len(seated_npc_map)}")
            print(f"   Vehicles with initial users: {len(initial_user_map)}")

            # Create set of all child IDs, seated IDs, and initial user IDs for metadata tracking
            all_child_ids = set()
            for child_list in structure_child_map.values():
                all_child_ids.update(child_list)

            all_seated_ids = set()
            for npc_list in seated_npc_map.values():
                all_seated_ids.update(npc_list)

            all_initial_user_ids = set()
            for user_list in initial_user_map.values():
                all_initial_user_ids.update(user_list)
            
            # ✨ CRITICAL FIX: Export ALL entities (parents AND children/seated NPCs)
            exported_files = []
            metadata = {
                'collection_name': collection_name,
                'export_date': time.strftime('%Y-%m-%d %H:%M:%S'),
                'entity_count': len(self.selected_entities),  # Original selection count
                'total_entities_with_children': len(all_entities_to_export),  # Total including relationships
                'original_selection_count': len(self.selected_entities),
                'preserve_positions': self.preserve_positions_check.isChecked(),
                'include_metadata': self.include_metadata_check.isChecked(),
                'has_structures': len(structure_child_map) > 0,
                'structure_count': len(structure_child_map),
                'structure_child_map': structure_child_map,
                'has_vehicles': len(seated_npc_map) > 0,
                'vehicle_count': len(seated_npc_map),
                'seated_npc_map': seated_npc_map,
                'has_initial_users': len(initial_user_map) > 0,
                'initial_user_vehicle_count': len(initial_user_map),
                'initial_user_map': initial_user_map,
                'entities': []
            }
            
            file_counter = 1
            
            # Export ALL entities - parents, children, and seated NPCs
            for entity in all_entities_to_export:
                # Create safe filename
                safe_name = self.create_safe_filename(entity.name)
                xml_filename = f"{safe_name}_{file_counter:03d}.xml"
                xml_path = os.path.join(collection_folder, xml_filename)
                
                # Export entity to XML
                success = self.export_entity_to_xml(entity, xml_path)
                
                if success:
                    exported_files.append(xml_filename)
                    
                    # Determine entity type for logging
                    is_parent = entity.id in structure_child_map
                    is_child = entity.id in all_child_ids
                    is_vehicle = entity.id in seated_npc_map
                    is_seated = entity.id in all_seated_ids
                    is_initial_user_vehicle = entity.id in initial_user_map
                    is_initial_user = entity.id in all_initial_user_ids

                    # Add to metadata
                    entity_metadata = {
                        'name': entity.name,
                        'id': entity.id,
                        'filename': xml_filename,
                        'original_position': {
                            'x': entity.x,
                            'y': entity.y,
                            'z': entity.z
                        },
                        'is_parent': is_parent,
                        'is_child': is_child,
                        'is_vehicle': is_vehicle,
                        'is_seated': is_seated,
                        'is_initial_user_vehicle': is_initial_user_vehicle,
                        'is_initial_user': is_initial_user
                    }

                    # Add child information for structures
                    if is_parent:
                        entity_metadata['child_ids'] = structure_child_map[entity.id]
                        entity_metadata['child_count'] = len(structure_child_map[entity.id])
                        print(f"   📦 {entity.name} - Structure with {entity_metadata['child_count']} children")

                    # Add seated NPC information for vehicles
                    if is_vehicle:
                        entity_metadata['seated_npc_ids'] = seated_npc_map[entity.id]
                        entity_metadata['seated_npc_count'] = len(seated_npc_map[entity.id])
                        print(f"   🚗 {entity.name} - Vehicle with {entity_metadata['seated_npc_count']} seated NPCs")

                    # Add initial user information for vehicles with pilots/drivers
                    if is_initial_user_vehicle:
                        entity_metadata['initial_user_ids'] = initial_user_map[entity.id]
                        entity_metadata['initial_user_count'] = len(initial_user_map[entity.id])
                        print(f"   ✈️ {entity.name} - Vehicle with {entity_metadata['initial_user_count']} initial user(s)")

                    # Mark children, seated NPCs, and initial users
                    if is_child:
                        print(f"   📄 {entity.name} - Child entity")
                    if is_seated:
                        print(f"   🪑 {entity.name} - Seated NPC")
                    if is_initial_user:
                        print(f"   👤 {entity.name} - Initial user (pilot/driver)")
                    
                    if self.include_metadata_check.isChecked():
                        entity_metadata.update({
                            'source_file': getattr(entity, 'source_file', None),
                            'source_file_path': getattr(entity, 'source_file_path', None),
                            'map_name': getattr(entity, 'map_name', None),
                            'source_sector_id': getattr(entity, 'source_sector_id', -1),
                            'source_layer': getattr(entity, 'source_layer', 'main')
                        })
                    
                    metadata['entities'].append(entity_metadata)
                    file_counter += 1
            
            # Save collection metadata
            metadata_path = os.path.join(collection_folder, "collection_info.json")
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            
            # Create a readme file
            readme_path = os.path.join(collection_folder, "README.txt")
            with open(readme_path, 'w', encoding='utf-8') as f:
                f.write(f"Entity Collection: {collection_name}\n")
                f.write(f"Exported: {metadata['export_date']}\n")
                f.write(f"Total Entities Exported: {len(exported_files)}\n")
                f.write(f"  - Top-level entities: {len(self.selected_entities)}\n")
                f.write(f"  - Children: {len(all_child_ids)}\n")
                f.write(f"  - Seated NPCs: {len(all_seated_ids)}\n")
                f.write(f"  - Initial users (pilots/drivers): {len(all_initial_user_ids)}\n")
                f.write("\n")
                
                if metadata['has_structures']:
                    f.write(f"Structures: {metadata['structure_count']}\n")

                if metadata['has_vehicles']:
                    f.write(f"Vehicles with seated NPCs: {metadata['vehicle_count']}\n")

                if metadata['has_initial_users']:
                    f.write(f"Vehicles with initial users: {metadata['initial_user_vehicle_count']}\n")
                
                f.write("\n")
                f.write("Relationship Summary:\n")
                
                # List structures and their children
                if structure_child_map:
                    f.write("\nStructures with Children:\n")
                    for parent_id, child_ids in structure_child_map.items():
                        # Find parent entity
                        parent_entity = None
                        for entity in all_entities_to_export:
                            if entity.id == parent_id:
                                parent_entity = entity
                                break
                        if parent_entity:
                            f.write(f"  • {parent_entity.name} ({len(child_ids)} children)\n")
                            for child_id in child_ids:
                                # Find child entity
                                for entity in all_entities_to_export:
                                    if entity.id == child_id:
                                        f.write(f"    - {entity.name}\n")
                                        break
                
                # List vehicles and their seated NPCs
                if seated_npc_map:
                    f.write("\nVehicles with Seated NPCs:\n")
                    for vehicle_id, npc_ids in seated_npc_map.items():
                        # Find vehicle entity
                        vehicle_entity = None
                        for entity in all_entities_to_export:
                            if entity.id == vehicle_id:
                                vehicle_entity = entity
                                break
                        if vehicle_entity:
                            f.write(f"  • {vehicle_entity.name} ({len(npc_ids)} seated NPCs)\n")
                            for npc_id in npc_ids:
                                # Find NPC entity
                                for entity in all_entities_to_export:
                                    if entity.id == npc_id:
                                        f.write(f"    - {entity.name}\n")
                                        break

                # List vehicles and their initial users
                if initial_user_map:
                    f.write("\nVehicles with Initial Users (pilots/drivers):\n")
                    for vehicle_id, user_ids in initial_user_map.items():
                        vehicle_entity = None
                        for entity in all_entities_to_export:
                            if entity.id == vehicle_id:
                                vehicle_entity = entity
                                break
                        if vehicle_entity:
                            f.write(f"  • {vehicle_entity.name} ({len(user_ids)} initial user(s))\n")
                            for user_id in user_ids:
                                for entity in all_entities_to_export:
                                    if entity.id == user_id:
                                        f.write(f"    - {entity.name} (pilot/driver)\n")
                                        break
                
                f.write("\n")
                f.write("All Exported Entities:\n")
                for entity_info in metadata['entities']:
                    f.write(f"- {entity_info['name']} ({entity_info['filename']})")
                    
                    tags = []
                    if entity_info.get('is_parent'):
                        tags.append(f"Structure with {entity_info['child_count']} children")
                    if entity_info.get('is_child'):
                        tags.append("Child")
                    if entity_info.get('is_vehicle'):
                        tags.append(f"Vehicle with {entity_info['seated_npc_count']} NPCs")
                    if entity_info.get('is_seated'):
                        tags.append("Seated NPC")
                    if entity_info.get('is_initial_user_vehicle'):
                        tags.append(f"Vehicle with {entity_info['initial_user_count']} pilot(s)")
                    if entity_info.get('is_initial_user'):
                        tags.append("Pilot/Driver")
                    
                    if tags:
                        f.write(f" [{', '.join(tags)}]")
                    
                    f.write("\n")
                
                f.write(f"\nNote: All entities are exported as individual XML files.\n")
                f.write(f"Relationships are preserved through entity ID references in the XML.\n")
                f.write(f"To import these entities, use the Entity Import function in the level editor.")
            
            # Show success message
            success_msg = f"Successfully exported {len(exported_files)} XML files to:\n{collection_folder}\n\n"
            success_msg += f"Export Summary:\n"
            success_msg += f"• {len(exported_files)} total entity XML files\n"
            success_msg += f"  - {len(self.selected_entities)} top-level entities\n"
            success_msg += f"  - {len(all_child_ids)} children\n"
            success_msg += f"  - {len(all_seated_ids)} seated NPCs\n"
            success_msg += f"  - {len(all_initial_user_ids)} initial users (pilots/drivers)\n"

            if metadata['has_structures']:
                success_msg += f"• {metadata['structure_count']} Structures with children\n"

            if metadata['has_vehicles']:
                success_msg += f"• {metadata['vehicle_count']} Vehicles with seated NPCs\n"

            if metadata['has_initial_users']:
                success_msg += f"• {metadata['initial_user_vehicle_count']} Vehicles with initial users\n"
            
            success_msg += f"• collection_info.json (metadata)\n"
            success_msg += f"• README.txt (documentation)"
            
            QMessageBox.information(self, "Export Successful", success_msg)
            
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Export Error", 
                            f"Failed to export entities: {str(e)}")
            import traceback
            traceback.print_exc()

    def collect_entities_with_children(self, selected_entities):
        """
        Collect all entities including Structure children, seated NPCs, and initial users (pilots/drivers).
        Returns: (all_entities_list, structure_child_map, seated_npc_map, initial_user_map)
        """
        all_entities_to_export = []
        already_included = set()
        structure_child_map = {}  # Maps parent structure ID to list of child IDs
        seated_npc_map = {}       # Maps vehicle ID to list of seated NPC IDs
        initial_user_map = {}     # Maps vehicle ID to list of initial user (pilot/driver) IDs
        
        # Build entity lookup dictionary
        entities_dict = {}
        if hasattr(self.parent_editor, 'entities'):
            for entity in self.parent_editor.entities:
                entities_dict[entity.id] = entity
        
        print("\n=== COLLECTING ENTITIES FOR EXPORT ===")
        
        for entity in selected_entities:
            if entity.id not in already_included:
                all_entities_to_export.append(entity)
                already_included.add(entity.id)
                print(f"✓ Added: {entity.name}")
                
                # Check if this entity has an XML element
                if hasattr(entity, 'xml_element') and entity.xml_element is not None:
                    
                    # 1. CHECK FOR STRUCTURE CHILDREN
                    entity_class_field = entity.xml_element.find(".//field[@name='text_hidEntityClass']")
                    if entity_class_field is not None:
                        entity_class = entity_class_field.get('value-String', '')
                        
                        if 'Prefab' in entity_class or 'Structure' in entity.name:
                            print(f"  → Structure/Prefab detected, finding children...")
                            
                            # Find children
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
                                                all_entities_to_export.append(child_entity)
                                                already_included.add(child_entity.id)
                                                print(f"    ✓ Added child: {child_name} (ID: {child_id})")
                                        elif child_name:
                                            # Fallback: find by name
                                            for ent_id, ent in entities_dict.items():
                                                if ent.name == child_name and ent.id not in already_included:
                                                    all_entities_to_export.append(ent)
                                                    already_included.add(ent.id)
                                                    child_ids.append(ent.id)
                                                    print(f"    ✓ Added child by name: {child_name}")
                                                    break
                                
                                if child_ids:
                                    structure_child_map[entity.id] = child_ids
                                    print(f"  → Structure has {len(child_ids)} children")
                    
                    # 2. CHECK FOR SEATED NPCs
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
                                            all_entities_to_export.append(seated_entity)
                                            already_included.add(seated_entity.id)
                                            seated_ids.append(seated_entity.id)
                                            print(f"    🪑 Added seated NPC: {seated_entity.name} (ID: {seated_entity.id})")

                            if seated_ids:
                                seated_npc_map[entity.id] = seated_ids
                                print(f"  🚗 Vehicle has {len(seated_ids)} seated NPCs")

                    # 3. CHECK FOR INITIAL USERS (pilots/drivers via entUser value-Id64)
                    initial_users_obj = entity.xml_element.find(".//object[@name='InitialUsers']")
                    if initial_users_obj is not None:
                        print(f"  ✈️ Vehicle with InitialUsers detected, checking for pilots/drivers...")
                        user_ids = []
                        for user_obj in initial_users_obj.findall("object"):
                            user_field = user_obj.find("field[@name='entUser']")
                            if user_field is not None:
                                user_id_ref = user_field.get('value-Id64')
                                if user_id_ref and user_id_ref in entities_dict:
                                    user_entity = entities_dict[user_id_ref]
                                    if user_entity.id != entity.id:
                                        if user_entity.id not in already_included:
                                            all_entities_to_export.append(user_entity)
                                            already_included.add(user_entity.id)
                                            user_ids.append(user_entity.id)
                                            print(f"    👤 Added initial user: {user_entity.name} (ID: {user_entity.id})")

                        if user_ids:
                            initial_user_map[entity.id] = user_ids
                            print(f"  ✈️ Vehicle has {len(user_ids)} initial user(s)")

        return all_entities_to_export, structure_child_map, seated_npc_map, initial_user_map

    def export_entity_to_xml(self, entity, xml_path):
        """Export a single entity to an XML file"""
        try:
            # Create a clean copy of the entity's XML element
            if hasattr(entity, 'xml_element') and entity.xml_element is not None:
                # Make a deep copy of the XML element
                import copy
                xml_copy = copy.deepcopy(entity.xml_element)
                
                # Update the position fields to current entity position if preserve_positions is checked
                if self.preserve_positions_check.isChecked():
                    XMLHelper.update_entity_position(xml_copy, entity.x, entity.y, entity.z)
                
                # Export the clean entity XML directly (no wrapper)
                self.write_xml_with_custom_formatting(xml_copy, xml_path)
                
                print(f"✓ Exported {entity.name} to {os.path.basename(xml_path)}")
                return True
            else:
                print(f"✗ Entity {entity.name} has no XML element")
                return False
                
        except Exception as e:
            print(f"✗ Error exporting {entity.name}: {e}")
            import traceback
            traceback.print_exc()
            return False
                            
    def write_xml_with_custom_formatting(self, element, xml_path):
        """Write XML with custom formatting - no declaration, 2-space indentation"""
        try:
            # Convert element to string with proper formatting
            import xml.dom.minidom
            
            # First convert to string using ElementTree
            rough_string = ET.tostring(element, encoding='unicode')
            
            # Parse with minidom for pretty printing
            dom = xml.dom.minidom.parseString(rough_string)
            
            # Get the pretty printed string with 2-space indentation
            pretty_xml = dom.documentElement.toprettyxml(indent="  ")
            
            # Remove the extra XML declaration that minidom adds
            lines = pretty_xml.split('\n')
            if lines[0].startswith('<?xml'):
                lines = lines[1:]
            
            # Remove empty lines and rejoin
            clean_lines = [line for line in lines if line.strip()]
            
            # Write to file with clean formatting
            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(clean_lines))
            
        except Exception as e:
            print(f"Error in custom XML formatting: {e}")
            # Fallback to standard method
            tree = ET.ElementTree(element)
            tree.write(xml_path, encoding='utf-8', xml_declaration=False)
                        
    def is_valid_folder_name(self, name):
        """Check if the folder name is valid"""
        invalid_chars = '<>:"/\\|?*'
        return not any(char in name for char in invalid_chars) and len(name) > 0
    
    def create_safe_filename(self, entity_name):
        """Create a safe filename from entity name"""
        # Remove or replace invalid filename characters
        safe_name = entity_name
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            safe_name = safe_name.replace(char, '_')
        
        # Remove multiple underscores and clean up
        while '__' in safe_name:
            safe_name = safe_name.replace('__', '_')
        
        safe_name = safe_name.strip('_')
        
        # Ensure it's not empty
        if not safe_name:
            safe_name = "entity"
        
        return safe_name

class EntityRelationshipDetector:
    """Detects and manages different types of entity relationships"""
    
    @staticmethod
    def find_all_related_entities(entity, entities_dict):
        """
        Find ALL related entities for a given entity.
        Returns: {
            'children': [],        # Structure children
            'seated': [],          # NPCs seated in vehicles (CFCXAIComponent)
            'initial_users': [],   # Pilots/drivers (InitialUsers.entUser)
            'linked': [],          # Other linked entities
        }
        """
        related = {
            'children': [],
            'seated': [],
            'initial_users': [],
            'linked': []
        }
        
        if not hasattr(entity, 'xml_element') or entity.xml_element is None:
            return related
        
        # 1. Structure Children (existing logic)
        children_obj = entity.xml_element.find(".//object[@name='Children']")
        if children_obj is not None:
            child_objects = children_obj.findall("object[@name='Child']")
            for child_obj in child_objects:
                id_field = child_obj.find("field[@name='ID']")
                if id_field is not None:
                    child_id = id_field.get('value-Hash64')
                    if child_id in entities_dict:
                        related['children'].append(entities_dict[child_id])
        
        # 2. Seated NPCs (NEW!)
        # Check CFCXAIComponent → AIObject for seated entity
        ai_component = entity.xml_element.find(".//object[@name='CFCXAIComponent']")
        if ai_component is not None:
            ai_object = ai_component.find(".//object[@name='AIObject']")
            if ai_object is not None:
                # Find the field that contains the entity ID reference
                for field in ai_object.findall("field"):
                    entity_id_ref = field.get('value-Hash64')
                    if entity_id_ref and entity_id_ref in entities_dict:
                        seated_entity = entities_dict[entity_id_ref]
                        # Make sure it's not self-reference
                        if seated_entity.id != entity.id:
                            related['seated'].append(seated_entity)
                            print(f"    🪑 Found seated entity: {seated_entity.name}")
        
        # 3. Initial Users (pilots/drivers via InitialUsers → entUser value-Id64)
        initial_users_obj = entity.xml_element.find(".//object[@name='InitialUsers']")
        if initial_users_obj is not None:
            for user_obj in initial_users_obj.findall("object"):
                user_field = user_obj.find("field[@name='entUser']")
                if user_field is not None:
                    user_id_ref = user_field.get('value-Id64')
                    if user_id_ref and user_id_ref in entities_dict:
                        user_entity = entities_dict[user_id_ref]
                        if user_entity.id != entity.id:
                            related['initial_users'].append(user_entity)
                            print(f"    👤 Found initial user: {user_entity.name}")

        # 4. Other linked entities (CEventComponent links, etc.)
        # Add more relationship types here as needed

        return related
    
    @staticmethod
    def collect_all_related_recursive(entity, entities_dict, already_collected=None):
        """
        Recursively collect entity and ALL its relationships.
        Returns list of all related entities.
        """
        if already_collected is None:
            already_collected = set()
        
        if entity.id in already_collected:
            return []
        
        result = [entity]
        already_collected.add(entity.id)
        
        # Find all direct relationships
        related = EntityRelationshipDetector.find_all_related_entities(entity, entities_dict)
        
        # Add children
        for child in related['children']:
            result.extend(
                EntityRelationshipDetector.collect_all_related_recursive(
                    child, entities_dict, already_collected
                )
            )
        
        # Add seated entities
        for seated in related['seated']:
            result.extend(
                EntityRelationshipDetector.collect_all_related_recursive(
                    seated, entities_dict, already_collected
                )
            )

        # Add initial users (pilots/drivers)
        for user in related['initial_users']:
            result.extend(
                EntityRelationshipDetector.collect_all_related_recursive(
                    user, entities_dict, already_collected
                )
            )

        # Add linked entities
        for linked in related['linked']:
            result.extend(
                EntityRelationshipDetector.collect_all_related_recursive(
                    linked, entities_dict, already_collected
                )
            )
        
        return result


class EntityImportDialog(QDialog):
    """Dialog for importing entities from XML files - WITH MISSIONLAYER SELECTION"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_editor = parent
        self.objects_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "objects")
        self.mass_export_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mass_exported_objects")
        self.selected_collection = None
        self.collection_metadata = None
        self.entities_to_import = []
        self.available_layers = []  # NEW: Store available layers
        
        self.setWindowTitle("Import Entities")
        self.setModal(True)
        self.resize(700, 600)  # Increased height for layer combo
        
        self.setup_ui()
        self.load_collections()
    
    def setup_ui(self):
        """Setup the import dialog UI - WITH PER-ENTITY TARGET ASSIGNMENT"""
        layout = QVBoxLayout(self)
        
        # Title
        title_label = QLabel("Import Entities from Collection")
        title_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)
        
        # Collections list
        collections_group = QGroupBox("Available Collections")
        collections_layout = QVBoxLayout(collections_group)
        
        self.collections_list = QListWidget()
        self.collections_list.currentItemChanged.connect(self.on_collection_selected)
        collections_layout.addWidget(self.collections_list)
        
        browse_button = QPushButton("Browse for Collection Folder...")
        browse_button.clicked.connect(self.browse_for_collection)
        collections_layout.addWidget(browse_button)
        
        layout.addWidget(collections_group)
        
        # Collection info
        self.collection_info_label = QLabel("Select a collection to view details")
        layout.addWidget(self.collection_info_label)
        
        # Entities to import - WITH TARGET ASSIGNMENT
        entities_group = QGroupBox("Entities in Collection")
        entities_layout = QVBoxLayout(entities_group)
        
        # Add entity tree widget for better organization
        self.entities_tree = QTreeWidget()
        self.entities_tree.setHeaderLabels(["Entity", "Type", "Target", "Sector", "Layer"])
        self.entities_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.entities_tree.setColumnWidth(0, 200)
        self.entities_tree.setColumnWidth(1, 100)
        self.entities_tree.setColumnWidth(2, 100)
        self.entities_tree.setColumnWidth(3, 100)
        self.entities_tree.setColumnWidth(4, 120)
        self.entities_tree.itemDoubleClicked.connect(self.on_entity_double_clicked)
        entities_layout.addWidget(self.entities_tree)
        
        # Add selection and grouping buttons
        selection_button_layout = QHBoxLayout()
        
        select_all_button = QPushButton("Select All")
        select_all_button.clicked.connect(self.select_all_entities)
        selection_button_layout.addWidget(select_all_button)

        deselect_all_button = QPushButton("Deselect All")
        deselect_all_button.clicked.connect(self.deselect_all_entities)
        selection_button_layout.addWidget(deselect_all_button)
        
        selection_button_layout.addStretch()
        
        # Group assignment buttons — row 1
        assign_mapsdata_btn = QPushButton("📄 Assign Selected → Mapsdata")
        assign_mapsdata_btn.clicked.connect(self.assign_selected_to_mapsdata)
        selection_button_layout.addWidget(assign_mapsdata_btn)

        assign_worldsector_btn = QPushButton("🗂️ Assign Selected → WorldSector")
        assign_worldsector_btn.clicked.connect(self.assign_selected_to_worldsector)
        selection_button_layout.addWidget(assign_worldsector_btn)

        entities_layout.addLayout(selection_button_layout)

        # Group assignment buttons — row 2 (landmark + omnis)
        assign_button_layout2 = QHBoxLayout()
        assign_button_layout2.addStretch()

        assign_lmfar_btn = QPushButton("🌿 Assign Selected → LandmarkFar")
        assign_lmfar_btn.clicked.connect(lambda: self.assign_selected_to_landmark("far"))
        assign_button_layout2.addWidget(assign_lmfar_btn)

        assign_lmnear_btn = QPushButton("🌱 Assign Selected → LandmarkNear")
        assign_lmnear_btn.clicked.connect(lambda: self.assign_selected_to_landmark("near"))
        assign_button_layout2.addWidget(assign_lmnear_btn)

        assign_omnis_btn = QPushButton("🌍 Assign Selected → Omnis")
        assign_omnis_btn.clicked.connect(self.assign_selected_to_omnis)
        assign_button_layout2.addWidget(assign_omnis_btn)

        entities_layout.addLayout(assign_button_layout2)

        layout.addWidget(entities_group)

        # Buttons
        button_layout = QHBoxLayout()
        
        self.import_button = QPushButton("Import Selected Entities")
        self.import_button.clicked.connect(self.import_entities)
        self.import_button.setEnabled(False)
        button_layout.addWidget(self.import_button)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        
        # Status label
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        
        # Initial setup - load available sectors for later use
        self.load_available_sectors()


    def assign_selected_to_worldsector(self):
        """Assign selected entities to WorldSector target with dialog for sector/layer selection"""
        selected_items = self.entities_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select entities to assign.")
            return
        
        # Create a dialog to choose sector and layer
        dialog = QDialog(self)
        dialog.setWindowTitle("Select WorldSector Target")
        dialog.setModal(True)
        dialog_layout = QVBoxLayout(dialog)
        
        # Sector selection
        dialog_layout.addWidget(QLabel("Select Target WorldSector:"))
        sector_combo = QComboBox()
        
        # Populate with available sectors
        sector_combo.addItem("-- Select Sector --", None)
        if hasattr(self, 'available_sectors'):
            for sector_info in self.available_sectors:
                sector_combo.addItem(sector_info['display_name'], sector_info['path'])
        
        dialog_layout.addWidget(sector_combo)
        
        # Layer selection row (combo + add-layer button side by side)
        dialog_layout.addWidget(QLabel("Select Target MissionLayer:"))
        layer_row = QHBoxLayout()
        layer_combo = QComboBox()
        layer_row.addWidget(layer_combo)

        add_layer_btn = QPushButton("Add main layer")
        add_layer_btn.setFixedWidth(110)
        add_layer_btn.setToolTip("Add a 'main' MissionLayer to the selected sector file")
        add_layer_btn.setEnabled(False)
        layer_row.addWidget(add_layer_btn)
        dialog_layout.addLayout(layer_row)

        # Layer info label
        layer_info_label = QLabel("")
        layer_info_label.setStyleSheet("color: #666; font-size: 9pt;")
        layer_info_label.setWordWrap(True)
        dialog_layout.addWidget(layer_info_label)

        def _reload_layers():
            """Populate layer_combo from the currently selected sector."""
            layer_combo.clear()
            sector_path = sector_combo.currentData()
            if not sector_path:
                add_layer_btn.setEnabled(False)
                return
            try:
                if not hasattr(self.parent_editor, 'worldsectors_trees'):
                    self.parent_editor.worldsectors_trees = {}
                if sector_path not in self.parent_editor.worldsectors_trees:
                    if os.path.exists(sector_path):
                        self.parent_editor.worldsectors_trees[sector_path] = ET.parse(sector_path)
                tree = self.parent_editor.worldsectors_trees[sector_path]
                root = tree.getroot()
                mission_layers = root.findall(".//object[@name='MissionLayer']")
                has_main = any(
                    ml.find("field[@name='text_PathId']") is not None and
                    ml.find("field[@name='text_PathId']").get('value-String') == 'main'
                    for ml in mission_layers
                )
                add_layer_btn.setEnabled(not has_main)
                for i, mission_layer in enumerate(mission_layers):
                    name_field = mission_layer.find(".//field[@name='text_PathId']")
                    layer_name = name_field.get('value-String', f'Layer {i+1}') if name_field is not None else f'Layer {i+1}'
                    entity_count = len(mission_layer.findall("object[@name='Entity']"))
                    layer_combo.addItem(f"{i+1}. {layer_name} ({entity_count} entities)", {'index': i, 'name': layer_name})
                if not mission_layers:
                    layer_combo.addItem("(no layers — click 'Add main layer')", None)
            except Exception as e:
                print(f"Error loading layers: {e}")
                layer_combo.addItem("⚠ Error loading layers", None)
                add_layer_btn.setEnabled(False)

        def on_sector_changed(index):
            layer_info_label.setText("")
            if index <= 0:
                layer_combo.clear()
                add_layer_btn.setEnabled(False)
                return
            _reload_layers()

        def on_add_layer_clicked():
            sector_path = sector_combo.currentData()
            if not sector_path:
                return
            try:
                if not hasattr(self.parent_editor, 'worldsectors_trees'):
                    self.parent_editor.worldsectors_trees = {}
                if sector_path not in self.parent_editor.worldsectors_trees:
                    if os.path.exists(sector_path):
                        self.parent_editor.worldsectors_trees[sector_path] = ET.parse(sector_path)
                tree = self.parent_editor.worldsectors_trees[sector_path]
                self._create_main_mission_layer(tree.getroot())
                print(f"Added 'main' MissionLayer to {os.path.basename(sector_path)}")
                _reload_layers()
            except Exception as e:
                print(f"Error adding main layer: {e}")

        add_layer_btn.clicked.connect(on_add_layer_clicked)
        sector_combo.currentIndexChanged.connect(on_sector_changed)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_button = QPushButton("Assign")
        ok_button.clicked.connect(dialog.accept)
        button_layout.addWidget(ok_button)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_button)
        
        dialog_layout.addLayout(button_layout)
        
        # Show dialog
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        
        # Get selected values
        sector_path = sector_combo.currentData()
        layer_data = layer_combo.currentData()
        
        if not sector_path or not layer_data:
            QMessageBox.warning(self, "Invalid Selection", "Please select both a sector and layer.")
            return
        
        layer_index = layer_data['index']
        layer_name = layer_data['name']
        sector_name = os.path.basename(sector_path)
        
        # Extract sector number
        import re
        match = re.search(r'worldsector(\d+)', sector_name)
        sector_num = match.group(1) if match else "?"
        
        # Assign to all selected items
        for item in selected_items:
            item.setText(2, "WorldSector")
            item.setText(3, f"Sector {sector_num}")
            item.setText(4, layer_name)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, "worldsector")
            item.setData(0, Qt.ItemDataRole.UserRole + 2, layer_index)
            item.setData(0, Qt.ItemDataRole.UserRole + 3, sector_path)
        
        print(f"✅ Assigned {len(selected_items)} entities to WorldSector {sector_num} → {layer_name}")


    def assign_selected_to_mapsdata(self):
        """Assign selected entities to Mapsdata target"""
        selected_items = self.entities_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select entities to assign.")
            return
        
        for item in selected_items:
            item.setText(2, "Mapsdata")
            item.setText(3, "-")
            item.setText(4, "-")
            item.setData(0, Qt.ItemDataRole.UserRole + 1, "mapsdata")
            item.setData(0, Qt.ItemDataRole.UserRole + 2, None)
            item.setData(0, Qt.ItemDataRole.UserRole + 3, None)
        
        print(f"✅ Assigned {len(selected_items)} entities to Mapsdata")


    def assign_selected_to_landmark(self, kind):
        """Assign selected entities to a LandmarkFar or LandmarkNear file"""
        selected_items = self.entities_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select entities to assign.")
            return

        label = "LandmarkFar" if kind == "far" else "LandmarkNear"
        landmark_files = self._load_available_landmark_files(kind)
        if not landmark_files:
            QMessageBox.warning(self, "No Files Found",
                f"No {label} files found. Load a level first.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Select {label} Target")
        dialog.setModal(True)
        dlayout = QVBoxLayout(dialog)
        dlayout.addWidget(QLabel(f"Select Target {label} File:"))
        file_combo = QComboBox()
        file_combo.addItem("-- Select File --", None)
        for info in landmark_files:
            file_combo.addItem(info['display_name'], info['path'])
        dlayout.addWidget(file_combo)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Assign")
        ok_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(ok_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        btn_row.addWidget(cancel_btn)
        dlayout.addLayout(btn_row)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        file_path = file_combo.currentData()
        if not file_path:
            QMessageBox.warning(self, "Invalid Selection", "Please select a file.")
            return

        import re
        fn = os.path.basename(file_path)
        if kind == "far":
            m = re.search(r'landmarkfar_(\d+)', fn, re.IGNORECASE)
        else:
            m = re.search(r'landmarknear(\d+)', fn, re.IGNORECASE)
        sector_num = m.group(1) if m else "?"

        target_type = "landmark_far" if kind == "far" else "landmark_near"
        for item in selected_items:
            item.setText(2, label)
            item.setText(3, f"Sector {sector_num}")
            item.setText(4, "main")
            item.setData(0, Qt.ItemDataRole.UserRole + 1, target_type)
            item.setData(0, Qt.ItemDataRole.UserRole + 2, 0)
            item.setData(0, Qt.ItemDataRole.UserRole + 3, file_path)

        print(f"✅ Assigned {len(selected_items)} entities to {label} Sector {sector_num}")

    def assign_selected_to_omnis(self):
        """Assign selected entities to the Omnis file"""
        selected_items = self.entities_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select entities to assign.")
            return

        if not hasattr(self.parent_editor, 'omnis_tree') or self.parent_editor.omnis_tree is None:
            QMessageBox.warning(self, "Omnis Not Loaded",
                "Omnis file is not loaded. Load a level first.")
            return

        for item in selected_items:
            item.setText(2, "Omnis")
            item.setText(3, "-")
            item.setText(4, "-")
            item.setData(0, Qt.ItemDataRole.UserRole + 1, "omnis")
            item.setData(0, Qt.ItemDataRole.UserRole + 2, None)
            item.setData(0, Qt.ItemDataRole.UserRole + 3, None)

        print(f"✅ Assigned {len(selected_items)} entities to Omnis")

    def _load_available_landmark_files(self, kind):
        """Return list of available landmark file infos for the given kind ('far' or 'near')"""
        import re
        if kind == "far":
            pattern = re.compile(r'^landmarkfar_(\d+)\.data\.fcb\.converted\.xml$', re.IGNORECASE)
        else:
            pattern = re.compile(r'^landmarknear(\d+)\.data\.fcb\.converted\.xml$', re.IGNORECASE)

        landmark_files = []
        existing_paths = set()

        def _add(file_path):
            if file_path in existing_paths:
                return
            m = pattern.match(os.path.basename(file_path))
            if m:
                sector_num = m.group(1)
                landmark_files.append({
                    'display_name': f"Sector {sector_num} ({os.path.basename(file_path)})",
                    'path': file_path,
                    'sector_num': int(sector_num),
                })
                existing_paths.add(file_path)

        if hasattr(self.parent_editor, 'worldsectors_trees'):
            for fp in self.parent_editor.worldsectors_trees.keys():
                _add(fp)

        if hasattr(self.parent_editor, 'worldsectors_path') and self.parent_editor.worldsectors_path:
            ws_path = self.parent_editor.worldsectors_path
            if os.path.exists(ws_path):
                for fname in os.listdir(ws_path):
                    if fname.endswith('.converted.xml'):
                        _add(os.path.join(ws_path, fname))

        landmark_files.sort(key=lambda x: x['sector_num'])
        return landmark_files

    def load_available_sectors(self):
        """Load available worldsector files and store them for later use"""
        self.available_sectors = []
        
        sectors_added = 0
        existing_paths = set()
        
        # Method 1: Check worldsectors_trees
        if hasattr(self.parent_editor, 'worldsectors_trees') and self.parent_editor.worldsectors_trees:
            for file_path in self.parent_editor.worldsectors_trees.keys():
                filename = os.path.basename(file_path)
                if 'worldsector' in filename:
                    import re
                    match = re.search(r'worldsector(\d+)', filename)
                    if match:
                        sector_num = match.group(1)
                        display_name = f"Sector {sector_num} ({filename})"
                        self.available_sectors.append({
                            'display_name': display_name,
                            'path': file_path,
                            'sector_num': sector_num
                        })
                        existing_paths.add(file_path)
                        sectors_added += 1
        
        # Method 2: Check entities for source files
        sectors_from_entities = set()
        if hasattr(self.parent_editor, 'entities'):
            for entity in self.parent_editor.entities:
                source_file = getattr(entity, 'source_file_path', None)
                if source_file and 'worldsector' in source_file and os.path.exists(source_file):
                    sectors_from_entities.add(source_file)
        
        for sector_file in sectors_from_entities:
            if sector_file not in existing_paths:
                filename = os.path.basename(sector_file)
                import re
                match = re.search(r'worldsector(\d+)', filename)
                if match:
                    sector_num = match.group(1)
                    display_name = f"Sector {sector_num} ({filename})"
                    self.available_sectors.append({
                        'display_name': display_name,
                        'path': sector_file,
                        'sector_num': sector_num
                    })
                    existing_paths.add(sector_file)
                    sectors_added += 1
        
        # Method 3: Check worldsectors_path
        if hasattr(self.parent_editor, 'worldsectors_path') and self.parent_editor.worldsectors_path:
            worldsectors_path = self.parent_editor.worldsectors_path
            if os.path.exists(worldsectors_path):
                for file in os.listdir(worldsectors_path):
                    if file.endswith('.converted.xml') and 'worldsector' in file:
                        file_path = os.path.join(worldsectors_path, file)
                        if file_path not in existing_paths:
                            import re
                            match = re.search(r'worldsector(\d+)', file)
                            if match:
                                sector_num = match.group(1)
                                display_name = f"Sector {sector_num} ({file})"
                                self.available_sectors.append({
                                    'display_name': display_name,
                                    'path': file_path,
                                    'sector_num': sector_num
                                })
                                existing_paths.add(file_path)
                                sectors_added += 1
        
        print(f"Loaded {sectors_added} available sectors for assignment")

    def select_all_entities(self):
        """Select all entities in the tree"""
        iterator = QTreeWidgetItemIterator(self.entities_tree)
        while iterator.value():
            item = iterator.value()
            item.setSelected(True)
            iterator += 1

    def deselect_all_entities(self):
        """Deselect all entities in the tree"""
        iterator = QTreeWidgetItemIterator(self.entities_tree)
        while iterator.value():
            item = iterator.value()
            item.setSelected(False)
            iterator += 1

    def on_entity_double_clicked(self, item, column):
        """Handle double-click on entity - toggle between Mapsdata and WorldSector"""
        if column == 2:  # Target column
            current_target = item.data(0, Qt.ItemDataRole.UserRole + 1)
            
            if current_target == "mapsdata":
                # Switch to WorldSector
                sector_data = self.sector_combo.currentData()
                layer_index = self.layer_combo.currentData()
                
                if sector_data and layer_index is not None:
                    layer_name = self.available_layers[layer_index]['name'] if layer_index < len(self.available_layers) else f"Layer {layer_index + 1}"
                    item.setText(2, "WorldSector")
                    item.setData(0, Qt.ItemDataRole.UserRole + 1, "worldsector")
                    item.setText(3, layer_name)
                    item.setData(0, Qt.ItemDataRole.UserRole + 2, layer_index)
                    item.setData(0, Qt.ItemDataRole.UserRole + 3, sector_data)
                else:
                    QMessageBox.warning(self, "No Target", "Please select a WorldSector and Layer first.")
            else:
                # Switch to Mapsdata
                item.setText(2, "Mapsdata")
                item.setData(0, Qt.ItemDataRole.UserRole + 1, "mapsdata")
                item.setText(3, "-")
                item.setData(0, Qt.ItemDataRole.UserRole + 2, None)

    def load_entities_from_collection(self, collection_path):
        """Load entities from the collection folder - WITH RELATIONSHIP TRACKING"""
        self.entities_tree.clear()
        
        # Load metadata to get relationship info
        metadata_path = os.path.join(collection_path, "collection_info.json")
        structure_child_map = {}
        seated_npc_map = {}
        entity_metadata_map = {}
        
        initial_user_map = {}

        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    structure_child_map = metadata.get('structure_child_map', {})
                    seated_npc_map = metadata.get('seated_npc_map', {})
                    initial_user_map = metadata.get('initial_user_map', {})

                    # Create a map of entity_id -> metadata
                    for entity_meta in metadata.get('entities', []):
                        entity_metadata_map[entity_meta['id']] = entity_meta
            except Exception as e:
                print(f"Error loading metadata: {e}")
        
        # Find all XML files
        xml_files = [f for f in os.listdir(collection_path) 
                    if f.endswith('.xml') and f != 'collection_info.json']
        
        # Parse all entities first
        entities_data = []
        for xml_file in xml_files:
            xml_path = os.path.join(collection_path, xml_file)
            
            try:
                tree = ET.parse(xml_path)
                root = tree.getroot()
                
                entity_name = XMLHelper.extract_entity_name(root)
                entity_id = XMLHelper.extract_entity_id(root)
                x, y, z = XMLHelper.extract_position_from_xml(root)
                
                # Get metadata for this entity
                entity_meta = entity_metadata_map.get(entity_id, {})
                
                entities_data.append({
                    'xml_path': xml_path,
                    'name': entity_name,
                    'id': entity_id,
                    'position': (x, y, z),
                    'xml_element': root,
                    'filename': xml_file,
                    'is_parent': entity_meta.get('is_parent', False),
                    'is_child': entity_meta.get('is_child', False),
                    'is_vehicle': entity_meta.get('is_vehicle', False),
                    'is_seated': entity_meta.get('is_seated', False),
                    'is_initial_user_vehicle': entity_meta.get('is_initial_user_vehicle', False),
                    'is_initial_user': entity_meta.get('is_initial_user', False),
                    'source_file': entity_meta.get('source_file', 'unknown'),
                    'child_count': entity_meta.get('child_count', 0),
                    'seated_npc_count': entity_meta.get('seated_npc_count', 0),
                    'initial_user_count': entity_meta.get('initial_user_count', 0)
                })
                    
            except Exception as e:
                print(f"Error loading entity from {xml_file}: {e}")
        
        # Collect all initial user IDs for grouping
        all_initial_user_ids_import = set()
        for user_ids in initial_user_map.values():
            all_initial_user_ids_import.update(user_ids)

        # Now organize into tree structure with groups
        parent_items = {}  # Track parent items by entity_id
        child_items_to_add = []  # Store (parent_id, child_data) tuples
        seated_items_to_add = []  # Store (vehicle_id, npc_data) tuples
        initial_user_items_to_add = []  # Store (vehicle_id, user_data) tuples

        # First pass: Create parent items and standalone entities
        for entity_data in entities_data:
            entity_id = entity_data['id']

            # Determine entity type for display
            entity_type = "Entity"
            if entity_data['is_parent']:
                entity_type = f"🏗️ Structure ({entity_data['child_count']})"
            elif entity_data['is_initial_user_vehicle']:
                npc_info = f" +{entity_data['seated_npc_count']} NPC" if entity_data['seated_npc_count'] else ""
                entity_type = f"✈️ Vehicle ({entity_data['initial_user_count']} pilot{npc_info})"
            elif entity_data['is_vehicle']:
                entity_type = f"🚗 Vehicle ({entity_data['seated_npc_count']})"
            elif entity_data['is_child']:
                entity_type = "📦 Child"
            elif entity_data['is_seated']:
                entity_type = "🪑 Seated NPC"
            elif entity_data['is_initial_user']:
                entity_type = "👤 Pilot/Driver"
            
            # Determine default target based on source
            default_target = "Mapsdata"
            default_sector = "-"
            default_layer = "-"
            if entity_data['source_file'] == 'worldsectors':
                default_target = "WorldSector"
                default_sector = "Unknown"
                default_layer = "outside_entity"
            
            # If this is a child or seated NPC, defer adding it
            if entity_data['is_child']:
                # Find parent
                parent_id = None
                for pid, child_ids in structure_child_map.items():
                    if entity_id in child_ids:
                        parent_id = pid
                        break
                if parent_id:
                    child_items_to_add.append((parent_id, entity_data, entity_type, default_target, default_sector, default_layer))
                    continue
            
            if entity_data['is_seated']:
                # Find vehicle
                vehicle_id = None
                for vid, npc_ids in seated_npc_map.items():
                    if entity_id in npc_ids:
                        vehicle_id = vid
                        break
                if vehicle_id:
                    seated_items_to_add.append((vehicle_id, entity_data, entity_type, default_target, default_sector, default_layer))
                    continue

            if entity_data['is_initial_user']:
                # Find vehicle this user belongs to
                vehicle_id = None
                for vid, user_ids in initial_user_map.items():
                    if entity_id in user_ids:
                        vehicle_id = vid
                        break
                if vehicle_id:
                    initial_user_items_to_add.append((vehicle_id, entity_data, entity_type, default_target, default_sector, default_layer))
                    continue

            # Create tree item for parent or standalone entity
            item = QTreeWidgetItem(self.entities_tree)
            item.setText(0, entity_data['name'])
            item.setText(1, entity_type)
            item.setText(2, default_target)
            item.setText(3, default_sector)
            item.setText(4, default_layer)

            # Store all data
            item.setData(0, Qt.ItemDataRole.UserRole, entity_data)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, default_target.lower())  # target type
            item.setData(0, Qt.ItemDataRole.UserRole + 2, None)  # layer index
            item.setData(0, Qt.ItemDataRole.UserRole + 3, None)  # sector path

            item.setSelected(True)

            # Track parent items
            if entity_data['is_parent'] or entity_data['is_vehicle'] or entity_data['is_initial_user_vehicle']:
                parent_items[entity_id] = item

        # Second pass: Add children to their parents
        for parent_id, child_data, entity_type, default_target, default_sector, default_layer in child_items_to_add:
            if parent_id in parent_items:
                parent_item = parent_items[parent_id]

                child_item = QTreeWidgetItem(parent_item)
                child_item.setText(0, child_data['name'])
                child_item.setText(1, entity_type)
                child_item.setText(2, default_target)
                child_item.setText(3, default_sector)
                child_item.setText(4, default_layer)

                child_item.setData(0, Qt.ItemDataRole.UserRole, child_data)
                child_item.setData(0, Qt.ItemDataRole.UserRole + 1, default_target.lower())
                child_item.setData(0, Qt.ItemDataRole.UserRole + 2, None)
                child_item.setData(0, Qt.ItemDataRole.UserRole + 3, None)

                child_item.setSelected(True)
                parent_item.setExpanded(True)

        # Third pass: Add seated NPCs to their vehicles
        for vehicle_id, npc_data, entity_type, default_target, default_sector, default_layer in seated_items_to_add:
            if vehicle_id in parent_items:
                vehicle_item = parent_items[vehicle_id]

                npc_item = QTreeWidgetItem(vehicle_item)
                npc_item.setText(0, npc_data['name'])
                npc_item.setText(1, entity_type)
                npc_item.setText(2, default_target)
                npc_item.setText(3, default_sector)
                npc_item.setText(4, default_layer)

                npc_item.setData(0, Qt.ItemDataRole.UserRole, npc_data)
                npc_item.setData(0, Qt.ItemDataRole.UserRole + 1, default_target.lower())
                npc_item.setData(0, Qt.ItemDataRole.UserRole + 2, None)
                npc_item.setData(0, Qt.ItemDataRole.UserRole + 3, None)

                npc_item.setSelected(True)
                vehicle_item.setExpanded(True)

        # Fourth pass: Add initial users (pilots/drivers) to their vehicles
        for vehicle_id, user_data, entity_type, default_target, default_sector, default_layer in initial_user_items_to_add:
            if vehicle_id in parent_items:
                vehicle_item = parent_items[vehicle_id]

                user_item = QTreeWidgetItem(vehicle_item)
                user_item.setText(0, user_data['name'])
                user_item.setText(1, entity_type)
                user_item.setText(2, default_target)
                user_item.setText(3, default_sector)
                user_item.setText(4, default_layer)

                user_item.setData(0, Qt.ItemDataRole.UserRole, user_data)
                user_item.setData(0, Qt.ItemDataRole.UserRole + 1, default_target.lower())
                user_item.setData(0, Qt.ItemDataRole.UserRole + 2, None)
                user_item.setData(0, Qt.ItemDataRole.UserRole + 3, None)

                user_item.setSelected(True)
                vehicle_item.setExpanded(True)

        print(f"✅ Loaded {len(entities_data)} entities with relationship tracking")
        print(f"   - Structures: {len([e for e in entities_data if e['is_parent']])}")
        print(f"   - Children: {len([e for e in entities_data if e['is_child']])}")
        print(f"   - Vehicles (seated): {len([e for e in entities_data if e['is_vehicle']])}")
        print(f"   - Seated NPCs: {len([e for e in entities_data if e['is_seated']])}")
        print(f"   - Vehicles (initial users): {len([e for e in entities_data if e['is_initial_user_vehicle']])}")
        print(f"   - Initial users (pilots/drivers): {len([e for e in entities_data if e['is_initial_user']])}")

    def import_entities(self):
        """Import entities based on their assigned targets"""
        # Collect all items (including children)
        all_items = []
        iterator = QTreeWidgetItemIterator(self.entities_tree, QTreeWidgetItemIterator.IteratorFlag.Selected)
        while iterator.value():
            all_items.append(iterator.value())
            iterator += 1
        
        if not all_items:
            QMessageBox.warning(self, "No Selection", "Please select entities to import.")
            return
        
        # Group items by target
        mapsdata_items = []
        worldsector_items = {}  # {(sector_path, layer_index): [items]}
        landmark_items = {}     # {(file_path, layer_index): [items]}
        omnis_items = []

        for item in all_items:
            target_type = item.data(0, Qt.ItemDataRole.UserRole + 1)

            if target_type == "mapsdata":
                mapsdata_items.append(item)
            elif target_type == "worldsector":
                layer_index = item.data(0, Qt.ItemDataRole.UserRole + 2)
                sector_path = item.data(0, Qt.ItemDataRole.UserRole + 3)
                if sector_path and layer_index is not None:
                    key = (sector_path, layer_index)
                    worldsector_items.setdefault(key, []).append(item)
            elif target_type in ("landmark_far", "landmark_near"):
                layer_index = item.data(0, Qt.ItemDataRole.UserRole + 2)
                file_path = item.data(0, Qt.ItemDataRole.UserRole + 3)
                if file_path and layer_index is not None:
                    key = (file_path, layer_index)
                    landmark_items.setdefault(key, []).append(item)
            elif target_type == "omnis":
                omnis_items.append(item)

        # Build confirmation message
        confirm_msg = f"Import {len(all_items)} entities:\n\n"
        if mapsdata_items:
            confirm_msg += f"📄 Mapsdata.xml: {len(mapsdata_items)} entities\n"

        for (sector_path, layer_index), items in worldsector_items.items():
            sector_name = os.path.basename(sector_path)
            layer_name = items[0].text(4) if items else f"Layer {layer_index + 1}"
            confirm_msg += f"🗂️ {sector_name} → {layer_name}: {len(items)} entities\n"

        for (file_path, layer_index), items in landmark_items.items():
            confirm_msg += f"🌿 {os.path.basename(file_path)}: {len(items)} entities\n"

        if omnis_items:
            confirm_msg += f"🌍 Omnis: {len(omnis_items)} entities\n"
        
        reply = QMessageBox.question(
            self,
            "Confirm Import",
            confirm_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        try:
            all_imported_entities = []
            
            # Import to Mapsdata
            if mapsdata_items:
                print("\n📄 IMPORTING TO MAPSDATA...")
                mapsdata_entities = self._import_to_mapsdata_internal(mapsdata_items)
                all_imported_entities.extend(mapsdata_entities)
            
            # Import to WorldSectors
            for (sector_path, layer_index), items in worldsector_items.items():
                print(f"\n🗂️ IMPORTING TO WORLDSECTOR...")
                worldsector_entities = self._import_to_worldsector_internal(items, sector_path, layer_index)
                all_imported_entities.extend(worldsector_entities)

            # Import to Landmark files
            for (file_path, layer_index), items in landmark_items.items():
                target_type = items[0].data(0, Qt.ItemDataRole.UserRole + 1)
                kind = "far" if target_type == "landmark_far" else "near"
                print(f"\n🌿 IMPORTING TO LANDMARK ({kind.upper()})...")
                lm_entities = self._import_to_landmark_internal(items, file_path, layer_index, kind)
                all_imported_entities.extend(lm_entities)

            # Import to Omnis
            if omnis_items:
                print(f"\n🌍 IMPORTING TO OMNIS...")
                omnis_entities = self._import_to_omnis_internal(omnis_items)
                all_imported_entities.extend(omnis_entities)

            # Update editor with all imported entities
            if all_imported_entities:
                self.parent_editor.entities.extend(all_imported_entities)

                # Assign 3D models immediately so imported entities appear in 3D mode
                if hasattr(self.parent_editor, 'canvas') and hasattr(self.parent_editor.canvas, 'model_loader'):
                    try:
                        self.parent_editor.canvas.model_loader.assign_models_to_entities(
                            all_imported_entities,
                            game_mode=getattr(self.parent_editor, 'game_mode', 'avatar')
                        )
                    except Exception as _me:
                        print(f"Warning: could not assign models to imported entities: {_me}")

                self.parent_editor.canvas.set_entities(self.parent_editor.entities, center_view=False)

                if hasattr(self.parent_editor, 'update_entity_tree'):
                    self.parent_editor.update_entity_tree()

                if hasattr(self.parent_editor, 'update_entity_statistics'):
                    self.parent_editor.update_entity_statistics()

                self.parent_editor.canvas.update()
            
            # Show results
            success_msg = f"Successfully imported {len(all_imported_entities)} total entities:\n"
            if mapsdata_items:
                success_msg += f"  📄 Mapsdata: {len(mapsdata_items)} entities\n"
            for (sector_path, layer_index), items in worldsector_items.items():
                layer_name = items[0].text(4) if items else f"Layer {layer_index + 1}"
                success_msg += f"  🗂️ WorldSector ({layer_name}): {len(items)} entities\n"
            for (file_path, layer_index), items in landmark_items.items():
                success_msg += f"  🌿 {os.path.basename(file_path)}: {len(items)} entities\n"
            if omnis_items:
                success_msg += f"  🌍 Omnis: {len(omnis_items)} entities\n"
            
            QMessageBox.information(self, "Import Successful", success_msg)
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import: {str(e)}")
            import traceback
            traceback.print_exc()

    def _build_cross_ref_id_map(self, selected_items):
        """
        Pass 1: Pre-generate new IDs for all entities being imported.
        Returns {old_entity_id_str: new_entity_id_int} so cross-references
        (entUser, AIObject value-Hash64) can be updated to match the new disEntityId.
        """
        id_map = {}
        for item in selected_items:
            entity_data = item.data(0, Qt.ItemDataRole.UserRole)
            old_id = entity_data.get('id')
            if old_id and old_id not in id_map:
                new_id = self.generate_unique_entity_id()
                id_map[old_id] = new_id
        print(f"   🔑 Pre-allocated {len(id_map)} new entity IDs for cross-reference sync")
        return id_map

    def _compute_group_pivot(self, selected_items):
        """Return (px, py, pz) pivot for the import group.
        Uses the parent entity's position if one exists, else the centroid."""
        def _pos(ed):
            p = ed.get('position', (0.0, 0.0, 0.0))
            if isinstance(p, (tuple, list)) and len(p) >= 3:
                return float(p[0]), float(p[1]), float(p[2])
            return 0.0, 0.0, 0.0

        for item in selected_items:
            ed = item.data(0, Qt.ItemDataRole.UserRole)
            if ed.get('is_parent'):
                return _pos(ed)
        xs, ys, zs = [], [], []
        for item in selected_items:
            px, py, pz = _pos(item.data(0, Qt.ItemDataRole.UserRole))
            xs.append(px); ys.append(py); zs.append(pz)
        if xs:
            return sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs)
        return 0.0, 0.0, 0.0

    def _get_viewport_center_world(self):
        """Return (cx, cy, cz) world coords at the current canvas viewport centre."""
        try:
            canvas = self.parent_editor.canvas
            cx, cy = canvas.screen_to_world(canvas.width() / 2, canvas.height() / 2)
            return cx, cy, 0.0
        except Exception:
            return 0.0, 0.0, 0.0

    def _import_to_mapsdata_internal(self, selected_items):
        """Internal method to import to mapsdata - returns list of imported entities"""
        if not hasattr(self.parent_editor, 'xml_tree') or self.parent_editor.xml_tree is None:
            print("⚠️ Mapsdata not loaded, skipping mapsdata import")
            return []

        # Pass 1: pre-allocate IDs so cross-entity references stay in sync
        id_map = self._build_cross_ref_id_map(selected_items)

        # Compute delta once: pivot → viewport centre, so children keep relative offsets
        pivot_x, pivot_y, pivot_z = self._compute_group_pivot(selected_items)
        cx, cy, cz = self._get_viewport_center_world()
        position_delta = (cx - pivot_x, cy - pivot_y, cz - pivot_z)
        print(f"   📐 Import delta (mapsdata): ({position_delta[0]:.2f}, {position_delta[1]:.2f}, {position_delta[2]:.2f})")

        progress = QProgressDialog("Importing to mapsdata...", "Cancel", 0, len(selected_items), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        imported_entities = []

        for i, item in enumerate(selected_items):
            progress.setValue(i)
            entity_data = item.data(0, Qt.ItemDataRole.UserRole)
            entity_name = entity_data['name']
            progress.setLabelText(f"Importing {entity_name} to mapsdata...")
            QApplication.processEvents()

            if progress.wasCanceled():
                break

            success, entity = self.import_single_entity_to_mapsdata(item, id_map=id_map, position_delta=position_delta)
            if success:
                imported_entities.append(entity)

        progress.close()
        return imported_entities

    def _import_to_worldsector_internal(self, selected_items, sector_data, layer_index):
        """Internal method to import to worldsector - returns list of imported entities"""
        # Pass 1: pre-allocate IDs so cross-entity references stay in sync
        id_map = self._build_cross_ref_id_map(selected_items)

        # Compute delta once: pivot → sector centre, so children keep relative offsets
        pivot_x, pivot_y, pivot_z = self._compute_group_pivot(selected_items)
        cx, cy, cz = self._get_sector_center(sector_data)
        position_delta = (cx - pivot_x, cy - pivot_y, cz - pivot_z)
        print(f"   📐 Import delta (worldsector): ({position_delta[0]:.2f}, {position_delta[1]:.2f}, {position_delta[2]:.2f})")

        progress = QProgressDialog("Importing to WorldSector...", "Cancel", 0, len(selected_items), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        imported_entities = []

        for i, item in enumerate(selected_items):
            progress.setValue(i)
            entity_data = item.data(0, Qt.ItemDataRole.UserRole)
            entity_name = entity_data['name']
            progress.setLabelText(f"Importing {entity_name} to WorldSector...")
            QApplication.processEvents()

            if progress.wasCanceled():
                break

            success, entity = self.import_single_entity(item, sector_data, layer_index, id_map=id_map, position_delta=position_delta)
            if success:
                imported_entities.append(entity)

        progress.close()
        return imported_entities

    def _set_entity_landmark_category(self, entity_xml, category):
        """Ensure CMissionComponent on entity has hidCategory = category ('LandmarkFar' or 'LandmarkNear')"""
        import copy
        components = entity_xml.find(".//object[@name='Components']")
        if components is None:
            components = ET.SubElement(entity_xml, 'object', {'hash': 'A115F62D', 'name': 'Components'})

        mission_comp = components.find("object[@name='CMissionComponent']")
        if mission_comp is None:
            mission_comp = ET.SubElement(components, 'object', {'hash': 'D18498C8', 'name': 'CMissionComponent'})

        # text_hidCategory
        tf = mission_comp.find("field[@name='text_hidCategory']")
        if tf is None:
            tf = ET.SubElement(mission_comp, 'field', {
                'hash': '27B31D2E', 'name': 'text_hidCategory', 'type': 'BinHex'})
        tf.set('value-String', category)
        tf.text = (category + '\x00').encode('utf-8').hex().upper()

        # hidCategory (ComputeHash32)
        hf = mission_comp.find("field[@name='hidCategory']")
        if hf is None:
            hf = ET.SubElement(mission_comp, 'field', {
                'hash': '37F59D7D', 'name': 'hidCategory', 'type': 'BinHex'})
        hf.set('value-ComputeHash32', category)
        # Store known hash values; fall back to leaving BinHex text blank if unknown
        _known = {'LandmarkFar': '0E28F6B9', 'LandmarkNear': '13E55A28'}
        if category in _known:
            hf.text = _known[category]

    def _import_to_landmark_internal(self, selected_items, file_path, layer_index, kind):
        """Import entities into a landmark (far or near) file — returns list of imported entities"""
        id_map = self._build_cross_ref_id_map(selected_items)

        pivot_x, pivot_y, pivot_z = self._compute_group_pivot(selected_items)
        cx, cy, cz = self._get_viewport_center_world()
        position_delta = (cx - pivot_x, cy - pivot_y, cz - pivot_z)
        label = "LandmarkFar" if kind == "far" else "LandmarkNear"
        category = "LandmarkFar" if kind == "far" else "LandmarkNear"
        print(f"   📐 Import delta ({label}): ({position_delta[0]:.2f}, {position_delta[1]:.2f}, {position_delta[2]:.2f})")

        progress = QProgressDialog(f"Importing to {label}...", "Cancel", 0, len(selected_items), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        imported_entities = []

        for i, item in enumerate(selected_items):
            progress.setValue(i)
            entity_data = item.data(0, Qt.ItemDataRole.UserRole)
            progress.setLabelText(f"Importing {entity_data['name']} to {label}...")
            QApplication.processEvents()
            if progress.wasCanceled():
                break

            try:
                import copy
                tree = ET.parse(entity_data['xml_path'])
                entity_xml = copy.deepcopy(tree.getroot())

                old_id = entity_data.get('id')
                new_id = id_map.get(old_id, self.generate_unique_entity_id()) if id_map else self.generate_unique_entity_id()
                XMLHelper.update_entity_id(entity_xml, new_id)

                orig_x, orig_y, orig_z = XMLHelper.extract_position_from_xml(entity_xml)
                XMLHelper.update_entity_position(
                    entity_xml,
                    orig_x + position_delta[0],
                    orig_y + position_delta[1],
                    orig_z + position_delta[2],
                )

                # Set the landmark category so the engine streams it correctly
                self._set_entity_landmark_category(entity_xml, category)

                # Reuse sector insertion (landmark files use the same WorldSector XML structure)
                success = self.add_entity_to_sector_with_layer(entity_xml, file_path, layer_index, entity_data['name'])
                if not success:
                    continue

                x, y, z = XMLHelper.extract_position_from_xml(entity_xml)
                entity = Entity(id=str(new_id), name=entity_data['name'], x=x, y=y, z=z, xml_element=entity_xml)
                entity.source_file = "landmark"
                entity.source_file_path = file_path
                imported_entities.append(entity)

            except Exception as e:
                print(f"❌ Error importing {entity_data.get('name','?')} to {label}: {e}")
                import traceback; traceback.print_exc()

        progress.close()

        # Sync the updated tree into landmark_trees so the next Save Level doesn't
        # overwrite this file with the old tree.  add_entity_to_sector_with_layer loads
        # the file into worldsectors_trees; the landmark save step reads landmark_trees —
        # without this sync the imported entities are silently erased on next save.
        if imported_entities:
            updated_tree = (
                getattr(self.parent_editor, 'worldsectors_trees', {}).get(file_path)
            )
            if updated_tree is not None:
                if not hasattr(self.parent_editor, 'landmark_trees'):
                    self.parent_editor.landmark_trees = {}
                if not hasattr(self.parent_editor, 'landmark_clean_hashes'):
                    self.parent_editor.landmark_clean_hashes = {}
                self.parent_editor.landmark_trees[file_path] = updated_tree
                import io as _io
                _buf = _io.BytesIO()
                updated_tree.write(_buf, encoding='utf-8', xml_declaration=True)
                # Store a hash that differs from any previous clean hash so the save
                # step always writes the file (it contains the newly imported entity).
                self.parent_editor.landmark_clean_hashes[file_path] = str(
                    hash(_buf.getvalue())
                ) + "_dirty"

        return imported_entities

    def _import_to_omnis_internal(self, selected_items):
        """Import entities into the omnis file — returns list of imported entities"""
        if not hasattr(self.parent_editor, 'omnis_tree') or self.parent_editor.omnis_tree is None:
            print("⚠️ Omnis not loaded, skipping omnis import")
            return []

        id_map = self._build_cross_ref_id_map(selected_items)

        pivot_x, pivot_y, pivot_z = self._compute_group_pivot(selected_items)
        cx, cy, cz = self._get_viewport_center_world()
        position_delta = (cx - pivot_x, cy - pivot_y, cz - pivot_z)
        print(f"   📐 Import delta (omnis): ({position_delta[0]:.2f}, {position_delta[1]:.2f}, {position_delta[2]:.2f})")

        omnis_root = self.parent_editor.omnis_tree.getroot()
        mission_layer = omnis_root.find(".//object[@name='MissionLayer']")
        if mission_layer is None:
            self._create_main_mission_layer(omnis_root)
            mission_layer = omnis_root.find(".//object[@name='MissionLayer']")

        omnis_path = None
        if hasattr(self.parent_editor, '_find_tree_file_path'):
            try:
                omnis_path = self.parent_editor._find_tree_file_path('omnis')
            except Exception:
                pass

        progress = QProgressDialog("Importing to Omnis...", "Cancel", 0, len(selected_items), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        imported_entities = []

        for i, item in enumerate(selected_items):
            progress.setValue(i)
            entity_data = item.data(0, Qt.ItemDataRole.UserRole)
            progress.setLabelText(f"Importing {entity_data['name']} to Omnis...")
            QApplication.processEvents()
            if progress.wasCanceled():
                break

            try:
                import copy
                tree = ET.parse(entity_data['xml_path'])
                entity_xml = copy.deepcopy(tree.getroot())

                old_id = entity_data.get('id')
                new_id = id_map.get(old_id, self.generate_unique_entity_id()) if id_map else self.generate_unique_entity_id()
                XMLHelper.update_entity_id(entity_xml, new_id)

                orig_x, orig_y, orig_z = XMLHelper.extract_position_from_xml(entity_xml)
                XMLHelper.update_entity_position(
                    entity_xml,
                    orig_x + position_delta[0],
                    orig_y + position_delta[1],
                    orig_z + position_delta[2],
                )

                xml_string = ET.tostring(entity_xml, encoding='unicode')
                entity_copy = ET.fromstring(xml_string)
                mission_layer.append(entity_copy)

                x, y, z = XMLHelper.extract_position_from_xml(entity_xml)
                entity = Entity(id=str(new_id), name=entity_data['name'], x=x, y=y, z=z, xml_element=entity_copy)
                entity.source_file = "omnis"
                entity.source_file_path = omnis_path
                imported_entities.append(entity)
                print(f"   ✅ Added {entity_data['name']} to Omnis")

            except Exception as e:
                print(f"❌ Error importing {entity_data.get('name','?')} to Omnis: {e}")
                import traceback; traceback.print_exc()

        progress.close()

        if imported_entities:
            try:
                ET.indent(self.parent_editor.omnis_tree, space="  ")
            except AttributeError:
                pass
            if omnis_path:
                self.parent_editor.omnis_tree.write(omnis_path, encoding='utf-8', xml_declaration=True)
                print(f"💾 Saved omnis file: {os.path.basename(omnis_path)}")
            self.parent_editor.omnis_tree_modified = True

        return imported_entities

    def on_sector_changed(self, index):
        """Handle sector selection change - load available MissionLayers"""
        self.layer_combo.clear()
        self.available_layers = []
        self.layer_info_label.setText("")
        
        if index <= 0:  # "-- Select Target Sector --"
            return
        
        sector_file_path = self.sector_combo.currentData()
        if not sector_file_path:
            return
        
        try:
            # Load the sector file to read MissionLayers
            if not hasattr(self.parent_editor, 'worldsectors_trees'):
                self.parent_editor.worldsectors_trees = {}
            
            if sector_file_path not in self.parent_editor.worldsectors_trees:
                if os.path.exists(sector_file_path):
                    import xml.etree.ElementTree as ET
                    tree = ET.parse(sector_file_path)
                    self.parent_editor.worldsectors_trees[sector_file_path] = tree
            
            tree = self.parent_editor.worldsectors_trees[sector_file_path]
            root = tree.getroot()
            
            # Find all MissionLayers
            mission_layers = root.findall(".//object[@name='MissionLayer']")
            
            if not mission_layers:
                print(f"⚠️ No MissionLayers in {os.path.basename(sector_file_path)} — 'main' will be auto-created on import")
                self.layer_combo.addItem("1. main (will be created on import)", 0)
                self.available_layers.append({'index': 0, 'name': 'main', 'entity_count': 0})
                self.layer_combo.setCurrentIndex(0)
                self.update_layer_info(0)
                return

            print(f"\n📋 Found {len(mission_layers)} MissionLayer(s) in {os.path.basename(sector_file_path)}")
            
            # Add each MissionLayer to combo
            for i, mission_layer in enumerate(mission_layers):
                # Get layer name from text_PathId
                name_field = mission_layer.find(".//field[@name='text_PathId']")
                if name_field is not None:
                    layer_name = name_field.get('value-String', f'Layer {i+1}')
                else:
                    layer_name = f'Layer {i+1}'
                
                # Count entities in this layer
                entity_count = len(mission_layer.findall("object[@name='Entity']"))
                
                display_name = f"{i+1}. {layer_name} ({entity_count} entities)"
                self.layer_combo.addItem(display_name, i)
                
                self.available_layers.append({
                    'index': i,
                    'name': layer_name,
                    'entity_count': entity_count
                })
                
                print(f"   {i+1}. {layer_name} ({entity_count} entities)")
            
            # Auto-select first layer
            if self.layer_combo.count() > 0:
                self.layer_combo.setCurrentIndex(0)
                self.update_layer_info(0)
        
        except Exception as e:
            print(f"❌ Error loading MissionLayers: {e}")
            self.layer_combo.addItem("❌ Error loading layers", None)
    
    def update_layer_info(self, layer_index):
        """Update the layer info label with guidance"""
        if layer_index < 0 or layer_index >= len(self.available_layers):
            self.layer_info_label.setText("")
            return
        
        layer = self.available_layers[layer_index]
        layer_name = layer['name'].lower()
        
        # Provide guidance based on layer name
        info_text = ""
        if layer_name == "main":
            info_text = "ℹ️ Main layer: Core level entities, always loaded"
        elif layer_name == "outside_entity":
            info_text = "ℹ️ Outside Entity layer: General gameplay objects"
        elif "mission" in layer_name or layer_name.startswith("m"):
            info_text = f"ℹ️ Mission layer: Entities for mission '{layer_name}' (CMissionComponent will be added)"
        else:
            info_text = f"ℹ️ Custom layer: '{layer_name}'"
        
        self.layer_info_label.setText(info_text)
        

    def remap_structure_child_ids(self, entity_xml, id_map=None):
        """
        Remap all child IDs in a Structure's Children block.

        When *id_map* is provided (the batch old→new mapping built by
        _build_cross_ref_id_map), uses the pre-allocated new ID for each child
        so that the parent's Children block stays in sync with the child
        entities' new disEntityId values.  Falls back to a fresh generated ID
        for any child not found in the map.

        Returns dict mapping old_id -> new_id.
        """
        child_id_map = {}

        children_obj = entity_xml.find(".//object[@name='Children']")
        if children_obj is None:
            return child_id_map

        child_objects = children_obj.findall("object[@name='Child']")
        print(f"   Found {len(child_objects)} children to remap")

        for i, child_obj in enumerate(child_objects):
            id_field = child_obj.find("field[@name='ID']")
            name_field = child_obj.find("field[@name='Name']")

            if id_field is None:
                continue

            old_child_id = id_field.get('value-Hash64')

            # Use the pre-allocated ID from the batch map when available
            if id_map and old_child_id and old_child_id in id_map:
                new_child_id = id_map[old_child_id]
            else:
                new_child_id = self.generate_unique_entity_id()

            id_field.set('value-Hash64', str(new_child_id))
            id_field.text = XMLHelper.int64_to_binhex(new_child_id)

            child_id_map[old_child_id] = new_child_id
            child_name = name_field.get('value-String') if name_field is not None else f"Child_{i+1}"
            print(f"      {child_name}: {old_child_id} → {new_child_id}")

        return child_id_map

    def remap_seated_npc_ids(self, entity_xml):
        """
        Remap all seated NPC IDs in a vehicle to new unique IDs.
        Returns dict mapping old_id -> new_id
        """
        seated_id_map = {}
        
        # Find CFCXAIComponent -> AIObject
        ai_component = entity_xml.find(".//object[@name='CFCXAIComponent']")
        if ai_component is None:
            return seated_id_map
        
        ai_object = ai_component.find(".//object[@name='AIObject']")
        if ai_object is None:
            return seated_id_map
        
        print(f"   Found AIObject, checking for seated NPC references...")
        
        # Find all fields that contain entity ID references
        remapped_count = 0
        for field in ai_object.findall("field"):
            entity_id_ref = field.get('value-Hash64')
            if entity_id_ref:
                # Generate new unique ID for this seated NPC
                new_seated_id = self.generate_unique_entity_id()
                
                # Update the field
                field.set('value-Hash64', str(new_seated_id))
                binary_hex = XMLHelper.int64_to_binhex(new_seated_id)
                field.text = binary_hex
                
                # Store mapping
                seated_id_map[entity_id_ref] = new_seated_id
                remapped_count += 1
                
                print(f"      🪑 Seated NPC: {entity_id_ref} → {new_seated_id}")
        
        print(f"   Remapped {remapped_count} seated NPC references")
        
        return seated_id_map

    def remap_seated_npc_ids_with_map(self, entity_xml, id_map):
        """
        Remap all seated NPC IDs in a vehicle using the pre-built cross-ref id_map.
        If the old ID is in the map, use the pre-allocated new ID (so it matches the
        NPC entity's new disEntityId). Falls back to a random new ID if not in map.
        Returns the count of remapped fields.
        """
        ai_component = entity_xml.find(".//object[@name='CFCXAIComponent']")
        if ai_component is None:
            return 0

        ai_object = ai_component.find(".//object[@name='AIObject']")
        if ai_object is None:
            return 0

        print(f"   Found AIObject, remapping seated NPC references...")
        remapped_count = 0
        for field in ai_object.findall("field"):
            entity_id_ref = field.get('value-Hash64')
            if entity_id_ref:
                if entity_id_ref in id_map:
                    new_seated_id = id_map[entity_id_ref]
                else:
                    new_seated_id = self.generate_unique_entity_id()
                field.set('value-Hash64', str(new_seated_id))
                binary_hex = XMLHelper.int64_to_binhex(new_seated_id)
                field.text = binary_hex
                remapped_count += 1
                print(f"      🪑 Seated NPC: {entity_id_ref} → {new_seated_id}")

        return remapped_count

    def remap_initial_user_ids(self, entity_xml, id_map):
        """
        Remap all entUser references in InitialUsers using the given old→new ID map.
        id_map: {old_id_str: new_id_int}
        Updates both value-Id64 attribute and BinHex text content.
        Returns the number of fields remapped.
        """
        import struct
        remapped_count = 0

        initial_users_obj = entity_xml.find(".//object[@name='InitialUsers']")
        if initial_users_obj is None:
            return remapped_count

        print(f"   Found InitialUsers, remapping entUser references...")
        for user_obj in initial_users_obj.findall("object"):
            user_field = user_obj.find("field[@name='entUser']")
            if user_field is not None:
                old_id = user_field.get('value-Id64')
                if old_id and old_id in id_map:
                    new_id = id_map[old_id]
                    user_field.set('value-Id64', str(new_id))
                    binary_hex = XMLHelper.int64_to_binhex(new_id)
                    user_field.text = binary_hex
                    remapped_count += 1
                    print(f"      👤 entUser: {old_id} → {new_id}")

        return remapped_count

    def import_single_entity_to_mapsdata(self, item, id_map=None, position_delta=None):
        """Import a single entity to mapsdata.xml (FCBConverter format)"""
        try:
            entity_data = item.data(0, Qt.ItemDataRole.UserRole)
            xml_path = entity_data['xml_path']

            print(f"\n📄 Importing {entity_data['name']} to mapsdata.xml")

            # Read exported XML — already in FCBConverter format, no conversion needed
            tree = ET.parse(xml_path)
            entity_xml = tree.getroot()

            import copy
            entity_xml = copy.deepcopy(entity_xml)

            # Use pre-allocated ID from id_map if available, otherwise generate a new one
            old_id = entity_data.get('id')
            if id_map and old_id and old_id in id_map:
                new_id = id_map[old_id]
            else:
                new_id = self.generate_unique_entity_id()
            XMLHelper.update_entity_id(entity_xml, new_id)

            # Remap cross-entity references using the id_map
            if id_map:
                seated_count = self.remap_seated_npc_ids_with_map(entity_xml, id_map)
                if seated_count:
                    print(f"   ✅ Remapped {seated_count} seated NPC ID(s)")
                user_count = self.remap_initial_user_ids(entity_xml, id_map)
                if user_count:
                    print(f"   ✅ Remapped {user_count} initial user ID(s)")

            # Find the container: the parent element of any existing FCBConverter Entity.
            # This mirrors how _remove_entity_from_main_xml locates the parent.
            root = self.parent_editor.xml_tree.getroot()
            entity_container = None
            for existing in root.findall(".//object[@name='Entity']"):
                for candidate in root.iter():
                    if existing in list(candidate):
                        entity_container = candidate
                        break
                if entity_container is not None:
                    break

            if entity_container is None:
                print("   ⚠️ No existing entities found — appending to root")
                entity_container = root
            else:
                print(f"   ✅ Found entity container: {entity_container.get('name', entity_container.tag)}")

            # Apply group-relative placement (orig + delta keeps children in formation)
            if position_delta is not None:
                orig_x, orig_y, orig_z = XMLHelper.extract_position_from_xml(entity_xml)
                new_x = orig_x + position_delta[0]
                new_y = orig_y + position_delta[1]
                new_z = orig_z + position_delta[2]
                XMLHelper.update_entity_position(entity_xml, new_x, new_y, new_z)
                print(f"   📍 Position: ({new_x:.2f}, {new_y:.2f}, {new_z:.2f})")

            # Create independent copy
            xml_string = ET.tostring(entity_xml, encoding='unicode')
            entity_copy = ET.fromstring(xml_string)
            
            # Append to entity container
            entity_container.append(entity_copy)
            print(f"   ✅ Added to mapsdata.xml entity container")
            
            # Save immediately
            try:
                ET.indent(self.parent_editor.xml_tree, space="  ")
            except AttributeError:
                pass
            
            xml_file_path = getattr(self.parent_editor, 'xml_file_path', None)
            if xml_file_path:
                self.parent_editor.xml_tree.write(xml_file_path, encoding='utf-8', xml_declaration=True)
                print(f"   💾 Saved mapsdata.xml")
            
            # Create Entity object
            entity_name = entity_data['name']
            x, y, z = XMLHelper.extract_position_from_xml(entity_xml)
            
            entity = Entity(
                id=str(new_id),
                name=entity_name,
                x=x, y=y, z=z,
                xml_element=entity_copy
            )
            
            entity.source_file = "mapsdata"
            entity.source_file_path = xml_file_path
            
            print(f"✅ Imported {entity_name} to mapsdata.xml")
            
            return True, entity
            
        except Exception as e:
            print(f"❌ Error importing to mapsdata: {e}")
            import traceback
            traceback.print_exc()
            return False, None
        
    def convert_fcb_to_mapsdata(self, fcb_xml):
        """Convert entity from WorldSector FCB format to mapsdata Dunia format"""
        print("   🔧 Converting FCB <field> format to mapsdata <value> format...")
        
        # Create new root in mapsdata format
        new_root = ET.Element("object", {"type": "Entity"})
        
        # 1. hidName (String)
        name_field = fcb_xml.find(".//field[@name='hidName']")
        if name_field is not None:
            name_value = ET.SubElement(new_root, "value", {"name": "hidName", "type": "String"})
            name_value.text = name_field.get('value-String', 'Unknown')
        
        # 2. disEntityId (UInt64)
        id_field = fcb_xml.find(".//field[@name='disEntityId']")
        if id_field is not None:
            id_value = ET.SubElement(new_root, "value", {"name": "disEntityId", "type": "UInt64"})
            id_value.text = id_field.get('value-Id64', '0')
        
        # 3. hidPos (Vector3)
        pos_field = fcb_xml.find(".//field[@name='hidPos']")
        if pos_field is not None:
            pos_vector = pos_field.get('value-Vector3', '0,0,0')
            x, y, z = pos_vector.split(',')
            
            pos_value = ET.SubElement(new_root, "value", {"name": "hidPos", "type": "Vector3"})
            ET.SubElement(pos_value, "x").text = x.strip()
            ET.SubElement(pos_value, "y").text = y.strip()
            ET.SubElement(pos_value, "z").text = z.strip()
        
        # 4. hidPos_precise (Vector3)
        pos_precise_field = fcb_xml.find(".//field[@name='hidPos_precise']")
        if pos_precise_field is not None:
            pos_vector = pos_precise_field.get('value-Vector3', '0,0,0')
            x, y, z = pos_vector.split(',')
            
            pos_precise_value = ET.SubElement(new_root, "value", {"name": "hidPos_precise", "type": "Vector3"})
            ET.SubElement(pos_precise_value, "x").text = x.strip()
            ET.SubElement(pos_precise_value, "y").text = y.strip()
            ET.SubElement(pos_precise_value, "z").text = z.strip()
        
        # 5. hidAngles (Vector3) - if it exists
        angles_field = fcb_xml.find(".//field[@name='hidAngles']")
        if angles_field is not None:
            angles_vector = angles_field.get('value-Vector3', '0,0,0')
            x, y, z = angles_vector.split(',')
            
            angles_value = ET.SubElement(new_root, "value", {"name": "hidAngles", "type": "Vector3"})
            ET.SubElement(angles_value, "x").text = x.strip()
            ET.SubElement(angles_value, "y").text = y.strip()
            ET.SubElement(angles_value, "z").text = z.strip()
        
        # 6. hidConstEntity (Bool)
        const_field = fcb_xml.find(".//field[@name='hidConstEntity']")
        if const_field is not None:
            const_value = ET.SubElement(new_root, "value", {"name": "hidConstEntity", "type": "Bool"})
            const_value.text = const_field.get('value-Bool', 'False')
        
        # 7. Components object - copy as-is (FCB and mapsdata both use <object>)
        components_obj = fcb_xml.find(".//object[@name='Components']")
        if components_obj is not None:
            # Deep copy components
            components_str = ET.tostring(components_obj, encoding='unicode')
            components_copy = ET.fromstring(components_str)
            new_root.append(components_copy)
        
        print("   ✅ Conversion complete")
        return new_root

    def _get_sector_id_from_path(self, sector_file_path):
        """Read GX/GY from WorldSector XML and return GY*16+GX. Returns -1 on failure."""
        try:
            tree = None
            if hasattr(self, 'parent_editor') and hasattr(self.parent_editor, 'worldsectors_trees'):
                tree = self.parent_editor.worldsectors_trees.get(sector_file_path)
            if tree is None:
                tree = ET.parse(sector_file_path)
            root = tree.getroot()
            gx_field = root.find(".//field[@name='X']")
            gy_field = root.find(".//field[@name='Y']")
            if gx_field is not None and gy_field is not None:
                gx = int(gx_field.get('value-Int32', -1))
                gy = int(gy_field.get('value-Int32', -1))
                if gx >= 0 and gy >= 0:
                    return gy * 16 + gx
        except Exception:
            pass
        return -1

    def _get_sector_center(self, sector_file_path):
        """Return (cx, cy, cz) world-center of the given sector file."""
        # Try canvas sector_data first (has x/y already computed)
        if hasattr(self, 'parent_editor') and hasattr(self.parent_editor, 'canvas'):
            for sd in getattr(self.parent_editor.canvas, 'sector_data', []):
                fp = sd.get('file_path', '')
                if fp and os.path.normcase(fp) == os.path.normcase(sector_file_path):
                    size = sd.get('size', 64)
                    # sd['x'] and sd['y'] are grid indices (0-15), not world coords
                    cx = sd['x'] * size + size / 2.0
                    cy = sd['y'] * size + size / 2.0
                    print(f"   📍 Sector center from sector_data: ({cx}, {cy})")
                    return cx, cy, 0.0
        # Fallback: parse grid coords from the XML
        try:
            sid = self._get_sector_id_from_path(sector_file_path)
            print(f"   📍 _get_sector_id_from_path returned: {sid}")
            if sid >= 0:
                gx = sid % 16
                gy = sid // 16
                cx, cy = gx * 64.0 + 32.0, gy * 64.0 + 32.0
                print(f"   📍 Sector center from XML (gx={gx},gy={gy}): ({cx}, {cy})")
                return cx, cy, 0.0
        except Exception as e:
            print(f"   ❌ _get_sector_center fallback failed: {e}")
        # Last resort: extract from filename
        try:
            import re
            m = re.search(r'worldsector(\d+)', os.path.basename(sector_file_path), re.IGNORECASE)
            if m:
                n = int(m.group(1))
                gx, gy = n % 16, n // 16
                cx, cy = gx * 64.0 + 32.0, gy * 64.0 + 32.0
                print(f"   📍 Sector center from filename (n={n},gx={gx},gy={gy}): ({cx}, {cy})")
                return cx, cy, 0.0
        except Exception:
            pass
        print(f"   ⚠️ Could not determine sector center for {sector_file_path}, using 0,0")
        return 0.0, 0.0, 0.0

    def import_single_entity(self, item, sector_file_path, target_layer_index=0, id_map=None, position_delta=None):
        """Import a single entity - WITH MISSIONLAYER SUPPORT AND CMissionComponent"""
        try:
            entity_data = item.data(0, Qt.ItemDataRole.UserRole)  # FIX: ADD COLUMN 0
            xml_path = entity_data['xml_path']

            # Read the exported XML file directly
            tree = ET.parse(xml_path)
            entity_xml = tree.getroot()

            # Make a deep copy to avoid modifying the original
            import copy
            entity_xml = copy.deepcopy(entity_xml)

            # Check if this is a Structure with children or Vehicle with seated NPCs / initial users
            entity_class_field = entity_xml.find(".//field[@name='text_hidEntityClass']")
            is_structure = False
            is_vehicle_seated = False
            is_vehicle_initial = False

            if entity_class_field is not None:
                entity_class = entity_class_field.get('value-String', '')
                if 'Prefab' in entity_class:
                    is_structure = True
                    print(f"\n🏗️ Importing Structure: {entity_data['name']}")

            ai_component = entity_xml.find(".//object[@name='CFCXAIComponent']")
            if ai_component is not None:
                ai_object = ai_component.find(".//object[@name='AIObject']")
                if ai_object is not None:
                    is_vehicle_seated = True

            if entity_xml.find(".//object[@name='InitialUsers']") is not None:
                is_vehicle_initial = True

            if is_vehicle_seated or is_vehicle_initial:
                print(f"\n🚗 Importing Vehicle: {entity_data['name']}")

            # Use pre-allocated ID from id_map if available, otherwise generate a new one
            old_id = entity_data.get('id')
            if id_map and old_id and old_id in id_map:
                new_id = id_map[old_id]
            else:
                new_id = self.generate_unique_entity_id()

            # Update the entity ID in the XML
            if not XMLHelper.update_entity_id(entity_xml, new_id):
                print("⚠️ Could not update entity ID")

            # Remap child IDs if this is a Structure — use batch id_map so the
            # parent's Children block points to the same new IDs as the child entities.
            if is_structure:
                child_id_map = self.remap_structure_child_ids(entity_xml, id_map=id_map)
                if child_id_map:
                    print(f"   ✅ Remapped {len(child_id_map)} child IDs")

            # Remap seated NPC IDs using the cross-ref id_map for correct sync
            if is_vehicle_seated:
                seated_count = self.remap_seated_npc_ids_with_map(entity_xml, id_map or {})
                if seated_count:
                    print(f"   ✅ Remapped {seated_count} seated NPC IDs")

            # Remap initial user (pilot/driver) IDs using the cross-ref id_map
            if is_vehicle_initial:
                user_count = self.remap_initial_user_ids(entity_xml, id_map or {})
                if user_count:
                    print(f"   ✅ Remapped {user_count} initial user ID(s)")
            
            orig_x, orig_y, orig_z = XMLHelper.extract_position_from_xml(entity_xml)
            if position_delta is not None:
                new_x = orig_x + position_delta[0]
                new_y = orig_y + position_delta[1]
                new_z = orig_z + position_delta[2]
            else:
                new_x, new_y, new_z = self._get_sector_center(sector_file_path)
            result = XMLHelper.update_entity_position(entity_xml, new_x, new_y, new_z)
            print(f"   📍 Position: ({new_x:.2f}, {new_y:.2f}, {new_z:.2f}), update_result={result}")

            # Add to sector with layer index
            success = self.add_entity_to_sector_with_layer(
                entity_xml, 
                sector_file_path, 
                target_layer_index,
                entity_data['name']
            )
            
            if not success:
                return False, None
            
            # Create Entity object for the editor
            entity_name = entity_data['name']
            x, y, z = XMLHelper.extract_position_from_xml(entity_xml)
            
            entity = Entity(
                id=str(new_id),
                name=entity_name,
                x=x, y=y, z=z,
                xml_element=entity_xml
            )
            
            entity.source_file = "worldsectors"
            entity.source_file_path = sector_file_path
            entity.source_sector_id = self._get_sector_id_from_path(sector_file_path)
            if hasattr(self, 'available_layers') and 0 <= target_layer_index < len(self.available_layers):
                entity.source_layer = self.available_layers[target_layer_index]['name']
            else:
                entity.source_layer = 'main'

            if is_structure:
                print(f"   ✅ Structure imported with remapped child IDs")
            if is_vehicle_seated:
                print(f"   ✅ Vehicle imported with remapped seated NPC IDs")
            if is_vehicle_initial:
                print(f"   ✅ Vehicle imported with remapped initial user IDs")
            if not is_structure and not is_vehicle_seated and not is_vehicle_initial:
                print(f"   ✅ Entity imported: {entity_name}")
            
            return True, entity
            
        except Exception as e:
            print(f"❌ Error importing entity: {e}")
            import traceback
            traceback.print_exc()
        return False, None
    
    @staticmethod
    def _create_main_mission_layer(root):
        """Append a 'main' MissionLayer to a WorldSector root element and return it."""
        ml = ET.SubElement(root, 'object')
        ml.set('hash', '494C09F2')
        ml.set('name', 'MissionLayer')
        tp = ET.SubElement(ml, 'field')
        tp.set('hash', 'C56F9204')
        tp.set('name', 'text_PathId')
        tp.set('value-String', 'main')
        tp.set('type', 'BinHex')
        tp.text = '6D61696E00'
        pid = ET.SubElement(ml, 'field')
        pid.set('hash', 'D0E30BF7')
        pid.set('name', 'PathId')
        pid.set('value-ComputeHash32', 'main')
        pid.set('type', 'BinHex')
        pid.text = '64CD28BF'
        return ml

    def add_entity_to_sector_with_layer(self, entity_xml, sector_file_path, target_layer_index, entity_name):
        """
        Add entity XML to specific MissionLayer in WorldSector file.
        Uses the same logic as your sector move function.
        """
        try:
            print(f"\n➕ Adding {entity_name} to {os.path.basename(sector_file_path)} (Layer {target_layer_index + 1})")
            
            # Auto-load target file if not already loaded
            if not hasattr(self.parent_editor, 'worldsectors_trees'):
                self.parent_editor.worldsectors_trees = {}
            
            if sector_file_path not in self.parent_editor.worldsectors_trees:
                if os.path.exists(sector_file_path):
                    tree = ET.parse(sector_file_path)
                    self.parent_editor.worldsectors_trees[sector_file_path] = tree
                    print(f"📂 Auto-loaded target file")
                else:
                    print(f"❌ Target file does not exist")
                    return False
            
            tree = self.parent_editor.worldsectors_trees[sector_file_path]
            root = tree.getroot()
            
            # Find ALL MissionLayers — create a 'main' one if none exist
            mission_layers = root.findall(".//object[@name='MissionLayer']")
            if not mission_layers:
                print(f"⚠️ No MissionLayer found — creating 'main' layer")
                self._create_main_mission_layer(root)
                mission_layers = root.findall(".//object[@name='MissionLayer']")

            # Validate layer index
            if target_layer_index < 0 or target_layer_index >= len(mission_layers):
                print(f"⚠️ Invalid layer index, using layer 0")
                target_layer_index = 0

            mission_layer = mission_layers[target_layer_index]
            
            # Get mission layer name
            mission_layer_name = None
            name_field = mission_layer.find(".//field[@name='text_PathId']")
            if name_field is not None:
                mission_layer_name = name_field.get('value-String', '').lower()
            
            print(f"🎯 Using MissionLayer {target_layer_index + 1}: '{mission_layer_name}'")
            
            # Count existing entities
            existing_count = len(mission_layer.findall("object[@name='Entity']"))
            print(f"📊 Layer has {existing_count} existing entities")
            
            # 🆕 ADD CMissionComponent if not main/outside_entity (COPY FROM YOUR SECTOR MOVE CODE)
            skip_layers = ['main', 'outside_entity']
            if mission_layer_name and mission_layer_name not in skip_layers:
                self.add_mission_component(entity_xml, mission_layer_name)
            
            # Create independent copy
            xml_string = ET.tostring(entity_xml, encoding='unicode')
            entity_copy = ET.fromstring(xml_string)
            
            # Append to MissionLayer
            mission_layer.append(entity_copy)
            
            # Verify
            new_count = len(mission_layer.findall("object[@name='Entity']"))
            if new_count <= existing_count:
                print(f"❌ Entity addition verification failed")
                return False
            
            print(f"✅ Added {entity_name} (now {new_count} entities in layer)")
            
            # Format and save
            try:
                ET.indent(tree, space="  ")
            except AttributeError:
                pass  # Python < 3.9
            
            tree.write(sector_file_path, encoding='utf-8', xml_declaration=True)
            print(f"💾 Saved {os.path.basename(sector_file_path)}")
            
            # Mark as modified
            if not hasattr(self.parent_editor, 'worldsectors_modified'):
                self.parent_editor.worldsectors_modified = {}
            self.parent_editor.worldsectors_modified[sector_file_path] = True
            
            return True
            
        except Exception as e:
            print(f"❌ Error adding entity: {e}")
            import traceback
            traceback.print_exc()
            return False

    def add_mission_component(self, entity_xml, mission_layer_name):
        """Add CMissionComponent to entity (COPIED FROM YOUR SECTOR MOVE CODE)"""
        print(f"🔧 Adding CMissionComponent for mission layer: {mission_layer_name}")
        
        # Find or create Components object
        components = entity_xml.find(".//object[@name='Components']")
        if components is None:
            print(f"   Creating new Components object")
            components = ET.SubElement(entity_xml, 'object', {
                'hash': 'A115F62D',
                'name': 'Components'
            })
        
        # Check if CMissionComponent already exists
        existing_mission_comp = components.find(".//object[@name='CMissionComponent']")
        if existing_mission_comp is not None:
            print(f"   Removing existing CMissionComponent")
            components.remove(existing_mission_comp)
        
        # Create CMissionComponent
        mission_comp = ET.SubElement(components, 'object', {
            'hash': 'D18498C8',
            'name': 'CMissionComponent'
        })
        
        # Convert mission layer name to BinHex
        mission_layer_binhex = mission_layer_name.encode('utf-8').hex().upper() + '00'
        
        # Add fields (EXACT COPY FROM YOUR CODE)
        ET.SubElement(mission_comp, 'field', {
            'hash': '7AF1FD74',
            'name': 'text_hidMissionLayerPath',
            'value-String': mission_layer_name,
            'type': 'BinHex'
        }).text = mission_layer_binhex
        
        # Calculate hash
        import struct
        mission_hash = sum(ord(c) for c in mission_layer_name) % (2**32)
        mission_hash_hex = struct.pack('<I', mission_hash).hex().upper()
        
        ET.SubElement(mission_comp, 'field', {
            'hash': '90AF9D50',
            'name': 'hidMissionLayerPath',
            'value-ComputeHash32': mission_layer_name,
            'type': 'BinHex'
        }).text = mission_hash_hex
        
        ET.SubElement(mission_comp, 'field', {
            'hash': '27B31D2E',
            'name': 'text_hidCategory',
            'value-String': '',
            'type': 'BinHex'
        }).text = '00'
        
        ET.SubElement(mission_comp, 'field', {
            'hash': '37F59D7D',
            'name': 'hidCategory',
            'type': 'BinHex'
        }).text = 'FFFFFFFF'
        
        ET.SubElement(mission_comp, 'field', {
            'hash': '136C40D8',
            'name': 'ForceMerge',
            'type': 'BinHex'
        }).text = '01'
        
        print(f"   ✅ CMissionComponent added")

    def generate_unique_entity_id(self):
        """Generate a unique entity ID"""
        # Try to use parent editor's method if available
        if hasattr(self.parent_editor, 'generate_new_entity_id'):
            return self.parent_editor.generate_new_entity_id()
        
        # Fallback: generate based on existing entities
        existing_ids = set()
        if hasattr(self.parent_editor, 'entities'):
            for entity in self.parent_editor.entities:
                try:
                    existing_ids.add(int(entity.id))
                except:
                    pass
        
        # Start from a high number to avoid conflicts
        new_id = 900000
        while new_id in existing_ids:
            new_id += 1
        
        return new_id

    def add_entity_xml_to_sector(self, entity_xml, sector_file_path):
        """Add entity XML to MissionLayer - prefers 'outside_entity', falls back to 'main'"""
        try:
            # Load the target file if not already loaded
            if not hasattr(self.parent_editor, 'worldsectors_trees'):
                self.parent_editor.worldsectors_trees = {}
            
            if sector_file_path not in self.parent_editor.worldsectors_trees:
                if os.path.exists(sector_file_path):
                    tree = ET.parse(sector_file_path)
                    self.parent_editor.worldsectors_trees[sector_file_path] = tree
                else:
                    print(f"Sector file does not exist: {sector_file_path}")
                    return False
            
            tree = self.parent_editor.worldsectors_trees[sector_file_path]
            root = tree.getroot()
            
            # Find ALL MissionLayers
            mission_layers = root.findall(".//object[@name='MissionLayer']")
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

                if target_mission_layer is not None:
                    break

            if target_mission_layer is None:
                print(f"⚠️ No 'outside_entity' or 'main' MissionLayer found — creating 'main' layer")
                target_mission_layer = self._create_main_mission_layer(root)
                target_path_id = "main"
            
            # Count existing entities BEFORE adding
            existing_entities = target_mission_layer.findall("object[@name='Entity']")
            print(f"MissionLayer '{target_path_id}' currently has {len(existing_entities)} entities")
            
            # CRITICAL FIX: Create truly independent copy by converting to string and parsing back
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
                # Fallback for older Python versions - manual indentation
                self._indent_xml_tree(root)
            
            # Save the file immediately
            print(f"💾 Writing to file: {sector_file_path}")
            tree.write(sector_file_path, encoding='utf-8', xml_declaration=True)
            print(f"💾 Saved {os.path.basename(sector_file_path)}")
            
            # Mark as modified
            if not hasattr(self.parent_editor, 'worldsectors_modified'):
                self.parent_editor.worldsectors_modified = {}
            self.parent_editor.worldsectors_modified[sector_file_path] = True
            
            return True
            
        except Exception as e:
            print(f"❌ Error adding entity to sector: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _indent_xml_tree(self, elem, level=0):
        """Fallback XML indentation for Python < 3.9"""
        i = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + "  "
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
            for child in elem:
                self._indent_xml_tree(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

    def load_collections(self):
        """Load available entity collections from objects/ (flat) and mass_exported_objects/ (recursive)."""
        self.collections_list.clear()
        collections_found = 0

        def _add_collection(item_path, display_prefix=""):
            nonlocal collections_found
            metadata_path = os.path.join(item_path, "collection_info.json")
            xml_files = [f for f in os.listdir(item_path) if f.endswith('.xml')]
            if not (os.path.exists(metadata_path) or xml_files):
                return
            collections_found += 1
            folder_name = os.path.basename(item_path)
            label = f"{display_prefix}{folder_name}" if display_prefix else folder_name
            if os.path.exists(metadata_path):
                try:
                    with open(metadata_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    total = meta.get('total_entities_with_children', meta.get('entity_count', len(xml_files)))
                    item_text = f"{label}  [{total} file(s)]  {meta.get('export_date', '')}"
                except Exception:
                    item_text = f"{label}  [{len(xml_files)} file(s)]"
            else:
                item_text = f"{label}  [{len(xml_files)} file(s)]"
            list_item = QListWidgetItem(item_text)
            list_item.setData(Qt.ItemDataRole.UserRole, item_path)
            self.collections_list.addItem(list_item)

        # ── objects/ — flat, one level deep (existing behaviour) ──────────
        if os.path.exists(self.objects_folder):
            for item in sorted(os.listdir(self.objects_folder)):
                item_path = os.path.join(self.objects_folder, item)
                if os.path.isdir(item_path):
                    _add_collection(item_path)

        # ── mass_exported_objects/ — recursive walk ────────────────────────
        if os.path.exists(self.mass_export_folder):
            for root, dirs, files in os.walk(self.mass_export_folder):
                dirs.sort()
                if 'collection_info.json' in files or any(f.endswith('.xml') for f in files):
                    rel = os.path.relpath(root, self.mass_export_folder)
                    parts = rel.replace('\\', '/').split('/')
                    # Show level/category/ as prefix so the type name stays readable
                    prefix = '/'.join(parts[:-1]) + '/' if len(parts) > 1 else ''
                    _add_collection(root, display_prefix=prefix)

        if collections_found == 0:
            self.status_label.setText("No entity collections found. Export some entities first.")
        else:
            self.status_label.setText(f"Found {collections_found} collection(s).")
        
    def browse_for_collection(self):
        """Browse for a collection folder"""
        start_dir = (self.mass_export_folder if os.path.exists(self.mass_export_folder)
                     else self.objects_folder if os.path.exists(self.objects_folder)
                     else "")
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select Entity Collection Folder",
            start_dir
        )
        
        if folder_path:
            # Check if it's a valid collection
            xml_files = [f for f in os.listdir(folder_path) if f.endswith('.xml')]
            if xml_files:
                self.load_collection_from_path(folder_path)
            else:
                QMessageBox.warning(self, "Invalid Collection", 
                                  "The selected folder does not contain any XML entity files.")
    
    def on_collection_selected(self, current, previous):
        """Handle collection selection"""
        if current:
            collection_path = current.data(Qt.ItemDataRole.UserRole)
            self.load_collection_from_path(collection_path)
    
    def load_collection_from_path(self, collection_path):
        """Load collection details from the given path"""
        self.selected_collection = collection_path
        self.entities_to_import = []
        
        # Load metadata if available
        metadata_path = os.path.join(collection_path, "collection_info.json")
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    self.collection_metadata = json.load(f)
            except:
                self.collection_metadata = None
        else:
            self.collection_metadata = None
        
        # Update collection info
        collection_name = os.path.basename(collection_path)
        info_text = f"Collection: {collection_name}\n"
        
        if self.collection_metadata:
            info_text += f"Exported: {self.collection_metadata.get('export_date', 'Unknown')}\n"
            info_text += f"Entity Count: {self.collection_metadata.get('entity_count', 'Unknown')}\n"
        
        self.collection_info_label.setText(info_text)
        
        # Load entities list
        self.load_entities_from_collection(collection_path)
        
        # Enable import button
        self.import_button.setEnabled(True)
    


def show_entity_export_dialog(editor):
    """Show the entity export dialog"""
    # Check if entities are selected
    selected_entities = []
    
    if hasattr(editor, 'canvas') and hasattr(editor.canvas, 'selected'):
        selected_entities = editor.canvas.selected
    elif hasattr(editor, 'selected_entity') and editor.selected_entity:
        selected_entities = [editor.selected_entity]
    
    if not selected_entities:
        QMessageBox.warning(
            editor,
            "No Selection",
            "Please select one or more entities to export.\n\n"
            "Click on entities in the canvas or use the entity browser to select them."
        )
        return
    
    # Show export dialog
    dialog = EntityExportDialog(editor, selected_entities)
    dialog.exec()


def show_entity_import_dialog(editor):
    """Show the entity import dialog"""
    # Enhanced worldsector detection
    worldsectors_available = False
    
    # Check multiple sources for worldsectors
    if hasattr(editor, 'worldsectors_trees') and editor.worldsectors_trees:
        worldsectors_available = True
        print(f"Found {len(editor.worldsectors_trees)} loaded worldsector trees")
    
    if not worldsectors_available and hasattr(editor, 'entities'):
        # Check if any entities have worldsector source files
        for entity in editor.entities:
            source_file = getattr(entity, 'source_file_path', None)
            if source_file and 'worldsector' in source_file and os.path.exists(source_file):
                worldsectors_available = True
                print(f"Found worldsector from entity: {source_file}")
                break
    
    if not worldsectors_available and hasattr(editor, 'worldsectors_path'):
        # Check if worldsectors_path exists and has .converted.xml files
        if editor.worldsectors_path and os.path.exists(editor.worldsectors_path):
            for file in os.listdir(editor.worldsectors_path):
                if file.endswith('.converted.xml') and 'worldsector' in file:
                    worldsectors_available = True
                    print(f"Found worldsector file: {file}")
                    break
    
    if not worldsectors_available:
        reply = QMessageBox.question(
            editor,
            "No Worldsectors Available",
            "No worldsector files are currently available for import.\n\n"
            "Entities need to be imported into worldsectors. Would you like to load worldsectors first?\n\n"
            "Available options:\n"
            "• Load Level Objects (recommended)\n"
            "• Load individual worldsector files",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Trigger load worldsectors
            if hasattr(editor, 'load_level_objects'):
                editor.load_level_objects()
                return
        else:
            return
    
    # Show import dialog
    dialog = EntityImportDialog(editor)
    dialog.exec()

def setup_entity_export_import_system(editor):
    """Setup the complete entity export/import system"""
    
    # Ensure objects folder exists
    objects_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "objects")
    if not os.path.exists(objects_folder):
        os.makedirs(objects_folder)
        print(f"Created objects folder: {objects_folder}")
    
    # Add generate_new_entity_id method to editor if it doesn't exist
    if not hasattr(editor, 'generate_new_entity_id'):
        def generate_new_entity_id(self):
            """Generate a new unique entity ID"""
            existing_ids = set()
            for entity in self.entities:
                try:
                    existing_ids.add(int(entity.id))
                except:
                    pass
            
            # Start from a high number to avoid conflicts
            new_id = 900000
            while new_id in existing_ids:
                new_id += 1
            
            return new_id
        
        # Bind the method to the editor instance
        import types
        editor.generate_new_entity_id = types.MethodType(generate_new_entity_id, editor)
            
    print("✅ Entity Export/Import system setup complete")


# Utility function to validate exported entities
def validate_exported_entity(xml_path):
    """Validate an exported entity XML file"""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # Check basic structure
        if root.tag != "object":
            return False, "Root element is not 'object'"
        
        # Check for essential fields
        essential_fields = ['hidName', 'disEntityId', 'hidPos']
        for field_name in essential_fields:
            # Check both formats
            fcb_field = root.find(f".//field[@name='{field_name}']")
            dunia_field = root.find(f".//value[@name='{field_name}']")
            
            if fcb_field is None and dunia_field is None:
                return False, f"Missing essential field: {field_name}"
        
        return True, "Valid entity XML"
        
    except Exception as e:
        return False, f"Parse error: {str(e)}"


# Utility function to batch export entities
def batch_export_entities(editor, entity_list, collection_name, output_folder=None):
    """Batch export multiple entities programmatically"""
    try:
        if output_folder is None:
            output_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "objects")
        
        collection_folder = os.path.join(output_folder, collection_name)
        if not os.path.exists(collection_folder):
            os.makedirs(collection_folder)
        
        exported_count = 0
        for i, entity in enumerate(entity_list):
            # Create filename
            safe_name = entity.name.replace('/', '_').replace('\\', '_')
            xml_filename = f"{safe_name}_{i+1:03d}.xml"
            xml_path = os.path.join(collection_folder, xml_filename)
            
            # Export entity
            if hasattr(entity, 'xml_element') and entity.xml_element is not None:
                import copy
                xml_copy = copy.deepcopy(entity.xml_element)
                
                # Update position
                XMLHelper.update_entity_position(xml_copy, entity.x, entity.y, entity.z)
                
                # Write to file
                tree = ET.ElementTree(xml_copy)
                tree.write(xml_path, encoding='utf-8', xml_declaration=True)
                
                exported_count += 1
        
        print(f"✓ Batch exported {exported_count} entities to {collection_folder}")
        return True, exported_count

    except Exception as e:
        print(f"✗ Batch export failed: {e}")
        return False, 0


# ============================================================================
# MASS EXPORT
# ============================================================================

def _mass_export_safe_name(name):
    """Sanitise a string for use as a file or folder name."""
    invalid = '<>:"/\\|?*'
    safe = name
    for ch in invalid:
        safe = safe.replace(ch, '_')
    while '__' in safe:
        safe = safe.replace('__', '_')
    return safe.strip('_') or 'misc'


def _get_mass_export_category(entity):
    """Return the top-level category folder name for an entity.

    Priority: first dot-segment of tplCreatureType, then first dot-segment of
    hidName, then the stripped hidName (no trailing _N), then 'misc'.
    """
    import re
    if hasattr(entity, 'xml_element') and entity.xml_element is not None:
        tpl_field = entity.xml_element.find("field[@name='tplCreatureType']")
        if tpl_field is not None:
            tpl = tpl_field.get('value-String', '').strip()
            if tpl:
                return tpl.split('.')[0]
    name = entity.name or ''
    if '.' in name:
        return name.split('.')[0]
    stripped = re.sub(r'_\d+$', '', name).strip()
    return stripped if stripped else 'misc'


def _write_mass_export_xml(element, xml_path):
    """Write an XML element to disk with 2-space indentation, no declaration."""
    import xml.dom.minidom
    try:
        rough = ET.tostring(element, encoding='unicode')
        dom = xml.dom.minidom.parseString(rough)
        pretty = dom.documentElement.toprettyxml(indent="  ")
        lines = pretty.split('\n')
        if lines[0].startswith('<?xml'):
            lines = lines[1:]
        clean = [l for l in lines if l.strip()]
        with open(xml_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(clean))
    except Exception:
        ET.ElementTree(element).write(xml_path, encoding='utf-8', xml_declaration=False)


def mass_export_level(editor, output_root, progress_callback=None):
    """Export one XML collection per unique entity type from the loaded level.

    Entities are organised into output_root/<category>/<type_name>/.
    Types are deduplicated by stripping the trailing _N instance number from
    hidName.  Children, seated NPCs, and initial users are bundled with their
    parent and not exported as separate top-level collections.

    progress_callback(current, total) → return False to cancel.

    Returns (num_categories, num_types, num_entity_files).
    """
    import re, copy, time

    entities = getattr(editor, 'entities', [])
    if not entities:
        return 0, 0, 0

    entities_dict = {e.id: e for e in entities}

    # ── First pass: collect all secondary IDs ──────────────────────────────
    all_secondary_ids = set()
    for entity in entities:
        if not hasattr(entity, 'xml_element') or entity.xml_element is None:
            continue
        related = EntityRelationshipDetector.find_all_related_entities(entity, entities_dict)
        for grp in (related['children'], related['seated'], related['initial_users']):
            for e in grp:
                all_secondary_ids.add(e.id)

    # ── Second pass: export one collection per type ────────────────────────
    seen_type_keys = set()
    seen_entity_ids = set()
    exported_categories = set()
    total_types = 0
    total_files = 0
    total = len(entities)

    for i, entity in enumerate(entities):
        if progress_callback:
            if not progress_callback(i, total):
                break

        if entity.id in all_secondary_ids or entity.id in seen_entity_ids:
            continue

        type_key = re.sub(r'_\d+$', '', entity.name).strip() or entity.name or 'unknown'
        if type_key in seen_type_keys:
            continue
        seen_type_keys.add(type_key)

        category = _get_mass_export_category(entity)
        group = EntityRelationshipDetector.collect_all_related_recursive(entity, entities_dict)
        for e in group:
            seen_entity_ids.add(e.id)

        folder = os.path.join(output_root, _mass_export_safe_name(category), _mass_export_safe_name(type_key))
        os.makedirs(folder, exist_ok=True)

        # Build relationship maps for metadata
        related = EntityRelationshipDetector.find_all_related_entities(entity, entities_dict)
        child_ids   = [e.id for e in related['children']]
        seated_ids  = [e.id for e in related['seated']]
        user_ids    = [e.id for e in related['initial_users']]

        exported_files = []
        metadata_entities = []
        counter = 1

        for ent in group:
            if not hasattr(ent, 'xml_element') or ent.xml_element is None:
                continue
            safe_name = _mass_export_safe_name(ent.name)
            filename = f"{safe_name}_{counter:03d}.xml"
            _write_mass_export_xml(copy.deepcopy(ent.xml_element), os.path.join(folder, filename))
            exported_files.append(filename)
            metadata_entities.append({
                'name': ent.name,
                'id': ent.id,
                'filename': filename,
                'original_position': {'x': ent.x, 'y': ent.y, 'z': ent.z},
                'is_primary': ent.id == entity.id,
                'is_child': ent.id in child_ids,
                'is_seated': ent.id in seated_ids,
                'is_initial_user': ent.id in user_ids,
                'source_file': getattr(ent, 'source_file', None),
                'source_layer': getattr(ent, 'source_layer', 'main'),
            })
            counter += 1

        metadata = {
            'collection_name': _mass_export_safe_name(type_key),
            'export_date': time.strftime('%Y-%m-%d %H:%M:%S'),
            'entity_count': 1,
            'total_entities_with_children': len(group),
            'original_selection_count': 1,
            'preserve_positions': True,
            'include_metadata': True,
            'has_structures': bool(child_ids),
            'structure_count': 1 if child_ids else 0,
            'structure_child_map': {entity.id: child_ids} if child_ids else {},
            'has_vehicles': bool(seated_ids),
            'vehicle_count': 1 if seated_ids else 0,
            'seated_npc_map': {entity.id: seated_ids} if seated_ids else {},
            'has_initial_users': bool(user_ids),
            'initial_user_vehicle_count': 1 if user_ids else 0,
            'initial_user_map': {entity.id: user_ids} if user_ids else {},
            'entities': metadata_entities,
        }
        with open(os.path.join(folder, 'collection_info.json'), 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        exported_categories.add(_mass_export_safe_name(category))
        total_types += 1
        total_files += len(exported_files)

    return len(exported_categories), total_types, total_files