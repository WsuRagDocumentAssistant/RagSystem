
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

import json
import os
import typing

from taskcontroller import work_regist, tasks
from ragmodul import RagController, chunk, parse
from ragmodul.util import document_to_payload, to_plain_sparse, to_plain_vector
from functions.data_functions import db_call   # DB 호출은 예외처리까지 묶여 있다

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
    "test_레그질의": QUERY_CHAIN + ["search_api_function", "answer_function"],
    "test_레그질의병합": QUERY_CHAIN + ["search_api_function", "answer_function", "merge_function"],
    "RAG_Search": QUERY_CHAIN + ["search_api_function", "answer_function"],
    "Merge": ["merge_function"],
})

#────────────────────────────────────────────────┌> 실제 태스크

# 앞에 ensure_session, 뒤에 save_conversation 을 끼운다. 그래야 대화가 세션으로
# 묶이고 사이드바 목록과 메시지 내역이 채워진다.
tasks["USER_QUERY"]    = (["ensure_session"] + QUERY_CHAIN
                          + ["search_api_function", "answer_function",
                             "save_conversation", "user_query_output"])

tasks["MERGE_RESULTS"] = ["merge_function", "merge_output"]


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

UNPACK_DIR = os.environ.get("RAG_UNPACK_DIR", "unpacked")
HWPX_FILE_PATH = os.environ.get("RAG_HWPX_FILE", "C:/Users/user/Desktop/RagSystem/test_file/2주기(2023년) 2022 ~ 2024 대학혁신지원사업 성과평가보고서.hwpx")
# 정적 서빙(main.py 의 IMAGE_DIR)과 같은 환경변수를 본다. 어긋나면 저장한 곳과
# 내보내는 곳이 달라져서 이미지가 안 뜬다.
IMAGE_PATH = os.environ.get("RAG_IMAGE_DIR", "images")

QUERY = os.environ.get("RAG_QUERY", "솔드림에 대해 설명해줘")

TOP_K_SEARCH = int(os.environ.get("RAG_TOP_K_SEARCH", "40"))     # 조각. 넉넉히 뽑는다
TOP_K_FINAL = int(os.environ.get("RAG_TOP_K_FINAL", "5"))        # LLM 에 실을 최종 개수

# 답변 초안을 만들 provider. 늘 도는 단계라 비용 0 인 쪽이 맞다. 사용자에게는 안 보이고
# 고를 수 있는 목록에도 없다 — 다듬은 결과만 나간다.
DRAFT_PROVIDER = os.environ.get("RAG_DRAFT_PROVIDER", "local_llm")

# 사용자가 고른 provider 들. 초안을 각자 다듬는다. 여기서 나온 것만 클라이언트로 간다.
ANSWER_PROVIDERS = [p for p in os.environ.get("RAG_LLM_PROVIDERS", "gpt").split(",") if p]

# 병합에 쓸 provider. 답변을 낸 것과 달라도 된다 — 판단 작업이라 더 센 모델을 쓸 수 있다.
MERGE_WITH = os.environ.get("RAG_MERGE_WITH") or "gpt"

# 사전 추출은 문서를 통째로 넘긴다. 로컬은 컨텍스트가 8192 토큰이라 안 들어간다.
VOCAB_PROVIDER = os.environ.get("RAG_VOCAB_PROVIDER", "claude")

# 축약어 추출을 몇 자씩 나눠 보낼지. pack_texts 가 부모 조각을 이 상한에 맞춰 묶는다.
# 크게 둘수록 앞뒤로 흩어진 짝을 잘 잇지만, 한 번에 너무 크면 응답이 느려져
# llm_api.timeout(config.json) 에 걸린다 — claude 로 88,000자를 한 번에 보내다 겪었다.
VOCAB_CHUNK_CHARS = int(os.environ.get("RAG_VOCAB_CHUNK_CHARS", "30000"))


# 외부 API 검색 개수. 1 이다 — 이건 근거가 아니라 "이런 것도 받아올 수 있다" 는
# 안내라서, 여러 개를 늘어놓으면 답변 끝이 목록이 된다.
TOP_K_API = int(os.environ.get("RAG_TOP_K_API", "1"))

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


