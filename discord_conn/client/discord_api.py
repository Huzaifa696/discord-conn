"""Discord REST API client supporting user token authentication, rate limiting, and message pagination."""

import logging
import time
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)


class DiscordAPIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, response_data: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class DiscordAPIClient:
    def __init__(
        self,
        token: str,
        base_url: str = "https://discord.com/api/v10",
        user_agent: Optional[str] = None,
        request_delay: float = 1.0,
    ):
        if not token:
            raise ValueError("Discord token must not be empty.")
        self.token = token.strip()
        self.base_url = base_url.rstrip("/")
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": self.token,
            "User-Agent": user_agent or "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "Accept": "*/*",
        })
        self._last_request_time = 0.0

    def _wait_for_rate_limit(self) -> None:
        """Enforce request delay pacing."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
    ) -> Any:
        url = f"{self.base_url}{endpoint}"
        retries = 0

        while retries <= max_retries:
            self._wait_for_rate_limit()
            self._last_request_time = time.time()

            try:
                resp = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data,
                    timeout=20,
                )
            except requests.RequestException as e:
                retries += 1
                if retries > max_retries:
                    raise DiscordAPIError(f"Network error connecting to Discord: {e}")
                time.sleep(2.0 * retries)
                continue

            # Handle rate limiting (HTTP 429)
            if resp.status_code == 429:
                try:
                    data = resp.json()
                    retry_after = float(data.get("retry_after", 2.0))
                except Exception:
                    retry_after = 2.0
                logger.warning("Discord 429 Rate Limit hit. Pausing for %.2f seconds.", retry_after)
                time.sleep(retry_after + 0.5)
                retries += 1
                continue

            # Handle unauthorized / forbidden
            if resp.status_code == 401:
                raise DiscordAPIError("Discord Authentication Failed (401). Please verify your DISCORD_USER_TOKEN.", status_code=401)
            if resp.status_code == 403:
                raise DiscordAPIError(f"Access Denied (403) for endpoint {endpoint}. You do not have permissions.", status_code=403)
            if resp.status_code == 404:
                raise DiscordAPIError(f"Resource Not Found (404) at {endpoint}.", status_code=404)

            if not resp.ok:
                raise DiscordAPIError(
                    f"Discord API error {resp.status_code}: {resp.text}",
                    status_code=resp.status_code,
                    response_data=resp.text,
                )

            if resp.status_code == 204:
                return None

            try:
                return resp.json()
            except Exception:
                return resp.text

        raise DiscordAPIError(f"Max retries exceeded for {url}")

    def get_current_user(self) -> Dict[str, Any]:
        """Fetch current authenticated user profile."""
        return self._request("GET", "/users/@me")

    def get_guilds(self) -> List[Dict[str, Any]]:
        """Fetch list of guilds (servers) the user is a member of."""
        return self._request("GET", "/users/@me/guilds")

    def get_guild_channels(self, guild_id: str) -> List[Dict[str, Any]]:
        """Fetch all channels in a guild."""
        return self._request("GET", f"/guilds/{guild_id}/channels")

    def get_channel(self, channel_id: str) -> Dict[str, Any]:
        """Fetch details of a specific channel."""
        return self._request("GET", f"/channels/{channel_id}")

    def get_channel_messages(
        self,
        channel_id: str,
        limit: int = 100,
        before: Optional[str] = None,
        after: Optional[str] = None,
        around: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch up to 100 messages from a channel using pagination cursors.
        """
        params: Dict[str, Any] = {"limit": min(limit, 100)}
        if before:
            params["before"] = str(before)
        elif after:
            params["after"] = str(after)
        elif around:
            params["around"] = str(around)

        return self._request("GET", f"/channels/{channel_id}/messages", params=params)

    def fetch_channel_history(
        self,
        channel_id: str,
        max_messages: int = 200,
        before: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch messages in batches of 100 backwards from 'before' cursor until max_messages is reached.
        """
        all_messages: List[Dict[str, Any]] = []
        curr_before = before

        while len(all_messages) < max_messages:
            batch_limit = min(100, max_messages - len(all_messages))
            batch = self.get_channel_messages(channel_id, limit=batch_limit, before=curr_before)
            if not batch:
                break
            all_messages.extend(batch)
            if len(batch) < batch_limit:
                # No more older messages
                break
            curr_before = batch[-1]["id"]

        return all_messages

    def send_message(
        self,
        channel_id: str,
        content: str,
        reply_to_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a message to a channel, optionally referencing a parent message as a reply.
        """
        payload: Dict[str, Any] = {"content": content}
        if reply_to_message_id:
            payload["message_reference"] = {
                "channel_id": str(channel_id),
                "message_id": str(reply_to_message_id),
            }

        return self._request("POST", f"/channels/{channel_id}/messages", json_data=payload)
