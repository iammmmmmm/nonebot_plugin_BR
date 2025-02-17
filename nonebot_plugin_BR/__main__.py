from pathlib import Path
from typing import TYPE_CHECKING, cast

from nonebot import on_command
from nonebot.adapters import Event, Message
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot_plugin_session import EventSession, SessionIdType
from nonebot_plugin_uninfo import Session, UniSession
from nonebot_plugin_waiter import prompt

from .config import config
from .game import Game, LocalData
from .model import GameData, StateDecide
from .robot import ai_action
from .utils import Format
from .weapon import Weapon

if TYPE_CHECKING:
    pass

game_players = cast("list[PlayerSession]", [])

br_help = on_command(
    "br help",
    aliases={"BR HELP", "Br Help", "br帮助"},
    priority=2,
    block=True,
)


@br_help.handle()
async def _(matcher: Matcher):
    await matcher.finish(
        """游戏指令
			- br开始/br加入/br准备 —— 开始游戏
			- br继续 ——继续未结束的游戏（如果有）
			- br设置血量 —— 设置血量
			- 开枪 —— 开枪(开始游戏后,第一次“开枪”决定先手而不是开枪)
			- 使用道具 xxx —— 使用道具
			- 结束游戏 —— 结束游戏
			- br人机对战 —— 开始人机对战""",  # noqa: RUF001
    )


br_start = on_command(
    "br开始",
    aliases={"br加入", "br进入", "br准备", "br继续"},
    priority=2,
    block=True,
)


@br_start.handle()
async def _(
    ev: Event,
    matcher: Matcher,
    session: EventSession,
    session_id: Session = UniSession(),
    # args: Message = CommandArg(),
):
    # 判断是否有在玩的游戏
    session_uid = session.get_id(SessionIdType.GROUP)
    player_id = ev.get_user_id()

    data_path = Path(config.br_path) / "player" / f"{session_uid}.json"

    if data_path.is_file():
        # 检查玩家数量
        game_data = await LocalData.read_data(session_uid)
        if game_data["player_id2"]:
            # 当前会话满人
            if player_id in [game_data["player_id"], game_data["player_id2"]]:
                await matcher.send("检测到在进行的游戏,游戏继续!")
                game_state = await Game.state(game_data, session_uid)
                await matcher.send(game_state["msg"])
                if game_data["round_self"] and player_id == game_data["player_id"]:
                    game_players.append(
                        cast(
                            "PlayerSession",
                            {
                                "player_id": player_id,
                                "player_name": session_id.user.nick
                                or session_id.user.name,
                                "session_uid": session_uid,
                            },
                        ),
                    )
                    await matcher.finish(
                        f"现在是{game_data['player_name']}的回合\n请行动"
                    )
                if (
                    not game_data["round_self"] and player_id == game_data["player_id"]
                ) and game_data["is_robot_game"]:
                    await matcher.send("现在是Gemini AI的回合")
                    game_data = await LocalData.read_data(
                        session.get_id(SessionIdType.GROUP)
                    )
                    await ai_do(
                        game_data, game_state, matcher, session_uid, session, -1
                    )
                    game_players.append(
                        cast(
                            "PlayerSession",
                            {
                                "player_id": player_id,
                                "player_name": session_id.user.nick
                                or session_id.user.name,
                                "session_uid": session_uid,
                            },
                        ),
                    )
                    return
                game_players.append(
                    cast(
                        "PlayerSession",
                        {
                            "player_id": player_id,
                            "player_name": session_id.user.nick or session_id.user.name,
                            "session_uid": session_uid,
                        },
                    ),
                )
            else:
                await matcher.finish("本群游戏玩家已满了呢.")
        else:
            if player_id != game_data["player_id"]:
                # 只有一个人
                await matcher.send(
                    f"""玩家 {session_id.user.nick or session_id.user.name} 加入游戏,游戏开始.
第一枪前发送“br设置血量”可修改双方的血量
请先手发送“开枪”来执行游戏操作""",
                )
                game_data["player_id2"] = player_id
                game_data["player_name2"] = (
                    session_id.user.nick or session_id.user.name or ""
                )
                await LocalData.save_data(session_uid, game_data)
                game_players.append(
                    cast(
                        "PlayerSession",
                        {
                            "player_id": player_id,
                            "player_name": session_id.user.nick or session_id.user.name,
                            "session_uid": session_uid,
                        },
                    ),
                )
            else:
                await matcher.send(
                    f"""玩家 {session_id.user.nick or session_id.user.name}已经加入游戏,请勿重复加入.""",
                )

    else:
        # 创建新的游戏
        (Path(config.br_path) / "player").mkdir(parents=True, exist_ok=True)
        game_data = await LocalData.new_data(
            player_id,
            session_id,
            False,  # noqa: FBT003
        )
        await LocalData.save_data(session_uid, game_data)
        await matcher.send(
            f"玩家 {session_id.user.name} 发起了恶魔轮盘游戏!\n请等待另外一个用户加入游戏",
        )
        game_players.append(
            cast(
                "PlayerSession",
                {
                    "player_id": player_id,
                    "player_name": session_id.user.nick or session_id.user.name,
                    "session_uid": session_uid,
                },
            ),
        )
    game_data = cast("GameData", game_data)


