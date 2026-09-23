import asyncio
from dataclasses import dataclass
import os
import re
import subprocess
#別のPythonファイルを別プロセスとして実行出来てるようにする
import sys
#現在実行中のPythonに関する情報を利用
from pathlib import Path
import unicodedata

from dotenv import load_dotenv
from agent_framework import (
#必要なクラスを読み込む
    Agent,
#Resarcherやwriterを作る
    AgentResponseUpdate,
#ストリーミング中の回答データを表す
    SkillsProvider,ToolApprovalMiddleware
#skillをフォルダを実行し、Skillのツール実行を承認
)
from agent_framework.openai import OpenAIChatClient
from agent_framework.orchestrations import (
    GroupChatBuilder,
#Group chatワークフローを作成
    GroupChatState,
#現在のラウンド数や参加者情報を持つ
)


# group_chat.pyが置かれているプロジェクトフォルダ
BASE_DIR = Path(__file__).resolve().parent
FLOOR_MAP_GUIDE = (
    BASE_DIR
    / "skills"
    / "dental-care"
    / "references"
    / "aoba-dental-floor-maps"
    / "README.md"
)
FLOOR_MAPS_DIR = FLOOR_MAP_GUIDE.parent / "maps"

# プロジェクト直下の.envを読み込む
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class FloorMap:
    """スキルの参照資料から読み取った1フロア分の画像情報。"""

    building: str
    floor: str
    title: str
    image_path: Path
    facility_names: tuple[str, ...]


def _normalize_for_match(text: str) -> str:
    """表記揺れを吸収するため、全角英数字と空白を正規化する。"""

    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", "", normalized)


def _facility_aliases(facility_name: str) -> set[str]:
    """READMEの施設名から、照合に使える部屋名の候補を作る。"""

    aliases = {_normalize_for_match(facility_name)}

    for part in re.split(r"[／/・、]", facility_name):
        normalized_part = _normalize_for_match(part)

        if len(normalized_part) >= 3:
            aliases.add(normalized_part)

        # 「一般診療 A101〜A104」のような表記から「一般診療」も取り出す。
        name_without_room_number = re.sub(
            r"[ab]\d{3}(?:[〜~-][ab]?\d{3})?",
            "",
            normalized_part,
            flags=re.IGNORECASE,
        ).strip()

        if len(name_without_room_number) >= 3:
            aliases.add(name_without_room_number)

    return aliases


def load_floor_maps() -> list[FloorMap]:
    """dental-care SkillのREADMEからフロアと画像パスを読み取る。"""

    if not FLOOR_MAP_GUIDE.exists():
        return []

    guide_text = FLOOR_MAP_GUIDE.read_text(encoding="utf-8")
    section_pattern = re.compile(
        r"^##\s+(?P<building>[AB])棟\s*(?P<floor>\d+)F\s*[^\n]*\n"
        r"(?P<body>.*?)(?=^---\s*$|^##\s+|\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    image_pattern = re.compile(
        r"!\[(?P<title>[^\]]+)]\((?P<path>[^)]+\.png)\)",
        flags=re.IGNORECASE,
    )
    floor_maps: list[FloorMap] = []
    maps_root = FLOOR_MAPS_DIR.resolve()

    for section_match in section_pattern.finditer(guide_text):
        body = section_match.group("body")
        image_match = image_pattern.search(body)

        if image_match is None:
            continue

        candidate_path = (
            FLOOR_MAP_GUIDE.parent / image_match.group("path")
        ).resolve()

        # Skillのmapsフォルダ外を指すパスは画像として採用しない。
        try:
            candidate_path.relative_to(maps_root)
        except ValueError:
            continue

        if not candidate_path.is_file():
            continue

        facility_names: list[str] = []

        for line in body.splitlines():
            if not line.startswith("|"):
                continue

            cells = [cell.strip() for cell in line.strip("|").split("|")]

            if not cells or cells[0] in ("施設", "---") or set(cells[0]) == {"-"}:
                continue

            facility_names.append(cells[0])

        floor_maps.append(
            FloorMap(
                building=section_match.group("building"),
                floor=section_match.group("floor"),
                title=image_match.group("title"),
                image_path=candidate_path,
                facility_names=tuple(facility_names),
            )
        )

    return floor_maps


