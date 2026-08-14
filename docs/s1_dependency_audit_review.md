# S1 Frontend Dependency Audit Review

Review date: 2026-08-14

## Result

`npm audit --json` now reports zero vulnerabilities for `frontend/`.

## Findings reviewed

| Package | Before | Reachability | Decision |
|---|---:|---|---|
| `next` | high, direct | Runtime framework and production build path | Upgraded directly to `16.3.1` |
| `postcss` | high/moderate, direct and transitive | Build tooling and CSS processing; not user-input runtime parsing in S1, but direct dependency | Upgraded directly to `8.5.26` |
| `sharp` | high, transitive through Next | Image optimization path; reachable if image optimization is enabled | Resolved by `next@16.3.1` |
| `nanoid` | high, transitive through PostCSS | Build tooling path | Resolved by `postcss@8.5.26` |
| `js-yaml` | high, transitive through ESLint config tooling | Dev-only lint/config parsing | Overrode to patched `4.3.1` |
| `brace-expansion` | high, transitive through minimatch/ESLint tooling | Dev-only glob expansion | Overrode vulnerable minimatch children to patched `1.1.18` and `5.0.9` |

## Notes

This was not an `npm audit fix` run. The remediation was targeted:

- direct runtime/build packages were upgraded explicitly,
- dev-only transitive utilities were patched with scoped `overrides`,
- `package-lock.json` was refreshed for reproducible installs.

Validation after remediation:

```bash
npm audit --json
npm test -- --run
npm run build
npm run e2e:s1:fixture
```
