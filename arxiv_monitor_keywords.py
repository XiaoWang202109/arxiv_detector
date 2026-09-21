import argparse
import copy
import html
import os
import re
import smtplib
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


# ==== 用户设置 ====
URL = "https://arxiv.org/list/cond-mat/new"
CHECK_INTERVAL = 120
RUN_LIMIT = 5 * 60 * 60 + 55 * 60  # 最多运行5小时55分钟，给最后发送提示邮件留缓冲

EMAIL_FROM = os.environ.get("EMAIL_FROM")  # 你的 QQ 邮箱账号，用来登录 SMTP
EMAIL_PASS = os.environ.get("EMAIL_PASS")
EMAIL_TO = os.environ.get("EMAIL_TO")
EMAIL_TO_2 = os.environ.get("EMAIL_TO_CRK")
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465

# 命中关键词的 PDF 会保存到这里。可通过环境变量 ARXIV_DOWNLOAD_DIR 修改。
DOWNLOAD_DIR = Path(
    os.environ.get(
        "ARXIV_DOWNLOAD_DIR",
        Path(__file__).resolve().parent / "downloads",
    )
)

# 之后想到新的关键词，直接追加到这个列表里即可。列表按首字母排序，方便查找。
KEYWORDS = [
    "Allan H. MacDonald",
    "Andrea F. Young",
    "Anlian Pan",
    "Brian D. Gerardot",
    "Brian D.Gerardot",
    "Chenhao Jin",
    "Chih-Kang Shih",
    "Chun Hung Lui",
    "Di Xiao",
    "Eric Anderson",
    "Erfu Liu",
    "Eslam Khalaf",
    "Feng Wang",
    "Fengcheng Wu",
    "Heonjoon Park",
    "Hongyi Yu",
    "Imamoglu",
    "Jiaqi Cai",
    "Jie Shan",
    "jie gu",
    "Jun Yan",
    "Kaifei Kang",
    "kenji",
    "Kenji Watanabe",
    "Kin Fai Mak",
    "Liang Fu",
    "Libai Huang",
    "Long Ju",
    "MacDonald",
    "moire",
    "MoS2",
    "MoSe2",
    "MoTe2",
    "Pablo Jarillo-Herrero",
    "Sufei Shi",
    "Takashi Taniguchi",
    "Yanhao Tang",
    "Ting Cao",
    "TingXin Li",
    "TMD",
    "Tony F. Heinz",
    "Weibo Gao",
    "WS2",
    "WSe2",
    "Xiaodong Xu",
    "Xiaoqin Li",
    "Xiaoxue Liu",
    "Xiaoyang Zhu",
    "Yao Wang",
    "Yimo Han",
    "YongTao Cui",
    "Yuanbo Zhang",
    "Ziliang Ye",
]


SUBSCRIPT_TRANSLATION = str.maketrans(
    {
        "₀": "0",
        "₁": "1",
        "₂": "2",
        "₃": "3",
        "₄": "4",
        "₅": "5",
        "₆": "6",
        "₇": "7",
        "₈": "8",
        "₉": "9",
        "⁰": "0",
        "¹": "1",
        "²": "2",
        "³": "3",
        "⁴": "4",
        "⁵": "5",
        "⁶": "6",
        "⁷": "7",
        "⁸": "8",
        "⁹": "9",
    }
)

SECTION_NAMES = {
    "new submissions": "New submissions",
    "cross submissions": "Cross submissions",
    "replacement submissions": "Replacement submissions",
}


@dataclass
class ArxivPaper:
    index: str
    arxiv_id: str
    title: str
    authors: str
    abstract_text: str
    abs_url: str
    pdf_url: str
    matched_keywords: list[str]
    download_path: str | None = None
    download_error: str | None = None


@dataclass
class ArxivSection:
    name: str
    heading: str
    total_entries: int
    shown_entries: int
    papers: list[ArxivPaper]


def fetch_soup() -> BeautifulSoup:
    response = requests.get(
        URL,
        timeout=30,
        headers={"User-Agent": "arxiv-cond-mat-monitor/2.0"},
    )
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def parse_header_date(header_text: str):
    date_str = header_text.replace("Showing new listings for ", "")
    return datetime.strptime(date_str, "%A, %d %B %Y").date()


def get_listing_header(soup: BeautifulSoup):
    for header in soup.find_all("h3"):
        text = header.get_text(" ", strip=True)
        if text.startswith("Showing new listings for "):
            return text
    return None


