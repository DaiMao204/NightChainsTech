"""
Author: Night-stars-1 nujj1042633805@gmail.com
Date: 2024-04-08 17:45:06
LastEditTime: 2024-04-28 19:00:55
LastEditors: Night-stars-1 nujj1042633805@gmail.com
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, RootModel


class RouteModel(BaseModel):
    """目标商品模型"""

    class GoodsData(BaseModel):
        """商品数据"""

        num: int = 0
        """数量"""
        buy_price: int = 0
        """购买价格"""
        sell_price: int = 0
        """出售价格"""
        profit: int = 0
        """利润"""

    buy_city_name: str = ""
    """购买城市"""
    sell_city_name: str = ""
    """出售城市"""
    haggle_num: int = 0
    """议价成功次数"""
    goods_data: Dict[str, GoodsData] = {}
    """商品数据"""
    buy_goods: Dict[str, int] = {}
    """待购商品列表"""
    buy_price: int = 0
    """总购价"""
    sell_price: int = 0
    """总售价"""
    cost: int = 0
    """含税买入成本"""
    income: int = 0
    """税后卖出收入"""
    profit: int = 0
    """总利润"""
    city_tired: int = 999
    """总疲劳"""
    city_tired_estimated: bool = False
    """总疲劳是否为估算值"""
    tired_profit: int = 0
    """单位利润"""
    book_profit: int = 0
    """单书利润"""
    general_profit_index: int = 0
    """综合参考利润"""
    book: int = -1
    """书"""
    num: int = 0
    last_not_wasting_restock: int = -1
    """总量"""


class RoutesModel(BaseModel):
    """路线模型集合"""

    city_data: List[RouteModel] = [RouteModel(), RouteModel()]
    profit: int = 0
    city_tired: int = 0
    tired_profit: int = 0
    book: int = -1
    general_profit_index: int = 0
    """综合参考利润"""
    jiaozi_profit: Optional[int] = None
    """武林源交子利润"""
    tiemeng_profit: Optional[int] = None
    """武林源铁盟币利润"""
    jiaozi_general_profit_index: Optional[int] = None
    """武林源交子综合参考利润"""
    tiemeng_general_profit_index: Optional[int] = None
    """武林源铁盟币综合参考利润"""
    strategy_label: str = ""
    """路线模型集合"""


class CityDataModel(BaseModel):
    """城市数据模型"""

    buy_num: float = 0.0
    """购买数量"""
    revenue: float = 0.0
    """税率"""


class SkillLevelModel(BaseModel):
    """技能等级模型"""

    星花: int = 0
    卡洛琳: int = 0
    伊尔: int = 0
    菲妮娅: int = 0
    叶珏: int = 0
    黛丝莉: int = 0
    阿知波: int = 0
    塞西尔: int = 0
    瓦伦汀: int = 0
    魇: int = 0
    奈弥: int = 0
    甘雅: int = 0
    艾略特: int = 0
    朱利安: int = 0
    瑞秋: int = 0
    山岚: int = 0
    卡莲: int = 0
    静流: int = 0
    雷火: int = 0
    狮鬃: int = 0
