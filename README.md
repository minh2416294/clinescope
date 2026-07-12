# Clinescope

[![CI](https://github.com/minh2416294/clinescope/actions/workflows/ci.yml/badge.svg)](https://github.com/minh2416294/clinescope/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)

Clinescope is an AI evaluation tool that lives in your Cline development workflow, reads your logs, and helps you write better prompts by checking tool choices, catching messy code rewrites, and ensuring updates don't break past work.

Clinescope reads a Cline log and scores four things:

- **`tool_selection`**: did the agent call the tools the task needed?
- **`diff_coherence`**: are its code patches valid and well-formed?
- **`diff_minimality`**: are its edits small and focused, not bloated rewrites?
- **`apply_recovery`**: when a patch failed, did the agent fix it?

> Clinescope is an independent, unofficial tool - not affiliated with, endorsed by, or sponsored by Cline or Cline Bot Inc. "Cline" is a trademark of Cline Bot Inc., used only to describe compatibility.

<p align="center"><img src="docs/demo.png" alt="clinescope scoring a failing Cline run and, with --advice, coaching how to fix the agent's prompt for each failing scorer" width="640"></p>

## Get started

1. **Install Clinescope**

    Requires Python 3.11+. Installing into a virtual environment is recommended.

    ```bash
    pip install "git+https://github.com/minh2416294/clinescope.git"
    ```

2. **Use Clinescope**

    **Get the score:**
  
    Point Clinescope at the Cline log file to score the run:
    ```bash
    clinescope path/to/messages.json --expected read_files apply_patch
    ```
    After `--expected`, list the tools you think the task needed. Clinescope checks whether the agent actually used them and scores the rest of the run automatically. Not sure which tool names to use? Run `clinescope --list-tools` to print the ones Clinescope knows.

    **Get full breakdown of every scorer:**
    ```bash
    clinescope path/to/messages.json --expected read_files apply_patch --verbose
    ```

    **Get advice to improve prompting:**
    ```bash
    clinescope path/to/messages.json --expected read_files apply_patch --advice
    ```

## Contributing

Small, discussed-first changes are welcome - see [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, tests, and what a scorer change needs.

## License

[Apache-2.0](LICENSE). Copyright 2026 Tran Binh Minh.
