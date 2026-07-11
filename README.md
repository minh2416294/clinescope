# Clinescope

[![CI](https://github.com/minh2416294/clinescope/actions/workflows/ci.yml/badge.svg)](https://github.com/minh2416294/clinescope/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)

Clinescope is an AI evaluation tool that lives in your development workflow, reads your Cline logs, and helps you ship better prompts by checking tool choices, catching messy block rewrites, and ensuring updates don't break past work.

Clinescope scores four things from the log: whether the agent used the right tools, whether its edits were clean, whether they were small and focused, and whether it recovered from failed edits. Optionally, it also checks its own AI judge against human ratings.

> Clinescope is an independent, unofficial tool - not affiliated with, endorsed by, or sponsored by Cline or Cline Bot Inc. "Cline" is a trademark of Cline Bot Inc., used only to describe compatibility.

<p align="center"><img src="docs/demo.gif" alt="clinescope scoring a Cline trace" width="800"></p>


## Get started

Requires Python 3.11+. Installing into a virtual environment is recommended.

```bash
pip install "git+https://github.com/minh2416294/clinescope.git"
```

Every time Cline finishes a task, it saves a log of what it did (a `messages.json` file). Point Clinescope at that file to score the run:

```bash
clinescope path/to/messages.json --expected read_files apply_patch
```

After `--expected`, list the tools you think the task needed (here: read a file, then edit it). Clinescope checks whether the agent actually used them and scores the rest of the run automatically. It reads the log only, and never changes your files.

## Contributing

Small, discussed-first changes are welcome - see [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, tests, and what a scorer change needs.

## License

[Apache-2.0](LICENSE). Copyright 2026 Tran Binh Minh.
