# 监控提醒：可选的 Telegram 与自定义 Webhook

监控与提醒是两个开关。项目默认不向外发送提醒；Phase 6-E 的本机 HTTPS
接收端已经能验证真实发送、交付账本和重复抑制，因此**不需要你提供自定义
Webhook URL 才能完成该阶段的验收**。想在手机上收到提醒时，优先选 Telegram。

## Telegram：推荐

Telegram 预设由程序生成固定的 Bot API 地址。你只需创建机器人并确认接收
聊天；不需要自己搭建服务器或寻找 Webhook URL。

1. 在 Telegram 打开 [@BotFather](https://t.me/BotFather)，发送 `/newbot`，
   按提示创建机器人。它返回的令牌相当于密码，**不要发到聊天、Git 或截图里**。
   [Telegram 官方创建说明](https://core.telegram.org/bots/tutorial)
2. 打开你刚创建的机器人，发送 `/start`。
3. 在运行 Turtle 的本机终端，隐藏输入令牌并查询聊天 ID：

   ```sh
   read -rs TVE_MONITORING_TELEGRAM_BOT_TOKEN
   printf '\n'
   export TVE_MONITORING_TELEGRAM_BOT_TOKEN
   python3 -m turtle_value_engine watch telegram-chats --network allow
   ```

   把令牌粘贴到 `read` 等待输入的那一行并按 Enter。它不会出现在命令文本或
   `telegram-chats` 输出里。新建机器人的输出通常只有一个
   `suggested_chat_id`；若为空，回到 Telegram 再发送一次 `/start`。
   `telegram-chats` 只读最近更新，不使用 offset 确认或消费消息；已给其他
   服务配置 Webhook 的机器人可能无法使用此查询。
4. 在私有项目配置的 `[monitoring.delivery]` 中选择：

   ```toml
   enabled = true
   transport = "telegram-v1"
   destination_id = "owner-primary"
   delivery_root = ".tve-private/monitoring/delivery"
   telegram_bot_token_ref = { env = "TVE_MONITORING_TELEGRAM_BOT_TOKEN" }
   telegram_chat_id = "填入上一步的 suggested_chat_id"
   receiver_idempotency_declared = false
   ```

   不启用示例里注释的 `endpoint_ref` 和 `auth_token_ref` 行。配置只保存令牌的
   环境变量名称，不保存令牌值。`telegram_chat_id` 是数字字符串，可以让
   Codex 代你填入私有配置；令牌请始终只在本机输入。

Phase 6-E 的私有验收配置则设置 `delivery_receiver` 为 `telegram`、
`delivery_telegram_chat_id` 为查询到的数字。验收脚本会生成对应项目配置，
无需手工改写生成文件。之后在同一个有令牌环境变量的终端运行：

```sh
python3 scripts/monitoring_live_acceptance.py \
  --acceptance-config .tve-private/monitoring/phase6e/acceptance-config.json \
  live-smoke --network allow --allow-existing
```

程序只在 Telegram 的 `sendMessage` 返回 `ok=true`、聊天 ID 和消息正文
都匹配时记录 `DELIVERED`。[Telegram Bot API](https://core.telegram.org/bots/api#sendmessage)
重跑同一交付身份不会再发送。Telegram 不提供接收端强制幂等保证；若网络在
发出请求后断开，账本会记录 `AMBIGUOUS`，避免自动发送第二条可能重复的提醒。

## 定时运行

当 Phase 6-E 验收配置选择 Telegram 或自定义 Webhook，渲染的 systemd
服务使用 `tve watch unattended-notify`：先运行持久化监控，再交付该次
activation 的提醒。通知关闭时，服务只运行监控。服务身份必须能解析令牌
环境变量；把它交给你使用的本机凭据管理方式注入到 systemd，**只在交互
终端执行 `export` 不会让重启后的定时服务持续拥有令牌**。在凭据来源未
配置好之前，可以先完成本机接收端的 Phase 6-E 验收。

## 自定义 Webhook：高级选项

只有你已经拥有接收 JSON POST 的 HTTPS 地址时，才选择 `webhook-v1`，
并把地址放在 `endpoint_ref` 指向的本机环境或凭据来源中。它不是普通用户
启用监控或完成 Phase 6-E 的前置条件。
