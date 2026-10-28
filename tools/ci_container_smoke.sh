#!/usr/bin/env bash
# Disposable GitHub runner only. No registry push, cloud token or production access.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${CI_SANDBOX:-}" == issue4 ]] || {
  echo "Refusing to run outside the explicit Issue #4 CI sandbox" >&2
  exit 1
}
mkdir -p ci-evidence
cleanup() {
  docker logs issue4-candidate > ci-evidence/candidate.log 2>&1 || true
  docker logs issue4-rollback > ci-evidence/rollback.log 2>&1 || true
  docker rm -f issue4-candidate issue4-rollback issue4-mysql >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker run -d --name issue4-mysql --network host \
  -e MYSQL_ROOT_PASSWORD=ci-only-mysql-password mysql:8.0 \
  --default-authentication-plugin=mysql_native_password
for attempt in {1..60}; do
  if docker exec issue4-mysql mysqladmin ping -h127.0.0.1 \
      -pci-only-mysql-password --silent >/dev/null 2>&1; then break; fi
  sleep 2
done
docker exec issue4-mysql mysqladmin ping -h127.0.0.1 -pci-only-mysql-password --silent
for scenario in empty legacy duplicates; do
  DATABASE_URL="mysql+pymysql://root:ci-only-mysql-password@127.0.0.1:3306/scentrise_ci_$scenario" \
    python tools/ci_mysql_baseline.py | tee "ci-evidence/mysql-$scenario.txt"
done
docker build --progress=plain -t issue4-candidate .
rollback_context="$(mktemp -d)"
git archive 6609c38561661bf8607c4461c346229e4007022e | tar -x -C "$rollback_context"
docker build --progress=plain -t issue4-rollback "$rollback_context"
docker image inspect issue4-candidate issue4-rollback \
  --format '{{.RepoTags}} local-image-id={{.Id}}' > ci-evidence/container-images.txt
for role in candidate rollback; do
  docker run -d --name "issue4-$role" --network host \
    -e DATABASE_URL=mysql+pymysql://root:ci-only-mysql-password@127.0.0.1:3306/scentrise_ci_legacy \
    -e JWT_SECRET=issue4-ci-only-secret-over-thirty-two-bytes \
    -e AUTO_CREATE_DATABASE=0 -e AUTO_CREATE_TABLES=0 -e PORT=8080 \
    "issue4-$role"
  python - <<'PY'
import time
import urllib.request
for attempt in range(60):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/readyz", timeout=2) as response:
            assert response.status == 200
        break
    except Exception:
        if attempt == 59:
            raise
        time.sleep(1)
for path in ("/healthz", "/readyz", "/admin/", "/admin/static/app.js",
             "/api/categories", "/api/products", "/api/articles"):
    with urllib.request.urlopen("http://127.0.0.1:8080" + path, timeout=5) as response:
        assert response.status == 200, path
    print("PASS", path)
PY
  [[ "$(docker exec "issue4-$role" id -u)" == 10001 ]]
  docker top "issue4-$role" -eo args | grep -q gunicorn
  echo "PASS $role: Gunicorn + UID 10001 + 8080 + migrated synthetic MySQL" \
    | tee "ci-evidence/$role.txt"
  docker logs "issue4-$role" > "ci-evidence/$role.log" 2>&1
  docker rm -f "issue4-$role"
done
echo "Rollback smoke uses a rebuild of source 6609c38, NOT the archived production image." \
  | tee ci-evidence/limitations.txt
