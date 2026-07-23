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
EXCLUDE_DIRS = {'objects', 'mass_exported_objects'}

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
    # 'entities' removed — archetypes now come from the level's patch-folder
    # entitylibrary.fcb (converted on load), not a bundled local folder.
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
    'archetype_library.py',
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
    'object_library.py',
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
# CRITICAL FIX #1: PyQt5 OpenGL Platform Plugins
# ============================================================================
print("\n" + "="*70)
print("ADDING PYQT5 OPENGL SUPPORT")
print("="*70)

try:
    import PyQt5
    pyqt5_path = os.path.dirname(PyQt5.__file__)

    # PyQt5 wheels place the Qt runtime under either 'Qt5' (recent) or 'Qt'
    # (older). Detect whichever exists so the plugin paths resolve correctly.
    qt_root = os.path.join(pyqt5_path, 'Qt5')
    if not os.path.exists(qt_root):
        qt_root = os.path.join(pyqt5_path, 'Qt')

    # Add platform plugins (REQUIRED for OpenGL rendering)
    platforms_src = os.path.join(qt_root, 'plugins', 'platforms')
    if os.path.exists(platforms_src):
        include_files.append((platforms_src, 'platforms'))
        print(f"✓ Added PyQt5 platform plugins from: {platforms_src}")
    else:
        print(f"⚠ Warning: PyQt5 platform plugins not found at: {platforms_src}")

    # Add imageformats plugins (for texture loading)
    imageformats_src = os.path.join(qt_root, 'plugins', 'imageformats')
    if os.path.exists(imageformats_src):
        include_files.append((imageformats_src, 'imageformats'))
        print(f"✓ Added PyQt5 imageformats plugins from: {imageformats_src}")

    # Qt5Core.dll / Qt5Gui.dll / Qt5Widgets.dll / Qt5OpenGL.dll are bundled
    # automatically by cx_Freeze via PyQt5.QtCore/QtGui/QtWidgets/QtOpenGL in
    # packages. In PyQt5 QOpenGLWidget lives in QtWidgets (there is no
    # QtOpenGLWidgets module). Do NOT copy the DLLs to the root — that causes
    # version-mismatch crashes when the user has a different Qt on their PATH.

except Exception as e:
    print(f"⚠ Warning: Could not locate PyQt5 plugins: {e}")

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
# Per-architecture output dir so a 32-bit build never overwrites the 64-bit one.
# Run `python setup.py build` (64-bit) and `py -3-32 setup.py build` (32-bit) — or
# just use build_both_versions.bat which does both.
_arch = 'x64' if sys.maxsize > 2**32 else 'x86'
_build_dir = 'build/Avatar_Level_Editor_%s' % _arch
print("Build architecture: %s  ->  %s" % (_arch, _build_dir))

