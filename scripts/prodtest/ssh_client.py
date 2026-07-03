"""Thin wrapper around the `ssh` binary (not paramiko -- the VPS host is
already in ~/.ssh/config with its own IdentityFile/User, so shelling out
to the real `ssh` command reuses that config for free instead of
re-implementing host/key resolution). Every method here is read-only or
narrowly scoped (single-row DELETE by primary key, `docker exec ls` for
file-existence checks) -- this class is deliberately NOT a general
"run arbitrary command" convenience wrapper, to keep the blast radius of
a bug in this harness small.
"""

from __future__ import annotations

import shlex
import subprocess


class SshCommandError(RuntimeError):
    def __init__(self, command: str, returncode: int, stdout: str, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            f"ssh command failed (exit {returncode}): {command}\n"
            f"stderr: {stderr.strip()}"
        )


class VpsSsh:
    def __init__(self, host_alias: str, timeout: float = 20.0) -> None:
        self._host = host_alias
        self._timeout = timeout

    def run(self, remote_command: str) -> str:
        """Runs `remote_command` on the VPS via the host's login shell and
        returns stdout. Raises SshCommandError on non-zero exit."""
        result = subprocess.run(
            ["ssh", self._host, remote_command],
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )
        if result.returncode != 0:
            raise SshCommandError(
                remote_command, result.returncode, result.stdout, result.stderr
            )
        return result.stdout

    def is_reachable(self) -> bool:
        try:
            self.run("true")
            return True
        except (SshCommandError, subprocess.TimeoutExpired, OSError):
            return False

    def docker_exec(self, container: str, *args: str) -> str:
        """`docker exec <container> <args...>` -- each arg individually
        shell-quoted, so a file path or id containing spaces/special
        characters can't break out of the intended command."""
        quoted = " ".join(shlex.quote(a) for a in args)
        return self.run(f"docker exec {shlex.quote(container)} {quoted}")

    def file_exists_in_container(self, container: str, path: str) -> bool:
        try:
            self.docker_exec(container, "test", "-e", path)
            return True
        except SshCommandError as exc:
            if exc.returncode == 1:
                return False
            raise

    def psql_delete_row(
        self,
        *,
        container: str,
        db_user: str,
        db_name: str,
        table: str,
        id_column: str,
        row_id: str,
    ) -> int:
        """DELETE FROM <table> WHERE <id_column> = '<row_id>' -- the last-
        resort cleanup path for tables the public API has no delete route
        for at all (invoice/budget append-only-by-design tables,
        inventory_locations with no delete endpoint). `table`/`id_column`
        come from this harness's own probe code, never from a server
        response or other untrusted input -- `row_id` is the only
        variable part and is embedded via psql's -v/:'var' quoting
        (psql-side quoting, not shell string interpolation), which is
        SQL-injection-safe for a plain UUID/text value.
        """
        if (
            not table.replace("_", "").isalnum()
            or not id_column.replace("_", "").isalnum()
        ):
            raise ValueError(
                f"unsafe identifier: table={table!r} id_column={id_column!r}"
            )
        self.docker_exec(
            container,
            "psql",
            "-U",
            db_user,
            "-d",
            db_name,
            "-v",
            f"row_id={row_id}",
            "-t",
            "-A",
            "-c",
            f"DELETE FROM {table} WHERE {id_column} = :'row_id';",
        )
        # Confirm via a follow-up SELECT rather than trusting DELETE's own
        # exit code -- a DELETE that matched zero rows still exits 0, and
        # "the row was already gone for some other reason" should surface
        # as loudly as "the row is still there."
        return self.psql_scalar_int(
            container=container,
            db_user=db_user,
            db_name=db_name,
            sql=f"SELECT count(*) FROM {table} WHERE {id_column} = :'row_id';",
            row_id=row_id,
        )

    def psql_scalar_int(
        self,
        *,
        container: str,
        db_user: str,
        db_name: str,
        sql: str,
        row_id: str | None = None,
    ) -> int:
        args = ["psql", "-U", db_user, "-d", db_name]
        if row_id is not None:
            args += ["-v", f"row_id={row_id}"]
        args += ["-t", "-A", "-c", sql]
        out = self.docker_exec(container, *args)
        return int(out.strip() or "0")
