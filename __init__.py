# -*- coding: utf-8 -*-
"""
汽水音乐 · Android 自动化脚本（实机校准版）
=============================================
所有控件坐标与文案均来自 OPPO PGT110（1080x2520 / Android 16 / ColorOS 16）实机抓取。

已实机验证的完整闭环：
  播放页 点「免费听」  → 进广告
  → 广告页等倒计时结束，右上角变「领取成功」
  → 点「领取成功」 → 中央弹窗「今日免费听」+「领取奖励」
  → 点「领取奖励」 → 自动进下一个广告（回到上一步）

实机抓到的关键控件（物理坐标，1080x2520）：
  免费听      text="免费听"                      中心 (806, 1979)
  倒计时      desc="30秒后可领取奖励，关闭，按钮"   x776-1032 y120-216
  领取成功     desc="领取成功，关闭，按钮"          x776-1032 y120-216
  领取奖励     desc="领取奖励"                    中心 (540, 1342)
  坚持退出     desc="坚持退出"                    中心 (540, 1506)
  立即下载     ← 广告诱导按钮，绝对不能点

设计原则：
  1. 控件树优先（Android 无障碍能读到 WebView 的 content-desc）
  2. OCR 只在探针里抽查，主链路不依赖
  3. 绝不点「立即下载」——所有点击都来自精确控件坐标
  4. 有累计上限，不会无脑夜跑

AScript 工程约定：入口必须叫 __init__.py，主体代码写顶层，不写 if __name__ == "__main__"
"""

import os
import time
import random
import traceback

from ascript.android import action, system                      # type: ignore
from ascript.android.system import R                            # type: ignore
from ascript.android.node import Selector                       # type: ignore
# 注意：Ocr 不在这里导入。AScript 一旦在启动时看到 screen/Ocr 依赖，
# 就会立刻弹「录制或投放」的图色授权框，把无人值守流程挡在第一步。
# 主链路只用控件树，OCR 仅在 SELFTEST 探针里抽查，所以在 selftest() 内部再导入。


# ==================================================================
# 配置
# ==================================================================

PKG = "com.luna.music"

# Selector 的 text/desc 参数是「正则」，不是精确匹配
ENTRY_PATTERN = ".*免费听.*"          # 播放页入口（"免费听" / "免费听1天" 都能命中）
ENTRY_EXCLUDE = ("今日免费听", "会员")  # 排除同名的弹窗标题/底部 tab
REWARD_DESC = "领取奖励"              # 弹窗主按钮
EXIT_DESC = "坚持退出"                # 弹窗放弃按钮

CLAIM_DESC_KEY = "领取成功"           # 广告页右上角（desc 是拼接串，用 contains 匹配）
COUNTDOWN_DESC_KEY = "秒后可领取奖励"

ENTRY_TIMEOUT = 150                   # 等「免费听」出现的最长时间（含用户手动开 App 的时间）
MAX_IDLE_ROUNDS = 8                   # 连续空转多少轮判定额度用完

# ---- 交互界面（WebWindow）----
UI_PANEL = "panel.html"               # 对应工程内 res/ui/panel.html
UI_TARGET_DEFAULT = 10                # 界面无法显示时的兜底目标
UI_TARGET_MIN, UI_TARGET_MAX = 1, 60  # 目标天数允许范围
UI_WAIT_TIMEOUT = 300                 # 等用户在界面上操作的超时（秒）
SHOW_UI = True                        # False = 跳过界面，直接用兜底目标
CLAIM_WAIT = 45                       # 等广告倒计时结束（秒），广告一般 30s
REWARD_WAIT = 12                      # 等「领取奖励」弹窗出现（秒）
JITTER = (0.5, 1.5)                   # 轮间随机停顿

FALLBACK_SIZE = (1080, 2520)          # 实测机型分辨率，探测失败时兜底
CLAIM_CLICK_RATIO = 0.42              # 「领取成功」框内横向取点比例（避开右边的 ×）

SELFTEST = False


# ==================================================================
# 基础工具
# ==================================================================

