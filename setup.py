from cx_Freeze import setup, Executable
import os
import sys
import glob
import multiprocessing
import site
import ctypes.util

# Define the base directory
base_dir = os.path.abspath(os.path.dirname(__file__))

# Collect all files and folders recursively
EXCLUDE_DIRS = {'objects', 'mass_exported_objects'}  # .model_cache no longer generated (direct XBG loading)

def collect_files(directory):
    files = []
    for path, dirs, filenames in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for filename in filenames:
            files.append((os.path.join(path, filename), os.path.relpath(os.path.join(path, filename), base_dir)))
    return files

# List all directories you want to include
directories_to_include = [
    'canvas',               # Canvas-related modules and resources
    'tools',                # FCBConverter and other conversion tools
    'icon',                 # Icons for the application
    #'cache',                # Cache directory
    'thumbnails',           # Thumbnails directory
    'entities',             # Entity XML templates/library
    #'objects',              # Objects directory (contains binhex_converter.py, etc.)
]

# Collect all files from these directories
include_files = []
for directory in directories_to_include:
    if os.path.exists(os.path.join(base_dir, directory)):
        include_files.extend(collect_files(os.path.join(base_dir, directory)))

# Add individual Python files that are part of your level editor
root_files = [
    'all_in_one_copy_paste.py',
    'avatar_icon.ico',
    'cache_manager.py',
    'check_exe_arch.py',
    'data_models.py',
    'default_i3.png',
    'default_i5.png',
    'entity_editor.py',
    'entity_export_import.py',
    'file_converter.py',
    'fix_frozen_paths.py',
    'game_selector.py',
    'hash_parser.py',
    'movie_data.py',
    'init.py',
    'loading_logo2.png',
    'loading_logo3.png',
    'main.py',
    'set_patch_folder.py',
    'simplified_map_editor.py',
    'theme_settings.py',
    '__init__.py',
]

for file in root_files:
    if os.path.exists(os.path.join(base_dir, file)):
        include_files.append((os.path.join(base_dir, file), file))

# Add any .exe files in tools directory with explicit destination paths
tools_exe_files = glob.glob(os.path.join(base_dir, "tools", "*.exe"))
for exe_file in tools_exe_files:
    filename = os.path.basename(exe_file)
    include_files.append((exe_file, f"tools/{filename}"))

# Add any .dll files that might be needed
dll_files = glob.glob(os.path.join(base_dir, "tools", "*.dll"))
for dll_file in dll_files:
    filename = os.path.basename(dll_file)
    include_files.append((dll_file, f"tools/{filename}"))

# Add any config files
config_files = glob.glob(os.path.join(base_dir, "tools", "*.config"))
for config_file in config_files:
    filename = os.path.basename(config_file)
    include_files.append((config_file, f"tools/{filename}"))

# ============================================================================
# ICON FILE - Explicitly include the icon file in the build
# ============================================================================
icon_file_path = os.path.join(base_dir, 'avatar_icon.ico')  # Icon in root directory
if os.path.exists(icon_file_path):
    include_files.append((icon_file_path, 'avatar_icon.ico'))
    print(f"✓ Icon file will be included: {icon_file_path}")
else:
    print(f"⚠ WARNING: Icon file not found at: {icon_file_path}")

# ============================================================================
# CRITICAL FIX #1: PyQt6 OpenGL Platform Plugins
# ============================================================================
print("\n" + "="*70)
print("ADDING PYQT6 OPENGL SUPPORT")
print("="*70)