async def game_rule(event: Event, session: EventSession):  # noqa: RUF029
    logger.debug(game_players)

    for one in game_players:
        if (
            event.get_user_id() == one["player_id"]
            and session.get_id(SessionIdType.GROUP) == one["session_uid"]
        ):
            return True
    return False


game_shut = on_command("开枪", rule=game_rule)


@game_shut.handle()
async def _(
    event: Event,
    matcher: Matcher,
    session: EventSession,
    args: Message = CommandArg(),
):
    logger.info("[br]正在执行开枪指令")
    player_id = event.get_user_id()
    session_uid = session.get_id(SessionIdType.GROUP)
    game_data = await LocalData.read_data(session_uid)

    if not game_data["player_id2"]:
        await matcher.finish("你还没有对手呢,快艾特你的好朋友发送“br加入”进入游戏吧")

    # 首次攻击判定
    if not game_data["is_start"]:
        logger.info("[br]开始游戏,先手为player1")
        game_data, _, new_weapon1, new_weapon2 = await Weapon.new_item(game_data)

        out_msg = f"""
道具新增:
{game_data["player_name"]}: {await Format.creat_item(new_weapon1)}
{game_data["player_name2"]}: {await Format.creat_item(new_weapon2)}
"""
        if player_id == game_data["player_id2"]:
            out_msg += f"\n{game_data['player_name2']}发动偷袭,开始游戏"
        else:
            out_msg += f"{game_data['player_name']}发动偷袭,开始游戏"
        if player_id == game_data["player_id2"]:
            game_data["player_id"], game_data["player_id2"] = (
                game_data["player_id2"],
                game_data["player_id"],
            )
            game_data["player_name"], game_data["player_name2"] = (
                game_data["player_name2"],
                game_data["player_name"],
            )

        game_data["is_start"] = True
        state_data = await Game.state(
            game_data,
            session_uid,
        )  # 获取状态信息,返回一个字典
        out_msg += "\n"
        out_msg += state_data["msg"]  # 从字典中提取 "msg" 键对应的值,它是一个字符串
        await matcher.finish(out_msg)

    # 判断是否是自己回合
    # logger.debug(game_data["round_self"])
    # logger.info(player_id == game_data["player_id2"])
    if game_data["round_self"] and player_id == game_data["player_id2"]:
        await matcher.finish(f"现在是{game_data['player_name']}的回合\n请等待对手行动")
    if not game_data["round_self"] and player_id == game_data["player_id"]:
        await matcher.finish(f"现在是{game_data['player_name2']}的回合\n请等待对手行动")
    if args.extract_plain_text() not in ["1", "2"]:
        resp = await prompt("请输入攻击目标,1为对方,2为自己", timeout=120)

        if resp is None:
            await matcher.send("等待超时")
            return
        if resp.extract_plain_text() not in ["1", "2"]:
            await matcher.send("无效输入")
            return
        obj = resp.extract_plain_text()
    else:
        obj = args.extract_plain_text()
    obj = obj.strip()
    logger.info(f"[br]正在执行开枪指令,对象为:{obj}")

    # 判断枪有没有子弹
    if_reload, out_msg = await Game.check_weapon(game_data, session_uid)
    if if_reload:
        await matcher.send(out_msg)
    if obj == "2":
        game_data, out_msg = await Game.start(game_data, True)  # noqa: FBT003
    else:
        game_data, out_msg = await Game.start(game_data, False)  # noqa: FBT003
    await matcher.send(out_msg)
    await LocalData.save_data(session_uid, game_data)

    # 状态判定
    state_data = await Game.state(game_data, session_uid)
    out_msg = state_data["msg"]

    if state_data["is_finish"]:
        # 游戏结束
        await LocalData.delete_data(session_uid)
        await matcher.finish(out_msg)

    await LocalData.save_data(session_uid, game_data)
    await matcher.send(out_msg)
    if game_data["is_robot_game"] and "实弹" in out_msg:
        logger.info("轮到ai操作")
        await ai_do(game_data, state_data, matcher, session_uid, session, -1)


