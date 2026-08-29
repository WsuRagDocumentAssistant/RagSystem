
#================================================
# document_functions.py
#================================================

from taskcontroller import work_regist, tasks
from data_functions import db_call   # DB 호출은 예외처리까지 묶여 있다

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
        "file_path": TEST_FILE_PATH,
        "work_category": TEST_WORK_CATEGORY,
        "p_task_name": TEST_TASK_NAME,      # task_name 이 아니라 p_task_name 이다
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
