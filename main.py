import sys
import os
import multiprocessing
import faulthandler
import traceback
import datetime

# CRITICAL: Import frozen exe fixes FIRST (before any other imports)
try:
    import fix_frozen_paths
except ImportError:
    # If not found, we're probably running from source - that's fine
    pass

# ============================================================================
# CRASH LOGGING — writes to crash_log.txt next to the exe (or CWD in dev)
# Catches BOTH Python exceptions (sys.excepthook) AND C-level crashes
# (segfaults, access violations) via faulthandler.
# ============================================================================
def _get_log_path():
    try:
        if getattr(sys, 'frozen', False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        base = os.getcwd()
    return os.path.join(base, 'crash_log.txt')

CRASH_LOG_PATH = _get_log_path()

def _write_crash_log(text):
    """Append text to crash_log.txt, flushing immediately."""
    try:
        with open(CRASH_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(text)
            f.flush()
    except Exception:
        pass  # If we can't write the log there's nothing more we can do

def _excepthook(exc_type, exc_value, exc_tb):
    """Global Python exception handler — logs to file then shows a message box."""
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = [
        f"\n{'='*70}\n",
        f"CRASH  {ts}\n",
        f"{'='*70}\n",
        ''.join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        f"{'='*70}\n",
    ]
    _write_crash_log(''.join(lines))
    # Try to show a Qt message box so the user knows to check the log
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app:
            msg = QMessageBox()
            msg.setWindowTitle("Avatar Level Editor — Crash")
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setText(
                f"The editor crashed with an unhandled error.\n\n"
                f"Details have been written to:\n{CRASH_LOG_PATH}\n\n"
                f"{exc_type.__name__}: {exc_value}"
            )
            msg.exec()
    except Exception:
        pass
    # Call the original hook so Python still prints to stderr (dev mode)
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _excepthook

# Enable faulthandler: logs C-level crashes (segfaults, access violations)
# to the same crash_log.txt file.  This runs even when Win32GUI suppresses stdout.
try:
    _crash_log_file = open(CRASH_LOG_PATH, 'a', encoding='utf-8')
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    _crash_log_file.write(f"\n{'='*70}\nSESSION START  {ts}\nLOG: {CRASH_LOG_PATH}\n{'='*70}\n")
    _crash_log_file.flush()
    faulthandler.enable(file=_crash_log_file, all_threads=True)
    # Keep the file open for the lifetime of the process
except Exception:
    pass

# CRITICAL: Must be first
if __name__ == "__main__":
    multiprocessing.freeze_support()

def main():
    """Main application entry point with game selection"""

    # Prevent launching GUI inside worker processes
    if multiprocessing.current_process().name != "MainProcess":
        return

    # 👉 Move GUI imports here so workers NEVER import them
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    from game_selector import GameSelectorDialog
    from simplified_map_editor import SimplifiedMapEditor

    app = QApplication(sys.argv)

    # Run diagnostics if running as frozen exe
    try:
        if fix_frozen_paths.IS_FROZEN:
            fix_frozen_paths.run_frozen_diagnostics()
    except NameError:
        # fix_frozen_paths not imported - running from source
        pass

    default_icon_path = os.path.join("icon", "avatar_icon.ico")
    if os.path.exists(default_icon_path):
        app.setWindowIcon(QIcon(default_icon_path))

    selector = GameSelectorDialog()
    result = selector.exec()

    if result == GameSelectorDialog.DialogCode.Accepted:
        selected_game = selector.get_selected_game()

        if selected_game:
            print(f"Selected game: {selected_game}")

            if "avatar" in selected_game.lower():
                icon_file = "avatar_icon.ico"
            elif any(x in selected_game.lower() for x in ["fc2", "farcry"]):
                icon_file = "fc2_icon.ico"
            else:
                icon_file = "avatar_icon.ico"

            icon_path = os.path.join("icon", icon_file)
            game_icon = QIcon(icon_path) if os.path.exists(icon_path) else None

            editor = SimplifiedMapEditor(game_mode=selected_game)

            if game_icon:
                editor.setWindowIcon(game_icon)
                app.setWindowIcon(game_icon)

            editor.show()
            sys.exit(app.exec())
        else:
            print("No game selected, exiting")
            sys.exit(0)
    else:
        print("User cancelled selection, exiting")
        sys.exit(0)

# CRITICAL: GUI + Qt imports MUST NOT exist at top level
if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()  