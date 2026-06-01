#!/usr/bin/env python3
"""
Math utilities for 3D transformations
"""

from typing import List, Tuple
import math

class Vector:
    """Simple 3D vector class"""
    def __init__(self, x=0, y=0, z=0):
        if isinstance(x, (list, tuple)) and len(x) >= 3:
            self.x, self.y, self.z = x[0], x[1], x[2]
        else:
            self.x, self.y, self.z = x, y, z
    
    def __mul__(self, scalar: float) -> 'Vector':
        return Vector(self.x * scalar, self.y * scalar, self.z * scalar)
    
    def __add__(self, other: 'Vector') -> 'Vector':
        return Vector(self.x + other.x, self.y + other.y, self.z + other.z)
    
    def to_list(self) -> List[float]:
        return [self.x, self.y, self.z]

class Matrix4x4:
    """4x4 transformation matrix (Row-Major storage for Python, GLTF export helper)"""
    def __init__(self, data: List[float] = None):
        if data is None:
            self.matrix = [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0]
            ]
        else:
            self.matrix = [
                list(data[0:4]),
                list(data[4:8]), 
                list(data[8:12]),
                list(data[12:16])
            ]
    
    def multiply(self, other: 'Matrix4x4') -> 'Matrix4x4':
        """Standard Matrix Multiplication"""
        result = Matrix4x4()
        m1 = self.matrix
        m2 = other.matrix
        for i in range(4):
            for j in range(4):
                result.matrix[i][j] = (
                    m1[i][0] * m2[0][j] +
                    m1[i][1] * m2[1][j] +
                    m1[i][2] * m2[2][j] +
                    m1[i][3] * m2[3][j]
                )
        return result
    
    def transform_point(self, point: List[float]) -> List[float]:
        x, y, z = point
        m = self.matrix
        return [
            m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
            m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
            m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3]
        ]
    
    def to_gl_list(self) -> List[float]:
        """Convert to Column-Major list for GLTF"""
        m = self.matrix
        return [
            m[0][0], m[1][0], m[2][0], m[3][0],
            m[0][1], m[1][1], m[2][1], m[3][1],
            m[0][2], m[1][2], m[2][2], m[3][2],
            m[0][3], m[1][3], m[2][3], m[3][3]
        ]

    def invert(self) -> 'Matrix4x4':
        """Invert matrix using Gaussian elimination"""
        m = [row[:] for row in self.matrix]
        identity = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
        
        for i in range(4):
            pivot = m[i][i]
            if abs(pivot) < 1e-6:
                # Swap rows
                for k in range(i + 1, 4):
                    if abs(m[k][i]) > 1e-6:
                        m[i], m[k] = m[k], m[i]
                        identity[i], identity[k] = identity[k], identity[i]
                        pivot = m[i][i]
                        break
                else:
                    return Matrix4x4() # Return Identity if singular
            
            inv_pivot = 1.0 / pivot
            for j in range(4):
                m[i][j] *= inv_pivot
                identity[i][j] *= inv_pivot
            
            for k in range(4):
                if k != i:
                    factor = m[k][i]
                    for j in range(4):
                        m[k][j] -= factor * m[i][j]
                        identity[k][j] -= factor * identity[i][j]
                        
        res = Matrix4x4()
        res.matrix = identity
        return res

    def get_translation(self) -> List[float]:
        return [self.matrix[0][3], self.matrix[1][3], self.matrix[2][3]]
    
    def get_scale(self) -> List[float]:
        sx = math.sqrt(self.matrix[0][0]**2 + self.matrix[1][0]**2 + self.matrix[2][0]**2)
        sy = math.sqrt(self.matrix[0][1]**2 + self.matrix[1][1]**2 + self.matrix[2][1]**2)
        sz = math.sqrt(self.matrix[0][2]**2 + self.matrix[1][2]**2 + self.matrix[2][2]**2)
        return [sx, sy, sz]
        
    def get_rotation_quat(self) -> List[float]:
        m = self.matrix
        sx, sy, sz = self.get_scale()
        
        if sx < 1e-5 or sy < 1e-5 or sz < 1e-5:
             return [0.0, 0.0, 0.0, 1.0]

        m00, m01, m02 = m[0][0]/sx, m[0][1]/sy, m[0][2]/sz
        m10, m11, m12 = m[1][0]/sx, m[1][1]/sy, m[1][2]/sz
        m20, m21, m22 = m[2][0]/sx, m[2][1]/sy, m[2][2]/sz

        trace = m00 + m11 + m22
        if trace > 0:
            s = 0.5 / math.sqrt(trace + 1.0)
            w = 0.25 / s
            x = (m21 - m12) * s
            y = (m02 - m20) * s
            z = (m10 - m01) * s
        elif m00 > m11 and m00 > m22:
            s = 2.0 * math.sqrt(1.0 + m00 - m11 - m22)
            w = (m21 - m12) / s
            x = 0.25 * s
            y = (m01 + m10) / s
            z = (m02 + m20) / s
        elif m11 > m22:
            s = 2.0 * math.sqrt(1.0 + m11 - m00 - m22)
            w = (m02 - m20) / s
            x = (m01 + m10) / s
            y = 0.25 * s
            z = (m12 + m21) / s
        else:
            s = 2.0 * math.sqrt(1.0 + m22 - m00 - m11)
            w = (m10 - m01) / s
            x = (m02 + m20) / s
            y = (m12 + m21) / s
            z = 0.25 * s
        return [x, y, z, w]


