# 统一 Job Schema

`scripts/job_radar.py` 输出 UTF-8 JSONL，每行一个岗位对象。字段缺失时使用 `null`、空字符串或空数组，不推测未知事实。

## 顶层字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `schema_version` | string | 当前为 `1.0` |
| `job_uid` | string | 本地稳定 ID；优先从 canonical URL，其次从来源外部 ID 生成 |
| `external_id` | string/null | Provider 公开的岗位 ID |
| `company` | string | 公司名；源数据未给出时可用配置中的已知公司名 |
| `title` | string | 职位名 |
| `description_text` | string | 去除 HTML 后的 JD 文本；搜索摘要不冒充完整 JD |
| `department` / `team` / `seniority` | string/null | 组织和级别信息 |
| `employment_type` | string/null | 全职、实习、合同等原始或近义值 |
| `workplace_type` | string/null | `remote` / `hybrid` / `on-site` / `unspecified` |
| `locations` | array | 结构见下文；多地点不压成单个字符串 |
| `salary` | object/null | 公开薪酬范围；不自行换算或猜测 |
| `posted_at` / `updated_at` / `expires_at` | string/null | ISO 8601 时间；保留源精度 |
| `job_url` | string | 岗位详情页 |
| `apply_url` | string/null | 官方申请页；本 Skill 不访问或提交 |
| `canonical_url` | string | 移除 fragment 和已知跟踪参数后的 URL |
| `language` | string/null | 源显式提供时记录，不用简单字符匹配猜语言 |
| `status` | string | `open` / `closed` / `expired` / `unknown` |
| `freshness_status` | string | `fresh` / `aging` / `stale` / `expired` / `unknown` |
| `quality_score` | integer | 0–100 的可解释完整度／来源分，不是录用率或岗位匹配度 |
| `quality_flags` | array[string] | 缺字段、日期未知、搜索发现、可疑语言等审核标记 |
| `content_fingerprint` | string | 标准化公司、标题、地点与 JD 文本后的 SHA-256 |
| `provenance` | array | 每个观测来源，不在去重时丢弃 |

## 嵌套对象

### `locations[]`

```json
{
  "raw": "Shanghai / Remote",
  "city": "Shanghai",
  "region": null,
  "country": "CN",
  "remote": true
}
```

`raw` 保留源表达；其他字段只在源数据可靠提供时填写。

### `salary`

```json
{
  "min": 30000,
  "max": 50000,
  "currency": "CNY",
  "interval": "MONTH",
  "text": "30k–50k CNY / month"
}
```

数值与区间必须来自原始岗位。只有一段薪酬文字时可仅填 `text`；不做汇率、税前税后、月薪年薪换算。

### `provenance[]`

```json
{
  "source_id": "acme-greenhouse",
  "provider": "greenhouse",
  "source_class": "official_ats",
  "source_url": "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true",
  "job_canonical_url": "https://boards.greenhouse.io/acme/jobs/123",
  "external_id": "123",
  "content_fingerprint": "...",
  "observed_at": "2026-09-07T10:30:00+00:00",
  "fetched_via": "documented_public_api"
}
```

去重后将多个 provenance 合并。`job_canonical_url` 和“来源＋`external_id`”用于在来源暂时失败时维持 SQLite 内的合并身份，`content_fingerprint` 保留当次去重证据；它们不是新的网络请求。不将 API 密钥、Search Engine ID、Cookie、Authorization header 或本地私有路径写入 `source_url`。

## URL 归一化

1. host 和 scheme 小写，移除默认端口；
2. 移除 fragment；
3. 移除 `utm_*`、`source`、`ref`、`gh_src`、`lever-source` 等已知跟踪参数；
4. 保留岗位 ID、语言、地点等可能改变资源语义的参数；
5. 对保留参数排序，非根路径移除末尾 `/`。

## 去重策略

依次尝试：

1. canonical URL 完全一致；
2. content fingerprint 完全一致，且不存在“同一来源但外部 ID 与 URL 均不同”的身份冲突。

合并时优先官方 ATS／官网，保留更长的 JD 文本、所有 provenance 和 URL 别名。不只用公司＋标题＋地点合并：这会错合并多个同名 Headcount。同源同文但不同 ID／URL 的记录保留独立，并标记 `possible_duplicate_same_source_identity_conflict`；其他内容差异较大的近似记录也保留为独立岗位，交给人工确认。

## 时效

使用 `posted_at`，缺失时才用 `updated_at`：

- `fresh`：不超过配置的 fresh 天数，默认 7 天；
- `aging`：超过 fresh，但不超过 stale 天数，默认 30 天；
- `stale`：超过 stale 天数，但原始来源仍表示 active；
- `expired`：`expires_at` 已过期；
- `unknown`：无可用日期。

`stale` 不等于 `closed`，日期缺失也不等于刚发布。

## 增量状态

- `new`：本地状态库中首次出现的 `job_uid`；
- `changed`：已有 `job_uid` 的 `content_fingerprint` 变化；
- `unchanged`：本次观测与上次指纹一致；
- `closed`：岗位在成功且完整的同一来源快照中连续缺失达到阈值，并且没有其他 active 来源。
- `reopened`：先前已标记 `closed` 的本地稳定岗位身份再次出现在有效快照中。

失败、截断、搜索 API、手工导入均不能单独导致 `closed`。
