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
    },
  },
})
