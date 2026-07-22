# PixelCrew 🧑‍💻🏢

> **Your agents have desks now.**

PixelCrew 把一个看不见的多任务项目，变成一间会自己更新的像素办公室。

每个 Codex 任务是一名 Crew：新任务会自动找到工位，最新汇报会冒成语言泡泡，计划变成进度条，模型、视频、报告和数据则被收进成果柜。项目换了？不用重画页面——换一份配置，整支 Crew 搬进新办公室。

![PixelCrew dashboard](docs/dashboard-preview.png)

## 办公室里发生了什么？

| 真实项目 | PixelCrew 世界 |
|---|---|
| Codex 项目任务 | 一名有工位的 Crew |
| 总规划任务 | 办公室负责人 |
| `update_plan` | 桌边任务板与进度条 |
| 最新汇报 | 人物头顶的语言泡泡 |
| 阻塞或等待 | 状态灯与需要关注区 |
| 模型、视频、报告 | 成果柜里的战利品 |
| 超过 6 个任务 | 自动开放下一层办公室 |

语言泡泡只引用真实任务记录；PixelCrew 不会为了让画面热闹而编造进度。

## 为什么不只是一个漂亮看板？

PixelCrew 同时带了一套轻量的 Agent 工作架构：

- **总负责人**拥有目标、依赖图和最终验收权；
- **执行 Crew**只拿边界清晰、可独立交付的工作包；
- **验证 Crew**不重复实现，只提交可复现证据；
- **等待就是等待**，不会伪装成“仍在高速推进”；
- **完成必须带证据**，不能只说“应该可以”。

工作协议见 [`AGENTS.md`](AGENTS.md)，完整方法见 [`docs/OPERATING_MODEL.md`](docs/OPERATING_MODEL.md)。

## 30 秒让 Crew 入驻

要求 Python 3.10+，本机已使用 Codex。运行时无第三方依赖。

```bash
git clone https://github.com/<your-account>/pixelcrew.git
cd pixelcrew

# 为任意项目生成一份本地配置
python3 scripts/init_project.py /absolute/path/to/your/project \
  --name "My Fantastic Project"

# 先看看发现了哪些任务，再打开办公室
python3 pixelcrew.py --config pixelcrew.json --snapshot
python3 pixelcrew.py --config pixelcrew.json --port 8765
```

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。办公室每 60 秒自动刷新。

## 给另一个项目搬家

前端不用改一行。生成第二份配置并换个端口即可：

```bash
python3 scripts/init_project.py /path/to/another/project \
  --name "Another Adventure" \
  --manager-thread-id "optional-thread-id" \
  --output pixelcrew.another.json

python3 pixelcrew.py --config pixelcrew.another.json --port 8766
```

同一套 PixelCrew 可以服务代码开发、科研实验、内容制作、机器人训练、数据分析或其他任何以 Codex 任务推进的项目。

## 配置地图

复制 [`pixelcrew.example.json`](pixelcrew.example.json)，或使用初始化脚本生成：

| 字段 | 作用 |
|---|---|
| `project.root` | 项目根目录，也是默认成果白名单 |
| `project.manager_thread_id` | 可选：指定唯一总负责人 |
| `discovery.workspace_match` | 匹配 Codex 任务工作目录 |
| `discovery.title_keywords` | 可选：只接纳标题含关键词的任务 |
| `roles` | 可选：给固定任务配置稳定角色名 |
| `artifacts.allowed_roots` | 哪些本地路径可以进入成果柜 |
| `artifacts.remote_prefixes` | 哪些路径显示为服务器成果；不会自动连接 |

没有角色配置的新任务也会自动成为 Crew，并依更新时间获得工位。

## 推荐开局流程

1. 用 [`PROJECT_CHARTER_TEMPLATE.md`](docs/PROJECT_CHARTER_TEMPLATE.md) 写清目标、完成定义和硬约束。
2. 总负责人按 [`TASK_BRIEF_TEMPLATE.md`](docs/TASK_BRIEF_TEMPLATE.md) 拆分互不冲突的工作包。
3. 执行 Crew 维护结构化计划，并提交文件与验证证据。
4. 高风险成果交给独立验证 Crew。
5. 总负责人统一验收，把决定和成果归档。

## PixelCrew 读取什么？

默认以只读方式读取：

- `~/.codex/state_5.sqlite`
- `~/.codex/session_index.jsonl`
- SQLite 记录的任务 rollout JSONL

这些是 Codex 的本地实现细节；如果未来存储格式改变，只需替换采集适配层，办公室数据模型与页面无需重做。

## 隐私护栏 🔒

- 生成的 `pixelcrew.json` 通常含本地路径和任务 ID，已默认加入 `.gitignore`。
- 服务默认只监听 `127.0.0.1`；不要直接暴露到公网。
- `/api/status` 会返回任务摘要和成果路径，只应在可信本机使用。
- PixelCrew 不会启动、停止或修改任务，不执行训练，也不打开成果文件。
- 仓库中的演示员工和任务全部为虚构数据。

## 验证

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile src/pixelcrew/server.py
python3 pixelcrew.py --config pixelcrew.json --snapshot > /tmp/pixelcrew-status.json
```

## License

MIT — 给你的 Crew 盖一栋新办公室吧。
