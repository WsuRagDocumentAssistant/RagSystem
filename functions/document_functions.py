
#================================================
# document_functions.py
#================================================

from taskcontroller import work_regist, tasks
from functions.data_functions import db_call, _to_millis   # DB 호출은 예외처리까지 묶여 있다
from functions.rag_functions import UploadStep, _step_in       # 업로드 체인이 meta 를 나르는 방법

# 통신모듈 붙기 전까지 첫 work 에 입력을 넣어주는 자리
TEST_DOCUMENT_ID     = 14
TEST_PRODUCTION_YEAR = 2025
TEST_FILE_PATH       = "documents/테스트문서.hwpx"
TEST_WORK_CATEGORY   = "교육"
TEST_TASK_NAME       = "자체평가"
TEST_DEPARTMENT      = "기획처"
TEST_REPORT_TYPE     = "결과보고서"
TEST_FILENAME_QUERY  = "테스트"

#────────────────────────────────────────────────

# 문서 CRUD
tasks["register_document"]             = ["test_document_input", "register_document"]
tasks["get_document"]                  = ["test_document_id", "get_document"]
tasks["list_documents"]                = ["list_documents"]
tasks["search_documents_by_filename"]  = ["test_filename_query", "search_documents_by_filename"]
tasks["update_document"]               = ["test_document_update_input", "update_document"]
tasks["delete_document"]               = ["test_document_id", "delete_document"]
# 드롭다운 옵션 (입력 없음)
tasks["get_work_category_options"]     = ["get_work_category_options"]
tasks["get_task_name_options"]         = ["get_task_name_options"]
tasks["get_department_options"]        = ["get_department_options"]
tasks["get_report_type_options"]       = ["get_report_type_options"]

#------------------------------------------------┌> dummy function

# 등록용 입력. 그대로 register_document 의 kwargs 가 된다
@work_regist("test_document_input")
def test_document_input(*args, **kwargs):
    return {
        "production_year": TEST_PRODUCTION_YEAR,
        "source_path": TEST_FILE_PATH,
        "work_category": TEST_WORK_CATEGORY,
        "task": TEST_TASK_NAME,             # task_name 이 아니라 task 다
        "department": TEST_DEPARTMENT,
        "report_type": TEST_REPORT_TYPE,
    }

# 수정용 입력. id 가 더 붙는다
@work_regist("test_document_update_input")
def test_document_update_input(*args, **kwargs):
    return {
        "id": TEST_DOCUMENT_ID,
        "production_year": TEST_PRODUCTION_YEAR,
        "work_category": TEST_WORK_CATEGORY,
        "p_task_name": TEST_TASK_NAME,
        "department": TEST_DEPARTMENT,
        "report_type": TEST_REPORT_TYPE,
    }

# 단건 조회 / 삭제용 id
@work_regist("test_document_id")
def test_document_id(*args, **kwargs):
    return TEST_DOCUMENT_ID

# 파일명 검색어
@work_regist("test_filename_query")
def test_filename_query(*args, **kwargs):
    return TEST_FILENAME_QUERY

#------------------------------------------------┌> document func

# 문서 등록. 분류값 옵션 테이블 upsert 는 DB 함수가 알아서 한다
@work_regist("register_document")
def register_document(*args, **kwargs):
    registered_document = db_call("register_document", **args[0])
    return registered_document

# 단건 조회
@work_regist("get_document")
def get_document(*args, **kwargs):
    selected_document = db_call("get_document", id=args[0])
    return selected_document

# 목록 조회 (최근 등록순, 기본 50건)
@work_regist("list_documents")
def list_documents(*args, **kwargs):
    document_list = db_call("list_documents")
    print(f" db 적용됐는지 확인하는 코드입니다{document_list}")
    return document_list

# 파일명 부분일치 검색
@work_regist("search_documents_by_filename")
def search_documents_by_filename(*args, **kwargs):
    searched_documents = db_call("search_documents_by_filename", query=args[0])
    return searched_documents

# 문서 수정. 수정된 id 를 돌려준다
@work_regist("update_document")
def update_document(*args, **kwargs):
    updated_document_id = db_call("update_document", **args[0])
    return updated_document_id

