#!/usr/bin/env python3
"""Publish this skill to SkillHub via the documented REST contract.

The official `skillhub` CLI covers the normal path, but it cannot attach a
skill icon: its release notes state that "CLI 发布不会自动上传 Skill 头像；
如果没有 iconUrl，发布后会使用默认占位图". This script fills that gap by
calling the same endpoint the web uploader uses.

Contract (reverse-engineered from the SkillHub web client and confirmed
against the live API):

    POST https://api.skillhub.cn/api/v1/community/skills/publish
    Authorization: Bearer <skh_...>
    Content-Type: multipart/form-data
        payload = JSON string
            {slug, displayName, version, summaryZh, changelog, iconUrl,
             category?, subCategories?}
        files   = repeated parts, filename = relative POSIX path

    POST https://api.skillhub.cn/api/v1/community/skill-icons/upload
    Authorization: Bearer <skh_...>
    Content-Type: multipart/form-data
        file = image bytes
    -> {"iconUrl": "..."}

Server rules learned the hard way:
  * File types are allow-listed. `LICENSE` (no extension) is rejected with
    "不允许的文件类型". Images are rejected too — the icon travels as an
    `iconUrl`, never as a packaged file.
  * `slug` must be globally unique and kebab-case (2-128 chars).
  * The package is capped at 10 MB.

Usage
-----
    export SKILLHUB_KEY=skh_xxx          # 个人中心 → API keys
    python3 scripts/publish_skillhub.py --dir . --dry-run
    python3 scripts/publish_skillhub.py --dir . --changelog "首次发布"
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HOST = "https://api.skillhub.cn"
PUBLISH_PATH = "/api/v1/community/skills/publish"
ICON_PATH = "/api/v1/community/skill-icons/upload"
CHECK_SLUG_PATH = "/api/v1/community/skills/check-slug"

# Mirrors the CLI's own exclusions plus the directories that must never leave
# the local machine (OCR intermediates, git metadata).
EXCLUDE_DIRS = {".git", ".idea", ".vscode", "node_modules", "__pycache__", "data"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".DS_Store", "Thumbs.db")
EXCLUDE_NAMES = {"LICENSE", "LICENCE", ".gitignore"}

# Extensions the server accepts. Anything outside this set is dropped with a
# warning rather than failing the whole publish.
ALLOWED_SUFFIXES = {
    ".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini",
    ".csv", ".tsv", ".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs",
    ".ts", ".tsx", ".jsx", ".swift", ".go", ".rs", ".java", ".kt", ".rb",
    ".c", ".h", ".cpp", ".hpp", ".sql", ".html", ".css", ".scss", ".xml",
    ".env.example", ".cfg", ".conf", ".properties", ".lock",
}

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---", re.S)


def parse_frontmatter(text: str) -> dict[str, str]:
    """Parse the flat `key: value` frontmatter used by SKILL.md.

    Deliberately dependency-free: PyYAML is not guaranteed to be present, and
    the fields we need are all single-line scalars.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    data: dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t", "-")) or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        data[key.strip()] = value
    return data


