// The browser half loads as dsh-client-modules loads it (a closure factory) and registers the panel, the tool
// rows and the settings page; its components render their trees with a stand-in React.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../lib/client.js', import.meta.url), 'utf8')

const React = {
  Fragment: 'Fragment',
  createElement: (type, props, ...children) => ({ type, props: { ...props, children: children.flat() } }),
  useState: init => [typeof init === 'function' ? init() : init, () => undefined],
  useEffect: () => undefined,
  useRef: value => ({ current: value }),
  useCallback: fn => fn,
}
const primitives = new Proxy({}, { get: (_, name) => String(name) })

function load() {
  const entries = []
  const style = []
  const sandbox = {
    window: {
      __ModuleLoader__: { load: entry => entries.push(entry) },
      addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
    },
    document: {
      documentElement: { lang: 'en' },
      querySelector: () => null,
      createElement: () => ({ dataset: {} }),
      head: { append: node => style.push(node) },
    },
    navigator: { language: 'en' },
    fetch: async () => ({ ok: false }),
    URLSearchParams, CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail } },
    setInterval, clearInterval, setTimeout, console,
  }
  vm.runInNewContext(source, sandbox)
  return { entries, style }
}

function harness(plugin) {
  const slots = []
  const tabs = []
  const locales = []
  const ctx = {
    effect: fn => fn(),
    get: () => undefined,
    locale: { register: (ns, dict) => { locales.push([ns, dict]); return () => undefined }, bind: () => key => key },
    slots: {
      inject: (_name, fn) => fn(),
      register: (options, component) => { slots.push({ options, component }); return () => undefined },
    },
    inject: (names, fn) => fn({ ...ctx, sidebarRightTabs: { register: def => { tabs.push(def); return () => undefined } } }),
  }
  plugin.apply(ctx)
  return { slots, tabs, locales }
}

/** Call function components until only host elements and primitives remain. */
function expand(node) {
  if (Array.isArray(node)) return node.map(expand)
  if (!node || typeof node !== 'object') return node
  if (typeof node.type === 'function') return expand(node.type(node.props))
  return { ...node, props: { ...node.props, children: expand(node.props?.children) } }
}

function find(node, test, out = []) {
  if (Array.isArray(node)) { for (const child of node) find(child, test, out); return out }
  if (!node || typeof node !== 'object') return out
  if (test(node)) out.push(node)
  for (const value of Object.values(node.props ?? {})) if (value && typeof value === 'object') find(value, test, out)
  return out
}

