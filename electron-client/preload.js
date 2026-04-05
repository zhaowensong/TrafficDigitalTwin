// 预加载脚本 - 在渲染进程加载前执行
// 用于安全地暴露主进程 API 给渲染进程

const { contextBridge } = require('electron');

// 可以在这里暴露安全的 API 给前端使用
// 目前前端直接使用 fetch 访问后端，不需要额外暴露

contextBridge.exposeInMainWorld('electronAPI', {
    // 示例：如果需要从主进程获取信息
    // getAppVersion: () => process.env.npm_package_version
});

// 记录 Electron 环境已加载
console.log('Electron preload script loaded');