# 运行日志落盘：手机端看不到控制台时，直接读这个文件就能复盘
# （也是电脑端调试的唯一可靠通道，WebSocket 日志时有时无）
#
# 路径不能写死：不同设备 / 是否开启「应用分身」下 user 目录不同
# （分身是 /storage/emulated/10，普通是 /storage/emulated/0）。
# 优先用 __file__ 反推脚本所在目录，失败再逐级兜底。
def _resolve_log_path():
    cands = []
    try:
        cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.log"))
    except Exception:
        pass
    cands += [
        "/sdcard/airscript/model/qishui/run.log",
        "/storage/emulated/0/airscript/model/qishui/run.log",
        "/storage/emulated/10/airscript/model/qishui/run.log",
    ]
    for p in cands:
        try:
            d = os.path.dirname(p)
            if not os.path.isdir(d):
                continue
            with open(p, "a", encoding="utf-8") as f:
                f.write("")
            return p
        except Exception:
            continue
    return cands[0] if cands else "run.log"


LOG_PATH = _resolve_log_path()


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
    except Exception:
        pass    # 日志写不进去不能影响主流程


_W, _H = 0, 0


def screen_size():
    global _W, _H
    if _W and _H:
        return _W, _H
    try:
        m = R.context.getResources().getDisplayMetrics()
        if int(m.widthPixels) > 0:
            _W, _H = int(m.widthPixels), int(m.heightPixels)
            return _W, _H
    except Exception as e:
        log(f"屏幕尺寸探测失败: {e}")
    _W, _H = FALLBACK_SIZE
    log(f"回退屏幕尺寸 {_W}x{_H}")
    return _W, _H


def node_bounds(node):
    """
    取控件矩形。AScript Android 的 rect 是 left/top/right/bottom，
    不是 iOS 那套 x1/y1/x2/y2 —— 写错会静默抛异常，导致所有控件被过滤。
    """
    if node is None:
        return None
    try:
        r = node.rect
        x1, y1 = int(r.left), int(r.top)
        x2, y2 = int(r.right), int(r.bottom)
        if x2 > x1 and y2 > y1:
            return x1, y1, x2, y2
    except Exception:
        pass
    # 降级：用中心点 + 尺寸反推
    try:
        cx, cy = int(node.center_x), int(node.center_y)
        w, h = int(node.rect.width()), int(node.rect.height())
        if w > 0 and h > 0:
            return cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2
    except Exception:
        pass
    return None


def node_center(node):
    if node is None:
        return None
    try:
        cx, cy = int(node.center_x), int(node.center_y)
        if cx > 0 or cy > 0:
            return cx, cy
    except Exception:
        pass
    b = node_bounds(node)
    if not b:
        return None
    x1, y1, x2, y2 = b
    return (x1 + x2) // 2, (y1 + y2) // 2


def find_node(text=None, desc=None, xpath=None):
    """按 text / content-desc / xpath 找控件，逐个尝试，命中即返回。"""
    if text:
        try:
            n = Selector().text(text).find()
            if n:
                return n
        except Exception:
            pass
    if desc:
        try:
            n = Selector().desc(desc).find()
            if n:
                return n
        except Exception:
            pass
    if xpath:
        try:
            n = Selector(xpath=xpath).find()
            if n:
                return n
        except Exception:
            pass
    return None


def desc_of(node):
    if node is None:
        return ""
    try:
        d = node.desc
        if d:
            return str(d)
    except Exception:
        pass
    try:
        return node.getAttr("content-desc") or ""
    except Exception:
        return ""


def text_of(node):
    if node is None:
        return ""
    try:
        return str(node.text or "")
    except Exception:
        return ""


def safe_click(x, y, label=""):
    try:
        log(f"  点击 [{label}] -> ({x},{y})")
        action.click(int(x), int(y))
        time.sleep(0.8)
        return True
    except Exception as e:
        log(f"  ✗ 点击失败 [{label}]: {e}")
        return False


def click_node(text=None, desc=None, xpath=None, label=""):
    n = find_node(text=text, desc=desc, xpath=xpath)
    c = node_center(n)
    if not c:
        return False
    return safe_click(c[0], c[1], label or text or desc or "xpath")


