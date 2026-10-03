#!/usr/bin/env bash
# YoungCrowHarness · setup.sh
# Copia o harness (CLAUDE.md, AGENTS.md, hooks, .mcp.json, .env.example, .gitignore) para um projeto
# e instala componentes de skills-lock.json. Segredos ficam no ambiente local.
#
# Copies the harness into a project and installs the plugins and skills from skills-lock.json.
# Keep credentials in the local environment.
#
# Uso / usage:
#   bash setup.sh <pasta-do-projeto> [--client claude|codex|both] [--nome "Nome"] [--force] [--sem-plugins]
set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-}"; NOME=""; FORCE=0; PLUGINS=1; CLIENT=both
TRIAL=0; TRIAL_CHILD=0; BACKUP_ROOT=""
shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --nome|--name)
      if [ $# -lt 2 ] || [ -z "$2" ] || [[ "$2" == --* ]]; then
        echo "uso / usage: --nome/--name exige um valor / requires a value" >&2; exit 2
      fi
      NOME="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --trial) TRIAL=1; shift ;;
    --trial-child) TRIAL=1; TRIAL_CHILD=1; shift ;;
    --backup-root)
      if [ $# -lt 2 ] || [ -z "$2" ] || [[ "$2" == --* ]]; then
        echo 'uso / usage: --backup-root exige caminho / requires a path' >&2; exit 2
      fi
      BACKUP_ROOT="$2"; shift 2 ;;
    --client)
      if [ $# -lt 2 ] || [[ "$2" != claude && "$2" != codex && "$2" != both ]]; then
        echo 'uso / usage: --client claude|codex|both' >&2; exit 2
      fi
      CLIENT="$2"; shift 2 ;;
    --sem-plugins|--no-plugins) PLUGINS=0; shift ;;
    *) echo "argumento desconhecido / unknown argument: $1"; exit 2 ;;
  esac
done
if [ -z "$TARGET" ]; then
  echo 'uso: bash setup.sh <pasta> [--client claude|codex|both] [--nome "Nome"] [--force] [--sem-plugins]'; exit 2
fi
falhar() { printf '%s\n' "$1" >&2; exit 1; }
[ -z "$BACKUP_ROOT" ] || [ "$TRIAL" = 1 ] || falhar '--backup-root exige / requires --trial'
REQUESTED_TARGET="$TARGET"
FILES=(CLAUDE.md AGENTS.md .env.example skills-lock.json docs/CLAUDE.en.md)
FILES+=(scripts/integrations.py skills/integrate-from-docs/SKILL.md
  skills/integrate-from-docs/references/memory.md
  vault/index.md vault/integrations/index.md vault/capabilities/index.md)
FILES+=(scripts/personalize.py skills/personalizer/SKILL.md skills/personalizer/references/interview.md)
FILES+=(scripts/vault.py scripts/document_store.py)
FILES+=(scripts/documents.py scripts/docling_worker.py requirements/docling.txt)
FILES+=(scripts/source_fetch.py)
FILES+=(requirements/docling-media.txt)
FILES+=(scripts/source_prompt.py skills/ingest-source/SKILL.md)
FILES+=(scripts/memory.py scripts/graphify_worker.py requirements/graphify.txt skills/retrieve-memory/SKILL.md)
FILES+=(scripts/capabilities.py skills/govern-capabilities/SKILL.md)
FILES+=(scripts/adoption.py scripts/adoption_fs.py scripts/adoption_acl.ps1)
FILES+=(scripts/mission_config.py scripts/mission_backlog.py scripts/mission_store.py scripts/mission_vault.py scripts/missions.py)
FILES+=(scripts/mission_clients.py scripts/mission_process.py scripts/mission_runs.py)
FILES+=(skills/yc-personalizer/SKILL.md skills/yc-config/SKILL.md skills/yc-missao/SKILL.md skills/yc-status/SKILL.md)
SKILL_ROOTS=()
if [ "$CLIENT" != codex ]; then
  FILES+=(.mcp.json .claude/settings.json .claude/agents/integration-specialist.md
    .claude/skills/integrate-from-docs/SKILL.md .claude/skills/personalizer/SKILL.md .claude/skills/ingest-source/SKILL.md .claude/skills/retrieve-memory/SKILL.md .claude/skills/govern-capabilities/SKILL.md)
  SKILL_ROOTS+=("$HOME/.claude/skills")
  FILES+=(.claude/skills/yc-personalizer/SKILL.md .claude/skills/yc-config/SKILL.md .claude/skills/yc-missao/SKILL.md .claude/skills/yc-status/SKILL.md)
