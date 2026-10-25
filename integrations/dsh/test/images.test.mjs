// Image paths in reelsmith's result text, and the image blocks attached to the MCP result.
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after, describe, it } from 'node:test'
import { imagesToAttach, namedImages, withImages } from '../lib/images.js'

const dir = mkdtempSync(join(tmpdir(), 'rs-img-'))
after(() => rmSync(dir, { recursive: true, force: true }))
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64')

const stillA = join(dir, 'still 0001.png')
const stillB = join(dir, 'still_0002.png')
const sheet = join(dir, 'contact.png')
for (const path of [stillA, stillB, sheet]) writeFileSync(path, PNG)

const preview = [
  '2 still(s) of a 12.5 s film at 30 fps (look with Read):',
  `- 0.50s (frame 15): ${stillA}`,
  `- 3.00s (frame 90): ${stillB}`,
  `contact sheet (dark bands = the platform's UI, yellow line = the safe area; words there are hidden on a phone): ${sheet}`,
  'layout: ok (no words outside the safe area, cut, overflowing, tiny, overlapping or low-contrast)',
].join('\n')

describe('namedImages', () => {
  it('finds the contact sheet and the stills, paths with spaces included', () => {
    assert.deepEqual(namedImages(preview), { sheets: [sheet], stills: [stillA, stillB] })
  })

  it('ignores relative paths and non-image files', () => {
    assert.deepEqual(namedImages('- 1.00s: stills/a.png\nDELIVERED: /tmp/out/film.mp4 (2 s)'), { sheets: [], stills: [] })
  })
})

describe('imagesToAttach', () => {
  it('always sends the sheet, and the stills when there are few', () => {
    assert.deepEqual(imagesToAttach('preview', preview, 4), [sheet, stillA, stillB])
    assert.deepEqual(imagesToAttach('preview', preview, 1), [sheet])
  })

  it('sends only contact sheets for tools that do not return stills', () => {
    assert.deepEqual(imagesToAttach('assets', preview, 4), [sheet])
  })
})

describe('withImages', () => {
  it('appends base64 image blocks after the text', async () => {
    const result = await withImages('preview', { content: [{ type: 'text', text: preview }] }, 4)
    assert.equal(result.content.length, 4)
    assert.deepEqual(result.content.slice(1).map(block => block.mimeType), ['image/png', 'image/png', 'image/png'])
    assert.equal(result.content[1].data, PNG.toString('base64'))
  })

  it('leaves errors, results that already carry images, and missing files alone', async () => {
    const failed = { content: [{ type: 'text', text: preview }], isError: true }
    assert.equal(await withImages('preview', failed, 4), failed)
    const own = { content: [{ type: 'text', text: preview }, { type: 'image', data: 'AA==', mimeType: 'image/png' }] }
    assert.equal(await withImages('preview', own, 4), own)
    const gone = { content: [{ type: 'text', text: `contact sheet (x): ${join(dir, 'gone.png')}` }] }
    assert.equal(await withImages('preview', gone, 4), gone)
  })
})