def visible_nodes(limit=50):
    out = []
    try:
        nodes = Selector().find_all() or []
    except Exception as e:
        log(f"  控件遍历失败: {e}")
        return out
    for n in nodes[:limit]:
        try:
            t = text_of(n).strip()
            d = desc_of(n).strip()
            c = node_center(n)
            if (t or d) and c:
                out.append((t, d, c))
        except Exception:
            continue
    return out


def brief_texts(limit=18):
    """当前界面在屏幕上显示的文字，用于诊断「找不到入口」时到底停在哪"""
    items = [f"{t}@{c}" for t, d, c in visible_nodes(60) if t][:limit]
    if not items:
        items = [f"desc:{d}@{c}" for t, d, c in visible_nodes(60) if d][:limit]
    return " | ".join(items) if items else "（读不到任何文字）"


def node_count():
    try:
        return len(Selector().find_all() or [])
    except Exception:
        return -1


# ==================================================================
# 广告页判定
# ==================================================================

def find_desc_contains(key, limit=80):
    """
    按 content-desc 包含关系找控件。
    广告页控件极少（实测 5 个左右），直接遍历比对比 XPath 更快更稳：
    XPath 每次都要全树匹配，广告页 WebView 高频刷新时会把 Python 进程拖垮。
    """
    try:
        for node in (Selector().find_all() or [])[:limit]:
            d = desc_of(node)
            if d and key in d:
                return node
    except Exception:
        pass
    return None


def scan_ad_state(limit=80):
    """
    一次遍历同时判断广告页状态，返回 (领取成功节点, 倒计时节点, 倒计时文本)。
    关键：每次轮询只做一次 find_all()。实测每秒 3~4 次全量扫描会让进程在
    广告页刷新期间异常退出（脚本跑约 50 秒就静默停止）。
    """
    claim = None
    cd_node = None
    try:
        nodes = Selector().find_all() or []
    except Exception:
        return None, None, ""

    for node in nodes[:limit]:
        d = desc_of(node)
        if not d:
            continue
        if claim is None and CLAIM_DESC_KEY in d:
            claim = node
        elif cd_node is None and COUNTDOWN_DESC_KEY in d:
            cd_node = node
        if claim is not None and cd_node is not None:
            break

    txt = desc_of(cd_node)[:24] if cd_node is not None else ""
    return claim, cd_node, txt


def find_claim_node():
    """右上角「领取成功」控件（desc 是拼接串，必须用包含匹配）"""
    return find_desc_contains(CLAIM_DESC_KEY)


def claim_ready():
    return find_claim_node() is not None


def find_countdown_node():
    return find_desc_contains(COUNTDOWN_DESC_KEY)


def on_ad_page():
    claim, cd_node, _ = scan_ad_state()
    return claim is not None or cd_node is not None


def countdown_text():
    _, _, txt = scan_ad_state()
    return txt


# ==================================================================
# 阶段一：启动
# ==================================================================

def init_env():
    w, h = screen_size()
    log(f"屏幕: {w}x{h}")
    try:
        name = system.get_app_name(PKG)
        log(f"目标应用: {name or '未安装'} ({PKG})")
        if not name:
            log("  ⚠️ 未检测到汽水音乐，请确认包名 com.luna.music")
    except Exception as e:
        log(f"包名查询异常: {e}")


def in_qishui():
    """
    判断当前是不是汽水音乐界面。
    三个判据，命中任一即可：
      1) 广告页（右上角倒计时/领取成功）—— 广告只可能来自汽水音乐
      2) 「第N天畅听」进度面板 —— 同上
      3) 底部 tab「听抖音 / 发现」—— 正常播放页的特征

    注意必须用 Selector().text() 直接查，不能遍历 find_all()：
    播放页有 228 个控件，底部 tab 排在 140 个之后，遍历会漏，
    结果就是「明明在前台却判定为不在」，白白等 20 秒再重拉一次。
    """
    if on_ad_page() or on_bonus_panel():
        return True
    for kw in ("听抖音", "发现"):
        try:
            if Selector().text(kw).find():
                return True
        except Exception:
            continue
    return False


