/**
 * dsh-plugin-reelsmith, browser half: the Video editor panel (a right-sidebar tab), reelsmith tool rows in the
 * conversation with their images and film inline, and the plugin's settings page. Loaded by dsh-client-modules
 * as a closure factory; React and the UI primitives come from the shell's shared module table.
 */

declare namespace JSX {
  interface IntrinsicElements { [name: string]: any }
  type Element = any
}

;(function registerReelsmithClient() {
  const ID = 'dsh-plugin-reelsmith'
  const NS = 'reelsmith'
  const PREFIX = 'mcp__reelsmith__'
  const TAB_ID = 'dsh-plugin-reelsmith/editor'
  const TAB_KIND = 'reelsmith'
  const ROW_KEY = 'dsh-plugin-reelsmith#reelsmith'
  const RESULT_EVENT = 'dsh-reelsmith-result'
  const LOADED_AT = Date.now()
  /** The tools rows are registered for before the Host reports its list (reelsmith's, and footage tools). */
  const KNOWN_TOOLS = [
    'manual', 'notes', 'note', 'new_project', 'describe', 'edit', 'undo', 'check', 'library', 'typecheck',
    'preview', 'render', 'review', 'speak', 'capture', 'draw', 'animate', 'import_asset', 'assets',
    'look', 'probe', 'scenes', 'silences', 'transcribe', 'frames',
  ]

  const en: Record<string, string> = {
    'panel.title': 'Video editor',
    'panel.description': 'The reelsmith project: preview, film and timeline',
    'panel.empty': 'No reelsmith project in this session yet. Ask the agent to make or open one.',
    'panel.film': 'Film',
    'panel.noFilm': 'No film yet: the agent renders out/film.mp4 when the edit is ready.',
    'panel.preview': 'Preview',
    'panel.noPreview': 'No preview yet.',
    'panel.review': 'Review',
    'panel.stills': 'Stills',
    'panel.timeline': 'Timeline',
    'panel.refresh': 'Refresh',
    'panel.reconnect': 'Reconnect',
    'panel.disconnected': 'reelsmith is not connected',
    'panel.configure': 'Set the Python interpreter in Plugins > reelsmith > Configure.',
    'panel.project': 'Project',
    'panel.loading': 'Loading...',
    'panel.unavailable': 'The reelsmith panel routes are not available on this Host.',
    'row.open': 'Show in the Video editor panel',
    'row.delivered': 'Delivered',
    'row.failed': 'Failed',
    'row.stopped': 'Stopped',
    'image.dialog': 'Image',
    'image.close': 'Close',
    'settings.summary': 'Python interpreter, workspace root and defaults for reelsmith',
    'settings.python': 'Python interpreter',
    'settings.python.hint': 'A Python with reelsmith installed; runs `python -m reelsmith.mcp_server`. Empty uses the command below.',
    'settings.command': 'Server command',
    'settings.command.hint': 'Used when no interpreter is set: the reelsmith-mcp entry point on PATH.',
    'settings.workspaceRoot': 'Workspace root',
    'settings.workspaceRoot.hint': 'REELSMITH_ROOT for every call. Empty uses each session\'s working directory.',
    'settings.fence': 'Keep projects inside the root',
    'settings.fence.hint': 'Tools refuse projects and local imports outside REELSMITH_ROOT.',
    'settings.profile': 'Default profile',
    'settings.profile.hint': 'Output profile for new projects when the agent names none (empty: reelsmith decides).',
    'settings.attachStills': 'Stills shown to the model',
    'settings.attachStills.hint': 'A preview or review with at most this many stills sends them as images; the contact sheet always goes.',
    'settings.timeoutMs': 'Call timeout (ms)',
    'settings.timeoutMs.hint': 'Longest a single reelsmith call may take; render takes minutes.',
    'settings.overridden': 'Changed',
    'settings.reset': 'Reset',
    'settings.invalid': 'Not a valid value',
    'settings.unavailable': 'Settings are not served for this row. Edit the reelsmith row in the profile\'s cordis.patch.yml.',
    'settings.readOnly': 'This profile\'s settings are read-only.',
    'settings.saveFailed': 'The Host did not accept these values.',
    'settings.save': 'Save',
    'settings.saving': 'Saving...',
    'settings.restart': 'Saving restarts the reelsmith server; new sessions see the new tools.',
  }
  const zh: Record<string, string> = {
    'panel.title': '视频剪辑',
    'panel.description': '当前 reelsmith 项目：预览、成片与时间线',
    'panel.empty': '这个会话还没有 reelsmith 项目。让智能体新建或打开一个。',
    'panel.film': '成片',
    'panel.noFilm': '还没有成片：剪辑就绪后智能体会渲染 out/film.mp4。',
    'panel.preview': '预览',
    'panel.noPreview': '还没有预览。',
    'panel.review': '审片',
    'panel.stills': '静帧',
    'panel.timeline': '时间线',
    'panel.refresh': '刷新',
    'panel.reconnect': '重新连接',
    'panel.disconnected': 'reelsmith 未连接',
    'panel.configure': '在 插件 > reelsmith > 配置 中设置 Python 解释器。',
    'panel.project': '项目',
    'panel.loading': '加载中…',
    'panel.unavailable': '此 Host 不提供 reelsmith 面板接口。',
    'row.open': '在视频剪辑面板中查看',
    'row.delivered': '已出片',
    'row.failed': '失败',
    'row.stopped': '已停止',
    'image.dialog': '图片',
    'image.close': '关闭',
    'settings.summary': 'reelsmith 的 Python 解释器、工作区根目录与默认值',
    'settings.python': 'Python 解释器',
    'settings.python.hint': '装有 reelsmith 的 Python，运行 `python -m reelsmith.mcp_server`。留空则用下面的命令。',
    'settings.command': '服务命令',
    'settings.command.hint': '未设置解释器时使用：PATH 上的 reelsmith-mcp。',
    'settings.workspaceRoot': '工作区根目录',
    'settings.workspaceRoot.hint': '每次调用的 REELSMITH_ROOT。留空则用各会话的工作目录。',
    'settings.fence': '项目限定在根目录内',
    'settings.fence.hint': '工具拒绝 REELSMITH_ROOT 之外的项目和本地导入。',
    'settings.profile': '默认画面规格',
    'settings.profile.hint': '智能体未指定时新项目使用的输出 profile（留空由 reelsmith 决定）。',
    'settings.attachStills': '给模型看的静帧数',
    'settings.attachStills.hint': '预览或审片的静帧不超过这个数时作为图片发给模型；接触表总会发送。',
    'settings.timeoutMs': '调用超时（毫秒）',
    'settings.timeoutMs.hint': '单次 reelsmith 调用的最长时间；渲染需要几分钟。',
    'settings.overridden': '已修改',
    'settings.reset': '恢复',
    'settings.invalid': '不是有效的值',
    'settings.unavailable': '这一行没有提供设置。请编辑配置的 cordis.patch.yml 里的 reelsmith 行。',
    'settings.readOnly': '此配置的设置为只读。',
    'settings.saveFailed': 'Host 没有接受这些值。',
    'settings.save': '保存',
    'settings.saving': '保存中…',
    'settings.restart': '保存后 reelsmith 服务会重启；新会话会看到新工具。',
  }
  const TOOL_LABELS: Record<string, [string, string]> = {
    manual: ['Manual', '手册'], notes: ['Notes', '笔记'], note: ['Note', '记笔记'], new_project: ['New project', '新建项目'],
    describe: ['Timeline', '时间线'], edit: ['Edit', '编辑'], undo: ['Undo', '撤销'], check: ['Check', '检查'],
    library: ['Library', '组件库'], typecheck: ['Type-check', '类型检查'], preview: ['Preview', '预览'],
    render: ['Render', '渲染'], review: ['Review', '审片'], speak: ['Narration', '配音'], capture: ['Capture', '截图'],
    draw: ['Draw', '画图'], animate: ['Animate', '动画'], import_asset: ['Import', '导入素材'], assets: ['Assets', '素材'],
    look: ['Look', '查看素材'], probe: ['Probe', '探测'], scenes: ['Scenes', '场景'], silences: ['Silences', '静音段'],
    transcribe: ['Transcribe', '转写'], frames: ['Frames', '抽帧'],
  }

  const w = window as any
  w.__ModuleLoader__.load({ id: ID, factory })

  function factory(require: (id: string) => any) {
    const React = require('react')
    const P = require('@deepseek-ai/dsh-client-ui-primitives')
    const h = React.createElement
    const Fragment = React.Fragment
    const { useCallback, useEffect, useRef, useState } = React
    void Fragment
    injectStyle()

    const fallbackT = (key: string): string => en[key] ?? key
    const zhActive = (): boolean => /^zh/i.test(document.documentElement.lang || navigator.language || '')
    const toolLabel = (tool: string): string => {
      const pair = TOOL_LABELS[tool]
      return pair ? pair[zhActive() ? 1 : 0] : tool
    }

    function fileUrl(path: string, version?: number): string {
      return `api/reelsmith/file?path=${encodeURIComponent(path)}${version ? `&v=${version}` : ''}`
    }

    function baseName(path: string): string {
      return path.split(/[\\/]/).filter(Boolean).pop() ?? path
    }

    function FilmIcon(): JSX.Element {
      return (
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <rect x="2.25" y="3.25" width="11.5" height="9.5" rx="1.75" stroke="currentColor" strokeWidth="1.2" />
          <path d="M4.75 3.5v9M11.25 3.5v9M2.5 6.25h2.25M2.5 9.75h2.25M11.25 6.25h2.25M11.25 9.75h2.25" stroke="currentColor" strokeWidth="1.2" />
          <path d="M7.1 6.4v3.2l2.5-1.6z" fill="currentColor" />
        </svg>
      )
    }

    function GuideArt(): JSX.Element {
      return (
        <svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden="true">
          <rect x="5" y="9" width="30" height="22" rx="4" stroke="currentColor" strokeWidth="1.6" />
          <path d="M11 9.5v21M29 9.5v21M5.5 15h5.5M5.5 25h5.5M29 15h5.5M29 25h5.5" stroke="currentColor" strokeWidth="1.6" />
          <path d="M17.5 15.5v9l7-4.5z" fill="currentColor" />
        </svg>
      )
    }

    /** A durable attachment image, resolved through the Session-authorized loader. */
    function AttachmentImage({ attachment, loadImage, onOpen, small }: any): JSX.Element | null {
      const [url, setUrl] = useState(() => loadImage?.peek?.(attachment))
      useEffect(() => {
        let live = true
        if (url === undefined && typeof loadImage === 'function') {
          loadImage(attachment).then((value: string) => { if (live) setUrl(value) }, () => undefined)
        }
        return () => { live = false }
      }, [attachment, loadImage, url])
      const className = small ? 'rs-thumb rs-small' : 'rs-thumb'
      if (!url) return <div className={`${className} rs-thumb-wait`} />
      return <img className={className} src={url} alt={attachment?.name ?? 'image'} onClick={() => onOpen(url)} />
    }

    /** Images with a lightbox. */
    function Gallery({ items, t }: any): JSX.Element | null {
      const [open, setOpen] = useState(null as string | null)
      if (!items.length) return null
      return (
        <div className="rs-gallery">
          {items.map((item: any, index: number) => item.attachment
            ? <AttachmentImage key={index} attachment={item.attachment} loadImage={item.loadImage} onOpen={setOpen} small={item.small} />
            : <img key={index} className={item.small ? 'rs-thumb rs-small' : 'rs-thumb'} src={item.url} alt={baseName(item.path ?? '')} loading="lazy" onClick={() => setOpen(item.url)} />)}
          {open ? <P.ImageLightbox src={open} alt="" labels={{ dialog: t('image.dialog'), close: t('image.close') }} onClose={() => setOpen(null)} /> : null}
        </div>
      )
    }

    function parseArgs(raw: unknown): Record<string, unknown> {
      if (typeof raw !== 'string' || !raw) return {}
      try {
        const value = JSON.parse(raw)
        return value && typeof value === 'object' ? value : {}
      } catch {
        return {}
      }
    }

    function contentText(content: any): string {
      if (!Array.isArray(content)) return ''
      return content.filter((block: any) => block?.type === 'text').map((block: any) => String(block.text ?? '')).join('\n')
    }

    /** Contact sheet paths in a result's text (shown when the model's images were not stored). */
    function sheetPaths(text: string): string[] {
      const out: string[] = []
      for (const line of text.split(/\r?\n/)) {
        if (!/contact sheet/i.test(line)) continue
        const cut = line.lastIndexOf(': ')
        const path = (cut >= 0 ? line.slice(cut + 2) : '').trim()
        if (/\.(png|jpe?g|webp)$/i.test(path)) out.push(path)
      }
      return out
    }

    function deliveredFilm(text: string): string | undefined {
      const match = /^DELIVERED: (.+?\.mp4) \(/m.exec(text)
      return match ? match[1] : undefined
    }

    function openPanel(ctx: any): void {
      try { ctx.get('sidebarRight')?.openTab(TAB_KIND) } catch { /* no Session on screen */ }
    }

    let autoOpened = false

    /** One reelsmith tool call: its row, then its images and film inline. */
    function ToolRow(props: any): JSX.Element {
      const t = props.t ?? fallbackT
      const tool = String(props.toolName ?? '').slice(PREFIX.length)
      const disclosure = props.useDisclosure ? props.useDisclosure() : { expanded: false, toggle: () => undefined }
      const block = props.block ?? {}
      const settled = props.phase === 'result'
      const args = parseArgs(settled ? block.call?.argsRaw : block.argsRaw)
      const text = settled ? contentText(block.content) : ''
      const state = !settled ? 'running' : block.error?.code === 'interrupted' ? 'stopped' : block.isError ? 'error' : 'ok'
      const project = typeof args.project === 'string' ? baseName(args.project) : ''
      const film = settled && state === 'ok' && tool === 'render' ? deliveredFilm(text) : undefined
      const firstLine = text.split(/\r?\n/)[0] ?? ''
      const summary = state === 'error' ? `${t('row.failed')}: ${firstLine}`
        : state === 'stopped' ? t('row.stopped')
        : film ? `${t('row.delivered')} · ${project}` : project
      const images: any[] = []
      if (settled && state === 'ok') {
        const stored = Array.isArray(block.content) ? block.content.filter((part: any) => part?.type === 'image' && part.attachment) : []
        // The plugin attaches contact sheets first, then stills: the sheets show large, the stills small.
        const sheets = sheetPaths(text)
        if (stored.length) stored.forEach((part: any, index: number) => images.push({ attachment: part.attachment, loadImage: props.loadImage, small: index >= Math.max(1, sheets.length) }))
        else for (const path of sheets) images.push({ path, url: fileUrl(path, block.time) })
      }
      const live = settled && typeof block.time === 'number' && block.time >= LOADED_AT
      useEffect(() => {
        if (!live) return
        window.dispatchEvent(new CustomEvent(RESULT_EVENT, { detail: { tool, project: args.project } }))
        if (!autoOpened && state === 'ok' && (tool === 'preview' || tool === 'review' || tool === 'render')) {
          autoOpened = true
          openPanel(props.ctx)
        }
      }, [live])
      const accessory = settled && project
        ? <button type="button" className="rs-row-open" title={t('row.open')} aria-label={t('row.open')} onClick={() => openPanel(props.ctx)}><FilmIcon /></button>
        : null
      return (
        <div className="rs-row" data-state={state} data-tool={tool}>
          <P.DisclosureRow
            icon={<FilmIcon />}
            title={toolLabel(tool)}
            open={disclosure.expanded}
            expandable={settled && text !== ''}
            expandOnRowClick
            onToggle={disclosure.toggle}
            running={!settled}
            keepContentWhenOpen
            collapsedContent={summary ? <span className="rs-row-summary">{summary}</span> : null}
            headerAccessory={accessory}
          >
            <pre className="rs-text">{text}</pre>
          </P.DisclosureRow>
          {images.length ? <Gallery items={images} t={t} /> : null}
          {film ? <video className="rs-film" controls preload="metadata" src={fileUrl(film, block.time)} /> : null}
        </div>
      )
    }

    /** Poll the panel state while the tab is visible, and right after every live reelsmith result. */
    function usePanelState(sessionId: string | undefined, visible: boolean, project: string | undefined): any {
      const [state, setState] = useState(null as any)
      const [error, setError] = useState(null as string | null)
      const busy = useRef(false)
      const load = useCallback(async () => {
        if (busy.current) return
        busy.current = true
        try {
          const query = new URLSearchParams()
          if (sessionId) query.set('session', String(sessionId))
          if (project) query.set('project', project)
          const response = await fetch(`api/reelsmith/state?${query}`, { cache: 'no-store', credentials: 'same-origin' })
          if (!response.ok) throw new Error(String(response.status))
          setState(await response.json())
          setError(null)
        } catch (failure: any) {
          setError(String(failure?.message ?? failure))
        } finally {
          busy.current = false
        }
      }, [sessionId, project])
      useEffect(() => {
        if (!visible) return
        void load()
        const timer = setInterval(() => { void load() }, 3000)
        const onResult = (): void => { void load() }
        window.addEventListener(RESULT_EVENT, onResult)
        return () => { clearInterval(timer); window.removeEventListener(RESULT_EVENT, onResult) }
      }, [visible, load])
      return { state, error, reload: load }
    }

    function Section({ title, children, aside }: any): JSX.Element {
      return (
        <section className="rs-section">
          <div className="rs-section-head"><h4>{title}</h4>{aside}</div>
          {children}
        </section>
      )
    }

    /** The Video editor tab body. */
    function Panel(props: any): JSX.Element {
      const t = props.t ?? fallbackT
      const info = typeof props.useTabInfo === 'function' ? props.useTabInfo() : undefined
      const tab = info?.tab
      const visible = tab ? tab.visible !== false : true
      const [chosen, setChosen] = useState(undefined as string | undefined)
      const { state, error, reload } = usePanelState(props.sessionId, visible, chosen)
      useEffect(() => tab?.actions?.bindCommands?.({ refresh: () => { void reload() } }), [tab?.actions, reload])
      const reconnect = async (): Promise<void> => {
        try { await fetch('api/reelsmith/reconnect', { method: 'POST', credentials: 'same-origin' }) } catch { /* shown by the next poll */ }
        void reload()
      }
      if (error && !state) return <div className="rs-panel"><p className="rs-muted">{error === '404' ? t('panel.unavailable') : error}</p></div>
      if (!state) return <div className="rs-panel"><p className="rs-muted">{t('panel.loading')}</p></div>
      const project = state.project
      return (
        <div className="rs-panel">
          <div className="rs-panel-head">
            <div className="rs-panel-title">
              <FilmIcon />
              <span>{project ? project.name : t('panel.title')}</span>
              {project ? <span className="rs-path" title={project.path}>{project.path}</span> : null}
            </div>
            <P.Button size="sm" onClick={() => { void reload() }}>{t('panel.refresh')}</P.Button>
          </div>
          {state.projects?.length > 1 ? (
            <label className="rs-picker">{t('panel.project')}
              <select value={project?.path ?? ''} onChange={(event: any) => setChosen(event.target.value || undefined)}>
                {state.projects.map((item: any) => <option key={item.path} value={item.path}>{item.name}</option>)}
              </select>
            </label>
          ) : null}
          {!state.status.connected ? (
            <div className="rs-notice">
              <strong>{t('panel.disconnected')}</strong>
              <pre>{state.status.error ?? state.status.command}</pre>
              <p>{t('panel.configure')}</p>
              <P.Button size="sm" variant="outline" onClick={() => { void reconnect() }}>{t('panel.reconnect')}</P.Button>
            </div>
          ) : null}
          {!project ? <p className="rs-muted">{t('panel.empty')}</p> : (
            <>
              <Section title={t('panel.film')}>
                {project.film
                  ? <video className="rs-film" controls preload="metadata" key={project.film.mtime} src={fileUrl(project.film.path, project.film.mtime)} />
                  : <p className="rs-muted">{t('panel.noFilm')}</p>}
              </Section>
              <Section title={t('panel.preview')}>
                {project.preview.sheet
                  ? <Gallery t={t} items={[{ path: project.preview.sheet.path, url: fileUrl(project.preview.sheet.path, project.preview.sheet.mtime) }]} />
                  : <p className="rs-muted">{t('panel.noPreview')}</p>}
                {project.preview.stills.length
                  ? <div className="rs-stills"><Gallery t={t} items={project.preview.stills.map((ref: any) => ({ path: ref.path, url: fileUrl(ref.path, ref.mtime) }))} /></div>
                  : null}
              </Section>
              {project.review.sheet ? (
                <Section title={t('panel.review')}>
                  <Gallery t={t} items={[{ path: project.review.sheet.path, url: fileUrl(project.review.sheet.path, project.review.sheet.mtime) }]} />
                </Section>
              ) : null}
              <Section title={t('panel.timeline')}>
                {project.describe
                  ? <pre className="rs-describe">{project.describe}</pre>
                  : <p className="rs-muted">{project.describeError ?? t('panel.loading')}</p>}
              </Section>
            </>
          )}
        </div>
      )
    }

    const SETTINGS_FIELDS: { field: string; kind: 'text' | 'number' }[] = [
      { field: 'python', kind: 'text' },
      { field: 'command', kind: 'text' },
      { field: 'workspaceRoot', kind: 'text' },
      { field: 'profile', kind: 'text' },
      { field: 'attachStills', kind: 'number' },
      { field: 'timeoutMs', kind: 'number' },
    ]

    function formatValue(value: unknown): string {
      return value === undefined || value === null ? '' : String(value)
    }

    function parseDraft(kind: 'text' | 'number', text: string): { op: 'set' | 'unset'; value?: unknown } | undefined {
      const trimmed = text.trim()
      if (kind === 'text') return { op: 'set', value: trimmed }
      if (trimmed === '') return { op: 'unset' }
      const value = Number(trimmed)
      return Number.isFinite(value) && value >= 0 ? { op: 'set', value: Math.floor(value) } : undefined
    }

    /** The row's settings entry on the Plugins page: a one-liner, or the form. */
    function SettingsPage(props: any): any {
      const t = props.t ?? fallbackT
      return props.view === 'summary' ? t('settings.summary') : <SettingsBody form={props.form} t={t} />
    }

    /** Staged edits and one Save, written through the page's revision-fenced form. */
    function SettingsBody({ form, t }: any): JSX.Element {
      const [draft, setDraft] = useState({} as Record<string, { text: string; clear?: boolean } | boolean>)
      const [saving, setSaving] = useState(false)
      const [failed, setFailed] = useState(false)
      if (!form) return <p className="rs-muted">{t('settings.unavailable')}</p>
      const snapshot = form.state ?? {}
      const value = (snapshot.value ?? {}) as Record<string, unknown>
      const user = (snapshot.user ?? {}) as Record<string, unknown>
      const fenceDraft = draft.fence
      const fence = typeof fenceDraft === 'boolean' ? fenceDraft : value.fence !== false
      const plan: { op: 'set' | 'unset'; path: string[]; value?: unknown }[] = []
      let invalid = false
      for (const { field, kind } of SETTINGS_FIELDS) {
        const staged = draft[field]
        if (staged === undefined || typeof staged === 'boolean') continue
        if (staged.clear) { plan.push({ op: 'unset', path: [field] }); continue }
        const parsed = parseDraft(kind, staged.text)
        if (parsed === undefined) { invalid = true; continue }
        plan.push(parsed.op === 'unset' ? { op: 'unset', path: [field] } : { op: 'set', path: [field], value: parsed.value })
      }
      if (typeof fenceDraft === 'boolean') plan.push({ op: 'set', path: ['fence'], value: fenceDraft })
      const save = async (): Promise<void> => {
        if (!plan.length || invalid) return
        setSaving(true)
        setFailed(false)
        try {
          const ok = await form.mutate(plan, snapshot.revision)
          if (ok) setDraft({})
          setFailed(!ok)
        } catch {
          setFailed(true)
        } finally {
          setSaving(false)
        }
      }
      const disabled = !snapshot.writable || saving
      return (
        <P.SettingsForm
          labels={{ unavailable: t('settings.unavailable'), readOnly: t('settings.readOnly'), saveFailed: t('settings.saveFailed'), save: t('settings.save'), saving: t('settings.saving') }}
          state={{ available: snapshot.status === 'ready', writable: Boolean(snapshot.writable), dirty: plan.length > 0, invalid, saving, failed }}
          onSave={() => { void save() }}
          onDiscard={() => { setDraft({}); setFailed(false) }}
        >
          {SETTINGS_FIELDS.map(({ field, kind }) => {
            const staged = draft[field]
            const text = staged !== undefined && typeof staged !== 'boolean' ? staged.text : formatValue(value[field])
            const overridden = staged !== undefined && typeof staged !== 'boolean' ? !staged.clear : Object.hasOwn(user, field)
            const bad = staged !== undefined && typeof staged !== 'boolean' && !staged.clear && parseDraft(kind, staged.text) === undefined
            return (
              <P.SettingsValueField
                key={field}
                id={`reelsmith-${field}`}
                label={t(`settings.${field}`)}
                hint={t(`settings.${field}.hint`)}
                text={text}
                overridden={overridden}
                invalid={bad}
                overriddenLabel={t('settings.overridden')}
                resetLabel={t('settings.reset')}
                invalidLabel={t('settings.invalid')}
                disabled={disabled}
                numeric={kind === 'number'}
                onEdit={(next: string) => setDraft({ ...draft, [field]: { text: next } })}
                onReset={() => setDraft({ ...draft, [field]: { text: '', clear: true } })}
              />
            )
          })}
          <div className="rs-switch-row">
            <div>
              <div className="rs-switch-label">{t('settings.fence')}</div>
              <div className="rs-muted">{t('settings.fence.hint')}</div>
            </div>
            <P.Switch checked={fence} label={t('settings.fence')} disabled={disabled} onChange={(next: boolean) => setDraft({ ...draft, fence: next })} />
          </div>
          <p className="rs-muted">{t('settings.restart')}</p>
        </P.SettingsForm>
      )
    }

    function apply(ctx: any): void {
      ctx.effect(() => ctx.locale.register(NS, { en, zh }), 'reelsmith: copy')
      const t = ctx.locale.bind ? ctx.locale.bind(NS) : fallbackT
      const registered = new Set<string>()
      const rowFor = (props: any) => h(ToolRow, { ...props, ctx })
      const registerRow = (tool: string): void => {
        const key = PREFIX + tool
        if (registered.has(key)) return
        registered.add(key)
        ctx.slots.inject('tool.call.toolview', () => ctx.slots.register({ name: 'tool.call.toolview', key, locale: NS }, rowFor))
      }
      for (const tool of KNOWN_TOOLS) registerRow(tool)
      // Tools this server has beyond the known list get rows too.
      fetch('api/reelsmith/state', { cache: 'no-store', credentials: 'same-origin' })
        .then(response => response.ok ? response.json() : undefined)
        .then((state: any) => { for (const tool of state?.status?.tools ?? []) registerRow(String(tool)) })
        .catch(() => undefined)

      ctx.inject(['sidebarRightTabs'], (inner: any) => {
        inner.effect(() => inner.sidebarRightTabs.register({
          id: TAB_ID,
          kind: TAB_KIND,
          priority: 'extension',
          title: () => t('panel.title'),
          guide: [{ id: 'open', order: 5, title: () => t('panel.title'), description: () => t('panel.description'), icon: GuideArt }],
        }), 'reelsmith: panel type')
        inner.slots.inject('sidebar.right.pane.tab', () => inner.slots.register({
          name: 'sidebar.right.pane.tab',
          key: TAB_ID,
          locale: NS,
          inject: (sessionId: unknown) => ({ sessionId }),
        }, Panel))
      })

      ctx.slots.inject('plugins.row.config', () => ctx.slots.register({ name: 'plugins.row.config', key: ROW_KEY, locale: NS }, SettingsPage))
    }

    return { inject: ['slots', 'locale'], apply }
  }

  function injectStyle(): void {
    if (document.querySelector(`style[data-plugin="${ID}"]`)) return
    const style = document.createElement('style')
    style.dataset.plugin = ID
    style.textContent = `
.rs-row { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.rs-row-summary { margin-left: 6px; color: var(--dsw-alias-label-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rs-row[data-state="error"] .rs-row-summary { color: var(--dsw-alias-state-error-primary); }
.rs-row-open { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; margin-left: 4px; border: 0; border-radius: var(--dsw-radius-sm, 6px); background: transparent; color: var(--dsw-alias-label-tertiary); cursor: pointer; }
.rs-row-open:hover { background: var(--dsw-alias-interactive-bg-hover); color: var(--dsw-alias-label-secondary); }
.rs-text { margin: 4px 0 0 22px; padding: 8px 10px; max-height: 320px; overflow: auto; white-space: pre-wrap; word-break: break-word; font: 12px/1.5 var(--dsw-font-mono, ui-monospace, monospace); color: var(--dsw-alias-label-secondary); background: var(--dsw-alias-bg-layer-2); border-radius: var(--dsw-radius-md, 8px); }
.rs-gallery { display: flex; flex-wrap: wrap; gap: 8px; margin-left: 22px; }
.rs-thumb { display: block; max-width: min(100%, 560px); max-height: 320px; border-radius: var(--dsw-radius-md, 8px); cursor: zoom-in; background: var(--dsw-alias-bg-layer-2); }
.rs-thumb-wait { width: 180px; height: 120px; }
.rs-stills .rs-gallery { margin-left: 0; }
.rs-gallery .rs-thumb.rs-small { max-height: 120px; max-width: 90px; }
.rs-film { display: block; width: 100%; max-height: 420px; margin-left: 0; border-radius: var(--dsw-radius-md, 8px); background: #000; }
.rs-row .rs-film { width: auto; max-width: min(100% - 22px, 560px); margin-left: 22px; }
.rs-panel { display: flex; flex-direction: column; gap: 16px; height: 100%; overflow: auto; padding: 12px 16px 24px; box-sizing: border-box; color: var(--dsw-alias-label-primary); font-size: var(--dsh-content-font-size-secondary, 13px); }
.rs-panel-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.rs-panel-title { display: flex; align-items: center; gap: 6px; min-width: 0; font-weight: 600; }
.rs-path { margin-left: 4px; font-weight: 400; color: var(--dsw-alias-label-tertiary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; direction: rtl; }
.rs-picker { display: flex; align-items: center; gap: 8px; color: var(--dsw-alias-label-secondary); }
.rs-picker select { flex: 1; min-width: 0; padding: 4px 0; border: 0; border-bottom: 1px solid var(--dsw-alias-border-l2); background: transparent; color: inherit; font: inherit; }
.rs-section { display: flex; flex-direction: column; gap: 8px; }
.rs-section-head { display: flex; align-items: center; justify-content: space-between; }
.rs-section h4 { margin: 0; font-size: 12px; font-weight: 600; letter-spacing: .02em; text-transform: uppercase; color: var(--dsw-alias-label-tertiary); }
.rs-panel .rs-gallery { margin-left: 0; }
.rs-panel .rs-thumb { max-width: 100%; max-height: 420px; }
.rs-panel .rs-stills .rs-thumb { max-height: 120px; max-width: 72px; }
.rs-describe { margin: 0; padding: 10px 12px; max-height: 480px; overflow: auto; white-space: pre; font: 12px/1.5 var(--dsw-font-mono, ui-monospace, monospace); color: var(--dsw-alias-label-secondary); background: var(--dsw-alias-bg-layer-2); border-radius: var(--dsw-radius-md, 8px); }
.rs-muted { margin: 0; color: var(--dsw-alias-label-tertiary); }
.rs-notice { display: flex; flex-direction: column; gap: 6px; padding: 10px 12px; border-radius: var(--dsw-radius-md, 8px); background: var(--dsw-alias-state-warn-tertiary, var(--dsw-alias-bg-layer-2)); color: var(--dsw-alias-label-primary); }
.rs-notice pre { margin: 0; white-space: pre-wrap; word-break: break-word; font: 12px/1.45 var(--dsw-font-mono, ui-monospace, monospace); color: var(--dsw-alias-label-secondary); }
.rs-notice p { margin: 0; }
.rs-switch-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 4px 0; }
.rs-switch-label { color: var(--dsw-alias-label-primary); font-size: 13px; font-weight: 500; }
.rs-switch-row .rs-muted { font-size: 12px; }
`
    document.head.append(style)
  }
})()
