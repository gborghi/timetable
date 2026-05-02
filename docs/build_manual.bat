@echo off
rem Windows version of build_manual.sh. Pipeline:
rem   lualatex + biber (if .bcf) + makeindex (if .idx) + lualatex x2
rem Run from anywhere; the script cd's to its own dir first.

setlocal enabledelayedexpansion
cd /d "%~dp0"

set JOB=manual
set TEX=manual.tex
set QUICK=0
if /I "%~1"=="--quick" set QUICK=1

echo [manual] pass 1: lualatex
lualatex -interaction=nonstopmode -halt-on-error %TEX% >NUL
if errorlevel 1 goto :error

if "%QUICK%"=="1" goto :clean

if exist "%JOB%.bcf" (
  echo [manual] biber
  biber %JOB% >NUL
)
if exist "%JOB%.idx" (
  echo [manual] makeindex
  makeindex %JOB%.idx >NUL
)
echo [manual] pass 2: lualatex
lualatex -interaction=nonstopmode -halt-on-error %TEX% >NUL
if errorlevel 1 goto :error
echo [manual] pass 3: lualatex
lualatex -interaction=nonstopmode -halt-on-error %TEX% >NUL
if errorlevel 1 goto :error

:clean
echo [manual] cleaning aux files
del /Q %JOB%.aux %JOB%.log %JOB%.toc %JOB%.out %JOB%.bcf ^
      %JOB%.run.xml %JOB%.idx %JOB%.ind %JOB%.ilg ^
      %JOB%.bbl %JOB%.blg %JOB%.lof %JOB%.lot ^
      %JOB%-blx.bib 2>NUL

echo [manual] OK -^> docs\manual.pdf
exit /b 0

:error
echo [manual] FAILED. See %JOB%.log
exit /b 1
