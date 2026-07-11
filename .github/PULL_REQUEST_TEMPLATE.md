<!-- See CONTRIBUTING.md for dev setup, tests, and what a scorer change needs. -->

## Summary

<!-- What does this change and why? -->

## Linked issue

<!-- Closes #... — open an issue first for anything larger than a bug/doc fix. -->

## How verified

<!-- The command you ran and what it returned (e.g. `pytest -q`, and a `clinescope <trace>` run). -->

## Checklist

- [ ] Tests + linters pass (`pytest -q`, `ruff check .`, `ruff format --check .`, `mypy src`)
- [ ] A scorer change adds a trace + its expected score (see CONTRIBUTING.md)
- [ ] Cline's golden fixture was not modified or copied in