def get_today_update_status(soup: BeautifulSoup):
    header_text = get_listing_header(soup)
    if not header_text:
        return False, None

    try:
        header_date = parse_header_date(header_text)
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        return header_date == today, header_text
    except Exception as exc:
        print("日期解析失败:", exc)
        return False, header_text


def clean_label_text(text: str, label: str) -> str:
    text = " ".join(text.split())
    if text.lower().startswith(label.lower()):
        return text[len(label) :].strip()
    return text


def unique_keep_order(items: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        normalized = item.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def normalize_for_search(text: str) -> str:
    text = text.translate(SUBSCRIPT_TRANSLATION)
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def compact_formula_text(text: str) -> str:
    text = normalize_for_search(text)
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    text = re.sub(r"[\s_\$\{\}\^\(\)\[\],.;:~`'\"+-]+", "", text)
    return text


def find_keywords(search_text: str) -> list[str]:
    normalized_text = normalize_for_search(search_text)
    compact_text = compact_formula_text(search_text)

    matched = []
    for keyword in KEYWORDS:
        normalized_keyword = normalize_for_search(keyword)
        compact_keyword = compact_formula_text(keyword)
        is_formula_keyword = any(char.isdigit() for char in compact_keyword)
        if normalized_keyword in normalized_text or (
            is_formula_keyword and compact_keyword in compact_text
        ):
            matched.append(keyword)

    return unique_keep_order(matched)


def parse_section_counts(heading: str) -> tuple[int | None, int | None]:
    match = re.search(r"showing\s+(\d+)\s+of\s+(\d+)\s+entries", heading, re.IGNORECASE)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def parse_section_name(heading: str) -> str | None:
    lowered = heading.casefold()
    for key, name in SECTION_NAMES.items():
        if key in lowered:
            return name
    return None


def parse_papers_from_entries(entries) -> list[ArxivPaper]:
    papers = []
    seen_arxiv_ids = set()

    for dt, dd in entries:
        index_link = dt.find("a", href=False)
        index = index_link.get_text(" ", strip=True) if index_link else ""

        abs_link = dt.find("a", href=lambda href: href and href.startswith("/abs/"))
        if not abs_link:
            continue

        arxiv_id = abs_link.get_text(" ", strip=True).replace("arXiv:", "").strip()
        if not arxiv_id or arxiv_id in seen_arxiv_ids:
            continue
        seen_arxiv_ids.add(arxiv_id)

        title_tag = dd.find(class_="list-title")
        authors_tag = dd.find(class_="list-authors")

        title = clean_label_text(
            title_tag.get_text(" ", strip=True) if title_tag else "",
            "Title:",
        )
        authors = authors_tag.get_text(" ", strip=True) if authors_tag else ""

        dd_for_abstract = copy.deepcopy(dd)
        for tag in dd_for_abstract.find_all(
            class_=["list-title", "list-authors", "list-comments", "list-journal-ref", "list-subjects"]
        ):
            tag.extract()
        abstract_text = " ".join(dd_for_abstract.stripped_strings)

        search_text = f"{title}\n{authors}\n{abstract_text}"
        matched_keywords = find_keywords(search_text)

        papers.append(
            ArxivPaper(
                index=index,
                arxiv_id=arxiv_id,
                title=title,
                authors=authors,
                abstract_text=abstract_text,
                abs_url=urljoin(URL, f"/abs/{arxiv_id}"),
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}#zoom=200",
                matched_keywords=matched_keywords,
            )
        )

    return papers


def collect_section_entries(header) -> list[tuple]:
    entries = []
    current_dt = None
    node = header.find_next_sibling()

    while node:
        if node.name == "h3" and parse_section_name(node.get_text(" ", strip=True)):
            break

        if node.name == "dt":
            current_dt = node
        elif node.name == "dd" and current_dt is not None:
            entries.append((current_dt, node))
            current_dt = None

        node = node.find_next_sibling()

    return entries


def parse_sections(soup: BeautifulSoup) -> list[ArxivSection]:
    sections = []
    seen_section_names = set()

    for header in soup.find_all("h3"):
        heading = header.get_text(" ", strip=True)
        section_name = parse_section_name(heading)
        if not section_name or section_name in seen_section_names:
            continue

        entries = collect_section_entries(header)
        papers = parse_papers_from_entries(entries)
        shown_entries, total_entries = parse_section_counts(heading)

        sections.append(
            ArxivSection(
                name=section_name,
                heading=heading,
                shown_entries=shown_entries if shown_entries is not None else len(papers),
                total_entries=total_entries if total_entries is not None else len(papers),
                papers=papers,
            )
        )
        seen_section_names.add(section_name)

    return sections


