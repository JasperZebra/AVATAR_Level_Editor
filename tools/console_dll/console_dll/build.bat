@echo off
REM Build avatar_console.dll as 32-bit, to match Avatar.exe (WOW64).
REM
REM NOTE: use vcvarsall.bat x86, NOT vcvars32.bat.  On this machine vcvars32
REM fails ("vswhere.exe is not recognized") and leaves an x64 environment,
REM which then rejects __thiscall with a wall of syntax errors.  Check the
REM banner says "for x86".

setlocal
REM Find vcvarsall.bat rather than hardcoding one install.  This used to name a
REM single path, which built fine here and failed for anyone with a different
REM edition, year or drive - the first thing a person trying to build this from
REM a shared copy would hit.  Try vswhere (the supported way), then the common
REM install locations for 2022 and 2019, Community/Professional/Enterprise/
REM BuildTools.
REM -prerelease IS REQUIRED, and leaving it off is a silent failure.  vswhere
REM does not report Insiders / Preview installs at all without it, so on a
REM machine whose ONLY toolchain is one of those - e.g. "Visual Studio 18
REM Insiders" - the query below returns nothing, every hardcoded fallback path
REM misses too (they enumerate 2022/2019 and the four retail editions), and the
REM build stops with "could not find vcvarsall.bat" while a perfectly good cl.exe
REM sits on disk.  Measured here: without -prerelease the query printed nothing;
REM with it, "C:\Program Files\Microsoft Visual Studio\18\Insiders".
REM Retail installs are still preferred - vswhere sorts them ahead of prerelease
REM for the same -latest query - so this only ever ADDS a candidate.
set "VCVARSALL="
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if exist "%VSWHERE%" (
    for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -prerelease -products * ^
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 ^
        -property installationPath 2^>nul`) do (
        if exist "%%i\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARSALL=%%i\VC\Auxiliary\Build\vcvarsall.bat"
    )
)
REM The fallbacks assume the retail "<year>\<edition>" layout.  Newer installs
REM use a version number and a channel name instead ("18\Insiders"), so those are
REM listed too - the loop is cheap and a missing compiler is not.
if not defined VCVARSALL (
    for %%y in (2022 2019 18 19) do for %%e in (BuildTools Community Professional Enterprise Insiders Preview) do (
        if not defined VCVARSALL if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\%%y\%%e\VC\Auxiliary\Build\vcvarsall.bat" ^
            set "VCVARSALL=%ProgramFiles(x86)%\Microsoft Visual Studio\%%y\%%e\VC\Auxiliary\Build\vcvarsall.bat"
        if not defined VCVARSALL if exist "%ProgramFiles%\Microsoft Visual Studio\%%y\%%e\VC\Auxiliary\Build\vcvarsall.bat" ^
            set "VCVARSALL=%ProgramFiles%\Microsoft Visual Studio\%%y\%%e\VC\Auxiliary\Build\vcvarsall.bat"
    )
)
if not defined VCVARSALL (
    echo ERROR: could not find vcvarsall.bat.
    echo Install "Visual Studio Build Tools" with the C++ x86/x64 workload,
    echo or set VCVARSALL yourself at the top of this file.
    exit /b 1
)
REM x86, NOT vcvars32.bat - on some installs vcvars32 fails with
REM "vswhere.exe is not recognized" and leaves an x64 environment, which then
REM rejects __thiscall with a wall of syntax errors.  The banner must say x86.
call "%VCVARSALL%" x86 >nul 2>&1

cd /d "%~dp0"

REM Build outputs live in dist\ - the root holds only what it takes to BUILD:
REM the source, the two generated headers it #includes, the completion-table
REM check the build gates on, and this file.
if not exist "%~dp0dist" mkdir "%~dp0dist"


REM Fail BEFORE compiling if the Tab-completion table has drifted from the
REM dispatch.  A command that is dispatched but in no completion list cannot be
REM Tab-completed however many times you press it; one that is completable but
REM not dispatched looks broken when you run it.  Both had already happened -
REM eleven of the former, plus `drivecam` and `grab` of the latter - and nothing
REM noticed, because the two lists are maintained by hand and never compared.
REM Skipped silently when python is not on PATH: this must never stop someone
REM building from a shared copy.
where python >nul 2>&1
if not errorlevel 1 (
    python "%~dp0check_cmds.py"
    if errorlevel 1 (
        echo.
        echo BUILD ABORTED: the command tables disagree - see above.
        echo Nothing was compiled.
        exit /b 1
    )
)

REM /TP = compile as C++.  __thiscall is a C++ calling convention; in C mode
REM MSVC rejects the function-pointer typedefs outright.
REM
REM /BASE:0x2A000000 - stay away from 0x10000000.  That is BOTH the MSVC default
REM image base for a DLL and Dunia.dll's preferred base, and as a proxy we are
REM mapped during Dunia's own import resolution.  Dunia is mapped first so it
REM keeps 0x10000000 in practice, but the day that stops being true every
REM hardcoded address moves, g_rebase has to correct it, and the decompile
REM addresses stop matching the live process 1:1 - which is the difference
REM between reading the log and re-deriving everything.  Costs nothing to avoid.
REM (With ASLR on, the linker's /DYNAMICBASE default relocates us anyway; this is
REM for the machines that have ASLR turned off.)
REM /IGNORE:4104 - "export of symbol 'DllCanUnloadNow' should be PRIVATE", once
REM for each of the four COM entry points the dinput8 proxy forwards.  Explained
REM in full next to the /export pragmas in avatar_console.c: the advice is about
REM the import library, which the del below throws away anyway, and taking it
REM costs the explicit export ordinals, which are the part that has to be right.
REM
REM NOTHING MAY GO BETWEEN THE TWO LINES BELOW. The first ends in ^, so whatever
REM follows is part of the same command - a REM put there was handed to cl as a
REM list of source file names, and cl compiled the real one, failed on the words,
REM and STILL left a DLL behind. A comment that breaks the build while the build
REM says BUILT is the worst kind.
cl /nologo /TP /LD /O2 /W3 /D_CRT_SECURE_NO_WARNINGS avatar_console.c ^
   /link /OUT:dist\avatar_console.dll /BASE:0x2A000000 /IGNORE:4104 ^
   /MAP:dist\avatar_console.map ^
   kernel32.lib user32.lib gdi32.lib
if errorlevel 1 (
    echo.
    echo BUILD FAILED
    exit /b 1
)
del /q avatar_console.obj avatar_console.exp avatar_console.lib 2>nul

REM THE AUTO-LOAD COPY.  dinput8.dll and avatar_console.dll are byte-for-byte the
REM same file; the DLL decides at run time which it is, from its own file name
REM (see the proxy block above DllMain in avatar_console.c).  Copying rather than
REM linking twice is deliberate: two links means two artefacts that can be built
REM from different sources, and this project has already lost hours to a stale
REM binary that reported success.
copy /y dist\avatar_console.dll dist\dinput8.dll >nul
if errorlevel 1 (
    echo.
    echo BUILD FAILED: could not write dist\dinput8.dll
    exit /b 1
)
echo.
echo BUILT: %~dp0dist\avatar_console.dll   (dist\inject.py)
echo BUILT: %~dp0dist\dinput8.dll          (auto-load - dist\install.bat)
dumpbin /nologo /headers dist\avatar_console.dll | findstr /i "machine"
REM Prove the exports are there.  A proxy whose export table is empty or
REM misspelled does not misbehave, it stops the game from starting at all with
REM "The procedure entry point DirectInput8Create could not be located" - and the
REM only thing that tells you apart from a hundred other startup failures is this
REM line at build time.
echo.
echo Exports (must be the six dinput8 names, ordinals 1-6):
dumpbin /nologo /exports dist\dinput8.dll | findstr /i "DirectInput8Create DllCanUnloadNow DllGetClassObject DllRegisterServer DllUnregisterServer GetdfDIJoystick"
endlocal
