# keycloak_auth.py

import os
import requests
import json
import time
import getpass
import logging
from typing import Optional, Tuple, Dict
from urllib.parse import urlparse, urlencode

# Try unified keyring first (new system), fall back to keyring_store (old system)
try:
    from unified_keyring import get_keycloak_credentials as _get_unified_creds
    def get_keyring_credentials():
        """Get credentials from unified keyring."""
        try:
            username, password = _get_unified_creds()
            return (username, password)
        except Exception:
            return None

    def store_keyring_credentials(username, password):
        """Store credentials - unified system uses 'make setup' instead."""
        logger.info("Credentials should be stored via 'make setup' for unified keyring system.")
        # No-op for unified system - credentials managed centrally
        pass

    USING_UNIFIED_KEYRING = True
except ImportError:
    # Fall back to old keyring_store system
    from keyring_store import (
        get_credentials as get_keyring_credentials,
        store_credentials as store_keyring_credentials,
    )
    USING_UNIFIED_KEYRING = False

# Logging configuration (guard against duplicate handlers)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    file_handler = logging.FileHandler('app.log')
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_formatter = logging.Formatter('%(message)s')

    file_handler.setFormatter(file_formatter)
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

TOKEN_FILE = "keycloak_tokens.json"
HISTORY_FILE = "keycloak_history.json"
REALM = os.getenv('KEYCLOAK_REALM', 'kelvin')
CLIENT_ID = os.getenv('KEYCLOAK_CLIENT_ID', 'admin-cli')


def normalize_url(url: str) -> str:
    """Normalizes the Keycloak URL for consistent storage and use."""
    parsed = urlparse(url.strip())
    netloc = parsed.netloc if parsed.netloc else parsed.path
    netloc = netloc.rstrip('/')
    return netloc


def construct_full_url(netloc: str) -> str:
    """Constructs the full URL with 'https://' scheme."""
    return f"https://{netloc}"


def read_json_file(file_path: str) -> Dict:
    """Reads JSON data from a file."""
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            try:
                return json.load(file)
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON format in '{file_path}'.")
                return {}
    return {}


def write_json_file(file_path: str, data: Dict):
    """Writes JSON data to a file."""
    with open(file_path, "w") as file:
        json.dump(data, file)


def add_to_history(keycloak_url: str, username: str):
    """Adds normalized keycloak_url and username to history."""
    keycloak_url = normalize_url(keycloak_url)
    history_data = read_json_file(HISTORY_FILE)
    keycloak_urls = history_data.get("keycloak_urls", [])
    usernames = history_data.get("usernames", [])

    if keycloak_url not in keycloak_urls:
        keycloak_urls.append(keycloak_url)
    if username not in usernames:
        usernames.append(username)

    history_data["keycloak_urls"] = keycloak_urls
    history_data["usernames"] = usernames
    write_json_file(HISTORY_FILE, history_data)


def remove_expired_tokens():
    """Removes expired tokens from the tokens file."""
    tokens_data = read_json_file(TOKEN_FILE)
    current_time = time.time()
    tokens_to_remove = []

    for keycloak_url, token_data in tokens_data.items():
        expires_at = token_data.get("expires_in", 0) + token_data.get("timestamp", 0)
        if expires_at <= current_time:
            tokens_to_remove.append(keycloak_url)

    if tokens_to_remove:
        for keycloak_url in tokens_to_remove:
            del tokens_data[keycloak_url]
            logger.debug(f"Removed expired token for {keycloak_url}")
        write_json_file(TOKEN_FILE, tokens_data)


