from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Literal

import cv2 as cv
from loguru import logger

from core.control.control import input_tap, restart_game_app, screenshot_image
from core.image.image import Image
from core.image.ocr import predict
from core.utils.utils import RESOURCES_PATH, ROOT_PATH


class PageKind(str, Enum):
    UNKNOWN = "unknown"
    START_SCREEN = "start_screen"
    MAIN_MAP = "main_map"
    CITY = "city"
    BUSINESS_MENU = "business_menu"
    BUY_PAGE = "buy_page"
    SELL_PAGE = "sell_page"
    STRENGTH_PAGE = "strength_page"
    BENTO_CABINET = "bento_cabinet"
    BUY_REPORT = "buy_report"
    SELL_REPORT = "sell_report"
    GENERIC_POPUP = "generic_popup"
    STATION_MAP = "station_map"
    ROUTE = "route"
    ROUTE_EVENT = "route_event"
    FIGHT = "fight"
    FIGHT_END = "fight_end"


@dataclass
class PageState:
    kind: PageKind
    confidence: float
    reason: str
    suggested_action: str
    matched_texts: list[str]
    texts: list[str]
    scores: dict[str, float]

    def is_one_of(self, *kinds: PageKind) -> bool:
        return self.kind in kinds


@dataclass
class RecoveryResult:
    before: PageState
    after: PageState
    recovered: bool
    action: str
    steps: int


@dataclass
class RouteActionResult:
    state: PageState
    handled: bool
    action: str
    should_wait_fight: bool = False


PAGE_STATE_DIR = ROOT_PATH / "diagnostics" / "page_state"

START_SCREEN_TEXTS = ("点击屏幕进入游戏", "点击任意位置进入游戏", "下载已经完成")

CITY_TEXTS = ("城市发展度", "声望等级", "隶属于")
BUSINESS_MENU_TEXTS = ("我要买", "我要卖")
BUY_PAGE_TEXTS = ("预计买入", "全部买入", "全部取消")
SELL_PAGE_TEXTS = ("预计卖出", "全部卖出", "全部出售", "全部取消")
STRENGTH_PAGE_TEXTS = ("FATIGUE", "恢复疲劳", "疲劳值", "列车长疲劳值", "提神", "口香糖", "仙人掌", "桦石", "补充")
BENTO_CABINET_TEXTS = ("BENTOCABINET", "BOXMEAL", "工作餐", "全部使用", "爱心便当")
BUY_REPORT_TEXTS = ("买入结算报告", "触碰空白区域退出")
SELL_REPORT_TEXTS = ("卖出结算报告", "出售结算报告", "触碰空白区域退出")
GENERIC_POPUP_TEXTS = (
    "触碰空白区域退出",
    "每日签到奖励",
    "累计登录",
    "生日快乐",
    "获取途径",
    "拥有数量",
)
STATION_MAP_TEXTS = ("前往目的地", "设为目的地", "选择目的地")
ROUTE_TEXTS = ("目的地", "剩余行程", "巡航")
ROUTE_EVENT_TEXTS = ("护卫队迎击", "敌方等级", "应对方式", "请选择")
FIGHT_TEXTS = ("自动战斗", "战斗", "撤退")

GENERIC_POPUP_FUZZY_TEXTS = ("空白区域退出",)

BUY_REPORT_CLOSE_POINT = (100, 100)
SELL_REPORT_CLOSE_POINT = (896, 676)
GENERIC_POPUP_CLOSE_POINTS = ((50, 360), (1230, 360), (640, 700), (100, 100), (1200, 700), (640, 40))
START_SCREEN_ENTER_POINT = (640, 360)
FIGHT_END_CLOSE_POINT = (1151, 626)
TRADE_PAGE_BACK_POINT = (83, 36)
TRADE_SWITCH_CROP_POS1 = (0, 560)
TRADE_SWITCH_CROP_POS2 = (260, 710)
TRADE_SWITCH_FALLBACK_POINTS = {
    PageKind.BUY_PAGE: (103, 654),
    PageKind.SELL_PAGE: (103, 654),
}
ROUTE_EVENT_ATTACK_POINT = (1009, 251)
FIGHT_AUTO_POINT = (159, 44)
FIGHT_START_CROP_POS1 = (1133, 132)
FIGHT_START_CROP_POS2 = (1268, 610)
FIGHT_START_TEMPLATE_THRESHOLD = 0.93
BUSINESS_OPTION_BY_TARGET = {
    PageKind.BUY_PAGE: "我要买",
    PageKind.SELL_PAGE: "我要卖",
}