def collect_files(skill_dir: Path) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Return (files, skipped). `files` is [(relative_posix_path, bytes)]."""
    files: list[tuple[str, bytes]] = []
    skipped: list[str] = []
    for root, dirs, names in os.walk(skill_dir):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        for name in sorted(names):
            path = Path(root) / name
            if path.is_symlink():
                skipped.append(f"{path.name} (symlink)")
                continue
            if name in EXCLUDE_NAMES or name.endswith(EXCLUDE_SUFFIXES):
                continue
            if path.suffix.lower() not in ALLOWED_SUFFIXES:
                skipped.append(f"{path.relative_to(skill_dir).as_posix()} "
                               f"(extension not allow-listed)")
                continue
            files.append((path.relative_to(skill_dir).as_posix(),
                          path.read_bytes()))
    return files, skipped


def _multipart(parts: list[tuple[str, str | None, bytes]]) -> tuple[bytes, str]:
    """Build a multipart/form-data body from (name, filename, content).

    A `filename` of None produces a plain form field. This matters: the server
    parses `payload` only when it arrives without a filename — sending it as a
    file part fails with "缺少 payload 字段".
    """
    boundary = "----skillhub" + uuid.uuid4().hex
    out = bytearray()
    for name, filename, content in parts:
        out += f"--{boundary}\r\n".encode()
        if filename is None:
            out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        else:
            out += (f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n').encode()
            ctype = (mimetypes.guess_type(filename)[0]
                     or "application/octet-stream")
            out += f"Content-Type: {ctype}\r\n\r\n".encode()
        out += content
        out += b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def request(path: str, token: str, parts=None, method="GET") -> dict:
    url = HOST + path
    headers = {"Authorization": f"Bearer {token}",
               "X-Submitted-From": "cli"}
    data = None
    if parts is not None:
        data, ctype = _multipart(parts)
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"raw": body}
        raise SystemExit(f"HTTP {exc.code} {path}: "
                         f"{parsed.get('error') or parsed.get('message') or body}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=".", help="skill 目录")
    parser.add_argument("--changelog", default="")
    parser.add_argument("--category", default="")
    parser.add_argument("--icon", default="cover.png",
                        help="本地图标文件；不存在则跳过")
    parser.add_argument("--no-icon", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("SKILLHUB_KEY", "").strip()
    if not token and not args.dry_run:
        raise SystemExit("缺少 SKILLHUB_KEY 环境变量（个人中心 → API keys）")

    skill_dir = Path(args.dir).resolve()
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise SystemExit(f"未找到 {skill_md}")

    meta = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    slug = meta.get("slug", "")
    version = meta.get("version", "")
    display = meta.get("displayName", "") or meta.get("display_name", "")
    summary = (meta.get("summary") or meta.get("description") or "").strip()

    problems = []
    if not slug or not SLUG_RE.match(slug) or not 2 <= len(slug) <= 128:
        problems.append(f"slug 非法: {slug!r}")
    if not SEMVER_RE.match(version):
        problems.append(f"version 非法: {version!r}")
    if not display:
        problems.append("缺少 displayName")
    if problems:
        raise SystemExit("预检失败:\n  - " + "\n  - ".join(problems))

    files, skipped = collect_files(skill_dir)
    total = sum(len(content) for _, content in files)
    print(f"slug={slug} version={version} displayName={display}")
    print(f"files={len(files)} size={total / 1024 / 1024:.2f} MB")
    for note in skipped:
        print(f"  skipped: {note}")
    if total > 10 * 1024 * 1024:
        raise SystemExit("超过服务端 10 MB 上限")

    if args.dry_run:
        print(f"✓ Dry-run passed: {slug}@{version}")
        return

    payload = {
        "slug": slug,
        "displayName": display,
        "version": version,
        "summaryZh": summary or None,
        "changelog": args.changelog or None,
    }
    if args.category:
        payload["category"] = args.category
        payload["subCategories"] = []

    icon = skill_dir / args.icon
    if not args.no_icon and icon.is_file():
        result = request(ICON_PATH, token,
                         [("file", icon.name, icon.read_bytes())], method="POST")
        icon_url = result.get("iconUrl")
        if icon_url:
            payload["iconUrl"] = icon_url
            print(f"icon uploaded: {icon_url}")
        else:
            print(f"warn: 图标上传未返回 iconUrl: {result}")

    parts: list[tuple[str, str | None, bytes]] = [
        ("payload", None, json.dumps(payload, ensure_ascii=False).encode())
    ]
    parts += [("files", rel, content) for rel, content in files]

    result = request(PUBLISH_PATH, token, parts, method="POST")
    print(f"✓ Published: {json.dumps(result, ensure_ascii=False)}")
    print(f"  https://skillhub.cn/skills/{result.get('slug', slug)}")


if __name__ == "__main__":
    sys.exit(main())
