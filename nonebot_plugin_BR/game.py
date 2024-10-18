import json
import random
from pathlib import Path
from typing import Dict, cast

from loguru import logger
from nonebot_plugin_uninfo import Session

from .config import config
from .model import GameData, StateDecide
from .utils import Format


class Game:

    @classmethod
    async def start(cls, game_data: GameData, shut_self: bool):
        """开枪判定"""
        reround = False
        if game_data["round_self"]:
            msg = f"{game_data['player_name']}开枪了!"
        else:
            msg = f"{game_data['player_name2']}开枪了!"
        damage = game_data["one_choice"]["damage"] if game_data["weapon_if"][0] else 0
        if shut_self:
            msg += "目标是自己。"
            if damage == 0:
                msg += "\n是空弹,你获得额外一回合行动"
                reround = True
            else:
                msg += f"造成{damage}点伤害"

        else:
            msg += "目标是对方。"
            if damage == 0:
                msg += "\n是空弹。"
            else:

                msg += f"造成{damage}点伤害"

        # 伤害计算
        if (game_data["round_self"] and shut_self) or (
            not game_data["round_self"] and not shut_self
        ):
            game_data["lives"] -= damage
        else:
            game_data["enemy_lives"] -= damage

        # 删除开枪的子弹
        game_data["weapon_if"].pop(0)
        game_data["weapon_all"] -= 1

        # 是否重复回合
        if not reround:
            game_data["round_self"] = not game_data["round_self"]

        return game_data, msg

    @classmethod
    async def state(cls, game_data: GameData):
        """当前状态结算"""
        out_data = cast(StateDecide, {})
        out_data: StateDecide = {
            "is_finish": False,
            "msg": "⭐状态结算⭐",
            "bullet": False,
            "weapon": 0,
        }

        # 判断是否死亡
        if game_data["lives"] <= 0:
            out_data["msg"] += f"\n{game_data['player_name']}血量为0,游戏结束"
            out_data["is_finish"] = True
            return out_data
        if game_data["enemy_lives"] <= 0:
            out_data["is_finish"] = True
            out_data["msg"] += f"\n{game_data['player_name']}你过关,"
            return out_data
        out_data[
            "msg"
        ] += f"""
🩸当前血量: 
{game_data["player_name"]}: {game_data["lives"]}
{game_data["player_name2"]}: {game_data["enemy_lives"]}
"""
        # 判断当前枪支子弹
        if game_data["weapon_all"] <= 0:
            new_nub = random.randint(2, 8)
            game_data["weapon_all"] = new_nub

            game_data["weapon_if"] = [True, False]
            if new_nub > 2:
                game_data["weapon_if"] += random.choices([True, False], k=new_nub - 2)
            random.shuffle(game_data["weapon_if"])
            out_data[
                "msg"
            ] += f"""
🔫子弹打完,已重置子弹
当前子弹数: {new_nub}
实弹数: {sum(game_data['weapon_if'])}
"""
            out_data["bullet"] = True
        else:
            out_data[
                "msg"
            ] += f"""
🔫当前子弹数: {game_data['weapon_all']}
实弹数: {sum(game_data['weapon_if'])}
"""
            out_data["bullet"] = False

        # 判断道具生成
        if random.random() < 0.3 and game_data["round_self"]:
            self_weapon = sum(
                int(value)
                for value in game_data["items"].values()
                if isinstance(value, (int, float))
            )
            enemy_weapon = sum(
                int(value)
                for value in game_data["eneny_items"].values()
                if isinstance(value, (int, float))
            )
            weapon_number_max = max(8 - self_weapon, 8 - enemy_weapon)
            swap_number = random.randint(1, max(4, weapon_number_max))

            out_data["weapon"] = swap_number

            # 剩余子弹
            out_data["msg"] += f"\n🔫剩余子弹: {game_data['weapon_all']}"

            # 生成新道具

            for _ in range(swap_number):
                # 随机生成道具索引并更新玩家道具
                await Format.generate_weapon(game_data["items"])
                await Format.generate_weapon(game_data["eneny_items"])

                # 更新输出信息
                out_data["msg"] += await Format.format_items_message(game_data)
                return out_data

            new_weapon1 = [random.randint(1, 5) for _ in range(swap_number)]
            for index in new_weapon1:
                weapon_key = f"weapon{index + 1}"
                # 检查并初始化道具数量
                if weapon_key not in game_data["items"]:
                    game_data["items"][weapon_key] = 0
                game_data["items"][weapon_key] += 1

            new_weapon2 = [random.randint(1, 5) for _ in range(swap_number)]
            for index in new_weapon2:
                weapon_key = f"weapon{index + 1}"
                # 检查并初始化敌方道具数量
                if weapon_key not in game_data["eneny_items"]:
                    game_data["eneny_items"][weapon_key] = 0
                game_data["eneny_items"][weapon_key] += 1
            logger.info(f"[br]道具生成,{new_weapon1}{new_weapon2}")

            async def creat_item(new_weapon: list[int]):  # noqa: RUF029
                # 道具生成输出
                item_names: Dict[int, str] = {
                    1: "刀",
                    2: "手铐",
                    3: "香烟",
                    4: "放大镜",
                    5: "饮料",
                }

                # 生成描述
                descriptions = []
                for index in new_weapon:
                    if index in item_names:
                        descriptions.append(f"{item_names[index]}1")  # 假设数量为 1

                return ",".join(descriptions)

            out_data[
                "msg"
            ] += f"""
道具新增:
{game_data["player_name"]}: {await creat_item(new_weapon1)}
{game_data["player_name2"]}: {await creat_item(new_weapon2)}
"""
        out_data[
            "msg"
        ] += f"""
当前道具
{game_data["player_name"]}:刀{game_data["items"]["knife"]}, 手铐{game_data["items"]["handcuffs"]}, 香烟{game_data["items"]["cigarettes"]}, 放大镜{game_data["items"]["glass"]}, 饮料{game_data["items"]["drink"]}
{game_data["player_name2"]}:刀{game_data["eneny_items"]["knife"]}, 手铐{game_data["eneny_items"]["handcuffs"]}, 香烟{game_data["eneny_items"]["cigarettes"]}, 放大镜{game_data["eneny_items"]["glass"]}, 饮料{game_data["eneny_items"]["drink"]}
        """
        game_data, msg = await cls.rest_one_choice(game_data)
        if msg:
            out_data["msg"] += "\n道具“手铐”已使用,跳过对手回合"

        return out_data

    @classmethod
    async def rest_one_choice(cls, game_data: GameData):
        game_data["one_choice"]["damage"] = 1
        outmsg = False
        if (game_data["one_choice"]["skip"] == 1 and game_data["round_self"]) or (
            game_data["one_choice"]["skip"] == 2 and not game_data["round_self"]
        ):
            game_data["round_self"] = not game_data["round_self"]
            outmsg = True

        return game_data, outmsg

    @classmethod
    async def check_weapon(cls, game_data: GameData, session_uid: str):
        if game_data["weapon_all"] <= 0:
            new_nub = random.randint(2, 8)
            game_data["weapon_all"] = new_nub
            game_data["weapon_if"] = [
                random.choice([True, False]) for _ in range(new_nub)
            ]
            msg = f"\n子弹打完,已重置子弹\n当前子弹数: {new_nub}\n实弹数: {sum(game_data['weapon_if'])}\n请重新开枪"
            if_reload = True
        else:
            msg = f"当前子弹数: {game_data['weapon_all']}\n实弹数: {sum(game_data['weapon_if'])}"
            if_reload = False
        await LocalData.save_data(session_uid, game_data)
        return if_reload, msg


