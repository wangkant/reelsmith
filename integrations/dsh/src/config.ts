/** The plugin's settings: what the Plugins page edits (volatile fields) and what only YAML sets. */
import Schema from '@deepseek-ai/schemastery'

/** A config field as the Loader hands it over: plain, or a live reference for `.volatile()` fields. */
export type Field<T> = T | { get(): T }

/** Read a field whether or not the Loader wrapped it in a volatile reference. */
export function read<T>(field: Field<T> | undefined, fallback: T): T {
  if (field === undefined || field === null) return fallback
  if (typeof field === 'object' && typeof (field as { get?: unknown }).get === 'function') {
    const value = (field as { get(): T }).get()
    return value === undefined || value === null ? fallback : value
  }
  return field as T
}

export interface Config {
  python: Field<string>
  command: Field<string>
  args: Field<string[]>
  workspaceRoot: Field<string>
  fence: Field<boolean>
  profile: Field<string>
  attachStills: Field<number>
  timeoutMs: Field<number>
  env: Record<string, string>
  idleMinutes: number
  skillDir: string
}

/** The settings resolved once per use, so one call sees one consistent set. */
export interface Settings {
  python: string
  command: string
  args: string[]
  workspaceRoot: string
  fence: boolean
  profile: string
  attachStills: number
  timeoutMs: number
  env: Record<string, string>
  idleMinutes: number
  skillDir: string
}

export const DEFAULT_TIMEOUT_MS = 30 * 60_000

export const Config: Schema<Config> = Schema.object({
  python: Schema.string().default('')
    .description('Python interpreter with reelsmith installed; runs `-m reelsmith.mcp_server`. Empty uses `command`.')
    .volatile(),
  command: Schema.string().default('reelsmith-mcp')
    .description('The MCP server command used when `python` is empty (the `reelsmith-mcp` entry point on PATH).')
    .volatile(),
  args: Schema.array(String).default([])
    .description('Arguments for `command` (not used with `python`).')
    .volatile(),
  workspaceRoot: Schema.string().default('')
    .description('REELSMITH_ROOT for every call. Empty uses the session working directory.')
    .volatile(),
  fence: Schema.boolean().default(true)
    .description('Set REELSMITH_ROOT, so the tools refuse projects and local imports outside it.')
    .volatile(),
  profile: Schema.string().default('')
    .description('Output profile new_project gets when the call names none (empty: reelsmith decides).')
    .volatile(),
  attachStills: Schema.number().min(0).max(24).step(1).default(4)
    .description('Attach the stills of a preview or review as images when it returns at most this many; the contact sheet is always attached.')
    .volatile(),
  timeoutMs: Schema.number().min(1000).step(1).default(DEFAULT_TIMEOUT_MS)
    .description('Longest a reelsmith call may take (render takes minutes).')
    .volatile(),
  env: Schema.dict(String).default({})
    .description('Extra environment for the server, merged over the scrubbed ambient environment.'),
  idleMinutes: Schema.number().min(1).step(1).default(30)
    .description('Close a working directory\'s server after this many idle minutes.'),
  skillDir: Schema.string().default('')
    .description('Folder holding the reelsmith Agent Skill (`reelsmith/SKILL.md`); empty finds the packaged or repository copy.'),
}) as unknown as Schema<Config>

/** Snapshot every field now. */
export function settingsOf(config: Partial<Config>): Settings {
  const env = config.env && typeof config.env === 'object' ? config.env : {}
  return {
    python: read(config.python, '').trim(),
    command: read(config.command, 'reelsmith-mcp').trim() || 'reelsmith-mcp',
    args: [...read(config.args, [] as string[])].map(String),
    workspaceRoot: read(config.workspaceRoot, '').trim(),
    fence: read(config.fence, true),
    profile: read(config.profile, '').trim(),
    attachStills: Math.max(0, Math.floor(read(config.attachStills, 4))),
    timeoutMs: Math.max(1000, Math.floor(read(config.timeoutMs, DEFAULT_TIMEOUT_MS))),
    env: { ...env },
    idleMinutes: typeof config.idleMinutes === 'number' && config.idleMinutes > 0 ? config.idleMinutes : 30,
    skillDir: typeof config.skillDir === 'string' ? config.skillDir.trim() : '',
  }
}

/** The process the MCP server runs as. */
export function serverCommand(settings: Settings): { command: string; args: string[] } {
  return settings.python
    ? { command: settings.python, args: ['-m', 'reelsmith.mcp_server'] }
    : { command: settings.command, args: settings.args }
}
