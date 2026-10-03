from selenium import webdriver
from selenium.webdriver.chrome.service import Service

print("start", flush=True)
options = webdriver.ChromeOptions()
for arg in ("--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"):
    options.add_argument(arg)
service = Service(log_output="/tmp/chromedriver.log")
driver = webdriver.Chrome(service=service, options=options)
print("SESSION OK", flush=True)
driver.set_page_load_timeout(15)
driver.get("https://example.com")
print("PAGE:", driver.page_source[:80], flush=True)
driver.quit()
print("DONE", flush=True)