ROUTE_STATUS_CROP_POS1 = (520, 20)
ROUTE_STATUS_CROP_POS2 = (760, 145)
ROUTE_EVENT_CROP_POS1 = (850, 210)
ROUTE_EVENT_CROP_POS2 = (1235, 620)


def _safe_label(label: str) -> str:
    label = re.sub(r"[^0-9A-Za-z_.-]+", "_", label.strip())
    return label.strip("_") or "page_state"


def _raw_image(image: Any | None = None):
    if image is None:
        return screenshot_image()
    if hasattr(image, "image"):
        return image.image
    return image


def _ocr_items(
    raw,
    cropped_pos1: tuple[int, int] = (0, 0),
    cropped_pos2: tuple[int, int] = (0, 0),
) -> list[dict[str, Any]]:
    try:
        return predict(raw, cropped_pos1=cropped_pos1, cropped_pos2=cropped_pos2)
    except Exception as exc:
        logger.debug(f"页面状态OCR失败: {exc}")
        return []


def _ocr_texts(
    raw,
    cropped_pos1: tuple[int, int] = (0, 0),
    cropped_pos2: tuple[int, int] = (0, 0),
) -> list[str]:
    return [
        item.get("text", "").replace(" ", "")
        for item in _ocr_items(raw, cropped_pos1=cropped_pos1, cropped_pos2=cropped_pos2)
    ]


def _matched(texts: list[str], needles: tuple[str, ...]) -> list[str]:
    return [needle for needle in needles if any(needle in text for text in texts)]


def _template_score(
    raw,
    template: Path,
    threshold: float,
    cropped_pos1: tuple[int, int] = (0, 0),
    cropped_pos2: tuple[int, int] = (0, 0),
) -> float:
    try:
        image = Image(raw.copy())
        if cropped_pos1 != (0, 0) or cropped_pos2 != (0, 0):
            image.crop_image(cropped_pos1, cropped_pos2)
        result = image.match_template(template, threshold)
        return float(result.score) if result else 0.0
    except Exception as exc:
        logger.debug(f"页面状态模板匹配失败: {template} {exc}")
        return 0.0


def _score_from_matches(matches: list[str], base: float = 0.72, step: float = 0.08) -> float:
    if not matches:
        return 0.0
    return min(0.98, base + step * len(matches))


