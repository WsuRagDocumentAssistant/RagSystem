
#================================================
# rag_functions.py
#================================================
"""
RAG 파이프라인 work 등록.

work 는 TaskExecutor 프로세스 안에서 실행된다. spawn 방식에서는 자식이 main 을
재import 하므로, RagController 를 모듈 레벨에서 만들면 프로세스마다 임베딩·리랭커
모델을 각각 로드한다. 그래서 첫 호출 시점에 한 번만 만든다.

파싱·청킹은 모델도 DB도 필요 없으므로 ragmodul 이 따로 열어둔 parse()/chunk() 를
직접 쓴다. RagController 를 거치면 생성자에서 모델 두 개를 올리기 때문에, 파싱만
보고 싶을 때도 그게 전부 떠 있어야 한다.

DB 는 RagController 를 거치지 않는다(use_db=False). 저장 프로시저를 data_functions
의 db_call 로 직접 부른다 — 스키마가 바뀌어도 프로시저가 흡수한다.

입력값(문서 경로·질의문)은 모듈 상수/환경변수로 준다. TaskExecutor 가 task() 를
인자 없이 호출하는 데다 워커가 별 프로세스라, main 에서 값을 넣어도 워커까지
넘어가지 않는다. 환경변수는 spawn 시점에 상속되므로 넘어간다.
"""

import logging
import os
import threading
import typing

from taskcontroller import work_regist, tasks
from ragmodul import RagController, chunk, parse
from ragmodul.util import document_to_payload, to_plain_sparse, to_plain_vector
from functions.data_functions import db_call   # DB 호출은 예외처리까지 묶여 있다
from utils import from_jsonb, static_url, resolve_image_path, IMAGE_DIR, UNPACK_DIR

logger = logging.getLogger(__name__)

#────────────────────────────────────────────────┌> 테스트 태스크

# 질의 검색은 세 task 가 공유한다. 세 번 적으면 한 곳만 고치고 어긋난다.
QUERY_CHAIN = ["embed_query_function", "hybrid_search_function", "rerank_function"]

tasks.update({
    "test_레그준비": ["warmup_function"],                          # 모델 미리 올리기
    "test_레그청킹": ["parse_function", "chunk_function"],          # 모델·DB 없이 확인용
    "RAG": ["parse_function", "chunk_function",
                    "vocab_function", "filter_vocab_function", "save_vocab_function",
                    "embed_function", "save_function"],
    "test_레그검색": QUERY_CHAIN,          
    "test_레그질의": QUERY_CHAIN + ["search_api_function", "history_function", "answer_function"],
    "test_레그질의병합": QUERY_CHAIN + ["search_api_function", "history_function",
                                        "answer_function", "merge_function"],
    "RAG_Search": QUERY_CHAIN + ["search_api_function", "history_function", "answer_function"],
    "Merge": ["merge_function"],
})

#────────────────────────────────────────────────┌> 실제 태스크

# 앞에 ensure_session, 뒤에 save_conversation 을 끼운다. 그래야 대화가 세션으로
# 묶이고 사이드바 목록과 메시지 내역이 채워진다.
tasks["USER_QUERY"]    = (["ensure_session"] + QUERY_CHAIN
                          + ["search_api_function", "history_function",
                             "search_images_function", "answer_function",
                             "save_conversation", "user_query_output"])

tasks["MERGE_RESULTS"] = ["merge_function", "save_merged", "merge_output"]

# 클라이언트가 대화 차례를 세어 창을 넘기면 부른다. 질의와 별도 요청이라 답변이
# 늦어지지 않는다.
tasks["CHAT_SESSION_COMPRESS"] = ["session_id_input", "compress_session",
                                  "compress_output"]


#────────────────────────────────────────────────

# 로컬 모델 폴더. 리랭커는 local_files_only 로 로드하므로 실제 폴더여야 한다.
EMBEDDING_MODEL_PATH = os.environ.get("RAG_EMBEDDING_MODEL", "models/bge-m3")
RERANKER_MODEL_PATH = os.environ.get("RAG_RERANKER_MODEL", "models/bge-reranker-v2-m3")

# None 이면 라이브러리 자동 감지. GPU 가 있으면 "cuda" 를 명시하는 편이 낫다
# (안 주면 가중치가 CPU 에 남아 배치마다 복사된다).
def _default_device() -> str | None:
    """GPU 가 있으면 "cuda", 없으면 None(=라이브러리 자동 감지).

    device 를 안 넘기면 가중치가 CPU 에 남고 연산할 때만 GPU 로 복사된다 —
    ragmodul 이 실측으로 확인해 문서에 적어둔 동작이다. 매 배치마다 복사가 일어나서
    GPU 를 붙여놓고도 제 속도가 안 나온다. 그래서 있으면 명시해 올려둔다.

    torch import 는 여기서 한다. 모듈을 읽는 것만으로 무거운 import 를 하지 않도록.
    """
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else None
    except Exception:                      # torch 가 없거나 깨져 있어도 죽지 않는다
        return None


# RAG_DEVICE 로 강제할 수 있다("cuda" / "cuda:1" / "cpu"). 없으면 위 규칙을 따른다.
DEVICE = os.environ.get("RAG_DEVICE") or _default_device()

HWPX_FILE_PATH = os.environ.get("RAG_HWPX_FILE", "C:/Users/user/Desktop/RagSystem/test_file/2주기(2023년) 2022 ~ 2024 대학혁신지원사업 성과평가보고서.hwpx")

QUERY = os.environ.get("RAG_QUERY", "솔드림에 대해 설명해줘")

TOP_K_SEARCH = int(os.environ.get("RAG_TOP_K_SEARCH", "40"))     # 조각. 넉넉히 뽑는다
TOP_K_FINAL = int(os.environ.get("RAG_TOP_K_FINAL", "5"))        # LLM 에 실을 최종 개수

# 답변 초안을 만들 provider. 늘 도는 단계라 비용 0 인 쪽이 맞다. 사용자에게는 안 보이고
# 고를 수 있는 목록에도 없다 — 다듬은 결과만 나간다.
DRAFT_PROVIDER = os.environ.get("RAG_DRAFT_PROVIDER", "local_llm")

# 병합에 쓸 provider. 답변을 낸 것과 달라도 된다 — 판단 작업이라 더 센 모델을 쓸 수 있다.
MERGE_WITH = os.environ.get("RAG_MERGE_WITH") or "gpt"

# 사전 추출은 문서를 통째로 넘긴다. 로컬은 컨텍스트가 8192 토큰이라 안 들어간다.
VOCAB_PROVIDER = os.environ.get("RAG_VOCAB_PROVIDER", "claude")

# 축약어 추출을 몇 자씩 나눠 보낼지. pack_texts 가 부모 조각을 이 상한에 맞춰 묶는다.
# 크게 둘수록 앞뒤로 흩어진 짝을 잘 잇지만, 한 번에 너무 크면 응답이 느려져
# llm_api.timeout(config.json) 에 걸린다 — claude 로 88,000자를 한 번에 보내다 겪었다.
VOCAB_CHUNK_CHARS = int(os.environ.get("RAG_VOCAB_CHUNK_CHARS", "30000"))

# 대화 압축. 최근 KEEP_TURNS 차례는 원문으로 남기고 그보다 앞은 요약에 접어 넣는다.
# history_function 이 읽어 넘기는 차례 수와 같아야 한다 — 다르면 어느 쪽에도 안 실리는
# 구간이 생긴다.
KEEP_TURNS = int(os.environ.get("RAG_KEEP_TURNS", "5"))
# 압축 대상을 찾으려면 창보다 많이 읽어야 한다. 세션 하나의 전체 대화 상한이기도 하다.
COMPRESS_SCAN_TURNS = int(os.environ.get("RAG_COMPRESS_SCAN_TURNS", "100"))
SUMMARY_PROVIDER = os.environ.get("RAG_SUMMARY_PROVIDER", "claude")

