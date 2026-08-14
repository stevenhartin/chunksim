@echo off
rem  Build the Windows installer, end to end, on a Windows machine.
rem
rem      packaging\build.bat                  ask for a version, then build
rem      packaging\build.bat /version 0.2.0   bump to 0.2.0 without asking
rem      packaging\build.bat /keep            build the current version, no bump
rem      packaging\build.bat /payload         stop after the payload, skip Inno Setup
rem      packaging\build.bat /nodps          build without the DPS calculator
rem
rem  Three steps, each a thing that can be *missing* rather than subtly wrong,
rem  so each is checked and named:
rem
rem    1. the version    - pyproject.toml and chunksim.iss, which must agree
rem    2. the payload    - embeddable CPython, chunksim and osrs-dps beside it,
rem                        and the GPL source for both. build_windows.py builds
rem                        the wheels and sdists it needs; this only makes sure
rem                        the `build` package is there to do it with.
rem    3. the installer  - Inno Setup compiles the payload into setup.exe
rem
rem  **The commit is last, and only on success.** A version bump committed for a
rem  build that then failed is a tag waiting to be cut for an artefact nobody
rem  has. If a step fails the two files are left modified and uncommitted, and
rem  this says so.
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
set "NEWVER="
set "KEEP="
set "DPSARG="
:args
if "%~1"=="" goto :args_done
if /i "%~1"=="/payload" set "SKIP_INNO=1"
if /i "%~1"=="/keep" set "KEEP=1"
if /i "%~1"=="/nodps" set "DPSARG=--without-dps"
if /i "%~1"=="/version" set "NEWVER=%~2"& shift
shift
goto :args
:args_done

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
%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)"
if errorlevel 1 (
    echo ERROR: Python 3.14 or newer is required ^(pyproject.toml says so^).
    goto :fail
)

rem --- 1. the version ---------------------------------------------------
for /f "delims=" %%V in ('%PY% packaging\set_version.py') do set "CURVER=%%V"
echo [1/3] current version: !CURVER!

set "BUMPED="
if defined KEEP goto :version_done
if not defined NEWVER (
    echo       Enter a new version, or press Enter to build !CURVER! as it is.
    set /p "NEWVER=      new version: "
)
if not defined NEWVER goto :version_done

%PY% packaging\set_version.py "!NEWVER!"
if errorlevel 1 (
    echo ERROR: the version was not changed. Nothing has been modified.
    goto :fail
)
set "BUMPED=1"

:version_done

rem --- 2. the payload ---------------------------------------------------
%PY% -c "import build" >nul 2>&1
if errorlevel 1 (
    echo       installing the 'build' package
    %PY% -m pip install --quiet build
    if errorlevel 1 (
        echo ERROR: could not install 'build'. Try: %PY% -m pip install build
        goto :fail
    )
)
echo [2/3] assembling the payload
%PY% packaging\build_windows.py %DPSARG%
if errorlevel 1 (
    echo ERROR: the payload is incomplete - see the lines marked ! above.
    goto :fail
)

rem --- 3. the installer -------------------------------------------------
if defined SKIP_INNO (
    echo [3/3] skipped ^(/payload^)
    echo.
    echo Payload ready: %CD%\packaging\build\payload
    goto :commit
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
echo [3/3] Inno Setup: !ISCC!
"!ISCC!" /Q "packaging\chunksim.iss"
if errorlevel 1 (
    echo ERROR: the installer did not compile.
    goto :fail
)

echo.
for %%F in ("packaging\build\chunksim-*-setup.exe") do echo Installer: %CD%\packaging\build\%%~nxF

rem --- the commit -------------------------------------------------------
:commit
if not defined BUMPED goto :done

for /f "delims=" %%V in ('%PY% packaging\set_version.py') do set "CURVER=%%V"
where git >nul 2>&1
if errorlevel 1 (
    echo.
    echo NOTE: git is not on PATH, so the version bump is uncommitted.
    echo       Commit pyproject.toml and packaging\chunksim.iss by hand.
    goto :done
)

rem  Named files, not `git commit -a`: whatever else is in the working tree is
rem  the author's business and must not be swept into a release commit.
git commit --only pyproject.toml packaging/chunksim.iss -m "Release !CURVER!"
if errorlevel 1 (
    echo.
    echo NOTE: nothing was committed - see git's message above.
    goto :done
)
echo.
echo Committed the bump to !CURVER!. To publish it:
echo       git tag v!CURVER!  ^&^&  git push  ^&^&  git push --tags
echo   then attach packaging\build\chunksim-!CURVER!-setup.exe to the release.

:done
echo.
echo Build finished.
popd
endlocal
exit /b 0

:fail
echo.
if defined BUMPED echo NOTE: the version was changed to !NEWVER! and is NOT committed.
echo Build FAILED.
popd
endlocal
exit /b 1
