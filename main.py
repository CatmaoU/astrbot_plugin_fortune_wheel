import os
import asyncio
import time
import json
from datetime import datetime
from typing import Dict
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import At

from .config_manager import ConfigManager
from .mute.pardon import handle_pardon
from .modules.cache_manager import CacheManager
from .modules.curse_manager import CurseManager
from .modules.vote_manager import VoteManager
from .modules.lottery_history import LotteryHistory
from .modules.permission_utils import is_bot_admin, require_permission, check_group_permission
from .utils.message_utils import MessageManager

from ._mixins.core_mixin import CoreMixin
from ._mixins.help_mixin import HelpMixin
from ._mixins.gift_mixin import GiftMixin
from ._mixins.curse_mixin import CurseMixin
from ._mixins.vote_mixin import VoteMixin
from ._mixins.petition_mixin import PetitionMixin
from ._mixins.unmute_mixin import UnmuteMixin


@register(
    "astrbot_plugin_fortune_wheel",
    "iMuli",
    "大礼包轮盘",
    "1.0.6"
)
class GiftLotteryPlugin(Star, CoreMixin, HelpMixin, GiftMixin, CurseMixin, VoteMixin, PetitionMixin, UnmuteMixin):
    def __init__(self, context: Context, **kwargs):
        super().__init__(context)
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_manager = ConfigManager(self.plugin_dir)
        self.config_manager.sync_json_to_txt()

        raw_cfg = self.config_manager.load_config()

        self.show_arrow = raw_cfg.get("show_arrow", True)
        self.enable_sub_wheel = raw_cfg.get("enable_sub_wheel", False)
        self.show_mute_msg = raw_cfg.get("show_mute_msg", True)
        self.main_wheel_delay = float(raw_cfg.get("main_wheel_delay", 6.5))
        self.sub_wheel_delay = float(raw_cfg.get("sub_wheel_delay", 3.0))
        self.mute_delay = float(raw_cfg.get("mute_delay", 1.5))
        self.main_wheel_duration = float(raw_cfg.get("main_wheel_duration", 7.0))
        self.sub_wheel_duration = float(raw_cfg.get("sub_wheel_duration", 3.0))

        self.pardon_enabled = raw_cfg.get("pardon_enabled", True)
        self.bot_name = raw_cfg.get("bot_name", "小号") or "小号"
        self.pardon_command = "求饶"
        raw_stages = raw_cfg.get("pardon_stages", ["1:12.5", "2:25", "3:50"])
        self.pardon_probabilities = []
        for item in raw_stages:
            if isinstance(item, str) and ":" in item:
                parts = item.split(":", 1)
                try:
                    self.pardon_probabilities.append(float(parts[1].strip()))
                except:
                    continue
        if not self.pardon_probabilities:
            self.pardon_probabilities = [12.5, 25, 50]
        self.pardon_attempts = len(self.pardon_probabilities)
        self.user_pardon_data = {}

        self.cache_mgr = CacheManager(self.plugin_dir)

        self.curse_mgr = CurseManager(
            self.plugin_dir,
            enabled=raw_cfg.get("curse_enabled", True),
            max_marks=int(raw_cfg.get("curse_max_marks", 5)),
            trigger_base_prob=float(raw_cfg.get("curse_trigger_base_prob", 5.0)),
            trigger_prob_increment=float(raw_cfg.get("curse_trigger_prob_increment", 10.0)),
            low_weight_bonus=float(raw_cfg.get("curse_low_weight_bonus", 20.0)),
            trigger_weight_bonus=float(raw_cfg.get("curse_trigger_weight_bonus", 50.0)),
            daily_limit=int(raw_cfg.get("curse_daily_limit", 1))
        )
        self.curse_transfer_success_rate = float(raw_cfg.get("curse_transfer_success_rate", 0.5))
        self.global_admins = raw_cfg.get("global_admins", [])

        self.help_gift_enabled = raw_cfg.get("help_gift_enabled", True)
        self.help_gift_success_rate = float(raw_cfg.get("help_gift_success_rate", 0.15))
        self.help_gift_penalty_multiplier = float(raw_cfg.get("help_gift_penalty_multiplier", 1.0))

        self.vote_mgr = VoteManager(
            required_agree=int(raw_cfg.get("vote_required_agree", 2)),
            duration_seconds=int(raw_cfg.get("vote_duration_seconds", 120))
        )
        self.gif_loop = raw_cfg.get("gif_loop", True)
        self.auto_sync_interval = int(raw_cfg.get("auto_sync_interval", 300))

        self.daily_lottery_limit = int(raw_cfg.get("daily_lottery_limit", -1))
        self.command_cooldown_seconds = float(raw_cfg.get("command_cooldown_seconds", 15.0))
        self.group_mode = raw_cfg.get("group_mode", "blacklist")
        self.group_list = raw_cfg.get("group_list", [])
        self.petition_enabled = raw_cfg.get("petition_enabled", True)

        self.message_mgr = MessageManager(raw_cfg)

        self.lottery_history = LotteryHistory(self.plugin_dir)

        self._last_command_time: Dict[int, float] = {}

        self._daily_lottery_count_file = os.path.join(self.plugin_dir, "cache", "daily_lottery_count.json")
        self._daily_lottery_count: Dict[str, int] = {}
        self._load_daily_count()

        self._petition_helpers_file = os.path.join(self.plugin_dir, "cache", "petition_helpers.json")
        self.petition_helpers = set()
        self._load_petition_helpers()

        self._bot = None
        try:
            self._bot = self.context.platform.bot
            logger.info("[缓存] 成功获取后台 Bot 实例")
        except AttributeError:
            logger.warning("[缓存] 无法获取后台 Bot 实例，自动刷新将禁用")

        self._auto_sync_task = None
        self._stop_auto_sync = asyncio.Event()
        if self._bot and self.auto_sync_interval > 0:
            self._start_auto_sync()
        else:
            if self.auto_sync_interval <= 0:
                logger.info("[缓存] 自动刷新已禁用（间隔设为0）")
            else:
                logger.warning("[缓存] 自动刷新已禁用（无 Bot 实例）")

    def get_message(self, key: str, default: str = "", **kwargs) -> str:
        """重写消息获取，统一使用 MessageManager"""
        return self.message_mgr.get_message(key, default, **kwargs)

    def _load_help(self) -> str:
        return HelpMixin._load_help(self)

    # ==================== 指令定义 ====================
    @filter.command("大礼包", alias={"抽奖", "幸运轮盘"}, desc="弹出轮盘随机抽取禁言时长并执行禁言")
    async def mute_lottery(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result(self.get_message("command_group_only", default="此指令仅可在群聊中使用喵"))
            return
        if not self._check_group_permission(group_id):
            yield event.plain_result(self.get_message("group_blocked", default="本群暂未开放此功能喵～"))
            return
        sender_id = event.get_sender_id()
        cooldown = self._check_cooldown(sender_id)
        if cooldown:
            yield event.plain_result(self.get_message("command_cooldown", seconds=round(cooldown, 1), default="操作过于频繁喵，请 {seconds} 秒后再试～"))
            return
        if not self._check_daily_limit(sender_id):
            limit = self.daily_lottery_limit
            yield event.plain_result(self.get_message("lottery_daily_limit_reached", limit=limit, default="你今天已经抽了 {limit} 次大礼包喵，明天再来吧～"))
            return
        async for msg in self.mute_lottery_logic(event):
            yield msg
        self._increment_daily_count(sender_id)

    @filter.command("诅咒", desc="设置全局诅咒或转移诅咒给指定用户（每日有限制）")
    async def curse(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id
        if group_id and not self._check_group_permission(group_id):
            yield event.plain_result(self.get_message("group_blocked", default="本群暂未开放此功能喵～"))
            return
        async for msg in self.curse_logic(event):
            yield msg

    @filter.command("诅咒状态", desc="查看当前群诅咒详情")
    async def curse_status(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id
        if group_id and not self._check_group_permission(group_id):
            yield event.plain_result(self.get_message("group_blocked", default="本群暂未开放此功能喵～"))
            return
        async for msg in self.curse_status_logic(event):
            yield msg

    @filter.command("清除诅咒", desc="管理员清除当前群的全局诅咒或指定用户的标记")
    @require_permission(lambda self: self.global_admins)
    async def clear_curse(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id
        if group_id and not self._check_group_permission(group_id):
            yield event.plain_result(self.get_message("group_blocked", default="本群暂未开放此功能喵～"))
            return
        async for msg in self.clear_curse_logic(event):
            yield msg

    @filter.command("随机诅咒", desc="随机选中一个用户进行诅咒，自己获得一半的全局累计诅咒标记")
    async def random_curse(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id
        if group_id and not self._check_group_permission(group_id):
            yield event.plain_result(self.get_message("group_blocked", default="本群暂未开放此功能喵～"))
            return
        async for msg in self.random_curse_logic(event):
            yield msg

    @filter.command("诅咒排行榜", desc="查看本群被诅咒最多的人及总禁言时长")
    async def curse_ranking(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id
        if group_id and not self._check_group_permission(group_id):
            yield event.plain_result(self.get_message("group_blocked", default="本群暂未开放此功能喵～"))
            return
        async for msg in self.curse_ranking_logic(event):
            yield msg

    @filter.command("放过", alias={"解禁", "取消禁言"}, desc="查看/发起解禁投票（管理员直接解禁）")
    async def admin_pardon(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id
        if group_id and not self._check_group_permission(group_id):
            yield event.plain_result(self.get_message("group_blocked", default="本群暂未开放此功能喵～"))
            return
        async for msg in self.admin_pardon_logic(event):
            yield msg

    @filter.command("同意", desc="在投票中投同意票")
    async def vote_agree(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id
        if group_id and not self._check_group_permission(group_id):
            yield event.plain_result(self.get_message("group_blocked", default="本群暂未开放此功能喵～"))
            return
        async for msg in self.vote_agree_logic(event):
            yield msg

    @filter.command("不同意", desc="在投票中投反对票")
    async def vote_disagree(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id
        if group_id and not self._check_group_permission(group_id):
            yield event.plain_result(self.get_message("group_blocked", default="本群暂未开放此功能喵～"))
            return
        async for msg in self.vote_disagree_logic(event):
            yield msg

    @filter.command("刷新缓存", desc="从服务器同步最新禁言列表（仅管理员）")
    @require_permission(lambda self: self.global_admins)
    async def refresh_cache(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id
        if group_id and not self._check_group_permission(group_id):
            yield event.plain_result(self.get_message("group_blocked", default="本群暂未开放此功能喵～"))
            return
        if not group_id:
            yield event.plain_result(self.get_message("refresh_cache_group_only", default="此指令仅可在群聊中使用喵"))
            return
        self_id = event.get_self_id()
        if not self_id:
            yield event.plain_result(self.get_message("refresh_cache_no_self", default="无法获取机器人自身信息喵～"))
            return
        if not await is_bot_admin(event.bot, group_id, self_id):
            yield event.plain_result(self.get_message("refresh_cache_bot_no_admin", default="机器人没有本群管理员权限，无法获取禁言列表喵～"))
            return

        yield event.plain_result(self.get_message("refresh_cache_start", default="正在从服务器同步禁言列表喵～"))
        success = await self.cache_mgr.sync_from_protocol(event.bot, group_id)
        if success:
            muted = await self.cache_mgr.get_muted(group_id)
            if muted:
                lines = [self.get_message("refresh_cache_success", default="缓存已刷新，当前被禁言用户：")]
                for idx, u in enumerate(muted, 1):
                    start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(u["start_time"]))
                    end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(u["expire_time"]))
                    lines.append(f"{idx}. {u['nickname']} ({u['user_id']}) 开始: {start_str} 结束: {end_str}")
                yield event.plain_result("\n".join(lines))
            else:
                yield event.plain_result(self.get_message("refresh_cache_empty", default="缓存已刷新，当前没有被禁言的用户喵～"))
        else:
            yield event.plain_result(self.get_message("refresh_cache_fail", default="刷新缓存失败，请检查日志喵～"))

    @filter.command("求饶", alias={"饶命", "救命"}, desc="私聊机器人尝试解除自己的禁言（概率递增）")
    async def pardon(self, event: AstrMessageEvent):
        async for msg in handle_pardon(event, self):
            yield msg

    @filter.command("求情", desc="替他人求情解除禁言（普通用户承担一半时间，管理员无惩罚）")
    async def petition(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id
        if group_id and not self._check_group_permission(group_id):
            yield event.plain_result(self.get_message("group_blocked", default="本群暂未开放此功能喵～"))
            return
        if not getattr(self, 'petition_enabled', True):
            yield event.plain_result("求情系统目前已关闭喵～")
            return
        async for msg in self.petition_logic(event):
            yield msg

    @filter.command("全部解除", alias={"解除全部", "全解"}, desc="管理员一键解除当前群所有被禁言用户")
    @require_permission(lambda self: self.global_admins)
    async def admin_unmute_all(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id
        if group_id and not self._check_group_permission(group_id):
            yield event.plain_result(self.get_message("group_blocked", default="本群暂未开放此功能喵～"))
            return
        async for msg in self.admin_unmute_all_logic(event):
            yield msg

    @filter.command("大礼包历史", alias={"抽奖历史", "历史记录"}, desc="查看自己的抽奖历史记录")
    async def lottery_history_cmd(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id
        if group_id and not self._check_group_permission(group_id):
            yield event.plain_result(self.get_message("group_blocked", default="本群暂未开放此功能喵～"))
            return
        target_id = event.get_sender_id()
        target_name = event.get_sender_name() or str(target_id)
        for comp in event.message_obj.message:
            if isinstance(comp, At):
                target_id = comp.qq
                try:
                    info = await event.bot.call_action(
                        "get_group_member_info",
                        group_id=group_id,
                        user_id=target_id,
                        no_cache=True
                    )
                    target_name = info.get('nickname') or info.get('card') or str(target_id)
                except:
                    target_name = str(target_id)
                break
        records = self.lottery_history.get_history(target_id, limit=10)
        if not records:
            yield event.plain_result(self.get_message("lottery_history_empty", default="没有抽奖记录喵～"))
            return
        lines = [self.get_message("lottery_history_title", user=target_name, default="【{user}的抽奖历史】")]
        for idx, rec in enumerate(reversed(records), 1):
            time_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(rec["time"]))
            lines.append(self.get_message("lottery_history_item",
                idx=idx,
                time=time_str,
                prize=rec.get("prize", "未知"),
                duration=rec.get("duration", "0"),
                default="{idx}. {time} → {prize}（{duration}）"
            ))
        total = self.lottery_history.get_count(target_id)
        lines.append(self.get_message("lottery_history_footer", total=total, show=len(records), default="共 {total} 条记录，显示最近 {show} 条"))
        yield event.plain_result("\n".join(lines))

    @filter.command("重载配置", desc="热重载配置文件（无需重启）")
    @require_permission(lambda self: self.global_admins)
    async def reload_config_cmd(self, event: AstrMessageEvent):
        try:
            new_cfg = self.config_manager.reload_config()
            self.show_arrow = new_cfg.get("show_arrow", True)
            self.enable_sub_wheel = new_cfg.get("enable_sub_wheel", False)
            self.show_mute_msg = new_cfg.get("show_mute_msg", True)
            self.main_wheel_delay = float(new_cfg.get("main_wheel_delay", 6.5))
            self.sub_wheel_delay = float(new_cfg.get("sub_wheel_delay", 3.0))
            self.mute_delay = float(new_cfg.get("mute_delay", 1.5))
            self.main_wheel_duration = float(new_cfg.get("main_wheel_duration", 7.0))
            self.sub_wheel_duration = float(new_cfg.get("sub_wheel_duration", 3.0))
            self.pardon_enabled = new_cfg.get("pardon_enabled", True)
            self.bot_name = new_cfg.get("bot_name", "小号") or "小号"
            self.pardon_command = "求饶"
            raw_stages = new_cfg.get("pardon_stages", ["1:12.5", "2:25", "3:50"])
            self.pardon_probabilities = []
            for item in raw_stages:
                if isinstance(item, str) and ":" in item:
                    parts = item.split(":", 1)
                    try:
                        self.pardon_probabilities.append(float(parts[1].strip()))
                    except:
                        continue
            if not self.pardon_probabilities:
                self.pardon_probabilities = [12.5, 25, 50]
            self.pardon_attempts = len(self.pardon_probabilities)
            self.curse_transfer_success_rate = float(new_cfg.get("curse_transfer_success_rate", 0.5))
            self.global_admins = new_cfg.get("global_admins", [])
            self.help_gift_enabled = new_cfg.get("help_gift_enabled", True)
            self.help_gift_success_rate = float(new_cfg.get("help_gift_success_rate", 0.15))
            self.help_gift_penalty_multiplier = float(new_cfg.get("help_gift_penalty_multiplier", 1.0))
            self.gif_loop = new_cfg.get("gif_loop", True)
            self.auto_sync_interval = int(new_cfg.get("auto_sync_interval", 300))
            self.daily_lottery_limit = int(new_cfg.get("daily_lottery_limit", -1))
            self.command_cooldown_seconds = float(new_cfg.get("command_cooldown_seconds", 15.0))
            self.group_mode = new_cfg.get("group_mode", "blacklist")
            self.group_list = new_cfg.get("group_list", [])
            self.petition_enabled = new_cfg.get("petition_enabled", True)
            self.vote_mgr.required_agree = int(new_cfg.get("vote_required_agree", 2))
            self.vote_mgr.duration_seconds = int(new_cfg.get("vote_duration_seconds", 120))
            self.curse_mgr.enabled = new_cfg.get("curse_enabled", True)
            self.curse_mgr.max_marks = int(new_cfg.get("curse_max_marks", 5))
            self.curse_mgr.trigger_base_prob = float(new_cfg.get("curse_trigger_base_prob", 5.0))
            self.curse_mgr.trigger_prob_increment = float(new_cfg.get("curse_trigger_prob_increment", 10.0))
            self.curse_mgr.low_weight_bonus_per_mark = float(new_cfg.get("curse_low_weight_bonus", 20.0))
            self.curse_mgr.trigger_weight_bonus = float(new_cfg.get("curse_trigger_weight_bonus", 50.0))
            self.curse_mgr.daily_limit = int(new_cfg.get("curse_daily_limit", 1))
            self.message_mgr = MessageManager(new_cfg)
            from .modules.prize_loader import _cached_prizes, _cached_time
            global _cached_prizes, _cached_time
            _cached_prizes = None
            _cached_time = 0
            yield event.plain_result("✅ 配置重载成功喵！")
        except Exception as e:
            logger.error(f"重载配置失败: {e}")
            yield event.plain_result(f"❌ 重载配置失败：{e}")

    async def stop(self):
        if self._auto_sync_task and not self._auto_sync_task.done():
            self._stop_auto_sync.set()
            self._auto_sync_task.cancel()
            try:
                await self._auto_sync_task
            except asyncio.CancelledError:
                pass
            logger.info("[缓存] 自动刷新任务已停止")