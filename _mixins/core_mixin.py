import os
import asyncio
import time
from datetime import datetime
from typing import Dict, List, Optional
from astrbot.api import logger
from ..modules.permission_utils import is_bot_admin, check_group_permission
from ..utils.storage import atomic_write_json, safe_read_json


class CoreMixin:
    """核心功能 Mixin：禁言/解禁、冷却、每日限制、求情者管理、自动同步等"""

    # ==================== 清理临时文件 ====================
    async def _cleanup_files(self, paths: list):
        for p in paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception as e:
                logger.warning(f"清理临时文件失败 {p}: {e}")

    # ==================== 每日抽奖计数 ====================
    def _load_daily_count(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data = safe_read_json(self._daily_lottery_count_file, {})
        if data.get("date") != today or "counts" not in data:
            self._daily_lottery_count = {"date": today, "counts": {}}
        else:
            self._daily_lottery_count = data

    def _save_daily_count(self):
        try:
            atomic_write_json(self._daily_lottery_count_file, self._daily_lottery_count)
        except Exception as e:
            logger.error(f"保存每日抽奖计数失败: {e}")

    def _check_daily_limit(self, user_id: int) -> bool:
        if self.daily_lottery_limit == -1:
            return True
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_lottery_count.get("date") != today:
            self._daily_lottery_count = {"date": today, "counts": {}}
        uid = str(user_id)
        used = self._daily_lottery_count["counts"].get(uid, 0)
        return used < self.daily_lottery_limit

    def _increment_daily_count(self, user_id: int):
        if self.daily_lottery_limit == -1:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_lottery_count.get("date") != today:
            self._daily_lottery_count = {"date": today, "counts": {}}
        uid = str(user_id)
        self._daily_lottery_count["counts"][uid] = self._daily_lottery_count["counts"].get(uid, 0) + 1
        self._save_daily_count()

    def _get_daily_used(self, user_id: int) -> int:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_lottery_count.get("date") != today:
            return 0
        return self._daily_lottery_count["counts"].get(str(user_id), 0)

    # ==================== 冷却检查 ====================
    def _check_cooldown(self, user_id: int) -> Optional[float]:
        now = time.time()
        last = self._last_command_time.get(user_id, 0)
        if last and (now - last) < self.command_cooldown_seconds:
            return self.command_cooldown_seconds - (now - last)
        self._last_command_time[user_id] = now
        return None

    # ==================== 主动求情者名单 ====================
    def _load_petition_helpers(self):
        data = safe_read_json(self._petition_helpers_file, [])
        self.petition_helpers = set(data) if isinstance(data, list) else set()
        if self.petition_helpers:
            logger.info(f"[求情] 加载主动求情者名单，共 {len(self.petition_helpers)} 人")

    def _save_petition_helpers(self):
        try:
            atomic_write_json(self._petition_helpers_file, list(self.petition_helpers))
        except Exception as e:
            logger.error(f"[求情] 保存主动求情者名单失败: {e}")

    def _mark_as_petition_helper(self, user_id: int):
        if user_id not in self.petition_helpers:
            self.petition_helpers.add(user_id)
            self._save_petition_helpers()
            logger.debug(f"[求情] 用户 {user_id} 被标记为主动求情者")

    def _clear_petition_helper(self, user_id: int):
        if user_id in self.petition_helpers:
            self.petition_helpers.remove(user_id)
            self._save_petition_helpers()
            logger.debug(f"[求情] 用户 {user_id} 的主动求情限制已解除")

    def _is_petition_helper(self, user_id: int) -> bool:
        return user_id in self.petition_helpers

    # ==================== 核心禁言/解禁方法 ====================
    async def _execute_mute_with_cache(self, event, group_id: int, user_id: int, duration_minutes: int,
                                       source: str = "lottery", *, bot=None, self_id=None):
        """执行禁言并更新缓存。bot/self_id 可显式传入（用于延迟任务，避免 event 失效）。"""
        if duration_minutes <= 0:
            return False, "禁言时间必须大于0"
        bot = bot if bot is not None else event.bot
        sid = self_id if self_id is not None else event.get_self_id()
        try:
            await asyncio.wait_for(
                bot.set_group_ban(
                    group_id=group_id,
                    user_id=user_id,
                    duration=duration_minutes * 60,
                    self_id=sid
                ),
                timeout=10.0
            )
            try:
                info = await asyncio.wait_for(
                    bot.call_action(
                        "get_group_member_info",
                        group_id=group_id,
                        user_id=user_id,
                        no_cache=True
                    ),
                    timeout=10.0
                )
                nickname = info.get('nickname') or info.get('card') or f"用户{user_id}"
            except Exception:
                nickname = f"用户{user_id}"
            await self.cache_mgr.add_muted(group_id, user_id, nickname, duration_minutes, source)
            self._reset_pardon_data(user_id)
            if source != "petition":
                self._clear_petition_helper(user_id)
            return True, None
        except asyncio.TimeoutError:
            return False, "操作超时"
        except Exception as e:
            return False, str(e)

    async def _execute_unmute(self, event, group_id: int, user_id: int, source: str = "",
                              *, bot=None, self_id=None):
        """解除禁言并更新缓存。bot/self_id 可显式传入（用于延迟任务，避免 event 失效）。"""
        bot = bot if bot is not None else event.bot
        sid = self_id if self_id is not None else event.get_self_id()
        try:
            await asyncio.wait_for(
                bot.set_group_ban(
                    group_id=group_id,
                    user_id=user_id,
                    duration=0,
                    self_id=sid
                ),
                timeout=10.0
            )
            await asyncio.sleep(0.5)
            await self.cache_mgr.remove_muted(group_id, user_id)
            self._reset_pardon_data(user_id)
            return True, None
        except asyncio.TimeoutError:
            return False, "操作超时"
        except Exception as e:
            return False, str(e)

    def _reset_pardon_data(self, user_id: int):
        today = datetime.now().strftime("%Y-%m-%d")
        if user_id not in self.user_pardon_data:
            self.user_pardon_data[user_id] = {
                "remaining": self.pardon_attempts,
                "used": 0,
                "last_reset_date": today
            }
        else:
            self.user_pardon_data[user_id]["remaining"] = self.pardon_attempts
            self.user_pardon_data[user_id]["used"] = 0
            self.user_pardon_data[user_id]["last_reset_date"] = today

    # ==================== 自动同步 ====================
    def _start_auto_sync(self):
        if self._auto_sync_task is None or self._auto_sync_task.done():
            self._stop_auto_sync.clear()
            self._auto_sync_task = asyncio.create_task(self._auto_sync_loop())
            logger.info(f"[缓存] 自动刷新任务已启动（间隔 {self.auto_sync_interval} 秒）")

    async def _auto_sync_loop(self):
        while not self._stop_auto_sync.is_set():
            try:
                await asyncio.sleep(self.auto_sync_interval)
                if self._stop_auto_sync.is_set():
                    break
                group_list = await self._get_group_list(self._bot)
                if not group_list:
                    continue
                synced = 0
                for g in group_list:
                    gid = g.get("group_id")
                    if not gid:
                        continue
                    if await is_bot_admin(self._bot, gid):
                        await self.cache_mgr.sync_from_protocol(self._bot, gid)
                        synced += 1
                        await asyncio.sleep(0.2)
                logger.info(f"[缓存] 自动刷新完成，共 {synced} 个群")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[缓存] 自动刷新异常: {e}")

    async def _get_group_list(self, bot) -> List[Dict]:
        try:
            result = await asyncio.wait_for(bot.call_action("get_group_list"), timeout=10.0)
            if isinstance(result, dict) and 'data' in result:
                return result['data']
            elif isinstance(result, list):
                return result
            return []
        except asyncio.TimeoutError:
            logger.warning("获取群列表超时")
            return []
        except Exception as e:
            logger.error(f"获取群列表失败: {e}")
            return []

    # ==================== 群组权限检查 ====================
    def _check_group_permission(self, group_id: int) -> bool:
        return check_group_permission(group_id, self.group_mode, self.group_list)
