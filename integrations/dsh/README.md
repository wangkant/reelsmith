# reelsmith for DeepSeek Harness

`dsh-plugin-reelsmith` turns [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (`dsh`) into a video
editor driven by [reelsmith](https://github.com/wangkant/reelsmith): a **Video editor** mode, reelsmith's editing
tools with their previews shown to the model as images, and a **Video editor panel** with the film, the latest
contact sheet and the timeline beside the conversation.

Tested with `@deepseek-ai/dsh` **0.2.1-rc.3** (a developer preview: pin that version) on Node 24.15, Windows 11.

## Install

1. Install reelsmith (Python 3.10+, see its README for the renderer) so that `reelsmith-mcp` is on PATH, or note
   the interpreter that has it:

   ```sh
   pip install -e .                 # in a reelsmith checkout
   ```

2. Install dsh, pinned: `npm install -g @deepseek-ai/dsh@0.2.1-rc.3` (`dsh plugin` needs `pnpm` on PATH).

3. Add the plugin to a profile (`web` for the browser UI, `headless` for one-shot tasks):

   ```sh
   dsh plugin --profile web add dsh-plugin-reelsmith                  # from npm, once published
   dsh plugin --profile web add ./dsh-plugin-reelsmith-0.1.0.tgz      # a tarball from `npm pack`
   (cd integrations/dsh && npm install && npm run build)              # or a checkout of this folder, from
   dsh plugin --profile web add ./integrations/dsh                    # the repository root
   ```

   The Web UI's **Plugins > Add plugin** accepts the same package name, tarball or folder. A plain git install is
   not supported: it arrives without the built `lib/`.

4. Restart `dsh web`. New bundles take effect at start.

## Use

Pick **Video editor** in the mode menu when you start a session, and ask for a film: "cut my clips in
`footage/` into a 60 s vertical teaser", "a 90 s explainer on tidal power with narration". To make it the default
mode, choose it in **Settings > General**, or add this to the profile's `cordis.patch.yml`:

```yaml
- id: agent-preset-registry
  config:
    default: video-editor
```

The agent gets reelsmith's tools (`mcp__reelsmith__manual`, `preview`, `edit`, `render`, `review`, ...), a prompt
section on how reelsmith works (an NLE it drives with tools and code, not text-to-video; the loop manual > notes >
project > assets > edit > preview > check > render > review; look at what you make), the reelsmith Agent Skill
when one is found, and DSH's usual file, shell, web, todo and subagent tools. In the `headless` profile (any
profile without `dsh-web-app`) the one agent gets the same tools and prompt without choosing a mode.

Relative `project` paths resolve against the session's working directory, and each working directory gets its own
reelsmith server, so the agent's file tools and reelsmith agree on what `demo/project.json` means.

## What you see

- **Conversation.** Each reelsmith call is a row with its project. Preview and review rows show the contact sheet
  (large) and the stills (small) inline: the images the model received. A delivered render plays inline. The film
  icon on a row opens the panel.
- **Video editor panel** (right sidebar; it opens by itself on the first live preview, review or render, and from
  the sidebar's **+** guide): the film player (`out/film.mp4`, seekable), the latest preview contact sheet and
  stills, the review sheet, and the timeline as reelsmith's `describe` prints it. It follows the project the
  session last touched, offers a picker when there are several, and refreshes after every reelsmith result.
  When the server cannot start it says why, with **Reconnect**.

## Settings

**Plugins > reelsmith video editor > reelsmith > Configure** edits these; they are written to the profile's
`cordis.patch.yml` and restart the server (a call in progress is stopped).

| Field | Default | Meaning |
|---|---|---|
| `python` | empty | Interpreter with reelsmith installed; runs `python -m reelsmith.mcp_server`. Empty uses `command`. |
| `command` | `reelsmith-mcp` | The server command when `python` is empty (`args` gives it arguments). |
| `workspaceRoot` | empty | `REELSMITH_ROOT` for every call; empty uses each session's working directory. A session outside the root works inside the root. |
| `fence` | `true` | Set `REELSMITH_ROOT`, so tools refuse projects and local imports outside it. |
| `profile` | empty | Output profile `new_project` gets when the agent names none. |
| `attachStills` | `4` | A preview or review with at most this many stills sends them as images too; the contact sheet always goes. |
| `timeoutMs` | `1800000` | Longest one call may take. |

YAML only: `env` (extra environment for the server, merged over DSH's scrubbed environment: credential-shaped
variables are dropped, so give reelsmith its keys through its workspace `.env` or here), `idleMinutes` (close an
idle working directory's server, default 30; a server with a call running stays), `skillDir` (where
`reelsmith/SKILL.md` lives). The server starts with `PYTHONSAFEPATH=1`, so a `json.py` or `queue.py` in the session
folder cannot shadow reelsmith's imports.

```yaml
- id: reelsmith
  config:
    python: /home/me/.venvs/reelsmith/bin/python
    profile: youtube
```

## How it works

| Piece | DSH seam |
|---|---|
| `reelsmith` row: settings, servers, panel routes | a host plugin providing the `reelsmith` service; `.volatile()` Config fields are the Plugins page form |
| Tools | `dsh-plugin-reelsmith/tools` registers each server tool through `createMcpToolDefinition` from `@deepseek-ai/dsh-mcp-client`, so results, errors and images follow DSH's MCP contract (images become durable attachments when the model takes images) |
| Images | reelsmith answers with PNG paths; for `preview`, `review`, `frames` and `scenes` the plugin adds the named contact sheets (and few stills) to the MCP result as image content, files inside the called project's `build/` only |
| Video editor mode | a `@deepseek-ai/dsh-agent-preset` row (persona, tools, skill provider, DSH's standard tool set) |
| Skill | a `@deepseek-ai/dsh-skill-filesystem` row reading `skills/reelsmith` from the packaged copy or the reelsmith checkout |
| Panel and rows | the browser half (`lib/client.js`): a `sidebarRightTabs` tab type, `tool.call.toolview` rows, a `plugins.row.config` page |
| Panel data | owner-only routes on Connection's authenticated `/api` channel: `/api/reelsmith/state`, `/api/reelsmith/file` (files of projects the session touched; byte ranges), `/api/reelsmith/reconnect` |

DSH's own `@deepseek-ai/dsh-mcp-client` row also connects reelsmith, as text only: it would not show the model the
contact sheets, and relative paths would resolve against the server's directory. To use it anyway:

```yaml
- insert:
    - id: mcp-reelsmith
      name: '@deepseek-ai/dsh-mcp-client'
      config: { serverName: reelsmith, transport: stdio, command: reelsmith-mcp, toolCallTimeoutMs: 1800000 }
```

## Development

```sh
npm install          # pins @deepseek-ai/dsh 0.2.1-rc.3 and the packages the tests load
npm test             # builds, then node:test: the plugin in a Cordis context with DSH's ToolRuntime and SystemPrompt
                     # and a fake reelsmith server, the image and file-route rules, the client bundle
npm run e2e -- --python <python with reelsmith>
                     # a throwaway dsh home: dsh plugin add, a reelsmith project, dsh --profile headless driven by
                     # DSH's scripted mock model (no key, no network); passes when the model is offered the tools,
                     # the prompt section and the skill, and its next request carries the contact sheet as an image
```

## Known limits

- DSH is a developer preview. The bundle declares `engines.dsh` `>=0.2.1-rc.3 <0.3.0`; the browser half uses Web
  client contracts (slot names and props, `sidebarRightTabs`, `connection.fetch`) typed locally because their
  packages are not a stable public API. Re-test on every dsh upgrade.
- Images reach the model only on routes that declare image input (the default `deepseek-flash` does;
  `deepseek-v4-pro` does not, and gets text placeholders). Files over 8 MB stay paths.
- The panel knows the projects reelsmith calls touched since `dsh` started; after a restart it fills again with the
  next call. Its timeline waits at most 8 s for `describe` while a render holds the server.
- Rows are registered for reelsmith's known tools and the ones the server reports when the page loads; a tool added
  later shows DSH's generic row until the page reloads.
- Tested on the Web UI and the headless profile; the desktop app and remote (non-loopback) Web hosts are untested.

MIT, Qiankang (Kant) Wang.
