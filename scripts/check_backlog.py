import openpyxl

wb = openpyxl.load_workbook(r"D:\Research_Project\JobMarketAnalysisPlatform\job_sites_uniform_master.xlsx", data_only=True)
ws = wb["Master Directory"]

headers = [ws.cell(4, c).value for c in range(1, ws.max_column+1)]
status_col = headers.index("GitHub Status") + 1
code_col = headers.index("GitHub Code") + 1
domain_col = headers.index("Domain") + 1
name_col = headers.index("Site / Portal Name") + 1
region_col = headers.index("Primary Region") + 1

backlog = []
for r in range(5, ws.max_row+1):
    status = str(ws.cell(r, status_col).value or "")
    if "Backlog" in status or "backlog" in status.lower():
        domain = str(ws.cell(r, domain_col).value or "").strip()
        if domain and "." in domain:
            row_data = {
                "row": r,
                "name": ws.cell(r, name_col).value,
                "domain": domain,
                "region": str(ws.cell(r, region_col).value or ""),
                "status": status,
            }
            backlog.append(row_data)

print(f"\nBacklog sites with domain: {len(backlog)}")
for b in backlog[:50]:
    print(f"  [{b['row']:3d}] {b['domain']:35s} | {b['region'][:25]}")