describe('client bundle', () => {
  const { entries, style } = load()
  const plugin = entries[0].factory(id => id === 'react' ? React : primitives)
  const { slots, tabs, locales } = harness(plugin)

  it('registers through the module loader under the package name', () => {
    assert.equal(entries.length, 1)
    assert.equal(entries[0].id, 'dsh-plugin-reelsmith')
    assert.deepEqual([...plugin.inject], ['slots', 'locale'])
    assert.equal(style.length, 1)
    assert.equal(locales[0][0], 'reelsmith')
    assert.ok(locales[0][1].en['panel.title'] && locales[0][1].zh['panel.title'])
  })

  it('adds the Video editor tab type, its body, tool rows and the settings page', () => {
    assert.equal(tabs.length, 1)
    assert.equal(tabs[0].kind, 'reelsmith')
    assert.equal(tabs[0].guide[0].id, 'open')
    const body = slots.find(slot => slot.options.name === 'sidebar.right.pane.tab')
    assert.equal(body.options.key, tabs[0].id)
    assert.equal(body.options.inject('session-9').sessionId, 'session-9')
    const rows = slots.filter(slot => slot.options.name === 'tool.call.toolview').map(slot => slot.options.key)
    for (const tool of ['preview', 'render', 'review', 'edit', 'describe']) assert.ok(rows.includes(`mcp__reelsmith__${tool}`), tool)
    assert.ok(slots.some(slot => slot.options.name === 'plugins.row.config' && slot.options.key === 'dsh-plugin-reelsmith#reelsmith'))
  })

  const row = slots.find(slot => slot.options.key === 'mcp__reelsmith__preview').component
  const common = { useDisclosure: () => ({ expanded: false, toggle() {} }), loadImage: async () => 'blob:x', t: key => key }

  it('shows a preview result\'s stored images inline', () => {
    const tree = expand(row({
      ...common, phase: 'result', toolName: 'mcp__reelsmith__preview',
      block: {
        time: 1, isError: false, call: { argsRaw: '{"project":"D:/films/demo"}' },
        content: [{ type: 'text', text: 'contact sheet (x): D:/films/demo/build/stills/contact.png' },
          { type: 'image', attachment: { attachmentId: 'a1', mediaType: 'image/png' } }],
      },
    }))
    const disclosure = find(tree, node => node.type === 'DisclosureRow')[0]
    assert.equal(disclosure.props.title, 'Preview')
    assert.equal(find(tree, node => node.type === 'div' && node.props.className === 'rs-gallery').length, 1)
    assert.equal(find(tree, node => node.type === 'div' && /rs-thumb/.test(node.props.className ?? '')).length, 1, 'attachment image waits for its URL')
  })

  it('falls back to the contact sheet file and plays a delivered film', () => {
    const preview = expand(row({
      ...common, phase: 'result', toolName: 'mcp__reelsmith__preview',
      block: { time: 1, isError: false, call: { argsRaw: '{"project":"demo"}' }, content: [{ type: 'text', text: 'contact sheet (x): D:/films/demo/build/stills/contact.png' }] },
    }))
    const img = find(preview, node => node.type === 'img')[0]
    assert.match(img.props.src, /^api\/reelsmith\/file\?path=D%3A%2Ffilms%2Fdemo%2Fbuild%2Fstills%2Fcontact\.png/)
    const render = expand(row({
      ...common, phase: 'result', toolName: 'mcp__reelsmith__render',
      block: { time: 1, isError: false, call: { argsRaw: '{"project":"demo"}' }, content: [{ type: 'text', text: 'DELIVERED: D:/films/demo/out/film.mp4 (12 s, 1080x1920)' }] },
    }))
    const video = find(render, node => node.type === 'video')[0]
    assert.match(video.props.src, /film\.mp4/)
    assert.ok(video.props.controls)
  })

  it('renders a running call as a shimmering row', () => {
    const tree = expand(row({ ...common, phase: 'start', toolName: 'mcp__reelsmith__render', block: { argsRaw: '{"project":"demo"}' } }))
    assert.equal(find(tree, node => node.type === 'DisclosureRow')[0].props.running, true)
  })

  it('renders the panel and the settings page', () => {
    const panel = slots.find(slot => slot.options.name === 'sidebar.right.pane.tab').component
    const loading = expand(panel({ t: key => key, sessionId: 's', useTabInfo: () => ({ tab: { visible: true, actions: {} } }) }))
    assert.equal(find(loading, node => node.type === 'p')[0].props.children[0], 'panel.loading')
    const settings = slots.find(slot => slot.options.name === 'plugins.row.config').component
    assert.equal(settings({ view: 'summary', t: key => key }), 'settings.summary')
    const page = expand(settings({
      view: 'page', t: key => key,
      form: { state: { status: 'ready', writable: true, value: { python: '', command: 'reelsmith-mcp', fence: true }, user: {}, revision: 3 }, mutate: async () => true },
    }))
    const fields = find(page, node => node.type === 'SettingsValueField').map(node => node.props.id)
    assert.deepEqual(fields, ['reelsmith-python', 'reelsmith-command', 'reelsmith-workspaceRoot', 'reelsmith-profile', 'reelsmith-attachStills', 'reelsmith-timeoutMs'])
    assert.equal(find(page, node => node.type === 'Switch').length, 1)
  })
})
