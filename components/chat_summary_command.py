import time
from typing import List, Tuple, Optional


from src.common.logger import get_logger
from src.config.api_ada_configs import TaskConfig
from src.config.config import global_config
from src.plugin_system import (
    BaseCommand,
    llm_api,
)
from ..utils import get_messages_by_user_in_stream, prepare_summary_messages, filter_messages_with_context, \
    resolve_stream_id

logger = get_logger("chat_summary_plugin")


class ChatSummaryCommand(BaseCommand):
    """
    总结Command - 响应/总结命令

    整理消息记录，调用LLM生成总结
    """

    command_name = "总结"
    command_description = "根据用户的聊天记录生成总结"
    # === 命令设置（必须填写）===
    command_pattern = r"^/总结$"

    #command_pattern = r"^/总结(\s*(?P<name>\S+))?(\s+(?P<chat_id>\S+))?"


    permission_mode: str = "blacklist"
    user_id_list: List[str] = []
    admin_id_list: List[str] = []

    async def execute(self) -> Tuple[bool, Optional[str], int]:

        user_id = self.message.message_info.user_info.user_id
        is_in_list = user_id in ChatSummaryCommand.user_id_list
        if ChatSummaryCommand.permission_mode == "blacklist" and is_in_list:
            return True, f"用户 {user_id} 没有使用该命令的权限", 1
        elif ChatSummaryCommand.permission_mode == "whitelist" and not is_in_list:
            return True, f"用户 {user_id} 没有使用该命令的权限", 1
        is_admin = user_id in ChatSummaryCommand.admin_id_list
        prompt_template = self.get_config("chat_summary_plugin.prompt_template", None)
        llm_list = self.get_config("llm_config.llm_list", [])

        if llm_list:
            model_config = TaskConfig()
            model_config.model_list = llm_list
            model_config.max_tokens = self.get_config("llm_config.max_tokens", 20000)
            model_config.temperature = self.get_config("llm_config.temperature", 0.7)
            model_config.slow_threshold = self.get_config("llm_config.slow_threshold", 30)
            model_config.selection_strategy = self.get_config("llm_config.selection_strategy", "balance")
        else:
            llm_group = self.get_config("llm_config.llm_group", "utils")
            models = llm_api.get_available_models()
            model_config = models.get(llm_group)
            if not model_config:
                logger.error(f"未找到可用的 {llm_group} 模型配置")
                return False, f"未找到可用的 {llm_group} 模型配置", 1
        if not prompt_template:
            logger.error("总结提示词为空")
            return False, "总结提示词为空", 1
        stream_id = await self.get_chat_id()
        logger.debug(f"聊天流ID: {stream_id}")

        start_time = time.time() - 24 * 3600 * 30
        end_time = time.time()
        if not stream_id and not is_admin:
            # 如果没有指定聊天流ID，则将会搜索所有聊天流中该用户的消息 该功能仅限管理员使用
            await self.send_text("你没有使用该参数的权限")
            return True, f"", 1
        if stream_id != self.message.chat_stream.stream_id and not is_admin:
            await self.send_text("你没有使用该参数的权限")
            return True, f"", 1
        retrieval_message_count = self.get_config("chat_summary_plugin.retrieval_message_count",
                                                  50000)
        context_length = self.get_config("chat_summary_plugin.context_length", 10)
        context_length_after = self.get_config("chat_summary_plugin.context_length_after", 3)
        max_message_count = self.get_config("chat_summary_plugin.max_message_count", 500)
        max_message_length = self.get_config("chat_summary_plugin.max_message_length", 200)

        # 获取用户在指定聊天流中的消息记录
        messages = get_messages_by_user_in_stream([], start_time, end_time, stream_id,
                                                  retrieval_message_count)
        retrieval_message_count = len(messages)
        # 过滤出总结对象的消息和上下文消息
        messages = filter_messages_with_context(messages, max_message_count * 2)
        # 删除对总结生成无用的信息并整理消息内容为字符串列表
        lines, user_count = await prepare_summary_messages(
            messages,
            max_message_count,
            person_name_dict={
                global_config.bot.qq_account: global_config.bot.nickname
            },
            max_message_length=max_message_length
        )
        if not messages:
            await self.send_text(f"未找到消息记录，无法生成总结。")
            return True, f"", 1
        if not lines:
            await self.send_text(f"未找到有效的消息内容，无法生成总结。")
            return True, f"", 1

        await self.send_text(
            f"使用了 {len(lines)} 条消息。正在生成总结，请稍候...")

        prompt = prompt_template.format(
            messages="\n".join(lines),
            message_count=len(messages)
        )
        success, response, _, _ = await llm_api.generate_with_model(prompt, model_config=model_config)
        if not success:
            logger.error(f"模型响应失败: {response}")
            return False, f"", 1

        message_body: Tuple[str, str] = ("text", response)
        message: Tuple[str, str, List[Tuple[str, str]]] = (
            global_config.bot.qq_account, global_config.bot.nickname, [message_body]
        )
        await self.send_forward([message])

        return True, f"", 1

    async def get_chat_id(self) -> str:
        """
        获取聊天流ID
        returns: str: 聊天流ID
        """
        chat_id = self.matched_groups.get("chat_id", "")
        if isinstance(chat_id, str): chat_id = chat_id.strip()
        if not chat_id:
            logger.debug(f"未指定聊天流ID，使用当前聊天流ID: {self.message.chat_stream.stream_id}")
            chat_id = self.message.chat_stream.stream_id
        elif chat_id == "全部":
            logger.debug("命令参数指定搜索所有聊天流")
            chat_id = ""  # 返回空字符串表示搜索所有聊天流
        else:
            logger.debug(f"命令参数指定聊天流ID: {chat_id}")
            stream_id = resolve_stream_id(chat_id)
            if not stream_id:
                logger.warn(f"无法根据命令参数指定的聊天ID找到对应的聊天流: “{chat_id}” 使用当前聊天流ID")
                chat_id = self.message.chat_stream.stream_id
            else:
                chat_id = stream_id
        return chat_id