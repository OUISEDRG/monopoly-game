from pathlib import Path

from playwright.sync_api import expect, sync_playwright


BASE_URL = "http://127.0.0.1:8765"
OUT_DIR = Path("tests/browser/artifacts")


def fill_and_click(page, selector, value=None):
    if value is not None:
        page.locator(selector).fill(value)
    page.locator(selector).click()


with sync_playwright() as p:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    browser = p.chromium.launch(headless=True)
    alice_context = browser.new_context(viewport={"width": 1366, "height": 900})
    bob_context = browser.new_context(viewport={"width": 390, "height": 844})

    alice = alice_context.new_page()
    bob = bob_context.new_page()

    alice.goto(BASE_URL)
    alice.wait_for_load_state("networkidle")
    fill_and_click(alice, "#create-nickname", "Alice")
    alice.locator("#create-btn").click()
    expect(alice.locator("#room-section")).to_be_visible()
    room_code = alice.locator("#room-chip").inner_text().strip()
    assert len(room_code) == 6

    bob.goto(BASE_URL)
    bob.wait_for_load_state("networkidle")
    fill_and_click(bob, "#join-nickname", "Bob")
    fill_and_click(bob, "#room-code", room_code)
    bob.locator("#join-btn").click()
    expect(bob.locator("#room-section")).to_be_visible()

    alice.locator("#ready-btn").click()
    bob.locator("#ready-btn").click()
    expect(alice.locator("#start-btn")).to_be_enabled(timeout=5000)
    alice.locator("#start-btn").click()

    expect(alice.locator("#game-section")).to_be_visible(timeout=5000)
    expect(bob.locator("#game-section")).to_be_visible(timeout=5000)
    expect(alice.locator(".online-cell")).to_have_count(41)
    expect(bob.locator(".online-cell")).to_have_count(41)

    alice.locator("#online-roll-btn").click()
    expect(alice.locator(".online-player-card.current")).to_be_visible(timeout=5000)

    alice.screenshot(path=str(OUT_DIR / "online-desktop.png"), full_page=True)
    bob.screenshot(path=str(OUT_DIR / "online-mobile.png"), full_page=True)

    alice_context.close()
    bob_context.close()
    browser.close()
