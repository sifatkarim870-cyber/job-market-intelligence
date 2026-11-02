import pathlib, re

path = pathlib.Path("scripts/build_uniform_job_sites_master.py")
text = path.read_text(encoding="utf-8")

old = '    "rekrute.com": "rekrute_com",\n}'
new = '    "rekrute.com": "rekrute_com",\n    "zimbojobs.com": "zimbojobs_com",\n}'

if old in text:
    text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    print("Replaced!")
else:
    print("Pattern not found, trying different line endings...")
    old2 = '    "rekrute.com": "rekrute_com",\r\n}'
    new2 = '    "rekrute.com": "rekrute_com",\r\n    "zimbojobs.com": "zimbojobs_com",\r\n}'
    if old2 in text:
        text = text.replace(old2, new2)
        path.write_text(text, encoding="utf-8")
        print("Replaced with CRLF!")
    else:
        print("Not found.")
        # Show around rekrute.com
        idx = text.find('"rekrute.com"')
        print("Context:", repr(text[idx:idx+60]))
