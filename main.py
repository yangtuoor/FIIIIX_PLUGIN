# -*- coding: utf-8 -*-
"""工具参数修复器 —— 修复 DSML / <tool_call> / raw 包装导致的参数不匹配。

问题现象：
    Tool `astrbot_execute_shell` Result: error: Tool handler parameter
    mismatch, please check the handler definition.
    Handler parameters: command: str, ...

原因：
    模型（DeepSeek 等）没有走标准 tool_calls 通道，而是把工具调用写成
    XML 文本，AstrBot 把它整段塞进 ``tool_args = {"raw": "<...>"}``，
    handler 拿不到 ``command`` 等真实参数。

解法：
    在 ``OnUsingLLMToolEvent`` 阶段介入，把 ``raw`` 解析回真实参数字典，
    原地覆盖 ``tool_args``，后续 handler 就能正常执行。
"""

from __future__ import annotations

from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.tool import FunctionTool

from .parser import parse_tool_raw

PLUGIN_NAME = "astrbot_plugin_tool_arg_fix"


@register(
    PLUGIN_NAME,
    "worker",
    "工具参数修复器：自动纠正 DSML / tool_call 包裹的工具参数",
    "1.0.0",
)
class ToolArgFixPlugin(Star):
    """监听工具调用前的参数，必要时重写。"""

    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self._fix_count = 0
        self._fail_count = 0

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------
    def _cfg(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    @property
    def _enabled(self) -> bool:
        return bool(self._cfg("enabled", True))

    @property
    def _log_level(self) -> str:
        return str(self._cfg("log_level", "info") or "info").lower()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def initialize(self) -> None:
        logger.info(
            f"[{PLUGIN_NAME}] 已加载；启用={self._enabled} 日志级别={self._log_level}"
        )

    async def terminate(self) -> None:
        logger.info(
            f"[{PLUGIN_NAME}] 已卸载；本次共修复 {self._fix_count} 次，失败 {self._fail_count} 次"
        )

    # ------------------------------------------------------------------
    # 核心钩子
    # ------------------------------------------------------------------
    @filter.on_using_llm_tool()
    async def fix_tool_args(
        self,
        event: AstrMessageEvent,
        tool: FunctionTool,
        tool_args: dict | None,
    ) -> None:
        """在工具执行前修复被 raw 包裹的参数。"""
        if not self._enabled:
            return
        if not isinstance(tool_args, dict):
            return

        raw = tool_args.get("raw")
        if raw is None:
            return

        # 只有「纯 raw 包装」才处理；如果模型正常传了参数，就不插手
        other_keys = [k for k in tool_args if k != "raw"]
        if other_keys:
            if self._log_level == "debug":
                logger.debug(
                    f"[{PLUGIN_NAME}] 跳过（已有正常参数 {other_keys}）"
                )
            return

        tool_name, parsed = parse_tool_raw(raw)

        if not parsed:
            self._fail_count += 1
            snippet = str(raw)[:160].replace("\n", "\\n")
            logger.warning(
                f"[{PLUGIN_NAME}] 解析失败，工具={getattr(tool, 'name', '?')} raw={snippet}"
            )
            return

        expected = getattr(tool, "name", None)
        if (
            tool_name
            and expected
            and tool_name != expected
            and bool(self._cfg("warn_on_name_mismatch", True))
        ):
            logger.warning(
                f"[{PLUGIN_NAME}] 工具名不一致：模型声明={tool_name} 实际={expected}"
                "（参数照常写回）"
            )

        # 原地替换，后续 handler 直接拿到正确参数
        tool_args.clear()
        tool_args.update(parsed)
        self._fix_count += 1

        if self._log_level in {"info", "debug"}:
            logger.info(
                f"[{PLUGIN_NAME}] 已修复 工具={expected} 参数={list(parsed.keys())}"
            )

    # ------------------------------------------------------------------
    # 运维指令
    # ------------------------------------------------------------------
    @filter.command("paramfix")
    async def paramfix_status(self, event: AstrMessageEvent):
        """查看参数修复统计。"""
        yield event.plain_result(
            f"工具参数修复器\n"
            f"状态：{'启用' if self._enabled else '关闭'}\n"
            f"已修复：{self._fix_count} 次\n"
            f"解析失败：{self._fail_count} 次"
        )
