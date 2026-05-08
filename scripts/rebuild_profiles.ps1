# Rebuild every mock-school profile (school_<name>.pkl + profs_<name>.pkl)
# under engine/scripts/data/<profile>/ so the dashboard's "Importa modelli
# risolti" dropdown is no longer empty for non-mega profiles.
#
# The pickles themselves are gitignored (engine/scripts/*.pkl, plus the
# leaf-level data/*/*.pkl by convention) so each developer regenerates
# them locally with this script after a fresh clone.
#
# Usage (from the repo root, on Windows PowerShell or pwsh):
#     powershell -File scripts/rebuild_profiles.ps1
#     powershell -File scripts/rebuild_profiles.ps1 -Profiles small,medium
#     powershell -File scripts/rebuild_profiles.ps1 -AssignmentTime 30
#
# Steps per profile:
#   1) python engine/big_mock_school.py --profile <name>
#        -> engine/scripts/data/<name>/school_<name>.pkl
#   2) python engine/cpsat_v2_assignment.py --school <school.pkl>
#                                           --out   <profs.pkl>
#                                           --time  <AssignmentTime>
#        -> engine/scripts/data/<name>/profs_<name>.pkl
#
# The CP-SAT assignment step grows ~quadratically with class count;
# defaults are tuned so small/medium/big finish in seconds and
# huge/superhuge in a few minutes. Bump -AssignmentTime if a profile
# fails with INFEASIBLE / TIMEOUT.

[CmdletBinding()]
param(
    [string[]] $Profiles = @("small", "medium", "big", "huge", "superhuge"),
    [int]      $AssignmentTime = 60,
    [int]      $AssignmentWorkers = 8,
    [string]   $Python = "python",
    [switch]   $SkipExisting
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$EngineDir = Join-Path $RepoRoot "engine"
$DataDir   = Join-Path $RepoRoot "engine\scripts\data"

if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir | Out-Null
}

Write-Host ""
Write-Host "[rebuild] repo root:  $RepoRoot"
Write-Host "[rebuild] engine dir: $EngineDir"
Write-Host "[rebuild] data dir:   $DataDir"
Write-Host "[rebuild] profiles:   $($Profiles -join ', ')"
Write-Host ""

foreach ($profile in $Profiles) {
    $profileDir = Join-Path $DataDir $profile
    if (-not (Test-Path $profileDir)) {
        New-Item -ItemType Directory -Path $profileDir | Out-Null
    }
    $schoolPkl = Join-Path $profileDir "school_$profile.pkl"
    $profsPkl  = Join-Path $profileDir "profs_$profile.pkl"

    if ($SkipExisting -and (Test-Path $schoolPkl) -and (Test-Path $profsPkl)) {
        Write-Host "[$profile] SKIP (both pickles already exist)"
        continue
    }

    Write-Host "============================================================"
    Write-Host "[$profile] step 1/2 - big_mock_school -> $schoolPkl"
    Write-Host "============================================================"
    & $Python (Join-Path $EngineDir "big_mock_school.py") `
        --profile $profile `
        --out $schoolPkl
    if ($LASTEXITCODE -ne 0) {
        throw "big_mock_school failed for profile=$profile"
    }

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "[$profile] step 2/2 - cpsat_v2_assignment -> $profsPkl"
    Write-Host "============================================================"
    & $Python (Join-Path $EngineDir "cpsat_v2_assignment.py") `
        --school $schoolPkl `
        --out $profsPkl `
        --time $AssignmentTime `
        --workers $AssignmentWorkers `
        --no-log
    if ($LASTEXITCODE -ne 0) {
        throw "cpsat_v2_assignment failed for profile=$profile"
    }

    $sSize = (Get-Item $schoolPkl).Length
    $pSize = (Get-Item $profsPkl).Length
    Write-Host ""
    Write-Host "[$profile] OK  school=$([math]::Round($sSize/1KB,1))KB  profs=$([math]::Round($pSize/1KB,1))KB"
    Write-Host ""
}

Write-Host ""
Write-Host "[rebuild] done. Files:"
Get-ChildItem $DataDir -Recurse -Filter *.pkl |
    Sort-Object FullName |
    ForEach-Object {
        $rel = $_.FullName.Substring($RepoRoot.Path.Length + 1)
        Write-Host ("  {0,-60}  {1,8} bytes" -f $rel, $_.Length)
    }
