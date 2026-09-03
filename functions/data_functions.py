
#================================================
# data_functions.py
#================================================

import asyncio
import uuid
import logging
import os
from types import SimpleNamespace

from dotenv import load_dotenv

from taskcontroller import work_regist, tasks
from session_data import build_session, Session
from api_data import collect, ApiEntity
import db_manager
from functions.exception_functions import safe_call
from utils import from_jsonb

#────────────────────────────────────────────────┌> 테스트 태스크

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

#────────────────────────────────────────────────┌> 실제 태스크

tasks["CHAT_SESSION_LIST"] = ["chat_session_list_input", "list_db_sessions",
                              "chat_session_list_output"]

tasks["CHAT_SESSION_MESSAGES"] = ["session_id_input", "get_recent_db_messages",
                                  "chat_session_messages_output"]

tasks["DICTIONARY_SAVE"]       = ["dictionary_save_input", "save_db_words",
                                  "dictionary_save_output"]

tasks["EXTERNAL_API_LIST"]     = ["select_all_db_api_data", "external_api_list_output"]

tasks["EXTERNAL_API_SAVE"]     = ["create_api_data", "insert_db_api_data",
                                  "embed_api_function", "external_api_save_output"]

tasks["EXTERNAL_API_SYNC"]     = ["api_id_input", "sync_db_api_data",
                                  "external_api_sync_output"]

tasks["EXTERNAL_API_DELETE"]   = ["api_id_input", "delete_db_api_data_by_id",
                                  "external_api_delete_output"]

tasks["CHAT_SESSION_DELETE"] = ["delete_session"]


load_dotenv()   # .env를 os.environ에 올린다 (없으면 조용히 넘어감)

# 워커가 basicConfig(level=INFO) 로 루트 로거를 열기 때문에 httpx 가 요청마다
# url 을 통째로 찍는다. url 에 인증키가 들어 있어 콘솔에 그대로 노출된다.
logging.getLogger("httpx").setLevel(logging.WARNING)


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
    updated_summary = db_call("update_  ", session_id=args[0].session_id, summary=args[0].session.summary)
    return inserted_message, updated_topic, updated_summary

#-----------------------------------------------┌> api func

# api 실제 데이터로 객체 생성
@work_regist("create_api_data")
def api_data(*args, **kwargs) -> ApiEntity:
    """요청 payload 로 외부 API 를 한 건 수집한다.

    통신부(EXTERNAL_API_SAVE)가 클라이언트에서 받은 값을 넘겨준다. 인자가 없으면
    (메뉴로 직접 실행) .env 의 상수로 떨어진다 — 통신부 붙기 전 통로를 남겨둔다.

    클라이언트는 apiKey 로 보내고 ApiEntity 는 key 로 받는다. 여기서 맞춘다.
    """
    payload = (args[0].get("payload") or {}) if args and isinstance(args[0], dict) else {}
    request = ApiEntity(
        title=payload.get("title") ,
        url=payload.get("url") ,
        source=payload.get("source") ,
        key=payload.get("apiKey") or payload.get("key"),
    )
    if not request.url:
        raise ValueError("payload 에 url 이 없습니다.")
    print(f"[create_api_data] 수집: {request.title} ({request.url[:60]})")
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
    # user_id 가 없으면(토큰이 UUID 가 아니면) 조회하지 않는다.
    if not args or args[0] is None:
        return []
    session_list = db_call("list_sessions", user_id=args[0])
    return session_list


