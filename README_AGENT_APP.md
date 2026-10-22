# 歯科相談・院内案内エージェント

既存の `group_chat.py` を残したまま、Microsoft Agent Framework のエージェントを
責務ごとのPythonファイルへ分離した実装です。

## 実行

```powershell
.\.venv\Scripts\python.exe app.py --validate
.\.venv\Scripts\python.exe app.py
```

既存の `.env` に `OPENAI_API_KEY` が必要です。生成地図を自動で開かない場合は
`--no-open` を追加します。

## 使い方

- `/research <質問>`: Researcherで歯科資料を検索して回答
- `/guide <質問>`: HospitalNavigatorで院内案内
- `/reset`: 両エージェントの会話セッションを再作成
- `/exit`: 終了

「案内」「行き方」「何階」「どこ」などを含む通常文も案内モードへ振り分けます。
案内の会話では、目的地検索後に現在地が不足していればエージェントが追加質問します。

例:

```text
/guide 初診相談室へ行きたい
いまは正面入口です
```

## 既存機能との関係

- `skills/dental-care/scripts/search.py` は変更せず、RAG Toolから既存CLIを呼び出します。
- Researcherの `SkillsProvider`、`ToolApprovalMiddleware`、LlamaIndex検索、
  `AgentSession`、1ラウンドGroup Chatを維持しています。
- 既存のフロアマップREADMEとPNGを読み込みます。
- 元の `group_chat.py` と `main.py` は比較・後方互換用に変更していません。

## 案内処理

HospitalNavigatorには次の2つのFunction Toolだけを公開します。

1. `search_facility(question)`: 既存LlamaIndex検索を実行し、検索証跡を案内セッションへ保存。
2. `commit_navigation(current_location, destination)`: 確定済みの2地点を送る宣言用Tool。

`NavigationExecutionMiddleware` は2番目のToolだけを捕捉します。現在地・目的地・
RAG証跡・施設名の一意性が揃った場合だけ、Dijkstra法による最短経路、距離、
画像上の8方向、手順、現在地／目的地マーカー付きPNGを生成します。

## データ上の重要な注意

`data/facility_graph.json` は既存の架空フロア図を使って動作確認できるよう作成しています。
画像座標は既存PNGに合わせていますが、距離はフロア図から作った未実測の推定値です。
実運用前に施設管理者が `edges[].distance_m` を実測値へ置き換えてください。

スタッフ専用区画、閉鎖経路、工事、診療時間、車椅子経路などの運用条件は未提供のため、
現状の経路選択には含まれません。

## テスト

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

外部APIを呼ばずに、施設解決、同一棟・別階・別棟経路、RAG条件、
Middlewareからの描画処理、Agent Frameworkのコンストラクタ互換性を確認します。

## 主なファイル

```text
app.py
hospital_agents/
  agents/researcher.py
  agents/navigation.py
  middleware/navigation.py
  services/rag.py
  services/routing.py
  services/map_renderer.py
  services/floor_maps.py
data/facility_graph.json
data/facility_graph.schema.json
scripts/render_route_map.py
tests/
```

詳しい責務分離は `ARCHITECTURE_AGENT_APP.md`、API確認内容は
`API_NOTES_AGENT_APP.md`、実運用前に必要な入力は
`MISSING_INPUTS_AGENT_APP.md` を参照してください。

