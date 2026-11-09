"""Recursos de servidor: botão de verificação (aceitar regras) e salas de voz privadas.

- Verificação: o botão guarda no próprio ID qual cargo deve dar ("verify:<id do cargo>"),
  então funciona em qualquer servidor e continua funcionando depois que o bot reinicia.
- Salas privadas: qualquer canal de voz cujo nome começa com "➕" vira um "criador".
  Quem entra nele ganha uma sala trancada só sua; o dono convida amigos com /sala.
  A sala é apagada quando fica vazia.
"""
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.util import UserError

log = logging.getLogger("bot.servidor")
CREATOR_PREFIX = "➕"


# ================================================================== verificação
class VerifyButton(discord.ui.DynamicItem[discord.ui.Button], template=r"verify:(?P<role>[0-9]+)"):
    def __init__(self, role_id: int):
        super().__init__(discord.ui.Button(label="Li e aceito as regras", emoji="✅",
                                           style=discord.ButtonStyle.success, custom_id=f"verify:{role_id}"))
        self.role_id = role_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match):
        return cls(int(match["role"]))

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            return await interaction.response.send_message("⚠️ O cargo de verificação não existe mais. "
                                                           "Avise um admin.", ephemeral=True)
        if role in interaction.user.roles:
            return await interaction.response.send_message("Você já está verificado!", ephemeral=True)
        try:
            await interaction.user.add_roles(role, reason="Aceitou as regras")
        except discord.Forbidden:
            return await interaction.response.send_message("⚠️ Não tenho permissão pra dar o cargo. Avise um admin.",
                                                           ephemeral=True)
        await interaction.response.send_message(f"✅ Bem-vindo(a)! O servidor foi liberado pra você.", ephemeral=True)


