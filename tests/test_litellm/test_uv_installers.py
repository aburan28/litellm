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
PINNED_ARCHIVE_NAME: Final = "uv-x86_64-unknown-linux-gnu.tar.gz"
PINNED_ARCHIVE_SHA256: Final = "20d79708222611fa540b5c9ed84f352bcd3937740e51aacc0f8b15b271c57594"
ARCHIVE_SHA256S: Final = MappingProxyType(
    {
        "uv-aarch64-apple-darwin.tar.gz": "a92f61e9ac9b0f29668c15f56152e4a60143fca148ff5bfadb86718472c3f376",
        "uv-x86_64-apple-darwin.tar.gz": "9cc2de7d195fa157f98b306a8a1cb151ded93f488939b93363cebc8b9d598c28",
        "uv-aarch64-unknown-linux-gnu.tar.gz": "cc0c5a8573e7d6d78aecb954e0a62b5c0d18217bb81f1e19363b428c57a9962a",
        "uv-aarch64-unknown-linux-musl.tar.gz": "05b0d3087e913ebe11756365a90dd47c05d6728752fdbe129ad4c3ccd769826d",
        "uv-arm-unknown-linux-musleabihf.tar.gz": "6220fa3eb5f8212cae4ec3a5053060914aaa829549cf706dde9f9cc344f75f61",
        "uv-armv7-unknown-linux-gnueabihf.tar.gz": "0076eac165c2f7129627e2297478e7ffbb9465d9ae6a8961b2f53dcbd807473d",
        "uv-armv7-unknown-linux-musleabihf.tar.gz": "f702e821b80e371e14987a886d58ee103c5948b7b096fa49a552624c24d7e073",
        "uv-i686-unknown-linux-gnu.tar.gz": "90d9168a4e7900463f9fd79a32eb1890081fb1e238d803404f6e17b2dcdcca7b",
        "uv-i686-unknown-linux-musl.tar.gz": "1d42b0d0a037b3d658b11ec889154686db3ab269ba2b789bdbc45d36e3549f34",
        "uv-powerpc64le-unknown-linux-gnu.tar.gz": "e804f4a7d0659e09ef806365f04bdd33c940603fab903e925402748d05dd109a",
        "uv-riscv64gc-unknown-linux-gnu.tar.gz": "1541596da45855e34202130027a613a2ace7d441e04d747cb4dd9f2590461c9a",
        "uv-s390x-unknown-linux-gnu.tar.gz": "a589d4a8930c82fa7225daec19c632651b3c84f50f770efe758056b387e5f0dd",
        PINNED_ARCHIVE_NAME: PINNED_ARCHIVE_SHA256,
        "uv-x86_64-unknown-linux-musl.tar.gz": "433e56874739e92c7cfd661ba9e5f287b376ca612c08c8194a41a98a13158aea",
    }
)
INSTALLERS: Final = (
    REPO_ROOT / "scripts" / "install.sh",
    REPO_ROOT / "scripts" / "install-cli.sh",
    REPO_ROOT / ".devcontainer" / "post-create.sh",
)
INSTALLER_IDS: Final = tuple(path.name for path in INSTALLERS)
FULL_INSTALLER: Final = REPO_ROOT / "scripts" / "install.sh"
CLI_INSTALLER: Final = REPO_ROOT / "scripts" / "install-cli.sh"
DEVCONTAINER_INSTALLER: Final = REPO_ROOT / ".devcontainer" / "post-create.sh"
PUBLIC_INSTALLERS: Final = (FULL_INSTALLER, CLI_INSTALLER)
CRON_VM_SETUP: Final = REPO_ROOT / "tests" / "e2e" / "claude_code" / "cron_vm" / "README.md"


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(0o755)


