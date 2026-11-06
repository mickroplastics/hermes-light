import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, readdirSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import os from 'node:os'
import path from 'node:path'

const require = createRequire(path.resolve('apps/desktop/package.json'))
const { _electron: electron } = require('@playwright/test')
const [app, out] = process.argv.slice(2)
const sandbox = mkdtempSync(path.join(os.tmpdir(), 'hermes-light-smoke-'))
const hermesHome = path.join(sandbox, 'hermes')
const executable = path.join(app, 'Contents/MacOS/Hermes Light')
const client = await electron.launch({
  executablePath: executable,
  env: { ...process.env, HERMES_HOME: hermesHome,
    HERMES_DESKTOP_USER_DATA_DIR: path.join(sandbox, 'desktop'),
    HERMES_DESKTOP_HERMES_ROOT: process.cwd() },
  timeout: 90000
})
try {
  const page = await client.firstWindow({ timeout: 90000 })
  await page.waitForFunction(async () =>
    Boolean(window.hermesDesktop && (await window.hermesDesktop.getBootstrapState()).setupChoice),
    undefined, { timeout: 90000 })
  await page.getByRole('heading', { name: 'Connect to existing Hermes', exact: true }).waitFor({ timeout: 30000 })
  const result = await page.evaluate(async () => {
    const denied = []
    for (const method of ['continueBootstrapLocal', 'repairBootstrap']) {
      try { await window.hermesDesktop[method](); denied.push(false) }
      catch (error) { denied.push(String(error).includes('client-only')) }
    }
    return { denied, body: document.body.innerText }
  })
  assert.deepEqual(result.denied, [true, true], 'Local installation or repair was not blocked')
  assert.ok(!result.body.includes('Install Hermes locally'), 'Local installation is offered')
  await page.screenshot({ path: path.join(out, 'onboarding.png') })
  const descendants = await client.evaluate(() => process.pid)
  const rows = execFileSync('ps', ['-axo', 'pid=,ppid=,command='], { encoding: 'utf8' })
    .trim().split('\n').map(line => line.trim().match(/^(\d+)\s+(\d+)\s+(.*)$/)).filter(Boolean)
  const children = new Set([descendants])
  for (let size = -1; size !== children.size;) {
    size = children.size
    for (const [, pid, parent] of rows) if (children.has(Number(parent))) children.add(Number(pid))
  }
  const runtime = rows.filter(([, pid, , command]) => children.has(Number(pid)) &&
    /(?:hermes_cli|gateway (?:ensure|run)|install\.sh|python.*hermes)/i.test(command))
  assert.equal(runtime.length, 0, 'Local Hermes child found')
  const forbidden = ['hermes-agent', 'tools', 'venv', '.venv', 'bootstrap-complete.json']
  for (const name of forbidden) assert.ok(!existsSync(path.join(hermesHome, name)), `Created ${name}`)
  writeFileSync(path.join(out, 'smoke.json'), JSON.stringify({
    onboarding: true, localInstallDenied: true, localRepairDenied: true,
    localRuntimeProcesses: 0, localRuntimePayload: false,
    hermesHomeEntries: existsSync(hermesHome) ? readdirSync(hermesHome) : []
  }, null, 2) + '\n')
} finally {
  await client.close()
}
