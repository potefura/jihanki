"""Guild-scoped gacha and balance commands."""
from __future__ import annotations

import json
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


def _products(item: dict) -> list[dict]:
    """Return products while transparently upgrading the old stock-only format."""
    products = item.setdefault("products", [])
    if item.get("stock"):
        for content in item.pop("stock"):
            products.append({
                "id": uuid.uuid4().hex,
                "name": "景品",
                "content": content,
                "is_loser": False,
                "received_count": 0,
            })
    return products


async def gacha_choices(interaction: discord.Interaction, current: str):
    data = load_data(interaction.guild_id, "gacha.json", {})
    return [
        app_commands.Choice(name=item["name"], value=gacha_id)
        for gacha_id, item in data.items()
        if item.get("owner_id") == str(interaction.user.id) and current.lower() in item["name"].lower()
    ][:25]


async def public_gacha_choices(interaction: discord.Interaction, current: str):
    data = load_data(interaction.guild_id, "gacha.json", {})
    return [
        app_commands.Choice(name=item.get("name", "名称未設定"), value=gacha_id)
        for gacha_id, item in data.items()
        if current.lower() in item.get("name", "").lower()
    ][:25]


class GachaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def owned(self, interaction, gacha_id):
        data = load_data(interaction.guild_id, "gacha.json", {})
        item = data.get(gacha_id)
        return data, item if item and item.get("owner_id") == str(interaction.user.id) else None

    async def _add_product(self, interaction, gacha_id: str, name: str, content: str, is_loser: bool):
        data, item = self.owned(interaction, gacha_id)
        if not item:
            return await interaction.response.send_message("ガチャが見つかりません。", ephemeral=True)
        product = {
            "id": uuid.uuid4().hex,
            "name": name,
            "content": content,
            "is_loser": is_loser,
            "received_count": 0,
        }
        _products(item).append(product)
        save_guild_json(interaction.guild_id, "gacha.json", data)
        kind = "ハズレ商品" if is_loser else "商品"
        await interaction.response.send_message(
            f"{kind}「{name}」を追加しました。ID: `{product['id']}`", ephemeral=True
        )

    async def _delete_product(self, interaction, gacha_id: str, product_id: str, is_loser: bool):
        data, item = self.owned(interaction, gacha_id)
        if not item:
            return await interaction.response.send_message("ガチャが見つかりません。", ephemeral=True)
        products = _products(item)
        product = next((p for p in products if p.get("id") == product_id and bool(p.get("is_loser")) == is_loser), None)
        if not product:
            return await interaction.response.send_message("指定された商品が見つかりません。", ephemeral=True)
        products.remove(product)
        save_guild_json(interaction.guild_id, "gacha.json", data)
        await interaction.response.send_message(f"「{product['name']}」を削除しました。", ephemeral=True)

    @app_commands.command(name="ガチャ作成", description="残高で引けるガチャを作成します")
    @is_allowed()
    async def create(self, interaction: discord.Interaction, name: str, 一回の価格: int):
        if 一回の価格 < 0:
            return await interaction.response.send_message("価格は0以上にしてください。", ephemeral=True)
        data = load_data(interaction.guild_id, "gacha.json", {})
        gacha_id = uuid.uuid4().hex
        data[gacha_id] = {
            "name": name,
            "price": 一回の価格,
            "owner_id": str(interaction.user.id),
            "products": [],
            "uses": 0,
            "log_channel_id": None,
        }
        save_guild_json(interaction.guild_id, "gacha.json", data)
        await interaction.response.send_message(f"ガチャ「{name}」を作成しました。ID: `{gacha_id}`", ephemeral=True)

    @app_commands.command(name="ガチャ商品追加", description="ガチャの当たり商品と配布内容を追加します")
    @app_commands.autocomplete(gacha_id=gacha_choices)
    @is_allowed()
    async def add_product(self, interaction: discord.Interaction, gacha_id: str, 商品名: str, 内容: str):
        await self._add_product(interaction, gacha_id, 商品名, 内容, False)

    @app_commands.command(name="ガチャ商品削除", description="ガチャの当たり商品を削除します")
    @app_commands.autocomplete(gacha_id=gacha_choices)
    @is_allowed()
    async def delete_product(self, interaction: discord.Interaction, gacha_id: str, 商品id: str):
        await self._delete_product(interaction, gacha_id, 商品id, False)

    @app_commands.command(name="ガチャハズレ商品追加", description="ガチャのハズレ商品と配布内容を追加します")
    @app_commands.autocomplete(gacha_id=gacha_choices)
    @is_allowed()
    async def add_loser(self, interaction: discord.Interaction, gacha_id: str, 商品名: str, 内容: str):
        await self._add_product(interaction, gacha_id, 商品名, 内容, True)

    @app_commands.command(name="ガチャハズレ商品削除", description="ガチャのハズレ商品を削除します")
    @app_commands.autocomplete(gacha_id=gacha_choices)
    @is_allowed()
    async def delete_loser(self, interaction: discord.Interaction, gacha_id: str, 商品id: str):
        await self._delete_product(interaction, gacha_id, 商品id, True)

    @app_commands.command(name="ガチャ在庫確認", description="商品名と受け取った人数を表示します")
    @app_commands.autocomplete(gacha_id=gacha_choices)
    @is_allowed()
    async def stock(self, interaction: discord.Interaction, gacha_id: str):
        data, item = self.owned(interaction, gacha_id)
        if not item:
            return await interaction.response.send_message("ガチャが見つかりません。", ephemeral=True)
        products = _products(item)
        save_guild_json(interaction.guild_id, "gacha.json", data)
        embed = discord.Embed(title=f"{item['name']}の商品", color=discord.Color.blue())
        if not products:
            embed.description = "商品はまだ登録されていません。"
        for product in products[:25]:
            kind = "ハズレ" if product.get("is_loser") else "当たり"
            embed.add_field(
                name=f"[{kind}] {product['name']}",
                value=f"受け取った人: **{product.get('received_count', 0)}人**\nID: `{product['id']}`",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
    @app_commands.autocomplete(gacha_id=public_gacha_choices)
    async def draw(self, interaction: discord.Interaction, gacha_id: str):
        data = load_data(interaction.guild_id, "gacha.json", {})
        item = data.get(gacha_id)
        balances = load_data(interaction.guild_id, "balance.json", {})
        user_id = str(interaction.user.id)
        products = _products(item) if item else []
        if not item or not products:
            return await interaction.response.send_message("ガチャがないか、商品が登録されていません。", ephemeral=True)
        if balances.get(user_id, 0) < item["price"]:
            return await interaction.response.send_message("残高が不足しています。", ephemeral=True)

        product = random.choice(products)
        result = "ハズレ" if product.get("is_loser") else "当たり"
        dm_embed = discord.Embed(
            title=f"ガチャ結果: {result}",
            description=product["content"],
            color=discord.Color.red() if product.get("is_loser") else discord.Color.gold(),
        )
        dm_embed.add_field(name="商品名", value=product["name"], inline=False)
        dm_delivered = True
        try:
            await interaction.user.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            dm_delivered = False

        balances[user_id] -= item["price"]
        item["uses"] = item.get("uses", 0) + 1
        if dm_delivered:
            product["received_count"] = product.get("received_count", 0) + 1
        save_guild_json(interaction.guild_id, "balance.json", balances)
        save_guild_json(interaction.guild_id, "gacha.json", data)

        if dm_delivered:
            await interaction.response.send_message(f"結果をDMに送りました。商品名: **{product['name']}**", ephemeral=True)
        else:
            await interaction.response.send_message("DMに送れませんでした。サーバーからのDMを許可してください。", ephemeral=True)

        channel = interaction.guild.get_channel(item.get("log_channel_id"))
        if channel:
            status = "DM送信成功" if dm_delivered else "DM送信失敗（商品を受け取れませんでした）"
            await channel.send(
                f"{interaction.user.mention} が「{item['name']}」を利用しました。\n"
                f"結果: **{result}** / 商品名: **{product['name']}** / {status}"
            )


async def setup(bot):
    await bot.add_cog(GachaCog(bot))