class LocalData:
    """本地数据"""

    @classmethod
    async def new_data(cls, game_id: str, session: Session):
        weapon_size = random.randint(2, 8)
        game_data = {
            "is_start": False,
            "player_id": game_id,
            "player_id2": "",
            "player_name": (session.user.nick or session.user.name),
            "player_name2": "",
            "round_num": 1,
            "round_self": True,
            "lives": 3,
            "enemy_lives": 3,
            "weapon_all": weapon_size,
            "weapon_if": [random.choice([True, False]) for _ in range(weapon_size)],
            "items": {
                "knife": 0,
                "handcuffs": 0,
                "cigarettes": 0,
                "glass": 0,
                "drink": 0,
            },
            "eneny_items": {
                "knife": 0,
                "handcuffs": 0,
                "cigarettes": 0,
                "glass": 0,
                "drink": 0,
            },
            "one_choice": {
                "damage": 1,
                "skip": 0,
            },
        }
        return cast(GameData, game_data)

    @classmethod
    async def read_data(cls, session_uid: str):
        with (Path(config.br_path) / "player" / f"{session_uid}.json").open(
            "r",
            encoding="utf-8",
        ) as f:
            return cast(GameData, json.load(f))

    @classmethod
    async def save_data(cls, session_uid: str, game_data: GameData):
        with (Path(config.br_path) / "player" / f"{session_uid}.json").open(
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(game_data, f, ensure_ascii=False, indent=4)

    @classmethod
    async def delete_data(cls, session_uid: str):
        (Path(config.br_path) / "player" / f"{session_uid}.json").unlink()

    @classmethod
    async def switch_life(
        cls,
        game_data: GameData,
        session_uid: str,
        player_lives: int,
    ):
        game_data["lives"] = player_lives
        game_data["enemy_lives"] = player_lives
        await LocalData.save_data(session_uid, game_data)
