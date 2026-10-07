#!/usr/bin/env python3
"""One-shot: Eastmoney f14 → patch name_zh on existing stock_sw_l2 members."""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import yaml

from scripts.common.em_client import _infer_ts_code, fetch_clist_all_a

_DEFAULT = os.path.join(_ROOT, "config", "taxonomy", "stock_sw_l2.yaml")


def _name_map() -> dict[str, str]:
    df = fetch_clist_all_a(["f12", "f13", "f14"])
    out: dict[str, str] = {}
    for _, r in df.iterrows():
        row = r.to_dict()
        ts = _infer_ts_code(row.get("f12"), row)
        if not ts:
            continue
        name = row.get("f14")
        if name in (None, ""):
            continue
        out[ts] = str(name)
    return out


def _fmt_code(code) -> str:
    if code in (None, ""):
        return "null"
    return "'%s'" % code


def _fmt_name(name: str) -> str:
    # Quote when YAML flow scalars would mis-parse (Ⅱ etc. are fine unquoted).
    if any(ch in name for ch in (":", "#", "{", "}", "[", "]", ",", '"', "'", "\\")):
        return yaml.dump(name, allow_unicode=True, default_style='"').strip()
    return name


def rewrite_yaml(data: dict, names: dict[str, str]) -> str:
    map_version = data.get("map_version") or "sw2021-v1"
    note = data.get("note")
    members = data.get("members") or []
    lines = ["map_version: %s" % map_version]
    if note is not None:
        note_s = str(note).rstrip("\n")
        if "\n" in note_s:
            lines.append("note: >")
            for part in note_s.splitlines():
                lines.append("  %s" % part)
        else:
            lines.append("note: %s" % note_s)
    lines.append("members:")
    if not members:
        lines.append("  []")
        return "\n".join(lines) + "\n"
    for m in members:
        if isinstance(m, str):
            lines.append("  - %s" % m)
            continue
        ts = m["ts_code"]
        code_s = _fmt_code(m.get("sw_l2_code"))
        name = names.get(ts) or m.get("name_zh")
        if name not in (None, ""):
            lines.append(
                "  - {ts_code: %s, sw_l2_code: %s, name_zh: %s}"
                % (ts, code_s, _fmt_name(str(name)))
            )
        else:
            lines.append("  - {ts_code: %s, sw_l2_code: %s}" % (ts, code_s))
    return "\n".join(lines) + "\n"


def patch(in_path: str, out_path: str) -> int:
    with open(in_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("yaml must be a mapping: %s" % in_path)
    members = data.get("members") or []
    before = len(members)
    names = _name_map()
    patched = 0
    for m in members:
        if isinstance(m, str):
            continue
        ts = m.get("ts_code")
        if ts in names:
            m["name_zh"] = names[ts]
            patched += 1
    text = rewrite_yaml(data, names)
    # Never add new ts_codes: rewrite only iterates existing members.
    after = len(data.get("members") or [])
    if after != before:
        raise RuntimeError("member count changed %d -> %d" % (before, after))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return patched


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="in_path", default=_DEFAULT)
    ap.add_argument("--out", dest="out_path", default=_DEFAULT)
    args = ap.parse_args(argv)
    n = patch(args.in_path, args.out_path)
    print("patched name_zh on %d existing members -> %s" % (n, args.out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
