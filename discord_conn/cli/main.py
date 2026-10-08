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
            gemini = GeminiClient(api_key=config.gemini_api_key, model_name=config.ai_model)
            test_resp = gemini.generate("Respond with 'OK' only.", model=config.ai_model)
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


@cli.command("sync")
@click.argument("channel_id")
@click.option("--max-messages", "-m", default=200, help="Maximum messages to sync.")
def sync_channel(channel_id: str, max_messages: int):
    """Sync recent message history for a channel into local SQLite."""
    client = get_client()
    repo = get_repo()

    with console.status(f"[bold green]Fetching channel details for {channel_id}..."):
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

    console.print(f"Syncing up to {max_messages} messages for [bold]#{cname}[/bold]...")

    with console.status("[bold green]Pulling message batches..."):
        try:
            messages = client.fetch_channel_history(channel_id, max_messages=max_messages)
            count = repo.upsert_messages_batch(messages)
            if messages:
                repo.update_sync_state(
                    channel_id=channel_id,
                    new_count=count,
                    oldest_id=messages[-1]["id"],
                    newest_id=messages[0]["id"],
                )
            console.print(f"[bold green]✓ Successfully synced {count} messages into SQLite![/bold green]")
        except Exception as e:
            console.print(f"[bold red]Sync failed:[/bold red] {e}")


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
@click.argument("channel_id")
@click.option("--hours", "-h", default=24, help="Hours of history to summarize (default 24).")
@click.option("--limit", "-l", default=500, help="Max messages to analyze.")
def summarize_channel(channel_id: str, hours: int, limit: int):
    """Generate an AI-powered executive summary of channel activity using Gemini."""
    repo = get_repo()
    summarizer = Summarizer(repository=repo)

    console.print(f"Analyzing past [bold]{hours} hours[/bold] of activity for channel [bold]{channel_id}[/bold]...")

    with console.status("[bold green]Synthesizing context and generating Gemini digest..."):
        try:
            result = summarizer.summarize_channel(
                channel_id=channel_id,
                hours_back=hours,
                limit=limit,
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

    # Print markdown output to terminal
    console.print("\n" + "=" * 60)
    console.print(Markdown(result["summary_markdown"]))
    console.print("=" * 60 + "\n")

    console.print(f"[bold green]✓ Digest generated and saved![/bold green]")
    console.print(f"  • Messages analyzed: [bold]{result['message_count']}[/bold]")
    console.print(f"  • Report file: [bold cyan]{result['report_path']}[/bold cyan]")
    console.print(f"  • SQLite Summary ID: [bold]{result['summary_id']}[/bold]")


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
