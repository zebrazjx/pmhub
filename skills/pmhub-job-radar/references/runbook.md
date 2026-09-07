# 岗位雷达运行手册

`scripts/job_radar.py` 仅使用 Python 3 标准库。命令默认不访问网络：必须显式选择 `--dry-run`、`--fixtures-dir` 或 `--live` 其中一种。

## 1. 最小配置

```json
{
  "schema_version": "1",
  "defaults": {
    "fresh_days": 7,
    "stale_days": 30,
    "close_after_misses": 2,
    "request_interval_seconds": 1.0,
    "timeout_seconds": 15,
    "max_response_bytes": 8388608
  },
  "filters": {
    "title_include": ["product manager", "产品经理"],
    "title_exclude": ["sales"],
    "keywords_any": ["AI", "LLM", "Agent"],
    "location_include": ["上海", "北京", "remote"],
    "remote_only": false,
    "posted_within_days": 45,
    "allow_unknown_dates": true,
    "min_quality_score": 0
  },
  "sources": [
    {"id": "acme-greenhouse", "provider": "greenhouse", "company": "Acme", "board_token": "acme"},
    {"id": "acme-lever-eu", "provider": "lever", "company": "Acme EU", "site": "acme", "region": "eu", "max_results": 500},
    {"id": "acme-ashby", "provider": "ashby", "company": "Acme", "board": "Acme", "include_compensation": true},
    {"id": "acme-smartrecruiters", "provider": "smartrecruiters", "company": "Acme", "company_identifier": "acme", "max_results": 300}
  ]
}
```

`source.id` 在配置内必须唯一，并在后续运行中保持稳定；更换 ID 会被视为新来源。

## 2. Provider 配置

### `greenhouse`

必填：`id`, `provider`, `company`, `board_token`。

### `lever`

必填：`id`, `provider`, `company`, `site`。`region` 可为 `global` 或 `eu`，默认 `global`。`max_results` 默认 500，`max_pages` 默认 100；达到任一上限或分页重复／停滞时，该次标记为非完整快照。

### `ashby`

必填：`id`, `provider`, `company`, `board`。`include_compensation` 默认 `true`。`isListed=false` 的直链岗位不纳入广播型岗位雷达。

### `smartrecruiters`

必填：`id`, `provider`, `company`, `company_identifier`。Adapter 会分页取列表，再取公开详情。`max_results` 默认 300，`max_pages` 默认 100；达到任一上限、分页停滞或详情读取失败时不视为完整快照。

### `jsonld`

```json
{
  "id": "acme-careers-pages",
  "provider": "jsonld",
  "company": "Acme",
  "urls": ["https://careers.acme.example/jobs/pm-123"]
}
```

只允许公开 `http/https` URL，不访问私网、localhost 或受限招聘平台域名。实时模式检查 robots.txt，检查失败时关闭。

### `sitemap_jsonld`

```json
{
  "id": "acme-careers-sitemap",
  "provider": "sitemap_jsonld",
  "company": "Acme",
  "sitemap_url": "https://careers.acme.example/sitemap.xml",
  "include_regex": "/jobs?/",
  "max_urls": 200
}
```

Adapter 最多追踪一层 sitemap index，只读同站点 URL，再提取每页 `JobPosting` JSON-LD。达到 `max_urls` 或出现子 sitemap 失败时不视为完整快照。必须设置能排除搜索页、分类页和其他非职位 URL 的 `include_regex`。

### `google_cse`

```json
{
  "id": "official-site-discovery",
  "provider": "google_cse",
  "company": "",
  "query": "(AI OR LLM OR Agent) product manager jobs",
  "site_search": "careers.example.com",
  "api_key_env": "PMHUB_GOOGLE_CSE_KEY",
  "cx_env": "PMHUB_GOOGLE_CSE_CX",
  "max_results": 20
}
```

运行前在环境中设置密钥和 Search Engine ID。两者均不得写入 JSON，并会在计划和报告中脱敏。`max_results` 上限为 100。输出是发现线索，默认不算入完整快照，受限平台结果会被过滤。

