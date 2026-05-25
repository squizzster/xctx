# AGENTS.md

This agent has full control to create, edit, organize, manage work, and initialize a local git repository with any suitable name inside 
 `/home/EdgarTools/workflow/xctx_v4_2`
which is the current directory ./

All tasks, files, temporary directories, repositories, and outputs should stay within this workspace so the project remains self-contained.
You are free to experiment, innovate, intuit within this space so that your output is something you are always proud to share.

Only modify the main code after we have agreed on that. Otherwise, use the
  ./experiments_tmp/<random_32_char_hex_string>/ space...
  ./experiments_tmp/`openssl rand -hex 16`>/ space...

## Project direction: live development, no backward-compatibility burden

This repository is a live, local, pre-release/protocol-evolution codebase. It is
not deployed as a public compatibility target. Do not preserve old behavior, old
command names, old aliases, old file names, or compatibility wrappers merely
because they existed before.

Default stance for every change:

- Prefer the clean current protocol over backward compatibility.
- Remove relic code instead of hiding it behind shims.
- Replace confusing obsolete names with precise current names.
- Delete old aliases unless a user explicitly asks to keep one.
- Make tests enforce the desired contract, not historical behavior.
- Treat stale docs, stale command hints, and old vocabulary as bugs.
- Do not add deprecation layers unless there is an explicit release/user-data
  migration requirement.
- Treat local skills, reports, and validation notes as development aids that may
  lag current code; reconcile them to the current code, tests, and YAML instead
  of treating stale guidance as authoritative.

For xctx specifically:

- The current root command set is exactly `discover`, `observe`, `plan`,
  `execute`, `audit`, and `repair`.
- `other` is a hidden extension lane, not an advertised command.
- Relic root commands such as `status`, `identify`, `doctor`, and `write`
  should stay removed unless the protocol is deliberately redesigned.
- There is no implicit domain selector. Commands must use explicit scoped
  domain references when a domain matters.
- Domain-specific behavior belongs in scoped YAML and adapter-side code, not in
  generic `libs/xctx` protocol runtime.

If a future change appears to require compatibility with old behavior, stop and
make that requirement explicit. In the absence of that explicit requirement,
choose the cleaner design and remove the obsolete path.
