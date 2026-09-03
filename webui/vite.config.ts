import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// M4 REQ-401：开发态代理到 FastAPI（127.0.0.1:8765）；
// 构建产物输出 app/web/dist，由 FastAPI 静态托管（dist 优先、旧 static 兜底）。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
    },
  },
  build: {
    outDir: '../app/web/dist',
    emptyOutDir: true,
  },
});
