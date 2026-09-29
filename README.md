# session-planner-dashboard

AWS Events API から re:Invent 2026 のセッション一覧を取得し、検索・絞り込み・お気に入り・日程確認ができる HTML ダッシュボードを生成します。すべて利用者の PC 上で動作します。

AWS および Amazon とは関係のない、個人の非公式ツールです。AWS、re:Invent は Amazon.com, Inc. またはその関連会社の商標です。

## 前提

- re:Invent 2026 に参加登録済みの Builder ID
- Python 3.12
- uv

## 使い方

次の 1 コマンドを実行します。

```console
uv run python -m session_planner
```

保存済みトークンが無い場合や更新できない場合はブラウザが開きます。AWS Builder ID でサインインすると、`http://localhost:8484/callback` で戻り先を自動的に受け取り、トークンを保存します。その後、全セッションを取得し、取得件数を API の `totalCount` と照合してから `data/sessions.json` に保存します。最後に `data/dashboard.html` を生成し、ブラウザで開きます。生成したファイルの場所は画面にも表示されるので、ブラウザが開かない場合はそのファイルを直接開いてください。

パスワードは AWS の画面で入力するため、このアプリには渡りません。

ダッシュボードを自動で開かない場合は `--no-open` を付けます。

```console
uv run python -m session_planner --no-open
```

### 個別に実行する場合

認証・取得・生成だけを行う既存コマンドも個別に実行できます。

```console
uv run python -m session_planner.login
uv run python -m session_planner.fetch_sessions
uv run python -m session_planner.build_dashboard
```

## うまくいかないとき

- 取得件数が `totalCount` と一致しない場合は、`data/sessions.json` を更新せずに終了し、ダッシュボードも生成しません。取得できた分は `data/sessions.partial.json` に保存されます。時間をおいて再実行してください。以前の `data/sessions.json` が残っていても、それは前回の結果です。
- API が 401 を返した場合は、トークンを 1 回だけ更新して再試行します。それでも 401 の場合はブラウザでサインインし直し、取得を 1 回だけやり直します。やり直しも失敗した場合は、終了コード 1 で終了します。
- 参加登録していない Builder ID でサインインすると 403 になります。サインインし直しても解決しないため、re:Invent 2026 に参加登録済みの Builder ID を使ってください。

## 注意

- 取得データは参加登録者向けの非公開情報です。共有しないでください。`data/` に作られるファイル（`sessions.json`、`dashboard.html`、最初のページの生データ `page1.raw.json`、件数が合わなかったときの `sessions.partial.json`）はすべて非公開情報を含みます。`data/` は `.gitignore` に登録済みです。
- 認証トークンは利用者の PC にだけ保存されます。既定の保存先は `~/.config/session-planner-dashboard/token.json` で、`XDG_CONFIG_HOME` が設定されている場合はその配下を使います。トークンファイルのパーミッションは 600 です。
- サインインの戻り先は `http://localhost:8484/callback` で、ポート 8484 固定です。ほかのアプリがこのポートを使用している場合はサインインに失敗します。

## 出典

- [AWS Events API 開発者ガイド](https://docs.aws.amazon.com/events/latest/devguide/what-is-events-api.html)
