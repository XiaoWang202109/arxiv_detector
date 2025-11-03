import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import time
import os

# ==== 用户设置 ====
URL = "https://arxiv.org/list/cond-mat/new"
CHECK_INTERVAL = 60 
RUN_LIMIT = 3 * 60 * 60  # 最多运行3小时
EMAIL_TO = os.environ.get("EMAIL_TO") 
EMAIL_FROM = os.environ.get("EMAIL_FROM")   #你的 QQ 邮箱账号，用来登录 SMTP
EMAIL_PASS = os.environ.get("EMAIL_PASS")
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465

def today_has_update():
    """检查网页是否有当天更新"""
    try:
        response = requests.get(URL, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        header = soup.find("h3")
        if not header:
            return False, None
        # header.text 示例: "Thu, 30 Oct 2025 (25 new submissions)"
        date_str = header.text.split("(")[0].strip()  # "Thu, 30 Oct 2025"
        header_date = datetime.strptime(date_str, "%a, %d %b %Y").date()
        today = datetime.now().date()
        return header_date == today, header.text.strip()
    except Exception as e:
        print("请求失败:", e)
        return False, None

def send_email(subject, content):
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(EMAIL_FROM, EMAIL_PASS)
        server.send_message(msg)
    print(f"邮件已发送：{subject}")

def main():
    start_time = datetime.now()
    already_sent = False

    print(f"[{datetime.now()}] 开始检测 arXiv 当天更新...")
    while (datetime.now() - start_time).seconds < RUN_LIMIT:
        has_update, header_text = today_has_update()
        if has_update and not already_sent:
            send_email("ArXiv cond-mat 当天有更新 ✅", f"更新标题: {header_text}\n{URL}")
            already_sent = True
            break
        else:
            print(f"[{datetime.now()}] 今日暂无更新，等待下一次检查...")
            time.sleep(CHECK_INTERVAL)

    if not already_sent:
        send_email("ArXiv 当天更新检测结果", "截至 3 小时未检测到今日更新。")

if __name__ == "__main__":
    main()
