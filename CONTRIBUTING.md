# Contributing to PixelCrew

感谢来给 Crew 添置新家具。

## 开发流程

1. Fork 并创建聚焦单一问题的分支。
2. 保持采集器只读；新智能功能必须可关闭且有确定性降级。
3. 不提交真实 Codex 任务、任务 ID、绝对路径、秘书缓存、令牌或私有成果。
4. UI 修改请同时检查桌面与窄屏，并附截图。
5. 行为修改请补单元测试和文档。

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
