# wbhist

`workbox` コンテナ（Claude Code 常駐コンテナ）が書き出す会話ログ（`sessions.db`）を、
ブラウザから閲覧するための Web アプリ。

- Flask（`app.py`）+ gunicorn + nginx（Docker Compose 構成）
- `sessions.db`（SQLite）を **read-only** でマウントして参照するだけで、
  `workbox` コンテナの内部（`~/.claude`）には一切アクセスしない
- 設計の背景（同期方式・DB スキーマ・運用方針）は `workbox` 側の設定リポジトリ
  （`hp-mini_config`）の `homeserver-webapp-spec.md` を参照（別リポジトリのため本リポジトリには含まない）

## 前提

`workbox` コンテナ側で同期スクリプト（`sync_to_sqlite.py`）が動作し、
ホスト上に `sessions.db` が生成されていること。

## セットアップ（サーバ上）

```bash
git clone git@github.com:ugohsu/wbhist && cd wbhist

cp .env.example .env
# SECRET_KEY・APP_UID・APP_GID・SQLITE_DIR を実際の値に編集

docker compose up -d --build
```

ブラウザで `http://<server-ip>:5001` を開く（VPN 内からのみアクセス可能・認証なし）。

## 環境変数（`.env`）

| 変数 | 説明 |
|---|---|
| `SECRET_KEY` | Flask セッション署名キー。`python3 -c "import secrets; print(secrets.token_hex(32))"` で生成 |
| `APP_UID` / `APP_GID` | コンテナが作るファイルの所有者をホストユーザーに合わせる（確認: `id -u` / `id -g`） |
| `SQLITE_DIR` | `sessions.db` が置かれているホスト上のディレクトリ（`workbox` の sync スクリプトの出力先。例: `~/claude-logs`） |

## ディレクトリ構成

```
wbhist/
├── app.py                  # Flask アプリ本体
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .env                     ← gitignore 対象
├── nginx/
│   └── nginx.conf
├── static/
│   ├── css/style.css        # 専用 CSS（Bootstrap は使わない）
│   └── js/app.js            # サイドバーの差し替えナビ・コピー機能
└── templates/
    ├── base.html            # サイドバー＋本文の2カラムシェル
    ├── _nav.html             # サイドバーのリスト項目を描画する Jinja マクロ
    ├── index.html            # ルート（プロジェクト一覧。本文は未選択時のプレースホルダ）
    ├── project.html          # プロジェクト選択時（セッション一覧。本文はプレースホルダ）
    └── session.html          # セッション選択時（会話表示）
```

## 機能（Phase 1・実装済み）

- `sessions.db` の `sessions` テーブルを `project_path` でグルーピングしたプロジェクト一覧を
  **サイドバー**に表示（Gemini のチャット履歴のような見た目）
- プロジェクトを選ぶとサイドバーがセッション一覧（`ai_title` ・更新日時）に切り替わる
- セッションを選ぶと本文に会話（user / assistant）を表示。user は右寄せの丸いバブル、
  assistant はバブルなしのプレーンテキスト
- サイドバー上の移動は `fetch` で `.side-nav` だけを差し替える方式で、**新しいセッションを
  実際に選ぶまで本文の会話表示は維持される**（フルページ遷移ではないので
  `history.pushState` で URL を同期。JS 無効時は通常のページ遷移にフォールバック）
- 各メッセージにマウスを乗せるとコピーアイコンが表れ、本文をクリップボードにコピーできる
  （`navigator.clipboard` は https/localhost でないと使えないため、http アクセス向けに
  `document.execCommand('copy')` フォールバックを実装済み）
- 表示する時刻はすべて JST（UTC+9）に変換（DB は UTC のまま。変換はテンプレート側のみ）
- スマホ幅ではサイドバーが既定で隠れ、左上のハンバーガーボタンで開閉する
- 認証なし（VPN 内からしかアクセスできない前提のため）

## Phase 2（未実装）

ファイルの変更履歴（`git log` / `git diff`）を表示する diff ビューア。詳細は
`homeserver-webapp-spec.md` の「Phase 2」を参照。

## Docker なしでのローカル動作確認

```bash
pip install -r requirements.txt
DB_PATH=/path/to/sessions.db python3 app.py
```

`http://127.0.0.1:8000` で確認できる（`app.py` の `__main__` が Flask 開発サーバを起動する）。
`DB_PATH` 未指定時のデフォルトは `/data/sessions.db`（Docker Compose のマウント先）。

## SQLite の read-only マウントについて

同期スクリプト側は `PRAGMA journal_mode=WAL` を使わず、デフォルトのロールバックジャーナル
のまま運用している（WAL だと本アプリ側も `-shm` ファイルへのアクセスが必要になり、
read-only マウントでは失敗しうるため）。本アプリは保険として
`file:sessions.db?mode=ro` の URI 接続で開き、誤って書き込むコードが混入することを防いでいる。
