# E9 control run (ASCII only, to avoid encoding problems on Korean/Japanese Windows)
# Purpose: with compute (45s) > deadline (30s), do we still get the same number of compute starts when the DB is NOT stopped?
#   C-min was 3 starts, V6 (v6_min) was 2 starts in the original E9 (DB stopped 3s).
# Run in C:\Users\User\Programming\LangGraph with the venv active:
#   powershell -ExecutionPolicy Bypass -File .\run_e9_control.ps1 -Rounds 1 -WithStop
# Close videos, browsers, pgAdmin before running. Do not touch the PC while it runs.
# NOTE: written by Claude, NOT tested on Windows+Docker.
param(
  [int]$Rounds = 1,
  [switch]$WithStop,
  [string]$V6Pkg = "covershift_prototype_v6_min",
  [string]$Sleep = "45",
  [string]$Timeout = "30"
)
$ErrorActionPreference = "Continue"
$OutDir = "results_e9_control"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Start-Transcript -Path "$OutDir\log_$(Get-Date -Format yyyyMMdd_HHmmss).txt" | Out-Null

# Back up existing E9 results (they get overwritten by the harness)
$stamp = Get-Date -Format yyyyMMdd_HHmmss
foreach ($f in @("harness_c\e9_c_result.json", "harness_v6real\e9_result.json")) {
  if (Test-Path $f) { Copy-Item $f ("$OutDir\backup_" + $stamp + "_" + (Split-Path $f -Leaf)) }
}

function Reset-Stack([string]$system) {
  docker compose -f docker-compose.proto_c.yml down -v --remove-orphans | Out-Null
  docker compose -f docker-compose.proto.yml down -v --remove-orphans | Out-Null
  if ($system -eq "C") { docker compose -f docker-compose.proto_c.yml up -d | Out-Null }
  else { docker compose -f docker-compose.proto.yml up -d | Out-Null }
  Write-Host "Waiting 15 s for DB (and queue) to initialize..."
  Start-Sleep -Seconds 15
}

function Run-One([string]$system, [string]$mode, [int]$round) {
  # mode = control (DB NOT stopped) or stop (original E9: DB stopped 3 s, 5 s after compute start)
  $env:EXP_SLEEP = $Sleep
  $env:JOB_TIMEOUT_SEC = $Timeout
  if ($system -eq "C") {
    $env:PKG = "covershift_prototype_c_queue"
    $mod = "harness_c.run_e9_c"; $src = "harness_c\e9_c_result.json"
    $compose = "docker-compose.proto_c.yml"
  } else {
    $env:PKG = $V6Pkg
    $mod = "harness_v6real.run_e9_dbrestart_midjob"; $src = "harness_v6real\e9_result.json"
    $compose = "docker-compose.proto.yml"
  }
  if ($mode -eq "control") {
    # Replace stop/start commands with no-ops (the log will say DB stopped, but it is NOT stopped)
    $env:E5_STOP_CMD = 'python -c "pass"'
    $env:E5_START_CMD = 'python -c "pass"'
  } else {
    $env:E5_STOP_CMD = "docker compose -f $compose stop db"
    $env:E5_START_CMD = "docker compose -f $compose start db"
  }
  Write-Host ""
  Write-Host "=== E9 $system / $mode / round $round  (compute ${Sleep}s, deadline ${Timeout}s) ==="
  Reset-Stack $system
  Remove-Item $src -ErrorAction SilentlyContinue
  python -m $mod
  $dst = "$OutDir\e9_" + $system + "_" + $mode + "_r" + $round + ".json"
  if (Test-Path $src) {
    Copy-Item $src $dst -Force
    $j = Get-Content $dst -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($system -eq "C") {
      $n = @($j.solver_log).Count
      Write-Host ">>> RESULT: compute starts = $n / result rows = $($j.solver_results_rows) / finished at $($j.finished_at_sec_after_db_stop) s"
    } else {
      $n = 0
      foreach ($p in $j.PSObject.Properties) { if ($p.Name -like "worker1_starts*" -or $p.Name -like "worker2_starts*") { $n += @($p.Value).Count } }
      Write-Host ">>> RESULT: compute starts = $n / finished at $($j.finished_at_sec_after_db_stop) s / final $($j.final.run_status)"
    }
  } else {
    Write-Host ">>> No result file was created. See the error above."
  }
}

for ($r = 1; $r -le $Rounds; $r++) {
  foreach ($sys in @("C", "V6")) {
    Run-One $sys "control" $r
    if ($WithStop) { Run-One $sys "stop" $r }
  }
}
docker compose -f docker-compose.proto_c.yml down -v --remove-orphans | Out-Null
docker compose -f docker-compose.proto.yml down -v --remove-orphans | Out-Null
# Restore the original E9 results to their original place
foreach ($f in @("harness_c\e9_c_result.json", "harness_v6real\e9_result.json")) {
  $b = "$OutDir\backup_" + $stamp + "_" + (Split-Path $f -Leaf)
  if (Test-Path $b) { Copy-Item $b $f -Force }
}
Write-Host ""
Write-Host "Done. Results are in $OutDir. Original E9 results were restored (backup copies kept)."
Stop-Transcript | Out-Null