def classify_page(image: Any | None = None) -> PageState:
    raw = _raw_image(image)
    texts = _ocr_texts(raw)
    route_texts = _ocr_texts(raw, ROUTE_STATUS_CROP_POS1, ROUTE_STATUS_CROP_POS2)
    event_texts = _ocr_texts(raw, ROUTE_EVENT_CROP_POS1, ROUTE_EVENT_CROP_POS2)
    all_texts = texts + route_texts + event_texts

    candidates: list[tuple[PageKind, float, str, str, list[str]]] = []
    scores: dict[str, float] = {}

    def add(
        kind: PageKind,
        score: float,
        reason: str,
        suggested_action: str,
        matches: list[str] | None = None,
    ):
        if score <= 0:
            return
        scores[kind.value] = max(scores.get(kind.value, 0.0), round(score, 4))
        candidates.append((kind, score, reason, suggested_action, matches or []))

    main_score = _template_score(raw, RESOURCES_PATH / "main_map.png", 0.96)
    add(PageKind.MAIN_MAP, main_score, "matched main_map template", "open target function from main map")

    city_score = _template_score(raw, RESOURCES_PATH / "fame.png", 0.95, (25, 634), (99, 707))
    add(PageKind.CITY, city_score, "matched city fame template", "open required city outlet")
    city_matches = _matched(all_texts, CITY_TEXTS)
    add(
        PageKind.CITY,
        _score_from_matches(city_matches, 0.84),
        f"matched OCR texts: {city_matches}",
        "open required city outlet",
        city_matches,
    )

    fight_end_score = _template_score(
        raw,
        RESOURCES_PATH / "fight" / "end_fight.png",
        0.98,
        (1137, 566),
        (1224, 652),
    )
    add(PageKind.FIGHT_END, fight_end_score, "matched fight end button", "tap fight end button")

    start_matches = _matched(all_texts, START_SCREEN_TEXTS)
    add(
        PageKind.START_SCREEN,
        _score_from_matches(start_matches, 0.86),
        f"matched OCR texts: {start_matches}",
        "tap screen to enter game",
        start_matches,
    )

    buy_matches = _matched(all_texts, BUY_PAGE_TEXTS)
    sell_matches = _matched(all_texts, SELL_PAGE_TEXTS)
    bento_matches = _matched(all_texts, BENTO_CABINET_TEXTS)
    if bento_matches:
        add(
            PageKind.BENTO_CABINET,
            _score_from_matches(bento_matches, 0.86),
            f"matched OCR texts: {bento_matches}",
            "return from bento cabinet",
            bento_matches,
        )

    strength_matches = _matched(all_texts, STRENGTH_PAGE_TEXTS)
    if strength_matches and not bento_matches:
        add(
            PageKind.STRENGTH_PAGE,
            _score_from_matches(strength_matches, 0.76),
            f"matched OCR texts: {strength_matches}",
            "return from strength page",
            strength_matches,
        )

    buy_report_matches = _matched(all_texts, BUY_REPORT_TEXTS)
    if "买入结算报告" in buy_report_matches:
        add(
            PageKind.BUY_REPORT,
            _score_from_matches(buy_report_matches, 0.88),
            f"matched OCR texts: {buy_report_matches}",
            "tap blank area to close buy report",
            buy_report_matches,
        )

    sell_report_matches = _matched(all_texts, SELL_REPORT_TEXTS)
    if any(text in sell_report_matches for text in ("卖出结算报告", "出售结算报告")):
        add(
            PageKind.SELL_REPORT,
            _score_from_matches(sell_report_matches, 0.88),
            f"matched OCR texts: {sell_report_matches}",
            "tap blank area to close sell report",
            sell_report_matches,
        )

    generic_popup_matches = _matched(all_texts, GENERIC_POPUP_TEXTS)
    generic_popup_matches += [
        needle
        for needle in GENERIC_POPUP_FUZZY_TEXTS
        if needle not in generic_popup_matches and any(needle in text for text in all_texts)
    ]
    if (
        generic_popup_matches
        and not strength_matches
        and not bento_matches
        and "买入结算报告" not in buy_report_matches
        and not any(text in sell_report_matches for text in ("卖出结算报告", "出售结算报告"))
    ):
        add(
            PageKind.GENERIC_POPUP,
            _score_from_matches(generic_popup_matches, 0.86),
            f"matched OCR texts: {generic_popup_matches}",
            "tap blank area to close popup",
            generic_popup_matches,
        )

    for kind, needles, base, action in (
        (PageKind.ROUTE_EVENT, ROUTE_EVENT_TEXTS, 0.84, "handle route event or fight"),
        (PageKind.BUY_PAGE, BUY_PAGE_TEXTS, 0.74, "continue buy flow"),
        (PageKind.SELL_PAGE, SELL_PAGE_TEXTS, 0.74, "continue sell flow"),
        (PageKind.BUSINESS_MENU, BUSINESS_MENU_TEXTS, 0.72, "choose buy or sell option"),
        (PageKind.STATION_MAP, STATION_MAP_TEXTS, 0.78, "select station or click travel"),
        (PageKind.ROUTE, ROUTE_TEXTS, 0.80, "wait route and monitor events"),
        (PageKind.FIGHT, FIGHT_TEXTS, 0.70, "wait fight or enable auto battle"),
    ):
        haystack = event_texts if kind == PageKind.ROUTE_EVENT else all_texts
        matches = _matched(haystack, needles)
        if kind == PageKind.BUSINESS_MENU and (buy_matches or sell_matches):
            continue
        add(kind, _score_from_matches(matches, base), f"matched OCR texts: {matches}", action, matches)

    if not candidates:
        return PageState(
            kind=PageKind.UNKNOWN,
            confidence=0.0,
            reason="no known page feature matched",
            suggested_action="capture state and return to main map if safe",
            matched_texts=[],
            texts=texts,
            scores=scores,
        )

    priority = {
        PageKind.FIGHT_END: 100,
        PageKind.BUY_REPORT: 95,
        PageKind.SELL_REPORT: 95,
        PageKind.GENERIC_POPUP: 94,
        PageKind.START_SCREEN: 92,
        PageKind.ROUTE_EVENT: 90,
        PageKind.BUY_PAGE: 80,
        PageKind.SELL_PAGE: 80,
        PageKind.BUSINESS_MENU: 70,
        PageKind.BENTO_CABINET: 68,
        PageKind.STRENGTH_PAGE: 67,
        PageKind.STATION_MAP: 65,
        PageKind.ROUTE: 60,
        PageKind.FIGHT: 55,
        PageKind.CITY: 50,
        PageKind.MAIN_MAP: 45,
        PageKind.UNKNOWN: 0,
    }
    candidates.sort(key=lambda item: (round(item[1], 4), priority[item[0]]), reverse=True)
    kind, score, reason, action, matches = candidates[0]
    return PageState(
        kind=kind,
        confidence=round(score, 4),
        reason=reason,
        suggested_action=action,
        matched_texts=matches,
        texts=texts,
        scores=scores,
    )


