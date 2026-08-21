# ScentRise WeChat backend

Flask backend for the ScentRise mini-program and administration console. The
admin console is served at `/admin/`; health probes are `/healthz` and
`/readyz`.

## Required configuration

No credentials or cloud identifiers have source-code defaults. Configure these
as secret/environment variables in WeChat CloudBase:

| Variable | Required | Purpose |
| --- | --- | --- |
| `JWT_SECRET` | yes | Long random admin-session signing secret |
| `DATABASE_URL` | one database option | Full SQLAlchemy URL |
| `MYSQL_USERNAME` | if no `DATABASE_URL` | MySQL username |
| `MYSQL_PASSWORD` | if no `DATABASE_URL` | MySQL password |
| `MYSQL_ADDRESS` | if no `DATABASE_URL` | `host:port` |
| `MYSQL_DBNAME` | no | Defaults to `scentrise` |
| `TCB_ENV_ID` | for uploads | CloudBase environment ID |
| `CDN_BASE` | for uploads | HTTPS object-storage CDN base URL |
| `WECHAT_ACCESS_TOKEN` | one upload auth option | Existing WeChat access token |
| `WECHAT_APPID` / `WECHAT_APPSECRET` | one upload auth option | Token retrieval credentials |
| `REQUESTS_CA_BUNDLE` | no | Custom CA bundle path; TLS verification stays enabled |
| `PORT` | no | Container port, defaults to `8080` |

Optional safety limits: `JWT_EXP_HOURS` (8), `MAX_CONTENT_LENGTH` (12 MiB),
`MAX_IMAGE_BYTES` (10 MiB), and `MAX_IMPORT_ROWS` (5000).

Do not enable `AUTO_CREATE_DATABASE` or `AUTO_CREATE_TABLES` in production.

## Local development and tests

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
export TESTING=1
export DATABASE_URL=sqlite:///local.db
export JWT_SECRET="replace-with-a-long-random-test-secret"
export AUTO_CREATE_TABLES=1
pytest -q
flask --app wxcloudrun run --port 8080
```

An administrator is never created automatically. For an intentional first-time
setup, run the migration and then use the guarded utility:

```bash
flask --app wxcloudrun db upgrade
ALLOW_ADMIN_SEED=1 INITIAL_ADMIN_USERNAME=admin \
INITIAL_ADMIN_PASSWORD='a-unique-strong-password' python seed_admin.py
```

The password must contain 12–72 characters and is never printed. Rotate the
currently deployed default password before exposing a new release.

## Product import contract

The administration console accepts these equivalent headers:

- name: `产品名称`, `名称`, `productName`
- model: `产品型号`, `型号`, `productModel`
- series: `产品系列`, `productSeries`
- description: `产品简介`, `产品描述`, `productDesc`
- optional English name: `英文名称`, `productEnglishName`

The first worksheet row is always treated as the header and data starts on row
two. Import is a two-step operation. `/api/admin/import/preflight` validates the
file, reports create/update/no-change counts, and returns a plan hash. Invalid
rows are reported and skipped while all other eligible rows still commit in one
transaction. For duplicate models inside the workbook, the administrator can
either use the last row or skip every row for that duplicate model. For models
already in the database, the administrator can update them or skip them; either
choice still imports the remaining eligible rows. Empty English-name/description
cells do not overwrite existing values by default, and blank tag cells preserve
existing usage tags. The database primary key is the numeric `id`; product model
is the globally unique business key used to match imports.

## Production rollout

1. Back up MySQL and inspect duplicate category names.
2. Configure all required secret variables and set the service container port
   to `8080`.
3. Run `flask --app wxcloudrun db upgrade` against the target database.
4. Build and deploy the Docker image. Gunicorn runs as an unprivileged user.
5. Verify `/healthz`, `/readyz`, public down/draft visibility, admin login,
   import preflight, and a small controlled import before the full workbook.
6. Rotate the admin password and `JWT_SECRET` if either legacy default was ever
   used.

`schema.sql` is only a non-destructive new-install bootstrap. Existing databases
must use migrations; it never drops tables or inserts users/data.
