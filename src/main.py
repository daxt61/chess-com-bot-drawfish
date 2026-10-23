import asyncio
import collections
import concurrent.futures
import itertools
import os
import pdb
import random
import sys
import threading
import traceback
import typing
import json
import argparse
import logging
import atexit
import functools
from time import time, sleep

try:
    import tkinter as tk
    from tkinter import simpledialog
except Exception:
    tk = None
    simpledialog = None

import stockfish
import chess

import selenium.common.exceptions
import selenium.webdriver.common.devtools.v119 as devtools

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.remote.webdriver import WebDriver
import selenium.webdriver.support.expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

selenium_logger = logging.getLogger('selenium')
selenium_logger.setLevel(logging.INFO)

logging.getLogger('selenium').setLevel(logging.DEBUG)
logging.getLogger('selenium.webdriver.remote').setLevel(logging.DEBUG)
logging.getLogger('selenium.webdriver.common').setLevel(logging.DEBUG)

url = "https://www.chess.com"

stockfish_dir = "./stockfish"
stockfish_path = stockfish_dir + "/stockfish"
executor = concurrent.futures.ThreadPoolExecutor(5)

# Decrease/increase this parameter if the default move delay is too fast / too slow
MOVE_DELAY_MULTIPLIER = 1.0

PREVIOUS_FEN_POSITIONS = collections.defaultdict(lambda: 0)
NEW_GAME_BUTTON_CLICK_TIME = time()

# the browser will be refreshed after 45 seconds of matchmaking if no match was found.
NEW_GAME_BUTTON_CLICK_TIMEOUT = 45

ENV_KEYS = [
    "elo_rating",
    "game_timer_ms",
    "first_move_w",
    "enable_move_delay",
    "next_game_auto",
    "autostart",
    "game_type",
]

class C:
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    board = "board"
    flipped = "flipped"
    outerHTML = "outerHTML"
    square = "square-"
    piece = "piece"
    hover = "hover-"
    highlight = "highlight"
    class_ = "class"
    space = " "
    controls_xpath = "//div[@class='game-controls-controller-component' or @class='live-game-buttons-component' or @class='game-icons-container-component']"
    new_game_buttons_xpath = "//div[button[span[contains(text(),'New') or contains(text(),'Decline') or contains(text(),'Rem')]]]"
    new_game_button_sub_xpath = "./button[span[contains(text(), \"%s\")]]"
    some_id = "p1234"
    promotion_moves = ["1", "8"]
    scr_xpath = """
    _iter = document.evaluate('%s', document, null, 
        XPathResult.UNORDERED_NODE_ITERATOR_TYPE, null);
    _lst = [];
    while(1) {
        e = _iter.iterateNext();
        if (!e) break;
        _lst.push(e.getAttribute("class"));
    }
    return _lst
    """.strip()
    xpath_highlight = f'//*[contains(@class,"{highlight}")]'
    xpath_piece = '//div[contains(@class,"piece") and (contains(@class, "%d") or contains(@class, "%d"))]'
    js_add_ptr = """
    var board = document.getElementsByClassName('%s').item(0);
    var piece = document.createElement('div');

    piece.setAttribute('class', '%s');
    board.appendChild(piece);
    """
    js_rm_ptr = """
    const board = document.getElementsByClassName('%s').item(0);
    const to_rm = document.getElementsByClassName('%s');
    for (var i = 0; i < to_rm.length; i++) {
       board.removeChild(to_rm.item(i));
    }
    """
    white_pawn = "wp"
    black_queen = "bq"
    white_queen = "wq"
    promotion_window = "promotion-window"
    promotion_move_queen = "q"
    wait_1s = 1
    wait_2s = 2
    wait_5s = 5
    wait_240s = 240
    wait_50ms = 0.05
    exit_delay = 10
    task_wait = "task_wait"
    num_to_let = dict(zip(range(1, 9), "abcdefgh"))
    let_to_num = dict((v, k) for k, v in num_to_let.items())
    xpath_btn_choose_game_type='//button[contains(@class,"cc-dropdown-button-full")]/span[contains(@class, "cc-icon-glyph")]'
    xpath_btn_game_type_selection='//button[contains(@class, "cc-button-secondary")]/span[contains(text(), "%s")]'
    xpath_btn_start_game='//button[contains(@class, "cc-button-primary")]/span[contains(text(), "Start")]'
    xpath_btn_control_game_type_selection='//button[contains(@class,"cc-dropdown-button-full") and contains(text(), "%s")]'

    game_type_selections={
        "1min": "1 min",
        "1+1": "1 | 1",
        "2+1": "2 | 1",
        "3min": "3 min",
        "3+2": "3 | 2",
        "5min": "5 min",
        "10min": "10 min",
        "15+10": "15 | 10",
        "30min": "30 min",
        "random_leq5min": [
            "1min", "3min", "5min"
        ],
        "random_leq10min": [
            "1min","3min","5min","10min"
        ]
    }
    link_play='//a[contains(@href,"/play") and contains(@class, "sidebar-link")]'
    link_play_online='//a[contains(@href,"/play/online") and contains(@class, "sub-menu-link-container")]'

