"""Scoped .pepper workspace archives; no server controls or worker jobs are saved."""
from __future__ import annotations
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import time
import uuid
import zipfile

FORMAT = 'salt-and-pepper-workspace'
VERSION = 1
ID = re.compile(r'^[a-f0-9]{32}$')
MAX_FILES = 50000
MAX_EXPANDED_BYTES = 8 * 1024**3
MAX_FILE_BYTES = 2 * 1024**3
MAX_JSON_BYTES = 128 * 1024**2
MAX_UI_BYTES = 1024**2
ACTIVE = {'queued', 'running', 'pending', 'cancelling'}
KINDS = ('boards', 'models', 'runs')
EXCLUDED = {'jobs', 'tmp', 'temp', 'cache', 'server.json', 'control.json', 'request.json', '.DS_Store'}


def _json_bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError('Workspace state must contain finite JSON values.') from exc


def _decode(raw):
    try:
        return json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite JSON.')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('Invalid workspace JSON.') from exc


def _read(path, default=None):
    if not path.is_file():
        return default
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError('Workspace JSON metadata is too large.')
    return _decode(path.read_bytes())


def _valid_id(value, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('Invalid saved board, model or run identifier.')
    return value


def _name(value):
    value = str(value or 'Workspace').replace('\\', '/').rsplit('/', 1)[-1]
    if value.lower().endswith('.pepper'):
        value = value[:-7]
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:100]
    return value or 'Workspace'


def _ui(value):
    if value is None:
        value = {}
    if not isinstance(value, dict) or len(_json_bytes(value)) > MAX_UI_BYTES:
        raise ValueError('Workspace interface state must be a JSON object smaller than 1 MiB.')
    return value


def _safe_folder(root, kind, key):
    folder = root / kind / key
    if folder.is_symlink() or not folder.is_dir() or not folder.resolve().is_relative_to(root):
        raise ValueError('A saved workspace item is missing or outside its data folder.')
    return folder


def _job_rows(root):
    for path in (root / 'jobs').glob('*/status.json'):
        row = _read(path, {})
        if isinstance(row, dict):
            yield row


def _files(folder):
    for current, dirs, files in os.walk(folder, followlinks=False):
        current = Path(current)
        for name in dirs + files:
            if (current / name).is_symlink():
                raise ValueError('Workspace archives cannot include symbolic links.')
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not d.startswith('.workspace-'))
        for name in sorted(files):
            path = current / name
            if name in EXCLUDED or name.startswith('.workspace-'):
                continue
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError('Workspace archives can include only regular files.')
            yield path


def export_workspace(data_root, board_id=None, model_id=None, name='Workspace', ui_state=None, outputpath=None):
    """Save one board and all its geometry/results, or a single STEP model.

    ``outputpath`` is written atomically. The result includes its exact path and
    a sanitized ``suggested_filename`` for a .pepper download. Legacy KiCad
    models are associated through saved job metadata when board_id is absent
    from their model metadata. Active work must finish before taking a snapshot.
    """
    root = Path(data_root).resolve()
    board_id = _valid_id(board_id, optional=True)
    model_id = _valid_id(model_id, optional=True)
    if not board_id and not model_id:
        raise ValueError('Import a board or geometry model before saving a workspace.')
    ui_state = _ui(ui_state)
    jobs = list(_job_rows(root))
    related_models = set()
    if board_id:
        _safe_folder(root, 'boards', board_id)
        for path in (root / 'models').glob('*/meta.json'):
            meta = _read(path, {})
            if isinstance(meta, dict) and meta.get('board_id') == board_id:
                related_models.add(_valid_id(path.parent.name))
        related_models.update(_valid_id(job['model_id']) for job in jobs
                      if job.get('board_id') == board_id and job.get('model_id'))
    if model_id:
        _safe_folder(root, 'models', model_id)
        if board_id and model_id not in related_models:
            raise ValueError('The active geometry model does not belong to this board.')
        related_models.add(model_id)
    runs = set()
    for path in (root / 'runs').glob('*/meta.json'):
        meta = _read(path, {})
        config = _read(path.parent / 'config.json', {})
        if (isinstance(meta, dict) and (meta.get('model_id') in related_models or board_id is not None and meta.get('board_id') == board_id)) or (isinstance(config, dict) and config.get('model_id') in related_models):
            runs.add(_valid_id(path.parent.name))
            for row in (meta, config):
                if isinstance(row, dict) and row.get('model_id'):
                    related_models.add(_valid_id(row['model_id']))
    models = {key for key in related_models if (root / 'models' / key).exists()}
    # Deleting geometry deliberately retains its self-contained result folders.
    # Preserve those references without recreating an invented geometry model.
    detached = related_models - models
    selected = {'boards': [board_id] if board_id else [], 'models': sorted(models), 'runs': sorted(runs)}
    for job in jobs:
        if job.get('status') in ACTIVE and (job.get('board_id') == board_id and board_id is not None or job.get('model_id') in related_models or job.get('run_id') in runs):
            raise ValueError('Wait for this workspace’s active jobs to finish before saving.')
    for kind, keys in selected.items():
        for key in keys:
            folder = _safe_folder(root, kind, key)
            if (_read(folder / 'meta.json', {}) or {}).get('status') in ACTIVE:
                raise ValueError('Wait for this workspace’s active jobs to finish before saving.')
    manifest = dict(format=FORMAT, version=VERSION, name=_name(name), created_at=time.time(),
                    board_id=board_id, model_id=model_id, models=selected['models'], detached_model_ids=sorted(detached), runs=selected['runs'], ui_state=ui_state)
    if outputpath is None:
        raise ValueError('Choose a workspace archive output path.')
    output = Path(outputpath).resolve()
    if any(_safe_folder(root, kind, key) in output.parents for kind, keys in selected.items() for key in keys):
        raise ValueError('Save the archive outside its board, model and result folders.')
    output.parent.mkdir(parents=True, exist_ok=True)
    count = total = 0
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.workspace-export-', suffix='.pepper', dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=4, allowZip64=True) as archive:
            archive.writestr('manifest.json', _json_bytes(manifest))
            for kind, keys in selected.items():
                for key in keys:
                    folder = _safe_folder(root, kind, key)
                    for path in _files(folder):
                        size = path.stat().st_size
                        count += 1; total += size
                        if count > MAX_FILES or size > MAX_FILE_BYTES or total > MAX_EXPANDED_BYTES:
                            raise ValueError('This workspace exceeds the archive size or file-count limit.')
                        archive.write(path, str(PurePosixPath(kind, key, *path.relative_to(folder).parts)))
        os.replace(temporary, output)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return dict(manifest, path=str(output), bytes=output.stat().st_size, suggested_filename=manifest['name'] + '.pepper')