class Quaternion:
    def __init__(self, x: float, y: float, z: float, w: float):
        self.x, self.y, self.z, self.w = x, y, z, w
    
    def to_matrix4x4(self) -> Matrix4x4:
        x, y, z, w = self.x, self.y, self.z, self.w
        xx, yy, zz = x*x, y*y, z*z
        xy, xz, yz = x*y, x*z, y*z
        wx, wy, wz = w*x, w*y, w*z
        
        mat = Matrix4x4()
        mat.matrix[0][0] = 1 - 2 * (yy + zz)
        mat.matrix[0][1] = 2 * (xy - wz)
        mat.matrix[0][2] = 2 * (xz + wy)
        mat.matrix[0][3] = 0
        mat.matrix[1][0] = 2 * (xy + wz)
        mat.matrix[1][1] = 1 - 2 * (xx + zz)
        mat.matrix[1][2] = 2 * (yz - wx)
        mat.matrix[1][3] = 0
        mat.matrix[2][0] = 2 * (xz - wy)
        mat.matrix[2][1] = 2 * (yz + wx)
        mat.matrix[2][2] = 1 - 2 * (xx + yy)
        mat.matrix[2][3] = 0
        return mat
    
    def multiply(self, other: 'Quaternion') -> 'Quaternion':
        x = self.w * other.x + self.x * other.w + self.y * other.z - self.z * other.y
        y = self.w * other.y - self.x * other.z + self.y * other.w + self.z * other.x
        z = self.w * other.z + self.x * other.y - self.y * other.x + self.z * other.w
        w = self.w * other.w - self.x * other.x - self.y * other.y - self.z * other.z
        return Quaternion(x, y, z, w)
    
    def to_list(self) -> List[float]:
        return [self.x, self.y, self.z, self.w]

def quaternion_from_xbg_data(quat_data: List[float]) -> Quaternion:
    if len(quat_data) >= 4:
        return Quaternion(quat_data[0], quat_data[1], quat_data[2], quat_data[3])
    return Quaternion(0, 0, 0, 1)

def create_translation_matrix(position: List[float]) -> Matrix4x4:
    mat = Matrix4x4()
    mat.matrix[0][3] = position[0]
    mat.matrix[1][3] = position[1]
    mat.matrix[2][3] = position[2]
    return mat