async def ai_do(
    game_data: GameData,
    state_data: StateDecide,
    matcher: Matcher,
    session_uid: str,
    session: EventSession,
    additional_information: int,
):
    """
    additional_information: int 0空包弹，1实弹，-1表示没有使用放大镜,2表示使用了手铐
    """
    if additional_information is None:
        additional_information = -1
    game_sate = await Game.state(game_data, session_uid)
    logger.debug(f"284 ai_action(game_data,game_state{additional_information})")
    action = await ai_action(game_data, game_sate, additional_information)
    if action:
        if action.action_type == "开枪":
            target = int(action.argument)
            # 执行开枪逻辑
            logger.info(f"AI 开枪,目标：{target}")  # noqa: RUF001
            # 判断枪有没有子弹
            if_reload, out_msg = await Game.check_weapon(game_data, session_uid)
            if if_reload:
                await matcher.send(out_msg)
            if target == "2":
                game_data, out_msg = await Game.start(game_data, True)  # noqa: FBT003
            else:
                game_data, out_msg = await Game.start(game_data, False)  # noqa: FBT003
            await matcher.send(out_msg)
            game_state = await Game.state(game_data, session_uid)
            await matcher.send(game_state["msg"])
            await LocalData.save_data(session_uid, game_data)
            # 判断下一步是谁操作
            if game_data["round_self"]:
                # 轮到玩家操作
                return
            # 轮到ai操作
            await ai_do(game_data, state_data, matcher, session_uid, session, -1)
        elif action.action_type == "使用":
            item = action.argument
            # 执行使用道具逻辑
            logger.info(f"AI 使用道具:{item}")
            t_items = None
            t_items = "items" if game_data["round_self"] else "eneny_items"
            txt = item
            await matcher.send("现在是Gemini AI的回合")
            if "knife" in txt:
                game_data = await Weapon.use_knife(game_data)
                game_data[t_items]["knife"] -= 1
                await LocalData.save_data(
                    session.get_id(SessionIdType.GROUP),
                    game_data,
                )
                await matcher.send("刀已使用,你下一次攻击伤害为2(无论是否有子弹)")
            if "handcuffs" in txt:
                game_data = await Weapon.use_handcuffs(game_data)
                game_data[t_items]["handcuffs"] -= 1
                await LocalData.save_data(
                    session.get_id(SessionIdType.GROUP),
                    game_data,
                )
                await matcher.send("手铐已使用, 跳过对方一回合")
                if not state_data["is_finish"]:
                    await ai_do(game_data, state_data, matcher, session_uid, session, 2)
                else:
                    return
            elif "cigarettes" in txt:
                game_data = await Weapon.use_cigarettes(game_data)
                game_data[t_items]["cigarettes"] -= 1
                await LocalData.save_data(
                    session.get_id(SessionIdType.GROUP),
                    game_data,
                )
                await matcher.send("香烟已使用, 血量加1")
            elif "glass" in txt:
                game_data, msg = await Weapon.use_glass(game_data)
                game_data[t_items]["glass"] -= 1
                await LocalData.save_data(
                    session.get_id(SessionIdType.GROUP),
                    game_data,
                )
                is_live_ammunition_temp = -1
                if msg:
                    await matcher.send("放大镜已使用,是实弹")
                    is_live_ammunition_temp = 1
                if not msg:
                    await matcher.send("放大镜已使用,是空弹")
                    is_live_ammunition_temp = 0
                await ai_do(
                    game_data,
                    state_data,
                    matcher,
                    session_uid,
                    session,
                    is_live_ammunition_temp,
                )
            elif "drink" in txt:
                game_data = await Weapon.use_drink(game_data)
                game_data[t_items]["drink"] -= 1
                await LocalData.save_data(
                    session.get_id(SessionIdType.GROUP),
                    game_data,
                )
                game_state = await Game.state(game_data, session_uid)

                await matcher.send("饮料已使用,退弹一发\n" + game_state["msg"])

                await ai_do(game_data, state_data, matcher, session_uid, session, -1)
    else:
        logger.error("无法解析 AI 操作")
        logger.error(action)


