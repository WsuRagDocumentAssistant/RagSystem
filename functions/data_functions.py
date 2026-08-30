
#================================================
# data_functions.py
#================================================

import asyncio
import logging
import os
from types import SimpleNamespace

from dotenv import load_dotenv

from taskcontroller import work_regist, tasks
from session_data import build_session, Session
from api_data import collect, ApiEntity
import db_manager
from functions.exception_functions import safe_call

load_dotenv()   # .env를 os.environ에 올린다 (없으면 조용히 넘어감)

# 워커가 basicConfig(level=INFO) 로 루트 로거를 열기 때문에 httpx 가 요청마다
# url 을 통째로 찍는다. url 에 인증키가 들어 있어 콘솔에 그대로 노출된다.
logging.getLogger("httpx").setLevel(logging.WARNING)

# 호출할 api 정보 하나. collect() 는 request.url 을 GET 만 하므로 인증키는 url 안에 있어야 한다.
API_TITLE  = os.environ["API_TITLE"]
API_SOURCE = os.environ["API_SOURCE"]
API_KEY    = os.environ["API_KEY"]   # 비밀값
API_URL    = os.environ["API_URL"]   # 인증키가 들어 있어 이것도 비밀값

dbmanager = db_manager.DBManager()
_inited = False


def db():
    """DB를 쓰는 프로세스에서 첫 호출 때 한 번만 연결한다.

    init()을 모듈 최상단에서 부르면 spawn 방식이라 부모·컨트롤러·워커가 각자
    main을 재import 하면서 커넥션 풀을 세 개 연다. 실제로 work를 실행하는 건
    워커뿐이고, DB가 꺼져 있으면 DB와 무관한 태스크까지 시작이 느려진다.
    """
    global _inited
    if not _inited:
        dbmanager.init()
        _inited = True
    return dbmanager 


def db_call(task_name, **kwargs):
    """DB 작업 호출. 실패하면 한 줄 찍고 None 을 돌려준다."""
    return safe_call(db().call, task_name, **kwargs)

#────────────────────────────────────────────────

# session-data
# session insert
tasks["session_insert"] = ["test_session_id", "create_session"]
# session save
tasks["session_save"] = ["test_session_data", "get_session", "insert_db_session_data"]
# session title
tasks["update_session_title"] = ["test_session_title_input", "update_db_session_title"]
# session 확보 / 목록
tasks["get_or_create_session"] = ["test_user_id", "get_or_create_db_session"]
tasks["list_sessions"] = ["test_user_id", "list_db_sessions"]

# api-data
# api insert
tasks["api_insert"] = ["create_api_data", "insert_db_api_data", "embed_api_function"]
# api all update
tasks["api_all_update"] = ["select_all_db_api_data", "update_api_data", "update_db_api_data"]
# api delete
tasks["api_delete"] = ["test_api_url", "delete_db_api_data"]



#------------------------------------------------┌> dummy function

# 통신모듈 붙기 전까지 첫 work 에 입력을 넣어주는 자리
TEST_SESSION_ID = "7ba0535a-eb7d-40d0-813d-fa7f9c1c09b1"
TEST_SESSION_TITLE = "과일 재배 문의"
TEST_USER_ID = "0049c7f8-d327-4b87-878d-20f6f0f8c444"

# session_id 하나
@work_regist("test_session_id")
def test_session_id(*args, **kwargs):
    return TEST_SESSION_ID

# session_id + Session 을 함께 들고 다니는 객체
@work_regist("test_session_data")
def test_session_data(*args, **kwargs):
    session = build_session(
        [{"user_query": "포도는요?", "ai_response": "포도는 여름 끝에 수확합니다..."}],
        "포도 수확기",
        "과일 재배 문의",
    )
    return SimpleNamespace(session_id=TEST_SESSION_ID, session=session)

#------------------------------------------------┌> session insert func

# 세션 객체 생성
@work_regist("create_session")
def create_session_data(*args,**kwargs):
    #session_id가 들어왔다 가정
    messages = db_call("get_recent_messages", session_id=args[0])
    context = db_call("get_session_context", session_id=args[0])
    return build_session(messages, context["current_topic"], context["overall_summary"])

#------------------------------------------------┌> session save func

# 새 세션의 대한 가공은 이전에 이미 되어있다 가정

# 세션 객체 획득
#------------------------------------------------┌> session save func

# 새 세션의 대한 가공은 이전에 이미 되어있다 가정

# 세션 객체 획득
@work_regist("get_session")
def get_session_data(*args, **kwargs):
    #session_id, session
    session_data = args[0]
    return session_data

