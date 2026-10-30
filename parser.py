# -*- coding: utf-8 -*-
"""工具参数解析器：兼容 DSML / <tool_call> / 裸 JSON 三种格式。

模型（尤其是 DeepSeek 系列）有时不按 OpenAI 标准输出 tool_calls，
而是把工具调用写成 XML 风格的文本，AstrBot 会把它整段塞进
``tool_args["raw"]``，导致真正的 handler 拿不到参数，报：

    Tool handler parameter mismatch, please check the handler definition.

本模块把这类文本还原成 (工具名, 参数字典)。
"""

from __future__ import annotations

import json
import re
from typing import Any

# DeepSeek 的专用标记：｜｜DSML｜｜（U+FF5C 全角竖线 ×2）
DSML_MARK = "\uff5c\uff5cDSML\uff5c\uff5c"

_DSML_MARK_ESC = re.escape(DSML_MARK)

# <｜｜DSML｜｜ parameter name="xxx" string="true">值</｜｜DSML｜｜ parameter>
DSML_PARAM_RE = re.compile(
    r"<" + _DSML_MARK_ESC + r"\s*parameter\s+name=[\"']([^\"']+)[\"'][^>]*>(.*?)</\s*"
    + _DSML_MARK_ESC + r"\s*parameter\s*>",
    re.S,
)

# <｜｜DSML｜｜ invoke name="xxx">
DSML_NAME_RE = re.compile(r"invoke\s+name=[\"']([^\"']+)[\"']", re.S)

# <｜｜DSML｜｜ calls> ... </｜｜DSML｜｜ calls>  整块
DSML_BLOCK_RE = re.compile(
    r"<" + _DSML_MARK_ESC + r"\s*calls?\s*>.*?</\s*" + _DSML_MARK_ESC + r"\s*calls?\s*>",
    re.S,
)

# <tool_call name="xxx">{json}</tool_call>
TOOLCALL_RE = re.compile(
    r"<tool_call\b[^>]*?name=[\"']([^\"']+)[\"'][^>]*>(.*?)</tool_call>",
    re.S,
)

# <tool_call id="x" name="y"> 的宽松匹配（属性顺序不定）
TOOLCALL_NAME_RE = re.compile(r"<tool_call\b([^>]*)>", re.I)

# 从任意文本里抓最外层的 {...}
JSON_OBJ_RE = re.compile(r"(\{.*\})", re.S)

_INT_RE = re.compile(r"-?\d+")
_FLOAT_RE = re.compile(r"-?\d+\.\d+")


def _try_json(value: str) -> tuple[bool, Any]:
    try:
        return True, json.loads(value)
    except Exception:  # noqa: BLE001
        return False, value


def _coerce(value: str) -> Any:
    """把字符串值按字面量推断类型。"""
    text = value.strip()
    low = text.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in {"null", "none"}:
        return None
    if _INT_RE.fullmatch(text):
        try:
            return int(text)
        except ValueError:
            return text
    if _FLOAT_RE.fullmatch(text):
        try:
            return float(text)
        except ValueError:
            return text
    # 值本身可能是 JSON 数组或对象
    if text[:1] in "[{":
        ok, parsed = _try_json(text)
        if ok:
            return parsed
    return text


def parse_dsml(raw: str) -> tuple[str | None, dict[str, Any] | None]:
    """解析 DeepSeek 的 DSML 格式。"""
    args: dict[str, Any] = {}
    for name, value in DSML_PARAM_RE.findall(raw):
        args[name.strip()] = _coerce(value)
    match = DSML_NAME_RE.search(raw)
    name = match.group(1).strip() if match else None
    return name, (args or None)


def parse_tool_call(raw: str) -> tuple[str | None, dict[str, Any] | None]:
    """解析 <tool_call name="xxx">{json}</tool_call>。"""
    match = TOOLCALL_RE.search(raw)
    if not match:
        # 属性顺序不定的情况：先拿 tag，再从标签属性里按字段找 name=
        tag = TOOLCALL_NAME_RE.search(raw)
        if tag:
            attrs = tag.group(1) or ""
            name_match = re.search(r"name=[\"']([^\"']+)[\"']", attrs)
            closing = raw.find("</tool_call>", tag.end())
            if name_match and closing > 0:
                body = raw[tag.end():closing]
                obj = JSON_OBJ_RE.search(body)
                if obj:
                    ok, parsed = _try_json(obj.group(1))
                    if ok and isinstance(parsed, dict):
                        return name_match.group(1).strip(), parsed
        return None, None

    name = match.group(1).strip()
    obj = JSON_OBJ_RE.search(match.group(2))
    if obj:
        ok, parsed = _try_json(obj.group(1))
        if ok and isinstance(parsed, dict):
            return name, parsed
    return None, None


def parse_bare_json(raw: str) -> tuple[None, dict[str, Any] | None]:
    """解析裸 JSON（没有工具名包裹）。"""
    if "tool_call" in raw or DSML_MARK in raw:
        return None, None
    obj = JSON_OBJ_RE.search(raw)
    if not obj:
        return None, None
    ok, parsed = _try_json(obj.group(1))
    if ok and isinstance(parsed, dict) and parsed:
        return None, parsed
    return None, None


def parse_tool_raw(raw: Any) -> tuple[str | None, dict[str, Any] | None]:
    """统一入口：从 raw 字符串解析出 (工具名, 参数字典)。

    Args:
        raw: 模型输出的原始文本。

    Returns:
        ``(tool_name, args)``。解析失败时返回 ``(None, None)``。
        ``tool_name`` 可能为 ``None``（裸 JSON 场景），此时只返回参数。
    """
    if not isinstance(raw, str) or not raw.strip():
        return None, None

    text = raw.strip()

    if DSML_MARK in text:
        name, args = parse_dsml(text)
        if args:
            return name, args
        return None, None

    name, args = parse_tool_call(text)
    if args:
        return name, args

    return parse_bare_json(text)


def strip_dsml_blocks(text: str) -> str:
    """把文本里的 DSML 调用块整段剥掉，只留正文。"""
    if DSML_MARK not in text:
        return text
    return DSML_BLOCK_RE.sub("", text).strip()


__all__ = [
    "DSML_MARK",
    "parse_tool_raw",
    "parse_dsml",
    "parse_tool_call",
    "parse_bare_json",
    "strip_dsml_blocks",
]
