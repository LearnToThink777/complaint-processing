// 서버가 없을 때 화면이 비지 않도록 하는 내장 폴백(오프라인 시연용).
//
// 여기 값은 '실제 데이터인 척'하지 않는다 — 화면 구조를 확인할 수 있을 만큼만 최소로 두고,
// 사람이 읽는 자리(hint/reasoning)에는 서버 미연결 상태임을 밝힌다. 실제 숫자·이력·판정은
// 전부 DB 에서 온다(demo_db.py). 예전엔 여기에도 6~7행짜리 가짜 이력이 쌓여 있어서
// 서버가 살아 있는지 죽었는지 화면만 봐서는 구분할 수 없었다.

// 화면에 그대로 찍히는 문구다 — '폴백'처럼 내부에서만 쓰는 말 대신 사용자가 읽을 말로.
const OFFLINE = '서버에 연결하지 못해 최신 정보를 불러오지 못했습니다.'

export const FALLBACK = {
  staffSummary: {
    summary: {
      officer: '홍길동',
      team: '준법감시팀',
      cards: [
        { key: 'todo', label: '처리 중인 사건', value: 0, unit: '건', hint: OFFLINE, tone: 'info' },
        { key: 'due_soon', label: '기한 임박 사건', value: 0, unit: '건', hint: OFFLINE, tone: 'bad' },
        { key: 'ai_wait', label: '담당자 조치 대기', value: 0, unit: '건', hint: OFFLINE, tone: 'warn' },
        { key: 'done_today', label: '오늘 종결', value: 0, unit: '건', hint: OFFLINE, tone: 'good' },
      ],
    },
    recent: [],
  },
  staffIntake: [
    { case_id: 'C-2024-05130', customer: '김서연', type: 'ELS 불완전판매', intake_date: '2024-05-21', track: 'legal', status: 'intake' },
    { case_id: 'C-2024-05124', customer: '김하늘', type: '보험금 지급거절', intake_date: '2024-05-21', track: 'legal', status: 'intake' },
  ],
  staffChecklistPlan: {
    case_id: 'C-2024-05130',
    classification: 'ELS 불완전판매',
    track: 'legal',
    status: 'ready',
    items: [
      { item: '적합성 원칙 위반 여부', law: '금융소비자보호법 제17조', source: 'fallback', status: 'pending' },
      { item: '설명의무 이행 여부', law: '금융소비자보호법 제19조', source: 'fallback', status: 'pending' },
    ],
    reasoning: OFFLINE,
  },
  // 처리현황 목록 — 서버가 검색·정렬을 책임지므로 응답은 {rows, facets, …} 형태다.
  staffCases: {
    rows: [
      {
        case_id: 'C-2024-05130', customer: '김서연', type: 'ELS 불완전판매', track: 'legal',
        channel: 'referred', status: 'verdict', status_ko: '판정 완료', status_tone: 'info',
        intake_date: '2024-05-21', due_date: null, days_left: null, over_deadline_risk: false,
        verdict_status: 'ready', verdict_digest: '위반 1 · 미이행 1', item_count: 2,
        has_verdict: true, next_action: '판정 확정 · 안내문 게시',
        mediation_status: 'none', mediation_status_ko: null,
        last_activity_at: null, updated_at: null,
      },
    ],
    total: 1,
    facets: { all: 1, reviewing: 0, verdict_generating: 0, verdict: 1, negotiating: 0, closed: 0, open: 1, attention: 1, due_soon: 0 },
    sort: 'updated_at',
    order: 'desc',
    filters: { q: '', status: 'all', due_soon: false },
  },
  staffCase: {
    case_id: 'C-2024-05130',
    type: 'ELS 불완전판매',
    customer: '김서연',
    channel: 'referred',
    status: 'verdict',
    status_ko: '판정 완료',
    track: 'legal',
    facts: '안정추구형으로 분류된 개인 고객에게 원금 비보장 고위험 ELS를 판매. 원금손실 위험 고지가 불충분했다.',
    product_type: 'els_dls',
    product_en: 'ELS mis-selling',
    attachments: [],
    keywords: {},
    intake_date: '2024-05-21',
    due_date: null,
    days_left: 0,
    over_deadline_risk: false,
    verdict_status: 'ready',
    classification: 'ELS 불완전판매',
    reasoning: OFFLINE,
    ledger: [
      {
        seq: 1, item: '적합성 원칙 위반 여부', law: '금소법 §17', source: 'fallback',
        code: '금소법 §17', verdict: '위반', ko: '적합성원칙 위반 확인',
        detail: '안정추구형 고객에 고위험 ELS 판매', critic: 'PASS', critic_meta: {},
        verdict_source: 'ai', edited: false, ai_original: null,
        override_reason: '', overridden_by: '', overridden_at: null,
      },
      {
        seq: 2, item: '설명의무 이행 여부', law: '금소법 §19', source: 'fallback',
        code: '금소법 §19', verdict: '미이행', ko: '설명의무 미이행',
        detail: '원금손실 위험 고지 불충분', critic: 'PASS', critic_meta: {},
        verdict_source: 'ai', edited: false, ai_original: null,
        override_reason: '', overridden_by: '', overridden_at: null,
      },
    ],
    critic_summary: { reviewed: 2, PASS: 2, ESCALATE: 0, BLOCK: 0, CONFIRMED: 0 },
    verdict_options: ['위반', '미이행', '해당', '하자', '선례', '산정', '해당없음'],
    mediation: null,
    // 처리 기록·게시 이력은 DB 에서만 온다 — 서버가 없으면 보여줄 것이 없다.
    events: [],
    staff_messages: [],
    customer_case_count: 1,
    next_action: '판정 확정 · 안내문 게시',
  },
  // 중재 콘솔 목록 — 서버가 없으면 고를 사건도 없다(빈 목록 → 화면이 안내를 그린다).
  staffMediations: [],
  staffCaseSimilar: {
    cases: [
      { case: '분쟁조정 2023-0942 ELS', kind: '분쟁조정 결정례', org: '', business_days: 42, award_ratio: 50, product_en: 'ELS mis-selling', similarity: 88 },
    ],
    estimated_completion: '',
    due_date: '',
    over_deadline_risk: false,
    product_matched: true,
    corpus_widened: false,
    reasoning: OFFLINE,
  },
  staffHistory: {
    customer: '김서연',
    customer_no: '',
    repeat_pattern: null,
    summary: { total: 1, open: 1, closed: 0, first_intake: '2024-05-21', last_intake: '2024-05-21', types: 1 },
    candidates: [],
    rows: [
      {
        case_id: 'C-2024-05130', intake_date: '2024-05-21', type: 'ELS 불완전판매',
        channel: 'referred', status: 'verdict',
        outcome: { code: 'verdict', ko: '판정 완료', tone: 'info' }, result: '위반 1 · 미이행 1',
        event_count: 0, last_activity_at: null, mediation_status_ko: null,
        in_progress: true, repeat: null,
      },
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
    // 활동로그는 실제 처리 이력(stage_events)에서 온다 — 서버가 없으면 보여줄 것이 없다.
    activity_log: [],
    session: { current_ip: '', last_login: '' },
  },
  complainantHome: {
    greeting_name: '김지은',
    current_case: {
      case_id: 'C-2025-06-001', title: 'ELS 불완전판매 관련 민원', status: 'reviewing', status_ko: '검토 중',
      intake_date: '2025-06-01', expected_completion: '2025-07-31', days_left: 0, risk: false,
    },
    notices: [{ icon: 'megaphone', title: '서버에 연결하지 못했어요', body: OFFLINE, at: '' }],
  },
  complainantProgress: {
    case_id: 'C-2025-06-001', title: 'ELS 불완전판매 관련 민원', intake_date: '2025-06-01',
    expected_completion: '2025-07-31', days_left: 0, risk: false, current: 1,
    steps: [
      { no: 1, key: 'intake', title: '접수', date: '2025-06-01', body: '민원이 정상적으로 접수되었어요. 담당자가 내용을 확인하고 있어요.', entry_count: 0, entries: [] },
      { no: 2, key: 'reviewing', title: '검토 중', date: null, body: '법률 검토와 사실관계 확인을 진행하고 있어요. 조금만 기다려주세요!', entry_count: 0, entries: [] },
      { no: 3, key: 'verdict', title: '판정 완료', date: null, body: '검토가 끝나면 판정 결과를 안내드려요.', entry_count: 0, entries: [] },
      { no: 4, key: 'negotiation', title: '협의', date: null, body: '필요 시 금융회사와 협의가 진행돼요.', entry_count: 0, entries: [] },
      { no: 5, key: 'closed', title: '종결', date: null, body: '모든 절차가 완료되면 종결 안내를 드려요.', entry_count: 0, entries: [] },
    ],
    mediation: null,
    cases: [],
  },
  complainantHistory: [
    {
      case_id: 'C-2025-06-001', type: 'ELS 불완전판매 관련 민원', intake_date: '2025-06-01',
      status: 'reviewing', status_ko: '검토 중', closed_at: null, expected_completion: '2025-07-31',
      days_left: 0, step: 1, step_total: 5, step_title: '검토 중',
      entry_count: 0, last_activity_at: null, mediation_status_ko: null,
    },
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
      { key: 'about', label: '서비스 정보', value: 'v1.0.0' },
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
  // 서버 없을 때 게시는 무해하게 성공 처리(오프라인 데모용 스텁).
  publishDisclosure: (body) => ({
    case_id: 'C-2025-06-001',
    stage_key: body?.stage_key ?? 'verdict',
  }),
}
