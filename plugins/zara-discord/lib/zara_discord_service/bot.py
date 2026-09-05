from __future__ import annotations

import asyncio
import logging
import random
import re
import threading
from typing import Literal

import discord
from discord import app_commands

from .config import PolicyStore
from .inspection import inspection_context
from .routing import split_discord_message


logger = logging.getLogger(__name__)


def conversation_id(*, guild_id: int | None, channel_id: int, user_id: int) -> str:
    identifiers = {
        "channel_id": channel_id,
        "user_id": user_id,
    }
    if guild_id is not None:
        identifiers["guild_id"] = guild_id
    for name, value in identifiers.items():
        if type(value) is not int:
            raise TypeError(f"{name} must be an integer Discord ID")
        if value < 0:
            raise ValueError(f"{name} must be a non-negative Discord ID")

    if guild_id is None:
        return f"discord:dm:channel:{channel_id}:user:{user_id}"
    return f"discord:guild:{guild_id}:channel:{channel_id}:user:{user_id}"


def remove_bot_mention(text: str, bot_user_id: int) -> str:
    mention = re.compile(rf"<@!?{bot_user_id}>")
    return mention.sub("", text).strip()


def bare_mention_prompt(display_name: str) -> str:
    return (
        f"{display_name} pinged you in Discord without adding a message. "
        "Reply naturally, briefly, and in character."
    )


def spontaneous_reply_prompt(display_name: str, content: str) -> str:
    content = content.strip()
    if content:
        return (
            f"Spontaneously join the Discord conversation by replying to {display_name}. "
            f"They just said: {content}"
        )
    return (
        f"Spontaneously say something brief and in character to {display_name} "
        "in this Discord channel."
    )


class ZaraDiscordBot(discord.Client):
    def __init__(
        self,
        controller,
        policies: PolicyStore,
        *,
        message_content: bool = False,
    ) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.messages = True
        intents.message_content = bool(message_content)
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
        random_group = app_commands.Group(
            name="random",
            description="Configure Zara's spontaneous replies",
        )

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
                    user_id=interaction.user.id,
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
            random_text = "on" if policy.random_mode else "off"
            await interaction.response.send_message(
                f"Access: **{policy.access_mode}**\n"
                f"Authorized users: {users_text}\n"
                f"Allowed channels: {channels_text}\n"
                f"Random replies: **{random_text}** "
                f"({policy.random_reply_chance * 100:g}% chance)",
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

        @random_group.command(name="on", description="Enable spontaneous Zara replies")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def random_on(interaction: discord.Interaction) -> None:
            if not await self._require_manager(interaction):
                return
            self.policies.set_random_mode(interaction.guild_id, True)
            chance = self.policies.policy(interaction.guild_id).random_reply_chance * 100
            await interaction.response.send_message(
                f"Random replies are **on** ({chance:g}% chance per eligible message).",
                ephemeral=True,
            )

        @random_group.command(name="off", description="Disable spontaneous Zara replies")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def random_off(interaction: discord.Interaction) -> None:
            if not await self._require_manager(interaction):
                return
            self.policies.set_random_mode(interaction.guild_id, False)
            await interaction.response.send_message(
                "Random replies are **off**.",
                ephemeral=True,
            )

        @random_group.command(name="chance", description="Set random reply chance from 0 to 100 percent")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def random_chance(
            interaction: discord.Interaction,
            percent: app_commands.Range[float, 0.0, 100.0],
        ) -> None:
            if not await self._require_manager(interaction):
                return
            self.policies.set_random_reply_chance(interaction.guild_id, percent / 100.0)
            await interaction.response.send_message(
                f"Random reply chance is now **{percent:g}%**.",
                ephemeral=True,
            )

        self.tree.add_command(root)
        self.tree.add_command(random_group)

    async def setup_hook(self) -> None:
        self._gateway_loop = asyncio.get_running_loop()
        await self.tree.sync()

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or self.user is None:
            return

        guild_id = message.guild.id if message.guild else None
        mentioned = message.guild is not None and self.user in message.mentions
        spontaneous = False

        if message.guild is not None and not mentioned:
            policy = self.policies.policy(message.guild.id)
            if not policy.random_mode:
                return
            if random.random() >= policy.random_reply_chance:
                return
            spontaneous = True

        if not self.policies.is_allowed(
            guild_id=guild_id,
            user_id=message.author.id,
            channel_id=message.channel.id,
            parent_channel_id=getattr(message.channel, "parent_id", None),
        ):
            if not spontaneous:
                await message.channel.send(
                    "You are not authorized to talk to Zara here.",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            return

        display_name = getattr(message.author, "display_name", message.author.name)
        if message.guild is None:
            text = message.content.strip()
        elif spontaneous:
            text = inspection_context(
                display_name=display_name,
                content=message.content,
                content_available=bool(self.intents.message_content),
            )
        else:
            text = remove_bot_mention(message.content, self.user.id)
            if not text:
                text = bare_mention_prompt(display_name)

        if not text:
            return

        loop = asyncio.get_running_loop()
        send = self._send_reply if message.guild is not None else self._send_channel_message
        self.controller.submit(
            text=text,
            conversation_id=conversation_id(
                guild_id=guild_id,
                channel_id=message.channel.id,
                user_id=message.author.id,
            ),
            on_response=lambda response: self._schedule(
                loop,
                send(message, response),
            ),
            on_error=lambda error: self._schedule(
                loop,
                send(message, error),
            ),
        )

    def run_gateway(self, token: str, _stop_event: threading.Event) -> None:
        try:
            self.run(token, log_handler=None)
        except discord.PrivilegedIntentsRequired as error:
            raise RuntimeError(
                "Discord rejected the requested Message Content privileged intent; "
                "enable Message Content Intent for this bot in the Discord Developer "
                "Portal or disable random inspection and restart Zara"
            ) from error

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
            guild = interaction.guild
            if guild is not None and guild.owner_id == interaction.user.id:
                return True

            permission_sets = (
                getattr(interaction, "permissions", None),
                getattr(interaction.user, "guild_permissions", None),
            )
            for permissions in permission_sets:
                if permissions is not None and (
                    getattr(permissions, "manage_guild", False)
                    or getattr(permissions, "administrator", False)
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
    async def _send_channel_message(message: discord.Message, text: str) -> None:
        await ZaraDiscordBot._send_channel(message.channel, text)

    @staticmethod
    async def _send_reply(message: discord.Message, text: str) -> None:
        chunks = split_discord_message(text) or ["Zara returned an empty response."]
        first, *rest = chunks
        await message.reply(
            first,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        for chunk in rest:
            await message.channel.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @staticmethod
    async def _send_interaction(interaction: discord.Interaction, text: str) -> None:
        chunks = split_discord_message(text) or ["Zara returned an empty response."]
        for chunk in chunks:
            await interaction.followup.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none(),
            )
