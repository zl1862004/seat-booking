#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""河北北方学院 座位预约自动化 - GitHub Actions 版"""

import requests
import json
import time
import logging
from datetime import datetime, timedelta
from urllib.parse import quote

STU_ID = "2024506081"
STU_NAME = "张乐涵"
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

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Linux; Android 12; SM-G9980) AppleWebKit/537.36 MicroMessenger/8.0.38",
    "Referer": f"https://servicewechat.com/{APP_ID}/0/page-frame.html",
}
LOGIN_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "Mozilla/5.0 (Linux; Android 12; SM-G9980) AppleWebKit/537.36 MicroMessenger/8.0.38",
    "Referer": f"https://servicewechat.com/{APP_ID}/0/page-frame.html",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("SeatBooking")


class SeatBookingBot:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.token = None

    def login(self):
        log.info("登录获取 token...")
        try:
            data = f"action=bindWeChat&stuid={STU_ID}&stuname={quote(STU_NAME)}&openid=&unionid=&sk=undefined&version=2.0.4"
            r = self.session.post(LOGIN_URL, data=data, headers=LOGIN_HEADERS, timeout=10)
            result = r.json()
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
        log.info("获取未签到预约列表...")
        try:
            r = self.session.post(f"{API_BASE}/getApplyList",
                                  json={"stuId": STU_ID, "isSign": 0, "pageNum": 1, "pageSize": 10}, timeout=10)
            result = r.json()
            if result.get("code") == 20000:
                apply_list = result.get("resultData", {}).get("applyList", [])
                log.info(f"  未签到预约数: {len(apply_list)}")
                for item in apply_list:
                    log.info(f"    - applyId={item.get('applyId')}, "
                             f"{item.get('areaName', '')}({item.get('areaId', '')}) "
                             f"{item.get('seatId', '')} {item.get('timeName', '')} "
                             f"日期={item.get('applyDate', '')}")
                return apply_list
            return []
        except:
            return []

    def cancel_apply(self, apply_id):
        log.info(f"  取消预约 applyId={apply_id}")
        try:
            r = self.session.post(f"{API_BASE}/cancalSign",
                                  json={"stuId": STU_ID, "applyId": apply_id, "isSign": 0}, timeout=10)
            result = r.json()
            if result.get("code") == 20000 and result.get("status") == "success":
                log.info(f"    取消成功")
                return True
            log.warning(f"    取消失败: {result.get('message', '')}")
            return False
        except:
            return False

    def auto_cancel_expired(self):
        log.info("检查过期预约...")
        items = self.get_apply_list()
        if not items:
            log.info("  无未签到预约，无需清理")
            return 0
        today = datetime.now().strftime("%Y-%m-%d")
        c = 0
        for i in items:
            d = i.get("applyDate", "")
            t = i.get("applyTime", 0)
            exp = False
            if d < today:
                exp = True
            elif d == today and datetime.now().hour >= TIME_END.get(t, 0):
                exp = True
            if exp:
                log.info(f"  发现过期预约: {d} {i.get('timeName', '')} {i.get('seatId', '')}")
                if self.cancel_apply(i.get("applyId")):
                    c += 1
                time.sleep(0.3)
        if c:
            log.info(f"  已清理 {c} 条过期预约")
        return c

    def auto_cancel_if_exceeded(self):
        items = self.get_apply_list()
        if not items:
            return True
        today = datetime.now().strftime("%Y-%m-%d")
        expired = [i for i in items
                   if i.get("applyDate", "") < today
                   or (i.get("applyDate", "") == today
                       and datetime.now().hour >= TIME_END.get(i.get("applyTime", 0), 0))]
        valid = [i for i in items if i not in expired]
        log.info(f"  预约分析: 已过期={len(expired)}条, 仍有效={len(valid)}条")
        c = 0
        for i in expired:
            if self.cancel_apply(i.get("applyId")):
                c += 1
            time.sleep(0.3)
        if len(valid) < 2:
            log.info(f"  有效预约 {len(valid)} 条，还有名额")
            return True
        log.warning(f"  有效预约达上限 {len(valid)} 条!")
        # 优先保留目标时段+目标座位
        def score(i):
            s = 0
            if i.get("applyTime") == TARGET_TIME_ID:
                s += 100
            if i.get("seatId") == f"{TARGET_AREA_ID}-{TARGET_SEAT_NO}":
                s += 50
            return s
        valid.sort(key=score, reverse=True)
        log.warning(f"  保留: {valid[0].get('applyDate', '')} {valid[0].get('timeName', '')} {valid[0].get('seatId', '')}")
        for i in valid[1:]:
            if self.cancel_apply(i.get("applyId")):
                c += 1
            time.sleep(0.3)
        if c:
            log.info(f"  共清理 {c} 条预约")
        return c > 0

    def init_config(self):
        log.info(f"获取配置... (预约日期: {self.tomorrow})")
        try:
            r = self.session.post(f"{API_BASE}/init", json={}, timeout=10)
            result = r.json()
            if result.get("code") == 20000:
                data = result.get("resultData", {})
                dates = data.get("enableApplyDate", [])
                log.info(f"  可预约日期: {dates}")
                if self.tomorrow not in dates:
                    log.warning(f"  明天({self.tomorrow})不在可预约日期中!")
                    if dates:
                        self.tomorrow = dates[0]
                        log.info(f"  改为预约: {self.tomorrow}")
                return data
            return None
        except:
            return None

    def post_apply(self, area_id, time_id, seat_no=None):
        sid = f"{area_id}-{seat_no}" if seat_no else ""
        data = {
            "areaId": area_id, "applyDate": self.tomorrow, "applyTime": time_id,
            "seatId": sid, "stuId": STU_ID, "stuName": STU_NAME,
            "token": self.token or "", "isSign": 0, "isCheck": 0, "isApplyd": 1, "version": 0,
        }
        log.info(f"提交预约: 区域={area_id}, 日期={self.tomorrow}, 时段={time_id}, 座位={sid or '自动'}")
        try:
            r = self.session.post(f"{API_BASE}/postApply", json=data, timeout=10)
            result = r.json()
            if result.get("code") == 20000 and result.get("status") == "success":
                log.info(f"  预约成功! {result.get('message', '')}")
                return "success"
            msg = result.get("message", result.get("errMsg", "未知错误"))
            log.warning(f"  预约失败: {msg}")
            if "未签到预约不能超过两个" in msg:
                return "limit_exceeded"
            if "已被预约" in msg:
                return "seat_taken"
            return "fail"
        except Exception as e:
            log.error(f"  预约异常: {e}")
            return "error"

    def run(self):
        log.info("=" * 50)
        log.info("座位预约机器人启动 (GitHub Actions)")
        log.info(f"目标: 国交楼{TARGET_AREA_ID}-{TARGET_SEAT_NO}座 20:00-22:00")
        log.info(f"预约日期: {self.tomorrow}")
        log.info("=" * 50)

        if not self.login():
            return False
        self.auto_cancel_expired()
        if len(self.get_apply_list()) >= 2:
            self.auto_cancel_if_exceeded()
        if not self.init_config():
            return False

        # 首选: 目标座位+时段
        r = self.post_apply(TARGET_AREA_ID, TARGET_TIME_ID, TARGET_SEAT_NO)
        if r == "success":
            return True
        if r == "limit_exceeded":
            self.auto_cancel_if_exceeded()
            r = self.post_apply(TARGET_AREA_ID, TARGET_TIME_ID, TARGET_SEAT_NO)
            if r == "success":
                return True
            if r == "limit_exceeded":
                log.error("自动清理后仍超限，请手动取消")
                return False

        # 备选1: 同区域同时段换座位
        for seat in FALLBACK_SEATS:
            r = self.post_apply(TARGET_AREA_ID, TARGET_TIME_ID, seat)
            if r == "success":
                return True
            if r == "limit_exceeded":
                return False
            time.sleep(0.5)

        # 备选2: 同区域不同时段
        for tid in FALLBACK_TIMES:
            r = self.post_apply(TARGET_AREA_ID, tid, TARGET_SEAT_NO)
            if r == "success":
                return True
            if r == "limit_exceeded":
                return False
            time.sleep(0.5)

        # 备选3: 其他区域目标时段
        for aid in FALLBACK_AREAS:
            r = self.post_apply(aid, TARGET_TIME_ID)
            if r == "success":
                return True
            if r == "limit_exceeded":
                return False
            time.sleep(0.5)

        log.error("所有尝试均失败!")
        return False


if __name__ == "__main__":
    success = False
    for attempt in range(1, MAX_RETRIES + 1):
        log.info(f"第 {attempt}/{MAX_RETRIES} 次尝试")
        bot = SeatBookingBot()
        if bot.run():
            success = True
            log.info("预约成功!")
            break
        elif attempt < MAX_RETRIES:
            time.sleep(RETRY_INTERVAL)
        else:
            log.error("达到最大重试次数，预约失败。")

    # GitHub Actions 用退出码表示成功/失败
    # 0=成功, 1=失败 (会触发邮件通知)
    exit(0 if success else 1)
