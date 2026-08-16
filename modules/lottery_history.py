import os
import time
import asyncio
from typing import List, Dict, Optional
from astrbot.api import logger
from ..utils.storage import atomic_write_json, safe_read_json

class LotteryHistory:
    def __init__(self, data_dir: str, max_records: int = 1000):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.history_file = os.path.join(data_dir, "lottery_history.json")
        self.max_records = max_records
        self.lock = asyncio.Lock()
        self._data: Dict[str, List[Dict]] = {}  # user_id_str -> list of records
        self._load()

    def _load(self):
        data = safe_read_json(self.history_file, {})
        if isinstance(data, dict):
            self._data = data
            if data:
                logger.info(f"[历史] 加载抽奖历史，共 {len(self._data)} 个用户")
        else:
            self._data = {}

    def _save(self):
        try:
            atomic_write_json(self.history_file, self._data)
        except Exception as e:
            logger.error(f"[历史] 保存失败: {e}")

    async def add_record(self, user_id: int, prize: str, duration: str, prob: str):
        """添加一条抽奖记录（异步 + 加锁，防止并发覆盖丢失记录）"""
        async with self.lock:
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
