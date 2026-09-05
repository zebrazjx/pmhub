#!/usr/bin/env python3
"""Deterministic scoring for the AI PM role-fit exploration skill.

The script calculates only transparent ranges and ranking diagnostics. It does
not infer scores from prose and does not use personality labels or market size.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROLE_NAMES = {
    "application": "AI 用户／应用产品经理",
    "agent": "Agent／智能体产品经理",
    "model_strategy": "模型／算法策略产品经理",
    "solution_delivery": "AI 解决方案／交付产品经理",
    "growth_commercial": "AI 商业化／增长运营产品经理",
    "edge_hardware": "端侧／软硬件系统产品经理",
    "platform_infra": "AI 平台／基础设施产品经理",
    "data_evaluation": "数据评测产品经理",
    "safety_governance": "AI 安全／治理产品经理",
}

CURRENT_WEIGHTS = {
    "affinity": 0.35,
    "readiness": 0.45,
    "compatibility": 0.20,
}

DEVELOPMENT_WEIGHTS = {
    "affinity": 0.50,
    "readiness": 0.15,
    "compatibility": 0.20,
    "learning": 0.15,
}

ROLE_FIELDS = frozenset(
    {
        "affinity",
        "readiness",
        "compatibility",
        "learning",
        "coverage",
        "evidence_quality",
        "technical_evidence_count",
        "personal_project_count",
        "hard_conflicts",
        "evidence",
        "tensions",
        "unknowns",
    }
)

TOP_LEVEL_FIELDS = frozenset(
    {"candidate", "consistency", "followup_count", "roles", "mbti", "zodiac"}
)

REALITY_TESTS = {
    "application": "访谈 5 名目标用户，做可运行原型与 30 条评测集，记录任务成功、失败、延迟和成本。",
    "agent": "做一个含两个工具和状态依赖的 Agent，加入确认、幂等和回滚，并分析 30 条任务 Trace。",
    "model_strategy": "为一个任务建立分层测试集，对比至少两种模型方案，并报告质量、成本、延迟和回归。",
    "solution_delivery": "为一条真实企业流程设计窄 POC，写清基线、验收、部署、权限、运维、ROI 和拒绝定制边界。",
    "growth_commercial": "为一个 AI 产品定义激活事件、漏斗与三种定价方案，并测算 Token、人工、渠道成本和毛利。",
    "edge_hardware": "做一个最小端侧原型，比较两套端云方案，并在三类环境下记录精度、延迟、功耗和失败。",
    "platform_infra": "做一个服务两个小应用的模型网关切面，加入鉴权、配额、日志、路由、降级和接入文档。",
    "data_evaluation": "建立 40 条分层评测集与评分 Rubric，对比规则、LLM Judge 和双人人评并分析分歧。",
    "safety_governance": "为可调用工具的 Agent 做威胁模型和攻击集，加入最小权限、确认、沙箱与审计并比较前后结果。",
}

MBTI_RE = re.compile(
    r"(?<![A-Za-z])(?:ISTJ|ISFJ|INFJ|INTJ|ISTP|ISFP|INFP|INTP|ESTP|ESFP|ENFP|ENTP|ESTJ|ESFJ|ENFJ|ENTJ)(?![A-Za-z])",
    re.IGNORECASE,
)
CHINESE_ZODIAC_RE = re.compile(
    r"(?:白羊|金牛|双子|巨蟹|狮子|处女|天秤|天蝎|射手|摩羯|水瓶|双鱼)座"
)
ENGLISH_ZODIAC_NAMES = (
    r"aries|taurus|gemini|cancer|leo|virgo|libra|scorpio|sagittarius|"
    r"capricorn|aquarius|pisces"
)
ENGLISH_ZODIAC_CONTEXT_RE = re.compile(
    rf"\b(?:(?:i(?:'m| am)|as)\s+(?:an?\s+)?(?:{ENGLISH_ZODIAC_NAMES})|"
    rf"(?:{ENGLISH_ZODIAC_NAMES})\s+(?:sign|zodiac))\b",
    re.IGNORECASE,
)
ENGLISH_ZODIAC_TOKEN_RE = re.compile(
    r"\b(?:aries|taurus|gemini|leo|virgo|libra|scorpio|sagittarius|capricorn|aquarius|pisces)\b",
    re.IGNORECASE,
)
CHINESE_SHENGXIAO_RE = re.compile(
    r"(?:(?:生肖\s*(?:是|为|属)?|属)\s*[鼠牛虎兔龙蛇马羊猴鸡狗猪])"
)
PERSONALITY_MARKER_RE = re.compile(
    r"(?:\bmbti\b\s*(?:is|为|是|[:=：])?|(?:星座|生肖)\s*(?:是|为|[:=：])?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Interval:
    low: float
    high: float

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def rounded(value: float) -> int:
    return int(math.floor(value + 0.5))


def parse_interval(value: Any, field: str) -> Interval:
    if value is None:
        return Interval(0.0, 4.0)
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number or [low, high], not boolean")
    if isinstance(value, (int, float)):
        number = float(value)
        if not 0 <= number <= 4:
            raise ValueError(f"{field} must be between 0 and 4")
        return Interval(number, number)
    if isinstance(value, list) and len(value) == 2:
        low, high = value
        if isinstance(low, bool) or isinstance(high, bool):
            raise ValueError(f"{field} bounds must be numeric")
        if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
            raise ValueError(f"{field} bounds must be numeric")
        low, high = float(low), float(high)
        if not 0 <= low <= high <= 4:
            raise ValueError(f"{field} must satisfy 0 <= low <= high <= 4")
        return Interval(low, high)
    raise ValueError(f"{field} must be a number, [low, high], or null")


def parse_unit(value: Any, field: str, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    value = float(value)
    if not 0 <= value <= 1:
        raise ValueError(f"{field} must be between 0 and 1")
    return value


def weighted_score(values: dict[str, Interval], weights: dict[str, float]) -> Interval:
    low = sum(values[key].low * weight for key, weight in weights.items()) * 25
    high = sum(values[key].high * weight for key, weight in weights.items()) * 25
    return Interval(low, high)


def interval_dict(interval: Interval) -> dict[str, float | int]:
    return {
        "low": rounded(interval.low),
        "high": rounded(interval.high),
        "mid": rounded(interval.mid),
    }


def normalize_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return [item.strip() for item in value if item.strip()]


def parse_count(value: Any, field: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer between 0 and {maximum}")
    if not 0 <= value <= maximum:
        raise ValueError(f"{field} must be between 0 and {maximum}")
    return value


def parse_optional_count(raw: dict[str, Any], field: str, maximum: int) -> int | None:
    if field not in raw or raw[field] is None:
        return None
    return parse_count(raw[field], field, maximum)


def strip_personality_labels(value: str) -> tuple[str, bool]:
    """Remove personality-label fragments while preserving behavioral remainder."""

    cleaned = value
    removed = False
    for pattern in (
        ENGLISH_ZODIAC_CONTEXT_RE,
        ENGLISH_ZODIAC_TOKEN_RE,
        CHINESE_ZODIAC_RE,
        CHINESE_SHENGXIAO_RE,
        MBTI_RE,
        PERSONALITY_MARKER_RE,
    ):
        cleaned, count = pattern.subn("", cleaned)
        removed = removed or count > 0

    if not removed:
        return value.strip(), False

    # Label removal can strand introductions and conjunctions. Removing those
    # fragments prevents the label alone from becoming a non-empty "evidence"
    # item, while a real action/result clause remains available to the scorer.
    cleaned = re.sub(
        r"(?i)\b(?:i(?:'m| am)|as)\s+(?:an?\s*)?(?=[,.;:，；、]|and\b|$)",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(?:我是|作为)\s*(?=[,.;:，；、]|并且|而且|所以|因此|$)", "", cleaned)
    cleaned = cleaned.strip(" \t\r\n,.;:!?，。；：！？、-/")
    cleaned = re.sub(
        r"(?i)^(?:(?:and|so|therefore|because)\b[\s,.;:，；、]*)+", "", cleaned
    )
    cleaned = re.sub(r"^(?:(?:并且|而且|所以|因此|因为)[\s,.;:，；、]*)+", "", cleaned)
    cleaned = cleaned.strip(" \t\r\n,.;:!?，。；：！？、-/")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned, True


def evidence_gate(
    technical_evidence_count: int | None, personal_project_count: int | None
) -> dict[str, Any]:
    missing: list[str] = []
    failed: list[str] = []
    if technical_evidence_count is None:
        missing.append("technical_evidence_count")
    elif technical_evidence_count < 3:
        failed.append("技术关键词证据少于 3/5")
    if personal_project_count is None:
        missing.append("personal_project_count")
    elif personal_project_count < 2:
        failed.append("个人项目证据少于 2/4")
    if failed:
        status = "not_met"
    elif missing:
        status = "unknown"
    else:
        status = "met"
    return {
        "status": status,
        "technical_evidence_count": technical_evidence_count,
        "personal_project_count": personal_project_count,
        "failed_reasons": failed,
        "missing_fields": missing,
    }


def entry_state(readiness: Interval, gate: dict[str, Any]) -> str:
    if gate["status"] == "not_met":
        return "硬证据不足，先做现实检验"
    if readiness.low == 0 and readiness.high == 4:
        return "准备度未知"
    if readiness.high < 2:
        return "硬证据不足，先做现实检验"
    if readiness.low == 0:
        return "准备度仍不确定，需补行为证据"
    if readiness.low >= 3:
        if gate["status"] == "met":
            return "已有直接投递证据"
        return "准备度较高，原卡硬证据门槛待核验"
    return "具备部分迁移基础，仍需补证据"


def intervals_overlap(first: Interval, second: Interval) -> bool:
    return max(first.low, second.low) <= min(first.high, second.high)


def score_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON must be an object")
    unknown_top_level_fields = sorted(set(payload) - TOP_LEVEL_FIELDS)
    if unknown_top_level_fields:
        raise ValueError(
            "top-level JSON has unknown fields: "
            + ", ".join(unknown_top_level_fields)
        )
    roles_input = payload.get("roles", {})
    if not isinstance(roles_input, dict):
        raise ValueError("roles must be an object")
    unknown_role_ids = sorted(set(roles_input) - set(ROLE_NAMES))
    if unknown_role_ids:
        raise ValueError(f"unknown role ids: {', '.join(unknown_role_ids)}")

    consistency = parse_unit(payload.get("consistency"), "consistency", 0.5)
    followup_count = (
        parse_count(payload["followup_count"], "followup_count", 4)
        if "followup_count" in payload
        else 0
    )
    warnings: list[str] = []
    missing = [role_id for role_id in ROLE_NAMES if role_id not in roles_input]
    if missing:
        warnings.append(
            "Missing roles were treated as unknown intervals, not zero: " + ", ".join(missing)
        )

    scored_roles: dict[str, dict[str, Any]] = {}
    score_intervals: dict[str, dict[str, Interval]] = {}
    for role_id, role_name in ROLE_NAMES.items():
        raw = roles_input.get(role_id, {})
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError(f"roles.{role_id} must be an object")
        unknown_fields = sorted(set(raw) - ROLE_FIELDS)
        if unknown_fields:
            raise ValueError(
                f"roles.{role_id} has unknown fields: {', '.join(unknown_fields)}"
            )
        values = {
            field: parse_interval(raw.get(field), f"roles.{role_id}.{field}")
            for field in ("affinity", "readiness", "compatibility", "learning")
        }
        coverage = parse_unit(raw.get("coverage"), f"roles.{role_id}.coverage", 0.0)
        evidence_quality = parse_unit(
            raw.get("evidence_quality"), f"roles.{role_id}.evidence_quality", 0.0
        )
        technical_evidence_count = parse_optional_count(
            raw, "technical_evidence_count", 5
        )
        personal_project_count = parse_optional_count(raw, "personal_project_count", 4)
        gate = evidence_gate(technical_evidence_count, personal_project_count)
        conflicts = normalize_list(raw.get("hard_conflicts"), f"roles.{role_id}.hard_conflicts")
        all_evidence = normalize_list(raw.get("evidence"), f"roles.{role_id}.evidence")
        evidence: list[str] = []
        ignored_personality_evidence: list[str] = []
        for item in all_evidence:
            cleaned_item, removed_label = strip_personality_labels(item)
            if removed_label:
                ignored_personality_evidence.append(item)
            if cleaned_item:
                evidence.append(cleaned_item)
        declared_evidence_quality = evidence_quality
        if not evidence:
            evidence_quality = 0.0
        if ignored_personality_evidence:
            warnings.append(
                f"roles.{role_id} 的人格标签片段已移除，不参与分数或置信度"
            )
        if declared_evidence_quality > 0 and not evidence:
            warnings.append(
                f"roles.{role_id}.evidence_quality 因缺少可用行为证据按 0 计入置信度"
            )
        tensions = normalize_list(raw.get("tensions"), f"roles.{role_id}.tensions")
        unknowns = normalize_list(raw.get("unknowns"), f"roles.{role_id}.unknowns")
        compatibility_is_zero = (
            values["compatibility"].low == 0 and values["compatibility"].high == 0
        )
        if conflicts and not compatibility_is_zero:
            warnings.append(
                f"roles.{role_id} 有 hard_conflicts，但 compatibility 不是 0；请核对编码"
            )
        if compatibility_is_zero and not conflicts:
            warnings.append(
                f"roles.{role_id}.compatibility 为 0，但未填写 hard_conflicts；请补充条件冲突"
            )
        current = weighted_score(values, CURRENT_WEIGHTS)
        development = weighted_score(values, DEVELOPMENT_WEIGHTS)
        score_intervals[role_id] = {
            "current": current,
            "development": development,
            "readiness": values["readiness"],
        }
        scored_roles[role_id] = {
            "id": role_id,
            "name": role_name,
            "raw": {key: interval_dict(value) for key, value in values.items()},
            "current": interval_dict(current),
            "development": interval_dict(development),
            "entry_state": entry_state(values["readiness"], gate),
            "hard_evidence_gate": gate,
            "coverage": coverage,
            "evidence_quality": evidence_quality,
            "declared_evidence_quality": declared_evidence_quality,
            "hard_conflicts": conflicts,
            "evidence": evidence,
            "ignored_personality_evidence": ignored_personality_evidence,
            "tensions": tensions,
            "unknowns": unknowns,
        }

    def ranking(score_key: str) -> list[dict[str, Any]]:
        return sorted(
            scored_roles.values(),
            key=lambda role: (
                -score_intervals[role["id"]][score_key].mid,
                -score_intervals[role["id"]][score_key].low,
                role["name"],
            ),
        )

    current_ranking = ranking("current")
    development_ranking = ranking("development")

    def overlap_components(
        items: list[dict[str, Any]], score_key: str
    ) -> list[list[dict[str, Any]]]:
        """Return ranking-order components connected by inclusive interval overlap."""

        remaining = {role["id"] for role in items}
        groups: list[list[dict[str, Any]]] = []
        for role in items:
            if role["id"] not in remaining:
                continue
            component_ids = {role["id"]}
            changed = True
            while changed:
                changed = False
                for candidate in items:
                    candidate_id = candidate["id"]
                    if candidate_id not in remaining or candidate_id in component_ids:
                        continue
                    candidate_score = score_intervals[candidate_id][score_key]
                    if any(
                        intervals_overlap(
                            candidate_score, score_intervals[member_id][score_key]
                        )
                        for member_id in component_ids
                    ):
                        component_ids.add(candidate_id)
                        changed = True
            group = [item for item in items if item["id"] in component_ids]
            groups.append(group)
            remaining -= component_ids
        return groups

    def ranking_diagnostics(items: list[dict[str, Any]], score_key: str) -> dict[str, Any]:
        top = items[:3]
        first, second = items[0], items[1]
        first_score = score_intervals[first["id"]][score_key]
        second_score = score_intervals[second["id"]][score_key]
        margin = max(0.0, first_score.mid - second_score.mid)
        top2_overlaps = intervals_overlap(first_score, second_score)
        overlap = max(
            0,
            min(first_score.high, second_score.high)
            - max(first_score.low, second_score.low),
        )
        rank_group_members = overlap_components(items, score_key)
        tie_members = rank_group_members[0]
        tie_group = [role["id"] for role in tie_members] if len(tie_members) > 1 else []
        leader_overlaps = bool(tie_group)
        base_separation = clamp(margin / 12, 0, 1)
        overlap_penalty = clamp(overlap / 20, 0, 1)
        separation = base_separation * (1 - overlap_penalty)
        coverage = sum(role["coverage"] for role in top) / len(top)
        evidence_quality = sum(role["evidence_quality"] for role in top) / len(top)
        confidence_raw = (
            0.30 * coverage
            + 0.30 * evidence_quality
            + 0.20 * consistency
            + 0.20 * separation
        )

        reasons: list[str] = []
        if margin < 8:
            reasons.append(f"Top 2 中点仅相差 {margin:.3g} 分")
        if top2_overlaps:
            if overlap > 0:
                reasons.append(f"Top 2 区间重叠 {overlap:.3g} 分")
            else:
                reasons.append("Top 2 区间在边界相接")
        elif leader_overlaps:
            other_ties = "、".join(role["name"] for role in tie_members[1:])
            reasons.append(f"第一名所在的区间连通候选组还包含：{other_ties}")

        diagnostic_roles = items[:2] + [role for role in tie_members[1:] if role not in items[:2]]
        for role in diagnostic_roles:
            if role is first:
                label = "第一名"
            elif role is second:
                label = "第二名"
            else:
                label = f"并列候选「{role['name']}」"
            if role["evidence_quality"] <= 0.5 or not role["evidence"]:
                reasons.append(f"{label}只有自评或缺少行为证据")
            elif role is first and role["evidence_quality"] < 1.0:
                reasons.append("第一名缺少完整行为证据")
            if role["hard_conflicts"]:
                reasons.append(f"{label}存在明确条件冲突")
            if role["tensions"]:
                reasons.append(f"{label}存在待核对的反面证据或判断张力")
            if role["unknowns"]:
                reasons.append(f"{label}仍有关键未知")
            if score_key == "current":
                readiness = score_intervals[role["id"]]["readiness"]
                gate_status = role["hard_evidence_gate"]["status"]
                if readiness.high < 2:
                    reasons.append(f"{label}当前硬证据不足")
                if gate_status == "not_met":
                    reasons.append(f"{label}未达到原卡硬证据门槛")
                elif gate_status == "unknown" and readiness.low >= 3:
                    reasons.append(f"{label}原卡硬证据门槛尚未核验")

        if confidence_raw < 0.55 and not any("证据" in reason for reason in reasons):
            reasons.append("Top 3 的覆盖或行为证据不足")

        first_has_complete_evidence = math.isclose(
            first["evidence_quality"], 1.0, abs_tol=1e-9
        ) and bool(first["evidence"])
        high_gate_failures: list[str] = []
        if not first_has_complete_evidence:
            high_gate_failures.append("第一名缺少完整行为证据")
        if leader_overlaps:
            high_gate_failures.append("第一名与至少一个候选方向区间重叠或相接")
        if reasons:
            high_gate_failures.append("仍有必须核对的追问原因")
        high_eligible = (
            confidence_raw >= 0.75
            and first_has_complete_evidence
            and not leader_overlaps
            and not reasons
        )
        if high_eligible:
            confidence_label = "高"
        elif confidence_raw >= 0.55:
            confidence_label = "中"
        else:
            confidence_label = "低"
        confidence_downgrade_reasons = (
            high_gate_failures
            if confidence_raw >= 0.75 and confidence_label != "高"
            else []
        )
        unresolved = bool(reasons)
        followup_exhausted = unresolved and followup_count >= 4
        reality_test_ids = (tie_group or [first["id"], second["id"]])[:2]
        reality_tests = (
            [
                {
                    "role_id": role_id,
                    "name": ROLE_NAMES[role_id],
                    "task": REALITY_TESTS[role_id],
                }
                for role_id in reality_test_ids
            ]
            if followup_exhausted
            else []
        )

        return {
            "confidence": round(confidence_raw, 3),
            "confidence_raw": round(confidence_raw, 3),
            "stability_index": round(confidence_raw, 3),
            "confidence_capped": False,
            "confidence_label": confidence_label,
            "confidence_downgrade_reasons": confidence_downgrade_reasons,
            "coverage": round(coverage, 3),
            "evidence_quality": round(evidence_quality, 3),
            "consistency": round(consistency, 3),
            "separation": round(separation, 3),
            "top2_margin": round(margin, 3),
            "top2_overlap": round(overlap, 3),
            "top2_overlaps": top2_overlaps,
            "leader_overlaps": leader_overlaps,
            "tie_group": tie_group,
            "rank_groups": [
                [role["id"] for role in group] for group in rank_group_members
            ],
            "tie_status": (
                "final" if tie_group and followup_exhausted else "provisional" if tie_group else "none"
            ),
            "unresolved": unresolved,
            "followup_count": followup_count,
            "followup_limit": 4,
            "needs_followup": unresolved and followup_count < 4,
            "followup_exhausted": followup_exhausted,
            "followup_reasons": reasons,
            "reality_tests": reality_tests,
            "top2": [first["id"], second["id"]],
        }

    return {
        "candidate": str(payload.get("candidate") or "未命名用户"),
        "method_version": "1.0.0",
        "scale_note": "Scores compare directions for one user; they are not hiring probabilities.",
        "ignored_fields": [key for key in ("mbti", "zodiac") if key in payload],
        "followup_count": followup_count,
        "warnings": warnings,
        "roles": scored_roles,
        "current_ranking": [role["id"] for role in current_ranking],
        "development_ranking": [role["id"] for role in development_ranking],
        "current_diagnostics": ranking_diagnostics(current_ranking, "current"),
        "development_diagnostics": ranking_diagnostics(development_ranking, "development"),
    }


def fmt_range(score: dict[str, int]) -> str:
    return str(score["low"]) if score["low"] == score["high"] else f"{score['low']}—{score['high']}"


def render_markdown(result: dict[str, Any]) -> str:
    roles = result["roles"]
    lines = [
        f"# {result['candidate']}｜AI 产品经理方向评分",
        "",
        "> 分数只用于本人九类方向的相对比较，不是录用概率。",
        "",
    ]
    for title, ranking_key, score_key, diagnostics_key in (
        ("当前可切入", "current_ranking", "current", "current_diagnostics"),
        ("值得发展", "development_ranking", "development", "development_diagnostics"),
    ):
        diagnostics = result[diagnostics_key]
        confidence_text = (
            f"置信度：**{diagnostics['confidence_label']}**"
            f"（稳定性指数 {diagnostics['stability_index']:.3f}"
        )
        if diagnostics["confidence_downgrade_reasons"]:
            confidence_text += (
                "；因门槛降级："
                + "、".join(diagnostics["confidence_downgrade_reasons"])
            )
        confidence_text += "）"
        lines.extend(
            [
                f"## {title}",
                "",
                confidence_text,
                "",
                "| 排名 | 方向 | 分数区间 | 准备／条件状态 |",
                "|---:|---|---:|---|",
            ]
        )
        tie_group = diagnostics["tie_group"]
        ordinal = 1
        for group in diagnostics["rank_groups"]:
            rank_label = str(ordinal) if len(group) == 1 else f"候选组 {ordinal}（并列）"
            for role_id in group:
                role = roles[role_id]
                conflict = "；条件冲突：" + "；".join(role["hard_conflicts"]) if role["hard_conflicts"] else ""
                status = role["entry_state"] + conflict
                lines.append(
                    f"| {rank_label} | {role['name']} | {fmt_range(role[score_key])} | {status} |"
                )
            ordinal += len(group)
        lines.append("")
        if tie_group:
            qualifier = "最终" if diagnostics["tie_status"] == "final" else "暂定"
            lines.append(
                f"{qualifier}并列候选："
                + "、".join(roles[role_id]["name"] for role_id in tie_group)
                + "。"
            )
            lines.append("")
        if diagnostics["needs_followup"]:
            lines.append(
                f"建议追问（已用 {diagnostics['followup_count']}/{diagnostics['followup_limit']} 题）："
                + "；".join(diagnostics["followup_reasons"])
                + "。"
            )
            lines.append("")
        elif diagnostics["followup_exhausted"]:
            lines.append(
                "已达到 4 道判别题上限，停止追问并保留未决结论。未决原因："
                + "；".join(diagnostics["followup_reasons"])
                + "。"
            )
            lines.append("")
            lines.append("现实检验：")
            lines.append("")
            for test in diagnostics["reality_tests"]:
                lines.append(f"- **{test['name']}**：{test['task']}")
            lines.append("")

    lines.extend(
        [
            "## 四项原始判断",
            "",
            "| 方向 | A 长期适配 | R 当前准备 | C 情境兼容 | L 学习可行 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for role_id in result["current_ranking"]:
        role = roles[role_id]
        raw = role["raw"]
        lines.append(
            f"| {role['name']} | {fmt_range(raw['affinity'])} | {fmt_range(raw['readiness'])} | "
            f"{fmt_range(raw['compatibility'])} | {fmt_range(raw['learning'])} |"
        )
    if result["ignored_fields"]:
        lines.extend(
            [
                "",
                "已忽略的非评分字段：" + "、".join(result["ignored_fields"]) + "。",
            ]
        )
    if result["warnings"]:
        lines.extend(["", "警告：" + "；".join(result["warnings"]) + "。"])
    return "\n".join(lines) + "\n"


def sample_payload() -> dict[str, Any]:
    roles = {
        role_id: {
            "affinity": [1, 3],
            "readiness": [0, 2],
            "compatibility": [1, 3],
            "learning": [1, 3],
            "coverage": 0.25,
            "evidence_quality": 0.5,
            "technical_evidence_count": None,
            "personal_project_count": None,
            "hard_conflicts": [],
            "evidence": ["仅有任务兴趣自评，尚无行为证据"],
            "tensions": [],
            "unknowns": ["示例：待补关键证据"],
        }
        for role_id in ROLE_NAMES
    }
    roles["application"].update(
        {
            "affinity": [3, 4],
            "readiness": [2, 3],
            "compatibility": 4,
            "learning": [3, 4],
            "coverage": 0.8,
            "evidence_quality": 0.75,
            "technical_evidence_count": 3,
            "personal_project_count": 2,
            "evidence": ["访谈 6 名用户并根据失败记录迭代原型"],
            "unknowns": [],
        }
    )
    return {
        "candidate": "示例用户",
        "consistency": 0.75,
        "followup_count": 0,
        "roles": roles,
    }


def self_test() -> None:
    def test_role(
        affinity: Any = 0,
        readiness: Any = 0,
        compatibility: Any = 1,
        learning: Any = 0,
        *,
        evidence_quality: float = 1.0,
        evidence: list[str] | None = None,
        hard_conflicts: list[str] | None = None,
        tensions: list[str] | None = None,
        unknowns: list[str] | None = None,
        technical_evidence_count: int | None = 5,
        personal_project_count: int | None = 4,
    ) -> dict[str, Any]:
        role = {
            "affinity": affinity,
            "readiness": readiness,
            "compatibility": compatibility,
            "learning": learning,
            "coverage": 1.0,
            "evidence_quality": evidence_quality,
            "hard_conflicts": hard_conflicts or [],
            "evidence": ["完整行为证据"] if evidence is None else evidence,
            "tensions": tensions or [],
            "unknowns": unknowns or [],
        }
        if technical_evidence_count is not None:
            role["technical_evidence_count"] = technical_evidence_count
        if personal_project_count is not None:
            role["personal_project_count"] = personal_project_count
        return role

    def role_set() -> dict[str, dict[str, Any]]:
        return {role_id: test_role() for role_id in ROLE_NAMES}

    sample = sample_payload()
    first = score_payload(sample)
    assert first["current_ranking"][0] == "application"
    assert first["development_ranking"][0] == "application"
    assert first["current_diagnostics"]["rank_groups"][0] == ["application"]
    assert len(first["current_diagnostics"]["rank_groups"][1]) == len(ROLE_NAMES) - 1
    assert "候选组 2（并列）" in render_markdown(first)

    unknown = score_payload({"candidate": "未知", "roles": {}})
    for role in unknown["roles"].values():
        assert role["current"] == {"low": 0, "high": 100, "mid": 50}
        assert role["development"] == {"low": 0, "high": 100, "mid": 50}
    assert len(unknown["current_diagnostics"]["tie_group"]) == len(ROLE_NAMES)
    assert len(unknown["current_diagnostics"]["rank_groups"]) == 1
    assert "并列候选" in render_markdown(unknown)

    with_labels = json.loads(json.dumps(sample))
    with_labels["mbti"] = "INFP"
    with_labels["zodiac"] = "天蝎座"
    labeled = score_payload(with_labels)
    assert first["current_ranking"] == labeled["current_ranking"]
    assert first["development_ranking"] == labeled["development_ranking"]
    assert first["roles"] == labeled["roles"]
    assert first["current_diagnostics"] == labeled["current_diagnostics"]
    assert first["development_diagnostics"] == labeled["development_diagnostics"]

    # Inclusive endpoint contact is overlap and cannot produce High confidence.
    touch_roles = role_set()
    touch_roles["application"] = test_role([0, 8 / 7], 4, 3)
    touch_roles["agent"] = test_role([0, 8 / 7], 4, 1)
    touching = score_payload({"roles": touch_roles, "consistency": 1})
    touch_diagnostics = touching["current_diagnostics"]
    assert touch_diagnostics["top2_overlaps"] is True
    assert touch_diagnostics["top2_overlap"] == 0
    assert touch_diagnostics["confidence_label"] != "高"
    assert touch_diagnostics["needs_followup"] is True
    assert touch_diagnostics["tie_group"] == ["application", "agent"]

    # A lower-midpoint wide interval touching the leader is also an unresolved tie.
    wide_tie_roles = role_set()
    wide_tie_roles["application"] = test_role(
        [3.2, 3.6], [3.2, 3.6], [3.2, 3.6], [3.2, 3.6]
    )
    wide_tie_roles["agent"] = test_role(
        [2.8, 3.0], [2.8, 3.0], [2.8, 3.0], [2.8, 3.0]
    )
    wide_tie_roles["model_strategy"] = test_role(
        [1.6, 3.2], [1.6, 3.2], [1.6, 3.2], [1.6, 3.2]
    )
    wide_tie = score_payload(
        {"roles": wide_tie_roles, "consistency": 1, "followup_count": 4}
    )["current_diagnostics"]
    assert wide_tie["top2_overlaps"] is False
    assert wide_tie["leader_overlaps"] is True
    assert wide_tie["tie_group"] == ["application", "agent", "model_strategy"]
    assert wide_tie["confidence_label"] == "中"
    assert wide_tie["unresolved"] is True
    assert wide_tie["needs_followup"] is False
    assert wide_tie["followup_exhausted"] is True
    assert wide_tie["tie_status"] == "final"
    assert len(wide_tie["reality_tests"]) == 2

    # Only evidence quality 1.0 can satisfy the complete-evidence High gate.
    quality_roles = role_set()
    quality_roles["application"] = test_role(
        4, 4, 4, 4, evidence_quality=0.75, evidence=["有动作但缺结果"]
    )
    quality_roles["agent"] = test_role(2, 2, 2, 2)
    incomplete = score_payload({"roles": quality_roles, "consistency": 1})
    assert incomplete["current_diagnostics"]["confidence_label"] == "中"
    assert incomplete["current_diagnostics"]["confidence"] > 0.75
    assert (
        incomplete["current_diagnostics"]["confidence"]
        == incomplete["current_diagnostics"]["confidence_raw"]
        == incomplete["current_diagnostics"]["stability_index"]
    )
    assert "第一名缺少完整行为证据" in incomplete["current_diagnostics"][
        "confidence_downgrade_reasons"
    ]
    assert "第一名缺少完整行为证据" in incomplete["current_diagnostics"]["followup_reasons"]
    incomplete_markdown = render_markdown(incomplete)
    assert "稳定性指数" in incomplete_markdown
    assert "因门槛降级：第一名缺少完整行为证据" in incomplete_markdown

    # Personality labels are removed from evidence and cannot lift confidence.
    personality_roles = role_set()
    personality_roles["application"] = test_role(
        4, 4, 4, 4, evidence_quality=1, evidence=["INTJ，天蝎座"]
    )
    no_evidence_roles = json.loads(json.dumps(personality_roles))
    no_evidence_roles["application"]["evidence"] = []
    personality = score_payload(
        {"roles": personality_roles, "consistency": 1, "mbti": "INTJ", "zodiac": "天蝎座"}
    )
    no_evidence = score_payload({"roles": no_evidence_roles, "consistency": 1})
    assert personality["roles"]["application"]["evidence_quality"] == 0
    assert personality["current_diagnostics"]["confidence"] == no_evidence["current_diagnostics"]["confidence"]

    # Sentence-wrapped labels are stripped, but a mixed behavioral clause survives.
    assert strip_personality_labels("I'm a Scorpio and very detail-oriented") == (
        "very detail-oriented",
        True,
    )
    assert strip_personality_labels("As a Leo, I prefer leadership") == (
        "I prefer leadership",
        True,
    )
    assert strip_personality_labels("属虎，所以敢冒险") == ("敢冒险", True)
    assert strip_personality_labels("我是 INTJ；我主导了三个项目并复盘结果") == (
        "我主导了三个项目并复盘结果",
        True,
    )
    mixed_roles = role_set()
    mixed_roles["application"] = test_role(
        4,
        4,
        4,
        4,
        evidence=["我是 INTJ；我主导了三个项目并复盘结果"],
    )
    stripped_roles = role_set()
    stripped_roles["application"] = test_role(
        4,
        4,
        4,
        4,
        evidence=["我主导了三个项目并复盘结果"],
    )
    mixed = score_payload({"roles": mixed_roles, "consistency": 1})
    stripped = score_payload({"roles": stripped_roles, "consistency": 1})
    assert mixed["roles"]["application"]["evidence"] == stripped["roles"][
        "application"
    ]["evidence"]
    assert mixed["current_diagnostics"] == stripped["current_diagnostics"]

    # Source-card evidence gates override a high readiness interval in entry-state text.
    gate_roles = role_set()
    gate_roles["application"] = test_role(
        4, 4, 4, technical_evidence_count=2, personal_project_count=4
    )
    gate_failed = score_payload({"roles": gate_roles})["roles"]["application"]
    assert gate_failed["hard_evidence_gate"]["status"] == "not_met"
    assert gate_failed["entry_state"] == "硬证据不足，先做现实检验"
    gate_roles["application"] = test_role(
        4, 4, 4, technical_evidence_count=3, personal_project_count=2
    )
    gate_met = score_payload({"roles": gate_roles})["roles"]["application"]
    assert gate_met["hard_evidence_gate"]["status"] == "met"
    assert gate_met["entry_state"] == "已有直接投递证据"
    gate_roles["application"] = test_role(
        4,
        4,
        4,
        technical_evidence_count=None,
        personal_project_count=None,
    )
    gate_unknown = score_payload({"roles": gate_roles})["roles"]["application"]
    assert gate_unknown["entry_state"] == "准备度较高，原卡硬证据门槛待核验"

    # Either Top-2 role can trigger checks for conflicts, self-report, or tensions.
    top2_roles = role_set()
    top2_roles["application"] = test_role(4, 4, 4, 4)
    top2_roles["agent"] = test_role(
        4,
        4,
        0,
        4,
        evidence_quality=0.5,
        evidence=["只有自评"],
        hard_conflicts=["不可协商的生产值班冲突"],
        tensions=["偏好题与反面经历矛盾"],
    )
    top2 = score_payload({"roles": top2_roles, "consistency": 1})["current_diagnostics"]
    assert top2["confidence_label"] != "高"
    assert any("第二名只有自评" in reason for reason in top2["followup_reasons"])
    assert any("第二名存在明确条件冲突" in reason for reason in top2["followup_reasons"])
    assert any("第二名存在待核对的反面证据" in reason for reason in top2["followup_reasons"])

    # Four questions stop the loop while retaining unresolved state and work samples.
    before_limit = score_payload(
        {"roles": touch_roles, "consistency": 1, "followup_count": 3}
    )["current_diagnostics"]
    at_limit = score_payload(
        {"roles": touch_roles, "consistency": 1, "followup_count": 4}
    )["current_diagnostics"]
    assert before_limit["needs_followup"] is True
    assert before_limit["followup_exhausted"] is False
    assert at_limit["needs_followup"] is False
    assert at_limit["unresolved"] is True
    assert at_limit["followup_exhausted"] is True
    assert at_limit["tie_status"] == "final"
    assert len(at_limit["reality_tests"]) == 2
    at_limit_result = score_payload(
        {"roles": touch_roles, "consistency": 1, "followup_count": 4}
    )
    at_limit_markdown = render_markdown(at_limit_result)
    assert "停止追问" in at_limit_markdown
    assert "现实检验" in at_limit_markdown

    stable_roles = role_set()
    stable_roles["application"] = test_role(4, 4, 4, 4)
    stable_roles["agent"] = test_role(2, 2, 2, 2)
    stable = score_payload(
        {"roles": stable_roles, "consistency": 1, "followup_count": 4}
    )["current_diagnostics"]
    assert stable["unresolved"] is False
    assert stable["followup_exhausted"] is False
    assert stable["tie_group"] == []

    # Ranking and the <8 trigger use exact scores, not rounded display values.
    exact_roles = role_set()
    exact_roles["model_strategy"] = test_role([1, 2], [2, 3], 4)
    exact_roles["application"] = test_role([2, 3], 3, [0, 2])
    exact = score_payload({"roles": exact_roles, "consistency": 1})
    assert exact["roles"]["model_strategy"]["current"]["mid"] == 61
    assert exact["roles"]["application"]["current"]["mid"] == 61
    assert exact["current_ranking"][0] == "model_strategy"

    margin_roles = role_set()
    margin_roles["application"] = test_role(0, 2, 3)
    margin_roles["agent"] = test_role(1, 1, 2)
    margin = score_payload({"roles": margin_roles, "consistency": 1})[
        "current_diagnostics"
    ]
    assert margin["top2_margin"] == 7.5
    assert any("仅相差 7.5" in reason for reason in margin["followup_reasons"])

    # Conflict/C=0 mismatches and schema typos must not pass silently.
    conflict_roles = role_set()
    conflict_roles["application"] = test_role(
        4, 4, 4, hard_conflicts=["不接受高频用户访谈"]
    )
    conflicted = score_payload({"roles": conflict_roles})
    assert any("有 hard_conflicts，但 compatibility 不是 0" in warning for warning in conflicted["warnings"])
    conflict_roles["application"]["compatibility"] = 0
    consistent_conflict = score_payload({"roles": conflict_roles})
    assert not any("roles.application 有 hard_conflicts" in warning for warning in consistent_conflict["warnings"])

    typo_roles = role_set()
    typo_roles["application"]["readness"] = typo_roles["application"].pop("readiness")
    try:
        score_payload({"roles": typo_roles})
    except ValueError as exc:
        assert "unknown fields: readness" in str(exc)
    else:
        raise AssertionError("unknown role field was accepted")

    try:
        score_payload({"roles": role_set(), "followup_counts": 1})
    except ValueError as exc:
        assert "top-level JSON has unknown fields: followup_counts" in str(exc)
    else:
        raise AssertionError("unknown top-level field was accepted")

    for invalid_count in (True, -1, 5, 1.5, "1", None):
        try:
            score_payload({"roles": {}, "followup_count": invalid_count})
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid followup_count was accepted: {invalid_count!r}")

    for diagnostics in (
        touching["current_diagnostics"],
        incomplete["current_diagnostics"],
        stable,
    ):
        if diagnostics["confidence_label"] == "高":
            assert diagnostics["confidence"] >= 0.75
        elif diagnostics["confidence_label"] == "中":
            assert diagnostics["confidence"] >= 0.55
        else:
            assert diagnostics["confidence"] < 0.55
        assert diagnostics["confidence"] == diagnostics["stability_index"]
        assert diagnostics["confidence_capped"] is False

    print("score_assessment.py self-test: PASS")


def load_payload(path: str) -> dict[str, Any]:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="-", help="JSON file path, or - for stdin")
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--sample", action="store_true", help="print a complete sample payload")
    parser.add_argument("--self-test", action="store_true", help="run deterministic invariants")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return
    if args.sample:
        print(json.dumps(sample_payload(), ensure_ascii=False, indent=2))
        return

    try:
        result = score_payload(load_payload(args.input))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(result), end="")


if __name__ == "__main__":
    main()
