// Capture design screenshots of the running app into ../screenshots via headless
// Chrome + the DevTools Protocol. Logs in through the API, seeds the JWT into
// localStorage (key 'cam.token', matching AuthContext), then shoots each route.
//
// Usage: node scripts/capture-screenshots.mjs
// Requires: the stack running (frontend :5173, backend :8000) and Chrome installed.

import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { tmpdir } from 'node:os'

const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = join(__dirname, '..', 'screenshots')
const FRONTEND = 'http://localhost:5173'
const BACKEND = 'http://localhost:8000'
const PORT = 9222
// Chrome location is platform-dependent; allow CHROME_BIN to override.
const CHROME =
  process.env.CHROME_BIN ||
  (process.platform === 'darwin'
    ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    : 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe')
const W = 1280
const H = 1480 // minimum clip height; tall pages are captured in full (see below)

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// Default run captures the core pages as admin. Override with CLI args for a
// single custom shot as any user:  node capture-screenshots.mjs <user> <path> <file>
const [, , argUser, argPath, argFile] = process.argv
const USER = argUser || 'admin'
const shots =
  argUser && argPath && argFile
    ? [{ file: argFile, path: argPath, auth: true }]
    : [
        { file: '01-login.png', path: '/login', auth: false },
        { file: '02-home.png', path: '/', auth: true },
        { file: '03-cost-centres.png', path: '/cost-centres', auth: true },
        { file: '04-key-requests.png', path: '/key-requests', auth: true },
      ]

async function getToken() {
  const res = await fetch(`${BACKEND}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: USER, password: USER }),
  })
  if (!res.ok) throw new Error(`login failed: ${res.status}`)
  return (await res.json()).access_token
}

function launchChrome(userDataDir) {
  return spawn(
    CHROME,
    [
      '--headless=new',
      '--disable-gpu',
      '--hide-scrollbars',
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${userDataDir}`,
      `--window-size=${W},${H}`,
      '--force-device-scale-factor=1.5',
      'about:blank',
    ],
    { stdio: 'ignore' },
  )
}

async function wsTarget() {
  for (let i = 0; i < 40; i++) {
    try {
      const list = await (await fetch(`http://localhost:${PORT}/json`)).json()
      const page = list.find((t) => t.type === 'page')
      if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl
    } catch {
      /* not up yet */
    }
    await sleep(250)
  }
  throw new Error('Chrome DevTools endpoint never came up')
}

function cdpClient(url) {
  const ws = new WebSocket(url)
  let id = 0
  const pending = new Map()
  const ready = new Promise((res) => (ws.onopen = res))
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data)
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg)
      pending.delete(msg.id)
    }
  }
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const myId = ++id
      pending.set(myId, (m) =>
        m.error ? reject(new Error(`${method}: ${m.error.message}`)) : resolve(m.result),
      )
      ws.send(JSON.stringify({ id: myId, method, params }))
    })
  return { ready, send, close: () => ws.close() }
}

async function main() {
  mkdirSync(OUT, { recursive: true })
  const token = await getToken()
  const userDataDir = join(process.env.TEMP || tmpdir(), `cr-shots-${Date.now()}`)
  const chrome = launchChrome(userDataDir)
  try {
    const { ready, send, close } = cdpClient(await wsTarget())
    await ready
    await send('Page.enable')
    await send('Runtime.enable')

    // Seed the auth token on the app origin so authed routes restore a session.
    await send('Page.navigate', { url: `${FRONTEND}/login` })
    await sleep(800)
    await send('Runtime.evaluate', {
      expression: `localStorage.setItem('cam.token', ${JSON.stringify(token)})`,
    })

    for (const shot of shots) {
      if (!shot.auth) {
        await send('Runtime.evaluate', {
          expression: `localStorage.removeItem('cam.token')`,
        })
      } else {
        await send('Runtime.evaluate', {
          expression: `localStorage.setItem('cam.token', ${JSON.stringify(token)})`,
        })
      }
      await send('Page.navigate', { url: `${FRONTEND}${shot.path}` })
      await sleep(1400) // load + React render + /auth/me round-trip
      await send('Runtime.evaluate', {
        expression: 'document.fonts.ready',
        awaitPromise: true,
      })
      await sleep(400)
      // Capture the full page so tall lists (keys, requests) aren't clipped.
      const { result: heightResult } = await send('Runtime.evaluate', {
        expression:
          'Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)',
        returnByValue: true,
      })
      const pageH = Math.min(Math.max(Number(heightResult?.value) || H, H), 6000)
      const { data } = await send('Page.captureScreenshot', {
        format: 'png',
        captureBeyondViewport: true,
        clip: { x: 0, y: 0, width: W, height: pageH, scale: 1 },
      })
      writeFileSync(join(OUT, shot.file), Buffer.from(data, 'base64'))
      console.log(`saved ${shot.file}`)
    }
    close()
  } finally {
    chrome.kill()
  }
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
