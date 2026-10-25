// Image paths in reelsmith's result text, and the image blocks attached to the MCP result.
import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after, describe, it } from 'node:test'
import { imagesToAttach, namedImages, withImages } from '../lib/images.js'

const dir = mkdtempSync(join(tmpdir(), 'rs-img-'))
after(() => rmSync(dir, { recursive: true, force: true }))
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64')

const project = join(dir, 'demo')
const stills = join(project, 'build', 'stills')
const shots = join(project, 'build', 'footage', 'a', 'scenes')
mkdirSync(stills, { recursive: true })
mkdirSync(shots, { recursive: true })
const stillA = join(stills, 'still 0001.png')
const stillB = join(stills, 'still_0002.png')
const sheet = join(stills, 'contact.png')
const scenesSheet = join(shots, 'contact.png')
const outside = join(dir, 'private.png')
for (const path of [stillA, stillB, sheet, scenesSheet, outside]) writeFileSync(path, PNG)

const preview = [
  '2 still(s) of a 12.5 s film at 30 fps (look with Read):',
  `- 0.50s (frame 15): ${stillA}`,
  `- 3.00s (frame 90): ${stillB}`,
  `contact sheet (dark bands = the platform's UI, yellow line = the safe area; words there are hidden on a phone): ${sheet}`,
  'layout: ok (no words outside the safe area, cut, overflowing, tiny, overlapping or low-contrast)',
].join('\n')

// what `reelsmith scenes` prints (reelsmith/providers/footage.py), with this test's path
const scenes = [
  '2 shot(s) in assets/a.mp4 (3.04 s; a cut where the scene score passes 0.3), source seconds:',
  '  #1 0.00-1.52 (1.52 s)',
  '  #2 1.52-3.04 (1.52 s)',
  `first frames, look with Read: ${scenesSheet}`,
  'JSON: {"path": "assets/a.mp4", "duration_s": 3.04, "threshold": 0.3, "shots": [{"i": 1, "start": 0.0, "end": 1.52, "dur": 1.52}, {"i": 2, "start": 1.52, "end": 3.04, "dur": 1.52}]}',
].join('\n')

describe('namedImages', () => {
  it('finds the contact sheet and the stills, paths with spaces included', () => {
    assert.deepEqual(namedImages(preview), { sheets: [sheet], stills: [stillA, stillB] })
  })

  it('takes the scenes sheet ("first frames") as a contact sheet', () => {
    assert.deepEqual(namedImages(scenes), { sheets: [scenesSheet], stills: [] })
  })

  it('ignores relative paths and non-image files', () => {
    assert.deepEqual(namedImages('- 1.00s: stills/a.png\nDELIVERED: /tmp/out/film.mp4 (2 s)'), { sheets: [], stills: [] })
  })
})

describe('imagesToAttach', () => {
  it('always sends the sheet, and the stills when there are few', () => {
    assert.deepEqual(imagesToAttach('preview', preview, 4), [sheet, stillA, stillB])
    assert.deepEqual(imagesToAttach('preview', preview, 1), [sheet])
    assert.deepEqual(imagesToAttach('scenes', scenes, 4), [scenesSheet])
  })

  it('sends nothing for tools that write no images, whatever their text names', () => {
    assert.deepEqual(imagesToAttach('assets', preview, 4), [])
    assert.deepEqual(imagesToAttach('notes', `contact sheet: ${outside}`, 4), [])
  })
})

describe('withImages', () => {
  it('appends base64 image blocks after the text', async () => {
    const result = await withImages('preview', { content: [{ type: 'text', text: preview }] }, 4, project)
    assert.equal(result.content.length, 4)
    assert.deepEqual(result.content.slice(1).map(block => block.mimeType), ['image/png', 'image/png', 'image/png'])
    assert.equal(result.content[1].data, PNG.toString('base64'))
    const shot = await withImages('scenes', { content: [{ type: 'text', text: scenes }] }, 4, project)
    assert.equal(shot.content.length, 2)
  })

  it('attaches only files inside the called project\'s build folder', async () => {
    const named = { content: [{ type: 'text', text: `contact sheet (x): ${outside}\n- 1.00s: ${stillA}` }] }
    const result = await withImages('preview', named, 4, project)
    assert.equal(result.content.length, 2)                   // the still in build/, not the file beside the project
    assert.equal(await withImages('preview', named, 4, dir), named)          // no build/ there
    const plain = { content: [{ type: 'text', text: preview }] }
    assert.equal(await withImages('preview', plain, 4), plain)                // no project named
  })

  it('does not follow a link in build/ to a file outside it', async (t) => {
    const link = join(stills, 'link.png')
    try {
      symlinkSync(outside, link)
    } catch {
      t.skip('symlinks need a privilege here')
      return
    }
    const named = { content: [{ type: 'text', text: `contact sheet (x): ${link}` }] }
    assert.equal(await withImages('preview', named, 4, project), named)
  })

  it('leaves errors, results that already carry images, and missing files alone', async () => {
    const failed = { content: [{ type: 'text', text: preview }], isError: true }
    assert.equal(await withImages('preview', failed, 4, project), failed)
    const own = { content: [{ type: 'text', text: preview }, { type: 'image', data: 'AA==', mimeType: 'image/png' }] }
    assert.equal(await withImages('preview', own, 4, project), own)
    const gone = { content: [{ type: 'text', text: `contact sheet (x): ${join(stills, 'gone.png')}` }] }
    assert.equal(await withImages('preview', gone, 4, project), gone)
  })
})
