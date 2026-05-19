#!/usr/bin/env python3
"""
GoLogin Account Creator Telegram Bot (CaptchaAI)
Commands:
  /get      - Start the account creation process (if not already running)
  /stop     - Stop the process gracefully
  /stats    - Show current statistics
  /sendresults - Send the proxies.txt file as a document (does not stop the process)
"""

import asyncio
import logging
import os
import random
import threading
import time
from datetime import datetime
from urllib.parse import urlparse

import requests
import urllib3
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------- Configuration ----------
# Set your bot token as environment variable or hardcode (not recommended)
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8351621086:AAEJTmQPqEC8w5LVqRfQNB1Ft43jMGAsec4")

# GoLogin / CaptchaAI settings
fp = {
    'fontsHash': 'a1b2c3d4e5f6g7h8',
    'canvasHash': '1234567890',
    'canvasAndFontsHash': 'x9y8z7w6v5u4t3s2',
    'os': 'win',
    'osSpec': 'win11'
}
ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36'
ixcynigga_api = "https://api.gologin.com"

# Updated CaptchaAI API key
captchaai_api_key = "jtmrtfrkvkgyd9wd0jbbckjsdkgsptrv"

# File paths
PROXIES_FILE = 'proxies.txt'
ACCOUNTS_FILE = 'accounts.txt'
STATS_FILE = 'stats.txt'
BAD_PROXIES_FILE = 'bad_proxies.txt'

# ---------- Logging ----------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- Proxy Manager (thread‑safe) ----------
class ProxyManager:
    def __init__(self, proxy_file=PROXIES_FILE):
        self.proxy_file = proxy_file
        self.proxies = []
        self.current_index = 0
        self.lock = threading.Lock()
        self.bad_proxies = set()
        self.load_proxies()

    def load_proxies(self):
        with self.lock:
            self.proxies = []
            if not os.path.exists(self.proxy_file):
                return
            with open(self.proxy_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and line not in self.bad_proxies:
                        self.proxies.append(line)
            seen = set()
            unique = []
            for p in self.proxies:
                if p not in seen:
                    seen.add(p)
                    unique.append(p)
            self.proxies = unique
            logger.info(f"[ProxyManager] Loaded {len(self.proxies)} working proxies")

    def get_next_proxy(self):
        with self.lock:
            if not self.proxies:
                return None
            proxy_str = self.proxies[self.current_index % len(self.proxies)]
            self.current_index += 1
            parts = proxy_str.split(':')
            if len(parts) == 4:
                username, password, host, port = parts
                proxy_url = f"http://{username}:{password}@{host}:{port}"
                return {'http': proxy_url, 'https': proxy_url}
            return None

    def mark_bad(self, proxy_dict):
        if not proxy_dict:
            return
        proxy_url = proxy_dict.get('http', '')
        if '://' in proxy_url:
            parsed = urlparse(proxy_url)
            user_pass = parsed.netloc.split('@')[0] if '@' in parsed.netloc else ''
            host_port = parsed.netloc.split('@')[-1] if '@' in parsed.netloc else parsed.netloc
            proxy_str = f"{user_pass}:{host_port}".replace(':', ':', 2)
            with self.lock:
                if proxy_str in self.proxies:
                    self.proxies.remove(proxy_str)
                self.bad_proxies.add(proxy_str)
                with open(BAD_PROXIES_FILE, 'a') as f:
                    f.write(f"{proxy_str}\n")
            logger.info(f"[ProxyManager] Marked proxy as bad: {proxy_str[:50]}...")

    def refresh(self):
        self.load_proxies()

# ---------- Helper Functions ----------
def gen_str(n=8):
    return ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=n))

def get_proxy_count():
    try:
        if not os.path.exists(PROXIES_FILE):
            return 0
        with open(PROXIES_FILE, 'r') as f:
            lines = f.readlines()
        unique = set(line.strip() for line in lines if line.strip())
        return len(unique)
    except:
        return 0