build_options = {
    'build_exe': _build_dir,  # arch-specific build directory name
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
        # PYQT5 PACKAGES
        # ===================================================================
        'PyQt5',
        'PyQt5.QtWidgets',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtOpenGL',
        'PyQt5.sip',
        
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
        'canvas.sky_shader_sources',    # ← embedded GLSL sources for sky_atmosphere (no loose files)
        'canvas.shadow_map',            # ← sun shadow mapping (depth FBO + light-space matrix)
        'canvas.cube_batch',            # ← instanced marker-cube renderer (one draw for all cubes)
        'canvas.line_batch',            # ← batched wireframe-overlay renderer (prims/triggers/shape)
        'canvas.hkx_parser',            # ← native Havok 5.5 .hkx collision reader (wireframe overlay)

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
        # Unused PyQt5 modules (QML, multimedia, network, designer, etc.)
        'PyQt5.QtQml',
        'PyQt5.QtQuick',
        'PyQt5.QtQuick3D',
        'PyQt5.QtMultimedia',
        'PyQt5.QtMultimediaWidgets',
        'PyQt5.QtNetwork',
        'PyQt5.QtPrintSupport',
        'PyQt5.QtDesigner',
        'PyQt5.QtSvg',
        'PyQt5.QtHelp',
        'PyQt5.QtPositioning',
        'PyQt5.QtRemoteObjects',
        'PyQt5.QtBluetooth',
        'PyQt5.QtSensors',
        'PyQt5.QtSql',
        'PyQt5.QtDBus',
        'PyQt5.QtWebEngine',
        'PyQt5.QtWebEngineCore',
        'PyQt5.QtWebEngineWidgets',
        'PyQt5.QtWebChannel',
        'PyQt5.QtWebKit',
        'PyQt5.QtWebKitWidgets',
        'PyQt5.QtXml',
        'PyQt5.QtXmlPatterns',
        'PyQt5.QtTextToSpeech',
        'PyQt5.QtCharts',
        'PyQt5.QtDataVisualization',
        'PyQt5.QtSerialPort',
        'PyQt5.QtNfc',
        'PyQt5.QtQuickWidgets',
        'PyQt5.Qt3DCore',
        'PyQt5.Qt3DRender',
        'PyQt5.Qt3DInput',
        'PyQt5.Qt3DLogic',
        'PyQt5.Qt3DAnimation',
        'PyQt5.Qt3DExtras',
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
    print("  ✓ PyQt5 OpenGL platform plugins")
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

    import shutil

    # ============================================================================
    # POST-BUILD: Strip unneeded PyQt5 / Qt5 components (~2+ GB savings)
    # ============================================================================
    print("\n" + "="*70)
    print("POST-BUILD: STRIPPING UNNEEDED PyQt5/Qt5 COMPONENTS")
    print("="*70)

    pyqt5_build = os.path.join(base_dir, 'build', 'Avatar_Level_Editor', 'lib', 'PyQt5')
    # PyQt5 wheels nest the Qt runtime under either 'Qt5' (recent) or 'Qt' (older).
    qt5_build = os.path.join(pyqt5_build, 'Qt5')
    if not os.path.exists(qt5_build):
        qt5_build = os.path.join(pyqt5_build, 'Qt')

    # 1. QML runtime — large, not used
    _del_dir = os.path.join(qt5_build, 'qml')
    if os.path.exists(_del_dir):
        shutil.rmtree(_del_dir)
        print(f"✓ Removed Qt5/qml")

    # 2. Translations — not required for a game-editor tool
    _del_dir = os.path.join(qt5_build, 'translations')
    if os.path.exists(_del_dir):
        shutil.rmtree(_del_dir)
        print(f"✓ Removed Qt5/translations")

    # 3. Plugin folders — keep only what the app uses
    _keep_plugins = {'platforms', 'imageformats', 'styles', 'iconengines'}
    _plugins_dir  = os.path.join(qt5_build, 'plugins')
    if os.path.exists(_plugins_dir):
        for _name in os.listdir(_plugins_dir):
            if _name not in _keep_plugins:
                _path = os.path.join(_plugins_dir, _name)
                if os.path.isdir(_path):
                    shutil.rmtree(_path)
                    print(f"✓ Removed plugin folder: {_name}")

    # 4. Unneeded Qt5 DLLs sitting in lib/PyQt5/ (and lib/PyQt5/Qt5/bin/).
    #    Note: KEEP Qt5OpenGL.dll — the 3D viewport (QOpenGLWidget) needs it.
    _unneeded_dlls = [
        'Qt5Quick.dll', 'Qt5Qml.dll', 'Qt5QmlModels.dll', 'Qt5QmlWorkerScript.dll',
        'Qt5Designer.dll', 'Qt5DesignerComponents.dll',
        'Qt5Quick3D.dll', 'Qt5Quick3DRuntimeRender.dll', 'Qt5Quick3DUtils.dll',
        'Qt5QuickWidgets.dll', 'Qt5QuickControls2.dll', 'Qt5QuickTemplates2.dll',
        'Qt5Multimedia.dll', 'Qt5MultimediaQuick.dll', 'Qt5MultimediaWidgets.dll',
        'Qt5Bluetooth.dll', 'Qt5DBus.dll', 'Qt5Nfc.dll',
        'Qt5RemoteObjects.dll', 'Qt5Svg.dll', 'Qt5Help.dll',
        'Qt5Positioning.dll', 'Qt5Network.dll', 'Qt5PrintSupport.dll',
        'Qt5WebEngineCore.dll', 'Qt5WebEngine.dll', 'Qt5WebEngineWidgets.dll',
        'Qt5WebChannel.dll', 'Qt5WebKit.dll', 'Qt5WebKitWidgets.dll',
        'Qt5Xml.dll', 'Qt5XmlPatterns.dll', 'Qt5SerialPort.dll',
        'Qt5Charts.dll', 'Qt5DataVisualization.dll', 'Qt5TextToSpeech.dll',
        'Qt53DCore.dll', 'Qt53DRender.dll', 'Qt53DInput.dll',
        'Qt53DLogic.dll', 'Qt53DAnimation.dll', 'Qt53DExtras.dll',
    ]
    _dll_dirs = [pyqt5_build, os.path.join(qt5_build, 'bin')]
    for _dir in _dll_dirs:
        for _dll in _unneeded_dlls:
            _p = os.path.join(_dir, _dll)
            if os.path.exists(_p):
                os.remove(_p)
                print(f"✓ Removed {_dll}")

    # 5. Unneeded PyQt5 .pyd bindings
    _unneeded_pyds = [
        'QtQuick.pyd', 'QtQml.pyd', 'QtNetwork.pyd', 'QtPrintSupport.pyd',
        'QtDesigner.pyd', 'QtMultimedia.pyd', 'QtMultimediaWidgets.pyd',
        'QtBluetooth.pyd', 'QtSvg.pyd', 'QtQuickWidgets.pyd',
        'QtHelp.pyd', 'QtPositioning.pyd', 'QtRemoteObjects.pyd',
        'QtSensors.pyd', 'QtSql.pyd', 'QtDBus.pyd', 'QtNfc.pyd',
        'QtSerialPort.pyd', 'QtXml.pyd', 'QtXmlPatterns.pyd',
        'QtWebChannel.pyd', 'QtWebEngine.pyd', 'QtWebEngineCore.pyd',
        'QtWebEngineWidgets.pyd', 'QtWebKit.pyd', 'QtWebKitWidgets.pyd',
        'QtTextToSpeech.pyd', 'QtCharts.pyd', 'QtDataVisualization.pyd',
        'Qt3DCore.pyd', 'Qt3DRender.pyd', 'Qt3DInput.pyd',
        'Qt3DLogic.pyd', 'Qt3DAnimation.pyd', 'Qt3DExtras.pyd',
    ]
    for _pyd in _unneeded_pyds:
        _p = os.path.join(pyqt5_build, _pyd)
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