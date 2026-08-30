
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

from taskcontroller import work_regist, tasks
from ragmodul import RagController, chunk, parse
from ragmodul.util import document_to_payload, to_plain_sparse, to_plain_vector
from functions.data_functions import db_call   # DB 호출은 예외처리까지 묶여 있다

#────────────────────────────────────────────────

# 로컬 모델 폴더. 리랭커는 local_files_only 로 로드하므로 실제 폴더여야 한다.
EMBEDDING_MODEL_PATH = os.environ.get("RAG_EMBEDDING_MODEL", "models/bge-m3")
RERANKER_MODEL_PATH = os.environ.get("RAG_RERANKER_MODEL", "models/bge-reranker-v2-m3")

# None 이면 라이브러리 자동 감지. GPU 가 있으면 "cuda" 를 명시하는 편이 낫다
# (안 주면 가중치가 CPU 에 남아 배치마다 복사된다).
DEVICE = os.environ.get("RAG_DEVICE") or None

UNPACK_DIR = os.environ.get("RAG_UNPACK_DIR", "unpacked")
HWPX_FILE_PATH = os.environ.get("RAG_HWPX_FILE", "C:/Users/user/Desktop/RagSystem/test_file/2주기(2023년) 2022 ~ 2024 대학혁신지원사업 성과평가보고서.hwpx")
IMAGE_PATH = "images/"

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
VOCAB_PROVIDER = os.environ.get("RAG_VOCAB_PROVIDER", "gpt")


# 외부 API 검색 개수. 1 이다 — 이건 근거가 아니라 "이런 것도 받아올 수 있다" 는
# 안내라서, 여러 개를 늘어놓으면 답변 끝이 목록이 된다.
TOP_K_API = int(os.environ.get("RAG_TOP_K_API", "1"))

#────────────────────────────────────────────────┌> test task 등록

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
    """hwpx -> DocumentModel. 체인의 첫 단계라 경로를 상수에서 받는다."""
    file_path = HWPX_FILE_PATH
    if not file_path:
        raise ValueError(
            "문서 경로가 비어 있습니다. RAG_HWPX_FILE 환경변수나 "
            "rag_functions.HWPX_FILE_PATH 를 지정하세요."
        )
    print(f"[parse_function] 파싱 시작: {file_path}")
    parsed = parse(file_path, unpack_dir=UNPACK_DIR, image_dir=IMAGE_PATH)
    print(f"[parse_function] 파싱 종료: block {len(parsed.blocks)}개")
    return parsed


@work_regist("chunk_function")
def chunk_function(*args, **kwargs):
    """DocumentModel -> ChunkedDocument (parent/child)."""
    document = chunk(args[0])
    print(f"[chunk_function] 청킹 종료: parent {len(document.parents)}, "
          f"child {len(document.children())}")
    return document


@work_regist("embed_function")
def embed_function(*args, **kwargs):
    """child 에 dense/sparse 를 채운다. 같은 객체를 돌려주므로 체인이 이어진다.

    forward 를 한 번만 돌린다. 예전에는 dense 와 sparse 를 따로 불러서 같은 텍스트를
    두 번 추론했다 — 실측(child 374개) 530초에서 265초로 줄었다.
    """
    document = get_controller().embed_bge_m3(args[0])
    print(f"[embed_function] 임베딩 종료: child {len(document.children())}개")
    return document


@work_regist("save_function")
def save_function(*args, **kwargs):
    """색인. save_document_json 프로시저에 통째로 넘긴다.

    document_to_payload 를 쓰는 이유: 프로시저가 읽는 키가 DB 컬럼명(embedding/
    lexical)이 아니라 vector/sparse 다. 이름이 틀리면 에러 없이 NULL 이 들어가서
    개수는 맞는데 embedded 가 0 이 된다(실측으로 겪었다). numpy 도 거기서 걷어낸다.

    같은 source_path 면 프로시저가 RAG 컬럼만 갱신하고 업무 분류값(production_year,
    work_category 등)은 보존한다.
    """
    document = args[0]
    rag = get_controller()
    document_id = db_call(
        "index_document",
        document=document_to_payload(document),
        sparse_dim=rag.sparse_dimension,
    )
    print(f"[save_function] 저장 종료: document_id={document_id}, "
          f"child {len(document.children())}개")
    return document_id

