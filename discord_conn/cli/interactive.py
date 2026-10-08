"""Interactive Human-in-the-Loop reply approval and editing interface."""

import sys
from typing import Any, Dict, Optional
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from ..client.discord_api import DiscordAPIClient
from ..ai.drafter import ReplyDrafter

console = Console()


def run_interactive_reply(
    client: DiscordAPIClient,
    drafter: ReplyDrafter,
    channel_id: str,
    message_id: str,
    initial_instruction: Optional[str] = None,
) -> bool:
    """
    Guides the user through reviewing context, generating AI drafts,
    editing or writing replies, and explicitly confirming before sending to Discord.
    """
    console.print(Panel(f"[bold cyan]Interactive Reply Assistant[/bold cyan]\nChannel ID: {channel_id} | Message ID: {message_id}", border_style="cyan"))

    instruction = initial_instruction or "Acknowledge and provide a helpful, natural response."

    while True:
        with console.status("[bold green]Drafting replies with Gemini based on thread context..."):
            result = drafter.draft_reply(
                channel_id=channel_id,
                message_id=message_id,
                custom_instruction=instruction,
            )

        if not result.get("success"):
            console.print(f"[bold red]Error drafting reply:[/bold red] {result.get('error')}")
            return False

        target_msg = result["target_message"]
        author = target_msg.get("global_name") or target_msg.get("username") or "User"
        content = target_msg.get("content", "")

        console.print("\n[bold yellow]Target Message:[/bold yellow]")
        console.print(f"  [bold]<{author}>[/bold]: {content}\n")

        console.print("[bold yellow]Thread Context Preview:[/bold yellow]")
        console.print(Panel(result["context_text"], border_style="dim"))

        console.print("[bold green]Gemini Draft Suggestions:[/bold green]")
        console.print(Panel(result["raw_drafts"], border_style="green"))

        console.print("\n[bold]Options:[/bold]")
        console.print("  [1] Send a draft (type or paste the chosen text)")
        console.print("  [2] Write custom reply from scratch")
        console.print("  [3] Regenerate drafts with new instructions")
        console.print("  [4] Cancel / Do not send")

        choice = Prompt.ask("Choose an action", choices=["1", "2", "3", "4"], default="1")

        if choice == "4":
            console.print("[yellow]Reply cancelled. No message was sent to Discord.[/yellow]")
            return False

        if choice == "3":
            instruction = Prompt.ask("Enter new drafting instructions for Gemini")
            continue

        selected_text = ""
        if choice == "1":
            selected_text = Prompt.ask("\nEnter the exact text you want to send")
        elif choice == "2":
            selected_text = Prompt.ask("\nEnter your custom reply message")

        if not selected_text.strip():
            console.print("[red]Message cannot be empty.[/red]")
            continue

        # Human-in-the-Loop Confirmation
        console.print("\n" + "=" * 50)
        console.print(Panel(f"[bold white]{selected_text}[/bold white]", title="[bold red]CONFIRM OUTGOING MESSAGE[/bold red]", border_style="red"))
        console.print(f"Target: #{result['channel_name']} (Message ID: {message_id} by {author})")
        console.print("=" * 50 + "\n")

        confirmed = Confirm.ask("[bold red]Are you sure you want to send this reply to Discord?[/bold red]", default=False)
        if not confirmed:
            console.print("[yellow]Cancelled sending. Returning to options...[/yellow]")
            continue

        # Send to Discord
        try:
            with console.status("[bold green]Sending message to Discord..."):
                sent = client.send_message(
                    channel_id=channel_id,
                    content=selected_text,
                    reply_to_message_id=message_id,
                )
            console.print(f"[bold green]✓ Message successfully sent![/bold green] (Message ID: {sent.get('id')})")
            return True
        except Exception as e:
            console.print(f"[bold red]Failed to send message:[/bold red] {e}")
            return False
