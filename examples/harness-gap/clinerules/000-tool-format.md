<!--
This is an EXPERIMENT SPECIMEN, not an active harness for this repo.

It is the `.clinerules/000-tool-format.md` file used in Clinescope's harness-gap A/B
experiment (see docs/harness-gap.md). The idea it tests, that a short rules file can lift a
weak model onto the tool path an eval grades, came from Cline community feedback.

To USE it, copy this file into a Cline workspace at `.clinerules/000-tool-format.md` (or
`.cline/rules/000-tool-format.md`). It loads first because rules are sorted by name.
-->

# Tool use and patch format

You edit files by calling the `apply_patch` tool. Never answer with code in prose. If you
output code without calling a tool, the task is NOT done.

## The apply_patch format

Every patch is wrapped in these sentinels, on their own lines:

```
*** Begin Patch
*** End Patch
```

Inside, use one action header per file (keep the trailing colon and space exactly):

- `*** Add File: path/to/new_file.py` for a new file. Every content line starts with `+`.
- `*** Update File: path/to/existing.py` to change an existing file. Use `@@` to mark a
  section, then content lines. Each content line starts with a single character: a space for
  an unchanged context line, `-` to remove a line, `+` to add a line.
- `*** Delete File: path/to/old.py` to remove a file.

A correct patch that adds a function to an existing file looks exactly like this:

```
*** Begin Patch
*** Update File: calc.py
@@
 def add(a, b):
     return a + b
+
+def sub(a, b):
+    return a - b
*** End Patch
```

## Edit quality

Change only the lines that change. Keep the surrounding lines as unchanged context (a leading
space) so the patch has an anchor. Do not delete a whole block of three or more lines just to
retype it; edit the specific lines instead.

## After you edit

After every `apply_patch`, verify the file actually changed (read it back or list it). If the
apply failed, do not move on: run `apply_patch` again on the same file until it succeeds.
