import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 빌드 산출물은 complaint_processing/ui/ 로 나가고, FastAPI 가 /ui 로 서빙한다.
// base '/ui/' 라서 index.html 은 자산을 /ui/assets/... 로 참조한다(같은 오리진).
// 개발 시에는 vite dev 서버(5173)가 /api 를 FastAPI(8000)로 프록시한다.
export default defineConfig({
  base: '/ui/',
  plugins: [react()],
  build: {
    outDir: '../ui',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      // 협상·중재 콘솔과 파이프라인 뷰어는 React 앱이 아니라 FastAPI 가 패키지 루트에서
      // 서빙하는 정적 HTML 이다. base 가 '/ui/' 라서 dev 서버(5173)에서 '/mediation.html'
      // 을 열면 "public base URL is /ui/" 404 가 났다 — 콘솔이 안 열리던 원인.
      // 프록시로 넘겨 dev·prod 모두 같은 '/mediation.html' 링크가 동작하게 한다.
      '/mediation.html': 'http://127.0.0.1:8000',
      '/mediation.json': 'http://127.0.0.1:8000',
      '/viewer.html': 'http://127.0.0.1:8000',
      '/frames.json': 'http://127.0.0.1:8000',
    },
  },
})
