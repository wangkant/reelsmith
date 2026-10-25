// A stand-in for reelsmith's MCP server over stdio: the same tool shapes and result text, no Python.
import { mkdirSync, writeFileSync } from 'node:fs'
import { basename, dirname, join, resolve } from 'node:path'
import { createInterface } from 'node:readline'

// 1x1 PNG
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64')

const project = { project: { type: 'string', title: 'Project' } }
const TOOLS = [
  {
    name: 'new_project',
    description: 'Create a project folder holding project.json.',
    inputSchema: { type: 'object', properties: { ...project, profile: { type: 'string', default: '' }, title: { type: 'string', default: '' } }, required: ['project'] },
  },
  {
    name: 'preview',
    description: 'Render stills at the given moments; returns PNG paths and a contact sheet.',
    inputSchema: {
      type: 'object',
      properties: {
        ...project,
        times: { type: 'array', default: [], items: { anyOf: [{ type: 'number' }, { type: 'string' }] } },
        sweep: { type: 'boolean', default: false },
      },
      required: ['project'],
    },
  },
  { name: 'describe', description: 'The editor window as text.', inputSchema: { type: 'object', properties: project, required: ['project'] } },
  { name: 'render', description: 'Render out/film.mp4.', inputSchema: { type: 'object', properties: project, required: ['project'] } },
  { name: 'check', description: 'Validation and rules.', inputSchema: { type: 'object', properties: project, required: ['project'] } },
]

const text = (value, isError = false) => ({ content: [{ type: 'text', text: value }], isError })

function dirOf(value) {
  const full = resolve(String(value))
  return basename(full) === 'project.json' ? dirname(full) : full
}

function call({ name, arguments: args = {} }) {
  const dir = args.project ? dirOf(args.project) : process.cwd()
  switch (name) {
    case 'new_project':
      mkdirSync(dir, { recursive: true })
      writeFileSync(join(dir, 'project.json'), JSON.stringify({ profile: args.profile || 'default', tracks: [] }))
      return text(`created ${dir} (profile ${args.profile || 'default'}); root=${process.env.REELSMITH_ROOT ?? 'unset'}; cwd=${process.cwd()}`)
    case 'preview': {
      const stills = join(dir, 'build', 'stills')
      mkdirSync(stills, { recursive: true })
      const times = Array.isArray(args.times) && args.times.length ? args.times : [0]
      const rows = [`${times.length} still(s) of a 2 s film at 30 fps (look with Read):`]
      times.forEach((t, i) => {
        const png = join(stills, `still_${String(i + 1).padStart(4, '0')}.png`)
        writeFileSync(png, PNG)
        rows.push(`- ${Number(t).toFixed(2)}s (frame ${i * 30}): ${png}`)
      })
      writeFileSync(join(stills, 'contact.png'), PNG)
      rows.push(`contact sheet (dark bands = the platform's UI, yellow line = the safe area; words there are hidden on a phone): ${join(stills, 'contact.png')}`)
      rows.push('layout: ok (no words outside the safe area, cut, overflowing, tiny, overlapping or low-contrast)')
      return text(rows.join('\n'))
    }
    case 'describe':
      return text(`canvas 1080x1920, 2.0 s\ntracks (bottom to top):\n  v1: c1 shape 0-2s\nproject ${basename(dir)}`)
    case 'render': {
      mkdirSync(join(dir, 'out'), { recursive: true })
      const film = join(dir, 'out', 'film.mp4')
      writeFileSync(film, Buffer.alloc(64))
      return text(`DELIVERED: ${film} (2.0 s, 1080x1920 30 fps, h264/aac, -14 LUFS, 0.1 MB; rendered in 1 s). Look at it with review.`)
    }
    case 'check':
      return text('[error] meta.title is missing', true)
    case 'env':     // unlisted: what the pool's tests read of the server's environment
      return text(`PYTHONSAFEPATH=${process.env.PYTHONSAFEPATH ?? 'unset'}`)
    default:
      return text(`no tool ${name}`, true)
  }
}

const send = message => process.stdout.write(`${JSON.stringify(message)}\n`)

createInterface({ input: process.stdin }).on('line', (line) => {
  if (!line.trim()) return
  const message = JSON.parse(line)
  if (message.id === undefined) return
  const reply = result => send({ jsonrpc: '2.0', id: message.id, result })
  switch (message.method) {
    case 'initialize':
      reply({
        protocolVersion: message.params?.protocolVersion ?? '2025-06-18',
        capabilities: { tools: {} },
        serverInfo: { name: 'reelsmith', version: 'fake' },
        instructions: 'fake reelsmith: start with manual.',
      })
      break
    case 'ping':
      reply({})
      break
    case 'tools/list':
      reply({ tools: TOOLS })
      break
    case 'tools/call':
      // unlisted `slow` stands in for a long render
      if (message.params?.name === 'slow') setTimeout(() => reply(text('slept')), Number(message.params.arguments?.ms ?? 1000))
      else reply(call(message.params ?? {}))
      break
    default:
      send({ jsonrpc: '2.0', id: message.id, error: { code: -32601, message: `unknown method ${message.method}` } })
  }
})
