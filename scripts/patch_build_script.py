import pathlib, re

path = pathlib.Path("scripts/build_uniform_job_sites_master.py")
text = path.read_text(encoding="utf-8")

old = '    "zimbojobs.com": "zimbojobs_com",\n}'
new = '    "zimbojobs.com": "zimbojobs_com",\n    "akhtaboot.com": "akhtaboot_com",\n}'

if old in text:
    text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    print("Replaced!")
else:
    old2 = '    "zimbojobs.com": "zimbojobs_com",\r\n}'
    new2 = '    "zimbojobs.com": "zimbojobs_com",\r\n    "akhtaboot.com": "akhtaboot_com",\r\n}'
    if old2 in text:
        text = text.replace(old2, new2)
        path.write_text(text, encoding="utf-8")
        print("Replaced with CRLF!")
    else:
        print("Not found.")
        idx = text.find('"zimbojobs.com"')
        print("Context:", repr(text[idx:idx+80]))
