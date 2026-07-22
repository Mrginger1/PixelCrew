<p align="center">
  <img src="docs/pixelcrew-avatar.svg" width="112" alt="PixelCrew pixel secretary avatar">
</p>

<h1 align="center">PixelCrew 🏢</h1>
<p align="center"><strong>Your agents have desks now.</strong><br>把 Codex 多任务项目变成一间会自己更新的像素办公室。</p>

PixelCrew 自动发现属于同一项目的 Codex 任务，把每个任务安排成一名 Crew：计划是进度条，最新进展是语言泡泡，里程碑是可逐条翻阅的木板记录，模型、视频和报告则进入成果柜。**不需要先找秘书手工搭办公室**；`init + serve` 就能完成确定性、只读同步。AI 秘书只是可选的跨任务总结增强。

![PixelCrew dashboard](docs/dashboard-preview.png)

## 一眼能看见什么

| 真实项目 | PixelCrew 世界 |
|---|---|
| Codex 项目任务 | 一名自动入驻的 Crew |
| 总规划任务 | 项目负责人 |
| `update_plan` | 工位进度与阶段记录 |
| 最新汇报 | 人物语言泡泡 |
| 阻塞 / 等待 | 状态灯与关注队列 |
| 每名 Crew 的历史 | 一张汇总卡 + 可点开的木板档案 |
| 检查点 / 里程碑 | 可逐条点击的完整记录 |
| 模型、视频、报告 | 成果柜里的交付证据 |
| 跨任务态势 | 规则秘书或 Codex AI 秘书 |

PixelCrew 不把消息数量当生产力，也不会为了热闹编造进度。阶段成果来自任务真实记录；“完成”最好同时带文件或验证证据。

![PixelCrew report](docs/report-preview.png)

点击任一检查点或里程碑，还能打开当时的完整记录，而不是只看截断摘要：

![PixelCrew checkpoint detail](docs/checkpoint-preview.png)

## 三分钟入驻

要求 Python 3.10+，并已在本机登录 Codex。

```bash
git clone https://github.com/<your-account>/pixelcrew.git
cd pixelcrew
python3 -m pip install -e .

# 1) 给任意项目生成本地配置
pixelcrew init /absolute/path/to/your/project --name "My Fantastic Project"

# 2) 确认 Codex 数据可读取、任务能被发现
pixelcrew doctor

# 3) 启动只读办公室
pixelcrew serve
```

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。新任务、进度和成果会自动同步，无需改网页。

> 只想先体验？阅读 [`docs/QUICKSTART.md`](docs/QUICKSTART.md)。旧版 `python3 pixelcrew.py --config ... --port 8765` 仍兼容。

## 秘书：默认规则，可选 AI

办公室本身完全不需要 LLM：规则秘书会根据状态、计划和关注队列即时生成事实简报。需要更有上下文的跨员工分析时，主动运行：

```bash
# 预览将送入模型的脱敏内容，不产生模型调用
pixelcrew secretary --dry-run

# 使用当前 Codex 登录生成一次 AI 简报
pixelcrew secretary

# 可选：每 15 分钟值班刷新
pixelcrew secretary --watch --interval 900
```

AI 秘书以临时、只读 Codex 会话运行；输入会移除任务 ID、绝对路径和常见密钥。调用失败或缓存过期时，页面仍可降级到规则秘书。**它不会默认后台调用模型，也不会替用户做决策。** 详见 [`docs/SECRETARY.md`](docs/SECRETARY.md)。

## 迁移到另一个项目

无需重画办公室，只需另一份配置：

```bash
pixelcrew init /path/to/another/project \
  --name "Another Adventure" \
  --output pixelcrew.another.json
pixelcrew doctor --config pixelcrew.another.json
pixelcrew serve --config pixelcrew.another.json --port 8766
```

适用于软件开发、科研实验、机器人训练、内容制作、数据分析等 Codex 多任务项目。没有预设角色的新任务也会自动入驻；需要稳定昵称时再配置 `roles`。

## 给 Agent 一套清晰的工作架构

PixelCrew 附带一套轻量协作协议：

- **项目负责人**持有目标、依赖关系和最终验收权；
- **执行 Crew**接收边界清晰、可独立交付的工作包；
- **验证 Crew**不重复实现，只提交可复现证据；
- 只在里程碑、路线变化、验证结论或风险变化时写阶段报告；
- 每名 Crew 的多条记录收拢为一张档案，首页保持简洁；
- 等待就是等待，阻塞写清解锁条件，完成必须有证据。

从 [`docs/PROJECT_CHARTER_TEMPLATE.md`](docs/PROJECT_CHARTER_TEMPLATE.md) 和 [`docs/TASK_BRIEF_TEMPLATE.md`](docs/TASK_BRIEF_TEMPLATE.md) 开始。完整方法见 [`AGENTS.md`](AGENTS.md) 与 [`docs/OPERATING_MODEL.md`](docs/OPERATING_MODEL.md)。

## 配置地图

| 字段 | 作用 |
|---|---|
| `project.root` | 项目根目录，也是默认成果白名单 |
| `project.manager_thread_id` | 可选：指定项目负责人任务 |
| `discovery.workspace_match` | 按工作目录自动发现 Codex 任务 |
| `discovery.title_keywords` | 可选：进一步限定任务标题 |
| `roles` | 可选：给任务配置稳定角色名与职责 |
| `artifacts.allowed_roots` | 允许展示的本地成果路径 |
| `artifacts.remote_prefixes` | 可识别但不自动连接的远端路径 |
| `secretary.enabled` | 是否在页面显示秘书能力 |
| `secretary.cache` | 可选 AI 简报的本地缓存位置 |

完整示例见 [`pixelcrew.example.json`](pixelcrew.example.json)。

## 数据与安全边界

PixelCrew 默认只读 `~/.codex/state_5.sqlite`、`~/.codex/session_index.jsonl` 和对应 rollout 记录。服务只监听 `127.0.0.1`，不会启动、停止或修改 Codex 任务，也不会执行训练和成果文件。

`pixelcrew.json`、`.pixelcrew/secretary.json` 可能含本地项目信息，已默认忽略，**不要提交到公开仓库**。更多威胁模型和报告渠道见 [`SECURITY.md`](SECURITY.md)，实现分层见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

## 开发与验证

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile src/pixelcrew/*.py
python3 -m pip wheel . -w /tmp/pixelcrew-wheel
```

欢迎读 [`CONTRIBUTING.md`](CONTRIBUTING.md) 后带着你的 Crew 来添砖加瓦。

## License

MIT — 给你的 agents 盖一栋办公室吧。
