import random
import time
from astrbot.api import logger
from astrbot.api.message_components import At
from ..modules.permission_utils import is_user_admin

class CurseMixin:
    async def curse_logic(self, event):
        if not self.curse_mgr.enabled:
            yield event.plain_result(self.get_message("curse_disabled", default="诅咒功能已关闭喵～"))
            return
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result(self.get_message("curse_group_only", default="此指令仅可在群聊中使用喵"))
            return
        sender_id = event.get_sender_id()
        sender_name = event.get_sender_name()

        target_id = None
        target_name = None
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

        allowed, remaining = await self.curse_mgr.check_daily_limit(group_id, sender_id)
        if not allowed:
            yield event.plain_result(self.get_message("curse_daily_limit", limit=self.curse_mgr.daily_limit, default="你今天已使用 /诅咒 {limit} 次，已达到上限喵～"))
            return

        used = await self.curse_mgr.record_curse_usage(group_id, sender_id)
        total_count = await self.curse_mgr.get_total_curse_count(group_id)

        if target_id is not None:
            if random.random() < self.curse_transfer_success_rate:
                high, bonus = await self.curse_mgr.add_mark(group_id, target_id)
                msg = self.get_message("curse_transfer_success", target=target_name, id=target_id, default="诅咒已转移给 @{target} ({id})，当前标记数增加！")
                if high:
                    msg += self.get_message("curse_transfer_success_high", bonus=bonus, default="\n触发高级诅咒！低权重物品权重 +{bonus}")
            else:
                await self.curse_mgr.add_mark(group_id, sender_id)
                msg = self.get_message("curse_transfer_fail", user=sender_name, default="诅咒转移失败！反弹到自己身上 @{user}，你被添加了一个诅咒标记！")
        else:
            await self.curse_mgr.set_global_curse(group_id)
            msg = self.get_message("curse_global_set", default="已设置全局诅咒，下一个使用 `/大礼包` 的人将继承所有累计标记！")

        msg += f"\n当前全局诅咒累计次数：{total_count} 次"
        msg += f"\n你今日剩余使用次数：{remaining-1} 次（限制 {self.curse_mgr.daily_limit} 次/天）"
        yield event.plain_result(msg)

    async def curse_status_logic(self, event):
        if not self.curse_mgr.enabled:
            yield event.plain_result(self.get_message("curse_disabled", default="诅咒功能已关闭喵～"))
            return
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result(self.get_message("curse_group_only", default="此指令仅可在群聊中使用喵"))
            return

        data = await self.curse_mgr.get_group_data(group_id)
        if not data:
            yield event.plain_result(self.get_message("curse_no_data", default="当前群无任何诅咒数据"))
            return

        lines = ["本群诅咒状态："]
        if data.get("global", False):
            lines.append(self.get_message("curse_global_status_active", default="全局诅咒：已激活（下一个使用 /大礼包 的人会继承所有累计标记）"))
        else:
            lines.append(self.get_message("curse_global_status_inactive", default="全局诅咒：未激活"))

        low_bonus = data.get("low_bonus", 0.0)
        lines.append(f"低权重物品加成：+{low_bonus}")

        total_count = data.get("total_curse_count", 0)
        lines.append(f"全局累计诅咒次数：{total_count}")

        users = data.get("users", {})
        if users:
            lines.append("用户诅咒标记：")
            for uid, info in users.items():
                marks = info.get("marks", 0)
                mute_min = info.get("total_mute_minutes", 0)
                lines.append(f"  - 用户 {uid}：{marks} 个标记，总禁言 {mute_min} 分钟")
        else:
            lines.append("暂无用户被标记")

        yield event.plain_result("\n".join(lines))

    async def clear_curse_logic(self, event):
        if not self.curse_mgr.enabled:
            yield event.plain_result(self.get_message("curse_disabled", default="诅咒功能已关闭喵～"))
            return
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result(self.get_message("curse_group_only", default="此指令仅可在群聊中使用喵"))
            return
        args = event.message_str.strip().split()
        params = args[1:] if len(args) > 1 else []

        if len(params) == 0:
            await self.curse_mgr.clear_group_curse(group_id)
            yield event.plain_result(self.get_message("curse_clear_all", default="已清除本群所有诅咒数据（全局诅咒和所有用户标记）喵～"))
        else:
            target_input = params[0]
            if target_input.isdigit():
                user_id = int(target_input)
                success = await self.curse_mgr.clear_user_marks(group_id, user_id)
                if success:
                    yield event.plain_result(self.get_message("curse_clear_user_success", uid=user_id, default="已清除用户 {uid} 的所有诅咒标记喵～"))
                else:
                    yield event.plain_result(self.get_message("curse_clear_user_fail", uid=user_id, default="用户 {uid} 没有诅咒标记喵～"))
            else:
                yield event.plain_result(self.get_message("curse_clear_invalid", default="请提供有效的用户ID（数字）"))

    async def random_curse_logic(self, event):
        if not self.curse_mgr.enabled:
            yield event.plain_result(self.get_message("curse_disabled", default="诅咒功能已关闭喵～"))
            return
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result(self.get_message("curse_group_only", default="此指令仅可在群聊中使用喵"))
            return
        sender_id = event.get_sender_id()

        try:
            members = await event.bot.call_action("get_group_member_list", group_id=group_id, no_cache=True)
            if isinstance(members, dict) and 'data' in members:
                members = members['data']
            if not members:
                yield event.plain_result(self.get_message("curse_member_fail", default="获取群成员失败，请稍后再试喵～"))
                return
            bot_id = event.get_self_id()
            if bot_id:
                members = [m for m in members if m.get('user_id') != int(bot_id)]
            if not members:
                yield event.plain_result(self.get_message("curse_no_member", default="群里没有其他成员喵～"))
                return
            target = random.choice(members)
            target_id = target.get('user_id')
            target_name = target.get('nickname') or target.get('card') or str(target_id)
        except Exception as e:
            logger.error(f"随机诅咒获取群成员失败: {e}")
            yield event.plain_result(self.get_message("curse_member_fail", default="获取群成员失败，请稍后再试喵～"))
            return

        total = await self.curse_mgr.get_total_curse_count(group_id)

        if total > 0:
            await self.curse_mgr.add_mark(group_id, target_id, count=total)
            half = round(total / 2)
            if half > 0:
                await self.curse_mgr.add_mark(group_id, sender_id, count=half)
            await self.curse_mgr.reset_total_curse_count(group_id)

            msg = self.get_message("curse_random_success", target=target_name, id=target_id, total=total, default="随机诅咒选中了 @{target} ({id})，继承了 {total} 个诅咒标记！")
            if half > 0:
                msg += self.get_message("curse_random_self_half", user=event.get_sender_name(), half=half, default="\n伤敌一千自损八百！你（@{user}）也获得了 {half} 个诅咒标记（全局累计次数的一半，四舍五入）！")
            else:
                msg += self.get_message("curse_random_self_zero", default="\n伤敌一千自损八百！你逃过一劫（总累计为0）")
        else:
            msg = self.get_message("curse_random_no_total", target=target_name, default="随机诅咒选中了 @{target}，但全局累计次数为 0，无人获得标记。")
        msg += self.get_message("curse_random_reset", default="\n全局累计次数已清零。")
        yield event.plain_result(msg)

    async def curse_ranking_logic(self, event):
        if not self.curse_mgr.enabled:
            yield event.plain_result(self.get_message("curse_disabled", default="诅咒功能已关闭喵～"))
            return
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result(self.get_message("curse_group_only", default="此指令仅可在群聊中使用喵"))
            return

        ranking = await self.curse_mgr.get_ranking(group_id)
        if not ranking:
            yield event.plain_result(self.get_message("curse_ranking_no_data", default="本群暂无诅咒数据"))
            return

        lines = [self.get_message("curse_ranking_title", default="本群诅咒排行榜（按标记数降序）：")]
        for idx, item in enumerate(ranking[:10], 1):
            uid = item["user_id"]
            marks = item["marks"]
            mute_min = item["total_mute_minutes"]
            lines.append(self.get_message("curse_ranking_item", idx=idx, uid=uid, marks=marks, mute_min=mute_min,
                default="{idx}. 用户 {uid}：{marks} 个诅咒标记，总禁言 {mute_min} 分钟"))
        yield event.plain_result("\n".join(lines))