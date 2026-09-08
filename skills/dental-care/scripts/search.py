import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from llama_index.core import SimpleDirectoryReader, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.openai import OpenAIEmbedding


SCRIPT_PATH = Path(__file__).resolve()
SKILL_DIR = SCRIPT_PATH.parent.parent
PROJECT_ROOT = SKILL_DIR.parent.parent
REFERENCES_DIR = SKILL_DIR / "references"

load_dotenv(PROJECT_ROOT / ".env")


def search_references(query: str, top_k: int) -> dict:
    """references内のMarkdownファイルをLlamaIndexで意味検索する。"""

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(".envにOPENAI_API_KEYが設定されていません。")

    if not REFERENCES_DIR.exists():
        raise FileNotFoundError(
            f"referencesフォルダが見つかりません: {REFERENCES_DIR}"
        )

    markdown_files = sorted(REFERENCES_DIR.rglob("*.md"))

    if not markdown_files:
        raise RuntimeError("references内にMarkdownファイルがありません。")

    documents = SimpleDirectoryReader(
        input_files=[str(path) for path in markdown_files],
        filename_as_id=True,
    ).load_data()

    embed_model = OpenAIEmbedding(model="text-embedding-3-small")
    text_splitter = SentenceSplitter(chunk_size=512, chunk_overlap=50)

    index = VectorStoreIndex.from_documents(
        documents,
        embed_model=embed_model,
        transformations=[text_splitter],
    )

    retriever = index.as_retriever(similarity_top_k=top_k)
    retrieved_nodes = retriever.retrieve(query)

    results = []

    for retrieved_node in retrieved_nodes:
        node = retrieved_node.node
        score = retrieved_node.score
        raw_path = node.metadata.get("file_path")

        if raw_path:
            try:
                source = Path(raw_path).resolve().relative_to(SKILL_DIR).as_posix()
            except ValueError:
                source = Path(raw_path).name
        else:
            source = node.metadata.get("file_name", "不明")

        results.append(
            {
                "source": source,
                "score": round(score, 4) if score is not None else None,
                "content": node.text,
            }
        )

    return {
        "query": query,
        "result_count": len(results),
        "results": results,
    }


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
