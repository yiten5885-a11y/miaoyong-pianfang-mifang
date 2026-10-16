#!/usr/bin/env python3
"""Local personal profile for the interaction gate (S3).

The profile is the one piece of state this skill keeps. It holds what the user
voluntarily told us about themselves — chronic conditions, regular medication,
allergies, pregnancy/nursing status, diet constraints — so that every later
answer can be filtered through it without the user repeating themselves.

Storage
-------
    ~/.miaoyong-pianfang-mifang/profile.json

Override with the `MIAOYONG_PROFILE_PATH` environment variable. The file is
written with mode 0600. It never leaves the machine: no script in this package
performs a network request, and `references/personal-profile.md` documents the
exact on-disk shape so the user can inspect or delete it.

Privacy stance
--------------
The profile is opt-in and revocable. An absent or empty profile is the default
and leaves the gate inert — the skill must never invent a condition the user
did not state, and must never block a formula on a guess.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from interactions import normalize_drugs, unknown_drugs  # noqa: E402

ENV_VAR = "MIAOYONG_PROFILE_PATH"
DEFAULT_DIR = ".miaoyong-pianfang-mifang"
DEFAULT_FILE = "profile.json"

FIELDS = ("conditions", "medications", "allergies", "special", "diet")

FIELD_LABELS = {
    "conditions": "慢性病 / 已知疾病",
    "medications": "长期服用的西药",
    "allergies": "食物或药物过敏",
    "special": "特殊状态",
    "diet": "饮食限制",
}

SPECIAL_OPTIONS = ["孕期", "备孕", "哺乳", "婴幼儿", "儿童", "老年", "素食"]

EMPTY_PROFILE: dict = {
    "version": 1,
    "updated_at": None,
    "conditions": [],
    "medications": [],
    "allergies": [],
    "special": [],
    "diet": [],
    "notes": "",
}


def profile_path() -> Path:
    override = os.environ.get(ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / DEFAULT_DIR / DEFAULT_FILE


def _clean_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace("；", ",").replace("、", ",").split(",")]
        return [p for p in parts if p]
    return [str(v).strip() for v in value if str(v).strip()]


def load_profile(path: Path | None = None, *, derive: bool = True) -> dict:
    """Read the profile. Returns an empty profile when none is stored.

    `derive=True` attaches the `_drug_classes` field used by the interaction
    engine. Derived data is never written back to disk.
    """
    path = path or profile_path()
    profile = json.loads(json.dumps(EMPTY_PROFILE))
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}
        if isinstance(raw, dict):
            for key in FIELDS:
                profile[key] = _clean_list(raw.get(key))
            profile["notes"] = str(raw.get("notes") or "")
            profile["updated_at"] = raw.get("updated_at")
    if derive:
        profile["_drug_classes"] = normalize_drugs(profile["medications"])
        profile["_unknown_drugs"] = unknown_drugs(profile["medications"])
    return profile


def save_profile(profile: dict, path: Path | None = None) -> Path:
    """Persist the profile with 0600 permissions."""
    path = path or profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: profile.get(key) or [] for key in FIELDS}
    payload["notes"] = profile.get("notes") or ""
    payload["version"] = 1
    payload["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return path


def clear_profile(path: Path | None = None) -> bool:
    path = path or profile_path()
    if path.is_file():
        path.unlink()
        return True
    return False


def update_profile(changes: dict, path: Path | None = None, *,
                   mode: str = "replace") -> dict:
    """Apply `changes` to the stored profile.

    mode="replace" overwrites the listed fields; mode="add" appends to them;
    mode="remove" deletes the given values from them.
    """
    profile = load_profile(path, derive=False)
    for key, value in changes.items():
        if key not in FIELDS:
            continue
        incoming = _clean_list(value)
        if mode == "replace":
            profile[key] = incoming
        elif mode == "add":
            existing = list(profile[key])
            for item in incoming:
                if item not in existing:
                    existing.append(item)
            profile[key] = existing
        elif mode == "remove":
            profile[key] = [v for v in profile[key] if v not in incoming]
    if "notes" in changes:
        profile["notes"] = str(changes["notes"] or "")
    save_profile(profile, path)
    return load_profile(path)


def is_empty(profile: dict) -> bool:
    return not any(profile.get(key) for key in FIELDS)


def describe(profile: dict) -> str:
    """One-line human summary, or a prompt to set one up."""
    if is_empty(profile):
        return "未建立用药档案（本次按通用规则给建议）"
    parts: list[str] = []
    for key in FIELDS:
        values = profile.get(key) or []
        if values:
            parts.append(f"{FIELD_LABELS[key]}：{'、'.join(values)}")
    return "；".join(parts)


def summary_payload(profile: dict) -> dict:
    """Structured summary for the answer layer, with derived drug classes.

    Accepts either a `load_profile()` result or an ad-hoc dictionary, so the
    caller never has to remember to pre-compute the derived fields.
    """
    medications = profile.get("medications") or []
    classes = profile.get("_drug_classes")
    if classes is None:
        classes = normalize_drugs(medications)
    unknown = profile.get("_unknown_drugs")
    if unknown is None:
        unknown = unknown_drugs(medications)
    return {
        "is_empty": is_empty(profile),
        "describe": describe(profile),
        "conditions": profile.get("conditions") or [],
        "medications": medications,
        "drug_classes": classes,
        "unknown_medications": unknown,
        "allergies": profile.get("allergies") or [],
        "special": profile.get("special") or [],
        "diet": profile.get("diet") or [],
        "storage": str(profile_path()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="妙用偏方秘方速查 · 个人用药档案")
    parser.add_argument("--show", action="store_true", help="显示当前档案")
    parser.add_argument("--path", action="store_true", help="显示档案文件路径")
    parser.add_argument("--json", dest="raw_json",
                        help="用一段 JSON 直接设置档案")
    parser.add_argument("--clear", action="store_true", help="删除档案")
    parser.add_argument("--mode", choices=("replace", "add", "remove"),
                        default="replace")
    for field in FIELDS:
        parser.add_argument(f"--{field}", action="append", default=None,
                            help=f"{FIELD_LABELS[field]}（逗号分隔，可重复）")
    parser.add_argument("--notes", default=None)
    args = parser.parse_args()

    if args.path:
        print(profile_path())
        return

    if args.clear:
        removed = clear_profile()
        print("档案已删除" if removed else "没有档案需要删除")
        return

    changes: dict = {}
    if args.raw_json:
        try:
            parsed = json.loads(args.raw_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--json 解析失败: {exc}")
        if not isinstance(parsed, dict):
            raise SystemExit("--json 需要一个 JSON 对象")
        changes.update(parsed)
    for field in FIELDS:
        values = getattr(args, field)
        if values:
            merged: list[str] = []
            for chunk in values:
                merged.extend(_clean_list(chunk))
            changes[field] = merged
    if args.notes is not None:
        changes["notes"] = args.notes

    if changes:
        profile = update_profile(changes, mode=args.mode)
        print(f"已更新（{args.mode}）-> {profile_path()}")
        print(describe(profile))
        unknown = profile.get("_unknown_drugs") or []
        if unknown:
            print(f"注意：以下药物未在相互作用库中登记，按未评估处理："
                  f"{'、'.join(unknown)}")
        return

    profile = load_profile()
    print(json.dumps(summary_payload(profile), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
