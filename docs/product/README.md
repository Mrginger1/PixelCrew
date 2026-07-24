# PixelCrew Product Desk

这里是 PixelCrew 的产品工作台：用户问题、需求判断、路线图、独立评审和迭代证据都在这里收敛。它不是功能许愿池，也不以文档数量代替交付。

## 谁负责什么

| 角色 | 核心问题 | 主要输出 |
|---|---|---|
| 用户 / Product Owner | 最终要解决什么、什么值得优先 | 目标、约束、验收反馈 |
| 产品负责人 | 为什么做、为谁做、做到什么程度 | PRD、优先级、用户旅程、指标、非目标 |
| 项目负责人 | 如何拆解、依赖如何处理、何时可验收 | 计划、工作包、集成与验收结论 |
| 执行 Crew | 如何实现边界明确的交付 | 代码、设计、文档与阶段报告 |
| 验证 Crew | 需求是否真的满足且没有明显回归 | 测试、体验复核与可复现证据 |
| 项目秘书 | 目前发生了什么、哪里需要关注 | 事实简报、风险与待决事项 |

产品负责人不是秘书，也不是隐藏的工程负责人：秘书整理已有事实，产品负责人维护问题定义和优先级，项目负责人维护交付路径。

## 产品资料

- [`PRODUCT_MANAGER.md`](PRODUCT_MANAGER.md)：产品负责人角色章程
- [`ITERATION_PROCESS.md`](ITERATION_PROCESS.md)：从反馈到发布的需求迭代流程
- [`PRODUCT_REQUIREMENTS.md`](PRODUCT_REQUIREMENTS.md)：当前产品需求基线
- [`UX_REVIEW.md`](UX_REVIEW.md)：独立体验评审
- [`TECHNICAL_REVIEW.md`](TECHNICAL_REVIEW.md)：独立工程评审
- [`ROADMAP.md`](ROADMAP.md)：收敛后的阶段路线图
- [`CYCLE_1_REVIEW.md`](CYCLE_1_REVIEW.md)：首轮生命周期交付与验收证据

三份独立评审已经完成并收敛到路线图；未通过验收的想法不会因为写进文档就自动成为承诺。

## 当前迭代

**Cycle 1 — 启动即可信（已验收，2026-07-24）**

首个产品周期已把“装过但打不开”的真实反馈闭环为 `start / status / open / stop` 生命周期，并完成单元、wheel 安装与源码运行验证。详见 [`CYCLE_1_REVIEW.md`](CYCLE_1_REVIEW.md)。

**下一候选：Cycle 2 — 数据可信且跑得久**

在进入开发前，产品负责人与项目负责人需要先完成 Ready 评审：冻结 Adapter 最小契约、采集性能基线、缓存失效规则和隐私披露边界；未通过 Ready 不直接开始大改采集层。
