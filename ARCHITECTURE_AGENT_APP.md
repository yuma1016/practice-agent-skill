# 構成説明

## 全体フロー

```text
ユーザー入力
  ├─ 資料相談 → Researcher → 既存search.py → LlamaIndex → 根拠付き回答
  └─ 院内案内 → HospitalNavigator
                  ├─ search_facility Tool → 既存search.py
                  └─ commit_navigation Tool
                         ↓ Function Middleware
                    施設名の一意解決
                         ↓
                    距離・方向・最短経路
                         ↓
                    render_route_map.py
                         ↓
                    マーカー付きPNG
```

## Researcher

`hospital_agents/agents/researcher.py` が元のResearcher設定を保持します。
毎ターン、既存の `search.py --query ... --top-k ...` を先に実行し、検索結果と
`SKILL.md` をタスクへ含めます。会話履歴はResearcher専用の `AgentSession` に保持し、
`GroupChatBuilder(max_rounds=1)` はターンごとに作り直します。

## HospitalNavigator

目的地抽出と不足情報の聞き返しはエージェントが担当します。経路計算へLLMの自由文を
直接渡さず、Function Toolの構造化引数を境界にしています。

案内用 `AgentSession` はResearcherと分離し、次を保存します。

- `hospital_navigation.last_rag_search`: 直前の施設RAG検索
- `hospital_navigation.last_route`: 最後に確定した経路と生成画像

## Function Middleware

`NavigationExecutionMiddleware` が `commit_navigation` の呼び出しを捕捉します。
次の条件をすべて満たした場合だけ決定論的処理を実行します。

1. 現在地と目的地が空でない。
2. 同じ案内セッションで `search_facility` が実行済み。
3. 両地点が施設グラフのname/aliasesへ一意に解決できる。
4. 目的地名が直前のRAG出力に含まれる。
5. 両地点を結ぶ経路がある。

Python版のAgent HooksではなくFunction Middlewareを採用したのは、対象が
特定Function Toolの前後処理であり、現在のインストール済みAgent Frameworkで
利用可能な安定した拡張点だからです。

## 経路と地図

`RouteEngine` は施設グラフを読み込み、Dijkstra法で登録距離の合計が最小の経路を
計算します。方向はPNGの左上を原点として「画像の右」「画像の左上」など8方向で表します。
地理的な東西ではありません。

描画処理はLLMが指定した任意スクリプトを実行しません。アプリ設定で固定した
`scripts/render_route_map.py` だけを `shell=False` の子プロセスとして起動します。
出力ファイル名はアプリ側がUUIDから生成します。

## 既存ファイルの保護

既存の `group_chat.py`、`main.py`、`search.py`、フロアマップREADME・PNGは
変更しません。新しい実装は `app.py` と `hospital_agents/` 以下から利用します。