def clean_pdf_title(title: str) -> str:
    """按 DownloadPaper3.1_gpt 的规则清理标题，使其可作 Windows 文件名。"""
    title = html.unescape(title)
    title = re.sub(r"&lt;.*?&gt;", "", title)
    title = re.sub(r"<[^>]*>", "", title)
    title = re.sub(r"\\(?:mathrm|ensuremath)", "", title)
    title = re.sub(r"(?:mathrm|ensuremath)", "", title)
    title = title.replace("$_", "").replace("}_", "")
    title = title.replace(r"\text{", "").replace("text{", "")
    title = title.replace("/", "-")
    title = re.sub(r"[$\{\}]", "", title)
    title = re.sub(r'[<>:"/\\|?*]', "", title)
    title = re.sub(r"[\x00-\x1f\x7f]", "", title)
    title = re.sub(r"\s+", " ", title).strip(" .")
    return title or "Untitled"


def normalize_paper_date(date_text: str) -> str:
    date_text = html.unescape(date_text).strip()
    match = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})", date_text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"

    for date_format in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(date_text, date_format).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return date_text.replace("/", "-")


def fetch_download_metadata(
    paper: ArxivPaper,
    session: requests.Session,
) -> tuple[str, str]:
    """读取参考脚本使用的 citation_title 和 citation_online_date。"""
    with session.get(paper.abs_url, timeout=30) as response:
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

    title_tag = soup.find("meta", attrs={"name": "citation_title"})
    title = title_tag.get("content", "").strip() if title_tag else ""
    title = title or paper.title

    date_text = ""
    for meta_name in ("citation_online_date", "citation_date"):
        date_tag = soup.find("meta", attrs={"name": meta_name})
        if date_tag and date_tag.get("content"):
            date_text = date_tag["content"]
            break

    if not date_text:
        submitted = soup.find(class_="submission-history")
        if submitted:
            match = re.search(
                r"Submitted\s+on\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
                submitted.get_text(" ", strip=True),
            )
            if match:
                date_text = match.group(1)

    if not date_text:
        # 元数据异常时仍给出稳定名称，至少保留 arXiv 编号中的年月。
        id_match = re.match(r"(\d{2})(\d{2})\.", paper.arxiv_id)
        date_text = f"20{id_match.group(1)}-{id_match.group(2)}" if id_match else "unknown-date"

    return clean_pdf_title(title), normalize_paper_date(date_text)


def make_pdf_filename(title: str, online_date: str) -> str:
    """生成“日期 - arXiv - 标题.pdf”，与参考脚本的 arXiv 规则一致。"""
    prefix = f"{online_date} - arXiv - "
    suffix = ".pdf"
    # 给 Windows 完整路径和临时文件扩展名留出余量。
    max_filename_length = 220
    max_title_length = max_filename_length - len(prefix) - len(suffix)
    safe_title = clean_pdf_title(title)[:max_title_length].rstrip(" .")
    return f"{prefix}{safe_title or 'Untitled'}{suffix}"


def download_paper(paper: ArxivPaper, session: requests.Session) -> Path:
    title, online_date = fetch_download_metadata(paper, session)
    destination = DOWNLOAD_DIR / make_pdf_filename(title, online_date)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    if destination.exists():
        print(f"PDF 已存在，跳过下载：{destination.name}")
        return destination

    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with session.get(
            paper.pdf_url.split("#", 1)[0],
            timeout=60,
            stream=True,
        ) as response:
            response.raise_for_status()
            with temporary.open("wb") as pdf_file:
                first_chunk = True
                for chunk in response.iter_content(chunk_size=1024 * 128):
                    if not chunk:
                        continue
                    if first_chunk and not chunk.lstrip().startswith(b"%PDF"):
                        raise ValueError("服务器返回的内容不是 PDF")
                    first_chunk = False
                    pdf_file.write(chunk)
                if first_chunk:
                    raise ValueError("服务器返回了空文件")
            temporary.replace(destination)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise

    print(f"PDF 下载完成：{destination}")
    return destination


def download_matched_papers(sections: list[ArxivSection]):
    matched_papers = [
        paper
        for section in sections
        for paper in section.papers
        if paper.matched_keywords
    ]
    if not matched_papers:
        return

    with requests.Session() as session:
        session.headers.update({"User-Agent": "arxiv-cond-mat-monitor/2.0"})
        for paper in matched_papers:
            try:
                paper.download_path = str(download_paper(paper, session))
            except Exception as exc:
                paper.download_error = str(exc)
                print(f"PDF 下载失败（arXiv:{paper.arxiv_id}）：{exc}")


