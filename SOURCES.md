# Sources

PMHub 0.3.0 包含以下既有与新建 Skill，并在套件内使用统一的 `pmhub-` 命名空间。

本文件只记录来源、固定版本与改造边界，不另行授予使用权。PMHub 当前未声明开源许可证；授权边界见 [README.md](README.md)。外部参考项目仍适用各自的许可证或使用条款。

## PMHub Router

- Created for PMHub on 2026-09-05; expanded for the 0.3.0 suite on 2026-09-07.
- PMHub name: `pmhub`, component version `0.3.0`.
- Included: suite routing, stage gates, resumable state, truth-source boundaries, UI metadata and `references/handoff-contract.md`.
- Boundary: the router selects and connects components; it does not duplicate their domain workflows.

## AI PM Role Fit

- Source skill: `ai-pm-role-fit`
- Source snapshot: `2026-09-05`, version `1.0.0`
- PMHub name: `pmhub-ai-pm-role-fit`, component version `1.0.1`
- Included: `SKILL.md`, five reference files, deterministic scorer and source-coverage audit.
- Adapted: PMHub UI metadata, routing boundaries, cross-stage handoff and a portable scoring-command example.
- Verification note: the bundled Feishu knowledge files are dated snapshots; their original Feishu links may require account permission and are not runtime dependencies.

## AI Native Resume

- Source: https://github.com/zebrazjx/ai-native-resume
- Vendored commit: `e9585196964f28ac554b3e54085f9d5faf5a26d6`
- PMHub name: `pmhub-ai-native-resume`, component version `1.0.0`.
- Source license note: no open-source license file was present at the vendored commit; this source record does not grant third-party reuse rights.
- Included: `SKILL.md`, `references/candidate-material-library.md`, `assets/template/`
- Adapted: Codex UI metadata, PMHub routing boundaries, cross-stage evidence reuse and public-template safety.
- Not included: the old repository landing page, README, `.git` history, or stale prebuilt `.skill` archive.

## PM Interview 1h Rescue

- Source: https://github.com/zebrazjx/pm-interview-1h-rescue
- Vendored commit: `bb2d8abd7c03f6d66dc5d0e6d0eb12197530f928`
- PMHub name: `pmhub-interview-1h-rescue`, component version `1.0.0`.
- Source license note: no open-source license file was present at the vendored commit; this source record does not grant third-party reuse rights.
- Included: `SKILL.md` and its four references.
- Adapted: Codex UI metadata, PMHub routing boundaries, evidence-truthfulness rules, company-fact safeguards and non-probabilistic readiness language.
- Not included: the old repository landing page, README, `.git` history, or stale prebuilt `.skill` archive.

## PMHub JD Reverse Engineer

- Created for PMHub on 2026-09-05.
- PMHub name: `pmhub-jd-reverse-engineer`, component version `1.0.2`.
- Included: the twelve-question JD decoding framework, AI-role lens, evidence plans, application rubric and scoped output templates.

## AI Learning Coach

- Created for PMHub on 2026-09-07.
- PMHub name: `pmhub-ai-learning-coach`, component version `1.0.1`.
- Included: JD-to-capability mapping, a three-layer AI capability map, Feynman-style explain-and-repair loop, retrieval practice, adaptive spacing, implementation evaluation and evidence handoff templates.
- Research basis: Roediger & Karpicke (2006), Cepeda et al. (2006), and Dunlosky et al. (2013), linked from `references/learning-loop.md`.
- Adaptation note: “Feynman-style” describes a practical explain–find gaps–re-explain–apply loop; it is not presented as a standardized psychological assessment.

## Advanced PM Interview Coach

- Created for PMHub on 2026-09-07.
- PMHub name: `pmhub-pm-interview-coach`, component version `1.0.1`.
- Included: interview blueprints, interviewer perspectives, adaptive follow-ups, behavior-anchored scoring, case variants, session records and delayed retesting.
- Boundary: this is an interactive deliberate-practice component; `pmhub-interview-1h-rescue` remains the compressed 60／30／15-minute preparation component.

## Career Planner

- Created for PMHub on 2026-09-07.
- PMHub name: `pmhub-career-planner`, component version `1.0.0`.
- Included: career asset and constraint inventory, adjacent and fallback paths, scenario planning, reversible experiments, opportunity-cost cards, job-search pipeline diagnosis and quarterly review.
- Boundary: it does not make deterministic career, salary, admission or hiring predictions; current market, salary, visa and legal facts must be checked at runtime.

## PM Full-cycle Toolkit

- Created for PMHub on 2026-09-07.
- PMHub name: `pmhub-pm-toolkit`, component version `1.0.0`.
- Public Agent Skill comparisons: Anthropic `knowledge-work-plugins/product-management` (Apache-2.0), Mind the Product `skills` (MIT), `quitecommlt/product-manager-skill` (MIT), `warren-wupeng/pm-skills` (MIT), and other repositories listed in `references/sources-and-adaptations.md`.
- Product-method calibration: first-party materials from Atlassian, Productboard, Product Talk, Christensen Institute, Nielsen Norman Group, Google Research, Amplitude, Intercom, Scrum Guides and Basecamp.
- Adapted: coverage and progressive-disclosure patterns were used as design inputs. PMHub's Chinese instructions, evidence／unknown／decision ledgers, risk gates, routing and templates were independently written; no upstream Skill or template was vendored.
- Included: discovery, research, JTBD, problem framing, prioritization, outcome roadmaps, tiered PRDs, delivery, metrics, experiments, launches, growth, stakeholder decisions and retrospectives, with a shared traceability chain.

## Multi-source Job Radar

- Created for PMHub on 2026-09-07.
- PMHub name: `pmhub-job-radar`, component version `1.0.1`.
- Public structured providers: Greenhouse Job Board API, Lever Postings API, Ashby public Job Postings API and SmartRecruiters public Posting API.
- Company-site fallback: Schema.org／Google `JobPosting` JSON-LD on explicitly configured pages or a bounded same-host sitemap; generic pages are checked against RFC 9309 robots rules and fail closed when policy cannot be read.
- Search discovery: Google Programmable Search JSON API with reserved PMHub environment-variable names. Search snippets remain `discovery_only` until an original page is verified.
- Third-party boundary: BOSS, Lagou and LinkedIn agreements explicitly restrict unapproved automation; 51job, Zhaopin, Liepin, Indeed and Glassdoor are also denied by default because no general public collection authorization was verified. Authorized exports remain importable without pretending to be live official snapshots.
- Implementation: Python-standard-library adapters, a unified provenance-first Job schema, conservative URL／fingerprint deduplication, SQLite incremental state, successful-complete-snapshot closure rules, guarded networking and offline fixtures.
- Exact source links and the dated policy matrix live in `skills/pmhub-job-radar/references/source-policy.md`.