fi
if [ "$CLIENT" != claude ]; then
  FILES+=(.codex/hooks.json .codex/config.toml .codex/agents/integration-specialist.toml
    .agents/skills/integrate-from-docs/SKILL.md .agents/skills/personalizer/SKILL.md .agents/skills/ingest-source/SKILL.md .agents/skills/retrieve-memory/SKILL.md .agents/skills/govern-capabilities/SKILL.md)
  SKILL_ROOTS+=("$TARGET/.agents/skills")
  FILES+=(.agents/skills/yc-personalizer/SKILL.md .agents/skills/yc-config/SKILL.md .agents/skills/yc-missao/SKILL.md .agents/skills/yc-status/SKILL.md)
fi
if [ "$TRIAL" = 1 ]; then SKILL_ROOTS=(); PLUGINS=0; fi
for ferramenta in python3 git mkdir cp chmod mv mktemp; do
  command -v "$ferramenta" >/dev/null 2>&1 || falhar "dependência ausente / missing dependency: $ferramenta"
done
python3 -c 'import json, pathlib, sys' || falhar 'python3 indisponível / unavailable'
if [ "$TRIAL" = 1 ]; then
  # All trial probes, including the public preflight and child, use the same safe Git reader.
  git() {
    python3 -B - "$HARNESS_DIR/scripts" "$@" <<'PY'
import pathlib, sys
sys.path.insert(0, sys.argv[1])
from adoption_fs import git_read
result = git_read(pathlib.Path.cwd(), *sys.argv[2:])
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
sys.exit(result.returncode)
PY
  }
fi
if [ "$TRIAL_CHILD" = 1 ]; then
  IFS= read -r SIGNAL || exit 2
  [ "$SIGNAL" = ready ] && [ -n "${YOUNGCROW_ADOPTION_TOKEN:-}" ] && [ -n "${YOUNGCROW_ADOPTION_BASE:-}" ] || exit 2
  python3 -B "$HARNESS_DIR/scripts/adoption.py" --root "$TARGET" --backup-root "$YOUNGCROW_ADOPTION_BASE" verify-child --json
fi
# Preflight is read-only. Resolve the requested root, then reject links inside it.
python3 - "$TARGET" "$HARNESS_DIR" "$HOME" "$CLIENT" "$TRIAL" "${FILES[@]}" <<'PY'
import json, pathlib, re, stat, sys

def check_path(root, relative):
    current = root
    parts = pathlib.Path(relative).parts
    for i, part in enumerate(parts):
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        # FILE_ATTRIBUTE_REPARSE_POINT works on Python 3.11 too (is_junction is 3.12+).
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, 'st_file_attributes', 0) & 0x400:
            raise ValueError('link em caminho gerenciado / linked managed path: ' + relative)
        if stat.S_ISDIR(metadata.st_mode) != (i < len(parts) - 1):
            raise ValueError('tipo de caminho incorreto / wrong path type: ' + relative)

