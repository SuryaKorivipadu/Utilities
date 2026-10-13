import requests
import pandas as pd
from bs4 import BeautifulSoup

def draw(url):
    html = requests.get(url).text
    soup = BeautifulSoup(html, "html.parser")

    rows = []

    for tr in soup.find_all("tr"):
        cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if cols:
            rows.append(cols)

    df = pd.DataFrame(rows[1:], columns=rows[0])
    df["x-coordinate"] = df["x-coordinate"].astype(int)
    df["y-coordinate"] = df["y-coordinate"].astype(int)
    n = df["x-coordinate"].max()+1
    m = df["y-coordinate"].max()+1
    matrix = [[0] * n for _ in range(m)]
    for row in df.iterrows():
        x = row[1]["x-coordinate"]
        y = row[1]["y-coordinate"]
        matrix[y][x] = row[1]["Character"]
    # matrix = matrix[::-1]
    for row in matrix:
        print("".join([str(cell) for cell in row if cell != 0]))
        print("")

draw("https://docs.google.com/document/d/e/2PACX-1vSvM5gDlNvt7npYHhp_XfsJvuntUhq184By5xO_pA4b_gCWeXb6dM6ZxwN8rE6S4ghUsCj2VKR21oEP/pub")