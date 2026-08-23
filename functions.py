from ra import RagController
from taskcontroller import work_regist


UNPACKED = ""
HWPX_FILE_PATH = ""
ctr = RagController(unpack_dir=UNPACKED)


@work_regist("parser_funtion")
def hwpx_parser_fun(*args, **kwargs):
    print("여기까지 오지?")
    parser_data = ctr.parse_document(HWPX_FILE_PATH)
    print("파싱 함수 종료")
    return parser_data


@work_regist("chunk_funtion")
def document_chunk_fun(*args, **kwargs):
    chunk = ctr.chunk_parent_child(args[0])
    print("청킹 함수 종료")
    return chunk

@work_regist("embedded_funtion")
def chunk_embedding_fun(*args, **kwargs):
    vector = ctr.embed_bge_m3(args[0])
    print("임베딩 함수 종료")


