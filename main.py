#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""河北北方学院 座位预约自动化 - 极速秒发版（无第三方依赖）

核心优化：提前登录+清理 → sleep到00:00:00 → 只发postApply
零点到预约请求仅需1-2秒（旧版需12秒）
"""

import json, time, logging, os, sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

BEIJING_TZ = timezone(timedelta(hours=8))

STU_ID = os.environ.get("STU_ID", "")
STU_NAME = os.environ.get("STU_NAME", "")
API_BASE = "https://bfxyrun.hebeinu.edu.cn/wxseat/spaceReservation"
LOGIN_URL = "https://bfxyrun.hebeinu.edu.cn/__WeChat_API__/"
APP_ID = "wx92e7591b4f77803d"
TARGET_AREA_ID = "10F"
TARGET_TIME_ID = 7
TARGET_SEAT_NO = "24"
FALLBACK_SEATS = ["26", "27"]
FALLBACK_AREAS = ["09F", "11F", "07F", "12F", "13F"]
FALLBACK_TIMES = [6, 5, 4, 3, 2, 1]
MAX_RETRIES = 3
RETRY_INTERVAL = 2
TIME_END = {1: 10, 2: 12, 3: 14, 4: 16, 5: 18, 6: 20, 7: 22}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("SeatBooking")


def now_beijing():
    """获取当前北京时间（无论服务器在哪个时区）"""
    return datetime.now(BEIJING_TZ)


def http_post(url, data=None, json_data=None, headers=None, timeout=10):
    """轻量 HTTP POST，无第三方依赖"""
    if json_data is not None:
        body = json.dumps(json_data).encode()
        h = {"Content-Type": "application/json"}
    elif data is not None:
        body = data.encode() if isinstance(data, str) else data
        h = {"Content-Type": "application/x-www-form-urlencoded"}
    else:
        body = b""
        h = {}
    h.update({"User-Agent": "Mozilla/5.0 (Linux; Android 12) MicroMessenger/8.0.38",
              "Referer": f"https://servicewechat.com/{APP_ID}/0/page-frame.html"})
    if headers:
        h.update(headers)
    req = Request(url, data=body, headers=h, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


class SeatBookingBot:
    def __init__(self):
        self.tomorrow = (now_beijing() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.token = None

    def login(self):
        log.info("登录...")
        try:
            data = f"action=bindWeChat&stuid={STU_ID}&stuname={quote(STU_NAME)}&openid=&unionid=&sk=undefined&version=2.0.4"
            result = http_post(LOGIN_URL, data=data)
            if result.get("status") == "success":
                self.token = result.get("token", "")
                log.info(f"  登录成功! Token: {self.token}")
                return True
            log.error(f"  登录失败: {result}")
            return False
        except Exception as e:
            log.error(f"  登录异常: {e}")
            return False

    def get_apply_list(self):
        try:
            result = http_post(f"{API_BASE}/getApplyList",
                              json_data={"stuId": STU_ID, "isSign": 0, "pageNum": 1, "pageSize": 10})
            if result.get("code") == 20000:
                return result.get("resultData", {}).get("applyList", [])
        except:
            pass
        return []

    def cancel_apply(self, apply_id):
        log.info(f"  取消预约 applyId={apply_id}")
        try:
            result = http_post(f"{API_BASE}/cancalSign",
                              json_data={"stuId": STU_ID, "applyId": apply_id, "isSign": 0})
            ok = result.get("code") == 20000 and result.get("status") == "success"
            if ok:
                log.info(f"    取消成功")
            return ok
        except:
            return False

    def auto_cancel_expired(self):
        log.info("检查过期预约...")
        items = self.get_apply_list()
        if not items:
            return 0
        today = now_beijing().strftime("%Y-%m-%d")
        c = 0
        for i in items:
            d = i.get("applyDate", "")
            t = i.get("applyTime", 0)
            exp = d < today or (d == today and now_beijing().hour >= TIME_END.get(t, 0))
            if exp:
                log.info(f"  过期: {d} {i.get('timeName','')} {i.get('seatId','')}")
                if self.cancel_apply(i.get("applyId")):
                    c += 1
                time.sleep(0.3)
        if c:
            log.info(f"  已清理 {c} 条过期预约")
        return c

    def auto_cancel_if_exceeded(self):
        """清理过期预约，有效预约绝不自动删除"""
        items = self.get_apply_list()
        if not items:
            return True
        today = now_beijing().strftime("%Y-%m-%d")
        expired = [i for i in items
                   if i.get("applyDate", "") < today
                   or (i.get("applyDate", "") == today
                       and now_beijing().hour >= TIME_END.get(i.get("applyTime", 0), 0))]
        valid = [i for i in items if i not in expired]
        c = 0
        for i in expired:
            if self.cancel_apply(i.get("applyId")):
                c += 1
            time.sleep(0.3)
        if c:
            log.info(f"  已清理 {c} 条过期预约")
        if len(valid) >= 2:
            log.warning(f"有效预约已达上限({len(valid)}条)，请手动去小程序取消")
            for v in valid:
                log.warning(f"  有效预约: {v.get('applyDate')} {v.get('timeName')} {v.get('seatId')}")
            return False
        return True

    def init_config(self):
        try:
            result = http_post(f"{API_BASE}/init", json_data={})
            if result.get("code") == 20000:
                dates = result.get("resultData", {}).get("enableApplyDate", [])
                if self.tomorrow not in dates and dates:
                    log.warning(f"  {self.tomorrow}不可约，改为 {dates[0]}")
                    self.tomorrow = dates[0]
                return True
        except:
            pass
        return False

    def post_apply(self, area_id, time_id, seat_no=None):
        sid = f"{area_id}-{seat_no}" if seat_no else ""
        data = {"areaId": area_id, "applyDate": self.tomorrow, "applyTime": time_id,
                "seatId": sid, "stuId": STU_ID, "stuName": STU_NAME,
                "token": self.token or "", "isSign": 0, "isCheck": 0, "isApplyd": 1, "version": 0}
        log.info(f"提交: {area_id} {self.tomorrow} 时段{time_id} {sid or '自动'}")
        try:
            result = http_post(f"{API_BASE}/postApply", json_data=data)
            if result.get("code") == 20000 and result.get("status") == "success":
                log.info(f"  ✅ 预约成功!")
                return "success"
            msg = result.get("message", "")
            log.warning(f"  ❌ {msg}")
            if "未签到预约不能超过两个" in msg:
                return "limit_exceeded"
            if "已被预约" in msg:
                return "seat_taken"
            return "fail"
        except Exception as e:
            log.error(f"  异常: {e}")
            return "error"

    def already_booked_tomorrow(self):
        """检查明天是否已有预约，避免重复请求触发风控"""
        items = self.get_apply_list()
        for i in items:
            if i.get("applyDate") == self.tomorrow:
                log.info(f"明天({self.tomorrow})已有预约: {i.get('seatId')} {i.get('timeName')}，跳过")
                return True
        return False

    def pre_login(self):
        """提前完成登录、查列表、清理过期、init——零点前全部做完
        注意：already_booked_tomorrow 检查移到 fire 阶段，因为零点后 tomorrow 会变"""
        log.info(f"=== 目标: {TARGET_AREA_ID}-{TARGET_SEAT_NO} 20:00-22:00 ===")
        if not self.login():
            return False
        # 提前清理过期预约
        self.auto_cancel_expired()
        # 提前获取可预约日期
        if not self.init_config():
            return False
        log.info("⏳ 预处理完成，等待零点秒发...")
        return True

    def fire(self):
        """零点瞬间只发预约请求，不再登录/查列表"""
        r = self.post_apply(TARGET_AREA_ID, TARGET_TIME_ID, TARGET_SEAT_NO)
        if r == "success": return True
        if r == "limit_exceeded":
            if self.auto_cancel_if_exceeded():
                r = self.post_apply(TARGET_AREA_ID, TARGET_TIME_ID, TARGET_SEAT_NO)
                if r == "success": return True
            if r == "limit_exceeded":
                log.error("有效预约已满2条，请手动去小程序取消")
                return False

        for seat in FALLBACK_SEATS:
            r = self.post_apply(TARGET_AREA_ID, TARGET_TIME_ID, seat)
            if r == "success": return True
            if r == "limit_exceeded": return False
            time.sleep(0.3)

        for aid in FALLBACK_AREAS:
            r = self.post_apply(aid, TARGET_TIME_ID)
            if r == "success": return True
            if r == "limit_exceeded": return False
            time.sleep(0.3)

        for tid in FALLBACK_TIMES:
            r = self.post_apply(TARGET_AREA_ID, tid, TARGET_SEAT_NO)
            if r == "success": return True
            if r == "limit_exceeded": return False
            time.sleep(0.3)

        log.error("所有尝试均失败!")
        return False


def wait_until_midnight():
    """等到北京时间00:00:00，精度10ms"""
    now = now_beijing()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    diff = (midnight - now).total_seconds()

    if diff <= 0:
        log.info("已过零点，立即执行")
        return False  # 不需要等

    if diff > 600:
        log.info(f"距零点还有 {diff/60:.1f} 分钟，直接执行(不等待)")
        return False

    # 10分钟以内，等待
    log.info(f"距零点还有 {diff:.1f} 秒，等待中...")
    if diff > 2:
        time.sleep(diff - 1.5)
    # 最后1.5秒忙等
    while True:
        remaining = (midnight - now_beijing()).total_seconds()
        if remaining <= 0:
            break
        time.sleep(0.01)
    log.info(f"⏰ 零点到达! 当前时间: {now_beijing().strftime('%H:%M:%S.%f')}")
    return True


if __name__ == "__main__":
    # ===== 极速秒发流程 =====
    # 1. 提前登录+清理（零点前做完）
    bot = SeatBookingBot()
    pre = bot.pre_login()

    if not pre:
        log.error("预处理失败，退出")
        exit(1)

    # 2. 等零点
    waited = wait_until_midnight()

    # 3. 零点瞬间只发预约请求
    if waited:
        # 等过零点了，tomorrow 需要重新计算
        bot.tomorrow = (now_beijing() + timedelta(days=1)).strftime("%Y-%m-%d")
        log.info(f"零点后重新计算日期: {bot.tomorrow}")
    else:
        # 非零点模式（备份/GitHub cron延迟触发）：先检查是否已有预约
        if bot.already_booked_tomorrow():
            exit(0)

    success = bot.fire()
    if not success:
        # 重试：重新登录+发请求
        for attempt in range(1, MAX_RETRIES + 1):
            log.info(f"重试 {attempt}/{MAX_RETRIES}")
            bot2 = SeatBookingBot()
            if bot2.pre_login() is True:
                if not waited and bot2.already_booked_tomorrow():
                    success = True
                    break
                if bot2.fire():
                    success = True
                    break
            time.sleep(RETRY_INTERVAL)

    log.info("预约成功!" if success else "预约失败。")
    exit(0 if success else 1)
