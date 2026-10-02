"""
モックのソルバー(計算はせず、決まったダミーを返す)。
v2: MOCK_SOLVER_SLEEP を設定すると、その秒数だけ待つ(本物のCP-SATが数秒かかる状況を再現するため)。
※ pyc から復元した版。ダミーの値は元の文字列に合わせたが、辞書のキー名は推測。
"""
import time
from typing import Dict, Any
from ..config import MOCK_SOLVER_SLEEP


# generate_shift_schedule: モックのシフト案を返す関数
def generate_shift_schedule(store_id: str) -> Dict[str, Any]:
    if MOCK_SOLVER_SLEEP > 0:
        time.sleep(MOCK_SOLVER_SLEEP)
        
    return {
        "draft_shift": "10/02(金) Aさん: 早番, Bさん: 遅番",
        "raw_input_names": {"スタッフA": "山田太郎", "スタッフB": "佐藤花子"},
    }
