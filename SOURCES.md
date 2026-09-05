# Sources

PMHub 0.2.0 包含以下既有 Skill，并在套件内使用统一的 `pmhub-` 命名空间。

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
- PMHub name: `pmhub-ai-native-resume`
- Included: `SKILL.md`, `references/candidate-material-library.md`, `assets/template/`
- Adapted: Codex UI metadata, PMHub routing boundaries, cross-stage evidence reuse and public-template safety.
- Not included: the old repository landing page, README, `.git` history, or stale prebuilt `.skill` archive.

## PM Interview 1h Rescue

- Source: https://github.com/zebrazjx/pm-interview-1h-rescue
- Vendored commit: `bb2d8abd7c03f6d66dc5d0e6d0eb12197530f928`
- PMHub name: `pmhub-interview-1h-rescue`
- Included: `SKILL.md` and its four references.
- Adapted: Codex UI metadata, PMHub routing boundaries, evidence-truthfulness rules, company-fact safeguards and non-probabilistic readiness language.
- Not included: the old repository landing page, README, `.git` history, or stale prebuilt `.skill` archive.

## PMHub JD Reverse Engineer

- Created for PMHub on 2026-09-05.
- PMHub name: `pmhub-jd-reverse-engineer`.
- Included: the twelve-question JD decoding framework, AI-role lens, evidence plans, application rubric and scoped output templates.
