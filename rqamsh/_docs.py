"""定位当前 SDK 的离线文档，按需同步到显式指定的 Skill。"""

from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

from . import __version__
from .errors import HarnessError


def _doc_files(root: Path) -> list[Path]:
    """枚举公开文档和案例材料，与 wheel 的包数据范围一致。"""
    files = (
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file() and (
            path.suffix == ".md"
            or path.relative_to(root).parts[0] == "demo" and path.suffix in {".py", ".json", ".csv", ".xlsx"}
        )
    )
    return sorted(files, key=Path.as_posix)


def _fingerprint(root: Path, files: list[Path]) -> str:
    """按相对路径和内容标识文档修订，与 SDK 版本号独立。"""
    digest = sha256()
    for name in files:
        digest.update(name.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256((root / name).read_bytes()).digest())
    return digest.hexdigest()


def _source_root() -> Path:
    """优先返回安装包文档；从源码运行时使用同仓库的公开文档。"""
    repo = Path(__file__).resolve().parents[1]
    bundled = repo / "rqamsh_docs"
    if (bundled / "index.md").is_file():
        return bundled
    source = repo / "docs"
    if (repo / "MANIFEST.in").is_file() and (repo / "pyproject.toml").is_file() and (source / "index.md").is_file():
        return source
    raise HarnessError("docs_unavailable", "当前 rqamsh 没有随包文档；请安装包含文档的 SDK")


def _sync_docs(source: Path, files: list[Path], revision: str, skill_dir: Path) -> Path:
    """只发布新的内容寻址目录，不替换已有技能、缓存或用户文件。"""
    skill_dir = skill_dir.resolve()
    if not (skill_dir / "SKILL.md").is_file():
        raise HarnessError("invalid_skill_dir", "--skill-dir 必须指定包含 SKILL.md 的 rqamsh 子技能目录")
    cache = skill_dir / "sdk-docs"
    if cache.resolve() != cache:
        raise HarnessError("invalid_skill_dir", "Skill 的 sdk-docs 必须是普通目录")
    cache.mkdir(exist_ok=True)
    target = cache / revision

    def validate() -> Path:
        """只复用与当前发布内容完全一致的版本。"""
        present = _doc_files(target) if target.is_dir() and target.resolve() == target else []
        if present != files or _fingerprint(target, present) != revision:
            raise HarnessError("docs_cache_conflict", f"Skill 文档目录与随包文档不一致，未覆盖：{target}")
        return target

    if target.exists() or target.is_symlink():
        return validate()
    with TemporaryDirectory(prefix=".sync-", dir=cache) as temporary:
        stage = Path(temporary) / "docs"
        for name in files:
            dest = stage / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            copyfile(source / name, dest)
        if _fingerprint(stage, files) != revision:
            raise HarnessError("docs_changed", "同步期间源文档已变化，请重新执行 rqamsh docs")
        try:
            stage.rename(target)
        except OSError:
            if not target.exists() and not target.is_symlink():
                raise
            return validate()
    return target


def _locate_docs(skill_dir: Path | None) -> dict[str, str]:
    """返回同一 SDK 的文档根路径、包版本和文档摘要。"""
    try:
        sdk_version = version("rqams-harness")
    except PackageNotFoundError:
        sdk_version = __version__
    source = _source_root()
    files = _doc_files(source)
    revision = _fingerprint(source, files)
    path = source if skill_dir is None else _sync_docs(source, files, revision, skill_dir)
    return {"path": str(path), "sdk_version": sdk_version, "docs_sha256": revision}
