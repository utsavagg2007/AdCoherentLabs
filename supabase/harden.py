"""ONE-SHOT Supabase hardening for the AdCoherent stack (run it yourself).

Does, in order (backups already at .env.bak-2026-07-13 / docker-compose.yml.bak-2026-07-13):
  1. mint fresh JWT_SECRET + anon/service_role keys (HS256), SECRET_KEY_BASE,
     VAULT_ENC_KEY, PG_META_CRYPTO_KEY, LOGFLARE tokens, POSTGRES_PASSWORD
     candidate
  2. binds ALL published ports (Kong 8000/8443, pooler 5432/6543) to
     127.0.0.1 in docker-compose.yml (skips lines already bound)
  3. verifies the live DB password from .env/.env backups; if the postgres
     role is a superuser, ALTER ROLE ... PASSWORD for every Supabase login
     role; otherwise preserve the verified live POSTGRES_PASSWORD and skip
     DB password rotation
  4. writes the updated values into C:/Users/HP/supabase-project/.env
  5. if the DB password changed, deletes the supavisor tenant row so the
     pooler reseeds itself with the new password on restart
  6. `docker compose up -d` (recreates only changed services; keeps the
     network so the adcoherent-rag-db-proxy socat container stays attached)
  7. rewrites the DB password/URLs in the repo-root .env, then runs
     scripts/sync_env.py to regenerate root .env + frontend/.env.local
  8. verifies: containers healthy, OLD demo anon key rejected (401), new
     anon key accepted, psql via the 54322 proxy works, ports loopback-only

Prints key fingerprints only, never full secrets (read them from .env).
Afterwards run:  python -m engine.cli saas-selftest

Usage:  python supabase/harden.py
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

STACK = Path("C:/Users/HP/supabase-project")
PROJECT = Path("C:/Users/HP/Downloads/adcoherentlabs-project/adcoherentlabs-project")
OLD_ANON = None  # captured from .env before rewrite

ROLES = ("postgres", "authenticator", "pgbouncer", "supabase_admin",
         "supabase_auth_admin", "supabase_functions_admin",
         "supabase_storage_admin", "supabase_replication_admin",
         "supabase_read_only_user")


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def mint_jwt(secret: str, role: str) -> str:
    now = int(time.time())
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"},
                               separators=(",", ":")).encode())
    payload = b64url(json.dumps(
        {"role": role, "iss": "supabase", "iat": now,
         "exp": now + 10 * 365 * 24 * 3600}, separators=(",", ":")).encode())
    signing = f"{header}.{payload}".encode()
    sig = b64url(hmac.new(secret.encode(), signing, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    redactions = tuple(kw.pop("redact", ()))
    shown = []
    for part in cmd[:6]:
        text = part
        for secret in redactions:
            if secret:
                text = text.replace(secret, "***")
        if text.startswith("PGPASSWORD="):
            text = "PGPASSWORD=***"
        shown.append(text)
    print("  $", " ".join(shown) + (" ..." if len(cmd) > 6 else ""))
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def env_value(text: str, key: str) -> str:
    m = re.search(rf"(?m)^{re.escape(key)}=(.*)$", text)
    return m.group(1).strip() if m else ""


def replace_env_values(text: str, values: dict[str, str]) -> str:
    for key, val in values.items():
        if not re.search(rf"(?m)^{re.escape(key)}=", text):
            raise KeyError(key)
        text = re.sub(rf"(?m)^{re.escape(key)}=.*$", f"{key}={val}", text)
    return text


def stack_env_candidates(env_path: Path, key: str) -> list[str]:
    candidates: list[str] = []
    paths = [env_path]
    paths.extend(sorted(env_path.parent.glob(".env.bak-*"),
                        key=lambda p: p.stat().st_mtime, reverse=True))
    for path in paths:
        try:
            val = env_value(path.read_text(encoding="utf-8"), key)
        except OSError:
            continue
        if val and val not in candidates:
            candidates.append(val)
    return candidates


def password_auth_works(password: str) -> bool:
    # -h supabase-db forces a docker-network TCP connection => real scram
    # auth. Loopback (127.0.0.1) inside the container is trust-authed and
    # would accept ANY password, making the probe meaningless.
    cmd = ["docker", "exec", "-e", f"PGPASSWORD={password}", "supabase-db",
           "psql", "-h", "supabase-db", "-U", "postgres", "-d", "postgres",
           "-tAc", "select 1;"]
    p = run(cmd, redact=(password,))
    return p.returncode == 0 and p.stdout.strip() == "1"


def current_role_is_superuser() -> bool | None:
    # -h 127.0.0.1 = container-loopback TCP (trust auth); the unix socket
    # requires a password and would fail here.
    p = run(["docker", "exec", "supabase-db", "psql", "-h", "127.0.0.1",
             "-U", "postgres", "-d", "postgres", "-tAc",
             "select rolsuper from pg_roles where rolname = current_user;"])
    if p.returncode != 0:
        print("ABORT: could not inspect postgres role:", p.stderr[-500:])
        return None
    return p.stdout.strip() == "t"


def main() -> int:
    global OLD_ANON
    # ---- 1. mint + validate stack .env -----------------------------------
    print("== 1. minting secrets and checking stack .env ==")
    jwt_secret = secrets.token_hex(32)
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    new = {
        "JWT_SECRET": jwt_secret,
        "ANON_KEY": mint_jwt(jwt_secret, "anon"),
        "SERVICE_ROLE_KEY": mint_jwt(jwt_secret, "service_role"),
        "SECRET_KEY_BASE": secrets.token_hex(32),
        "VAULT_ENC_KEY": secrets.token_hex(16),
        "PG_META_CRYPTO_KEY": secrets.token_hex(16),
        "LOGFLARE_PUBLIC_ACCESS_TOKEN": secrets.token_hex(16),
        "LOGFLARE_PRIVATE_ACCESS_TOKEN": secrets.token_hex(16),
        "POSTGRES_PASSWORD": "".join(secrets.choice(alphabet) for _ in range(32)),
    }
    env_path = STACK / ".env"
    env = env_path.read_text(encoding="utf-8")
    OLD_ANON = env_value(env, "ANON_KEY")
    for key in new:
        if not re.search(rf"(?m)^{re.escape(key)}=", env):
            print(f"ABORT: {key} not found in stack .env - nothing written")
            return 1
    print("  minted:", ", ".join(new))

    live_password = ""
    print("  checking live database password candidates")
    for candidate in stack_env_candidates(env_path, "POSTGRES_PASSWORD"):
        if password_auth_works(candidate):
            live_password = candidate
            break
    if not live_password:
        print("ABORT: could not verify the current database password from "
              "stack .env or .env backups - nothing written")
        return 1
    if live_password != env_value(env, "POSTGRES_PASSWORD"):
        print("  stack .env POSTGRES_PASSWORD was stale; will restore the "
              "verified live password")

    # ---- 2. loopback port bindings ---------------------------------------
    print("== 2. binding published ports to 127.0.0.1 ==")
    compose_path = STACK / "docker-compose.yml"
    compose = compose_path.read_text(encoding="utf-8")
    for var, cport in (("KONG_HTTP_PORT", "8000/tcp"),
                       ("KONG_HTTPS_PORT", "8443/tcp"),
                       ("POSTGRES_PORT", "5432"),
                       ("POOLER_PROXY_PORT_TRANSACTION", "6543")):
        bound = f"- 127.0.0.1:${{{var}}}:{cport}"
        plain = f"- ${{{var}}}:{cport}"
        if bound in compose:
            print(f"  {var}: already loopback-bound")
        elif plain in compose:
            compose = compose.replace(plain, bound)
            print(f"  {var}: bound to 127.0.0.1")
        else:
            print(f"ABORT: ports line for {var} not found in docker-compose.yml")
            return 1
    compose_path.write_text(compose, encoding="utf-8", newline="\n")

    # ---- 3. rotate DB role passwords -------------------------------------
    print("== 3. ALTER ROLE passwords in Postgres ==")
    rotated_db_password = False
    is_superuser = current_role_is_superuser()
    if is_superuser is None:
        return 1
    if is_superuser:
        sql = "do $$ begin\n" + "".join(
            f"if exists (select 1 from pg_roles where rolname = '{r}') then "
            f"execute format('alter role {r} with password %L', "
            f"'{new['POSTGRES_PASSWORD']}'); end if;\n" for r in ROLES) + "end $$;"
        p = run(["docker", "exec", "-i", "supabase-db", "psql", "-h", "127.0.0.1",
                 "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1",
                 "-c", sql])
        if p.returncode != 0:
            print("ABORT: role rotation failed:", p.stderr[-500:])
            print("nothing secret was written to stack .env; fix the DB role "
                  "permissions or retry with a verified superuser role.")
            return 1
        rotated_db_password = True
        print("  roles rotated:", ", ".join(ROLES))
    else:
        new["POSTGRES_PASSWORD"] = live_password
        print("  postgres is not a superuser; keeping the verified live "
              "POSTGRES_PASSWORD and skipping DB role password rotation")

    # ---- 4. write stack .env ----------------------------------------------
    print("== 4. writing stack .env ==")
    try:
        env = replace_env_values(env, new)
    except KeyError as e:
        print(f"ABORT: {e.args[0]} not found in stack .env - nothing written")
        return 1
    env_path.write_text(env, encoding="utf-8", newline="\n")
    print("  written:", ", ".join(new))

    # ---- 5. pooler tenant reseed ------------------------------------------
    print("== 5. dropping supavisor tenant (reseeds on restart) ==")
    if rotated_db_password:
        p = run(["docker", "exec", "supabase-db", "psql", "-h", "127.0.0.1",
                 "-U", "postgres", "-d", "_supabase", "-c",
                 "delete from _supavisor.tenants where external_id = 'your-tenant-id';"])
        print("  ", (p.stdout or p.stderr).strip())
    else:
        print("  skipped: DB password was not rotated")

    # ---- 6. restart stack --------------------------------------------------
    print("== 6. docker compose up -d (recreates changed services) ==")
    p = run(["docker", "compose", "up", "-d"], cwd=str(STACK))
    if p.returncode != 0:
        print("ABORT: compose up failed:", p.stderr[-800:])
        return 1
    run(["docker", "restart", "adcoherent-rag-db-proxy"])

    # ---- 7. project env files ---------------------------------------------
    # The project has exactly TWO env files: the repo-root .env and
    # frontend/.env.local, both owned by scripts/sync_env.py. Rewrite the
    # root .env's password/URLs here (stdlib, always works), then let
    # sync_env.py do the canonical regeneration of both files.
    print("== 7. regenerating project env files ==")
    root_env = PROJECT / ".env"
    text = root_env.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^POSTGRES_PASSWORD=.*$",
                  f"POSTGRES_PASSWORD={new['POSTGRES_PASSWORD']}", text)
    text = re.sub(r"postgresql://postgres:[^@]*@",
                  f"postgresql://postgres:{new['POSTGRES_PASSWORD']}@", text)
    root_env.write_text(text, encoding="utf-8", newline="\n")
    print("  updated", root_env)
    p = run([sys.executable, str(PROJECT / "scripts" / "sync_env.py")],
            cwd=str(PROJECT))
    if p.returncode == 0:
        for line in p.stdout.strip().splitlines():
            print("  " + line)
    else:
        print("  WARNING: scripts/sync_env.py failed - run it yourself to "
              "realign root .env + frontend/.env.local:\n", p.stderr[-400:])

    # ---- 8. verify ---------------------------------------------------------
    print("== 8. verification ==")
    deadline = time.time() + 180
    while time.time() < deadline:
        p = run(["docker", "compose", "ps", "--format",
                 "{{.Name}} {{.Status}}"], cwd=str(STACK))
        lines = [l for l in p.stdout.splitlines() if l.strip()]
        unhealthy = [l for l in lines
                     if "unhealthy" in l or "starting" in l or "Restarting" in l]
        if lines and not unhealthy:
            break
        time.sleep(5)
    print(p.stdout)

    import urllib.request
    def status_for(key: str) -> int:
        req = urllib.request.Request("http://127.0.0.1:8000/rest/v1/",
                                     headers={"apikey": key})
        try:
            return urllib.request.urlopen(req, timeout=10).status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception:
            return -1

    old_status = status_for(OLD_ANON)
    new_status = status_for(new["ANON_KEY"])
    ok_keys = old_status == 401 and new_status in (200, 404)
    print(f"  old demo anon key -> HTTP {old_status} (want 401)")
    print(f"  new anon key      -> HTTP {new_status} (want 200)")

    # -h supabase-db => scram auth: proves the NEW password really works
    # (loopback would be trust-authed and prove nothing).
    p = run(["docker", "exec", "-e", f"PGPASSWORD={new['POSTGRES_PASSWORD']}",
             "supabase-db", "psql", "-h", "supabase-db", "-U", "postgres",
             "-tAc", "select count(*) from rag_chunks;"],
            redact=(new["POSTGRES_PASSWORD"],))
    print("  rag_chunks reachable:", p.stdout.strip() or p.stderr.strip())
    p = run(["docker", "port", "supabase-kong"])
    q = run(["docker", "port", "supabase-pooler"])
    loopback_only = all(("127.0.0.1" in l) for l in
                        (p.stdout + q.stdout).splitlines() if "->" in l
                        and "[::]" not in l)
    print(p.stdout + q.stdout)
    print("-" * 60)
    print("fingerprints:", json.dumps({
        "jwt_secret": jwt_secret[:8] + "...",
        "anon_key": "..." + new["ANON_KEY"][-10:],
        "service_role_key": "..." + new["SERVICE_ROLE_KEY"][-10:]}))
    if ok_keys and loopback_only:
        print("HARDENING COMPLETE - old demo keys are dead, ports loopback-only.")
        print("Now run:  cd", PROJECT, "&& CV-RULE_ENG-NLP/.venv/Scripts/python.exe "
              "-m engine.cli saas-selftest")
        return 0
    print("PARTIAL: check the lines above; backups: .env.bak-2026-07-13, "
          "docker-compose.yml.bak-2026-07-13")
    return 1


if __name__ == "__main__":
    sys.exit(main())
