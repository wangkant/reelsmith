#!/usr/bin/env node
// At pack time, ship the repository's reelsmith Agent Skill (skills/reelsmith) inside the npm package.
import { cpSync, existsSync, rmSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const pkg = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = resolve(pkg, '..', '..', 'skills', 'reelsmith')
const target = join(pkg, 'skills', 'reelsmith')
rmSync(join(pkg, 'skills'), { recursive: true, force: true })
if (existsSync(join(source, 'SKILL.md'))) {
  cpSync(source, target, { recursive: true })
  console.log(`packed the reelsmith skill from ${source}`)
} else {
  console.log(`no skill at ${source}; the package ships without one`)
}
