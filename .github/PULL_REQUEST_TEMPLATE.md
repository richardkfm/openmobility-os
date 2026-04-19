## Summary

<!-- What does this PR do? One paragraph is fine. -->

## Type of change

- [ ] Bug fix
- [ ] New feature / connector / measure rule
- [ ] Refactor or cleanup
- [ ] Documentation
- [ ] CI / infrastructure

## Checklist (CLAUDE.md governance)

- [ ] I have read [CLAUDE.md](../CLAUDE.md) and my changes comply with all core principles
- [ ] `CHANGELOG.md` has a new entry under `[Unreleased]`
- [ ] `README.md` is updated if user-facing behavior changed
- [ ] `VERSION` is bumped if warranted (see versioning policy in CLAUDE.md)
- [ ] No logic is hard-wired to a specific city, country, or language
- [ ] All new user-facing strings use `gettext` / `{% trans %}`
- [ ] `docker compose up --build` runs cleanly and core flows work
- [ ] `python manage.py test` passes

## Testing notes

<!-- How did you verify this? Manual steps, edge cases checked, test fixtures added. -->

## Related issues

<!-- Closes #... -->
