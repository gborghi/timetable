@echo off
rem Build the three PDF manuals on Windows.
rem Outputs (in docs/):
rem   manual_generale.pdf    Parte I
rem   appendici_tecniche.pdf Parte II
rem   manual_completo.pdf    entrambe

setlocal enabledelayedexpansion
cd /d "%~dp0"

set QUICK=0
set PICK=
:argparse
if "%~1"=="" goto run
if /I "%~1"=="--quick" set QUICK=1 & shift & goto argparse
if /I "%~1"=="manual_generale" set PICK=%~1 & shift & goto argparse
if /I "%~1"=="appendici_tecniche" set PICK=%~1 & shift & goto argparse
if /I "%~1"=="manual_completo" set PICK=%~1 & shift & goto argparse
echo [manual] unknown arg: %~1
shift
goto argparse

:run
if defined PICK (
  call :build %PICK%
) else (
  call :build manual_generale
  call :build appendici_tecniche
  call :build manual_completo
)
echo [manual] OK
exit /b 0

:build
set JOB=%~1
set TEX=%JOB%.tex
if not exist %TEX% (
  echo [manual] missing %TEX%, skip
  exit /b 0
)
echo [manual] === %JOB% ===
lualatex -interaction=nonstopmode -halt-on-error %TEX% >NUL
if errorlevel 1 (
  echo [manual] %JOB% FAILED on pass 1
  exit /b 1
)
if "%QUICK%"=="0" (
  if exist %JOB%.bcf biber %JOB% >NUL
  if exist %JOB%.idx makeindex %JOB%.idx >NUL
  lualatex -interaction=nonstopmode -halt-on-error %TEX% >NUL
  lualatex -interaction=nonstopmode -halt-on-error %TEX% >NUL
)
del /Q %JOB%.aux %JOB%.log %JOB%.toc %JOB%.out %JOB%.bcf ^
       %JOB%.run.xml %JOB%.idx %JOB%.ind %JOB%.ilg ^
       %JOB%.bbl %JOB%.blg %JOB%.lof %JOB%.lot ^
       %JOB%-blx.bib 2>NUL
echo [manual] %JOB%.pdf done
exit /b 0
