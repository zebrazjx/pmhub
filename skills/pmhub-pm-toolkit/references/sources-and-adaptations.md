# 来源与自主设计说明

资料核对日期：2026-09-07。本文记录设计时查看的公开来源、许可证和抽象层面的借鉴。`pmhub-pm-toolkit` 的中文指令、路由、账本、模板和质量门均为本项目重新设计与撰写；没有复制任何来源的长段文字、完整模板或示例。

## 1. 公开 PM Agent Skills

| 来源 | 核对版本／许可 | 观察到的设计价值 | 本 Skill 的处理 |
|---|---|---|---|
| [Anthropic knowledge-work-plugins／product-management](https://github.com/anthropics/knowledge-work-plugins/tree/main/product-management) | commit `1f517b9`; 子目录 `product-management/LICENSE` 为 Apache-2.0 | 以研究综合、规格、路线图、迭代、指标和干系人更新等任务分流；连接器是可选能力 | 借鉴“按任务路由、外部系统可选”的产品形态；自主加入端到端证据链、未知项与决定闭环，未复制其流程文本或连接器语法 |
| [Mind the Product／skills](https://github.com/mindtheproduct/skills) | commit `3fb3d46`; MIT | 单一高价值决策实践、分阶段按需加载、最后形成决策快照 | 借鉴“复杂决策分阶段、入口保持小”的信息架构；本 Skill 用四种交互模式和六类参考文件实现，问题、标签和快照均重新设计 |
| [quitecommlt／product-manager-skill](https://github.com/quitecommlt/product-manager-skill) | commit `cf16be0`; MIT | 快速／结构化／深度／成品等输出深度，以及模板与 playbook 分离 | 借鉴“深度随请求调整、细节延迟加载”的原则；本 Skill 改为快速产物／审查／工作坊／端到端循环，并围绕决定风险选深度 |
| [warren-wupeng／pm-skills](https://github.com/warren-wupeng/pm-skills) | commit `76f66e8`; MIT | 将 JTBD、机会树、PRD、路线图、用户故事等拆成可组合单项能力 | 用其覆盖面做缺项核对；本 Skill 不复制其多 Skill 编排，而在一个独立 Skill 内通过模式路由保持上下文真源 |
| [assimovt／productskills](https://github.com/assimovt/productskills) | commit `66f9cee`; MIT | 一组短小、方法驱动的发现、优先级、PRD、实验和路线图 Skills | 用作能力覆盖对照；保留“框架服务具体决定”的思想，同时取消僵硬的固定阈值和一刀切规则 |
| [pratikshadake／claude-product-management-skills](https://github.com/pratikshadake/claude-product-management-skills) | commit `0f81a86`; MIT | 针对问题清晰度、假设、采用、路线图现实度和上线学习的独立检查器 | 借鉴“把质量风险变成可审查门”的方向；本 Skill 将门槛融入每个模式并回写共同台账 |
| [phuryn／pm-skills](https://github.com/phuryn/pm-skills) | commit `18468a95b427e70e258b51389796367c6f684e7d`（tag `v2.1.0`）；MIT | 产品发现、执行、数据、GTM、策略等广覆盖目录及工作流 | 用作生命周期覆盖检查；本 Skill 选择更小的入口和五个领域参考，避免一次加载百项能力 |
| [Digidai／product-manager-skills](https://github.com/Digidai/product-manager-skills) | commit `ab7a406`; CC BY-NC-SA 4.0 | 领域路由、先产出有用草案、显式假设和取舍 | **只作竞品结构观察**。因其许可证包含非商业与相同方式共享条件，本项目未复制或改编其文本、模板、示例和固定表达 |

仓库许可证以核对版本中的 `LICENSE` 为准；未来上游变更不自动改变本项目内容或许可。

## 2. 权威框架与一手资料

| 来源 | 用于校准的核心点 | 自主适配 |
|---|---|---|
| [Atlassian：Product management](https://www.atlassian.com/agile/product-management) | 产品管理关注客户和长期结果，区别于只管理任务／时间 | 路由把机会、结果型路线图和交付计划分层 |
| [Atlassian：Agile roadmaps](https://www.atlassian.com/agile/product-management/roadmaps) | 路线图提供愿景和日常工作的上下文，应随学习演进；可用 Now／Next／Later | 不禁止真实日期；在合同／法规等硬日期场景允许日期，但要求承诺级别、依赖与复查触发器 |
| [Atlassian：DACI](https://www.atlassian.com/blog/teamwork/daci-method-for-better-project-decisions) | Driver、唯一 Approver、Contributors、Informed 的决策角色 | 形成高影响决定的 DACI 卡，并补充制度性阻断权和升级规则 |
| [Atlassian：Retrospectives](https://www.atlassian.com/agile/scrum/retrospectives/) | 复盘服务持续改进，行动需要明确负责人并跟进 | 区分产品结果、团队过程和事故三类复盘；所有行动回写日志并在下次检查 |
| [Productboard：What is Productboard](https://support.productboard.com/hc/en-us/articles/360058147693-What-is-Productboard) | 聚合用户反馈、连接洞察与功能、按业务目标选择优先级并共享路线图 | 设计 Signal ID → Evidence ID → Opportunity ID → Decision ID 的追踪链 |
| [Product Talk：Opportunity Solution Trees](https://www.producttalk.org/opportunity-solution-tree/) | 从目标结果连接客户机会、多个方案与假设测试，支持持续发现 | 机会树仅作为发现地图；不允许从既定功能反向编造用户问题，测试结果进入证据账本 |
| [Christensen Institute：Jobs to Be Done](https://www.christenseninstitute.org/theory/) | JTBD 关注特定情境下促使人改变行为的进展 | 模板同时记录情境、功能／情绪／社会进展、现有替代与切换阻力 |
| [Nielsen Norman Group：Interviewing Users](https://www.nngroup.com/articles/interviewing-users/) | 访谈适合部分探索问题，但不能替代行为观察或可用性证据 | 研究方法表明确每种方法能回答和不能证明什么，禁止模拟用户冒充真实证据 |
| [Google Research：HEART](https://research.google/pubs/measuring-the-user-experience-on-a-large-scale-user-centered-metrics-for-web-applications/) | 从用户体验目标映射信号和规模化指标 | HEART 作为按需透镜，不要求五维全选；所有指标进入统一指标契约 |
| [Amplitude：North Star Framework](https://amplitude.com/books/north-star/about-north-star-framework) | 北极星代表用户获得的价值，并由可行动输入推动，作为业务结果领先信号 | 增加护栏指标和因果假设标签，避免把北极星当万能 KPI |
| [Intercom：RICE](https://www.intercom.com/blog/rice-simple-prioritization-for-product-managers/) | Reach、Impact、Confidence、Effort 让排序输入显式化 | 保留公式，但要求统一单位、输入依据、区间和敏感性检查；不以小数差异伪装确定性 |
| [Intercom：Deliver outcomes](https://www.intercom.com/blog/product-principles-deliver-outcomes/) | 发版后仍需观察是否解决目标问题并产生用户／业务结果 | 上线不是完成，必须在指标成熟窗后作扩大、维持、修改、回滚或停止决定 |
| [Scrum Guides：Scrum Guide 2020](https://scrumguides.org/scrum-guide.html) | Product Goal、Sprint Goal、透明检查与适应；团队对可用增量负责 | 交付模式强调目标、可验证切片、检查点与适应，不强制所有团队使用 Scrum 术语 |
| [Basecamp：Shape Up／Set Boundaries](https://basecamp.com/shapeup/1.2-chapter-03) | 先设投入 appetite，以固定时间和可变范围促成取舍 | 用于范围切片和容量讨论；不强制六周周期，也不把估算完全替换成 appetite |

## 3. 本项目的原创整合

下列设计不是从某一个上游模板移植：

1. **贯穿式三账本**：证据账本保存原始信号与边界，未知项台账按“若为假影响”驱动研究，决策日志保存当时理由、异议和复查条件。
2. **可追踪产品链**：`Signal → Evidence → Insight／Opportunity → Outcome → Decision → Requirement／Experiment → Metric → Learning`，允许明确标出断链。
3. **风险相称的文档深度**：一页实验说明、轻量 PRD、完整 PRD、决策包四级，不以篇幅作为质量指标。
4. **框架选择门**：先确认比较层级和待解决未知，再选 RICE、加权表、范围分级或假设测试，拒绝多模型机械平均。
5. **指标契约**：将公式、人群、时间窗、排除、数据质量、基线、Owner 和决策用途放在同一记录，降低口径漂移。
6. **三类复盘分离**：产品结果、团队过程、事故分别处理，但都更新证据、未知和决定。
7. **真实日期的条件化处理**：路线图默认表达结果与不确定性；遇到法规、合同或活动窗口时保留日期并公开承诺和风险，而不是教条地去日期。
8. **AI 产品补充门**：对模型质量、评测集、权限、提示注入、人在回路、成本和降级单列要求，但不把通用 PM 工作强制 AI 化。

## 4. 使用和维护原则

- 新增框架前先证明它能改变路由、决定或质量门；仅增加名词不构成价值。
- 上游来源只用于校准覆盖面和概念准确性。需要引用原文时应直接链接，并遵守对应许可和引用限制。
- 模板只提供结构；具体事实、数字、用户原话、团队估算和组织共识必须来自用户材料或可核验数据。
- 定期复查外链、许可证和框架原始定义，但不因上游更新自动覆盖本项目的自主设计。