# 문서 삭제. 삭제된 id 를 돌려준다
@work_regist("delete_document")
def delete_document(*args, **kwargs):
    deleted_document_id = db_call("delete_document", id=args[0])
    return deleted_document_id

#------------------------------------------------┌> dropdown option func

@work_regist("get_work_category_options")
def get_work_category_options(*args, **kwargs):
    return db_call("get_work_category_options")

@work_regist("get_task_name_options")
def get_task_name_options(*args, **kwargs):
    return db_call("get_task_name_options")

@work_regist("get_department_options")
def get_department_options(*args, **kwargs):
    return db_call("get_department_options")

@work_regist("get_report_type_options")
def get_report_type_options(*args, **kwargs):
    return db_call("get_report_type_options")

#────────────────────────────────────────────────┌> 통신부 task (명세 task_type)

tasks["FILE_LIST"]     = ["list_documents", "file_list_output"]   # payload 없음
tasks["FILE_DELETE"]   = ["file_id_input", "delete_document", "file_delete_output"]
tasks["FILE_DOWNLOAD"] = ["file_id_input", "get_document", "file_download_output"]
# get_document 를 거치지 않는다. list_document_images 가 document_id 로 바로 찾는다
# (제목으로 찾던 우회가 없어졌다).
tasks["FILE_IMAGE_LIST"] = ["file_id_input", "list_document_images",
                            "file_image_list_output"]
# update_document_image 가 image_name·image_path 를 필수로 받는다. 저장 전에 현재
# 행을 읽어와야 그 두 값을 그대로 넘길 수 있다 — 안 넘기면 NULL 로 덮여 이미지를 잃는다.
tasks["FILE_IMAGE_SAVE"] = ["file_image_save_input", "get_document_image",
                            "save_document_image", "file_image_save_output"]


@work_regist("file_id_input")
def file_id_input(*args, **kwargs):
    """payload {fileId} -> 문서 id.

    삭제·다운로드가 받는 모양이 같아서 하나로 쓴다. 서로 달라지면 그때 나눈다.

    명세는 fileId 를 문자열로 보내는데 DB 는 정수 id 다. 문자열 그대로 넘기면
    프로시저가 에러 없이 null 을 돌려준다(실측). 그래서 숫자면 정수로 바꾼다.
    """
    file_id = (args[0].get("payload") or {})["fileId"]

    # 문서 id 는 정수다. 클라이언트가 업로드 응답을 못 받으면 자기가 만든 임시 id
    # ("tmp-1788139009759-ptze")를 그대로 보내는데, 그걸 통과시키면 DB 가 거절하고
    # 우리는 success 에 빈 값을 실어 보내게 된다 — 클라이언트는 성공인 줄 안다.
    # 여기서 막아 무엇이 잘못됐는지 알려준다.
    if not str(file_id).isdigit():
        raise ValueError(
            f"올바른 문서 id 가 아닙니다: {file_id!r}. "
            "업로드 응답을 받지 못해 임시 id 를 보내고 있는지 확인하세요.")
    return int(file_id)


@work_regist("file_list_output")
def file_list_output(*args, **kwargs):
    """DB 행 목록 -> 클라이언트가 읽는 모양.

    다른 _LIST 와 달리 배열 그 자체를 돌려준다. 클라이언트가 result 를 그대로
    files 상태에 넣고 map 을 돌린다(AppState.fetchFiles).
    """
    rows = args[0] or []

    # DB 의 filename 은 hwpx 내부 이름이라 확장자가 없다(실측). 그대로 내보내면
    # 클라이언트가 그 이름으로 파일을 저장해 확장자 없는 파일이 떨어진다.
    # documents/ 에 원본이 있으면 실제 파일명(확장자 포함)을 쓴다.
    disk = _document_files_by_stem()

    return [
        {
            "id": str(row.get("id")),
            "name": _display_name(row, disk),
            "workCategory": row.get("work_category"),
            "task": row.get("task_name"),
            "department": row.get("department"),
            "reportType": row.get("report_type"),
            "productionYear": row.get("production_year"),
            # 클라이언트는 숫자 timestamp 로 읽는다.
            "uploadedAt": _to_millis(row.get("registered_at")),
            # list_documents 가 SELECT * 라, 테이블에 컬럼이 생기면 그대로 실려 온다.
            # 아직 없으면 None 이고 클라이언트는 빈 값으로 표시한다.
            "size": row.get("size"),
            "mimeType": row.get("mime_type"),
            # status 는 명세상 선택이고 저장할 값이 없다. 목록에 있으면 색인이 끝난
            # 문서라 ready 말고 다른 값이 될 수 없다 — 클라이언트 기본값에 맡긴다.
        }
        for row in rows
    ]


