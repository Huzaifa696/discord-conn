"""Main CLI interface for Discord Connector."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from ..config import config
from ..db.repository import Repository
from ..client.discord_api import DiscordAPIClient, DiscordAPIError
from ..pipeline.context import ContextBuilder
from ..ai.gemini import GeminiClient, GeminiAPIError
from ..ai.summarizer import Summarizer
from ..ai.drafter import ReplyDrafter
from .interactive import run_interactive_reply

console = Console()


def get_repo() -> Repository:
    return Repository(config.database_path)


def get_client() -> DiscordAPIClient:
    token = config.discord_token
    if not token:
        console.print("[bold red]Error: DISCORD_USER_TOKEN is not set.[/bold red]")
        console.print("Please set it in your .env file or environment variable.")
        sys.exit(1)
    return DiscordAPIClient(
        token=token,
        base_url=config.discord_api_base,
        user_agent=config.user_agent,
        request_delay=config.request_delay,
    )


@click.group()
def cli():
    """Discord Connector: Zero-AI context pipeline with Gemini summarizer & replies."""
    pass


@cli.command("auth-check")
def auth_check():
    """Verify Discord user token and Gemini API key."""
    console.print(Panel("[bold cyan]Authentication Status Check[/bold cyan]", border_style="cyan"))

    # 1. Check Discord Token
    if not config.discord_token:
        console.print("[red]✗ DISCORD_USER_TOKEN: Missing[/red]")
    else:
        try:
            client = get_client()
            user = client.get_current_user()
            u_name = user.get("username", "Unknown")
            g_name = user.get("global_name", "")
            display = f"{g_name} (@{u_name})" if g_name else f"@{u_name}"
            console.print(f"[green]✓ Discord Authentication:[/green] Connected as [bold]{display}[/bold] (ID: {user.get('id')})")
        except DiscordAPIError as e:
            console.print(f"[red]✗ Discord Authentication Failed:[/red] {e}")
        except Exception as e:
            console.print(f"[red]✗ Discord Connection Error:[/red] {e}")

    # 2. Check Gemini Key
    if not config.gemini_api_key:
        console.print("[yellow]! GEMINI_API_KEY: Missing or empty (summarization will be unavailable until set)[/yellow]")
    else:
        try:
            gemini = GeminiClient(
                api_key=config.gemini_api_key,
                model_name=config.ai_model,
                fallback_model=config.ai_fallback_model,
                fallback_candidates=config.ai_fallback_candidates,
                max_retries_per_model=config.ai_max_retries,
                retry_delay_seconds=config.ai_retry_delay,
            )
            test_resp = gemini.generate("Respond with 'OK' only.")
            console.print(f"[green]✓ Gemini API Connected:[/green] Model {config.ai_model} is ready. (Response: {test_resp.strip()})")
        except Exception as e:
            console.print(f"[red]✗ Gemini Connection Error:[/red] {e}")


@cli.command("servers")
def list_servers():
    """List Discord servers (guilds) you have joined."""
    client = get_client()
    repo = get_repo()
    with console.status("[bold green]Fetching servers from Discord..."):
        try:
            guilds = client.get_guilds()
        except Exception as e:
            console.print(f"[bold red]Failed to fetch servers:[/bold red] {e}")
            return

    table = Table(title="Joined Discord Servers")
    table.add_column("Server ID", style="cyan")
    table.add_column("Server Name", style="bold white")
    table.add_column("Owner", style="dim")

    for g in guilds:
        repo.upsert_guild(guild_id=str(g["id"]), name=g.get("name", "Unknown"), icon=g.get("icon"))
        table.add_row(str(g["id"]), g.get("name", "Unknown"), "Yes" if g.get("owner") else "No")

    console.print(table)
    console.print(f"[dim]Total: {len(guilds)} servers (cached in local database)[/dim]")


@cli.command("channels")
@click.argument("guild_id")
def list_channels(guild_id: str):
    """List text channels for a specific server (guild)."""
    client = get_client()
    repo = get_repo()
    with console.status(f"[bold green]Fetching channels for server {guild_id}..."):
        try:
            channels = client.get_guild_channels(guild_id)
        except Exception as e:
            console.print(f"[bold red]Failed to fetch channels:[/bold red] {e}")
            return

    table = Table(title=f"Channels for Server {guild_id}")
    table.add_column("Channel ID", style="cyan")
    table.add_column("Channel Name", style="bold white")
    table.add_column("Type", style="dim")
    table.add_column("Topic", style="dim")

    # Discord channel types: 0=GUILD_TEXT, 2=GUILD_VOICE, 4=GUILD_CATEGORY, 15=GUILD_FORUM
    text_channels = [c for c in channels if c.get("type") in (0, 5, 15)]

    for c in text_channels:
        repo.upsert_channel(
            channel_id=str(c["id"]),
            name=c.get("name", "unknown"),
            guild_id=str(guild_id),
            channel_type=c.get("type", 0),
            topic=c.get("topic"),
            last_message_id=str(c.get("last_message_id") or ""),
        )
        table.add_row(
            str(c["id"]),
            f"#{c.get('name', 'unknown')}",
            "Text" if c.get("type") == 0 else str(c.get("type")),
            (c.get("topic") or "")[:40],
        )

    console.print(table)
    console.print(f"[dim]Stored {len(text_channels)} text channels in local database.[/dim]")


def _sync_single_channel(client: DiscordAPIClient, repo: Repository, channel_id: str, max_messages: int = 200, quiet: bool = False) -> int:
    try:
        chan_info = client.get_channel(channel_id)
        repo.upsert_channel(
            channel_id=str(chan_info["id"]),
            name=chan_info.get("name", f"channel-{channel_id}"),
            guild_id=str(chan_info.get("guild_id") or ""),
            channel_type=chan_info.get("type", 0),
            topic=chan_info.get("topic"),
        )
        cname = chan_info.get("name", channel_id)
    except Exception:
        cname = channel_id

    if not quiet:
        console.print(f"Syncing up to {max_messages} messages for [bold]#{cname}[/bold]...")

    messages = client.fetch_channel_history(channel_id, max_messages=max_messages)
    count = repo.upsert_messages_batch(messages)
    if messages:
        repo.update_sync_state(
            channel_id=channel_id,
            new_count=count,
            oldest_id=messages[-1]["id"],
            newest_id=messages[0]["id"],
        )
    return count


def _sync_server_helper(client: DiscordAPIClient, repo: Repository, guild_id: str, channel_limit: int, max_messages: int):
    guild = repo.get_guild(guild_id)
    gname = guild["name"] if guild else f"Server-{guild_id}"
    console.print(f"[bold cyan]Syncing channels for server '{gname}' (ID: {guild_id})...[/bold cyan]")

    # 1. Fetch/refresh channels from Discord
    with console.status("[bold green]Fetching channels from Discord API..."):
        try:
            remote_channels = client.get_guild_channels(guild_id)
            for ch in remote_channels:
                repo.upsert_channel(
                    channel_id=str(ch["id"]),
                    name=ch.get("name", str(ch["id"])),
                    guild_id=str(guild_id),
                    channel_type=ch.get("type", 0),
                    topic=ch.get("topic"),
                    last_message_id=ch.get("last_message_id"),
                )
        except Exception as e:
            console.print(f"[yellow]Note: Could not refresh channels from API ({e}), using locally cached channels.[/yellow]")

    # 2. Query text channels (type 0=guild_text, 5=guild_announcement)
    channels = repo.list_channels(guild_id)
    text_channels = [c for c in channels if c.get("type", 0) in (0, 5)]
    text_channels.sort(
        key=lambda c: int(c.get("last_message_id") or "0"),
        reverse=True,
    )

    if not text_channels:
        console.print(f"[yellow]No accessible text channels found for server {guild_id}.[/yellow]")
        return

    to_sync = text_channels[:channel_limit]
    console.print(f"Syncing top [bold]{len(to_sync)}[/bold] active channels (out of {len(text_channels)} text channels, {max_messages} msgs each)...")

    total_synced = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Syncing channels...", total=len(to_sync))
        for ch in to_sync:
            cname = ch.get("name", ch["id"])
            progress.update(task, description=f"[cyan]Syncing #{cname}...")
            try:
                count = _sync_single_channel(client, repo, ch["id"], max_messages=max_messages, quiet=True)
                total_synced += count
            except Exception as e:
                console.print(f"  [red]✗ Failed to sync #{cname}: {e}[/red]")
            progress.advance(task)

    console.print(f"[bold green]✓ Completed server sync! Stored {total_synced} messages across {len(to_sync)} channels into SQLite.[/bold green]")


@cli.command("sync")
@click.argument("target_id")
@click.option("--max-messages", "-m", default=200, help="Maximum messages to sync per channel.")
@click.option("--channels", "-c", "channel_limit", default=5, help="If target is a server, number of top channels to sync.")
@click.option("--server", "-s", "is_server", is_flag=True, default=False, help="Force treat target_id as a server (guild) ID.")
def sync_cmd(target_id: str, max_messages: int, channel_limit: int, is_server: bool):
    """Sync message history for a channel or an entire server into local SQLite."""
    client = get_client()
    repo = get_repo()

    guild = repo.get_guild(target_id)
    if is_server or guild is not None:
        _sync_server_helper(client, repo, target_id, channel_limit, max_messages)
        return

    with console.status(f"[bold green]Syncing channel {target_id}..."):
        try:
            count = _sync_single_channel(client, repo, target_id, max_messages=max_messages)
            console.print(f"[bold green]✓ Successfully synced {count} messages into SQLite![/bold green]")
        except Exception as e:
            console.print(f"[bold red]Sync failed:[/bold red] {e}")


@cli.command("sync-server")
@click.argument("guild_id")
@click.option("--channels", "-c", "channel_limit", default=5, help="Number of active channels to sync (default 5).")
@click.option("--max-messages", "-m", default=100, help="Maximum messages to sync per channel.")
@click.option("--all-channels", is_flag=True, default=False, help="Sync all text channels in the server.")
def sync_server_cmd(guild_id: str, channel_limit: int, max_messages: int, all_channels: bool):
    """Sync message history for multiple active channels in a server (guild)."""
    client = get_client()
    repo = get_repo()
    lim = 999 if all_channels else channel_limit
    _sync_server_helper(client, repo, guild_id, lim, max_messages)


@cli.command("recent")
@click.argument("channel_id")
@click.option("--limit", "-n", default=20, help="Number of messages to display.")
def recent_messages(channel_id: str, limit: int):
    """Display recent messages and conversation flow from the local database."""
    repo = get_repo()
    msgs = repo.get_messages_for_channel(channel_id=channel_id, limit=limit, order_asc=True)

    if not msgs:
        console.print(f"[yellow]No messages found for channel {channel_id}. Run 'sync {channel_id}' first.[/yellow]")
        return

    builder = ContextBuilder()
    ctx = builder.build_channel_context(msgs, channel_name=channel_id)

    console.print(Panel(ctx["formatted_text"], title=f"[bold]Recent Context: #{channel_id}[/bold]", border_style="cyan"))
    console.print(f"[dim]Total messages displayed: {len(msgs)} | Estimated tokens: {ctx['token_estimate']}[/dim]")


@cli.command("summarize")
@click.argument("target_id")
@click.option("--hours", "-h", default=24, help="Hours of history to summarize (default 24). Pass 0 for all history.")
@click.option("--all", "-a", "all_time", is_flag=True, default=False, help="Summarize the whole channel or server across all time.")
@click.option("--limit", "-l", default=500, help="Max messages to analyze.")
@click.option("--server", "-s", "is_server", is_flag=True, default=False, help="Force treat target_id as a server (guild) ID.")
def summarize(target_id: str, hours: int, all_time: bool, limit: int, is_server: bool):
    """Generate an AI-powered executive summary of a channel or an entire server using Gemini."""
    repo = get_repo()
    summarizer = Summarizer(repository=repo)

    if hours <= 0:
        all_time = True

    guild = repo.get_guild(target_id)
    if is_server or guild is not None:
        gname = guild["name"] if guild else f"Server-{target_id}"
        time_desc = "all available history" if all_time else f"past {hours} hours"
        console.print(f"Analyzing [bold]{time_desc}[/bold] of activity across server [bold]{gname}[/bold] (ID: {target_id})...")

        with console.status("[bold green]Synthesizing multi-channel context and generating Gemini digest..."):
            try:
                result = summarizer.summarize_server(
                    guild_id=target_id,
                    hours_back=hours if not all_time else None,
                    limit=limit,
                    all_time=all_time,
                )
            except GeminiAPIError as e:
                console.print(f"[bold red]Gemini Summarization Error:[/bold red] {e}")
                return
            except Exception as e:
                console.print(f"[bold red]Unexpected Error:[/bold red] {e}")
                return

        if not result.get("success"):
            console.print(f"[yellow]{result.get('error')}[/yellow]")
            return

        console.print("\n" + "=" * 60)
        console.print(Markdown(result["summary_markdown"]))
        console.print("=" * 60 + "\n")

        console.print(f"[bold green]✓ Server digest generated and saved![/bold green]")
        console.print(f"  • Channels included: [bold]{result['channel_count']}[/bold]")
        console.print(f"  • Messages analyzed: [bold]{result['message_count']}[/bold]")
        console.print(f"  • Report file: [bold cyan]{result['report_path']}[/bold cyan]")
        console.print(f"  • SQLite Summary ID: [bold]{result['summary_id']}[/bold]")
        return

    # Channel summary
    time_desc = "all available history" if all_time else f"past {hours} hours"
    chan = repo.get_channel(target_id)
    cname = f"#{chan['name']}" if chan else f"channel {target_id}"
    console.print(f"Analyzing [bold]{time_desc}[/bold] of activity for [bold]{cname}[/bold]...")

    with console.status("[bold green]Synthesizing context and generating Gemini digest..."):
        try:
            result = summarizer.summarize_channel(
                channel_id=target_id,
                hours_back=hours if not all_time else None,
                limit=limit,
                all_time=all_time,
            )
        except GeminiAPIError as e:
            console.print(f"[bold red]Gemini Summarization Error:[/bold red] {e}")
            return
        except Exception as e:
            console.print(f"[bold red]Unexpected Error:[/bold red] {e}")
            return

    if not result.get("success"):
        console.print(f"[yellow]{result.get('error')}[/yellow]")
        return

    console.print("\n" + "=" * 60)
    console.print(Markdown(result["summary_markdown"]))
    console.print("=" * 60 + "\n")

    console.print(f"[bold green]✓ Digest generated and saved![/bold green]")
    console.print(f"  • Messages analyzed: [bold]{result['message_count']}[/bold]")
    console.print(f"  • Report file: [bold cyan]{result['report_path']}[/bold cyan]")
    console.print(f"  • SQLite Summary ID: [bold]{result['summary_id']}[/bold]")


@cli.command("summarize-server")
@click.argument("guild_id")
@click.option("--hours", "-h", default=24, help="Hours of history to summarize (default 24). Pass 0 for all history.")
@click.option("--all", "-a", "all_time", is_flag=True, default=False, help="Summarize across all time.")
@click.option("--limit", "-l", default=1000, help="Max messages to analyze across channels.")
def summarize_server_cmd(guild_id: str, hours: int, all_time: bool, limit: int):
    """Generate an AI-powered executive summary across all channels in a server (guild)."""
    ctx = click.get_current_context()
    ctx.invoke(summarize, target_id=guild_id, hours=hours, all_time=all_time, limit=limit, is_server=True)


@cli.command("reply")
@click.argument("channel_id")
@click.argument("message_id")
@click.option("--text", "-t", default=None, help="Direct reply text (skips interactive drafting).")
@click.option("--instruction", "-i", default=None, help="Custom instructions for AI draft generation.")
def reply_message(channel_id: str, message_id: str, text: Optional[str], instruction: Optional[str]):
    """Reply to a specific Discord message (with human-in-the-loop approval)."""
    client = get_client()
    repo = get_repo()

    if text:
        # Direct reply mode with explicit confirmation
        console.print(Panel(f"[white]{text}[/white]", title="[bold red]CONFIRM OUTGOING MESSAGE[/bold red]", border_style="red"))
        from rich.prompt import Confirm
        if Confirm.ask("Send this message to Discord as a reply?", default=True):
            try:
                sent = client.send_message(channel_id=channel_id, content=text, reply_to_message_id=message_id)
                console.print(f"[bold green]✓ Message sent! (ID: {sent.get('id')})[/bold green]")
            except Exception as e:
                console.print(f"[bold red]Failed to send:[/bold red] {e}")
        else:
            console.print("[yellow]Sending cancelled.[/yellow]")
        return

    # Interactive Human-in-the-loop workflow
    drafter = ReplyDrafter(repository=repo)
    run_interactive_reply(
        client=client,
        drafter=drafter,
        channel_id=channel_id,
        message_id=message_id,
        initial_instruction=instruction,
    )


@cli.command("daemon")
@click.option("--interval-minutes", "-i", default=60, help="Sync and summarize interval in minutes.")
def run_daemon_command(interval_minutes: int):
    """Run background scheduler to periodically sync watched channels and generate digests."""
    from ..scheduler.runner import SchedulerRunner
    runner = SchedulerRunner(interval_minutes=interval_minutes)
    runner.start()


if __name__ == "__main__":
    cli()
