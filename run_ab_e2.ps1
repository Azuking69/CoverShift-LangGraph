# V6 と v6_min を交互に E2 測定する (各3回)。プロトタイプ用DB(5434)だけを作り直します。
# 実行場所: C:\Users\User\Programming\LangGraph  (venv を有効にした状態で)
#   powershell -ExecutionPolicy Bypass -File .\run_ab_e2.ps1
$ErrorActionPreference = "Continue"
$order = @(
  @("V6","covershift_prototype_v6_langgraph"),
  @("v6_min","covershift_prototype_v6_min")
)
$rounds = 3
New-Item -ItemType Directory -Force -Path harness\ab | Out-Null
for ($r = 1; $r -le $rounds; $r++) {
  foreach ($o in $order) {
    $name = $o[0]; $env:PKG = $o[1]
    Write-Host "=== 第$r回 : $name ==="
    docker compose -f docker-compose.proto.yml down -v | Out-Null
    docker compose -f docker-compose.proto.yml up -d | Out-Null
    Write-Host "DBの初期化を15秒待ちます..."
    Start-Sleep -Seconds 15
    python -m harness.run_e2_latency
    Copy-Item harness\e2_result.json "harness\ab\e2_${name}_r$r.json" -Force
  }
}
Write-Host ""
Write-Host "=== まとめ: 各回の [結果] 行(上の画面にも出ています)。生データは harness\ab\ にあります ==="
Get-ChildItem harness\ab\e2_*_r*.json | Sort-Object Name | ForEach-Object { Write-Host $_.Name }