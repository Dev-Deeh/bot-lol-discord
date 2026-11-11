"""Recursos de servidor: botão de verificação (aceitar regras) e salas de voz privadas.

- Verificação: o botão guarda no próprio ID qual cargo deve dar ("verify:<id do cargo>"),
  então funciona em qualquer servidor e continua funcionando depois que o bot reinicia.
- Salas privadas: qualquer canal de voz cujo nome começa com "➕" vira um "criador".
  Quem entra nele ganha uma sala trancada só sua; o dono convida amigos com /sala.
  A sala é apagada quando fica vazia.
"""
import asyncio
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


def owner_overwrite() -> discord.PermissionOverwrite:
    """Dono da sala privada: entra, fala, transmite e controla quem está lá (arrastar, desconectar, mutar)."""
    return discord.PermissionOverwrite(view_channel=True, connect=True, speak=True, stream=True,
                                       use_voice_activation=True, move_members=True, mute_members=True,
                                       deafen_members=True, manage_channels=True)


# ================================================================== salas privadas
class Servidor(commands.Cog):
    sala = app_commands.Group(name="sala", description="Gerencie sua sala de voz privada", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.locks: dict[int, asyncio.Lock] = {}

    async def cog_load(self):
        self.bot.add_dynamic_items(VerifyButton)
        self.cleanup.start()
        self.personal_sync.start()

    async def cog_unload(self):
        self.cleanup.cancel()
        self.personal_sync.cancel()

    async def my_room(self, interaction: discord.Interaction) -> discord.VoiceChannel:
        for table in ("personal_rooms", "private_rooms"):
            row = await self.bot.db.fetchone(f"SELECT channel_id FROM {table} WHERE guild_id=? AND owner_id=?",
                                             (interaction.guild_id, interaction.user.id))
            channel = interaction.guild.get_channel(row["channel_id"]) if row else None
            if channel:
                return channel
        raise UserError("Você não tem sala privada. Ela é criada quando você recebe um cargo do time.")

    # ------------------------------------------------------------ privado fixo de cada jogador
    # Config do servidor: "privados:cat" = ID da categoria; "privados:roles" = IDs dos cargos do time (vírgula).
    # Quem tem um cargo do time ganha uma sala "🔒 Nome" só sua; quem perde o cargo perde a sala.
    # Vários times: config "times" = "cargo:categoria_privados:categoria_tierlist" separados por ";".
    async def teams(self, guild: discord.Guild) -> list[tuple]:
        raw = await self.bot.db.get_config(guild.id, "times")
        out = []
        if raw:
            for part in str(raw).split(";"):
                bits = part.split(":")
                if len(bits) == 3 and all(bits):
                    out.append((int(bits[0]), guild.get_channel(int(bits[1])), guild.get_channel(int(bits[2]))))
            return [t for t in out if t[1] is not None]
        cat_id = await self.bot.db.get_config(guild.id, "privados:cat")
        roles = await self.bot.db.get_config(guild.id, "privados:roles")
        category = guild.get_channel(int(cat_id)) if cat_id else None
        if category is None or not roles:
            return []
        tcat = await self.tier_category(guild)
        return [(int(r), category, tcat) for r in str(roles).split(",") if r]

    @staticmethod
    def team_of(member: discord.Member, teams):
        ids = {r.id for r in member.roles}
        return next((t for t in teams if t[0] in ids), None)

    def guild_lock(self, guild_id: int) -> asyncio.Lock:
        # uma sincronização por vez em cada servidor (evita criar a mesma sala duas vezes)
        if guild_id not in self.locks:
            self.locks[guild_id] = asyncio.Lock()
        return self.locks[guild_id]

    async def sync_member(self, member: discord.Member, teams):
        async with self.guild_lock(member.guild.id):
            await self._sync_member(member, teams)

    async def _sync_member(self, member: discord.Member, teams):
        if member.bot or not teams:
            return
        team = self.team_of(member, teams)
        is_team = team is not None
        category = team[1] if team else None
        await self._sync_tier(member, team[2] if team else None)
        row = await self.bot.db.fetchone("SELECT channel_id FROM personal_rooms WHERE guild_id=? AND owner_id=?",
                                         (member.guild.id, member.id))
        room = member.guild.get_channel(row["channel_id"]) if row else None
        if is_team and room is not None and room.category_id != category.id:  # trocou de time: sala nova no time novo
            try:
                await room.delete(reason="Trocou de time")
            except discord.HTTPException:
                pass
            await self.bot.db.execute("DELETE FROM personal_rooms WHERE channel_id=?", (row["channel_id"],))
            room, row = None, None
        if is_team and room is None:
            overwrites = {}
            for target, ow in category.overwrites.items():
                ow = discord.PermissionOverwrite(**dict(ow))
                if ow.connect:  # o time vê a sala, mas só entra quem o dono chamar
                    ow.update(connect=False)
                overwrites[target] = ow
            everyone = overwrites.get(member.guild.default_role, discord.PermissionOverwrite())
            everyone.update(connect=False)
            overwrites[member.guild.default_role] = everyone
            overwrites[member] = owner_overwrite()
            overwrites[member.guild.me] = discord.PermissionOverwrite(view_channel=True, connect=True,
                                                                      manage_channels=True, move_members=True)
            try:
                room = await member.guild.create_voice_channel(f"🔒 {member.display_name}"[:100], category=category,
                                                               overwrites=overwrites, reason="Privado do jogador")
                await self.bot.db.execute("INSERT OR REPLACE INTO personal_rooms (channel_id, guild_id, owner_id) "
                                          "VALUES (?,?,?)", (room.id, member.guild.id, member.id))
                log.info("Privado criado para %s", member)
            except discord.HTTPException as e:
                log.warning("Falha ao criar privado de %s: %s", member, e)
        elif is_team and room is not None:
            if room.overwrites_for(member) != owner_overwrite():
                try:
                    await room.set_permissions(member, overwrite=owner_overwrite(), reason="Permissões do dono")
                except discord.HTTPException:
                    pass
        elif not is_team and row:
            await self.bot.db.execute("DELETE FROM personal_rooms WHERE channel_id=?", (row["channel_id"],))
            if room:
                try:
                    await room.delete(reason="Saiu do time")
                except discord.HTTPException:
                    pass

    # ------------------------------------------------------------ canal de tier list de cada jogador
    # Config "tierlist:cat" = ID da categoria. Mesmos cargos dos privados. Só o dono posta; o time lê e reage.
    async def tier_category(self, guild: discord.Guild):
        cat_id = await self.bot.db.get_config(guild.id, "tierlist:cat")
        return guild.get_channel(int(cat_id)) if cat_id else None

    @staticmethod
    def tier_overwrites(member: discord.Member, tcat):
        overwrites = {}
        for target, ow in tcat.overwrites.items():
            ow = discord.PermissionOverwrite(**dict(ow))
            if isinstance(target, discord.Role):  # o time lê e reage, mas não escreve no canal dos outros
                ow.update(send_messages=False, create_public_threads=False, send_messages_in_threads=False)
            overwrites[target] = ow
        overwrites[member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True,
                                                         embed_links=True, manage_messages=True,
                                                         read_message_history=True)
        overwrites[member.guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                                  manage_channels=True)
        return overwrites

    async def _sync_tier(self, member: discord.Member, tcat):
        """tcat = categoria de tier list do time do jogador (None = não é de nenhum time)."""
        is_team = tcat is not None
        row = await self.bot.db.fetchone("SELECT channel_id FROM tier_channels WHERE guild_id=? AND owner_id=?",
                                         (member.guild.id, member.id))
        channel = member.guild.get_channel(row["channel_id"]) if row else None
        if is_team and channel is not None and channel.category_id != tcat.id:  # trocou de time: leva a tier list
            try:
                await channel.edit(category=tcat, overwrites=self.tier_overwrites(member, tcat),
                                   reason="Trocou de time")
            except discord.HTTPException as e:
                log.warning("Falha ao mover tier list de %s: %s", member, e)
        elif is_team and channel is None:
            overwrites = self.tier_overwrites(member, tcat)
            try:
                channel = await member.guild.create_text_channel(
                    f"📝・{member.display_name}"[:100], category=tcat, overwrites=overwrites,
                    topic=f"Tier list de {member.display_name}. Só {member.display_name} posta aqui; o time comenta "
                          f"com reações.", reason="Tier list do jogador")
                await self.bot.db.execute("INSERT OR REPLACE INTO tier_channels (channel_id, guild_id, owner_id) "
                                          "VALUES (?,?,?)", (channel.id, member.guild.id, member.id))
                log.info("Canal de tier list criado para %s", member)
            except discord.HTTPException as e:
                log.warning("Falha ao criar tier list de %s: %s", member, e)
        elif not is_team and row:
            await self.bot.db.execute("DELETE FROM tier_channels WHERE channel_id=?", (row["channel_id"],))
            if channel:
                try:
                    await channel.delete(reason="Saiu do time")
                except discord.HTTPException:
                    pass

    async def sync_guild(self, guild: discord.Guild):
        teams = await self.teams(guild)
        if not teams:
            return
        async with self.guild_lock(guild.id):
            for member in guild.members:
                await self._sync_member(member, teams)
            # faxina da tier list: canais que não são de alguém do time
            for tcat in {t[2].id: t[2] for t in teams if t[2]}.values():
                rows = await self.bot.db.fetchall("SELECT channel_id FROM tier_channels WHERE guild_id=?", (guild.id,))
                tracked = {r["channel_id"] for r in rows}
                for channel in tcat.text_channels:
                    if channel.id not in tracked:
                        try:
                            await channel.delete(reason="Tier list sem dono do time")
                        except discord.HTTPException:
                            pass
            # faxina: qualquer sala na categoria que não seja o privado registrado de alguém do time é apagada
            rows = await self.bot.db.fetchall("SELECT channel_id FROM personal_rooms WHERE guild_id=?", (guild.id,))
            tracked = {r["channel_id"] for r in rows}
            for channel in [c for cat in {t[1].id: t[1] for t in teams}.values() for c in cat.voice_channels]:
                if channel.id not in tracked:
                    try:
                        await channel.delete(reason="Privado sem dono do time")
                        log.info("Privado órfão apagado: %s", channel.name)
                    except discord.HTTPException:
                        pass

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles != after.roles:
            await self.sync_member(after, await self.teams(after.guild))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Cargo automático pra quem entra (config "autorole")."""
        if member.bot:
            return
        role_id = await self.bot.db.get_config(member.guild.id, "autorole")
        role = member.guild.get_role(int(role_id)) if role_id else None
        if role:
            try:
                await member.add_roles(role, reason="Cargo automático de entrada")
            except discord.HTTPException as e:
                log.warning("Não consegui dar o cargo automático: %s", e)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        row = await self.bot.db.fetchone("SELECT channel_id FROM personal_rooms WHERE guild_id=? AND owner_id=?",
                                         (member.guild.id, member.id))
        if row:
            await self.bot.db.execute("DELETE FROM personal_rooms WHERE channel_id=?", (row["channel_id"],))
            room = member.guild.get_channel(row["channel_id"])
            if room:
                try:
                    await room.delete(reason="Saiu do servidor")
                except discord.HTTPException:
                    pass

    @tasks.loop(minutes=10)
    async def personal_sync(self):
        for guild in self.bot.guilds:
            try:
                await self.sync_guild(guild)
            except Exception:
                log.exception("Falha ao sincronizar privados de %s", guild)

    @personal_sync.before_loop
    async def before_personal_sync(self):
        await self.bot.wait_until_ready()

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
        overwrites = dict(room.overwrites)
        for target, ow in overwrites.items():
            if isinstance(target, discord.Role):
                ow.update(connect=None)
        await room.edit(overwrites=overwrites)
        await interaction.response.send_message("🔓 Sala aberta pra todos.", ephemeral=True)

    @sala.command(name="trancar", description="Volta a deixar só os convidados entrarem")
    async def sala_trancar(self, interaction: discord.Interaction):
        room = await self.my_room(interaction)
        overwrites = dict(room.overwrites)
        for target, ow in overwrites.items():
            if isinstance(target, discord.Role) and target != interaction.guild.me.top_role:
                ow.update(connect=False)
        overwrites.setdefault(interaction.guild.default_role, discord.PermissionOverwrite(connect=False))
        await room.edit(overwrites=overwrites)
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