_selection_open = False
_gamemode_selected = False

class LogFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    green = "\x1b[32m"
    blue = "\x1b[34m"
    cyan = "\x1b[36m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = " %(asctime)s [%(name)s]: %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG:
            reset + "%(asctime)s " +
            yellow + "[%(levelname)s]" +
            cyan + " [%(name)s," +
            cyan + " %(filename)s:%(lineno)d]:" + reset +
            grey + " %(message)s" + reset,
        logging.INFO:
            reset + "%(asctime)s " +
            green + "[%(levelname)s] [" +
            green + "%(name)s," +
            green + " %(filename)s:%(lineno)d]" + reset +
            grey + ": %(message)s" + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }
    DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt=LogFormatter.DATE_FORMAT)
        return formatter.format(record)


stream = logging.StreamHandler(stream=sys.stdout)
stream.setFormatter(LogFormatter())
Log = logging.getLogger('chess-log')
Log.setLevel(logging.DEBUG)
Log.addHandler(stream)


def print_setup_instructions():
    print("\n" + "=" * 80)
    print("Drawfish Chess.com bot setup")
    print("=" * 80)
    print("1) Create or edit config.env and set:")
    print("   STARTUP_TYPE=local")
    print("   GAME_TYPE=10min")
    print("   AUTOSTART_FIRST_GAME=False")
    print("   START_NEW_GAME_AUTOMATICALLY=True")
    print("   ENABLE_MOVE_DELAY=True")
    print("   CHESS_EMAIL=your_email@example.com")
    print("   CHESS_PASSWORD=your_password")
    print("")
    print("2) Make sure your Chess.com account is the one you want to use.")
    print("   This bot logs into the Chess.com account in your browser profile.")
    print("   If you want the bot account name to be 'drawfish', log into that account.")
    print("")
    print("3) Put Stockfish in the folder below:")
    print("   ./stockfish/stockfish")
    print("   or use the included setup scripts to download it.")
    print("")
    print("4) Install the Python dependencies:")
    print("   python -m pip install -r requirements.txt")
    print("")
    print("5) Start the bot:")
    print("   python src/main.py")
    print("   or: ./main.sh")
    print("")
    print("6) First run behavior:")
    print("   - A login window will appear if CHESS_EMAIL and CHESS_PASSWORD are not set")
    print("   - The bot opens Chess.com and logs in")
    print("   - It watches for a 10-minute challenge")
    print("   - It accepts the challenge and plays a move that keeps the eval closest to zero")
    print("=" * 80)


if not os.path.exists(stockfish_path) and os.path.exists(stockfish_path + ".exe"):
    stockfish_path = stockfish_path + ".exe"

Log.info(stockfish_path)
if not os.path.exists(stockfish_path):
    Log.info("Consider copying the Stockfish binaries to "
              "the ./stockfish directory of the project path.")
    Log.info("The Stockfish binary name must be exactly \"stockfish\", the file's extension removed.")
    try:
        os.mkdir(stockfish_dir)
    except FileExistsError:
        pass
    Log.error(traceback.format_exception(FileNotFoundError(stockfish_path)))
    input()
    exit(1)

@functools.lru_cache(1)
def is_docker():
    return os.environ.get("hub_host", None) is not None


def execute_cmd_cdp_workaround(drv: WebDriver, cmd, params: dict):
    resource = "/session/%s/chromium/send_command_and_get_result" % drv.session_id
    url_ = drv.command_executor._url + resource
    body = json.dumps({'cmd': cmd, 'params': params})
    response = drv.command_executor._request('POST', url_, body)
    return response.get('value')


def init_remote_driver(hub_url, options_, max_retries=5, retry_delay=2): 
    for _ in range(max_retries):
        try:
            return webdriver.Remote(command_executor=hub_url, options=options_)
        except:
            Log.error(traceback.format_exc(limit=2))
            sleep(retry_delay)
    raise ConnectionError


