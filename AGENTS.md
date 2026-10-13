# Agent Guidance

For tasks that investigate, debug, review, test, or modify this robot's runtime, Python perception, camera/streaming, City/Race modes, configuration, Arduino communication, or firmware:

1. Read and follow [Self-Driving Robot Engineering Skill](.agents/skills/self-driving-robot-engineering/SKILL.md).
2. Read the relevant reference files linked by that skill before making cross-module changes.
3. Treat source code, tests, configuration files, and workflow definitions on the checked-out commit as authoritative. Historical reports are investigation leads, not proof of current behavior.
4. Before editing, inspect the current branch, HEAD, working tree, and diff. Preserve unrelated user changes. Never reset, clean, or discard work to make tests pass.
5. Prefer hardware-free tests and deterministic fakes. Do not initiate real motor movement or perform a hardware test unless the user explicitly requests it.
6. Report exactly which tests and commands were run, which were not run, and what remains unverified.