def capture_page_state(
    label: str,
    image: Any | None = None,
    *,
    extra: dict[str, Any] | None = None,
) -> PageState:
    raw = _raw_image(image)
    state = classify_page(raw)
    PAGE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{time.strftime('%Y%m%d_%H%M%S')}_{_safe_label(label)}"
    image_path = PAGE_STATE_DIR / f"{stem}.png"
    json_path = PAGE_STATE_DIR / f"{stem}.json"
    cv.imwrite(str(image_path), raw)
    data = {
        "label": label,
        "image": str(image_path.resolve()),
        "state": asdict(state),
        "extra": _json_safe(extra or {}),
    }
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.warning(
        f"页面状态: {state.kind.value} confidence={state.confidence} "
        f"action={state.suggested_action} image={image_path.resolve()}"
    )
    return state


def _normalize_targets(target: PageKind | Iterable[PageKind] | None) -> tuple[PageKind, ...]:
    if target is None:
        return ()
    if isinstance(target, PageKind):
        return (target,)
    return tuple(target)


def _is_target_state(state: PageState, target: PageKind | Iterable[PageKind] | None) -> bool:
    targets = _normalize_targets(target)
    if not targets:
        return state.kind != PageKind.UNKNOWN
    return state.kind in targets


def _target_name(target: PageKind | Iterable[PageKind] | None) -> str | None:
    targets = _normalize_targets(target)
    if not targets:
        return None
    if len(targets) == 1:
        return targets[0].value
    return ",".join(kind.value for kind in targets)


def _tap_ocr_text(
    text: str,
    image: Any | None = None,
    cropped_pos1: tuple[int, int] = (0, 0),
    cropped_pos2: tuple[int, int] = (0, 0),
) -> bool:
    raw = _raw_image(image)
    for item in _ocr_items(raw, cropped_pos1, cropped_pos2):
        item_text = item.get("text", "").replace(" ", "")
        if text not in item_text:
            continue
        position = item["position"]
        center_x = int((position[0][0] + position[2][0]) / 2)
        center_y = int((position[0][1] + position[2][1]) / 2)
        input_tap((center_x, center_y))
        return True
    return False


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _tap_trade_switch_option(target_kind: PageKind) -> bool:
    option_text = BUSINESS_OPTION_BY_TARGET[target_kind]
    if _tap_ocr_text(option_text, cropped_pos1=TRADE_SWITCH_CROP_POS1, cropped_pos2=TRADE_SWITCH_CROP_POS2):
        return True
    if _tap_ocr_text(option_text):
        return True
    point = TRADE_SWITCH_FALLBACK_POINTS.get(target_kind)
    if not point:
        return False
    input_tap(point)
    return True


