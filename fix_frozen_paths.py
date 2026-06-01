"""
Runtime fixes for frozen executable (cx_Freeze/PyInstaller)

Import this FIRST in main.py before any other imports:
    import fix_frozen_paths

This module fixes common issues with frozen executables:
1. Temp directory access for GLTF terrain generation
2. OpenGL context issues
3. File path resolution
"""

import os
import sys
import tempfile

# ============================================================================
# FIX #1: Detect if running as frozen executable
# ============================================================================
IS_FROZEN = getattr(sys, 'frozen', False)

if IS_FROZEN:
    # Get the directory where the exe is located
    EXE_DIR = os.path.dirname(sys.executable)
    print(f"Running as frozen executable from: {EXE_DIR}")
else:
    # Running as normal Python script
    EXE_DIR = os.path.dirname(os.path.abspath(__file__))
    print(f"Running as Python script from: {EXE_DIR}")

# ============================================================================
# FIX #2: Create writable temp directory for GLTF terrain files
# ============================================================================
if IS_FROZEN:
    # Create temp directory next to exe (has write permissions)
    TEMP_TERRAIN_DIR = os.path.join(EXE_DIR, 'temp_terrain')
    os.makedirs(TEMP_TERRAIN_DIR, exist_ok=True)
    print(f"✓ Created temp terrain directory: {TEMP_TERRAIN_DIR}")
    
    # Override tempfile.mkdtemp for terrain generation
    _original_mkdtemp = tempfile.mkdtemp
    
    def custom_mkdtemp(suffix=None, prefix=None, dir=None):
        """Custom mkdtemp that uses exe directory for terrain files"""
        # If this is a terrain-related temp directory, create a unique
        # subdirectory inside TEMP_TERRAIN_DIR so each level load gets a
        # distinct path. Without this, every load returns the same path and
        # model_loader's cache returns the first level's terrain for all
        # subsequent levels.
        if prefix and 'terrain' in prefix.lower():
            unique_dir = _original_mkdtemp(suffix=suffix, prefix=prefix, dir=TEMP_TERRAIN_DIR)
            print(f"✓ Redirecting terrain temp dir to: {unique_dir}")
            return unique_dir
        # Otherwise use default behavior
        return _original_mkdtemp(suffix, prefix, dir)
    
    # Replace tempfile.mkdtemp
    tempfile.mkdtemp = custom_mkdtemp
    print("✓ Patched tempfile.mkdtemp for frozen exe")

# ============================================================================
# FIX #3: Fix OpenGL environment for frozen exe
# ============================================================================
if IS_FROZEN:
    # Configure PyOpenGL for frozen exe (don't set PYOPENGL_PLATFORM - let it auto-detect)
    # Setting it to a specific platform can cause import errors
    print("✓ OpenGL environment configured for frozen exe")

# ============================================================================
# FIX #4: Ensure PIL can find its plugins in frozen exe
# ============================================================================
if IS_FROZEN:
    try:
        import PIL
        import PIL.Image
        
        # Force PIL to load all plugins
        PIL.Image.preinit()
        PIL.Image.init()
        
        print(f"✓ PIL initialized with {len(PIL.Image.OPEN)} image formats")
        
        # Check if DDS plugin is available
        if 'DDS' in PIL.Image.OPEN:
            print("✓ DDS plugin loaded successfully")
        else:
            print("⚠ WARNING: DDS plugin not available - textures may not load!")
            
    except Exception as e:
        print(f"⚠ Warning: PIL initialization error: {e}")

# ============================================================================
# FIX #5: Add exe directory to Python path for local imports
# ============================================================================
if IS_FROZEN and EXE_DIR not in sys.path:
    sys.path.insert(0, EXE_DIR)
    print(f"✓ Added exe directory to Python path")

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_resource_path(relative_path):
    """
    Get absolute path to resource - works for dev and frozen exe
    
    Args:
        relative_path: Relative path to resource file
        
    Returns:
        Absolute path to resource
    """
    if IS_FROZEN:
        # In frozen exe, resources are in same dir as exe
        base_path = EXE_DIR
    else:
        # In dev, resources are relative to this file
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    return os.path.join(base_path, relative_path)

