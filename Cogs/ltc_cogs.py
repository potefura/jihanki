"""Litecoin seller configuration and per-order escrow wallets."""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from datetime import timedelta

import discord
import requests
from discord import app_commands, ui
from discord.ext import commands

from Cogs.ltc_zpub import derive_ltc_address
from Cogs.server_data import payment_settings, set_payment
from utils import is_allowed


LTC_API = "https://litecoinspace.org/api"
LITOSHI = 100_000_000


def order_embed(title: str, description: str, *, error: bool = False) -> discord.Embed:
    """Build a consistent status message for the DM checkout flow."""
    return discord.Embed(
        title=title,
        description=description,
        color=discord.Color.red() if error else discord.Color.blue(),
        timestamp=discord.utils.utcnow(),
    )


def address_balance(address: str) -> tuple[int, int]:
    response = requests.get(f"{LTC_API}/address/{address}", headers={"accept": "application/json"}, timeout=10)
    response.raise_for_status()
    data = response.json()
    chain, mempool = data.get("chain_stats", {}), data.get("mempool_stats", {})
    confirmed = chain.get("funded_txo_sum", 0) - chain.get("spent_txo_sum", 0)
    pending = mempool.get("funded_txo_sum", 0) - mempool.get("spent_txo_sum", 0)
    return confirmed, pending


class LTCOrderView(ui.View):
    def __init__(self, order: dict, required: int, success_callback=None):
        super().__init__(timeout=3600)
        self.order, self.required = order, required
        self.finished = False
        self.success_callback = success_callback
        self.paid_attempts: dict[int, deque[float]] = defaultdict(deque)
        self.settle_lock = asyncio.Lock()

    async def on_timeout(self) -> None:
        """Close the order after one hour without retaining a global lock."""
        if self.finished:
            return
        self.finished = True

    def allow_paid_attempt(self, user_id: int) -> bool:
        """Allow at most five balance checks per user in a rolling minute."""
        now = time.monotonic()
        attempts = self.paid_attempts[user_id]
        while attempts and now - attempts[0] >= 60:
            attempts.popleft()
        if len(attempts) >= 5:
            return False
        attempts.append(now)
        return True

    async def _settle(self, interaction: discord.Interaction, cancelled: bool = False):
        if self.finished:
            return await interaction.response.send_message(
                embed=order_embed("処理済み", "この注文はすでに処理されています。")
            )
        if cancelled:
            self.finished = True
            for child in self.children:
                child.disabled = True
            return await interaction.response.send_message(embed=order_embed("注文キャンセル", "注文をキャンセルしました。"))
        await interaction.response.defer()
        await asyncio.sleep(10)
        try:
            confirmed, pending = await asyncio.to_thread(address_balance, self.order["address"])
        except requests.RequestException:
            return await interaction.followup.send(
                embed=order_embed("残高確認エラー", "残高APIを取得できませんでした。もう一度押してください。", error=True)
            )
        received = confirmed + pending
        if received < self.required:
            short = (self.required - received) / LITOSHI
            if confirmed < received:
                return await interaction.followup.send(
                    embed=order_embed(
                        "入金額不足・承認待ち",
                        f"必要額より少ない入金を確認しました。この入金はすでに受取先アドレスへ送られています。\n"
                        f"承認後にもう一度「送金完了」を押してください。\n不足額\n```text\n{short:.8f} LTC\n```",
                        error=True,
                    )
                )
            self.finished = True
            for child in self.children:
                child.disabled = True
            return await interaction.followup.send(
                embed=order_embed(
                    "入金額不足",
                    f"決済は完了していません。入金先への着金は確認済みです。\n"
                    f"不足額\n```text\n{short:.8f} LTC\n```",
                    error=True,
                )
            )
        if confirmed < self.required:
            return await interaction.followup.send(
                embed=order_embed("入金を確認しました", "未承認入金を確認しました。承認後にもう一度「送金完了」を押してください。")
            )
        self.finished = True
        for child in self.children:
            child.disabled = True
        await interaction.followup.send(embed=order_embed("決済が完了しました", "LTCの着金を確認しました。"))
        if self.success_callback:
            await self.success_callback(interaction)

    @ui.button(label="送金完了", style=discord.ButtonStyle.success)
    async def paid(self, interaction: discord.Interaction, button: ui.Button):
        if not self.allow_paid_attempt(interaction.user.id):
            return await interaction.response.send_message(
                embed=order_embed("レート制限", "「送金完了」は1分間に5回まで押せます。少し待ってからやり直してください。", error=True)
            )
        async with self.settle_lock:
            await self._settle(interaction)

    @ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        async with self.settle_lock:
            await self._settle(interaction, cancelled=True)


