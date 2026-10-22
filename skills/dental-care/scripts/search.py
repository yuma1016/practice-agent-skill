import argparse
#ターミナルから渡された引数を使えるようにする
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from llama_index.core import SimpleDirectoryReader, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.openai import OpenAIEmbedding


SCRIPT_PATH = Path(__file__).resolve()
#現在実行しているファイルの場所を絶対パスにする
SKILL_DIR = SCRIPT_PATH.parent.parent
#search.pyから親ファイルへと二度辿る(dental-care/まで)
PROJECT_ROOT = SKILL_DIR.parent.parent
#dental-careから更に二度辿る(cavity-skill-demoまで)
REFERENCES_DIR = SKILL_DIR / "references"
#Skillフォルダとreferencesを結合

load_dotenv(PROJECT_ROOT / ".env")
#.envを読み込む


def search_references(query: str, top_k: int) -> dict:
    #検索したい質問と上位何件まで受け取るかを引数として返り値を辞書型にする
    """references内のMarkdownファイルをLlamaIndexで意味検索する。"""

    if not os.getenv("OPENAI_API_KEY"):
    #APIが取得出来ているかどうか
        raise RuntimeError(".envにOPENAI_API_KEYが設定されていません。")
    #エラーを発生させる

    if not REFERENCES_DIR.exists():
    #referencesが存在するかどうか
        raise FileNotFoundError(
            f"referencesフォルダが見つかりません: {REFERENCES_DIR}"
        )
    #フォルダがなければどこを探したか述べつつエラーを出す

    markdown_files = sorted(REFERENCES_DIR.rglob("*.md"))
    #references内にある全ての.mdを検索する.rglob("*.md")は下のフォルダまで再帰的に検索する
    #sorted()は見つけたファイルをパス順に並べる
    if not markdown_files:
    #markdownファイルがなかった場合
        raise RuntimeError("references内にMarkdownファイルがありません。")

    documents = SimpleDirectoryReader(
    #LlamaIndexのファイルを読み込む関数
        input_files=[str(path) for path in markdown_files],
    #読み込むファイルの一覧を指定(markdown_fileのパスをstr(path)により文字列に変換し、リストに追加)
        filename_as_id=True,
    #ファイル名を文書の識別情報として利用(どのファイルから読み込んだか追跡しやすくなる)
    ).load_data()
    #指定したファイルを読み込む

    embed_model = OpenAIEmbedding(model="text-embedding-3-small")
    text_splitter = SentenceSplitter(chunk_size=512, chunk_overlap=50)

    index = VectorStoreIndex.from_documents(
    #検索用のindexを構築
        documents,
    #検索対象となる文書を渡す
        embed_model=embed_model,
        transformations=[text_splitter],
    #文書を分割する
    )

    retriever = index.as_retriever(similarity_top_k=top_k)
    #質問を検索するretrieverを作る。意味が近い検索結果を上位何件取得するか
    retrieved_nodes = retriever.retrieve(query)
    #実際に質問を検索する。検索結果はretriever_nodesに保存

    results = []
    #結果を格納する空リスト
    for retrieved_node in retrieved_nodes:
        node = retrieved_node.node
        #文章本体やメタデータを持つnodeを取り出す
        score = retrieved_node.score
        #質問と文章の類似度スコアを取り出す
        raw_path = node.metadata.get("file_path")
        #メタデータから元のファイルのパスを取り出す(.getはfile_pathが存在してもエラーにならない)

        if raw_path:
        #ファイルパスが取得出来たら
            try:
                source = Path(raw_path).resolve().relative_to(SKILL_DIR).as_posix()
        #絶対パスを短い相対パスにする(Path()は文字列をPathに変換し、.relative_to(SKILL_DIR)はSKILLフォルダからの相対パスにする)
        #.as_posix()で区切り文字を/に統一
            except ValueError:
                source = Path(raw_path).name
        else:
            source = node.metadata.get("file_name", "不明")

        results.append(
        #検索結果をリストに追加
            {
                "source": source,
            #元の資料名を追加
                "score": round(score, 4) if score is not None else None,
            #類似度スコアを小数第四位まで
                "content": node.text,
            #検索で見つかった文章を保存
            }
        )

    return {
        "query": query,
        "result_count": len(results),
#検索結果の件数
        "results": results,
    }
#検索結果を辞書で返す


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LlamaIndexでMarkdown形式の歯科資料を検索します。"
    )
    parser.add_argument("question", nargs="?", help="検索したい質問")
    parser.add_argument("--query", help="検索したい質問")
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="取得する検索結果数",
    )

    args = parser.parse_args()
    query = args.query or args.question

    if not query:
        parser.error("検索質問を指定してください。")

    top_k = max(1, min(args.top_k, 10))
    result = search_references(query=query, top_k=top_k)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