try:
    import PyQt6
    pyqt6_path = os.path.dirname(PyQt6.__file__)
    
    # Add platform plugins (REQUIRED for OpenGL rendering)
    platforms_src = os.path.join(pyqt6_path, 'Qt6', 'plugins', 'platforms')
    if os.path.exists(platforms_src):
        include_files.append((platforms_src, 'platforms'))
        print(f"✓ Added PyQt6 platform plugins from: {platforms_src}")
    else:
        print(f"⚠ Warning: PyQt6 platform plugins not found at: {platforms_src}")
    
    # Add imageformats plugins (for texture loading)
    imageformats_src = os.path.join(pyqt6_path, 'Qt6', 'plugins', 'imageformats')
    if os.path.exists(imageformats_src):
        include_files.append((imageformats_src, 'imageformats'))
        print(f"✓ Added PyQt6 imageformats plugins from: {imageformats_src}")
    
    # Qt6OpenGL.dll / Qt6OpenGLWidgets.dll are bundled automatically by
    # cx_Freeze via PyQt6.QtOpenGL / PyQt6.QtOpenGLWidgets in packages.
    # Do NOT copy them to the root — that causes version-mismatch crashes
    # when the user has a different Qt version on their system PATH.
    
except Exception as e:
    print(f"⚠ Warning: Could not locate PyQt6 plugins: {e}")

# ============================================================================
# CRITICAL FIX #2: PIL/Pillow DDS Support and Binary Files
# ============================================================================
print("\n" + "="*70)
print("ADDING PIL/PILLOW TEXTURE SUPPORT (DDS, PNG, TGA, etc.)")
print("="*70)

try:
    import PIL
    pil_path = os.path.dirname(PIL.__file__)
    
    # Include ALL plugin files (Python and binary)
    plugin_count = 0
    for item in os.listdir(pil_path):
        item_path = os.path.join(pil_path, item)
        
        # Include plugin .py files
        if item.endswith('Plugin.py'):
            include_files.append((item_path, f'PIL/{item}'))
            print(f"✓ Added PIL plugin: {item}")
            plugin_count += 1
        
        # Include binary extension modules (.pyd on Windows, .so on Linux)
        elif item.endswith('.pyd') or item.endswith('.so') or item.endswith('.dll'):
            include_files.append((item_path, f'PIL/{item}'))
            print(f"✓ Added PIL binary: {item}")
            plugin_count += 1
    
    print(f"✓ Added {plugin_count} PIL components from: {pil_path}")
    
except Exception as e:
    print(f"⚠ Warning: Could not locate PIL plugins: {e}")

# ============================================================================
# CRITICAL FIX #3: OpenGL System DLLs (Windows)
# ============================================================================
if sys.platform == 'win32':
    print("\n" + "="*70)
    print("ADDING OPENGL SYSTEM DLLS (WINDOWS)")
    print("="*70)
    
    try:
        # Find OpenGL32.dll and GLU32.dll
        opengl32_path = ctypes.util.find_library('opengl32')
        glu32_path = ctypes.util.find_library('glu32')
        
        if opengl32_path:
            # Usually in C:\Windows\System32
            # Don't actually copy system DLLs - just verify they exist
            print(f"✓ OpenGL32.dll found: {opengl32_path}")
        else:
            print(f"⚠ Warning: OpenGL32.dll not found - 3D rendering may fail!")
        
        if glu32_path:
            print(f"✓ GLU32.dll found: {glu32_path}")
        else:
            print(f"⚠ Warning: GLU32.dll not found - 3D rendering may fail!")
            
    except Exception as e:
        print(f"⚠ Could not verify OpenGL DLLs: {e}")

# ============================================================================
# CRITICAL FIX #4: NumPy Binary Files
# ============================================================================
print("\n" + "="*70)
print("ADDING NUMPY BINARY SUPPORT")
print("="*70)

