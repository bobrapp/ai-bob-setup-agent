# Contributing to ai-bob-setup-agent

Thank you for your interest in contributing! This project is open source under the MIT licence — everyone is welcome to use it, learn from it, and improve it.

## Ways to contribute

- **Report bugs** — open a [bug report issue](https://github.com/bobrapp/ai-bob-setup-agent/issues/new?template=bug_report.md).
- **Suggest features** — open a [feature request issue](https://github.com/bobrapp/ai-bob-setup-agent/issues/new?template=feature_request.md).
- **Fix bugs / add features** — submit a pull request (see workflow below).
- **Improve docs** — typo fixes, clearer explanations, translated guides are all valuable.

## Development workflow

1. **Fork** the repository and clone your fork.
2. Create a feature branch:
   ```bash
   git checkout -b feat/your-feature-name
   ```
3. Install dependencies:
   ```bash
   make install
   ```
4. Make your changes. Keep commits small and focused.
5. Run the test suite and environment check:
   ```bash
   make test
   make doctor
   ```
6. Push to your fork and open a pull request against `main`.

## Pull request guidelines

- Fill in the PR template completely.
- Reference any related issues (`Closes #123`).
- Keep PRs focused — one logical change per PR.
- All CI checks must pass before merge.
- At least one maintainer review is required.

## Code style

- Python: follow PEP 8, use type hints, add docstrings to public functions.
- Shell scripts: use `set -euo pipefail`, quote all variables.
- HTML/CSS: match the existing style; prefer semantic elements.

## Commit messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) format:

```
feat: add Telegram meta-agent provisioning
fix: handle missing .env gracefully
docs: clarify quick-start steps
```

## Code of Conduct

This project follows the [Contributor Covenant](./CODE_OF_CONDUCT.md). By participating you agree to abide by its terms.

## Security

Please **do not** open public issues for security vulnerabilities. See [SECURITY.md](./SECURITY.md) for responsible-disclosure instructions.
