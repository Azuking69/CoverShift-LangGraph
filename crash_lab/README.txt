追加実験2本(V2 / V6 用)  crash_lab
================================
入れる場所: covershift_prototype などのパッケージがあるフォルダ(harness\ と同じ階層)に crash_lab\ ごと置く。

■ 何を調べるか
 実験1(run_x1.py) ワーカーを「グラフ実行の直後・runs に書く前」でいきなり落とし、別のワーカーが拾い直したとき正しい結果になるか。
   C0 落とさずに「却下」(基準)   A 開始の仕事で落とす   B 再開(承認)で落とす   C 再開(却下)で落とす
   → 正しい結果: A=承認待ち / B=完了 / C=C0と同じ(承認待ちに戻る)
 実験2(run_x2.py) 同じ件の仕事を2台のワーカーが同時に持つとどうなるか。
   D 期限切れの拾い直しが、まだ動いている仕事と重なる(期限3秒・計算8秒)
   E 同じ件の「開始」を2つ入れる    F 承認待ちの件に「却下」の再開を2つ入れる

■ 手順(PowerShell)  ※ V2 と V6 は同じDBを使えないので、切り替えるたびに down -v
 1) docker compose -f docker-compose.proto.yml down -v
    docker compose -f docker-compose.proto.yml up -d
 2) V2 のとき:  $env:PKG="covershift_prototype"
    V6 のとき:  $env:PKG="covershift_prototype_v6_langgraph"
 3) python crash_lab\run_x1.py        (約2〜3分)
    Copy-Item crash_lab\crash_lab_x1_result.json crash_lab\x1_<V2かV6>.json
 4) python crash_lab\run_x2.py        (約2分)
    Copy-Item crash_lab\crash_lab_x2_result.json crash_lab\x2_<V2かV6>.json
 5) 別バージョンを試すときは 1) に戻る。

■ 注意
 - 実験用ワーカーは自動で起動・停止します。他のワーカー/APIは止めておいてください(同じDBを見ているため)。
 - 計算はモック(MOCK_SOLVER_SLEEP で待つだけ)。本物のCP-SATではありません。
 - 本物の worker.py は書き換えません(起動時に見張りを付けるだけ)。
 - 途中で止まったら、残ったpythonを止めて(Get-Process python | Stop-Process)から 1) へ。
 - 送ってほしいもの: x1_*.json と x2_*.json、最後の画面の出力。
