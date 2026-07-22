# 项目秘书

PixelCrew 有两层秘书能力。

## 规则秘书（默认）

随每次快照即时生成，不调用模型。它统计正在推进、完成、阻塞和等待的 Crew，并从关注队列和当前计划形成简报与建议动作。办公室始终可以仅靠这一层工作。

## Codex AI 秘书（显式启用）

AI 秘书把多个员工的阶段进展串成一份负责人简报，适合回答“主线卡在哪里”“任务间有什么依赖”“下一步先协调什么”。它不会创建办公室，也不会更改任务。

```bash
pixelcrew secretary --config pixelcrew.json --dry-run
pixelcrew secretary --config pixelcrew.json
pixelcrew secretary --config pixelcrew.json --watch --interval 900
```

### 接入方式

- 复用用户现有 Codex 登录，无需另配 OpenAI API Key。
- 使用 `codex exec --ephemeral`，会话不持久化。
- 沙箱为 `read-only`，审批策略为 `never`，秘书任务不执行外部操作。
- 模型输出受 JSON Schema 约束并原子写入本地缓存。
- 看板读取缓存；无缓存、过期或调用失败时降级为规则秘书。

### 隐私边界

发送模型前只保留项目名称、汇总指标、角色名、任务标题、计划、阶段摘要和成果文件名。代码会移除：

- Codex task/thread ID；
- Unix/Windows 绝对路径；
- 常见 API key 字样和 `sk-...` token；
- UUID 样式的任务标识。

先运行 `--dry-run` 可人工检查完整输入。脱敏是纵深防御而非万能 DLP：若任务文字本身含公司机密、客户数据或不规则密钥，请关闭 AI 秘书或在使用前自行审查。

### 成本与刷新

PixelCrew 不会默认偷偷调用模型。每次普通 `secretary` 是一次显式调用；`--watch` 会按用户给定间隔持续调用，直到进程停止，可能产生相应额度或费用。推荐先手动调用，确定价值后再配置值班进程。

### 配置

```json
{
  "secretary": {
    "enabled": true,
    "cache": "/project/.pixelcrew/secretary.json",
    "max_age_minutes": 180
  }
}
```

`enabled: false` 会关闭页面上的增强提示。缓存属于项目本地状态，不应提交到 Git。