def refresh_token(keycloak_url: str, refresh_token: str) -> Optional[Dict]:
    """Refreshes the access token using the refresh token."""
    keycloak_url = normalize_url(keycloak_url)
    full_url = construct_full_url(keycloak_url)
    token_url = f"{full_url}/auth/realms/{REALM}/protocol/openid-connect/token"
    data = {
        "client_id": CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    try:
        response = requests.post(token_url, data=urlencode(data), headers=headers, timeout=10)
        response.raise_for_status()
        token_data = response.json()
        token_data["keycloak_url"] = keycloak_url  # Ensure normalized URL is stored
        return token_data
    except requests.exceptions.RequestException as e:
        logger.error(f"Token refresh failed: {e}")
        return None


def authenticate(
    keycloak_url: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    *,
    prompt: bool = True,
) -> Optional[str]:
    """Authenticates with Keycloak and returns an access token.

    Parameters
    ----------
    keycloak_url:
        Hostname or URL for the Keycloak server.
    username/password:
        Optional credentials. When omitted and ``prompt`` is True the user is
        interactively prompted. When ``prompt`` is False both values must be
        supplied or the function returns ``None``.
    prompt:
        Controls whether interactive prompts are allowed.
    """
    keycloak_url = normalize_url(keycloak_url)
    full_url = construct_full_url(keycloak_url)
    token_url = f"{full_url}/auth/realms/{REALM}/protocol/openid-connect/token"
    history_data = read_json_file(HISTORY_FILE)
    usernames = history_data.get("usernames", [])

    selected_username = username

    used_keyring_creds = False

    if selected_username is None or password is None:
        keyring_creds = get_keyring_credentials()
        if keyring_creds:
            stored_username, stored_password = keyring_creds
            if selected_username is None:
                selected_username = stored_username
            if password is None:
                password = stored_password
                logger.debug(
                    "Using Keycloak credentials from keyring for %s",
                    keycloak_url,
                )
            used_keyring_creds = True

    if selected_username is None:
        if prompt:
            # Only display username history if it exists
            if usernames:
                print("Available usernames from history:")
                for i, historic_username in enumerate(usernames, 1):
                    print(f"{i}. {historic_username}")

                selected_username = select_from_history(
                    usernames,
                    "Choose a username from history (or press Enter to enter a new username): ",
                )
            if not selected_username:
                selected_username = input("Enter your Keycloak username: ").strip()
        else:
            logger.error("Username must be provided when interactive prompts are disabled.")
            return None

    secret = password
    if secret is None:
        if prompt:
            secret = getpass.getpass('Enter your Keycloak password: ')
        else:
            logger.error("Password must be provided when interactive prompts are disabled.")
            return None

    data = {
        "client_id": CLIENT_ID,
        "grant_type": "password",
        "username": selected_username,
        "password": secret,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    try:
        response = requests.post(token_url, data=urlencode(data), headers=headers, timeout=10)
        response.raise_for_status()
        token_data = response.json()
        token_data["timestamp"] = time.time()
        token_data["keycloak_url"] = keycloak_url  # Ensure normalized URL is stored
        tokens_data = read_json_file(TOKEN_FILE)
        tokens_data[keycloak_url] = token_data
        write_json_file(TOKEN_FILE, tokens_data)
        if prompt:
            add_to_history(keycloak_url, selected_username)
            auto_store = os.getenv("KEYCLOAK_KEYRING_AUTO_STORE", "1") != "0"
            if auto_store and not used_keyring_creds:
                try:
                    store_keyring_credentials(selected_username, secret)
                    logger.info("Saved Keycloak credentials to keyring for future non-interactive runs.")
                except Exception as exc:  # pragma: no cover - best-effort
                    logger.debug("Skipping keyring storage: %s", exc)
        return token_data["access_token"]
    except requests.exceptions.RequestException as e:
        logger.error(f"Authentication failed: {e}")
        print("Authentication failed. Please check your credentials and try again.")
        return None


def get_access_token(keycloak_url: str) -> Optional[str]:
    """Retrieves a valid access token, refreshing or authenticating as needed."""
    keycloak_url = normalize_url(keycloak_url)
    tokens_data = read_json_file(TOKEN_FILE)
    current_time = time.time()

    token_data = tokens_data.get(keycloak_url)
    if token_data:
        expires_at = token_data.get("expires_in", 0) + token_data.get("timestamp", 0)
        if expires_at > current_time:
            return token_data.get("access_token")

        refresh_token_str = token_data.get("refresh_token")
        if refresh_token_str:
            refresh_token_data = refresh_token(keycloak_url, refresh_token_str)
            if refresh_token_data:
                refresh_token_data["timestamp"] = current_time
                tokens_data[keycloak_url] = refresh_token_data
                write_json_file(TOKEN_FILE, tokens_data)
                return refresh_token_data["access_token"]
            else:
                # Remove invalid refresh token
                del tokens_data[keycloak_url]
                write_json_file(TOKEN_FILE, tokens_data)

    return authenticate(keycloak_url)


def select_from_history(options: list, prompt: str) -> Optional[str]:
    """Selects an item from history or returns None."""
    if not options:
        return None

    choice = input(prompt).strip()
    if choice.isdigit() and 1 <= int(choice) <= len(options):
        return options[int(choice) - 1]
    elif choice == '':
        return None
    else:
        print("Invalid selection.")
        return None


def choose_auth_method(default_url: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Allows the user to choose an authentication method."""
    # Remove expired tokens before proceeding
    remove_expired_tokens()

    default_normalized = normalize_url(default_url) if default_url else None

    env_keycloak_url = os.getenv('KEYCLOAK_URL') or os.getenv('KEYCLOAK_SERVER')
    env_access_token = os.getenv('KEYCLOAK_ACCESS_TOKEN') or os.getenv('KEYCLOAK_BEARER_TOKEN')
    if env_access_token and env_keycloak_url:
        normalized_url = normalize_url(env_keycloak_url)
        return env_access_token.strip(), normalized_url

    env_username = os.getenv('KEYCLOAK_USERNAME') or os.getenv('KEYCLOAK_USER')
    env_password = os.getenv('KEYCLOAK_PASSWORD')
    if env_keycloak_url and env_username and env_password:
        normalized_url = normalize_url(env_keycloak_url)
        token = authenticate(normalized_url, env_username, env_password, prompt=False)
        if token:
            return token, normalized_url
        logger.error("Failed to authenticate with Keycloak using environment credentials.")

    tokens_data = read_json_file(TOKEN_FILE)
    current_time = time.time()
    valid_tokens = {}
    history_data = read_json_file(HISTORY_FILE)
    keycloak_urls = history_data.get("keycloak_urls", [])

    # Normalize keycloak_urls in history
    keycloak_urls = [normalize_url(url) for url in keycloak_urls]
    if default_normalized and default_normalized not in keycloak_urls:
        keycloak_urls.append(default_normalized)

    # Build the valid tokens dictionary
    for keycloak_url, token_data in tokens_data.items():
        expires_at = token_data.get("expires_in", 0) + token_data.get("timestamp", 0)
        if expires_at > current_time:
            valid_tokens[keycloak_url] = token_data["access_token"]

    # If there are valid tokens, let the user choose one
    if valid_tokens:
        print("Existing valid tokens found:")
        for i, keycloak_url in enumerate(valid_tokens.keys(), 1):
            print(f"{i}. {construct_full_url(keycloak_url)}")

        keycloak_url = select_from_history(
            list(valid_tokens.keys()),
            "Choose a valid token to use (or press Enter to authenticate with a new URL): ",
        )
        if keycloak_url:
            return valid_tokens[keycloak_url], keycloak_url

    # If there are keycloak URLs in history, let the user choose one
    if keycloak_urls:
        print("History of Keycloak servers:")
        for i, keycloak_url in enumerate(keycloak_urls, 1):
            print(f"{i}. {construct_full_url(keycloak_url)}")

        keycloak_url = select_from_history(
            keycloak_urls,
            "Choose a Keycloak server from history (or press Enter to authenticate with a new URL): ",
        )
        if not keycloak_url:
            if default_normalized:
                keycloak_url = default_normalized
            else:
                keycloak_url = input("Enter Keycloak server URL (e.g., your-keycloak-server): ").strip()
                keycloak_url = normalize_url(keycloak_url)
    else:
        # No keycloak URLs in history, prompt the user to enter a new URL
        if default_normalized:
            keycloak_url = default_normalized
        else:
            keycloak_url = input("Enter Keycloak server URL (e.g., your-keycloak-server): ").strip()
            keycloak_url = normalize_url(keycloak_url)

    token = authenticate(keycloak_url)
    return token, keycloak_url


def get_all_groups(keycloak_url: str, access_token: str) -> list:
    """Retrieves all groups from Keycloak."""
    keycloak_url = normalize_url(keycloak_url)
    full_url = construct_full_url(keycloak_url)
    url = f"{full_url}/auth/admin/realms/{REALM}/groups"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get groups: {e}")
        return []


def assign_user_to_group(keycloak_url: str, user_id: str, group_id: str, access_token: str):
    """Assigns a user to a group in Keycloak."""
    keycloak_url = normalize_url(keycloak_url)
    full_url = construct_full_url(keycloak_url)
    url = f"{full_url}/auth/admin/realms/{REALM}/users/{user_id}/groups/{group_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.put(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to assign user to group: {e}")


def get_group_by_name(keycloak_url: str, group_name: str, access_token: str) -> Optional[dict]:
    """Retrieves a group by name."""
    groups = get_all_groups(keycloak_url, access_token)
    for group in groups:
        if group['name'] == group_name:
            return group
    return None