# DB에 저장
@work_regist("insert_db_session_data")
def insert_db_session_data(*args, **kwargs):
    inserted_message = db_call("insert_message", session_id=args[0].session_id, user_query=args[0].session.recent_conversations[-1]["user_query"], ai_response=args[0].session.recent_conversations[-1]["ai_response"])
    updated_topic = db_call("update_current_topic", session_id=args[0].session_id, topic=args[0].session.current_topic)
    updated_summary = db_call("update_overall_summary", session_id=args[0].session_id, summary=args[0].session.summary)
    return inserted_message, updated_topic, updated_summary

#-----------------------------------------------┌> api func

# api 실제 데이터로 객체 생성
@work_regist("create_api_data")
def api_data(*args, **kwargs) -> ApiEntity:
    request = ApiEntity(title=API_TITLE, url=API_URL, source=API_SOURCE, key=API_KEY)
    return asyncio.run(collect(request))

# DB에 저장, API 결과 리스트 반환
@work_regist("insert_db_api_data")
def insert_db_api_data(*args, **kwargs):
    inserted_api_data = db_call("insert_api_data", title=args[0].title, url=args[0].url, source=args[0].source, key=args[0].key, data=args[0].data, data_type=args[0].data_type)
    return inserted_api_data

#-----------------------------------------------┌> api all update

# 기존 API 전체 조회
@work_regist("select_all_db_api_data")
def select_all_db_api_data(*args, **kwargs):
    return db_call("select_all_api_data")

# 행마다 api 재호출
@work_regist("update_api_data")
def update_api_data(*args, **kwargs):
    updated_entities = []
    for row in args[0]:
        entity = safe_call(lambda: asyncio.run(collect(ApiEntity(title=row["title"], url=row["url"], source=row["source"], key=row["key"]))), label=row.get("title", "api 수집"))
        if entity is not None:
            updated_entities.append(entity)
    return updated_entities

# 갱신된 data 를 url 기준으로 저장
@work_regist("update_db_api_data")
def update_db_api_data(*args, **kwargs):
    updated_api_data = [db_call("update_api_data_date", url=entity.url, data=entity.data) for entity in args[0]]
    return updated_api_data

#-----------------------------------------------┌>  api timer all update



#-----------------------------------------------┌> api delete

# 삭제할 url (통신모듈 붙기 전까지 .env 의 API_URL 을 그대로 쓴다)
@work_regist("test_api_url")
def test_api_url(*args, **kwargs):
    return API_URL

# url 단건 삭제
@work_regist("delete_db_api_data")
def delete_db_api_data(*args, **kwargs):
    deleted_api_data = db_call("delete_api_data", url=args[0])
    return deleted_api_data

#-----------------------------------------------┌> session title func

# session_id, title
@work_regist("test_session_title_input")
def test_session_title_input(*args, **kwargs):
    return TEST_SESSION_ID, TEST_SESSION_TITLE

# 세션 제목 갱신. 갱신된 세션 row 를 돌려준다
@work_regist("update_db_session_title")
def update_db_session_title(*args, **kwargs):
    session_id, title = args[0]
    updated_title = db_call("update_session_title", session_id=session_id, title=title)
    return updated_title

#-----------------------------------------------┌> session user func

# user_id 하나
@work_regist("test_user_id")
def test_user_id(*args, **kwargs):
    return TEST_USER_ID

# 세션 확보. 없거나 타임아웃이면 새로 만든다
@work_regist("get_or_create_db_session")
def get_or_create_db_session(*args, **kwargs):
    session = db_call("get_or_create_session", user_id=args[0])
    return session["session_id"]

# 세션 목록. 최근 활동순
@work_regist("list_db_sessions")
def list_db_sessions(*args, **kwargs):
    session_list = db_call("list_sessions", user_id=args[0])
    return session_list


#────────────────────────────────────────────────┌> 통신부 task (명세 task_type)

tasks["CHAT_SESSION_LIST"] = ["chat_session_list_input", "list_db_sessions",
                              "chat_session_list_output"]