#------------------------------------------------┌> 축약어 사전


@work_regist("vocab_function")
def vocab_function(*args, **kwargs):
    """문서 전체에서 축약어/확장어 짝을 뽑는다. LLM 한 번.

    부모 단위로 쪼개 돌리면 호출이 32번인데 결과는 더 적다 — 문서 앞뒤에 흩어진
    '축약어 ... 풀어쓴 말' 을 못 잇기 때문이다. 로컬 모델은 컨텍스트가 8192 토큰이라
    문서 전체(88,178자)가 안 들어가므로 클라우드로 부른다.

    다음 단계들이 문서도 필요하므로 함께 실어 보낸다.
    """
    document = args[0]
    text = "/n/n".join(parent.content for parent in document.parents)
    pairs = get_controller().extract_vocab(text, provider=VOCAB_PROVIDER)
    print(f"[vocab_function] {len(text):,}자 -> {len(pairs)}짝")
    return pairs, document


@work_regist("filter_vocab_function")
def filter_vocab_function(*args, **kwargs):
    """못 쓸 짝을 걸러낸다. 모델도 DB 도 안 쓴다.

    지금 gpt 로 뽑으면 거의 안 버린다. 남겨두는 이유는 중복 제거와, 모델이나
    프롬프트를 바꿨을 때의 안전망이다. 버린 것도 이유와 함께 찍어서 규칙이 정상
    항목을 오탐하면 보이게 한다.
    """
    pairs, document = args[0]
    kept, dropped = get_controller().filter_vocab(pairs)
    for pair in kept:
        print(f"[filter_vocab_function] {pair.term} -> {pair.expansion}")
    for pair, reason in dropped:
        print(f"[filter_vocab_function] 버림({reason}) {pair.term}")
    return kept, document


@work_regist("save_vocab_function")
def save_vocab_function(*args, **kwargs):
    """사전을 DB 에 넣는다. 같은 짝을 또 넣어도 안 늘어난다(upsert).

    다음 단계(임베딩)가 문서를 받아야 하므로 문서를 돌려준다.
    """
    kept, document = args[0]
    added = db_call(
        "save_vocab_pairs",
        pairs=[{"term": p.term, "expansion": p.expansion} for p in kept],
    )
    print(f"[save_vocab_function] 확장어 {added}개 추가")
    return document


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
    if not QUERY:
        raise ValueError("질의가 비어 있습니다. RAG_QUERY 환경변수를 지정하세요.")

    vocab = load_vocab()
    vector, weights = get_controller().embed_query(QUERY, vocab)
    print(f"[embed_query_function] 사전 {len(vocab)}개 적용")
    return QUERY, vector, weights


@work_regist("hybrid_search_function")
def hybrid_search_function(*args, **kwargs):
    """dense + sparse 를 RRF 로 합쳐 검색한다.

    두 점수를 더하지 않고 순위로 합친다 — dense 는 코사인이라 0~1 인데 sparse 는
    가중치 내적이라 상한이 없어서, 그냥 더하면 sparse 가 결과를 지배한다.
    """
    query, vector, weights = args[0]
    rag = get_controller()
    hits = db_call(
        "search_documents_hybrid",
        query_vector=to_plain_vector(vector),
        query_weights=to_plain_sparse(weights),
        sparse_dim=rag.sparse_dimension,
        top_k=TOP_K_SEARCH,
    ) or []
    print(f"[hybrid_search_function] 조각 {len(hits)}개")
    return query, hits


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
    query, hits = args[0]
    rag = get_controller()

    contexts = rag.build_contexts(hits)
    print(f"[rerank_function] 맥락 {len(contexts)}개 "
          f"(승격 {sum(1 for c in contexts if c.merged)})")

    ordered = rag.rerank(query, contexts, top_k=TOP_K_FINAL)
    for rank, context in enumerate(ordered, 1):
        print(f"[rerank_function] {rank}. score={context.rerank_score:.4f} "
              f"merged={context.merged} {context.breadcrumb[:60]}")
    return query, ordered