@work_regist("file_delete_output")
def file_delete_output(*args, **kwargs):
    """삭제된 id -> {}.

    클라이언트는 이 결과를 읽지 않는다(FileService.deleteFile 이 반환값을 버린다).
    그래도 dict 을 돌려주는 이유는 TaskResponse.result 가 dict 만 받기 때문이다 —
    id 를 그대로 내보내면 pydantic 이 거부해서 응답이 500 으로 터진다.
    """
    return {}


#────────────────────────────────────────────────┌> 파일 업로드

import base64
import os
import re

# 업로드된 원본이 쌓이는 곳. TEST_FILE_PATH 가 가리키던 자리와 같다.
DOCUMENT_DIR = os.environ.get("RAG_DOCUMENT_DIR", "documents")

# 색인이 먼저다. register_document 는 임베딩된 문서에만 분류값을 붙일 수 있다.
# 색인이 먼저다 — register_document 는 임베딩된 문서에만 분류값을 붙일 수 있다.
# 업무 분류값(meta)은 UploadStep 에 실려 단계 사이를 통과한다(rag_functions).
tasks["FILE_UPLOAD"] = ["file_upload_input",
                        "parse_function", "chunk_function",
                        "vocab_function", "filter_vocab_function", "save_vocab_function",
                        "embed_function", "save_function", "register_images",
                        "file_upload_register"]
# get_vocab 은 DB 원본(word/replacement)을 그대로 준다. 클라이언트는 term/synonyms 로
# 읽으므로 변환 단계를 뒤에 붙인다(data_functions 의 dictionary_list_output).
tasks["DICTIONARY_LIST"] = ["get_vocab", "dictionary_list_output"]

def _safe_name(name: str) -> str:
    """경로 구분자와 상위 이동을 걷어낸다.

    이름은 클라이언트가 보내는 값이라 그대로 믿고 열면 "../../" 로 아무 데나 쓸 수
    있다. 파일명만 남기고 남은 위험한 문자도 지운다.
    """
    name = os.path.basename(name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "", name).strip(". ")
    if not name:
        raise ValueError("파일 이름이 비어 있습니다.")
    return name


@work_regist("file_upload_input")
def file_upload_input(*args, **kwargs):
    """payload 의 base64 를 파일로 떨구고, register_document 가 받는 dict 을 만든다.

    색인(파싱·임베딩)은 여기서 하지 않는다. 클라이언트 XHR 타임아웃이 60초인데
    임베딩만 수백 초라 반드시 실패한다. 등록을 먼저 해두면 나중에 같은 source_path
    로 색인할 때 프로시저가 그 행의 RAG 컬럼만 채우고 분류값은 보존한다.
    """
    payload = args[0].get("payload") or {}
    name = _safe_name(payload.get("name"))
    content = payload.get("content")
    if not content:
        raise ValueError("파일 내용(content)이 비어 있습니다.")

    os.makedirs(DOCUMENT_DIR, exist_ok=True)
    path = os.path.join(DOCUMENT_DIR, name)
    raw = base64.b64decode(content)
    with open(path, "wb") as f:
        f.write(raw)
    print(f"[file_upload_input] 저장: {path} ({len(raw):,} bytes)")

    # 이 뒤로는 meta 를 UploadStep 에 실어 나른다. 체인이 값 하나만 넘기는데
    # 마지막 단계(register_document)가 분류값을 필요로 하기 때문이다.
    # register_document 가 **kwargs 로 받는 키 이름에 맞춘다(클라이언트는 camelCase).
    # production_year 는 프로시저가 정수로 받는다. 클라이언트는 문자열로 보내는데
    # 그대로 넘기면 db_call 이 예외를 삼키고 None 을 돌려줘 조용히 등록이 안 된다.
    year = payload.get("productionYear")
    year = int(year) if year not in (None, "") and str(year).isdigit() else None

    meta = {
        "production_year": year,
        "source_path": path.replace("\\", "/"),
        "work_category": payload.get("workCategory"),
        "task": payload.get("task"),
        "department": payload.get("department"),
        "report_type": payload.get("reportType"),
    }
    # 다음 단계는 parse_function 이다. 값 자리에 파싱할 경로를 넣는다.
    return UploadStep(meta, meta["source_path"])


