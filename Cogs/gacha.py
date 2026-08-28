"""Guild-scoped, inventory-backed gacha and balance commands."""
from __future__ import annotations

import json
import io
import random
import uuid

import discord
from discord import app_commands
from discord.ext import commands

from Cogs.server_data import guild_dir, save_guild_json
from utils import is_allowed


def load_data(guild_id: int, name: str, default: dict) -> dict:
    path = guild_dir(guild_id) / name
    if not path.exists():
        save_guild_json(guild_id, name, default)
        return default.copy()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default.copy()


async def gacha_choices(interaction: discord.Interaction, current: str):
    data = load_data(interaction.guild_id, "gacha.json", {})
    return [
        app_commands.Choice(name=item["name"], value=gacha_id)
        for gacha_id, item in data.items()
        if item.get("owner_id") == str(interaction.user.id) and current.lower() in item["name"].lower()
    ][:25]


class GachaCog(commands.Cog):
    def __init__(self, bot): self.bot = bot

    def owned(self, interaction, gacha_id):
        data = load_data(interaction.guild_id, "gacha.json", {})
        item = data.get(gacha_id)
        return data, item if item and item.get("owner_id") == str(interaction.user.id) else None

    @app_commands.command(name="ガチャ作成", description="残高で引けるガチャを作成します")
    @is_allowed()
    async def create(self, interaction: discord.Interaction, name: str, 一回の価格: int):
        if 一回の価格 < 0:
            return await interaction.response.send_message("価格は0以上にしてください。", ephemeral=True)
        data = load_data(interaction.guild_id, "gacha.json", {})
        gacha_id = uuid.uuid4().hex
        data[gacha_id] = {"name": name, "price": 一回の価格, "owner_id": str(interaction.user.id), "stock": [], "uses": 0, "log_channel_id": None}
        save_guild_json(interaction.guild_id, "gacha.json", data)
        await interaction.response.send_message(f"ガチャ「{name}」を作成しました。ID: `{gacha_id}`", ephemeral=True)

    @app_commands.command(name="ガチャ在庫追加", description="改行区切りの景品在庫を追加します")
    @app_commands.autocomplete(gacha_id=gacha_choices)
    @is_allowed()
    async def add_stock(self, interaction: discord.Interaction, gacha_id: str, 在庫ファイル: discord.Attachment):
        data, item = self.owned(interaction, gacha_id)
        if not item:
            return await interaction.response.send_message("ガチャが見つかりません。", ephemeral=True)
        if 在庫ファイル.size > 1_000_000:
            return await interaction.response.send_message("在庫ファイルは1MB以下にしてください。", ephemeral=True)
        lines = [line.strip() for line in (await 在庫ファイル.read()).decode("utf-8-sig").splitlines() if line.strip()]
        item["stock"].extend(lines)
        save_guild_json(interaction.guild_id, "gacha.json", data)
        await interaction.response.send_message(f"{len(lines)}個追加しました。", ephemeral=True)

    @app_commands.command(name="ガチャ在庫引き出し", description="ガチャ在庫をファイルで引き出します")
    @app_commands.autocomplete(gacha_id=gacha_choices)
    @is_allowed()
    async def withdraw(self, interaction: discord.Interaction, gacha_id: str, 数量: int):
        data, item = self.owned(interaction, gacha_id)
        if not item or 数量 <= 0 or len(item["stock"]) < 数量:
            return await interaction.response.send_message("ガチャまたは在庫数を確認してください。", ephemeral=True)
        values, item["stock"] = item["stock"][:数量], item["stock"][数量:]
        save_guild_json(interaction.guild_id, "gacha.json", data)
        file = discord.File(fp=io.BytesIO("\n".join(values).encode()), filename="gacha-stock.txt")
        await interaction.response.send_message(file=file, ephemeral=True)

    @app_commands.command(name="ガチャ在庫数", description="現在のガチャ在庫数を表示します")
    @app_commands.autocomplete(gacha_id=gacha_choices)
    @is_allowed()
    async def stock_count(self, interaction: discord.Interaction, gacha_id: str):
        _, item = self.owned(interaction, gacha_id)
        await interaction.response.send_message(f"在庫数: **{len(item['stock']) if item else 0}個**", ephemeral=True)

    @app_commands.command(name="ガチャ利用数", description="ガチャが引かれた回数を表示します")
    @app_commands.autocomplete(gacha_id=gacha_choices)
    @is_allowed()
    async def uses(self, interaction: discord.Interaction, gacha_id: str):
        _, item = self.owned(interaction, gacha_id)
        await interaction.response.send_message(f"利用数: **{item['uses'] if item else 0}回**", ephemeral=True)

    @app_commands.command(name="ガチャログ", description="ガチャ利用ログの送信先を設定します")
    @app_commands.autocomplete(gacha_id=gacha_choices)
    @is_allowed()
    async def log(self, interaction: discord.Interaction, gacha_id: str, チャンネル: discord.TextChannel):
        data, item = self.owned(interaction, gacha_id)
        if not item:
            return await interaction.response.send_message("ガチャが見つかりません。", ephemeral=True)
        item["log_channel_id"] = チャンネル.id
        save_guild_json(interaction.guild_id, "gacha.json", data)
        await interaction.response.send_message(f"ログを {チャンネル.mention} に設定しました。", ephemeral=True)

    @app_commands.command(name="balance追加", description="ユーザーのガチャ残高を追加します")
    @is_allowed()
    async def add_balance(self, interaction: discord.Interaction, ユーザー: discord.Member, 金額: int):
        balances = load_data(interaction.guild_id, "balance.json", {})
        balances[str(ユーザー.id)] = balances.get(str(ユーザー.id), 0) + 金額
        save_guild_json(interaction.guild_id, "balance.json", balances)
        await interaction.response.send_message(f"{ユーザー.mention} の残高: {balances[str(ユーザー.id)]}円", ephemeral=True)

    @app_commands.command(name="ガチャを引く", description="残高を使ってガチャを1回引きます")
    async def draw(self, interaction: discord.Interaction, gacha_id: str):
        data = load_data(interaction.guild_id, "gacha.json", {})
        item = data.get(gacha_id)
        balances = load_data(interaction.guild_id, "balance.json", {})
        user_id = str(interaction.user.id)
        if not item or not item["stock"]:
            return await interaction.response.send_message("ガチャがないか、在庫切れです。", ephemeral=True)
        if balances.get(user_id, 0) < item["price"]:
            return await interaction.response.send_message("残高が不足しています。", ephemeral=True)
        balances[user_id] -= item["price"]
        index = random.randrange(len(item["stock"]))
        prize = item["stock"].pop(index)
        item["uses"] += 1
        save_guild_json(interaction.guild_id, "balance.json", balances)
        save_guild_json(interaction.guild_id, "gacha.json", data)
        await interaction.response.send_message(embed=discord.Embed(title="ガチャ結果", description=f"```{prize}```", color=discord.Color.blue()), ephemeral=True)
        channel = interaction.guild.get_channel(item.get("log_channel_id"))
        if channel:
            await channel.send(f"{interaction.user.mention} が「{item['name']}」を利用しました。")


async def setup(bot):
    await bot.add_cog(GachaCog(bot))