# ================================================================== salas privadas
class Servidor(commands.Cog):
    sala = app_commands.Group(name="sala", description="Gerencie sua sala de voz privada", guild_only=True)

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_dynamic_items(VerifyButton)
        self.cleanup.start()

    async def cog_unload(self):
        self.cleanup.cancel()

    async def my_room(self, interaction: discord.Interaction) -> discord.VoiceChannel:
        row = await self.bot.db.fetchone("SELECT channel_id FROM private_rooms WHERE guild_id=? AND owner_id=?",
                                         (interaction.guild_id, interaction.user.id))
        channel = interaction.guild.get_channel(row["channel_id"]) if row else None
        if not channel:
            raise UserError("Você não tem sala privada aberta. Entre no canal **➕ Criar sala privada**.")
        return channel

    # ------------------------------------------------------------ criar / apagar
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState):
        if member.bot:
            return
        if after.channel and after.channel != before.channel and after.channel.name.startswith(CREATOR_PREFIX):
            await self.create_room(member, after.channel)
        if before.channel and before.channel != after.channel and not before.channel.members:
            await self.delete_if_room(before.channel)

    async def create_room(self, member: discord.Member, creator: discord.VoiceChannel):
        guild = member.guild
        existing = await self.bot.db.fetchone("SELECT channel_id FROM private_rooms WHERE guild_id=? AND owner_id=?",
                                              (guild.id, member.id))
        if existing and (room := guild.get_channel(existing["channel_id"])):
            try:
                return await member.move_to(room)
            except discord.HTTPException:
                return
        category = creator.category
        overwrites = dict(category.overwrites) if category else {}
        everyone = overwrites.get(guild.default_role, discord.PermissionOverwrite())
        everyone.update(connect=False)
        overwrites[guild.default_role] = everyone
        overwrites[member] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True, stream=True,
                                                         move_members=True, manage_channels=True)
        overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True,
                                                           move_members=True)
        try:
            room = await guild.create_voice_channel(f"🔒 {member.display_name}"[:100], category=category,
                                                    overwrites=overwrites, reason="Sala privada")
            await self.bot.db.execute("INSERT OR REPLACE INTO private_rooms (channel_id, guild_id, owner_id) "
                                      "VALUES (?,?,?)", (room.id, guild.id, member.id))
            await member.move_to(room)
            await room.send(f"🔒 {member.mention}, essa sala é sua! Só entra quem você chamar.\n"
                            f"• `/sala convidar @amigo` — libera alguém\n"
                            f"• `/sala abrir` / `/sala trancar` — libera ou fecha pra todo mundo\n"
                            f"• `/sala limite 5` — limite de pessoas\n"
                            f"A sala some sozinha quando ficar vazia.")
        except discord.HTTPException as e:
            log.warning("Falha ao criar sala privada: %s", e)

    async def delete_if_room(self, channel):
        row = await self.bot.db.fetchone("SELECT 1 FROM private_rooms WHERE channel_id=?", (channel.id,))
        if not row:
            return
        await self.bot.db.execute("DELETE FROM private_rooms WHERE channel_id=?", (channel.id,))
        try:
            await channel.delete(reason="Sala privada vazia")
        except discord.HTTPException:
            pass

    @tasks.loop(minutes=10)
    async def cleanup(self):
        """Apaga salas que ficaram vazias enquanto o bot estava desligado."""
        for row in await self.bot.db.fetchall("SELECT channel_id FROM private_rooms"):
            channel = self.bot.get_channel(row["channel_id"])
            if channel is None:
                await self.bot.db.execute("DELETE FROM private_rooms WHERE channel_id=?", (row["channel_id"],))
            elif not channel.members:
                await self.delete_if_room(channel)

    @cleanup.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------ /sala
    @sala.command(name="convidar", description="Libera alguém para entrar na sua sala")
    async def sala_convidar(self, interaction: discord.Interaction, membro: discord.Member):
        room = await self.my_room(interaction)
        await room.set_permissions(membro, view_channel=True, connect=True, speak=True, stream=True)
        await interaction.response.send_message(f"✅ {membro.mention} pode entrar em {room.mention}.")

    @sala.command(name="remover", description="Tira a permissão de alguém (e expulsa se estiver na sala)")
    async def sala_remover(self, interaction: discord.Interaction, membro: discord.Member):
        room = await self.my_room(interaction)
        if membro.id == interaction.user.id:
            raise UserError("Você não pode se remover da própria sala.")
        await room.set_permissions(membro, overwrite=None)
        if membro.voice and membro.voice.channel == room:
            await membro.move_to(None)
        await interaction.response.send_message(f"👋 {membro.display_name} não pode mais entrar.", ephemeral=True)

    @sala.command(name="abrir", description="Deixa qualquer membro verificado entrar")
    async def sala_abrir(self, interaction: discord.Interaction):
        room = await self.my_room(interaction)
        await room.set_permissions(interaction.guild.default_role, connect=None)
        await interaction.response.send_message("🔓 Sala aberta pra todos.", ephemeral=True)

    @sala.command(name="trancar", description="Volta a deixar só os convidados entrarem")
    async def sala_trancar(self, interaction: discord.Interaction):
        room = await self.my_room(interaction)
        await room.set_permissions(interaction.guild.default_role, connect=False)
        await interaction.response.send_message("🔒 Sala trancada.", ephemeral=True)

    @sala.command(name="limite", description="Limite de pessoas na sala (0 = sem limite)")
    async def sala_limite(self, interaction: discord.Interaction, pessoas: app_commands.Range[int, 0, 99]):
        room = await self.my_room(interaction)
        await room.edit(user_limit=pessoas)
        await interaction.response.send_message(f"👥 Limite: {pessoas or 'sem limite'}.", ephemeral=True)

    @sala.command(name="nome", description="Muda o nome da sua sala")
    async def sala_nome(self, interaction: discord.Interaction, nome: app_commands.Range[str, 1, 90]):
        room = await self.my_room(interaction)
        await room.edit(name=f"🔒 {nome}")
        await interaction.response.send_message("✏️ Nome alterado.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Servidor(bot))
