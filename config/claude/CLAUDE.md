# Global Claude Code Guidelines

## Skills

Always load the relevant skill before starting work. Skills provide critical guidelines and patterns — use them proactively, don't wait to be asked.

- `/php-guidelines-from-spatie` — Any PHP/Laravel code (writing, reviewing, refactoring)
- `/frontend-design` — UI design, styling, visual components, layouts
- `/web-design-guidelines` — Reviewing UI, checking accessibility, auditing UX
- `/simplify` — After writing or changing code, review for quality and efficiency

### Code Intelligence

Prefer LSP over Grep/Glob/Read for code navigation:
- `goToDefinition` / `goToImplementation` to jump to source
- `findReferences` to see all usages across the codebase
- `workspaceSymbol` to find where something is defined
- `documentSymbol` to list all symbols in a file
- `hover` for type info without reading the file
- `incomingCalls` / `outgoingCalls` for call hierarchy

Before renaming or changing a function signature, use
`findReferences` to find all call sites first.

Use Grep/Glob only for text/pattern searches (comments,
strings, config values) where LSP doesn't help.

After writing or editing code, check LSP diagnostics before
moving on. Fix any type errors or missing imports immediately.