def _manifest(value):
    if not isinstance(value, dict) or value.get('format') != FORMAT or type(value.get('version')) is not int or value['version'] != VERSION:
        raise ValueError('This is not a supported .pepper workspace archive.')
    board = _valid_id(value.get('board_id'), optional=True)
    model = _valid_id(value.get('model_id'), optional=True)
    selected = {'boards': [board] if board else []}
    for kind in ('models', 'runs'):
        rows = value.get(kind)
        if not isinstance(rows, list) or len(rows) != len(set(str(row) for row in rows)):
            raise ValueError('Invalid workspace item list.')
        selected[kind] = [_valid_id(row) for row in rows]
    detached = value.get('detached_model_ids', [])
    if not isinstance(detached, list) or len(detached) != len(set(str(row) for row in detached)):
        raise ValueError('Invalid detached geometry identifiers.')
    detached = [_valid_id(row) for row in detached]
    if set(detached) & set(selected['models']) or detached and not board:
        raise ValueError('Detached geometry must belong to a board workspace.')
    if not board and not model or model is not None and model not in selected['models']:
        raise ValueError('The workspace has no valid active board or model.')
    if not isinstance(value.get('ui_state', {}), dict):
        raise ValueError('Invalid workspace interface state.')
    _ui(value.get('ui_state', {}))
    return selected, detached


def _rewrite(value, mapping, root):
    if isinstance(value, dict):
        return {key: _rewrite(item, mapping, root) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite(item, mapping, root) for item in value]
    if not isinstance(value, str):
        return value
    if value in mapping:
        return mapping[value]
    # Relocate filesystem paths before replacing browser links: an absolute
    # /old/data/runs/<id>/... path also contains the /runs/<id> URL pattern.
    if not value.startswith(('/api/', '/runs/', '/artifacts/')) and (value.startswith('/') or re.match(r'^[A-Za-z]:[\\/]', value)):
        normalized = value.replace('\\', '/')
        for kind in KINDS:
            for old, new in mapping.items():
                marker = '/' + kind + '/' + old
                index = normalized.find(marker)
                if index >= 0 and (index + len(marker) == len(normalized) or normalized[index + len(marker)] == '/'):
                    return str(root / kind / new) + normalized[index + len(marker):]
    if not value.startswith(('/api/', '/runs/', '/artifacts/', 'http://', 'https://')):
        return value
    for old, new in mapping.items():
        value = re.sub(r'(/(?:api/(?:models|kicad/boards)|runs|artifacts)/)' + old + r'(?=/|$|[?#])', lambda match: match[1] + new, value)
    return value


