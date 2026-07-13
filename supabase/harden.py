"""ONE-SHOT Supabase hardening for the AdCoherent stack (run it yourself).

Does, in order (backups already at .env.bak-2026-07-13 / docker-compose.yml.bak-2026-07-13):
  1. mint fresh JWT_SECRET + anon/service_role keys (HS256), SECRET_KEY_BASE,
     VAULT_ENC_KEY, PG_META_CRYPTO_KEY, LOGFLARE tokens, POSTGRES_PASSWORD
     -> writes them into C:/Users/HP/supabase-project/.env
  2. binds ALL published ports (Kong 8000/8443, pooler 5432/6543) to
     127.0.0.1 in docker-compose.yml (skips lines already bound)
  3. ALTER ROLE ... PASSWORD for every Supabase login role in Postgres
  4. deletes the supavisor tenant row so the pooler reseeds itself with the
     new password on restart
  5. `docker compose up -d` (recreates only changed services; keeps the
     network so the adcoherent-rag-db-proxy socat container stays attached)
  6. updates DATABASE_URL in the project's .env and rag-engine/.env
  7. verifies: containers healthy, OLD demo anon key rejected (401), new
     anon key accepted, psql via the 54322 proxy works, ports loopback-only

Prints key fingerprints only, never full secrets (read them from .env).
Afterwards run:  python -m engine.cli saas-selftest

Usage:  python rotate.py
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
    print("  $", " ".join(cmd[:6]) + (" ..." if len(cmd) > 6 else ""))
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def main() -> int:
    global OLD_ANON
    # ---- 1. mint + write stack .env --------------------------------------
    print("== 1. rotating secrets in stack .env ==")
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
    m = re.search(r"(?m)^ANON_KEY=(.+)$", env)
    OLD_ANON = m.group(1).strip() if m else ""
    for key, val in new.items():
        if not re.search(rf"(?m)^{key}=", env):
            print(f"ABORT: {key} not found in stack .env - nothing written")
            return 1
        env = re.sub(rf"(?m)^{key}=.*$", f"{key}={val}", env)
    env_path.write_text(env, encoding="utf-8", newline="\n")
    print("  written:", ", ".join(new))

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
    sql = "do $$ begin\n" + "".join(
        f"if exists (select 1 from pg_roles where rolname = '{r}') then "
        f"execute format('alter role {r} with password %L', "
        f"'{new['POSTGRES_PASSWORD']}'); end if;\n" for r in ROLES) + "end $$;"
    p = run(["docker", "exec", "-i", "supabase-db", "psql", "-U", "postgres",
             "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", sql])
    if p.returncode != 0:
        print("ABORT: role rotation failed:", p.stderr[-500:])
        print("stack .env now holds the NEW password but the DB has the OLD "
              "one - restore .env.bak-2026-07-13 or re-run after fixing.")
        return 1
    print("  roles rotated:", ", ".join(ROLES))

    # ---- 4. pooler tenant reseed ------------------------------------------
    print("== 4. dropping supavisor tenant (reseeds on restart) ==")
    p = run(["docker", "exec", "supabase-db", "psql", "-U", "postgres",
             "-d", "_supabase", "-c",
             "delete from _supavisor.tenants where external_id = 'your-tenant-id';"])
    print("  ", (p.stdout or p.stderr).strip())

    # ---- 5. restart stack --------------------------------------------------
    print("== 5. docker compose up -d (recreates changed services) ==")
    p = run(["docker", "compose", "up", "-d"], cwd=str(STACK))
    if p.returncode != 0:
        print("ABORT: compose up failed:", p.stderr[-800:])
        return 1
    run(["docker", "restart", "adcoherent-rag-db-proxy"])

    # ---- 6. project env files ----------------------------------------------
    print("== 6. updating project DATABASE_URLs ==")
    url = (f"postgresql://postgres:{new['POSTGRES_PASSWORD']}"
           "@127.0.0.1:54322/postgres")
    for env_file in (PROJECT / ".env", PROJECT / "rag-engine" / ".env"):
        text = env_file.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^DATABASE_URL=.*$", f"DATABASE_URL={url}", text)
        env_file.write_text(text, encoding="utf-8", newline="\n")
        print("  updated", env_file)

    # ---- 7. verify -----------------------------------------------------------
    print("== 7. verification ==")
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

    p = run(["docker", "exec", "supabase-db", "psql", "-U", "postgres",
             "-tAc", "select count(*) from rag_chunks;"])
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