def _install_shims(
    tmp_path: Path,
    hash_utility: str,
    reported_sha256: str,
    uv_version: str = "0.0.0",
    reported_archive_sha256: str = PINNED_ARCHIVE_SHA256,
) -> tuple[Path, Path, Path]:
    bin_dir: Final = tmp_path / "bin"
    home_bin: Final = tmp_path / "home" / ".local" / "bin"
    marker: Final = tmp_path / "bootstrap-marker"
    record: Final = tmp_path / "record"
    bin_dir.mkdir(parents=True)
    home_bin.mkdir(parents=True)

    system_commands: Final = ("awk", "cat", "chmod", "cmp", "cp", "env", "grep", "head", "mktemp", "rm", "uname")
    system_executables: Final = tuple(shutil.which(command) for command in system_commands)
    for command, executable in zip(system_commands, system_executables):
        assert executable is not None
        (bin_dir / command).symlink_to(executable)

    _write_executable(
        bin_dir / "curl",
        """#!/bin/sh
set -eu
output=""
url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) output="$2"; shift 2 ;;
    https://*) url="$1"; shift ;;
    -*) shift ;;
    *) shift ;;
  esac
done
[ -n "$output" ]
case "$url" in
  */uv-*.tar.gz) cp "$ARCHIVE_PAYLOAD" "$output" ;;
  *) cp "$PAYLOAD" "$output" ;;
esac
printf 'download=%s\n' "$output" >> "$RECORD"
printf 'download_url=%s\n' "$url" >> "$RECORD"
""",
    )
    _write_executable(
        bin_dir / hash_utility,
        """#!/bin/sh
set -eu
if [ "${1:-}" = "-a" ]; then shift 2; fi
if [ "$1" = "$ARCHIVE_PATH" ]; then
  cmp -s "$ARCHIVE_PAYLOAD" "$1"
  printf '%s  %s\n' "$REPORTED_ARCHIVE_SHA256" "$1"
  printf 'archive_verified=%s\n' "$1" >> "$RECORD"
else
  cmp -s "$PAYLOAD" "$1"
  printf '%s  %s\n' "$REPORTED_SHA256" "$1"
  printf 'verified=%s\n' "$1" >> "$RECORD"
fi
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
        f"""#!/bin/sh
set -eu
printf 'uv=%s\n' "$*" >> "$RECORD"
case "$*" in
  --version) printf 'uv {uv_version}\n' ;;
  'tool dir --bin') printf '%s\n' "$HOME/.local/bin" ;;