# 이미지 설명. hwpx 문서 그림은 절반쯤이 bmp 인데(실측 243장 중 117장) gpt·claude 는
# bmp 를 400 으로 거절한다 — gemini 만 읽는다. 다른 걸 고르면 그 그림들이 통째로 빠진다.
IMAGE_PROVIDER = os.environ.get("RAG_IMAGE_PROVIDER", "gemini")
# 동시에 몇 장을 보낼지. 큰 요청 여럿이 같은 순간에 나가면 429 가 난다(ragmodul 실측).
# extract_vocab_all 이 쓰는 값과 같은 수준으로 잡았다. 429 가 보이면 줄인다.
IMAGE_CONCURRENCY = int(os.environ.get("RAG_IMAGE_CONCURRENCY", "4"))
# 문서 하나에서 설명을 만들 그림의 상한. 문서 앞에서부터 이 장수까지만 LLM 에 보낸다.
# 그 뒤 그림은 등록은 되지만(목록에 보이고 설명을 직접 쓸 수 있다) ai_summary 가
# 없어 이미지 검색에는 안 걸린다. 등록은 LLM 을 안 부르니 비용이 없어 그대로 둔다.
IMAGE_DESCRIBE_MAX = int(os.environ.get("RAG_IMAGE_DESCRIBE_MAX", "40"))

# 그림을 SVG 로 바꿀 provider. 설명과 같은 이유로 gemini 다 — 문서 그림 절반이 bmp 고
# 그걸 읽는 건 gemini 와 로컬뿐인데, 로컬은 SVG 를 그릴 만큼은 아니다.
VECTORIZE_PROVIDER = os.environ.get("RAG_VECTORIZE_PROVIDER", "gemini")


# 질의에 붙일 그림. 검색은 넉넉히 뽑고 그중 몇 장만 응답에 싣는다.
#
# 그림은 모델에 보내지 않는다(색인 때 만든 설명으로 검색만 하고 사용자에게 보여준다).
# 그래서 장수는 답변 시간과 무관하고, 화면에 몇 장까지 보여줄지의 문제다. 전에는 그림을
# 모델에도 실어서 장당 3초씩 늘어나 2장으로 묶어 뒀었다.
# 후보는 넉넉히 뽑고 리랭커가 줄인다. 문서 검색과 같은 방식이다 — 약한 신호(유사도)로
# 미리 자른 뒤 강한 신호(리랭커)에게 남은 것만 주는 건 순서가 거꾸로다.
IMAGE_SEARCH_TOP_K = int(os.environ.get("RAG_IMAGE_SEARCH_TOP_K", "20"))
IMAGE_ATTACH_MAX = int(os.environ.get("RAG_IMAGE_ATTACH_MAX", "5"))

# 이 아래 점수는 버린다. 유사도 검색은 질의가 무엇이든 상위 몇 개를 돌려주므로
# 문턱이 없으면 상관없는 그림이 딸려 나온다.
#
# 코사인 유사도 대신 리랭커 점수로 거른다. 코사인은 절대값을 해석하기 어려운데
# 리랭커 점수는 관련성으로 학습돼서 0~1 로 나온다. 0.01 은 ragmodul 이 문서 맥락으로
# 재서 정한 바닥값이다(무관한 질의 최고점이 0.000445 였다). 이미지 설명으로는 아직
# 재보지 않았으니, 로그의 점수를 보고 조정하면 된다.
IMAGE_MIN_RERANK = float(os.environ.get("RAG_IMAGE_MIN_RERANK", "0.01"))

# 외부 API 검색 개수. 1 이다 — 이건 근거가 아니라 "이런 것도 받아올 수 있다" 는
# 안내라서, 여러 개를 늘어놓으면 답변 끝이 목록이 된다.
TOP_K_API = int(os.environ.get("RAG_TOP_K_API", "1"))

# 외부 API 응답 원문을 프롬프트에 얼마나 실을지. 원문이 수십 KB 일 수 있어 자른다 —
# 다듬기는 클라우드라 컨텍스트는 넉넉하지만 매 질의마다 토큰이 나간다.
API_DATA_CHARS = int(os.environ.get("RAG_API_DATA_CHARS", "20000"))

#────────────────────────────────────────────────┌> test task 등록



#------------------------------------------------┌> 업로드 체인이 나르는 것


class UploadStep(typing.NamedTuple):
    """업로드 체인이 단계 사이로 넘기는 값.

    체인은 값 하나만 넘기는데 마지막 단계(register_document)가 업무 분류값(meta)을
    필요로 한다. 그래서 meta 를 값과 함께 묶어 끝까지 들고 간다.

    RAG 태스크와 메뉴는 값 하나만 넘기므로 각 work 은 두 모양을 다 받는다 —
    _step_in 이 그걸 흡수하고 _step_out 이 원래 모양대로 돌려준다.
    """
    meta: dict
    value: typing.Any


def _step_in(args):
    """(meta, 값) 또는 값 단독 -> (meta 또는 None, 값)."""
    value = args[0] if args else None
    if isinstance(value, UploadStep):
        return value.meta, value.value
    return None, value


def _step_out(meta, value):
    """meta 가 있으면 다시 묶고, 없으면 값만 돌려준다."""
    return UploadStep(meta, value) if meta is not None else value


#------------------------------------------------┌> 지연 생성

_controller: RagController | None = None
# 실행부가 스레드 풀이면 첫 요청 여럿이 동시에 여기 들어온다. 잠금이 없으면 모델을
# 두 벌 올린다(수십 초 × 2, VRAM 도 두 배).
_controller_lock = threading.Lock()


def get_controller() -> RagController:
    """워커 프로세스에서 처음 필요할 때 한 번만 만든다.

    생성자가 임베딩 모델과 리랭커를 올리므로 몇십 초 걸린다.

    use_db=False 다. DB 는 db_call 로 직접 부르므로 여기서 커넥션을 들 이유가 없다.
    실수로 rag.hybrid_search() 같은 걸 부르면 원인이 적힌 ValueError 가 난다.

    LLM 설정은 config.json + .env 가 단일 출처다(cwd 기준). 모델명·엔드포인트·키·
    타임아웃이 거기 다 있어서 여기서 표를 또 만들면 두 곳이 어긋난다.
    """
    global _controller
    if _controller is not None:          # 잠금 없이 먼저 본다. 만들어진 뒤엔 잠글 이유가 없다
        return _controller
    with _controller_lock:
        if _controller is None:
            from ai_rag_comm import load_config

            cfg = load_config()
            _controller = RagController(
                EMBEDDING_MODEL_PATH,
                RERANKER_MODEL_PATH,
                device=DEVICE,
                unpack_dir=UNPACK_DIR,
                image_dir=IMAGE_DIR,
                use_db=False,
                llm_api_config=cfg.llm_api,
                local_llm_config=cfg.local_llm,
                llm_default=DRAFT_PROVIDER,
            )
    return _controller


@work_regist("warmup_function")
def warmup_function(*args, **kwargs):
    """모델을 미리 올려둔다. 첫 질의가 몇십 초 걸리는 걸 앞으로 당긴다."""
    rag = get_controller()
    logger.info(f"[warmup_function] 준비 완료. LLM: {', '.join(rag.llm.providers())}")
    return "ready"

#------------------------------------------------┌> 문서 등록


@work_regist("parse_function")
def parse_function(*args, **kwargs):
    """hwpx -> DocumentModel.

    FILE_UPLOAD 는 앞 work 이 방금 저장한 경로를 넘겨준다. 메뉴로 돌리는 test_ 태스크는
    params 가 None 이라 args 가 비고, 그때는 상수로 떨어진다. 문자열만 경로로 인정한다.

    압축을 푼 자리는 parse 가 스스로 치운다(cleanup=True 기본). 파서가 자기가 푼
    unpacked/<문서명>/ 만 지우므로, 같은 순간에 다른 문서를 파싱하는 스레드의 산출물은
    건드리지 않는다. 전에는 여기서 UNPACK_DIR 을 통째로 비웠는데, 실행부가 스레드 풀이
    되면 남의 파싱 중간 산출물까지 지우게 되어 없앴다. 실패했을 때는 parse 가 남긴다 —
    무엇을 받았는지 열어봐야 하는 경우가 그때다.
    """
    meta, value = _step_in(args)
    file_path = value if isinstance(value, str) and value else HWPX_FILE_PATH
    if not file_path:
        raise ValueError(
            "문서 경로가 비어 있습니다. RAG_HWPX_FILE 환경변수나 "
            "rag_functions.HWPX_FILE_PATH 를 지정하세요."
        )
    logger.info(f"[parse_function] 파싱 시작: {file_path}")
    parsed = parse(file_path, unpack_dir=UNPACK_DIR, image_dir=IMAGE_DIR)
    logger.info(f"[parse_function] 파싱 종료: block {len(parsed.blocks)}개")
    return _step_out(meta, parsed)




@work_regist("chunk_function")
def chunk_function(*args, **kwargs):
    """DocumentModel -> ChunkedDocument (parent/child)."""
    meta, parsed = _step_in(args)
    document = chunk(parsed)
    logger.info(f"[chunk_function] 청킹 종료: parent {len(document.parents)}, "
          f"child {len(document.children())}")
    return _step_out(meta, document)


