"""
webagent.py
Gemini Computer Use + Playwright browser agent for Hope.
Streams screenshots into BROWSE_STATE for the live browser panel.
State is written to disk so gunicorn workers can share it.
Uses DuckDuckGo instead of Google to avoid captcha walls.
"""
from __future__ import annotations

import os
import time
import json
import asyncio
import base64
from pathlib import Path
from typing import Optional, Dict, Any

SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 800
MODEL_ID = os.getenv("GEMINI_CU_MODEL", "gemini-2.5-computer-use-preview-10-2025")
MAX_TURNS = int(os.getenv("WEBAGENT_MAX_TURNS", "12"))
HEADLESS = os.getenv("WEBAGENT_HEADLESS", "true").lower() != "false"

# Prefer DuckDuckGo — Google often captchas Railway / datacenter IPs
START_URL = os.getenv("WEBAGENT_START_URL", "https://duckduckgo.com")
SEARCH_URL = os.getenv("WEBAGENT_SEARCH_URL", "https://duckduckgo.com")

BLOCKED_HOST_PARTS = (
    "accounts.google.com",
    "login",
    "signin",
    "checkout",
    "paypal.com",
    "stripe.com",
)

# Shared across gunicorn workers via disk
_BROWSE_STATE_PATH = Path(os.getenv("HOPE_BROWSE_STATE", "/tmp/hope_browse_state.json"))

BROWSE_STATE: Dict[str, Any] = {
    "active": False,
    "image": None,  # base64 PNG (no data: prefix)
    "log": "",
    "url": "",
    "updated_at": 0.0,
}

def _write_browse_state():
    try:
        _BROWSE_STATE_PATH.write_text(json.dumps(BROWSE_STATE), encoding="utf-8")
    except Exception as e:
        print(f"[WebAgent] state write failed: {e}")

def _set_browse_state(image_b64: Optional[str] = None, log: str = "", url: str = ""):
    if image_b64 is not None:
        BROWSE_STATE["image"] = image_b64
    if log:
        BROWSE_STATE["log"] = log
    if url:
        BROWSE_STATE["url"] = url
    BROWSE_STATE["updated_at"] = time.time()
    _write_browse_state()

def get_browse_state() -> Dict[str, Any]:
    try:
        if _BROWSE_STATE_PATH.exists():
            data = json.loads(_BROWSE_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"[WebAgent] state read failed: {e}")
    return dict(BROWSE_STATE)

def _gemini_key() -> str:
    return (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    ).strip()

def denormalize_x(x: int, width: int) -> int:
    return int((int(x) / 1000) * width)

def denormalize_y(y: int, height: int) -> int:
    return int((int(y) / 1000) * height)