def import_workspace(data_root, archive_path):
    """Validate and restore an archive under fresh IDs, preserving existing data."""
    root = Path(data_root).resolve(); root.mkdir(parents=True, exist_ok=True)
    moved = []
    try:
        with zipfile.ZipFile(archive_path, 'r') as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_FILES + 1:
                raise ValueError('Workspace archive has too many files.')
            paths = set(); total = 0; manifest_info = None
            for info in infos:
                raw = info.filename; path = PurePosixPath(raw)
                if '\\' in raw or '\x00' in raw or ':' in raw or path.is_absolute() or any(part in ('', '.', '..') for part in raw.rstrip('/').split('/')):
                    raise ValueError('Workspace archive contains an unsafe path.')
                if raw in paths or str(path) in paths:
                    raise ValueError('Workspace archive contains duplicate paths.')
                paths.add(str(path))
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or info.flag_bits & 1:
                    raise ValueError('Workspace archive contains an unsupported file entry.')
                if info.file_size > MAX_FILE_BYTES:
                    raise ValueError('Workspace archive contains an oversized file.')
                total += info.file_size
                if total > MAX_EXPANDED_BYTES:
                    raise ValueError('Workspace archive exceeds the expanded-size limit.')
                if raw == 'manifest.json': manifest_info = info
            if manifest_info is None or manifest_info.file_size > MAX_UI_BYTES * 2:
                raise ValueError('Workspace manifest is missing or too large.')
            manifest = _decode(archive.read(manifest_info)); selected, detached = _manifest(manifest)
            for info in infos:
                if info.filename == 'manifest.json': continue
                parts = PurePosixPath(info.filename).parts
                if len(parts) < 2 or parts[0] not in KINDS or parts[1] not in selected[parts[0]] or any(part in EXCLUDED for part in parts[2:]):
                    raise ValueError('Workspace archive contains files outside its declared items.')
                if len(parts) < 3 and not info.is_dir():
                    raise ValueError('Workspace item must be a directory.')
            mapping = {old: uuid.uuid4().hex for keys in selected.values() for old in keys}
            mapping.update({old: uuid.uuid4().hex for old in detached})
            with tempfile.TemporaryDirectory(prefix='.workspace-import-', dir=root) as temporary:
                stage = Path(temporary)
                for info in infos:
                    if info.filename == 'manifest.json' or info.is_dir(): continue
                    parts = PurePosixPath(info.filename).parts
                    target = stage / parts[0] / mapping[parts[1]] / Path(*parts[2:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open('wb') as output:
                        shutil.copyfileobj(source, output, length=1024**2)
                for kind, keys in selected.items():
                    for old in keys:
                        folder = stage / kind / mapping[old]
                        meta = _read(folder / 'meta.json')
                        if not isinstance(meta, dict) or meta.get('id') != old or meta.get('status') in ACTIVE:
                            raise ValueError('Workspace metadata is missing, inconsistent or still active.')
                        if kind == 'boards' and not (folder / 'board.json').is_file():
                            raise ValueError('Workspace board inventory is missing.')
                        if kind == 'models' and not (folder / 'inventory.json').is_file():
                            raise ValueError('Workspace geometry inventory is missing.')
                        if kind == 'runs':
                            config = _read(folder / 'config.json', {})
                            refs = [value for value in (meta.get('model_id'), config.get('model_id')) if value is not None]
                            if not refs or any(value not in selected['models'] + detached for value in refs) or len(set(refs)) != 1:
                                raise ValueError('A result references geometry outside this workspace.')
                        if kind == 'models' and meta.get('board_id') is not None and meta['board_id'] not in selected['boards']:
                            raise ValueError('A geometry model references another board.')
                        for path in folder.rglob('*.json'):
                            value = _read(path)
                            value = _rewrite(value, mapping, root)
                            if path.name == 'meta.json' and path.parent == folder:
                                value.pop('job_id', None)
                                value['restored_from_workspace'] = True
                                value['workspace_name'] = _name(manifest.get('name'))
                                if kind in ('models', 'runs') and selected['boards']:
                                    value['board_id'] = mapping[selected['boards'][0]]
                            path.write_bytes(_json_bytes(value))
                # All validation and extraction precede publication. Roll back any
                # already moved item if a subsequent filesystem move fails.
                for kind, keys in selected.items():
                    (root / kind).mkdir(exist_ok=True)
                    if (root / kind).is_symlink(): raise ValueError('Workspace storage cannot be a symbolic link.')
                    for old in keys:
                        target = root / kind / mapping[old]
                        if target.exists(): raise ValueError('Workspace restore identifier collision.')
                        os.rename(stage / kind / mapping[old], target); moved.append(target)
            result = _rewrite(manifest, mapping, root)
            result['name'] = _name(manifest.get('name'))
            return result
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, UnicodeError, OSError, ValueError, RecursionError) as exc:
        for path in reversed(moved):
            shutil.rmtree(path, ignore_errors=True)
        if isinstance(exc, ValueError): raise
        raise ValueError('The workspace archive could not be restored: ' + str(exc)) from exc
