import asyncio
import time
from astrbot.api import logger
from astrbot.api.message_components import At
from ..modules.permission_utils import is_user_admin, is_bot_admin
from ..utils.prize_utils import format_duration

class PetitionMixin:
    """求情功能：替他人解除禁言，自己承担一半时间"""
    
    async def petition_logic(self, event):
        group_id = event.message_obj.group_id
        if not group_id:
            yield event.plain_result(self.get_message("petition_group_only", default="此指令仅可在群聊中使用喵"))
            return

        sender_id = event.get_sender_id()
        sender_name = event.get_sender_name() or str(sender_id)

        # 检查用户是否曾主动求情过（永久限制，除非被非求情方式禁言）
        if self._is_petition_helper(sender_id):
            yield event.plain_result(self.get_message("petition_helper_muted", default="帮助求情的人不能被求情喵！"))
            return

        self_id = event.get_self_id()
        if not self_id:
            yield event.plain_result(self.get_message("refresh_cache_no_self", default="无法获取机器人自身信息喵～"))
            return

        bot_is_admin = await is_bot_admin(event.bot, group_id, self_id)
        if not bot_is_admin:
            yield event.plain_result(self.get_message("refresh_cache_bot_no_admin", default="机器人没有本群管理员权限，无法获取禁言列表喵～"))
            return

        # 强制从协议同步最新数据
        await self.cache_mgr.sync_from_protocol(event.bot, group_id)

        # 直接从原始缓存加载（包含 source 字段）
        raw_cache = self.cache_mgr._load_cache()
        gid = str(group_id)
        all_users = raw_cache.get(gid, [])

        if not all_users:
            yield event.plain_result(self.get_message("petition_no_muted", default="当前群组内没有被禁言的用户喵～"))
            return

        current_time = int(time.time())
        muted_users = []
        for u in all_users:
            if u["expire_time"] > current_time:
                if "source" not in u:
                    u["source"] = "lottery"
                muted_users.append(u)

        if not muted_users:
            yield event.plain_result(self.get_message("petition_no_muted", default="当前群组内没有被禁言的用户喵～"))
            return

        is_admin = await is_user_admin(event.bot, group_id, sender_id, self.global_admins)

        if not is_admin:
            for entry in all_users:
                if str(entry["user_id"]) == str(sender_id) and entry["expire_time"] > current_time:
                    yield event.plain_result(self.get_message("petition_helper_muted", default="帮助求情的人不能被求情喵！"))
                    return

        args = event.message_str.strip().split()
        params = args[1:] if len(args) > 1 else []

        if params and params[0] in ("全部", "all"):
            if not is_admin:
                for entry in all_users:
                    if str(entry["user_id"]) == str(sender_id) and entry["expire_time"] > current_time:
                        yield event.plain_result(self.get_message("petition_helper_muted", default="帮助求情的人不能被求情喵！"))
                        return

            total_remaining = sum(max(0, u["expire_time"] - current_time) for u in muted_users)
            if total_remaining <= 0:
                yield event.plain_result(self.get_message("petition_all_expired", default="所有用户禁言已过期，无需求情喵～"))
                return

            if is_admin:
                success_list = []
                fail_list = []
                for entry in muted_users:
                    user_id = entry["user_id"]
                    nickname = entry.get("nickname", f"用户{user_id}")
                    if entry.get("source", "lottery") == "petition":
                        fail_list.append(f"{nickname}(来源:求情处罚，不可解禁)")
                        continue
                    success, err = await self._execute_unmute(event, group_id, user_id, source="petition")
                    if success:
                        success_list.append(nickname)
                    else:
                        fail_list.append(f"{nickname}({err})")
                    await asyncio.sleep(0.3)
                msg = self.get_message("petition_admin_all_success",
                    user=sender_name,
                    success=len(success_list),
                    default="管理员 {user} 替所有人解除了禁言喵！成功 {success} 人"
                )
                if fail_list:
                    msg += f"，失败 {len(fail_list)} 人：{', '.join(fail_list)}"
                try:
                    await event.bot.call_action("send_group_msg", group_id=group_id, message=msg)
                except Exception as e:
                    logger.error(f"发送求情消息失败: {e}")
                return

            # 普通用户全部求情
            penalty_seconds = max(60, (total_remaining + 1) // 2)
            penalty_minutes = (penalty_seconds + 59) // 60

            success_list = []
            fail_list = []
            for entry in muted_users:
                user_id = entry["user_id"]
                nickname = entry.get("nickname", f"用户{user_id}")
                if entry.get("source", "lottery") == "petition":
                    fail_list.append(f"{nickname}(来源:求情处罚，不可解禁)")
                    continue
                success, err = await self._execute_unmute(event, group_id, user_id, source="petition")
                if success:
                    success_list.append(nickname)
                else:
                    fail_list.append(f"{nickname}({err})")
                await asyncio.sleep(0.3)

            if not success_list:
                yield event.plain_result(self.get_message("petition_all_fail", default="全部解禁失败，无法继续给自己禁言喵～"))
                return

            self._mark_as_petition_helper(sender_id)

            mute_success, mute_err = await self._execute_mute_with_cache(event, group_id, sender_id, penalty_minutes, source="petition")
            if not mute_success:
                yield event.plain_result(self.get_message("petition_self_mute_fail",
                    count=len(success_list),
                    error=mute_err,
                    default="已解除 {count} 人禁言，但给自己禁言失败喵：{error}"
                ))
                return

            msg = self.get_message("petition_group_message_all",
                user=sender_name,
                default="好人一生平安，{user}替所有人背负了一半喵！大家都自由啦喵！"
            )
            try:
                await event.bot.call_action("send_group_msg", group_id=group_id, message=msg)
            except Exception as e:
                logger.error(f"发送求情消息失败: {e}")

            result_msg = self.get_message("petition_all_success",
                count=len(success_list),
                user=sender_name,
                duration=format_duration(penalty_minutes),
                default="已为 {count} 人解除禁言喵！\n你（{user}）替所有人承担了 {duration} 禁言时间喵～"
            )
            if fail_list:
                result_msg += f"\n失败 {len(fail_list)} 人：{', '.join(fail_list)}"
            yield event.plain_result(result_msg)
            return

        # 单个用户求情
        target_id = None
        target_name = None
        target_entry = None

        for comp in event.message_obj.message:
            if isinstance(comp, At):
                target_id = comp.qq
                break

        if target_id is not None:
            for entry in all_users:
                if str(entry["user_id"]) == str(target_id):
                    if entry["expire_time"] <= current_time:
                        yield event.plain_result(self.get_message("petition_user_expired", default="该用户禁言已过期，无需求情喵～"))
                        return
                    if entry.get("source", "lottery") == "petition":
                        yield event.plain_result("该用户是因为求情别人而被禁言的，不能被求情解禁喵～")
                        return
                    target_entry = entry
                    target_name = entry["nickname"]
                    break
            if not target_entry:
                yield event.plain_result(self.get_message("petition_user_not_muted", default="该用户当前没有被禁言喵～"))
                return
        elif params:
            try:
                choice = int(params[0])
            except ValueError:
                yield event.plain_result(self.get_message("petition_invalid_param", default="请提供有效的序号或 `全部` 喵～"))
                return
            if choice < 1 or choice > len(muted_users):
                yield event.plain_result(self.get_message("petition_out_of_range", max=len(muted_users), default="序号超出范围，请输入 1-{max} 喵～"))
                return
            target_entry = muted_users[choice - 1]
            target_id = target_entry["user_id"]
            target_name = target_entry["nickname"]
            if target_entry.get("source", "lottery") == "petition":
                yield event.plain_result("该用户是因为求情别人而被禁言的，不能被求情解禁喵～")
                return
        else:
            lines = [self.get_message("petition_list_title", default="求情列表：")]
            for idx, u in enumerate(muted_users, 1):
                start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(u["start_time"]))
                end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(u["expire_time"]))
                source_label = " [求情处罚]" if u.get("source", "lottery") == "petition" else ""
                lines.append(f"{idx}. {u['nickname']} ({u['user_id']}) 开始: {start_str} 结束: {end_str}{source_label}")
            lines.append("\n发送 `/求情 @用户` 、`/求情 [序号]` 或 `/求情 全部` 替对方/所有人求情喵～")
            yield event.plain_result("\n".join(lines))
            return

        if str(sender_id) == str(target_id):
            yield event.plain_result(self.get_message("petition_self", default="不能自己替自己求情喵～"))
            return

        if is_admin:
            success, err = await self._execute_unmute(event, group_id, target_id, source="petition")
            if success:
                msg = self.get_message("petition_admin_success",
                    user=sender_name,
                    target=target_name,
                    default="管理员 {user} 替 {target} 解除了禁言喵！"
                )
                try:
                    await event.bot.call_action("send_group_msg", group_id=group_id, message=msg)
                except Exception as e:
                    logger.error(f"发送求情消息失败: {e}")
            else:
                yield event.plain_result(self.get_message("petition_unmute_fail", target=target_name, error=err, default="解除 {target} 禁言失败喵：{error}"))
            return

        # 普通用户单个求情
        self._mark_as_petition_helper(sender_id)

        remaining_seconds = target_entry["expire_time"] - current_time
        if remaining_seconds <= 0:
            yield event.plain_result(self.get_message("petition_user_expired", default="该用户禁言已过期，无需求情喵～"))
            return

        penalty_seconds = max(60, remaining_seconds // 2)
        penalty_minutes = (penalty_seconds + 59) // 60

        success, err = await self._execute_unmute(event, group_id, target_id, source="petition")
        if not success:
            yield event.plain_result(self.get_message("petition_unmute_fail", target=target_name, error=err, default="解除 {target} 禁言失败喵：{error}"))
            return

        mute_success, mute_err = await self._execute_mute_with_cache(event, group_id, sender_id, penalty_minutes, source="petition")
        if not mute_success:
            yield event.plain_result(self.get_message("petition_self_mute_fail",
                count=1,
                error=mute_err,
                default="已解除 {target} 禁言，但给自己禁言失败喵：{error}"
            ))
            return

        msg = self.get_message("petition_group_message_single",
            user=sender_name,
            target=target_name,
            default="好人一生平安，{user}替{target}背负了一半喵！{target}你自由啦喵！"
        )
        try:
            await event.bot.call_action("send_group_msg", group_id=group_id, message=msg)
        except Exception as e:
            logger.error(f"发送求情消息失败: {e}")

        reply = self.get_message("petition_success",
            target=target_name,
            user=sender_name,
            duration=format_duration(penalty_minutes),
            default="已为 {target} 解除禁言喵！\n你（{user}）替 TA 承担了 {duration} 禁言时间喵～"
        )
        yield event.plain_result(reply)