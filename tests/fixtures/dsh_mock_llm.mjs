// DeepSeek Harness's scripted mock model (no key, no network) for tests that boot a real dsh.
//   node dsh_mock_llm.mjs <dsh-llm-mock-server package dir> '<options JSON>'
// Prints {"baseURL": ...} once listening; on stdin EOF prints {"requests": [...]} and exits.
import { pathToFileURL } from 'node:url'
import { join } from 'node:path'

const [dir, raw] = process.argv.slice(2)
const { startMockLlmServer } = await import(pathToFileURL(join(dir, 'lib', 'index.js')).href)
const mock = await startMockLlmServer({ apiKey: 'mock-key', sequence: ['success'], ...JSON.parse(raw || '{}') })
process.stdout.write(JSON.stringify({ baseURL: mock.baseURL }) + '\n')
process.stdin.resume()
process.stdin.on('end', async () => {
  const requests = mock.requests.map(r => ({
    path: r.path, behavior: r.behavior, tools: (r.body?.tools ?? []).map(t => t.name), messages: JSON.stringify(r.body?.messages ?? []),
  }))
  process.stdout.write(JSON.stringify({ requests }) + '\n')
  await mock.close()
  process.exit(0)
})
