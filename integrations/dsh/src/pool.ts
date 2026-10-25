/**
 * reelsmith MCP servers over stdio, one per (working directory, REELSMITH_ROOT): relative paths in any tool
 * argument then mean what they mean to the session's own file tools.
 */
import { existsSync } from 'node:fs'
import { Client, type Transport } from '@modelcontextprotocol/client'
import { StdioClientTransport } from '@modelcontextprotocol/client/stdio'
import { scrubbedParentEnv } from '@deepseek-ai/dsh-subprocess'

/** One tool as the server lists it. */
export interface ToolInfo {
  name: string
  description: string
  inputSchema: Record<string, unknown>
  outputSchema?: unknown
}

/** How to start a server. */
export interface ServerSpec {
  command: string
  args: string[]
  env: Record<string, string>
}

/** Where a server runs. */
export interface ServerPlace {
  cwd: string
  /** REELSMITH_ROOT, or undefined for no fence. */
  root: string | undefined
}

/** Builds the transport; tests swap in an in-memory pair. */
export type TransportFactory = (spec: ServerSpec, place: ServerPlace, stderr: (chunk: string) => void) => Transport

const STDERR_TAIL = 4000

/** The real transport: the server as a child process with the subprocess seam's scrubbed environment. */
export const stdioTransport: TransportFactory = (spec, place, stderr) => {
  const env: Record<string, string> = {
    ...scrubbedParentEnv(),
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
    ...spec.env,
  }
  if (place.root !== undefined) env.REELSMITH_ROOT = place.root
  else delete env.REELSMITH_ROOT
  const transport = new StdioClientTransport({ command: spec.command, args: spec.args, env, cwd: place.cwd, stderr: 'pipe' })
  transport.stderr?.on('data', (chunk: Buffer | string) => { stderr(String(chunk)) })
  return transport
}

/** One server process and its client; reconnects on the next use after it exits. */
export class Server {
  private client: Client | undefined
  private connecting: Promise<Client> | undefined
  private stderrTail = ''
  private closed = false
  lastUsed = Date.now()

  constructor(
    readonly place: ServerPlace,
    private readonly spec: ServerSpec,
    private readonly transports: TransportFactory,
    private readonly version: string,
  ) {}

  /** The server's own instructions, once connected. */
  instructions(): string {
    return this.client?.getInstructions() ?? ''
  }

  async tools(): Promise<ToolInfo[]> {
    const client = await this.connect()
    const { tools } = await client.listTools()
    return tools.map(tool => ({
      name: tool.name,
      description: tool.description ?? '',
      inputSchema: tool.inputSchema as Record<string, unknown>,
      ...tool.outputSchema === undefined ? {} : { outputSchema: tool.outputSchema },
    }))
  }

  async call(name: string, args: Record<string, unknown>, signal: AbortSignal, timeout: number): Promise<unknown> {
    this.lastUsed = Date.now()
    const client = await this.connect()
    try {
      return await client.callTool({ name, arguments: args }, { signal, timeout, resetTimeoutOnProgress: true })
    } finally {
      this.lastUsed = Date.now()
    }
  }

  async close(): Promise<void> {
    this.closed = true
    const client = this.client ?? await this.connecting?.catch(() => undefined)
    this.client = undefined
    this.connecting = undefined
    await client?.close().catch(() => undefined)
  }

  private connect(): Promise<Client> {
    if (this.closed) return Promise.reject(new Error('the reelsmith server was shut down'))
    if (this.client !== undefined) return Promise.resolve(this.client)
    this.connecting ??= this.open().then(
      (client) => { this.client = client; this.connecting = undefined; return client },
      (error: unknown) => { this.connecting = undefined; throw error },
    )
    return this.connecting
  }

  private async open(): Promise<Client> {
    this.stderrTail = ''
    if (!existsSync(this.place.cwd)) {
      throw new Error(`could not start the reelsmith MCP server: the folder ${this.place.cwd} does not exist (check the workspace root setting)`)
    }
    const transport = this.transports(this.spec, this.place, (chunk) => {
      this.stderrTail = (this.stderrTail + chunk).slice(-STDERR_TAIL)
    })
    const client = new Client({ name: 'dsh-plugin-reelsmith', version: this.version })
    client.onclose = () => { if (this.client === client) this.client = undefined }
    try {
      await client.connect(transport)
    } catch (error) {
      await client.close().catch(() => undefined)
      throw new Error(this.describeFailure(error))
    }
    return client
  }

  private describeFailure(error: unknown): string {
    const reason = error instanceof Error ? error.message : String(error)
    const tail = this.stderrTail.trim().split(/\r?\n/).slice(-6).join('\n')
    const command = [this.spec.command, ...this.spec.args].join(' ')
    return `could not start the reelsmith MCP server (${command} in ${this.place.cwd}): ${reason}`
      + (tail ? `\nserver output:\n${tail}` : '')
  }
}

/** Servers by place; the spec is read on every lookup, so a settings change starts fresh servers. */
export class ServerPool {
  private readonly servers = new Map<string, Server>()

  constructor(
    private readonly spec: () => ServerSpec,
    private readonly transports: TransportFactory = stdioTransport,
    private readonly version = '0',
  ) {}

  get(place: ServerPlace): Server {
    const spec = this.spec()
    const key = JSON.stringify([place.cwd, place.root ?? null, spec.command, spec.args, spec.env])
    let server = this.servers.get(key)
    if (server === undefined) {
      server = new Server(place, spec, this.transports, this.version)
      this.servers.set(key, server)
    }
    return server
  }

  /** Close servers idle for longer than `ms`, except `keep`. */
  async reap(ms: number, keep?: Server): Promise<void> {
    const now = Date.now()
    const idle = [...this.servers].filter(([, server]) => server !== keep && now - server.lastUsed > ms)
    for (const [key] of idle) this.servers.delete(key)
    await Promise.all(idle.map(([, server]) => server.close()))
  }

  async closeAll(): Promise<void> {
    const all = [...this.servers.values()]
    this.servers.clear()
    await Promise.all(all.map(server => server.close()))
  }

  get size(): number {
    return this.servers.size
  }
}
