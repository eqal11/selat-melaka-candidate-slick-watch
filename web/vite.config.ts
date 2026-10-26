import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
export default defineConfig({plugins:[react(),tailwindcss()],server:{host:'0.0.0.0',port:5173,proxy:{'/api':'http://localhost:8000'}},test:{environment:'jsdom',include:['src/**/*.test.ts']}})