def _to_millis(value):
    """클라이언트가 createdAt 을 숫자 timestamp(ms)로 읽는다. DB 는 datetime 을 준다."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    to_timestamp = getattr(value, "timestamp", None)
    if to_timestamp is not None:            # datetime
        return int(to_timestamp() * 1000)
    # date 는 timestamp() 가 없다. 그날 자정으로 본다 — 목록 정렬에는 그걸로 충분하다.
    if hasattr(value, "year") and hasattr(value, "month"):
        import datetime as _dt
        return int(_dt.datetime(value.year, value.month, value.day).timestamp() * 1000)
    return None


@work_regist("chat_session_list_input")
def chat_session_list_input(*args, **kwargs):
    """요청 -> user_id.

    명세상 payload 가 없고 Authorization 토큰으로 사용자를 식별한다. login_output 이
    지금 user_id 를 토큰으로 내보내고 있어서 그대로 쓸 수 있다 — 토큰 발급 방식이
    바뀌면 여기서 토큰을 user_id 로 바꾸는 단계가 필요하다.

    인자가 없으면(메뉴로 직접 실행) TEST_USER_ID 로 떨어진다.
    """
    req = args[0] if args and isinstance(args[0], dict) else {}
    user_id = req.get("token") or TEST_USER_ID
    if not user_id:
        raise ValueError("사용자를 알 수 없습니다. Authorization 헤더가 필요합니다.")
    return user_id


@work_regist("chat_session_list_output")
def chat_session_list_output(*args, **kwargs):
    """세션 행 목록 -> 클라이언트가 읽는 {sessions:[{sessionId, title, createdAt}]}.

    title 컬럼이 없으면 요약이나 현재 토픽을 대신 쓴다. 그것도 없으면 클라이언트가
    기본값으로 쓰는 문구를 그대로 넣는다.
    """
    rows = args[0] or []
    return {"sessions": [
        {
            "sessionId": str(row.get("session_id")),
            "title": (row.get("title") or row.get("current_topic")
                      or row.get("overall_summary") or "새 대화"),
            "createdAt": _to_millis(row.get("created_at")),
        }
        for row in rows
    ]}


#────────────────────────────────────────────────┌> 통신부 task (대화/사전/외부 API)

tasks["CHAT_SESSION_MESSAGES"] = ["session_id_input", "get_recent_db_messages",
                                  "chat_session_messages_output"]
tasks["DICTIONARY_LIST"]       = ["list_all_db_words", "dictionary_list_output"]
tasks["DICTIONARY_SAVE"]       = ["dictionary_save_input", "save_db_words",
                                  "dictionary_save_output"]
tasks["EXTERNAL_API_LIST"]     = ["select_all_db_api_data", "external_api_list_output"]
tasks["EXTERNAL_API_DELETE"]   = ["api_id_input", "delete_db_api_data_by_id",
                                  "external_api_delete_output"]


@work_regist("session_id_input")
def session_id_input(*args, **kwargs):
    """payload {sessionId} -> session_id. 인자가 없으면 상수로 떨어진다(메뉴 실행)."""
    payload = (args[0].get("payload") or {}) if args and isinstance(args[0], dict) else {}
    return payload.get("sessionId") or TEST_SESSION_ID


@work_regist("get_recent_db_messages")
def get_recent_db_messages(*args, **kwargs):
    return db_call("get_recent_messages", session_id=args[0])


@work_regist("chat_session_messages_output")
def chat_session_messages_output(*args, **kwargs):
    """대화 행 -> 클라이언트가 읽는 {messages:[...]}.

    DB 는 한 행에 (user_query, ai_response) 를 함께 담는데 클라이언트는 role 별로
    메시지 하나씩을 기대한다. 그래서 한 행을 둘로 편다.
    """
    rows = args[0] or []
    messages = []
    for row in rows:
        turn = str(row.get("turn_index") or row.get("message_id") or row.get("id") or "")
        created = _to_millis(row.get("created_at"))
        if row.get("user_query"):
            messages.append({"id": f"{turn}-user", "role": "user",
                             "content": row["user_query"], "createdAt": created,
                             "turnId": turn})
        if row.get("ai_response"):
            messages.append({"id": f"{turn}-assistant", "role": "assistant",
                             "content": row["ai_response"], "createdAt": created,
                             "turnId": turn, "preferred": True})
    return {"messages": messages}


@work_regist("list_all_db_words")
def list_all_db_words(*args, **kwargs):
    """전체 목록을 읽고, 검색어를 다음 단계로 함께 넘긴다.

    search_word 는 정확일치만 되고(부분일치 안 됨) 목록이 작아서, 검색은 여기서
    받아온 목록을 걸러 처리한다.
    """
    req = args[0] if args and isinstance(args[0], dict) else {}
    search = ((req.get("payload") or {}).get("search") or "").strip()
    return search, (db_call("list_all_words") or [])


@work_regist("dictionary_list_output")
def dictionary_list_output(*args, **kwargs):
    """단어 행 -> {entries:[{id, term, synonyms, created_at, updated_at}]}.

    DB 는 word/replacement 로 부르고 클라이언트는 term/synonyms 로 읽는다.

    list_all_words() 가 주는 건 word 와 replacement 뿐이다. id 자리에는 word 를
    넣는다 — word 가 PK 라서 그게 사실상의 식별자이고, 클라이언트가 저장할 때
    돌려주면 그대로 어느 항목인지 알 수 있다. created_at/updated_at 은 컬럼이
    없어서 비워 보낸다.
    """
    # 앞 work 이 무엇이냐에 따라 모양이 다르게 온다.
    #   list_all_db_words -> (검색어, 행 목록)
    #   get_vocab         -> {"entries": 행 목록}
    value = args[0]
    if isinstance(value, tuple):
        search, rows = value
    elif isinstance(value, dict):
        search, rows = "", (value.get("entries") or [])
    else:
        search, rows = "", (value or [])
    entries = []
    for row in rows:
        term = row.get("term") or row.get("word")
        synonyms = row.get("synonyms") or row.get("replacement")
        if search and search not in (term or "") and search not in (synonyms or ""):
            continue
        entries.append({
            "id": term,
            "term": term,
            "synonyms": synonyms,
            "created_at": None,
            "updated_at": None,
        })
    return {"entries": entries}


@work_regist("external_api_list_output")
def external_api_list_output(*args, **kwargs):
    """외부 API 행 -> {apis:[...]}. 키 이름을 클라이언트 쪽(camelCase)으로 바꾼다."""
    rows = args[0] or []
    return {"apis": [
        {
            "id": row.get("url"),          # url 이 PK 다. 삭제·갱신이 이 값으로 걸린다
            "title": row.get("title"),
            "url": row.get("url"),
            "source": row.get("source"),
            "apiKey": row.get("key") or row.get("api_key"),
            "fetchedAt": str(row.get("date") or row.get("fetched_at") or "") or None,
            "refreshIntervalMinutes": row.get("refresh_interval_minutes"),
        }
        for row in rows
    ]}


@work_regist("api_id_input")
def api_id_input(*args, **kwargs):
    """payload {id} -> 외부 API 식별자.

    api_datas 는 url 이 PK 다 — delete_api_data / update_api_data_date /
    save_api_data_vector 가 전부 url 로 건다. 그래서 목록(external_api_list_output)이
    id 자리에 url 을 내보내고, 클라이언트는 그걸 그대로 돌려준다.
    """
    payload = (args[0].get("payload") or {}) if args and isinstance(args[0], dict) else {}
    api_id = payload.get("id")
    if not api_id:
        raise ValueError("payload 에 id 가 없습니다.")
    return api_id


@work_regist("delete_db_api_data_by_id")
def delete_db_api_data_by_id(*args, **kwargs):
    return db_call("delete_api_data", url=args[0])


@work_regist("external_api_delete_output")
def external_api_delete_output(*args, **kwargs):
    return {}


@work_regist("dictionary_save_input")
def dictionary_save_input(*args, **kwargs):
    """payload {entries:[{term, synonyms}]} -> 저장할 짝 목록.

    클라이언트는 화면에 있는 전체 목록을 통째로 보낸다.
    """
    payload = (args[0].get("payload") or {}) if args and isinstance(args[0], dict) else {}
    entries = payload.get("entries") or []
    pairs = [(e.get("term"), e.get("synonyms") or "")
             for e in entries if (e.get("term") or "").strip()]
    if not pairs:
        raise ValueError("payload 에 entries 가 없습니다.")
    return pairs


@work_regist("save_db_words")
def save_db_words(*args, **kwargs):
    """이미 있는 단어는 대체어만 고치고, 없는 단어는 새로 넣는다.

    update_word 는 word 가 PK 라 단어 이름 자체는 못 바꾼다. 삭제도 DB 가 막아둬서
    (word_dictionary 는 삭제 기능을 제공하지 않음) 화면에서 지운 항목은 남는다.
    """
    pairs = args[0]
    existing = {row.get("word") for row in (db_call("list_all_words") or [])}

    added = updated = 0
    for term, synonyms in pairs:
        if term in existing:
            if db_call("update_word", word=term, new_replacement=synonyms) is not None:
                updated += 1
        else:
            if db_call("insert_word", word=term, replacement=synonyms) is not None:
                added += 1
    print(f"[save_db_words] 추가 {added}개, 수정 {updated}개")
    return added, updated


@work_regist("dictionary_save_output")
def dictionary_save_output(*args, **kwargs):
    """클라이언트가 result 를 읽지 않는다. 명세대로 빈 객체."""
    return {}