def press_back():
    try:
        action.Key.back()
        time.sleep(0.9)
        return True
    except Exception as e:
        log(f"  返回键异常: {e}")
        return False


def on_bonus_panel():
    """「第N天畅听」进度面板：领取奖励后会不定期弹出，挡住播放页"""
    for key in (".*天畅听.*", ".*明日畅听.*"):
        try:
            if Selector().desc(key).find():
                return True
        except Exception:
            continue
    return False


def close_bonus_panel():
    if not on_bonus_panel():
        return False
    log("  ⏹ 检测到「第N天畅听」面板，按返回键关闭")
    press_back()
    time.sleep(1.0)
    if not on_bonus_panel():
        log("  ✓ 面板已关闭")
        return True
    log("  ⚠️ 面板仍在，稍后再试")
    return False


def start_app():
    """拉起汽水音乐。system.open 是本版唯一可用的启动方式（4.0.17 没有 ascript.android.app）。"""
    try:
        system.open(PKG)
        return True
    except Exception as e:
        log(f"  启动异常: {e}")
        return False


def launch_app():
    log("阶段一：启动汽水音乐")
    if in_qishui():
        log("  ✓ 已在前台，跳过启动")
        return True

    start_app()
    # 自动启动只给 8 秒机会，OPPO 拦得很快，多等没意义
    for _ in range(16):
        time.sleep(0.5)
        if in_qishui():
            log("  ✓ 已到汽水音乐")
            time.sleep(1.0)
            return True

    log("  ⚠️ 自动启动被系统拦截（OPPO 的「后台弹出界面」限制）")
    log("     👉 请手动点开汽水音乐，脚本会自动接管")
    log("     永久解决：设置 → 应用管理 → AScript → 权限 → 允许「后台弹出界面 / 关联启动」")

    # 给用户 40 秒手动打开的窗口期，期间一直盯着前台
    for _ in range(80):
        time.sleep(0.5)
        if in_qishui():
            log("  ✓ 已检测到汽水音乐，继续")
            time.sleep(1.0)
            return True

    log("  ⏱ 40 秒内没看到汽水音乐，转入入口轮询")
    return False


# ==================================================================
# 阶段二：点「免费听」进广告
# ==================================================================

def find_entry_node():
    """
    找播放页的「免费听」入口。
    text 约束传的是正则，"免费听" / "免费听1天" 都能命中；
    但要排除弹窗标题「今日免费听」和底部「会员」tab。
    """
    try:
        nodes = Selector().text(ENTRY_PATTERN).find_all() or []
    except Exception as e:
        log(f"  入口检索异常: {e}")
        return None

    for n in nodes:
        try:
            t = text_of(n).strip()
            if any(x in t for x in ENTRY_EXCLUDE):
                continue
            if node_bounds(n):
                return n
        except Exception:
            continue
    return None


def enter_ad(timeout=ENTRY_TIMEOUT):
    log(f"阶段二：进入广告（轮询上限 {timeout}s）")
    deadline = time.time() + timeout
    attempt = 0
    clicked = 0

    while time.time() < deadline:
        attempt += 1
        if on_ad_page():
            log("  ✓ 已在广告页")
            return True

        n = find_entry_node()
        if n:
            b = node_bounds(n)
            c = node_center(n)
            log(f"  第{attempt}次命中入口 text='{text_of(n).strip()}' rect={b} center={c}")
            if clicked >= 3:
                log("  已点击 3 次仍未进广告，停止重试")
                return False
            safe_click(c[0], c[1], "免费听入口")
            clicked += 1
            for _ in range(8):
                time.sleep(0.5)
                if on_ad_page():
                    log("  ✓ 已进入广告")
                    return True
            log("  点了但未进广告")
        else:
            if attempt in (1, 6):
                log(f"  第{attempt}次未找到入口 | 界面文字: {brief_texts()}")
            if attempt == 2:
                log("  💡 没检测到播放页：若汽水音乐还没打开，请手动点开它，脚本会自动接管")
            if attempt == 30:
                log("  💡 若今日还有额度，可在播放页手动点【免费听】进广告，脚本会自动接管")
            # 进度面板会挡住播放页，先关掉再找入口
            if on_bonus_panel():
                close_bonus_panel()
                continue
            # 每隔一段时间确认没被切走（广告跳应用商店、误触返回等）
            if attempt % 10 == 0 and not in_qishui():
                log("  已不在汽水音乐界面，重新拉起")
                start_app()
                time.sleep(3.0)

        time.sleep(1.2)

    log("  超时仍未进入广告")
    return False


