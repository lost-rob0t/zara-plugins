from __future__ import annotations

import asyncio
import logging
import re
import threading
from typing import Literal

import discord
from discord import app_commands

from .config import PolicyStore
from .routing import split_discord_message


logger = logging.getLogger(__name__)


def conversation_id(*, guild_id: int | None, channel_id: int) -> str:
    if guild_id is None:
        return f"discord:dm:channel:{channel_id}"
    return f"discord:guild:{guild_id}:channel:{channel_id}"


def remove_bot_mention(text: str, bot_user_id: int) -> str:
    mention = re.compile(rf"<@!?{bot_user_id}>")
    return mention.sub("", text).strip()


class ZaraDiscordBot(discord.Client):
    def __init__(self, controller, policies: PolicyStore) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.messages = True
        super().__init__(intents=intents)
        self.controller = controller
        self.policies = policies
        self.tree = app_commands.CommandTree(self)
        self._gateway_loop: asyncio.AbstractEventLoop | None = None
        self._register_commands()

    def _register_commands(self) -> None:
        root = app_commands.Group(name="zara", description="Talk to and configure Zara")
        access = app_commands.Group(name="access", description="Configure who can talk", parent=root)
        users = app_commands.Group(name="users", description="Configure authorized users", parent=root)
        channels = app_commands.Group(name="channels", description="Configure allowed channels", parent=root)

        @root.command(name="ask", description="Send a message to Zara")
        async def ask(interaction: discord.Interaction, message: str) -> None:
            if not self._interaction_allowed(interaction):
                await interaction.response.send_message(
                    "You are not authorized to talk to Zara here.",
                    ephemeral=True,
                )
                return
            await interaction.response.defer(thinking=True)
            loop = asyncio.get_running_loop()
            self.controller.submit(
                text=message,
                conversation_id=conversation_id(
                    guild_id=interaction.guild_id,
                    channel_id=interaction.channel_id,
                ),
                on_response=lambda text: self._schedule(
                    loop,
                    self._send_interaction(interaction, text),
                ),
                on_error=lambda text: self._schedule(
                    loop,
                    self._send_interaction(interaction, text),
                ),
            )

        @root.command(name="status", description="Show Zara's access settings")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def status(interaction: discord.Interaction) -> None:
            if not await self._require_manager(interaction):
                return
            policy = self.policies.policy(interaction.guild_id)
            users_text = (
                ", ".join(f"<@{user_id}>" for user_id in sorted(policy.authorized_user_ids))
                or "none"
            )
            channels_text = (
                ", ".join(
                    f"<#{channel_id}>" for channel_id in sorted(policy.allowed_channel_ids)
                )
                or "all channels"
            )
            await interaction.response.send_message(
                f"Access: **{policy.access_mode}**\n"
                f"Authorized users: {users_text}\n"
                f"Allowed channels: {channels_text}",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        @access.command(name="set", description="Set open or authorized-user access")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def set_access(
            interaction: discord.Interaction,
            mode: Literal["open", "restricted"],
        ) -> None:
            if not await self._require_manager(interaction):
                return
            self.policies.set_access_mode(interaction.guild_id, mode)
            await interaction.response.send_message(
                f"Zara access is now **{mode}**.",
                ephemeral=True,
            )

        @users.command(name="add", description="Authorize a user")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def add_user(interaction: discord.Interaction, user: discord.User) -> None:
            if not await self._require_manager(interaction):
                return
            changed = self.policies.add_authorized_user(interaction.guild_id, user.id)
            message = f"Authorized {user.mention}." if changed else f"{user.mention} is already authorized."
            await interaction.response.send_message(message, ephemeral=True)

        @users.command(name="remove", description="Remove an authorized user")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def remove_user(interaction: discord.Interaction, user: discord.User) -> None:
            if not await self._require_manager(interaction):
                return
            changed = self.policies.remove_authorized_user(interaction.guild_id, user.id)
            message = f"Removed {user.mention}." if changed else f"{user.mention} was not authorized."
            await interaction.response.send_message(message, ephemeral=True)

        @users.command(name="clear", description="Remove every authorized user")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def clear_users(interaction: discord.Interaction) -> None:
            if not await self._require_manager(interaction):
                return
            changed = self.policies.clear_authorized_users(interaction.guild_id)
            message = "Cleared authorized users." if changed else "The authorized-user list is already empty."
            await interaction.response.send_message(message, ephemeral=True)

        @channels.command(name="add", description="Allow Zara in a channel")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def add_channel(
            interaction: discord.Interaction,
            channel: discord.TextChannel,
        ) -> None:
            if not await self._require_manager(interaction):
                return
            changed = self.policies.add_allowed_channel(interaction.guild_id, channel.id)
            message = f"Allowed {channel.mention}." if changed else f"{channel.mention} is already allowed."
            await interaction.response.send_message(message, ephemeral=True)

        @channels.command(name="remove", description="Disallow Zara in a channel")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def remove_channel(
            interaction: discord.Interaction,
            channel: discord.TextChannel,
        ) -> None:
            if not await self._require_manager(interaction):
                return
            changed = self.policies.remove_allowed_channel(interaction.guild_id, channel.id)
            message = f"Removed {channel.mention}." if changed else f"{channel.mention} was not allowed."
            await interaction.response.send_message(message, ephemeral=True)

        @channels.command(name="clear", description="Allow Zara in every channel")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def clear_channels(interaction: discord.Interaction) -> None:
            if not await self._require_manager(interaction):
                return
            changed = self.policies.clear_allowed_channels(interaction.guild_id)
            message = "Zara is now allowed in every channel." if changed else "Zara is already allowed in every channel."
            await interaction.response.send_message(message, ephemeral=True)

        self.tree.add_command(root)

    async def setup_hook(self) -> None:
        self._gateway_loop = asyncio.get_running_loop()
        await self.tree.sync()

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or self.user is None:
            return
        if message.guild is not None and self.user not in message.mentions:
            return
        if not self.policies.is_allowed(
            guild_id=message.guild.id if message.guild else None,
            user_id=message.author.id,
            channel_id=message.channel.id,
            parent_channel_id=getattr(message.channel, "parent_id", None),
        ):
            await message.channel.send(
                "You are not authorized to talk to Zara here.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        text = (
            remove_bot_mention(message.content, self.user.id)
            if message.guild is not None
            else message.content.strip()
        )
        if not text:
            await message.channel.send(
                "Mention me with a message, or use `/zara ask`.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        loop = asyncio.get_running_loop()
        self.controller.submit(
            text=text,
            conversation_id=conversation_id(
                guild_id=message.guild.id if message.guild else None,
                channel_id=message.channel.id,
            ),
            on_response=lambda response: self._schedule(
                loop,
                self._send_channel(message.channel, response),
            ),
            on_error=lambda error: self._schedule(
                loop,
                self._send_channel(message.channel, error),
            ),
        )

    def run_gateway(self, token: str, _stop_event: threading.Event) -> None:
        self.run(token, log_handler=None)

    def request_close(self) -> None:
        if self._gateway_loop is not None and not self._gateway_loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.close(), self._gateway_loop)

    def _interaction_allowed(self, interaction: discord.Interaction) -> bool:
        return self.policies.is_allowed(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            channel_id=interaction.channel_id,
            parent_channel_id=getattr(interaction.channel, "parent_id", None),
        )

    @staticmethod
    async def _require_manager(interaction: discord.Interaction) -> bool:
        if interaction.guild_id is not None:
            permissions = getattr(interaction.user, "guild_permissions", None)
            if permissions is not None and (
                permissions.manage_guild or permissions.administrator
            ):
                return True
        await interaction.response.send_message(
            "Manage Server permission is required for this setup command.",
            ephemeral=True,
        )
        return False

    @staticmethod
    def _schedule(loop: asyncio.AbstractEventLoop, coroutine) -> None:
        if loop.is_closed():
            coroutine.close()
            return
        asyncio.run_coroutine_threadsafe(coroutine, loop)

    @staticmethod
    async def _send_channel(channel, text: str) -> None:
        chunks = split_discord_message(text) or ["Zara returned an empty response."]
        for chunk in chunks:
            await channel.send(chunk, allowed_mentions=discord.AllowedMentions.none())

    @staticmethod
    async def _send_interaction(interaction: discord.Interaction, text: str) -> None:
        chunks = split_discord_message(text) or ["Zara returned an empty response."]
        for chunk in chunks:
            await interaction.followup.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none(),
            )