Google 已关闭该 API 的新客户接入，现有客户需在 **2027-01-01** 前迁移。新配置不应依赖它；改用目标公司清单与官网／ATS／sitemap 发现，或用宿主已授权的搜索能力找到官方页后再核验。详见 [来源阶梯与合规边界](source-policy.md#3-搜索-api-与普通网页回退)。

### `manual_import`

```json
{
  "id": "authorized-export",
  "provider": "manual_import",
  "company": "",
  "path": "./authorized-jobs.csv",
  "format": "csv"
}
```

支持 `jsonl`、`json` 和 `csv`。路径必须相对于配置文件，解析后仍必须位于配置目录内；不接受绝对路径、越界符号链接、非普通文件或超过 `defaults.max_response_bytes` 的导入。推荐字段：`external_id,company,title,description_text,location,job_url,apply_url,posted_at,updated_at,expires_at,employment_type,department,team,workplace_type,source_url`。导入源不参与缺失关闭判定。

## 3. 预演

```bash
python3 scripts/job_radar.py collect --config /absolute/path/sources.json --dry-run
```

预演验证字段、Provider 参数、重复 ID、受限 URL 和密钥环境变量名，并显示经脱敏的请求计划。它不发网络请求、不读导入文件、不写状态库。

## 4. 离线 fixture 模式

```bash
python3 scripts/job_radar.py collect \
  --config tests/fixtures/sources.json \
  --fixtures-dir tests/fixtures \
  --output /tmp/pmhub-jobs.jsonl \
  --report /tmp/pmhub-run-report.json \
  --state /tmp/pmhub-job-radar.sqlite
```

fixture 目录用 `http_map.json` 将经脱敏的 URL 映射到本地 JSON/HTML/XML 文件。该模式绝不访问网络，适合 Adapter 测试和回归。

## 5. 实时采集

```bash
python3 scripts/job_radar.py collect \
  --config /absolute/path/sources.json \
  --live \
  --output /absolute/path/jobs.jsonl \
  --report /absolute/path/run-report.json \
  --state /absolute/path/job-radar.sqlite
```

实时模式使用固定 User-Agent，按域名限速，遵守 robots 中可解析的 `Crawl-delay` / `Request-rate`，对 `429` 和短暂 `5xx` 做有界重试。服务端要求的 `Retry-After` 或 robots 间隔超过本地最长等待时，脚本会停止该来源，不会提前重试。

每个网络目标在连接前解析，所有解析地址必须为公网 IP；TCP 连接固定到已验证 IP，HTTPS 证书和 SNI 仍校验原始主机名。每一跳重定向都重新执行 IP、受限域和 robots 检查。响应超过配置大小、重定向到不安全目标、robots 拒绝或 robots 不可用时，对该来源失败关闭，但继续处理其他来源。

某些公司网络、VPN、代理或隔离沙箱会把外部域名解析到 `198.18.0.0/15`、私网或假 IP；实时模式会按预期拒绝。应改用具有正常公网 DNS 的受控运行环境，不关闭 IP 验证。常规 CI 只跑离线 fixture；维护者可手动触发 `live-smoke.yml` 在干净公网 runner 上对公开 ATS 做少量只读冒烟验证。

## 6. 筛选语义

- `title_include`：任一子串命中即保留；空数组表示不限制。
- `title_exclude`：任一子串命中即排除。
- `keywords_any`：在职位名、部门、团队和 JD 中任一命中即保留。
- `location_include`：在任一 `locations[].raw/city/region/country` 命中即保留。
- `remote_only`：只保留 `workplace_type=remote` 或地点明示 remote 的岗位。
- `posted_within_days`：基于 `posted_at`，缺失时用 `updated_at`。`allow_unknown_dates=true` 时日期未知记录仍保留，但带 `date_unknown`。
- `min_quality_score`：仅是数据质量门槛，不是候选人匹配度。

## 7. 查看状态

```bash
python3 scripts/job_radar.py state --state /absolute/path/job-radar.sqlite --status open --limit 100
```

输出当前岗位的 JSONL。`--status` 可为 `open`、`closed`、`expired` 或 `all`。SQLite 中只保存标准化岗位、来源观测和运行状态，不应写入简历、联系方式或平台凭据。

## 8. 运行报告检查

运行结束后至少检查：

1. `sources[].success` 与 `complete_snapshot`；
2. `errors` 是否影响目标公司；
3. `counts.raw / deduped / matched_filters`；
4. `counts.new / changed / unchanged / closed / reopened`；
5. `warnings` 中的未知日期、搜索发现、分页截断和受限结果数量。

如果一个核心来源失败，可交付其他已成功结果，但必须明确写“本次是不完整快照”，不声称全量覆盖。
