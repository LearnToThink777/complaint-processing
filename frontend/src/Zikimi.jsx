import base from './assets/zikimi/base.svg'
import shield from './assets/zikimi/shield.svg'
import wave from './assets/zikimi/wave.svg'
import search from './assets/zikimi/search.svg'
import docs from './assets/zikimi/docs.svg'
import done from './assets/zikimi/done.svg'
import wait from './assets/zikimi/wait.svg'
import cheer from './assets/zikimi/cheer.svg'

// 마스코트 '지킴이'. 포즈는 src/assets/zikimi/ 아래 SVG 파일 하나당 하나씩 대응한다 —
// 그림을 고치고 싶으면 해당 .svg 파일만 열어 고치면 되고, 나중에 PNG로 갈아끼우더라도
// 아래 import 경로만 바꾸면 화면 쪽 코드는 손댈 필요가 없다.
const POSES = { base, shield, wave, search, docs, done, wait, cheer }

// alt 를 주지 않으면 장식용으로 보고 스크린리더에서 감춘다 — 옆에 이미 같은 뜻의
// 문구가 있는 자리(빈 상태 안내, 히어로 인사)가 대부분이라 읽어 주면 중복이 된다.
export default function Zikimi({ pose = 'base', size = 40, alt = '', className = '', style }) {
  const src = POSES[pose] || POSES.base
  return (
    <img
      src={src}
      width={size}
      height={size}
      alt={alt}
      aria-hidden={alt ? undefined : true}
      draggable="false"
      className={`zikimi ${className}`.trim()}
      style={{ display: 'block', flex: 'none', ...style }}
    />
  )
}
