@echo off
REM Install the console mod so the GAME loads it, with no injector and no
REM scripts at run time.
REM
REM What this copies and why it is enough:
REM   dinput8.dll  ->  <install>\bin\dinput8.dll
REM
REM That single file IS the mod. Dunia.dll statically imports DirectInput8Create
REM from DINPUT8.dll (dumpbin /imports says so - one entry), dinput8.dll is not a
REM KnownDLL, and the application directory - the folder Avatar.exe lives in - is
REM searched before System32. So our copy is found first, the loader maps it, its
REM DllMain starts the mod, and every one of the six dinput8 exports is handed
REM straight through to the real C:\Windows\SysWOW64\dinput8.dll. Nothing else is
REM needed: the Tab-completion list, the multiplayer spawn points and the command
REM tables are all compiled into the binary.
REM
REM Uninstall: delete <install>\bin\dinput8.dll. That is the whole of it - no
REM registry, no patched game file, nothing else is written except the log.

setlocal
cd /d "%~dp0"

REM The install path. Override on the command line for a different drive:
REM     install.bat "E:\Games\Avatar The Game"
set "GAME=%~1"
if "%GAME%"=="" set "GAME=D:\Games\Avatar The Game"
set "BIN=%GAME%\bin"

if not exist "%BIN%\Avatar.exe" (
    echo ERROR: no Avatar.exe in "%BIN%".
    echo Pass the install folder as an argument:
    echo     install.bat "E:\Games\Avatar The Game"
    exit /b 1
)
if not exist "%~dp0dinput8.dll" (
    echo ERROR: dinput8.dll is not here - run build.bat first.
    exit /b 1
)

REM REFUSE WHILE THE GAME IS UP. The copy would fail with a sharing violation
REM anyway, but it fails PER FILE and would leave a half-done install; and the
REM error Windows prints for it reads like a permissions problem, which sends
REM people looking in the wrong place. Say what it actually is.
tasklist /FI "IMAGENAME eq Avatar.exe" 2>nul | find /i "Avatar.exe" >nul
if not errorlevel 1 (
    echo ERROR: Avatar.exe is running. Close the game first - a loaded DLL
    echo        cannot be overwritten.
    exit /b 1
)

copy /y "%~dp0dinput8.dll" "%BIN%\dinput8.dll" >nul
if errorlevel 1 (
    echo ERROR: could not write "%BIN%\dinput8.dll".
    exit /b 1
)

echo INSTALLED: %BIN%\dinput8.dll
echo.
echo Start the game normally. The mod arms itself as soon as a level is loaded
echo - not at the main menu, because the engine does not build the console
echo object until then. Press F9 for the console.
echo.
echo Log: %BIN%\avatar_console_dll.log
echo      (the DLL writes next to itself, so everything it reads or writes now
echo       lives in bin\ - including avatar_cmds.txt, the file F11 runs)
echo.
echo Uninstall: del "%BIN%\dinput8.dll"
endlocal