@work_regist("file_upload_register")
def file_upload_register(*args, **kwargs):
    """색인된 문서에 업무 분류값을 붙이고, 클라이언트가 읽는 {fileId, status, chunks} 로 만든다.

    분류값 등록이 실패해도 업로드를 실패로 만들지 않는다. 색인은 이미 끝났고 문서는
    검색된다 — 분류값이 비어 있을 뿐이라 나중에 수정 화면에서 채우면 된다.
    """
    meta, (document_id, chunks) = _step_in(args)

    # register_document 는 source_path 로 색인된 문서를 찾는다. 그런데 색인이 저장하는
    # source_path 는 우리가 넘긴 업로드 경로가 아니라 hwpx 문서 내부의 제목이다
    # (ragmodul/util.py: file.filename or file.title). 그대로 넘기면 "임베딩된 문서를
    # 찾을 수 없습니다" 로 거절당한다 — 그래서 방금 색인한 행에서 실제 값을 읽어 쓴다.
    row = db_call("get_document", id=document_id) or {}
    source_path = row.get("source_path") or meta.get("source_path")
    meta = {**meta, "source_path": source_path}

    if not db_call("register_document", **meta):
        print(f"[file_upload_register] 분류값 등록 실패(source_path={source_path!r}) — 색인은 완료됨")
    return {"fileId": str(document_id), "status": "ready", "chunks": chunks}



@work_regist("get_vocab")
def list_all_words(*args, **kwargs):
    """검색어 사전을 읽는다.

    list_all_words(word_dictionary 테이블)가 아니라 load_vocab(vocab 테이블)을 본다.
    문서를 올릴 때 뽑은 축약어는 save_vocab_pairs 로 vocab 에 들어가고, 질의 확장도
    그걸 쓴다. word_dictionary 는 아무도 채우지 않아서 화면이 늘 비어 있었다.

    load_vocab 은 {축약어: [확장어, ...]} 를 준다(jsonb 라 문자열로 올 수도 있다).
    """
    from functions.rag_functions import load_vocab

    req = args[0] if args and isinstance(args[0], dict) else {}
    search = ((req.get("payload") or {}).get("search") or "").strip()

    vocab = load_vocab() or {}
    print(f"[get_vocab] 사전 {len(vocab)}개" + (f" / 검색 {search!r}" if search else ""))
    return {"entries": vocab, "search": search}


#────────────────────────────────────────────────┌> 다운로드 / 이미지

IMAGE_DIR = os.environ.get("RAG_IMAGE_DIR", "images")


def _document_files_by_stem() -> dict:
    """documents/ 의 파일을 {확장자 뺀 이름: 실제 파일명} 으로 모은다.

    행마다 폴더를 훑지 않도록 한 번만 읽는다.
    """
    from pathlib import Path

    folder = Path(DOCUMENT_DIR)
    if not folder.is_dir():
        return {}
    return {p.stem: p.name for p in folder.iterdir() if p.is_file()}


def _display_name(row: dict, disk: dict) -> str:
    """클라이언트에 보여줄(그리고 저장될) 파일 이름."""
    stem = row.get("filename") or row.get("source_path") or ""
    return disk.get(stem, stem)