try:
    import numpy
    numpy_path = os.path.dirname(numpy.__file__)
    
    # Include numpy binary extensions
    numpy_core = os.path.join(numpy_path, 'core')
    if os.path.exists(numpy_core):
        for item in os.listdir(numpy_core):
            if item.endswith('.pyd') or item.endswith('.so') or item.endswith('.dll'):
                item_path = os.path.join(numpy_core, item)
                include_files.append((item_path, f'numpy/core/{item}'))
                print(f"✓ Added NumPy binary: {item}")
    
    # Include numpy.libs directory (contains MKL, OpenBLAS, etc.)
    numpy_libs = os.path.join(numpy_path, '.libs')
    if os.path.exists(numpy_libs):
        include_files.append((numpy_libs, 'numpy/.libs'))
        print(f"✓ Added NumPy libraries from: {numpy_libs}")
    
    # Alternative location for newer numpy versions
    numpy_libs2 = os.path.join(numpy_path, 'numpy.libs')
    if os.path.exists(numpy_libs2):
        include_files.append((numpy_libs2, 'numpy.libs'))
        print(f"✓ Added NumPy libraries from: {numpy_libs2}")
        
except Exception as e:
    print(f"⚠ Warning: Could not locate NumPy binaries: {e}")

# ============================================================================
# SHADER FILES (if any exist in your project)
# ============================================================================
print("\n" + "="*70)
print("SEARCHING FOR SHADER FILES")
print("="*70)

shader_extensions = ['.vert', '.frag', '.glsl', '.vs', '.fs', '.shader']
shader_count = 0
for root, dirs, files in os.walk(base_dir):
    # Skip excluded directories
    if any(skip in root for skip in ['build', 'dist', '__pycache__', '.git', 'venv', 'objects', 'mass_exported_objects']):
        continue
    for file in files:
        if any(file.endswith(ext) for ext in shader_extensions):
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, base_dir)
            include_files.append((full_path, rel_path))
            print(f"✓ Added shader file: {rel_path}")
            shader_count += 1

if shader_count == 0:
    print("✓ No shader files found (using fixed-function pipeline)")

print("\n" + "="*70)
print(f"TOTAL FILES TO INCLUDE: {len(include_files)}")
print("="*70 + "\n")