@work_regist("embed_function")
def embed_function(*args, **kwargs):
    """child 에 dense/sparse 를 채운다. 같은 객체를 돌려주므로 체인이 이어진다.

    forward 를 한 번만 돌린다. 예전에는 dense 와 sparse 를 따로 불러서 같은 텍스트를
    두 번 추론했다 — 실측(child 374개) 530초에서 265초로 줄었다.
    """
    meta, parsed = _step_in(args)
    document = get_controller().embed_bge_m3(parsed)
    logger.info(f"[embed_function] 임베딩 종료: child {len(document.children())}개")
    return _step_out(meta, document)


@work_regist("save_function")
def save_function(*args, **kwargs):
    """색인. save_document_json 프로시저에 통째로 넘긴다.

    document_to_payload 를 쓰는 이유: 프로시저가 읽는 키가 DB 컬럼명(embedding/
    lexical)이 아니라 vector/sparse 다. 이름이 틀리면 에러 없이 NULL 이 들어가서
    개수는 맞는데 embedded 가 0 이 된다(실측으로 겪었다). numpy 도 거기서 걷어낸다.

    같은 source_path 면 프로시저가 RAG 컬럼만 갱신하고 업무 분류값(production_year,
    work_category 등)은 보존한다.
    """
    meta, document = _step_in(args)
    rag = get_controller()

    # 파서는 파일 크기·형식을 모른다(hwpx 내용만 다룬다). 업로드 요청이 들고 온 값을
    # meta 로 받아 여기서 얹는다 — 프로시저가 JSON 에서 size/mime_type 을 꺼내 쓴다.
    # meta 가 없는 경로(RAG 태스크·메뉴)에서는 키가 안 붙고 컬럼이 NULL 로 남는다.
    payload = document_to_payload(document)
    for key in ("size", "mime_type"):
        if meta and meta.get(key) is not None:
            payload[key] = meta[key]
    # 업로드 경로는 file_upload_input 이 만든 'processing' 행을 채운다. document_id 가
    # 있으면 프로시저가 그 행의 RAG 컬럼만 갱신하고 status 를 ready 로 바꾼다. 없으면
    # (RAG 테스트 task) 예전처럼 source_path 로 UPSERT 한다.
    if meta and meta.get("document_id"):
        payload["document_id"] = meta["document_id"]

    document_id = db_call(
        "index_document",
        document=payload,
        sparse_dim=rag.sparse_dimension,
    )
    # db_call 은 실패를 삼키고 None 을 준다. 그대로 흘려보내면 뒤 단계가 document_id
    # None 으로 헛돌고(이미지 등록이 전부 거절됐다) 업로드가 성공으로 응답된다 —
    # 임베딩까지 다 해놓고 검색에 안 잡히는 문서가 생긴다.
    if document_id is None:
        raise ValueError("문서 색인에 실패했습니다. 잠시 후 다시 시도해주세요.")
    logger.info(f"[save_function] 저장 종료: document_id={document_id}, "
          f"child {len(document.children())}개")
    # 업로드 체인은 다음 단계(register_images)가 document 를 봐야 해서 함께 넘긴다.
    # RAG 태스크와 메뉴는 예전처럼 document_id 하나만 받는다.
    return _step_out(meta, (document_id, document)) if meta is not None else document_id

#------------------------------------------------┌> 축약어 사전


@work_regist("vocab_function")
def vocab_function(*args, **kwargs):
    """문서에서 축약어/확장어 짝을 뽑는다. 몇 덩어리로 나눠 동시에 보낸다.

    부모 단위로 쪼개면(호출 32번) 결과가 더 적다 — 문서 앞뒤에 흩어진
    '축약어 ... 풀어쓴 말' 을 못 잇기 때문이다. 그렇다고 전체를 한 번에 보내면
    응답이 느려 timeout 에 걸리고, JSON 파싱이 어긋나면 88,000자를 통째로 다시
    보내게 된다(claude 로 겪었다).

    그래서 pack_texts 로 크게 묶는다. 30,000자면 경계가 두어 곳뿐이라 짝을 잇는 데
    거의 지장이 없고, 호출 하나는 시간 안에 끝난다. extract_vocab_all 이 동시에
    던지므로 걸리는 시간은 가장 느린 하나다.

    로컬 모델은 컨텍스트가 8192 토큰이라 이 크기가 안 들어간다 — 클라우드로 부른다.

    다음 단계들이 문서도 필요하므로 함께 실어 보낸다.
    """
    meta, document = _step_in(args)
    rag = get_controller()

    chunks = rag.pack_texts([parent.content for parent in document.parents],
                            max_chars=VOCAB_CHUNK_CHARS)
    # 조각 하나가 실패해도 나머지는 돌려준다. 중복은 다음 단계(filter_vocab)가 지운다.
    pairs = rag.extract_vocab_all(chunks, provider=VOCAB_PROVIDER)

    logger.info(f"[vocab_function] {sum(len(c) for c in chunks):,}자 "
          f"-> {len(chunks)}덩어리 -> {len(pairs)}짝")
    return _step_out(meta, (pairs, document))


@work_regist("filter_vocab_function")
def filter_vocab_function(*args, **kwargs):
    """못 쓸 짝을 걸러낸다. 모델도 DB 도 안 쓴다.

    지금 gpt 로 뽑으면 거의 안 버린다. 남겨두는 이유는 중복 제거와, 모델이나
    프롬프트를 바꿨을 때의 안전망이다. 버린 것도 이유와 함께 찍어서 규칙이 정상
    항목을 오탐하면 보이게 한다.
    """
    meta, (pairs, document) = _step_in(args)
    kept, dropped = get_controller().filter_vocab(pairs)
    for pair in kept:
        logger.info(f"[filter_vocab_function] {pair.term} -> {pair.expansion}")
    for pair, reason in dropped:
        logger.info(f"[filter_vocab_function] 버림({reason}) {pair.term}")
    return _step_out(meta, (kept, document))


@work_regist("save_vocab_function")
def save_vocab_function(*args, **kwargs):
    """사전을 DB 에 넣는다. 같은 짝을 또 넣어도 안 늘어난다(upsert).

    다음 단계(임베딩)가 문서를 받아야 하므로 문서를 돌려준다.
    """
    meta, (kept, document) = _step_in(args)
    added = db_call(
        "save_vocab_pairs",
        pairs=[{"term": p.term, "expansion": p.expansion} for p in kept],
    )
    logger.info(f"[save_vocab_function] 확장어 {added}개 추가")
    return _step_out(meta, document)


def load_vocab() -> dict:
    """{축약어: [확장어, ...]} 를 읽는다.

    프로시저가 jsonb 를 돌려주는데 asyncpg 가 그걸 문자열로 준다(VocabRepository 의
    반환 설명은 dict 인데 실제로는 str 이다). 여기서 푼다 — 문자열을 그대로 넘기면
    질의 확장이 dict 처럼 순회하다 깨진다. 그쪽이 고쳐도 아래 검사는 그대로 통과한다.
    """
    return from_jsonb(db_call("load_vocab"), {})

#------------------------------------------------┌> 질의 검색


@work_regist("embed_query_function")
def embed_query_function(*args, **kwargs):
    """질의 -> (dense 벡터, sparse 가중치). 체인의 첫 단계라 질의를 상수에서 받는다.

    Task.__call__ 이 첫 함수를 인자 없이 부르므로 args 가 비어 있다.

    사전을 넘기면 질의에 걸리는 축약어의 짝을 덧붙여 임베딩한다. dense·sparse 양쪽에
    같은 확장 질의를 쓴다 — 실측에서 둘 다 좋아졌고 나빠진 사례가 없었다.
    사전이 비면 {} 라 확장이 안 걸리고 예전과 같다.

    다음 단계가 질의 문자열도 필요하므로(리랭킹) 함께 실어 보낸다.
    """
    # 통신부가 붙으면 앞 work 이 질의를 넘겨준다. 메뉴에서 부를 때는 params 가
    # None 이라 상수로 떨어진다. 문자열만 질의로 인정한다 — 숫자 같은 게 들어오면
    # 그대로 임베딩되어 조용히 엉뚱한 검색이 된다.
    req = args[0] if args and isinstance(args[0], dict) else {}
    query = (req.get("payload") or {}).get("query") or QUERY
    if not query or not query.strip():
        raise ValueError("질의가 비어 있습니다. payload.query 를 보내주세요.")

    vocab = load_vocab()
    vector, weights = get_controller().embed_query(query, vocab)
    logger.info(f"[embed_query_function] 사전 {len(vocab)}개 적용 / 질의 {query[:40]!r}")
    return req, query, vector, weights


