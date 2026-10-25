/**
 * dsh-plugin-reelsmith, host half: provides the `reelsmith` service (settings, the reelsmith MCP servers, the
 * tool list) and the Video editor panel's routes. `dsh-plugin-reelsmith/tools` puts the tools in front of an
 * agent; the browser half is `lib/client.js`.
 * @module dsh-plugin-reelsmith
 */
import type { Context } from '@deepseek-ai/cordis'
import { Config } from './config.ts'
import { registerRoutes, type ConnectionLike } from './routes.ts'
import { ReelsmithService } from './service.ts'

export { Config } from './config.ts'
export { ReelsmithService } from './service.ts'
export type { PanelState } from './service.ts'

declare module '@deepseek-ai/cordis' {
  interface Context {
    reelsmith: ReelsmithService
  }
  interface Events {
    /** Emitted by the Loader to this fiber when a `.volatile()` field changed (cordis-plugin-loader). */
    'loader/volatile-update'(paths: readonly (readonly string[])[]): void
  }
}

export const name = 'reelsmith'

const REAP_EVERY_MS = 60_000

export function apply(ctx: Context, config: Config): void {
  const service = new ReelsmithService(ctx, config)
  ctx.provide('reelsmith', service)
  ctx.effect(() => () => service.dispose(), 'reelsmith: servers')
  // A settings edit on the Plugins page lands as a volatile update: start fresh servers with the new values.
  ctx.on('loader/volatile-update', () => { void service.restart() })
  ctx.effect(() => {
    const timer = setInterval(() => { void service.reap() }, REAP_EVERY_MS)
    timer.unref?.()
    return () => { clearInterval(timer) }
  }, 'reelsmith: idle servers')
  ctx.inject(['connection'], (inner) => {
    // Each register() is an effect of the calling context, so the routes leave with this plugin.
    registerRoutes((inner as unknown as { connection: ConnectionLike }).connection, service)
  })
  void service.ready()
}