#------------------------------------------------┌> 답변


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
    query, contexts, refs  = args[0]
    rag = get_controller()

    draft = rag.answer(query, contexts, provider=DRAFT_PROVIDER, external=refs)
    print(f"[answer_function] 초안 {DRAFT_PROVIDER} {len(draft):,}자 (내부용)")

    answers = rag.refine_all(query, contexts, draft, ANSWER_PROVIDERS, external=refs)
    for name in ANSWER_PROVIDERS:
        mark = f"{len(answers[name]):,}자" if name in answers else "실패"
        print(f"[answer_function] 다듬기 {name} {mark}")

    if not answers:
        raise RuntimeError(f"다듬기가 전부 실패했습니다: {ANSWER_PROVIDERS}")
    return [{"provider": name, "answer": text} for name, text in answers.items()]


@work_regist("merge_function")
def merge_function(*args, **kwargs):
    """다듬은 답변들을 하나로 합친다. {provider, answer} 하나로 돌려준다.

    답변이 하나면 모듈이 호출 없이 그대로 돌려준다. 셋 이상도 한 번에 넘긴다 —
    둘씩 접어 올리면 나중 것이 '이미 합쳐진 것' 과 1:1 로 겨루게 되어 앞선 답변의
    근거가 묽어진다.
    """
    answers = args[0]
    merged = get_controller().merge(
        QUERY, [a["answer"] for a in answers], provider=MERGE_WITH)
    print(f"[merge_function] {MERGE_WITH} 병합 {len(merged):,}자")
    return {"provider": MERGE_WITH, "answer": merged}


#------------------------------------------------┌> 외부 데이터
@work_regist("search_api_function")
def search_api_function(*args, **kwargs):
    """질의와 비슷한 외부 API 를 찾는다. (query, contexts, api_refs).

    질의 벡터를 다시 만든다. 앞 단계가 이미 만들었지만 rerank 까지 오면서 버려졌고,
    가져오려면 체인 중간 두 함수의 반환값을 바꿔야 한다. 질의 한 문장이라 수십 ms 다.

    실패해도 답변을 막지 않는다. 이건 부가 정보라 없으면 없는 대로 답하면 된다 —
    외부 데이터 테이블이 비었다는 이유로 질의 전체가 죽으면 안 된다.
    """
    query, contexts = args[0]

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
    return query, contexts, refs


@work_regist("embed_api_function")
def embed_api_function(*args, **kwargs):
    """등록된 외부 API 목록을 임베딩해서 api_data_vectors 에 넣는다. 저장한 개수.

    임베딩 대상은 title 과 source 뿐이다. data 는 API 응답 원문이라 길고 자주 바뀌고,
    key 는 인증키다 — 둘 다 벡터에 들어가면 안 된다.

    문서 색인과 달리 sparse 를 만들지 않는다. api_data_vectors 는 embedding
    vector(1024) 한 컬럼뿐이라 넣을 자리가 없다. title 은 30~60자로 짧아서 어휘가
    겹칠 일이 적고, 그런 짧은 문자열은 sparse 가 잘 못 잡는다.

    매번 전체를 다시 임베딩한다. 어떤 url 에 벡터가 이미 있는지 물어볼 task 가
    db_manager 에 없기 때문이다. save_api_data_vector 가 UPSERT 라 덮어써도 문제는
    없고, 목록이 수십 건 규모라 한 번의 forward 로 끝난다. 수천 건이 되면 그때
    '벡터 없는 것만' 을 돌려주는 프로시저를 요청하는 게 맞다.

    체인의 첫 단계로도 쓰므로 args 가 비어 있어도 돈다.
    """
    inserted_api_data = args[0]
    if not inserted_api_data:
        print("[embed_api_function] 등록된 외부 API 가 없습니다")
        return 0

    texts = [f"{inserted_api_data['title']} · {inserted_api_data['source']}"]
    vectors = get_controller().embed_texts(texts)


    try:
        db_call("save_api_data_vector", url=inserted_api_data["url"], embedding=vectors[0])

    except Exception as e:
            # url 하나가 실패해도 나머지는 넣는다. FK 위반(api_datas 에서 지워진 url)이
            # 대부분이라, 하나 때문에 전체를 되돌릴 이유가 없다.
            print(f"[embed_api_function] 실패 {inserted_api_data['url']}: {type(e).__name__} - {e}")

    print(f"[embed_api_function] 저장 {len(inserted_api_data)}개")
    return len(inserted_api_data)