try:
    target, source, user = [pathlib.Path(p).resolve() for p in sys.argv[1:4]]
    client = sys.argv[4]
    if target == source or target == target.parent:
        raise ValueError('destino inválido / invalid destination')
    if target.exists() and not target.is_dir():
        raise ValueError('destino não é diretório / destination is not a directory')
    files = [*sys.argv[6:], '.gitignore']
    for name in files:
        if not (source / name).is_file():
            raise ValueError('fonte ausente / missing source: ' + name)
        check_path(target, name)
    check_path(target, '.env')
    roots = [] if sys.argv[5] == '1' else (([(user, '.claude/skills')] if client != 'codex' else []) + ([(target, '.agents/skills')] if client != 'claude' else []))
    for root, relative in roots:
        for name in ('humanizer', 'humanizer-ptbr'):
            check_path(root, relative + '/' + name + '/SKILL.md')
    if not (source / 'skills/humanizer-ptbr/SKILL.md').is_file():
        raise ValueError('fonte ausente / missing source: humanizer-ptbr')
    manifest = json.loads((source / 'skills-lock.json').read_text(encoding='utf-8'))
    skill = manifest['skills_de_usuario']['humanizer']['upstream']
    if not re.fullmatch(r'[0-9a-f]{40}', skill['commit']):
        raise ValueError('commit inválido / invalid skill commit')
    if not isinstance(skill['repo'], str) or not skill['repo'].startswith('https://') or any(c.isspace() for c in skill['repo']):
        raise ValueError('origem inválida / invalid skill source')
    for name, plugin in manifest['plugins'].items():
        for value in (name, plugin['marketplace']):
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', value):
                raise ValueError('identificador inválido / invalid plugin identifier')
        if not isinstance(plugin.get('origem'), str):
            raise ValueError('origem inválida / invalid plugin source')
    existing = target
    while not existing.exists():
        existing = existing.parent
    if not existing.is_dir():
        raise ValueError('diretório pai inválido / invalid parent directory')
except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
    # Never echo arbitrary manifest values or file contents.
    print('preflight falhou / failed: ' + (str(error) if type(error) is ValueError else type(error).__name__), file=sys.stderr)
    sys.exit(1)
PY
TARGET="$(python3 -c 'import pathlib,sys; sys.stdout.reconfigure(newline="\n"); print(pathlib.Path(sys.argv[1]).resolve().as_posix())' "$TARGET")"
EXISTING="$TARGET"
while [ ! -d "$EXISTING" ]; do EXISTING="$(dirname "$EXISTING")"; done
IN_GIT=0
if GIT_PROBE="$(LC_ALL=C git -C "$EXISTING" rev-parse --is-inside-work-tree 2>&1)"; then
  [ "$GIT_PROBE" = true ] || falhar 'destino sem worktree Git / destination has no Git worktree'
  IN_GIT=1
  if git --literal-pathspecs -C "$EXISTING" ls-files --error-unmatch -- "$TARGET/.env" >/dev/null 2>&1; then
    falhar '.env rastreado pelo Git; resolva antes de instalar / tracked .env; resolve before installing'
  else
    [ "$?" -eq 1 ] || falhar 'falha ao verificar env rastreado / cannot check tracked env'
  fi
else
  case "$GIT_PROBE" in
    *'not a git repository'*) ;;
    *) falhar 'falha ao verificar repositório / cannot inspect repository' ;;
  esac
fi
read -r SKILL_REPO SKILL_COMMIT < <(python3 - "$HARNESS_DIR/skills-lock.json" <<'PY'
import json, sys
sys.stdout.reconfigure(newline='\n')
s = json.load(open(sys.argv[1], encoding='utf-8'))['skills_de_usuario']['humanizer']['upstream']
print(s['repo'], s['commit'])
PY
)
verificar_skill() {
  local prefix head status
  prefix="$(git -C "$1" rev-parse --show-prefix 2>/dev/null)" || return 1
  [ -z "$prefix" ] || return 1
  head="$(git -C "$1" rev-parse HEAD 2>/dev/null)" || return 1
  [ "$head" = "$SKILL_COMMIT" ] && [ -f "$1/SKILL.md" ] || return 1
  status="$(git -C "$1" status --porcelain --untracked-files=all 2>/dev/null)" || return 1
  [ -z "$status" ]
}
for SK in "${SKILL_ROOTS[@]}"; do
  if [ -d "$SK/humanizer" ]; then
    verificar_skill "$SK/humanizer" || falhar "humanizer divergente ou modificado / mismatched or dirty: $SK/humanizer; preservado / preserved"
  fi
done
if [ "$TRIAL" = 1 ] && [ "$TRIAL_CHILD" = 0 ]; then
  ARGS=(--root "$REQUESTED_TARGET")
  [ -z "$BACKUP_ROOT" ] || ARGS+=(--backup-root "$BACKUP_ROOT")
  ARGS+=(install --source "$HARNESS_DIR" --client "$CLIENT")
  [ -z "$NOME" ] || ARGS+=(--name "$NOME")
  [ "$FORCE" = 0 ] || ARGS+=(--force)
  exec python3 -B "$HARNESS_DIR/scripts/adoption.py" "${ARGS[@]}"
