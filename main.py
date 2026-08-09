import os
import asyncio
import time
import json
from datetime import datetime
from typing import List, Dict, Optional
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

from .config_manager import ConfigManager
from .mute.pardon import handle_pardon
from .modules.cache_manager import CacheManager
from .modules.curse_manager import CurseManager
from .modules.vote_manager import VoteManager
from .modules.permission_utils import is_bot_admin, require_permission, check_group_permission
from .utils.message_utils import MessageManager
from .utils.lottery_history import LotteryHistory

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
    "1.0.4"
)
class GiftLotteryPlugin(Star, HelpMixin, GiftMixin, CurseMixin, VoteMixin, PetitionMixin, UnmuteMixin):
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
        self.help_gift_penalty_multiplier = float(raw_cfg.get("help_gift_penalty_multiplier", 2.0))

        self.vote_mgr = VoteManager(
            required_agree=int(raw_cfg.get("vote_required_agree", 2)),
            duration_seconds=int(raw_cfg.get("vote_duration_seconds", 120))
        )
        self.gif_loop = raw_cfg.get("gif_loop", True)
        self.auto_sync_interval = int(raw_cfg.get("auto_sync_interval", 300))

        # ★ 新增配置
        self.daily_lottery_limit = int(raw_cfg.get("daily_lottery_limit", -1))
        self.command_cooldown_seconds = float(raw_cfg.get("command_cooldown_seconds", 15.0))
        self.group_mode = raw_cfg.get("group_mode", "blacklist")
        self.group_list = raw_cfg.get("group_list", [])

        self.message_mgr = MessageManager(raw_cfg)

        # ★ 抽奖历史
        self.lottery_history = LotteryHistory(self.plugin_dir)

        # ★ 冷却记录
        self._last_command_time: Dict[int, float] = {}

        # ★ 每日抽奖计数
        self._daily_lottery_count_file = os.path.join(self.plugin_dir, "cache", "daily_lottery_count.json")
        self._daily_lottery_count: Dict[str, int] = {}
        self._load_daily_count()

        # ★ 主动求情者名单持久化（迁移到 PetitionMixin，但为了兼容保留引用）
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

    # ==================== 消息模板 ====================
    def get_message(self, key: str, default: str = "", **kwargs) -> str:
        raw_cfg = self.config_manager.load_config()
        template = raw_cfg.get(key)
        if template is not None:
            try:
                return template.format(**kwargs)
            except KeyError as e:
                logger.warning(f"消息模板 {key} 缺少占位符: {e}")
                return template
        templates = raw_cfg.get("message_templates", {})
        template = templates.get(key)
        if template is None:
            return default
        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.warning(f"消息模板 {key} 缺少占位符: {e}")
            return template

    # ==================== 每日抽奖计数 ====================
    def _load_daily_count(self):
        if os.path.exists(self._daily_lottery_count_file):
            try:
                with open(self._daily_lottery_count_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 检查日期是否变化
                today = datetime.now().strftime("%Y-%m-%d")
                if data.get("date") != today:
                    self._daily_lottery_count = {"date": today, "counts": {}}
                else:
                    self._daily_lottery_count = data
            except:
                today = datetime.now().strftime("%Y-%m-%d")
                self._daily_lottery_count = {"date": today, "counts": {}}
        else:
            today = datetime.now().strftime("%Y-%m-%d")
            self._daily_lottery_count = {"date": today, "counts": {}}

    def _save_daily_count(self):
        try:
            os.makedirs(os.path.dirname(self._daily_lottery_count_file), exist_ok=True)
            with open(self._daily_lottery_count_file, "w", encoding="utf-8") as f:
                json.dump(self._daily_lottery_count, f, ensure_ascii=False, indent=2)
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

    # ==================== 主动求情者名单（迁移到 PetitionMixin） ====================
    def _load_petition_helpers(self):
        if os.path.exists(self._petition_helpers_file):
            try:
                with open(self._petition_helpers_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.petition_helpers = set(data)
                logger.info(f"[求情] 加载主动求情者名单，共 {len(self.petition_helpers)} 人")
            except Exception as e:
                logger.error(f"[求情] 加载主动求情者名单失败: {e}")
                self.petition_helpers = set()
        else:
            self.petition_helpers = set()

    def _save_petition_helpers(self):
        try:
            os.makedirs(os.path.dirname(self._petition_helpers_file), exist_ok=True)
            with open(self._petition_helpers_file, "w", encoding="utf-8") as f:
                json.dump(list(self.petition_helpers), f, ensure_ascii=False, indent=2)
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

    # ==================== 核心禁言/解禁方法（带超时控制） ====================
    async def _execute_mute_with_cache(self, event, group_id: int, user_id: int, duration_minutes: int, source: str = "lottery"):
        if duration_minutes <= 0:
            return False, "禁言时间必须大于0"
        try:
            await asyncio.wait_for(
                event.bot.set_group_ban(
                    group_id=group_id,
                    user_id=user_id,
                    duration=duration_minutes * 60,
                    self_id=event.get_self_id()
                ),
                timeout=10.0
            )
            try:
                info = await asyncio.wait_for(
                    event.bot.call_action(
                        "get_group_member_info",
                        group_id=group_id,
                        user_id=user_id,
                        no_cache=True
                    ),
                    timeout=10.0
                )
                nickname = info.get('nickname') or info.get('card') or f"用户{user_id}"
            except:
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

    async def _execute_unmute(self, event, group_id: int, user_id: int, source: str = ""):
        try:
            await asyncio.wait_for(
                event.bot.set_group_ban(
                    group_id=group_id,
                    user_id=user_id,
                    duration=0,
                    self_id=event.get_self_id()
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

    # ==================== 帮助 ====================
    def _load_help(self) -> str:
        help_path = os.path.join(self.plugin_dir, "helps.json")
        if not os.path.exists(help_path):
            logger.error(f"[帮助] 文件不存在: {help_path}")
            return "帮助文件缺失，请重新安装插件喵～"
        try:
            with open(help_path, "r", encoding="utf-8") as f:
                content = f.read()
            if content.startswith('\ufeff'):
                content = content.lstrip('\ufeff')
            data = json.loads(content)
            if "sections" not in data or not isinstance(data["sections"], list):
                logger.error("[帮助] 帮助文件缺少 sections 字段或格式错误")
                return "帮助文件格式错误，请检查 sections 字段喵～"
            return self._format_help(data)
        except json.JSONDecodeError as e:
            logger.error(f"[帮助] JSON 解析失败: {e}")
            return f"帮助文件 JSON 解析失败：{e} 喵～"
        except Exception as e:
            logger.error(f"[帮助] 加载失败: {e}")
            return f"帮助信息加载失败：{e} 喵～"

    def _format_help(self, data: dict) -> str:
        lines = [data.get("title", "大礼包使用帮助")]
        lines.append("")
        sections = data.get("sections", [])
        for section in sections:
            title = section.get("title", "")
            lines.append(title)
            for item in section.get("items", []):
                cmd = item.get("cmd", "")
                desc = item.get("desc", "")
                lines.append(f"  {cmd}：{desc}")
            lines.append("")
        footer = data.get("footer", "")
        if footer:
            lines.append(footer)
        return "\n".join(lines)

    # ==================== 群组权限检查 ====================
    def _check_group_permission(self, group_id: int) -> bool:
        return check_group_permission(group_id, self.group_mode, self.group_list)

    # ==================== 指令定义 ====================
    @filter.command("大礼包", alias={"抽奖", "幸运轮盘"}, desc="弹出轮盘随机抽取禁言时长并执行禁言")
    async def mute_lottery(self, event: AstrMessageEvent):
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result(self.get_message("command_group_only", default="此指令仅可在群聊中使用喵"))
            return
        # 群组黑白名单检查
        if not self._check_group_permission(group_id):
            yield event.plain_result(self.get_message("group_blocked", default="本群暂未开放此功能喵～"))
            return
        # 冷却检查
        sender_id = event.get_sender_id()
        cooldown = self._check_cooldown(sender_id)
        if cooldown:
            yield event.plain_result(self.get_message("command_cooldown", seconds=round(cooldown, 1), default="操作过于频繁喵，请 {seconds} 秒后再试～"))
            return
        # 每日限制检查
        if not self._check_daily_limit(sender_id):
            limit = self.daily_lottery_limit
            yield event.plain_result(self.get_message("lottery_daily_limit_reached", limit=limit, default="你今天已经抽了 {limit} 次大礼包喵，明天再来吧～"))
            return
        # 执行抽奖（逻辑在 gift_mixin 中）
        async for msg in self.mute_lottery_logic(event):
            yield msg
        # 增加计数
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
        # 检查是否有 @ 用户
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
            # 更新相关配置
            self.daily_lottery_limit = int(new_cfg.get("daily_lottery_limit", -1))
            self.command_cooldown_seconds = float(new_cfg.get("command_cooldown_seconds", 15.0))
            self.group_mode = new_cfg.get("group_mode", "blacklist")
            self.group_list = new_cfg.get("group_list", [])
            self.message_mgr = MessageManager(new_cfg)
            # 更新其他可能需要热加载的配置...
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
        # 注意：Star 基类可能没有 stop 方法，故不调用 super().stop()