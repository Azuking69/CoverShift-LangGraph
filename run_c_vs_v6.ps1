# C案(最小版)と V6 を、同じ条件で交互に測る (E1・E2・E3・E5・E6)。
# 実行場所: C:\Users\User\Programming\LangGraph  (venv を有効にした状態で)
#   powershell -ExecutionPolicy Bypass -File .\run_c_vs_v6.ps1
#   例: powershell -ExecutionPolicy Bypass -File .\run_c_vs_v6.ps1 -Rounds 3 -SlowRounds 1
# 測る前に: 動画・ブラウザ・pgAdmin・VSCodeのDB拡張を閉じる(前回、動画で数字が乱れたため)。測定中はPCを触らない。
param(
  [int]$Rounds = 3,          # E1・E2 の交互の回数(各システム)
  [int]$SlowRounds = 1,      # E3・E5・E6 の回数(各システム。E5が1回約4分のため既定は1)
  [string]$V6Pkg = "covershift_prototype_v6_langgraph",
  [string[]]$Only = @()      # 例: -Only E2,E3 で一部だけ
)
$ErrorActionPreference = "Continue"
$OutDir = "results_cv6"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Start-Transcript -Path "$OutDir\log_$(Get-Date -Format yyyyMMdd_HHmmss).txt" | Out-Null

function Reset-Stack([string]$system) {
  docker compose -f docker-compose.proto_c.yml down -v --remove-orphans | Out-Null
  if ($system -eq "C") { docker compose -f docker-compose.proto_c.yml up -d | Out-Null }
  else { docker compose -f docker-compose.proto.yml up -d | Out-Null }
  Write-Host "DB(とキュー)の初期化を15秒待ちます..."
  Start-Sleep -Seconds 15
}

function Run-One([string]$system, [string]$exp, [int]$round) {
  $e = $exp.ToLower()
  if ($system -eq "C") {
    $env:PKG = "covershift_prototype_c_queue"
    $mod = "harness_c.run_${e}_c"; $src = "harness_c\${e}_c_result.json"
  } else {
    $env:PKG = $V6Pkg
    $mod = "harness_v6real.run_${e}_real"; $src = "harness_v6real\${e}_result.json"
  }
  Write-Host ""
  Write-Host "=== $exp  第${round}回 : $system ==="
  Reset-Stack $system
  if ($system -eq "C") {
    $env:E5_STOP_CMD = "docker compose -f docker-compose.proto_c.yml stop db"
    $env:E5_START_CMD = "docker compose -f docker-compose.proto_c.yml start db"
  } else {
    $env:E5_STOP_CMD = "docker compose -f docker-compose.proto.yml stop db"
    $env:E5_START_CMD = "docker compose -f docker-compose.proto.yml start db"
  }
  if ($system -eq "V6" -and $exp -eq "E6") {
    # V6は、新品のDBでワーカーを2台同時に起動すると、LangGraphの表づくりがぶつかって数件が失敗する。
    # E6を「処理能力」の試験にするため、表だけ先に1回作っておく(測定そのものは変えない)。
    python -c "from ${env:PKG}.worker import HOLDER; HOLDER.get(); print('LangGraph用の表を先に作りました')"
  }
  if (Test-Path $src) { Remove-Item $src -Force }
  python -m $mod
  if (Test-Path $src) { Copy-Item $src "$OutDir\${exp}_${system}_r$round.json" -Force }
  else { Write-Host "[注意] 結果ファイルがありません: $src" }
}

function Want([string]$exp) { return ($Only.Count -eq 0) -or ($Only -contains $exp) }

# E1・E2: V6 → C を交互に
foreach ($exp in @("E1","E2")) {
  if (-not (Want $exp)) { continue }
  for ($r = 1; $r -le $Rounds; $r++) {
    Run-One "V6" $exp $r
    Run-One "C"  $exp $r
  }
}
# E3・E5・E6
foreach ($exp in @("E3","E6","E5")) {
  if (-not (Want $exp)) { continue }
  for ($r = 1; $r -le $SlowRounds; $r++) {
    Run-One "V6" $exp $r
    Run-One "C"  $exp $r
  }
}
docker compose -f docker-compose.proto_c.yml down -v --remove-orphans | Out-Null
Write-Host ""
Write-Host "=== まとめ ==="
python summarize_cv6.py
Stop-Transcript | Out-Null