fi
if [ "$TRIAL" = 1 ]; then
  echo '== teste local / local trial: sem plugins, downloads ou escrita no perfil global / no plugins, downloads or global profile writes'
else
  echo '== instalação normal: sem ponto de retorno inicial / normal installation: no initial restore point'
fi
mkdir -p "$TARGET"; TARGET="$(cd "$TARGET" && pwd -P)"
[ -n "$NOME" ] || NOME="$(basename "$TARGET")"

copiar() {  # copiar <relativo>: nunca sobrescreve sem --force
  local rel="$1" src="$HARNESS_DIR/$1" dst="$TARGET/$1"
  # Knowledge is product data, never a replaceable configuration template.
  if [[ "$rel" == vault/* ]] && [ -e "$dst" ]; then echo "  mantido / preserved: $rel (vault)"; return; fi
  case "$rel" in
    skills-lock.json|skills/*|.claude/skills/*|.agents/skills/*|.claude/agents/*|.codex/agents/*|scripts/mission_clients.py|scripts/mission_runs.py|scripts/mission_process.py)
      if [ -e "$dst" ]; then
        echo "  preservado / preserved: $rel; compare e mescle / compare and merge"; return
      fi ;;
    .mcp.json|.codex/config.toml|.claude/settings.json|.codex/hooks.json)
      if [ -e "$dst" ]; then
        echo "  preservado / preserved: $rel; compare e mescle / compare and merge with $src"; return
      fi ;;
  esac
  if [ -e "$dst" ] && [ "$FORCE" != 1 ]; then echo "  mantido  $rel (já existe; use --force para trocar)"; return; fi
  mkdir -p "$(dirname "$dst")"; cp "$src" "$dst"; echo "  copiado  $rel"
  case "$rel" in
    CLAUDE.md|AGENTS.md|docs/CLAUDE.en.md)
      python3 - "$dst" "$NOME" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); t = p.read_text(encoding="utf-8")
p.write_text(t.replace("{{PROJETO}}", sys.argv[2]).replace("{{PROJECT}}", sys.argv[2]), encoding="utf-8")
PY
      ;;
  esac
}

echo "== YoungCrowHarness → $TARGET  (projeto: $NOME; client: $CLIENT)"
for f in "${FILES[@]}"; do
  copiar "$f"
done
# Ignore rules are merged even with --force. Never replace a consumer's rules.
[ -f "$TARGET/.gitignore" ] || cp "$HARNESS_DIR/.gitignore" "$TARGET/.gitignore"
python3 - "$TARGET/.gitignore" "$CLIENT" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); data = p.read_bytes()
# Final rules override earlier negations; downloaded Git repos must not become gitlinks.
rules = [b'/.env', b'/vault/local/', b'/.operacao-local/docling/', b'/.operacao-local/memory/', b'/.operacao-local/capabilities/']
if sys.argv[2] != 'claude':
    rules += [b'/.agents/skills/humanizer/', b'/.agents/skills/humanizer-ptbr/']
if data.splitlines()[-len(rules):] != rules:
    with p.open('ab') as output:
        output.write((b'' if not data or data.endswith(b'\n') else b'\n') + b'\n'.join(rules) + b'\n')
    print('  mesclado / merged: .gitignore (env + skills locais / local skills)')
PY
if [ "$IN_GIT" = 1 ]; then
  git -C "$TARGET" check-ignore --no-index -q -- .env || falhar '.env não protegido / not ignored'
  echo '  .env: proteção Git verificada / Git ignore verified'
else
  echo '  .env: ignore preparado; verifique após git init / ignore prepared; verify after git init'
fi
# .env local, nunca versionado
if [ ! -f "$TARGET/.env" ]; then
  (umask 077; cp "$TARGET/.env.example" "$TARGET/.env"; chmod 600 "$TARGET/.env")
  echo '  criado / created: .env (600 onde suportado / where supported)'
else
  echo "  mantido  .env"
fi

# Skills are activated only after validation. Cleanup owns only this run's staging.
STAGE=""
limpar_stage() {
  [ -n "$STAGE" ] || return 0
  python3 - "$SK" "$STAGE" <<'PY'
import os, pathlib, shutil, stat, sys
root, stage = map(pathlib.Path, sys.argv[1:])
if stage.is_symlink() or stage.resolve().parent != root.resolve() or not stage.name.startswith('.humanizer.'):
    sys.exit('staging fora da raiz / staging outside root')
def writable_remove(func, path, error):
    os.chmod(path, stat.S_IWRITE)
    func(path)
if stage.exists():
    shutil.rmtree(stage, onerror=writable_remove)
PY
}
trap limpar_stage EXIT
for SK in "${SKILL_ROOTS[@]}"; do
mkdir -p "$SK"
if [ ! -d "$SK/humanizer" ]; then
  STAGE="$(mktemp -d "$SK/.humanizer.XXXXXX")"
  git clone -q -- "$SKILL_REPO" "$STAGE" >/dev/null 2>&1 || falhar 'falhou / failed: humanizer download'
  git -C "$STAGE" checkout -q --detach "$SKILL_COMMIT" >/dev/null 2>&1 || falhar 'falhou / failed: humanizer checkout'
  verificar_skill "$STAGE" || falhar 'falhou / failed: humanizer verification'
  [ ! -e "$SK/humanizer" ] && [ ! -L "$SK/humanizer" ] || falhar 'destino ocupado / destination occupied: humanizer'
  mv -- "$STAGE" "$SK/humanizer"
  STAGE=""
  echo "  instalado / installed: humanizer @ $SKILL_COMMIT → $SK/humanizer"
else echo "  verificado e mantido / verified and kept: $SK/humanizer"; fi
if [ ! -d "$SK/humanizer-ptbr" ]; then
  cp -r "$HARNESS_DIR/skills/humanizer-ptbr" "$SK/humanizer-ptbr"; echo "  skill    humanizer-ptbr → $SK/humanizer-ptbr"
else echo "  mantido  $SK/humanizer-ptbr"; fi
done

# Marketplace versions are inventory, not enforced pins.
FALHAS=0
if [ "$CLIENT" = codex ]; then
  echo '== plugins Claude: pulados / skipped (--client codex); plugins Codex: instalar no cliente / install in client'
elif [ "$PLUGINS" = 0 ]; then
  echo '== plugins: pulados / skipped (--sem-plugins / --no-plugins)'
elif ! command -v claude >/dev/null 2>&1; then
  echo '== plugins: pulados / skipped (claude ausente / missing from PATH)'
else
  echo "== plugins (claude plugin marketplace add + install)"
  while read -r nome mkt origem; do
    if ! claude plugin marketplace add "$origem" >/dev/null 2>&1; then
      echo "  falhou / failed marketplace: $mkt" >&2; FALHAS=$((FALHAS + 1))
    elif ! claude plugin install "$nome@$mkt" >/dev/null 2>&1; then
      echo "  falhou / failed plugin: $nome" >&2; FALHAS=$((FALHAS + 1))
    else echo "  instalado / installed plugin: $nome"; fi
  done < <(python3 - "$HARNESS_DIR/skills-lock.json" <<'PY'
import json, sys
sys.stdout.reconfigure(newline='\n')
d = json.load(open(sys.argv[1], encoding='utf-8'))
for nome, p in d["plugins"].items():
    o = p.get("origem") or ""
    if "/" in o and " " not in o:
        print(nome, p["marketplace"], o)
PY
  )
  echo "  nota     impeccable vem de diretório local no manifesto: instale do upstream do plugin à mão"
fi
echo '  manual: skills sem upstream / skills without upstream — veja / see skills-lock.json'
[ "$FALHAS" -eq 0 ] || falhar "instalação incompleta / incomplete installation: $FALHAS falha(s) / failure(s)"

cat <<FIM

Pronto. Próximos passos / next steps:
  1. cd "$TARGET" && \$EDITOR .env          # valores reais, só aqui
  2. \$EDITOR CLAUDE.md                     # troque cada <preencher> pelo seu projeto
  3. MCPs: .mcp.json (Claude); .codex/config.toml (Codex), conforme --client
  4. Abra o cliente escolhido na pasta / open the selected client in the project:
     claude / codex — confira skills, MCPs e confiança / check skills, MCPs and trust

☧ Ora et labora ☧ et coda </>
FIM
