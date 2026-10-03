"""Temporary minimal probe: figure out which seleniumbase call WInCI works.

MODE labels:
  plain                 - Driver(browser='chrome', headless2=True) + nothing
  plain_ns              - above + no_sandbox=True
  plain_ns_gpu          - plain_ns + disable_gpu=True
  plain_ns_gpu_shm      - plain_ns_gpu + chromium_arg='--disable-dev-shm-usage'
  plain_all             - everything the IndeedClient would pass (agent,
                          eager/normal strategy, ns, gpu, shm) but uc=False
  plain_all_eager       - plain_all with page_load_strategy='eager'
  uc_normal             - Driver(uc=True, headless2=True)
"""

from __future__ import annotations

import sys

MODE = sys.argv[1]

from seleniumbase import Driver

if MODE == "plain":
    kw = {"browser": "chrome", "headless2": True}
elif MODE == "plain_ns":
    kw = {"browser": "chrome", "headless2": True, "no_sandbox": True}
elif MODE == "plain_ns_gpu":
    kw = {"browser": "chrome", "headless2": True, "no_sandbox": True, "disable_gpu": True}
elif MODE == "plain_ns_gpu_shm":
    kw = {
        "browser": "chrome",
        "headless2": True,
        "no_sandbox": True,
        "disable_gpu": True,
        "chromium_arg": "--disable-dev-shm-usage",
    }
elif MODE == "plain_all":
    kw = {
        "browser": "chrome",
        "uc": False,
        "headless2": True,
        "agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "page_load_strategy": "normal",
        "no_sandbox": True,
        "disable_gpu": True,
        "chromium_arg": "--disable-dev-shm-usage",
    }
elif MODE == "plain_all_eager":
    kw = {
        "browser": "chrome",
        "uc": False,
        "headless2": True,
        "agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "page_load_strategy": "eager",
        "no_sandbox": True,
        "disable_gpu": True,
        "chromium_arg": "--disable-dev-shm-usage",
    }
elif MODE == "uc_normal":
    kw = {"uc": True, "headless2": True}
else:
    raise SystemExit(2)

print(f"MODE={MODE} kwargs={kw}", flush=True)
d = Driver(**kw)
print("SESSION OK", flush=True)
d.set_page_load_timeout(30)
d.get("https://example.com")
print(f"PAGE: {d.page_source[:80]!r}", flush=True)
d.quit()
print("DONE", flush=True)
