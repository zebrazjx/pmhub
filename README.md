# PMHub

PMHub 是一套模块化的产品经理求职与实战 Skills。它既覆盖从职业方向、岗位发现、JD、学习补缺、简历到面试的求职链路，也覆盖产品发现、研究、PRD、优先级、指标、交付、发布和复盘等日常 PM 工作。

它不是把所有任务塞进同一条提示词的“万能助手”。每个 Skill 只负责一个清晰阶段，`$pmhub` 负责识别意图、选择组件和传递必要事实。

## 包含的 10 个 Skills

| Skill | 适合什么时候用 | 主要交付 |
|---|---|---|
| `$pmhub` | 不知道从哪里开始，或需要连续完成多个阶段 | 阶段路由、事实衔接、下一步最小动作 |
| `$pmhub-career-planner` | 规划职业路径、转型、地域／行业选择或季度复盘 | 目标与约束、情景路线、决策门、行动与复盘 |
| `$pmhub-ai-pm-role-fit` | 不知道适合哪类 AI 产品经理 | 九类方向的当前切入与长期发展双榜、证据与现实检验 |
| `$pmhub-job-radar` | 从多个公开来源发现、整理和更新岗位 | 统一岗位数据、来源追溯、去重、筛选与增量快照 |
| `$pmhub-jd-reverse-engineer` | 拆一条 JD、找门槛并判断是否值得投 | 三个核心任务、证据矩阵、学习／项目／投递建议 |
| `$pmhub-ai-learning-coach` | 从目标岗位倒推 Agent／AI 产品学习 | 基线诊断、费曼闭环、检索练习、实作评测与复习计划 |
| `$pmhub-ai-native-resume` | HTML 化简历，或根据 JD 生成真实匹配版本 | 可编辑 A4 HTML、PDF 验证、JD 匹配报告 |
| `$pmhub-pm-interview-coach` | 有时间进行完整模拟面试和针对性复训 | 动态追问、Case／行为题训练、评分证据与复训计划 |
| `$pmhub-interview-1h-rescue` | 某场产品经理面试临近，需要集中准备 | 60／30／15 分钟作战包与最后 10 分钟速记 |
| `$pmhub-pm-toolkit` | 需要完成真实的产品经理日常工作 | 从发现到复盘的模式路由、方法选择和可执行工作物 |

白板规划中的“自动生成完整简历”不作为独立 Skill。简历组件只会基于用户提供的真实经历做结构化、HTML 化和定向改写，不会从零编造一份履历。

## 两条主工作流

### 求职链路

```text
职业目标与硬约束
   ↓
职业规划／九类 AI PM 方向诊断（按需）
   ↓
公司官网＋公开 ATS/API＋授权第三方导出／单条输入的岗位雷达
   ↓
单条 JD 的任务、门槛与证据缺口
   ↓
费曼学习与项目补证（按需）
   ↓
真实定向的一页 A4 简历
   ↓
进阶模拟面试 → 临场 1h 急救（按时间选择）
```

已有具体 JD 时可以直接进入 JD 组件；已有定稿简历且马上面试时直接调用急救组件。组件按缺口选择，不要求机械地从头跑到尾。

### PM 实战链路

```text
业务目标／用户问题／现有材料
   ↓
选择最小适用模式
   ↓
发现与研究 → 问题定义 → 方案与 PRD → 优先级与路线图
   ↓
指标与实验 → 交付 → 发布／增长 → 复盘与决策记录
```

`$pmhub-pm-toolkit` 面向真实产品工作，不默认接管求职流程。只有用户希望把工作产物转成求职证据时，才衔接 JD、简历或面试组件。

## 岗位雷达的来源策略

已实现 Greenhouse、Lever（全球／欧洲）、Ashby、SmartRecruiters 四类公开 ATS 接口，以及官网 JobPosting JSON-LD、有界 sitemap、搜索发现和 JSON／JSONL／CSV 授权导入。来源配置、增量状态和运行命令见 [岗位雷达运行手册](skills/pmhub-job-radar/references/runbook.md)。

岗位采集按可靠性和合规性分层：

1. 公司官网与官方公开 ATS／Job Board API：优先使用结构化公开接口，并保留原始职位链接；
2. 其他公开公司招聘页：在站点允许且页面可公开访问时读取，无法稳定结构化时转为搜索发现和人工核验；
3. 第三方招聘平台：只处理官方 API／合作 Feed、平台允许且用户有权使用的导出，或用户主动提供的少量单条岗位；也可通过合规搜索定位同一岗位的公司官网原页；
4. 用户有权使用的 CSV／JSON／已保存公开页面：作为可复现的离线输入，统一标准化、去重和更新。

岗位雷达不绕过登录、验证码、限流、robots 或平台条款，不调用未经证实的私有接口，也不自动投递。搜索摘要只用于发现，投递前应回到公司官网或原始发布页核验状态。

## 使用示例

