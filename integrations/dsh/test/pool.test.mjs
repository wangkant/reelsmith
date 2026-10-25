// The server pool against the fake reelsmith server over real stdio: the environment a server starts with, and
// the idle reaper sparing a server whose call is still running.
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after, describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'
import { ServerPool, serverEnv } from '../lib/pool.js'

const FAKE = fileURLToPath(new URL('./fixtures/fake-reelsmith.mjs', import.meta.url))
const work = mkdtempSync(join(tmpdir(), 'rs-pool-'))
after(() => rmSync(work, { recursive: true, force: true }))
const spec = { command: process.execPath, args: [FAKE], env: {} }
const text = result => result.content.map(block => block.text ?? '').join('\n')
const sleep = ms => new Promise(done => setTimeout(done, ms))

describe('serverEnv', () => {
  it('keeps the session folder off the server\'s imports and sets the fence', () => {
    const env = serverEnv({ ...spec, env: { EXTRA: '1' } }, { cwd: work, root: work })
    assert.equal(env.PYTHONSAFEPATH, '1')
    assert.equal(env.PYTHONUTF8, '1')
    assert.equal(env.EXTRA, '1')
    assert.equal(env.REELSMITH_ROOT, work)
    assert.equal(serverEnv(spec, { cwd: work, root: undefined }).REELSMITH_ROOT, undefined)
  })
})

describe('ServerPool', () => {
  it('starts servers with PYTHONSAFEPATH, so a module in the session folder cannot shadow reelsmith\'s', async () => {
    const pool = new ServerPool(() => spec)
    try {
      const result = await pool.get({ cwd: work, root: undefined }).call('env', {}, new AbortController().signal, 10_000)
      assert.match(text(result), /PYTHONSAFEPATH=1/)
    } finally {
      await pool.closeAll()
    }
  })

  it('does not reap a server while one of its calls runs', async () => {
    const pool = new ServerPool(() => spec)
    try {
      const server = pool.get({ cwd: work, root: undefined })
      // longer than the transport's close grace (about 2 s), so a reaped server would fail the call
      const call = server.call('slow', { ms: 4000 }, new AbortController().signal, 20_000)
      await sleep(500)
      await pool.reap(100)
      assert.equal(pool.size, 1)
      assert.equal(text(await call), 'slept')
      await sleep(200)
      await pool.reap(100)
      assert.equal(pool.size, 0)
    } finally {
      await pool.closeAll()
    }
  })
})
