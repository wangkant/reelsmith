#!/usr/bin/env node
// End to end without a model: install this folder into a throwaway dsh home's `headless` profile, make a
// reelsmith project, and let DSH's scripted mock LLM (no key, no network) ask for mcp__reelsmith__preview.
// Passes when the real reelsmith server rendered stills and the next model request carried the contact sheet
// as an image.
//
//   node scripts/e2e.mjs --python <python with reelsmith> [--keep]
import { spawn, spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { delimiter, dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(join(PKG, 'package.json'))
const PNPM = 'pnpm@11.28.5'
const args = process.argv.slice(2)
const option = name => { const at = args.indexOf(name); return at >= 0 ? args[at + 1] : undefined }
const python = option('--python') ?? process.env.REELSMITH_PYTHON ?? 'python'
const keep = args.includes('--keep')

const DSH_BIN = join(dirname(require.resolve('@deepseek-ai/dsh/package.json')), 'lib', 'bin.js')
const { startMockLlmServer } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-llm-mock-server')).href)

const scratch = mkdtempSync(join(tmpdir(), 'dsh-reelsmith-e2e-'))
const home = join(scratch, 'home')
const work = join(scratch, 'work')
mkdirSync(home)
mkdirSync(work)

const env = { ...process.env, DSH_HOME: home, DSH_TELEMETRY_DISABLED: '1', PYTHONUTF8: '1' }
delete env.DEEPSEEK_API_KEY
// `dsh plugin` forwards to pnpm on PATH; without one, a shim runs the version DSH pins.
if (spawnSync('pnpm --version', { shell: true, env }).status !== 0) {
  const bin = join(scratch, 'bin')
  mkdirSync(bin)
  writeFileSync(join(bin, 'pnpm.cmd'), `@echo off\r\nnpx -y ${PNPM} %*\r\n`)
  writeFileSync(join(bin, 'pnpm'), `#!/bin/sh\nexec npx -y ${PNPM} "$@"\n`, { mode: 0o755 })
  env.PATH = `${bin}${delimiter}${env.PATH ?? env.Path ?? ''}`
  env.Path = env.PATH
}

function run(command, argv, options = {}) {
  const result = spawnSync(command, argv, { encoding: 'utf8', env, ...options })
  if (result.status !== 0) throw new Error(`${command} ${argv.join(' ')} failed (${result.status}):\n${result.stdout}\n${result.stderr}`)
  return result.stdout
}

function step(text) {
  console.log(`\n== ${text}`)
}

let mock
try {
  step('install the plugin into the headless profile (dsh plugin add)')
  console.log(run(process.execPath, [DSH_BIN, 'plugin', '--profile', 'headless', 'add', PKG]).trim().split('\n').filter(line => /dsh-plugin-reelsmith|Done/.test(line)).join('\n'))
  // A stand-in Agent Skill proves the skill row; the title model would take a scripted reply, so it is off.
  const skills = join(scratch, 'skills')
  mkdirSync(join(skills, 'reelsmith'), { recursive: true })
  writeFileSync(join(skills, 'reelsmith', 'SKILL.md'),
    '---\nname: reelsmith\ndescription: E2E stand-in skill for editing films with reelsmith.\n---\n\nRead the manual first.\n')
  writeFileSync(join(home, 'profiles', 'headless', 'cordis.patch.yml'), [
    '- id: reelsmith', '  config:', `    python: ${JSON.stringify(python)}`, `    skillDir: ${JSON.stringify(skills)}`,
    '- id: session-title-llm', '  disabled: true', '',
  ].join('\n'))

  step('make a reelsmith project with one text clip')
  run(python, ['-m', 'reelsmith.cli', 'new', 'demo'], { cwd: work })
  run(python, ['-m', 'reelsmith.cli', 'edit', 'demo', JSON.stringify([
    { op: 'add_track', track: { id: 'v1', kind: 'visual', clips: [] } },
    { op: 'add_clip', track: 'v1', clip: { id: 't1', type: 'text', start: 0, dur: 3, text: 'Hello from DeepSeek Harness', box: { x: 90, y: 800, w: 900, h: 200 } } },
  ])], { cwd: work })

  step('script the mock model: one preview call (relative project path), then a final answer')
  mock = await startMockLlmServer({
    apiKey: 'mock-key',
    sequence: ['tool_call_success', 'success'],
    toolName: 'mcp__reelsmith__preview',
    toolArguments: JSON.stringify({ project: 'demo', times: [1] }),
    successText: 'The preview looks right.',
  })
  console.log(`mock model at ${mock.baseURL}`)

  step('dsh --profile headless (cwd = the work folder)')
  const child = spawn(process.execPath, [DSH_BIN, '--profile', 'headless', 'Preview the demo project and look at it.'], {
    cwd: work,
    env: { ...env, DEEPSEEK_BASE_URL: mock.baseURL, DEEPSEEK_API_KEY: 'mock-key' },
  })
  let stdout = ''
  let stderr = ''
  child.stdout.on('data', chunk => { stdout += chunk })
  child.stderr.on('data', chunk => { stderr += chunk })
  const code = await new Promise((done) => {
    const timer = setTimeout(() => { child.kill(); done('timeout') }, 5 * 60_000)
    child.on('exit', (status) => { clearTimeout(timer); done(status) })
  })
  console.log(`exit ${code}; stdout: ${stdout.trim()}`)
  for (const line of stderr.split(/\r?\n/).filter(line => /reelsmith/i.test(line))) console.log(`stderr: ${line}`)
  if (code !== 0) throw new Error(`dsh exited ${code}\n${stderr.slice(-4000)}`)

  step('what the model received')
  const messages = mock.requests.filter(request => request.path.endsWith('/messages'))
  if (messages.length < 2) throw new Error(`expected 2 model requests, got ${messages.length}`)
  const first = messages[0].body
  const tool = first.tools?.find(item => item.name === 'mcp__reelsmith__preview')
  if (!tool) throw new Error('mcp__reelsmith__preview was not offered to the model')
  console.log(`request 1: ${first.tools.filter(item => item.name.startsWith('mcp__reelsmith__')).length} reelsmith tools offered; preview schema keys: ${Object.keys(tool.input_schema?.properties ?? {}).join(', ')}`)
  const system = JSON.stringify(first.system ?? '')
  if (!system.includes('Video editing with reelsmith')) throw new Error('the Video editor section is missing from the system prompt')
  console.log('request 1: system prompt carries "# Video editing with reelsmith"')
  if (!JSON.stringify(first).includes('E2E stand-in skill for editing films')) throw new Error('the reelsmith skill is not in the catalog')
  console.log('request 1: the reelsmith skill is in the skill catalog')
  const results = messages[1].body.messages.flatMap(message => Array.isArray(message.content) ? message.content : [])
    .filter(block => block.type === 'tool_result')
  const parts = results.flatMap(block => Array.isArray(block.content) ? block.content : [])
  const text = parts.filter(part => part.type === 'text').map(part => part.text).join('\n')
  const images = parts.filter(part => part.type === 'image')
  console.log(`request 2: tool_result text starts "${text.split('\n').find(line => /still/.test(line)) ?? text.slice(0, 80)}"`)
  if (!/contact sheet/.test(text)) throw new Error(`the preview result is not in the next request:\n${text.slice(0, 2000)}`)
  if (images.length === 0) throw new Error('no image reached the model')
  for (const image of images) {
    const source = image.source ?? {}
    const size = typeof source.data === 'string' ? Buffer.from(source.data, 'base64').length : 0
    console.log(`request 2: image block ${source.type ?? '?'} ${source.media_type ?? source.file_id ?? ''} ${size ? `${size} bytes` : ''}`.trim())
  }
  console.log('\nPASS: the real reelsmith server ran preview inside dsh and the model got the contact sheet as an image.')
} catch (error) {
  console.error(`\nFAIL: ${error instanceof Error ? error.message : String(error)}`)
  for (const request of mock?.requests ?? []) {
    const body = request.body ?? {}
    console.error(`  request ${request.attempt} ${request.path} ${request.behavior}: ${(body.tools ?? []).length} tools, system ${JSON.stringify(body.system ?? '').slice(0, 160)}`)
  }
  process.exitCode = 1
} finally {
  await mock?.close()
  if (keep) console.log(`kept ${scratch}`)
  else rmSync(scratch, { recursive: true, force: true, maxRetries: 5, retryDelay: 500 })
}
