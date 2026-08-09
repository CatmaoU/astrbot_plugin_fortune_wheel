import os
import json
import time
from typing import List, Dict, Optional
from astrbot.api import logger

class LotteryHistory:
    def __init__(self, plugin_dir: str, max_records: int = 1000):
        self.cache_dir = os.path.join(plugin_dir, "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.history_file = os.path.join(self.cache_dir, "lottery_history.json")
        self.max_records = max_records
        self._data: Dict[str, List[Dict]] = {}  # user_id_str -> list of records
        self._load()

    def _load(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                logger.info(f"[历史] 加载抽奖历史，共 {len(self._data)} 个用户")
            except Exception as e:
                logger.error(f"[历史] 加载失败: {e}")
                self._data = {}
        else:
            self._data = {}

    def _save(self):
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[历史] 保存失败: {e}")

    def add_record(self, user_id: int, prize: str, duration: str, prob: str):
        """添加一条抽奖记录"""
        uid = str(user_id)
        record = {
            "time": int(time.time()),
            "prize": prize,
            "duration": duration,
            "prob": prob
        }
        if uid not in self._data:
            self._data[uid] = []
        self._data[uid].append(record)
        # 限制最大记录数
        if len(self._data[uid]) > self.max_records:
            self._data[uid] = self._data[uid][-self.max_records:]
        self._save()

    def get_history(self, user_id: int, limit: int = 10) -> List[Dict]:
        """获取某个用户的最近历史记录"""
        uid = str(user_id)
        records = self._data.get(uid, [])
        return records[-limit:] if records else []

    def get_count(self, user_id: int) -> int:
        """获取用户总抽奖次数"""
        uid = str(user_id)
        return len(self._data.get(uid, []))

    def clear_user(self, user_id: int):
        """清除某个用户的所有历史"""
        uid = str(user_id)
        if uid in self._data:
            del self._data[uid]
            self._save()