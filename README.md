# wbhist

`workbox` コンテナ（Claude Code 常駐コンテナ）が書き出す会話ログ（`sessions.db`）を、
ブラウザから閲覧するための Web アプリ。

- Flask（`app.py`）+ gunicorn + nginx（Docker Compose 構成）
- `sessions.db`（SQLite）を **read-only** でマウントして参照するだけで、
  `workbox` コンテナの内部（`~/.claude`）には一切アクセスしない
- `sessions.db` のスキーマ・同期方式は `workbox` コンテナ側（別リポジトリ `hp-mini_config/workbox_setup/`）の
  `sync_to_sqlite.py` が定義・管理する。本アプリは read-only で参照するのみで、スキーマの変更権限は持たない

## 前提

`workbox` コンテナ側で同期スクリプト（`sync_to_sqlite.py`）が動作し、
ホスト上に `sessions.db` が生成されていること。

## セットアップ（サーバ上）

```bash
git clone git@github.com:ugohsu/wbhist && cd wbhist

cp .env.example .env
# SECRET_KEY・APP_PASSWORD・APP_UID・APP_GID・SQLITE_DIR を実際の値に編集

docker compose up -d --build
```

ブラウザで `http://<server-ip>:5001` を開く（VPN 内からのみアクセス可能。
`APP_PASSWORD` に設定した共有パスワードでログインする）。

## 環境変数（`.env`）

| 変数 | 説明 |
|---|---|
| `SECRET_KEY` | Flask セッション署名キー。`python3 -c "import secrets; print(secrets.token_hex(32))"` で生成 |
| `APP_PASSWORD` | ログイン画面で要求する共有パスワード。未設定だとログインできなくなるので必ず設定する |
| `APP_UID` / `APP_GID` | コンテナが作るファイルの所有者をホストユーザーに合わせる（確認: `id -u` / `id -g`） |
| `SQLITE_DIR` | `sessions.db` が置かれているホスト上のディレクトリ（`workbox` の sync スクリプトの出力先。例: `~/claude-logs`） |
| `APP_DATA_DIR` | 本アプリ自身の設定（GitHub連携など）を保存する**書き込み可能**なホスト上のディレクトリ（例: `~/wbhist-data`）。事前に `mkdir -p` し `APP_UID`/`APP_GID` で書き込めることを確認しておく |

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
    ├── _repo_link.html       # サイドバーの GitHub 連携フォームを描画する Jinja マクロ
    ├── login.html            # ログイン画面（共有パスワード入力）
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
- 共有パスワードによるログイン認証（`.env` の `APP_PASSWORD` と一致するパスワードを
  入力するとセッションが発行され、以後30日間は再ログイン不要。サイドバー下部の
  「ログアウト」でセッションを破棄できる）。VPN 内からのみアクセス可能という
  前提に加えて、同一LAN/VPN上の他の利用者からの不用意なアクセスを防ぐための
  簡易的なものであり、ユーザーごとの権限分離は行わない

## Phase 2（実装済み）

git は使わず、Claude Code 自身の `Edit` tool_use（`old_string`/`new_string`）を
diff の元データとして表示する（`Write` 等は対象外）。各会話ターンの本文に
テキストがある場合はコピーアイコンの隣、無い場合（Edit のみのターン）は
そのターンの行に、diff 表示用のアイコンが表れる。クリックでそのターンの
`file_edits`（`sessions.db`）を diff として展開表示する。

採用までの経緯：git 管理は `.git` の入れ子問題（サブディレクトリが独立した
`.git` を持つと embedded repository として扱われ diff に出てこない）のため
不採用。`Write` 用のベースライン管理（直前の内容を別テーブルで保持し、初回は
起動時バックフィルが必要）も、得られる効果に対して複雑さ・将来の破損リスクが
大きいため見送り。`Edit` だけは、`old_string` が実際のファイル内容と一致しないと
失敗する仕様上、`old_string`/`new_string` の組自体が変更の正確な diff になっている
ため、ベースライン管理なしで採用できた。

## GitHub連携（任意・実装済み）

プロジェクトごとに「GitHubリポジトリURL＋ブランチ」を登録すると、Phase 2 の diff パネルに
出てくるファイルパスがそのファイルの GitHub 上のページへのリンクになる。

- 登録・解除はサイドバー（プロジェクト名の下）から行う。プロジェクトごとに任意・個別設定で、
  登録しなければ従来どおりプレーンテキストのまま
- 保存先は `sessions.db` とは別の、本アプリ専用の書き込み可能な DB（`APP_DATA_DIR` 配下の
  `wbhist.db`、`repo_links` テーブル）。`sessions.db` は read-only のまま変更しない
- URL は `https://github.com/<org>/<repo>` の形式のみ受け付ける。ブランチは空欄なら `main`
- リンク先は `file_edits.file_path`（`sessions.db` の `sessions.project_path` を前置詞として
  相対パス化したもの）を使い、`<repo_url>/blob/<branch>/<relative_path>` を組み立てるだけ
- **制約**：リンクは登録した**現在のデフォルトブランチの最新内容**を指すだけで、編集した
  当時のコミットには紐付かない（コミット単位の対応付けはせず、URL生成のみなので git連携や
  Phase 2 で避けた入れ子 `.git` 問題は再発しない）。ファイルがリネーム・削除されていたり、
  該当プロジェクトが git 管理外・未 push の場合はリンク先が無いか的外れになりうる

## Docker なしでのローカル動作確認

```bash
pip install -r requirements.txt
DB_PATH=/path/to/sessions.db DATA_DB_PATH=/path/to/wbhist.db python3 app.py
```

`http://127.0.0.1:8000` で確認できる（`app.py` の `__main__` が Flask 開発サーバを起動する）。
`DB_PATH` 未指定時のデフォルトは `/data/sessions.db`、`DATA_DB_PATH` 未指定時のデフォルトは
`/app-data/wbhist.db`（いずれも Docker Compose のマウント先）。`DATA_DB_PATH` の親ディレクトリは
存在しなければ起動時に自動作成される。

## SQLite の read-only マウントについて

`sessions.db` は同期スクリプト側が `PRAGMA journal_mode=WAL` を使わず、デフォルトの
ロールバックジャーナルのまま運用している（WAL だと本アプリ側も `-shm` ファイルへの
アクセスが必要になり、read-only マウントでは失敗しうるため）。本アプリは保険として
`file:sessions.db?mode=ro` の URI 接続で開き、誤って書き込むコードが混入することを防いでいる。
GitHub連携の設定（`repo_links`）は別の書き込み可能な `wbhist.db`（`APP_DATA_DIR`）に保存しており、
この read-only 制約・WAL 不使用の対象は `sessions.db` のみ。