def find_floor_maps_in_researcher_output(
    researcher_output: str,
    floor_maps: list[FloorMap],
) -> list[FloorMap]:
    """Researcherの出力から、最も関連性が高いフロア画像を探す。"""

    normalized_output = _normalize_for_match(researcher_output)
    image_path_matches: set[tuple[str, str]] = set()
    room_number_matches: set[tuple[str, str]] = set()
    building_floor_matches: set[tuple[str, str]] = set()
    mentioned_buildings: set[str] = set()
    facility_aliases_by_floor: dict[tuple[str, str], set[str]] = {}
    floors_by_facility_alias: dict[str, set[tuple[str, str]]] = {}

    for floor_map in floor_maps:
        key = (floor_map.building, floor_map.floor)
        aliases = {
            alias
            for facility_name in floor_map.facility_names
            for alias in _facility_aliases(facility_name)
        }
        facility_aliases_by_floor[key] = aliases

        for alias in aliases:
            floors_by_facility_alias.setdefault(alias, set()).add(key)

    matched_facility_aliases: list[tuple[str, tuple[str, str]]] = []

    for floor_map in floor_maps:
        building = floor_map.building.casefold()
        floor = floor_map.floor
        key = (floor_map.building, floor_map.floor)

        if f"{building}棟" in normalized_output:
            mentioned_buildings.add(floor_map.building)

        if floor_map.image_path.name.casefold() in normalized_output:
            image_path_matches.add(key)

        if any(
            marker in normalized_output
            for marker in (
                f"{building}棟{floor}f",
                f"{building}棟{floor}階",
            )
        ):
            building_floor_matches.add(key)

        if re.search(
            rf"(?<![a-z0-9]){re.escape(building)}{re.escape(floor)}\d{{2}}(?!\d)",
            normalized_output,
            flags=re.IGNORECASE,
        ) is not None:
            room_number_matches.add(key)

        matched_facility_aliases.extend(
            (alias, key)
            for alias in facility_aliases_by_floor[key]
            if alias in normalized_output
        )

    def maps_for(keys: set[tuple[str, str]]) -> list[FloorMap]:
        return [
            floor_map
            for floor_map in floor_maps
            if (floor_map.building, floor_map.floor) in keys
        ]

    # Researcherが明示した画像パスと部屋番号を最優先する。
    if image_path_matches:
        return maps_for(image_path_matches)

    if room_number_matches:
        return maps_for(room_number_matches)

    # 「初診相談室」のように1フロアだけにある固有施設を優先する。
    unique_facility_matches = {
        key
        for alias, key in matched_facility_aliases
        if len(floors_by_facility_alias[alias]) == 1
    }

    if unique_facility_matches:
        return maps_for(unique_facility_matches)

    if building_floor_matches:
        return maps_for(building_floor_matches)

    # 「トイレ」のような共通設備しかない場合は、登場フロア数が最少の
    # 施設名を優先し、無関係な画像が増えないようにする。
    if matched_facility_aliases:
        minimum_floor_count = min(
            len(floors_by_facility_alias[alias])
            for alias, _ in matched_facility_aliases
        )
        closest_facility_matches = {
            key
            for alias, key in matched_facility_aliases
            if len(floors_by_facility_alias[alias]) == minimum_floor_count
        }
        return maps_for(closest_facility_matches)

    # 「A棟」のように階を特定できない場合は、その棟の全フロアを候補にする。
    building_matches = {
        (floor_map.building, floor_map.floor)
        for floor_map in floor_maps
        if floor_map.building in mentioned_buildings
    }
    return maps_for(building_matches)


def format_floor_map_output(floor_maps: list[FloorMap]) -> str:
    """画像を表示できるMarkdownと、確認用ファイルパスを作る。"""

    output_lines = ["該当するフロアマップです。"]

    for floor_map in floor_maps:
        relative_path = floor_map.image_path.relative_to(BASE_DIR).as_posix()
        output_lines.extend(
            (
                "",
                f"### {floor_map.title}",
                "",
                f"![{floor_map.title}]({relative_path})",
                "",
                f"画像ファイル: `{relative_path}`",
            )
        )

    return "\n".join(output_lines)


def show_floor_map_images(floor_maps: list[FloorMap]) -> None:
    """該当するフロアマップをWindowsの標準画像ビューアーで開く。"""

    if not hasattr(os, "startfile"):
        print("この環境では画像ビューアーを自動で開けません。")
        return

    for floor_map in floor_maps:
        try:
            os.startfile(str(floor_map.image_path))
        except OSError as error:
            print(f"画像を開けませんでした: {floor_map.image_path}")
            print(f"理由: {error}")

def load_skill_instructions() -> str:
#引数無しで実行するとSKILL.mdの内容を文字列で返す
    """SKILL.mdを読み込み、文字列として返す。"""

    skill_file = (
        BASE_DIR
        / "skills"
        / "dental-care"
        / "SKILL.md"
    )
    skill_instructions = skill_file.read_text(
#skill_fileが指すファイルを読み込み、skill_instructionsに保存
        encoding="utf-8"
#ファイルをUTF-8として読み込む
    ).strip()
