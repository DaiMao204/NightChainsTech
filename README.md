# 黑月科技

雷索纳斯自动化辅助工具，当前维护版聚焦跑商路线规划、地图导航、账号配置读取、自动购买/出售和运行状态可视化。

本项目基于 [Night-stars-1/Auto_Resonance](https://github.com/Night-stars-1/Auto_Resonance) 继续维护和重构，保留原项目许可和作者声明。

> [!WARNING]
> 当前版本为 `v0.1.0-beta` 测试版。地图识别、账号配置读取、跑商流程和疲劳恢复仍需要更多账号与模拟器环境验证。

## 主要变化

- 重构跑商配置界面，支持自动规划、手动双城、候选路线三选一/五选一。
- 接入 Columba Bot 风格的商品、疲劳、声望与综合参考利润计算。
- 支持账号配置读取：货舱容量、城市声望、城市开放状态、商品未解锁状态。
- 增加实时运行状态：当前路线、书量、抬砍、疲劳、利润和执行/停止按钮。
- 引入 GitHub Releases 自动更新，不再依赖 MirrorChyan。
- 更新地图导航方案，按城市坐标与锚点进行定位。

## 下载与运行

1. 前往 [Releases](https://github.com/DaiMao204/NightChainsTech/releases/latest) 下载 `NightChainsTech_<version>.zip`。
2. 解压到英文路径目录。
3. 运行 `黑月科技.exe`。

推荐模拟器：

- MuMu 模拟器
- 16:9 分辨率
- 推荐 `1920x1080` 或 `1280x720`

## 源码运行

需要 Python 3.11 或 3.12。

```powershell
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
python gui.py
```

## 自动更新

软件内点击左侧底部 `更新`，会检查本仓库最新 GitHub Release。

发布完整包时建议同时在 Release 说明中写入 SHA256：

```text
SHA256: <64位sha256>
```

详细流程见 [docs/AUTO_UPDATE.md](docs/AUTO_UPDATE.md)。

维护者发布流程见 [docs/RELEASE.md](docs/RELEASE.md)。

## 反馈

请前往 [Issues](https://github.com/DaiMao204/NightChainsTech/issues) 提交问题、截图、日志和复现步骤。

## 许可

本项目沿用原项目 MIT 许可。详见 [LICENSE](LICENSE)。
