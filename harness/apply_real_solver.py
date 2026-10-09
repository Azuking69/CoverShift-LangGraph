r"""
バージョンのフォルダに、本物のCP-SATを差し込む(切り替え式)。V1・V2・V4・V6 に使える。
  - <パッケージ>\solver\real_solver.py を置く
  - <パッケージ>\graphs\main_graph.py の solver の import を、「SOLVER=cpsat のとき本物」に書き換える
    (元は main_graph.py.bak に保存。設定なしなら今までどおりダミーで動く)
使い方(PowerShell):
    python harness\apply_real_solver.py covershift_prototype_v6_langgraph
    python harness\apply_real_solver.py covershift_prototype_V4_celery_redis
    python harness\apply_real_solver.py <フォルダのパス>      (もう一度実行しても安全)
元に戻す: main_graph.py.bak を main_graph.py に戻す。
"""
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if len(sys.argv) < 2:
    raise SystemExit("使い方: python harness\\apply_real_solver.py <パッケージのフォルダ>")
pkg = Path(sys.argv[1])
if not pkg.is_absolute():
    for base in (Path.cwd(), HERE.parent, HERE):
        if (base / pkg).is_dir():
            pkg = base / pkg
            break
pkg = pkg.resolve()
graph = pkg / "graphs" / "main_graph.py"
if not graph.is_file() or not (pkg / "solver").is_dir():
    raise SystemExit(f"[エラー] {pkg} に graphs\\main_graph.py と solver\\ が見つかりません。")
src = HERE / "real_solver.py"
if not src.is_file():
    raise SystemExit("[エラー] harness\\real_solver.py がありません(このスクリプトと同じフォルダに置く)。")

text = graph.read_text(encoding="utf-8")
if 'os.getenv("SOLVER"' in text:
    print("すでに切り替え式です。real_solver.py だけ更新します。")
else:
    # ダミー(generate_shift_schedule)型: V1/V2/V6
    m = re.search(r"^from (\S*?)solver\.mock_solver import generate_shift_schedule[ \t]*\r?$", text, re.M)
    if m:
        pre = m.group(1)
        new = ("import os\n"
               "# SOLVER=cpsat のとき、本物のCP-SATを使う(既定は今までどおりダミー)\n"
               'if os.getenv("SOLVER", "mock") == "cpsat":\n'
               f"    from {pre}solver.real_solver import generate_shift_schedule\n"
               "else:\n"
               f"    from {pre}solver.mock_solver import generate_shift_schedule")
    else:
        # V4型: solve_shift_optimization
        m = re.search(r"^from (\S*?)solver\.main_solver import solve_shift_optimization[ \t]*\r?$", text, re.M)
        if not m:
            raise SystemExit("[エラー] main_graph.py に、想定した solver の import 行が見つかりません。手で直す必要があります。")
        pre = m.group(1)
        new = ("import os\n"
               "# SOLVER=cpsat のとき、本物のCP-SAT(人数・日数を設定できる版)を使う(既定は今までどおり)\n"
               'if os.getenv("SOLVER", "mock") == "cpsat":\n'
               f"    from {pre}solver.real_solver import solve_shift_optimization\n"
               "else:\n"
               f"    from {pre}solver.main_solver import solve_shift_optimization")
    bak = graph.with_name("main_graph.py.bak")
    if not bak.exists():
        shutil.copy2(graph, bak)
    graph.write_text(text[:m.start()] + new + text[m.end():], encoding="utf-8")
    print(f"main_graph.py を書き換えました(元: {bak.name})")
shutil.copy2(src, pkg / "solver" / "real_solver.py")
print(f"solver\\real_solver.py を置きました: {pkg}")
print("使う: $env:SOLVER=\"cpsat\" を設定して、いつもの試験を実行(戻す: Remove-Item Env:SOLVER)")
