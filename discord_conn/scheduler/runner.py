"""Background scheduler for periodic channel synchronization and automatic digests."""

import logging
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from rich.console import Console

from ..config import config
from ..db.repository import Repository
from ..client.discord_api import DiscordAPIClient
from ..ai.summarizer import Summarizer

logger = logging.getLogger(__name__)
console = Console()


class SchedulerRunner:
    def __init__(self, interval_minutes: int = 60):
        self.interval_seconds = interval_minutes * 60
        self._running = True
        self.repo = Repository(config.database_path)
        self.client: Optional[DiscordAPIClient] = None
        if config.discord_token:
            self.client = DiscordAPIClient(
                token=config.discord_token,
                base_url=config.discord_api_base,
                user_agent=config.user_agent,
                request_delay=config.request_delay,
            )
        self.summarizer = Summarizer(repository=self.repo)

    def _setup_signals(self) -> None:
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

    def _handle_exit(self, signum, frame) -> None:
        console.print("\n[yellow]Stopping scheduler daemon gracefully...[/yellow]")
        self._running = False

    def run_cycle(self) -> None:
        watched = config.watched_channels
        if not watched:
            console.print("[dim]No channels defined in 'watched_channels' in config/config.yaml. Waiting...[/dim]")
            return

        if not self.client:
            console.print("[red]Cannot sync: DISCORD_USER_TOKEN is not configured.[/red]")
            return

        console.print(f"[bold cyan][{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][/bold cyan] Running sync cycle for {len(watched)} watched channels...")

        for entry in watched:
            cid = str(entry.get("channel_id") or "")
            cname = entry.get("name", cid)
            if not cid:
                continue

            try:
                # 1. Sync messages
                msgs = self.client.fetch_channel_history(cid, max_messages=config.max_messages_per_sync)
                count = self.repo.upsert_messages_batch(msgs)
                console.print(f"  • Synced [bold]#{cname}[/bold] ({count} messages)")

                # 2. Check if summary is due
                hours = entry.get("summary_interval_hours", 24)
                if config.gemini_api_key:
                    res = self.summarizer.summarize_channel(channel_id=cid, hours_back=hours)
                    if res.get("success"):
                        console.print(f"    [green]✓ Digest generated:[/green] {res.get('report_path')}")
            except Exception as e:
                console.print(f"  [red]✗ Error processing #{cname}:[/red] {e}")

    def start(self) -> None:
        self._setup_signals()
        console.print(f"[bold green]Starting Discord Connector Daemon[/bold green] (Interval: {self.interval_seconds // 60}m)")
        console.print("Press Ctrl+C to stop.")

        while self._running:
            self.run_cycle()
            # Sleep in short increments to respond quickly to shutdown signals
            for _ in range(int(self.interval_seconds)):
                if not self._running:
                    break
                time.sleep(1)

        console.print("[green]Scheduler daemon exited.[/green]")
