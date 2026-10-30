# 更新日志

## [1.1.0] - 2026-10-30

### 变更

- **移除 `@register` 装饰器**。AstrBot 3.5.19+ 会自动识别继承 `Star` 的类，
  该装饰器已废弃且未来会移除。插件元数据完全交由 `metadata.yaml` 提供。
- **配置改用 `AstrBotConfig` 注入**。构造函数签名从 `config: dict | None` 改为
  `config: AstrBotConfig | None`，符合官方规范。

### 新增

- **`sensitive_tools` 配置项**。默认包含 `astrbot_execute_shell`、
  `astrbot_execute_python`、`astrbot_execute_sandbox`。这些工具的参数被修复时，
  日志只记录参数数量（`<2 个参数，已隐藏>`），不打印参数名。
- **`dry_run` 演练模式**。开启后只解析并输出日志，不真正改写 `tool_args`，
  用于排查「修了但依然报错」的情况。
- **`/paramfix` 增加「跳过」计数**，区分「已有正常参数」和「演练模式」两种情况。
- **配置项 `log_level` 增加中文 `labels` 与 `subtitles`**，管理面板下拉框里
  直接显示「静默（仅记录失败）/ 常规（记录修复动作）/ 调试（打印解析细节）」。

### 修复

- `metadata.yaml` 的 `help` 字段含冒号未加引号，导致 YAML 解析失败。
  改用 `|` 块标量。
- `sensitive_tools` 默认值原本写在代码里，用户在面板上保存一次就会被空列表覆盖。
  改为直接写进 `_conf_schema.json` 的 `default`。
- `metadata.yaml` 的 `desc` 键规范为 AstrBot 实际读取的 `desc`（原为 `description`）。
- `author` 从占位值改为 `yangtuoor`。

### 已知问题

- 无。

---

## [1.0.0] - 2026-10-30

### 新增

- 监听 `OnUsingLLMToolEvent`，工具执行前解析 `raw` 并原地重写 `tool_args`。
- 支持三种格式：DeepSeek DSML、标准 `<tool_call>`、裸 JSON。
- 参数值自动类型推断：bool / null / int / float / array / object。
- `/paramfix` 指令查看修复统计。
- 配置项：`enabled`、`log_level`、`warn_on_name_mismatch`。

### 测试

10 项单元测试全部通过（DSML 单/多参数、tool_call 带/不带 id、裸 JSON、
三种纯文本不误伤、`strip_dsml_blocks`）。
