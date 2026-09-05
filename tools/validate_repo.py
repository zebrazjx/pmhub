#!/usr/bin/env python3
"""Validate PMHub's plugin manifest, skill names, UI prompts, and local links."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
EXPECTED_SKILLS = {
    "pmhub",
    "pmhub-jd-reverse-engineer",
    "pmhub-ai-native-resume",
    "pmhub-interview-1h-rescue",
}


def frontmatter_value(text: str, key: str) -> str | None:
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return None
    value_match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", match.group(1))
    if not value_match:
        return None
    return value_match.group(1).strip().strip('"\'')


def local_markdown_links(path: Path, text: str):
    for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text):
        target = target.strip().strip("<>")
        if not target or target.startswith(("http://", "https://", "mailto:", "#", "/")):
            continue
        clean = unquote(target.split("#", 1)[0])
        if clean:
            yield (path.parent / clean).resolve(), target


def main() -> int:
    errors: list[str] = []

    manifest_path = ROOT / ".codex-plugin" / "plugin.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"Invalid plugin manifest: {exc}")
        manifest = {}

    for key in ("name", "version", "description", "author", "skills", "interface"):
        if not manifest.get(key):
            errors.append(f"plugin.json is missing {key}")
    if manifest.get("name") != "pmhub":
        errors.append("plugin.json name must be pmhub")
    if manifest.get("skills") != "./skills/":
        errors.append("plugin.json skills must be ./skills/")

    discovered: set[str] = set()
    if not SKILLS_DIR.is_dir():
        errors.append("skills/ directory is missing")
    else:
        for skill_dir in sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir()):
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                errors.append(f"Missing SKILL.md in {skill_dir.relative_to(ROOT)}")
                continue
            text = skill_md.read_text(encoding="utf-8")
            name = frontmatter_value(text, "name")
            description = frontmatter_value(text, "description")
            if not name:
                errors.append(f"Missing frontmatter name in {skill_md.relative_to(ROOT)}")
                continue
            discovered.add(name)
            if name != skill_dir.name:
                errors.append(f"Folder/name mismatch: {skill_dir.name} != {name}")
            if not description:
                errors.append(f"Missing description in {skill_md.relative_to(ROOT)}")
            if "[TODO:" in text:
                errors.append(f"Unfinished placeholder in {skill_md.relative_to(ROOT)}")

            ui_path = skill_dir / "agents" / "openai.yaml"
            if not ui_path.is_file():
                errors.append(f"Missing agents/openai.yaml for {name}")
            else:
                ui_text = ui_path.read_text(encoding="utf-8")
                if f"${name}" not in ui_text:
                    errors.append(f"Default prompt does not mention ${name}: {ui_path.relative_to(ROOT)}")

            for markdown in skill_dir.rglob("*.md"):
                markdown_text = markdown.read_text(encoding="utf-8")
                if "[TODO:" in markdown_text:
                    errors.append(f"Unfinished placeholder in {markdown.relative_to(ROOT)}")
                for resolved, raw_target in local_markdown_links(markdown, markdown_text):
                    if not resolved.exists():
                        errors.append(
                            f"Broken link in {markdown.relative_to(ROOT)}: {raw_target}"
                        )

            if any(skill_dir.rglob(".git")):
                errors.append(f"Nested .git directory in {skill_dir.relative_to(ROOT)}")
            if any(skill_dir.rglob("*.skill")):
                errors.append(f"Stale prebuilt .skill archive in {skill_dir.relative_to(ROOT)}")

    missing = EXPECTED_SKILLS - discovered
    extra = discovered - EXPECTED_SKILLS
    if missing:
        errors.append(f"Missing expected skills: {', '.join(sorted(missing))}")
    if extra:
        errors.append(f"Unexpected skills: {', '.join(sorted(extra))}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"PMHub validation passed: {len(discovered)} skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