def _static_url(path: str, root: str, prefix: str) -> str | None:
    """서버 로컬 경로 -> 브라우저가 열 수 있는 URL.

    main.py 가 /documents 와 /images 를 정적 경로로 내보낸다. 그 아래에 있는 파일만
    URL 로 바꾼다 — 밖의 경로를 그대로 노출하면 서버 파일이 새어 나간다.
    """
    from pathlib import Path
    from urllib.parse import quote

    if not path:
        return None
    try:
        rel = Path(path).resolve().relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return None
    return f"{prefix}/" + quote(rel.as_posix())


def _find_document_file(row: dict):
    """DB 행에 대응하는 원본 파일을 documents/ 에서 찾는다. 없으면 None.

    경로를 그대로 쓸 수 없다. 색인이 저장하는 source_path 는 우리가 넘긴 업로드
    경로가 아니라 hwpx 내부 이름이고, 확장자도 폴더도 없다(실측: 파일이
    "documents/보고서.hwpx" 여도 source_path 는 "보고서").

    그래서 이름(stem)이 같은 파일을 폴더에서 찾는다. 업로드하지 않고 색인만 된
    문서는 애초에 원본이 없으므로 None 이 맞다.
    """
    from pathlib import Path

    stem = (row.get("source_path") or row.get("filename") or "").strip()
    if not stem:
        return None

    stem = Path(stem).stem          # 혹시 확장자가 붙어 와도 벗긴다
    folder = Path(DOCUMENT_DIR)
    if not folder.is_dir():
        return None

    for path in folder.iterdir():
        if path.is_file() and path.stem == stem:
            return path
    return None


@work_regist("file_download_output")
def file_download_output(*args, **kwargs):
    """문서 행 -> 클라이언트가 읽는 {url}.

    업로드로 들어온 문서만 원본 파일이 있다. 색인만 된 문서는 url 이 비어 나간다 —
    클라이언트가 다운로드 버튼을 눌러도 받을 게 없다는 뜻이다.
    """
    row = args[0] or {}
    path = _find_document_file(row)
    if path is None:
        print(f"[file_download_output] 원본 파일 없음: {row.get('source_path')!r}")
        return {"url": None}

    return {"url": _static_url(str(path), DOCUMENT_DIR, "/api/documents")}


@work_regist("list_document_images")
def list_document_images(*args, **kwargs):
    """문서 id -> (문서 id, 이미지 행 목록)."""
    document_id = args[0]
    rows = db_call("list_document_images", document_id=document_id) or []
    return document_id, rows


@work_regist("file_image_list_output")
def file_image_list_output(*args, **kwargs):
    """이미지 행 목록 -> 클라이언트가 읽는 {images:[...]}.

    DB 컬럼은 스네이크, 클라이언트는 camelCase 다. 여기서 맞춘다.
    key_facts·key_phrases 는 text[] 라 그대로 배열로 온다.
    """
    document_id, rows = args[0]

    images = [
        {
            "id": str(r.get("id")),
            "index": index,
            "imageUrl": _static_url(r.get("image_path") or "", IMAGE_DIR, "/api/images"),
            "caption": r.get("caption"),
            "majorTitle": r.get("major_title"),
            "midTitle": r.get("mid_title"),
            "minorTitle": r.get("minor_title"),
            "note": r.get("note"),
            "aiSummary": r.get("ai_summary"),
            "keyFacts": r.get("key_facts") or [],
            "keyPhrases": r.get("key_phrases") or [],
        }
        for index, r in enumerate(rows)
    ]
    print(f"[file_image_list_output] 이미지 {len(images)}개 (document_id={document_id})")
    return {"images": images}


# 이미지 설명 필드. 클라이언트 이름 -> DB 컬럼 이름.
# 앞의 여섯은 글(text), 뒤의 둘은 문자열 배열(text[])이다.
IMAGE_TEXT_FIELDS = {
    "caption": "caption",
    "majorTitle": "major_title",
    "midTitle": "mid_title",
    "minorTitle": "minor_title",
    "note": "note",
    "aiSummary": "ai_summary",
}
IMAGE_LIST_FIELDS = {"keyFacts": "key_facts", "keyPhrases": "key_phrases"}