def find_route_event_attack_point(image: Any | None = None) -> tuple[int, int] | None:
    raw = _raw_image(image)
    saw_event_panel = False
    for item in _ocr_items(raw, ROUTE_EVENT_CROP_POS1, ROUTE_EVENT_CROP_POS2):
        text = item.get("text", "").replace(" ", "")
        if any(keyword in text for keyword in ROUTE_EVENT_TEXTS[:1]):
            position = item["position"]
            return (
                int((position[0][0] + position[2][0]) / 2),
                int((position[0][1] + position[2][1]) / 2),
            )
        if any(keyword in text for keyword in ROUTE_EVENT_TEXTS[1:]):
            saw_event_panel = True
    if saw_event_panel:
        return ROUTE_EVENT_ATTACK_POINT
    return None


def tap_route_event_attack(image: Any | None = None) -> bool:
    point = find_route_event_attack_point(image)
    if not point:
        return False
    input_tap(point)
    return True


def tap_fight_start_button(image: Any | None = None) -> bool:
    raw = _raw_image(image)
    try:
        cropped = Image(raw.copy())
        cropped.crop_image(FIGHT_START_CROP_POS1, FIGHT_START_CROP_POS2)
        result = cropped.match_template(
            RESOURCES_PATH / "fight" / "start_fight.png",
            FIGHT_START_TEMPLATE_THRESHOLD,
        )
    except Exception as exc:
        logger.debug(f"战斗开始按钮模板匹配失败: {exc}")
        return False
    if not result:
        return False
    input_tap(result.loc)
    return True


def close_fight_end(image: Any | None = None) -> bool:
    state = classify_page(image)
    if state.kind != PageKind.FIGHT_END:
        return False
    input_tap(FIGHT_END_CLOSE_POINT)
    time.sleep(1.0)
    return True


def close_generic_popup(image: Any | None = None) -> bool:
    state = classify_page(image)
    if state.kind != PageKind.GENERIC_POPUP:
        return False
    for point in GENERIC_POPUP_CLOSE_POINTS:
        input_tap(point)
        time.sleep(0.8)
        if classify_page().kind != PageKind.GENERIC_POPUP:
            return True
    return False


def tap_start_screen(image: Any | None = None) -> bool:
    state = classify_page(image)
    if state.kind != PageKind.START_SCREEN:
        return False
    input_tap(START_SCREEN_ENTER_POINT)
    time.sleep(2.0)
    return True


def enable_auto_fight(image: Any | None = None) -> bool:
    state = classify_page(image)
    if state.kind != PageKind.FIGHT:
        return False
    input_tap(FIGHT_AUTO_POINT)
    time.sleep(0.5)
    return True


def start_route_fight(
    attack_point: tuple[int, int] | None = None,
    *,
    label: str = "start_route_fight",
    max_attempts: int = 3,
) -> RouteActionResult:
    actions: list[str] = []
    if attack_point:
        input_tap(attack_point)
        actions.append("tap_route_attack_point")
    elif tap_route_event_attack():
        actions.append("tap_route_event_attack")
    else:
        state = capture_page_state(f"{label}_attack_missing")
        return RouteActionResult(state, False, "none")

    time.sleep(1.0)
    for attempt in range(1, max_attempts + 1):
        image = screenshot_image()
        if tap_fight_start_button(image):
            actions.append("tap_fight_start")
            state = wait_for_page_state(
                (PageKind.FIGHT, PageKind.FIGHT_END, PageKind.ROUTE),
                timeout=2.0,
                interval=0.5,
            )
            should_wait_fight = state.kind not in (PageKind.FIGHT_END, PageKind.ROUTE)
            return RouteActionResult(
                state,
                True,
                " -> ".join(actions),
                should_wait_fight=should_wait_fight,
            )

        state = classify_page(image)
        if state.kind in (PageKind.FIGHT, PageKind.FIGHT_END, PageKind.ROUTE):
            return RouteActionResult(
                state,
                True,
                " -> ".join(actions) or "none",
                should_wait_fight=state.kind == PageKind.FIGHT,
            )
        time.sleep(1.0)

    state = capture_page_state(
        f"{label}_start_missing",
        extra={"attempts": max_attempts, "actions": actions},
    )
    return RouteActionResult(state, False, " -> ".join(actions) or "none")


