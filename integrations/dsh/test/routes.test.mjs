// The panel's file route: only files of touched projects, media types only, byte ranges for the film.
import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after, describe, it } from 'node:test'
import { ProjectBook } from '../lib/projects.js'
import { serveFile } from '../lib/routes.js'

const root = mkdtempSync(join(tmpdir(), 'rs-route-'))
after(() => rmSync(root, { recursive: true, force: true }))
const project = join(root, 'demo')
mkdirSync(join(project, 'out'), { recursive: true })
const film = join(project, 'out', 'film.mp4')
writeFileSync(film, Buffer.from('0123456789'))
writeFileSync(join(project, 'project.json'), '{}')
writeFileSync(join(root, 'secret.mp4'), 'x')
writeFileSync(join(project, 'notes.txt'), 'x')

const book = new ProjectBook()
book.touch('s1', project, root, root)
const get = (path, headers = {}) => serveFile(new Request(`http://h/api/reelsmith/file?path=${encodeURIComponent(path)}`, { headers }), book)

describe('serveFile', () => {
  it('serves a project file whole, with its type', async () => {
    const response = await get(film)
    assert.equal(response.status, 200)
    assert.equal(response.headers.get('content-type'), 'video/mp4')
    assert.equal(await response.text(), '0123456789')
  })

  it('answers byte ranges', async () => {
    const response = await get(film, { range: 'bytes=2-5' })
    assert.equal(response.status, 206)
    assert.equal(response.headers.get('content-range'), 'bytes 2-5/10')
    assert.equal(await response.text(), '2345')
    const tail = await get(film, { range: 'bytes=-3' })
    assert.equal(await tail.text(), '789')
    assert.equal((await get(film, { range: 'bytes=20-' })).status, 416)
  })

  it('refuses files outside touched projects, other types, and relative paths', async () => {
    assert.equal((await get(join(root, 'secret.mp4'))).status, 403)
    assert.equal((await get(join(project, 'notes.txt'))).status, 415)
    assert.equal((await get('demo/out/film.mp4')).status, 400)
    assert.equal((await get(join(project, 'out', 'missing.mp4'))).status, 404)
  })
})