#文字列の先頭と末尾の余分な空白や改行を削除
    return skill_instructions
#SKILL.mdの内容を返り値にする


def select_next_speaker(state: GroupChatState) -> str:
#group chatの状態を受け取り、次に発言するAgent名を文字列で返す
    """奇数ラウンドはResearcher、偶数ラウンドはWriterを選ぶ。"""

    # current_roundは0から始まるため、表示用には1を足す
    round_number = state.current_round + 1
#現在のラウンド番号を取得

    if round_number % 2 == 1:
#ラウンド番号が奇数か確認
        return "Researcher"

    return "Writer"


def reached_maximum_rounds(conversation) -> bool:
    #会話履歴を受け取り、Group_chatを終了するか判断
    """ResearcherとWriterの発言が合計4回になったら終了する。"""

    assistant_message_count = sum(
    #アシスタント役のメッセージ数を数える
        1
    #該当するメッセージ1件につき、数値の1を作る
        for message in conversation
    #conversation内のメッセージを1件ずつ、messageへ取り出す
        if message.role == "assistant"
    #メッセージの役割がassistantのものだけ対象にする。researcher、writerの発言はどちらもassistant
    )

    return assistant_message_count >= 4
#発言が4件以上ならTrueを返す
def search_documents(
#資料を検索する関数
    question: str,
#検索したい質問を文字列として受け取る
    top_k: int = 5,
#検索結果を何件取得するか
) -> str:
    """Group Chat開始前にsearch.pyを実行する。"""

    search_script = (
        BASE_DIR
        / "skills"
        / "dental-care"
        / "scripts"
        / "search.py"
    )

    if not search_script.exists():
        raise FileNotFoundError(
            "search.pyが見つかりません。\n"
            f"確認した場所: {search_script}"
        )

    command = [
    #実行するコマンドをリストにする
        sys.executable,
    #現在プログラムを実行するPythonの場所
        "-X",
        "utf8",
        str(search_script),
    #実行対象である search.pyのパス
        "--query",
    #--queryオプションを渡す
        question,
    #質問を渡す
        "--top-k",
    #--top-kとして渡す
        str(top_k),
    #コマンドの引数は文字列のため整数に変換
    ]
#python search.py --query "虫歯にならないためには？" --top-k 5
    print("LlamaIndexで資料を検索しています...")

    completed_process = subprocess.run(
    #search.pyを別のプロセスとして実行
        command,
    #コマンドを実行
        capture_output=True,
    #出力をPython側で受け取る
        text=True,
    #出力をPythonの文字列として受け取る
        encoding="utf-8",
    #出力をUTF-8として読み取る
        errors="replace",
    #解読できない文字を代替文字に置き換える
        timeout=120,
    #120秒超えても終わらない場合はタイムアウトとして停止
        cwd=str(search_script.parent),
    #
    )

    if completed_process.returncode != 0:
        raise RuntimeError(
            "search.pyの実行に失敗しました。\n"
            f"{completed_process.stderr}"
        )

    search_result = completed_process.stdout.strip()

    if not search_result:
        raise RuntimeError(
            "search.pyから検索結果が返されませんでした。"
        )

    print("資料検索が完了しました。\n")

    return search_result