class WebAgent:
    def __init__(self):
        self.client = None
        self.browser = None
        self.context = None
        self.page = None

    def _blocked_url(self, url: str) -> bool:
        u = (url or "").lower()
        return any(part in u for part in BLOCKED_HOST_PARTS)

    async def execute_function_calls(self, function_calls):
        results = []
        for call in function_calls:
            call_id = getattr(call, "id", None)
            fn_name = call.name
            args = dict(call.args or {})
            print(f"[WebAgent] Action: {fn_name} {args}")

            requires_acknowledgement = False
            if "safety_decision" in args:
                decision = args.get("safety_decision") or {}
                if decision.get("decision") == "require_confirmation":
                    explanation = decision.get("explanation") or ""
                    print(f"[WebAgent] Safety: {explanation}")
                    low = explanation.lower()
                    if any(w in low for w in ("password", "login", "purchase", "pay", "credit card")):
                        results.append((call_id, fn_name, {"error": "Blocked safety-sensitive action"}))
                        continue
                    requires_acknowledgement = True

            result_data = {}
            try:
                if fn_name == "open_web_browser":
                    pass
                elif fn_name == "navigate":
                    url = args.get("url") or ""
                    # Soft-redirect Google search → DuckDuckGo to avoid captcha
                    low = url.lower()
                    if "google.com/search" in low or low.rstrip("/") in (
                        "https://www.google.com",
                        "http://www.google.com",
                        "https://google.com",
                        "http://google.com",
                    ):
                        url = SEARCH_URL
                    if self._blocked_url(url):
                        result_data = {"error": f"Blocked navigation: {url}"}
                    else:
                        await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                elif fn_name == "go_back":
                    await self.page.go_back()
                elif fn_name == "go_forward":
                    await self.page.go_forward()
                elif fn_name == "search":
                    await self.page.goto(SEARCH_URL, wait_until="domcontentloaded")
                elif fn_name == "wait_5_seconds":
                    await asyncio.sleep(5)
                elif fn_name == "click_at":
                    x = denormalize_x(args["x"], SCREEN_WIDTH)
                    y = denormalize_y(args["y"], SCREEN_HEIGHT)
                    await self.page.mouse.click(x, y)
                elif fn_name == "type_text_at":
                    x = denormalize_x(args["x"], SCREEN_WIDTH)
                    y = denormalize_y(args["y"], SCREEN_HEIGHT)
                    text = args.get("text", "")
                    press_enter = args.get("press_enter", False)
                    clear_before = args.get("clear_before_typing", True)
                    await self.page.mouse.click(x, y)
                    if clear_before:
                        await self.page.keyboard.press("Control+A")
                        await self.page.keyboard.press("Backspace")
                    await self.page.keyboard.type(text, delay=20)
                    if press_enter:
                        await self.page.keyboard.press("Enter")
                elif fn_name == "hover_at":
                    x = denormalize_x(args["x"], SCREEN_WIDTH)
                    y = denormalize_y(args["y"], SCREEN_HEIGHT)
                    await self.page.mouse.move(x, y)
                elif fn_name == "drag_and_drop":
                    start_x = denormalize_x(args["x"], SCREEN_WIDTH)
                    start_y = denormalize_y(args["y"], SCREEN_HEIGHT)
                    end_x = denormalize_x(args["destination_x"], SCREEN_WIDTH)
                    end_y = denormalize_y(args["destination_y"], SCREEN_HEIGHT)
                    await self.page.mouse.move(start_x, start_y)
                    await self.page.mouse.down()
                    await self.page.mouse.move(end_x, end_y)
                    await self.page.mouse.up()
                elif fn_name == "key_combination":
                    await self.page.keyboard.press(args.get("keys") or "")
                elif fn_name in ("scroll_document", "scroll_at"):
                    magnitude = int(args.get("magnitude", 800))
                    direction = args.get("direction", "down")
                    if fn_name == "scroll_at":
                        x = denormalize_x(args["x"], SCREEN_WIDTH)
                        y = denormalize_y(args["y"], SCREEN_HEIGHT)
                        await self.page.mouse.move(x, y)
                    dx, dy = 0, 0
                    if direction == "down":
                        dy = magnitude
                    elif direction == "up":
                        dy = -magnitude
                    elif direction == "right":
                        dx = magnitude
                    elif direction == "left":
                        dx = -magnitude
                    await self.page.mouse.wheel(dx, dy)
                else:
                    print(f"[WebAgent] Unimplemented: {fn_name}")
                    result_data = {"warning": f"unimplemented:{fn_name}"}

                await asyncio.sleep(0.8)

                # If we somehow landed on a blocked page, bounce to DuckDuckGo (not Google)
                if self._blocked_url(self.page.url):
                    await self.page.goto(START_URL, wait_until="domcontentloaded")
                    result_data = {"error": "Left a blocked page"}
            except Exception as e:
                print(f"[WebAgent] Error {fn_name}: {e}")
                result_data = {"error": str(e)}

            if requires_acknowledgement:
                result_data["safety_acknowledgement"] = True
            results.append((call_id, fn_name, result_data))
        return results

    async def get_function_responses(self, results):
        from google.genai import types

        screenshot_bytes = await self.page.screenshot(type="png")
        current_url = self.page.url
        function_responses = []
        for call_id, name, result in results:
            response_data = {"url": current_url}
            response_data.update(result)
            function_responses.append(
                types.FunctionResponse(
                    name=name,
                    id=call_id,
                    response=response_data,
                    parts=[
                        types.FunctionResponsePart(
                            inline_data=types.FunctionResponseBlob(
                                mime_type="image/png",
                                data=screenshot_bytes,
                            )
                        )
                    ],
                )
            )
        return function_responses, screenshot_bytes

    async def run_task(self, prompt: str, update_callback=None) -> str:
        from google import genai
        from google.genai import types
        from playwright.async_api import async_playwright

        key = _gemini_key()
        if not key:
            return "Browser agent is offline, sir — set GEMINI_API_KEY on Railway."

        self.client = genai.Client(api_key=key)
        final_response = "I opened the web, boss, but didn’t get a clean summary."
        last_url = ""
        print(f"[WebAgent] Goal: {prompt}")

        async def _emit(image_bytes: Optional[bytes], log: str, url: str = ""):
            b64 = base64.b64encode(image_bytes).decode("utf-8") if image_bytes else None
            _set_browse_state(b64, log, url)
            if update_callback:
                try:
                    maybe = update_callback(b64, log, url)
                    if asyncio.iscoroutine(maybe):
                        await maybe
                except Exception as e:
                    print(f"[WebAgent] update_callback error: {e}")

        async with async_playwright() as p:
            self.browser = await p.chromium.launch(headless=HEADLESS)
            self.context = await self.browser.new_context(
                viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="America/New_York",
            )
            self.page = await self.context.new_page()
            await self.page.goto(START_URL, wait_until="domcontentloaded")

            config = types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        computer_use=types.ComputerUse(
                            environment=types.Environment.ENVIRONMENT_BROWSER
                        )
                    )
                ]
            )

            initial_screenshot = await self.page.screenshot(type="png")
            await _emit(initial_screenshot, "Browser opened", self.page.url)

            chat_history = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=(
                                "You are Hope's web browser. Complete this task, then give a short "
                                "spoken-friendly summary of what you found.\n"
                                "Rules:\n"
                                "- Do not log into accounts or complete purchases.\n"
                                "- Prefer opening direct URLs when the user names a site.\n"
                                "- If you need a search engine, use DuckDuckGo (not Google).\n"
                                "- Avoid Google if possible — it often blocks this browser.\n\n"
                                "TASK:\n" + prompt
                            )
                        ),
                        types.Part.from_bytes(data=initial_screenshot, mime_type="image/png"),
                    ],
                )
            ]

            for turn in range(MAX_TURNS):
                print(f"[WebAgent] Turn {turn + 1}")
                try:
                    response = await self.client.aio.models.generate_content(
                        model=MODEL_ID,
                        contents=chat_history,
                        config=config,
                    )
                except Exception as e:
                    print(f"[WebAgent] API error: {e}")
                    final_response = f"Browser agent error, sir: {e}"
                    await _emit(None, f"Error: {e}")
                    break

                if not getattr(response, "candidates", None):
                    break

                model_content = response.candidates[0].content
                chat_history.append(model_content)

                agent_text = ""
                for part in model_content.parts:
                    if getattr(part, "text", None) and not getattr(part, "thought", False):
                        agent_text = part.text
                if agent_text:
                    final_response = agent_text

                function_calls = [
                    part.function_call
                    for part in model_content.parts
                    if getattr(part, "function_call", None)
                ]
                if not function_calls:
                    print("[WebAgent] Done")
                    try:
                        shot = await self.page.screenshot(type="png")
                        await _emit(shot, "Task finished", self.page.url)
                    except Exception:
                        await _emit(None, "Task finished", last_url)
                    break

                results = await self.execute_function_calls(function_calls)
                function_responses, shot = await self.get_function_responses(results)
                last_url = self.page.url
                actions_log = ", ".join([r[1] for r in results])
                await _emit(shot, f"Turn {turn + 1}: {actions_log}", last_url)

                response_parts = [types.Part(function_response=fr) for fr in function_responses]
                chat_history.append(types.Content(role="user", parts=response_parts))

            try:
                last_url = self.page.url
            except Exception:
                pass
            await self.browser.close()

        if last_url:
            return f"{final_response}\n\nSource: {last_url}"
        return final_response

def browse_sync(prompt: str, timeout_sec: int = 90) -> str:
    """Sync wrapper so Flask / liveweb can call this."""
    BROWSE_STATE["active"] = True
    BROWSE_STATE["image"] = None
    BROWSE_STATE["log"] = "Starting browser..."
    BROWSE_STATE["url"] = ""
    BROWSE_STATE["updated_at"] = time.time()
    _write_browse_state()

    async def _run():
        agent = WebAgent()
        return await agent.run_task(prompt)

    try:
        return asyncio.run(asyncio.wait_for(_run(), timeout=timeout_sec))
    except asyncio.TimeoutError:
        return "That page took too long to finish browsing, boss. Try a more specific site."
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(asyncio.wait_for(_run(), timeout=timeout_sec))
        finally:
            loop.close()
    except Exception as e:
        print(f"[WebAgent] browse_sync error: {e}")
        return f"Couldn’t surf that right now, sir: {e}"
    finally:
        BROWSE_STATE["active"] = False
        BROWSE_STATE["log"] = BROWSE_STATE.get("log") or "Browser closed"
        BROWSE_STATE["updated_at"] = time.time()
        _write_browse_state()
