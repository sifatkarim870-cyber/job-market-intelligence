"""Diagnostic: which Chrome flag set actually starts a session on the CI runner?

Run via .github/workflows/indeed_uc_probe.yml. Not imported by anything.

Each variant is tried in a SEPARATE process (one python invocation per
variant, from the calling workflow) so a wedged or half-crashed browser can't
take the next attempt down with it. Prints one unambiguous line per attempt:

    PROBE <name>: OK elapsed=<n>s
    PROBE <name>: FAIL(<ExceptionClass>) elapsed=<n>s <first line of message>
"""

import sys
import time
import tracemalloc

from selenium import webdriver
from selenium.webdriver.chrome.service import Service

VARIANTS = {
    # The set client.py used originally, which worked in the probe (45s) but
    # then began failing on the real run. Kept as the control.
    "minimal": ["--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
    # Same, minus --disable-gpu: on a VM with no GPU, --disable-gpu still
    # forces Chrome to initialise its GPU process, which is one more
    # multi-process child competing for a very small RAM budget.
    "no-gpu-flag": ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage"],
    # --disable-dev-shm-usage makes Chrome write shared memory to /tmp
    # instead of /dev/shm. On a runner where /dev/shm is tiny this is the
    # difference between working and dying in the renderer, so try WITHOUT it
    # too: /dev/shm being correctly sized would make this flag unnecessary.
    "real-shm": ["--headless=new", "--no-sandbox", "--disable-gpu"],
    # Cap renderer processes. Chrome spawns one process per site/tab and
    # preallocates generously; on an ~800MiB VM the whole browser can be
    # OOM-killed before DevToolsActivePort is ever written, which is exactly
    # the "DevToolsActivePort file doesn't exist" failure.
    "single-renderer": [
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--renderer-process-limit=1",
    ],
    # Last resort, and genuinely known to be unstable in Chrome: one process
    # for everything. Only here to find out whether the VM is simply too
    # small for a normal multi-process headless Chrome.
    "single-process": [
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--single-process",
    ],
    # Old headless is a much smaller process than the new one (no full
    # browser UI stack). Chrome still accepts --headless=old in most 15x
    # builds; included to find out whether size, not flags, is the problem.
    "old-headless": [
        "--headless=old",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
    ],
}


def main() -> int:
    name = sys.argv[1]
    args = VARIANTS[name]
    print(f"PROBE {name}: args={' '.join(args)}", flush=True)
    tracemalloc.start()
    started = time.monotonic()
    driver = None
    try:
        driver = webdriver.Chrome(
            options=_options(args),
            service=Service(log_output="/tmp/chromedriver.log"),
        )
        elapsed = time.monotonic() - started
        _, peak = tracemalloc.get_traced_memory()
        print(
            f"PROBE {name}: OK elapsed={elapsed:.0f}s peak_py={peak // 1024 // 1024}MiB",
            flush=True,
        )
        driver.quit()
        return 0
    except Exception as exc:  # noqa: BLE001 - a probe reports everything
        elapsed = time.monotonic() - started
        message = str(exc).strip().splitlines()
        print(
            f"PROBE {name}: FAIL({type(exc).__name__}) elapsed={elapsed:.0f}s "
            f"{message[0] if message else ''}",
            flush=True,
        )
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        return 1


def _options(args: list[str]):
    options = webdriver.ChromeOptions()
    for arg in args:
        options.add_argument(arg)
    return options


if __name__ == "__main__":
    raise SystemExit(main())