# ==================================================================
# 阶段三：等广告倒计时结束（只检测不点击）
# ==================================================================

def wait_ad_finish(timeout=CLAIM_WAIT):
    log(f"阶段三：等待广告结束（上限 {timeout}s）")
    deadline = time.time() + timeout
    last_txt = None
    checks = 0
    while time.time() < deadline:
        checks += 1
        claim, cd_node, txt = scan_ad_state()

        if claim is not None:
            log(f"  ✓ 出现「领取成功」(第 {checks} 次轮询)")
            return True

        # 倒计时只每 5 次打一条，减少日志刷屏和通道压力
        if txt and txt != last_txt:
            if checks % 5 == 1:
                log(f"  倒计时: {txt}")
            last_txt = txt

        if checks > 8 and cd_node is None:
            log("  已离开广告页，本轮放弃")
            return False

        time.sleep(0.9)

    log(f"  超时 {timeout}s，未出现「领取成功」")
    return False


# ==================================================================
# 阶段四：两步领取
# ==================================================================

def click_claim_button():
    """
    点右上角「领取成功」。
    这个控件 desc 是「领取成功，关闭，按钮」，右侧约 1/3 是 × 关闭区，
    所以不能点中心（会关掉广告而不是领奖），要按比例往左取点。
    """
    n = find_claim_node()
    b = node_bounds(n)
    if not b:
        log("  找不到「领取成功」控件")
        return False
    x1, y1, x2, y2 = b
    cx = int(x1 + (x2 - x1) * CLAIM_CLICK_RATIO)
    cy = (y1 + y2) // 2
    log(f"  控件 x{x1}-{x2} y{y1}-{y2}，按 {CLAIM_CLICK_RATIO} 取点 ({cx},{cy})")
    return safe_click(cx, cy, "领取成功")


def click_reward_button():
    return click_node(desc=REWARD_DESC, label="领取奖励(弹窗)")


def claim_once():
    """点领取成功 → 等弹窗 → 点领取奖励。返回 1 成功 / 0 失败"""
    log("阶段四：领取奖励")
    if not click_claim_button():
        return 0

    log(f"  [2/2] 等待「领取奖励」弹窗（上限 {REWARD_WAIT}s）")
    deadline = time.time() + REWARD_WAIT
    tries = 0
    claimed = False

    while time.time() < deadline:
        tries += 1
        if click_reward_button():
            log("  ✓ 已点「领取奖励」")
            claimed = True
            break
        # 有时不弹常规弹窗，而是直接出「第N天畅听」进度面板 → 奖励同样到账
        if on_bonus_panel():
            log("  ✓ 出现「第N天畅听」面板 → 奖励已到账")
            claimed = True
            break
        if tries == 4:
            log("  弹窗未出现，补点一次「领取成功」")
            click_claim_button()
        time.sleep(0.7)

    if not claimed:
        if click_node(desc=EXIT_DESC, label="坚持退出(兜底)"):
            log("  点了「坚持退出」脱离卡死弹窗")
        log("  ✗ 本轮领取失败")
        return 0

    time.sleep(1.5)
    # 领取后可能弹进度面板，必须关掉才能回到播放页继续下一轮
    close_bonus_panel()
    return 1


# ==================================================================
# 阶段五：主循环
# ==================================================================

