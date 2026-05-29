# 自动更新方案

项目当前使用 GitHub Releases 作为更新源，不再要求用户填写第三方 CDK 或 `manifest.json` 地址。

## 发布要求

1. 在 `DaiMao204/NightChainsTech` 创建新的 GitHub Release。
2. 上传完整 ZIP 更新包，文件名建议为 `NightChainsTech_<version>.zip`。
3. 如果同一 Release 中同时存在增量包，完整包文件名不要包含 `Update`、`Patch`、`Increment`。
4. 推荐在 Release 说明中填写 SHA256，格式例如：

```text
SHA256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

如果 GitHub 资源接口提供 `digest=sha256:...`，程序会优先使用该值。未提供 SHA256 时仍可更新，但会跳过完整性校验。

## 用户流程

1. 点击左侧导航底部的 `更新`。
2. 程序请求 GitHub 最新 Release。
3. 有新版本时点击 `立即更新`。
4. 程序下载 ZIP、校验 SHA256（如果提供）、启动独立 updater。
5. 主程序退出，updater 备份旧文件、替换新文件并重启。

## 保护目录

更新替换时会保留这些用户数据目录：

- `config`
- `logs`
- `cache`
- `diagnostics`
- `temp`

第一版使用完整 ZIP 包更新，不做增量补丁。
