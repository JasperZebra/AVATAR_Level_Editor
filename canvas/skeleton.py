#!/usr/bin/env python3
"""
Skeleton and bone data structures
"""

from typing import List, Optional
from math_utils import Quaternion, Matrix4x4, quaternion_from_xbg_data, create_translation_matrix


class Bone:
    """Bone data structure"""
    def __init__(self):
        self.name: Optional[str] = None
        self.parent_id: Optional[int] = None
        
        # Raw data from file
        self.local_rotation_quat: Optional[Quaternion] = None
        self.local_position: List[float] = [0, 0, 0]
        
        # Computed matrices
        self.rot_matrix: Optional[Matrix4x4] = None
        self.pos_matrix: Optional[Matrix4x4] = None
        self.local_matrix: Optional[Matrix4x4] = None
        self.world_matrix: Optional[Matrix4x4] = None
        
        # Final transform for export
        self.translation: List[float] = [0, 0, 0]
        self.rotation: List[float] = [0, 0, 0, 1]
        self.scale: List[float] = [1, 1, 1]


class Skeleton:
    """Skeleton data structure"""
    def __init__(self):
        self.bones: List[Bone] = []
        
    def add_bone(self, bone: Bone):
        self.bones.append(bone)
        
    def get_bone_count(self) -> int:
        return len(self.bones)
        
    def get_bone(self, index: int) -> Optional[Bone]:
        if 0 <= index < len(self.bones):
            return self.bones[index]
        return None
    
    def compute_bone_transforms(self):
        """
        Compute world-space transforms for all bones.
        """
        print("\nComputing bone transforms...")
        
        for i, bone in enumerate(self.bones):
            if bone.local_rotation_quat is None:
                continue
            
            # Create rotation matrix from quaternion
            bone.rot_matrix = bone.local_rotation_quat.to_matrix4x4()
            
            # Create translation matrix
            bone.pos_matrix = create_translation_matrix(bone.local_position)
            
            # Combine into local matrix
            # CORRECT ORDER: Translation * Rotation
            # This ensures the translation is applied relative to the parent, 
            # and the rotation is applied locally to the bone.
            bone.local_matrix = bone.pos_matrix.multiply(bone.rot_matrix)
            
            # Calculate World Matrix
            if bone.parent_id is not None and bone.parent_id >= 0 and bone.parent_id < len(self.bones):
                parent = self.bones[bone.parent_id]
                if parent.world_matrix is not None:
                    bone.world_matrix = parent.world_matrix.multiply(bone.local_matrix)
                else:
                    bone.world_matrix = bone.local_matrix
            else:
                # Root bone
                bone.world_matrix = bone.local_matrix
                
            # Extract components for debug
            bone.translation = bone.world_matrix.get_translation()


def parse_skeleton_chunk(g, skeleton: Skeleton):
    """Parse EDON chunk - skeleton data"""
    w = g.i(3)
    bone_count = w[2]
    
    print(f"\nParsing skeleton with {bone_count} bones...")
    
    for m in range(bone_count):
        bone = Bone()
        g.b(4)
        w = g.i(3)
        
        # Read quaternion rotation (stored as x,y,z,w)
        quat_data = g.f(4)
        bone.local_rotation_quat = quaternion_from_xbg_data(quat_data)
        
        # Read position
        pos_data = g.f(3)
        bone.local_position = list(pos_data)
        
        g.f(3)  # skip
        g.i(1)[0]  # skip
        g.f(1)[0]  # skip
        g.i(1)[0]  # skip
        
        # Read bone name
        name_len = g.i(1)[0]
        bone.name = g.word(name_len)[-25:] 
        bone.parent_id = w[2]
        g.b(1)
        
        skeleton.add_bone(bone)
    
    # Compute transforms immediately
    skeleton.compute_bone_transforms()