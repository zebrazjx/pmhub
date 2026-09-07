# 学习状态与证据模板

在需要跨轮次继续、多人协作或交接给简历／面试 Skill 时使用。可输出为 Markdown，不要求创建文件，除非用户明确要求保存。

## 学习状态

```yaml
goal:
  target_role: ""
  target_tasks: []
  deadline: ""
  weekly_hours: null
constraints:
  tools: []
  data_privacy: ""
  budget: ""
assumptions: []
units:
  - id: "rag-retrieval-01"
    topic: ""
    jd_task: ""
    current_level: "unknown"
    evidence: []
    misconceptions: []
    next_action: ""
    next_review: "YYYY-MM-DD"
    interval_days: 1
    attempts: 0
projects:
  - name: ""
    status: "idea|building|evaluated|evidence-ready"
    artifact: ""
    evaluation: ""
    failure_review: ""
updated_at: "YYYY-MM-DD"
```

只记录用户明确提供或当轮可观察到的表现。`unknown` 不得改写为失败，计划中的项目不得标为完成。

## 单元卡

```markdown
### 单元：{名称}

- 对应岗位任务：
- 学完能够：
- 当前层级／证据：
- 关键原理：
- 产品决策：
- 最小实作：
- 验收标准：
- 复述题：
- 迁移题：
- 常见失败：
- 下次复习：
```

## 项目证据卡

```markdown
### 项目：{名称}

- 目标用户与任务：
- 真实约束：
- 基线：
- 方案与备选：
- 关键个人决策：
- 数据／测试集：
- 指标与结果：
- 失败样本及根因：
- 调整与取舍：
- 可核验产物：
- 尚不能证明：
- 可支持的 JD 要求：
```

## 周计划

| 本周结果 | 学习单元 | 主动练习 | 项目产物 | 验收方式 | 预计时间 |
|---|---|---|---|---|---:|
|  |  |  |  |  |  |

## 周末复盘

1. 哪个结论现在可以无提示解释？
2. 哪个决策题仍依赖模板？
3. 哪次失败暴露了真正缺口？
4. 哪项产物已经可供别人审查？
5. 下周应继续、降级还是删除哪个单元？

## 向其他 Skill 交接

只传递可验证内容：

- 目标岗位任务；
- 已达到的层级及证据；
- 项目证据卡；
- 尚未证明的能力；
- 用户认可的事实边界。

不要把学习时的示例数字、理想答案或计划目标转写成简历事实。
