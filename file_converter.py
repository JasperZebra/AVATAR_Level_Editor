import multiprocessing
from multiprocessing import Pool, cpu_count

from cache_manager import get_cache_manager

import sys
import subprocess

import os
import subprocess
import shutil
import time
import glob
from pathlib import Path

# Prevent multiprocessing issues during cx_Freeze build
if __name__ == '__main__':
    multiprocessing.freeze_support()

# Also ensure it's called when module is imported in frozen state
if getattr(sys, 'frozen', False):
    try:
        multiprocessing.freeze_support()
    except:
        pass

class FileConverter:
    """Simplified file converter for FCBConverter tool only"""

    def __init__(self, tools_path="tools", game_mode="avatar"):
        """Initialize the converter with FCBConverter tool"""
        import sys
        import os
        
        # Write debug info to a file we can check
        debug_path = os.path.join(os.getcwd(), "converter_debug.txt")
        with open(debug_path, "w") as f:
            f.write(f"Frozen: {getattr(sys, 'frozen', False)}\n")
            f.write(f"Executable: {sys.executable}\n")
            f.write(f"Working dir: {os.getcwd()}\n")
            f.write(f"Tools path: {tools_path}\n")
            f.write(f"Tools exists: {os.path.exists(tools_path)}\n")
            
            # Check if we're running as exe and try executable directory
            if getattr(sys, 'frozen', False):
                exe_dir = os.path.dirname(sys.executable)
                f.write(f"Exe dir: {exe_dir}\n")
                exe_tools_path = os.path.join(exe_dir, "tools")
                f.write(f"Exe tools path: {exe_tools_path}\n")
                f.write(f"Exe tools exists: {os.path.exists(exe_tools_path)}\n")
                if os.path.exists(exe_tools_path):
                    f.write(f"Exe tools contents: {os.listdir(exe_tools_path)}\n")
            
            if os.path.exists(tools_path):
                f.write(f"Tools contents: {os.listdir(tools_path)}\n")
            
            # Try the converter in multiple locations
            converter_paths = [
                os.path.join(tools_path, "fcbconverter.exe"),
                os.path.join(tools_path, "FCBConverter.exe")
            ]
            
            if getattr(sys, 'frozen', False):
                exe_dir = os.path.dirname(sys.executable)
                converter_paths.extend([
                    os.path.join(exe_dir, "tools", "fcbconverter.exe"),
                    os.path.join(exe_dir, "tools", "FCBConverter.exe"),
                    os.path.join(exe_dir, "fcbconverter.exe"),
                    os.path.join(exe_dir, "FCBConverter.exe")
                ])
            
            for i, converter_path in enumerate(converter_paths):
                f.write(f"Converter path {i+1}: {converter_path}\n")
                f.write(f"Converter {i+1} exists: {os.path.exists(converter_path)}\n")
        
        # Store paths for the class
        self.tools_path = tools_path
        self.fcb_converter_path = os.path.join(tools_path, "fcbconverter.exe")  # Default
        
        # Check if any converter exists
        self.can_convert_fcb = False
        for converter_path in converter_paths:
            if os.path.exists(converter_path):
                self.fcb_converter_path = converter_path
                self.can_convert_fcb = True
                print(f"Found FCB converter at: {converter_path}")
                break
        
        self.conversion_enabled = self.can_convert_fcb
        self.game_mode = game_mode

    def _fcb_cmd(self, file_path):
        """Build FCBConverter command — always uses -fc2 flag"""
        return [self.fcb_converter_path, file_path, "-fc2"]

        if not self.can_convert_fcb:
            print(f"WARNING: fcbconverter.exe not found")
            print("File conversion is disabled.")
            print(f"Check converter_debug.txt for details")

    def _hidden_window_kwargs(self):
        """Return subprocess kwargs that suppress any console window on Windows."""
        kwargs = {}
        if sys.platform == 'win32':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            kwargs['startupinfo'] = si
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        return kwargs

    def _run_batch_fcbconverter(self, folder: str, filter_pattern: str, timeout: int = 300) -> subprocess.CompletedProcess:
        """Run FCBConverter in batch folder mode — always uses -fc2 flag."""
        cmd = [self.fcb_converter_path, f"-source={folder}", f"-filter={filter_pattern}", "-fc2"]
        print(f"Batch FCBConverter: {' '.join(cmd)}")
        return subprocess.run(cmd, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, **self._hidden_window_kwargs())

    def convert_data_fcb_files(self, worldsectors_path, progress_callback=None):
        """Convert .data.fcb files to .converted.xml format with caching and optional multiprocessing"""
        if not self.conversion_enabled:
            msg = "File conversion is disabled."
            print(msg)
            if progress_callback:
                try:
                    progress_callback(1.0, msg)
                except TypeError:
                    progress_callback(1.0)
            return 0, 0, []
        
        # Get cache manager
        cache = get_cache_manager()
        
        # Helper to log messages to both console and log box
        def log(message):
            print(message)  # Keep console output
            if progress_callback:
                try:
                    # Send message without updating progress bar
                    progress_callback(None, message)
                except:
                    pass
        
        log(f"\nScanning for .data.fcb files in: {worldsectors_path}")
        
        # Find all .data.fcb files (no recursive search)
        pattern = os.path.join(worldsectors_path, "*.data.fcb")
        data_fcb_files = glob.glob(pattern)
        
        log(f"Found {len(data_fcb_files)} .data.fcb files")
        
        if not data_fcb_files:
            if progress_callback:
                try:
                    progress_callback(1.0)
                except:
                    pass
            return 0, 0, []
        
        # ============ CACHE INTEGRATION HERE ============
        # Filter out files that have valid cached conversions
        files_to_convert = []
        cached_count = 0
        
        for fcb_file in data_fcb_files:
            xml_out = fcb_file + ".converted.xml"
            xml_exists = os.path.exists(xml_out)
            # Skip if XML already exists and is at least as new as the FCB —
            # covers the case where Save Level just wrote the FCB (cache miss)
            # but the XML was freshly produced by a prior FCBConverter run.
            xml_up_to_date = (xml_exists and
                              os.path.getmtime(xml_out) >= os.path.getmtime(fcb_file))
            if xml_up_to_date or (xml_exists and cache.is_fcb_conversion_cached(fcb_file)):
                log(f"Using cached conversion for: {os.path.basename(fcb_file)}")
                cached_count += 1
            else:
                files_to_convert.append(fcb_file)
        
        if cached_count > 0:
            log(f"Cache hit: {cached_count} files already converted (skipped)")
        
        if not files_to_convert:
            log(f"All {len(data_fcb_files)} FCB files already converted — using cached .converted.xml files (no reconversion needed)")
            if progress_callback:
                try:
                    progress_callback(1.0)
                except:
                    pass
            return 0, 0, []
        
        log(f"Converting {len(files_to_convert)} new/modified .data.fcb files, Please Wait.")
        # ============ END CACHE INTEGRATION ============

        success_count = 0
        error_count = 0
        errors = []

        # Per-file mode is much faster when only a few files need converting —
        # batch mode scans the entire directory (256+ files) even for a single change.
        USE_BATCH_THRESHOLD = 10
        if len(files_to_convert) <= USE_BATCH_THRESHOLD:
            log(f"Running FCBConverter per-file FCB → XML ({len(files_to_convert)} file(s))...")
            for fcb_file in files_to_convert:
                cmd = [self.fcb_converter_path, fcb_file, "-fc2"]
                log(f"  Converting: {os.path.basename(fcb_file)}")
                try:
                    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            timeout=60, **self._hidden_window_kwargs())
                    if result.returncode != 0:
                        err = result.stderr.decode(errors='replace').strip()
                        log(f"  [WARNING] FCBConverter returned code {result.returncode}")
                        if err:
                            log(err)
                except subprocess.TimeoutExpired:
                    log(f"  ERROR: FCBConverter timed out on {os.path.basename(fcb_file)}")
                except Exception as e:
                    log(f"  ERROR: {e}")
        else:
            batch_cmd_str = f"{self.fcb_converter_path} -source={worldsectors_path} -filter=*.data.fcb -fc2"
            log(f"Running FCBConverter batch FCB → XML (with -fc2 flag)...")
            log(f"Command: {batch_cmd_str}")
            try:
                result = self._run_batch_fcbconverter(worldsectors_path, "*.data.fcb")
                out = result.stdout.decode(errors='replace').strip()
                if out:
                    log(out)
                if result.returncode != 0:
                    err = result.stderr.decode(errors='replace').strip()
                    log(f"[WARNING] FCBConverter returned code {result.returncode}")
                    if err:
                        log(err)
            except subprocess.TimeoutExpired:
                log("ERROR: FCBConverter timed out during batch conversion")
            except Exception as e:
                log(f"ERROR: Batch conversion failed: {e}")

        # Count successes by checking which .converted.xml files now exist
        for fcb_file in files_to_convert:
            xml_out = fcb_file + ".converted.xml"
            if os.path.exists(xml_out):
                success_count += 1
                if cache:
                    cache.mark_fcb_converted(fcb_file)
            else:
                error_count += 1
                errors.append(f"No output: {os.path.basename(fcb_file)}")
                log(f"  [MISSING] No XML produced for: {os.path.basename(fcb_file)}")

        if progress_callback:
            try:
                progress_callback(1.0, f"Batch conversion done: {success_count} OK, {error_count} failed")
            except Exception:
                try:
                    progress_callback(1.0)
                except Exception:
                    pass

        log(f"FCB → XML batch done: {success_count} OK, {error_count} missing (total {len(data_fcb_files)} files, {cached_count} were cached)")

        # Save cache to disk after conversion
        cache._save_fcb_cache()

        return success_count, error_count, errors
        
    def _convert_sequential(self, files_to_convert, progress_callback, cache=None, log_callback=None):
        """Sequential conversion with caching support"""
        success_count = 0
        error_count = 0
        errors = []

        for i, fcb_file in enumerate(files_to_convert):
            try:
                msg = f"Converting ({i+1}/{len(files_to_convert)}): {os.path.basename(fcb_file)}"
                print(msg)
                if log_callback:
                    try:
                        log_callback(msg)
                    except Exception:
                        pass

                if self.convert_fcb_to_converted_xml(fcb_file):
                    success_count += 1
                    
                    # ============ CACHE INTEGRATION HERE ============
                    # Mark file as successfully converted in cache
                    if cache:
                        cache.mark_fcb_converted(fcb_file)
                    # ============ END CACHE INTEGRATION ============
                else:
                    error_count += 1
                    errors.append(f"Failed to convert: {os.path.basename(fcb_file)}")
                
                # Update progress
                if progress_callback:
                    progress = (i + 1) / len(files_to_convert)
                    progress_callback(progress)
                    
            except Exception as e:
                error_count += 1
                error_msg = f"Error converting {os.path.basename(fcb_file)}: {str(e)}"
                print(error_msg)
                errors.append(error_msg)
        
        if progress_callback:
            progress_callback(1.0)
        
        print(f"Data FCB conversion complete: {success_count} successful, {error_count} failed")
        return success_count, error_count, errors

    def _convert_multiprocessing(self, files_to_convert, progress_callback, cache=None, log_callback=None):
        """Parallel conversion using multiprocessing with caching and cancellation support"""
        from multiprocessing import Pool, cpu_count
        
        file_count = len(files_to_convert)
        
        # Determine optimal worker count (always at least 1)
        if file_count < 4:
            num_workers = max(1, min(file_count, cpu_count() - 2))
        else:
            num_workers = max(2, min(cpu_count() - 2, 8))
        
        chunksize = 1
        
        msg = f"Using multiprocessing with {num_workers} workers (processing {file_count} files)"
        print(msg)
        if progress_callback:
            try:
                progress_callback(None, msg)
            except:
                pass
        
        # Create conversion tasks with converter path
        tasks = [(fcb_file, self.fcb_converter_path, self.game_mode) for fcb_file in files_to_convert]
        
        success_count = 0
        error_count = 0
        errors = []
        
        # Track timing
        import time
        start_time = time.time()
        
        pool = None
        cancelled = False
        
        try:
            pool = Pool(processes=num_workers)
            
            for i, result in enumerate(pool.imap(_convert_fcb_worker, tasks, chunksize=chunksize)):
                # Create log message
                log_msg = f"({i+1}/{len(tasks)}) "

                if result.get('message'):
                    log_msg += result['message']
                else:
                    status = "Converted" if result['success'] else "Failed"
                    log_msg += f"{status}: {result['filename']}"
                print(log_msg)
                if log_callback:
                    try:
                        log_callback(log_msg)
                    except Exception:
                        pass
                
                # Count results
                if result['success']:
                    success_count += 1
                    
                    # ============ CACHE INTEGRATION HERE ============
                    # Mark file as successfully converted in cache
                    if cache and 'fcb_file' in result:
                        cache.mark_fcb_converted(result['fcb_file'])
                    # ============ END CACHE INTEGRATION ============
                else:
                    error_count += 1
                    if result.get('error'):
                        errors.append(f"{result['filename']}: {result['error']}")
                
                # Update progress with log message
                progress = (i + 1) / len(tasks)
                if progress_callback:
                    try:
                        progress_callback(progress, log_msg)
                    except (BrokenPipeError, ConnectionResetError, AttributeError, InterruptedError):
                        print("Cancellation detected - stopping conversion...")
                        cancelled = True
                        break
                    except TypeError:
                        try:
                            progress_callback(progress)
                        except (BrokenPipeError, ConnectionResetError, AttributeError, InterruptedError):
                            print("Cancellation detected - stopping conversion...")
                            cancelled = True
                            break
        
        except (BrokenPipeError, ConnectionResetError, EOFError) as e:
            print(f"Multiprocessing interrupted (user cancelled): {type(e).__name__}")
            cancelled = True
            
        except Exception as e:
            print(f"Multiprocessing error: {e}, falling back to sequential processing")
            if pool:
                try:
                    pool.terminate()
                    pool.join()
                except:
                    pass
            return self._convert_sequential(files_to_convert, progress_callback, cache)
        
        finally:
            # Always clean up the pool
            if pool:
                try:
                    # Always terminate (not close) to avoid pool.join() hanging on
                    # Windows after all work is done. Safe because all results have
                    # already been consumed from the imap iterator.
                    print("Terminating worker pool...")
                    pool.terminate()
                    pool.join()
                    print("Worker pool cleaned up")
                except Exception as e:
                    print(f"Error during pool cleanup: {e}")
        
        # Only try to send final progress if not cancelled
        if not cancelled and progress_callback:
            try:
                progress_callback(1.0, f"Conversion complete: {success_count} OK, {error_count} failed")
            except:
                pass
        
        elapsed_total = time.time() - start_time
        minutes = int(elapsed_total / 60)
        seconds = int(elapsed_total % 60)
        
        if cancelled:
            print(f"\nConversion cancelled: {success_count} completed before cancellation in {minutes}m {seconds}s")
        else:
            print(f"\nParallel conversion complete: {success_count} successful, {error_count} failed in {minutes}m {seconds}s")
        
        return success_count, error_count, errors

    def convert_fcb_to_converted_xml(self, fcb_path):
        """Optimized single file conversion with detailed diagnostics"""
        try:
            converted_xml_path = fcb_path + ".converted.xml"
            
            if os.path.exists(converted_xml_path):
                print(f"Converted XML file already exists: {os.path.basename(converted_xml_path)}")
                return True
            
            print(f"Converting FCB to converted XML: {os.path.basename(fcb_path)} -> {os.path.basename(converted_xml_path)}, Please Wait.")
            
            # Log the directory contents BEFORE conversion
            fcb_dir = os.path.dirname(fcb_path)
            print(f"Directory before conversion: {fcb_dir}")
            before_files = set(os.listdir(fcb_dir))
            print(f"Files before ({len(before_files)} total): {list(before_files)[:5]}...")  # Show first 5
            
            # Check if source file exists
            if not os.path.exists(fcb_path):
                print(f"ERROR: Source FCB file does not exist: {fcb_path}")
                return False
            
            fcb_size_before = os.path.getsize(fcb_path)
            print(f"Source FCB size before: {fcb_size_before} bytes")
            
            # Run the FCB converter — use 600s timeout (managers.fcb can be 1.3MB+)
            print(f"Running converter: {self.fcb_converter_path} {fcb_path} -fc2")
            process = subprocess.run(
                self._fcb_cmd(fcb_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=600,
                **self._hidden_window_kwargs()
            )
            
            print(f"Converter return code: {process.returncode}")
            if process.stdout:
                print(f"Converter stdout: {process.stdout}")
            if process.stderr:
                print(f"Converter stderr: {process.stderr}")
            
            # Log the directory contents AFTER conversion
            after_files = set(os.listdir(fcb_dir))
            new_files = after_files - before_files
            deleted_files = before_files - after_files
            
            print(f"Files after ({len(after_files)} total)")
            print(f"New files created: {new_files if new_files else 'NONE'}")
            print(f"Files deleted: {deleted_files if deleted_files else 'NONE'}")
            
            # Check if source FCB still exists
            if not os.path.exists(fcb_path):
                print(f"WARNING: Source FCB was DELETED by converter!")
            else:
                fcb_size_after = os.path.getsize(fcb_path)
                if fcb_size_after != fcb_size_before:
                    print(f"WARNING: Source FCB size changed: {fcb_size_before} -> {fcb_size_after}")
            
            # Check for expected output
            if os.path.exists(converted_xml_path):
                xml_size = os.path.getsize(converted_xml_path)
                print(f"SUCCESS: Found expected output: {os.path.basename(converted_xml_path)} ({xml_size} bytes)")
                return True
            else:
                print(f"ERROR: Expected output not found: {converted_xml_path}")
                
                # Check if ANY new XML files were created
                for new_file in new_files:
                    if new_file.endswith('.xml'):
                        print(f"Found unexpected XML file: {new_file}")
                
                return False
                
        except subprocess.TimeoutExpired:
            print(f"Conversion timed out for: {fcb_path}")
            return False
        except Exception as e:
            print(f"Error converting FCB file {fcb_path}: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    def convert_fcb_to_xml(self, fcb_path):
        """Convert main FCB file to XML using FCBConverter"""
        try:
            xml_path = fcb_path.replace(".fcb", ".xml")
            converted_xml_path = fcb_path + ".converted.xml"

            if not self.can_convert_fcb:
                print(f"FCBConverter not available")
                return False

            # Check if XML already exists
            if os.path.exists(xml_path):
                print(f"XML file already exists: {os.path.basename(xml_path)}")
                return True

            print(f"Converting FCB to XML: {os.path.basename(fcb_path)} -> {os.path.basename(xml_path)}, Please Wait.")

            # FCBConverter produces file.fcb.converted.xml — 600s for large files
            process = subprocess.run(
                self._fcb_cmd(fcb_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=600,
                **self._hidden_window_kwargs()
            )

            if process.returncode == 0 and os.path.exists(converted_xml_path):
                shutil.copy2(converted_xml_path, xml_path)
                xml_size = os.path.getsize(xml_path)
                try:
                    os.remove(converted_xml_path)
                except Exception:
                    pass
                print(f"Successfully converted: {os.path.basename(xml_path)} ({xml_size} bytes)")
                return True
            else:
                print(f"Conversion failed. Return code: {process.returncode}")
                if process.stderr:
                    print(f"Error: {process.stderr}")
                return False

        except subprocess.TimeoutExpired:
            print(f"Conversion timed out for: {fcb_path}")
            return False
        except Exception as e:
            print(f"Error converting FCB file {fcb_path}: {e}")
            return False

    def convert_converted_xml_back_to_fcb(self, original_fcb_path):
        """Convert .converted.xml back to FCB format"""
        try:
            converted_xml_path = original_fcb_path + ".converted.xml"
            
            if not os.path.exists(converted_xml_path):
                print(f"No .converted.xml file found: {os.path.basename(converted_xml_path)}")
                return False
            
            # Get expected output path
            fcb_dir = os.path.dirname(original_fcb_path)
            base_name = os.path.splitext(os.path.basename(original_fcb_path))[0]
            expected_new_fcb_path = os.path.join(fcb_dir, base_name + "_new.fcb")
            
            print(f"Converting XML back to FCB: {os.path.basename(converted_xml_path)} -> {os.path.basename(expected_new_fcb_path)}, Please Wait.")
            
            # Remove existing _new file if it exists
            if os.path.exists(expected_new_fcb_path):
                try:
                    os.remove(expected_new_fcb_path)
                    print(f"Removed existing: {os.path.basename(expected_new_fcb_path)}")
                except Exception as e:
                    print(f"Warning: Could not remove existing file: {e}")
            
            # Run the FCB converter
            process = subprocess.run(
                self._fcb_cmd(converted_xml_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
                **self._hidden_window_kwargs()
            )

            if os.path.exists(expected_new_fcb_path) and os.path.getsize(expected_new_fcb_path) > 0:
                fcb_size = os.path.getsize(expected_new_fcb_path)
                print(f"Successfully converted: {os.path.basename(expected_new_fcb_path)} ({fcb_size} bytes)")
                return expected_new_fcb_path
            else:
                print(f"Conversion failed. Return code: {process.returncode}")
                if process.stderr:
                    print(f"Error: {process.stderr}")
                if process.stdout:
                    print(f"Output: {process.stdout}")
                return False
                
        except subprocess.TimeoutExpired:
            print(f"Conversion timed out for: {converted_xml_path}")
            return False
        except Exception as e:
            print(f"Error converting XML back to FCB {converted_xml_path}: {e}")
            return False
        
    def delete_original_fcb_files(self, fcb_paths):
        """Delete original FCB files - NO BACKUPS"""
        deleted_files = []
        failed_files = []
        
        print(f"ðŸ—‘ Deleting {len(fcb_paths)} original FCB files, Please wait.")
        
        for fcb_path in fcb_paths:
            try:
                if not os.path.exists(fcb_path):
                    print(f"   File already missing: {os.path.basename(fcb_path)}")
                    continue
                
                # Get file info before deletion
                file_size = os.path.getsize(fcb_path)
                
                # Make file writable if needed
                try:
                    current_attrs = os.stat(fcb_path).st_mode
                    os.chmod(fcb_path, current_attrs | 0o200)  # Add write permission
                except Exception as chmod_error:
                    print(f"   Could not change permissions for {os.path.basename(fcb_path)}: {chmod_error}")
                
                # Delete the file
                os.remove(fcb_path)
                
                # Verify deletion
                if not os.path.exists(fcb_path):
                    deleted_files.append(fcb_path)
                    print(f"   Deleted: {os.path.basename(fcb_path)} ({file_size} bytes)")
                else:
                    failed_files.append(fcb_path)
                    print(f"   Deletion failed: {os.path.basename(fcb_path)}")
                    
            except PermissionError as perm_error:
                failed_files.append(fcb_path)
                print(f"   Permission denied: {os.path.basename(fcb_path)} - {perm_error}")
                print(f"   ðŸ’¡ Make sure the game is closed and no other programs are using the file")
                
            except Exception as e:
                failed_files.append(fcb_path)
                print(f"   Error deleting {os.path.basename(fcb_path)}: {e}")
        
        print(f"ðŸ“Š Deletion summary: {len(deleted_files)} deleted, {len(failed_files)} failed")
        
        return {
            'deleted_files': deleted_files,
            'failed_files': failed_files
        }

    def rename_new_fcb_files(self, new_fcb_paths, original_fcb_paths):
        """Rename _new.fcb files to original names - SIMPLE RENAME (no overwriting)"""
        renamed_files = []
        failed_renames = []
        
        print(f"ðŸ“ Renaming {len(new_fcb_paths)} _new.fcb files to original names, Please wait.")
        
        for new_fcb_path, original_fcb_path in zip(new_fcb_paths, original_fcb_paths):
            try:
                if not os.path.exists(new_fcb_path):
                    print(f"   New FCB file missing: {os.path.basename(new_fcb_path)}")
                    failed_renames.append((new_fcb_path, original_fcb_path))
                    continue
                
                # Check if target already exists (shouldn't happen if deletion worked)
                if os.path.exists(original_fcb_path):
                    print(f"   Target file still exists: {os.path.basename(original_fcb_path)}")
                    # Try to delete it one more time
                    try:
                        os.remove(original_fcb_path)
                        print(f"   ðŸ—‘ Removed remaining target file")
                    except Exception as e:
                        print(f"   Could not remove target file: {e}")
                        failed_renames.append((new_fcb_path, original_fcb_path))
                        continue
                
                # Get file info before rename
                new_file_size = os.path.getsize(new_fcb_path)
                
                # Perform the rename
                print(f"   ðŸ“ Renaming: {os.path.basename(new_fcb_path)} {os.path.basename(original_fcb_path)}")
                os.rename(new_fcb_path, original_fcb_path)
                
                # Verify the rename worked
                if os.path.exists(original_fcb_path) and not os.path.exists(new_fcb_path):
                    final_size = os.path.getsize(original_fcb_path)
                    print(f"   Rename successful: {os.path.basename(original_fcb_path)} ({final_size} bytes)")
                    renamed_files.append(original_fcb_path)
                else:
                    print(f"   Rename verification failed")
                    failed_renames.append((new_fcb_path, original_fcb_path))
                    
            except Exception as e:
                print(f"   Error renaming {os.path.basename(new_fcb_path)}: {e}")
                failed_renames.append((new_fcb_path, original_fcb_path))
        
        print(f"ðŸ“Š Rename summary: {len(renamed_files)} successful, {len(failed_renames)} failed")
        
        return {
            'renamed_files': renamed_files,
            'failed_renames': failed_renames
        }

    def cleanup_backup_files(self, backup_files, keep_backups=False):
        """Clean up backup files after successful conversion"""
        if keep_backups:
            print(f"ðŸ’¾ Keeping {len(backup_files)} backup files for safety")
            return
        
        print(f"Cleaning up {len(backup_files)} backup files, Please wait.")
        
        for backup_file in backup_files:
            try:
                if os.path.exists(backup_file):
                    os.remove(backup_file)
                    print(f"   ðŸ—‘ Removed backup: {os.path.basename(backup_file)}")
            except Exception as e:
                print(f"   Could not remove backup {os.path.basename(backup_file)}: {e}")

    def convert_all_worldsector_files_improved(self, worldsectors_path):
        """Convert all worldsector XML files back to FCB using FCBConverter batch mode."""
        try:
            print("")
            print("Starting WorldSector FCB conversion (batch mode), Please wait.")

            # Step 1: Find all .converted.xml files
            xml_pattern = os.path.join(worldsectors_path, "*.data.fcb.converted.xml")
            xml_files = glob.glob(xml_pattern)

            if not xml_files:
                print(f"No .converted.xml files found in {worldsectors_path}")
                return False

            print(f"Found {len(xml_files)} .converted.xml files to process")

            # Step 2: Delete original FCB files first
            print("")
            print("Phase 1: Deleting original FCB files, Please wait.")
            original_fcb_files = [f.replace(".converted.xml", "") for f in xml_files]
            deleted_files = []
            failed_deletions = []

            for fcb_file in original_fcb_files:
                try:
                    if os.path.exists(fcb_file):
                        file_size = os.path.getsize(fcb_file)
                        os.remove(fcb_file)
                        if not os.path.exists(fcb_file):
                            deleted_files.append(fcb_file)
                            print(f"   Deleted: {os.path.basename(fcb_file)} ({file_size} bytes)")
                        else:
                            failed_deletions.append(fcb_file)
                            print(f"   Failed to delete: {os.path.basename(fcb_file)}")
                    else:
                        print(f"   File doesn't exist: {os.path.basename(fcb_file)}")
                except Exception as e:
                    failed_deletions.append(fcb_file)
                    print(f"   Error deleting {os.path.basename(fcb_file)}: {e}")

            if failed_deletions:
                print(f"Warning: {len(failed_deletions)} files could not be deleted")
                print("Make sure the game is closed and try again")

            # Step 3: Batch convert all XMLs to _new.fcb in one FCBConverter call
            print("")
            print("Phase 2: Converting XML files to FCB (batch), Please wait.")
            try:
                result = self._run_batch_fcbconverter(worldsectors_path, "*.data.fcb.converted.xml")
                out = result.stdout.decode(errors="replace").strip()
                if out:
                    print(out)
                if result.returncode != 0:
                    err = result.stderr.decode(errors="replace").strip()
                    print(f"[WARNING] FCBConverter returned code {result.returncode}")
                    if err:
                        print(err)
            except subprocess.TimeoutExpired:
                print("ERROR: FCBConverter timed out during batch XML -> FCB conversion")
                return False
            except Exception as e:
                print(f"ERROR: Batch XML -> FCB conversion failed: {e}")
                return False

            # Step 4: Rename all _new.fcb files to final names
            print("")
            print("Phase 3: Renaming _new.fcb files, Please wait.")
            new_fcb_files = glob.glob(os.path.join(worldsectors_path, "*.data_new.fcb"))
            print(f"Conversion Results: {len(new_fcb_files)}/{len(xml_files)} _new.fcb files produced")

            if not new_fcb_files:
                print("No FCB files were successfully converted")
                return False

            renamed_files = []
            failed_renames = []

            for new_file in new_fcb_files:
                original_file = new_file.replace("_new.fcb", ".fcb")
                try:
                    if os.path.exists(new_file):
                        if os.path.exists(original_file):
                            os.remove(original_file)
                        os.rename(new_file, original_file)
                        if os.path.exists(original_file) and not os.path.exists(new_file):
                            renamed_files.append(original_file)
                            final_size = os.path.getsize(original_file)
                            print(f"   Renamed: {os.path.basename(new_file)} -> {os.path.basename(original_file)} ({final_size} bytes)")
                        else:
                            failed_renames.append((new_file, original_file))
                            print(f"   Rename failed: {os.path.basename(new_file)}")
                    else:
                        failed_renames.append((new_file, original_file))
                        print(f"   New file missing: {os.path.basename(new_file)}")
                except Exception as e:
                    failed_renames.append((new_file, original_file))
                    print(f"   Error renaming {os.path.basename(new_file)}: {e}")

            # Step 5: Clean up XML files
            print("")
            print("Phase 4: Cleanup, Please wait.")
            if len(renamed_files) == len(xml_files) and not failed_renames:
                print("Removing .converted.xml files, Please wait.")
                for xml_file in xml_files:
                    try:
                        os.remove(xml_file)
                        print(f"   Removed: {os.path.basename(xml_file)}")
                    except Exception as e:
                        print(f"   Could not remove {os.path.basename(xml_file)}: {e}")
            else:
                print("Partial success - keeping XML files for troubleshooting")

            # Step 6: Final summary
            print("")
            print("FINAL RESULTS:")
            print(f"   Successfully converted: {len(renamed_files)}/{len(xml_files)} files")
            print(f"   Failed deletions: {len(failed_deletions)}")
            print(f"   Failed renames: {len(failed_renames)}")

            if len(renamed_files) == len(xml_files):
                print("ALL FILES SUCCESSFULLY CONVERTED!")
                print("Your changes should now appear in the game")
                return True
            else:
                print("PARTIAL SUCCESS - some files may need manual intervention")
                return len(renamed_files) > 0

        except Exception as e:
            print(f"Conversion process failed: {e}")
            import traceback
            traceback.print_exc()
            return False


    def restore_from_backups(self, backup_files):
        """Restore original files from backups if something goes wrong"""
        print(f"ðŸ”„ Restoring {len(backup_files)} files from backups, Please wait.")
        
        restored_count = 0
        for backup_file in backup_files:
            try:
                if not os.path.exists(backup_file):
                    print(f"   Backup missing: {os.path.basename(backup_file)}")
                    continue
                
                # Get original file path
                if backup_file.endswith('.pre_delete_backup'):
                    original_file = backup_file.replace('.pre_delete_backup', '')
                else:
                    original_file = backup_file.replace('.backup', '')
                
                # Restore the file
                shutil.copy2(backup_file, original_file)
                print(f"   Restored: {os.path.basename(original_file)}")
                restored_count += 1
                
            except Exception as e:
                print(f"   Error restoring {os.path.basename(backup_file)}: {e}")
        
        print(f"ðŸ“Š Restored {restored_count}/{len(backup_files)} files")
        return restored_count

    def get_data_file_info(self, worldsectors_path):
        """Get information about .data files in worldsectors folder"""
        try:
            # Find all .data.fcb files
            fcb_pattern = os.path.join(worldsectors_path, "*.data.fcb")
            fcb_files = glob.glob(fcb_pattern)

            # Find converted .xml files for data.fcb
            converted_pattern = os.path.join(worldsectors_path, "*.data.fcb.converted.xml")
            converted_files = glob.glob(converted_pattern)

            # Count files that still need conversion
            needs_conversion = 0
            for fcb_file in fcb_files:
                expected_xml = fcb_file + ".converted.xml"
                if not os.path.exists(expected_xml):
                    needs_conversion += 1

            return {
                'total_fcb_files': len(fcb_files),
                'total_xml_files': len(converted_files),
                'needs_conversion': needs_conversion,
                'fcb_files': fcb_files,
                'xml_files': converted_files
            }

        except Exception as e:
            print(f"Error getting data file info: {str(e)}")
            return {
                'total_fcb_files': 0,
                'total_xml_files': 0,
                'needs_conversion': 0,
                'fcb_files': [],
                'xml_files': []
            }
        
    def convert_folder(self, folder_path, progress_callback=None, log_callback=None):
        """Convert main level FCB files to XML format.

        Walks folder_path recursively to find main FCB files, runs targeted batch
        FCBConverter calls (one per pattern) so library files are never included,
        then copies .fcb.converted.xml → .xml where .xml is missing.

        Never overwrites an existing .xml (treated as the user's working copy).
        """
        if not self.can_convert_fcb:
            if progress_callback:
                progress_callback(1.0)
            return 0, 0, []

        # Each entry is (substring_to_match, batch_filter_glob).
        # The glob must be specific enough to exclude entitylibrary.fcb which
        # crashes FCBConverter. entitylibrary_full.fcb is safe to include.
        target_patterns = [
            ('.managers.fcb',        '*.managers.fcb'),
            ('mapsdata.fcb',         '*.mapsdata.fcb'),
            ('.omnis.fcb',           '*.omnis.fcb'),
            ('sectorsdep.fcb',       '*.sectorsdep.fcb'),
            ('entitylibrary_full.fcb', '*entitylibrary_full.fcb'),
        ]

        print("Looking for main FCB files to convert, Please wait.")

        # Walk the whole folder tree to find all main FCB files
        all_main_fcbs = []
        for root, _, files in os.walk(folder_path):
            for filename in files:
                if not filename.endswith('.fcb') or filename.endswith('_new.fcb'):
                    continue
                for pat, _ in target_patterns:
                    if pat in filename:
                        all_main_fcbs.append(os.path.join(root, filename))
                        break

        if not all_main_fcbs:
            if progress_callback:
                progress_callback(1.0)
            return 0, 0, []

        # Run one targeted batch call per pattern — only for patterns that have
        # at least one unconverted file. This avoids hitting entitylibrary.fcb.
        for pat, glob_filter in target_patterns:
            needs = [
                f for f in all_main_fcbs
                if pat in os.path.basename(f)
                and not os.path.exists(f + '.converted.xml')
                and not os.path.exists(f.replace('.fcb', '.xml'))
            ]
            if not needs:
                continue
            print(f"  Batch converting {glob_filter} files in {os.path.basename(folder_path)}...")
            try:
                result = self._run_batch_fcbconverter(folder_path, glob_filter, timeout=300)
                if result.returncode != 0:
                    err = result.stderr.decode(errors='replace').strip()
                    print(f"  [WARNING] FCBConverter returned {result.returncode}: {err}")
            except subprocess.TimeoutExpired:
                print(f"  ERROR: FCBConverter timed out ({glob_filter})")
            except Exception as e:
                print(f"  ERROR: Batch conversion failed ({glob_filter}): {e}")

        # Copy .fcb.converted.xml → .xml only when .xml is missing
        success_count = 0
        error_count = 0
        for fcb_path in all_main_fcbs:
            converted = fcb_path + '.converted.xml'
            xml_path  = fcb_path.replace('.fcb', '.xml')
            if os.path.exists(xml_path):
                success_count += 1  # existing .xml — leave it alone
            elif os.path.exists(converted):
                try:
                    shutil.copy2(converted, xml_path)
                    success_count += 1
                    try:
                        os.remove(converted)
                    except Exception:
                        pass
                except Exception as e:
                    error_count += 1
                    print(f"  Error copying {os.path.basename(fcb_path)}: {e}")
            else:
                error_count += 1

        if progress_callback:
            progress_callback(1.0)

        return success_count, error_count, []

    def convert_folder_batch(self, folder_path):
        """Convert all FCB files in a folder using a single FCBConverter batch call.

        Used during patch-folder scan to convert main level files (omnis, mapsdata,
        managers, sectorsdep) without spawning one subprocess per file.

        After conversion, renames <name>.fcb.converted.xml → <name>.xml for the main
        level files (anything that does NOT contain '.data.fcb' in its name), leaving
        worldsector / landmark .data.fcb.converted.xml files untouched.

        Returns (success_count, error_count, errors).
        """
        if not self.can_convert_fcb:
            return 0, 0, []

        if not os.path.isdir(folder_path):
            return 0, 0, []

        # Find all main FCB files in this folder
        main_patterns = ['.managers.fcb', 'mapsdata.fcb', '.omnis.fcb',
                         'sectorsdep.fcb', 'entitylibrary_full.fcb']
        all_main_fcbs = []
        for fname in os.listdir(folder_path):
            if not fname.endswith('.fcb') or fname.endswith('_new.fcb'):
                continue
            for pat in main_patterns:
                if pat in fname:
                    all_main_fcbs.append(fname)
                    break

        if not all_main_fcbs:
            return 0, 0, []

        # Only run FCBConverter for files where NEITHER output exists yet
        needs_convert = []
        for fname in all_main_fcbs:
            converted = os.path.join(folder_path, fname + ".converted.xml")
            xml_out   = os.path.join(folder_path, fname.replace('.fcb', '.xml'))
            if not os.path.exists(converted) and not os.path.exists(xml_out):
                needs_convert.append(fname)

        if needs_convert:
            print(f"  Batch converting {len(needs_convert)} main FCB file(s) in "
                  f"{os.path.basename(folder_path)} via FCBConverter batch mode...")
            try:
                result = self._run_batch_fcbconverter(folder_path, "*.fcb", timeout=120)
                if result.returncode != 0:
                    err = result.stderr.decode(errors='replace').strip()
                    print(f"  [WARNING] FCBConverter returned {result.returncode}: {err}")
            except subprocess.TimeoutExpired:
                print("  ERROR: FCBConverter timed out during batch conversion")
            except Exception as e:
                print(f"  ERROR: Batch conversion failed: {e}")

        # Copy .fcb.converted.xml → .xml only when .xml is missing
        success_count = 0
        error_count = 0
        for fname in all_main_fcbs:
            converted = os.path.join(folder_path, fname + ".converted.xml")
            xml_out   = os.path.join(folder_path, fname.replace('.fcb', '.xml'))
            if os.path.exists(xml_out):
                success_count += 1  # already have .xml — leave it alone
            elif os.path.exists(converted):
                try:
                    shutil.copy2(converted, xml_out)
                    success_count += 1
                    try:
                        os.remove(converted)
                    except Exception:
                        pass
                except Exception as e:
                    error_count += 1
                    print(f"  Error copying {fname}: {e}")
            else:
                error_count += 1
                print(f"  No output for: {fname}")

        return success_count, error_count, []

    def convert_xml_to_fcb(self, xml_path):
        """Convert main XML file back to FCB using FCBConverter"""
        try:
            fcb_path = xml_path.replace(".xml", ".fcb")
            converted_xml_path = fcb_path + ".converted.xml"
            fcb_dir = os.path.dirname(fcb_path)
            base_name = os.path.splitext(os.path.basename(fcb_path))[0]
            new_fcb_path = os.path.join(fcb_dir, base_name + "_new.fcb")

            # Copy xml to the .converted.xml name FCBConverter expects
            shutil.copy2(xml_path, converted_xml_path)
            print(f"Converting: {os.path.basename(xml_path)} → FCB (using -fc2 flag)")

            # Remove any existing _new.fcb
            if os.path.exists(new_fcb_path):
                os.remove(new_fcb_path)

            process = subprocess.run(
                self._fcb_cmd(converted_xml_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
                **self._hidden_window_kwargs()
            )

            # Clean up temp file regardless of outcome
            try:
                os.remove(converted_xml_path)
            except Exception:
                pass

            if process.returncode == 0 and os.path.exists(new_fcb_path):
                if os.path.exists(fcb_path):
                    os.remove(fcb_path)
                os.rename(new_fcb_path, fcb_path)
                return True
            else:
                print(f"Conversion failed. Return code: {process.returncode}")
                if process.stderr:
                    print(f"Error: {process.stderr}")
                return False

        except Exception as e:
            print(f"Error converting XML to FCB {xml_path}: {e}")
            return False
        
def _convert_fcb_worker(task):
    """Worker function for parallel FCB conversion - runs in separate process"""
    fcb_path, converter_path, game_mode = task
    
    result = {
        'filename': os.path.basename(fcb_path),
        'success': False,
        'error': None,
        'message': None
    }
    
    try:
        converted_xml_path = fcb_path + ".converted.xml"
        
        # Check if already exists
        if os.path.exists(converted_xml_path):
            result['success'] = True
            result['message'] = f"Already converted: {result['filename']}"
            return result
        
        # Get directory for checking new files
        fcb_dir = os.path.dirname(fcb_path)
        before_files = set(os.listdir(fcb_dir))
        
        # Create startup info to hide console window
        startupinfo = None
        if sys.platform == 'win32':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        
        # Run the FCB converter with hidden window — always use -fc2
        cmd = [converter_path, fcb_path, "-fc2"]
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        if process.returncode == 0:
            # Check what happened
            after_files = set(os.listdir(fcb_dir))
            new_files = after_files - before_files
            deleted_files = before_files - after_files
            
            if os.path.exists(converted_xml_path):
                xml_size = os.path.getsize(converted_xml_path)
                result['success'] = True
                result['message'] = f"Converted: {result['filename']} ({xml_size} bytes)"
            else:
                # File was converted but output missing
                result['error'] = f"Output missing. New: {new_files}, Deleted: {deleted_files}"
                result['message'] = f"Failed: {result['filename']}"
        else:
            result['error'] = f"Return code: {process.returncode}"
            if process.stderr:
                result['error'] += f" - {process.stderr[:100]}"
            result['message'] = f"Failed: {result['filename']}"
    
    except subprocess.TimeoutExpired:
        result['error'] = "Conversion timed out"
        result['message'] = f"Timeout: {result['filename']}"
    except Exception as e:
        result['error'] = str(e)
        result['message'] = f"Error: {result['filename']}"
    
    return result