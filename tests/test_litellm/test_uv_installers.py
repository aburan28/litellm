import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
PINNED_SHA256: Final = "7fc46e39cb97290b57169c0c813a17970585ac519139f19006453c99b5f2f45f"
INSTALLERS: Final = (
    REPO_ROOT / "scripts" / "install.sh",
    REPO_ROOT / "scripts" / "install-cli.sh",
    REPO_ROOT / ".devcontainer" / "post-create.sh",
)
INSTALLER_IDS: Final = tuple(path.name for path in INSTALLERS)
FULL_INSTALLER: Final = REPO_ROOT / "scripts" / "install.sh"
DEVCONTAINER_INSTALLER: Final = REPO_ROOT / ".devcontainer" / "post-create.sh"


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(0o755)


def _install_shims(tmp_path: Path, hash_utility: str, reported_sha256: str) -> tuple[Path, Path, Path]:
    bin_dir: Final = tmp_path / "bin"
    home_bin: Final = tmp_path / "home" / ".local" / "bin"
    marker: Final = tmp_path / "bootstrap-marker"
    record: Final = tmp_path / "record"
    bin_dir.mkdir(parents=True)
    home_bin.mkdir(parents=True)

    system_commands: Final = ("awk", "cat", "cmp", "cp", "env", "grep", "head", "mktemp", "rm", "uname")
    system_executables: Final = tuple(shutil.which(command) for command in system_commands)
    for command, executable in zip(system_commands, system_executables):
        assert executable is not None
        (bin_dir / command).symlink_to(executable)

    _write_executable(
        bin_dir / "curl",
        """#!/bin/sh
set -eu
output=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) output="$2"; shift 2 ;;
    -*) shift ;;
    *) shift ;;
  esac
done
[ -n "$output" ]
cp "$PAYLOAD" "$output"
printf 'download=%s\n' "$output" >> "$RECORD"
""",
    )
    _write_executable(
        bin_dir / hash_utility,
        """#!/bin/sh
set -eu
if [ "${1:-}" = "-a" ]; then shift 2; fi
cmp -s "$PAYLOAD" "$1"
printf '%s  %s\n' "$REPORTED_SHA256" "$1"
printf 'verified=%s\n' "$1" >> "$RECORD"
""",
    )
    _write_executable(
        bin_dir / "sh",
        """#!/bin/sh
printf 'executed=%s\n' "$1" >> "$RECORD"
exec /bin/sh "$@"
""",
    )
    _write_executable(
        home_bin / "uv",
        """#!/bin/sh
set -eu
printf 'uv=%s\n' "$*" >> "$RECORD"
case "$*" in
  --version) printf 'uv 0.0.0\n' ;;
  'tool dir --bin') printf '%s\n' "$HOME/.local/bin" ;;
esac
""",
    )
    for command in ("lite", "litellm", "npm"):
        _write_executable(
            home_bin / command,
            f"#!/bin/sh\nprintf '{command}=%s\\n' \"$*\" >> \"$RECORD\"\n",
        )

    payload: Final = tmp_path / "payload.sh"
    payload.write_text(f"#!/bin/sh\nprintf 'executed\\n' > '{marker}'\n")
    environment: Final = tmp_path / "environment"
    environment.write_text(
        "\n".join(
            (
                f"PATH={bin_dir}",
                f"HOME={tmp_path / 'home'}",
                f"PAYLOAD={payload}",
                f"RECORD={record}",
                f"REPORTED_SHA256={reported_sha256}",
            )
        )
    )
    return environment, marker, record


def _run_installer(script: Path, tmp_path: Path, environment_file: Path) -> subprocess.CompletedProcess[str]:
    environment_values: Final = _environment_values(environment_file)
    environment: Final = MappingProxyType({**os.environ, **environment_values, "TMPDIR": str(tmp_path)})
    interpreter: Final = "/bin/bash" if script == DEVCONTAINER_INSTALLER else "/bin/sh"
    return subprocess.run(
        (interpreter, str(script)),
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
        start_new_session=True,
    )


def _environment_values(environment_file: Path) -> Mapping[str, str]:
    entries: Final = (line.split("=", 1) for line in environment_file.read_text().splitlines())
    return MappingProxyType({key: value for key, value in entries})


