import time
import requests
import os
import tempfile
import requests
import contextlib
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import Config
from app.utils.exceptions import APIConnectionError


logger = logging.getLogger(__name__)

@contextlib.contextmanager
def temp_audio_file(suffix=".wav"):
    temp_dir = Config.TEMP_DIR
    fd, path = tempfile.mkstemp(suffix=suffix, dir=temp_dir)
    try:
        os.close(fd)
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError as e:
            logger.warning(f"Failed to delete temporary file {path}: {e}")

@retry(stop=stop_after_attempt(Config.MAX_RETRIES), wait=wait_exponential(multiplier=1, min=1, max=10))
def download_audio(url, timeout=None):
    timeout = timeout or Config.REQUEST_TIMEOUT
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.content
    except requests.RequestException as e:
        logger.error(f"Failed to download audio from {url}: {e}")
        raise APIConnectionError("audio download service", e)


def download_with_retry(url, headers=None, max_retries=5, initial_delay=2.0, backoff_factor=2):
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[404, 408, 429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    verify_ssl = True

    last_exception = None
    delay = initial_delay

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Download attempt {attempt}/{max_retries} for {url}")
            resp = session.get(url, headers=headers, timeout=(3.05, 30), verify=verify_ssl)
            if resp.status_code == 200:
                if len(resp.content) > 100:
                    logger.info(f"Downloaded {len(resp.content)} bytes successfully.")
                    return resp.content
                logger.warning(f"Attempt {attempt}: Empty response (size={len(resp.content)} bytes)")
            resp.raise_for_status()
        except requests.exceptions.SSLError as e:
            last_exception = e
            logger.warning(f"SSL error on attempt {attempt}: {e}")
            if "UNEXPECTED_EOF" in str(e) and verify_ssl:
                verify_ssl = False
                logger.warning("Trying without SSL verification for next attempt")
        except Exception as e:
            last_exception = e
            logger.warning(f"Attempt {attempt} failed: {e}")

        if attempt < max_retries:
            sleep_time = min(delay * (backoff_factor ** (attempt - 1)), 60)
            logger.info(f"Waiting {sleep_time:.1f}s before retry...")
            time.sleep(sleep_time)

    raise Exception(f"Failed to download {url} after {max_retries} attempts. Last error: {last_exception}")
