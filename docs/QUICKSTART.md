# PixelCrew 快速开始

## 0. 前提

- Python 3.10+
- Codex Desktop 或 Codex CLI 已登录
- 目标项目至少有一个以该项目目录为工作目录的 Codex 任务

## 1. 安装

```bash
git clone https://github.com/Mrginger1/PixelCrew.git
cd PixelCrew
python3 -m pip install -e .
```

## 2. 自动搭办公室

```bash
pixelcrew init /absolute/path/to/project --name "Project Name"
pixelcrew doctor
pixelcrew start
pixelcrew status
pixelcrew open
```

`open` 会打开 `http://127.0.0.1:8765`。到这里已经完成，不需要 LLM，也不需要手工登记员工。

`init` 写入本地 `pixelcrew.json`；`start` 在后台启动只监听本机的服务，并在项目的 `.pixelcrew/` 下保存 PID、身份令牌和日志。`status` 会同时检查配置、进程身份和 `/api/status` 健康状态。每个新任务会自动变成 Crew，页面每 60 秒刷新。

常用生命周期命令：

```bash
pixelcrew status       # 查看 URL、PID 和日志
pixelcrew open         # 只在服务健康时打开本地页面
pixelcrew stop         # 仅停止身份可验证的本项目 PixelCrew 进程
pixelcrew serve        # 兼容入口：保持服务在当前终端前台运行
```

## 3. 可选：指定负责人和昵称

初始化时可传负责人任务 ID：

```bash
pixelcrew init /path/to/project --manager-thread-id "..." --force
```

或编辑本地配置：

```json
{
  "roles": {
    "codex-thread-id": {
      "id": "researcher",
      "name": "动作研究员",
      "assignment": "探索、筛选并归档动作数据"
    }
  }
}
```

不配置也能工作；角色只是改善稳定命名和职责表达。

## 4. 可选：启用 AI 秘书

```bash
pixelcrew secretary --dry-run
pixelcrew secretary
```

第一次命令只展示脱敏后的模型输入，第二次才使用当前 Codex 登录发起模型调用。页面自动读取缓存；失败时保留规则秘书。

## 5. 多项目

每个项目生成一份配置，用不同端口启动：

```bash
pixelcrew init /path/to/project-b --output pixelcrew.b.json
pixelcrew start --config pixelcrew.b.json --port 8766
pixelcrew open --config pixelcrew.b.json
# 停止时使用同一配置：pixelcrew stop --config pixelcrew.b.json
```

## 常见问题

### 发现 0 个任务

运行 `pixelcrew doctor`，确认任务工作目录与 `discovery.workspace_match` 一致。必要时调整该字段，不要修改网页。

### 里程碑从哪里来

Crew 调用 `update_plan` 时，在 `explanation` 写 2–4 句阶段总结。PixelCrew 会保存当时的完成步骤、当前步骤、进度变化和时间，点击员工档案中的记录即可展开。

### 能直接公开服务吗

不建议。API 会返回本地任务摘要和允许范围内的成果路径。默认只监听 `127.0.0.1`，请保持本机使用或自行增加认证反向代理。
