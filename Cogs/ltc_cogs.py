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

from Cogs.server_data import payment_settings, set_payment
from utils import is_allowed


LTC_API = "https://litecoinspace.org/api"
LITOSHI = 100_000_000
ACTIVE_WALLETS: set[str] = set()


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


def order_receipts(order: dict, confirmed: int, pending: int) -> tuple[int, int]:
    """Return confirmed/pending amounts received after this order started."""
    initial_total = order["initial_confirmed"] + order["initial_pending"]
    received = max(0, confirmed + pending - initial_total)
    new_pending = min(received, max(0, pending - order["initial_pending"]))
    return received - new_pending, new_pending


class LTCOrderView(ui.View):
    def __init__(self, order: dict, required: int, success_callback=None):
        super().__init__(timeout=3600)
        self.order, self.required = order, required
        self.finished = False
        self.success_callback = success_callback
        self.paid_attempts: dict[int, deque[float]] = defaultdict(deque)
        self.settle_lock = asyncio.Lock()

    async def on_timeout(self) -> None:
        """Close an unpaid direct-to-wallet order after one hour."""
        if self.finished:
            return
        self.finished = True
        ACTIVE_WALLETS.discard(self.order["address"])

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
        await interaction.response.defer()
        await asyncio.sleep(10)
        try:
            confirmed, pending = await asyncio.to_thread(address_balance, self.order["address"])
        except requests.RequestException:
            return await interaction.followup.send(
                embed=order_embed("残高確認エラー", "残高APIを取得できませんでした。もう一度押してください。", error=True)
            )
        confirmed, pending = order_receipts(self.order, confirmed, pending)
        received = confirmed + pending
        if received == 0 and cancelled:
            self.finished = True
            ACTIVE_WALLETS.discard(self.order["address"])
            return await interaction.followup.send(embed=order_embed("注文キャンセル", "注文をキャンセルしました。"))
        if received < self.required and not cancelled:
            short = (self.required - received) / LITOSHI
            if confirmed < received:
                await interaction.followup.send(
                    embed=order_embed(
                        "入金額不足・承認待ち",
                        f"必要額より少ない入金を確認しました。この入金はすでに受取先アドレスへ送られています。\n"
                        f"不足額\n```text\n{short:.8f} LTC\n```",
                        error=True,
                    )
                )
                for _ in range(60):
                    await asyncio.sleep(30)
                    try:
                        current_confirmed, current_pending = await asyncio.to_thread(
                            address_balance, self.order["address"]
                        )
                        confirmed, pending = order_receipts(self.order, current_confirmed, current_pending)
                    except requests.RequestException:
                        continue
                    if confirmed >= received:
                        break
                else:
                    return await interaction.followup.send(
                        embed=order_embed(
                            "承認待ちタイムアウト",
                            "入金承認後にもう一度「送金完了」を押してください。",
                            error=True,
                        )
                    )
            self.finished = True
            ACTIVE_WALLETS.discard(self.order["address"])
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
        target = received if cancelled else self.required
        if confirmed < target:
            await interaction.followup.send(
                embed=order_embed("入金を確認しました", "未承認入金を確認しました。ネットワーク承認を待っています。")
            )
            for _ in range(60):
                await asyncio.sleep(30)
                try:
                    current_confirmed, current_pending = await asyncio.to_thread(address_balance, self.order["address"])
                    confirmed, pending = order_receipts(self.order, current_confirmed, current_pending)
                except requests.RequestException:
                    continue
                if confirmed >= target:
                    break
            else:
                return await interaction.followup.send(
                    embed=order_embed(
                        "承認待ちタイムアウト", "承認後にもう一度「送金完了」を押してください。", error=True
                    )
                )
        self.finished = True
        ACTIVE_WALLETS.discard(self.order["address"])
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
    # Checking the address and opening a DM can exceed Discord's three-second
    # interaction response window, so acknowledge the button immediately.
    await interaction.response.defer(ephemeral=True)
    settings = payment_settings(interaction.guild_id, seller_id)
    address = settings.get("ltc_wallet")
    if not settings.get("ltc") or not address:
        await interaction.followup.send(
            embed=order_embed("LTC決済エラー", "LTC決済は現在利用できません。", error=True), ephemeral=True
        )
        return False
    if address in ACTIVE_WALLETS:
        await interaction.followup.send(
            embed=order_embed("LTC決済待機中", "このLTCウォレットでは別の注文を処理中です。完了後にやり直してください。"),
            ephemeral=True,
        )
        return False
    ACTIVE_WALLETS.add(address)
    try:
        initial_confirmed, initial_pending = await asyncio.to_thread(address_balance, address)
    except requests.RequestException:
        ACTIVE_WALLETS.discard(address)
        await interaction.followup.send(
            embed=order_embed("LTC決済エラー", "入金先の残高を確認できませんでした。", error=True), ephemeral=True
        )
        return False
    order = {
        "address": address,
        "initial_confirmed": initial_confirmed,
        "initial_pending": initial_pending,
    }
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
        ACTIVE_WALLETS.discard(address)
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
        if not settings.get("ltc_wallet"):
            return await interaction.response.send_message("先に `/ltcウォレット設定` で入金先を設定してください。", ephemeral=True)
        set_payment(interaction.guild_id, interaction.user.id, "ltc", True)
        await interaction.response.send_message("LTC決済を有効化しました。", ephemeral=True)

    @app_commands.command(name="ltc無効化", description="LTC決済を無効化します")
    @is_allowed()
    async def disable(self, interaction: discord.Interaction):
        set_payment(interaction.guild_id, interaction.user.id, "ltc", False)
        await interaction.response.send_message("LTC決済を無効化しました。", ephemeral=True)


async def setup(bot):
    await bot.add_cog(LTCCog(bot))
