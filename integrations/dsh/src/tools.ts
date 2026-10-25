/**
 * dsh-plugin-reelsmith/tools: reelsmith's tools and the Video editor prompt section for the agents in scope
 * (a preset's agents, or the process-wide agent of headless/SDK profiles). Each tool goes through
 * dsh-mcp-client's own MCP adapter, so results, errors and images behave as for any MCP server.
 * @module dsh-plugin-reelsmith/tools
 */
import type { Context } from '@deepseek-ai/cordis'
import { createMcpToolDefinition } from '@deepseek-ai/dsh-mcp-client'
import type { ToolInfo } from './pool.ts'
import type { ExecutionLike, ReelsmithService } from './service.ts'

export const name = 'reelsmith-tools'
export const inject = ['tools', 'reelsmith']

/** Prefix shared with dsh-mcp-client's naming, so permission rules read the same. */
export const TOOL_PREFIX = 'mcp__reelsmith__'

/** After the persona, before the first-party tool guidance. */
const SECTION_ORDER = 100

/** DeepSeek's function-name contract. */
const VALID_NAME = /^[A-Za-z0-9_-]{1,64}$/

/** Wait at most this long for the first tool list before the agent starts without it. */
const READY_TIMEOUT_MS = 60_000

interface ToolsLike {
  register(definition: unknown): () => void
}

interface SystemPromptLike {
  section(section: { name: string; order: number; interpolate?: boolean; text: () => string }): () => void
}

/** The model-facing definition of one reelsmith tool. */
export function definitionFor(ctx: Context, service: Pick<ReelsmithService, 'call'>, tool: ToolInfo): unknown {
  return createMcpToolDefinition(ctx, {
    name: TOOL_PREFIX + tool.name,
    rawName: tool.name,
    description: tool.description,
    inputSchema: tool.inputSchema,
    ...tool.outputSchema === undefined ? {} : { outputSchema: tool.outputSchema },
    call: (args, execution) => service.call(tool.name, args, execution as unknown as ExecutionLike),
  })
}

export async function apply(ctx: Context): Promise<void> {
  const service = ctx.get('reelsmith') as ReelsmithService
  // Property access, not ctx.get: the caller-bound service files registrations under this scope (a preset's).
  const tools = (ctx as unknown as { tools: ToolsLike }).tools
  let live: (() => void)[] = []
  let disposed = false
  const clear = (): void => {
    for (const dispose of live) {
      try { dispose() } catch { /* already gone with its scope */ }
    }
    live = []
  }
  let synced = false
  const sync = (list: readonly ToolInfo[]): void => {
    if (disposed) return
    synced = true
    clear()
    try {
      for (const tool of list) {
        if (VALID_NAME.test(TOOL_PREFIX + tool.name)) live.push(tools.register(definitionFor(ctx, service, tool)))
        else ctx.logger?.warn?.(`reelsmith: skipped tool ${JSON.stringify(tool.name)}: not a valid function name`)
      }
    } catch (error) {
      // All or nothing, as dsh-mcp-client does: a conflict leaves no partial tool set.
      clear()
      ctx.logger?.error?.('reelsmith: tool registration failed', error)
    }
  }
  ctx.effect(() => service.onTools(sync), 'reelsmith: tool list')
  ctx.effect(() => () => { disposed = true; clear() }, 'reelsmith: tools')
  ctx.inject(['systemPrompt'], (inner) => {
    // section() is itself an effect of the calling context.
    ;(inner as unknown as { systemPrompt: SystemPromptLike }).systemPrompt.section({
      name: 'reelsmith:editor',
      order: SECTION_ORDER,
      interpolate: false,
      text: () => service.promptText(),
    })
  })
  await Promise.race([
    service.ready(),
    new Promise<void>((done) => { setTimeout(done, READY_TIMEOUT_MS).unref?.() }),
  ])
  // A discovery that finished before this plugin subscribed: register its list now.
  if (!synced) sync(service.toolList())
}
