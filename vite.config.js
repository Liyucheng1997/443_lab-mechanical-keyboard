import { defineConfig } from 'vite';

// base 用相对路径，部署到 GitHub Pages 子路径也能正常加载
export default defineConfig({ base: './' });
