# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-10-30

### 新增

- 监听 `OnUsingLLMToolEvent`，在工具执行前修复被 `raw` 包裹的参数
- 支持三种模型输出格式：
  - DeepSeek DSML：`<｜｜DSML｜｜ calls> / <｜｜DSML｜｜ invoke> / <｜｜DSML｜｜ parameter>`
  - 标准 `<tool_call name="x">{json}</tool_call>`（属性顺序不限）
  - 裸 JSON：`{"command": "ls", "timeout": 30}`
- 参数值自动类型推断：`true` / `false` / `null` / 整数 / 浮点 / JSON 数组 / JSON 对象
- `strip_dsml_blocks()` 工具函数：把 DSML 调用块从正文里剥离
- `/paramfix` 指令：查看修复统计

### 配置项

- `enabled`：总开关，默认 `true`
- `log_level`：`silent` / `info` / `debug`，默认 `info`
- `warn_on_name_mismatch`：工具名不一致时告警，默认 `true`

### 修复的问题

- `Tool handler parameter mismatch, please check the handler definition.`
  模型把工具调用写成 XML 文本，AstrBot 塞进 `tool_args["raw"]`，handler 拿不到
  `command` 等参数而报错。
- 机器人把 `<｜｜DSML｜｜ calls>...` 原文当正文发到聊天窗口。

### 测试

10 项单元测试全部通过，覆盖：

- DSML 单参数 / 多参数（含数值与布尔）/ 带正文
- `tool_call` 标准与带 `id` 属性
- 裸 JSON
- 3 种普通文本不被误伤
- `strip_dsml_blocks` 剥离正确性