async def main() -> None:
    # OpenAIクライアント
    skills_provider = SkillsProvider.from_paths(
    #フォルダからSKiLLを見つけ変数に格納
        skill_paths=BASE_DIR / "skills",
    # 開発中はSKILL.mdやCSVの変更を毎回反映させる
        disable_caching=True,
    )
    approval_middleware = ToolApprovalMiddleware(
    #Agentを実行するのに実行を許可するか確認
        auto_approval_rules=[
    #どのツールを用いてよいのかを指定
            SkillsProvider.read_only_tools_auto_approval_rule
        ],
    #読み取り専用ツールを自動承認するルールをMiddlewareに引き渡す
    )
    client = OpenAIChatClient()

    # 資料検索と検証を担当
    researcher = Agent(
    client=client,
    name="Researcher",
    description="SKILL.mdと検索済みの歯科資料を調査し、根拠を整理します。",
    instructions=(
        "あなたは歯科資料の調査担当です。"
        "ユーザーメッセージには、LlamaIndexによる検索結果が含まれています。"
        "検索結果のresultsにあるcontentだけを根拠にしてください。"
        "最初の発言から具体的な調査結果を提示してください。"
        "「これから調べます」「少々お待ちください」などとは回答しないでください。"
        "質問に関連するSkillがある場合は、必ずそのSkillを読み込んでください。"
        "資料にない時間、回数、効果などを追加しないでください。"
        "根拠として使用したsourceを必ず列挙してください。"
        "施設名、部屋名、A棟、B棟、階数が回答に含まれる場合は、"
        "フロアマップ資料に記載された対応画像の相対パスも正確に列挙してください。"
        "Writerがすでに回答している場合は、その回答と検索結果を比較し、"
        "資料にない記述や誤りを指摘してください。"
    ),
        context_providers=[skills_provider],
    #skill providerをAgentに渡す
         middleware=[approval_middleware],
    #middlewareをAgentに引き渡す
)

    # Researcherの内容を文章化
    writer = Agent(
    client=client,
    name="Writer",
    description="Researcherの調査結果から最終回答を作成します。",
    instructions=(
        "あなたは回答作成担当です。"
        "Researcherが提示した検索結果と調査結果だけを根拠にしてください。"
        "資料に書かれていない時間、頻度、数値、効果を追加しないでください。"
        "根拠がない内容は削除してください。"
        "最初の発言では回答案を作成してください。"
        "Researcherによる確認結果がある場合は、指摘を反映して修正してください。"
        "回答の最後に、実際のsourceファイル名を列挙してください。"
        "『一般的なガイドライン』のような曖昧な出典名は使わないでください。"
    ),
)

    # Group Chatを作成
    workflow = GroupChatBuilder(
        participants=[
            researcher,
            writer,
        ],
    

        # Researcher、Writerの合計発言数が4回で終了
        termination_condition=reached_maximum_rounds,

        # 奇数Researcher、偶数Writer
        selection_func=select_next_speaker,

        # 両方の発言をストリーミング出力する
        intermediate_output_from=[
            researcher,
            writer,
        ],
    ).build()

    question = "初診相談はどこで出来る？"

    print(f"質問：{question}")

    # Group Chatを開始する前に資料を検索
    search_result = search_documents(
        question=question,
        top_k=5,
    )
    skill_instructions=load_skill_instructions()

    # 質問と検索結果をResearcherへ渡す
    task = (
        "以下の質問に、検索結果だけを根拠として回答してください。\n\n"
        f"【ユーザーの質問】\n{question}\n\n"
        f"【LlamaIndexによる検索結果】\n{search_result}\n\n"
        f"【SKILL.md】\n{skill_instructions}\n\n"
        "【必須ルール】\n"
        "- Researcherは最初の発言から検索結果を整理する\n"
        "- 「これから調べます」とは回答しない\n"
        "- results内のcontentだけを根拠にする\n"
        "- 資料にない数値、時間、頻度、効果を追加しない\n"
        "- 使用したsourceを正確に記載する\n"
        "- 施設名、部屋名、棟、階が含まれる場合は、資料にある画像の相対パスも記載する\n"
    )

    print("Group Chatを実行しています...\n")

    current_author: str | None = None
    researcher_chunks: list[str] = []
    latest_writer_chunks: list[str] = []

    stream = workflow.run(
        task,
        stream=True,
    )

    async for event in stream:
        if event.type not in ("intermediate", "output"):
            continue

        data = event.data

        if not isinstance(data, AgentResponseUpdate):
            continue

        author_name = data.author_name

        if author_name not in ("Researcher", "Writer"):
            continue

        text_chunk = data.text or ""

        if author_name != current_author:
            if current_author is not None:
                print("\n")

            print(f"===== {author_name} =====")

            if author_name == "Writer":
                latest_writer_chunks = []

            current_author = author_name

        print(
            text_chunk,
            end="",
            flush=True,
        )

        if author_name == "Writer":
            latest_writer_chunks.append(text_chunk)
        elif author_name == "Researcher":
            researcher_chunks.append(text_chunk)

    await stream.get_final_response()

    researcher_output = "".join(researcher_chunks).strip()
    final_answer = "".join(latest_writer_chunks).strip()
    floor_maps = load_floor_maps()
    matched_floor_maps = find_floor_maps_in_researcher_output(
        researcher_output=researcher_output,
        floor_maps=floor_maps,
    )

    print("\n\n===== 最終回答 =====")

    if matched_floor_maps:
        print(format_floor_map_output(matched_floor_maps))
        show_floor_map_images(matched_floor_maps)
    elif final_answer:
        print(final_answer)
    else:
        print("Writerの最終回答を取得できませんでした。")

if __name__ == "__main__":
    asyncio.run(main())