def _document_ids(req) -> list | None:
    """payload 의 fileIds -> 정수 목록. 없으면 None(전체 검색).

    클라이언트는 문서 id 를 문자열로 보낸다(FILE_LIST 가 준 그대로). DB 는 정수
    배열을 받으므로 바꿔 넘긴다.

    숫자가 아닌 값이 섞이면 거절한다. 업로드 응답을 못 받은 클라이언트가 자기가 만든
    임시 id("tmp-1788139009759")를 보내는 경우가 있는데, 조용히 걸러내면 사용자는
    문서 다섯 개를 골랐다고 믿는 채 네 개만 검색된 답을 받는다.
    """
    file_ids = (req.get("payload") or {}).get("fileIds") if isinstance(req, dict) else None
    if not file_ids:
        return None

    bad = [i for i in file_ids if not str(i).isdigit()]
    if bad:
        raise ValueError(f"올바른 문서 id 가 아닙니다: {bad}")
    return [int(i) for i in file_ids]


@work_regist("hybrid_search_function")
def hybrid_search_function(*args, **kwargs):
    """dense + sparse 를 RRF 로 합쳐 검색한다.

    두 점수를 더하지 않고 순위로 합친다 — dense 는 코사인이라 0~1 인데 sparse 는
    가중치 내적이라 상한이 없어서, 그냥 더하면 sparse 가 결과를 지배한다.

    payload 에 fileIds 가 오면 그 문서들 안에서만 찾는다("검색 문서 선택"). 프로시저가
    순위를 매기기 전에 걸러 주므로, 몇 개를 고르든 후보 수는 top_k 로 같다.
    """
    req, query, vector, weights = args[0]
    rag = get_controller()

    document_ids = _document_ids(req)
    hits = db_call(
        "search_documents_hybrid",
        query_vector=to_plain_vector(vector),
        query_weights=to_plain_sparse(weights),
        sparse_dim=rag.sparse_dimension,
        top_k=TOP_K_SEARCH,
        document_ids=document_ids,      # None 이면 전체 검색
    ) or []
    scope = f"문서 {document_ids} 한정" if document_ids else "전체"
    logger.info(f"[hybrid_search_function] 조각 {len(hits)}개 ({scope})")
    return req, query, hits


@work_regist("rerank_function")
def rerank_function(*args, **kwargs):
    """검색된 조각을 맥락으로 묶고 재정렬해 상위 몇 개만 남긴다.

    묶기와 재정렬을 한 work 로 둔다. 둘은 항상 붙어 다니고 — 묶지 않고 재정렬할
    일도, 묶어놓고 재정렬 안 할 일도 없다 — 떼어놓으면 그 사이에 미리 자르는 코드가
    끼어들 자리가 생긴다.

    묶기: 조각이 절반 넘게 걸린 섹션만 본문으로 승격한다. 조금 걸린 섹션은 조각
    그대로 둔다 — 같은 본문이 여러 번 실려가는 걸 막는다.

    여기서 limit 을 걸지 않는다. 약한 신호(유사도)로 미리 자른 뒤 강한 신호(리랭커)
    에게 남은 것만 주는 건 순서가 거꾸로다 — 실측으로 recall 이 93%에서 83%로
    떨어졌다. 후보를 다 넘기고 리랭커가 top_k 로 줄이게 한다.

    재정렬: 한 부모의 조각이 최종 자리를 독점하지 못하게 개수를 제한한다. 조각들이
    표 머리글을 공유해서 LLM 이 거의 같은 글을 여러 번 보게 된다.
    """
    req, query, hits = args[0]
    rag = get_controller()

    contexts = rag.build_contexts(hits)
    logger.info(f"[rerank_function] 맥락 {len(contexts)}개 "
          f"(승격 {sum(1 for c in contexts if c.merged)})")

    ordered = rag.rerank(query, contexts, top_k=TOP_K_FINAL)
    for rank, context in enumerate(ordered, 1):
        logger.info(f"[rerank_function] {rank}. score={context.rerank_score:.4f} "
              f"merged={context.merged} {context.breadcrumb[:60]}")
    return req, query, ordered

#------------------------------------------------┌> 답변


@work_regist("history_function")
def history_function(*args, **kwargs):
    """이전 대화와 요약을 읽어 함께 넘긴다. (req, 질의, 맥락, 외부, 세션맥락).

    세션맥락은 {"history": 최근 차례들, "summary": 그 앞의 요약} 이다. 둘을 묶는 이유는
    같은 것의 두 부분이기 때문이다 — 튜플 자리를 하나씩 늘리면 뒤 work 의 언팩이
    금세 여섯 일곱 개가 된다.

    ragmodul 의 _format_history 가 get_recent_messages 의 모양({user_query,
    ai_response})을 그대로 받는다. 가공하지 않고 넘긴다 — 자르기와 순서(최근 것부터,
    넘치면 오래된 차례를 버림)도 그쪽이 한다.

    session_id 가 없으면(새 대화·더미 토큰) 빈 목록이다. 읽기에 실패해도 질의를 막지
    않는다 — 이력은 해석 단서일 뿐이라 없으면 없는 대로 답하면 된다.
    """
    req, query, contexts, refs = args[0]

    session_id = req.get("session_id")
    if not session_id:
        return req, query, contexts, refs, {"history": [], "summary": ""}

    history = db_call("get_recent_messages", session_id=session_id,
                      limit_count=KEEP_TURNS) or []
    # 창 밖으로 밀려난 대화는 요약으로만 남는다(CHAT_SESSION_COMPRESS 가 채운다).
    context = db_call("get_session_context", session_id=session_id) or {}
    summary = context.get("overall_summary") or ""

    logger.info(f"[history_function] 이전 대화 {len(history)}차례, 요약 {len(summary)}자")
    return req, query, contexts, refs, {"history": history, "summary": summary}



@work_regist("search_images_function")
def search_images_function(*args, **kwargs):
    """질의에 딸려 보낼 문서 그림을 고른다. (req, 질의, 맥락, 외부, 세션맥락, 그림들).

    먼저 그림을 찾는 질의인지 가른다(ragmodul is_image_query). "그림·도표·그래프를
    직접 찾는 말" 일 때만 참이고, 내용을 묻는 말은 그림이 도움이 될 것 같아도 거짓이다.
    아니면 벡터 검색도 하지 않고 빈 목록으로 지나간다.

    판정을 먼저 두면 질의마다 LLM 왕복이 하나 붙는다(짧은 프롬프트라 1초 안쪽).
    반대로 검색을 먼저 하고 걸린 게 있을 때만 판정하면 그 왕복을 아낄 수 있는데,
    대신 그림이 없는 질의에서도 매번 벡터 검색이 돈다. 지금은 판정을 먼저 둔다 —
    답변이 느려지는 게 보이면 순서를 뒤집으면 된다.

    고른 그림은 두 곳에 쓰인다. 하나는 모델이다(초안·다듬기 양쪽에 실어 보낸다 —
    로컬도 이미지를 받는다. 실측 png 1MB 3.2초, 두 장도 됨). 다른 하나는 화면이라,
    사용자가 답변과 같은 그림을 본다.

    실패해도 질의를 막지 않는다. 그림은 덤이라 없으면 없는 대로 답하면 된다.
    """
    req, query, contexts, refs, session = args[0]

    try:
        images = _search_images(req, query)
    except Exception as e:                                   # noqa: BLE001
        logger.warning(f"[search_images_function] 건너뜀: {type(e).__name__} - {e}")
        images = []
    return req, query, contexts, refs, session, images