swich_life = on_command("br设置血量", rule=game_rule)


@swich_life.handle()
async def _(
    ev: Event,
    matcher: Matcher,
    session: EventSession,
    args: Message = CommandArg(),
):
    logger.info("[br]正在设置血量指令")
    player_id = ev.get_user_id()
    session_uid = session.get_id(SessionIdType.GROUP)
    game_data = await LocalData.read_data(session_uid)
    if player_id != game_data["player_id"] and player_id != game_data["player_id2"]:
        await matcher.finish("你不是游戏中的玩家")
    if game_data["is_start"]:
        await matcher.finish("游戏已开始,请勿修改血量")
    lives = args.extract_plain_text()
    if not lives.isdigit():
        await matcher.finish("血量必须为数字")
    lives = int(lives)
    if lives < 0 or lives > 8:
        await matcher.finish("血量范围为1-8")
    await LocalData.switch_life(game_data, session_uid, lives)
    logger.info(f"[br]血量已设置为{lives}")
    await matcher.finish(f"血量已设置为{lives}")


use_itme = on_command("使用", rule=game_rule)


@use_itme.handle()
async def _(
    event: Event,
    matcher: Matcher,
    session: EventSession,
    args: Message = CommandArg(),
):
    logger.info("[br]正在使用道具指令")
    player_id = event.get_user_id()
    txt = args.extract_plain_text().strip()
    game_data = await LocalData.read_data(session.get_id(SessionIdType.GROUP))
    session_uid = session.get_id(SessionIdType.GROUP)
    # # 判断是否是自己回合
    if game_data["round_self"] and player_id == game_data["player_id2"]:
        await matcher.finish(f"现在是{game_data['player_name']}的回合\n请等待对手行动")
    if not game_data["round_self"] and player_id == game_data["player_id"]:
        await matcher.finish(f"现在是{game_data['player_name2']}的回合\n请等待对手行动")
    t_items = None
    t_items = "items" if game_data["round_self"] else "eneny_items"
    if "刀" in txt:
        if game_data[t_items]["knife"] <= 0:
            await matcher.finish("你没有刀")
        game_data = await Weapon.use_knife(game_data)
        game_data[t_items]["knife"] -= 1
        await LocalData.save_data(session.get_id(SessionIdType.GROUP), game_data)
        await matcher.finish("刀已使用,你下一次攻击伤害为2(无论是否有子弹)")
    if "手铐" in txt:
        if game_data[t_items]["handcuffs"] <= 0:
            await matcher.finish("你没有手铐")
        game_data = await Weapon.use_handcuffs(game_data)
        game_data[t_items]["handcuffs"] -= 1
        await LocalData.save_data(session.get_id(SessionIdType.GROUP), game_data)
        await matcher.finish("手铐已使用, 跳过对方一回合")
    if "香烟" in txt:
        if game_data[t_items]["cigarettes"] <= 0:
            await matcher.finish("你没有香烟")
        game_data = await Weapon.use_cigarettes(game_data)
        game_data[t_items]["cigarettes"] -= 1
        await LocalData.save_data(session.get_id(SessionIdType.GROUP), game_data)
        await matcher.finish("香烟已使用, 血量加1")
    if "放大镜" in txt:
        if game_data[t_items]["glass"] <= 0:
            await matcher.finish("你没有放大镜")
        game_data, msg = await Weapon.use_glass(game_data)
        game_data[t_items]["glass"] -= 1
        await LocalData.save_data(session.get_id(SessionIdType.GROUP), game_data)
        if msg:
            await matcher.finish("放大镜已使用,是实弹")
        if not msg:
            await matcher.finish("放大镜已使用,是空弹")
    if "饮料" in txt:
        if game_data[t_items]["drink"] <= 0:
            await matcher.finish("你没有饮料")
        game_data = await Weapon.use_drink(game_data)
        game_data[t_items]["drink"] -= 1
        await LocalData.save_data(session.get_id(SessionIdType.GROUP), game_data)
        game_state = await Game.state(game_data, session_uid)
        await matcher.finish("饮料已使用,退弹一发\n" + game_state["msg"])
    await matcher.finish("无效道具")


