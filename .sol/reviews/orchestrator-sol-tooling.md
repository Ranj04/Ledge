# Orchestrator note — how Sol is invoked on this machine, and why

**Date:** 2026-09-10. **Decided by:** Ranjiv, on the orchestrator's escalation.

## The constraint

Codex CLI 0.154.0 on Windows 11 has **no sandbox implementation**. It sandboxes with
Seatbelt on macOS and Landlock on Linux; on Windows it has neither, and rather than
running unsandboxed it refuses every write and every shell command. Measured:

```
$ codex exec -m gpt-5.6-sol --sandbox workspace-write "Create probe.txt ..."
Unable to create `probe.txt`: the workspace is read-only and write approval is disabled.

$ codex exec -m gpt-5.6-sol --sandbox read-only "print the contents of readable.txt"
exec_command failed: CreateProcess { message: "Rejected(\"`cmd.exe /c 'type readable.txt'`
rejected: blocked by policy\")" }
```

Tried and did not help: `--sandbox workspace-write`, `-c sandbox_mode="workspace-write"`,
`--ignore-rules`, running inside a git repo versus outside one. There is no
`~/.codex/config.toml` on this machine, so no user config is responsible.

`wsl.exe` is present and WSL2 is the default version, but **no distro is installed**
(`wsl --list --quiet` returns empty), so the Linux-sandbox route was not available
without a distro install and probable reboot.

**What did work unchanged:** `--output-schema` with `-o`. The findings-JSON mechanism the
protocol depends on was verified end to end against a scratch schema before any of this
was decided. Sol's *reasoning and structured output* were never in question — only its
tools.

## The decision

**Sol is invoked with `--dangerously-bypass-approvals-and-sandbox`.**

Codex's own help describes that flag as "intended solely for running in environments that
are externally sandboxed". This environment is not externally sandboxed in the OS sense.
What contains it instead is the protocol itself: every track runs on its own branch, the
tree was clean and committed before any agent ran, ownership is disjoint by directory, and
the orchestrator reviews every diff before it merges. That is containment by git, not by
kernel, and it should be described that way rather than dressed up.

Two alternatives were put to Ranjiv and declined:

- **Fable builds every track, Sol reviews every track.** Would have preserved the single
  property that matters most — no model reviews its own work — at zero added risk, at the
  cost of Sol filing `failure_scenario` findings rather than committing failing tests.
- **Install a WSL distro.** Safest, slowest.

Ranjiv chose the bypass flag explicitly, so the role table in `MemoryLedger-EXECUTE.md`
§3 stands unchanged: Sol builds tracks A, C and P, and reviews T0, B, Q and the solo
stages.

## What this changes for anyone reading the results later

Nothing about the measurements. Sol's sandbox has no bearing on what the cache simulator
computes or what the ablation harness reports. It bears only on *how the work was
produced*, which is exactly why it is written down here rather than left implicit.

The invocation used throughout is:

```bash
codex exec -m gpt-5.6-sol --dangerously-bypass-approvals-and-sandbox \
  [--output-schema <schema>] [-o <findings.json>] "$(cat <prompt>)" < /dev/null
```

`< /dev/null` matters: `codex exec` otherwise blocks reading additional input from stdin.
