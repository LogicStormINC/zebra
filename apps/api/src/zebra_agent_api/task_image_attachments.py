from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from agent_core.application import task_workspace_image_prompt_suffix
from agent_core.domain.attachments import SessionAttachmentRef
from agent_core.domain.identifiers import ArtifactId, EventId
from zebra_agent_config import ZebraAgentSettings, task_workspace_root

from zebra_agent_api.session_attachment_inputs import ImageAttachmentInput


@dataclass(frozen=True)
class StagedTaskImage:
    attachment_id: ArtifactId
    file_name: str
    media_type: str
    size_bytes: int
    sha256: str
    workspace_path: str
    path: Path


@dataclass(frozen=True)
class StagedTaskImages:
    workspace_root: Path
    images: tuple[StagedTaskImage, ...]

    def refs_for(self, message_event_id: EventId) -> tuple[SessionAttachmentRef, ...]:
        return tuple(
            SessionAttachmentRef(
                attachment_id=image.attachment_id,
                message_event_id=message_event_id,
                file_name=image.file_name,
                media_type=image.media_type,
                size_bytes=image.size_bytes,
                sha256=image.sha256,
                storage_kind="task_workspace",
                workspace_path=image.workspace_path,
            )
            for image in self.images
        )


def stage_task_images(
    settings: ZebraAgentSettings,
    *,
    task_id: str,
    images: tuple[ImageAttachmentInput, ...],
) -> StagedTaskImages:
    root = task_workspace_root(settings, task_id)
    if not images:
        return StagedTaskImages(root, ())
    base = settings.task_workspace_root.expanduser()
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    base = base.resolve(strict=True)
    root = base / task_id
    created_dirs: list[Path] = []
    created_paths: list[Path] = []
    try:
        if _ensure_directory(root):
            created_dirs.append(root)
        image_root = root / "images"
        if _ensure_directory(image_root):
            created_dirs.append(image_root)
        staged: list[StagedTaskImage] = []
        for image in images:
            suffix = ".png" if image.media_type == "image/png" else ".jpg"
            file_name = f"image-{image.attachment_id}{suffix}"
            workspace_path = f"images/{file_name}"
            path = image_root / file_name
            _write_new_file(path, image.payload)
            created_paths.append(path)
            staged.append(
                StagedTaskImage(
                    attachment_id=image.attachment_id,
                    file_name=file_name,
                    media_type=image.media_type,
                    size_bytes=len(image.payload),
                    sha256=sha256(image.payload).hexdigest(),
                    workspace_path=workspace_path,
                    path=path,
                )
            )
        return StagedTaskImages(root, tuple(staged))
    except Exception:
        _cleanup_paths(created_paths, created_dirs)
        raise


def cleanup_staged_task_images(staged: StagedTaskImages) -> None:
    _cleanup_paths(
        [image.path for image in staged.images],
        [staged.workspace_root / "images", staged.workspace_root],
    )


def task_image_prompt_suffix(staged: StagedTaskImages) -> str:
    return task_workspace_image_prompt_suffix(
        tuple((image.workspace_path, image.media_type) for image in staged.images)
    )


def _ensure_directory(path: Path) -> bool:
    if path.is_symlink():
        raise ValueError("managed task image workspace must not be a symlink")
    try:
        path.mkdir(mode=0o700)
        return True
    except FileExistsError:
        if path.is_symlink() or not path.is_dir():
            raise ValueError("managed task image workspace must be a directory") from None
        return False


def _write_new_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)


def _cleanup_paths(paths: Sequence[Path], directories: Sequence[Path]) -> None:
    for path in reversed(paths):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for directory in reversed(directories):
        try:
            directory.rmdir()
        except OSError:
            pass
