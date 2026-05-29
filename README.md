# 黑月科技

雷索纳斯自动化辅助工具，当前维护版对原项目进行了重构，优化和新增了大量功能，同时大幅调整了UI界面。

本项目基于 [Night-stars-1/Auto_Resonance](https://github.com/Night-stars-1/Auto_Resonance) 继续维护和重构，保留了原项目许可和作者声明。

> [!WARNING]
> 当前版本为 `v0.1.0-beta` 测试版。地图识别、账号配置读取、跑商流程和疲劳恢复仍需要更多账号与模拟器环境验证。

## 主要变化

- 重构跑商配置界面，支持自动规划、手动规划路线。
- 接入了与雷索纳斯bot类似的商品、疲劳、声望与综合参考利润计算。
- 支持账号配置读取：智能读取货舱容量、城市声望、城市开放状态和商品未解锁状态并持续更新。
- 增加实时运行状态显示：可以显示当前路线、书量、抬砍、疲劳、利润。并合并了执行和停止按钮。
- 引入 GitHub Releases 自动更新。
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

## 反馈

请前往 [Issues](https://github.com/DaiMao204/NightChainsTech/issues) 提交问题、截图、日志和复现步骤。

## 许可

本项目沿用原项目 MIT 许可。详见 [LICENSE](LICENSE)。
