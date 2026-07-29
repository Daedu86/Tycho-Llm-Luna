# Contributing

Issues and focused fixes to Tycho are welcome. Keep changes small, include a regression test, and
run `make validate` before opening a pull request.

Provider integrations should implement the transport interface exposed through `TYCHO_LLM_PLUGIN`
instead of adding provider-specific branches to actor policy, prompts, actions, or scoring. Runner
integrations should use `TYCHO_RUNNER_PLUGIN` for the same reason.
