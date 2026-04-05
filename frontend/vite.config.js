import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiUrl = env.VITE_API_URL || 'http://localhost:8000'

  return {
    plugins: [vue()],
    resolve: { alias: { '@': '/src' } },
    server: {
      proxy: {
        '/api': {
          target: apiUrl,
          changeOrigin: true,
        }
      }
    }
  }
})
