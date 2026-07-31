"""Execute gateway scripts safely with asyncio."""

import asyncio
import logging

from config import SCRIPTS

logger = logging.getLogger(__name__)

# Global lock — one script at a time to prevent concurrent iptables/ipset modifications
_lock = asyncio.Lock()


class ScriptResult:
    def __init__(self, exit_code: int, output: str):
        self.exit_code = exit_code
        self.output = output
        self.success = exit_code == 0


async def run_script(name: str) -> ScriptResult:
    """Run a whitelisted script by name. Returns ScriptResult."""
    if name not in SCRIPTS:
        return ScriptResult(1, f"Unknown script: {name}")

    script_path = SCRIPTS[name]
    if not script_path.exists():
        return ScriptResult(1, f"Script not found: {script_path}")

    async with _lock:
        logger.info("Running script: %s (%s)", name, script_path)
        try:
            proc = await asyncio.create_subprocess_exec(
                str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
            output = stdout.decode("utf-8", errors="replace")
            logger.info("Script %s finished with exit code %d", name, proc.returncode)
            return ScriptResult(proc.returncode, output)
        except asyncio.TimeoutError:
            proc.kill()
            return ScriptResult(1, "Script timed out after 120 seconds")
        except Exception as e:
            return ScriptResult(1, f"Script execution error: {e}")


async def run_command(*args: str, timeout: int = 30) -> ScriptResult:
    """Run an arbitrary command with arguments (no shell). For system queries."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode("utf-8", errors="replace")
        return ScriptResult(proc.returncode, output)
    except asyncio.TimeoutError:
        proc.kill()
        return ScriptResult(1, f"Command timed out after {timeout}s")
    except Exception as e:
        return ScriptResult(1, f"Command error: {e}")
