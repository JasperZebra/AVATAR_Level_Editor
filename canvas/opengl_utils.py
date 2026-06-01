"""OpenGL utility functions for coordinate conversion and helpers - 2D ONLY"""

import math
from time import time
from PyQt6.QtGui import QVector3D


# ---------------------------------------------------------------------------
# Layout-independent movement key detection
# ---------------------------------------------------------------------------
# Windows scan codes for the physical key positions that QWERTY labels W/A/S/D/Q/E.
# These are identical regardless of keyboard layout (AZERTY, DVORAK, Colemak…).
_SCAN_TO_ACTION = {
    17: "FORWARD",    # W position  (Z on AZERTY)
    30: "LEFT",       # A position  (Q on AZERTY)
    31: "BACKWARD",   # S position  (same everywhere)
    32: "RIGHT",      # D position  (same everywhere)
    16: "DOWN",       # Q position  (A on AZERTY)
    18: "UP",         # E position  (same everywhere)
}

def movement_action(event):
    """Return a movement action string for a key event using the physical scan code,
    so the controls work on any keyboard layout (AZERTY, DVORAK, Colemak…).

    Returns one of 'FORWARD', 'BACKWARD', 'LEFT', 'RIGHT', 'UP', 'DOWN',
    or None if the key is not a movement key.
    """
    return _SCAN_TO_ACTION.get(event.nativeScanCode())

class OpenGLUtils:
    """Utility functions for OpenGL operations and coordinate conversions - 2D ONLY"""
    
    @staticmethod
    def world_to_screen(world_x, world_y, canvas):
        """Convert world coordinates to screen coordinates"""
        screen_x = world_x * canvas.scale_factor + canvas.offset_x
        screen_y = canvas.height() - (world_y * canvas.scale_factor + canvas.offset_y)
        return screen_x, screen_y

    @staticmethod
    def screen_to_world(screen_x, screen_y, canvas):
        """Convert screen coordinates to world coordinates"""
        world_x = (screen_x - canvas.offset_x) / canvas.scale_factor
        world_y = (canvas.height() - screen_y - canvas.offset_y) / canvas.scale_factor
        return world_x, world_y

    @staticmethod
    def create_shader_program(vertex_source, fragment_source):
        """Create and compile a shader program (for future OpenGL expansion)"""
        try:
            from PyQt6.QtOpenGL import QOpenGLShaderProgram, QOpenGLShader
            
            program = QOpenGLShaderProgram()
            
            # Add vertex shader
            if not program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, vertex_source):
                print(f"Vertex shader failed: {program.log()}")
                return None
            
            # Add fragment shader
            if not program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fragment_source):
                print(f"Fragment shader failed: {program.log()}")
                return None
            
            # Link program
            if not program.link():
                print(f"Shader linking failed: {program.log()}")
                return None
            
            return program
            
        except ImportError:
            print("OpenGL not available for shader creation")
            return None
        except Exception as e:
            print(f"Error creating shader program: {e}")
            return None

    @staticmethod
    def create_opengl_buffer(data, buffer_type):
        """Create an OpenGL buffer with data (for future expansion)"""
        try:
            from PyQt6.QtOpenGL import QOpenGLBuffer
            import numpy as np
            
            buffer = QOpenGLBuffer(buffer_type)
            if buffer.create():
                buffer.bind()
                if isinstance(data, np.ndarray):
                    buffer.allocate(data.tobytes(), len(data) * 4)
                else:
                    buffer.allocate(data, len(data))
                buffer.release()
                return buffer
            return None
            
        except ImportError:
            return None
        except Exception as e:
            print(f"Error creating OpenGL buffer: {e}")
            return None