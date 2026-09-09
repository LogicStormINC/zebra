from __future__ import annotations

import asyncio
import io
import json
import stat
import zipfile

import pytest
from agent_runtime import github_skill_import as importer
from agent_tools.skill_packages import validate_skill_package

SKILL = (
    b"---\nname: better-writing\ndescription: Write better prose.\n---\n"
    b"Follow references/style.md.\n"
)


def archive(files: dict[str, bytes], *, symlinks: tuple[str, ...] = ()) -> bytes:
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.comment = b"a" * 40
        for name, content in files.items():
            info = zipfile.ZipInfo("repo-sha/" + name)
            info.external_attr = (stat.S_IFLNK if name in symlinks else stat.S_IFREG) << 16
            bundle.writestr(info, content)
    return result.getvalue()


def test_root_preferred_ignores_symlink_and_repository_files() -> None:
    source = archive(
        {
            "SKILL.md": SKILL,
            "references/style.md": b"Short sentences.",
            "LICENSE": b"MIT",
            ".github/workflows/test.yml": b"not imported",
            "evals/test.py": b"not executed",
            "skills/better-writing/SKILL.md": b"../../SKILL.md",
        },
        symlinks=("skills/better-writing/SKILL.md",),
    )
    result, path = importer._select_package(source, None)
    assert path == ""
    assert result == importer._select_package(source, None)[0]
    package = validate_skill_package(result)
    assert {file.path for file in package.files} == {
        "SKILL.md",
        "references/style.md",
        "references/repository-LICENSE",
    }


def test_multiple_skills_require_directory() -> None:
    source = archive({"skills/a/SKILL.md": SKILL, "skills/b/SKILL.md": SKILL})
    with pytest.raises(importer.GitHubSkillImportError) as error:
        importer._select_package(source, None)
    assert error.value.reason == "skill_directory_required"
    assert error.value.candidates == ("skills/a", "skills/b")
    assert importer._select_package(source, "skills/b")[1] == "skills/b"


def test_single_nested_skill_is_discovered() -> None:
    assert importer._select_package(archive({"skills/a/SKILL.md": SKILL}), None)[1] == "skills/a"


def test_nested_skill_preserves_repository_license() -> None:
    result, _ = importer._select_package(
        archive({"skills/a/SKILL.md": SKILL, "LICENSE": b"MIT"}), None
    )
    assert {file.path for file in validate_skill_package(result).files} == {
        "SKILL.md",
        "references/repository-LICENSE",
    }


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "https://github.com.evil/a/b",
        "https://token@github.com/a/b",
        "https://github.com:443/a/b",
        "https://github.com/a/b?q=x",
        "https://github.com/a/..",
        "https://github.com/a",
        "https://github.com/a/b/tree/main/%2e%2e/x",
        "https://github.com/a/b/blob/main/SKILL.md",
    ],
)
def test_reject_untrusted_urls(url: str) -> None:
    with pytest.raises(importer.GitHubSkillImportError, match="invalid_github_skill_url"):
        importer._parse_url(url, None)


def test_tree_path_and_encoded_ref() -> None:
    assert importer._parse_url("https://github.com/a/b/tree/feature%2Fskill/skills/a", None) == (
        "a",
        "b",
        "feature/skill",
        "skills/a",
    )
    with pytest.raises(importer.GitHubSkillImportError):
        importer._parse_url("https://github.com/a/b/tree/main/skills/a", "skills/b")


@pytest.mark.parametrize(
    "files,symlinks,reason",
    [
        ({"../SKILL.md": SKILL}, (), "invalid_path"),
        (
            {"SKILL.md": SKILL, "references/escape": b"/etc/passwd"},
            ("references/escape",),
            "unsupported_entry",
        ),
        ({"SKILL.md": b"../../SKILL.md"}, ("SKILL.md",), "skill_file_not_found"),
        ({"SKILL.md": b"missing frontmatter"}, (), "invalid_skill_file"),
        (
            {"SKILL.md": SKILL, "LICENSE": b"MIT", "references/repository-LICENSE": b"x"},
            (),
            "path_conflict",
        ),
    ],
)
def test_invalid_packages(files: dict[str, bytes], symlinks: tuple[str, ...], reason: str) -> None:
    with pytest.raises(importer.GitHubSkillImportError, match=reason):
        importer._select_package(archive(files, symlinks=symlinks), None)


