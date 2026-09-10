#================================================
# paths.py
#================================================
"""파일이 쌓이는 곳. 세 파일이 같은 값을 봐야 해서 여기 한 번만 둔다.

전에는 main.py, document_functions, rag_functions 가 각자 os.environ 을 읽었다.
같은 환경변수를 같은 기본값으로 읽고 있어서 어긋나지는 않았지만, 누가 한 곳의
기본값만 고치면 파일을 쓰는 곳과 내보내는 곳이 달라진다 — 저장은 됐는데 화면에
안 뜨는 상태가 된다.

k8s 는 PVC 를 /app/documents 와 /app/images 에 붙인다(values.yaml). WORKDIR 이
/app 이라 아래 기본값이 정확히 거기로 떨어진다. 환경변수로 바꾸려면 values.yaml 의
마운트 경로도 함께 바꿔야 한다 — 안 그러면 PVC 밖에 쌓여서 파드가 재시작될 때 사라진다.

unpacked 는 마운트가 없다. 컨테이너 임시 디스크라 쌓이면 파드가 쫓겨난다.
parse_function 이 파싱을 마치면 비운다.
"""

import os

IMAGE_DIR = os.environ.get("RAG_IMAGE_DIR", "images")
DOCUMENT_DIR = os.environ.get("RAG_DOCUMENT_DIR", "documents")
UNPACK_DIR = os.environ.get("RAG_UNPACK_DIR", "unpacked")
