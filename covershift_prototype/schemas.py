# covershift_prototype/schemas.py
"""
データの形式・型チェック（ルール）
1. 画面(フロントエンド)からデータが届く
    店長が「店舗ID: store-101」を送ってくる。
2. schemas.py(スキーマ)がチェック
    「store-101 は文字型だから受け取りOK!」とデータの形を検証する。
3. LangGraph / ソルバーが処理
    シフト計算や AI 解説文を作成する。
4. DB(データベース)に保存
    確定したシフト結果を DB のテーブルに書き込んで保存する
    (これで明日PCを付けてもデータが残る)
"""
from typing import TypedDict, Optional, Dict, Any
from pydantic import BaseModel


# --- LangGraph 用 State (状態管理) 定義 ---
class CoverShiftState(TypedDict):
    store_id: str
    status: str
    draft_shift: str
    llm_explanation: Optional[str]
    manager_approved: Optional[bool]
    raw_input_names: Dict[str, str]
    retry_count: int


# --- FastAPI 用 リクエストモデル ---
class StartShiftRequest(BaseModel):
    store_id: str

class ResumeShiftRequest(BaseModel):
    thread_id: str
    approved: bool