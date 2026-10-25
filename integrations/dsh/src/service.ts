/** The `reelsmith` service: settings, the MCP servers, the tool list, and what the panel reads. */
import { existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Context } from '@deepseek-ai/cordis'
import { type Config, type Settings, serverCommand, settingsOf } from './config.ts'
import { withImages, resultText } from './images.ts'
import { ServerPool, stdioTransport, type Server, type ServerPlace, type ToolInfo, type TransportFactory } from './pool.ts'
import { inside, ProjectBook, projectDir, viewOf, type ProjectView } from './projects.ts'
import { promptText } from './prompt.ts'

/** The slice of a tool execution this service reads. */
export interface ExecutionLike {
  readonly agent?: { readonly id?: unknown }
  readonly signal: AbortSignal
}

interface WorkingDirectoryLike {
  ensure(agent: unknown, signal?: AbortSignal): Promise<string>
}

/** What the panel's state route answers. */
export interface PanelState {
  status: { connected: boolean; error: string | null; command: string; tools: string[] }
  project: (ProjectView & { describe: string | null; describeError: string | null }) | null
  projects: { path: string; name: string; at: number }[]
  rev: number
}

const PACKAGE_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const VERSION = '0.1.0'
const DESCRIBE_TIMEOUT_MS = 8000

export class ReelsmithService {
  private readonly pool: ServerPool
  private tools: ToolInfo[] = []
  private readonly toolListeners = new Set<(tools: readonly ToolInfo[]) => void>()
  private error: string | undefined
  private connected = false
  private instructionsText = ''
  private discovery: Promise<void> | undefined
  private generation = 0
  private disposed = false
  private readonly describeCache = new Map<string, { key: string; text: string }>()
  readonly projects = new ProjectBook()

  constructor(
    private readonly ctx: Context,
    private readonly config: Partial<Config>,
    transports: TransportFactory = stdioTransport,
  ) {
    this.pool = new ServerPool(() => {
      const s = this.settings()
      return { ...serverCommand(s), env: s.env }
    }, transports, VERSION)
  }

  settings(): Settings {
    return settingsOf(this.config)
  }

  /** Where calls without a session directory run: the configured root, else where dsh was started. */
  defaultCwd(): string {
    const s = this.settings()
    if (s.workspaceRoot) return resolve(s.workspaceRoot)
    const profile = this.ctx.get('profileContext') as { cwd?: string } | undefined
    return resolve(profile?.cwd ?? process.cwd())
  }

  private place(cwd: string): ServerPlace {
    const s = this.settings()
    return { cwd, root: s.fence ? resolve(s.workspaceRoot || cwd) : undefined }
  }

  /** The session's directory; outside a configured workspace root, the root (relative paths must land inside it). */
  private async cwdFor(exec: ExecutionLike | undefined): Promise<string> {
    const wd = this.ctx.get('workingDirectory') as WorkingDirectoryLike | undefined
    if (wd !== undefined && exec?.agent !== undefined) {
      try {
        const cwd = resolve(await wd.ensure(exec.agent, exec.signal))
        const root = this.settings().workspaceRoot
        return root && !inside(root, cwd) ? resolve(root) : cwd
      } catch {
        // A session without a resolvable directory falls back to the default.
      }
    }
    return this.defaultCwd()
  }

  /** Discover the tools once (again after `restart`); never rejects. */
  ready(): Promise<void> {
    this.discovery ??= this.discover()
    return this.discovery
  }

  private async discover(): Promise<void> {
    const generation = this.generation
    const server = this.pool.get(this.place(this.defaultCwd()))
    try {
      const tools = await server.tools()
      if (generation !== this.generation || this.disposed) return
      this.tools = tools
      this.connected = true
      this.error = undefined
      this.instructionsText = server.instructions()
      this.ctx.logger?.info?.(`reelsmith: ${tools.length} tools from ${serverCommand(this.settings()).command}`)
    } catch (error) {
      if (generation !== this.generation || this.disposed) return
      this.tools = []
      this.connected = false
      this.error = error instanceof Error ? error.message : String(error)
      this.ctx.logger?.warn?.(`reelsmith: ${this.error}`)
    }
    this.projects.bump()
    for (const listener of [...this.toolListeners]) {
      try { listener(this.tools) } catch (error) { this.ctx.logger?.warn?.('reelsmith: tool listener failed', error) }
    }
  }

  /** Close every server and discover again (settings changed, or the user asked). */
  async restart(): Promise<void> {
    this.generation++
    this.discovery = undefined
    this.describeCache.clear()
    await this.pool.closeAll()
    await this.ready()
  }

  /** Called with the tool list after every discovery; returns the unsubscriber (read the current list with toolList). */
  onTools(listener: (tools: readonly ToolInfo[]) => void): () => void {
    this.toolListeners.add(listener)
    return () => { this.toolListeners.delete(listener) }
  }

  toolList(): readonly ToolInfo[] {
    return this.tools
  }

  promptText(): string {
    return promptText({
      profile: this.settings().profile,
      connected: this.connected,
      error: this.error,
      instructions: this.instructionsText,
    })
  }

