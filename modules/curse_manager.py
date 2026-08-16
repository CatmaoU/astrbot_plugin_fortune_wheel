import os
import asyncio
from datetime import datetime
from typing import Dict, Tuple, List
from astrbot.api import logger
from ..utils.storage import atomic_write_json, safe_read_json

class CurseManager:
    def __init__(self, data_dir: str, enabled: bool = True, 
                 max_marks: int = 5,
                 trigger_base_prob: float = 5.0,
                 trigger_prob_increment: float = 10.0,
                 low_weight_bonus: float = 20.0,
                 trigger_weight_bonus: float = 50.0,
                 daily_limit: int = 1):
        self.enabled = enabled
        self.max_marks = max_marks
        self.trigger_base_prob = trigger_base_prob
        self.trigger_prob_increment = trigger_prob_increment
        self.low_weight_bonus_per_mark = low_weight_bonus
        self.trigger_weight_bonus = trigger_weight_bonus
        self.daily_limit = daily_limit

        self.data_dir = data_dir
        self.cache_file = os.path.join(data_dir, "curse_data.json")
        os.makedirs(data_dir, exist_ok=True)
        self.lock = asyncio.Lock()
        self._data = {}

        self._load_data()
        self._check_reset_daily()

    def _load_data(self):
        if not self.enabled:
            return
        if os.path.exists(self.cache_file):
            data = safe_read_json(self.cache_file, {})
            if isinstance(data, dict):
                self._data = data
                logger.info(f"[诅咒] 从缓存加载数据，共 {len(self._data)} 个群")
            else:
                self._data = {}
                logger.error(f"[诅咒] 缓存数据格式非法，已重置")
        else:
            self._data = {}

    def _save_data(self):
        if not self.enabled:
            return
        try:
            atomic_write_json(self.cache_file, self._data)
            logger.debug("[诅咒] 数据已保存")
        except Exception as e:
            logger.error(f"[诅咒] 保存缓存失败: {e}")

    def _ensure_group(self, group_id: int):
        gid = str(group_id)
        if gid not in self._data:
            self._data[gid] = {
                "global": False,
                "low_bonus": 0.0,
                "users": {},
                "daily_usage": {},
                "total_curse_count": 0,
                "last_reset_date": datetime.now().strftime("%Y-%m-%d")
            }

    def _ensure_user(self, group_id: int, user_id: int):
        gid = str(group_id)
        uid = str(user_id)
        self._ensure_group(group_id)
        if uid not in self._data[gid]["users"]:
            self._data[gid]["users"][uid] = {
                "marks": 0,
                "total_mute_minutes": 0
            }

    def _check_reset_daily(self):
        """检查日期是否变化，重置 daily_usage"""
        today = datetime.now().strftime("%Y-%m-%d")
        for gid in self._data:
            if self._data[gid].get("last_reset_date") != today:
                self._data[gid]["daily_usage"] = {}
                self._data[gid]["last_reset_date"] = today
        self._save_data()

    # ---------- 公开接口 ----------
    async def reset_daily(self):
        """手动重置每日使用计数（通常由定时任务调用）"""
        async with self.lock:
            self._check_reset_daily()

    async def set_global_curse(self, group_id: int) -> bool:
        if not self.enabled:
            return False
        async with self.lock:
            gid = str(group_id)
            self._ensure_group(group_id)
            self._data[gid]["global"] = True
            self._save_data()
            logger.info(f"[诅咒] 群 {group_id} 设置全局诅咒")
            return True

    async def get_and_clear_global_curse(self, group_id: int) -> bool:
        if not self.enabled:
            return False
        async with self.lock:
            gid = str(group_id)
            if gid not in self._data:
                return False
            if self._data[gid].get("global", False):
                self._data[gid]["global"] = False
                self._save_data()
                return True
            return False

    async def add_mark(self, group_id: int, user_id: int, count: int = 1) -> Tuple[bool, float]:
        if not self.enabled or count <= 0:
            return False, 0.0
        async with self.lock:
            gid = str(group_id)
            uid = str(user_id)
            self._ensure_user(group_id, user_id)
            old_marks = self._data[gid]["users"][uid]["marks"]
            new_marks = old_marks + count
            self._data[gid]["users"][uid]["marks"] = new_marks

            high_triggered = False
            bonus_added = 0.0
            # ★ 只在首次达到阈值时触发一次
            if old_marks < self.max_marks and new_marks >= self.max_marks:
                high_triggered = True
                self._data[gid]["low_bonus"] = self._data[gid].get("low_bonus", 0.0) + self.low_weight_bonus_per_mark
                bonus_added = self.low_weight_bonus_per_mark
                logger.info(f"[诅咒] 用户 {user_id} 首次达到 {self.max_marks} 标记，触发高级诅咒，低权重加成 +{self.low_weight_bonus_per_mark}")

            self._save_data()
            return high_triggered, bonus_added

    async def remove_mark(self, group_id: int, user_id: int, count: int = 1) -> int:
        if not self.enabled or count <= 0:
            return 0
        async with self.lock:
            gid = str(group_id)
            uid = str(user_id)
            if gid not in self._data or uid not in self._data[gid]["users"]:
                return 0
            old = self._data[gid]["users"][uid]["marks"]
            new = max(0, old - count)
            self._data[gid]["users"][uid]["marks"] = new
            self._save_data()
            return new

    async def clear_user_marks(self, group_id: int, user_id: int) -> bool:
        if not self.enabled:
            return False
        async with self.lock:
            gid = str(group_id)
            uid = str(user_id)
            if gid in self._data and uid in self._data[gid]["users"]:
                self._data[gid]["users"][uid]["marks"] = 0
                self._save_data()
                return True
            return False

    async def get_marks(self, group_id: int, user_id: int) -> int:
        if not self.enabled:
            return 0
        gid = str(group_id)
        uid = str(user_id)
        if gid not in self._data or uid not in self._data[gid]["users"]:
            return 0
        return self._data[gid]["users"][uid]["marks"]

    async def get_trigger_probability(self, group_id: int, user_id: int) -> float:
        if not self.enabled:
            return 0.0
        marks = await self.get_marks(group_id, user_id)
        if marks == 0:
            return 0.0
        prob = self.trigger_base_prob + (marks - 1) * self.trigger_prob_increment
        return min(100.0, prob)

    async def get_low_bonus(self, group_id: int) -> float:
        if not self.enabled:
            return 0.0
        gid = str(group_id)
        if gid not in self._data:
            return 0.0
        return self._data[gid].get("low_bonus", 0.0)

    async def get_global_curse_status(self, group_id: int) -> bool:
        if not self.enabled:
            return False
        gid = str(group_id)
        if gid not in self._data:
            return False
        return self._data[gid].get("global", False)

    async def get_group_data(self, group_id: int) -> Dict:
        gid = str(group_id)
        if gid not in self._data:
            return {}
        return self._data[gid].copy()

    async def clear_group_curse(self, group_id: int) -> bool:
        if not self.enabled:
            return False
        async with self.lock:
            gid = str(group_id)
            if gid in self._data:
                del self._data[gid]
                self._save_data()
                return True
            return False

    # ---------- 新增功能 ----------
    async def check_daily_limit(self, group_id: int, user_id: int) -> Tuple[bool, int]:
        if not self.enabled or self.daily_limit <= 0:
            return True, 999
        # 每次检查前先重置日期（如果日期变化）
        self._check_reset_daily()
        gid = str(group_id)
        uid = str(user_id)
        self._ensure_group(group_id)
        daily = self._data[gid].get("daily_usage", {})
        used = daily.get(uid, 0)
        remaining = self.daily_limit - used
        return remaining > 0, remaining

    async def record_curse_usage(self, group_id: int, user_id: int) -> int:
        if not self.enabled:
            return 0
        async with self.lock:
            # 添加日期检查
            self._check_reset_daily()
            gid = str(group_id)
            uid = str(user_id)
            self._ensure_group(group_id)
            daily = self._data[gid].get("daily_usage", {})
            used = daily.get(uid, 0) + 1
            daily[uid] = used
            self._data[gid]["daily_usage"] = daily
            self._data[gid]["total_curse_count"] = self._data[gid].get("total_curse_count", 0) + 1
            self._save_data()
            return used

    async def get_total_curse_count(self, group_id: int) -> int:
        gid = str(group_id)
        if gid not in self._data:
            return 0
        return self._data[gid].get("total_curse_count", 0)

    async def reset_total_curse_count(self, group_id: int) -> bool:
        async with self.lock:
            gid = str(group_id)
            if gid in self._data:
                self._data[gid]["total_curse_count"] = 0
                self._save_data()
                return True
            return False

    async def add_mute_duration(self, group_id: int, user_id: int, minutes: int):
        if not self.enabled or minutes <= 0:
            return
        async with self.lock:
            gid = str(group_id)
            uid = str(user_id)
            self._ensure_user(group_id, user_id)
            self._data[gid]["users"][uid]["total_mute_minutes"] += minutes
            self._save_data()

    async def get_ranking(self, group_id: int) -> List[Dict]:
        gid = str(group_id)
        if gid not in self._data:
            return []
        users = self._data[gid].get("users", {})
        ranking = []
        for uid, data in users.items():
            ranking.append({
                "user_id": int(uid),
                "marks": data.get("marks", 0),
                "total_mute_minutes": data.get("total_mute_minutes", 0)
            })
        ranking.sort(key=lambda x: x["marks"], reverse=True)
        return ranking