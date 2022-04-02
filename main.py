"""Python script to book first available time for getting a passport in Sweden."""

import datetime
import sys
from time import sleep
import tkinter as tk
from random import randint
from tkinter import Tk, messagebox, ttk

from playwright.sync_api import sync_playwright

# Random time between searches in milliseconds (min, max)
RANDOM_WAIT_RANGE = (15_000, 20_000)

# Whether or not to screenshot _before_ confirming booking (it will still screenshot after)
SCREENSHOT_BEFORE_BOOKING = False

LOCATIONS = [
    "blekinge",
    "dalarna",
    "gotland",
    "gavleborg",
    "halland",
    "jamtland",
    "jonkoping",
    "kalmar",
    "kronoberg",
    "norrbotten",
    "skane",
    "stockholm",
    "sodermanland",
    "uppsala",
    "varmland",
    "vasterbotten",
    "vasternorrland",
    "vastmanland",
    "vastragotaland",
    "orebro",
    "ostergotland",
]

root = Tk()
root.title("Passport booker - Svenska polisen")
root.geometry("350x150")
root.bind("<Control-c>", root.quit)

ttk.Label(root, text="Plats (län):").grid(row=0, column=0)
location = tk.StringVar(root)
ttk.OptionMenu(root, location, "stockholm", *LOCATIONS).grid(row=0, column=1)

ttk.Label(root, text="Antal personer:").grid(row=2, column=0)
people = ttk.Entry(root)
people.grid(row=2, column=1)
people.insert(0, "1")

ttk.Label(root, text="Sista möjliga datum:").grid(row=3, column=0)
date_field = ttk.Entry(root)
date_field.grid(row=3, column=1)
dt = datetime.datetime.now().date()
dt += datetime.timedelta(days=60)
date_field.insert(0, dt.strftime("%Y-%m-%d"))

ttk.Button(root, text="Hitta tid", command=root.quit).grid(
    row=4, column=0, columnspan=2
)

root.protocol("WM_DELETE_WINDOW", sys.exit)
root.mainloop()
root.withdraw()

try:
    last_date = datetime.datetime.strptime(date_field.get(), "%Y-%m-%d")
except ValueError:
    print("Felaktigt datum")
    sys.exit(1)

with sync_playwright() as playwright:
    # pass slow_mo=100 to enable slow mo
    browser = playwright.firefox.launch(headless=False)
    browser.on("disconnected", lambda _: sys.exit(1))
    page = browser.new_page()
    page.goto(f"https://bokapass.nemoq.se/Booking/Booking/Index/{location.get()}")
    page.locator('input:has-text("Boka ny tid")').click()
    # Check "Jag har tagit del av informationen ovan"
    page.locator('input[type="checkbox"]').check()

    ppl_selector = page.locator('select[name="NumberOfPeople"]')
    ppl_selector.select_option(people.get())

    page.locator("text=Nästa").click()

    ppl_selector = page.locator('select[name="NumberOfPeople"]')
    ppl_selector.select_option(people.get())
    sleep(10)
    page.locator("text=Nästa").click()
    page.wait_for_load_state("domcontentloaded")
    checkboxes = page.locator("text=Ja, jag bor i Sverige")
    count = checkboxes.count()
    if count != int(people.get()):
        print("Hittade inte alla radioknappar")
        sys.exit(1)
    for i in range(count):
        checkboxes.nth(i).click()

    page.locator("text=Nästa").click()

    page.wait_for_load_state("domcontentloaded")
    expeditions = page.locator('select[name="SectionId"]')
    option_tags = expeditions.locator("option")
    options = list(
        filter(
            None,
            (option_tags.nth(i).text_content() for i in range(option_tags.count())),
        )
    )

    popup = Tk()
    popup.title("Välj passexpedition (ort)")
    popup.geometry("350x150")
    popup.bind("<Control-c>", popup.quit)
    popup.protocol("WM_DELETE_WINDOW", lambda: sys.exit(1))

    ttk.Label(popup, text="Passexpedition:").grid(row=0, column=0)
    expedition = tk.StringVar(popup)
    ttk.OptionMenu(popup, expedition, options[0], *options).grid(row=0, column=1)

    ttk.Button(popup, text="Fortsätt", command=popup.quit).grid(
        row=4, column=0, columnspan=2
    )

    popup.mainloop()
    if popup.winfo_ismapped():
        popup.withdraw()

    expeditions.select_option(label=expedition.get())

    try:
        while browser.is_connected():
            today = datetime.datetime.now().date().strftime("%Y-%m-%d")
            page.locator(':has-text("Datum:") >> input[type="text"]').fill(today)
            closebtn = page.locator("text=Stäng")
            if closebtn.is_visible():
                closebtn.click()

            page.wait_for_load_state("domcontentloaded")
            page.locator('input:has-text("Första lediga tid")').click()

            page.wait_for_load_state("domcontentloaded")
            # if rate limited, wait 5 minutes
            rate_limit = page.locator(
                "text=Du har gjort för många 'första lediga tid' sökningar, "
                "var vänlig och vänta en stund."
            )
            if rate_limit.is_visible():
                print("Du har gjort för många sökningar, programmet väntar 5 min")
                page.wait_for_timeout(300_000)
                continue

            page.goto(f"{page.url}#SectionId", wait_until="domcontentloaded")
            times = page.locator('[data-function="timeTableCell"]')
            for time in (times.nth(i) for i in range(times.count())):
                datestring = time.get_attribute("data-fromdatetime")
                if not datestring:
                    print("En tid saknar datumsträng")
                    sys.exit(1)
                date = datetime.datetime.strptime(datestring, "%Y-%m-%d %H:%M:%S")
                if date < last_date:
                    raw_info = time.locator("../ancestor::table").inner_text()
                    DESCRIPTION = "\n".join(
                        line
                        for line in raw_info.splitlines()
                        if line and len(line) > 2 and line[2] != ":"
                    )
                    time.click()
                    if SCREENSHOT_BEFORE_BOOKING:
                        page.screenshot(path="tider.png", full_page=True)
                    page.locator('[aria-label="submit"]').click()

                    page.wait_for_load_state("domcontentloaded")
                    time_gone = page.locator(
                        "text=Tiden du valde är inte tillgänglig. Var god välj en ny tid."
                    )
                    if time_gone.is_visible():
                        print("Hittad tid är inte längre tillgänglig")
                        page.wait_for_timeout(10_000)
                        break

                    MESSAGE = "\n".join(
                        [
                            f"En ledig bokning {date} har hittats:",
                            DESCRIPTION,
                            "Vill du behålla denna tid?",
                        ]
                    )
                    root.bell()
                    sleep(1.25)
                    root.bell()
                    sleep(1.25)
                    root.bell()
                    keep = messagebox.askyesno("Behåll denna tid?", MESSAGE)
                    if not keep:
                        page.locator("text=Tillbaka").click()
                        break

                    input("Tryck enter när du bokat färdigt för att spara en skärmdump")
                    page.screenshot(path="bokning.png", full_page=True)
            else:
                wait = randint(*RANDOM_WAIT_RANGE)
                print(f"Väntar {(wait / 1000):.2f} sekunder innan nästa försök")
                page.wait_for_timeout(wait)
            # don't wait for timeout when exiting early
    except (KeyboardInterrupt, SystemExit):
        print("trying to quit")
        root.quit()
        popup.quit()
        playwright.stop()
        sys.exit()
