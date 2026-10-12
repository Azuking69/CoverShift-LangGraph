# C案(最小版) と V6 の比較結果

※ C案(最小版)はClaudeが資料から作った簡易版で、スンヒョクさんのC案のコードではありません。V6はLangGraph+PostgresSaverを含みます。C案(最小版)にはLangGraphもCP-SATもLINEもありません。

## E1 何もしない60秒(DBへの問い合わせ)
| システム | 回 | トランザクション | 新しい接続 |
|---|---|---|---|
| V6 | 1 | 14 | 6 |
| V6 | 2 | 14 | 6 |
| V6 | 3 | 14 | 6 |
| C | 1 | 14 | 0 |
| C | 2 | 14 | 0 |
| C | 3 | 14 | 0 |

## E2 仕事を出してから始まるまでの遅れ(ms。時計ずれ補正済み)
| システム | 回 | 中央値 | 95% | 最大 | 欠け |
|---|---|---|---|---|---|
| V6 | 1 | 176 | 695 | 923 | 0 |
| V6 | 2 | 152 | 670 | 977 | 0 |
| V6 | 3 | 95 | 430 | 602 | 0 |
| C | 1 | 121 | 143 | 180 | 0 |
| C | 2 | 110 | 130 | 294 | 0 |
| C | 3 | 116 | 130 | 148 | 0 |
- V6: 中央値の平均 141 ms / 回ごとの幅 95〜176 ms
- C: 中央値の平均 115.7 ms / 回ごとの幅 110〜121 ms
(C案は「API受付→送信箱→リレー→キュー→フロー処理器」、V6は「API受付→ワーカーが仕事を取る」まで。測る区間が違う)

## E3 ワーカー突然死 → 復旧
- V6 第1回: {"sleep_sec": "8", "timeout_sec": "10", "passed": true, "thread_id": "e3-1791713029-2026-10", "seconds_after_restart": 21.2, "final_status": "PAUSED_FOR_APPROVAL", "jobs": [{"id": 1, "kind": "start", "status": "done", "attempts": 2}], "attempts": 2}
- C 第1回: {"system": "C-min", "sleep_sec": "8", "timeout_sec": "10", "passed": true, "thread_id": "e3-1791713076-2026-10", "seconds_after_restart": 17.0, "final_status": "PAUSED_FOR_APPROVAL", "solver_log": [[1, 1, "pid12888"], [1, 2, "pid14732"]], "max_receive_count": 2}

## E6 ワーカー2台で20件
- V6 第1回: {"jobs": 20, "seconds_for_starts": 25.1, "paused": 20, "max_attempts": 1, "jobs_per_worker": {"e6_w1": 10, "e6_w2": 10}, "resume_http": {"202": 20}, "completed_after_resume": 20}
- V6 第2回: {"jobs": 20, "seconds_for_starts": 25.1, "paused": 20, "max_attempts": 1, "jobs_per_worker": {"e6_w1": 10, "e6_w2": 10}, "resume_http": {"202": 20}, "completed_after_resume": 20}
- V6 第3回: {"jobs": 20, "seconds_for_starts": 24.9, "paused": 20, "max_attempts": 1, "jobs_per_worker": {"e6_w1": 10, "e6_w2": 10}, "resume_http": {"202": 20}, "completed_after_resume": 20}
- C 第1回: {"system": "C-min", "jobs": 20, "seconds_for_starts": 22.3, "paused": 20, "max_receive_count": 1, "duplicate_solves": 0, "jobs_per_solver": {"e6_s1": 10, "e6_s2": 10}, "events_per_flow": {"e6_f1": 19, "e6_f2": 21}, "resume_http": {"202": 20}, "completed_after_resume": 20}
- C 第2回: {"system": "C-min", "jobs": 20, "seconds_for_starts": 22.1, "paused": 20, "max_receive_count": 1, "duplicate_solves": 0, "jobs_per_solver": {"e6_s1": 10, "e6_s2": 10}, "events_per_flow": {"e6_f1": 21, "e6_f2": 19}, "resume_http": {"202": 20}, "completed_after_resume": 20}
- C 第3回: {"system": "C-min", "jobs": 20, "seconds_for_starts": 21.9, "paused": 20, "max_receive_count": 1, "duplicate_solves": 0, "jobs_per_solver": {"e6_s1": 10, "e6_s2": 10}, "events_per_flow": {"e6_f1": 19, "e6_f2": 21}, "resume_http": {"202": 20}, "completed_after_resume": 20}

## E5 DB停止
- V6 第1回: {"A_latency_after_short_outage_sec": [1.0, 0.7, 0.7], "A_notify_lines": 3, "B_post_during_down": {"http": 500, "sec": 10.6}, "B_worker_alive_after_45s": true, "B_latency_after_long_outage_sec": 0.9, "B_worker_alive_end": true, "C_queued_during_restart_processed_of_3": 3}
- C 第1回: {"system": "C-min", "A_latency_after_short_outage_sec": [0.3, 2.5, 2.6], "B_post_during_down": {"http": 500, "sec": 10.1}, "B_alive_after_45s": {"e5_api": true, "e5_relay": true, "e5_flow": true, "e5_solver": true}, "B_latency_after_long_outage_sec": 2.5, "B_alive_end": {"e5_api": true, "e5_relay": true, "e5_flow": true, "e5_solver": true}, "C_queued_during_restart_processed_of_3": 3, "D_post_during_queue_down": [{"http": 202, "sec": 0.1}, {"http": 202, "sec": 0.1}, {"http": 202, "sec": 0.0}], "D_outbox_unsent_during_queue_down": 3, "D_alive_during_queue_down": {"e5_api": true, "e5_relay": true, "e5_flow": true, "e5_solver": true}, "D_processed_of_3": 3, "D_seconds_after_queue_back": 0.1}
