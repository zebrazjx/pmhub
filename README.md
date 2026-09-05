# PMHub

PMHub 是一套模块化的产品经理求职 Skills：方向不清时可以先比较九类 AI 产品经理方向，也可以直接从目标岗位 JD 出发，把岗位要求翻译成可验证证据，落到简历和面试。

它不是一个把所有任务塞进同一提示词的“万能助手”。每个 Skill 只负责一个清晰阶段，`$pmhub` 负责路由与衔接。

## 包含的 Skills

| Skill | 适合什么时候用 | 主要交付 |
|---|---|---|
| `$pmhub` | 不知道从哪里开始，或要连续完成多个阶段 | 识别阶段、调用组件、保持事实一致 |
| `$pmhub-ai-pm-role-fit` | 不知道适合哪类 AI 产品经理，或准备转型／选择实习校招方向 | 九类方向的当前切入与长期发展双榜、证据、现实检验 |
| `$pmhub-jd-reverse-engineer` | 拆一条 JD、判断真 AI／AI 标签、找门槛与准备重点 | 三个核心任务、证据矩阵、学习／项目／投递建议 |
| `$pmhub-ai-native-resume` | 把简历 HTML 化，或根据 JD 生成真实匹配版本 | 可编辑 A4 HTML、PDF 验证、JD 匹配报告 |
| `$pmhub-interview-1h-rescue` | 某场产品经理面试临近，需要集中准备 | 60／30／15 分钟作战包与最后 10 分钟速记 |

## 推荐工作流

```text
AI PM 方向不清时
   ↓
九类方向诊断与现实检验（按需）
   ↓
目标 JD
   ↓
岗位任务、硬门槛与证据缺口
   ↓
真实定向的一页 A4 简历
   ↓
基于同一证据的面试故事与临场速记
```

可以跳过不需要的阶段。已有具体 JD 时直接调用 JD 组件，不必先做方向诊断；已有定稿简历且马上面试时直接调用面试组件。

## 安装

克隆仓库：

```bash
git clone https://github.com/zebrazjx/pmhub.git
cd pmhub
```

仓库根目录包含 `.codex-plugin/plugin.json`，可作为完整 Codex 插件使用。若当前客户端只按独立 Skill 加载，也可以复制全部 Skill：

```bash
mkdir -p ~/.codex/skills
cp -R skills/pmhub* ~/.codex/skills/
```

重新打开任务后，即可显式调用：

```text
$pmhub 帮我从这条 JD 开始，完成岗位判断、定向简历和面试准备。
```

或直接调用某个组件：

```text
$pmhub-ai-pm-role-fit 帮我判断最适合当前切入和长期发展的 AI 产品经理方向。
$pmhub-jd-reverse-engineer 判断这条 JD 的三个核心任务，以及我该不该投。
$pmhub-ai-native-resume 根据这份 JD，把我的简历做成一页 A4 HTML。
$pmhub-interview-1h-rescue 我 30 分钟后面试，请生成最后冲刺包。
```

不同插件宿主可能会在 Skill 名前再显示插件命名空间，例如 `pmhub:pmhub-jd-reverse-engineer`。这时以客户端展示的完整名称调用即可；Skill 自身名称仍统一以 `pmhub-` 开头。

## 设计原则

- 以任务证据匹配岗位，不按热词数量制造“匹配率”；
- 方向诊断同时区分长期适配与当前准备；MBTI、星座只作叙事入口，不参与评分；
- 不编造经历、数字、技术、个人贡献、公司事实或上线状态；
- 把 Demo、离线评测、受控试用、真实上线和规模化结果分开；
- 同一份候选人事实贯穿 JD、简历和面试，不在下游逐步升级；
- 单项请求只交付单项，端到端请求才由 `$pmhub` 编排。

## 仓库结构

```text
pmhub/
├── .codex-plugin/plugin.json
├── skills/
│   ├── pmhub/
│   ├── pmhub-ai-pm-role-fit/
│   ├── pmhub-jd-reverse-engineer/
│   ├── pmhub-ai-native-resume/
│   └── pmhub-interview-1h-rescue/
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
```

仓库还通过 Codex 的 Skill 与 Plugin 官方校验脚本进行发布前检查。

## 来源与改造

套件整合了既有 Skills，并为 PMHub 做了命名空间、Codex 元数据、职责边界和阶段衔接适配。固定来源版本见 [SOURCES.md](SOURCES.md)。原始组件仍可独立使用。

当前仓库尚未声明开源许可证；公开可见不等于自动授予复制、修改或再分发权。
