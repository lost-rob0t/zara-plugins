from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import timedelta
import random

import discord

from .bot import ZaraDiscordBot, bare_mention_prompt, conversation_id, remove_bot_mention
from .inspection import inspection_context
from .moderation import ModerationContext, ModerationContextStore
from .moderation_acknowledgements import ModerationAcknowledgementStore
from .moderation_audit import ModerationAudit


EXECUTION_TIMEOUT_SECONDS = 15.0
PROTECTED_PERMISSION_NAMES = (
    "administrator",
    "manage_guild",
    "moderate_members",
    "kick_members",
    "ban_members",
    "manage_messages",
)
ACKNOWLEDGEMENT_ACTIONS = frozenset({"warn", "timeout", "kick", "ban"})


class ModeratedZaraDiscordBot(ZaraDiscordBot):
    def __init__(
        self,
        controller,
        policies,
        contexts: ModerationContextStore,
        acknowledgements: ModerationAcknowledgementStore,
        audit: ModerationAudit,
        *,
        message_content: bool = False,
    ) -> None:
        super().__init__(
            controller,
            policies,
            message_content=message_content,
        )
        self.moderation_contexts = contexts
        self.moderation_acknowledgements = acknowledgements
        self.moderation_audit = audit

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or self.user is None:
            return

        guild_id = message.guild.id if message.guild else None
        mentioned = message.guild is not None and self.user in message.mentions
        spontaneous = False
        inspection_policy = None

        if message.guild is not None:
            inspection_policy = self.policies.inspection_policy(
                message.guild.id,
                message.channel.id,
            )

        if message.guild is not None and not mentioned:
            if not inspection_policy.enabled:
                return
            if random.random() >= inspection_policy.chance:
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
                trigger_prompt=inspection_policy.trigger_prompt,
                response_style_prompt=inspection_policy.response_style_prompt,
            )
        else:
            text = remove_bot_mention(message.content, self.user.id)
            if not text:
                text = bare_mention_prompt(display_name)

        if not text:
            return

        if (
            message.guild is not None
            and inspection_policy is not None
            and inspection_policy.moderation_enabled
        ):
            token = self.moderation_contexts.issue(
                guild_id=message.guild.id,
                channel_id=message.channel.id,
                message_id=message.id,
                target_id=message.author.id,
            )
            text += (
                " Moderation mode is enabled for this Discord channel. "
                f"Current scoped moderation context_token={token}. "
                "Use only the discord_moderation_* tools with this token; it is "
                "short-lived and bound to this exact message and author. Never "
                "invent or substitute Discord IDs."
            )

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

    def execute_moderation(
        self,
        action: str,
        context: ModerationContext,
        reason: str,
        timeout_seconds: int | None,
    ) -> str:
        loop = self._gateway_loop
        if loop is None or loop.is_closed():
            raise RuntimeError("Discord moderation is unavailable because the gateway is not running")
        future = asyncio.run_coroutine_threadsafe(
            self._execute_moderation_async(action, context, reason, timeout_seconds),
            loop,
        )
        try:
            return future.result(timeout=EXECUTION_TIMEOUT_SECONDS)
        except FutureTimeoutError as error:
            future.cancel()
            raise RuntimeError("Discord moderation action timed out without confirmed success") from error

    async def _execute_moderation_async(
        self,
        action: str,
        context: ModerationContext,
        reason: str,
        timeout_seconds: int | None,
    ) -> str:
        policy = self.policies.inspection_policy(context.guild_id, context.channel_id)
        if not policy.moderation_enabled:
            return self._refuse(context, action, "moderation mode is disabled for this channel")

        guild = self.get_guild(context.guild_id)
        if guild is None:
            return self._refuse(context, action, "Discord guild is unavailable")
        channel = self.get_channel(context.channel_id)
        if channel is None or getattr(channel, "guild", None) is None:
            return self._refuse(context, action, "Discord channel is unavailable")
        if channel.guild.id != context.guild_id:
            return self._refuse(context, action, "cross-guild channel mismatch")

        try:
            message = await channel.fetch_message(context.message_id)
        except Exception as error:
            self._audit(context, action, "failed", f"cannot resolve current message: {error}")
            raise RuntimeError("Discord moderation failed: current message could not be resolved") from error
        if (
            message.id != context.message_id
            or message.channel.id != context.channel_id
            or message.guild is None
            or message.guild.id != context.guild_id
            or message.author.id != context.target_id
        ):
            return self._refuse(context, action, "scoped message target mismatch")

        target = guild.get_member(context.target_id)
        if target is None:
            try:
                target = await guild.fetch_member(context.target_id)
            except Exception as error:
                self._audit(context, action, "failed", f"cannot resolve current member: {error}")
                raise RuntimeError("Discord moderation failed: current member could not be resolved") from error

        protected_reason = self._protected_reason(guild, target)
        if protected_reason:
            return self._refuse(context, action, protected_reason)

        if action == "inspect":
            permissions = [
                name
                for name in PROTECTED_PERMISSION_NAMES
                if getattr(target.guild_permissions, name, False)
            ]
            self._audit(context, action, "succeeded", "current member inspected")
            return (
                f"current_member target_id={target.id} protected=false "
                f"moderation_enabled=true protected_permissions={permissions}"
            )

        self._audit(context, action, "attempted", reason or "moderation action requested")
        try:
            if action == "delete":
                await message.delete()
            elif action == "warn":
                if not reason:
                    raise ValueError("warn requires a non-empty reason")
                await message.reply(
                    reason,
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            elif action == "timeout":
                if timeout_seconds is None:
                    raise ValueError("timeout requires timeout_seconds")
                until = discord.utils.utcnow() + timedelta(seconds=timeout_seconds)
                await target.timeout(until, reason=reason or None)
            elif action == "kick":
                await target.kick(reason=reason or None)
            elif action == "ban":
                await guild.ban(target, reason=reason or None, delete_message_seconds=0)
            else:
                raise ValueError(f"unsupported moderation action: {action!r}")
        except Exception as error:
            self._audit(context, action, "failed", str(error))
            raise RuntimeError(
                f"Discord moderation {action} failed without confirmed success: {error}"
            ) from error

        self._audit(context, action, "succeeded", reason or "moderation action succeeded")
        acknowledgement = ""
        if action in ACKNOWLEDGEMENT_ACTIONS:
            acknowledgement = self.moderation_acknowledgements.moderation_acknowledgement(
                context.guild_id,
                context.channel_id,
                action,
            )
        if acknowledgement:
            await channel.send(
                acknowledgement,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        return f"discord moderation {action} succeeded for scoped target_id={context.target_id}"

    def _protected_reason(self, guild, target) -> str:
        if self.user is not None and target.id == self.user.id:
            return "bot/self target is protected"
        if getattr(target, "bot", False):
            return "bot target is protected"
        if target.id == guild.owner_id:
            return "guild owner is protected"
        protected = [
            name
            for name in PROTECTED_PERMISSION_NAMES
            if getattr(target.guild_permissions, name, False)
        ]
        if protected:
            return f"member is protected by moderation permissions: {','.join(protected)}"
        return ""

    def _refuse(self, context: ModerationContext, action: str, reason: str) -> str:
        self._audit(context, action, "refused", reason)
        return f"discord moderation {action} refused: {reason}"

    def _audit(
        self,
        context: ModerationContext,
        action: str,
        outcome: str,
        reason: str,
    ) -> None:
        self.moderation_audit.record(
            guild_id=context.guild_id,
            channel_id=context.channel_id,
            message_id=context.message_id,
            target_id=context.target_id,
            action=action,
            outcome=outcome,
            reason=reason,
        )
