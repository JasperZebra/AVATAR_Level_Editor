@echo off
echo ================================================
echo Building Avatar Level Editor - Both Architectures
echo ================================================

REM Change to this script's directory
cd /d "%~dp0"

REM Clean previous builds
if exist "build" (
    echo Cleaning previous builds...
    rmdir /s /q build
    echo Previous builds cleaned.
    echo.
)

echo.
echo [1/4] Building 64-bit version...
echo ------------------------------------------------
python setup.py build
if errorlevel 1 (
    echo ERROR: 64-bit build failed!
    pause
    exit /b 1
)

echo.
echo [2/4] 64-bit build complete!
echo.

echo [3/4] Building 32-bit version...
echo ------------------------------------------------
REM Requires a 32-bit Python with PyQt5 + numpy<2.0 installed.
REM Install its deps first with:  py -3-32 -m pip install -r requirements.txt
py -3-32 setup.py build
if errorlevel 1 (
    echo ERROR: 32-bit build failed!
    echo Make sure 32-bit Python is installed and has the deps:
    echo   py -3-32 -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo.
echo [4/4] 32-bit build complete!
echo.

echo ================================================
echo Both builds completed successfully!
echo ================================================
echo.
echo 64-bit version: build\Avatar_Level_Editor_x64\
echo 32-bit version: build\Avatar_Level_Editor_x86\
echo.
pause