search_game = on_command("br当前状态", rule=game_rule)


@search_game.handle()
async def _(
    ev: Event,
    matcher: Matcher,
    session: EventSession,
):
    logger.info("[br]正在查询游戏状态指令")
    player_id = ev.get_user_id()
    session_uid = session.get_id(SessionIdType.GROUP)
    game_data = await LocalData.read_data(session_uid)
    if player_id != game_data["player_id"] and player_id != game_data["player_id2"]:
        await matcher.finish("你不是游戏中的玩家")
    out_msg = await Game.state(game_data, session_uid)
    await matcher.finish(out_msg["msg"])


game_end = on_command("结束游戏")


@game_end.handle()
async def _(
    ev: Event,
    matcher: Matcher,
    session: EventSession,
):
    logger.info("[br]正在结束游戏指令")
    player_id = ev.get_user_id()
    session_uid = session.get_id(SessionIdType.GROUP)
    game_data = await LocalData.read_data(session_uid)
    if player_id != game_data["player_id"] and player_id != game_data["player_id2"]:
        await matcher.finish("您不不是游戏玩家或无权限结束游戏")
    # 结束游戏并清理玩家
    game_players[:] = [one for one in game_players if one["session_uid"] != session_uid]
    await LocalData.delete_data(session_uid)
    await matcher.finish("恶魔轮盘已游戏结束")


game_end_super = on_command("结束游戏", permission=SUPERUSER)


@game_end_super.handle()
async def _(
    matcher: Matcher,
    session: EventSession,
):
    logger.info("[br]正在结束游戏指令")
    # player_id = ev.get_user_id()
    session_uid = session.get_id(SessionIdType.GROUP)
    # game_data = await LocalData.read_data(session_uid)
    # 结束游戏并清理玩家
    game_players[:] = [one for one in game_players if one["session_uid"] != session_uid]
    await LocalData.delete_data(session_uid)
    await matcher.finish("恶魔轮盘已游戏结束")


robot_game = on_command(
    "br人机对战",
    aliases={"br人机", "brai"},
    priority=2,
    block=True,
)


@robot_game.handle()
async def _(
    ev: Event,
    matcher: Matcher,
    session: EventSession,
    session_id: Session = UniSession(),
):
    session_uid = session.get_id(SessionIdType.GROUP)
    player_id = ev.get_user_id()

    # 创建新的游戏数据
    (Path(config.br_path) / "player").mkdir(parents=True, exist_ok=True)
    game_data = await LocalData.new_data(player_id, session_id, True)  # noqa: FBT003

    # 设置 AI 玩家信息
    game_data["player_id2"] = "gemini_ai"  # 使用特殊 ID 标识 AI 玩家
    game_data["player_name2"] = "Gemini AI"

    await LocalData.save_data(session_uid, game_data)
    game_players.append(
        cast(
            "PlayerSession",
            {
                "player_id": player_id,
                "player_name": session_id.user.nick or session_id.user.name,
                "session_uid": session_uid,
            },
        ),
    )
    game_players.append(
        cast(
            "PlayerSession",
            {
                "player_id": game_data["player_id2"],
                "player_name": game_data["player_name2"],
                "session_uid": session_uid,
            },
        ),
    )
    await matcher.send(
        f"玩家 {session_id.user.name} 发起了与 Gemini AI 的恶魔轮盘游戏!\n你作为先手开始游戏。",
    )

    # 触发第一回合开始
    game_data["is_start"] = True
    game_data, _, new_weapon1, new_weapon2 = await Weapon.new_item(game_data)

    out_msg = f"""
道具新增:
{game_data["player_name"]}: {await Format.creat_item(new_weapon1)}
{game_data["player_name2"]}: {await Format.creat_item(new_weapon2)}
"""
    state_data = await Game.state(game_data, session_uid)  # 获取状态信息,返回一个字典
    out_msg += state_data["msg"]  # 从字典中提取 "msg" 键对应的值,它是一个字符串
    await matcher.send(out_msg)
    await LocalData.save_data(session_uid, game_data)

    await matcher.finish()
