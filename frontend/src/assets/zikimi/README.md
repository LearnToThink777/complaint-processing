# 지킴이 마스코트 에셋

포즈 하나당 SVG 파일 하나. 화면에서는 직접 import 하지 말고 `src/Zikimi.jsx` 를 쓴다.

```jsx
import Zikimi from '../Zikimi.jsx'

<Zikimi pose="shield" size={54} />
<Zikimi pose="done" size={84} alt="접수가 완료되었습니다" />
```

| 파일 | pose | 쓰는 자리 |
| --- | --- | --- |
| `base.svg` | `base` | 특별한 맥락이 없는 기본 등장 |
| `shield.svg` | `shield` | 브랜드 로고(랜딩 · 민원인 헤더 · 직원 사이드바) |
| `wave.svg` | `wave` | 인사 — 홈 히어로, 민원인 포털 입구 |
| `search.svg` | `search` | 검토/조회 중 · 검색 결과 없음 |
| `docs.svg` | `docs` | 서류 · 이력 · 직원 포털 입구 |
| `done.svg` | `done` | 접수 완료 · 처리 완료 |
| `wait.svg` | `wait` | 로딩 · 대기 |
| `cheer.svg` | `cheer` | 격려가 필요한 빈 상태 |

## 그림을 고칠 때

모든 포즈가 같은 몸통 path·얼굴 좌표를 공유한다(viewBox `0 0 200 200`).
얼굴이나 몸통을 바꾸면 8개 파일에 같은 수정을 반영해야 톤이 어긋나지 않는다.

- 몸통: `M100 14C64 14 40 62 40 108c0 40 26 66 60 66s60-26 60-66c0-46-24-94-60-94Z`
- 눈: `(78, 98)` / `(122, 98)`, 입: y 116~136, 볼: `(59, 118)` / `(141, 118)`
- 팔은 `<defs>` 의 `*-arm` 을 `<use>` 로 배치한다. **소품을 든 포즈는 팔을 먼저 그리고
  소품을 나중에 그린다** — 순서가 반대면 손이 소품을 뚫고 나온 것처럼 보인다.
- id 는 파일명을 접두사로 쓴다(`shield-skin`, `docs-blush` …). 여러 SVG 를 한 문서에
  인라인해도 gradient/filter id 가 충돌하지 않게 하기 위해서다.

## PNG 로 교체할 때

`Zikimi.jsx` 의 import 8줄만 `.png` 로 바꾸면 된다. 호출부는 그대로 둔다.