def wait_for_page_state(
    target: PageKind | Iterable[PageKind],
    *,
    timeout: float = 3.0,
    interval: float = 0.5,
    label: str | None = None,
) -> PageState:
    """Poll until the current page matches one of the requested states."""
    end = time.perf_counter() + timeout
    state = classify_page()
    while True:
        if _is_target_state(state, target):
            return state
        if time.perf_counter() >= end:
            if label:
                capture_page_state(
                    label,
                    extra={
                        "target": _target_name(target),
                        "actual": state.kind.value,
                        "confidence": state.confidence,
                    },
                )
            return state
        time.sleep(interval)
        state = classify_page()


def restart_game_to_main(
    *,
    label: str = "restart_game_to_main",
    timeout: float = 90.0,
    interval: float = 2.0,
) -> RecoveryResult:
    """Restart the game and settle on the main map when possible."""
    before = classify_page()
    actions = ["restart_game_app"]
    restart_game_app(launch_wait=6.0)

    deadline = time.perf_counter() + timeout
    state = classify_page()
    while True:
        if state.kind == PageKind.MAIN_MAP:
            return RecoveryResult(before, state, True, " -> ".join(actions), len(actions))
        if time.perf_counter() >= deadline:
            capture_page_state(
                f"{label}_timeout",
                extra={
                    "actions": actions,
                    "final_kind": state.kind.value,
                    "final_confidence": state.confidence,
                },
            )
            return RecoveryResult(before, state, False, " -> ".join(actions), len(actions))

        if state.kind == PageKind.START_SCREEN:
            tap_start_screen()
            actions.append("tap_start_screen")
            time.sleep(5.0)
        elif state.kind == PageKind.GENERIC_POPUP:
            close_generic_popup()
            actions.append("close_generic_popup")
            time.sleep(1.5)
        else:
            time.sleep(interval)
        state = classify_page()


def recover_trade_page(
    action: Literal["buy", "sell"],
    *,
    label: str = "recover_trade_page",
    max_steps: int = 4,
    capture_on_blocked: bool = True,
) -> RecoveryResult:
    target = PageKind.BUY_PAGE if action == "buy" else PageKind.SELL_PAGE
    return recover_page_state(
        target,
        label=label,
        max_steps=max_steps,
        capture_on_blocked=capture_on_blocked,
    )


def recover_route_state(
    target: PageKind | Iterable[PageKind] | None = None,
    *,
    label: str = "recover_route_state",
    max_steps: int = 3,
    capture_on_blocked: bool = True,
) -> RecoveryResult:
    """Handle deterministic route/fight transient pages.

    This does not wait for an entire fight to finish. If it reaches an active
    fight page, the caller should continue fight monitoring.
    """
    if target is None:
        target = (PageKind.ROUTE, PageKind.MAIN_MAP, PageKind.CITY, PageKind.BUSINESS_MENU)

    before = classify_page()
    state = before
    actions: list[str] = []
    last_step = 0
    auto_fight_clicked = False

    for step in range(max_steps + 1):
        last_step = step
        if _is_target_state(state, target):
            return RecoveryResult(before, state, True, " -> ".join(actions) or "none", step)
        if step >= max_steps:
            break

        if state.kind == PageKind.ROUTE_EVENT:
            result = start_route_fight(label=f"{label}_event")
            actions.append(result.action)
            state = result.state
        elif state.kind == PageKind.FIGHT_END:
            close_fight_end()
            actions.append("close_fight_end")
            time.sleep(0.8)
            state = classify_page()
        elif state.kind == PageKind.GENERIC_POPUP:
            close_generic_popup()
            actions.append("close_generic_popup")
            time.sleep(0.8)
            state = classify_page()
        elif state.kind == PageKind.START_SCREEN:
            tap_start_screen()
            actions.append("tap_start_screen")
            time.sleep(2.0)
            state = classify_page()
        elif state.kind == PageKind.FIGHT and not auto_fight_clicked:
            if enable_auto_fight():
                actions.append("enable_auto_fight")
                auto_fight_clicked = True
                time.sleep(1.0)
                state = classify_page()
            else:
                break
        else:
            if capture_on_blocked:
                capture_page_state(
                    f"{label}_manual_intervention",
                    extra={
                        "target": _target_name(target),
                        "kind": state.kind.value,
                        "suggested_action": state.suggested_action,
                    },
                )
            break

    return RecoveryResult(
        before,
        state,
        _is_target_state(state, target),
        " -> ".join(actions) or "none",
        last_step,
    )


