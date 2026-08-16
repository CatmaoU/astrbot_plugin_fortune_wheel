import os
import time
import asyncio
from typing import Dict, List, Any
from astrbot.api import logger
from ..utils.storage import atomic_write_json, safe_read_json

class CacheManager:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.cache_file = os.path.join(data_dir, "muted_cache.json")
        os.makedirs(data_dir, exist_ok=True)
        self.lock = asyncio.Lock()

    def _load_cache(self) -> Dict:
        return safe_read_json(self.cache_file, {})

    def _save_cache(self, data):
        try:
            atomic_write_json(self.cache_file, data)
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")

    async def add_muted(self, group_id: int, user_id: int, nickname: str, duration_minutes: int, source: str = "lottery"):
        """
        添加禁言记录
        :param source: "lottery" 表示轮盘抽奖禁言，"petition" 表示求情处罚禁言
        """
        async with self.lock:
            cache = self._load_cache()
            gid = str(group_id)
            now = int(time.time())
            expire_time = now + duration_minutes * 60
            entry = {
                "user_id": user_id,
                "nickname": nickname,
                "start_time": now,
                "expire_time": expire_time,
                "source": source
            }
            cache.setdefault(gid, [])
            cache[gid] = [e for e in cache[gid] if e["user_id"] != user_id]
            cache[gid].append(entry)
            self._save_cache(cache)

    async def remove_muted(self, group_id: int, user_id: int):
        async with self.lock:
            cache = self._load_cache()
            gid = str(group_id)
            if gid in cache:
                cache[gid] = [e for e in cache[gid] if e["user_id"] != user_id]
                if not cache[gid]:
                    del cache[gid]
                self._save_cache(cache)

    async def get_muted(self, group_id: int) -> List[Dict]:
        """返回包含 source 字段的禁言列表"""
        cache = self._load_cache()
        gid = str(group_id)
        if gid not in cache:
            return []
        now = int(time.time())
        valid = []
        for entry in cache[gid]:
            if entry["expire_time"] > now:
                valid.append({
                    "user_id": entry["user_id"],
                    "nickname": entry["nickname"],
                    "start_time": entry.get("start_time"),
                    "expire_time": entry["expire_time"],
                    "source": entry.get("source", "lottery")
                })
        if len(valid) != len(cache[gid]):
            cache[gid] = [e for e in cache[gid] if e["expire_time"] > now]
            if not cache[gid]:
                del cache[gid]
            self._save_cache(cache)
        return valid

    async def sync_from_protocol(self, bot, group_id: int) -> bool:
        try:
            members = await bot.call_action("get_group_member_list", group_id=group_id, no_cache=True)
            if isinstance(members, dict) and 'data' in members:
                members = members['data']
            if not members:
                return False
            now = int(time.time())
            muted = []
            for m in members:
                mute_seconds = 0
                if 'mute_time_remaining' in m:
                    mute_seconds = m.get('mute_time_remaining', 0)
                elif 'shut_up_timestamp' in m:
                    ts = m.get('shut_up_timestamp', 0)
                    if ts > now:
                        mute_seconds = ts - now
                elif 'ban_expire_time' in m:
                    ts = m.get('ban_expire_time', 0)
                    if ts > now:
                        mute_seconds = ts - now
                if mute_seconds > 0:
                    nickname = m.get('nickname') or m.get('card') or f"用户{m.get('user_id')}"
                    muted.append({
                        "user_id": m.get('user_id'),
                        "nickname": nickname,
                        "start_time": now,
                        "expire_time": now + mute_seconds,
                        "source": "lottery"
                    })
            async with self.lock:
                cache = self._load_cache()
                gid = str(group_id)
                if muted:
                    cache[gid] = muted
                else:
                    cache.pop(gid, None)
                self._save_cache(cache)
            return True
        except Exception as e:
            logger.error(f"同步缓存失败 (群{group_id}): {e}")
            return False
