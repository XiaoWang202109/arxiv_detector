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

def get_latest_title():
    try:
        response = requests.get(URL, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        header = soup.find("h3")
        return header.text.strip() if header else None
    except Exception as e:
        print("请求失败:", e)
        return None

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
    last_title = None

    print(f"[{datetime.now()}] 开始检测 arXiv 更新...")
    while (datetime.now() - start_time).seconds < RUN_LIMIT:
        title = get_latest_title()
        if title and title != last_title:
            last_title = title
            send_email("ArXiv cond-mat 有新更新！", f"新标题：{title}\n{URL}")
            return
        else:
            print(f"[{datetime.now()}] 无更新，等待下一次检查...")
            time.sleep(CHECK_INTERVAL)

    # 超时仍无更新
    send_email("ArXiv 检测结果", "截至 3 小时未检测到新更新。")

if __name__ == "__main__":
    main()
