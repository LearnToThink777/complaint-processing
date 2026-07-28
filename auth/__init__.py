"""인증 계층 — 로그인·토큰·현재 사용자 판별.

팀원(지영) 브랜치 feat/login(PR #2)의 구현을 이식했다. 인증 로직(bcrypt 해싱, JWT
access/refresh, 역할 가드)은 그쪽 설계를 그대로 쓰고, 인프라만 이 저장소에 맞췄다:

  - 패키지 이름을 `api` 가 아니라 `auth` 로 둔다 — `api.py`(FastAPI 앱)와 이름이 겹치면
    Python 이 패키지를 모듈보다 먼저 찾아 `complaint_processing.api:app` 기동이 깨진다.
  - 자체 engine/Base/SessionLocal 을 두지 않고 db.py·models.py 를 쓴다(Base 가 둘이면
    메타데이터 레지스트리가 갈라져 같은 테이블이 두 번 정의된다).
  - Customer/Staff 모델도 models.py 것을 쓴다(컬럼은 원래 동일했다).

지금은 '신원 판별용'으로만 쓴다 — 토큰이 있으면 그 사람으로 동작하고 없으면 시드 계정으로
되돌아간다. 라우트를 막지는 않는다(require_staff/require_customer 는 전환용으로 남겨 둠).
"""