def _search_images(req, query: str) -> list:
    """그림 검색. 화면에 띄울 행 목록을 돌려준다.

    모델에는 그림을 보내지 않는다. 색인할 때 만들어둔 설명(ai_summary)이 이미
    검색을 태웠고, 그림 자체를 다시 실어 보내면 장당 몇 초가 답변 시간에 더해진다
    (로컬 실측 1MB 3.2초). 사용자는 답변 옆에서 그림을 직접 본다.

    후보를 넉넉히 뽑아 리랭커로 줄인다. 벡터 검색은 의미가 비슷한 것을 찾을 뿐이라,
    "2026년 취업률 그래프" 처럼 숫자와 이름이 걸린 질의에서 순위가 흔들린다.
    리랭커는 질의와 설명을 함께 보고 판정하므로 그 자리를 메운다.

    파일이 실제로 있는 행만 남긴다 — 없는 파일의 URL 을 내보내면 화면에 깨진
    그림이 뜨고, 그런 걸 리랭킹하는 것도 낭비다.
    """
    rag = get_controller()
    if not rag.is_image_query(query):
        logger.info("[search_images] 그림을 찾는 질의가 아니다 — 건너뜀")
        return []

    vector, _ = rag.embed_query(query)
    rows = db_call("search_document_image_vector",
                   query_vector=to_plain_vector(vector),
                   top_k=IMAGE_SEARCH_TOP_K,
                   document_ids=_document_ids(req)) or []

    candidates, texts = [], []
    for row in rows:
        # 설명이 없는 그림은 판정할 근거가 없다. 로고·장식이라 설명이 비어 있거나,
        # 색인 때 설명 생성이 실패한 경우다.
        text = " ".join(x for x in (row.get("ai_summary"), row.get("caption")) if x).strip()
        if not text:
            continue
        if resolve_image_path(row.get("image_path") or "", IMAGE_DIR) is None:
            logger.warning(f"[search_images] 파일 없음: {row.get('image_path')}")
            continue
        candidates.append(row)
        texts.append(text)

    if not candidates:
        logger.info(f"[search_images] 후보 없음 (검색 {len(rows)})")
        return []

    # 문턱은 여기서 걸지 않는다. 버린 것의 점수도 로그로 봐야 문턱을 실측으로 정할
    # 수 있어서, 전부 받아놓고 아래에서 자른다.
    ranked = rag.rerank_texts(query, texts, min_score=None)

    picked = []
    for index, score in ranked:
        row = candidates[index]
        if score < IMAGE_MIN_RERANK:
            mark = "x"          # 문턱 미달
        elif len(picked) >= IMAGE_ATTACH_MAX:
            mark = "-"          # 점수는 됐는데 자리가 찼다
        else:
            mark = "o"
            picked.append(row)
        logger.info(f"[search_images] {mark} rerank={score:.4f} "
                    f"sim={row.get('similarity') or 0:.4f} "
                    f"{row.get('image_name')} ({row.get('document_title')})")

    logger.info(f"[search_images] 그림 {len(picked)}장 "
                f"(검색 {len(rows)}, 후보 {len(candidates)}, 문턱 {IMAGE_MIN_RERANK})")
    return picked


def _dedup_sources(rows) -> list:
    """(id, 이름) 쌍들 -> 클라이언트가 읽는 [{id, name}].

    id 로 중복을 걷어내고, id 가 없으면 이름으로 본다 — 클라이언트가 목데이터를
    섞어 보내도 같은 문서가 두 번 뜨지 않게 한다.
    """
    seen, sources = set(), []
    for source_id, name in rows:
        key = str(source_id or name or "")
        if not key or key in seen:
            continue
        seen.add(key)
        sources.append({"id": str(source_id or ""), "name": name or ""})
    return sources


def _format_api_ref(ref: dict) -> str:
    """외부 API 한 건 -> 프롬프트에 실을 한 덩어리.

    제목·출처만으로는 모델이 값을 알 수 없어 응답 원문(data)까지 붙인다. url 과 key 는
    넣지 않는다 — 링크를 답변에 옮기면 사용자가 인증 없이 눌러 실패하고, 키는 새면 안 된다.
    """
    head = f"{ref.get('title') or ''} ({ref.get('source') or ''})".strip()
    data = (ref.get("data") or "")[:API_DATA_CHARS]
    if not data:
        return head
    return f"""{head}
{data}"""


def _to_sources(contexts) -> list:
    """맥락들 -> [{id, name}]. 문서 하나당 한 줄만 남긴다.

    document_id 가 없는 맥락은 버린다 — 문서에 붙지 않은 조각이라 출처로 띄울 게 없다.
    """
    return _dedup_sources((c.document_id, c.document_title)
                          for c in contexts if c.document_id is not None)


def _image_answer(images: list) -> list:
    """찾은 그림들 -> 답변 하나. LLM 을 부르지 않는다.

    색인할 때 만들어둔 설명(ai_summary)을 그대로 쓴다. 문구는 고정이라 같은 질의에
    같은 답이 나오고, 없는 사실이 끼어들 자리도 없다.

    provider 는 비운다. 어느 모델도 부르지 않았으니 이름을 붙이면 거짓이 된다 —
    클라이언트는 provider 가 없으면 일반 말풍선으로 그린다(대화 내역과 같은 규칙).
    """
    lines = [f"요청하신 그림 {len(images)}장을 찾았습니다.", ""]
    for index, image in enumerate(images, 1):
        summary = (image.get("ai_summary") or image.get("caption")
                   or image.get("image_name") or "").strip()
        title = image.get("document_title")
        lines.append(f"{index}. {summary}" + (f" — {title}" if title else ""))
    return [{"provider": None, "answer": chr(10).join(lines)}]


@work_regist("answer_function")
def answer_function(*args, **kwargs):
    """초안을 만들고 고른 모델들이 각자 다듬는다. [{provider, answer}, ...].

    초안은 결과에 안 넣는다 — 내부 단계이고 사용자가 고를 수 있는 모델도 아니다.
    다듬기가 전부 실패하면 답이 없는 것으로 본다. 대신 초안을 보내면 안 보내기로 한
    것을 보내는 셈이다.

    다듬기는 서로 독립이고 동시에 나간다. 같은 초안을 각자 받아 따로 고친다 —
    순차로 넘기면 앞 모델의 판단이 굳어져 뒷 모델이 손댈 여지가 줄어든다.
    걸리는 시간도 합이 아니라 가장 느린 하나가 된다.
    """
    # search_images_function 이 붙으면 6칸, 없으면(test_ 태스크) 5칸이다.
    value = args[0]
    req, query, contexts, refs, session = value[:5]
    images = value[5] if len(value) > 5 else []
    history, summary = session["history"], session["summary"]

    # 그림을 찾는 질의였고 실제로 찾았으면 LLM 을 타지 않는다. 사용자가 원한 것은
    # 그림이고 그 설명은 색인할 때 이미 만들어 뒀다 — 같은 내용을 모델에게 다시
    # 쓰게 하면 시간과 돈만 든다.
    #
    # 그리고 지금 구조에서는 모델이 그림을 못 본다(이미지를 안 넘긴다). 그래서
    # 그냥 두면 "사진 파일은 확인되지 않았습니다" 라고 답하면서 화면 옆에는 그림이
    # 떠 있는 모순이 생긴다 — 실제로 그렇게 나왔다.
    if images:
        return req, _image_answer(images), _to_sources(contexts), images

    rag = get_controller()

    # 그림은 모델에 넘기지 않는다. 찾은 그림은 응답에만 실어 사용자가 보게 한다
    # (user_query_output). 그림을 프롬프트에 얹으면 장당 몇 초가 답변 시간에 더해지는데,
    # 그 내용은 색인할 때 만들어둔 설명으로 이미 검색을 태웠다.
    #
    # 초안에는 외부 데이터를 주지 않는다. DRAFT_PROVIDER 가 로컬 모델이라 API 응답
    # 원문이 붙으면 게이트웨이가 413 으로 자른다(실측 32KB). 최종 답변은 다듬기
    # 단계에서 나오므로 거기서만 실어 보내면 된다.
    #
    # 이력은 초안에도 준다. 다듬는 쪽이 "초안이 대명사를 제대로 짚었는지" 판단하려면
    # 같은 대화를 보고 있어야 한다(ragmodul arefine 의 설명). 실은 만큼 맥락 예산에서
    # 빼주므로 로컬이 넘치지 않는다.
    draft = rag.answer(query, contexts, provider=DRAFT_PROVIDER,
                       history=history, summary=summary)
    logger.info(f"[answer_function] 초안 {DRAFT_PROVIDER} {len(draft):,}자 (내부용)")

    # 클라이언트가 고른 모델. 배열로 온다 — 비교 화면에서 여러 개를 고르면 여럿,
    # 하나만 고르면 하나짜리 배열이다. 문자열도 받아준다.
    #
    # 배열로 받는 게 중요한 이유: provider 마다 요청을 따로 보내면 같은 질의로 검색·
    # 리랭킹·초안 생성이 그 수만큼 반복된다(실측 28초 × N). 한 번에 받으면 그 앞단이
    # 한 번만 돌고 다듬기만 병렬로 늘어난다.
    chosen = (req.get("payload") or {}).get("provider")
    if isinstance(chosen, (list, tuple)):
        providers = [str(name) for name in chosen if name]
    elif chosen:
        providers = [str(chosen)]
    else:
        providers = []

    # 클라이언트가 최소 하나를 강제하므로 빈 값은 오지 않는다. 그래도 확인은 남긴다 —
    # 빈 목록을 그대로 넘기면 refine_all 이 아무것도 부르지 않고
    # "다듬기가 전부 실패했습니다: []" 라는 엉뚱한 문장이 사용자에게 간다.
    if not providers:
        raise ValueError("답변할 모델(provider)이 지정되지 않았습니다.")

    # dict 로 넘기면 ragmodul 이 title·source 만 쓴다(_format_external). 문자열로 넘기면
    # 그 줄을 그대로 실어주므로, 응답 원문까지 붙여 보낸다.
    external = [_format_api_ref(ref) for ref in refs]
    answers = rag.refine_all(query, contexts, draft, providers,
                             external=external, history=history, summary=summary)
    for name in providers:
        mark = f"{len(answers[name]):,}자" if name in answers else "실패"
        logger.info(f"[answer_function] 다듬기 {name} {mark}")

    if not answers:
        raise RuntimeError(f"다듬기가 전부 실패했습니다: {providers}")

    # contexts 는 여기서 끊기는데 뒤 단계(save_conversation, user_query_output)가
    # 출처를 필요로 한다. 요청 봉투(req)에 얹지 않고 함께 넘긴다 — 봉투는 통신부가
    # 만든 것이라 우리 중간 결과를 섞지 않는다.
    sources = _to_sources(contexts)
    logger.info(f"[answer_function] 출처 {len(sources)}건")

    return (req,
            [{"provider": name, "answer": text} for name, text in answers.items()],
            sources, images)