def run_loop(target=None):
    target = int(target or UI_TARGET_DEFAULT)
    log("#" * 56)
    log(f"核心循环：进广告 → 等倒计时 → 领取成功 → 领取奖励 → 下一轮")
    log(f"目标：{target} 天（连续空转 {MAX_IDLE_ROUNDS} 轮自动停止）")
    log("#" * 56)

    if not enter_ad():
        log("❌ 进不去广告：可能今日额度已领完，或当前不在播放页")
        log("   可手动点【免费听】进入广告后重跑，脚本会自动接管")
        return 0

    success = 0
    idle = 0
    rnd = 0

    while success < target:
        rnd += 1
        log(f"\n---- 第 {rnd} 轮（已成功 {success}/{target}）----")

        if not wait_ad_finish():
            idle += 1
            log(f"  本轮无广告（连续 {idle}/{MAX_IDLE_ROUNDS}）")
            if idle >= MAX_IDLE_ROUNDS:
                log("  连续多轮无广告 → 判定当日额度用完，退出")
                break
            if not on_ad_page():
                enter_ad()
            time.sleep(3)
            continue

        if claim_once() == 1:
            success += 1
            idle = 0
            log(f"  ✅ 累计成功 {success}/{target}")
        else:
            idle += 1
            log(f"  本轮失败（连续 {idle}/{MAX_IDLE_ROUNDS}）")
            if idle >= MAX_IDLE_ROUNDS:
                log("  连续失败过多，退出")
                break

        time.sleep(random.uniform(*JITTER))

    return success


# ==================================================================
# 探针模式（改 SELFTEST=True 运行，只读不点击）
# ==================================================================

def selftest():
    log("=" * 56)
    log("探针模式：只读，不点击")
    log("=" * 56)
    w, h = screen_size()
    log(f"屏幕 {w}x{h}")
    log(f"在广告页={on_ad_page()}  领取就绪={claim_ready()}  倒计时='{countdown_text()}'")
    log(f"「免费听」node: {node_bounds(find_entry_node())}  中心={node_center(find_entry_node())}")
    log(f"「领取奖励」中心: {node_center(find_node(desc=REWARD_DESC))}")
    log(f"「领取成功」框: {node_bounds(find_claim_node())}")
    log(f"界面控件总数: {node_count()}")

    log("\n--- 当前界面带文字的控件 ---")
    for t, d, c in visible_nodes(60):
        log(f"  @{c}  text='{t}'  desc='{d}'")

    log("\n--- OCR 兜底抽查（右上角）---")
    try:
        from ascript.android.screen import Ocr   # 延迟导入，避免主流程触发图色授权
        rect = [int(w * 0.70), int(h * 0.03), w, int(h * 0.10)]
        res = Ocr.paddleocr(rect=rect, pattern=r"领取|秒")
        if res:
            for r in res:
                log(f"  {getattr(r, 'text', r)} @({getattr(r, 'center_x', '?')},"
                    f"{getattr(r, 'center_y', '?')})")
        else:
            log("  （无结果）")
    except Exception as e:
        log(f"  OCR 异常: {e}")


# ==================================================================
# 交互界面：用 HTML 弹窗设置目标天数
# ==================================================================