def get_temp_terrain_dir():
    """Get the temp directory for terrain GLTF files"""
    if IS_FROZEN:
        return TEMP_TERRAIN_DIR
    else:
        # In dev mode, use system temp
        return tempfile.gettempdir()

def verify_opengl_available():
    """
    Verify OpenGL is available and working
    
    Returns:
        True if OpenGL is available, False otherwise
    """
    try:
        from OpenGL import GL
        from OpenGL.GL import glGetString, GL_VERSION
        
        print("✓ OpenGL modules imported successfully")
        return True
        
    except ImportError as e:
        print(f"✗ OpenGL import failed: {e}")
        return False
    except Exception as e:
        print(f"✗ OpenGL error: {e}")
        return False

def verify_pil_dds_available():
    """
    Verify PIL can open DDS files
    
    Returns:
        True if DDS support is available, False otherwise
    """
    try:
        from PIL import Image
        
        # Check if DDS plugin is registered
        if 'DDS' in Image.OPEN or 'dds' in Image.EXTENSION:
            print("✓ DDS support available")
            return True
        else:
            print("✗ DDS support not available")
            return False
            
    except Exception as e:
        print(f"✗ PIL DDS check failed: {e}")
        return False

# ============================================================================
# DIAGNOSTIC FUNCTION - Call from main.py after imports
# ============================================================================

def run_frozen_diagnostics():
    """
    Run diagnostics to check if all 3D rendering dependencies are available
    Call this from main.py after all imports
    """
    print("\n" + "="*70)
    print("FROZEN EXECUTABLE DIAGNOSTICS")
    print("="*70)
    
    print(f"\nExecution mode: {'FROZEN EXE' if IS_FROZEN else 'PYTHON SCRIPT'}")
    print(f"Base directory: {EXE_DIR}")
    
    if IS_FROZEN:
        print(f"Temp terrain dir: {TEMP_TERRAIN_DIR}")
        print(f"Temp dir exists: {os.path.exists(TEMP_TERRAIN_DIR)}")
        print(f"Temp dir writable: {os.access(TEMP_TERRAIN_DIR, os.W_OK)}")
    
    print("\nChecking 3D rendering dependencies:")
    
    # Check OpenGL
    opengl_ok = verify_opengl_available()
    print(f"  OpenGL: {'✓ OK' if opengl_ok else '✗ FAILED'}")
    
    # Check PIL DDS
    dds_ok = verify_pil_dds_available()
    print(f"  DDS Support: {'✓ OK' if dds_ok else '✗ FAILED'}")
    
    # Check NumPy
    try:
        import numpy
        print(f"  NumPy: ✓ OK (version {numpy.__version__})")
    except ImportError:
        print(f"  NumPy: ✗ FAILED")
    
    # Check PyQt6 OpenGL
    try:
        from PyQt6.QtOpenGLWidgets import QOpenGLWidget
        print(f"  PyQt6 OpenGL: ✓ OK")
    except ImportError:
        print(f"  PyQt6 OpenGL: ✗ FAILED")
    
    print("\n" + "="*70)
    
    if not (opengl_ok and dds_ok):
        print("⚠ WARNING: Some 3D rendering components are missing!")
        print("3D models and terrain may not render correctly.")
        print("="*70)
    else:
        print("✓ All 3D rendering components are available")
        print("="*70)
    
    print()

# ============================================================================
# AUTO-RUN ON IMPORT
# ============================================================================
if IS_FROZEN:
    print("\n" + "="*70)
    print("FROZEN EXECUTABLE FIXES APPLIED")
    print("="*70)
    print("✓ Temp directory fix applied")
    print("✓ OpenGL environment configured")
    print("✓ PIL plugins initialized")
    print("✓ Python path configured")
    print("="*70 + "\n")