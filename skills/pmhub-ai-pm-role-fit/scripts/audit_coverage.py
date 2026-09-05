#!/usr/bin/env python3
"""Audit the local knowledge snapshot and role catalog for structural coverage."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "references" / "source-self-check-cards.md"
PROFILES = ROOT / "references" / "role-profiles.md"
SKILL = ROOT / "SKILL.md"

ROLE_SOURCES = (
    ("01", "AI 用户／应用产品经理", "application", "ZYKfwZrhXiHzYjkH09tcnDTFnMf", 265),
    ("02", "Agent／智能体产品经理", "agent", "BMLJwt6TDiS4k5kR7NncHy08n4y", 284),
    ("03", "模型／算法策略产品经理", "model_strategy", "NKQLwmOpfiN7PEkhowCcqDqUnEd", 127),
    ("04", "AI 解决方案／交付产品经理", "solution_delivery", "HXMqwrQQNiePxbkRYlacmAknnDc", 95),
    ("05", "AI 商业化／增长运营产品经理", "growth_commercial", "QBQKwJcDsiPRNZkodgOcJ3tDnYc", 103),
    ("06", "端侧／软硬件系统产品经理", "edge_hardware", "JOsDwPSoViKD4vkL9WGcAfpQnOf", 105),
    ("07", "AI 平台／基础设施产品经理", "platform_infra", "UIpswJIjziJJm6kEOVNcdn9Inag", 97),
    ("08", "数据评测产品经理", "data_evaluation", "LwBmwFwMBiuz7QkkETNcwsWOnag", 106),
    ("09", "AI 安全／治理产品经理", "safety_governance", "MPCjwqLn2i7H4JkIjeNcABOunue", 119),
)

EXPECTED_MODULE_ROWS = {"1": 5, "2": 5, "3": 5, "4": 4, "5": 4, "6": 5, "7": 4}

EXPECTED_SECTION_SHA256 = {
    "01": "5e253cac7b6231ec2fc4ba6d05d3470d5cb0b56d7f9dbc2e1d2f59086cca5c5d",
    "02": "3362b2e8aece01bcadbbead43c7a657449d78bbe1438e8917c7b018b3c47d83e",
    "03": "e2048a2adcc5bb8cbf4ce733288991c65a1545683840eea2e2dc2b9ba7d283fa",
    "04": "227e4a4575634d5b157fda409fb21564b792f8395a105cb70055a1d6fd3d6704",
    "05": "29622abad46de062699091db7f9fd5bfeb5fbcac664b6b30c0455afed8dda996",
    "06": "0fd2b6539fb2954e0bb085dfb35cd1b14f03a25828a4b1342e4ca8dd304e2963",
    "07": "b795fdb2c589895038dc46e10d360357fd4d3c3e5e5813db981842832716f7fa",
    "08": "83f5f11b7d55d049ca722cee0b2807730d7ca1094676b81d077205b49ebf646b",
    "09": "459fac7a98a86483c3f2a858180a70a2aaaacc22637911287033bf111b49e670",
}


def main() -> None:
    errors: list[str] = []
    cards = CARDS.read_text(encoding="utf-8")
    profiles = PROFILES.read_text(encoding="utf-8")
    skill = SKILL.read_text(encoding="utf-8")

    headings = list(re.finditer(r"^## (0[1-9]) (.+)$", cards, re.MULTILINE))
    if len(headings) != 9:
        errors.append(f"expected 9 source-card sections, found {len(headings)}")
    total_rows = 0
    seen_urls: set[str] = set()
    for index, match in enumerate(headings):
        if index >= len(ROLE_SOURCES):
            errors.append(f"unexpected extra section: {match.group(1)} {match.group(2)}")
            continue
        number, title, role_id, token, revision = ROLE_SOURCES[index]
        if (match.group(1), match.group(2)) != (number, title):
            errors.append(
                f"section {index + 1} is {match.group(1)} {match.group(2)!r}, "
                f"expected {number} {title!r}"
            )
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(cards)
        section = cards[start:end]
        actual_digest = hashlib.sha256(section.encode("utf-8")).hexdigest()
        if actual_digest != EXPECTED_SECTION_SHA256[number]:
            errors.append(
                f"{number} source snapshot checksum mismatch; re-extract and version intentionally"
            )
        row_matches = re.findall(r"^\| 3\.([1-7]) ", section, re.MULTILINE)
        rows = len(row_matches)
        total_rows += rows
        if rows != 32:
            errors.append(f"{match.group(1)} {match.group(2)} has {rows} rows, expected 32")
        for module, expected_rows in EXPECTED_MODULE_ROWS.items():
            actual_rows = row_matches.count(module)
            if actual_rows != expected_rows:
                errors.append(
                    f"{number} module 3.{module} has {actual_rows} rows, expected {expected_rows}"
                )
        expected_url = f"https://kcn7b9ghigc3.feishu.cn/wiki/{token}"
        source_match = re.search(r"^- 来源：(https://\S+)$", section, re.MULTILINE)
        actual_url = source_match.group(1) if source_match else None
        if actual_url != expected_url:
            errors.append(f"{number} source URL mismatch: {actual_url!r}")
        elif actual_url in seen_urls:
            errors.append(f"{number} duplicates source URL {actual_url}")
        else:
            seen_urls.add(actual_url)
        revision_match = re.search(r"^- 文档版本：revision (\d+)$", section, re.MULTILINE)
        actual_revision = int(revision_match.group(1)) if revision_match else None
        if actual_revision != revision:
            errors.append(
                f"{number} revision mismatch: {actual_revision!r}, expected {revision}"
            )

        profile_heading = f"## `{role_id}`"
        profile_start = profiles.find(profile_heading)
        if profile_start < 0:
            errors.append(f"role profile missing: {role_id}")
        else:
            profile_end = profiles.find("\n## `", profile_start + len(profile_heading))
            profile_section = profiles[profile_start : profile_end if profile_end >= 0 else len(profiles)]
            expected_profile_source = f"- 来源：{expected_url}（revision {revision}）"
            if expected_profile_source not in profile_section:
                errors.append(f"role profile source/revision mismatch: {role_id}")
    if total_rows != 288:
        errors.append(f"expected 288 total self-check items, found {total_rows}")

    if len(seen_urls) != 9:
        errors.append(f"expected 9 unique source URLs, found {len(seen_urls)}")
    if "TODO" in skill or "[TODO" in cards or "[TODO" in profiles:
        errors.append("unfinished TODO marker found")
    if "经历历" in cards:
        errors.append("duplicated text typo found: 经历历")

    if errors:
        print("coverage audit: FAIL")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("coverage audit: PASS")
    print("- 9/9 role documents represented")
    print("- 288/288 source self-check items retained")
    print("- 9/9 role profiles linked to Feishu sources")


if __name__ == "__main__":
    main()