@work_regist("file_image_save_input")
def file_image_save_input(*args, **kwargs):
    """payload {fileId, imageId, ...설명} -> update_document_image 가 받는 dict.

    클라이언트는 바뀐 필드만 보낼 수도, 전부 보낼 수도 있다(이미지 보기 모달의
    저장 버튼). 보내지 않은 필드는 키 자체를 뺀다 — "빈 문자열로 덮어쓰기" 와
    "안 건드림" 을 뒤 단계가 구분할 수 있어야 한다.

    키 이름을 여기서 DB 컬럼으로 바꾼다. 뒤 단계는 넘기기만 하므로 클라이언트
    명세를 몰라도 된다 — file_upload_input 과 같은 방식이다.
    """
    payload = (args[0].get("payload") or {}) if args and isinstance(args[0], dict) else {}

    document_id, image_id = payload.get("fileId"), payload.get("imageId")
    # file_id_input 과 같은 이유로 막는다 — 임시 id 를 통과시키면 성공으로 보인다.
    if not str(document_id).isdigit():
        raise ValueError(f"올바른 문서 id 가 아닙니다: {document_id!r}")
    if not str(image_id).isdigit():
        raise ValueError(f"올바른 이미지 id 가 아닙니다: {image_id!r}")

    fields = {"id": int(image_id), "document_id": int(document_id)}
    for name, column in IMAGE_TEXT_FIELDS.items():
        if name in payload:
            value = payload[name]
            fields[column] = "" if value is None else str(value)
    for name, column in IMAGE_LIST_FIELDS.items():
        if name in payload:
            value = payload[name] or []
            # 클라이언트가 문자열 하나로 보내는 경우도 있어 배열이 아니면 감싼다
            fields[column] = [str(v) for v in (value if isinstance(value, list) else [value])]

    return fields


@work_regist("get_document_image")
def get_document_image(*args, **kwargs):
    """저장할 dict 에 현재 image_name·image_path 를 채워 넣는다.

    update_document_image 가 그 둘을 필수로 받는다. 설명만 고치는 요청에도
    넘겨야 하고, 빠뜨리면 NULL 로 덮여 이미지 파일을 잃는다.
    """
    fields = args[0]
    row = db_call("get_document_image", id=fields["id"])
    if not row:
        raise ValueError(f"이미지를 찾을 수 없습니다: {fields['id']}")

    # 다른 문서의 이미지 id 를 보내 남의 이미지를 고치는 것을 막는다.
    if row.get("document_id") != fields["document_id"]:
        raise ValueError("이 문서의 이미지가 아닙니다.")

    fields["image_name"] = row.get("image_name")
    fields["image_path"] = row.get("image_path")
    return fields


@work_regist("save_document_image")
def save_document_image(*args, **kwargs):
    """이미지 설명을 저장한다. 받은 dict 을 그대로 DB 로 넘긴다.

    앞 단계가 DB 컬럼 이름으로 맞춰 주므로 여기서는 이름을 손대지 않는다.
    document_id 는 update 함수가 받지 않으므로 빼고 넘긴다.
    """
    fields = dict(args[0])
    fields.pop("document_id", None)

    saved = db_call("update_document_image", **fields)
    if not saved:
        raise ValueError("이미지 설명을 저장하지 못했습니다.")
    print(f"[save_document_image] id={fields['id']} 저장 필드={list(fields)}")
    return saved


@work_regist("file_image_save_output")
def file_image_save_output(*args, **kwargs):
    """저장된 행 -> 클라이언트가 읽는 {image:{...}}.

    클라이언트는 응답을 쓰지 않지만(낙관적 반영), 나중에 서버 값으로 되맞출 수
    있도록 저장된 모양 그대로 돌려준다.
    """
    row = args[0]
    return {"image": {
        "id": str(row.get("id")),
        "imageUrl": _static_url(row.get("image_path") or "", IMAGE_DIR, "/api/images"),
        "caption": row.get("caption"),
        "majorTitle": row.get("major_title"),
        "midTitle": row.get("mid_title"),
        "minorTitle": row.get("minor_title"),
        "note": row.get("note"),
        "aiSummary": row.get("ai_summary"),
        "keyFacts": row.get("key_facts") or [],
        "keyPhrases": row.get("key_phrases") or [],
    }}