import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Vue3 + Vercel AI SDK 前端。dev 时把 /chat-ai 代理到 Python 后端，避免跨域。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/chat-ai': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
