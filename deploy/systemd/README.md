# Feishu collector on Linux

The browser OAuth bootstrap runs on a trusted local machine. The server only needs the resulting
owner-only token file and runs the non-interactive `sync` command.

## Local configuration

Do not put the App Secret in Python code. For local testing, put the values in the ignored project
file `/opt/jobpicky/.env` (or export them directly in the same terminal), then load them before
running the script:

```bash
set -a
source /opt/jobpicky/.env
set +a
uv run python scripts/feishu.py auth
```

The server does not use this local `.env`; its values belong in `/etc/jobpicky/feishu.env`.

1. Install the project at `/opt/jobpicky` and create the `jobpicky` user.
2. Create `/etc/jobpicky/feishu.env` from `feishu.env.example`; replace every placeholder and set
   its mode to `0600`.
3. Create `/var/lib/jobpicky` and `/var/cache/jobpicky`, owned by `jobpicky`.
4. Run `uv run alembic upgrade head` once against the production database.
5. On the local machine, run `uv run python scripts/feishu.py auth`, then securely copy the generated
   token file to `/var/lib/jobpicky/feishu-token.json` and set its mode to `0600`.
6. Install the two unit files under `/etc/systemd/system/`, then run:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl start jobpicky-feishu.service
   sudo systemctl enable --now jobpicky-feishu.timer
   sudo journalctl -u jobpicky-feishu.service -n 100 --no-pager
   ```

The collector refreshes and atomically replaces the rotating token file when necessary. If the
refresh token is revoked or expires, run the local `auth` bootstrap again and copy the new file.