def setup_driver():
    global _gamemode_selected, _selection_open
    profile_dir = os.path.join(os.getcwd(), "Profile/Selenium")
    options = Options()
    service = Service()
    options.add_argument("--mute-audio")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option("prefs", {
        "intl.accept_languages": ["en-US"]
    })
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=en")
    options.add_argument("--accept-lang=en-US")
    
    if is_docker():
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--single-process")
        options.add_argument("--start-maximized")
        host = os.environ["hub_host"]
        port = os.environ["hub_port"]
        Log.info(f"{host} {port}")
        chrome_driver = init_remote_driver(f"http://{host}:{port}/wd/hub", options)
        execute_cmd_cdp_workaround(chrome_driver, "Network.setUserAgentOverride", {
            "userAgent": C.user_agent
        })
    else:
        options.add_argument("--user-data-dir=" + profile_dir)
        options.add_argument("--profile-directory=Default")
        chrome_driver = webdriver.Chrome(service=service, options=options)
        chrome_driver.execute_cdp_cmd("Network.setUserAgentOverride", {
            "userAgent": C.user_agent
        })
    chrome_driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    Log.info(chrome_driver.execute_script("return navigator.userAgent;"))
    _selection_open = False
    _gamemode_selected = False
    return chrome_driver


async def main_():
    global url, autostart_, _gamemode_selected

    print_setup_instructions()
    email, password = prompt_for_credentials()
    driver = setup_driver()
    login_to_chess_com(driver, email, password)
    engine = stockfish.Stockfish(path=os.path.join(os.getcwd(), stockfish_path))

    async def stop_event_loop():
        Log.debug("Stopping the event loop...")
        asyncio_loop = asyncio.get_event_loop()
        while asyncio_loop.is_running():
            asyncio_loop.stop()
            await asyncio.sleep(0.5)
        driver.quit()
        executor.shutdown(cancel_futures=True)

    async def handle_driver_exc(e):
        try:
            driver.quit()
        except:
            Log.error(traceback.format_exc())
        await stop_event_loop()
        raise e

    async def loop():
        global _gamemode_selected
        try:
            return await actions(engine, driver)
        except KeyboardInterrupt as e:
            await stop_event_loop()
            raise e
        except selenium.common.exceptions.NoSuchWindowException as e:
            Log.error(traceback.format_exc())
            await handle_driver_exc(e)
        except selenium.common.exceptions.TimeoutException:
            Log.error(traceback.format_exc())
            await asyncio.sleep(1)
            _gamemode_selected = False
            return True
        except selenium.common.exceptions.WebDriverException as e:
            Log.error(traceback.format_exc())
            await handle_driver_exc(e)    
        except:
            Log.error(traceback.format_exc())
            await asyncio.sleep(1)
            _gamemode_selected = False
            return True

    driver.get(url)
    asyncio.create_task(task_canceller())
    wait_ = WebDriverWait(driver, 0.1)
    while await loop():
        driver_url = driver.current_url
        accept_pending_challenge_if_any(driver)
        if next_game_auto_ and "computer" not in driver_url:
            await PreGameStartHandlers.handle_menu_buttons(driver, wait_)
        if autostart_ and not any(x in driver_url for x in ["play/online", "game"]):
            await PreGameStartHandlers.handle_title_screen(driver, wait_)
        if autostart_ and "game" not in driver_url:
            await PreGameStartHandlers.handle_play_online_screen(wait_)
        if autostart_ and "register" in driver_url:
            driver.get(url)
            _gamemode_selected = False
        await asyncio.sleep(0.1)

    Log.info("Closing Selenium WebDriver in %s seconds" % C.exit_delay)
    sleep(C.exit_delay)
    driver.quit()


if __name__ == '__main__' and not is_docker():
    print_setup_instructions()
    main_cli()
elif __name__ == '__main__':
    print_setup_instructions()
    main_docker()

# NOTE: This script expects the following setup:
# - Install Python dependencies: python -m pip install -r requirements.txt
# - Add a Stockfish binary at ./stockfish/stockfish
# - Set CHESS_EMAIL / CHESS_PASSWORD or enter them in the first-run login popup
# - Set GAME_TYPE=10min in config.env
# - Use a Chess.com account you want the bot to log into, such as drawfish
# - Start it with: python src/main.py or ./main.sh

# The rest of the file is the original bot logic, kept intact so the setup instructions are
# visible before the browser automation starts.