def get_controller() -> RagController:
    """워커 프로세스에서 처음 필요할 때 한 번만 만든다.

    생성자가 임베딩 모델과 리랭커를 올리므로 몇십 초 걸린다.

    use_db=False 다. DB 는 db_call 로 직접 부르므로 여기서 커넥션을 들 이유가 없다.
    실수로 rag.hybrid_search() 같은 걸 부르면 원인이 적힌 ValueError 가 난다.

    LLM 설정은 config.json + .env 가 단일 출처다(cwd 기준). 모델명·엔드포인트·키·
    타임아웃이 거기 다 있어서 여기서 표를 또 만들면 두 곳이 어긋난다.
    """
    global _controller
    if _controller is None:
        from ai_rag_comm import load_config

        cfg = load_config()
        _controller = RagController(
            EMBEDDING_MODEL_PATH,
            RERANKER_MODEL_PATH,
            device=DEVICE,
            unpack_dir=UNPACK_DIR,
            image_dir=IMAGE_PATH,
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
    print(f"[warmup_function] 준비 완료. LLM: {', '.join(rag.llm.providers())}")
    return "ready"

#------------------------------------------------┌> 문서 등록


@work_regist("parse_function")
def parse_function(*args, **kwargs):
    """hwpx -> DocumentModel.

    FILE_UPLOAD 는 앞 work 이 방금 저장한 경로를 넘겨준다. 메뉴로 돌리는 test_ 태스크는
    params 가 None 이라 args 가 비고, 그때는 상수로 떨어진다. 문자열만 경로로 인정한다.
    """
    meta, value = _step_in(args)
    file_path = value if isinstance(value, str) and value else HWPX_FILE_PATH
    if not file_path:
        raise ValueError(
            "문서 경로가 비어 있습니다. RAG_HWPX_FILE 환경변수나 "
            "rag_functions.HWPX_FILE_PATH 를 지정하세요."
        )
    print(f"[parse_function] 파싱 시작: {file_path}")
    parsed = parse(file_path, unpack_dir=UNPACK_DIR, image_dir=IMAGE_PATH)
    print(f"[parse_function] 파싱 종료: block {len(parsed.blocks)}개")
    return _step_out(meta, parsed)


@work_regist("chunk_function")
def chunk_function(*args, **kwargs):
    """DocumentModel -> ChunkedDocument (parent/child)."""
    meta, parsed = _step_in(args)
    document = chunk(parsed)
    print(f"[chunk_function] 청킹 종료: parent {len(document.parents)}, "
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
    print(f"[embed_function] 임베딩 종료: child {len(document.children())}개")
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
    document_id = db_call(
        "index_document",
        document=document_to_payload(document),
        sparse_dim=rag.sparse_dimension,
    )
    print(f"[save_function] 저장 종료: document_id={document_id}, "
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

    print(f"[vocab_function] {sum(len(c) for c in chunks):,}자 "
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
        print(f"[filter_vocab_function] {pair.term} -> {pair.expansion}")
    for pair, reason in dropped:
        print(f"[filter_vocab_function] 버림({reason}) {pair.term}")
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
    print(f"[save_vocab_function] 확장어 {added}개 추가")
    return _step_out(meta, document)


def load_vocab() -> dict:
    """{축약어: [확장어, ...]} 를 읽는다.

    프로시저가 jsonb 를 돌려주는데 asyncpg 가 그걸 문자열로 준다(VocabRepository 의
    반환 설명은 dict 인데 실제로는 str 이다). 여기서 푼다 — 문자열을 그대로 넘기면
    질의 확장이 dict 처럼 순회하다 깨진다. 그쪽이 고쳐도 아래 검사는 그대로 통과한다.
    """
    vocab = db_call("load_vocab") or {}
    if isinstance(vocab, str):
        vocab = json.loads(vocab or "{}")
    return vocab

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
    print(f"[embed_query_function] 사전 {len(vocab)}개 적용 / 질의 {query[:40]!r}")
    return req, query, vector, weights


@work_regist("hybrid_search_function")
def hybrid_search_function(*args, **kwargs):
    """dense + sparse 를 RRF 로 합쳐 검색한다.

    두 점수를 더하지 않고 순위로 합친다 — dense 는 코사인이라 0~1 인데 sparse 는
    가중치 내적이라 상한이 없어서, 그냥 더하면 sparse 가 결과를 지배한다.
    """
    req, query, vector, weights = args[0]
    rag = get_controller()
    hits = db_call(
        "search_documents_hybrid",
        query_vector=to_plain_vector(vector),
        query_weights=to_plain_sparse(weights),
        sparse_dim=rag.sparse_dimension,
        top_k=TOP_K_SEARCH,
    ) or []
    print(f"[hybrid_search_function] 조각 {len(hits)}개")
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
    print(f"[rerank_function] 맥락 {len(contexts)}개 "
          f"(승격 {sum(1 for c in contexts if c.merged)})")

    ordered = rag.rerank(query, contexts, top_k=TOP_K_FINAL)
    for rank, context in enumerate(ordered, 1):
        print(f"[rerank_function] {rank}. score={context.rerank_score:.4f} "
              f"merged={context.merged} {context.breadcrumb[:60]}")
    return req, query, ordered

#------------------------------------------------┌> 답변


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


def _to_sources(contexts) -> list:
    """맥락들 -> [{id, name}]. 문서 하나당 한 줄만 남긴다.

    document_id 가 없는 맥락은 버린다 — 문서에 붙지 않은 조각이라 출처로 띄울 게 없다.
    """
    return _dedup_sources((c.document_id, c.document_title)
                          for c in contexts if c.document_id is not None)


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
    req, query, contexts, refs = args[0]
    rag = get_controller()

    draft = rag.answer(query, contexts, provider=DRAFT_PROVIDER, external=refs)
    print(f"[answer_function] 초안 {DRAFT_PROVIDER} {len(draft):,}자 (내부용)")

    # 클라이언트가 고른 모델. 없으면 설정값으로 떨어진다(통신부 없이 돌리는 test_ 태스크).
    providers = [p] if (p := (req.get("payload") or {}).get("provider")) else ANSWER_PROVIDERS

    answers = rag.refine_all(query, contexts, draft, providers, external=refs)
    for name in providers:
        mark = f"{len(answers[name]):,}자" if name in answers else "실패"
        print(f"[answer_function] 다듬기 {name} {mark}")

    if not answers:
        raise RuntimeError(f"다듬기가 전부 실패했습니다: {providers}")
    # 출처를 요청에 담아 흘려보낸다. 체인은 값 하나만 넘기는데 마지막 단계
    # (user_query_output)가 sources 를 채워야 하고, contexts 는 여기서 끊긴다.
    req["_sources"] = _to_sources(contexts)
    print(f"[answer_function] 출처 {len(req['_sources'])}건")

    return req, [{"provider": name, "answer": text} for name, text in answers.items()]


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
    if isinstance(value, tuple):                      # 질의 체인 뒤에 붙었을 때
        req, answers = value
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
    print(f"[merge_function] {provider} 병합 {len(merged):,}자")
    # 합친 답변의 출처는 재료가 된 답변들의 출처를 합집합으로 둔다 — 같은 질의에
    # 대한 답변들이라 근거 문서도 그 답변들이 본 것 전부다. 질의 체인 뒤에 붙었을
    # 때는(test_레그질의병합) 앞 단계가 req 에 담아둔 것을 쓴다.
    sources = req.get("_sources") or _merge_sources(answers)
    return {"provider": provider, "answer": merged, "sources": sources}


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
        print(f"[search_api_function] 건너뜀: {type(e).__name__} - {e}")

    for ref in refs:
        print(f"[search_api_function] {ref['title']} "
              f"({ref['source']}) sim={ref['similarity']:.4f}")
    if not refs:
        print("[search_api_function] 관련 외부 데이터 없음")
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
        print("[embed_api_function] 등록된 행이 없어 건너뜁니다")
        return None

    text = f"{row['title']} · {row['source']}"
    vector = get_controller().embed_texts([text])[0]
    db_call("save_api_data_vector", url=row["url"], embedding=vector)

    print(f"[embed_api_function] 벡터 저장: {text}")
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

    answers 는 명세에 없지만 provider 를 여러 개 쓸 때 비교 화면에 필요하다.
    """
    req, answers = args[0]
    return {
        "reply": answers[0]["answer"] if answers else "",
        "answers": answers,
        "sessionId": req.get("session_id"),
        "sources": req.get("_sources") or [],
    }


@work_regist("merge_output")
def merge_output(*args, **kwargs):
    """merge_function 의 결과 -> 클라이언트가 읽는 {reply, sources}."""
    merged = args[0]
    return {"reply": merged.get("answer", ""),
            "provider": merged.get("provider"),
            "sources": merged.get("sources") or []}


@work_regist("register_images")
def register_images(*args, **kwargs):
    """파서가 빼낸 이미지를 document_images 에 등록한다. 업로드 체인의 한 단계다.

    실패해도 업로드를 실패로 만들지 않는다. 이미지는 본문 검색에 안 쓰이고, 목록이
    비는 것과 색인을 통째로 되돌리는 것은 무게가 다르다.
    """
    meta, (document_id, document) = _step_in(args)
    _register_images(document, document_id)
    return _step_out(meta, (document_id, len(document.children())))


def _register_images(document, document_id: int) -> int:
    """파서가 빼낸 이미지를 document_images 에 등록한다. 등록한 개수.

    parse(image_dir=...) 가 이미 images/<문서명>/ 으로 파일을 복사해뒀다. 그 폴더를
    읽어 DB 에 이름과 경로만 남긴다 — 파일 자체는 /images 정적 경로로 나간다.

    폴더명은 파서가 문서 내부 filename 의 stem 으로 만든다(업로드 파일명이 아니다).

    실패해도 업로드를 실패로 만들지 않는다. 이미지는 본문 검색에 안 쓰이고, 목록이
    비는 것과 색인을 통째로 되돌리는 것은 무게가 다르다.
    """
    import os
    from pathlib import Path

    try:
        stem = Path(getattr(document.file, "filename", "") or "document").stem
        folder = Path(IMAGE_PATH) / stem
        if not folder.is_dir():
            print(f"[_register_images] 이미지 폴더 없음: {folder}")
            return 0

        names = sorted(p.name for p in folder.iterdir() if p.is_file())
        saved = 0
        for name in names:
            row = db_call("create_document_image", document_id=document_id,
                          image_name=name, image_path=str(folder / name).replace("\\", "/"))
            if row:
                saved += 1
        print(f"[_register_images] 이미지 {saved}/{len(names)}개 등록 (document_id={document_id})")
        return saved
    except Exception as e:                                   # noqa: BLE001
        print(f"[_register_images] 등록 실패, 건너뜀: {type(e).__name__} - {e}")
        return 0
