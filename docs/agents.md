# reelsmith with coding agents

reelsmith's MCP server is the way in for every coding agent: the agent edits, previews and renders through the same
tools a person uses from the CLI. `reelsmith setup <agent>` writes the server into the agent's own config and
installs the reelsmith skill where that agent loads skills; `reelsmith run --engine <agent>` lets an agent make a
film headless. The full contract of the tools is [manual.md](manual.md); the platform reference is
[editor-spec.md](editor-spec.md) (setup and transports in section 10, the runner in section 11).

## reelsmith setup

```sh
reelsmith setup claude-code            # or codex, dsh, cursor, generic
reelsmith setup codex --print          # show exactly what would be written, write nothing
reelsmith setup cursor --user          # the agent's user-level config instead of this folder's
reelsmith setup claude-code --root ~/studio     # the tools refuse projects outside ~/studio
reelsmith setup dsh --uninstall        # take out what setup added
```

| target | MCP server: this folder (default) | MCP server: `--user` | skill: this folder / `--user` |
|---|---|---|---|
| `claude-code` | `.mcp.json` | `claude mcp add-json --scope user` (`~/.claude.json`) | `.claude/skills/reelsmith/` / `~/.claude/skills/reelsmith/` |
| `codex` | `.codex/config.toml` | `$CODEX_HOME/config.toml` (`~/.codex`) | `.agents/skills/reelsmith/` / `~/.agents/skills/reelsmith/` |
| `dsh` | `.dsh/reelsmith.cordis.yml`, passed with `--patch` | `$DSH_HOME/cordis.patch.yml` (`~/.dsh`) | `<git root>/.dsh/skills/reelsmith/` / `$DSH_HOME/skills/reelsmith/` |
| `cursor` | `.cursor/mcp.json` | `~/.cursor/mcp.json` | `.cursor/skills/reelsmith/` / `~/.cursor/skills/reelsmith/` |
| `generic` | printed | printed | printed |

The server is the Python that ran setup, by absolute path, running `-m reelsmith.mcp_server`, so it works without
`reelsmith-mcp` on `PATH`; run setup again after moving or recreating that environment. Config files are merged:
other servers, keys and comments stay, a second run changes nothing, and a file setup cannot parse is left alone
with an error. The installed skill is a copy: run setup again after upgrading reelsmith.

## The skill

`skills/reelsmith/SKILL.md` (the Agent Skills format) tells an agent what reelsmith is (an editor it drives, not a
text-to-video model), when to use it (any request to make or edit a video), the working loop (manual, notes, new
project, assets, edit, preview, check, render, review) and the rules that save a render. It is short on purpose and
sends the agent to the `manual` tool for the contract.

## Claude Code

- **Plugin:** `/plugin marketplace add wangkant/reelsmith`, then `/plugin install reelsmith@reelsmith`. The plugin
  brings the skill and runs `reelsmith-mcp` from `PATH`, so install reelsmith into an environment on `PATH` first.
- **Or setup:** `reelsmith setup claude-code` in the folder you run Claude Code in. It asks once to approve the
  project's `.mcp.json` servers.
- `render` can run for many minutes in one call: raise `MCP_TOOL_TIMEOUT` (milliseconds) if its calls time out.
- **Headless:** `claude -p "Make a 60-second film about ..."` in a set-up folder, or `reelsmith run <project>
  --engine agent-sdk` (a Claude Agent SDK session that needs no setup).

## Codex

- `reelsmith setup codex` writes `[mcp_servers.reelsmith]` with `tool_timeout_sec = 3600` (render is long) and
  `startup_timeout_sec = 60`, and lists the variables the tools read (OpenRouter key, proxies, Codex location) in
  `env_vars`, Codex's allowlist for what reaches a server's environment. Codex reads a project's
  `.codex/config.toml` only once the project is trusted; `--user` sets it up for every project.
- The skill goes to `.agents/skills/`, where Codex looks for skills; mention it as `$reelsmith` or let it trigger.
- **Headless:** `reelsmith run <project> --engine codex` drives `codex exec` with the server injected and no setup
  needed (section 11 of the spec), or run `codex exec "..."` yourself in a set-up project.

## DeepSeek Harness

- `reelsmith setup dsh` writes a patch overlay that mounts the server through `@deepseek-ai/dsh-mcp-client` (with
  a one-hour `toolCallTimeoutMs`; DSH's default of 60 s would cut a render) and the skill. DSH has no per-project MCP
  config: start it with `dsh --patch .dsh/reelsmith.cordis.yml web`, or use `--user` to add the rows to
  `$DSH_HOME/cordis.patch.yml` for every profile.
- DSH drops variables named like `*KEY*`, `*TOKEN*`, `*SECRET*` or `*PASSWORD*` from an MCP server's
  environment: keep provider keys in the workspace `.env`, where the tools read them.
- The reelsmith DSH plugin package (`integrations/dsh`) is the richer option when it fits your setup.
- **Headless:** `reelsmith run <project> --engine dsh` drives `dsh --profile headless` with its own DSH home and the
  server attached; it needs `DEEPSEEK_API_KEY`.

## Cursor

- `reelsmith setup cursor` writes `.cursor/mcp.json` and `.cursor/skills/reelsmith/` (`--user`: `~/.cursor`).
  Cursor also reads `.claude/skills` and `.agents/skills`, so a folder set up for another agent works as well.
- **Headless:** Cursor's CLI (`agent -p`) uses the same MCP config as the editor.

## Any other MCP client

- `reelsmith setup generic` prints an instructions block to paste into the agent's instructions file, the server
  as `mcpServers` JSON and where the skill lives. It writes nothing.
- **stdio:** `python -m reelsmith.mcp_server`, `reelsmith mcp` or `reelsmith-mcp`.
- **HTTP:** `reelsmith mcp --http` serves streamable HTTP at `http://127.0.0.1:8765/mcp` (`--host`, `--port`). It
  binds loopback addresses only; `--allow-remote` takes any address and needs a bearer token of at least 16
  characters in `REELSMITH_MCP_TOKEN` (or the variable `--token-env` names), which clients send as
  `Authorization: Bearer <token>`, and `--root <folder>` (or `REELSMITH_ROOT`) to fence the projects remote callers
  reach. It is plain HTTP: put a remote bind behind TLS (a reverse proxy) on a network you trust. While the token
  variable is set, loopback requests need the token too.

## Headless runs

`reelsmith run <project> --brief "..."` makes one film with no client attached, on one of four engines: `api`
(reelsmith's own loop over an OpenAI-compatible API, the default), `agent-sdk` (a Claude Agent SDK session), `codex`
(`codex exec`) and `dsh` (DeepSeek Harness headless). All four get the same role, delivery checks and fix-up
sessions, and an interrupted run resumes its own session. Section 11 of [editor-spec.md](editor-spec.md) has the
settings, the fences each engine runs inside and how spend is counted.
