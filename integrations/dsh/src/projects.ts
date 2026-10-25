/** What the panel shows: the projects reelsmith calls touched, per session, and each one's latest outputs. */
import { readdir, stat } from 'node:fs/promises'
import { basename, dirname, isAbsolute, join, relative, resolve } from 'node:path'
import { namedImages } from './images.ts'

/** A file the panel can show, with its mtime as a cache key. */
export interface FileRef {
  path: string
  mtime: number
  size: number
}

/** The latest images a preview or review wrote, as its result named them. */
export interface Shots {
  sheets: string[]
  stills: string[]
  at: number
}

/** One project the agent worked on. */
export interface ProjectRecord {
  path: string
  cwd: string
  root: string | undefined
  at: number
  preview?: Shots
  review?: Shots
}

/** The folder a `project` argument names (the folder itself, or its project.json). */
export function projectDir(value: string, cwd: string): string {
  const full = isAbsolute(value) ? value : resolve(cwd, value)
  return basename(full).toLowerCase() === 'project.json' ? dirname(full) : full
}

/** Whether `child` is `parent` or inside it (case-insensitive on Windows). */
export function inside(parent: string, child: string): boolean {
  const rel = relative(resolve(parent), resolve(child))
  return rel === '' || (!rel.startsWith('..') && !isAbsolute(rel))
}

async function fileRef(path: string): Promise<FileRef | undefined> {
  try {
    const info = await stat(path)
    return info.isFile() ? { path, mtime: Math.round(info.mtimeMs), size: info.size } : undefined
  } catch {
    return undefined
  }
}

async function refs(paths: readonly string[]): Promise<FileRef[]> {
  return (await Promise.all(paths.map(fileRef))).filter((ref): ref is FileRef => ref !== undefined)
}

/** The newest stills of a folder (by mtime), when no result named them. */
async function newestStills(folder: string, count: number): Promise<string[]> {
  try {
    const names = (await readdir(folder)).filter(name => /^still_.*\.png$/i.test(name))
    const dated = await Promise.all(names.map(async name => ({ path: join(folder, name), ref: await fileRef(join(folder, name)) })))
    return dated
      .filter(item => item.ref !== undefined)
      .sort((a, b) => (b.ref?.mtime ?? 0) - (a.ref?.mtime ?? 0))
      .slice(0, count)
      .map(item => item.path)
  } catch {
    return []
  }
}

/** The panel's view of one project. */
export interface ProjectView {
  path: string
  name: string
  at: number
  preview: { sheet: FileRef | null; stills: FileRef[] }
  review: { sheet: FileRef | null; stills: FileRef[] }
  film: FileRef | null
  projectJson: FileRef | null
}

const PANEL_STILLS = 12

/** The latest outputs of a project: what results named, else reelsmith's usual places. */
export async function viewOf(record: ProjectRecord): Promise<ProjectView> {
  const dir = record.path
  const previewSheet = (record.preview && (await refs(record.preview.sheets))[0])
    ?? await fileRef(join(dir, 'build', 'stills', 'contact.png'))
  const previewStills = record.preview
    ? await refs(record.preview.stills.slice(0, PANEL_STILLS))
    : await refs(await newestStills(join(dir, 'build', 'stills'), PANEL_STILLS))
  const reviewSheet = (record.review && (await refs(record.review.sheets))[0])
    ?? await fileRef(join(dir, 'build', 'review', 'contact.png'))
  const reviewStills = record.review ? await refs(record.review.stills.slice(0, PANEL_STILLS)) : []
  return {
    path: dir,
    name: basename(dir),
    at: record.at,
    preview: { sheet: previewSheet ?? null, stills: previewStills },
    review: { sheet: reviewSheet ?? null, stills: reviewStills },
    film: (await fileRef(join(dir, 'out', 'film.mp4'))) ?? null,
    projectJson: (await fileRef(join(dir, 'project.json'))) ?? null,
  }
}

const MAX_PROJECTS = 50

/** Projects by session, most recent first, plus every folder the panel may read files from. */
export class ProjectBook {
  private readonly bySession = new Map<string, ProjectRecord[]>()
  private readonly all = new Map<string, ProjectRecord>()
  /** Bumped on every change, so a panel can tell when to fetch again. */
  rev = 0

  touch(session: string | undefined, path: string, cwd: string, root: string | undefined): ProjectRecord {
    const key = resolve(path)
    let record = this.all.get(key)
    if (record === undefined) {
      record = { path: key, cwd, root, at: Date.now() }
      this.all.set(key, record)
      if (this.all.size > MAX_PROJECTS) {
        const oldest = [...this.all.values()].sort((a, b) => a.at - b.at)[0]
        if (oldest) this.all.delete(oldest.path)
      }
    }
    record.at = Date.now()
    record.cwd = cwd
    record.root = root
    const sid = session ?? ''
    const list = (this.bySession.get(sid) ?? []).filter(item => item.path !== key)
    list.unshift(record)
    this.bySession.set(sid, list.slice(0, 10))
    this.rev++
    return record
  }

  /** Remember the images a preview or review named. */
  shots(record: ProjectRecord, kind: 'preview' | 'review', text: string): void {
    const { sheets, stills } = namedImages(text)
    if (sheets.length === 0 && stills.length === 0) return
    record[kind] = { sheets, stills, at: Date.now() }
    this.rev++
  }

  bump(): void {
    this.rev++
  }

  recent(session: string | undefined): ProjectRecord[] {
    return this.bySession.get(session ?? '') ?? []
  }

  find(path: string): ProjectRecord | undefined {
    return this.all.get(resolve(path))
  }

  /** Whether a file lies inside a project some call touched. */
  readable(path: string): boolean {
    for (const record of this.all.values()) if (inside(record.path, path)) return true
    return false
  }
}
