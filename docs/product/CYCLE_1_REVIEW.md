# Cycle 1 结果复盘：启动即可信

> 验收日期：2026-07-24
> 对应版本：v0.4.0
> 结果：**达到**

## 用户问题

用户已经安装或克隆 PixelCrew，但无法判断办公室是否仍在运行、地址和日志在哪里；终端退出后页面不可达时，也缺少明确的恢复路径。

## 本轮交付

- `pixelcrew start`：默认后台启动，等待 `/api/status` 健康后才报告成功；
- `pixelcrew status`：区分配置错误、已退出、进程存活但服务不可达和健康运行；
- `pixelcrew open`：只打开经过计算和健康检查的 `127.0.0.1` 地址；
- `pixelcrew stop`：验证 PID、随机进程令牌和命令身份后才发送信号；
- `.pixelcrew/server.json` 与 `server.log`：在被管理项目内保存状态与诊断证据；
- 保留 `serve` 兼容入口，并支持已安装 wheel 与源码 checkout 两种运行方式；
- 中英文 README、快速开始、架构文档和 CLI 测试同步更新。

## 验收证据

1. `python3 -m unittest discover -s tests -v`：26 项通过；覆盖并发保护、重复启动、端口冲突、坏配置、不可达服务、PID 身份不匹配、安全停止、本地 URL 打开，以及 SIGTERM 恰在子进程创建期间到达的回收路径。
2. `python3 -m py_compile src/pixelcrew/*.py scripts/init_project.py pixelcrew.py`：通过。
3. Python 3.12 隔离 venv 安装构建出的 `pixelcrew-0.4.0` wheel，完成：
   `init → start(8887) → status → GET /api/status（含实例令牌握手）→ stop → status(exit 1)`。
4. 未安装 console package 的源码 checkout 完成后台、并发及前台生命周期：
   `python3 pixelcrew.py init → start → status → GET /api/status → stop`。
5. 并发双 `start` 实测只产生一个 PID；普通前台运行和健康检查阶段收到 SIGTERM 时，父进程均以 143 退出、子进程被回收、状态落为 `stopped`，测试端口不再监听。
6. `git diff --check`：通过。
7. 独立安全复审结论：无 P0/P1，Cycle 1 可验收。

以上测试均使用临时目录和 8884–8887 端口，没有停止用户现有的 8765 服务。

## 剩余风险

- macOS 自带 Python 可能低于项目要求的 3.10，安装失败仍需在 `doctor` 之前由安装说明解释；
- 状态文件是本地诊断状态，不是跨重启的通用守护进程；
- SIGKILL 仅在 SIGTERM 超时且进程身份再次验证后使用；仍需持续覆盖平台差异；
- 本轮解决服务生命周期，不解决 Codex rollout 全量解析的性能和兼容性问题。

## 路线判断

Cycle 1 关闭。下一轮优先进入 **Cycle 2 的 Ready 评审**，先冻结版本化 Adapter 与增量快照契约，再开始采集层改造；不提前叠加纯视觉功能。
