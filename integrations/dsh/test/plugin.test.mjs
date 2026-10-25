// The plugin inside a Cordis context with DSH's real ToolRuntime and SystemPrompt services and a fake
// reelsmith MCP server over stdio: tools register with the server's schemas, one call round-trips, and the
// contact sheet comes back as a durable image block. No model calls.
import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, rmSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { after, before, describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'
import { Context } from '@deepseek-ai/cordis'
import SystemPrompt, { renderPrompt } from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import * as host from '../lib/index.js'
import * as toolsPlugin from '../lib/tools.js'

const FAKE = fileURLToPath(new URL('./fixtures/fake-reelsmith.mjs', import.meta.url))

describe('dsh-plugin-reelsmith in a Cordis context', () => {
  let ctx
  let work
  let saved
  const fibers = []
  const agent = {
    id: 'session-test',
    options: { provider: 'deepseek-official', model: 'deepseek-flash' },
    session: { requestHeader: () => undefined },
  }

  before(async () => {
    work = mkdtempSync(join(tmpdir(), 'rs-dsh-'))
    saved = []
    ctx = new Context()
    // Services the tools reach for: the session directory, the model's image capability, the attachment store.
    ctx.provide('workingDirectory', { ensure: async () => work })
    ctx.provide('llm', { resolveModelInfo: async () => ({ inputModalities: ['text', 'image'] }) })
    ctx.provide('attachments', {
      saveImages: async (images) => images.map((image, i) => {
        saved.push(image)
        return { attachmentId: `att-${saved.length}-${i}`, mediaType: image.mediaType, bytes: image.data.length, width: 1, height: 1 }
      }),
    })
    fibers.push(await ctx.plugin(SystemPrompt, {}))
    fibers.push(await ctx.plugin(ToolRuntime, {}))
    fibers.push(await ctx.plugin(host, { command: process.execPath, args: [FAKE], attachStills: 4 }))
    fibers.push(await ctx.plugin(toolsPlugin))
  })

  after(async () => {
    // Disposing the host plugin closes every server it started (the fake's cwd is the work folder).
    for (const fiber of fibers.reverse()) await fiber.dispose()
    rmSync(work, { recursive: true, force: true })
  })

  it('registers every server tool under mcp__reelsmith__ with its own schema', () => {
    const names = ctx.tools.schemas().map(schema => schema.name).filter(name => name.startsWith('mcp__reelsmith__')).sort()
    assert.deepEqual(names, ['mcp__reelsmith__check', 'mcp__reelsmith__describe', 'mcp__reelsmith__new_project',
      'mcp__reelsmith__preview', 'mcp__reelsmith__render'])
    const preview = ctx.tools.schemas().find(schema => schema.name === 'mcp__reelsmith__preview')
    assert.deepEqual(preview.parameters.required, ['project'])
    assert.deepEqual(preview.parameters.properties.times.items, { anyOf: [{ type: 'number' }, { type: 'string' }] })
    assert.match(preview.description, /contact sheet/)
  })

  it('adds the Video editor section, with the server instructions, to the system prompt', async () => {
    const text = renderPrompt(await ctx.systemPrompt.assemble({}))
    assert.match(text, /# Video editing with reelsmith/)
    assert.match(text, /not a text-to-video model/)
    assert.match(text, /fake reelsmith: start with manual/)
  })

  it('resolves a relative project against the session directory and fences REELSMITH_ROOT there', async () => {
    const result = await ctx.tools.execute({
      callId: 'call-1', name: 'mcp__reelsmith__new_project', arguments: { project: 'demo' }, agent, signal: new AbortController().signal,
    })
    assert.equal(result.isError, false, JSON.stringify(result))
    const text = result.content.map(block => block.text ?? '').join('\n')
    assert.match(text, new RegExp(`created ${escape(resolve(work, 'demo'))}`))
    assert.match(text, new RegExp(`root=${escape(resolve(work))};`))
    assert.ok(existsSync(join(work, 'demo', 'project.json')))
  })

  it('round-trips preview and delivers its contact sheet and stills as durable images', async () => {
    const before = saved.length
    const result = await ctx.tools.execute({
      callId: 'call-2', name: 'mcp__reelsmith__preview', arguments: { project: 'demo', times: [0.5, 'line:1'] }, agent, signal: new AbortController().signal,
    })
    assert.equal(result.isError, false, JSON.stringify(result))
    const images = result.content.filter(block => block.type === 'image')
    assert.equal(images.length, 3, 'contact sheet + 2 stills')
    assert.match(images[0].attachment.attachmentId, /^att-/)
    assert.equal(images[0].attachment.mediaType, 'image/png')
    assert.equal(saved.length - before, 3)
    assert.match(result.content[0].text, /contact sheet/)
  })

  it('passes a server error back as a failed call with its text', async () => {
    const result = await ctx.tools.execute({
      callId: 'call-3', name: 'mcp__reelsmith__check', arguments: { project: 'demo' }, agent, signal: new AbortController().signal,
    })
    assert.equal(result.isError, true)
    assert.match(JSON.stringify(result), /meta\.title is missing/)
  })

  it('serves the panel state for the session: project, preview sheet, describe text', async () => {
    await ctx.tools.execute({
      callId: 'call-4', name: 'mcp__reelsmith__render', arguments: { project: 'demo' }, agent, signal: new AbortController().signal,
    })
    const state = await ctx.reelsmith.panelState('session-test', undefined)
    assert.equal(state.status.connected, true)
    assert.equal(state.project.path, resolve(work, 'demo'))
    assert.ok(state.project.preview.sheet.path.endsWith('contact.png'))
    assert.equal(state.project.preview.stills.length, 2)
    assert.ok(state.project.film.path.endsWith('film.mp4'))
    assert.match(state.project.describe, /canvas 1080x1920/)
    assert.ok(ctx.reelsmith.readable(state.project.film.path))
    assert.equal(ctx.reelsmith.readable(join(tmpdir(), 'elsewhere.png')), false)
  })

  it('resolves relative paths against a configured workspace root when the session is outside it', async () => {
    const root = join(work, 'studio')
    mkdirSync(root)
    const other = new Context()
    other.provide('workingDirectory', { ensure: async () => tmpdir() })
    const owned = [
      await other.plugin(SystemPrompt, {}),
      await other.plugin(ToolRuntime, {}),
      await other.plugin(host, { command: process.execPath, args: [FAKE], workspaceRoot: root, profile: 'youtube' }),
      await other.plugin(toolsPlugin),
    ]
    const result = await other.tools.execute({
      callId: 'call-5', name: 'mcp__reelsmith__new_project', arguments: { project: 'film' }, agent, signal: new AbortController().signal,
    })
    const text = result.content.map(block => block.text ?? '').join('\n')
    assert.match(text, new RegExp(`created ${escape(join(root, 'film'))} \\(profile youtube\\); root=${escape(root)};`))
    for (const fiber of owned.reverse()) await fiber.dispose()
  })

  it('registers the tools when discovery finished before the tools plugin loaded (a preset made later)', async () => {
    const other = new Context()
    other.provide('workingDirectory', { ensure: async () => work })
    const owned = [
      await other.plugin(SystemPrompt, {}),
      await other.plugin(ToolRuntime, {}),
      await other.plugin(host, { command: process.execPath, args: [FAKE] }),
    ]
    await other.reelsmith.ready()
    owned.push(await other.plugin(toolsPlugin))
    assert.equal(other.tools.schemas().filter(schema => schema.name.startsWith('mcp__reelsmith__')).length, 5)
    for (const fiber of owned.reverse()) await fiber.dispose()
  })

  it('reports a server that cannot start in the prompt and the panel, without failing the plugin', async () => {
    const other = new Context()
    other.provide('workingDirectory', { ensure: async () => work })
    const owned = [
      await other.plugin(SystemPrompt, {}),
      await other.plugin(ToolRuntime, {}),
      await other.plugin(host, { command: join(work, 'no-such-reelsmith-mcp') }),
      await other.plugin(toolsPlugin),
    ]
    const state = await other.reelsmith.panelState(undefined, undefined)
    assert.equal(state.status.connected, false)
    assert.match(state.status.error, /could not start the reelsmith MCP server/)
    assert.equal(other.tools.schemas().filter(schema => schema.name.startsWith('mcp__reelsmith__')).length, 0)
    assert.match(renderPrompt(await other.systemPrompt.assemble({})), /reelsmith is not connected right now/)
    for (const fiber of owned.reverse()) await fiber.dispose()
  })
})

function escape(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

