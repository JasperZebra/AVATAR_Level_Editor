#!/usr/bin/env python3
"""
XBG to GLTF Converter
Main script that coordinates the conversion process
"""

import os
import argparse
import glob
from xbg_parser import XBGParser
from gltf_exporter import GLTFExporter


def convert_single_file(input_path, output_path, lod_level, materials_path):
    """Convert a single XBG file to GLTF"""
    try:
        print(f"\n{'='*60}")
        print(f"Parsing XBG file: {input_path}")
        
        # Parse XBG file
        parser = XBGParser(input_path)
        xbg_data = parser.parse(lod_level)
        
        print(f"Found {xbg_data.skeleton.get_bone_count()} bones and {len(xbg_data.meshes)} meshes")
        
        # Export to GLTF
        print(f"Converting to GLTF: {output_path}")
        
        # Check if materials path exists
        mat_path = materials_path if materials_path and os.path.exists(materials_path) else None
        if mat_path:
            print(f"Using materials from: {mat_path}")
        else:
            if materials_path:
                print(f"WARNING: Materials path not found: {materials_path}")
            print("Textures will not be embedded. Model will export with colored materials only.")
        
        exporter = GLTFExporter(xbg_data, mat_path)
        exporter.export(output_path)
        
        print(f"✓ Conversion completed successfully: {os.path.basename(output_path)}")
        return True
        
    except Exception as e:
        print(f"✗ Error during conversion of {input_path}: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description='Convert XBG files to GLTF format with textures')
    parser.add_argument('input', help='Input XBG file path or directory (for batch mode)')
    parser.add_argument('-o', '--output', help='Output GLTF file path (single file) or directory (batch mode)')
    parser.add_argument('-l', '--lod', type=int, default=0, 
                       help='LOD level to export (default: 0 = highest detail)')
    parser.add_argument('-m', '--materials', 
                       default=r'D:\Games\Avatar The Game\Data_Win32\Data\graphics\_materials',
                       help='Path to materials folder')
    parser.add_argument('-b', '--batch', action='store_true',
                       help='Batch mode: convert all XBG files in input directory')
    parser.add_argument('-r', '--recursive', action='store_true',
                       help='Recursively search for XBG files in subdirectories (batch mode only)')
    
    args = parser.parse_args()
    
    input_path = args.input
    
    # Check if batch mode
    if args.batch or os.path.isdir(input_path):
        # Batch mode
        if not os.path.isdir(input_path):
            print(f"Error: Batch mode requires input to be a directory")
            return
        
        # Find all XBG files
        if args.recursive:
            xbg_files = glob.glob(os.path.join(input_path, '**', '*.xbg'), recursive=True)
        else:
            xbg_files = glob.glob(os.path.join(input_path, '*.xbg'))
        
        if not xbg_files:
            print(f"No XBG files found in: {input_path}")
            return
        
        print(f"Found {len(xbg_files)} XBG file(s) to convert")
        
        # Get script directory and create models folder
        script_dir = os.path.dirname(os.path.abspath(__file__))
        models_dir = os.path.join(script_dir, 'models')
        
        # Determine output base directory
        if args.output:
            output_base = args.output
        else:
            output_base = models_dir
        
        # Normalize input path for relative path calculation
        input_path_abs = os.path.abspath(input_path)
        
        # Convert each file
        success_count = 0
        for xbg_file in xbg_files:
            # Get relative path from input directory
            xbg_file_abs = os.path.abspath(xbg_file)
            rel_path = os.path.relpath(xbg_file_abs, input_path_abs)
            
            # Get directory structure and filename
            rel_dir = os.path.dirname(rel_path)
            base_name = os.path.splitext(os.path.basename(rel_path))[0]
            
            # Create output path preserving directory structure
            output_dir = os.path.join(output_base, rel_dir)
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
            
            output_path = os.path.join(output_dir, f"{base_name}.gltf")
            
            if convert_single_file(xbg_file, output_path, args.lod, args.materials):
                success_count += 1
        
        print(f"\n{'='*60}")
        print(f"Batch conversion complete: {success_count}/{len(xbg_files)} files converted successfully")
        print(f"Output location: {output_base}")
    
    else:
        # Single file mode
        if not os.path.exists(input_path):
            print(f"Error: Input file '{input_path}' not found")
            return
        
        if not input_path.lower().endswith('.xbg'):
            print("Error: Input file must be an .xbg file")
            return
        
        output_path = args.output
        if not output_path:
            base_name = os.path.splitext(input_path)[0]
            output_path = f"{base_name}_lod{args.lod}.gltf"
        
        convert_single_file(input_path, output_path, args.lod, args.materials)


if __name__ == "__main__":
    main()