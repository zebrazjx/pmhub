# 训练记录模板

## 训练配置

```yaml
session_id: ""
date: "YYYY-MM-DD"
target_role: ""
jd_core_tasks: []
round: ""
persona: ""
mode: ""
feedback_timing: "per-question|per-module|end"
difficulty: "standard|pressure|executive"
duration_minutes: null
facts_available: []
assumptions: []
```

## 岗位考察蓝图

| 维度 | JD 信号 | 要看到的证据 | 主问题 | 风险信号 |
|---|---|---|---|---|
|  |  |  |  |  |

## 问答记录

```markdown
### Q{n}：{问题}

- 目的：
- 用户回答摘要：
- 关键原话／事实：
- 追问及回答：
- 观察到的维度：
- 分数与证据：
- 反馈：
- 重答变化：
- 仍待核验：
```

不要把教练建议或示范话术记录成用户原话。

## 本轮总结

```markdown
### 本轮结论

- 最强表现：
- 最大风险：
- 未观察维度：
- 优先目标 1：
  - 当前证据：
  - 升级条件：
  - 复训题：
- 优先目标 2：
  - 当前证据：
  - 升级条件：
  - 复训题：
- 待补充／核验事实：
- 下次训练建议日期：
```

## 跨轮趋势

| 日期 | 场景难度 | 维度 | 分数 | 改善状态 | 证据 | 下一步 |
|---|---|---|---:|---|---|---|
|  |  |  |  |  |  |  |

只有使用相近 Rubric 且记录场景难度时才比较分数。优先比较具体行为是否出现，而不是小数总分。

## 暂停检查点

用户暂停时记录以下最小状态；恢复后从 `next_question` 继续，不重开已完成部分。

```yaml
checkpoint:
  session_id: ""
  round: ""
  completed_questions: []
  last_question: ""
  last_answer_summary: ""
  observed_scores: []
  fact_anchors: []
  unanswered_question: ""
  next_question: ""
  saved_at: "YYYY-MM-DDTHH:MM:SS+08:00"
```

`observed_scores` 中每项保留维度、分数、行为证据与置信度。`fact_anchors` 只收录用户已经确认的经历、动作和数字；教练范文、推断与待核验内容不得进入。
