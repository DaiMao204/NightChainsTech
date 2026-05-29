# 跑商路线规划接入记录

## 计算口径

当前规划器已按 `resonance-columba-bot` 的 OneGraph 跑商逻辑重写：

- 从实时行情接口读取 `server_trade`。
- 使用 columba-bot 的静态商品数据决定商品购买城市、基础购买量、商品类型、城市从属、满声望税率、角色共振、事件加成。
- 单程先按单件利润排序，再按指定进货书数量把货仓填满。
- 往返路线枚举“总进货书”在去程和回程之间的分配，选总利润最高的分配。
- 排序默认使用 bot 的综合参考利润：

```text
综合参考利润 = round(总利润 / (总疲劳 + 总进货书 * 33))
```

## 数据文件

- `resources/goods/ColumbaTradeData2026.json`
  - 由 `tools/import_columba_trade_data.py` 从本地 columba-bot 的 `src/data` 导出。
  - 包含 21 个城市、229 个商品、声望、角色共振和事件数据。
- `resources/goods/CityFatigueData2026.json`
  - 由 `tools/import_columba_fatigue.py` 从 columba-bot 的 `fatigue.ts` 导出。
  - 路线疲劳优先使用该表，缺失时才退回地图坐标估算。

## 常用命令

重新导入 columba 商品/角色/声望数据：

```powershell
.\.venv\Scripts\python.exe tools\import_columba_trade_data.py
```

重新导入 columba 城市疲劳表，并生成离线基准行情资源：

```powershell
.\.venv\Scripts\python.exe tools\import_columba_fatigue.py
.\.venv\Scripts\python.exe tools\build_columba_local_market_data.py
```

使用实时 API 干跑最高综合参考利润路线：

```powershell
.\.venv\Scripts\python.exe tools\plan_business_routes.py --api-url https://reso-online-ddos.soli-reso.com/get_server_trade/ --top 5 --strategy general_profit_index --max-restock 4
```

实时 API 默认启用本地缓存，缓存位置为 `cache/market/`。同一接口 300 秒内会直接复用上次返回的数据，避免超过接口的 5 分钟请求限制。需要主动刷新时使用 `--refresh-cache`；临时禁用缓存时使用 `--no-cache`；调整缓存有效期可用 `--cache-ttl 秒数`。如果实时请求失败但本地存在旧缓存，规划器会自动使用旧缓存兜底。

不接 API 时无法得到当前商品波动价格，因此不能计算真实最佳路线。`resources/goods/ColumbaLocalMarketData2026.json` 只保存 columba-bot 的静态基准买卖价，供离线冒烟和公式对照使用；需要显式传入 `--use-local-baseline` 才会启用，且不能配合 `--execute` 真实跑商。

离线检查静态基准公式是否还能跑通：

```powershell
.\.venv\Scripts\python.exe tools\plan_business_routes.py --use-local-baseline --top 3
```

只计算将要执行的第一名路线，不点击游戏：

```powershell
.\.venv\Scripts\python.exe tools\run_planned_business.py --api-url https://reso-online-ddos.soli-reso.com/get_server_trade/ --max-restock 4
```

真正执行自动跑商时才加 `--execute`：

```powershell
.\.venv\Scripts\python.exe tools\run_planned_business.py --api-url https://reso-online-ddos.soli-reso.com/get_server_trade/ --max-restock 4 --execute
```

## 参数方向

- `--max-goods-num`：货舱容量，不传时使用 columba-bot `BotConfig.maxLot`，当前为 `1136`。
- `--max-restock`：本轮往返总进货书数量，不传时使用 columba-bot `BotConfig.onegraph.maxRestock`，当前为 `4`。
- `--strategy`：支持 `general_profit_index`、`profit`、`tired_profit`、`book_profit`。
- `--include-city` / `--exclude-city`：限制路线只包含或排除某些城市。
- 默认同时比较“全抬砍”和“回程不抬砍”，可用 `--no-compare-no-return-bargain` 关闭。
- 商品过滤：
  - `--locked-good 家用机器人`：视为未解锁，不参与计算。
  - `--blocked-good 商品名`：临时屏蔽商品。
  - `--allowed-good 商品名`：只允许这些商品参与计算。
- 玩家参数覆盖：
  - `--role 朱利安=4`：覆盖成员共振等级。
  - `--disable-role 朱利安`：禁用某个成员带来的加成。
  - `--prestige 修格里城=20`：覆盖城市声望等级。
  - `--event 红茶战争=false`：覆盖事件开关。
- 默认会使用 columba-bot 的 `BotConfig.productUnlockStatus`，例如 `家用机器人` 默认不可用；可用 `--no-default-product-locks` 忽略这份默认解锁表。

## 本项目用户配置

自动选线入口会读取两层配置：

- `config/app.json` 中的 `TradePlanner` 段，给 UI 使用。
- `config/trade_planner.json`，给高级用户直接编辑和分享自己的跑商配置；如果在 `TradePlanner.ConfigPath` 里填了其他路径，则优先读取该路径。

可以从 [trade_planner.example.json](trade_planner.example.json) 复制一份作为模板。没有配置文件时使用以下默认值：

```json
{
  "TradePlanner": {
    "MaxLot": 1136,
    "MaxRestock": 4,
    "BargainPercent": 20,
    "RaisePercent": 20,
    "BargainFatigue": 20,
    "RaiseFatigue": 20,
    "CompareNoReturnBargain": true,
    "DefaultPrestigeLevel": 20,
    "PrestigeByCity": {},
    "RoleResonance": {},
    "DisabledRoles": [],
    "ProductUnlockStatus": {
      "家用机器人": false
    },
    "BlockedGoods": [],
    "AllowedGoods": [],
    "Events": {
      "红茶战争": {
        "activated": false
      }
    },
    "IncludeCities": [],
    "ExcludeCities": [],
    "AllowedCityPairs": [],
    "BlockedCityPairs": []
  }
}
```

`RoleResonance` 为空时会从 columba-bot 默认角色配置开始计算；只填某个角色时表示覆盖这个角色等级。`ProductUnlockStatus` 也同理，只需要写和默认值不同的商品。

城市对限制：

- `AllowedCityPairs` 非空时，只会在这些城市对之间选线。
- `BlockedCityPairs` 用于排除指定城市对。
- 城市对是往返路线，`武林源-贡露城` 和 `贡露城-武林源` 等价。
- 支持 `A-B`、`A->B`、`A<->B`、`A,B` 写法。

干跑指定城市对：

```powershell
.\.venv\Scripts\python.exe tools\plan_business_routes.py --api-url https://reso-online-ddos.soli-reso.com/get_server_trade/ --allowed-pair 武林源-贡露城 --top 3
```

使用自定义配置文件：

```powershell
.\.venv\Scripts\python.exe tools\plan_business_routes.py --api-url https://reso-online-ddos.soli-reso.com/get_server_trade/ --planner-config docs\trade_planner.example.json --top 3
```

## 自动化衔接

规划器输出仍然是项目原有的 `RoutesModel`，所以执行层继续复用 `auto.run_business.main.run(routes)`。每条腿的 `book` 会使用 OneGraph 算出的进货书分配，`goods_data` 的顺序就是购买优先级。
