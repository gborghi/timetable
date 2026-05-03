@echo off
rem Build the unified PDF manual on Windows.
rem Output (in docs/):
rem   manual.pdf -- monografia unica, capitoli numerati progressivamente

setlocal enabledelayedexpansion
cd /d "%~dp0"

set QUICK=0
:argparse
if "%~1"=="" goto run
if /I "%~1"=="--quick" set QUICK=1 & shift & goto argparse
echo [manual] unknown arg: %~1
shift
goto argparse

:run
set JOB=manual
set TEX=%JOB%.tex
if not exist %TEX% (
  echo [manual] %TEX% not found
  exit /b 1
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
