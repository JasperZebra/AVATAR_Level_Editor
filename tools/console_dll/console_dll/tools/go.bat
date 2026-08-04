@echo off
REM go.bat - edit avatar_console.c, run this, play.
REM
REM One entry point for working on the console DLL alone: build, prove the DLL
REM that came out is actually newer than the source, then inject it.
REM
REM   go            build + check + inject
REM   go build      build + check, do not inject
REM   go inject     inject whatever is already built (no rebuild)
REM
REM The check exists because a silent failure has cost this project two
REM debugging rounds: the link failed with LNK1104 while the game had the DLL
REM loaded, nobody noticed, and the next hour was spent testing a stale binary.
REM A build that does not produce a newer DLL is a FAILED build, and this says so.

setlocal
cd /d "%~dp0"

if /i "%~1"=="inject" goto :inject

REM Explicit path, not a bare name: depending on how the shell was launched,
REM "." is not always on PATH and a bare `call build.bat` fails with
REM "is not recognized" - which would then be misreported as a build failure.
call "%~dp0build.bat"
if errorlevel 1 (
    echo.
    echo ============================================================
    echo BUILD FAILED.
    echo.
    echo If the error was LNK1104 "cannot open avatar_console.dll",
    echo the game still has it loaded. Press End in-game to unload,
    echo then run this again. Nothing was rebuilt - do NOT test.
    echo ============================================================
    exit /b 1
)

REM Freshness gate: the DLL must be newer than the source it came from.
REM buildstatus.py lives in the dev tree, NOT in this folder - a shared copy of
REM console_dll on its own will not have it, and that is fine.  The build above
REM already failed loudly if it failed; this is an extra check for us, not a
REM requirement for anyone building from a shared folder.
if exist "%~dp0..\scripts\buildstatus.py" (
    python "%~dp0..\scripts\buildstatus.py"
)

if /i "%~1"=="build" (
    echo.
    echo Built only, not injected. Run "go inject" when the game is up.
    exit /b 0
)

:inject
echo.
echo ---- injecting ----
python "%~dp0inject.py"
if errorlevel 1 (
    echo.
    echo Inject failed. Is Avatar.exe running?
    exit /b 1
)
echo.
echo Done. F9 opens the console, End unloads.
endlocal
