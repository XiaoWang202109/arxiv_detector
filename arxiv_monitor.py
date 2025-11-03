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
EMAIL_FROM = os.environ.get("EMAIL_FROM")   #你的 QQ 邮箱账号，用来登录 SMTP
EMAIL_PASS = os.environ.get("EMAIL_PASS")
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
EMAIL_TO_LIST = [
    os.environ.get("EMAIL_TO"),
    os.environ.get("EMAIL_TO_2")
]

def today_has_update():
    response = requests.get(URL)
    soup = BeautifulSoup(response.text, "html.parser")
    header = soup.find("h3")
    if not header:
        return False, None
    # header.text 示例: "Showing new listings for Monday, 3 November 2025"
    text = header.text.strip()
    try:
        date_str = text.replace("Showing new listings for ", "")  # "Monday, 3 November 2025"
        header_date = datetime.strptime(date_str, "%A, %d %B %Y").date()
        today = datetime.now().date()
        return header_date == today, text
    except Exception as e:
        print("日期解析失败:", e)
        return False, text

def send_email(subject, content):
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    valid_emails = [e for e in EMAIL_TO_LIST if isinstance(e, str) and e.strip()]
    if not valid_emails:
        print("No valid recipient email found, skipping send_email.")
        return
    msg["To"] = ", ".join(valid_emails)
    with smtplib.SMTP_SSL("smtp.qq.com", 465) as server:
         server.login(EMAIL_FROM, EMAIL_PASS)
         server.sendmail(EMAIL_FROM, EMAIL_TO_LIST, msg.as_string())
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
    print("EMAIL_TO_LIST:", EMAIL_TO_LIST)
