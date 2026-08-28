"""Litecoin seller configuration and per-order escrow wallets."""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from pathlib import Path

import discord
import requests
from bitcoinlib.wallets import Wallet as BitcoinWallet, wallet_delete_if_exists
from discord import app_commands, ui
from discord.ext import commands

from Cogs.server_data import guild_dir, payment_settings, set_payment
from utils import is_allowed


LTC_API = "https://litecoinspace.org/api"
LITOSHI = 100_000_000
LTC_ADDRESS = re.compile(r"^(?:ltc1[ac-hj-np-z02-9]{20,87}|[LM3][a-km-zA-HJ-NP-Z1-9]{25,34})$")


def address_balance(address: str) -> tuple[int, int]:
    response = requests.get(f"{LTC_API}/address/{address}", headers={"accept": "application/json"}, timeout=10)
    response.raise_for_status()
    data = response.json()
    chain, mempool = data.get("chain_stats", {}), data.get("mempool_stats", {})
    confirmed = chain.get("funded_txo_sum", 0) - chain.get("spent_txo_sum", 0)
    pending = mempool.get("funded_txo_sum", 0) - mempool.get("spent_txo_sum", 0)
    return confirmed, pending


def create_order_wallet(guild_id: int, order_id: str) -> dict:
    """Create an isolated temporary wallet for one order."""
    cache = guild_dir(guild_id) / "cache"
    database_file = cache / f"ltc-{order_id}.sqlite"
    database = f"sqlite:///{database_file.resolve()}"
    wallet_name = f"jihanki-{guild_id}-{order_id}"
    wallet = BitcoinWallet.create(name=wallet_name, network="litecoin", db_uri=database)
    key = wallet.get_key()
    os.chmod(database_file, 0o600)
    order = {
        "order_id": order_id,
        "wallet_name": wallet.name,
        "database": database,
        "database_file": str(database_file.resolve()),
        "address": key.address,
    }
    path = cache / f"ltc-{order_id}.json"
    order["recovery_file"] = str(path.resolve())
    path.write_text(json.dumps(order, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(path, 0o600)
    return order


def destroy_order_wallet(order: dict) -> None:
    """Remove the temporary wallet and every local recovery artifact."""
    wallet_delete_if_exists(order["wallet_name"], db_uri=order["database"], force=True)
    for filename in (
        order.get("recovery_file"),
        order.get("database_file"),
        f"{order.get('database_file')}-wal" if order.get("database_file") else None,
        f"{order.get('database_file')}-shm" if order.get("database_file") else None,
    ):
        if filename:
            Path(filename).unlink(missing_ok=True)


def sweep_order(order: dict, recipient: str, amount: int) -> str:
    """Sweep the temporary wallet to the seller, then destroy it."""
    wallet = BitcoinWallet(order["wallet_name"], db_uri=order["database"])
    wallet.scan()
    fee = max(2_000, int(amount * 0.001))
    if amount <= fee:
        raise ValueError("送金額がネットワーク手数料以下です。")
    transaction = wallet.send_to(recipient, amount - fee, fee=fee, broadcast=False)
    response = requests.post(
        f"{LTC_API}/tx", data=transaction.raw_hex(), headers={"Content-Type": "text/plain"}, timeout=15
    )
    response.raise_for_status()
    txid = response.text.strip()
    destroy_order_wallet(order)
    return txid


class LTCOrderView(ui.View):
    def __init__(self, order: dict, required: int, seller_wallet: str, success_callback=None):
        super().__init__(timeout=1800)
        self.order, self.required, self.seller_wallet = order, required, seller_wallet
        self.finished = False
        self.success_callback = success_callback

    async def _settle(self, interaction: discord.Interaction, cancelled: bool = False):
        if self.finished:
            return await interaction.response.send_message("この注文は処理済みです。", ephemeral=True)
        await interaction.response.defer()
        await asyncio.sleep(10)
        try:
            confirmed, pending = await asyncio.to_thread(address_balance, self.order["address"])
        except requests.RequestException:
            return await interaction.followup.send("残高APIを取得できませんでした。もう一度押してください。")
        received = confirmed + pending
        if received == 0 and cancelled:
            self.finished = True
            await asyncio.to_thread(destroy_order_wallet, self.order)
            return await interaction.followup.send("注文をキャンセルしました。")
        if received < self.required and not cancelled:
            short = (self.required - received) / LITOSHI
            return await interaction.followup.send(f"金額があと **{short:.8f} LTC** 足りません。")
        target = received if cancelled else self.required
        if confirmed < target:
            await interaction.followup.send("未承認入金を確認しました。ネットワーク承認を待っています。")
            for _ in range(60):
                await asyncio.sleep(30)
                try:
                    confirmed, pending = await asyncio.to_thread(address_balance, self.order["address"])
                except requests.RequestException:
                    continue
                if confirmed >= target:
                    break
            else:
                return await interaction.followup.send("承認待ちがタイムアウトしました。承認後にもう一度押してください。")
        try:
            txid = await asyncio.to_thread(sweep_order, self.order, self.seller_wallet, confirmed)
        except (requests.RequestException, ValueError) as error:
            return await interaction.followup.send(f"販売者ウォレットへの送金に失敗しました: {error}")
        self.finished = True
        for child in self.children:
            child.disabled = True
        await interaction.followup.send(f"決済が完了しました。`{txid}`")
        if self.success_callback:
            await self.success_callback(interaction)

    @ui.button(label="送金完了", style=discord.ButtonStyle.success)
    async def paid(self, interaction: discord.Interaction, button: ui.Button):
        await self._settle(interaction)

    @ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await self._settle(interaction, cancelled=True)


async def start_ltc_order(interaction: discord.Interaction, seller_id: str, amount_ltc: float, success_callback=None) -> bool:
    settings = payment_settings(interaction.guild_id, seller_id)
    recipient = settings.get("ltc_wallet")
    if not settings.get("ltc") or not recipient:
        await interaction.response.send_message("販売者のLTC決済は現在利用できません。", ephemeral=True)
        return False
    order_id = uuid.uuid4().hex
    try:
        order = await asyncio.to_thread(create_order_wallet, interaction.guild_id, order_id)
    except (ImportError, ModuleNotFoundError):
        await interaction.response.send_message("bitcoinlibがインストールされていません。", ephemeral=True)
        return False
    required = round(amount_ltc * LITOSHI)
    view = LTCOrderView(order, required, recipient, success_callback)
    embed = discord.Embed(
        title="Litecoin決済",
        description=f"`{order['address']}` に **{amount_ltc:.8f} LTC** を送ってください。",
        color=discord.Color.blue(),
    )
    try:
        await interaction.user.send(embed=embed, view=view)
    except (discord.Forbidden, discord.HTTPException):
        await asyncio.to_thread(destroy_order_wallet, order)
        await interaction.response.send_message("DMを受信できるようにしてからやり直してください。", ephemeral=True)
        return False
    await interaction.response.send_message("決済用ウォレットをDMに送りました。", ephemeral=True)
    return True


class LTCCog(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="ltc登録", description="売上受取用Litecoinウォレットを登録します")
    @is_allowed()
    async def register(self, interaction: discord.Interaction, address: str):
        if not interaction.guild_id or not LTC_ADDRESS.fullmatch(address.strip()):
            return await interaction.response.send_message("サーバー内で正しいLTCアドレスを指定してください。", ephemeral=True)
        set_payment(interaction.guild_id, interaction.user.id, "ltc", True, ltc_wallet=address.strip())
        await interaction.response.send_message(embed=discord.Embed(title="LTC登録完了", color=discord.Color.blue()), ephemeral=True)

    @app_commands.command(name="ltc有効化", description="登録済みLTC決済を有効化します")
    @is_allowed()
    async def enable(self, interaction: discord.Interaction):
        settings = payment_settings(interaction.guild_id, interaction.user.id)
        if not settings.get("ltc_wallet"):
            return await interaction.response.send_message("先に `/ltc登録` を実行してください。", ephemeral=True)
        set_payment(interaction.guild_id, interaction.user.id, "ltc", True)
        await interaction.response.send_message("LTC決済を有効化しました。", ephemeral=True)

    @app_commands.command(name="ltc無効化", description="LTC決済を無効化します")
    @is_allowed()
    async def disable(self, interaction: discord.Interaction):
        set_payment(interaction.guild_id, interaction.user.id, "ltc", False)
        await interaction.response.send_message("LTC決済を無効化しました。", ephemeral=True)


async def setup(bot):
    await bot.add_cog(LTCCog(bot))
