import random
import re
import os
import time
import asyncio
from astrbot.api import logger
from astrbot.api.message_components import At
from ..utils.prize_utils import format_duration, parse_range
from ..wheel.main_wheel import generate_main_wheel
from ..wheel.sub_wheel import generate_sub_wheel
from ..modules.prize_loader import load_prizes
from ..modules.permission_utils import is_user_admin


class GiftMixin:
    """大礼包抽奖核心功能"""

    async def mute_lottery_logic(self, event):
        args = event.message_str.strip().split()
        if len(args) > 1 and args[1] in ("帮助", "help", "--help", "-h"):
            yield event.plain_result(self._load_help())
            return

        sender_id = event.get_sender_id()
        sender_name = event.get_sender_name() or str(sender_id)
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result(self.get_message("command_group_only", default="此指令仅可在群聊中使用喵"))
            return

        # ========== 解析 @ 用户 ==========
        target_user_id = sender_id
        target_user_name = sender_name
        is_help_gift = False
        is_help_gift_attempt = False
        is_help_gift_failed = False
        penalty_multiplier = 1

        for comp in event.message_obj.message:
            if isinstance(comp, At):
                target_user_id = comp.qq
                is_help_gift = True
                is_help_gift_attempt = True
                break

        # 如果不是替别人使用（且没有尝试过），拦截管理员/群主
        if not is_help_gift_attempt:
            is_admin = await is_user_admin(event.bot, group_id, sender_id, self.global_admins)
            if is_admin:
                yield event.plain_result(self.get_message("mute_failed_admin", default="老大凑什么热闹喵！管理员不可用玩！"))
                return

        # ========== 替别人使用大礼包 ==========
        if is_help_gift:
            # 获取目标用户昵称
            try:
                info = await event.bot.call_action(
                    "get_group_member_info",
                    group_id=group_id,
                    user_id=target_user_id,
                    no_cache=True
                )
                target_user_name = info.get('nickname') or info.get('card') or str(target_user_id)
            except Exception:
                target_user_name = str(target_user_id)

            # 检查目标用户是否已被禁言
            muted_list = await self.cache_mgr.get_muted(group_id)
            for muted in muted_list:
                if muted["user_id"] == target_user_id:
                    yield event.plain_result(
                        self.get_message("help_gift_target_muted", target=target_user_name, default="放过 @{target} 吧喵！已经很惨了喵！")
                    )
                    return

            if not self.help_gift_enabled:
                yield event.plain_result(self.get_message("help_gift_disabled", default="替别人使用大礼包功能已关闭喵～"))
                return

            if await is_user_admin(event.bot, group_id, target_user_id, self.global_admins):
                yield event.plain_result(self.get_message("help_gift_admin_target", default="不能对管理员使用大礼包喵～"))
                return

            marks = await self.curse_mgr.get_marks(group_id, target_user_id)
            if marks > 0:
                params = [p for p in args[1:] if not (re.fullmatch(r'\d+', p) or re.fullmatch(r'\d+-\d+', p))]
                args = [args[0]] + params
                yield event.plain_result(self.get_message("help_gift_curse_warning", default="你现在诅咒缠身喔！不能规避诅咒喵！"))

            sender_is_admin = await is_user_admin(event.bot, group_id, sender_id, self.global_admins)
            if not sender_is_admin:
                if random.random() >= self.help_gift_success_rate:
                    # 失败：惩罚自己，加倍禁言，标记失败
                    target_user_id = sender_id
                    is_help_gift = False
                    is_help_gift_failed = True
                    penalty_multiplier = self.help_gift_penalty_multiplier
                    # target_user_name 保留为原始目标（被替的人）

        # ========== 诅咒处理 ==========
        curse_msg = ""
        curse_triggered = False
        curse_bonus = 0.0

        if await self.curse_mgr.get_and_clear_global_curse(group_id):
            total_curse = await self.curse_mgr.get_total_curse_count(group_id)
            if total_curse > 0:
                await self.curse_mgr.add_mark(group_id, sender_id, count=total_curse)
                await self.curse_mgr.reset_total_curse_count(group_id)
                curse_msg = self.get_message("curse_global", total=total_curse, default="全局诅咒触发！你继承了 {total} 个诅咒标记喵～") + "\n"
            else:
                curse_msg = self.get_message("curse_global_empty", default="全局诅咒触发！但当前累计次数为 0，没有标记可继承喵～") + "\n"

        marks = await self.curse_mgr.get_marks(group_id, target_user_id)
        prob = await self.curse_mgr.get_trigger_probability(group_id, target_user_id)

        if marks > 0:
            curse_msg += self.get_message("curse_mark_status", marks=marks, prob=prob, default="当前诅咒标记：{marks} 个，触发概率 {prob:.1f}%") + "\n"

        if marks > 0 and random.random() * 100 < prob:
            curse_triggered = True
            await self.curse_mgr.clear_user_marks(group_id, target_user_id)
            curse_bonus = self.curse_mgr.trigger_weight_bonus
            curse_msg += self.get_message("curse_trigger", bonus=curse_bonus, default="诅咒触发！所有奖品权重 +{bonus}（已清空所有诅咒标记）喵～") + "\n"
        elif marks > 0:
            curse_msg += self.get_message("curse_no_trigger", marks=marks, default="本次未触发诅咒（剩余 {marks} 个标记，概率继续累积）喵～") + "\n"

        low_bonus = await self.curse_mgr.get_low_bonus(group_id)
        if low_bonus > 0:
            curse_msg += self.get_message("curse_low_bonus", bonus=low_bonus, default="本群低权重物品累计加成 +{bonus}") + "\n"

        # ========== 加载奖品 ==========
        prizes, weights, prize_durations = load_prizes(self.config_manager)
        if not prizes:
            yield event.plain_result(self.get_message("config_sync_fail", default="配置同步失败，无可用奖品喵！"))
            return

        params = args[1:] if len(args) > 1 else []
        if marks > 0:
            params = [p for p in params if not (re.fullmatch(r'\d+', p) or re.fullmatch(r'\d+-\d+', p))]

        new_weights = weights.copy()
        if curse_triggered:
            new_weights = [w + curse_bonus for w in new_weights]
        if low_bonus > 0:
            sorted_indices = sorted(range(len(new_weights)), key=lambda i: new_weights[i])
            num_low = min(2, len(sorted_indices))
            for idx in sorted_indices[:num_low]:
                new_weights[idx] += low_bonus
        weights = new_weights

        # ========== 变量默认值（用于历史记录） ==========
        custom_range = False
        min_val = max_val = 1
        prob_str = "100.00000%"

        # ========== 指定分钟或区间 ==========
        if len(params) == 1 and re.fullmatch(r'\d+', params[0]):
            mute_minutes = int(params[0])
            if mute_minutes <= 0:
                yield event.plain_result(self.get_message("mute_time_zero", default="禁言时间必须大于 0 分钟喵。"))
                return

            final_minutes = mute_minutes * penalty_multiplier
            if final_minutes == 0:
                yield event.plain_result(self.get_message("mute_participation", default="你抽中了重在参与！什么都不会发生喵～"))
                return

            success, err = await self._execute_mute_with_cache(event, group_id, target_user_id, final_minutes)
            if not success:
                if err and "cannot ban owner" in str(err).lower():
                    yield event.plain_result(self.get_message("mute_failed_admin", default="老大凑什么热闹喵！管理员不可用玩！"))
                else:
                    yield event.plain_result(self.get_message("mute_failed_general", error=err, default="大礼包发放失败喵：{error}"))
                return

            prize_name = f"{mute_minutes}分钟"
            self.lottery_history.add_record(
                user_id=target_user_id,
                prize=prize_name,
                duration=format_duration(final_minutes),
                prob="100.00000%"
            )

            await self.curse_mgr.add_mute_duration(group_id, target_user_id, final_minutes)

            # ★★★ 消息模板选择 ★★★
            if is_help_gift_failed:
                key = "mute_success_penalty"
            elif is_help_gift:
                key = "mute_success_help"
            elif penalty_multiplier > 1:
                key = "mute_success_penalty"
            else:
                key = "mute_success_template"

            if key == "mute_success_penalty":
                msg_kwargs = {
                    "user": sender_name,
                    "target": target_user_name,
                    "prob": "100.00000%",
                    "duration": format_duration(final_minutes),
                    "bot": self.bot_name,
                    "pardon": self.pardon_command,
                    "multiplier": penalty_multiplier
                }
            elif key == "mute_success_help":
                msg_kwargs = {
                    "user": target_user_name,
                    "target": target_user_name,
                    "prob": "100.00000%",
                    "duration": format_duration(final_minutes),
                    "bot": self.bot_name,
                    "pardon": self.pardon_command
                }
            else:
                msg_kwargs = {
                    "user": target_user_name,
                    "prob": "100.00000%",
                    "duration": format_duration(final_minutes),
                    "bot": self.bot_name,
                    "pardon": self.pardon_command
                }

            reply = self.get_message(key, default="禁言已执行喵！", **msg_kwargs)
            if curse_msg:
                reply = curse_msg + "\n" + reply
            yield event.plain_result(reply)
            return

        # ========== 区间处理 ==========
        default_min, default_max = 1, 43199
        min_val, max_val = default_min, default_max
        custom_range = False
        match = re.search(r'(\d+)-(\d+)', event.message_str)
        if match:
            try:
                min_val = int(match.group(1))
                max_val = int(match.group(2))
                if min_val <= 0:
                    yield event.plain_result(self.get_message("mute_time_zero", default="禁言时间必须大于 0 分钟喵。"))
                    return
                if 1 <= min_val <= max_val <= 43199:
                    custom_range = True
                else:
                    yield event.plain_result(self.get_message("mute_range_invalid", default="参数范围无效喵～"))
            except:
                yield event.plain_result(self.get_message("mute_range_format", default="参数格式错误喵～"))

        # ========== 生成轮盘 ==========
        timestamp = int(time.time() * 1000)
        cache_dir = os.path.join(self.plugin_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        gif_path = os.path.join(cache_dir, f"gift_wheel_{timestamp}.gif")
        sub_gif_path = None
        files_to_delete = [gif_path]

        try:
            if custom_range:
                temp_prizes = [f"{min_val}-{max_val}分钟"]
                temp_weights = [100]
                winner_name = generate_main_wheel(
                    prizes=temp_prizes,
                    weights=temp_weights,
                    output_path=gif_path,
                    show_arrow=self.show_arrow,
                    duration_ms=int(self.main_wheel_duration * 1000),
                    loop=self.gif_loop
                )
                mute_minutes = random.randint(min_val, max_val)
                prob_str = "100.00000%"
            else:
                winner_name = generate_main_wheel(
                    prizes=prizes,
                    weights=weights,
                    output_path=gif_path,
                    show_arrow=self.show_arrow,
                    duration_ms=int(self.main_wheel_duration * 1000),
                    loop=self.gif_loop
                )
                winner_index = prizes.index(winner_name)
                total_weight = sum(weights)
                prob_str = f"{weights[winner_index] / total_weight * 100:.5f}%"

            yield event.image_result(gif_path)
            await asyncio.sleep(self.main_wheel_delay)

            sub_triggered = False
            if not custom_range and self.enable_sub_wheel:
                if winner_name in prize_durations:
                    min_m, max_m = prize_durations[winner_name]
                    if max_m - min_m >= 1:
                        unit = "分钟"
                        step_base = 1
                        if "小时" in winner_name:
                            unit, step_base = "小时", 60
                        elif "天" in winner_name:
                            unit, step_base = "天", 1440
                        sub_options = []
                        for i in range(min_m, max_m + 1, step_base):
                            if unit == "小时":
                                sub_options.append(f"{i // 60}{unit}")
                            elif unit == "天":
                                sub_options.append(f"{i // 1440}{unit}")
                            else:
                                sub_options.append(f"{i}{unit}")
                        sub_weights = [100.0 / len(sub_options)] * len(sub_options)
                        sub_timestamp = int(time.time() * 1000)
                        sub_gif_path = os.path.join(cache_dir, f"gift_sub_wheel_{sub_timestamp}.gif")
                        files_to_delete.append(sub_gif_path)

                        sub_winner_name = generate_sub_wheel(
                            prizes=sub_options,
                            weights=sub_weights,
                            output_path=sub_gif_path,
                            show_arrow=self.show_arrow,
                            duration_ms=int(self.sub_wheel_duration * 1000),
                            loop=self.gif_loop
                        )
                        _, sub_m, _ = parse_range(sub_winner_name)
                        mute_minutes = sub_m
                        sub_triggered = True

                        yield event.image_result(sub_gif_path)
                        await asyncio.sleep(self.sub_wheel_delay)

            if not sub_triggered:
                if custom_range:
                    pass
                elif winner_name in prize_durations:
                    min_m, max_m = prize_durations[winner_name]
                    mute_minutes = random.randint(min_m, max_m)

            await asyncio.sleep(self.mute_delay)

            final_minutes = mute_minutes * penalty_multiplier
            if final_minutes == 0:
                yield event.plain_result(self.get_message("mute_participation", default="你抽中了重在参与！什么都不会发生喵～"))
                return

            success, err = await self._execute_mute_with_cache(event, group_id, target_user_id, final_minutes)
            if not success:
                if err and "cannot ban owner" in str(err).lower():
                    yield event.plain_result(self.get_message("mute_failed_admin", default="老大凑什么热闹喵！管理员不可用玩！"))
                else:
                    yield event.plain_result(self.get_message("mute_failed_general", error=err, default="大礼包发放失败喵：{error}"))
                return

            if success:
                self.lottery_history.add_record(
                    user_id=target_user_id,
                    prize=winner_name,
                    duration=format_duration(final_minutes),
                    prob=prob_str
                )

            await self.curse_mgr.add_mute_duration(group_id, target_user_id, final_minutes)

            if self.show_mute_msg:
                # ★★★ 消息模板选择 ★★★
                if is_help_gift_failed:
                    key = "mute_success_penalty"
                elif is_help_gift:
                    key = "mute_success_help"
                elif penalty_multiplier > 1:
                    key = "mute_success_penalty"
                else:
                    key = "mute_success_template"

                if key == "mute_success_penalty":
                    msg_kwargs = {
                        "user": sender_name,
                        "target": target_user_name,
                        "prob": prob_str,
                        "duration": format_duration(final_minutes),
                        "bot": self.bot_name,
                        "pardon": self.pardon_command,
                        "multiplier": penalty_multiplier
                    }
                elif key == "mute_success_help":
                    msg_kwargs = {
                        "user": target_user_name,
                        "target": target_user_name,
                        "prob": prob_str,
                        "duration": format_duration(final_minutes),
                        "bot": self.bot_name,
                        "pardon": self.pardon_command
                    }
                else:
                    msg_kwargs = {
                        "user": target_user_name,
                        "prob": prob_str,
                        "duration": format_duration(final_minutes),
                        "bot": self.bot_name,
                        "pardon": self.pardon_command
                    }

                reply = self.get_message(key, default="禁言已执行喵！", **msg_kwargs)
                if curse_msg:
                    reply = curse_msg + "\n" + reply
                yield event.plain_result(reply)
            else:
                yield event.plain_result(self.get_message("mute_simple", default="禁言已执行喵！"))

        except Exception as e:
            logger.error(f"大礼包执行失败: {e}")
            yield event.plain_result(self.get_message("mute_failed_general", error=str(e), default="大礼包发放失败喵：{error}"))
        finally:
            asyncio.create_task(self._cleanup_files(files_to_delete))