```text
$pmhub 帮我规划 AI 产品经理求职路径，并从公开来源找到值得跟进的岗位。
$pmhub-career-planner 比较留在当前岗位、转 AI PM 和先做解决方案产品三条路线。
$pmhub-job-radar 追踪这些公司官网和公开 ATS 上新增的北京／远程 AI 产品岗位。
$pmhub-jd-reverse-engineer 判断这条 JD 的三个核心任务，以及我现在该不该投。
$pmhub-ai-learning-coach 针对这条 JD，用费曼法带我补齐 RAG 评测能力。
$pmhub-ai-native-resume 根据目标 JD，把我的简历做成真实匹配的一页 A4 HTML。
$pmhub-pm-interview-coach 按二面标准模拟一场 AI 产品经理面试，连续追问并评分。
$pmhub-interview-1h-rescue 我 30 分钟后面试，请生成最后冲刺包。
$pmhub-pm-toolkit 把这批访谈记录合成机会地图，并起草可交付给研发的 PRD。
```

## 安装（仓库所有者／已获授权用户）

当前仓库未声明开源许可证。下列安装命令仅用于仓库所有者或已明确获得作者授权的用户，不构成向公众授予复制、修改或再分发权利。

克隆仓库：

```bash
git clone https://github.com/zebrazjx/pmhub.git
cd pmhub
```

仓库根目录包含 `.codex-plugin/plugin.json`，可以作为完整 Codex 插件使用。若宿主只按独立 Skill 加载，也可以复制全部 Skill：

```bash
mkdir -p ~/.codex/skills
cp -R skills/pmhub* ~/.codex/skills/
```

不同插件宿主可能会在 Skill 名前显示插件命名空间，例如 `pmhub:pmhub-job-radar`。以客户端展示的完整名称调用即可；Skill 自身名称统一以 `pmhub-` 开头。

## 设计原则

- 以可核验事实和任务证据做判断，不用热词制造“匹配率”；
- 不编造公司、岗位状态、候选人经历、指标、用户研究或市场结论；
- 区分原始事实、外部证据、合理推断、训练表现和待确认项；
- 把 Demo、离线评测、受控试用、真实上线和规模化结果分开；
- 岗位记录保留来源、抓取时间、原始链接和内容指纹；
- 学习掌握度由复述、检索、实作或评测证明，“读过”不等于“会做”；
- 面试训练分只表示本轮回答质量，不表示录用概率；
- PM 方法服务于当前决策，不为了套框架而套框架；
- 单项请求只交付单项，跨阶段请求才由 `$pmhub` 编排。

## 仓库结构

```text
pmhub/
├── .codex-plugin/plugin.json
├── skills/
│   ├── pmhub/                         # 总路由
│   ├── pmhub-career-planner/          # 职业规划
│   ├── pmhub-ai-pm-role-fit/          # AI PM 方向诊断
│   ├── pmhub-job-radar/               # 多来源岗位雷达
│   ├── pmhub-jd-reverse-engineer/     # JD 倒推
│   ├── pmhub-ai-learning-coach/       # Agent／AI 学习教练
│   ├── pmhub-ai-native-resume/        # 证据型 HTML 简历
│   ├── pmhub-pm-interview-coach/      # 进阶模拟面试
│   ├── pmhub-interview-1h-rescue/     # 临场面试急救
│   └── pmhub-pm-toolkit/              # PM 日常实战包
├── tools/validate_repo.py
└── SOURCES.md
```

## 验证

```bash
python3 tools/validate_repo.py
python3 skills/pmhub-ai-pm-role-fit/scripts/score_assessment.py --self-test
python3 skills/pmhub-ai-pm-role-fit/scripts/audit_coverage.py
node --check skills/pmhub-ai-native-resume/assets/template/resume-data.js
node --check skills/pmhub-ai-native-resume/assets/template/script.js
python3 -m py_compile skills/pmhub-job-radar/scripts/job_radar.py
python3 -m unittest discover -s skills/pmhub-job-radar/tests -v
```

日常 CI 使用离线数据。维护者可手动运行 `Public ATS live smoke` 工作流，以 [公开 ATS 示例配置](skills/pmhub-job-radar/examples/public-ats-smoke.json) 检查实网连接和解析；该工作流不会随普通提交或 PR 自动采集，也不会建立持续监控。示例公司仅用于接口验证，岗位数可能为零，来源也可能变化。

CI 会从 `openai/codex` 的固定 commit `b04ed4c50c5cebb198074c3e5aaf712b989313cc` 取得 Codex 官方 Skill 与 Plugin 校验器，并对插件与 10 个 Skill 逐一检查。岗位雷达测试完全使用本地 fixtures，不访问真实招聘网站。

## 来源与改造

套件整合了既有 Skills，并为 PMHub 做了命名空间、Codex 元数据、职责边界和阶段衔接适配。新增 PM 实战包参考公开的产品管理 Skills 与一手方法资料；岗位雷达只接入公开、可归因且允许访问的来源。固定来源、版本和改造说明见 [SOURCES.md](SOURCES.md) 以及各 Skill 的来源参考文件。

## 授权说明

当前仓库尚未声明开源许可证；公开可见不等于自动授予复制、修改或再分发权。第三方如需使用、修改、打包或再分发 PMHub，需先另行获得作者授权。外部参考项目与资料仍适用各自的许可证或使用条款，具体来源与本项目的改造边界见 [SOURCES.md](SOURCES.md)。
