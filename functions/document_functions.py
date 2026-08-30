
#================================================
# document_functions.py
#================================================

from taskcontroller import work_regist, tasks
from functions.data_functions import db_call   # DB 호출은 예외처리까지 묶여 있다

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
tasks["FILE_DOWNLOAD"] = ["file_id_input", "get_document"]


@work_regist("file_id_input")
def file_id_input(*args, **kwargs):
    """payload {fileId} -> 문서 id.

    삭제·다운로드가 받는 모양이 같아서 하나로 쓴다. 서로 달라지면 그때 나눈다.

    명세는 fileId 를 문자열로 보내는데 DB 는 정수 id 다. 문자열 그대로 넘기면
    프로시저가 에러 없이 null 을 돌려준다(실측). 그래서 숫자면 정수로 바꾼다.
    """
    file_id = (args[0].get("payload") or {})["fileId"]
    return int(file_id) if str(file_id).isdigit() else file_id


@work_regist("file_list_output")
def file_list_output(*args, **kwargs):
    """DB 행 목록 -> 클라이언트가 읽는 모양.

    다른 _LIST 와 달리 배열 그 자체를 돌려준다. 클라이언트가 result 를 그대로
    files 상태에 넣고 map 을 돌린다(AppState.fetchFiles).
    """
    rows = args[0] or []
    return [
        {
            "id": str(row.get("id")),
            "name": row.get("filename") or row.get("source_path") or "",
            "workCategory": row.get("work_category"),
            "task": row.get("task_name"),
            "department": row.get("department"),
            "reportType": row.get("report_type"),
            "productionYear": row.get("production_year"),
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
tasks["FILE_UPLOAD"] = ["file_upload_input", "file_upload_index", "file_upload_register"]
tasks["DICTIONARY_LIST"] = ["get_vocab"]

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

    # register_document 가 **kwargs 로 받는 키 이름에 맞춘다(클라이언트는 camelCase).
    # production_year 는 프로시저가 정수로 받는다. 클라이언트는 문자열로 보내는데
    # 그대로 넘기면 db_call 이 예외를 삼키고 None 을 돌려줘 조용히 등록이 안 된다.
    year = payload.get("productionYear")
    year = int(year) if year not in (None, "") and str(year).isdigit() else None

    return {
        "production_year": year,
        "source_path": path.replace("\\", "/"),
        "work_category": payload.get("workCategory"),
        "task": payload.get("task"),
        "department": payload.get("department"),
        "report_type": payload.get("reportType"),
    }


@work_regist("file_upload_register")
def file_upload_register(*args, **kwargs):
    """색인된 문서에 업무 분류값을 붙이고, 클라이언트가 읽는 {fileId, status, chunks} 로 만든다.

    분류값 등록이 실패해도 업로드를 실패로 만들지 않는다. 색인은 이미 끝났고 문서는
    검색된다 — 분류값이 비어 있을 뿐이라 나중에 수정 화면에서 채우면 된다.
    """
    document_id, meta, chunks = args[0]
    if not db_call("register_document", **meta):
        print("[file_upload_register] 분류값 등록 실패 — 색인은 완료됨")
    return {"fileId": str(document_id), "status": "ready", "chunks": chunks}



@work_regist("get_vocab")
def list_all_words(*args, **kwargs):
        vocab =db_call("list_all_words")
        print(f"[list_all_words] DB 단어 추출 — {(vocab)}")
        return {"entries": vocab}