def _merge_sources(answers) -> list:
    """답변들이 실어 온 출처를 하나로 합친다."""
    return _dedup_sources((source.get("id"), source.get("name"))
                          for answer in answers
                          for source in answer.get("sources") or [])


@work_regist("merge_function")
def merge_function(*args, **kwargs):
    """다듬은 답변들을 하나로 합친다. {provider, answer} 하나로 돌려준다.

    답변이 하나면 모듈이 호출 없이 그대로 돌려준다. 셋 이상도 한 번에 넘긴다 —
    둘씩 접어 올리면 나중 것이 '이미 합쳐진 것' 과 1:1 로 겨루게 되어 앞선 답변의
    근거가 묽어진다.
    """
    value = args[0] if args else None
    sources = None
    if isinstance(value, tuple):                      # 질의 체인 뒤에 붙었을 때
        req, answers, sources = value[:3]             # answer_function 이 출처까지 준다
    else:                                             # MERGE_RESULTS 로 단독 호출
        req = value if isinstance(value, dict) else {}
        # 명세는 content, 이쪽은 answer 로 읽는다. 여기서 맞춘다.
        answers = [{"provider": a.get("provider"),
                    "answer": a.get("content") or a.get("answer") or "",
                    "sources": a.get("sources") or []}
                   for a in (req.get("payload") or {}).get("answers") or []]
    if not answers:
        raise ValueError("합칠 답변이 없습니다. payload.answers 를 보내주세요.")

    payload = req.get("payload") or {}
    query = payload.get("query") or QUERY
    provider = payload.get("provider") or MERGE_WITH

    merged = get_controller().merge(query, [a["answer"] for a in answers], provider=provider)
    logger.info(f"[merge_function] {provider} 병합 {len(merged):,}자")
    # 합친 답변의 출처는 재료가 된 답변들의 출처를 합집합으로 둔다 — 같은 질의에
    # 대한 답변들이라 근거 문서도 그 답변들이 본 것 전부다. 질의 체인 뒤에 붙었을
    # 때는(test_레그질의병합) 앞 단계가 준 것을 그대로 쓴다.
    # req 를 함께 넘긴다. 다음 단계(save_merged)가 session_id 를 봐야 한다.
    return req, {"provider": provider, "answer": merged,
                 "sources": sources or _merge_sources(answers)}


#------------------------------------------------┌> 대화 압축


@work_regist("compress_session")
def compress_session(*args, **kwargs):
    """창 밖으로 밀려난 대화를 요약에 접어 넣는다. (요약, 접어 넣은 차례 수).

    최근 KEEP_TURNS 차례는 원문으로 실리므로 압축 대상이 아니다. 그보다 앞의 차례만
    넘긴다 — ragmodul 이 '기존 요약 + 밀려난 차례' 로 누적 갱신한다.

    밀려난 차례가 없으면 ragmodul 이 LLM 을 부르지 않고 기존 요약을 그대로 돌려준다.
    그래도 여기서 먼저 걸러 DB 쓰기까지 건너뛴다.
    """
    session_id = args[0]

    rows = db_call("get_recent_messages", session_id=session_id,
                   limit_count=COMPRESS_SCAN_TURNS) or []
    dropped = rows[:-KEEP_TURNS] if len(rows) > KEEP_TURNS else []
    if not dropped:
        logger.info(f"[compress_session] 밀려난 차례 없음 ({len(rows)}차례)")
        return "", 0

    context = db_call("get_session_context", session_id=session_id) or {}
    previous = context.get("overall_summary") or ""

    summary, topic = get_controller().summarize_session(previous, dropped,
                                                        provider=SUMMARY_PROVIDER)
    if not summary:
        raise ValueError("대화 요약에 실패했습니다.")

    db_call("update_overall_summary", session_id=session_id, summary=summary)
    # 주제는 빈 문자열로 올 수 있다(밀려난 차례가 없어 LLM 을 안 부른 경우).
    # 그때 덮어쓰면 쓰던 주제를 지우는 셈이라 건너뛴다.
    if topic:
        db_call("update_current_topic", session_id=session_id, topic=topic)

    logger.info(f"[compress_session] {len(dropped)}차례 압축 -> {len(summary)}자, 주제={topic!r}")
    return summary, len(dropped)


@work_regist("compress_output")
def compress_output(*args, **kwargs):
    """(요약, 차례 수) -> 클라이언트가 읽는 {compressed}.

    요약문 자체는 내보내지 않는다. 서버가 다음 질의에 알아서 싣는 값이라 화면에
    쓸 일이 없고, 지나간 대화 내용이 그대로 나가는 것도 피한다.
    """
    _summary, count = args[0]
    return {"compressed": count}


#------------------------------------------------┌> 문서 이미지 설명


@work_regist("describe_images_function")
def describe_images_function(*args, **kwargs):
    """등록된 그림마다 LLM 설명을 만들어 document_images 에 채운다.

    질의 때 그림을 찾으려면 그림 내용이 텍스트로 있어야 한다. 그 텍스트를 여기서
    만든다 — 업로드 때 장당 한 번이고, 질의 때는 다시 부르지 않는다.

    provider 는 gemini 가 기본이다. hwpx 그림은 절반쯤이 bmp 인데 gpt·claude 는
    그걸 400 으로 거절한다(ragmodul 실측).

    동시에 여러 장을 보낸다. 순차로 돌리면 장당 몇 초 × 수십 장이라 업로드가 몇 분씩
    길어진다. 동시 실행은 ragmodul 의 describe_images_all 이 맡고, 한 번에 너무 많이
    던지지 않도록 IMAGE_CONCURRENCY 를 넘겨준다.

    실패해도 업로드를 실패로 만들지 않는다. 색인은 이미 끝났고, 설명이 없는 그림은
    검색에 안 걸릴 뿐이다 — 그것 때문에 문서 등록을 통째로 되돌릴 이유가 없다.
    """
    meta, (document_id, chunks, rows) = _step_in(args)
    if not rows:
        return _step_out(meta, (document_id, chunks, []))

    # rows 는 _register_images 가 문서 순서로 넣은 것이라 앞에서 자르면 앞쪽 그림이 남는다.
    targets = rows[:IMAGE_DESCRIBE_MAX]
    skipped = len(rows) - len(targets)

    described = _describe_images(targets)
    logger.info(f"[describe_images_function] 설명 {len(described)}/{len(targets)}장 "
          f"(provider={IMAGE_PROVIDER}, 동시 {IMAGE_CONCURRENCY}"
          + (f", 상한 {IMAGE_DESCRIBE_MAX} — {skipped}장 건너뜀" if skipped else "") + ")")
    return _step_out(meta, (document_id, chunks, described))


