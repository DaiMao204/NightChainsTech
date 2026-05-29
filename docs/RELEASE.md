# 发布流程

## 首次迁移

1. 在 GitHub 打开原项目 `Night-stars-1/Auto_Resonance`。
2. 点击 `Fork`。
3. Fork 后进入仓库设置，将仓库名改为 `NightChainsTech`。
4. 本地执行：

```powershell
git remote set-url origin https://github.com/DaiMao204/NightChainsTech.git
git push -u origin maintenance/revive-2026
```

确认无误后，可以在 GitHub 上将默认分支切换为 `maintenance/revive-2026`，或把本地分支合并/重命名为 `main` 后推送。

## 发布测试版

第一个测试版 tag：

```powershell
git tag v0.1.0-beta
git push origin v0.1.0-beta
```

推送 tag 后，`.github/workflows/build_release.yml` 会自动构建 Windows 发布包：

- `NightChainsTech_v0.1.0-beta.zip`
- `SHA256.txt`

Release 会被标记为 prerelease。

## 更新版本号

界面显示版本在 `version.py`：

```python
__version__ = "v0.1.0-beta"
```

Python 包版本在 `pyproject.toml`，使用 PEP 440 写法：

```toml
version = "0.1.0b0"
```

正式发布前建议同步更新 README 中的测试版说明。
