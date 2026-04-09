const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');

// 保持窗口对象的全局引用，防止被垃圾回收
let mainWindow;

function createWindow() {
    // 创建浏览器窗口
    mainWindow = new BrowserWindow({
        width: 1400,
        height: 900,
        minWidth: 1200,
        minHeight: 700,
        webPreferences: {
            nodeIntegration: false,      // 安全：禁用 Node 集成
            contextIsolation: true,       // 安全：启用上下文隔离
            preload: path.join(__dirname, 'preload.js')  // 预加载脚本
        },
        titleBarStyle: 'default',
        show: false  // 先不显示，等加载完成再显示
    });

    // 加载本地 HTML 文件
    mainWindow.loadFile(path.join(__dirname, 'src', 'index.html'));

    // 开发工具（生产环境关闭）
    // mainWindow.webContents.openDevTools();

    // 窗口加载完成后显示
    mainWindow.once('ready-to-show', () => {
        // 清除旧的服务器配置缓存，使用代码中的默认值
        mainWindow.webContents.executeJavaScript("localStorage.removeItem('serverConfig')");
        mainWindow.show();
    });

    // 窗口关闭时的处理
    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

// Electron 初始化完成
app.whenReady().then(() => {
    createWindow();

    // macOS: 点击 dock 图标时重新创建窗口
    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });
});

// 所有窗口关闭时退出应用（Windows/Linux）
app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

// 防止多开
const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
    app.quit();
} else {
    app.on('second-instance', () => {
        // 用户尝试打开第二个实例时，聚焦到已有窗口
        if (mainWindow) {
            if (mainWindow.isMinimized()) {
                mainWindow.restore();
            }
            mainWindow.focus();
        }
    });
}
