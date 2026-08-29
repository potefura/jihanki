from __future__ import annotations

import re

import discord
import requests
from discord import app_commands
from discord.ext import commands

from Cogs.server_data import ensure_guild_files, payment_settings, set_payment
from utils import is_allowed


LTC_API = "https://litecoinspace.org/api"
LTC_ADDRESS = re.compile(r"^(?:ltc1[ac-hj-np-z02-9]{20,87}|[LM3][a-km-zA-HJ-NP-Z1-9]{25,34})$")


def ltc_balance(address: str) -> tuple[int, int]:
    """Return confirmed and mempool balances in litoshi."""
    response = requests.get(
        f"{LTC_API}/address/{address}",
        headers={"accept": "application/json", "user-agent": "jihanki-discord-bot/1.0"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    chain = data.get("chain_stats", {})
    mempool = data.get("mempool_stats", {})
    confirmed = chain.get("funded_txo_sum", 0) - chain.get("spent_txo_sum", 0)
    pending = mempool.get("funded_txo_sum", 0) - mempool.get("spent_txo_sum", 0)
    return confirmed, pending


class PaymentCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ltcウォレット設定", description="売上を受け取るLTCウォレットを設定します")
    @app_commands.describe(address="送金先のLitecoinアドレス")
    @is_allowed()
    async def set_ltc_wallet(self, interaction: discord.Interaction, address: str):
        if interaction.guild_id is None:
            return await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
        address = address.strip()
        if not LTC_ADDRESS.fullmatch(address):
            return await interaction.response.send_message("正しいLitecoinアドレスを入力してください。", ephemeral=True)
        ensure_guild_files(interaction.guild_id)
        set_payment(
            interaction.guild_id,
            interaction.user.id,
            "ltc",
            True,
            ltc_wallet=address,
        )
        embed = discord.Embed(
            title="LTCウォレット設定完了",
            description=f"入金先を `{address}` に設定しました。注文のLTCはこのアドレスへ直接送金されます。",
            color=discord.Color.blue(),
        )
        embed.set_footer(text="シードフレーズ・秘密鍵はBOTへ送信しないでください。")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ltc残高", description="設定済みLTCウォレットの残高を確認します")
    @is_allowed()
    async def show_ltc_balance(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            return await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
        address = payment_settings(interaction.guild_id, interaction.user.id).get("ltc_wallet")
        if not address:
            return await interaction.response.send_message("先にLTCウォレットを設定してください。", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            confirmed, pending = ltc_balance(address)
        except (requests.RequestException, ValueError):
            return await interaction.followup.send("Litecoin APIから残高を取得できませんでした。", ephemeral=True)
        embed = discord.Embed(title="LTC残高", color=discord.Color.blue())
        embed.add_field(name="承認済み", value=f"{confirmed / 100_000_000:.8f} LTC")
        embed.add_field(name="未承認", value=f"{pending / 100_000_000:.8f} LTC")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PaymentCog(bot))
