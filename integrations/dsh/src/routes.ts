/**
 * The panel's routes on Connection's authenticated /api channel (owner only): the project state, the files of
 * projects reelsmith calls touched (with Range, so the film seeks), and a reconnect.
 */
import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import { extname, isAbsolute } from 'node:path'
import { Readable } from 'node:stream'
import type { ReelsmithService } from './service.ts'

/** The slice of `ctx.connection` this file uses. */
export interface ConnectionLike {
  fetch: {
    register(route: {
      path: string
      methods: ('GET' | 'HEAD' | 'POST')[]
      requestBody: 'buffered' | 'streaming'
      fetch: (request: Request) => Promise<Response>
    }): () => Promise<void>
  }
}

export const STATE_PATH = '/api/reelsmith/state'
export const FILE_PATH = '/api/reelsmith/file'
export const RECONNECT_PATH = '/api/reelsmith/reconnect'

const TYPES: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
  '.mov': 'video/quicktime',
  '.wav': 'audio/wav',
  '.mp3': 'audio/mpeg',
  '.m4a': 'audio/mp4',
  '.json': 'application/json',
}

const NO_STORE = {
  'Cache-Control': 'private, no-store',
  'X-Content-Type-Options': 'nosniff',
  'Content-Security-Policy': "sandbox; default-src 'none'",
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { ...NO_STORE, 'Content-Type': 'application/json; charset=utf-8' } })
}

function fail(status: number, text: string): Response {
  return new Response(text, { status, headers: { ...NO_STORE, 'Content-Type': 'text/plain; charset=utf-8' } })
}

/** Answer one file request; exported for tests. */
export async function serveFile(request: Request, service: Pick<ReelsmithService, 'readable'>): Promise<Response> {
  const path = new URL(request.url).searchParams.get('path') ?? ''
  if (!path || path.includes('\0') || !isAbsolute(path)) return fail(400, 'absolute path required')
  const type = TYPES[extname(path).toLowerCase()]
  if (type === undefined) return fail(415, 'not a media or JSON file')
  if (!service.readable(path)) return fail(403, 'outside every reelsmith project of this session')
  let size: number
  try {
    const info = await stat(path)
    if (!info.isFile()) return fail(404, 'not found')
    size = info.size
  } catch {
    return fail(404, 'not found')
  }
  const headers: Record<string, string> = { ...NO_STORE, 'Content-Type': type, 'Accept-Ranges': 'bytes' }
  const range = /^bytes=(\d*)-(\d*)$/.exec(request.headers.get('range') ?? '')
  let start = 0
  let end = size - 1
  let status = 200
  if (range && (range[1] || range[2])) {
    if (range[1]) {
      start = Number(range[1])
      end = range[2] ? Math.min(Number(range[2]), size - 1) : size - 1
    } else {
      start = Math.max(0, size - Number(range[2]))
    }
    if (start > end || start >= size) {
      return new Response(null, { status: 416, headers: { ...headers, 'Content-Range': `bytes */${size}` } })
    }
    status = 206
    headers['Content-Range'] = `bytes ${start}-${end}/${size}`
  }
  headers['Content-Length'] = String(size === 0 ? 0 : end - start + 1)
  if (request.method === 'HEAD' || size === 0) return new Response(null, { status, headers })
  const body = Readable.toWeb(createReadStream(path, { start, end })) as ReadableStream<Uint8Array>
  return new Response(body, { status, headers })
}

/** Register the routes; the returned disposer removes them. */
export function registerRoutes(connection: ConnectionLike, service: ReelsmithService): () => Promise<void> {
  const disposers = [
    connection.fetch.register({
      path: STATE_PATH,
      methods: ['GET'],
      requestBody: 'buffered',
      fetch: async (request) => {
        const params = new URL(request.url).searchParams
        const state = await service.panelState(params.get('session') ?? undefined, params.get('project') ?? undefined)
        return json(state)
      },
    }),
    connection.fetch.register({
      path: FILE_PATH,
      methods: ['GET', 'HEAD'],
      requestBody: 'buffered',
      fetch: request => serveFile(request, service),
    }),
    connection.fetch.register({
      path: RECONNECT_PATH,
      methods: ['POST'],
      requestBody: 'buffered',
      fetch: async () => {
        await service.restart()
        return json((await service.panelState(undefined, undefined)).status)
      },
    }),
  ]
  return async () => { await Promise.all(disposers.map(dispose => dispose())) }
}
