import random
import time
from datetime import datetime
from astrbot.api import logger

async def handle_pardon(event, plugin):
    if not plugin.pardon_enabled:
        yield event.plain_result("求饶系统目前已关闭")  # 简化，也可改为模板
        return

    sender_id = event.get_sender_id()
    sender_name = event.get_sender_name() or str(sender_id)
    args = event.message_str.strip().split()
    params = args[1:] if len(args) > 1 else []

    if sender_id not in plugin.user_pardon_data:
        plugin.user_pardon_data[sender_id] = {
            "remaining": plugin.pardon_attempts,
            "used": 0,
            "last_reset_date": datetime.now().strftime("%Y-%m-%d")
        }

    user_data = plugin.user_pardon_data[sender_id]
    today = datetime.now().strftime("%Y-%m-%d")
    if user_data.get("last_reset_date") != today:
        user_data["remaining"] = plugin.pardon_attempts
        user_data["used"] = 0
        user_data["last_reset_date"] = today
        logger.info(f"[求饶] 用户 {sender_id} 已重置求饶次数（过0点）")

    cache = plugin.cache_mgr._load_cache()
    muted_groups = []
    for gid_str, user_list in cache.items():
        for entry in user_list:
            if entry["user_id"] == sender_id:
                if entry["expire_time"] > int(time.time()):
                    try:
                        group_info = await event.bot.call_action(
                            "get_group_info", group_id=int(gid_str)
                        )
                        group_name = group_info.get("group_name", f"群{gid_str}")
                    except Exception:
                        group_name = f"群{gid_str}"
                    muted_groups.append({
                        "group_id": int(gid_str),
                        "group_name": group_name,
                        "nickname": entry.get("nickname", f"用户{sender_id}"),
                        "expire_time": entry["expire_time"],
                        "start_time": entry.get("start_time")
                    })
                    break

    if not muted_groups:
        user_data["remaining"] = plugin.pardon_attempts
        user_data["used"] = 0
        user_data["last_reset_date"] = today
        yield event.plain_result(plugin.get_message("pardon_no_muted", default="你当前没有被禁言的群喵～"))
        return

    if len(params) == 0:
        header = plugin.get_message("pardon_list_header", user=sender_name, id=sender_id, default="求饶列表：\n{user}（{id}）")
        lines = header.split('\n')
        for idx, g in enumerate(muted_groups, 1):
            lines.append(plugin.get_message("pardon_list_item", idx=idx, group_name=g['group_name'], group_id=g['group_id'],
                default=f"{idx}. {g['group_name']}（{g['group_id']}）"))
        lines.append(plugin.get_message("pardon_list_tip", default="\n发送 `/求饶 [序号]` 进行求饶喵～"))
        lines.append(plugin.get_message("pardon_list_remaining", remaining=user_data['remaining'], default=f"你有 {user_data['remaining']} 次机会。"))
        yield event.plain_result("\n".join(lines))
        return

    try:
        choice = int(params[0])
    except ValueError:
        yield event.plain_result(plugin.get_message("pardon_invalid_choice", default="请提供正确的序号，例如 `/求饶 1` 喵～"))
        return

    if choice < 1 or choice > len(muted_groups):
        yield event.plain_result(plugin.get_message("pardon_out_of_range", max=len(muted_groups), default="序号超出范围，请输入 1-{max} 之间的数字喵～"))
        return

    target_group = muted_groups[choice - 1]
    target_group_id = target_group["group_id"]
    target_group_name = target_group["group_name"]

    if user_data["remaining"] <= 0:
        yield event.plain_result(plugin.get_message("pardon_no_chance", default="你已经没有求饶机会了喵～"))
        return

    used = user_data["used"]
    if used >= len(plugin.pardon_probabilities):
        success_prob = plugin.pardon_probabilities[-1]
    else:
        success_prob = plugin.pardon_probabilities[used]

    success = random.random() * 100 < success_prob
    user_data["remaining"] -= 1
    user_data["used"] += 1

    if success:
        try:
            await event.bot.set_group_ban(
                group_id=target_group_id,
                user_id=sender_id,
                duration=0,
                self_id=event.get_self_id()
            )
            await plugin.cache_mgr.remove_muted(target_group_id, sender_id)

            try:
                await event.bot.call_action(
                    "send_group_msg",
                    group_id=target_group_id,
                    message=f"{sender_name}向我求饶了，我勉为其难的答应了"
                )
            except Exception as e:
                logger.error(f"发送求饶成功群消息失败: {e}")

            reply = plugin.get_message("pardon_success",
                user=sender_name,
                group=target_group_name,
                prob=success_prob,
                default="恭喜 @{user} 求饶成功喵！\n你已被解除在群 {group} 的禁言喵～\n本次成功率：{prob}%"
            )
            yield event.plain_result(reply)
        except Exception as e:
            logger.error(f"解除禁言失败: {e}")
            yield event.plain_result(plugin.get_message("pardon_unmute_fail", error=str(e), default="解除禁言失败喵：{error}\n请确认 Bot 是否拥有管理员权限。"))
    else:
        reply = plugin.get_message("pardon_fail",
            prob=success_prob,
            remaining=user_data['remaining'],
            default="很遗憾，求饶失败喵～\n本次成功率：{prob}%\n剩余机会：{remaining} 次\n继续努力，下次可能就成功啦喵！"
        )
        yield event.plain_result(reply)