"""Run git, gh and shell commands the same way in every subcommand."""

import subprocess


class CommandError(Exception):
    """A command could not start, or exited non-zero when it had to succeed."""

    def __init__(self, cmd, code, output):
        self.cmd, self.code, self.output = cmd, code, output
        shown = " ".join(cmd) if isinstance(cmd, (list, tuple)) else cmd
        super().__init__(f"`{shown}` exited {code}: {output.strip()[-500:]}")


def run(cmd, cwd=None, check=True, env=None, timeout=None, input_text=None):
    """Run `cmd` (a list) and return (exit code, stdout, stderr).

    A missing program is exit 127, as a shell reports it.
    """
    try:
        done = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout,
                              capture_output=True, text=True, input=input_text,
                              check=False)
    except FileNotFoundError:
        if check:
            raise CommandError(cmd, 127, f"{cmd[0]}: command not found") from None
        return 127, "", f"{cmd[0]}: command not found"
    except subprocess.TimeoutExpired:
        if check:
            raise CommandError(cmd, 124, "timed out") from None
        return 124, "", "timed out"
    if check and done.returncode != 0:
        raise CommandError(cmd, done.returncode, done.stderr or done.stdout)
    return done.returncode, done.stdout, done.stderr


def git(cwd, *args, check=True):
    """Run git in `cwd`; return stdout (or (code, out, err) when check=False)."""
    code, out, err = run(["git", *args], cwd=cwd, check=check)
    return out if check else (code, out, err)