def recover_page_state(
    target: PageKind | Iterable[PageKind] | None = None,
    *,
    label: str = "recover",
    max_steps: int = 3,
    allow_go_home: bool = False,
    capture_on_blocked: bool = True,
) -> RecoveryResult:
    """Conservatively recover from well-known transient pages.

    This helper intentionally avoids solving every state. It only performs
    deterministic actions that are safe across the current automation flow.
    """
    before = classify_page()
    state = before
    actions: list[str] = []
    target_kinds = _normalize_targets(target)
    last_step = 0

    for step in range(max_steps + 1):
        last_step = step
        if _is_target_state(state, target):
            return RecoveryResult(before, state, True, " -> ".join(actions) or "none", step)
        if step >= max_steps:
            break

        if state.confidence < 0.70:
            if capture_on_blocked:
                capture_page_state(f"{label}_unknown", extra={"target": _target_name(target)})
            break

        if state.kind == PageKind.BUY_REPORT:
            actions.append("close_buy_report")
            input_tap(BUY_REPORT_CLOSE_POINT)
            time.sleep(0.8)
        elif state.kind == PageKind.SELL_REPORT:
            actions.append("close_sell_report")
            input_tap(SELL_REPORT_CLOSE_POINT)
            time.sleep(0.8)
        elif state.kind == PageKind.GENERIC_POPUP:
            actions.append("close_generic_popup")
            close_generic_popup()
            time.sleep(0.8)
        elif state.kind == PageKind.START_SCREEN:
            actions.append("tap_start_screen")
            tap_start_screen()
            time.sleep(2.0)
        elif state.kind == PageKind.FIGHT_END:
            actions.append("close_fight_end")
            input_tap(FIGHT_END_CLOSE_POINT)
            time.sleep(1.2)
        elif state.kind in (PageKind.BENTO_CABINET, PageKind.STRENGTH_PAGE):
            actions.append(f"back_from_{state.kind.value}")
            input_tap(TRADE_PAGE_BACK_POINT)
            time.sleep(1.0)
        elif len(target_kinds) == 1 and target_kinds[0] in BUSINESS_OPTION_BY_TARGET:
            target_kind = target_kinds[0]
            if state.kind == PageKind.BUSINESS_MENU:
                option_text = BUSINESS_OPTION_BY_TARGET[target_kind]
                if not _tap_ocr_text(option_text):
                    if capture_on_blocked:
                        capture_page_state(
                            f"{label}_business_option_missing",
                            extra={"target": target_kind.value, "option": option_text},
                        )
                    break
                actions.append(f"open_{target_kind.value}")
                time.sleep(1.0)
            elif state.kind in (PageKind.BUY_PAGE, PageKind.SELL_PAGE):
                if _tap_trade_switch_option(target_kind):
                    actions.append(f"switch_to_{target_kind.value}")
                    time.sleep(1.0)
                else:
                    actions.append("back_to_business_menu")
                    input_tap(TRADE_PAGE_BACK_POINT)
                    time.sleep(0.8)
            else:
                if capture_on_blocked:
                    capture_page_state(
                        f"{label}_manual_intervention",
                        extra={
                            "target": _target_name(target),
                            "kind": state.kind.value,
                            "suggested_action": state.suggested_action,
                        },
                    )
                break
        elif allow_go_home and target_kinds == (PageKind.MAIN_MAP,):
            actions.append("go_home")
            from core.preset.control import go_home

            go_home()
            time.sleep(0.5)
        else:
            if capture_on_blocked:
                capture_page_state(
                    f"{label}_manual_intervention",
                    extra={
                        "target": _target_name(target),
                        "kind": state.kind.value,
                        "suggested_action": state.suggested_action,
                    },
                )
            break
        state = classify_page()

    return RecoveryResult(
        before,
        state,
        _is_target_state(state, target),
        " -> ".join(actions) or "none",
        last_step,
    )
