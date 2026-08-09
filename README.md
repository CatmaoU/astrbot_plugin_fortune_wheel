# 大礼包轮盘插件 astrbot_plugin_fortune_wheel

（原 astrbot_plugin_gift_lottery）

> 基于 AstrBot 框架的趣味禁言插件，通过轮盘随机抽奖决定禁言时长，支持投票解禁、诅咒系统、求饶系统等丰富功能

---

## 功能特性

- **轮盘抽奖**：`/大礼包` 弹出动态轮盘，按权重随机抽取禁言时长
- **自定义范围**：`/大礼包 5-30` 指定禁言区间（1～43199 分钟）
- **投票解禁**：普通用户发起解禁投票，群友 `/同意` `/不同意` 表决；同意票达阈值立即解禁，投票结束需满足同意 > 反对
- **诅咒系统**：
  - 诅咒标记累积，每个用户可叠加多个标记
  - 概率触发：每个标记增加触发概率
  - 高级诅咒：标记数超过阈值后，低权重物品获得额外加成
  - 全局诅咒：下一个使用 `/大礼包` 的用户继承所有累计标记
  - 随机诅咒：随机选中用户并转移累计标记（伤敌一千自损八百）
  - 诅咒排行榜：查看本群被诅咒最多的用户及总禁言时长
- **求饶系统**：私聊机器人尝试解除禁言，成功率随尝试次数递增；支持在多个被禁言群中选择
- **求情系统**：替他人求情解除禁言（承担一半剩余时长），支持 `/求情 全部`
- **全局管理员**：支持配置全局管理员列表，拥有最高权限（不受群管理员限制）
- **缓存管理**：自动刷新禁言列表，支持手动 `/刷新缓存`
- **抽奖历史**：查看自己的抽奖历史记录
- **高度可配置**：所有关键参数均可在配置文件中调整

---

## 安装与配置

### 1. 安装插件

- 通过 AstrBot 插件市场安装
- 或手动将 `astrbot_plugin_fortune_wheel` 文件夹放入 AstrBot 的 `plugins/` 目录

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 配置项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| global_admins | list | `[]` | 全局管理员QQ号列表 |
| enable_participation_prize | bool | `true` | 是否启用'重在参与'奖品 |
| daily_lottery_limit | int | `-1` | 每日抽奖次数限制（-1 无限制） |
| command_cooldown_seconds | float | `15.0` | 指令冷却时间（秒） |
| group_mode | string | `"blacklist"` | 群组模式：'blacklist' 或 'whitelist' |
| group_list | list | `[]` | 群组黑白名单列表 |
| wheel_items | list | 见默认配置 | 奖品与权重列表（格式："奖品:权重"） |
| show_arrow | bool | `false` | 轮盘指针是否显示 |
| enable_sub_wheel | bool | `true` | 是否启用二级细化轮盘 |
| show_mute_msg | bool | `true` | 是否发送详细的中奖文字信息 |
| main_wheel_duration | float | `7.0` | 主轮盘旋转动画总时长（秒） |
| sub_wheel_duration | float | `3.0` | 二级轮盘旋转动画总时长（秒） |
| main_wheel_delay | float | `6.5` | 主轮盘后续执行延迟（秒） |
| sub_wheel_delay | float | `3.0` | 二级轮盘后续执行延迟（秒） |
| mute_delay | float | `1.5` | 执行最终禁言前延迟（秒） |
| gif_loop | bool | `false` | 动图是否循环播放 |
| auto_sync_interval | int | `300` | 自动刷新缓存间隔（秒），设为0禁用 |
| pardon_enabled | bool | `true` | 是否启用求饶系统 |
| pardon_stages | list | `["1:12.5", "2:25", "3:50"]` | 求饶次数与对应成功率 |
| petition_enabled | bool | `true` | 是否启用求情系统 |
| help_gift_penalty_multiplier | float | `1.0` | 替别人使用失败时禁言翻倍倍率 |
| help_gift_enabled | bool | `true` | 是否允许替别人使用大礼包 |
| help_gift_success_rate | float | `0.15` | 替别人使用大礼包的成功概率（0-1） |
| help_gift_penalty_multiplier | float | `2.0` | 替别人使用失败时禁言翻倍倍率 |
| bot_name | string | `"小鱼喵"` | 消息中显示的名字 |
| vote_required_agree | int | `2` | 投票通过所需最小同意票数 |
| vote_duration_seconds | int | `120` | 投票持续时间（秒） |
| curse_enabled | bool | `true` | 是否启用诅咒系统 |
| curse_transfer_success_rate | float | `0.5` | 诅咒转移成功率（0~1） |
| curse_max_marks | int | `5` | 最大诅咒标记数 |
| curse_trigger_base_prob | float | `5.0` | 触发诅咒的基础概率（%） |
| curse_trigger_prob_increment | float | `10.0` | 每个标记增加的概率（%） |
| curse_low_weight_bonus | float | `20.0` | 高级诅咒每次增加的低权重加成 |
| curse_trigger_weight_bonus | float | `50.0` | 触发诅咒时所有奖池额外权重 |
| curse_daily_limit | int | `1` | 每个用户每天可使用 `/诅咒` 的次数 |

完整配置请参考 `_conf_schema.json`。

---

## 指令

| 指令 | 说明 |
|------|------|
| `/大礼包` | 弹出轮盘随机禁言 |
| `/大礼包 [分钟数]` | 指定禁言时长（例如：`/大礼包 10`） |
| `/大礼包 [最小]-[最大]` | 在指定区间内随机禁言（例如：`/大礼包 5-30`） |
| `/大礼包 @用户` | 替别人使用大礼包（有概率成功，失败时自己承担翻倍禁言时长） |
| `/大礼包 帮助` | 显示完整帮助信息 |
| `/大礼包历史` | 查看自己的抽奖历史记录 |
| `/放过` | 查看当前被禁言用户列表 |
| `/放过 [序号]` | 管理员直接解禁；普通用户发起投票解禁 |
| `/放过 @用户` | 管理员可直接 @用户 解禁 |
| `/同意` | 在投票中投同意票 |
| `/不同意` | 在投票中投反对票 |
| `/诅咒` | 设置全局诅咒 |
| `/诅咒 @用户` | 尝试将诅咒转移给指定用户 |
| `/诅咒状态` | 查看当前群诅咒详情 |
| `/随机诅咒` | 随机选中用户进行诅咒，自己获得一半累计标记 |
| `/诅咒排行榜` | 查看本群被诅咒最多的人及总禁言时长 |
| `/清除诅咒` | 管理员清除当前诅咒数据 |
| `/求饶` | 私聊机器人尝试解除自己的禁言 |
| `/求情` | 替他人求情解除禁言（承担一半剩余时长） |
| `/求情 全部` | 替所有人求情解除禁言 |
| `/全部解除` | 管理员一键解除当前群所有被禁言用户 |
| `/刷新缓存` | 强制从服务器同步最新禁言列表 |
| `/重载配置` | 热重载配置文件（无需重启） |

---

## 依赖

- Pillow>=9.0.0（轮盘图片生成）

---

## 更新日志

详见 `CHANGELOG.md`
