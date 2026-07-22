// 서버가 없을 때 화면이 비지 않도록 하는 내장 폴백.
// demo_store.py 의 시드와 같은 값을 축약해 담았다(라벨 포함 형태).
const outcome = (code) => {
  const m = { accepted: '고객 수용', partial: '일부 수용', rejected: '기각' }
  const t = { accepted: 'good', partial: 'warn', rejected: 'bad' }
  return code ? { code, ko: m[code], tone: t[code], decided_by: '담당자' } : null
}

export const FALLBACK = {
  staffSummary: {
    summary: {
      officer: '홍길동',
      team: '준법감시팀',
      cards: [
        { key: 'todo', label: '오늘 처리할 항목', value: 24, unit: '건', hint: '전체 32건', tone: 'info' },
        { key: 'due_soon', label: '기한 임박 사건', value: 7, unit: '건', hint: '3일 이내 마감', tone: 'bad' },
        { key: 'ai_wait', label: 'AI 검토 대기', value: 18, unit: '건', hint: '검토 필요', tone: 'warn' },
        { key: 'done_today', label: '오늘 완료', value: 15, unit: '건', hint: '목표 20건', tone: 'good' },
      ],
    },
    recent: [
      { case_id: 'C-2024-05123', customer: '김민수', type: 'ELS 불완전판매', outcome: outcome('accepted'), processed_at: '2025-05-20 16:42', officer: '홍길동' },
      { case_id: 'C-2024-05122', customer: '이영희', type: 'DLF 손실', outcome: outcome('partial'), processed_at: '2025-05-20 15:31', officer: '홍길동' },
      { case_id: 'C-2024-05121', customer: '박준혁', type: '예금상품 설명부족', outcome: outcome('rejected'), processed_at: '2025-05-20 14:22', officer: '최지영' },
      { case_id: 'C-2024-05120', customer: '정다은', type: '투자권유 부적정', outcome: outcome('accepted'), processed_at: '2025-05-20 11:10', officer: '홍길동' },
      { case_id: 'C-2024-05119', customer: '최성민', type: '신용카드 과다수수료', outcome: outcome('partial'), processed_at: '2025-05-20 10:05', officer: '최지영' },
    ],
  },
  staffIntake: [
    { case_id: 'C-2024-05130', customer: '김서연', type: 'ELS 불완전판매', intake_date: '2024-05-21', track: 'legal' },
    { case_id: 'C-2024-05129', customer: '오민석', type: 'DLF 손실', intake_date: '2024-05-21', track: 'legal' },
    { case_id: 'C-2024-05128', customer: '배지현', type: '펀드 설명부족', intake_date: '2024-05-21', track: 'legal' },
    { case_id: 'C-2024-05127', customer: '유재현', type: '투자권유 부적정', intake_date: '2024-05-21', track: 'legal' },
    { case_id: 'C-2024-05126', customer: '한지은', type: '예금 만기 미이행', intake_date: '2024-05-21', track: 'legal' },
    { case_id: 'C-2024-05125', customer: '정무진', type: '신용카드 분쟁', intake_date: '2024-05-21', track: 'general' },
    { case_id: 'C-2024-05124', customer: '김하늘', type: '보험금 지급거절', intake_date: '2024-05-21', track: 'legal' },
  ],
  staffChecklistPlan: {
    case_id: 'C-2024-05130',
    classification: 'ELS 불완전판매',
    track: 'legal',
    items: [
      { n: 1, item: '적합성 원칙 위반 여부', law: '금융소비자보호법 제17조', status: 'pending' },
      { n: 2, item: '설명의무 이행 여부', law: '금융소비자보호법 제19조', status: 'pending' },
      { n: 3, item: '불완전판매 판단', law: '금융소비자보호법 제20조', status: 'pending' },
      { n: 4, item: '손해 인과관계', law: '민법 제750조', status: 'pending' },
      { n: 5, item: '손해액 산정 적정성', law: '분쟁조정 기준', status: 'pending' },
      { n: 6, item: '배상책임 범위', law: '분쟁조정위 결정례 2024-1041', status: 'pending' },
    ],
    reasoning: '안정추구형 고객 대상 고위험 ELS 판매 정황. 적합성·설명의무 중심으로 6개 항목 검토 계획 수립.',
  },
  staffCase: {
    case_id: 'C-2024-05130',
    type: 'ELS 불완전판매',
    customer: '김서연',
    status: 'reviewing',
    due_date: '2024-05-23',
    days_left: 2,
    over_deadline_risk: true,
    ledger: [
      { item: '적합성 원칙 위반 여부', code: '금소법 §17', verdict: '위반', critic: 'PASS' },
      { item: '설명의무 이행 여부', code: '금소법 §19', verdict: '위반', critic: 'PASS' },
      { item: '불완전판매 판단', code: '금소법 §20', verdict: '해당', critic: 'PASS' },
      { item: '손해 인과관계', code: '민법 §750', verdict: '인과관계 인정', critic: 'ESCALATE' },
      { item: '손해액 산정 적정성', code: '배상 5750', verdict: '일부 인정', critic: 'PASS' },
      { item: '배상책임 범위', code: '결정례 2024-1041', verdict: '50% 배상', critic: 'BLOCK' },
    ],
    critic_summary: { reviewed: 6, PASS: 4, ESCALATE: 1, BLOCK: 1 },
    similar_cases: [
      { case_id: 'C-2024-01045', title: 'ELS 불완전판매 · 50% 배상', similarity: 92, closed_at: '2024-02-14', outcome_ko: '고객 수용' },
      { case_id: 'C-2023-08912', title: 'ELS 불완전판매 · 40% 배상', similarity: 85, closed_at: '2023-11-03', outcome_ko: '조정 성립' },
      { case_id: 'C-2023-07654', title: 'ELS 불완전판매 · 60% 배상', similarity: 78, closed_at: '2023-09-21', outcome_ko: '고객 수용' },
    ],
    renegotiation: {
      attachments: [{ name: '재협상_안_20240521.pdf', size: '1.2MB', uploaded_at: '2024-05-21 14:33' }],
      note: '예상 완료일이 처리 기한을 초과할 위험. 재협상 자료 검토 후 담당자가 새 기한을 결정합니다.',
    },
  },
  staffHistory: {
    customer: '김민수',
    customer_no: '123-45-67890',
    repeat_pattern: { type: 'ELS 불완전판매', count: 3, message: '동일 유형(ELS 불완전판매) 민원이 총 3회 접수되었습니다.' },
    rows: [
      { case_id: 'C-2024-05123', intake_date: '2024-05-20', type: 'ELS 불완전판매', outcome: outcome('accepted'), result: '배상 50%', repeat: null, consistency: 92 },
      { case_id: 'C-2023-11456', intake_date: '2023-10-12', type: 'ELS 불완전판매', outcome: outcome('partial'), result: '배상 30%', repeat: '동일 유형 2회차', consistency: 85 },
      { case_id: 'C-2023-07331', intake_date: '2023-06-21', type: '펀드 설명부족', outcome: outcome('rejected'), result: '-', repeat: null, consistency: 76 },
      { case_id: 'C-2022-09110', intake_date: '2022-08-05', type: '보험금 지급거절', outcome: outcome('partial'), result: '배상 20%', repeat: null, consistency: 81 },
      { case_id: 'C-2022-04122', intake_date: '2022-04-18', type: '신용카드 수수료', outcome: outcome('accepted'), result: '환급', repeat: null, consistency: 90 },
      { case_id: 'C-2021-10203', intake_date: '2021-10-30', type: '대출금리 불만', outcome: outcome('rejected'), result: '-', repeat: null, consistency: 70 },
    ],
  },
  staffMe: {
    account: { name: '홍길동', team: '준법감시팀', rank: '선임조사역', email: 'hong.gildong@internal.com', phone: '010-1234-5678', verified: true },
    notifications: [
      { key: 'due_soon', label: '기한 임박 알림', enabled: true },
      { key: 'ai_done', label: 'AI 검토 완료 알림', enabled: true },
      { key: 'transfer', label: '이관 사건 알림', enabled: true },
      { key: 'system', label: '시스템 공지 알림', enabled: false },
    ],
    activity_log: [
      { at: '2024-05-21 09:12', action: '로그인', detail: '성공', ip: '10.20.30.40' },
      { at: '2024-05-21 09:11', action: '사건 검토', detail: 'C-2024-05130 열람', ip: '10.20.30.40' },
      { at: '2024-05-20 08:55', action: '자료 다운로드', detail: '재협상_안_20240521.pdf', ip: '10.20.30.40' },
      { at: '2024-05-20 16:42', action: '사건 처리 완료', detail: 'C-2024-05123', ip: '10.20.30.40' },
      { at: '2024-05-20 15:31', action: '메모 작성', detail: 'C-2024-05122', ip: '10.20.30.40' },
    ],
    session: { current_ip: '10.20.30.40', last_login: '2024-05-21 09:12 (Chrome / Windows)' },
  },
  complainantHome: {
    greeting_name: '김지은',
    current_case: {
      case_id: 'C-2025-06-001', title: 'ELS 불완전판매 관련 민원', status: 'reviewing', status_ko: '검토 중',
      intake_date: '2025-06-01', expected_completion: '2025-07-31', days_left: 15, risk: true,
    },
    notices: [
      { icon: 'megaphone', title: '담당 검토가 시작되었어요', body: '사실관계 확인을 위한 검토가 진행 중입니다.', at: '2시간 전' },
      { icon: 'document', title: '추가 자료 제출 요청', body: '계약서 사본을 추가로 제출해주세요.', at: '1일 전' },
    ],
  },
  complainantProgress: {
    case_id: 'C-2025-06-001', title: 'ELS 불완전판매 관련 민원', intake_date: '2025-06-01',
    expected_completion: '2025-07-31', days_left: 15, risk: true, current: 1,
    steps: [
      { no: 1, key: 'intake', title: '접수', date: '2025-06-01', body: '민원이 정상적으로 접수되었어요. 담당자가 내용을 확인하고 있어요.' },
      { no: 2, key: 'reviewing', title: '검토 중', date: '2025-06-05 ~', body: '법률 검토와 사실관계 확인을 진행하고 있어요. 조금만 기다려주세요!' },
      { no: 3, key: 'verdict', title: '판정 완료', date: null, body: '검토가 끝나면 판정 결과를 안내드려요.' },
      { no: 4, key: 'negotiation', title: '협의', date: null, body: '필요 시 금융회사와 협의가 진행돼요.' },
      { no: 5, key: 'closed', title: '종결', date: null, body: '모든 절차가 완료되면 종결 안내를 드려요.' },
    ],
  },
  complainantHistory: [
    { case_id: 'C-2025-06-001', type: 'ELS 불완전판매 관련 민원', intake_date: '2025-06-01', status: 'reviewing', status_ko: '진행중', closed_at: null, expected_completion: '2025-07-31' },
    { case_id: 'C-2025-03-015', type: '펀드 환매 지연 관련 민원', intake_date: '2025-03-15', status: 'closed', status_ko: '종결', closed_at: '2025-04-20' },
    { case_id: 'C-2025-01-010', type: '대출 중도상환 수수료 관련 민원', intake_date: '2025-01-10', status: 'closed', status_ko: '종결', closed_at: '2025-02-05' },
    { case_id: 'C-2024-11-020', type: '보험금 지급 거절 관련 민원', intake_date: '2024-11-20', status: 'closed', status_ko: '종결', closed_at: '2024-12-30' },
  ],
  complainantMe: {
    name: '김지은', email: 'jieun.kim@example.com', verified: true,
    notifications: [
      { key: 'progress', label: '민원 진행 알림', hint: '진행 상황을 푸시로 알려드려요.', enabled: true },
      { key: 'notice', label: '중요 안내 알림', hint: '중요한 공지나 안내를 알려드려요.', enabled: true },
      { key: 'event', label: '이벤트/혜택 알림', hint: '이벤트 및 혜택 정보를 알려드려요.', enabled: false },
    ],
    menu: [
      { key: 'faq', label: '자주 묻는 질문' },
      { key: 'support', label: '고객센터 문의' },
      { key: 'about', label: '앱 정보', value: 'v1.0.0' },
    ],
  },
  complainantProductTypes: [
    { key: 'deposit', label: '예금·적금' },
    { key: 'fund', label: '펀드' },
    { key: 'els_dls', label: 'ELS·DLS' },
    { key: 'insurance', label: '보험' },
    { key: 'loan', label: '대출' },
    { key: 'etc', label: '기타' },
  ],
  submitComplaint: (body) => ({
    case_id: 'C-2025-06-101',
    product_type: body?.product_type ?? '',
    facts: body?.facts ?? '',
    attachments: body?.attachments ?? [],
    status: 'intake',
    status_ko: '접수 완료',
    received_at: '방금 전',
  }),
}
