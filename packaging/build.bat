@echo off
rem  Build the Windows installer, end to end, on a Windows machine.
rem
rem      packaging\build.bat            release build
rem      packaging\build.bat /payload   stop after the payload, skip Inno Setup
rem
rem  Three steps, and each one is a thing that can be missing rather than a
rem  thing that can go subtly wrong, so each is checked and named:
rem
rem    1. a wheel        - its .dist-info goes beside the package, and without
rem                        it the watermark and the update check go quiet
rem    2. the payload    - embeddable CPython with chunksim next to it
rem    3. the installer  - Inno Setup compiles the payload into setup.exe
rem
rem  Everything lands in packaging\build\, which is gitignored.

setlocal enabledelayedexpansion

rem  Read the two Program Files variables *outside* any parenthesised block.
rem  `%ProgramFiles(x86)%` contains brackets, and inside an if or for block cmd
rem  parses those as the end of the block - the classic way a batch file that
rem  looks right fails only on the machine that has the 32-bit path set.
set "PF=%ProgramFiles%"
set "PF86=%ProgramFiles(x86)%"

rem  Run from the repository root whatever directory this was invoked from.
pushd "%~dp0.."

set "SKIP_INNO="
if /i "%~1"=="/payload" set "SKIP_INNO=1"

echo.
echo === chunksim Windows build ===
echo     repository: %CD%
echo.

rem --- Python -----------------------------------------------------------
rem  The py launcher ships with the python.org installer and is how a Windows
rem  box picks a version; a bare `python` may be the Store alias, which is a
rem  stub that opens the Store rather than running anything.
set "PY="
py -3.14 -c "import sys" >nul 2>&1 && set "PY=py -3.14"
if not defined PY py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY (
    echo ERROR: no Python found. Install 3.14 from https://www.python.org/downloads/
    goto :fail
)
echo [1/3] Python: %PY%
%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)"
if errorlevel 1 (
    echo ERROR: Python 3.14 or newer is required ^(pyproject.toml says so^).
    goto :fail
)

rem --- 1. the wheel -----------------------------------------------------
%PY% -c "import build" >nul 2>&1
if errorlevel 1 (
    echo       installing the 'build' package
    %PY% -m pip install --quiet build
    if errorlevel 1 (
        echo ERROR: could not install 'build'. Try: %PY% -m pip install build
        goto :fail
    )
)
echo       building the wheel
%PY% -m build --wheel --outdir dist >nul
if errorlevel 1 (
    echo ERROR: the wheel did not build. Run without ^>nul to see why:
    echo        %PY% -m build --wheel --outdir dist
    goto :fail
)

rem --- 2. the payload ---------------------------------------------------
echo [2/3] assembling the payload
%PY% packaging\build_windows.py
if errorlevel 1 (
    echo ERROR: the payload is incomplete - see the lines marked ! above.
    goto :fail
)

rem --- 3. the installer -------------------------------------------------
if defined SKIP_INNO (
    echo [3/3] skipped ^(/payload^)
    echo.
    echo Payload ready: %CD%\packaging\build\payload
    goto :done
)

rem  ISCC is Inno Setup's command-line compiler. On PATH if the installer was
rem  told to add it; otherwise it is in one of the two Program Files trees.
set "ISCC="
for %%I in (iscc.exe) do if not defined ISCC if not "%%~$PATH:I"=="" set "ISCC=%%~$PATH:I"
if not defined ISCC if exist "%PF86%\Inno Setup 6\ISCC.exe" set "ISCC=%PF86%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%PF%\Inno Setup 6\ISCC.exe" set "ISCC=%PF%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    echo ERROR: Inno Setup 6 not found.
    echo        Install it from https://jrsoftware.org/isdl.php
    echo        or re-run with /payload to stop after the payload.
    goto :fail
)
echo [3/3] Inno Setup: %ISCC%
"%ISCC%" /Q "packaging\chunksim.iss"
if errorlevel 1 (
    echo ERROR: the installer did not compile.
    goto :fail
)

echo.
for %%F in ("packaging\build\chunksim-*-setup.exe") do echo Installer: %CD%\packaging\build\%%~nxF

:done
echo.
echo Build finished.
popd
endlocal
exit /b 0

:fail
echo.
echo Build FAILED.
popd
endlocal
exit /b 1