def _describe_images(rows: list) -> list:
    """그림들을 동시에 설명해 DB 에 저장한다. 설명이 붙은 행 목록.

    동시 실행은 ragmodul 이 한다. 여기서 asyncio 를 쓰면 안 된다 — 그쪽은 스레드마다
    루프를 하나 만들어 재사용하고 HTTP 클라이언트가 그 루프에 묶여 있는데, 우리가
    asyncio.run 으로 루프를 새로 파면 같은 클라이언트를 다른 루프에서 쓰게 된다.
    같은 이유로 그 루프 안에서는 db_call 도 못 부른다(DBManager 가 자기 루프에
    run_until_complete 를 건다). 그래서 설명은 한 번에 받고, 저장은 여기서 한다.

    로고·장식처럼 설명할 것이 없는 그림은 세 값이 다 비어서 온다. 실패한 그림도
    빈 설명으로 온다(둘은 반환값으로 구분되지 않는다 — ragmodul 로그를 본다).
    어느 쪽이든 결과에 넣지 않는다 — 억지로 임베딩하면 엉뚱한 질의에 걸린다.
    """
    rag = get_controller()

    # 파일을 못 읽는 그림은 여기서 뺀다. 목록에 남겨두면 설명 결과와 행의 짝이 어긋난다.
    targets = []
    for row in rows:
        path = resolve_image_path(row.get("image_path") or "", IMAGE_DIR)
        if path is None:
            logger.info(f"[describe_images] 파일 없음: {row.get('image_path')}")
            continue
        try:
            targets.append((row, path, path.read_bytes()))
        except OSError as e:
            logger.warning(f"[describe_images] {path.name} 읽기 실패: {type(e).__name__} - {e}")
    if not targets:
        return []

    descriptions = rag.describe_images_all(
        [(data, _mime_type(path)) for _, path, data in targets],
        provider=IMAGE_PROVIDER, max_concurrent=IMAGE_CONCURRENCY)

    described = []
    for (row, path, _data), desc in zip(targets, descriptions):
        text = " ".join([desc.ai_summary, *desc.key_facts, *desc.key_phrases]).strip()
        if not text:
            logger.info(f"[describe_images] {path.name} 설명 없음 — 건너뜀")
            continue
        # update 는 안 넘긴 컬럼을 전부 NULL 로 덮는다 — image_name·image_path 뿐 아니라
        # 제목 경로·캡션·note 도 그렇다. 앞 단계(_register_images)가 막 넣은 제목 경로를
        # 여기서 지워버린 적이 있어서(화면의 대·중·소제목이 비었다), 행이 이미 가진 값을
        # 그대로 실어 보낸다. get_document_image 가 FILE_IMAGE_SAVE 에서 하는 것과 같다.
        db_call("update_document_image", id=row["id"],
                image_name=row["image_name"], image_path=row["image_path"],
                caption=row.get("caption"), major_title=row.get("major_title"),
                mid_title=row.get("mid_title"), minor_title=row.get("minor_title"),
                note=row.get("note"),
                ai_summary=desc.ai_summary, key_facts=list(desc.key_facts),
                key_phrases=list(desc.key_phrases))
        described.append({**row, "_text": text})
    return described


@work_regist("embed_images_function")
def embed_images_function(*args, **kwargs):
    """설명을 임베딩해 이미지 벡터로 저장한다.

    설명 세 값을 이어붙인 문장 하나를 임베딩한다. 이미지 하나당 벡터 하나라 검색
    결과가 그대로 이미지 목록이 된다.

    임베딩은 목록을 한 번에 넘긴다 — 장마다 부르면 모델 호출이 장 수만큼 늘어난다.
    """
    meta, (document_id, chunks, described) = _step_in(args)
    if not described:
        return _step_out(meta, (document_id, chunks))

    vectors = get_controller().embed_texts([row["_text"] for row in described])

    saved = 0
    for row, vector in zip(described, vectors):
        if db_call("save_document_image_vector", image_id=row["id"],
                   embedding=to_plain_vector(vector)):
            saved += 1

    logger.info(f"[embed_images_function] 이미지 벡터 {saved}/{len(described)}개 저장")
    # 뒤 단계(file_upload_register)는 등록 전 모양을 기대한다. 이미지 정보는 여기서 끝난다.
    return _step_out(meta, (document_id, chunks))




def _mime_type(path) -> str:
    """확장자로 mime 을 정한다. gemini 가 형식을 보고 처리한다."""
    import mimetypes

    return mimetypes.guess_type(path.name)[0] or "image/png"


#------------------------------------------------┌> 외부 데이터
@work_regist("search_api_function")
def search_api_function(*args, **kwargs):
    """질의와 비슷한 외부 API 를 찾는다. (query, contexts, api_refs).

    질의 벡터를 다시 만든다. 앞 단계가 이미 만들었지만 rerank 까지 오면서 버려졌고,
    가져오려면 체인 중간 두 함수의 반환값을 바꿔야 한다. 질의 한 문장이라 수십 ms 다.

    실패해도 답변을 막지 않는다. 이건 부가 정보라 없으면 없는 대로 답하면 된다 —
    외부 데이터 테이블이 비었다는 이유로 질의 전체가 죽으면 안 된다.
    """
    req, query, contexts = args[0]

    refs = []
    try:
        vector, _ = get_controller().embed_query(query)
        refs = db_call(
            "search_api_data_vector",
            query_vector=to_plain_vector(vector),
            top_k=TOP_K_API,
        ) or []
    except Exception as e:
        logger.warning(f"[search_api_function] 건너뜀: {type(e).__name__} - {e}")

    for ref in refs:
        logger.info(f"[search_api_function] {ref['title']} "
              f"({ref['source']}) sim={ref['similarity']:.4f}")
    if not refs:
        logger.info("[search_api_function] 관련 외부 데이터 없음")
    return req, query, contexts, refs

@work_regist("embed_api_function")
def embed_api_function(*args, **kwargs):
    """방금 등록된 외부 API 를 임베딩해 api_data_vectors 에 넣는다. url 또는 None.

    api_insert 체인에서 insert_db_api_data 다음에 붙는다. 앞 단계가 방금 넣은 행
    하나를 준다 — title, url, source, key, data, data_type, date.

    임베딩 대상은 title 과 source 뿐이다. data 는 API 응답 원문이라 길고 자주 바뀌고,
    key 는 인증키다 — 둘 다 벡터에 들어가면 안 된다. 그래서 update_api_data_date 로
    data 만 갱신될 때는 이 work 가 다시 돌 필요가 없다. 삭제도 마찬가지다 —
    url FK 에 ON DELETE CASCADE 가 걸려 있어 delete_api_data 가 벡터까지 지운다.
    결국 벡터가 새로 필요한 순간은 등록 하나뿐이다.

    sparse 를 만들지 않는다. api_data_vectors 는 embedding vector(1024) 한 컬럼뿐이라
    넣을 자리가 없다. title 은 30~60자로 짧아 어휘가 겹칠 일이 적고, 그런 짧은
    문자열은 sparse 가 잘 못 잡는다.

    임베딩이 실패해도 등록 자체를 되돌리지 않는다. 행은 이미 들어갔고, 벡터가 없으면
    유사도 검색에 안 잡힐 뿐이다 — 그것 때문에 등록을 실패로 만들 이유가 없다.
    """
    row = args[0] if args else None
    if not row or not row.get("url"):
        logger.warning("[embed_api_function] 등록된 행이 없어 건너뜁니다")
        return None

    text = f"{row['title']} · {row['source']}"
    vector = get_controller().embed_texts([text])[0]
    db_call("save_api_data_vector", url=row["url"], embedding=vector)

    logger.info(f"[embed_api_function] 벡터 저장: {text}")
    return row["url"]

#────────────────────────────────────────────────┌> 통신부 task (명세 task_type)
#
# 이름은 클라이언트(src/config/TaskType.js)가 보내는 그대로 쓴다. 기존 test_ 태스크는
# 손대지 않는다 — 통신부 없이 체인만 돌려보는 통로가 그대로 남아 있어야 한다.