#────────────────────────────────────────────────┌> 통신부 task (명세 task_type)



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

    # 토큰이 곧 user_id 인 임시 구조라, 클라이언트가 더미 계정으로 로그인하면
    # "dummy-token-1" 같은 값이 그대로 넘어온다. 그대로 DB 에 던지면 프로시저가
    # invalid UUID 로 거절한다 — 여기서 먼저 걸러 로그를 깨끗하게 유지한다.
    try:
        uuid.UUID(str(user_id))
    except (ValueError, AttributeError, TypeError):
        print(f"[chat_session_list_input] user_id 가 아닌 토큰({user_id!r}) — 빈 목록으로 처리")
        return None

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
                             "turnId": turn, "preferred": True,
                             # 저장 안 된 예전 대화는 NULL 이라 빈 목록이 된다.
                             "sources": from_jsonb(row.get("sources"), [])})
    return {"messages": messages}


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
        search = value.get("search") or ""
        entries = value.get("entries")
        if isinstance(entries, dict):
            # load_vocab 은 {축약어: [확장어, ...]} 를 준다. 화면은 확장어를 한 줄로
            # 본다(synonyms 가 문자열이다).
            rows = [{"word": term,
                     "replacement": ", ".join(exp) if isinstance(exp, list) else str(exp)}
                    for term, exp in entries.items()]
        else:
            rows = entries or []
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


@work_regist("external_api_save_output")
def external_api_save_output(*args, **kwargs):
    """등록된 외부 API -> 클라이언트가 읽는 {api: {...}}.

    앞 단계(embed_api_function)가 url 또는 None 을 준다. 그걸로 방금 넣은 행을
    목록에서 찾아 돌려준다 — insert 반환값을 그대로 쓰면 컬럼 이름이 DB 쪽이라
    클라이언트가 못 읽는다.

    refreshIntervalMinutes 는 api_datas 에 컬럼이 없어 비워 보낸다.
    """
    url = args[0] if args and isinstance(args[0], str) else None
    rows = db_call("select_all_api_data") or []
    row = next((r for r in rows if r.get("url") == url), None) if url else None
    if row is None:
        raise ValueError("등록된 외부 API 를 찾지 못했습니다.")

    return {"api": {
        "id": row.get("url"),               # url 이 PK 다
        "title": row.get("title"),
        "url": row.get("url"),
        "source": row.get("source"),
        "apiKey": row.get("key") or row.get("api_key"),
        "fetchedAt": str(row.get("date") or row.get("fetched_at") or "") or None,
        "refreshIntervalMinutes": None,
    }}


#────────────────────────────────────────────────┌> 대화 세션 (USER_QUERY 체인에 끼움)


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


@work_regist("ensure_session")
def ensure_session(*args, **kwargs):
    """대화 세션을 확보해 요청에 담는다. 질의 체인의 첫 단계다.

    클라이언트가 보낸 session_id 가 있으면 그대로 이어간다. 없으면(새 대화)
    get_or_create_session 으로 만든다 — 그래야 응답의 sessionId 로 돌려줄 수 있고,
    다음 요청부터 같은 대화로 묶인다.

    토큰이 user_id 가 아니면(더미 로그인) 세션 없이 진행한다. 답변은 정상적으로
    나가고 저장만 안 된다 — 그것 때문에 채팅을 막을 이유는 없다.

    req 를 그대로 돌려준다. 뒤 단계(embed_query_function)가 이걸 받는다.
    """
    req = args[0] if args and isinstance(args[0], dict) else {}

    if _is_uuid(req.get("session_id")):
        return req

    user_id = req.get("token")
    if not _is_uuid(user_id):
        print(f"[ensure_session] user_id 가 아닌 토큰({user_id!r}) — 세션 없이 진행")
        return req

    # create_new_session 은 "새채팅" 전용이라 시간과 무관하게 항상 새로 만든다.
    # get_or_create_session 을 쓰면 30분 안에 연 대화가 기존 세션으로 합쳐진다
    # (방을 둘 만들어도 새로고침하면 하나가 됐다).
    created = db_call("create_new_session", user_id=user_id)
    session_id = created.get("session_id") if isinstance(created, dict) else created
    if not session_id:
        print("[ensure_session] 세션 생성 실패 — 세션 없이 진행")
        return req

    req["session_id"] = str(session_id)

    # 제목을 여기서 붙인다. 저장 단계(save_conversation)까지 미루면, 그 사이 답변이
    # 실패한 방이 제목 없이 남는다 — 다음 요청부터는 클라이언트가 이 session_id 를
    # 보내오므로 이 work 이 다시 돌지 않아 영영 무제목이 된다(LLM 오류로 겪었다).
    # 질문은 이 시점에 이미 payload 에 있어 따로 읽을 것이 없다.
    title = ((req.get("payload") or {}).get("query") or "").strip()
    if title:
        db_call("update_session_title", session_id=req["session_id"], title=title[:30])

    print(f"[ensure_session] 새 세션 {req['session_id']} 제목={title[:30]!r}")
    return req