def ask_target():
    """
    弹出配置界面，等用户设定目标天数。返回 >0 的目标；取消/超时返回 0。

    为什么不用 show(wait=True)：wait=True 是纯阻塞且没有超时参数，
    界面一旦异常（WebView 崩溃 / 资源缺失）脚本会永久卡死，只能强杀。
    这里改成非阻塞 show() + 主线程轮询，任何异常都能自己收场。
    """
    if not SHOW_UI:
        log(f"界面已跳过（SHOW_UI=False），使用默认目标 {UI_TARGET_DEFAULT} 天")
        return UI_TARGET_DEFAULT

    try:
        from ascript.android.ui import WebWindow
        w = WebWindow(R.ui(UI_PANEL))
    except Exception as e:
        log(f"⚠️ 配置界面不可用: {e}")
        log(f"   改用默认目标 {UI_TARGET_DEFAULT} 天")
        return UI_TARGET_DEFAULT

    state = {"target": 0, "cancel": False}

    # 透明底 + 居中卡片：圆角和背景交给 HTML 自己画，窗口只负责承载
    for fn, args in (("size", ("88vw", "44vh")),
                     ("background", ("#00000000",)),
                     ("dim_amount", (0.35,)),
                     ("gravity", (17,))):
        try:
            getattr(w, fn)(*args)
        except Exception as e:
            log(f"  界面样式 [{fn}] 设置失败（不影响使用）: {e}")

    try:
        @w.on("start")
        def _on_start(value):
            try:
                n = int(str(value).strip())
            except Exception:
                n = UI_TARGET_DEFAULT
            state["target"] = max(UI_TARGET_MIN, min(UI_TARGET_MAX, n))
            log(f"界面：设定目标 {state['target']} 天")

        @w.on("cancel")
        def _on_cancel(value):
            state["cancel"] = True
            log("界面：用户取消")
    except Exception as e:
        log(f"⚠️ 界面消息通道注册失败: {e}")
        log(f"   改用默认目标 {UI_TARGET_DEFAULT} 天")
        return UI_TARGET_DEFAULT

    try:
        w.show()
    except Exception as e:
        log(f"⚠️ 显示配置界面失败: {e}")
        log(f"   改用默认目标 {UI_TARGET_DEFAULT} 天")
        return UI_TARGET_DEFAULT

    log(f"已弹出配置界面，等待操作（上限 {UI_WAIT_TIMEOUT}s）")
    deadline = time.time() + UI_WAIT_TIMEOUT
    while time.time() < deadline:
        if state["target"] or state["cancel"]:
            break
        time.sleep(0.25)

    # 统一在 Python 主线程关闭窗口，不在 JS 回调里操作 UI
    try:
        w.close()
    except Exception:
        pass
    time.sleep(1.2)   # 等窗口真正消失，否则无障碍可能还读到弹窗内容

    if state["cancel"]:
        return 0
    if state["target"]:
        return state["target"]

    log("⏱ 界面超时未操作，已退出（避免无人确认时凭空白刷）")
    return 0


# ==================================================================
# 结果反馈窗
# ==================================================================

def show_result(total, target):
    """
    跑完后弹一个轻量结果窗。此时脚本已停止点击，窗口只负责展示，
    30 秒无操作自动关，不会一直挡着手机。
    """
    if not SHOW_UI:
        return
    try:
        from ascript.android.ui import WebWindow
        w = WebWindow(R.ui("result.html"))
        w.size("80vw", "32vh")
        w.background("#00000000")
        w.dim_amount(0.45)
        w.gravity(17)
    except Exception as e:
        log(f"  结果窗创建失败（不影响已领取的结果）: {e}")
        return

    state = {"ok": False}
    try:
        @w.on("ok")
        def _on_ok(value):
            state["ok"] = True
    except Exception:
        pass

    try:
        w.show()
    except Exception as e:
        log(f"  结果窗显示失败: {e}")
        return

    time.sleep(1.0)   # 等 HTML 加载完再把数据推给 JS
    try:
        w.call(f"setResult({int(total)},{int(target)})")
    except Exception as e:
        log(f"  结果数据推送失败: {e}")

    deadline = time.time() + 30
    while time.time() < deadline and not state["ok"]:
        time.sleep(0.25)

    try:
        w.close()
    except Exception:
        pass


# ==================================================================
# 入口
# ==================================================================

def main():
    log("")
    log("=" * 56)
    log(f"🎵 汽水音乐 Android 自动化 · {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 56)
    try:
        init_env()
        if SELFTEST:
            selftest()
            return

        target = ask_target()
        if target <= 0:
            log("已取消，未执行任何点击")
            return

        log(f"🎯 本次目标：{target} 天")
        launch_app()      # 失败也继续，enter_ad 里还有重试与重新拉起
        total = run_loop(target)

        log("=" * 56)
        log(f"✅ 结束：成功 {total}/{target} 次")
        if total < target:
            log("   未达标通常是今日额度领完，或连续空转触发了保护")
        show_result(total, target)
    except Exception as e:
        log(f"❌ 主流程异常: {e}")
        traceback.print_exc()
    finally:
        log("脚本退出")


main()