# ============================================================================
# BUILD OPTIONS
# ============================================================================
build_options = {
    'build_exe': 'build/Avatar_Level_Editor',  # Custom build directory name
    'include_files': include_files,
    'packages': [
        # ===================================================================
        # STANDARD LIBRARY PACKAGES
        # ===================================================================
        'os', 'sys', 'json', 'pathlib', 'typing', 'time', 'math', 'struct', 
        'copy', 'types', 'argparse', 'ast', 'base64', 'collections', 
        'dataclasses', 'datetime', 'glob', 'hashlib', 'importlib', 
        'importlib.util', 'inspect', 'io', 'pickle', 'platform', 'random', 
        're', 'shutil', 'subprocess', 'tempfile', 'traceback',
        
        # XML packages (heavily used)
        'xml', 'xml.etree', 'xml.etree.ElementTree', 'xml.parsers', 
        'xml.parsers.expat', 'xml.dom', 'xml.dom.minidom',
        
        # Multiprocessing packages (comprehensive)
        'multiprocessing',
        'multiprocessing.pool',
        'multiprocessing.connection',
        'multiprocessing.context',
        'multiprocessing.process',
        'multiprocessing.queues',
        'multiprocessing.reduction',
        'multiprocessing.synchronize',
        'multiprocessing.util',
        'multiprocessing.managers',
        'multiprocessing.sharedctypes',
        'multiprocessing.heap',
        'multiprocessing.popen_spawn_win32',
        
        # tkinter (used in objects folder)
        'tkinter',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'tkinter.scrolledtext',
        'tkinter.ttk',
        
        # Other stdlib
        'contextlib', 'functools', 'operator', 'codecs', 'locale',
        'socket', 'urllib', 'urllib.parse', 'decimal', 'uuid', 
        'binascii', 'keyword', 'token', 'tokenize', 'logging',
        'threading', 'queue', 'weakref', 'gc', 'ctypes', 'ctypes.util',
        
        # ===================================================================
        # PYQT6 PACKAGES
        # ===================================================================
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtOpenGL',
        'PyQt6.QtOpenGLWidgets',
        'PyQt6.sip',
        
        # ===================================================================
        # OPENGL PACKAGES - COMPLETE WITH ALL CRITICAL MODULES
        # ===================================================================
        'OpenGL',
        'OpenGL.GL',
        'OpenGL.GLU',
        'OpenGL.GLUT',
        
        # Arrays (CRITICAL for vertex data)
        'OpenGL.arrays',
        'OpenGL.arrays.vbo',
        'OpenGL.arrays.arraydatatype',
        'OpenGL.arrays.formathandler',
        'OpenGL.arrays.numpymodule',
        'OpenGL.arrays.strings',
        'OpenGL.arrays.numbers',
        'OpenGL.arrays.lists',
        
        # GL submodules
        'OpenGL.GL.shaders',
        'OpenGL.GL.framebufferobjects',
        'OpenGL.GL.VERSION',
        'OpenGL.GL.images',
        'OpenGL.GL.exceptional',
        
        # Platform support - CRITICAL FOR DLL LOADING
        'OpenGL.platform',
        'OpenGL.platform.baseplatform',      # ← CRITICAL - Base platform abstraction
        'OpenGL.platform.ctypesloader',      # ← CRITICAL - Loads OpenGL DLLs via ctypes
        'OpenGL.platform.win32',             # Windows-specific
        
        # Core OpenGL modules
        'OpenGL.error',
        'OpenGL.constant',
        'OpenGL.extensions',
        'OpenGL.contextdata',
        'OpenGL.converters',
        'OpenGL.wrapper',
        'OpenGL.latebind',
        
        # Raw modules (low-level OpenGL)
        'OpenGL.raw',
        'OpenGL.raw.GL',
        'OpenGL.raw.GLU',
        'OpenGL.raw.GLUT',
        'OpenGL.raw.GL.VERSION',
        
        # Optional: OpenGL accelerate (comment out if not installed or causing issues)
        # 'OpenGL.accelerate',
        # 'OpenGL.accelerate.arraydatatype',
        # 'OpenGL.accelerate.vbo',
        
        # ===================================================================
        # NUMPY - COMPLETE (compatible with numpy 1.20+)
        # ===================================================================
        'numpy',
        'numpy.core',
        'numpy.lib',
        'numpy.linalg',
        'numpy.random',
        'numpy.fft',
        'numpy.polynomial',
        'numpy.ma',
        
        # ===================================================================
        # PIL/PILLOW - COMPLETE WITH ALL FORMAT PLUGINS
        # ===================================================================
        'PIL',
        'PIL.Image',
        'PIL.ImageFile',
        'PIL.ImageOps',
        'PIL.ImageDraw',
        'PIL.ImageFilter',
        'PIL.ImageChops',
        'PIL.ImageEnhance',
        'PIL.ImageFont',
        'PIL.ImageColor',
        'PIL.ImageMode',
        'PIL.ImagePalette',
        'PIL.ImageSequence',
        'PIL.ImageStat',
        'PIL.ImageTransform',
        'PIL.ImageMath',
        
        # Image format plugins - CRITICAL FOR GAME TEXTURES
        'PIL.PngImagePlugin',       # PNG support
        'PIL.JpegImagePlugin',      # JPEG support
        'PIL.BmpImagePlugin',       # BMP support
        'PIL.TgaImagePlugin',       # TGA support (common in games)
        'PIL.TiffImagePlugin',      # TIFF support
        'PIL.GifImagePlugin',       # GIF support
        'PIL.PpmImagePlugin',       # PPM support
        'PIL.DdsImagePlugin',       # ← CRITICAL - DDS support for game textures
        'PIL.IcoImagePlugin',       # ICO support
        'PIL.PcxImagePlugin',       # PCX support
        'PIL.SgiImagePlugin',       # SGI support
        'PIL.SpiderImagePlugin',    # Spider support
        'PIL.WebPImagePlugin',      # WebP support
        
        # ===================================================================
        # ROOT LEVEL MODULES (your application modules)
        # ===================================================================
        'all_in_one_copy_paste',
        'cache_manager',
        'data_models',
        'entity_editor',
        'entity_export_import',
        'file_converter',
        'fix_frozen_paths',
        'game_selector',
        'hash_parser',
        'init',
        'main',
        'set_patch_folder',
        'simplified_map_editor',
        'theme_settings',
        
        # ===================================================================
        # CANVAS PACKAGE - ALL SUBMODULES
        # ===================================================================
        'canvas',
        'canvas.__init__',
        'canvas.binary_reader',
        'canvas.camera_controller',
        'canvas.entity_renderer',
        'canvas.game_paths_config',
        'canvas.gizmo_3d',
        'canvas.gizmo_renderer',
        'canvas.grid_renderer',
        'canvas.input_handler',
        'canvas.map_canvas_gpu',        # ← CRITICAL - Main 3D canvas
        'canvas.math_utils',
        'canvas.mesh',
        'canvas.model_loader',          # ← CRITICAL - 3D model loading
        'canvas.opengl_utils',          # ← CRITICAL - OpenGL utilities
        'canvas.skeleton',
        'canvas.terrain_renderer',      # ← CRITICAL - 2D terrain rendering
        'canvas.terrain_to_gltf',       # ← CRITICAL - 3D terrain generation
        'canvas.texture_loader',        # ← CRITICAL - Texture loading
        'canvas.undo_redo',
        'canvas.terrain_editor_dialog',
        'canvas.terrain_texture_painter',
        'canvas.water_editor_dialog',
        'canvas.water_mesh_editor',
        'canvas.water_plane_renderer',
        'canvas.movie_renderer',
        'canvas.mp_spawn_creator',
        'canvas.xbg_parser',
        'canvas.xbg_direct_loader',     # ← Direct XBG→model loading (no GLTF cache)
        'canvas.model_shader',          # ← GLSL per-pixel material shader (normal maps + spec + emission)
        'canvas.gpu_driven_renderer',   # ← GL 4.3+ MultiDrawIndirect fast path (modern GPUs; falls back otherwise)
        'canvas.night_sky',             # ← night-sky star dome (Night Sky.glb), day/night cycle
        'canvas.sky_atmosphere',        # ← daytime spectral atmosphere sky (fgarlin shadertoy port)
        'canvas.shadow_map',            # ← sun shadow mapping (depth FBO + light-space matrix)
        'canvas.cube_batch',            # ← instanced marker-cube renderer (one draw for all cubes)
        'canvas.line_batch',            # ← batched wireframe-overlay renderer (prims/triggers/shape)

        # ===================================================================
        # TOOLS PACKAGE
        # ===================================================================
        'tools',
        
        # ===================================================================
        # OTHER DEPENDENCIES
        # ===================================================================
        'pkg_resources',
        'encodings',
        'encodings.utf_8',
        'encodings.latin_1',
        'encodings.cp1252',
    ],
    
    'excludes': [
        # Test / dev tools
        'test', 'unittest', 'pytest',
        'matplotlib', 'scipy',
        'IPython', 'jupyter',
        'pandas',
        'setuptools',
        'distutils',
        # Unused PyQt6 modules (QML, multimedia, network, designer, etc.)
        'PyQt6.QtQml',
        'PyQt6.QtQuick',
        'PyQt6.QtQuick3D',
        'PyQt6.QtMultimedia',
        'PyQt6.QtMultimediaWidgets',
        'PyQt6.QtNetwork',
        'PyQt6.QtPrintSupport',
        'PyQt6.QtDesigner',
        'PyQt6.QtSvg',
        'PyQt6.QtSvgWidgets',
        'PyQt6.QtHelp',
        'PyQt6.QtPositioning',
        'PyQt6.QtRemoteObjects',
        'PyQt6.QtBluetooth',
        'PyQt6.QtSensors',
        'PyQt6.QtSql',
        'PyQt6.QtDBus',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebChannel',
        'PyQt6.QtPdf',
        'PyQt6.QtPdfWidgets',
        'PyQt6.QtShaderTools',
        'PyQt6.QtSpatialAudio',
        'PyQt6.QtTextToSpeech',
        'PyQt6.QtCharts',
        'PyQt6.QtDataVisualization',
        'PyQt6.Qt3DCore',
        'PyQt6.Qt3DRender',
        'PyQt6.Qt3DInput',
        'PyQt6.Qt3DLogic',
        'PyQt6.Qt3DAnimation',
        'PyQt6.Qt3DExtras',
    ],
    
    'include_msvcr': True,
    'optimize': 0,  # Don't optimize - helps with debugging
    'zip_include_packages': ['encodings', 'importlib'],
    'bin_includes': [],
    'replace_paths': [('*', '')],
}

