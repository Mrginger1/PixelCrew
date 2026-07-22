# Agent Project HQ

一个面向 Codex 多任务项目的**只读像素办公室看板 + Agent 工作架构**。

![Agent Project HQ dashboard](docs/dashboard-preview.png)

它把同一项目工作区里的每个 Codex 任务映射成一名员工：新任务自动入驻，最新计划/汇报显示为人物语言泡泡，文件、模型、视频和报告进入成果柜；负责人、执行成员和验证成员使用同一套可验收工作协议。

## 特性

- 自动发现指定工作区的 Codex 任务，不手工维护员工列表。
- 读取 `update_plan`、最新汇报、任务状态与更新时间。
- 语言泡泡只展示真实任务内容，不生成虚构进度。
- 计划步骤自动换算进度；阻塞、等待、陈旧状态独立显示。
- 每层 6 个工位，任务增多后自动生成办公室楼层。
- 自动提取成果路径并过滤 `/tmp`、缓存和依赖目录。
- Python 标准库实现，无运行时第三方依赖。
- 同步过程只读，不修改 Codex 任务，也不执行成果文件。
- 附带负责人—子任务—独立验收的完整工作模板。

## 30 秒启动

要求 Python 3.10+，并在本机运行 Codex。

```bash
git clone https://github.com/<your-account>/agent-project-hq.git
cd agent-project-hq
python3 scripts/init_project.py /absolute/path/to/your/project --name "My Project"
python3 hq.py --config project-hq.json --port 8765
```

浏览器打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。页面每 60 秒刷新一次。

也可以直接试示例配置：

```bash
cp project-hq.example.json project-hq.json
# 修改 root 和 workspace_match 后启动
python3 hq.py --config project-hq.json --snapshot
python3 hq.py --config project-hq.json
```

## 迁移到另一个项目

只需重新生成配置：

```bash
python3 scripts/init_project.py /path/to/another/project \
  --name "Another Project" \
  --manager-thread-id "optional-thread-id" \
  --output project-hq.another.json
python3 hq.py --config project-hq.another.json --port 8766
```

配置中的关键字段：

| 字段 | 用途 |
|---|---|
| `project.root` | 项目根目录，只用于身份和成果白名单 |
| `project.manager_thread_id` | 指定唯一总负责人；可为空 |
| `discovery.workspace_match` | 匹配 Codex 任务 `cwd` 的字符串 |
| `discovery.title_keywords` | 可选，只保留标题含关键词的任务 |
| `roles` | 可选，把特定任务映射为稳定角色名 |
| `artifacts.allowed_roots` | 允许展示的本地成果根目录 |
| `artifacts.remote_prefixes` | 识别服务器路径；不会连接服务器 |

## 推荐工作方式

1. 用 [`docs/PROJECT_CHARTER_TEMPLATE.md`](docs/PROJECT_CHARTER_TEMPLATE.md) 固化目标、完成定义与硬约束。
2. 总负责人按 [`docs/TASK_BRIEF_TEMPLATE.md`](docs/TASK_BRIEF_TEMPLATE.md) 拆工作包。
3. 执行任务维护结构化计划并提交可复现证据。
4. 高风险结果由独立验证任务复核。
5. 总负责人统一验收并把决策写入项目记忆。

详见 [`docs/OPERATING_MODEL.md`](docs/OPERATING_MODEL.md) 和 [`AGENTS.md`](AGENTS.md)。

## 数据来源与兼容性

默认读取：

- `~/.codex/state_5.sqlite`
- `~/.codex/session_index.jsonl`
- SQLite 中记录的任务 rollout JSONL

这些是本地实现细节，未来 Codex 存储格式变化时可能需要更新适配器。同步器以 SQLite 只读 URI 打开数据库。

## 隐私与安全

- **不要提交生成的 `project-hq.json`**：它通常含本地绝对路径和任务 ID，已被 `.gitignore` 忽略。
- 网页服务默认只监听 `127.0.0.1`，不要直接暴露到公网。
- API 会返回任务摘要和成果路径；只在可信本机使用。
- 同步器不会启动/停止任务、训练或 shell 命令。
- GitHub 版本只包含虚构演示数据，不包含真实项目记录。

## 测试

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile src/agent_project_hq/server.py
python3 hq.py --config project-hq.json --snapshot > /tmp/status.json
```

## License

MIT
