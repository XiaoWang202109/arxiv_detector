import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import time
import os

# ==== 用户设置 ====
URL = "https://arxiv.org/list/cond-mat/new"
CHECK_INTERVAL = 120 
RUN_LIMIT = 6 * 60 * 60  # 最多运行6小时
EMAIL_FROM = os.environ.get("EMAIL_FROM")   #你的 QQ 邮箱账号，用来登录 SMTP
EMAIL_PASS = os.environ.get("EMAIL_PASS")
EMAIL_TO = os.environ.get("EMAIL_TO")
EMAIL_TO_2 = os.environ.get("EMAIL_TO_CRK")
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
EMAIL_TO_LIST = [EMAIL_TO,EMAIL_TO_2]
print(f"当前系统时间（UTC）: {datetime.utcnow()}  => 北京时间: {datetime.now()}")
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
    if not EMAIL_TO_LIST:
        print("没有有效的收件人邮箱，跳过发送邮件。")
        return
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(EMAIL_TO_LIST)
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_FROM, EMAIL_PASS)
            server.sendmail(EMAIL_FROM, EMAIL_TO_LIST, msg.as_string())
        print(f"邮件已发送：{subject}，收件人：{EMAIL_TO_LIST}")
    except Exception as e:
        print("发送邮件失败:", e)

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
