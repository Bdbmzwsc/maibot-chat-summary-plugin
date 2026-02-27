import re
import time
from typing import List, Optional, Dict, Any, Tuple

from src.common.data_models.database_data_model import DatabaseMessages
from src.common.logger import get_logger
from src.common.message_repository import find_messages
from src.plugin_system import (
    chat_api,
    person_api
)

logger = get_logger("summary_plugin")

def get_messages_by_user_in_stream(user_ids: List[str], start_time: Optional[float], end_time: Optional[float],
                                   stream_id: Optional[str],
                                   limit: int = 1000) -> List[DatabaseMessages]:
    """获取指定用户在指定聊天流中的消息记录"""
    filter_query: Dict[str, Any] = {}
    time_range = {}
    if start_time:
        time_range["$gt"] = start_time
    if end_time:
        time_range["$lt"] = end_time
    if time_range:
        filter_query["time"] = time_range
    if user_ids:
        filter_query['user_id'] = {"$in": user_ids}
    if stream_id:
        filter_query["chat_id"] = stream_id
    sort_order = [("time", 1)] if limit == 0 else None
    messages = find_messages(
        message_filter=filter_query,
        sort=sort_order,
        limit=limit,
        limit_mode="latest",
        filter_command=True
    )
    return messages


async def prepare_summary_messages(
        messages: List[DatabaseMessages],
        limit: int = 500,
        person_name_dict: Optional[Dict[str, str]] = None,
        max_message_length: int = 0) -> Tuple[List[str], int, int]:
    """
    清洗并格式化消息，生成用户画像的输入

    :param messages: 消息列表
    :param limit: 最大返回消息条数
    :param primary_user_id: 目标用户ID
    :param person_name_dict: 用户ID到昵称的映射
    :param max_message_length: 单条消息最大字数限制，0表示不限制
    :return: 格式化后的消息字符串列表（按时间升序）、列表中属于 primary_user_id 的消息数（如果未提供 primary_user_id 则为 0）、列表中属于其他用户的消息数
    """
    if person_name_dict is None:
        person_name_dict = {}
    lines = []
    user_count = 0
    pattern1 = re.compile("={10}\s*转发消息开始\s*={10}\s*([\s\S]*?)\s*={10}\s*转发消息结束\s*={10}", re.DOTALL)
    pattern2 = re.compile(r"\[回复<.+]，说：", re.DOTALL)
    pattern3 = re.compile(r"@<.+>")
    pattern4 = re.compile(r"\[表情包.+]", re.DOTALL)
    pattern5 = re.compile(r"\[picid.+]", re.DOTALL)
    pattern6 = re.compile(r"\[command.+]", re.DOTALL)
    patterns = [
        ("转发消息开始", pattern1),
        ("回复", pattern2),
        ("@", pattern3),
        ("[表情包", pattern4),
        ("[picid", pattern5),
        ("[command", pattern6),
    ]
    message: DatabaseMessages
    for message in reversed(messages):
        if len(lines) >= limit:
            break
        text = message.processed_plain_text.strip()
        if not text or "[文件:" in text:
            continue
        for key, pat in patterns:
            if key in text:
                text = pat.sub("", text)
        text = text.strip()
        if not text: continue
        if 0 < max_message_length < len(text):
            text = text[:max_message_length] + "......[由于消息过长，后续消息已被截断]"
        time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(message.time))
        person_name = person_name_dict.get(message.user_info.user_id)
        if not person_name:
            user_id = message.user_info.user_id
            person_id = person_api.get_person_id('qq', user_id)
            person_name = await person_api.get_person_value(person_id, "person_name", message.user_info.user_nickname)
            person_name_dict[user_id] = person_name
        text = f"[{time_str}] {person_name}: {text}"
        lines.append(text)
        user_count += 1
    lines.reverse()
    return lines, user_count


def resolve_stream_id(raw_chat_id: str) -> Optional[str]:
    """
    根据提供的原始聊天ID，解析并返回对应的聊天流ID
    """
    chat_id = raw_chat_id.strip()
    if not chat_id:
        return None
    chat_stream = chat_api.get_stream_by_group_id(chat_id)
    if not chat_stream:
        chat_stream = chat_api.get_stream_by_user_id(chat_id)
    return chat_stream.stream_id if chat_stream else None


def filter_messages_with_context(messages: List[DatabaseMessages], limit: int = 1000) -> List[
    DatabaseMessages]:
    if not messages:
        return []
    return sorted(messages, key=lambda x: x.time)[-limit:]