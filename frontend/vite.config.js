import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import dotenv from 'dotenv'

dotenv.config()

export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,
    proxy: {
      '/api': {
        target: process.env.VITE_IP_HOST || 'http://localhost:5000',
        changeOrigin: true,
        secure: false
      }
    }
  }
})
