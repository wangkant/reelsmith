/**
 * reelsmith answers with text that names the PNGs it wrote ("contact sheet (...): <path>", "- 1.00s: <path>").
 * The model should see them, so the contact sheets (and a few stills) ride the MCP result as image content,
 * which dsh-mcp-client's projection stores as durable attachments when the model takes images.
 */
import { readFile, realpath, stat } from 'node:fs/promises'
import { basename, extname, isAbsolute, join, relative } from 'node:path'

const MEDIA: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
}

/**
 * The tools that write images into <project>/build; no other result gets any, since result text can carry words
 * the agent wrote itself (notes, text clips) that name any file.
 */
export const IMAGE_TOOLS = new Set(['preview', 'review', 'frames', 'scenes'])

/** Of those, the ones whose bullet lines are stills worth attaching (scenes sends only its sheet). */
export const STILL_TOOLS = new Set(['preview', 'review', 'frames'])

/** Larger files stay paths: the model can still open them with read_image. */
const MAX_IMAGE_BYTES = 8 * 1024 * 1024

/** The images one result names, contact sheets first. */
export interface NamedImages {
  sheets: string[]
  stills: string[]
}

function imagePathIn(line: string): string | undefined {
  // The path is the last thing on the line, after the last ": " (paths may hold spaces, never ": ").
  const cut = line.lastIndexOf(': ')
  const candidate = (cut >= 0 ? line.slice(cut + 2) : line).trim().replace(/^["'`]|["'`.,;]$/g, '')
  if (!MEDIA[extname(candidate).toLowerCase()]) return undefined
  return isAbsolute(candidate) ? candidate : undefined
}

/** Contact sheets and stills named in a result's text (scenes calls its sheet "first frames"). */
export function namedImages(text: string): NamedImages {
  const sheets: string[] = []
  const stills: string[] = []
  for (const line of text.split(/\r?\n/)) {
    const path = imagePathIn(line)
    if (path === undefined) continue
    if (/contact sheet|first frames/i.test(line) || basename(path).toLowerCase() === 'contact.png') {
      if (!sheets.includes(path)) sheets.push(path)
    } else if (/^\s*-\s/.test(line) && !stills.includes(path)) {
      stills.push(path)
    }
  }
  return { sheets, stills }
}

/** The image paths to attach for one call: every sheet, and the stills when there are few. */
export function imagesToAttach(tool: string, text: string, maxStills: number): string[] {
  if (!IMAGE_TOOLS.has(tool)) return []
  const { sheets, stills } = namedImages(text)
  const keepStills = STILL_TOOLS.has(tool) && stills.length > 0 && stills.length <= maxStills
  return [...sheets, ...keepStills ? stills : []]
}

interface McpBlock {
  type: string
  text?: string
}

/** The text of an MCP result's content. */
export function resultText(result: unknown): string {
  const content = (result as { content?: unknown })?.content
  if (!Array.isArray(content)) return ''
  return content
    .filter((block): block is McpBlock => typeof block === 'object' && block !== null && (block as McpBlock).type === 'text')
    .map(block => block.text ?? '')
    .join('\n')
}

/** Whether `child` is inside `parent` (both real paths). */
function within(parent: string, child: string): boolean {
  const rel = relative(parent, child)
  return rel !== '' && !rel.startsWith('..') && !isAbsolute(rel)
}

/**
 * Append image blocks for the files a result names, only those that really lie in the called project's build
 * folder (links resolved). A result that already carries images (a server that attaches its own), an error
 * result and a call without a project are left alone; unreadable files stay text.
 */
export async function withImages(tool: string, result: unknown, maxStills: number, project?: string): Promise<unknown> {
  if (typeof result !== 'object' || result === null || project === undefined) return result
  const r = result as { content?: unknown; isError?: boolean }
  if (r.isError === true || !Array.isArray(r.content)) return result
  if (r.content.some(block => typeof block === 'object' && block !== null && (block as McpBlock).type === 'image')) return result
  const paths = imagesToAttach(tool, resultText(result), maxStills)
  if (paths.length === 0) return result
  let build: string
  try {
    build = await realpath(join(project, 'build'))
  } catch {
    return result
  }
  const blocks: unknown[] = []
  for (const path of paths) {
    try {
      if (!within(build, await realpath(path))) continue
      const info = await stat(path)
      if (!info.isFile() || info.size > MAX_IMAGE_BYTES) continue
      const data = await readFile(path)
      blocks.push({ type: 'image', data: data.toString('base64'), mimeType: MEDIA[extname(path).toLowerCase()] })
    } catch {
      // A file that went away or cannot be read stays a path in the text.
    }
  }
  return blocks.length === 0 ? result : { ...r, content: [...r.content, ...blocks] }
}