def update_stats(success_count, total_count):
    try:
        with open(STATS_FILE, 'w') as f:
            f.write(f"Accounts Created: {success_count}\n")
            f.write(f"Total Attempts: {total_count}\n")
            f.write(f"Success Rate: {success_count/total_count*100:.1f}%\n" if total_count > 0 else "Success Rate: 0%\n")
            f.write(f"Proxies Collected: {get_proxy_count()}\n")
            f.write(f"Proxies Available (working): {len(proxy_manager.proxies)}\n")
            f.write(f"Last Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    except:
        pass

def solve_captcha(use_proxy=False):
    logger.info("=> Solving captcha via CaptchaAI...")
    submit_url = "https://ocr.captchaai.com/in.php"
    submit_data = {
        "key": captchaai_api_key,
        "method": "turnstile",
        "sitekey": "0x4AAAAAAAQn-wN8S1gi-nJa",
        "pageurl": "https://app.gologin.com/sign_up",
        "json": 1
    }

    max_attempts = 3 if use_proxy else 1
    for attempt in range(max_attempts):
        proxy = None
        if use_proxy:
            proxy = proxy_manager.get_next_proxy()
            if proxy:
                logger.info(f"=> Using proxy for captcha submit (attempt {attempt+1})")

        try:
            submit_resp = requests.post(submit_url, data=submit_data, timeout=45,
                                        proxies=proxy, verify=False)
            if submit_resp.status_code != 200:
                if proxy and submit_resp.status_code == 429:
                    proxy_manager.mark_bad(proxy)
                continue

            submit_result = submit_resp.json()
            if submit_result.get("status") != 1:
                logger.info(f"=> Captcha submit error: {submit_result.get('request', 'Unknown error')}")
                continue

            task_id = submit_result.get("request")
            if not task_id:
                logger.info("=> No task ID received")
                continue
            logger.info(f"=> Task submitted, ID: {task_id}")

            result_url = "https://ocr.captchaai.com/res.php"
            for _ in range(40):
                time.sleep(2)
                poll_params = {"key": captchaai_api_key, "action": "get", "id": task_id, "json": 1}
                poll_resp = requests.get(result_url, params=poll_params, timeout=30,
                                         proxies=proxy, verify=False)
                if poll_resp.status_code != 200:
                    if proxy and poll_resp.status_code == 429:
                        proxy_manager.mark_bad(proxy)
                        break
                    continue

                poll_result = poll_resp.json()
                status = poll_result.get("status")
                if status == 1:
                    token = poll_result.get("request")
                    if token:
                        logger.info(f"=> Captcha solved: {token[:20]}...")
                        return token
                elif status == 0:
                    continue
                else:
                    logger.info(f"=> Captcha solving error: {poll_result.get('request', 'Unknown')}")
                    break

            if proxy:
                proxy_manager.mark_bad(proxy)

        except Exception as e:
            logger.error(f"=> Captcha solving error: {e}")
            if proxy:
                proxy_manager.mark_bad(proxy)
            continue

    logger.error("=> Captcha solving failed after all attempts")
    return None

def get_prox(tk, use_proxy=False):
    logger.info("=> Fetching proxies...")
    hdr = {
        'accept': '*/*',
        'authorization': f'Bearer {tk}',
        'gologin-meta-header': f'site-{fp["os"]}-10.0',
        'user-agent': ua
    }

    proxies_to_try = [None]
    if use_proxy:
        proxies_to_try.append(proxy_manager.get_next_proxy())

    for proxy in proxies_to_try:
        if proxy is None:
            logger.info("=> Trying direct connection...")
        else:
            logger.info("=> Trying with proxy...")

        try:
            resp = requests.get(f'{ixcynigga_api}/proxy/v2?page=1', headers=hdr,
                                timeout=30, verify=False, proxies=proxy)
            if resp.status_code == 429 and proxy:
                proxy_manager.mark_bad(proxy)
                continue
            if resp.status_code != 200:
                logger.info(f"=> Proxy fetch failed: HTTP {resp.status_code}")
                continue

            prox_list = resp.json().get('proxies', [])
            if not prox_list:
                logger.info("=> No proxies found")
                return 0

            existing_proxies = set()
            if os.path.exists(PROXIES_FILE):
                with open(PROXIES_FILE, 'r') as f:
                    for line in f:
                        if line.strip():
                            existing_proxies.add(line.strip())

            new_count = 0
            with open(PROXIES_FILE, 'a') as f:
                for p in prox_list:
                    if all([p.get(x) for x in ['username', 'password', 'host', 'port']]):
                        proxy_str = f"{p['username']}:{p['password']}:{p['host']}:{p['port']}"
                        if proxy_str not in existing_proxies:
                            f.write(f"{proxy_str}\n")
                            new_count += 1

            logger.info(f"=> Added {new_count} new proxies. Total: {len(existing_proxies) + new_count}")
            proxy_manager.refresh()
            return new_count

        except Exception as e:
            logger.error(f"=> Error fetching proxies: {e}")
            if proxy:
                proxy_manager.mark_bad(proxy)
            continue

    return 0

def create_acc(tk, use_proxy=False):
    logger.info("=> Creating account...")
    email = f"user_{gen_str()}@gmail.com"
    pwd = f"Yuki_{random.randint(1000, 9999)}"

    hdr = {
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9',
        'content-type': 'application/json',
        'gologin-meta-header': f"site-{fp['os']}-10.0",
        'origin': 'https://app.gologin.com',
        'referer': 'https://app.gologin.com/',
        'user-agent': ua
    }

    body = {
        'email': email,
        'password': pwd,
        'passwordConfirm': pwd,
        'captchaToken': tk,
        'fromApp': False,
        'canvasAndFontsHash': fp['canvasAndFontsHash'],
        'fontsHash': fp['fontsHash'],
        'canvasHash': fp['canvasHash'],
        'userOs': fp['os'],
        'osSpec': fp['osSpec'],
        'resolution': '1920x1080'
    }

    max_attempts = 10 if use_proxy else 1
    for attempt in range(max_attempts):
        proxy = None
        if use_proxy:
            proxy = proxy_manager.get_next_proxy()
            if not proxy:
                logger.info("=> No proxies available for brute force. Waiting 30s...")
                time.sleep(30)
                proxy_manager.refresh()
                continue
            logger.info(f"=> Using proxy (attempt {attempt+1}/{max_attempts})")

        try:
            resp = requests.post(
                f'{ixcynigga_api}/user',
                params={'free-plan': 'true', 'registerAs': 'workspaces'},
                headers=hdr, json=body, timeout=30, verify=False, proxies=proxy
            )

            if resp.status_code == 429:
                logger.info("=> Rate limited (429) with this proxy")
                if proxy:
                    proxy_manager.mark_bad(proxy)
                continue

            if resp.status_code in [200, 201]:
                logger.info(f"=> Account created: {email}")
                tk2 = resp.json().get('token')

                with open(ACCOUNTS_FILE, 'a') as f:
                    f.write(f"{email}:{pwd}\n")
                logger.info("=> Saved credentials to accounts.txt")

                time.sleep(0.5)
                new_proxies = get_prox(tk2, use_proxy=use_proxy)
                return True, email, new_proxies
            else:
                logger.info(f"=> Account creation failed: HTTP {resp.status_code}")
                if resp.text:
                    logger.info(f"=> Response: {resp.text[:200]}")
                if proxy and resp.status_code not in [400, 401, 403]:
                    proxy_manager.mark_bad(proxy)
                return False, None, 0

        except Exception as e:
            logger.error(f"=> Error creating account: {e}")
            if proxy:
                proxy_manager.mark_bad(proxy)
            continue

    logger.info("=> All proxy attempts exhausted. Account creation failed.")
    return False, None, 0

# ---------- Global State and Background Thread ----------
proxy_manager = ProxyManager()

class BotState:
    def __init__(self):
        self.running = False
        self.thread = None
        self.success_count = 0
        self.total_count = 0
        self.lock = threading.Lock()

    def start_process(self):
        if self.running:
            return False
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        return True

    def stop_process(self):
        self.running = False
        # The thread will exit at the next iteration

    def _run_loop(self):
        """Main continuous loop (runs in background thread)"""
        use_proxy_mode = False
        while self.running:
            with self.lock:
                self.total_count += 1
                total = self.total_count
                success = self.success_count

            current_proxies = get_proxy_count()
            logger.info(f"Cycle #{total} | Accounts: {success}/{total-1} | Proxies: {current_proxies}/5")
            logger.info(f"Proxy Mode: {'ON' if use_proxy_mode else 'OFF'}")
            logger.info(f"Working proxies in rotation: {len(proxy_manager.proxies)}")

            captcha_token = solve_captcha(use_proxy=use_proxy_mode)
            if not captcha_token:
                logger.info("Captcha solving failed. Retrying in 10s...")
                time.sleep(10)
                continue

            success_flag, email, new_proxies = create_acc(captcha_token, use_proxy=use_proxy_mode)

            with self.lock:
                if success_flag:
                    self.success_count += 1
                update_stats(self.success_count, self.total_count)

            if success_flag:
                logger.info(f"Cycle completed successfully! Account: {email}, New proxies: {new_proxies}")
                if not use_proxy_mode and get_proxy_count() >= 5:
                    use_proxy_mode = False
                    logger.info("Enough proxies collected, staying in direct mode.")
            else:
                logger.info("Cycle failed.")
                if not use_proxy_mode:
                    use_proxy_mode = True
                    logger.info("Enabling proxy brute force mode.")
                    proxy_manager.refresh()
                else:
                    logger.info("Proxy mode active, will try next proxy.")

            delay = 5 if success_flag else 10
            time.sleep(delay)

        logger.info("Process stopped by user.")

state = BotState()

# ---------- Telegram Bot Handlers ----------
async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the account creation process."""
    if state.running:
        await update.message.reply_text("⚠️ Process is already running.")
        return

    if state.start_process():
        await update.message.reply_text(
            "✅ Account creation started!\n"
            "Use /stats to see progress, /sendresults to get proxies, /stop to halt."
        )
    else:
        await update.message.reply_text("❌ Could not start process.")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop the account creation process."""
    if not state.running:
        await update.message.reply_text("ℹ️ Process is not running.")
        return

    state.stop_process()
    await update.message.reply_text("🛑 Stop signal sent. The process will exit after the current cycle.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send current statistics."""
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r') as f:
            content = f.read()
    else:
        content = "No stats available yet."

    running_status = "🟢 Running" if state.running else "🔴 Stopped"
    message = f"*Status:* {running_status}\n\n```\n{content}\n```"
    await update.message.reply_text(message, parse_mode="Markdown")

async def sendresults_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the proxies.txt file as a document."""
    if not os.path.exists(PROXIES_FILE) or os.path.getsize(PROXIES_FILE) == 0:
        await update.message.reply_text("ℹ️ No proxies have been collected yet.")
        return

    await update.message.reply_document(
        document=open(PROXIES_FILE, 'rb'),
        filename="proxies.txt",
        caption="Here are the collected proxies."
    )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

# ---------- Main ----------
def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("Please set your TELEGRAM_BOT_TOKEN environment variable.")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("get", get_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("sendresults", sendresults_command))
    application.add_error_handler(error_handler)

    logger.info("Bot started. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()