# ============================================================================
# EXECUTABLE CONFIGURATION
# ============================================================================
# Define the icon path - this is used to embed the icon into the .exe file
# Icon should be in the root directory: Avatar_Level_Editor\avatar_icon.ico
icon_path = os.path.join(base_dir, 'avatar_icon.ico')

# Verify the icon file exists
if os.path.exists(icon_path):
    print(f"\n✓ Icon file verified for embedding: {icon_path}")
    use_icon = icon_path
else:
    print(f"\n⚠ WARNING: Icon file not found at: {icon_path}")
    print("The executable will be built without an icon.")
    use_icon = None

executables = [
    Executable(
        'main.py',
        base='Win32GUI' if sys.platform == 'win32' else None,
        target_name='Avatar_Level_Editor.exe',
        icon=use_icon,  # Icon is embedded into the .exe at build time
    )
]

# ============================================================================
# SETUP - MUST be inside if __name__ == '__main__' for multiprocessing
# ============================================================================
if __name__ == '__main__':
    # CRITICAL: Must be first for multiprocessing support in frozen exe
    multiprocessing.freeze_support()
    
    print("\n" + "="*70)
    print("BUILDING AVATAR LEVEL EDITOR WITH CX_FREEZE")
    print("="*70)
    print(f"Base directory: {base_dir}")
    print(f"Platform: {sys.platform}")
    print(f"Python version: {sys.version}")
    print(f"Including {len(include_files)} files")
    print("="*70)
    print("\n🔧 CRITICAL 3D RENDERING FIXES APPLIED:")
    print("  ✓ OpenGL platform loaders (ctypesloader, baseplatform)")
    print("  ✓ PIL/Pillow DDS plugin with binaries")
    print("  ✓ NumPy binary extensions")
    print("  ✓ PyQt6 OpenGL platform plugins")
    print("  ✓ All texture format plugins")
    print("="*70 + "\n")
    
    setup(
        name='Avatar Level Editor',
        version='1.9.5',
        description='Level Editor for Avatar: The Game - Edit maps, entities, and worldsectors with 3D support',
        author='Jasper_Zebra',
        options={'build_exe': build_options},
        executables=executables
    )

    # ============================================================================
    # POST-BUILD CLEANUP: Remove directories that should not ship in the build
    # (cx_Freeze copies the full canvas package dir, bypassing EXCLUDE_DIRS)
    # ============================================================================
    import shutil
    cleanup_dirs = [
        os.path.join(base_dir, 'build', 'Avatar_Level_Editor', 'lib', 'canvas', '.model_cache'),
    ]
    for cleanup_path in cleanup_dirs:
        if os.path.exists(cleanup_path):
            shutil.rmtree(cleanup_path)
            print(f"✓ Removed from build: {cleanup_path}")

    # ============================================================================
    # POST-BUILD: Strip unneeded PyQt6 / Qt6 components (~2+ GB savings)
    # ============================================================================
    print("\n" + "="*70)
    print("POST-BUILD: STRIPPING UNNEEDED PyQt6/Qt6 COMPONENTS")
    print("="*70)

    pyqt6_build = os.path.join(base_dir, 'build', 'Avatar_Level_Editor', 'lib', 'PyQt6')
    qt6_build   = os.path.join(pyqt6_build, 'Qt6')

    # 1. QML runtime — 2.0 GB, not used
    _del_dir = os.path.join(qt6_build, 'qml')
    if os.path.exists(_del_dir):
        shutil.rmtree(_del_dir)
        print(f"✓ Removed Qt6/qml (~2 GB)")

    # 2. Translations — ~7 MB, not required for a game-editor tool
    _del_dir = os.path.join(qt6_build, 'translations')
    if os.path.exists(_del_dir):
        shutil.rmtree(_del_dir)
        print(f"✓ Removed Qt6/translations")

    # 3. Plugin folders — keep only what the app uses
    _keep_plugins = {'platforms', 'imageformats', 'styles', 'iconengines'}
    _plugins_dir  = os.path.join(qt6_build, 'plugins')
    if os.path.exists(_plugins_dir):
        for _name in os.listdir(_plugins_dir):
            if _name not in _keep_plugins:
                _path = os.path.join(_plugins_dir, _name)
                if os.path.isdir(_path):
                    shutil.rmtree(_path)
                    print(f"✓ Removed plugin folder: {_name}")

    # 4. Unneeded Qt6 DLLs sitting in lib/PyQt6/
    _unneeded_dlls = [
        'Qt6Quick.dll', 'Qt6Qml.dll', 'Qt6QmlModels.dll', 'Qt6QmlWorkerScript.dll',
        'Qt6Designer.dll', 'Qt6Pdf.dll', 'Qt6ShaderTools.dll',
        'Qt6Quick3D.dll', 'Qt6Quick3DRuntimeRender.dll', 'Qt6Quick3DUtils.dll',
        'Qt6Multimedia.dll', 'Qt6MultimediaQuick.dll',
        'Qt6Bluetooth.dll', 'Qt6DBus.dll', 'Qt6SpatialAudio.dll',
        'Qt6RemoteObjects.dll', 'Qt6Svg.dll', 'Qt6Help.dll',
        'Qt6Positioning.dll', 'Qt6Network.dll', 'Qt6PrintSupport.dll',
        'Qt6WebEngineCore.dll', 'Qt6Charts.dll', 'Qt6DataVisualization.dll',
    ]
    for _dll in _unneeded_dlls:
        _p = os.path.join(pyqt6_build, _dll)
        if os.path.exists(_p):
            os.remove(_p)
            print(f"✓ Removed {_dll}")

    # 5. Unneeded PyQt6 .pyd bindings
    _unneeded_pyds = [
        'QtQuick.pyd', 'QtQml.pyd', 'QtNetwork.pyd', 'QtPrintSupport.pyd',
        'QtDesigner.pyd', 'QtMultimedia.pyd', 'QtMultimediaWidgets.pyd',
        'QtBluetooth.pyd', 'QtSvg.pyd', 'QtSvgWidgets.pyd',
        'QtHelp.pyd', 'QtPositioning.pyd', 'QtRemoteObjects.pyd',
        'QtSensors.pyd', 'QtSql.pyd', 'QtDBus.pyd', 'QtPdf.pyd',
        'QtPdfWidgets.pyd', 'QtShaderTools.pyd', 'QtSpatialAudio.pyd',
        'QtTextToSpeech.pyd', 'QtCharts.pyd', 'QtDataVisualization.pyd',
        'Qt3DCore.pyd', 'Qt3DRender.pyd', 'Qt3DInput.pyd',
        'Qt3DLogic.pyd', 'Qt3DAnimation.pyd', 'Qt3DExtras.pyd',
    ]
    for _pyd in _unneeded_pyds:
        _p = os.path.join(pyqt6_build, _pyd)
        if os.path.exists(_p):
            os.remove(_p)
            print(f"✓ Removed {_pyd}")

    print("\n" + "="*70)
    print("BUILD COMPLETE!")
    print("="*70)
    print("\nTo build the executable, run:")
    print("  python setup.py build")
    print("\nOutput will be in: build/Avatar_Level_Editor/")
    print("="*70 + "\n")