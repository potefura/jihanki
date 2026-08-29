from __future__ import annotations

import discord
import requests
from discord import app_commands
from discord.ext import commands

from Cogs.ltc_zpub import derive_ltc_address
from Cogs.server_data import ensure_guild_files, payment_settings, set_payment
from utils import is_allowed


LTC_API = "https://litecoinspace.org/api"
IAN_COLEMAN_BIP39_URL = "https://iancoleman.io/bip39/"
IAN_COLEMAN_GITHUB_URL = "https://github.com/iancoleman/bip39"


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

    @app_commands.command(name="ltcウォレット設定", description="Ian Coleman BIP39から出力したzpubを設定します")
    @app_commands.describe(zpub="Account Extended Public Key欄のzpub（秘密鍵やシードは入力禁止）")
    @is_allowed()
    async def set_ltc_wallet(self, interaction: discord.Interaction, zpub: str):
        if interaction.guild_id is None:
            return await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
        zpub = zpub.strip()
        try:
            first_address = derive_ltc_address(zpub, 0)
        except ValueError:
            return await interaction.response.send_message(
                "正しいzpubを入力してください。シードや秘密鍵は入力しないでください。", ephemeral=True
            )
        ensure_guild_files(interaction.guild_id)
        set_payment(
            interaction.guild_id,
            interaction.user.id,
            "ltc",
            True,
            ltc_zpub=zpub,
            ltc_address_index=0,
        )
        embed = discord.Embed(
            title="LTCウォレット設定完了",
            description=f"zpubを設定しました。最初の入金アドレスは `{first_address}` です。",
            color=discord.Color.blue(),
        )
        embed.add_field(name="導出ツール", value=f"[Ian Coleman BIP39]({IAN_COLEMAN_BIP39_URL})", inline=False)
        embed.set_footer(text="シードフレーズ・秘密鍵はBOTへ送信しないでください。")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ltc設定方法", description="zpubの取得方法と設定時の注意を表示します")
    @is_allowed()
    async def ltc_setup_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="LTC zpub設定方法",
            description=(
                f"[Ian Coleman BIP39]({IAN_COLEMAN_BIP39_URL}) でLitecoinのアカウントを開き、"
                "`Account Extended Public Key` に表示された **zpubだけ** を "
                "`/ltcウォレット設定` へ入力してください。"
            ),
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="重要",
            value="シードフレーズ、xprv、zprv、秘密鍵は絶対にBOTや他人へ送信しないでください。",
            inline=False,
        )
        embed.add_field(name="ソースコード", value=f"[GitHub]({IAN_COLEMAN_GITHUB_URL})", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ltc残高", description="設定済みLTCウォレットの残高を確認します")
    @is_allowed()
    async def show_ltc_balance(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            return await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
        settings = payment_settings(interaction.guild_id, interaction.user.id)
        zpub = settings.get("ltc_zpub")
        if not zpub:
            return await interaction.response.send_message("先にLTCウォレットを設定してください。", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            addresses = [derive_ltc_address(zpub, index) for index in range(int(settings.get("ltc_address_index", 0)))]
            balances = [ltc_balance(address) for address in addresses]
            confirmed = sum(balance[0] for balance in balances)
            pending = sum(balance[1] for balance in balances)
        except (requests.RequestException, ValueError):
            return await interaction.followup.send("Litecoin APIから残高を取得できませんでした。", ephemeral=True)
        embed = discord.Embed(title="LTC残高", color=discord.Color.blue())
        embed.add_field(name="承認済み", value=f"{confirmed / 100_000_000:.8f} LTC")
        embed.add_field(name="未承認", value=f"{pending / 100_000_000:.8f} LTC")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PaymentCog(bot))
