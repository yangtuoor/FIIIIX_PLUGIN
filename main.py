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

插件元数据由同目录的 metadata.yaml 提供；AstrBot 3.5.19+ 会自动识别
继承 Star 的类，无需（也不应）使用已废弃的 @register 装饰器。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

from .parser import parse_tool_raw

PLUGIN_NAME = "astrbot_plugin_tool_arg_fix"

# 默认敏感工具：参数里可能含命令、代码或密钥，日志中不打印参数名
_DEFAULT_SENSITIVE: tuple[str, ...] = (
    "astrbot_execute_shell",
    "astrbot_execute_python",
    "astrbot_execute_sandbox",
)


class ToolArgFixPlugin(Star):
    """监听工具调用前的参数，必要时重写。

    当模型把工具调用写成 XML 文本而不是标准 tool_calls 时，AstrBot 会得到
    ``tool_args = {"raw": "<tool_call ...>{...}</tool_call>"}``。本插件在工具
    执行前解析这段 raw，把真实参数写回 tool_args。

    安装即用，默认无需任何配置。
    """

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        # AstrBot 依据 _conf_schema.json 自动生成配置对象并传入。
        # 它继承自 dict，同时提供 save_config() 等方法。
        self.config: AstrBotConfig | dict = config if config is not None else {}
        try:
            self.data_dir = str(StarTools.get_data_dir(PLUGIN_NAME))
        except Exception:  # noqa: BLE001
            self.data_dir = ""

        self._fix_count = 0
        self._fail_count = 0
        self._skip_count = 0

    # ------------------------------------------------------------------
    # 配置读取（带类型兜底，防止用户手改坏配置文件）
    # ------------------------------------------------------------------
    def _cfg(self, key: str, default: Any = None) -> Any:
        try:
            return self.config.get(key, default)
        except Exception:  # noqa: BLE001
            return default

    @property
    def enabled(self) -> bool:
        """是否启用参数修复。"""
        value = self._cfg("enabled", True)
        if isinstance(value, str):
            return value.strip().lower() not in {"false", "0", "no", "off", ""}
        return bool(value)

    @property
    def log_level(self) -> str:
        """日志级别，仅允许 silent / info / debug。"""
        value = str(self._cfg("log_level", "info") or "info").strip().lower()
        return value if value in {"silent", "info", "debug"} else "info"

    @property
    def warn_on_name_mismatch(self) -> bool:
        """工具名不一致时是否告警。"""
        return bool(self._cfg("warn_on_name_mismatch", True))

    @property
    def dry_run(self) -> bool:
        """演练模式：只解析不改写。"""
        return bool(self._cfg("dry_run", False))

    @property
    def sensitive_tools(self) -> set[str]:
        """日志中隐藏参数名的工具集合。

        配置项是个列表，默认值已在 _conf_schema.json 中给出。
        用户显式清空列表时，视为「不屏蔽任何工具」。
        """
        raw = self._cfg("sensitive_tools", _DEFAULT_SENSITIVE)
        if not isinstance(raw, list):
            return set(_DEFAULT_SENSITIVE)
        return {str(item).strip() for item in raw if str(item).strip()}

    def _describe_params(self, tool_name: str, keys: list[str]) -> str:
        """敏感工具只报参数数量，避免命令内容进日志。"""
        if tool_name in self.sensitive_tools:
            return f"<{len(keys)} 个参数，已隐藏>"
        return str(keys)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def initialize(self) -> None:
        """插件加载完成时调用。"""
        logger.info(
            f"[{PLUGIN_NAME}] 已加载；启用={self.enabled} "
            f"日志级别={self.log_level} 演练模式={self.dry_run}"
        )

    async def terminate(self) -> None:
        """插件卸载时调用。"""
        logger.info(
            f"[{PLUGIN_NAME}] 已卸载；本次共修复 {self._fix_count} 次，"
            f"失败 {self._fail_count} 次，跳过 {self._skip_count} 次"
        )

    # ------------------------------------------------------------------
    # 核心钩子
    # ------------------------------------------------------------------
    @filter.on_using_llm_tool()
    async def fix_tool_args(
        self,
        event: AstrMessageEvent,
        tool: Any,
        tool_args: dict | None,
    ) -> None:
        """在工具执行前修复被 raw 包裹的参数。"""
        if not self.enabled:
            return
        if not isinstance(tool_args, dict):
            return

        raw = tool_args.get("raw")
        if raw is None:
            return

        # 只处理「纯 raw 包装」；模型正常传了参数就不插手
        other_keys = [k for k in tool_args if k != "raw"]
        if other_keys:
            self._skip_count += 1
            if self.log_level == "debug":
                logger.debug(
                    f"[{PLUGIN_NAME}] 跳过（已有正常参数 {other_keys}）"
                )
            return

        tool_name, parsed = parse_tool_raw(raw)
        expected = getattr(tool, "name", None) or "?"

        if not parsed:
            self._fail_count += 1
            snippet = str(raw)[:160].replace("\n", "\\n")
            logger.warning(
                f"[{PLUGIN_NAME}] 解析失败，工具={expected} raw={snippet}"
            )
            return

        if (
            tool_name
            and expected != "?"
            and tool_name != expected
            and self.warn_on_name_mismatch
        ):
            logger.warning(
                f"[{PLUGIN_NAME}] 工具名不一致：模型声明={tool_name} 实际={expected}"
                "（参数照常写回）"
            )

        if self.dry_run:
            self._skip_count += 1
            logger.info(
                f"[{PLUGIN_NAME}] 演练模式，未修改。工具={expected} "
                f"将写入的参数={self._describe_params(expected, list(parsed.keys()))}"
            )
            return

        # 原地替换，后续 handler 直接拿到正确参数
        tool_args.clear()
        tool_args.update(parsed)
        self._fix_count += 1

        if self.log_level in {"info", "debug"}:
            logger.info(
                f"[{PLUGIN_NAME}] 已修复 工具={expected} "
                f"参数={self._describe_params(expected, list(parsed.keys()))}"
            )

    # ------------------------------------------------------------------
    # 运维指令
    # ------------------------------------------------------------------
    @filter.command("paramfix")
    async def paramfix_status(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[Any, None]:
        """查看参数修复统计。"""
        mode = "（演练模式）" if self.dry_run else ""
        yield event.plain_result(
            "工具参数修复器\n"
            f"状态：{'启用' if self.enabled else '关闭'}{mode}\n"
            f"已修复：{self._fix_count} 次\n"
            f"解析失败：{self._fail_count} 次\n"
            f"跳过：{self._skip_count} 次"
        )