@pytest.mark.parametrize("script", INSTALLERS, ids=INSTALLER_IDS)
@pytest.mark.parametrize("hash_utility", ("sha256sum", "shasum"))
def test_uv_installers_execute_only_checksum_verified_content(
    script: Path,
    hash_utility: str,
    tmp_path: Path,
) -> None:
    environment_file, marker, record = _install_shims(tmp_path, hash_utility, PINNED_SHA256)

    result: Final = _run_installer(script, tmp_path, environment_file)

    if script == FULL_INSTALLER:
        assert result.returncode != 0
        assert "/dev/tty" in result.stderr
    else:
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert marker.read_text() == "executed\n"
    record_lines: Final = record.read_text().splitlines()
    download_line: Final = next(line for line in record_lines if line.startswith("download="))
    verified_line: Final = next(line for line in record_lines if line.startswith("verified="))
    executed_line: Final = next(line for line in record_lines if line.startswith("executed="))
    assert download_line.removeprefix("download=") == verified_line.removeprefix("verified=")
    assert verified_line.removeprefix("verified=") == executed_line.removeprefix("executed=")
    assert record_lines.index(download_line) < record_lines.index(verified_line) < record_lines.index(executed_line)
    assert any(line.startswith("uv=tool install") or line.startswith("uv=sync") for line in record_lines)
    assert not Path(download_line.removeprefix("download=")).exists()


@pytest.mark.parametrize("script", INSTALLERS, ids=INSTALLER_IDS)
@pytest.mark.parametrize("hash_utility", ("sha256sum", "shasum"))
def test_uv_installers_reject_modified_content_before_execution(
    script: Path,
    hash_utility: str,
    tmp_path: Path,
) -> None:
    environment_file, marker, record = _install_shims(tmp_path, hash_utility, "0" * 64)

    result: Final = _run_installer(script, tmp_path, environment_file)

    assert result.returncode != 0
    assert "checksum verification failed" in result.stderr
    assert not marker.exists()
    record_lines: Final = record.read_text().splitlines()
    download_line: Final = next(line for line in record_lines if line.startswith("download="))
    verified_line: Final = next(line for line in record_lines if line.startswith("verified="))
    assert record_lines.index(download_line) < record_lines.index(verified_line)
    assert download_line.removeprefix("download=") == verified_line.removeprefix("verified=")
    assert not any(line.startswith("executed=") for line in record_lines)
    assert tuple(line for line in record_lines if line.startswith("uv=")) in ((), ("uv=--version",))
    assert not any(line.startswith(("lite=", "litellm=", "npm=")) for line in record_lines)
    assert not Path(download_line.removeprefix("download=")).exists()


@pytest.mark.parametrize("script", INSTALLERS, ids=INSTALLER_IDS)
def test_uv_installers_stop_when_download_fails(script: Path, tmp_path: Path) -> None:
    environment_file, marker, record = _install_shims(tmp_path, "sha256sum", PINNED_SHA256)
    environment_values: Final = _environment_values(environment_file)
    curl: Final = Path(environment_values["PATH"]) / "curl"
    _write_executable(
        curl,
        """#!/bin/sh
set -eu
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) output="$2"; shift 2 ;;
    -*) shift ;;
    *) shift ;;
  esac
done
printf 'download=%s\n' "$output" >> "$RECORD"
exit 22
""",
    )

    result: Final = _run_installer(script, tmp_path, environment_file)

    assert result.returncode != 0
    assert not marker.exists()
    record_lines: Final = record.read_text().splitlines()
    download_line: Final = next(line for line in record_lines if line.startswith("download="))
    assert not any(line.startswith("verified=") for line in record_lines)
    assert not Path(download_line.removeprefix("download=")).exists()


@pytest.mark.parametrize("script", INSTALLERS, ids=INSTALLER_IDS)
def test_uv_installers_fail_closed_without_sha256_utility(script: Path, tmp_path: Path) -> None:
    environment_file, marker, record = _install_shims(tmp_path, "sha256sum", PINNED_SHA256)
    environment_values: Final = _environment_values(environment_file)
    (Path(environment_values["PATH"]) / "sha256sum").unlink()

    result: Final = _run_installer(script, tmp_path, environment_file)

    assert result.returncode != 0
    assert "SHA-256 utility" in result.stderr
    assert not marker.exists()
    record_lines: Final = record.read_text().splitlines()
    download_line: Final = next(line for line in record_lines if line.startswith("download="))
    assert not any(line.startswith("verified=") for line in record_lines)
    assert not Path(download_line.removeprefix("download=")).exists()


def test_uv_installer_version_and_checksum_match_ci_precedent() -> None:
    circleci: Final = (REPO_ROOT / ".circleci" / "config.yml").read_text()
    installer_contents: Final = tuple(script.read_text() for script in INSTALLERS)

    for contents in installer_contents:
        assert 'UV_VERSION="0.10.9"' in contents
        assert f'UV_INSTALLER_SHA256="{PINNED_SHA256}"' in contents
        assert "astral.sh/uv" in contents
        assert "install.sh\" |" not in contents

    assert PINNED_SHA256 in circleci