@work_regist("delete_session")
def delete_session(*args, **kwargs):
    """대화 하나를 지운다. 명세대로 빈 객체를 돌려준다.

    session_repo.delete 는 bool 을 준다. 그대로 내보내면 TaskResponse.result 가
    dict 만 받아서 pydantic 이 거부한다.

    실패를 성공으로 넘기지 않는다 — 사용자는 지워진 줄 알고 새로고침에서 다시
    보게 된다. messages.session_id 에 ON DELETE CASCADE 가 없으면 대화가 남은
    세션은 FK 제약으로 삭제되지 않는다.
    """
    req = args[0] if args and isinstance(args[0], dict) else {}
    session_id = (req.get("payload") or {}).get("sessionId")
    if not _is_uuid(session_id):
        raise ValueError(f"올바른 sessionId 가 아닙니다: {session_id!r}")

    deleted = db_call("delete_session", session_id=session_id)
    print(f"[delete_session] {session_id} 삭제 결과: {deleted}")
    if not deleted:
        raise ValueError("대화를 삭제하지 못했습니다. 이미 삭제됐거나 메시지가 남아 있습니다.")
    return {}

@work_regist("save_conversation")
def save_conversation(*args, **kwargs):
    """질문과 답변을 세션에 남긴다. 답변 직후에 끼운다.

    저장에 실패해도 답변은 그대로 내보낸다 — 이미 만들어진 답을 기록 실패 때문에
    버릴 이유가 없다.

    (req, answers) 를 그대로 흘려보낸다. 다음 단계가 user_query_output 이다.
    """
    req, answers, sources = args[0]
    session_id = req.get("session_id")
    if not session_id:
        return req, answers, sources

    query = (req.get("payload") or {}).get("query") or ""
    reply = answers[0]["answer"] if answers else ""

    try:
        # 출처는 answer_function 이 함께 넘겨준 것이다. jsonb 컬럼이라 목록을 그대로
        # 넘기면 db_manager 가 json 문자열로 만들어 보낸다.
        db_call("insert_message", session_id=session_id, user_query=query,
                ai_response=reply, sources=sources)
        print(f"[save_conversation] 세션 {session_id} 에 저장")
    except Exception as e:                                   # noqa: BLE001
        print(f"[save_conversation] 저장 실패, 답변은 그대로 보냄: {type(e).__name__} - {e}")

    return req, answers, sources


@work_regist("sync_db_api_data")
def sync_db_api_data(*args, **kwargs):
    """등록된 외부 API 한 건을 다시 수집해 저장한다. 갱신된 행을 돌려준다.

    api_all_update 는 전체를 훑지만 명세의 EXTERNAL_API_SYNC 는 한 건만 갱신한다.
    url 이 PK 라 목록에서 그 행을 찾아 title/source/key 를 그대로 쓰고 데이터만
    새로 받아온다.
    """
    url = args[0]
    rows = db_call("select_all_api_data") or []
    row = next((r for r in rows if r.get("url") == url), None)
    if row is None:
        raise ValueError(f"등록되지 않은 외부 API 입니다: {url}")

    entity = asyncio.run(collect(ApiEntity(
        title=row.get("title"), url=row.get("url"),
        source=row.get("source"), key=row.get("key"))))

    db_call("update_api_data_date", url=url, data=entity.data)
    print(f"[sync_db_api_data] 갱신: {row.get('title')}")

    # 갱신된 date 를 읽어야 하므로 다시 조회한다
    rows = db_call("select_all_api_data") or []
    return next((r for r in rows if r.get("url") == url), row)


@work_regist("external_api_sync_output")
def external_api_sync_output(*args, **kwargs):
    """갱신된 행 -> 클라이언트가 읽는 {fetchedAt}."""
    row = args[0] or {}
    fetched = row.get("date") or row.get("fetched_at")
    return {"fetchedAt": str(fetched) if fetched else None}


