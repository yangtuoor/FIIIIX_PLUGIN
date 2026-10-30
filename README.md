# 工具参数修复器

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.16%2C%3C5-blue)](https://github.com/AstrBotDevs/AstrBot)
[![Version](https://img.shields.io/badge/version-1.0.0-brightgreen)](CHANGELOG.md)

修复模型以 **DSML / `<tool_call>` / 裸 JSON** 形式输出工具调用参数，导致 AstrBot 报
`Tool handler parameter mismatch, please check the handler definition.` 的问题。

安装即用，无需任何配置。

---

## 症状

### 表现一：日志报参数不匹配

```
使用工具：astrbot_execute_shell，参数：{'raw': '<tool_call id="call_kb02" name="astrbot_execute_shell">\n{"command": "ls ..."}'}
Tool `astrbot_execute_shell` Result: error: Tool handler parameter mismatch,
please check the handler definition.
Handler parameters: command: str, yield_time_ms: int = 10000, timeout: int | None = None, ...
```

### 表现二：机器人把 XML 当正文发出来

QQ 聊天窗口里出现这样的消息：

```
<｜｜DSML｜｜ calls>
<｜｜DSML｜｜ invoke name="web_search">
<｜｜DSML｜｜ parameter name="query" string="true">今天天气</｜｜DSML｜｜ parameter>
</｜｜DSML｜｜ invoke>
</｜｜DSML｜｜ calls>
```

---

## 原理

模型（尤其是 DeepSeek 系列）没有走标准 `tool_calls` 通道，而是把工具调用写成 XML 文本。
AstrBot 无法解析这种格式，只好把它整段塞进 `tool_args["raw"]`：

```python
tool_args = {"raw": '<tool_call name="astrbot_execute_shell">{"command": "ls"}</tool_call>'}
```

真正的 handler 定义是：

```python
async def call(self, context, command: str, background: bool = False, ...)
```

拿不到 `command`，于是抛 `TypeError`，被包装成「参数不匹配」。

本插件监听 `OnUsingLLMToolEvent`，在工具执行前把 `raw` 解析回真实参数字典，
原地覆盖 `tool_args`，handler 就能正常执行：

```python
tool_args.clear()
tool_args.update(parsed)   # {"command": "ls"}
```

---

## 安装

### 方式一：面板安装（推荐）

AstrBot 面板 → 插件 → 安装 → 填入仓库地址：

```
https://github.com/yangtuoor/FIIIIX_PLUGIN
```

### 方式二：手动解压

```bash
cd /opt/astrbot/data/plugins
unzip astrbot_plugin_tool_arg_fix.zip
systemctl restart astrbot
```

Windows 部署则解压到 `AstrBot/data/plugins/` 下，重启 AstrBot。

---

## 支持的格式

| 格式 | 示例 |
|---|---|
| DeepSeek DSML | `<｜｜DSML｜｜ invoke name="x"><｜｜DSML｜｜ parameter name="k" string="true">v</...>` |
| 标准 tool_call | `<tool_call name="x">{"k": "v"}</tool_call>` |
| 带 id 的 tool_call | `<tool_call id="call_1" name="x">{"k": "v"}</tool_call>` |
| 裸 JSON | `{"command": "ls", "timeout": 30}` |

参数值自动类型推断：

| 原始值 | 解析结果 |
|---|---|
| `true` / `false` | `True` / `False` |
| `null` / `none` | `None` |
| `30` | `30` (int) |
| `1.5` | `1.5` (float) |
| `["a","b"]` | `["a", "b"]` (list) |
| `{"k":"v"}` | `{"k": "v"}` (dict) |
| 其他 | 原样字符串 |

---

## 配置

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | bool | `true` | 启用参数修复 |
| `log_level` | string | `info` | `silent` / `info` / `debug` |
| `warn_on_name_mismatch` | bool | `true` | 模型声明的工具名与框架实际调用的工具名不一致时输出告警 |

---

## 指令

| 指令 | 说明 |
|---|---|
| `/paramfix` | 查看修复统计（已修复次数、解析失败次数） |

---

## 日志关键字

```
[tool_arg_fix] 已加载；启用=True 日志级别=info
[tool_arg_fix] 已修复 工具=web_search 参数=['query']
[tool_arg_fix] 解析失败，工具=web_search raw=<...>
[tool_arg_fix] 工具名不一致：模型声明=xxx 实际=yyy
[tool_arg_fix] 已卸载；本次共修复 N 次，失败 M 次
```

---

## 项目结构

```
astrbot_plugin_tool_arg_fix/
├── metadata.yaml        插件元信息
├── _conf_schema.json    配置项声明
├── main.py              插件主体（钩子 + 指令）
├── parser.py            格式解析器（可独立单测）
├── README.md            本文件
├── CHANGELOG.md         更新日志
└── LICENSE              MIT
```

`parser.py` 不依赖 AstrBot 运行时，可以脱离框架单独测试：

```python
from parser import parse_tool_raw

name, args = parse_tool_raw('<tool_call name="web_search">{"query": "天气"}</tool_call>')
# name == 'web_search'
# args == {'query': '天气'}
```

---

## 常见问题

**Q：装了之后原来的工具还能正常用吗？**

能。插件只处理「参数被包成纯 `{"raw": "..."}`」的情况。如果模型正常传了参数
（`tool_args` 里有 `command` 等真实字段），插件直接跳过，不做任何修改。

**Q：会不会误伤普通文本？**

不会。`parse_tool_raw` 只在文本含 DSML 标记、`<tool_call>` 标签，或本身是合法 JSON
对象时才返回结果。普通聊天文本返回 `(None, None)`。

**Q：和 `astrbot_plugin_search_hub` 里的同名功能冲突吗？**

功能重复但不冲突。`search_hub` 修复后 `raw` 已被清空，本插件检测到 `raw` 不存在会直接跳过，
只是日志可能多一行。建议二选一。

---

## 许可

[MIT](LICENSE) © 2026 yangtuoor