def test_revalidate_and_immutable_download(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    sha = "a" * 40

    def download(host: str, path: str, limit: int) -> bytes:
        calls.append((host, path))
        if path.endswith("/commits/main"):
            return json.dumps({"sha": sha}).encode()
        if host == "codeload.github.com":
            return archive({"SKILL.md": SKILL})
        return b'{"default_branch":"main"}'

    monkeypatch.setattr(importer, "_download", download)
    result = asyncio.run(
        importer.import_github_skill(
            "https://github.com/forjd/better-writing", revalidate=lambda: calls.append("authorize")
        )
    )
    assert result.commit_sha == sha
    assert calls == [
        "authorize",
        ("api.github.com", "/repos/forjd/better-writing"),
        "authorize",
        ("api.github.com", "/repos/forjd/better-writing/commits/main"),
        "authorize",
        ("codeload.github.com", "/forjd/better-writing/zip/" + sha),
        "authorize",
    ]


def test_revocation_stops_before_download(monkeypatch: pytest.MonkeyPatch) -> None:
    def revoked() -> None:
        raise PermissionError("revoked")

    def unexpected(*args: object) -> bytes:
        pytest.fail("network after revocation")

    monkeypatch.setattr(importer, "_download", unexpected)
    with pytest.raises(PermissionError):
        asyncio.run(importer.import_github_skill("https://github.com/a/b", revalidate=revoked))


def test_rate_limit_fallback_pins_archive_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[tuple[str, str]] = []

    def download(host: str, path: str, limit: int) -> bytes:
        requests.append((host, path))
        if host == "api.github.com":
            raise importer.GitHubSkillImportError("github_access_or_rate_limited")
        return archive({"SKILL.md": SKILL})

    monkeypatch.setattr(importer, "_download", download)
    result = asyncio.run(
        importer.import_github_skill("https://github.com/a/b", revalidate=lambda: None)
    )
    assert result.commit_sha == "a" * 40
    assert requests == [
        ("api.github.com", "/repos/a/b"),
        ("codeload.github.com", "/a/b/zip/HEAD"),
        ("codeload.github.com", "/a/b/zip/" + "a" * 40),
    ]


def test_pinned_download_commit_mismatch_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importer, "_json", lambda target: {"sha": "b" * 40})
    monkeypatch.setattr(importer, "_download", lambda *args: archive({"SKILL.md": SKILL}))
    with pytest.raises(importer.GitHubSkillImportError, match="github_commit_mismatch"):
        asyncio.run(
            importer.import_github_skill(
                "https://github.com/a/b/tree/main", revalidate=lambda: None
            )
        )


def test_archive_without_commit_cannot_pin() -> None:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as bundle:
        bundle.writestr("SKILL.md", SKILL)
    with pytest.raises(importer.GitHubSkillImportError, match="github_commit_unavailable"):
        importer._archive_commit(data.getvalue())


@pytest.mark.parametrize(
    "status,declared,body,reason",
    [
        (302, None, b"", "github_http_error"),
        (404, None, b"", "github_repository_or_ref_not_found"),
        (429, None, b"", "github_access_or_rate_limited"),
        (200, "11", b"", "github_response_too_large"),
        (200, None, b"x" * 11, "github_response_too_large"),
    ],
)
def test_bounded_http_and_no_redirects(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    declared: str | None,
    body: bytes,
    reason: str,
) -> None:
    requests: list[tuple[object, ...]] = []

    class Response:
        def __init__(self) -> None:
            self.status = status

        def getheader(self, name: str) -> str | None:
            return declared

        def read(self, limit: int) -> bytes:
            assert limit == 11
            return body[:limit]

    class Connection:
        def __init__(self, host: str, timeout: int) -> None:
            assert host == "api.github.com" and timeout == 20

        def request(self, *args: object, **kwargs: object) -> None:
            requests.append(args)

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            requests.append(("closed",))

    monkeypatch.setattr(importer, "PublicMcpHttpsConnection", Connection)
    with pytest.raises(importer.GitHubSkillImportError, match=reason):
        importer._download("api.github.com", "/repos/a/b", 10)
    assert requests == [("GET", "/repos/a/b"), ("closed",)]


def test_archive_limits_and_duplicate_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    source = archive({"SKILL.md": SKILL})
    monkeypatch.setattr(importer, "MAX_ARCHIVE_BYTES", len(source) - 1)
    with pytest.raises(importer.GitHubSkillImportError, match="archive_too_large"):
        importer._select_package(source, None)
    monkeypatch.setattr(importer, "MAX_ARCHIVE_BYTES", len(source) + 1)
    monkeypatch.setattr(importer, "MAX_EXPANDED_BYTES", len(SKILL) - 1)
    with pytest.raises(importer.GitHubSkillImportError, match="expanded_archive_too_large"):
        importer._select_package(source, None)
