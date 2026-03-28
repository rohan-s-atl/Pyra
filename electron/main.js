const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const fs = require('fs')

let mainWindow = null
let backendProcess = null

// ── Find backend Python ───────────────────────────────────────────────────────
function getPythonPath() {
  const candidates = [
    path.join(process.resourcesPath, 'backend', 'venv', 'Scripts', 'python.exe'), // Windows packaged
    path.join(process.resourcesPath, 'backend', 'venv', 'bin', 'python'),          // Mac/Linux packaged
    path.join(__dirname, '..', 'backend', '.venv', 'Scripts', 'python.exe'),       // Windows dev
    path.join(__dirname, '..', 'backend', '.venv', 'bin', 'python'),               // Mac/Linux dev
    'python3',
    'python',
  ]
  for (const p of candidates) {
    if (p.includes('python3') || p.includes('python') && !p.includes('/')) return p
    if (fs.existsSync(p)) return p
  }
  return 'python'
}

function getBackendDir() {
  if (app.isPackaged) return path.join(process.resourcesPath, 'backend')
  return path.join(__dirname, '..', 'backend')
}

// ── Start FastAPI backend ─────────────────────────────────────────────────────
function startBackend() {
  const python  = getPythonPath()
  const backDir = getBackendDir()

  console.log(`[electron] Starting backend: ${python} in ${backDir}`)

  backendProcess = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], {
    cwd: backDir,
    env: { ...process.env },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  backendProcess.stdout.on('data', d => console.log(`[backend] ${d.toString().trim()}`))
  backendProcess.stderr.on('data', d => console.log(`[backend:err] ${d.toString().trim()}`))

  backendProcess.on('close', (code) => {
    console.log(`[electron] Backend exited with code ${code}`)
  })
}

// ── Create window ─────────────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width:  1440,
    height: 900,
    minWidth: 1200,
    minHeight: 700,
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#151419',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
    icon: path.join(__dirname, 'assets', 'icon.png'),
    title: 'Pyra — Wildfire Command Intelligence',
  })

  // Load built frontend or dev server
  if (app.isPackaged) {
    mainWindow.loadFile(path.join(__dirname, '..', 'frontend', 'dist', 'index.html'))
  } else {
    // Wait for Vite dev server
    const tryLoad = (retries = 20) => {
      mainWindow.loadURL('http://localhost:5173').catch(() => {
        if (retries > 0) setTimeout(() => tryLoad(retries - 1), 500)
      })
    }
    tryLoad()
  }

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  if (!app.isPackaged) mainWindow.webContents.openDevTools({ mode: 'detach' })
}

// ── IPC handlers ──────────────────────────────────────────────────────────────
ipcMain.handle('get-api-key', async () => {
  const envPath = path.join(getBackendDir(), '.env')
  try {
    const content = fs.readFileSync(envPath, 'utf8')
    const match = content.match(/ANTHROPIC_API_KEY=(.+)/)
    return match ? match[1].trim() : ''
  } catch { return '' }
})

ipcMain.handle('set-api-key', async (_, key) => {
  const envPath = path.join(getBackendDir(), '.env')
  try {
    let content = ''
    if (fs.existsSync(envPath)) content = fs.readFileSync(envPath, 'utf8')
    if (content.includes('ANTHROPIC_API_KEY=')) {
      content = content.replace(/ANTHROPIC_API_KEY=.*/g, `ANTHROPIC_API_KEY=${key}`)
    } else {
      content += `\nANTHROPIC_API_KEY=${key}`
    }
    fs.writeFileSync(envPath, content.trim() + '\n')
    return { success: true }
  } catch (e) { return { success: false, error: e.message } }
})

ipcMain.handle('restart-backend', async () => {
  if (backendProcess) { backendProcess.kill(); backendProcess = null }
  setTimeout(startBackend, 500)
  return { success: true }
})

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(() => {
  startBackend()
  // Give backend 2s to start before opening window
  setTimeout(createWindow, 2000)

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (backendProcess) backendProcess.kill()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  if (backendProcess) backendProcess.kill()
})