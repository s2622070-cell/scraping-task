import sqlite3
import time
import re
import requests
from bs4 import BeautifulSoup

# --- 1. データベースの初期化 ---
conn = sqlite3.connect("google_repos.db")
cursor = conn.cursor()

cursor.execute("DROP TABLE IF EXISTS repositories")
cursor.execute("""
CREATE TABLE repositories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_name TEXT NOT NULL UNIQUE,
    language TEXT,
    stars INTEGER
)
""")
conn.commit()

# --- 2. スクレイピング処理（全ページ自動巡回） ---
base_url = "https://github.com/orgs/google/repositories?page={}"
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

ignore_paths = {"/google", "/orgs/google", "/google/sponsors", "/orgs/google/repositories", "/orgs/google/people"}
global_seen_names = set()
page = 1

print("全リポジトリのスクレイピングを開始します（約100ページ・2分ほどかかります）...")

while True:
    url = base_url.format(page)
    
    try:
        res = requests.get(url, headers=headers, timeout=15)
    except requests.RequestException as e:
        print(f"[Page {page}] 通信エラーが発生しました: {e} -> 5秒待機してリトライします")
        time.sleep(5)
        continue

    if res.status_code == 429:
        print(f"[Page {page}] アクセス制限(429)を検知しました -> 10秒待機してリトライします")
        time.sleep(10)
        continue
    elif res.status_code != 200:
        print(f"[Page {page}] 取得終了 (Status: {res.status_code})")
        break

    soup = BeautifulSoup(res.text, "html.parser")
    all_links = soup.find_all("a", href=True)
    
    page_repo_count = 0

    for a in all_links:
        href = a['href']

        if href.startswith("/google/") and href not in ignore_paths:
            parts = href.split("/")
            if len(parts) >= 3:
                repo_name = parts[2].split("?")[0].split("#")[0]

                if not repo_name or "/" in repo_name:
                    continue

                # ページ上のリポジトリ数をカウント（最終ページ判定用）
                if repo_name not in global_seen_names:
                    global_seen_names.add(repo_name)
                    page_repo_count += 1
                else:
                    continue

                # リポジトリ1件分のカード要素まで親を遡る
                card = a
                while card and card.parent and card.parent.name != 'body':
                    card = card.parent
                    if card.name in ['li', 'article']:
                        break
                    classes = " ".join(card.get('class', [])).lower()
                    if 'box-row' in classes or 'col-12' in classes:
                        break

                # --- 主要言語の抽出 ---
                language = "None"
                
                # 1. itemprop属性から取得
                lang_elem = card.find(attrs={"itemprop": "programmingLanguage"})
                if lang_elem:
                    language = lang_elem.get_text(strip=True)
                else:
                    # 2. 言語カラーアイコン（style="background-color:..."）の周辺テキストから取得
                    color_dot = card.find("span", style=re.compile(r"background-color\s*:", re.I))
                    if color_dot:
                        # 親要素のテキスト（色ドット自体は空文字なので言語名だけが取れる）
                        parent_text = color_dot.parent.get_text(strip=True)
                        if parent_text:
                            language = parent_text

                # --- スター数の抽出 ---
                star_elem = card.find("a", href=re.compile(r"/stargazers"))
                stars = 0
                if star_elem:
                    raw_text = star_elem.get_text(strip=True).replace(",", "").lower()
                    match = re.search(r'([\d.]+)\s*([km])?', raw_text)
                    if match:
                        num_str, unit = match.groups()
                        try:
                            val = float(num_str)
                            if unit == 'k':
                                stars = int(val * 1000)
                            elif unit == 'm':
                                stars = int(val * 1000000)
                            else:
                                stars = int(val)
                        except ValueError:
                            stars = 0

                # データベースに保存
                cursor.execute("""
                INSERT OR IGNORE INTO repositories (repo_name, language, stars)
                VALUES (?, ?, ?)
                """, (repo_name, language, stars))

    conn.commit()
    print(f"[Page {page}] {page_repo_count} 件取得（累計: {len(global_seen_names)} 件）")

    # そのページで新規リポジトリが0件になったら全ページ取得完了とみなして終了
    if page_repo_count == 0:
        print("最終ページに到達したため、スクレイピングを完了します。")
        break

    page += 1
    # 課題要件: サーバー負荷軽減のための1秒待機
    time.sleep(1)

# --- 3. SELECT文でデータを表示 ---
print("\n=== 保存されたリポジトリ情報 (SELECT文による抽出) ===")
cursor.execute("SELECT id, repo_name, language, stars FROM repositories")
rows = cursor.fetchall()

print(f"{'ID':<5} | {'Repository Name':<38} | {'Language':<15} | {'Stars':<8}")
print("-" * 74)
for row in rows:
    print(f"{row[0]:<5} | {row[1]:<38} | {row[2]:<15} | {row[3]:<8}")

print("-" * 74)
print(f"データベース総保存件数: {len(rows)} 件")

conn.close()