esac
""",
    )
    for command in ("lite", "litellm", "npm"):
        _write_executable(
            home_bin / command,
            f'#!/bin/sh\nprintf \'{command}=%s\\n\' "$*" >> "$RECORD"\n',
        )

    payload: Final = tmp_path / "payload.sh"
    payload.write_text(
        "\n".join(
            (
                "#!/bin/sh",
                "set -eu",
                f'curl -sSfL "https://releases.astral.sh/github/uv/releases/download/0.10.9/{PINNED_ARCHIVE_NAME}" '
                ' -o "$ARCHIVE_PATH"',
                'printf \'bootstrap_complete=%s\\n\' "$ARCHIVE_PATH" >> "$RECORD"',
                f"printf 'executed\\n' > '{marker}'",
            )
        )
    )
    archive_payload: Final = tmp_path / "archive-payload.tar.gz"
    archive_payload.write_text("synthetic uv archive\n")
    archive_path: Final = tmp_path / PINNED_ARCHIVE_NAME
    environment: Final = tmp_path / "environment"
    environment.write_text(
        "\n".join(
            (
                f"PATH={bin_dir}",
                f"HOME={tmp_path / 'home'}",
                f"PAYLOAD={payload}",
                f"ARCHIVE_PAYLOAD={archive_payload}",
                f"ARCHIVE_PATH={archive_path}",
                f"RECORD={record}",
                f"REPORTED_SHA256={reported_sha256}",
                f"REPORTED_ARCHIVE_SHA256={reported_archive_sha256}",
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
    archive_verified_line: Final = next(line for line in record_lines if line.startswith("archive_verified="))
    bootstrap_complete_line: Final = next(line for line in record_lines if line.startswith("bootstrap_complete="))
    assert download_line.removeprefix("download=") == verified_line.removeprefix("verified=")
    assert verified_line.removeprefix("verified=") == executed_line.removeprefix("executed=")
    assert record_lines.index(download_line) < record_lines.index(verified_line) < record_lines.index(executed_line)
    assert archive_verified_line.removeprefix("archive_verified=") == bootstrap_complete_line.removeprefix(
        "bootstrap_complete="
    )
    assert record_lines.index(archive_verified_line) < record_lines.index(bootstrap_complete_line)
    assert any(line.startswith("uv=tool install") or line.startswith("uv=sync") for line in record_lines)
    assert not Path(download_line.removeprefix("download=")).exists()


@pytest.mark.parametrize("script", INSTALLERS, ids=INSTALLER_IDS)
@pytest.mark.parametrize("hash_utility", ("sha256sum", "shasum"))
def test_uv_installers_reject_modified_archive_before_use(
    script: Path,
    hash_utility: str,
    tmp_path: Path,
) -> None:
    environment_file, marker, record = _install_shims(
        tmp_path,
        hash_utility,
        PINNED_SHA256,
        reported_archive_sha256="0" * 64,
    )

    result: Final = _run_installer(script, tmp_path, environment_file)

    assert result.returncode != 0
    assert "uv archive checksum verification failed" in result.stderr
    assert not marker.exists()
    record_lines: Final = record.read_text().splitlines()
    assert any(line.startswith("archive_verified=") for line in record_lines)
    assert not any(line.startswith("bootstrap_complete=") for line in record_lines)
    assert tuple(line for line in record_lines if line.startswith("uv=")) in ((), ("uv=--version",))
    assert not any(line.startswith(("lite=", "litellm=", "npm=")) for line in record_lines)


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


@pytest.mark.parametrize("script", PUBLIC_INSTALLERS, ids=("install.sh", "install-cli.sh"))
def test_uv_installers_reuse_exact_version_without_bootstrap(script: Path, tmp_path: Path) -> None:
    environment_file, marker, record = _install_shims(tmp_path, "sha256sum", PINNED_SHA256, uv_version="0.10.9")
    environment_values: Final = _environment_values(environment_file)
    (Path(environment_values["PATH"]) / "sha256sum").unlink()

    result: Final = _run_installer(script, tmp_path, environment_file)

    if script == FULL_INSTALLER:
        assert result.returncode != 0
        assert "/dev/tty" in result.stderr
    else:
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert not marker.exists()
    record_lines: Final = record.read_text().splitlines()
    assert record_lines[0] == "uv=--version"
    assert any(line.startswith("uv=tool install") for line in record_lines)
    assert not any(line.startswith(("download=", "verified=", "executed=")) for line in record_lines)


def test_uv_installer_version_and_checksum_match_ci_precedent() -> None:
    circleci: Final = (REPO_ROOT / ".circleci" / "config.yml").read_text()
    installer_contents: Final = tuple(script.read_text() for script in INSTALLERS)
    cron_vm_setup: Final = CRON_VM_SETUP.read_text()

    for contents in installer_contents:
        assert 'UV_VERSION="0.10.9"' in contents
        assert f'UV_INSTALLER_SHA256="{PINNED_SHA256}"' in contents
        assert "https://releases.astral.sh/github/uv/releases/download/${UV_VERSION}/uv-installer.sh" in contents
        assert 'install.sh" |' not in contents
        for archive_name, archive_sha256 in ARCHIVE_SHA256S.items():
            assert f'{archive_name}) UV_ARCHIVE_SHA256="{archive_sha256}"' in contents

    assert PINNED_SHA256 in circleci
    assert PINNED_ARCHIVE_SHA256 in cron_vm_setup
    assert f'uv_archive="{PINNED_ARCHIVE_NAME}"' in cron_vm_setup
    assert "https://releases.astral.sh/github/uv/releases/download/0.10.9/$uv_archive" in cron_vm_setup
    assert "https://astral.sh/uv/install.sh | sh" not in cron_vm_setup