  /** Skill roots for dsh-skill-filesystem: the configured one, the packaged copy, or the repository's. */
  skillDirs(): string[] {
    const s = this.settings()
    if (s.skillDir) return [resolve(s.skillDir)]
    const packaged = join(PACKAGE_DIR, 'skills')
    const repository = resolve(PACKAGE_DIR, '..', '..', 'skills')
    if (existsSync(join(packaged, 'reelsmith', 'SKILL.md'))) return [packaged]
    if (existsSync(join(PACKAGE_DIR, '..', '..', 'reelsmith', 'mcp_server.py'))) return [repository]
    return []
  }

  /** The arguments the server gets: paths made absolute, the default profile filled in. */
  prepareArgs(tool: string, args: Record<string, unknown>, cwd: string): Record<string, unknown> {
    const sent: Record<string, unknown> = { ...args }
    if (typeof sent.project === 'string' && sent.project.trim()) sent.project = resolve(cwd, sent.project.trim())
    if (tool === 'import_asset' && typeof sent.source === 'string' && !/^[a-z][a-z0-9+.-]*:\/\//i.test(sent.source)
      && sent.source.trim()) {
      sent.source = resolve(cwd, sent.source.trim())
    }
    const profile = this.settings().profile
    if (tool === 'new_project' && profile && (sent.profile === undefined || sent.profile === null || sent.profile === '')) {
      sent.profile = profile
    }
    return sent
  }

  /** Run one reelsmith tool for one execution: the server for its directory, images attached. */
  async call(tool: string, args: Record<string, unknown>, exec: ExecutionLike): Promise<unknown> {
    const cwd = await this.cwdFor(exec)
    const place = this.place(cwd)
    const sent = this.prepareArgs(tool, args, cwd)
    const s = this.settings()
    const server = this.pool.get(place)
    const result = await server.call(tool, sent, exec.signal, s.timeoutMs)
    this.record(exec, tool, sent, result, place)
    return await withImages(tool, result, s.attachStills)
  }

  private record(exec: ExecutionLike, tool: string, sent: Record<string, unknown>, result: unknown, place: ServerPlace): void {
    if (typeof sent.project !== 'string') return
    const dir = projectDir(sent.project, place.cwd)
    if (!existsSync(join(dir, 'project.json'))) return
    const session = typeof exec.agent?.id === 'string' ? exec.agent.id : undefined
    const record = this.projects.touch(session, dir, place.cwd, place.root)
    if (tool === 'preview' || tool === 'review') this.projects.shots(record, tool, resultText(result))
  }

  /** The panel's state for a session (or one named project). */
  async panelState(session: string | undefined, project: string | undefined): Promise<PanelState> {
    const recent = this.projects.recent(session)
    const record = project ? this.projects.find(project) : recent[0]
    let view: PanelState['project'] = null
    if (record !== undefined) {
      const base = await viewOf(record)
      const described = await this.describe(record.path, record.cwd, base.projectJson?.mtime ?? 0)
      view = { ...base, describe: described.text, describeError: described.error }
    }
    return {
      status: {
        connected: this.connected,
        error: this.error ?? null,
        command: [serverCommand(this.settings()).command, ...serverCommand(this.settings()).args].join(' '),
        tools: this.tools.map(tool => tool.name),
      },
      project: view,
      projects: recent.map(item => ({ path: item.path, name: item.path.split(/[\\/]/).pop() ?? item.path, at: item.at })),
      rev: this.projects.rev,
    }
  }

  /** describe(project), cached until project.json changes; bounded so a long render cannot stall the panel. */
  private async describe(path: string, cwd: string, mtime: number): Promise<{ text: string | null; error: string | null }> {
    const key = `${mtime}`
    const cached = this.describeCache.get(path)
    if (cached?.key === key) return { text: cached.text, error: null }
    if (!this.tools.some(tool => tool.name === 'describe')) return { text: cached?.text ?? null, error: 'describe is not available' }
    const server: Server = this.pool.get(this.place(cwd))
    const signal = AbortSignal.timeout(DESCRIBE_TIMEOUT_MS)
    try {
      const result = await server.call('describe', { project: path }, signal, DESCRIBE_TIMEOUT_MS)
      const text = resultText(result)
      if ((result as { isError?: boolean }).isError) return { text: cached?.text ?? null, error: text }
      this.describeCache.set(path, { key, text })
      return { text, error: null }
    } catch (error) {
      return { text: cached?.text ?? null, error: error instanceof Error ? error.message : String(error) }
    }
  }

  /** Whether the panel may read this file. */
  readable(path: string): boolean {
    return this.projects.readable(path)
  }

  /** Close servers nobody used for a while. */
  async reap(): Promise<void> {
    const keep = this.pool.get(this.place(this.defaultCwd()))
    await this.pool.reap(this.settings().idleMinutes * 60_000, keep)
  }

  async dispose(): Promise<void> {
    this.disposed = true
    this.toolListeners.clear()
    await this.pool.closeAll()
  }
}
