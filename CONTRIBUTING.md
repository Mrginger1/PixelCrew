# Contributing to PixelCrew

感谢来给 Crew 添置新家具。

## 开发流程

1. Fork 并创建聚焦单一问题的分支。
2. 保持采集器只读；新智能功能必须可关闭且有确定性降级。
3. 不提交真实 Codex 任务、任务 ID、绝对路径、秘书缓存、令牌或私有成果。
4. UI 修改请同时检查桌面与窄屏，并附截图。
5. 行为修改请补单元测试和文档。

## 从需求到开发

提交功能前，请先使用 GitHub 的“Product idea / 功能建议”模板描述用户问题、受影响用户和期望结果。产品负责人会按 [`docs/product/ITERATION_PROCESS.md`](docs/product/ITERATION_PROCESS.md) 将需求置于 `Inbox / Discovery / Ready / Delivery / Validation / Shipped`；只有满足 Definition of Ready 的需求才进入迭代。

优先阅读 [`docs/product/PRODUCT_REQUIREMENTS.md`](docs/product/PRODUCT_REQUIREMENTS.md) 与 [`docs/product/ROADMAP.md`](docs/product/ROADMAP.md)。路线图不是功能许愿池：提案应说明它为何比当前 P0/P1 更重要，且不能破坏 local-first、read-only 和默认不依赖 LLM 的边界。

## 本地检查

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile src/pixelcrew/*.py scripts/init_project.py pixelcrew.py
python3 -m pip wheel . -w /tmp/pixelcrew-wheel
```

提交前再运行 `git diff --check`，并检查演示数据全部为虚构内容。

## 设计约束

- 前端应保持零构建步骤，方便单文件部署和 pip 打包。
- 不以 LLM 输出替换原始事实；需要显示来源和更新时间。
- 新指标必须能解释，不能用对话量或虚假 ETA 代替进度。
- 新成果链接必须经过允许根目录过滤。

安全问题不要公开 issue，请按 [`SECURITY.md`](SECURITY.md) 私下报告。
