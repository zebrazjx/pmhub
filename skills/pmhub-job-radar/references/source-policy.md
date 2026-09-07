# 来源阶梯与合规边界

> 文档快照：2026-09-07。外部接口、robots.txt 和平台协议可能变化；每次实时采集前重新核对。这份文档是工程决策边界，不是法律意见。

## 1. 可直接使用的官方公开职位源

| Provider | 公开读取方式 | 关键边界 | 本 Skill 的 Adapter |
|---|---|---|---|
| Greenhouse | `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true` | 官方文档明确说 Job Board 数据公开，GET 无需认证；投递 POST 需要认证，不属于本 Skill | `greenhouse` |
| Lever | `GET https://api.lever.co/v0/postings/{site}?mode=json` | 只返回 published 职位；全球与 EU 域名不同；本 Skill 只读 GET，不使用投递 POST | `lever` |
| Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/{board}` | 官方文档定义为当前已发布 Job Postings；`includeCompensation=true` 可返回公开薪酬 | `ashby` |
| SmartRecruiters | `GET https://api.smartrecruiters.com/v1/companies/{companyIdentifier}/postings` | 官方 Posting API 列出特定公司的 active public postings；列表后再读公开详情 | `smartrecruiters` |

一手文档：

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html)
- [Lever Postings API](https://github.com/lever/postings-api)
- [Ashby Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api)
- [SmartRecruiters Posting API 端点](https://developers.smartrecruiters.com/docs/endpoints)
- [SmartRecruiters Customer API 概览](https://developers.smartrecruiters.com/docs/customer-overview)

### Provider 识别

- `boards.greenhouse.io/{token}`、`job-boards.greenhouse.io/{token}` 通常可提取 Greenhouse `board_token`。
- `jobs.lever.co/{site}` 或 `jobs.eu.lever.co/{site}` 对应 Lever `site` 及 `region`。
- `jobs.ashbyhq.com/{board}` 末段对应 Ashby `board`。
- `careers.smartrecruiters.com/{companyIdentifier}` 末段对应 SmartRecruiters `company_identifier`。

识别出 ATS 不代表可以猜测任意端点。只用上述官方文档定义的公开 GET 端点。

## 2. 公司官网

优先读每个单独职位页中的 `application/ld+json` / `JobPosting`，因为它比针对某个 CSS 选择器的爬虫更稳定，也保留 `datePosted`、`validThrough`、`hiringOrganization`、`jobLocation` 等语义字段。

- Google 官方的 [`JobPosting` 结构化数据指南](https://developers.google.com/search/docs/appearance/structured-data/job-posting) 规定了岗位页常用字段，并强调 canonical URL、准确更新时间和及时移除过期职位。
- [RFC 9309 Robots Exclusion Protocol](https://www.rfc-editor.org/rfc/rfc9309.html) 规定爬虫如何解释 robots.txt。robots 是站点的自动访问请求，不是授权或版权许可；还要同时遵守平台协议与法律。

本 Skill 的 `jsonld` Adapter 只读配置中明确列出的职位 URL；`sitemap_jsonld` 只读公司官网 sitemap 中通过正则筛选后的有限 URL。两者均禁止访问私有网络地址、受限域名，并且 robots 读取失败时默认关闭。

## 3. 搜索 API 与普通网页回退

可使用有明确文档和凭据的搜索 API 发现官方职位页。API 结果只包含标题、URL 和摘要，所以必须标记 `discovery_only`，不能据此宣布岗位仍在招。

Google 官方已在 [Custom Search JSON API 概览](https://developers.google.com/custom-search/v1/overview) 说明：该 API 已关闭新客户，现有客户必须在 **2027-01-01** 前迁移。因此 `google_cse` 只是过渡 Adapter：

- 仅在用户已有可用的 Custom Search JSON API 资格时运行，不引导新用户为它开通计费项目；
- 新用户或迁移期优先以“目标公司清单 → 官网／官方 ATS → sitemap / JobPosting JSON-LD”回退；
- 宿主已有合规网页搜索能力时，可用它发现官方页，再交给官网／ATS Adapter 核验；不把宿主搜索写成本地 CLI 已支持的 Provider。

搜索 API 密钥只从预留的 `PMHUB_GOOGLE_CSE_KEY` 和 `PMHUB_GOOGLE_CSE_CX` 两个环境变量读取，不允许配置改为任意环境变量，不枚举环境，不写入配置、日志、报告或 provenance。API key 与 Search Engine ID (`cx`) 在请求计划、错误和报告中均脱敏。搜索结果指向受限招聘平台时，脚本默认丢弃该结果，不用搜索缓存规避原平台条款。

## 4. 第三方招聘平台的现实边界

### 明确限制自动化访问的例子

- [BOSS 直聘用户协议](https://www.zhipin.com/web/common/protocol/protocol-2019-09-30.html) 将未经许可的 spider、爬虫、拟人程序或规避技术措施获取数据列为禁止行为，也限制第三方工具接入平台。
- [拉勾网用户协议](https://www.lagou.com/privacy.html) 第三条禁止机器人／脚本自动访问，并禁止未经允许的爬虫、抓取、批量检索复制公开或非公开信息。
- [LinkedIn User Agreement](https://www.linkedin.com/legal/user-agreement) 第 8.2 节禁止使用 scripts、robots、crawlers 等抓取或复制服务数据，也禁止规避访问控制和使用未授权自动化方法。

对前程无忧、智联招聘、猎聘、Indeed、Glassdoor 等未在本快照中确认有通用公开岗位 API 和采集授权的平台，脚本采用保守的默认禁止直连。若未来获得官方 API／书面授权，应新增专用 Adapter 和授权记录，不要关闭通用禁止。

### 允许的替代路径

1. 使用平台官方 API、合作 Feed 或官方导出，严格按其授权范围处理。
2. 让用户主动提供少量单条 JD 或平台允许的导出，通过 `manual_import` 标准化；不把它伪装成官方快照。
3. 通过搜索 API 定位公司官网的同源职位，再以官网／官方 ATS 为准。

## 5. 新 Provider 上线门槛

新增 Adapter 前必须同时满足：

- 有官方 API／Feed 文档或官方明确的自动访问许可，记录 URL 和查看日期；
- 只实现最小必要的公开 GET，端点固定在 Adapter 内，不允许配置替换域名；
- 有最小间隔、超时、有界重试、`429`/`Retry-After` 处理和响应大小上限；
- 有不含真实个人数据的 fixture 及离线测试；
- 可以区分完整快照和部分结果，不会因为分页截断误报关闭；
- 输出统一 Schema、provenance、content fingerprint 和可观测错误；
- 没有投递、聊天、个人信息采集、隐藏职位或内部职位读取能力。