@work_regist("user_query_output")
def user_query_output(*args, **kwargs):
    """(req, 답변들) -> 클라이언트가 읽는 {reply, sessionId, sources}.

    sessionId 는 받은 것을 그대로 돌려준다. 클라이언트가 다음 요청에 그대로 실어
    보내기 때문에(ChatService.sendMessage), 여기서 비우면 대화가 매번 끊긴다.
    세션 work 이 붙으면 새로 만든 id 로 바뀐다.

    answers 는 provider 를 여러 개 골랐을 때 비교 화면이 쓴다. 모양을 MERGE_RESULTS
    payload 와 같게(provider/content/sources) 맞춰서, 클라이언트가 변환 없이 그대로
    실어 보낼 수 있게 한다.

    실패한 provider 는 answers 에 없다. 셋을 보냈는데 둘만 오면 하나가 실패한 것이다 —
    refine_all 이 성공한 것만 돌려주기 때문이다. 전부 실패하면 앞 단계가 예외를 낸다.

    sources 는 검색 결과라 답변마다 같다. 최상위와 각 답변에 같은 값을 넣어 클라이언트가
    어느 쪽을 읽어도 되게 한다.
    """
    value = args[0]
    req, answers, sources = value[:3]
    images = value[3] if len(value) > 3 else []
    sources = sources or []
    return {
        "reply": answers[0]["answer"] if answers else "",
        "answers": [{"provider": a["provider"], "content": a["answer"],
                     "sources": sources} for a in answers],
        "sessionId": req.get("session_id"),
        "sources": sources,
        # 모델이 본 그림을 사용자도 본다. base64 는 빼고 URL 로 준다 — 응답에 실으면
        # 방금 보낸 것을 되돌려주는 셈이라 무겁고, 파일은 /api/images 로 이미 나간다.
        "images": [
            {
                "id": str(image.get("image_id") or ""),
                "url": static_url(image.get("image_path") or "", IMAGE_DIR, "/api/images"),
                "name": image.get("image_name"),
                "caption": image.get("caption"),
                "aiSummary": image.get("ai_summary"),
                "documentId": str(image.get("document_id") or ""),
                "documentTitle": image.get("document_title"),
            }
            for image in images
        ],
    }


@work_regist("save_merged")
def save_merged(*args, **kwargs):
    """병합 답변을 세션에 남긴다. (req, 병합결과) 를 그대로 흘려보낸다.

    질문도 함께 넣는다. 다중 질의에서는 최종 답변이 병합 결과라, 그 행 하나에 질문과
    답변이 모여야 대화 내역이 완결된다 — 질문을 비워두면 그 행만 봐서는 무엇에 대한
    답인지 알 수 없다.

    질문은 payload 에 있다. MERGE_RESULTS 가 query 를 그대로 받기 때문이다.

    session_id 가 없으면 저장하지 않는다. 통신부가 봉투에 넣어주지 않는 경우를 대비해
    payload 도 본다.

    저장에 실패해도 답변은 그대로 내보낸다.
    """
    req, merged = args[0]
    payload = req.get("payload") or {}

    session_id = req.get("session_id") or payload.get("sessionId")
    if not session_id:
        logger.warning("[save_merged] sessionId 가 없어 저장 건너뜀")
        return req, merged

    try:
        db_call("insert_message", session_id=session_id,
                user_query=payload.get("query") or "",
                ai_response=merged.get("answer") or "",
                sources=merged.get("sources"),
                # 병합에 쓴 모델을 남긴다. "merged" 같은 종류 표시가 아니라 실제로
                # 그 답변을 만든 모델이다 — 컬럼이 그 값을 담게 되어 있다.
                provider=merged.get("provider"))
        logger.info(f"[save_merged] 세션 {session_id} 에 병합 답변 저장")
    except Exception as e:                                   # noqa: BLE001
        logger.warning(f"[save_merged] 저장 실패, 답변은 그대로 보냄: {type(e).__name__} - {e}")

    return req, merged


@work_regist("merge_output")
def merge_output(*args, **kwargs):
    """(req, 병합결과) -> 클라이언트가 읽는 {reply, sources}."""
    _req, merged = args[0]
    return {"reply": merged.get("answer", ""),
            "provider": merged.get("provider"),
            "sources": merged.get("sources") or []}


@work_regist("vectorize_image")
def vectorize_image_function(*args, **kwargs):
    """그림을 SVG 마크업으로 바꾼다. 문자열 하나를 돌려준다.

    실패는 예외로 올라온다(ragmodul 이 그렇게 만들었다). 사용자가 버튼을 눌러
    기다리는 결과라, 빈 값을 성공으로 돌려주면 화면이 빈 채로 남는다. 잘린 SVG 도
    예외라서 깨진 마크업이 화면에 가지 않는다.
    """
    data, mime = args[0]

    svg = get_controller().vectorize_image(data, mime, provider=VECTORIZE_PROVIDER)
    logger.info(f"[vectorize_image] {mime} {len(data):,}바이트 -> SVG {len(svg):,}자 "
                f"(provider={VECTORIZE_PROVIDER})")
    return svg


@work_regist("register_images")
def register_images(*args, **kwargs):
    """파서가 빼낸 이미지를 document_images 에 등록한다. 업로드 체인의 한 단계다.

    실패해도 업로드를 실패로 만들지 않는다. 이미지는 본문 검색에 안 쓰이고, 목록이
    비는 것과 색인을 통째로 되돌리는 것은 무게가 다르다.
    """
    meta, (document_id, document) = _step_in(args)
    rows = _register_images(document, document_id)
    # 뒤 단계(설명·임베딩)가 등록된 행의 id 와 경로를 쓴다. 개수만 넘기면 다시 조회해
    # 이름으로 짝을 맞춰야 한다.
    return _step_out(meta, (document_id, len(document.children()), rows))


def _heading_titles(heading_path: list) -> dict:
    """제목 경로 -> major/mid/minor_title. 앞 세 단계를 쓴다.

    ['Ⅱ. 교육혁신', '2-1 전공 개편', '가. 배정 현황', '(1) 세부']
      -> major='Ⅱ. 교육혁신', mid='2-1 전공 개편', minor='가. 배정 현황'

    표 셀 안의 그림은 블록이 없어 경로가 비어 있다(ragmodul 설명). 그때는 빈 dict 다.
    """
    names = ("major_title", "mid_title", "minor_title")
    return {name: value for name, value in zip(names, heading_path or []) if value}


def _register_images(document, document_id: int) -> list:
    """파서가 빼낸 이미지를 document_images 에 등록한다. 등록된 행 목록.

    parse(image_dir=...) 가 파일을 복사하면서 model.document_images 에 목록을
    붙여준다 — 저장 경로·문서 순서·제목 경로·캡션이 들어 있다.

    폴더를 훑지 않는 이유: 폴더에는 지난 업로드의 잔재가 남는다. 확장자가 바뀐
    옛 파일(bmp -> png)이나 새 버전에서 없어진 그림까지 등록돼서, 지워진 그림이
    계속 검색에 걸렸다(실측). 파서가 준 목록은 이번 파싱에서 나온 것만 담고 있다.

    order 순으로 넣는다. 그러면 id 순서가 곧 문서 순서라, list_document_images
    (ORDER BY id)가 문서에 나온 차례대로 돌려준다 — 파일명순으로 넣으면 image1,
    image10, image11, image2 로 섞인다.

    실패해도 업로드를 실패로 만들지 않는다. 이미지는 본문 검색에 안 쓰이고, 목록이
    비는 것과 색인을 통째로 되돌리는 것은 무게가 다르다.
    """
    from pathlib import Path

    images = getattr(document, "document_images", None)
    if not images:
        # image_dir 를 주지 않고 파싱하면 이 속성이 아예 없다(ragmodul 설명).
        logger.info("[_register_images] 파서가 넘긴 그림이 없다")
        return []

    try:
        saved = []
        for image in sorted(images, key=lambda i: i.order):
            path = str(image.path).replace("\\", "/")
            row = db_call("create_document_image", document_id=document_id,
                          image_name=Path(path).name, image_path=path)
            if not row:
                continue

            # 제목 경로와 캡션은 create 가 받지 않아 따로 넣는다. update 는 안 넘긴
            # 설명 컬럼을 NULL 로 덮는데, 방금 만든 행이라 덮을 것이 없다.
            extra = _heading_titles(image.heading_path)
            if image.caption:
                extra["caption"] = image.caption
            if extra:
                updated = db_call("update_document_image", id=row["id"],
                                  image_name=row["image_name"],
                                  image_path=row["image_path"], **extra)
                if updated:
                    row = updated
            saved.append(row)

        titled = sum(1 for i in images if i.heading_path)
        logger.info(f"[_register_images] 이미지 {len(saved)}/{len(images)}개 등록 "
                    f"(document_id={document_id}, 제목 경로 {titled}개)")
        return saved
    except Exception as e:                                   # noqa: BLE001
        logger.warning(f"[_register_images] 등록 실패, 건너뜀: {type(e).__name__} - {e}")
        return []
