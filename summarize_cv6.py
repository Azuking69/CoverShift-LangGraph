"""results_cv6 の結果を、表にまとめる(画面に出す + results_cv6/summary.md に保存)。"""
import glob
import json
import os
import re
import statistics

D = "results_cv6"
rows = {}
for f in sorted(glob.glob(os.path.join(D, "E*_*_r*.json"))):
    m = re.match(r"(E\d)_(V6|C)_r(\d+)\.json", os.path.basename(f))
    if not m:
        continue
    rows.setdefault((m.group(1), m.group(2)), []).append((int(m.group(3)), json.load(open(f, encoding="utf-8"))))

out = []


def p(s=""):
    print(s)
    out.append(s)


def get(d, *ks):
    for k in ks:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


p("# C案(最小版) と V6 の比較結果")
p("")
p("※ C案(最小版)はClaudeが資料から作った簡易版で、スンヒョクさんのC案のコードではありません。V6はLangGraph+PostgresSaverを含みます。C案(最小版)にはLangGraphもCP-SATもLINEもありません。")
p("")
if ("E1", "V6") in rows or ("E1", "C") in rows:
    p("## E1 何もしない60秒(DBへの問い合わせ)")
    p("| システム | 回 | トランザクション | 新しい接続 |")
    p("|---|---|---|---|")
    for s in ("V6", "C"):
        for r, d in rows.get(("E1", s), []):
            p(f"| {s} | {r} | {d.get('transactions')} | {d.get('connections_opened')} |")
    p("")
if ("E2", "V6") in rows or ("E2", "C") in rows:
    p("## E2 仕事を出してから始まるまでの遅れ(ms。時計ずれ補正済み)")
    p("| システム | 回 | 中央値 | 95% | 最大 | 欠け |")
    p("|---|---|---|---|---|---|")
    for s in ("V6", "C"):
        for r, d in rows.get(("E2", s), []):
            c = d.get("client_based", {})
            p(f"| {s} | {r} | {c.get('median_ms')} | {c.get('p95_ms')} | {c.get('max_ms')} | {c.get('missing')} |")
    for s in ("V6", "C"):
        ms = [get(d, "client_based", "median_ms") for _, d in rows.get(("E2", s), [])]
        ms = [x for x in ms if x is not None]
        if ms:
            p(f"- {s}: 中央値の平均 {round(statistics.mean(ms), 1)} ms / 回ごとの幅 {min(ms)}〜{max(ms)} ms")
    p("(C案は「API受付→送信箱→リレー→キュー→フロー処理器」、V6は「API受付→ワーカーが仕事を取る」まで。測る区間が違う)")
    p("")
for exp, title in (("E3", "E3 ワーカー突然死 → 復旧"), ("E6", "E6 ワーカー2台で20件"), ("E5", "E5 DB停止")):
    if ("%s" % exp, "V6") not in rows and (exp, "C") not in rows:
        continue
    p(f"## {title}")
    for s in ("V6", "C"):
        for r, d in rows.get((exp, s), []):
            p(f"- {s} 第{r}回: " + json.dumps(d, ensure_ascii=False, default=str)[:900])
    p("")
open(os.path.join(D, "summary.md"), "w", encoding="utf-8").write("\n".join(out))
print(f"\n保存: {D}/summary.md")