def build_email_content(header_text: str, sections: list[ArxivSection]) -> tuple[str, str]:
    total_papers = sum(len(section.papers) for section in sections)
    matched_papers = [
        paper
        for section in sections
        for paper in section.papers
        if paper.matched_keywords
    ]

    if matched_papers:
        subject = f"ArXiv cond-mat 今日更新，关键词命中 {len(matched_papers)} 篇"
    else:
        subject = "ArXiv cond-mat 今日有更新，但暂无关键词命中"

    lines = [
        f"更新标题: {header_text}",
        f"页面链接: {URL}",
        f"本次共解析到 {total_papers} 篇文献。",
        "",
    ]

    for section in sections:
        matched = [paper for paper in section.papers if paper.matched_keywords]
        lines.extend(
            [
                f"====={section.name}=====",
                f"关键词命中：{len(matched)}/{section.total_entries}",
                "",
            ]
        )

        if not matched:
            lines.append("本部分暂无关键词命中。")
            lines.append("")
            continue

        for number, paper in enumerate(matched, start=1):
            lines.extend(
                [
                    f"{number}. {paper.index} arXiv:{paper.arxiv_id}",
                    f"标题: {paper.title}",
                    f"作者: {paper.authors}",
                    f"命中关键词: {', '.join(paper.matched_keywords)}",
                    f"PDF: {paper.pdf_url}",
                    f"摘要页: {paper.abs_url}",
                ]
            )
            if paper.download_path:
                lines.append(f"已下载: {paper.download_path}")
            elif paper.download_error:
                lines.append(f"下载失败: {paper.download_error}")
            lines.append("")

    if not sections:
        lines.append("已检测到今日更新，但没有解析到 New/Cross/Replacement 分区。")

    return subject, "\n".join(lines).strip()


def get_email_recipients() -> list[str]:
    return [email for email in [EMAIL_TO, EMAIL_TO_2] if email]


def send_email(subject: str, content: str):
    recipients = get_email_recipients()
    if not EMAIL_FROM or not EMAIL_PASS or not recipients:
        print("邮箱账号、授权码或收件人不完整，跳过发送邮件。")
        print("邮件主题:", subject)
        print("邮件内容:\n", content)
        return

    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(recipients)

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_FROM, EMAIL_PASS)
            server.sendmail(EMAIL_FROM, recipients, msg.as_string())
        print(f"邮件已发送：{subject}，收件人：{recipients}")
    except Exception as exc:
        print("发送邮件失败:", exc)


def check_once():
    soup = fetch_soup()
    has_update, header_text = get_today_update_status(soup)
    if not has_update:
        return False, header_text, []
    return True, header_text, parse_sections(soup)


def main():
    parser = argparse.ArgumentParser(description="Monitor arXiv cond-mat new papers.")
    parser.add_argument(
        "--test-send",
        action="store_true",
        help="抓取当前页面并立即发送一封测试邮件，不检查是否为当天更新。",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="只检查和发送邮件，不下载命中关键词的 PDF。",
    )
    args = parser.parse_args()

    if args.test_send:
        soup = fetch_soup()
        _, header_text = get_today_update_status(soup)
        sections = parse_sections(soup)
        subject, content = build_email_content(header_text or "arXiv cond-mat 当前页面", sections)
        send_email("[测试] " + subject, content)
        return

    start_time = datetime.now()
    already_sent = False

    print(f"当前系统时间（UTC）: {datetime.now(ZoneInfo('UTC'))}")
    print(f"北京时间: {datetime.now(ZoneInfo('Asia/Shanghai'))}")
    print(f"[{datetime.now()}] 开始检测 arXiv cond-mat 当天更新和关键词...")

    while (datetime.now() - start_time).total_seconds() < RUN_LIMIT:
        try:
            has_update, header_text, sections = check_once()
        except Exception as exc:
            print(f"[{datetime.now()}] 检查失败，等待下一次重试: {exc}")
            time.sleep(CHECK_INTERVAL)
            continue

        if has_update and not already_sent:
            if not args.no_download:
                download_matched_papers(sections)
            subject, content = build_email_content(header_text, sections)
            send_email(subject, content)
            already_sent = True
            break

        print(f"[{datetime.now()}] 今日暂无更新，等待下一次检查...")
        time.sleep(CHECK_INTERVAL)

    if not already_sent:
        send_email("ArXiv 当天更新检测结果", "截至运行时间上限，未检测到今日更新。")


if __name__ == "__main__":
    main()