async def start_ltc_order(interaction: discord.Interaction, seller_id: str, amount_ltc: float, success_callback=None) -> bool:
    # Deriving an address and opening a DM can exceed Discord's three-second
    # interaction response window, so acknowledge the button immediately.
    await interaction.response.defer(ephemeral=True)
    settings = payment_settings(interaction.guild_id, seller_id)
    zpub = settings.get("ltc_zpub")
    if not settings.get("ltc") or not zpub:
        await interaction.followup.send(
            embed=order_embed("LTC決済エラー", "LTC決済は現在利用できません。", error=True), ephemeral=True
        )
        return False
    address_index = int(settings.get("ltc_address_index", 0))
    try:
        address = derive_ltc_address(zpub, address_index)
    except (TypeError, ValueError):
        await interaction.followup.send(
            embed=order_embed("LTC決済エラー", "登録済みzpubから入金アドレスを作成できません。", error=True), ephemeral=True
        )
        return False
    set_payment(interaction.guild_id, seller_id, "ltc", True, ltc_zpub=zpub, ltc_address_index=address_index + 1)
    order = {"address": address, "address_index": address_index}
    required = round(amount_ltc * LITOSHI)
    view = LTCOrderView(order, required, success_callback)
    embed = order_embed("Litecoin決済", "下記のアドレスへ、表示された金額を正確に送金してください。")
    expires_at = discord.utils.utcnow() + timedelta(hours=1)
    embed.add_field(name="送金先アドレス（タップしてコピー）", value=f"```text\n{order['address']}\n```", inline=False)
    embed.add_field(name="送金額（タップしてコピー）", value=f"```text\n{amount_ltc:.8f}\n```", inline=False)
    embed.add_field(
        name="支払期限",
        value=f"<t:{int(expires_at.timestamp())}:F>（<t:{int(expires_at.timestamp())}:R>）",
        inline=False,
    )
    embed.set_footer(text="未入金の注文は、キャンセル操作がなくても1時間後に自動終了します。")
    try:
        await interaction.user.send(embed=embed, view=view)
    except (discord.Forbidden, discord.HTTPException):
        await interaction.followup.send(
            embed=order_embed(
                "DMを送信できませんでした",
                "サーバーメンバーからのDMを受信できるようにしてから、もう一度やり直してください。",
                error=True,
            ),
            ephemeral=True,
        )
        return False
    await interaction.followup.send(
        embed=order_embed("DMを送信しました", "決済用ウォレットをDMに送りました。"), ephemeral=True
    )
    return True


class LTCCog(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="ltc有効化", description="登録済みLTC決済を有効化します")
    @is_allowed()
    async def enable(self, interaction: discord.Interaction):
        settings = payment_settings(interaction.guild_id, interaction.user.id)
        if not settings.get("ltc_zpub"):
            return await interaction.response.send_message("先に `/ltcウォレット設定` でzpubを設定してください。", ephemeral=True)
        set_payment(interaction.guild_id, interaction.user.id, "ltc", True)
        await interaction.response.send_message("LTC決済を有効化しました。", ephemeral=True)

    @app_commands.command(name="ltc無効化", description="LTC決済を無効化します")
    @is_allowed()
    async def disable(self, interaction: discord.Interaction):
        set_payment(interaction.guild_id, interaction.user.id, "ltc", False)
        await interaction.response.send_message("LTC決済を無効化しました。", ephemeral=True)


async def setup(bot):
    await bot.add_cog(LTCCog(bot))
